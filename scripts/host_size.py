"""Measure generated agent layouts against the limits agent hosts document: a report, never a check.

The host facts live in scripts/host-limits.toml. The core (`parse`, `measure`, `totals`, `order`)
takes file names with their bytes, an optional tool list and the parsed facts, and returns rows:
it touches no file and starts no process. `main` is the thin layer that reads them.

    host_size.py report [--root DIR] [--tools FILE] [--server NAME] [--json]

It writes nothing, decides nothing and always exits 0. Nothing in SE calls it.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_lint import fields, scalar  # noqa: E402

DATA = Path(__file__).resolve().parent / "host-limits.toml"
ROLES = ("instructions", "agent", "skill", "reference")
# What each role's file is measured for; a subject without a limit in the data is "not measured".
SUBJECTS = {"instructions": ("instructions-file",), "agent": ("agent-body",),
            "skill": ("skill-name", "skill-description", "skill-length"), "reference": ("reference-file",)}
# The unit a size is shown in where no limit names one.
DEFAULT_UNIT = {"skill-length": "lines", "instructions-file": "bytes", "reference-file": "bytes"}
STATUSES = ("over", "under", "not measured")


@dataclass(frozen=True)
class Surface:
    id: str
    name: str
    reads: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Limit:
    surface: str
    subject: str
    value: float
    unit: str
    source: str
    read: str
    mark: str
    measures: str = ""
    note: str = ""


@dataclass(frozen=True)
class Facts:
    surfaces: tuple[Surface, ...]
    limits: tuple[Limit, ...]


@dataclass(frozen=True)
class Row:
    surface: str
    item: str
    subject: str
    size: int | None
    unit: str
    status: str
    limit: Limit | None = None
    load: str = "always"


@dataclass(frozen=True)
class Total:
    surface: str
    agent: str
    always: int
    on_demand: int
    parts: Mapping[str, int] = field(default_factory=dict)


def parse(data: Mapping) -> Facts:
    """The host facts of a parsed host-limits.toml."""
    surfaces = tuple(Surface(key, str(value.get("name", key)),
                             {role: tuple(value.get(role, ())) for role in ROLES})
                     for key, value in data.get("surfaces", {}).items())
    limits = tuple(Limit(surface=row["surface"], subject=row["subject"], value=row["value"], unit=row["unit"],
                         source=row.get("source", ""), read=str(row.get("read", "")), mark=row.get("mark", ""),
                         measures=row.get("measures", ""), note=row.get("note", ""))
                   for row in data.get("limits", ()))
    return Facts(surfaces, limits)


def tool_list(answer: object) -> list[Mapping]:
    """The tools of a `tools/list` answer: its result, or the whole JSON-RPC response."""
    if isinstance(answer, Mapping):
        answer = answer.get("result", answer)
        answer = answer.get("tools", ()) if isinstance(answer, Mapping) else answer
    return [tool for tool in answer or () if isinstance(tool, Mapping)] if isinstance(answer, list) else []


def split(text: str) -> tuple[str, str]:
    """A Markdown file's front matter and its body; CRLF reads as LF."""
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[:end + 5], text[end + 5:]
    return "", text


def size(text: str, unit: str) -> int | None:
    """The size of a text in a unit; None for a unit it cannot be counted in (tokens, time)."""
    if unit == "bytes":
        return len(text.encode("utf-8"))
    if unit == "characters":
        return len(text)
    if unit == "lines":
        return text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return None


def role(surface: Surface, path: str) -> str | None:
    """The role a file plays for a host: the first whose pattern matches its posix path."""
    for name in ROLES:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in surface.reads.get(name, ())):
            return name
    return None


def judge(surface: str, item: str, subject: str, texts: Mapping[str, str], limits: Sequence[Limit],
          load: str = "always") -> Row:
    """One row: the tightest limit that applies, by the share of it the size takes.

    `texts` maps a limit's `measures` form (or "") to the text it measures."""
    found = [limit for limit in limits if limit.surface == surface and limit.subject == subject]
    best: tuple[float, int, Limit] | None = None
    for limit in found:
        measured = size(texts.get(limit.measures, texts.get("", "")), limit.unit)
        if measured is not None and limit.value > 0 and (best is None or measured / limit.value > best[0]):
            best = (measured / limit.value, measured, limit)
    if best is None:
        unit = DEFAULT_UNIT.get(subject, "characters")
        return Row(surface, item, subject, size(texts.get("", ""), unit), unit, "not measured",
                   found[0] if found else None, load)
    _, measured, limit = best
    return Row(surface, item, subject, measured, limit.unit, "over" if measured > limit.value else "under",
               limit, load)


def file_texts(path: str, file_role: str, text: str) -> dict[str, str]:
    """The text each subject of a file measures."""
    head, body = split(text)
    if file_role == "skill":
        found = fields(head)
        return {"skill-name": scalar(found.get("name", "")),
                "skill-description": scalar(found.get("description", "")), "skill-length": text}
    if file_role == "agent":
        return {"agent-body": body}
    return {subject: text for subject in SUBJECTS[file_role]}


def measure(files: Mapping[str, bytes], facts: Facts, tools: Sequence[Mapping] | None = None,
            server: str = "se") -> list[Row]:
    """Every row: per host, each file it reads and each tool, against the tightest limit that applies."""
    rows = []
    for surface in facts.surfaces:
        listing = []
        for path in sorted(files):
            file_role = role(surface, path)
            if file_role is None:
                continue
            texts = file_texts(path, file_role, files[path].decode("utf-8", errors="replace"))
            for subject in SUBJECTS[file_role]:
                load = "on demand" if file_role == "reference" or subject == "skill-length" else "always"
                rows.append(judge(surface.id, path, subject, {"": texts[subject]}, facts.limits, load))
            if file_role == "skill":
                listing.append(f"{texts['skill-name']}: {texts['skill-description']}")
        if listing:
            rows.append(judge(surface.id, "(all skills)", "skill-listing", {"": "\n".join(listing)}, facts.limits))
        for tool in tools or ():
            name = str(tool.get("name", ""))
            item = f"tool {name}"
            rows.append(judge(surface.id, item, "mcp-tool-description", {"": str(tool.get("description", ""))},
                              facts.limits))
            forms = {limit.measures: limit.measures.format(server=server, tool=name) for limit in facts.limits
                     if limit.subject == "tool-name" and limit.measures}
            rows.append(judge(surface.id, item, "tool-name", {"": name, **forms}, facts.limits))
    return order(rows)


def order(rows: Sequence[Row]) -> list[Row]:
    """The largest overrun first, then the closest to its limit; unmeasured last; ties by name."""
    def key(row: Row):
        share = row.size / row.limit.value if row.status != "not measured" and row.limit and row.size else 0.0
        return STATUSES.index(row.status), -share, row.item, row.surface, row.subject
    return sorted(rows, key=key)


def totals(files: Mapping[str, bytes], facts: Facts, tools: Sequence[Mapping] | None = None) -> list[Total]:
    """Per host and agent, the bytes a session is always handed apart from those that load on demand.

    Always: the root instruction file, that agent's file, each skill's name and description, the tool
    list (its JSON). On demand: the skills' bodies past their name and description, and references."""
    result = []
    tool_bytes = sum(len(json.dumps(tool, separators=(",", ":")).encode("utf-8")) for tool in tools or ())
    for surface in facts.surfaces:
        parts = {"instructions": 0, "skill listing": 0, "tools": tool_bytes, "skill bodies": 0, "references": 0}
        agents = {}
        for path in sorted(files):
            file_role, raw = role(surface, path), files[path]
            if file_role == "instructions":
                parts["instructions"] += len(raw)
            elif file_role == "agent":
                agents[path] = len(raw)
            elif file_role == "reference":
                parts["references"] += len(raw)
            elif file_role == "skill":
                found = fields(split(raw.decode("utf-8", errors="replace"))[0])
                listed = len((scalar(found.get("name", "")) + scalar(found.get("description", ""))).encode("utf-8"))
                parts["skill listing"] += listed
                parts["skill bodies"] += len(raw) - listed
        shared = parts["instructions"] + parts["skill listing"] + parts["tools"]
        on_demand = parts["skill bodies"] + parts["references"]
        for path, agent_bytes in sorted(agents.items()) or [("(no agent)", 0)]:
            result.append(Total(surface.id, path, shared + agent_bytes, on_demand, {**parts, "agent": agent_bytes}))
    return result


def text(rows: Sequence[Row], sums: Sequence[Total], data: str) -> str:
    """The report as lines to read."""
    lines = [f"host_size: generated layouts against {data}; a report, it decides nothing", ""]
    table = [(row.status, row.surface, row.item, row.subject, f"{'?' if row.size is None else row.size} {row.unit}",
              f"{row.limit.value:g} {row.limit.unit} ({row.limit.mark}, read {row.limit.read})" if row.limit and
              row.status != "not measured" else "no limit in the data" if row.limit is None else
              f"{row.limit.value:g} {row.limit.unit}: not countable here") for row in rows]
    widths = [max((len(cells[i]) for cells in table), default=0) for i in range(5)]
    lines += ["  ".join(cell.ljust(width) for cell, width in zip(cells, widths)) + "  " + cells[5]
              for cells in table]
    lines += ["", "bytes per session, always handed apart from on demand:"]
    lines += [f"{total.surface}  {total.agent}  always {total.always} B  on demand {total.on_demand} B"
              for total in sums]
    return "\n".join(line.rstrip() for line in lines)


def gather(root: Path, facts: Facts) -> dict[str, bytes]:
    """The files of a checkout that any host reads, by their posix path."""
    found = {}
    for surface in facts.surfaces:
        for pattern in (pattern for patterns in surface.reads.values() for pattern in patterns):
            for path in root.glob(pattern):
                if path.is_file():
                    found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="host_size.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="print every row, the largest overrun first; always exits 0")
    report.add_argument("--root", type=Path, default=Path.cwd(), help="the repository to measure (default: here)")
    report.add_argument("--tools", type=Path, help="the JSON of a tools/list answer")
    report.add_argument("--server", default="se", help="the MCP server's name, as hosts prefix its tools")
    report.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    try:
        known = parse(tomllib.loads(DATA.read_text(encoding="utf-8")))
        tools = tool_list(json.loads(args.tools.read_text(encoding="utf-8"))) if args.tools else None
        files = gather(args.root.resolve(), known)
    except (OSError, ValueError) as error:
        print(f"host_size.py: nothing measured: {error}")
        return 0
    rows, sums = measure(files, known, tools, args.server), totals(files, known, tools)
    if args.json:
        print(json.dumps({"data": DATA.name, "rows": [asdict(row) for row in rows],
                          "totals": [asdict(total) for total in sums]}, indent=2))
    else:
        print(text(rows, sums, DATA.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
