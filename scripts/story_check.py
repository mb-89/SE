"""Check a story deck: one actor, then problem, start, one to six steps and result, one claim per slide.

A story deck is an obs vault whose manifest names the actor and links its slides in order. Each slide
note has a `#` title, a `## Claim` section and a `## Evidence` section; an evidence half that is
exactly ``NOT_YET_RUN`` is a claim whose run has not happened yet. The core (``slides``, ``halves``,
``check``, ``render``) is pure: texts in, a report out. Only ``main`` reads files. It prints the
story, its actor, its counts and its problems, and exits 0 whatever it finds; 2 when the manifest
cannot be read.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The evidence half of a slide whose run has not happened yet, exactly.
NOT_YET_RUN = "> [!todo] Not yet run\n> Added from the record of the run once the run has happened."
# The parts of a story in the order its slides tell them.
PARTS = ("problem", "start", "step", "result")
ONCE = ("problem", "start", "result")
MOST_STEPS = 6

_LINK = re.compile(r"(?<!!)\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_LIST = re.compile(r"([-*+]|\d+\.) ")


@dataclass(frozen=True)
class Halves:
    """A slide's two halves: each section's text (None where the section is missing) and whether the
    evidence section comes above the claim."""

    claim: str | None
    evidence: str | None
    evidence_first: bool = False


@dataclass
class Report:
    title: str
    actor: str
    slides: int
    steps: int
    not_yet_run: int
    problems: list[str] = field(default_factory=list)


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def _split(text: str) -> tuple[list[str], list[str]]:
    """The frontmatter's lines and the body's lines of a note's ``text``."""
    lines = _lines(text)
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return lines[1:index], lines[index + 1:]
    return [], lines


def _value(raw: str) -> str:
    """A flat frontmatter value without its `#` comment and its quotes."""
    value = re.sub(r"(^|\s)#.*$", "", raw).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _entries(front: list[str], key: str) -> list[tuple[str, list[str]]]:
    """Each top-level ``key:`` line of ``front``: its value and the `- ` lines below it."""
    entries = []
    for index, line in enumerate(front):
        match = re.match(rf"{re.escape(key)}:(.*)$", line)
        if not match:
            continue
        items = []
        for below in front[index + 1:]:
            item = re.match(r"\s*- (.*)$", below)
            if not item:
                break
            items.append(_value(item.group(1)))
        entries.append((_value(match.group(1)), items))
    return entries


def _body(lines: list[str]) -> list[tuple[str, bool]]:
    """The body's lines, each with whether it is fenced code (a fence line counts as fenced)."""
    marked, fenced = [], False
    for line in lines:
        fence = line.lstrip().startswith(("```", "~~~"))
        marked.append((line, fenced or fence))
        fenced ^= fence
    return marked


def slides(manifest_text: str) -> list[str]:
    """The slide names the manifest body links, `[[name]]` or `[[name|alias]]`, in order."""
    _, body = _split(manifest_text)
    return [match.group(1).strip() for line in body for match in _LINK.finditer(line)]


def halves(note_text: str) -> Halves:
    """The `## Claim` and `## Evidence` sections of a note: the one place that finds them."""
    _, body = _split(note_text)
    sections: dict[str, tuple[int, list[str]]] = {}
    current = None
    for index, (line, fenced) in enumerate(_body(body)):
        heading = None if fenced else re.match(r"(#{1,2}) +(.*?)\s*$", line)
        if heading:
            name = heading.group(2).casefold() if heading.group(1) == "##" else None
            current = name if name in ("claim", "evidence") and name not in sections else None
            if current:
                sections[current] = (index, [])
            continue
        if current:
            sections[current][1].append(line)
    texts = {name: "\n".join(lines).strip() for name, (_, lines) in sections.items()}
    first = "claim" in sections and "evidence" in sections and sections["evidence"][0] < sections["claim"][0]
    return Halves(texts.get("claim"), texts.get("evidence"), first)


def _slide_problems(halves_: Halves, body: list[str]) -> list[str]:
    problems = []
    if not any(not fenced and re.match(r"# +\S", line) for line, fenced in _body(body)):
        problems.append("no title")
    if not halves_.claim:
        problems.append("no claim half")
    if not halves_.evidence:
        problems.append("no evidence half")
    if halves_.evidence_first:
        problems.append("evidence before claim")
    if halves_.claim and any(_LIST.match(line.lstrip()) for line in halves_.claim.split("\n")):
        problems.append("claim holds a list")
    return problems


def check(manifest_name: str, manifest_text: str, notes: dict[str, str | None]) -> Report:
    """The report of a story: the manifest's text and each linked note's text (None for a missing note),
    keyed by the names ``slides`` returns."""
    front, _ = _split(manifest_text)
    titles = _entries(front, "title")
    actors = _entries(front, "actor")
    manifest_problems = []
    actor = ""
    if len(actors) > 1:
        manifest_problems.append("more than one actor")
        actor = ", ".join(value for value, _ in actors)
    elif actors:
        value, items = actors[0]
        if value.startswith("[") or (not value and items):
            manifest_problems.append("more than one actor")
            actor = value or ", ".join(items)
        elif not value:
            manifest_problems.append("no actor")
        else:
            actor = value
    else:
        manifest_problems.append("no actor")

    names = slides(manifest_text)
    seen: set[str] = set()
    last, steps, not_yet_run = -1, 0, 0
    slide_problems = []
    for name in names:
        note = f"{name}.md"
        text = notes.get(name)
        if text is None:
            slide_problems.append(f"{note}: no such note")
            continue
        front_, body = _split(text)
        parts = _entries(front_, "part")
        part = parts[0][0] if parts and parts[0][0] else None
        problems = []
        if part is None:
            problems.append("no part")
        elif part not in PARTS:
            problems.append(f"unknown part {part}")
        else:
            order = PARTS.index(part)
            if order < last or (part in ONCE and part in seen):
                problems.append(f"{part} out of order")
            elif part == "step" and steps >= MOST_STEPS:
                problems.append("more than six steps")
            seen.add(part)
            last = max(last, order)
            steps += part == "step"
        found = halves(text)
        problems += _slide_problems(found, body)
        not_yet_run += found.evidence == NOT_YET_RUN
        slide_problems += [f"{note}: {problem}" for problem in problems]
    manifest_problems += [f"no {part} slide" for part in PARTS if part not in seen]
    return Report(
        title=titles[0][0] if titles else "",
        actor=actor,
        slides=len(names),
        steps=steps,
        not_yet_run=not_yet_run,
        problems=[f"{manifest_name}: {problem}" for problem in manifest_problems] + slide_problems,
    )


def render(report: Report) -> list[str]:
    """The lines ``main`` prints for ``report``."""
    lines = [
        f"story: {report.title}",
        f"actor: {report.actor}",
        f"slides: {report.slides}, steps: {report.steps}",
        f"not yet run: {report.not_yet_run} of {report.slides} evidence halves",
    ]
    return lines + (report.problems or ["problems: none"])


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", type=Path, metavar="MANIFEST", help="the story's manifest note")
    arguments = parser.parse_args(argv)
    manifest = arguments.manifest
    text = _read(manifest)
    if text is None:
        print(f"story_check: cannot read {manifest}", file=sys.stderr)
        return 2
    notes = {name: _read(manifest.parent / f"{name}.md") for name in slides(text)}
    for line in render(check(manifest.name, text, notes)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
