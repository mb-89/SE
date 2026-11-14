#!/usr/bin/env python3
"""An overhaul: is the design still right? (README "Work commands").

`overhaul.py new` files the overhaul issue, `docs/overhaul-<yyyymmdd>` labelled `discovery`, with
the body of `.github/ISSUE_TEMPLATE/overhaul.md`, through `work_tickets.py file`'s filing path:
once, an open overhaul answering a second `new`.

`overhaul.py read <issue> [--out FILE] [--json] [--answers DIR]` writes the draft the judge starts
from: every rule of the rule book with what checks it (a test, a check, or judgment); the retros
closed since the last closed overhaul, from their reports' blocks; the previous overhaul's findings
and the state of the issues that name them (`overhaul #<n> finding <k>`), too early to score where
one is still open; and the pruning facts.
It ends in a JSON block under BLOCK_MARKER whose judgment the judge fills.

`overhaul.py file <issue> --draft FILE` refuses an incomplete judgment, writing nothing; it files
no issue (wrk-007). It posts the report, each finding with its kind (`work`, which SE bundles, or
`decision`, for the owner's decision list; a rule change is always a decision), then the facts and
the block, as the overhaul issue's closing comment, and closes the issue.

GitHub is read and written through work_tickets.py's door (gh); without gh `read` prints its reads
as a plan for the session's GitHub tools and takes their answers from `--answers DIR`, and `file`
prints its comment and close as a plan, as the work model's "Without gh" says for `integrate`.

`overhaul.py facts [--json] [--repo PATH]` lists what an overhaul's pruning judgment starts from:
the functions and classes in `scripts/` that nothing but tests reaches, duplicate and
near-duplicate blocks, the lines of code and of tests per script, the longest functions, files and
parameter lists, the files untouched longest, and each script command that no authored text names.
It only reads and judges nothing: the facts are candidates, the overhaul decides.

Standard library only."""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import keyword
import re
import sys
import time
import tokenize
import tomllib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import git_door
# A duplicate block is at least WINDOW lines alike, MEANINGFUL of them with MIN_CHARS characters
# or more; a block written more than COMMON times is an idiom, not a copy. Near-duplicate
# functions have MIN_TOKENS tokens or more and share NEAR_ALIKE percent of their SHINGLE-token
# shingles, a shingle in more than COMMON functions being an idiom. Each list of the longest shows
# TOP entries.
WINDOW = 6
MEANINGFUL = 4
MIN_CHARS = 10
MIN_TOKENS = 40
SHINGLE = 8
NEAR_ALIKE = 75
COMMON = 8
TOP = 10

# The authored text where se.toml names none: every tracked Markdown file.
DEFAULT_AUTHORED = ["**/*.md"]


@dataclass
class Checkout:
    """What facts reads: the scripts and tests by path, the authored text, the git history."""

    scripts: dict[str, str]
    tests: dict[str, str]
    authored: dict[str, str]
    # The tracked files, and each one's last change as a Unix time where git has one.
    tracked: list[str]
    changed: dict[str, int]


@dataclass
class Facts:
    unreached: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    near: list[dict] = field(default_factory=list)
    sizes: list[dict] = field(default_factory=list)
    long_functions: list[dict] = field(default_factory=list)
    long_files: list[dict] = field(default_factory=list)
    long_parameters: list[dict] = field(default_factory=list)
    untouched: list[dict] = field(default_factory=list)
    unnamed: list[str] = field(default_factory=list)


# Reading the checkout


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(arguments)} failed in {root}: {result.stderr.strip()}")
    return result.stdout


def glob_pattern(pattern: str) -> re.Pattern[str]:
    """A tracked-path glob as se.toml writes it: `**/` any directories, `*` within one."""
    parts = re.split(r"(\*\*/|\*)", pattern)
    regex = "".join("(?:.*/)?" if part == "**/" else "[^/]*" if part == "*" else re.escape(part)
                    for part in parts)
    return re.compile(regex + r"\Z")


def authored_patterns(root: Path) -> list[str]:
    settings = root / "se.toml"
    if not settings.is_file():
        return DEFAULT_AUTHORED
    with settings.open("rb") as handle:
        return tomllib.load(handle).get("project", {}).get("authored_content", DEFAULT_AUTHORED)


def last_changes(root: Path) -> dict[str, int]:
    """Each path's newest change on HEAD, from one walk of the history."""
    changed: dict[str, int] = {}
    when = 0
    for line in git(root, "log", "--format=%x00%ct", "--name-only", "HEAD").splitlines():
        if line.startswith("\0"):
            when = int(line[1:])
        elif line and line not in changed:
            changed[line] = when
    return changed


def read(root: Path) -> Checkout:
    tracked = [path for path in git(root, "ls-files", "-z").split("\0") if path]
    patterns = [glob_pattern(pattern) for pattern in authored_patterns(root)]

    def text(path: str) -> str:
        return (root / path).read_text(encoding="utf-8", errors="replace")

    present = [path for path in tracked if (root / path).is_file()]
    return Checkout(
        scripts={path: text(path) for path in present
                 if path.startswith("scripts/") and path.count("/") == 1 and path.endswith(".py")},
        tests={path: text(path) for path in present
               if path.startswith("tests/") and path.endswith(".py")},
        authored={path: text(path) for path in present
                  if any(pattern.match(path) for pattern in patterns)},
        tracked=present,
        changed=last_changes(root),
    )


# The facts


@dataclass
class Definition:
    path: str
    name: str
    kind: str  # function, class or method
    owner: str  # the class of a method, "" otherwise
    node: ast.AST
    refs: set[str]
    external_base: bool = False


def names_in(*nodes: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                found.add(child.id)
            elif isinstance(child, ast.Attribute):
                found.add(child.attr)
    return found


def registers(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Whether a decorator registers the definition by name, `@command("sync", ...)`: the
    registry, not a caller, reaches it."""
    return any(isinstance(decorator, ast.Call) and decorator.args
               and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str)
               for decorator in node.decorator_list)


def definitions(path: str, tree: ast.Module) -> tuple[list[Definition], set[str]]:
    """The module's functions, classes and methods with the names each refers to, and the names its
    import-time code refers to."""
    found: list[Definition] = []
    roots: set[str] = set()
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for statement in tree.body:
        if isinstance(statement, functions):
            found.append(Definition(path, statement.name, "function", "", statement, names_in(statement)))
        elif isinstance(statement, ast.ClassDef):
            body = [child for child in statement.body if not isinstance(child, functions)]
            known_bases = all(isinstance(base, ast.Name) and base.id in ("object", "Exception", "ValueError",
                                                                         "RuntimeError")
                              for base in statement.bases) or not statement.bases
            found.append(Definition(path, statement.name, "class", "", statement,
                                    names_in(*statement.bases, *statement.decorator_list, *body),
                                    external_base=not known_bases))
            for child in statement.body:
                if isinstance(child, functions):
                    found.append(Definition(path, child.name, "method", statement.name, child,
                                            names_in(child)))
        else:
            roots |= names_in(statement)
            continue
        if registers(statement):
            roots.add(statement.name)
    return found, roots


def identifiers(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))


def reached_from(every: list[Definition], roots: set[str]) -> set[int]:
    """The definitions the names in roots reach, by name, through what each reached one refers to."""
    by_name: dict[str, list[Definition]] = defaultdict(list)
    for definition in every:
        by_name[definition.name].append(definition)
    reached: set[int] = set()
    pending = list(roots)
    seen_names: set[str] = set()

    def reach(definition: Definition) -> None:
        if id(definition) not in reached:
            reached.add(id(definition))
            pending.extend(definition.refs)
            if definition.kind == "class":
                for method in every:
                    if method.owner == definition.name and method.path == definition.path and (
                            method.name.startswith("__") or definition.external_base):
                        reach(method)

    while pending:
        name = pending.pop()
        if name in seen_names:
            continue
        seen_names.add(name)
        for definition in by_name.get(name, []):
            reach(definition)
    return reached


def unreached(scripts: dict[str, ast.Module], tests: dict[str, str], authored: dict[str, str]
              ) -> list[dict]:
    """The definitions in scripts that no import-time code, command, reached definition or authored
    code span (`name`, a documented interface) refers to by name: what nothing but tests reaches,
    each marked with whether the tests reach it. Names are matched across scripts, so a name
    another script uses reaches every definition of it; the list errs towards missing dead code,
    never towards naming live code."""
    every: list[Definition] = []
    roots: set[str] = set()
    for path, tree in scripts.items():
        found, module_roots = definitions(path, tree)
        every += found
        roots |= module_roots
    for text in authored.values():
        roots |= set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)(?:\(\))?`", text))
    reached = reached_from(every, roots)
    tested = reached_from(every, roots | set().union(*map(identifiers, tests.values())))
    return [{"at": f"{definition.path}:{definition.node.lineno}",
             "what": f"{definition.kind} {definition.owner + '.' if definition.owner else ''}{definition.name}",
             "tests": id(definition) in tested}
            for definition in every if id(definition) not in reached]


def meaningful(line: str) -> str:
    stripped = line.strip()
    return "" if not stripped or stripped.startswith("#") else stripped


def duplicate_blocks(scripts: dict[str, str]) -> list[dict]:
    """Runs of WINDOW or more lines written alike in two places, blank and comment lines aside."""
    lines: dict[str, list[tuple[int, str]]] = {
        path: [(number, text) for number, raw in enumerate(source.splitlines(), 1)
               if (text := meaningful(raw))]
        for path, source in scripts.items()}
    windows: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    for path, kept in lines.items():
        for start in range(len(kept) - WINDOW + 1):
            texts = tuple(text for _, text in kept[start:start + WINDOW])
            if sum(len(text) >= MIN_CHARS for text in texts) >= MEANINGFUL:
                windows[texts].append((path, start))
    pairs: set[tuple[str, int, str, int]] = set()
    for places in windows.values():
        if 2 <= len(places) <= COMMON:
            for index, (path_a, start_a) in enumerate(places):
                for path_b, start_b in places[index + 1:]:
                    if path_a != path_b or start_b - start_a >= WINDOW:
                        pairs.add((path_a, start_a, path_b, start_b))
    found = []
    for path_a, start_a, path_b, start_b in sorted(pairs):
        if (path_a, start_a - 1, path_b, start_b - 1) in pairs:
            continue  # inside a longer run, reported from its start
        length = WINDOW
        while (path_a, start_a + length - WINDOW + 1, path_b, start_b + length - WINDOW + 1) in pairs:
            length += 1

        def span(path: str, start: int) -> str:
            return f"{path}:{lines[path][start][0]}-{lines[path][start + length - 1][0]}"

        found.append({"lines": length, "a": span(path_a, start_a), "b": span(path_b, start_b)})
    return sorted(found, key=lambda block: (-block["lines"], block["a"]))


def functions(path: str, tree: ast.Module):
    """The module's top-level functions and methods, with their qualified names."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    for statement in tree.body:
        if isinstance(statement, kinds):
            yield statement.name, statement
        elif isinstance(statement, ast.ClassDef):
            for child in statement.body:
                if isinstance(child, kinds):
                    yield f"{statement.name}.{child.name}", child


def shape_tokens(source: str) -> list[tuple[int, str]]:
    """The source's tokens by line, names, strings and numbers reduced to their kind."""
    shaped = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.NAME:
                text = token.string if keyword.iskeyword(token.string) else "N"
            elif token.type == tokenize.STRING or token.type in getattr(tokenize, "FSTRING_TYPES", ()):
                text = "S"
            elif token.type == tokenize.NUMBER:
                text = "0"
            elif token.type in (tokenize.OP, tokenize.INDENT, tokenize.DEDENT):
                text = token.string if token.type == tokenize.OP else tokenize.tok_name[token.type]
            else:
                continue
            shaped.append((token.start[0], text))
    except (tokenize.TokenError, SyntaxError):
        return []
    return shaped


def near_duplicates(scripts: dict[str, str], trees: dict[str, ast.Module]) -> list[dict]:
    """Pairs of functions whose shapes (names and literals aside) share NEAR_ALIKE percent of their
    uncommon shingles."""
    shingles: dict[str, set[int]] = {}
    for path, source in scripts.items():
        tokens = shape_tokens(source)
        for name, node in functions(path, trees[path]):
            body = [text for line, text in tokens if node.lineno <= line <= node.end_lineno]
            if len(body) >= MIN_TOKENS:
                shingles[f"{path}:{node.lineno} {name}"] = {
                    hash(tuple(body[start:start + SHINGLE])) for start in range(len(body) - SHINGLE + 1)}
    owners: dict[int, list[str]] = defaultdict(list)
    for place, hashes in shingles.items():
        for value in hashes:
            owners[value].append(place)
    uncommon = {place: {value for value in hashes if len(owners[value]) <= COMMON}
                for place, hashes in shingles.items()}
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for value, places in owners.items():
        if len(places) <= COMMON:
            for index, first in enumerate(places):
                for second in places[index + 1:]:
                    shared[tuple(sorted((first, second)))] += 1
    found = []
    for (first, second), count in shared.items():
        union = len(uncommon[first] | uncommon[second])
        alike = 100 * count // union if union else 0
        if alike >= NEAR_ALIKE:
            found.append({"alike": alike, "a": first, "b": second})
    return sorted(found, key=lambda pair: (-pair["alike"], pair["a"], pair["b"]))


def code_lines(source: str) -> int:
    return sum(1 for line in source.splitlines() if meaningful(line))


def tested_script(test_path: str, source: str, stems: set[str]) -> str:
    """The script a test file tests: the one it imports or runs; of several, the one its name
    starts like."""
    used = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = ast.Module(body=[], type_ignores=[])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            used |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            used.add(node.module)
    used = (used | set(re.findall(r"\b(\w+)\.py\b", source))) & stems
    if not used:
        return ""
    name = Path(test_path).stem.removeprefix("test_")

    def common_prefix(stem: str) -> int:
        return next((index for index, (a, b) in enumerate(zip(stem, name)) if a != b), min(len(stem), len(name)))

    return max(sorted(used), key=common_prefix)


def sizes(scripts: dict[str, str], tests: dict[str, str]) -> list[dict]:
    stems = {Path(path).stem: path for path in scripts}
    test_lines: dict[str, int] = defaultdict(int)
    for path, source in tests.items():
        test_lines[stems.get(tested_script(path, source, set(stems)), "")] += code_lines(source)
    rows = [{"script": path, "lines": code_lines(source), "test_lines": test_lines.get(path, 0)}
            for path, source in scripts.items()]
    if test_lines.get(""):
        rows.append({"script": "(no script)", "lines": 0, "test_lines": test_lines[""]})
    return sorted(rows, key=lambda row: (-row["lines"], -row["test_lines"], row["script"]))


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    arguments = node.args
    named = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)]
    if named and named[0] in ("self", "cls"):
        named = named[1:]
    return len(named) + bool(arguments.vararg) + bool(arguments.kwarg)


def script_commands(path: str, tree: ast.Module) -> list[str]:
    """The commands a script offers, each as its words after the script's name: argparse
    `add_parser("name")`, and the registry's `command("name", ..., parent=GROUP)` under
    `GROUP = command_group("name", ...)`."""
    groups: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "command_group"
                and node.value.args and isinstance(node.value.args[0], ast.Constant)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    groups[target.id] = str(node.value.args[0].value)
    commands = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if callee not in ("add_parser", "command"):
            continue
        words = [node.args[0].value]
        parent = next((keyword_.value for keyword_ in node.keywords if keyword_.arg == "parent"), None)
        if isinstance(parent, ast.Name) and parent.id in groups:
            words.insert(0, groups[parent.id])
        commands.append(" ".join(words))
    return sorted(set(commands))


def unnamed_commands(scripts: dict[str, str], trees: dict[str, ast.Module], authored: dict[str, str]
                     ) -> list[str]:
    """Each script command no authored line names: a line that names `<script>.py` with the
    command's words after it, in order. A script without commands is one command, its name."""
    lines = [line for text in authored.values() for line in text.splitlines() if ".py" in line]
    missing = []
    for path in sorted(scripts):
        script = Path(path).name
        commands = script_commands(path, trees[path])
        for command in commands or [""]:
            words = [re.escape(script), *(rf"\b{re.escape(word)}\b" for word in command.split())]
            pattern = re.compile(r"(?<![\w-])" + r".*?".join(words))
            if not any(pattern.search(line) for line in lines):
                missing.append(f"{script} {command}".strip())
    return missing


def find(checkout: Checkout) -> Facts:
    trees = {}
    for path, source in checkout.scripts.items():
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError:
            trees[path] = ast.Module(body=[], type_ignores=[])
    measured = [(f"{path}:{node.lineno}", name, node) for path, tree in trees.items()
                for name, node in functions(path, tree)]
    longest = sorted(measured, key=lambda item: (-(item[2].end_lineno - item[2].lineno + 1), item[0]))
    widest = sorted(measured, key=lambda item: (-parameters(item[2]), item[0]))
    files = sorted(checkout.scripts.items(), key=lambda item: (-len(item[1].splitlines()), item[0]))
    untouched = sorted((path for path in checkout.tracked if path in checkout.changed),
                       key=lambda path: (checkout.changed[path], path))
    return Facts(
        unreached=unreached(trees, checkout.tests, checkout.authored),
        duplicates=duplicate_blocks(checkout.scripts),
        near=near_duplicates(checkout.scripts, trees),
        sizes=sizes(checkout.scripts, checkout.tests),
        long_functions=[{"at": at, "what": name, "lines": node.end_lineno - node.lineno + 1}
                        for at, name, node in longest[:TOP]],
        long_files=[{"at": path, "lines": len(source.splitlines())} for path, source in files[:TOP]],
        long_parameters=[{"at": at, "what": name, "parameters": parameters(node)}
                         for at, name, node in widest[:TOP]],
        untouched=[{"at": path, "last": time.strftime("%Y-%m-%d", time.gmtime(checkout.changed[path]))}
                   for path in untouched[:TOP]],
        unnamed=unnamed_commands(checkout.scripts, trees, checkout.authored),
    )


# The report


def render(facts: Facts) -> str:
    out = ["# Overhaul facts", ""]

    def section(title: str, rows: list[str], empty: str = "none") -> None:
        out.extend([f"## {title}", ""])
        out.extend(f"- {row}" for row in rows) if rows else out.append(empty)
        out.append("")

    section("Reached by nothing but tests",
            [f"{item['at']} {item['what']}{' (tests only)' if item['tests'] else ' (not even tests)'}"
             for item in facts.unreached])
    section(f"Duplicate blocks ({WINDOW} lines or more)",
            [f"{block['lines']} lines: {block['a']} and {block['b']}" for block in facts.duplicates])
    section(f"Near-duplicate functions ({NEAR_ALIKE}% alike or more)",
            [f"{pair['alike']}%: {pair['a']} and {pair['b']}" for pair in facts.near])
    total, tested = sum(row["lines"] for row in facts.sizes), sum(row["test_lines"] for row in facts.sizes)
    section(f"Lines of code and of tests ({total} and {tested})",
            [f"{row['script']}: {row['lines']} code, {row['test_lines']} tests" for row in facts.sizes])
    section("Longest functions", [f"{item['at']} {item['what']}: {item['lines']} lines"
                                  for item in facts.long_functions])
    section("Longest files", [f"{item['at']}: {item['lines']} lines" for item in facts.long_files])
    section("Longest parameter lists", [f"{item['at']} {item['what']}: {item['parameters']} parameters"
                                        for item in facts.long_parameters])
    section("Untouched longest", [f"{item['at']}: {item['last']}" for item in facts.untouched])
    section("Commands no authored text names", facts.unnamed)
    return "\n".join(out).rstrip() + "\n"


# The overhaul issue: new, read, file


def sibling(name: str):
    """The script `<name>.py` beside this one, imported when a command needs it: `facts` imports
    only se_components, for its route, which uses the standard library alone."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)
    return importlib.import_module(name)


SE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = SE_ROOT / ".github" / "ISSUE_TEMPLATE" / "overhaul.md"
BOOK = Path("src") / "skills" / "work-model" / "references" / "rules.md"
OVERHAUL_TITLE = "docs/overhaul-"
OVERHAUL_LABEL = "discovery"
# An overhaul is due once this many retros closed since the last one (se.toml [overhaul] due_after).
DUE_AFTER = 3
BLOCK_MARKER = "<!-- se:overhaul-yaml -->"
REPORT_MARKER = "<!-- se:overhaul-report -->"
JUDGE_BEGIN, JUDGE_END = "<!-- se:overhaul-judge -->", "<!-- se:overhaul-judge:end -->"
BLOCK_VERSION = 1
# A work issue names each overhaul finding it takes as `overhaul #<n> finding <k>`.
FINDING_REFERENCE = re.compile(r"\boverhaul #(\d+) finding (\d+)\b", re.IGNORECASE)
# What checks a rule, read from its live implementations.
CHECKED_BY = ("test", "check", "judgment")
TESTED = re.compile(r"\btests/|\btest_\w+|\bthe suite\b", re.IGNORECASE)
SCRIPT_LINK = re.compile(r"\]\([^)]*scripts/[^)]*\)")
JUDGMENT = ("verdicts", "looked_at", "findings", "went_well")
VERDICT_FIELDS = ("rule", "strays", "how")
STRAYS = ("none", "slightly", "far")
# The parts of se the judge looks at besides the rules, each answered ("nothing to change" is an
# answer): the outside world, the consistency of the whole, the rule book itself, the retros'
# effect, speed, what to mechanize and what to remove.
LOOKED_AT = ("outside", "consistency", "rules", "retro", "speed", "mechanize", "removal")
FINDING_FIELDS = ("title", "body", "rule", "place", "controversial", "why", "sources")
# A finding's `rule` for a rule the book lacks: a rule change.
NEW_RULE = "new"
WORK, DECISION = "work", "decision"
RULE_CHANGE = "it changes a rule"


def template_body() -> tuple[str, str]:
    """The overhaul issue's title pattern and body, from its template without the front matter."""
    text = sibling("work_tickets").read_file(TEMPLATE, "the overhaul template")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{TEMPLATE} has no front matter")
    title = re.search(r'^title:\s*"?([^"\n]+)"?\s*$', match[1], re.MULTILINE)
    return (title[1] if title else f"{OVERHAUL_TITLE}<yyyymmdd>"), text[match.end():]


def run_new(args: argparse.Namespace) -> int:
    work_tickets = sibling("work_tickets")
    root = work_tickets.worktree_root(args.worktree)
    pattern, body = template_body()
    title = pattern.replace("<yyyymmdd>", work_tickets.today_stamp())
    with work_tickets.tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / "overhaul.md"
        file.write_text(body, encoding="utf-8")
        print(work_tickets.file_work_issue(root, title, file, [], args.repo, (OVERHAUL_LABEL,)))
    return 0


def checked_by(rule) -> list[str]:
    """What checks `rule`, from its live implementations, each naming one kind or more: a test
    (it names the tests or the suite), judgment ("by judgment"), a check (it links a script, or
    names neither of the others)."""
    rule_book = sibling("rule_book")
    found = set()
    for item in rule.implementations:
        if rule_book.FROZEN.match(item):
            continue
        kinds = {kind for kind, pattern in (("test", TESTED), ("judgment", rule_book.JUDGMENT))
                 if pattern.search(item)}
        found |= kinds | ({"check"} if not kinds or SCRIPT_LINK.search(item) else set())
    return [kind for kind in CHECKED_BY if kind in found]


def book_rules(root: Path) -> list:
    """The live rules of the checkout's rule book, else se's."""
    rule_book = sibling("rule_book")
    path = root / BOOK if (root / BOOK).is_file() else rule_book.BOOK
    rules, _, _ = rule_book.parse(sibling("work_tickets").read_file(path, "the rule book"))
    return [rule for rule in rules if rule.retired is None]


def is_overhaul(issue) -> bool:
    return issue.title.startswith(OVERHAUL_TITLE)


def due_after(root: Path) -> int:
    """`[overhaul] due_after` in se.toml: how many closed retros make an overhaul due; built in
    DUE_AFTER."""
    return sibling("retro").due_after(root, "overhaul", DUE_AFTER)


def retros_since_overhaul(door) -> int | None:
    """How many retros closed since the last overhaul, read through `door`, counted as retro.py
    counts the work landed since the last retro: the window starts at the last closed overhaul's
    close, else at the oldest open overhaul's creation, else it is the whole history, and a retro
    closed as a duplicate or as not planned does not count. None where the door is still missing
    answers."""
    retro = sibling("retro")
    closed = [retro.issue_of(item) for item in door.closed_issues()]
    if door.missing:
        return None
    for issue in closed:
        if (is_overhaul(issue) or retro.is_retro(issue)) and not issue.closed_at:
            read = retro.issue_of(door.issue(issue.number))
            issue.closed_at, issue.state_reason = read.closed_at, read.state_reason
    if door.missing:
        return None
    last = max((issue for issue in closed if is_overhaul(issue) and retro.when(issue.closed_at)),
               key=lambda issue: retro.when(issue.closed_at), default=None)
    if last is not None:
        since = retro.when(last.closed_at)
    else:
        opened = [retro.issue_of(item) for item in door.open_issues()]
        if door.missing:
            return None
        oldest = min((issue for issue in opened if is_overhaul(issue) and retro.when(issue.created_at)),
                     key=lambda issue: retro.when(issue.created_at), default=None)
        since = retro.when(oldest.created_at) if oldest else None
    return sum(1 for issue in closed
               if retro.is_retro(issue) and retro.when(issue.closed_at)
               and (since is None or retro.when(issue.closed_at) > since)
               and not retro.is_duplicate(issue) and issue.state_reason != "not_planned")


def door_for(retro, work_tickets, args: argparse.Namespace, root: Path):
    """The read door: the answer files where given, else gh, else the plan's placeholders."""
    tracker = work_tickets.resolve_repo(root, args.repo)

    if args.answers is not None:
        return retro.FileDoor(args.answers, tracker, tracker)
    if work_tickets.hand_off():
        return retro.FileDoor(Path("<dir>"), tracker, tracker)
    return retro.GhDoor(root, tracker, tracker)


def last_block(texts: list[str], marker: str, reader) -> dict | None:
    """The last block under `marker` among `texts`, read by `reader`."""
    blocks = [reader(text) for text in texts if marker in text]
    return blocks[-1] if blocks else None


def retro_row(issue, block: dict | None) -> dict:
    """One retro of the window as the block of the retro doc its report links names it."""
    if block is None:
        return {"retro": issue.number, "closed_at": issue.closed_at, "block": False}
    findings = [item for item in block.get("findings") or [] if isinstance(item, dict)]
    earlier = [item for item in ((block.get("previous") or {}).get("findings") or [])
               if isinstance(item, dict)]
    too_early = sibling("retro").TOO_EARLY
    scored = [item for item in earlier if item.get("state") != too_early]
    return {
        "retro": issue.number, "closed_at": issue.closed_at, "block": True,
        "sizes": block.get("sizes") or {},
        "broken": [str(check.get("name")) for check in block.get("rule_checks") or []
                   if isinstance(check, dict) and not check.get("kept", True)],
        "findings": {WORK: sum(item.get("kind") == WORK for item in findings),
                     DECISION: sum(item.get("kind") == DECISION for item in findings)},
        "classes": sorted({str(item.get("name")) for item in block.get("classes") or []
                           if isinstance(item, dict) and item.get("name")}),
        "previous": {"scored": len(scored),
                     "closed": sum(item.get("state") == "closed" for item in scored),
                     "recurred": sum(bool(item.get("recurred")) for item in scored),
                     "too_early": len(earlier) - len(scored)}}


def scored_findings(previous: dict | None, overhaul: int, closed: list, opened: list) -> list[dict]:
    """Each finding of the previous overhaul's block with the issues that name it
    (`overhaul #<overhaul> finding <k>`) and their state: closed where one closed as completed,
    too early to score where one is still open (it had no time to land, so it is no failure), else
    the reason they closed with, else none."""
    found: list[dict] = []
    for index, finding in enumerate((previous or {}).get("findings") or [], 1):
        if not isinstance(finding, dict):
            continue
        number = int(finding.get("finding") or index)

        def names(issue) -> bool:
            return any(int(match[1]) == overhaul and int(match[2]) == number
                       for match in FINDING_REFERENCE.finditer(issue.body))

        shut = [issue for issue in closed if names(issue)]
        still = [issue for issue in opened if names(issue)]
        reasons = [issue.state_reason or "completed" for issue in shut]
        state = ("closed" if "completed" in reasons else sibling("retro").TOO_EARLY if still
                 else reasons[0] if reasons else "none")
        found.append({"finding": number, "title": str(finding.get("title") or ""),
                      "rule": str(finding.get("rule") or ""), "kind": finding.get("kind"),
                      "issues": sorted(issue.number for issue in shut + still), "state": state})
    return found


def fact_counts(facts: Facts) -> dict:
    """The facts' sizes, which the next overhaul compares."""
    return {"unreached": len(facts.unreached), "duplicates": len(facts.duplicates),
            "near": len(facts.near), "lines": sum(row["lines"] for row in facts.sizes),
            "test_lines": sum(row["test_lines"] for row in facts.sizes),
            "unnamed": len(facts.unnamed)}


@dataclass
class Gathered:
    number: int
    since: str | None
    since_overhaul: int | None
    until: str
    rules: list[dict]
    retros: list[dict]
    previous: dict | None
    facts: Facts

    def data(self) -> dict:
        return {"version": BLOCK_VERSION, "overhaul": self.number, "since": self.since,
                "since_overhaul": self.since_overhaul, "until": self.until,
                "rules": [{key: rule[key] for key in ("id", "name", "checked_by")}
                          for rule in self.rules],
                "retros": self.retros, "previous": self.previous,
                "facts": fact_counts(self.facts),
                "verdicts": [], "looked_at": {part: "" for part in LOOKED_AT},
                "findings": [], "went_well": []}


def gather(number: int, door, rules: list, facts: Facts, now: datetime,
           show) -> Gathered | None:
    """Overhaul `number`'s draft data, read through `door`, each retro's block from the retro doc
    its report links, read with `show(sha, path)` (retro.posted_block); None while the door is
    still missing answers (`door.missing`)."""
    retro = sibling("retro")
    closed = [retro.issue_of(item) for item in door.closed_issues()]
    opened = [retro.issue_of(item) for item in door.open_issues()]
    if door.missing:
        return None
    for issue in closed:
        if (is_overhaul(issue) or retro.is_retro(issue)) and not issue.closed_at:
            read = retro.issue_of(door.issue(issue.number))
            issue.closed_at, issue.state_reason = read.closed_at, read.state_reason
            issue.body = issue.body or read.body
    if door.missing:
        return None
    overhauls = [issue for issue in closed if is_overhaul(issue) and issue.number != number
                 and retro.when(issue.closed_at)]
    last = max(overhauls, key=lambda issue: retro.when(issue.closed_at), default=None)
    since = retro.when(last.closed_at) if last else None
    window = sorted((issue for issue in closed if retro.is_retro(issue)
                     and retro.when(issue.closed_at)
                     and (since is None or retro.when(issue.closed_at) > since)),
                    key=lambda issue: retro.when(issue.closed_at))

    def texts(issue) -> list[str]:
        return [issue.body, *(str(item.get("body") or "") for item in door.comments(issue.number))]

    posted = {issue.number: texts(issue) for issue in window}
    previous_block = last_block(texts(last), BLOCK_MARKER, read_block) if last else None
    if door.missing:
        return None
    rows = [retro_row(issue, retro.posted_block(posted[issue.number], issue.number, show))
            for issue in window]
    previous = None
    if last is not None:
        previous = {"overhaul": last.number, "found": previous_block is not None,
                    "facts": (previous_block or {}).get("facts"),
                    "findings": scored_findings(previous_block, last.number, closed, opened)}
    return Gathered(
        number, last.closed_at if last else None, last.number if last else None,
        now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        [{"id": rule.id, "name": rule.name, "statement": " ".join(rule.statement),
          "checked_by": checked_by(rule),
          "implementations": [item for item in rule.implementations
                              if not sibling("rule_book").FROZEN.match(item)]}
         for rule in rules],
        rows, previous, facts)


def read_block(text: str) -> dict | None:
    """The data of the last block under BLOCK_MARKER in `text`; None where it has none."""
    return sibling("retro").read_block(text, BLOCK_MARKER)


def draft(found: Gathered) -> str:
    """The draft as the judge reads it, ending in the block `read_block` parses."""
    review = sibling("review")
    lines = [f"# Overhaul draft for #{found.number}", ""]
    if found.since:
        lines.append(f"Since overhaul #{found.since_overhaul} closed, {found.since}, up to "
                     f"{found.until}.")
    else:
        lines.append(f"The whole history up to {found.until}; no overhaul issue has closed.")
    kinds = Counter(kind for rule in found.rules for kind in rule["checked_by"])
    lines += ["", f"## The rule book ({len(found.rules)} rules)", "",
              "What checks each rule, from its live implementations: "
              + ", ".join(f"{kinds[kind]} by a {kind}" if kind != "judgment"
                          else f"{kinds[kind]} by judgment" for kind in CHECKED_BY) + "."]
    for rule in found.rules:
        checks = ", ".join(rule["checked_by"]) or "nothing"
        lines += ["", f"- **{rule['id']} {rule['name']}** (checked by: {checks}): "
                      f"{rule['statement']}"]
        lines += [f"  - {item}" for item in rule["implementations"]]
    lines += ["", "## The retros since the last overhaul", ""]
    if found.retros:
        lines += ["| retro | closed | landed | escalated | broken checks | findings (work, "
                  "decision) | previous findings closed, recurred, too early |", "|---|---|---|---|---|---|---|"]
        for row in found.retros:
            if not row["block"]:
                lines.append(f"| #{row['retro']} | no report block found | | | | | |")
                continue
            sizes, previous = row["sizes"], row["previous"]
            lines.append(
                f"| #{row['retro']} | {sizes.get('closed', '')} | {sizes.get('landed', '')} | "
                f"{sizes.get('escalated', '')} | {', '.join(row['broken']) or 'none'} | "
                f"{row['findings'][WORK]}, {row['findings'][DECISION]} | "
                f"{previous['closed']} of {previous['scored']}, {previous['recurred']}, "
                f"{previous['too_early']} |")
        named = Counter(name for row in found.retros if row["block"] for name in row["classes"])
        repeated = sorted(name for name, count in named.items() if count > 1)
        lines += ["", "Finding classes more than one retro named: "
                  + (", ".join(repeated) if repeated else "none") + "."]
    else:
        lines.append("None.")
    if found.previous:
        number = found.previous["overhaul"]
        lines += ["", f"## The findings of overhaul #{number}", ""]
        if not found.previous["found"]:
            lines.append(f"Overhaul #{number} carries no {BLOCK_MARKER} block.")
        elif found.previous["findings"]:
            lines += ["| finding | rule | kind | issues | state |", "|---|---|---|---|---|"]
            for item in found.previous["findings"]:
                issues = ", ".join(f"#{issue}" for issue in item["issues"]) or "none"
                lines.append(f"| {item['finding']}. {item['title']} | {item['rule']} | "
                             f"{item['kind'] or ''} | {issues} | {item['state']} |")
        else:
            lines.append("None.")
    facts = render(found.facts).split("\n", 1)[1]
    lines += ["", "## Pruning facts", ""]
    counted = (found.previous or {}).get("facts")
    if counted:
        now = fact_counts(found.facts)
        lines += [f"Against overhaul #{found.previous['overhaul']}: " + ", ".join(
            f"{name} {counted.get(name, '?')} then, {value} now" for name, value in now.items())
            + ".", ""]
    lines.append(review.demoted(facts, 1).strip())
    block = json.dumps(found.data(), indent=2, ensure_ascii=False)
    lines += ["", JUDGE_BEGIN, "## Judgment", "",
              "The judge reads se itself (the README, the agents and skills, the rule book, the "
              "scripts), then fills the block below and runs "
              f"`overhaul.py file {found.number} --draft <this file>`: `verdicts`, one per rule "
              f"(`rule`, `strays`: {', '.join(STRAYS)}, `how`); `looked_at`, every part answered "
              f"({', '.join(LOOKED_AT)}; \"nothing to change\" is an answer); `findings`, each "
              f"with `title` (five words or more, the fix), `body`, `rule` (a rule's id, or "
              f"`{NEW_RULE}` for one the book lacks), `place` (the file it changes), "
              "`controversial` with its `why`, and optionally `sources`; `went_well`. A finding "
              "that changes a rule (its place is the rule book, or its rule is "
              f"`{NEW_RULE}`) is always a decision for the person. This part is not posted.",
              JUDGE_END, "", BLOCK_MARKER, review.fenced(block, "yaml")]
    return "\n".join(lines) + "\n"


def changes_rule(finding: dict) -> bool:
    place = str(finding.get("place") or "").strip().lstrip("./")
    return place == BOOK.as_posix() or str(finding.get("rule") or "").strip() == NEW_RULE


def judgment_problems(block: dict) -> list[str]:
    """What keeps the judgment in `block` from being complete; none where it is."""
    words = sibling("review").words
    problems: list[str] = []
    if not all(isinstance(block.get(name), list) for name in ("verdicts", "findings", "went_well")):
        return [f"`{name}` is not a list" for name in ("verdicts", "findings", "went_well")
                if not isinstance(block.get(name), list)]
    rules = [str(rule.get("id")) for rule in block.get("rules") or [] if isinstance(rule, dict)]
    judged: set[str] = set()
    for index, given in enumerate(block["verdicts"], 1):
        if not isinstance(given, dict):
            problems.append(f"verdict {index} is not an object with {', '.join(VERDICT_FIELDS)}")
            continue
        rule = words(given.get("rule"))
        name = f"the verdict on {rule}" if rule else f"verdict {index}"
        extra = sorted(set(given) - set(VERDICT_FIELDS))
        if extra:
            problems.append(f"{name} has the unknown field {extra[0]}")
        if rule not in rules:
            problems.append(f"{name} names no rule of the book" if rule else f"{name} has no rule")
        elif rule in judged:
            problems.append(f"{rule} has two verdicts")
        judged.add(rule)
        if given.get("strays") not in STRAYS:
            problems.append(f"{name}: strays is one of {', '.join(STRAYS)}")
        if not words(given.get("how")):
            problems.append(f"{name} has no how")
    problems += [f"{rule} has no verdict" for rule in rules if rule not in judged]
    looked = block.get("looked_at")
    if not isinstance(looked, dict):
        problems.append(f"`looked_at` is not an object with {', '.join(LOOKED_AT)}")
    else:
        problems += [f"`looked_at` has the unknown part {part}"
                     for part in sorted(set(looked) - set(LOOKED_AT))]
        problems += [f"`looked_at.{part}` is empty (\"nothing to change\" is an answer)"
                     for part in LOOKED_AT if not words(looked.get(part))]
    for index, given in enumerate(block["findings"], 1):
        if not isinstance(given, dict):
            problems.append(f"finding {index} is not an object with {', '.join(FINDING_FIELDS)}")
            continue
        name, found = sibling("retro").finding_basics(given, index, FINDING_FIELDS)
        problems += found
        rule = words(given.get("rule"))
        if not rule:
            problems.append(f"{name} has no rule: a rule's id, or {NEW_RULE}")
        elif rule != NEW_RULE and rule not in rules:
            problems.append(f'{name} names the rule "{rule}", which is not in the book')
        if not words(given.get("place")):
            problems.append(f"{name} has no place: the file it changes")
        controversial = given.get("controversial", False)
        if not isinstance(controversial, bool):
            problems.append(f"{name}: controversial is true or false")
        elif controversial and not words(given.get("why")):
            problems.append(f"{name} is controversial without a why")
        sources = given.get("sources", [])
        if not isinstance(sources, list) or not all(words(item) for item in sources):
            problems.append(f"{name}: sources is a list of the places cited")
    if not [entry for entry in block["went_well"] if words(entry)]:
        problems.append("`went_well` is empty: record what went well")
    return problems


def judged(text: str, number: int) -> dict:
    """The block of the draft `text`, its judgment checked and each finding given its kind; every
    refusal is raised before anything is written."""
    work_tickets = sibling("work_tickets")
    block = read_block(text)
    if block is None:
        raise work_tickets.QueueError(f"The draft has no {BLOCK_MARKER} block: write it with "
                                      f"overhaul.py read {number} --out FILE")
    if block.get("overhaul") != number:
        raise work_tickets.QueueError(f"The draft is overhaul #{block.get('overhaul')}'s, not "
                                      f"#{number}'s")
    problems = judgment_problems(block)
    if problems:
        raise work_tickets.QueueError(f"The judgment of overhaul #{number} is not complete, so "
                                      "nothing was written: " + "; ".join(problems))
    findings = []
    for index, given in enumerate(block["findings"], 1):
        rule_change = changes_rule(given)
        controversial = given.get("controversial") is True or rule_change
        why = sibling("review").words(given.get("why")) or RULE_CHANGE
        findings.append({"finding": index, **{key: given[key] for key in FINDING_FIELDS
                                              if key in given},
                         "controversial": controversial, "rule_change": rule_change,
                         **({"why": why} if controversial else {}),
                         "kind": DECISION if controversial else WORK})
    return {**block, "findings": findings}


def report(text: str, block: dict, number: int) -> str:
    """The overhaul's report, its closing comment: the verdicts, what was looked at, each finding
    with its kind, what went well, what follows, the facts, then the block the next overhaul
    reads."""
    review = sibling("review")
    one_line = sibling("retro").one_line
    lines = [REPORT_MARKER, f"## Overhaul #{number}: the report", "", "### Verdicts", "",
             "| rule | strays | how |", "|---|---|---|"]
    names = {rule["id"]: rule.get("name", "") for rule in block.get("rules") or []}
    order = {rule: index for index, rule in enumerate(names)}
    for verdict in sorted(block["verdicts"], key=lambda item: order.get(item["rule"].strip(), 0)):
        rule = verdict["rule"].strip()
        lines.append(f"| {rule} {names.get(rule, '')} | {verdict['strays']} | "
                     f"{one_line(verdict['how']).replace('|', '/')} |")
    lines += ["", "### What was looked at", ""]
    lines += [f"- **{part}**: {one_line(block['looked_at'][part])}" for part in LOOKED_AT]
    lines += ["", "### Findings", ""]
    if not block["findings"]:
        lines.append("None.")
    for item in block["findings"]:
        kind = (f"{DECISION}, for the owner's decision list: {item['why'].strip()}"
                if item["kind"] == DECISION else f"{WORK}, for SE to bundle")
        change = "; a rule change" if item["rule_change"] else ""
        lines += [f"- **{item['finding']}. {item['title'].strip()}** ({kind}{change}; rule "
                  f"{item['rule'].strip()}; place `{item['place'].strip()}`)",
                  "  " + "\n  ".join(item["body"].strip().splitlines())]
        lines += [f"  - Source: {source.strip()}" for source in item.get("sources") or []]
    lines += ["", "### What went well", ""]
    lines += [f"- {entry.strip()}" for entry in block["went_well"] if review.words(entry)]
    work = [item["finding"] for item in block["findings"] if item["kind"] == WORK]
    decisions = [item["finding"] for item in block["findings"] if item["kind"] == DECISION]
    lines += ["", "### What follows", "",
              f"This overhaul filed no issue. SE bundles the {WORK} findings "
              f"({', '.join(map(str, work)) or 'none'}) into as few work issues as the work "
              f"needs, each naming `overhaul #{number} finding <k>` for every finding it takes, "
              f"so the next overhaul scores it; the {DECISION} findings "
              f"({', '.join(map(str, decisions)) or 'none'}), every rule change among them, go "
              "on the owner's decision list.",
              "", "### The facts", "", sibling("retro").facts_of(text, BLOCK_MARKER, (JUDGE_BEGIN, JUDGE_END)), "", BLOCK_MARKER,
              review.fenced(json.dumps(block, indent=2, ensure_ascii=False), "yaml")]
    return "\n".join(lines) + "\n"


def run_file(args: argparse.Namespace) -> int:
    work_tickets, retro = sibling("work_tickets"), sibling("retro")
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    text = work_tickets.read_file(args.draft, "the overhaul draft")
    block = judged(text, args.overhaul)
    steps = retro.file_steps(tracker, args.overhaul, [report(text, block, args.overhaul)],
                             "overhaul")
    if work_tickets.hand_off():
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools:")
        print(steps.text())
    else:
        work_tickets.run_plan(steps, work_tickets.tracker_actions(root, tracker))
        print(f"Posted the report of overhaul #{args.overhaul} as its closing comment and closed it")
    findings = block["findings"]
    kinds = [item["kind"] for item in findings]
    print(f"Overhaul #{args.overhaul}: {kinds.count(WORK)} {WORK} and {kinds.count(DECISION)} "
          f"{DECISION} finding(s), {sum(item['rule_change'] for item in findings)} of them rule "
          f"changes; no issue filed: SE bundles the {WORK} findings into work issues and puts the "
          f"{DECISION} findings on the owner's decision list")
    return 0


def run_read(args: argparse.Namespace) -> int:
    work_tickets, retro = sibling("work_tickets"), sibling("retro")
    root = work_tickets.worktree_root(args.worktree)
    door = door_for(retro, work_tickets, args, root)
    found = gather(args.overhaul, door, book_rules(root), find(read(root)),
                   datetime.now(timezone.utc), retro.git_show(root))
    if found is None:
        directory = args.answers or Path("<dir>")
        then = (f"overhaul.py read {args.overhaul} --answers {directory}"
                f"{f' --out {args.out}' if args.out else ''}{' --json' if args.json else ''}"
                f"{f' --repo {args.repo}' if args.repo else ''} --worktree {root}")
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools "
              f"and saves their answers into {directory}:")
        print(work_tickets.Plan(f"the draft of overhaul #{args.overhaul}", tuple(door.missing),
                                then).text())
        return 0
    output = (json.dumps(found.data(), indent=2, ensure_ascii=False) + "\n" if args.json
              else draft(found))
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"Wrote the overhaul draft of #{args.overhaul} to {args.out}: {len(found.rules)} "
              f"rules, {len(found.retros)} retro(s) since the last overhaul")
    else:
        sys.stdout.write(output)
    return 0


def run_facts(args: argparse.Namespace) -> int:
    try:
        facts = find(read(args.repo.resolve()))
    except (OSError, ValueError) as error:
        print(f"error: overhaul.py facts: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(facts), indent=2) if args.json else render(facts),
          end="" if not args.json else "\n")
    return 0


#: overhaul.py's commands as one kern component (README "Commands as components"); each command's
#: usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "overhaul", "Overhaul",
    "An overhaul: new files its issue, read writes its draft, file checks the judged draft and "
    "closes the issue with its report, and facts lists a checkout's pruning facts.",
    ("new", "read", "file", "facts")),)
#: The commands that go through kern where it runs (se_components.routed): facts, which only reads
#: the checkout while a person waits; new, read and file write or read GitHub at length.
INTERACTIVE_COMMANDS = frozenset({"facts"})


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="overhaul.py", description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)

    def github(command: argparse.ArgumentParser) -> None:
        command.add_argument("--worktree", default=".",
                             help="the checkout of the repository (default: .)")
        command.add_argument("--repo", help="[HOST/]OWNER/REPO of the issues (default: the "
                                            "tracker or origin remote)")

    new_command = commands.add_parser(
        "new", help="file the overhaul issue through work_tickets.py file",
        description=f"File the overhaul issue, {OVERHAUL_TITLE}<yyyymmdd> labelled "
                    f"{OVERHAUL_LABEL}, with the body of .github/ISSUE_TEMPLATE/overhaul.md, "
                    "through work_tickets.py file: once, an open overhaul answering a second.")
    github(new_command)
    new_command.set_defaults(run=run_new)
    read_command = commands.add_parser(
        "read", help="write an overhaul's draft",
        description="Write the draft: every rule with what checks it, the retros since the last "
                    "overhaul, the previous overhaul's findings with their issues' state, and the "
                    f"pruning facts, ending in a {BLOCK_MARKER} block for the judgment.")
    read_command.add_argument("overhaul", type=int, help="the overhaul issue's number")
    read_command.add_argument("--out", type=Path, metavar="FILE",
                              help="write the draft to FILE (default: print it)")
    read_command.add_argument("--json", action="store_true",
                              help="the block's data as JSON instead of the draft")
    read_command.add_argument("--answers", type=Path, metavar="DIR",
                              help="without gh: the directory the session saves the plan's "
                                   "answers into")
    github(read_command)
    read_command.set_defaults(run=run_read)
    file_command = commands.add_parser(
        "file", help="check a judged overhaul draft and close the overhaul issue with its report",
        description="Check the judgment in the draft's block, refusing an incomplete one and "
                    "writing nothing; post the report (the verdicts, what was looked at, each "
                    f"finding with its kind, {WORK} or {DECISION}, a rule change always a "
                    f"{DECISION}, then the facts and the block) as the overhaul issue's closing "
                    "comment and close it. It files no issue: SE reads the report and files the "
                    "work.")
    file_command.add_argument("overhaul", type=int, help="the overhaul issue's number")
    file_command.add_argument("--draft", type=Path, required=True, metavar="FILE",
                              help="the draft overhaul.py read wrote, its block judged")
    github(file_command)
    file_command.set_defaults(run=run_file)
    facts_command = commands.add_parser("facts", help="list the pruning facts of a checkout")
    facts_command.add_argument("--repo", type=Path, default=Path("."), help="the checkout (default: .)")
    facts_command.add_argument("--json", action="store_true", help="print the facts as JSON")
    facts_command.set_defaults(run=run_facts)
    return top


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    words = [args.command]
    routed = sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        args.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    try:
        return args.run(args)
    except sibling("work_tickets").QueueError as error:
        print(f"overhaul.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
