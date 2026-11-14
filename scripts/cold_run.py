"""The cold run's reader: what a filled `docs/copilot-cold-run.toml` says, in a few lines.

`report(text)` is pure: it takes the record's text and returns the report, reading no file,
calling nothing outside and refusing nothing. Called by nothing in SE; only a person runs it:

    uv run python scripts/cold_run.py report docs/copilot-cold-run.toml

The report names the steps that differ, the steps that needed something beyond their written
step, the total minutes, the dispatch result, and whether a tool list, a manifest and the doctor's
report were recorded. It never says a run passed: a record of steps never run reports
`nothing run`. A malformed record is named with its line, and the command still exits 0; only a
file it cannot read exits 2.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass

AS_EXPECTED = "as expected"
DIFFERS = "differs"
NOT_RUN = "not run"
RESULTS = (AS_EXPECTED, DIFFERS, NOT_RUN)
DISPATCH = ("yes", "no", NOT_RUN)
NOTHING = "nothing"

_TOML_LINE = re.compile(r"\(at line (\d+), column \d+\)")
_TABLE = re.compile(r"^\s*\[\[?\s*([A-Za-z_]+)\s*\]\]?\s*(?:#.*)?$")


@dataclass(frozen=True)
class Step:
    number: int
    name: str
    result: str
    minutes: int
    beyond: str

    @property
    def label(self) -> str:
        return f"step {self.number} ({self.name})"


class _Lines:
    """Where each table and key of the record starts, so a finding names its line."""

    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.tables: list[tuple[str, int]] = []  # (table name, 1-based line), in order
        for index, line in enumerate(self.lines, 1):
            match = _TABLE.match(line)
            if match:
                self.tables.append((match.group(1), index))

    def table(self, name: str, nth: int = 0) -> int | None:
        found = [line for table, line in self.tables if table == name]
        return found[nth] if nth < len(found) else None

    def key(self, table: str, key: str, nth: int = 0) -> int | None:
        start = self.table(table, nth)
        if start is None:
            return None
        ends = [line for _, line in self.tables if line > start]
        end = min(ends) if ends else len(self.lines) + 1
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for index in range(start + 1, end):
            if pattern.match(self.lines[index - 1]):
                return index
        return start


def _where(line: int | None) -> str:
    return f"line {line}" if line else "the record"


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _steps(data: dict, lines: _Lines, malformed: list[str]) -> list[Step]:
    raw = data.get("step", [])
    if not isinstance(raw, list) or not raw:
        malformed.append(f"{_where(lines.table('step'))}: no [[step]] entries")
        return []
    steps = []
    for nth, entry in enumerate(raw):
        here = lines.table("step", nth)

        def bad(key: str, why: str) -> None:
            malformed.append(f"{_where(lines.key('step', key, nth) or here)}: {why}")

        number, name = entry.get("number"), entry.get("name")
        result, minutes, beyond = entry.get("result"), entry.get("minutes"), entry.get("beyond")
        if not isinstance(number, int) or isinstance(number, bool):
            bad("number", f"step {nth + 1}: number must be a whole number")
            number = nth + 1
        if not isinstance(name, str) or not name.strip():
            bad("name", f"step {number}: name is missing")
            name = "?"
        if result not in RESULTS:
            bad("result", f"step {number}: result {result!r} is not one of "
                          + ", ".join(f'"{r}"' for r in RESULTS))
            result = NOT_RUN
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 0:
            bad("minutes", f"step {number}: minutes {minutes!r} is not a whole number of minutes")
            minutes = 0
        if not isinstance(beyond, str):
            bad("beyond", f"step {number}: beyond must be text, \"{NOTHING}\" where nothing")
            beyond = NOTHING
        steps.append(Step(number, name.strip(), result, minutes, beyond.strip()))
    return steps


def _table(data: dict, name: str, lines: _Lines, malformed: list[str]) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        malformed.append(f"{_where(lines.table(name))}: {name} must be a table, [{name}]")
        return {}
    return value


def report(text: str) -> str:
    """The report of one record's text, ending in a newline."""
    malformed: list[str] = []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        match = _TOML_LINE.search(str(error))
        reason = _TOML_LINE.sub("", str(error)).strip()
        where = f"line {match.group(1)}" if match else "the record"
        return (f"cold run: the record is malformed\n"
                f"malformed: {where}: {reason}\n"
                f"verdict: nothing read\n")
    lines = _Lines(text)
    run = _table(data, "run", lines, malformed)
    asked = _table(data, "asked", lines, malformed)
    proof = _table(data, "proof", lines, malformed)
    steps = _steps(data, lines, malformed)

    dispatch = _text(asked.get("dispatch"))
    if dispatch and dispatch not in DISPATCH:
        malformed.append(f"{_where(lines.key('asked', 'dispatch'))}: dispatch {dispatch!r} is "
                         "not one of " + ", ".join(f'"{d}"' for d in DISPATCH))
        dispatch = ""

    ran = [step for step in steps if step.result != NOT_RUN]
    differ = [step for step in steps if step.result == DIFFERS]
    beyond = [step for step in steps if step.beyond and step.beyond.lower() != NOTHING]
    who = ", ".join(_text(run.get(key)) or f"{key} not recorded"
                    for key in ("host", "platform", "date"))
    manifest = _text(asked.get("manifest"))
    doctor = _text(proof.get("doctor"))

    out = [f"cold run: {who}",
           f"steps: {len(ran)} of {len(steps)} run, {len(ran) - len(differ)} as expected, "
           f"{len(differ)} differ, {len(steps) - len(ran)} not run"]
    out.append("differs:" + ("" if differ else " none"))
    out += [f"  {step.label}" for step in differ]
    out.append("beyond the written step:" + ("" if beyond else " none"))
    out += [f"  {step.label}: {step.beyond}" for step in beyond]
    out.append(f"minutes: {sum(step.minutes for step in steps)}")
    out.append(f"dispatch: {dispatch or 'not recorded'}")
    out.append(f"tools: {'recorded' if _text(asked.get('tools')) else 'not recorded'}")
    out.append(f"manifest: {manifest if manifest else 'not recorded'}")
    out.append(f"doctor's report: {doctor if doctor else 'not recorded'}")
    out += [f"malformed: {finding}" for finding in malformed]
    if not ran:
        verdict = "nothing run"
    else:
        verdict = f"{len(ran)} of {len(steps)} steps run, {len(differ)} differ"
    out.append(f"verdict: {verdict}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("report", help="report what a filled cold-run record says")
    read.add_argument("record", help="the record, e.g. docs/copilot-cold-run.toml")
    args = parser.parse_args(argv)
    try:
        with open(args.record, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        print(f"cold run: cannot read {args.record}: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(report(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
