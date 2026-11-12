#!/usr/bin/env python3
"""An overhaul's pruning facts, read from a checkout (README "Work commands").

`overhaul.py facts [--json] [--repo PATH]` lists what an overhaul's pruning judgment starts from:
the functions and classes in `scripts/` that nothing but tests reaches, duplicate and
near-duplicate blocks, the lines of code and of tests per script, the longest functions, files and
parameter lists, the files untouched longest, and each script command that no authored text names.
It only reads, uses the standard library alone and judges nothing: the facts are candidates, the
overhaul decides."""

from __future__ import annotations

import argparse
import ast
import io
import json
import keyword
import re
import subprocess
import sys
import time
import tokenize
import tomllib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    facts_command = commands.add_parser("facts", help="list the pruning facts of a checkout")
    facts_command.add_argument("--repo", type=Path, default=Path("."), help="the checkout (default: .)")
    facts_command.add_argument("--json", action="store_true", help="print the facts as JSON")
    args = parser.parse_args(argv)
    try:
        facts = find(read(args.repo.resolve()))
    except (OSError, ValueError) as error:
        print(f"error: overhaul.py facts: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(facts), indent=2) if args.json else render(facts), end="" if not args.json else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
