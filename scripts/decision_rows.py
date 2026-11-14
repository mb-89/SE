"""Decision rows: every row of the Decisions table in the field reports of the landings of a window.

`decision_rows.py list --since DATE [--until DATE]` lists, for each pull request merged into the
integration branch in the window, newest first, the rows of the `## Decisions` table of its field
report (decision, alternatives, rationale, confidence) with the landing's date, the pull request,
the work issue and its title, and the report's Result, so the owner can find and overrule what
workers decided on their own. A landing whose report has no Decisions section, or that has no field
report, is named as such, so a gap never reads as "no decisions". `--json` prints the same rows.

Two layers:

- the core (`parse` and `landings` and what they call) is pure: the text of one field report, or
  the answers GitHub gave, in; rows out. It reads no file, process, clock or network. What it reads
  in a report (the heading, the columns, the Result field, the words that mean none) are the
  constants below, in one place, as the report template may still change;
- the command reads the window through retro.py's GitHub door (gh, or without gh the answers the
  session saved into `--answers <dir>`, printing the steps still missing as a plan, as
  `retro.py collect` does), and writes and files nothing.

Read-only and standalone: nothing in SE calls it. Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded once under its own name."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


retro = sibling("retro")
work_tickets = retro.work_tickets
QueueError = work_tickets.QueueError

# What the core reads in a field report: the template's (.github/pull_request_template.md)
# Decisions heading and columns, the header field that holds the Result, and the words that mean
# no decision. The report markers are work_tickets.py's (REPORT_BEGIN, REPORT_END).
HEADING = "Decisions"
COLUMNS = ("Decision", "Alternatives", "Rationale", "Confidence")
FIELDS = tuple(column.lower() for column in COLUMNS)
RESULT_FIELD = "Result"
NONE_WORDS = frozenset({"none", "none.", "-", "n/a"})

# A row's status: split into the columns, or kept whole as its text.
PARSED, UNPARSED = "parsed", "unparsed"
# A report's state: rows found, none decided (None, an empty table), no Decisions section, no field
# report at all.
DECIDED, NONE, NO_SECTION, NO_REPORT = "decided", "none", "no-section", "no-report"
GAPS = {NO_SECTION: f"no {HEADING} section", NO_REPORT: "no field report"}

SEPARATOR = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
PIPE = re.compile(r"(?<!\\)\|")
RESULT = re.compile(rf"\*\*{re.escape(RESULT_FIELD)}:\*\*[ \t]*(.*?)[ \t]*(?=\*\*|$)", re.MULTILINE)


# The core: pure.

@dataclass(frozen=True)
class Row:
    """One decision: its four cells where it split into them (PARSED), else its text (UNPARSED)."""

    status: str
    decision: str = ""
    alternatives: str = ""
    rationale: str = ""
    confidence: str = ""
    text: str = ""


@dataclass(frozen=True)
class Report:
    """What one pull request description says of its decisions."""

    state: str
    result: str = ""
    rows: tuple[Row, ...] = ()


def cells(line: str) -> list[str]:
    """The cells of one table line; an escaped pipe (`\\|`) stays in its cell, unescaped."""
    text = line.strip()
    text = text[1:] if text.startswith("|") else text
    text = text[:-1] if text.endswith("|") and not text.endswith("\\|") else text
    return [cell.strip().replace("\\|", "|") for cell in PIPE.split(text)]


def is_none(text: str) -> bool:
    return " ".join(text.split()).lower() in NONE_WORDS


def blocks(text: str) -> list[tuple[bool, list[str]]]:
    """`text` as its runs of lines, each (whether it is a table, its non-blank lines)."""
    found: list[tuple[bool, list[str]]] = []
    for line in text.splitlines():
        if not line.strip():
            if found and not found[-1][0] and found[-1][1]:
                found.append((False, []))
            continue
        table = line.strip().startswith("|")
        if found and found[-1][0] == table:
            found[-1][1].append(line.strip())
        else:
            found.append((table, [line.strip()]))
    return [(table, lines) for table, lines in found if lines]


def table_rows(lines: list[str]) -> list[Row]:
    """The rows of one table: none for an empty one; the whole table as one UNPARSED row where its
    header is not COLUMNS; a line that does not split into the columns as an UNPARSED row."""
    header, body = cells(lines[0]), lines[1:]
    if body and SEPARATOR.match(body[0]):
        body = body[1:]
    if [cell.lower() for cell in header] != list(FIELDS):
        return [Row(UNPARSED, text="\n".join(lines))]
    rows: list[Row] = []
    for line in body:
        found = cells(line)
        if len(found) != len(COLUMNS):
            rows.append(Row(UNPARSED, text=line))
        elif all(is_none(cell) or not cell for cell in found):
            continue
        else:
            rows.append(Row(PARSED, **dict(zip(FIELDS, found))))
    return rows


def decisions(text: str) -> list[Row]:
    """The rows of a Decisions section's text, in order; text outside a table that is not "None"
    is kept as an UNPARSED row, never dropped."""
    rows: list[Row] = []
    for table, lines in blocks(text):
        if table:
            rows += table_rows(lines)
        elif not is_none(" ".join(lines)):
            rows.append(Row(UNPARSED, text="\n".join(lines)))
    return rows


def parse(body: str) -> Report:
    """What the field report in `body` (a pull request description) says of its decisions."""
    report = retro.report_of(body or "")
    if report is None:
        return Report(NO_REPORT)
    plain = work_tickets.HTML_COMMENT_PATTERN.sub("", report)
    found = RESULT.search(plain)
    result = found[1].strip() if found else ""
    if not re.search(rf"^## {re.escape(HEADING)}[ \t]*$", plain, re.MULTILINE):
        return Report(NO_SECTION, result)
    rows = tuple(decisions(retro.section(report, HEADING)))
    return Report(DECIDED if rows else NONE, result, rows)


@dataclass(frozen=True)
class Landing:
    """One pull request merged into the integration branch in the window, and its report."""

    landed: str
    pull: int
    report_pull: int | None
    issue: int | None
    title: str
    report: Report


def landed_pulls(pulls: list[dict], branch: str, since: str | None, until: str | None) -> list:
    """The pull requests of `pulls` (as GitHub answered) merged into `branch` after `since` and
    before `until`, newest first."""
    start, end = retro.when(since), retro.when(until)
    merged = [retro.pull_of(item) for item in pulls]
    found = [pull for pull in merged if pull.merged_at and pull.base == branch
             and (start is None or retro.when(pull.merged_at) > start)
             and (end is None or retro.when(pull.merged_at) < end)]
    return sorted(found, key=lambda pull: (retro.when(pull.merged_at), pull.number), reverse=True)


def landings(pulls: list[dict], titles: dict[int, str], tracker: str, branch: str,
             since: str | None, until: str | None) -> list[Landing]:
    """The landings of the window, newest first, each with the report of the pull request that
    carries it (the landing's `se:field-report-in` marker names it, else the landing itself) and
    its work issue's title from `titles`."""
    by_number = {pull.number: pull for pull in map(retro.pull_of, pulls)}
    found: list[Landing] = []
    for pull in landed_pulls(pulls, branch, since, until):
        marker = retro.REPORT_IN.search(pull.body)
        carrier = by_number.get(int(marker[1])) if marker else pull
        report = parse(carrier.body) if carrier else Report(NO_REPORT)
        issue = retro.reference(pull, tracker)
        found.append(Landing(
            pull.merged_at, pull.number,
            carrier.number if carrier and report.state != NO_REPORT else None,
            issue, titles.get(issue, "") if issue is not None else "", report))
    return found


def rows_of(found: list[Landing]) -> list[dict]:
    """One flat record per decision row, in the order of `found` and of each report."""
    return [{"landed": landing.landed, "pull": landing.pull, "report_pull": landing.report_pull,
             "issue": landing.issue, "title": landing.title, "result": landing.report.result,
             **asdict(row)}
            for landing in found for row in landing.report.rows]


def gaps_of(found: list[Landing]) -> list[dict]:
    """The landings whose report has no Decisions section, or that have no field report."""
    return [{"landed": landing.landed, "pull": landing.pull, "issue": landing.issue,
             "title": landing.title, "state": landing.report.state}
            for landing in found if landing.report.state in GAPS]


def data(found: list[Landing], since: str | None, until: str | None) -> dict:
    return {"since": since, "until": until, "rows": rows_of(found), "gaps": gaps_of(found)}


def text(found: list[Landing], since: str | None, until: str | None) -> str:
    """The rows grouped by pull request, newest first; each gap named."""
    rows = rows_of(found)
    lines = [f"Decisions of {len(found)} landings merged after {since or 'the start'}"
             f"{f' and before {until}' if until else ''}: {len(rows)} rows, "
             f"{len(gaps_of(found))} landings without them."]
    for landing in found:
        issue = (f"work issue #{landing.issue}" + (f" {landing.title}" if landing.title else "")
                 if landing.issue is not None else "no work issue")
        carrier = (f" (field report in #{landing.report_pull})"
                   if landing.report_pull not in (None, landing.pull) else "")
        result = f", Result {landing.report.result}" if landing.report.result else ""
        lines += ["", f"#{landing.pull}{carrier} landed {landing.landed[:10]}, {issue}{result}"]
        state = landing.report.state
        if state in GAPS:
            lines.append(f"  {GAPS[state].upper()}")
        elif state == NONE:
            lines.append("  none")
        for row in landing.report.rows:
            if row.status == UNPARSED:
                lines.append(f"  - {UNPARSED}: " + row.text.replace("\n", "\n    "))
                continue
            lines.append(f"  - {COLUMNS[0]}: {row.decision}")
            lines += [f"    {column}: {getattr(row, name)}"
                      for column, name in zip(COLUMNS[1:], FIELDS[1:])]
    return "\n".join(lines) + "\n"


def until_of(value: str | None) -> str | None:
    """`--until`, a date (the end of that day, UTC) or an ISO time, as GitHub writes times."""
    try:
        moment = retro.since_of(value)
    except QueueError:
        raise QueueError(f"--until {value}: give a date (YYYY-MM-DD) or an ISO time") from None
    if moment is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        moment = (retro.when(moment) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return moment


# The command: the thin wiring around the core.

def read(door, tracker: str, branch: str, since: str | None,
         until: str | None) -> list[Landing] | None:
    """The window's landings read through `door` (retro.py's); None while it misses answers."""
    pulls = door.pulls()
    if door.missing:
        return None
    titles: dict[int, str] = {}
    for pull in landed_pulls(pulls, branch, since, until):
        issue = retro.reference(pull, tracker)
        if issue is not None and issue not in titles:
            titles[issue] = str(door.issue(issue).get("title") or "")
    if door.missing:
        return None
    return landings(pulls, titles, tracker, branch, since, until)


def run_list(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    remote = work_tickets.remote_repo(root) or tracker
    branch = work_tickets.integration_branch(root)
    since, until = retro.since_of(args.since), until_of(args.until)
    if args.answers is not None:
        door = retro.FileDoor(args.answers, tracker, remote)
    elif work_tickets.hand_off():
        door = retro.FileDoor(Path("<dir>"), tracker, remote)
    else:
        door = retro.GhDoor(root, tracker, remote)
    found = read(door, tracker, branch, since, until)
    if found is None:
        directory = args.answers or Path("<dir>")
        then = (f"decision_rows.py list --since {args.since}"
                f"{f' --until {args.until}' if args.until else ''} --answers {directory}"
                f"{' --json' if args.json else ''}{f' --repo {args.repo}' if args.repo else ''}"
                f" --worktree {root}")
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools "
              f"and saves their answers into {directory}:")
        print(retro.Plan(f"the decisions of the landings since {args.since}",
                         tuple(door.missing), then).text())
        return 0
    sys.stdout.write(json.dumps(data(found, since, until), indent=2, ensure_ascii=False) + "\n"
                     if args.json else text(found, since, until))
    return 0


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="decision_rows.py", description=__doc__.split("\n\n")[0])
    commands = top.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list", help="list the Decisions rows of the field reports of a window's landings",
        description="List every row of the Decisions table in the field reports of the pull "
                    "requests merged into the integration branch in the window, grouped by pull "
                    "request, newest first, naming each landing without a Decisions section or "
                    "field report. Writes and files nothing.")
    listing.add_argument("--since", metavar="DATE", required=True,
                         help="landings merged after DATE (YYYY-MM-DD, its start, or an ISO time)")
    listing.add_argument("--until", metavar="DATE",
                         help="landings merged before DATE (YYYY-MM-DD, its end, or an ISO time)")
    listing.add_argument("--answers", type=Path, metavar="DIR",
                         help="without gh: the directory the session saves the plan's answers into")
    listing.add_argument("--repo", help="[HOST/]OWNER/REPO of the issues (default: the tracker or "
                                        "origin remote)")
    listing.add_argument("--json", action="store_true", help="the rows and gaps as JSON")
    listing.add_argument("--worktree", default=".",
                         help="the checkout of the repository (default: .)")
    listing.set_defaults(run=run_list)
    return top


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        return args.run(args)
    except (QueueError, ValueError) as error:
        print(f"decision_rows.py {args.command}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
