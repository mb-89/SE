"""What each command costs: one JSON line per run of a `work_tickets.py` or `se_start.py`
subcommand, and the report of its top spenders and overruns (README "Metrics").

A run's line holds its command, start, wall seconds, its GitHub calls through the door (count,
refusals, wait seconds) and its exit code, plus what the command notes itself (`integrate`: the
suite's wall time and the issue it landed; an interactive command: its budget, declared in
feedback.py). The line goes to `~/.se/metrics.jsonl` (or `$SE_METRICS`); a failure to write it
never fails the command.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PATH_DEFAULT = Path("~/.se/metrics.jsonl")
PATH_ENV = "SE_METRICS"
TOP = 10  # spenders listed per ranking

clock: Callable[[], float] = time.monotonic
now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731


def _sibling(name: str):
    """The script `<name>.py` beside this one, loaded once under its own name."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


feedback = _sibling("feedback")


def path() -> Path:
    """Where the lines go: `$SE_METRICS`, else `~/.se/metrics.jsonl`."""
    return Path(os.environ.get(PATH_ENV) or PATH_DEFAULT).expanduser()


@dataclass
class Run:
    command: str
    start: datetime
    started: float
    gh_calls: int = 0
    gh_refusals: int = 0
    gh_wait_seconds: float = 0.0
    noted: dict[str, object] = field(default_factory=dict)


_runs: list[Run] = []
_lock = threading.Lock()


def start(command: str) -> None:
    """Begin measuring a run of `command` (`<script>.py <subcommand>`)."""
    _runs.append(Run(command, now(), clock()))


def door_call(refused: bool = False) -> None:
    """Count one GitHub call through the door; `refused`: GitHub refused it for its rate limit
    or transiently."""
    if _runs:
        with _lock:
            _runs[-1].gh_calls += 1
            _runs[-1].gh_refusals += int(refused)


def door_wait(seconds: float) -> None:
    """Count seconds spent waiting on GitHub (a retry after a refusal, a poll)."""
    if _runs:
        with _lock:
            _runs[-1].gh_wait_seconds += seconds


def note(**fields: object) -> None:
    """Add fields to the current run's line."""
    if _runs:
        _runs[-1].noted.update(fields)


def _line(run: Run, exit_code: int) -> dict[str, object]:
    return {
        "command": run.command,
        "start": run.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wall_seconds": round(clock() - run.started, 3),
        "gh_calls": run.gh_calls,
        "gh_refusals": run.gh_refusals,
        "gh_wait_seconds": round(run.gh_wait_seconds, 3),
        "exit_code": exit_code,
        **run.noted,
    }


def snapshot(exit_code: int = 0) -> dict[str, object] | None:
    """The current run's line as it stands now, with `exit_code`, neither ended nor written: what
    a landing pull request records of the integration that opens it; None where no run started."""
    return _line(_runs[-1], exit_code) if _runs else None


def finish(exit_code: int) -> dict[str, object] | None:
    """End the current run and append its line; the line, or None where none was started. A write
    that fails is ignored: measuring never fails the command."""
    if not _runs:
        return None
    line = _line(_runs.pop(), exit_code)
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(line, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - a lost line never fails the command it measures
        pass
    return line


def recorded(command: str, body: Callable[[], int]) -> tuple[int, dict[str, object] | None]:
    """Run `body` measured as `command`, watched for its first line and with its budget noted
    (both declared in feedback.py): its exit code and its line. An exception that escapes `body`
    is recorded with exit code 1 (or SystemExit's code) and raised."""
    start(command)
    if (seconds := feedback.budget(command)) is not None:
        note(budget_seconds=seconds)
    code = 1
    try:
        with feedback.watched(command):
            code = body()
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
        finish(code)
        raise
    except BaseException:
        finish(code)
        raise
    return code, finish(code)


# A line in a text: the integration's line that `integrate` prints last and that ends the landing
# pull request's description, read back by `retro.py collect` (README "Metrics").

TEXT_PREFIX = "Metrics: "


def text(line: dict[str, object]) -> str:
    """`line` as one line of text, `Metrics: {...}`."""
    return TEXT_PREFIX + json.dumps(line, sort_keys=True)


def of_text(body: str) -> dict | None:
    """The run's line of the last `Metrics: {...}` line in `body`; None where it holds none that
    reads as a run's line."""
    for candidate in reversed(body.splitlines()):
        if candidate.startswith(TEXT_PREFIX):
            try:
                line = json.loads(candidate[len(TEXT_PREFIX):])
            except json.JSONDecodeError:
                return None
            readable = isinstance(line, dict) and isinstance(line.get("command"), str)
            return line if readable and "start" in line else None
    return None


def merged(*sources: Iterable[dict]) -> list[dict]:
    """The lines of `sources`, each run once: a run is its command and its start, and the first
    source that holds it wins (a local file's finished line over a landing's snapshot of it)."""
    seen: dict[tuple[str, str], dict] = {}
    for source in sources:
        for line in source:
            seen.setdefault((str(line["command"]), str(line["start"])), line)
    return sorted(seen.values(), key=lambda line: (str(line["start"]), str(line["command"])))


# The report


def read(source: Path) -> tuple[list[dict], int]:
    """The lines of `source` and how many could not be read as a run's line."""
    lines, skipped = [], 0
    if not source.exists():
        return lines, skipped
    for text in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(line, dict) and isinstance(line.get("command"), str) and "start" in line:
            lines.append(line)
        else:
            skipped += 1
    return lines, skipped


def _number(line: dict, key: str) -> float:
    value = line.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def overruns(line: dict) -> list[str]:
    """What `line` spent over a budget it declares: its wall time over `budget_seconds`, its
    suite over `suite_limit_seconds` (se.toml `[tests]`)."""
    found = []
    for spent, budget, what in (("wall_seconds", "budget_seconds", "wall time"),
                                ("suite_seconds", "suite_limit_seconds", "suite")):
        if line.get(budget) is not None and _number(line, spent) > _number(line, budget):
            found.append(f"{what} {_number(line, spent):.1f} s over its budget "
                         f"{_number(line, budget):g} s")
    return found


def report(lines: Iterable[dict], since: str | None = None, source: Path | None = None,
           skipped: int = 0) -> str:
    """Top spenders by total wall time and by GitHub calls, and every overrun, of the lines that
    started on or after `since` (`YYYY-MM-DD`)."""
    chosen = [line for line in lines if since is None or str(line["start"])[:10] >= since]
    window = f" since {since}" if since else ""
    where = f" in {source}" if source else ""
    out = [f"Metrics: {len(chosen)} runs{window}{where}"
           + (f"; {skipped} unreadable lines skipped" if skipped else "")]
    totals: dict[str, dict[str, float]] = {}
    for line in chosen:
        total = totals.setdefault(line["command"], {"runs": 0, "wall": 0.0, "calls": 0.0,
                                                    "refusals": 0.0, "wait": 0.0})
        total["runs"] += 1
        total["wall"] += _number(line, "wall_seconds")
        total["calls"] += _number(line, "gh_calls")
        total["refusals"] += _number(line, "gh_refusals")
        total["wait"] += _number(line, "gh_wait_seconds")

    def row(command: str) -> str:
        total = totals[command]
        return (f"  {command}: {int(total['runs'])} runs, {total['wall']:.1f} s wall, "
                f"{int(total['calls'])} GitHub calls, {int(total['refusals'])} refused, "
                f"{total['wait']:.0f} s waiting")

    for title, key in (("Top spenders by wall time", "wall"), ("Top spenders by GitHub calls", "calls")):
        ranked = sorted(totals, key=lambda command: (-totals[command][key], command))[:TOP]
        out.append(f"{title}:")
        out.extend(row(command) for command in ranked if totals[command][key] > 0 or key == "wall")
    flagged = [(line, found) for line in chosen if (found := overruns(line))]
    out.append(f"Overruns: {len(flagged)}" if flagged else "Overruns: none")
    for line, found in flagged:
        issue = f" #{line['issue']}" if line.get("issue") else ""
        out.append(f"  {line['start']} {line['command']}{issue}: {'; '.join(found)}")
    return "\n".join(out)
