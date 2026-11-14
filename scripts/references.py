#!/usr/bin/env python3
"""Dangling references: text that names a file or a command that does not exist.

One function, `dangling`, finds the references in a Markdown text and checks them; both places that
refuse them call it: the repository check (`scripts/hygiene.py` references, over se's agents,
skills, README.md, AGENTS.md and the rule book) and the issue-filing commands `work_tickets.py file`,
`backlog file` and `route` (over the issue body's commands).

- Paths: a relative Markdown link, resolved from the text's own file, and a repository path in a
  code span or a fenced block (`scripts/…`, `src/…`, `tests/…`, `.github/…`, also after `<se>/`),
  resolved from the repository root. A path holding a placeholder (`<name>`, `*`, `…`, `{a,b}`) or
  a variable names no one file and is not checked.
- Commands: `<x>.py <subcommand> [<subcommand>]` in a code span or a fenced block, where
  `scripts/<x>.py` is one of the repository's scripts whose argument parser defines subcommands.
  That parser is the command registry while SE is Python: read in process, never run.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import re
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATH_ROOTS = ("scripts/", "src/", "tests/", ".github/")
PLACEHOLDER = re.compile(r"[<>*…{}$?\[\]|]")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_DEFINITION = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:[ \t]+<?(\S+?)>?(?:[ \t]+\"[^\"]*\")?[ \t]*$",
                                  re.MULTILINE)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
SUBCOMMAND = re.compile(r"[a-z][a-z0-9-]*")
TRAILING = ".,;:)'\""


@dataclass(frozen=True)
class Finding:
    """One reference that names nothing: its line in the text, the item and why."""
    line: int
    item: str
    reason: str

    def __str__(self) -> str:
        return f"line {self.line}: `{self.item}` {self.reason}"


def dangling(text: str, root: Path = ROOT, source: Path | None = None, *,
             paths: bool = True, bare_scripts: bool = True,
             created: bool = False) -> list[Finding]:
    """The references in Markdown `text` that name something missing, in text order.

    `root` is the repository the paths and commands are resolved from (its `scripts/`), and
    `source` the file the text is read from, for its relative links (no links are checked without
    it). With `paths` false only commands are checked, and repository paths only where they name a
    script (`scripts/…`); with `bare_scripts` false too, a `scripts/…` path only after `<se>/`.
    With `created`, a reference passes where the text's Requirements say it creates it: one
    requirement names it and says "new", "add" or "create".
    """
    scripts = root / "scripts"
    prose, code = split_code(text)
    found: list[Finding] = []
    if source is not None and paths:
        for match in [*LINK.finditer(prose), *REFERENCE_DEFINITION.finditer(prose)]:
            finding = dead_link(match.group(1), source, root, line_of(text, match.start(1)))
            if finding:
                found.append(finding)
    for start, snippet in code:
        tokens = [(match.group(), line_of(text, start + match.start()))
                  for match in re.finditer(r"\S+", snippet)]
        found += dead_code(tokens, root, scripts, paths, bare_scripts)
    if created:
        made = requirements(text)
        found = [finding for finding in found if not creates(made, finding.item)]
    return sorted(found, key=lambda finding: finding.line)


CREATING = re.compile(r"\b(new|adds?|added|creates?|created|introduces?)\b", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
ITEM = re.compile(r"^[ \t]*(?:\d+[.)]|[-*+])[ \t]+")


def requirements(text: str) -> list[str]:
    """The items of the text's Requirements sections, each with its continuation lines."""
    items: list[str] = []
    level = None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            depth = len(heading.group(1))
            if level is not None and depth <= level:
                level = None
            if level is None and heading.group(2).strip().lower() == "requirements":
                level = depth
            continue
        if level is None:
            continue
        if ITEM.match(line) or not items:
            items.append(line)
        elif line.strip():
            items[-1] += " " + line.strip()
    return items


def creates(items: list[str], reference: str) -> bool:
    """Whether one requirement names `reference` (each of its words, a path by its file name) and
    says it is new, added or created."""
    words = [Path(word).name if "/" in word else word for word in reference.split()]
    return any(CREATING.search(item) and all(word in item for word in words) for item in items)


def split_code(text: str) -> tuple[str, list[tuple[int, str]]]:
    """`text` with its code blanked out (same length, so offsets keep their lines), and its code:
    each fenced block's lines and each code span, with the offset it starts at."""
    code: list[tuple[int, str]] = []
    prose = list(text)
    offset, fence = 0, None
    outside: list[tuple[int, int]] = []
    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None and marker and marker.group(1).startswith(fence):
            fence = None
        elif fence is not None:
            body = line.rstrip("\r\n")
            code.append((offset, body))
            prose[offset:offset + len(body)] = " " * len(body)
        else:
            outside.append((offset, offset + len(line)))
        offset += len(line)
    # Code spans may wrap across lines, so they are found in each run of prose lines.
    for begin, end in runs(outside):
        for match in CODE_SPAN.finditer(text, begin, end):
            code.append((match.start(2), match.group(2)))
            for index in range(match.start(), match.end()):
                if prose[index] != "\n":
                    prose[index] = " "
    return "".join(prose), sorted(code)


def runs(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Adjacent spans merged."""
    merged: list[tuple[int, int]] = []
    for begin, end in spans:
        if merged and merged[-1][1] == begin:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((begin, end))
    return merged


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def dead_link(target: str, source: Path, root: Path, line: int) -> Finding | None:
    """A relative link whose file is missing; links to anchors, URLs and placeholders pass."""
    path = target.split("#", 1)[0]
    if not path or SCHEME.match(path) or PLACEHOLDER.search(path) or path.startswith("/"):
        return None
    if (source.parent / path).exists():
        return None
    return Finding(line, target, f"links to {relative(source.parent / path, root)}, which does "
                                 "not exist")


def dead_code(tokens: list[tuple[str, int]], root: Path, scripts: Path,
              paths: bool, bare_scripts: bool) -> list[Finding]:
    """The dead repository paths and unknown subcommands among one piece of code's `tokens`, each
    with its line: a code span's (which may wrap) or a fenced block line's."""
    found = []
    for index, (raw, line) in enumerate(tokens):
        token = raw.rstrip(TRAILING).lstrip("('\"")
        path = repository_path(token)
        script = path is not None and path.startswith("scripts/") and (
            bare_scripts or token.startswith("<se>/"))
        if path is not None and (paths or script):
            if not PLACEHOLDER.search(path) and not (root / path).exists():
                found.append(Finding(line, path, "names a file that does not exist"))
                continue
        if token.endswith(".py"):
            following = [word for word, _ in tokens[index + 1:]]
            finding = unknown_subcommand(Path(token).name, following, scripts, line)
            if finding:
                found.append(finding)
    return found


def repository_path(token: str) -> str | None:
    """The repository path a code token names, or None: `scripts/…`, `src/…`, `tests/…` or
    `.github/…`, also after `<se>/` or `./`, without an anchor or a line number."""
    for prefix in ("<se>/", "./"):
        token = token.removeprefix(prefix)
    if not token.startswith(PATH_ROOTS) or token in PATH_ROOTS:
        return None
    path = re.sub(r"(#.*|:\d+(:\d+)?)$", "", token)
    return path or None


def unknown_subcommand(script: str, rest: list[str], scripts: Path, line: int) -> Finding | None:
    """`script` followed by `rest` where the script's parser defines no such subcommand."""
    tree = command_tree(scripts / script)
    words = []
    for raw in rest:
        word = raw.rstrip(TRAILING)
        if not tree or not SUBCOMMAND.fullmatch(word):
            return None
        words.append(word)
        if word not in tree:
            return Finding(line, " ".join((script, *words)),
                           f"names a subcommand {script}'s parser does not define; it defines "
                           + ", ".join(sorted(tree)))
        tree = tree[word]
    return None


Tree = dict[str, "Tree"]


class _Captured(BaseException):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__()
        self.parser = parser


@contextmanager
def capturing():
    """While active, a parser's first parse raises `_Captured` with the parser instead."""
    saved = argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args

    def capture(self, *arguments, **options):
        raise _Captured(self)
    argparse.ArgumentParser.parse_args = capture  # type: ignore[method-assign]
    argparse.ArgumentParser.parse_known_args = capture  # type: ignore[method-assign]
    try:
        yield
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = saved


@cache
def command_tree(script: Path) -> Tree:
    """The subcommands `script`'s argument parser defines, nested; empty where it defines none or
    is no script with a `main`. Its `main` runs only until it parses its arguments, its output
    swallowed, and never in a script without argparse (git_door.py's main runs git)."""
    if not script.is_file() or script.suffix != ".py" or "argparse" not in script.read_text(encoding="utf-8"):
        return {}
    module = load(script)
    main = getattr(module, "main", None)
    if main is None:
        return {}
    sink = io.TextIOWrapper(io.BytesIO())
    with capturing(), redirect_stdout(sink), redirect_stderr(sink):
        try:
            main([])
        except _Captured as captured:
            return parser_tree(captured.parser)
        except (Exception, SystemExit):
            return {}
    return {}


def load(script: Path):
    """The script as a module: the one already loaded under its name where it is this file, else
    loaded once under its name, so its siblings share it."""
    name = script.stem
    module = sys.modules.get(name)
    if module is not None and Path(getattr(module, "__file__", "")).resolve() == script.resolve():
        return module
    if script.resolve().parent == Path(__file__).resolve().parent and module is None:
        key = name
    else:
        key = f"_references_{abs(hash(script.resolve()))}_{name}"
    spec = importlib.util.spec_from_file_location(key, script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


def parser_tree(parser: argparse.ArgumentParser) -> Tree:
    """A parser's subcommands: its subparsers, nested, or its first positional's choices."""
    for action in parser._actions:  # argparse has no public accessor for them
        if isinstance(action, argparse._SubParsersAction):
            return {name: parser_tree(sub) for name, sub in action.choices.items()}
    for action in parser._actions:
        if not action.option_strings and action.choices:
            return {str(choice): {} for choice in action.choices}
    return {}


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
