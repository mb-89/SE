#!/usr/bin/env python3
"""Every reach outside a declared door, counted per file against a baseline that may only shrink.

Each door declares in a data file (`scripts/doors/<door>.toml`) what it guards: `door` (its name),
`files` (its own files), `contract_tests`, the reach patterns `commands`, `imports`, `calls` and
`literals`, and a `[baseline]` table of `"path" = { count = n, reason = "..." }` (rule book des-004,
one door per outside thing).

`uv run python scripts/door_report.py [--root DIR] [--doors DIR]` reads the declarations (default:
SE's `scripts/doors`) and scans the `.py` and `.go` files under scripts, tests, components and kern
of the root (default: SE's checkout), skipping .venv, testdata and __pycache__: the ground hygiene's
git-door check scans. A door's own `files` are not scanned for that door; its contract tests are
scanned like any other file.

For each door it prints each reach outside it as `path:line: kind word`, then the ratchet's new and
gone in report mode (scripts/ratchet.py), then one line with the reach, baseline, new and gone counts.
A source file that cannot be read or parsed is printed as `path: not read (reason)` and counts no
reaches. It exits 0 whatever it finds, and 2 only when a declaration cannot be read, naming it.

What a reach is (`reaches`, pure: a path, its text and a declaration in, reach lines out):

- Python, read by its syntax tree: a command is a list or tuple literal whose first element is the
  word, unless it is an argument of a call named `reading`, or a `run`, `Popen`, `check_output`,
  `check_call` or `call` whose first argument is a string that starts with the word and a space; an
  import is `import x` or `from x import`, at the name or below it; a call is a call of the name,
  bare or as an attribute; a literal is a string constant that contains the text.
- Go, read by line: `exec.Command` or `exec.CommandContext` of the word, a quoted import path at or
  below the name, and a quoted string that contains the literal. Calls are matched in Python only.

It reads files only: no git, no network, no subprocess, and nothing from hygiene.py.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import ratchet

ROOT = Path(__file__).resolve().parents[1]
DOORS = ROOT / "scripts" / "doors"

SCANNED = ("scripts", "tests", "components")
SUFFIXES = (".py", ".go")
SKIPPED = frozenset({".venv", "testdata", "__pycache__"})
SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
PATTERNS = ("commands", "imports", "calls", "literals")
LISTS = ("files", "contract_tests", *PATTERNS)
KEYS = ("door", *LISTS, "baseline")
ENTRY_KEYS = ("count", "reason")
# The kind each pattern list gives its reaches.
KIND = {"commands": "command", "imports": "import", "calls": "call", "literals": "literal"}
GO_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`')


class DeclarationError(Exception):
    """A declaration that cannot be read; its message names the file and the key."""


@dataclass(frozen=True)
class Declaration:
    door: str
    files: tuple[str, ...] = ()
    contract_tests: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    # path -> (count, reason)
    baseline: Mapping[str, tuple[int, str]] = field(default_factory=dict)


@dataclass(frozen=True, order=True)
class Reach:
    path: str
    line: int
    kind: str
    word: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} {self.word}"


# Declarations


def declaration(name: str, data: Mapping[str, object]) -> Declaration:
    """The declaration `data` holds, as read from the file `name`; refuses an unknown key, a list that
    is not a list of strings, a baseline entry without a reason and a count below 1."""
    for key in data:
        if key not in KEYS:
            raise DeclarationError(f"{name}: unknown key {key!r}")
    door = data.get("door")
    if not isinstance(door, str) or not door.strip():
        raise DeclarationError(f"{name}: key 'door' must name the door")
    lists = {}
    for key in LISTS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise DeclarationError(f"{name}: key {key!r} must be a list of non-empty strings")
        lists[key] = tuple(value)
    table = data.get("baseline", {})
    if not isinstance(table, Mapping):
        raise DeclarationError(f"{name}: key 'baseline' must be a table")
    baseline = {}
    for path, entry in table.items():
        where = f"baseline.{path!r}"
        if not isinstance(entry, Mapping):
            raise DeclarationError(f"{name}: key {where} must be a table of count and reason")
        for key in entry:
            if key not in ENTRY_KEYS:
                raise DeclarationError(f"{name}: unknown key {where}.{key}")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise DeclarationError(f"{name}: key {where}.reason is missing: every baseline entry says why")
        count = entry.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise DeclarationError(f"{name}: key {where}.count must be a whole number of at least 1")
        baseline[path] = (count, reason)
    return Declaration(door=door, baseline=baseline, **lists)


def load(path: Path) -> Declaration:
    """The declaration in the TOML file `path`."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DeclarationError(f"{path.as_posix()}: not read ({error})") from error
    return declaration(path.as_posix(), data)


def load_all(folder: Path) -> list[Declaration]:
    """Every declaration in `folder`, by file name."""
    paths = sorted(folder.glob("*.toml"))
    if not paths:
        raise DeclarationError(f"{folder.as_posix()}: no door declaration (*.toml)")
    return [load(path) for path in paths]


# The finder (pure)


def called_name(call: ast.Call) -> str:
    function = call.func
    return function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")


def at_or_below(module: str, name: str) -> bool:
    return module == name or module.startswith(name + ".")


def python_features(tree: ast.AST) -> list[tuple[str, int, str]]:
    """The nodes of a parsed Python file a reach can be, walked once for every door, as `(feature,
    line, value)`: `head`, the first element of a list or tuple literal not passed to `reading`;
    `run`, the string a subprocess call starts with; `call`, a called name; `import`, an imported
    module; `string`, a string constant."""
    nodes = list(ast.walk(tree))
    announced = {id(argument) for node in nodes
                 if isinstance(node, ast.Call) and called_name(node) == "reading" for argument in node.args}
    features = []
    for node in nodes:
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) \
                and isinstance(node.elts[0].value, str) and id(node) not in announced:
            features.append(("head", node.lineno, node.elts[0].value))
        elif isinstance(node, ast.Call):
            name = called_name(node)
            if name in SUBPROCESS_CALLS and node.args and isinstance(node.args[0], ast.Constant):
                features.append(("run", node.lineno, str(node.args[0].value)))
            features.append(("call", node.lineno, name))
        elif isinstance(node, ast.Import):
            features += [("import", node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            features.append(("import", node.lineno, node.module))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            features.append(("string", node.lineno, node.value))
    return features


def python_reaches(path: str, features: Sequence[tuple[str, int, str]], door: Declaration) -> list[Reach]:
    """The reaches for `door` among the features (`python_features`) of the Python file `path`."""
    found = []
    for feature, line, value in features:
        if feature == "head":
            found += [Reach(path, line, "command", word) for word in door.commands if value == word]
        elif feature == "run":
            found += [Reach(path, line, "command", word) for word in door.commands if value.startswith(word + " ")]
        elif feature == "call":
            found += [Reach(path, line, "call", word) for word in door.calls if value == word]
        elif feature == "import":
            found += [Reach(path, line, "import", word) for word in door.imports if at_or_below(value, word)]
        else:
            found += [Reach(path, line, "literal", word) for word in door.literals if word in value]
    return sorted(found)


def go_reaches(path: str, text: str, door: Declaration) -> list[Reach]:
    """The reaches of the Go file `path` for `door`, read by line."""
    commands = [(word, re.compile(r'exec\.Command(?:Context)?\((?:\w+, )?"' + re.escape(word) + '"'))
                for word in door.commands]
    imports = [(word, re.compile('"' + re.escape(word) + '(?:/[^"]*)?"')) for word in door.imports]
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        found += [Reach(path, number, "command", word) for word, pattern in commands if pattern.search(line)]
        found += [Reach(path, number, "import", word) for word, pattern in imports if pattern.search(line)]
        strings = GO_STRING.findall(line)
        found += [Reach(path, number, "literal", word) for word in door.literals
                  if any(word in string for string in strings)]
    return found


def reaches(path: str, text: str, door: Declaration) -> list[Reach]:
    """The reaches of the file `path` holding `text` for `door`, each with its line, kind and word;
    a Python text that does not parse raises SyntaxError (or ValueError)."""
    if path.endswith(".go"):
        return go_reaches(path, text, door)
    return python_reaches(path, python_features(ast.parse(text, path)), door)


# The report (pure: texts and declarations in, lines out)


@dataclass
class DoorResult:
    door: Declaration
    reaches: list[Reach]
    new: list[str]
    gone: list[str]

    @property
    def lines(self) -> list[str]:
        baseline = sum(count for count, _ in self.door.baseline.values())
        return [f"door {self.door.door}",
                *(f"{reach}" for reach in self.reaches),
                *(f"new: {path}" for path in self.new),
                *(f"gone: {path}" for path in self.gone),
                f"{self.door.door}: {len(self.reaches)} reaches, {baseline} baseline, "
                f"{len(self.new)} new, {len(self.gone)} gone"]


def scan(texts: Mapping[str, str], doors: Sequence[Declaration]) -> tuple[list[DoorResult], dict[str, str]]:
    """Each door's reaches outside it in `texts` (path -> text), with the ratchet's new and gone in
    report mode, and the Python texts that did not parse (path -> reason)."""
    features, unread = {}, {}
    for path, text in texts.items():
        if path.endswith(".py"):
            try:
                features[path] = python_features(ast.parse(text, path))
            except (SyntaxError, ValueError) as error:
                unread[path] = f"{type(error).__name__}: {error}"
    results = []
    for door in doors:
        found = []
        for path in sorted(texts):
            if path in door.files or path in unread:
                continue
            found += (python_reaches(path, features[path], door) if path in features
                      else go_reaches(path, texts[path], door))
        counts: dict[str, int] = {}
        for reach in found:
            counts[reach.path] = counts.get(reach.path, 0) + 1
        new, gone = ratchet.compare(counts, {path: count for path, (count, _) in door.baseline.items()}, "report")
        results.append(DoorResult(door, sorted(found), new, gone))
    return results, unread


# Wiring


def ground(root: Path) -> list[Path]:
    """The files the report scans under `root`: hygiene's git-door ground."""
    return [path for folder in SCANNED for path in sorted((root / folder).rglob("*"))
            if path.suffix in SUFFIXES and path.is_file() and not SKIPPED & set(path.relative_to(root).parts)]


def read(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """The texts of the scanned files of `root` (path -> text), and those not read (path -> reason)."""
    texts, unread = {}, {}
    for path in ground(root):
        name = path.relative_to(root).as_posix()
        try:
            texts[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            unread[name] = f"{type(error).__name__}: {error}"
    return texts, unread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout to scan (default: SE's)")
    parser.add_argument("--doors", type=Path, default=DOORS, help="the declarations' folder (default: SE's)")
    args = parser.parse_args(argv)
    try:
        doors = load_all(args.doors)
    except DeclarationError as error:
        print(f"door_report: {error}", file=sys.stderr)
        return 2
    texts, unread = read(args.root)
    results, unparsed = scan(texts, doors)
    for name, reason in sorted({**unread, **unparsed}.items()):
        print(f"{name}: not read ({reason})")
    for result in results:
        print("\n".join(result.lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
