"""Check se's rule book: every rule's id and shape.

The book's own header owns the id scheme and the shape of a rule
(src/skills/work-model/references/rules.md, "Ids" and "The shape of a rule"); this script refuses a
book that breaks them and lists, without failing, every rule followed only by judgment.

Exit code 0: the book passed; 1: it has problems (each printed as `<book>:<line>: <problem>`);
2: setup error (the book is missing).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "src" / "skills" / "work-model" / "references" / "rules.md"

# The cross-cutting areas. A project's prefix is p-<project>, so no area may start with "p-".
AREAS = ("gen", "des", "tst", "doc", "wrk", "dec", "pub")
FIELDS = ("Why", "Without it", "Prevents", "Implementations", "Related")
ID = re.compile(r"^(?:(?P<area>[a-z]+)|p-(?P<project>[a-z0-9]+))-(?P<number>\d{3,})$")
SECTION = re.compile(r"^## (?P<prefix>[a-z0-9-]+): (?P<title>.+?)\s*$")
RULE = re.compile(r"^### (?P<id>\S+) (?P<name>.+?)\s*$")
FIELD = re.compile(r"^- \*\*(?P<name>[^*]+?):\*\*\s*(?P<value>.*)$")
SUB_ITEM = re.compile(r"^\s{2,}- (?P<value>.+)$")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
MAPPING = re.compile(r"^\|\s*(?P<number>\d+)\s*\|\s*(?P<id>[^|\s]+)\s*\|")
LINK = re.compile(r"\]\([^)]+\)")
JUDGMENT = re.compile(r"\bby judgment\b", re.IGNORECASE)
FROZEN = re.compile(r"^[^:]*\(frozen\):")


@dataclass
class Rule:
    id: str
    name: str
    line: int
    statement: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    implementations: list[str] = field(default_factory=list)
    retired: str | None = None

    @property
    def judgment_only(self) -> bool:
        """Every live implementation is "by judgment"; a frozen line's implementations are not live."""
        live = [item for item in self.implementations if not FROZEN.match(item)]
        return bool(live) and all(JUDGMENT.search(item) and not LINK.search(item) for item in live)


def area_problems() -> list[str]:
    """The fixed areas themselves: lowercase letters, never a project prefix."""
    return [f"area prefix {area!r} must be lowercase letters and must not start with 'p-'"
            for area in AREAS if not re.fullmatch(r"[a-z]+", area) or area.startswith("p-")]


def id_problem(rule_id: str) -> str | None:
    """Why an id is malformed, or None: `<area>-<nnn>` or `p-<project>-<nnn>`, lowercase."""
    match = ID.match(rule_id)
    if not match:
        return (f"malformed id {rule_id!r}: write <area>-<number> or p-<project>-<number>, "
                "lowercase, the number with at least three digits (gen-001, p-se-001)")
    area = match["area"]
    if area is not None and area not in AREAS:
        return (f"malformed id {rule_id!r}: {area!r} is not an area ({', '.join(AREAS)}); "
                f"a project rule's id starts with 'p-' (p-{area}-{match['number']})")
    return None


def prefix_of(rule_id: str) -> str:
    return rule_id.rsplit("-", 1)[0]


def parse(text: str) -> tuple[list[Rule], list[tuple[int, str]], list[tuple[int, int, str]]]:
    """The book's rules, its problems so far, and its old-number mapping rows (line, number, id)."""
    rules: list[Rule] = []
    problems: list[tuple[int, str]] = []
    mapping: list[tuple[int, int, str]] = []
    section: str | None = None
    rule: Rule | None = None
    current: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            rule = current = None
            match = SECTION.match(line)
            section = match["prefix"] if match else None
            if section is not None and section not in AREAS and not re.fullmatch(r"p-[a-z0-9]+", section):
                problems.append((number, f"section prefix {section!r} is neither an area "
                                 f"({', '.join(AREAS)}) nor a project's p-<project>"))
            continue
        if line.startswith("### ") and section is not None:
            match = RULE.match(line)
            if not match:
                problems.append((number, "a rule heading is '### <id> <name>'"))
                rule = None
                continue
            rule = Rule(match["id"], match["name"], number)
            rules.append(rule)
            current = None
            problem = id_problem(rule.id)
            if problem:
                problems.append((number, problem))
            elif prefix_of(rule.id) != section:
                problems.append((number, f"{rule.id} stands in section {section!r}; "
                                 f"move it to section {prefix_of(rule.id)!r}"))
            continue
        if section is None:
            row = MAPPING.match(line)
            if row:
                mapping.append((number, int(row["number"]), row["id"]))
            continue
        if rule is None:
            continue
        match = FIELD.match(line)
        if match:
            current = match["name"]
            value = match["value"].strip()
            if current == "Retired":
                rule.retired = value
            elif current in FIELDS:
                if current in rule.fields:
                    problems.append((number, f"{rule.id}: field {current} appears twice"))
                rule.fields[current] = value
            else:
                problems.append((number, f"{rule.id}: unknown field {current!r}; the fields are "
                                 f"{', '.join(FIELDS)} and Retired"))
            continue
        sub = SUB_ITEM.match(line)
        if sub and current == "Implementations":
            rule.implementations.append(sub["value"])
        elif not line.strip():
            continue
        elif current is None:
            rule.statement.append(line.strip())
        elif line.startswith(" "):
            if current == "Implementations" and rule.implementations:
                rule.implementations[-1] += " " + line.strip()
            elif current in rule.fields:
                rule.fields[current] = (rule.fields[current] + " " + line.strip()).strip()
        else:
            problems.append((number, f"{rule.id}: text after the fields; the rule's sentence "
                             "comes first, then its fields"))
    return rules, problems, mapping


def rule_problems(rule: Rule) -> list[tuple[int, str]]:
    problems: list[tuple[int, str]] = []
    statement = " ".join(rule.statement)
    if not statement:
        problems.append((rule.line, f"{rule.id}: missing the one sentence stating the rule"))
    elif len(SENTENCE_END.findall(statement)) != 1 or not SENTENCE_END.search(statement[-1]):
        problems.append((rule.line, f"{rule.id}: the rule is stated in exactly one sentence"))
    for name in FIELDS:
        value = rule.fields.get(name)
        if value is None or (name != "Implementations" and not value):
            problems.append((rule.line, f"{rule.id}: missing field {name}"))
    if "Implementations" in rule.fields and not rule.implementations:
        problems.append((rule.line, f"{rule.id}: Implementations lists no implementation; "
                         "name each as an item '  - <language or project>: <how>'"))
    if rule.retired is not None and not rule.retired:
        problems.append((rule.line, f"{rule.id}: a retired rule names the reason it was retired"))
    return problems


def check(text: str) -> tuple[list[tuple[int, str]], list[Rule]]:
    """The book's problems (line, problem) and its rules followed only by judgment."""
    rules, problems, mapping = parse(text)
    problems = [(0, problem) for problem in area_problems()] + problems
    seen: dict[str, Rule] = {}
    for rule in rules:
        problems += rule_problems(rule)
        earlier = seen.get(rule.id)
        if earlier is None:
            seen[rule.id] = rule
        elif earlier.retired is not None or rule.retired is not None:
            problems.append((rule.line, f"{rule.id} reuses a retired id (line {earlier.line}); "
                             "a retired id is never reused: give the rule a new id"))
        else:
            problems.append((rule.line, f"duplicate id {rule.id} (also line {earlier.line})"))
    for rule in rules:
        related = rule.fields.get("Related", "")
        if related.casefold().rstrip(".") == "none":
            continue
        for reference in filter(None, (part.strip().rstrip(".") for part in related.split(","))):
            if reference not in seen:
                problems.append((rule.line, f"{rule.id}: Related names {reference!r}, "
                                 "which is no rule in the book"))
    for line, number, rule_id in mapping:
        if rule_id not in seen:
            problems.append((line, f"principle {number} maps to {rule_id!r}, which is no rule in the book"))
    judgment = [rule for rule in rules if rule.retired is None and rule.judgment_only]
    return sorted(problems), judgment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--book", type=Path, default=BOOK, help="the rule book (default: se's)")
    args = parser.parse_args(argv)
    try:
        text = args.book.read_text(encoding="utf-8")
    except OSError as error:
        print(f"rule_book.py: cannot read the rule book {args.book}: {error}", file=sys.stderr)
        return 2
    problems, judgment = check(text)
    for line, problem in problems:
        print(f"{args.book}:{line}: {problem}")
    for rule in judgment:
        print(f"by judgment only: {rule.id} {rule.name}")
    print(f"rule_book.py: {'failed, ' + str(len(problems)) + ' problem(s)' if problems else 'passed'}; "
          f"{len(judgment)} rule(s) followed by judgment only")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
