#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Every reach outside a declared door, refused: a check with no baseline and no shrink-only allowance.

Each door declares in a data file (`scripts/doors/<door>.toml`) what it guards: `door` (its name),
`level`, `files` (its own files), `contract_tests`, `ground` (the scanned folders it checks, default
all of them), and the reach patterns `commands`, `imports`,
`calls`, `names` and `literals` (rule book des-004, one door per outside thing). Every key but
`door` and `level` may be left out.

The level is the rule's day-one path (no grandfathering): a new door starts at `warn` while the
reaches it finds move behind it, and is set to `error` once they are gone.

- `error`: each reach outside the door is printed and refused.
- `warn`: the door's reaches are counted on one warning line (each one printed under `--list`), and
  pass; a `warn` door that finds no reach is refused, naming the step left, `level = "error"`, so
  no door stays a warning once its reaches are gone.

`uv run python scripts/door_report.py [--root DIR] [--doors DIR] [--list]` reads the declarations
(default: SE's `scripts/doors`) and scans the `.py` and `.go` files under scripts, tests and
components of the root (default: SE's checkout), skipping .venv, testdata and __pycache__: the
ground hygiene's git-door check scans. A door's own `files` and its `contract_tests` are not
scanned for that door. A source file that cannot be read or parsed is refused, as nothing in it can
be checked. Exit code 0 passed, 1 refused, 2 a declaration cannot be read, naming it. hygiene.py
(its check `doors`) and the commit hook (se.toml `[commit_checks]`) run the same check.

What a reach is (`reaches`, pure: a path, its text and a declaration in, reach lines out):

- Python, read by its syntax tree: a command is a list or tuple literal whose first element is the
  word, unless it is an argument of a call named `reading`, or a `run`, `Popen`, `check_output`,
  `check_call` or `call` whose first argument is a string that starts with the word and a space; an
  import is `import x` or `from x import`, at the name or below it; a call is a call of the name,
  bare or as an attribute, and a dotted name (`subprocess.run`) matches a call whose dotted callee
  is it or ends with it; a name is a dotted reference (`os.environ`) used anywhere, called or not,
  matched the same way; a literal is a string constant that contains the text.
- Go, read by line: `exec.Command` or `exec.CommandContext` of the word, a quoted import path at or
  below the name, and a quoted string that contains the literal. Calls and names are matched in
  Python only.

It reads files only: no git, no network, no subprocess.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import se_script

ROOT = Path(__file__).resolve().parents[1]
DOORS = ROOT / "scripts" / "doors"

SCANNED = ("scripts", "tests", "components")
SUFFIXES = (".py", ".go")
SKIPPED = frozenset({".venv", "testdata", "__pycache__"})
SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
PATTERNS = ("commands", "imports", "calls", "names", "literals")
LISTS = ("files", "contract_tests", "ground", *PATTERNS)
KEYS = ("door", "level", *LISTS)
ERROR, WARN = "error", "warn"
LEVELS = (ERROR, WARN)
GO_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`')


class DeclarationError(Exception):
    """A declaration that cannot be read; its message names the file and the key."""


@dataclass(frozen=True)
class Declaration:
    door: str
    level: str = ERROR
    files: tuple[str, ...] = ()
    contract_tests: tuple[str, ...] = ()
    ground: tuple[str, ...] = SCANNED
    commands: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()


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
    """The declaration `data` holds, as read from the file `name`; refuses an unknown key (a
    `baseline` among them: there is none), a level that is not `warn` or `error`, and a list that is
    not a list of strings."""
    for key in data:
        if key not in KEYS:
            hint = ": a door keeps no baseline; set level = \"warn\" while its reaches move" if key == "baseline" else ""
            raise DeclarationError(f"{name}: unknown key {key!r}{hint}")
    door = data.get("door")
    if not isinstance(door, str) or not door.strip():
        raise DeclarationError(f"{name}: key 'door' must name the door")
    level = data.get("level")
    if level not in LEVELS:
        raise DeclarationError(f"{name}: key 'level' must be one of {', '.join(LEVELS)}")
    lists = {}
    for key in LISTS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise DeclarationError(f"{name}: key {key!r} must be a list of non-empty strings")
        lists[key] = tuple(value)
    if unknown := [folder for folder in lists["ground"] if folder not in SCANNED]:
        raise DeclarationError(f"{name}: key 'ground' names {', '.join(unknown)}, not one of {', '.join(SCANNED)}")
    lists["ground"] = lists["ground"] or SCANNED
    return Declaration(door=door, level=level, **lists)


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


def dotted(node: ast.AST) -> str:
    """The dotted name of a chain of names and attributes (`os.environ`), else its last attribute."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def matches(value: str, word: str) -> bool:
    """Whether the dotted `value` is the pattern `word`: a dotted word is the value or its end, a
    plain word the value's last part."""
    if "." in word:
        return value == word or value.endswith("." + word)
    return value.rsplit(".", 1)[-1] == word


def at_or_below(module: str, name: str) -> bool:
    return module == name or module.startswith(name + ".")


def python_features(tree: ast.AST) -> list[tuple[str, int, str]]:
    """The nodes of a parsed Python file a reach can be, walked once for every door, as `(feature,
    line, value)`: `head`, the first element of a list or tuple literal not passed to `reading`;
    `run`, the string a subprocess call starts with; `call`, a called dotted name; `name`, a dotted
    reference that is not a call's callee; `import`, an imported module; `string`, a string constant."""
    nodes = list(ast.walk(tree))
    announced = {id(argument) for node in nodes
                 if isinstance(node, ast.Call) and called_name(node) == "reading" for argument in node.args}
    callees = {id(node.func) for node in nodes if isinstance(node, ast.Call)}
    inner = {id(node.value) for node in nodes if isinstance(node, ast.Attribute)}
    features = []
    for node in nodes:
        if isinstance(node, (ast.Attribute, ast.Name)) and id(node) not in callees and id(node) not in inner:
            features.append(("name", node.lineno, dotted(node)))
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) \
                and isinstance(node.elts[0].value, str) and id(node) not in announced:
            features.append(("head", node.lineno, node.elts[0].value))
        elif isinstance(node, ast.Call):
            name = called_name(node)
            if name in SUBPROCESS_CALLS and node.args and isinstance(node.args[0], ast.Constant):
                features.append(("run", node.lineno, str(node.args[0].value)))
            features.append(("call", node.lineno, dotted(node.func) or name))
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
            found += [Reach(path, line, "call", word) for word in door.calls if matches(value, word)]
            found += [Reach(path, line, "name", word) for word in door.names if "." in word and matches(value, word)]
        elif feature == "name":
            found += [Reach(path, line, "name", word) for word in door.names if matches(value, word)]
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


# The check (pure: texts and declarations in, lines out)


@dataclass
class DoorResult:
    door: Declaration
    reaches: list[Reach]

    @property
    def refused(self) -> list[str]:
        """What this door refuses: each reach at `error`, its own clean state at `warn`."""
        if self.door.level == ERROR:
            return [f"{reach} outside the {self.door.door} door" for reach in self.reaches]
        if not self.reaches:
            return [f"{self.door.door}: no reach left outside the door at level warn: set level = \"error\" "
                    f"in scripts/doors/{self.door.door}.toml"]
        return []

    def lines(self, listed: bool = False) -> list[str]:
        """The door's report: what it refuses, then at `warn` its count (and, `listed`, each reach)."""
        lines = [f"door_report: {line}" for line in self.refused]
        if self.door.level == WARN and self.reaches:
            files = len({reach.path for reach in self.reaches})
            lines.append(f"door_report: warning: {self.door.door}: {len(self.reaches)} reach(es) in {files} "
                         f"file(s) outside the door, level warn while they move behind it "
                         f"(door_report.py --list names each)")
            if listed:
                lines += [f"door_report: warning: {reach}" for reach in self.reaches]
        return lines


def scan(texts: Mapping[str, str], doors: Sequence[Declaration]) -> tuple[list[DoorResult], dict[str, str]]:
    """Each door's reaches outside it in `texts` (path -> text), and the Python texts that did not
    parse (path -> reason)."""
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
            if path in door.files or path in door.contract_tests or path in unread \
                    or path.split("/", 1)[0] not in door.ground:
                continue
            found += (python_reaches(path, features[path], door) if path in features
                      else go_reaches(path, texts[path], door))
        results.append(DoorResult(door, sorted(found)))
    return results, unread


def check(texts: Mapping[str, str], unread: Mapping[str, str], doors: Sequence[Declaration],
          listed: bool = False) -> tuple[list[str], list[str]]:
    """The check's printed lines and its refusals: each file not read or parsed, then each door's."""
    results, unparsed = scan(texts, doors)
    not_read = [f"{name}: not read ({reason}), so no door can check it"
                for name, reason in sorted({**unread, **unparsed}.items())]
    refused = [*not_read, *(line for result in results for line in result.refused)]
    lines = [f"door_report: {line}" for line in not_read]
    for result in results:
        lines += result.lines(listed)
    return lines, refused


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
    parser = se_script.parser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout to scan (default: SE's)")
    parser.add_argument("--doors", type=Path, default=DOORS, help="the declarations' folder (default: SE's)")
    parser.add_argument("--list", action="store_true", help="also name each reach of a door at level warn")
    args = parser.parse_args(argv)
    try:
        doors = load_all(args.doors)
    except DeclarationError as error:
        print(f"door_report: {error}", file=sys.stderr)
        return 2
    texts, unread = read(args.root)
    lines, refused = check(texts, unread, doors, args.list)
    print("\n".join(lines)) if lines else None
    if refused:
        print(f"door_report: refused ({len(refused)} finding(s)) in {args.root}")
        return 1
    print(f"door_report: passed ({len(doors)} doors) in {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
