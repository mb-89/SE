# se:template se/python-module 1.0.0
"""The overhaul's scrutiny facts: the tests, the doors and the files over the bound.

`overhaul.py facts` imports it for the facts its questions on tests and long files are answered
from (templates/overhaul-questions.md): each door with its reaches outside (`door_rows`), the
tests' spawn marks by kind (`spawn_marks`), the slowest test files by CI's seconds
(`slowest_files`), the lines BROAD tests or more run (`broad_lines`), and, for each file over
hygiene.py's LONG_LINES, its commands by component (`components_of`) and the roots each command's
lines are reached from (`command_roots`), or a Markdown file's lines per section
(`markdown_jobs`). QUESTION_FACTS names, for every question of the overhaul's own, the facts it is
answered from or why judgment alone answers it; `question_fact_problems` refuses a question with
neither. It only reads, and judges nothing.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

import door_report

# A line this many tests run or more is run by an over-broad battery (`broad_lines`).
BROAD = 200
# CI's seconds per test file (AGENTS.md "Tests", File order), which the slowest files are read from.
FILE_SECONDS = "tests/file-seconds.json"
# A spawn mark, `@pytest.mark.spawns("<kind>: <why>")` (scripts/spawn_guard.py): its kind is the
# words before the colon.
SPAWN_MARK = re.compile(r'mark\.spawns\(\s*"([a-z][a-z ]*):')

# The overhaul's own questions (templates/overhaul-questions.md, QUESTIONS_TEMPLATE), each with the
# facts it is answered from, as fields of overhaul.py's Facts, or why judgment alone answers it: a
# question with neither fails `overhaul.py facts`, so no question the overhaul asks goes without
# what the checkout can count.
QUESTIONS_TEMPLATE = "overhaul-questions"
QUESTION_FACTS: dict[str, tuple[str, ...] | str] = {
    "voice_style": "the voice is read, not counted; the docs build's lints hold what can be counted",
    "best_method": "a method is weighed against the best one known outside, which the checkout does not hold",
    "guidance_drift": ("unnamed",),
    "file_earns_place": ("unreached", "untouched", "sizes"),
    "design_pattern": ("duplicates", "near", "long_functions", "long_parameters"),
    "outside_world": "the outside world is outside the checkout",
    "doors": ("doors",),
    "door_tests": ("doors", "spawn_marks"),
    "superfluous_tests": ("repeats", "broad_lines"),
    "slowest_tests": ("slowest_files",),
    "long_files": ("long_file_jobs",),
}


def question_fact_problems(fields: list[str], known: set[str],
                           facts: dict[str, tuple[str, ...] | str] = QUESTION_FACTS) -> list[str]:
    """What keeps each question field in `fields` from naming its facts in `facts`: a question
    with no entry, an entry for no question, a fact not among the `known` ones, and a judgment
    with no reason; none where every question names its facts or why judgment alone answers it."""
    problems = [f"{name}: the question names no fact; add QUESTION_FACTS[{name!r}] in "
                f"scripts/overhaul_scrutiny.py, the facts it is answered from or why judgment alone answers it"
                for name in fields if name not in facts]
    problems += [f"QUESTION_FACTS[{name!r}]: no question of {QUESTIONS_TEMPLATE}; remove the entry"
                 for name in facts if name not in fields]
    for name, named in facts.items():
        if isinstance(named, str):
            if not named.strip():
                problems.append(f"QUESTION_FACTS[{name!r}]: a judgment names its reason")
        elif not named:
            problems.append(f"QUESTION_FACTS[{name!r}]: names no fact")
        else:
            problems += [f"QUESTION_FACTS[{name!r}]: {fact} is no field of the overhaul's Facts"
                         for fact in named if fact not in known]
    return problems


def facts_behind(name: str) -> str:
    """The facts QUESTION_FACTS names for the question `name`, or its judgment's reason."""
    named = QUESTION_FACTS.get(name, "")
    return f"judgment: {named}" if isinstance(named, str) else ", ".join(named)


# Reading the checkout


def components_of(root: Path) -> dict[str, dict[str, list[str]]]:
    """Each script's commands by the component they attach as, read from the declarations
    `work_tickets.py docs` writes (`components/<name>/component.toml`), whose command keys are
    `<script>.py <words>`."""
    found: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for declaration in sorted((root / "components").glob("*/component.toml")):
        try:
            data = tomllib.loads(declaration.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"{declaration}: {error}") from error
        name = str(data.get("name", declaration.parent.name))
        for key in data.get("commands", {}):
            script, _, words = str(key).partition(" ")
            found[f"scripts/{script}"].setdefault(name, []).append(words)
    return dict(found)


def door_rows(root: Path) -> list[dict]:
    """Each door `scripts/doors/*.toml` declares, with its level, its contract tests and the
    reaches outside it `door_report.py` finds; none where the checkout declares no door."""
    folder = root / "scripts" / "doors"
    if not any(folder.glob("*.toml")):
        return []
    try:
        declarations = door_report.load_all(folder)
    except door_report.DeclarationError as error:
        raise ValueError(f"doors: {error}") from error
    texts, _ = door_report.read(root)
    results, _ = door_report.scan(texts, declarations)
    return [{"door": result.door.door, "level": result.door.level,
             "contract_tests": list(result.door.contract_tests), "reaches": len(result.reaches),
             "files": len({reach.path for reach in result.reaches})} for result in results]


def file_seconds(root: Path) -> dict[str, float]:
    """CI's seconds per test file (FILE_SECONDS); none where the checkout keeps none."""
    path = root / FILE_SECONDS
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    return {str(name): float(seconds) for name, seconds in data.items()}


# The facts


def _string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _names(*nodes: ast.AST) -> set[str]:
    return {child.id if isinstance(child, ast.Name) else child.attr for node in nodes for child in ast.walk(node)
            if isinstance(child, (ast.Name, ast.Attribute))}


def command_roots(tree: ast.Module) -> dict[str, set[str]]:
    """The names each command's code starts from, by the command's words, as a script dispatches
    it: the registry's `@command("name", ..., parent=GROUP)` on a function; argparse's
    `<parser> = ....add_parser("name")` with `<parser>.set_defaults(<key>=<handler>)`; a dict
    literal from command names to handlers; and an `if args.command == "name":` branch. A parser
    is a name it is assigned to, or the `add_parser` call `set_defaults` is chained on."""
    groups: dict[str, str] = {}
    parsers: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and node.value.args:
            callee = node.value.func
            called = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            word = _string(node.value.args[0])
            for target in node.targets:
                if isinstance(target, ast.Name) and word and called == "command_group":
                    groups[target.id] = word
                elif isinstance(target, ast.Name) and word and called == "add_parser":
                    parsers[target.id] = word
    commands = set(parsers.values())
    found: dict[str, set[str]] = defaultdict(set)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "command"
                        and decorator.args and (word := _string(decorator.args[0]))):
                    parent = next((item.value for item in decorator.keywords if item.arg == "parent"), None)
                    words = [groups[parent.id], word] if isinstance(parent, ast.Name) and parent.id in groups else [word]
                    found[" ".join(words)].add(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_defaults":
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in parsers:
                word = parsers[owner.id]
            elif (isinstance(owner, ast.Call) and isinstance(owner.func, ast.Attribute)
                  and owner.func.attr == "add_parser" and owner.args):
                word = _string(owner.args[0])
            else:
                word = None
            if word:
                found[word] |= _names(*(item.value for item in node.keywords))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (word := _string(key)) in commands and isinstance(value, (ast.Name, ast.Attribute, ast.Lambda)):
                    found[word] |= _names(value)
        elif (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1
              and isinstance(node.test.ops[0], ast.Eq) and isinstance(node.test.left, ast.Attribute)
              and node.test.left.attr == "command" and (word := _string(node.test.comparators[0]))):
            found[word] |= _names(*node.body)
    return dict(found)


def markdown_jobs(text: str, top: int) -> list[dict]:
    """A Markdown file's lines per `## ` section, the `top` longest first: its jobs, as its
    headings name them."""
    rows: list[dict] = []
    for line in text.splitlines():
        if line.startswith("## "):
            rows.append({"job": line[3:].strip(), "commands": 0, "lines": 0})
        if rows:
            rows[-1]["lines"] += 1
    return sorted(rows, key=lambda row: (-row["lines"], row["job"]))[:top]


def spawn_marks(tests: dict[str, str]) -> list[dict]:
    """The tests' spawn marks by kind (`contract`, `entry`, `shell`, ...), each with how many marks
    and the files that hold them: the tests that start a real process, by why."""
    kinds: dict[str, Counter] = defaultdict(Counter)
    for path, source in tests.items():
        for kind in SPAWN_MARK.findall(source):
            kinds[kind.strip()][path] += 1
    rows = [{"kind": kind, "marks": sum(files.values()), "files": sorted(files)} for kind, files in kinds.items()]
    return sorted(rows, key=lambda row: (-row["marks"], row["kind"]))


def slowest_files(seconds: dict[str, float], top: int) -> list[dict]:
    """The `top` slowest test files by CI's seconds, the slowest first."""
    rows = sorted(seconds.items(), key=lambda item: (-item[1], item[0]))[:top]
    return [{"file": path, "seconds": took} for path, took in rows]


def broad_lines(lines: dict[str, frozenset], files: dict[int, str], top: int, broad: int | None = None) -> list[dict]:
    """The lines (file id, line) `broad` tests or more run in their calls, by file (`files` names
    each id), the `top` with the most first: where an over-broad battery runs the same code again
    and again; `broad` defaults to BROAD."""
    broad = BROAD if broad is None else broad
    counts = Counter(line for held in lines.values() for line in held)
    by_file: dict[str, list[int]] = defaultdict(list)
    for (file_id, _), count in counts.items():
        if count >= broad:
            by_file[files.get(file_id, str(file_id))].append(count)
    rows = [{"file": path, "lines": len(found), "most": max(found)} for path, found in by_file.items()]
    return sorted(rows, key=lambda row: (-row["lines"], row["file"]))[:top]


# The report


def sections(long_file_jobs: list[dict], doors: list[dict], marks: list[dict], slowest: list[dict],
             broad: list[dict] | None, bound: int, unmeasured: str) -> list[str]:
    """The report's sections of the files over the `bound`, the doors, the spawn marks, the slowest
    test files and the lines BROAD tests or more run (`unmeasured` where no run is kept)."""
    out = [f"## Files over {bound} lines and their jobs ({len(long_file_jobs)})", ""]
    for row in long_file_jobs:
        commands = "; ".join(f"{name}: {', '.join(words)}" for name, words in row["components"].items())
        jobs = ", ".join(f"{job['job']} {job['lines']}" for job in row["jobs"])
        out.append(f"- {row['at']}: {row['lines']} lines; {row['reason'] or 'no reason stated'}"
                   + (f"; commands by component: {commands}" if commands else "")
                   + (f"; lines per job: {jobs}" if jobs else ""))
    out += [] if long_file_jobs else ["none"]
    out += ["", "## Doors and their reaches outside", ""]
    out += [f"- {row['door']} ({row['level']}): {row['reaches']} reaches in {row['files']} files outside; "
            f"contract tests: {', '.join(row['contract_tests']) or 'none'}" for row in doors] or ["none"]
    out += ["", "## Spawn marks by kind", ""]
    out += [f"- {row['kind']}: {row['marks']} marks in {len(row['files'])} files" for row in marks] or ["none"]
    out += ["", f"## Slowest test files ({FILE_SECONDS})", ""]
    out += [f"- {row['file']}: {row['seconds']:.1f} s" for row in slowest] or ["none"]
    out += ["", f"## Lines {BROAD} tests or more run", ""]
    if broad is None:
        out.append(unmeasured)
    else:
        out += [f"- {row['file']}: {row['lines']} lines, the most run by {row['most']} tests" for row in broad] or ["none"]
    return out + [""]
