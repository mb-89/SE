#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Session cost: what sessions spend in tokens, read from their transcripts and weighed per model.
It writes nothing, draws no conclusions and is called by nothing.

    uv run python scripts/session_cost.py <transcripts or directories> [--json] [--prices FILE]

It finds the files the way the transcript reader does (`transcript_signals.transcripts()`, loaded
beside this script, never copied) and reads Claude Code's JSONL only. The core is pure:

- `calls(lines, label, subagent)`: transcript lines in, one `Call` per call out. A call is one
  request to the model: an assistant record's `message.id`, else its `requestId`, else the record
  alone. Rows of one id count once, the largest value per usage field; a `<synthetic>` record is no
  call, and only the top-level `usage` fields count (`usage.iterations` is not added on top).
- `sessions(calls, prices)`: calls in, one session each by `sessionId` out. A sub-agent's file under
  `<session>/subagents/` carries its parent's id, so its calls join the parent as sub-agent calls.
- `render_text` and `render_json` print the result.

Units: one unit is one standard uncached input token of the same model, so the kinds of tokens add
up without a dollar price. A call's units are each kind's tokens times its ratio in `PRICES`, a
dated table kept as data (`--prices FILE` replaces it with TOML `[[price]]` rows of the same keys).
A row's `above_tokens` with its `above` ratios price a call whose context is over it. Units are
totalled per model only; a call without a row counts in tokens and its model's units read `unknown`.

The output holds counts, ratios, model ids, session ids, file labels and tool names only: never
message text, tool input, a prompt or a path outside the directory read.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import se_script


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded once under its own name."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


KINDS = ("input", "cache_read", "write_5m", "write_1h", "output")  # the kinds of tokens, in order
KIND_NAMES = {"input": "input", "cache_read": "cache read", "write_5m": "write 5m",
              "write_1h": "write 1h", "output": "output"}
EDIT_TOOLS = ("Edit", "MultiEdit", "NotebookEdit")  # beside the reader's WRITE_TOOLS
SYNTHETIC = "<synthetic>"
_DATED = re.compile(r"-\d{8}$")  # a model id's date suffix, as in `<model>-20250514`

PAGE = "provider price page (platform.claude.com/docs/en/about-claude/pricing)"
PAGE_DATE = "2026-11-16"


def _row(model: str, speed: str, ratios: tuple[float, ...], above: tuple | None = None) -> dict:
    row = {"model": model, "speed": speed, **dict(zip(KINDS, ratios)), "source": PAGE, "date": PAGE_DATE}
    if above:
        row["above_tokens"] = above[0]
        row["above"] = dict(zip(KINDS, above[1]))
    return row


def _standard(read: float) -> tuple[float, ...]:
    """The standard ratios with the model's cache hit multiplier."""
    return (1, read, 1.25, 2, 5)


def _fast(input_: float, output: float, read: float) -> tuple[float, ...]:
    """Fast speed: its input and output ratios, the caching multipliers on top of its input."""
    return (input_, input_ * read, input_ * 1.25, input_ * 2, output)


# Ratios to the same model's standard uncached input price: input, cache read, 5-minute write,
# 1-hour write, output. Every model and speed the page lists. Mythos ids follow the others' naming.
PRICES: list[dict] = [
    _row("claude-fable-5-2", "standard", _standard(0.025)),
    _row("claude-fable-5-2", "fast", _fast(2, 10, 0.025)),
    _row("claude-mythos-5-2", "standard", _standard(0.025)),
    _row("claude-mythos-5-2", "fast", _fast(2, 10, 0.025)),
    _row("claude-opus-5-5", "standard", _standard(0.05)),
    _row("claude-opus-5-5", "fast", _fast(2, 10, 0.05)),
    _row("claude-sonnet-5-5", "standard", _standard(0.05)),
    _row("claude-haiku-5-5", "standard", _standard(0.1), (100_000, (5, 0.5, 6.25, 10, 25))),
    _row("claude-fable-5-1", "standard", _standard(0.025)),
    _row("claude-mythos-5-1", "standard", _standard(0.025)),
    _row("claude-fable-5", "standard", _standard(0.1)),
    _row("claude-mythos-5", "standard", _standard(0.1)),
    _row("claude-opus-5", "standard", _standard(0.1)),
    _row("claude-opus-5", "fast", _fast(2, 10, 0.1)),
    _row("claude-opus-4-8", "standard", _standard(0.1)),
    _row("claude-opus-4-8", "fast", _fast(2, 10, 0.1)),
    _row("claude-opus-4-7", "standard", _standard(0.1)),
    _row("claude-opus-4-6", "standard", _standard(0.1)),
    _row("claude-opus-4-5", "standard", _standard(0.1)),
    _row("claude-opus-4-1", "standard", _standard(0.1)),
    _row("claude-opus-4", "standard", _standard(0.1)),
    _row("claude-sonnet-5", "standard", _standard(0.1)),
    _row("claude-sonnet-4-6", "standard", _standard(0.1)),
    _row("claude-sonnet-4-5", "standard", _standard(0.1)),
    _row("claude-sonnet-4", "standard", _standard(0.1)),
    _row("claude-haiku-4-5", "standard", _standard(0.1)),
]


# The pure core: lines in, calls out.


@dataclass
class Call:
    """One request to the model, its usage the largest value per field over its rows."""
    key: str
    session: str
    file: str
    subagent: bool
    model: str
    speed: str = "standard"
    tokens: dict = field(default_factory=lambda: dict.fromkeys(KINDS, 0))
    split: bool = True  # the cache write came split by TTL
    tools: list = field(default_factory=list)

    @property
    def context(self) -> int:
        return sum(self.tokens[kind] for kind in ("input", "cache_read", "write_5m", "write_1h"))

    def merge(self, other: "Call") -> None:
        for kind in KINDS:
            self.tokens[kind] = max(self.tokens[kind], other.tokens[kind])
        self.split = self.split and other.split
        self.subagent = self.subagent or other.subagent
        self.tools.extend(tool for tool in other.tools if tool not in self.tools)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _call(record: dict, label: str, subagent: bool, session: str, line: int) -> Call | None:
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return None
    usage = message.get("usage")
    model = message.get("model")
    if not isinstance(usage, dict) or not isinstance(model, str) or model == SYNTHETIC:
        return None
    key = message.get("id") or record.get("requestId") or f"{label}:{line}"
    tokens = {"input": _count(usage.get("input_tokens")),
              "cache_read": _count(usage.get("cache_read_input_tokens")),
              "output": _count(usage.get("output_tokens"))}
    creation = usage.get("cache_creation")
    split = isinstance(creation, dict) and ("ephemeral_5m_input_tokens" in creation
                                            or "ephemeral_1h_input_tokens" in creation)
    if split:
        tokens["write_5m"] = _count(creation.get("ephemeral_5m_input_tokens"))
        tokens["write_1h"] = _count(creation.get("ephemeral_1h_input_tokens"))
    else:
        tokens["write_5m"] = _count(usage.get("cache_creation_input_tokens"))
        tokens["write_1h"] = 0
    speed = usage.get("speed")
    content = message.get("content")
    tools = [block["name"] for block in content if isinstance(block, dict)
             and block.get("type") == "tool_use" and isinstance(block.get("name"), str)] \
        if isinstance(content, list) else []
    return Call(str(key), session, label, subagent or record.get("isSidechain") is True, model,
                speed if isinstance(speed, str) and speed else "standard", tokens, split, tools)


def calls(lines: Iterable[str], label: str, subagent: bool = False,
          fallback_session: str | None = None) -> list[Call]:
    """One row per call, in the order of its first row; rows of one id merged."""
    found: dict[str, Call] = {}
    for line, raw in enumerate(lines, 1):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        session = record.get("sessionId")
        session = session if isinstance(session, str) and session else (fallback_session or label)
        call = _call(record, label, subagent, session, line)
        if call is None:
            continue
        if call.key in found:
            found[call.key].merge(call)
        else:
            found[call.key] = call
    return list(found.values())


# Calls in, sessions out.


def price_row(prices: list[dict], model: str, speed: str) -> dict | None:
    """The row of a model id, or of the id without its date suffix, at that speed."""
    for name in (model, _DATED.sub("", model)):
        for row in prices:
            if row["model"] == name and row["speed"] == speed:
                return row
    return None


def units(call: Call, prices: list[dict]) -> float | None:
    """The call's weight in standard uncached input tokens of its model; None without a row."""
    row = price_row(prices, call.model, call.speed)
    if row is None:
        return None
    ratios = row.get("above") if row.get("above_tokens") is not None \
        and call.context > row["above_tokens"] else row
    return sum(call.tokens[kind] * ratios[kind] for kind in KINDS)


def _add(total: dict, tokens: dict) -> None:
    for kind in KINDS:
        total[kind] += tokens[kind]


def _sum_units(weighed: list[tuple[Call, float | None]]) -> dict:
    """Per model, the units of these calls: None where any of them has no row."""
    result: dict[str, float | None] = {}
    for call, weight in weighed:
        known = result.get(call.model, 0.0)
        result[call.model] = None if known is None or weight is None else known + weight
    return result


def _first_edit(main: list[Call], write_tools: Iterable[str]) -> int | None:
    tools = set(write_tools) | set(EDIT_TOOLS)
    return next((index for index, call in enumerate(main) if tools & set(call.tools)), None)


def session(name: str, members: list[Call], prices: list[dict], write_tools: Iterable[str]) -> dict:
    weighed = [(call, units(call, prices)) for call in members]
    main = [pair for pair in weighed if not pair[0].subagent]
    sub = [pair for pair in weighed if pair[0].subagent]
    tokens = {part: dict.fromkeys(KINDS, 0) for part in ("all", "main", "subagent")}
    for call, _ in weighed:
        _add(tokens["all"], call.tokens)
        _add(tokens["subagent" if call.subagent else "main"], call.tokens)
    all_units, main_units, sub_units = _sum_units(weighed), _sum_units(main), _sum_units(sub)
    models: dict[str, int] = {}
    for call in members:
        models[call.model] = models.get(call.model, 0) + 1
    edit = _first_edit([call for call, _ in main], write_tools)
    before: dict | str = "no edit"
    if edit is not None:
        spent = _sum_units(main[:edit])
        before = {}
        for model, whole in main_units.items():
            part = spent.get(model, 0.0)
            before[model] = None if whole is None or part is None else (part / whole if whole else 0.0)
    contexts = [call.context for call, _ in main]
    return {
        "session": name,
        "files": sorted({call.file for call in members}),
        "calls": len(members), "main_calls": len(main), "subagent_calls": len(sub),
        "models": dict(sorted(models.items())),
        "tokens": tokens,
        "units": {model: {"all": all_units[model], "main": main_units.get(model, 0.0),
                          "subagent": sub_units.get(model, 0.0)} for model in sorted(all_units)},
        "context": {"first": contexts[0] if contexts else None,
                    "first_edit": contexts[edit] if edit is not None else None,
                    "peak": max(contexts) if contexts else None},
        "before_first_edit": before,
        "write_ttl_split": all(call.split for call in members),
    }


def _rank(entry: dict) -> tuple:
    """Highest units of the model that answered most calls first; unknown last; ties by id."""
    model = min(entry["models"], key=lambda name: (-entry["models"][name], name))
    weight = entry["units"][model]["all"]
    return (weight is None, -(weight or 0.0), entry["session"])


def _merged(found: list[Call]) -> dict[str, Call]:
    """One call per id over every file read (a resumed session repeats earlier rows)."""
    merged: dict[str, Call] = {}
    for call in found:
        if call.key in merged:
            merged[call.key].merge(call)
        else:
            merged[call.key] = call
    return merged


def sessions(found: list[Call], prices: list[dict], write_tools: Iterable[str] = ()) -> list[dict]:
    """Calls grouped by session, one id across files counted once, sorted by `_rank`."""
    merged = _merged(found)
    groups: dict[str, list[Call]] = {}
    for call in merged.values():
        groups.setdefault(call.session, []).append(call)
    return sorted((session(name, members, prices, write_tools) for name, members in groups.items()),
                  key=_rank)


def tally(found: list[Call], no_usage: list[str], prices: list[dict],
          write_tools: Iterable[str] = ()) -> dict:
    """Everything the renderings print: sessions, files without usage, totals per model."""
    entries = sessions(found, prices, write_tools)
    per_model: dict[str, dict] = {}
    merged = _merged(found)
    for call in merged.values():
        part = per_model.setdefault(call.model, {"calls": 0, "tokens": dict.fromkeys(KINDS, 0), "units": 0.0})
        part["calls"] += 1
        _add(part["tokens"], call.tokens)
        weight = units(call, prices)
        part["units"] = None if part["units"] is None or weight is None else part["units"] + weight
    return {"sessions": entries, "no_usage": sorted(no_usage), "total": dict(sorted(per_model.items()))}


# Renderings.


def render_json(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True)


def _units(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def _tokens(tokens: dict) -> str:
    return "  ".join(f"{KIND_NAMES[kind]} {tokens[kind]}" for kind in KINDS)


def _context(value: int | None) -> str:
    return "-" if value is None else str(value)


def render_text(result: dict) -> str:
    lines: list[str] = []
    for entry in result["sessions"]:
        lines.append(f"session {entry['session']}: {entry['calls']} calls "
                     f"({entry['main_calls']} main, {entry['subagent_calls']} sub-agent)")
        lines.append(f"  files: {', '.join(entry['files'])}")
        lines.append("  models: " + ", ".join(f"{model} {count}" for model, count in entry["models"].items()))
        for part, name in (("all", "tokens"), ("main", "main"), ("subagent", "sub-agent")):
            lines.append(f"  {name:<9} {_tokens(entry['tokens'][part])}")
        for model, value in entry["units"].items():
            lines.append(f"  units {model} {_units(value['all'])} "
                         f"(main {_units(value['main'])}, sub-agent {_units(value['subagent'])})")
        context = entry["context"]
        lines.append(f"  context first {_context(context['first'])}, first edit "
                     f"{_context(context['first_edit'])}, peak {_context(context['peak'])}")
        before = entry["before_first_edit"]
        if isinstance(before, str):
            lines.append(f"  before first edit: {before}")
        else:
            shares = ", ".join(f"{model} {'unknown' if share is None else f'{share:.1%}'}"
                               for model, share in before.items())
            lines.append(f"  before first edit: {shares or '-'}")
        if not entry["write_ttl_split"]:
            lines.append("  write TTL not split")
    for label in result["no_usage"]:
        lines.append(f"no usage read: {label}")
    lines.append("total per model:")
    for model, total in result["total"].items():
        lines.append(f"  {model}: {total['calls']} calls  {_tokens(total['tokens'])}  "
                     f"units {_units(total['units'])}")
    return "\n".join(lines)


# The wiring: files in, the rendering out.


def load_prices(path: Path) -> list[dict]:
    """The `[[price]]` rows of a TOML file; ValueError where one lacks a key."""
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("price")
    if not isinstance(rows, list) or not rows:
        raise ValueError("no [[price]] rows")
    for row in rows:
        missing = [key for key in ("model", "speed", *KINDS, "source", "date") if key not in row]
        if "above_tokens" in row:
            missing += [f"above.{kind}" for kind in KINDS if kind not in row.get("above", {})]
        if missing:
            raise ValueError(f"a row lacks {', '.join(missing)}")
    return rows


def _subagent_session(path: Path) -> str | None:
    """A file under `<session>/subagents/` belongs to that session."""
    return path.parent.parent.name if path.parent.name == "subagents" else None


def make_parser() -> argparse.ArgumentParser:
    parser = se_script.parser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", help="transcript files or directories of them")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--prices", help="a TOML file of [[price]] rows that replaces the table")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    prices = PRICES
    if args.prices:
        try:
            prices = load_prices(Path(args.prices))
        except (OSError, ValueError) as error:  # tomllib's errors are ValueErrors
            print(f"session_cost: cannot read --prices {args.prices}: {type(error).__name__}", file=sys.stderr)
            return 2
    for given in args.paths:
        if not Path(given).exists():
            print(f"session_cost: cannot read {given}", file=sys.stderr)
            return 2
    signals = sibling("transcript_signals")
    found: list[Call] = []
    no_usage: list[str] = []
    for path, label in signals.transcripts([Path(given) for given in args.paths]):
        subagent_of = _subagent_session(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            no_usage.append(label)
            continue
        read = calls(text.splitlines(), label, subagent_of is not None, subagent_of)
        if read:
            found.extend(read)
        else:
            no_usage.append(label)
    result = tally(found, no_usage, prices, signals.WRITE_TOOLS)
    print(render_json(result) if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
