"""The commands SE's scripts name in their own messages exist: every string in `scripts/*.py`
(docstrings aside) that names `<script>.py <subcommand>` or one of its `--options` is held to
that script's argument parser, the registry `scripts/references.py` reads, so a rename that leaves
a remedy behind fails here before it lands."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from positive_control import positive_control

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import references  # noqa: E402

HOLE = "{}"  # an f-string's hole, a placeholder like `<name>`
ALLOWED = (
    ("scripts/templates.py", "templates.py and",
     "prose: \"a script beside scripts/templates.py and what it defines\", no command"),
    ("scripts/se_modules.py", "se_modules.py resolved",
     "prose: the lock file's header line says what wrote it, no command"),
    ("scripts/timeline.py", "deck.py builds",
     "prose: the render group's description says what deck.py does, no command"),
)
SCRIPT = re.compile(r"(?<![\w}\-.])(?:[^\s`'\"(]*/)?([A-Za-z_][\w-]*)\.py(?![\w/.])")
OPTION = re.compile(r"--[A-Za-z0-9][\w-]*")
PROSE_END = re.compile(r"[,;]|\.(?=\s|$)")


@dataclass(frozen=True)
class Text:
    """One string of a script: its file relative to the root, its line and its text."""
    file: str
    line: int
    text: str


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    item: str
    why: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.item} {self.why}"


def strings(root: Path) -> Iterator[Text]:
    """Every string constant and f-string of `root`'s `scripts/*.py`, read with `ast`, never run;
    docstrings are skipped, and an f-string's holes stand as `{}`."""
    for path in sorted((root / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)
                      and isinstance(node.body[0].value.value, str)}
        file = path.relative_to(root).as_posix()
        yield from texts(tree, file, docstrings)


def texts(node: ast.AST, file: str, docstrings: set[int]) -> Iterator[Text]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if id(node) not in docstrings:
            yield Text(file, node.lineno, node.value)
        return
    if isinstance(node, ast.JoinedStr):
        yield Text(file, node.lineno, "".join(
            part.value if isinstance(part, ast.Constant) else HOLE for part in node.values))
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                yield from texts(part.value, file, docstrings)
        return
    for child in ast.iter_child_nodes(node):
        yield from texts(child, file, docstrings)


def segments(text: str) -> Iterator[tuple[str, bool]]:
    """`text`'s code spans and the prose between them, each with whether it is code."""
    position = 0
    for match in references.CODE_SPAN.finditer(text):
        yield text[position:match.start()], False
        yield match.group(2), True
        position = match.end()
    yield text[position:], False


def mentions(text: str, scripts: Path) -> Iterator[tuple[str, list[str]]]:
    """Each `<script>.py <words>` in `text` whose script has an argument parser, with its words."""
    for segment, code in segments(text):
        found = [match for match in SCRIPT.finditer(segment) if parsed(scripts / f"{match.group(1)}.py")]
        for index, match in enumerate(found):
            end = found[index + 1].start() if index + 1 < len(found) else len(segment)
            rest = segment[match.end():end]
            if not code:
                stop = PROSE_END.search(rest)
                rest = rest[:stop.start()] if stop else rest
            yield f"{match.group(1)}.py", rest.split()


def parsed(script: Path) -> bool:
    return bool(references.command_tree(script) or references.command_options(script))


def check(script: str, words: list[str], scripts: Path) -> Iterator[tuple[str, str]]:
    """The item and why of each word in a mention its script's parser does not define."""
    finding = references.unknown_subcommand(script, words, scripts, 0)
    if finding is not None:
        yield finding.item, finding.reason
        return
    tree, leading = references.command_tree(scripts / script), []
    for raw in words:
        word = raw.rstrip(references.TRAILING)
        if word.startswith("-") or not tree:
            break
        if word not in tree:
            return  # a placeholder where a subcommand is due: the options' parser is unknown
        leading.append(word)
        tree = tree[word]
    defined = references.command_options(scripts / script, leading)
    for raw in words:
        word = raw.strip(references.TRAILING + "(")
        if not word.startswith("--") or references.PLACEHOLDER.search(word):
            continue
        option = word.split("=", 1)[0]
        if OPTION.fullmatch(option) and option not in defined:
            command = " ".join((script, *leading))
            yield (f"{command} {option}",
                   f"names an option {command} does not define; it defines "
                   + ", ".join(sorted(name for name in defined if name.startswith("--"))))


def sweep(root: Path) -> list[Finding]:
    """Every mention in `root`'s scripts' strings that names an undefined subcommand or option."""
    scripts = root / "scripts"
    return [Finding(text.file, text.line, item, why)
            for text in strings(root)
            for script, words in mentions(text.text, scripts)
            for item, why in check(script, words, scripts)]


def unexplained(found: list[Finding], allowed=ALLOWED) -> tuple[list[Finding], list[tuple[str, str, str]]]:
    """The findings no allow-list entry covers, and the entries that cover none."""
    covered = {(entry[0], entry[1]) for entry in allowed}
    left = [finding for finding in found if (finding.file, finding.item) not in covered]
    hit = {(finding.file, finding.item) for finding in found}
    return left, [entry for entry in allowed if (entry[0], entry[1]) not in hit]


def verdict(found: list[Finding], allowed=ALLOWED) -> str | None:
    """The failure message for `found`, or None where every finding is allowed and every entry used."""
    left, stale = unexplained(found, allowed)
    lines = [str(finding) for finding in left]
    lines += [f"allow-list entry {file}: {mention!r} matches nothing; remove it" for file, mention, _ in stale]
    if not lines:
        return None
    return ("\n".join(lines) + "\nCorrect the message, or, where the words are plain prose, add an "
            "allow-list entry with its reason to tests/test_remedy_strings.py.")


TOOL = '''import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("push").add_argument("--redeliver", action="store_true")
    commands.add_parser("deliver")
    return parser.parse_args(argv)
'''
FLAT = '''import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rev")
    return parser.parse_args(argv)
'''
CALLER = '''def refuse(name, flag):
    """Docstrings name tool.py delivr freely."""
    messages = [
        "use `tool.py delivr` instead",
        "run tool.py push --forse",
        "run flat.py --revv",
        "run tool.py push --redeliver, then flat.py --rev.",
        f"run tool.py {name} --anything",
        f"run tool.py push --{flag}",
    ]
    return messages
'''


@pytest.fixture
def made_up(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text(TOOL, encoding="utf-8")
    (scripts / "flat.py").write_text(FLAT, encoding="utf-8")
    (scripts / "plain.py").write_text("def main(argv=None):\n    return 0\n", encoding="utf-8")
    return tmp_path


def test_the_sweep_finds_each_unknown_subcommand_and_option(made_up: Path) -> None:
    found = positive_control("remedy strings", sweep, made_up, "scripts/caller.py", CALLER,
                             Finding("scripts/caller.py", 4, "tool.py delivr",
                                     "names a subcommand tool.py's parser does not define; it defines "
                                     "deliver, push"))
    assert [(finding.file, finding.line, finding.item) for finding in found] == [
        ("scripts/caller.py", 4, "tool.py delivr"),
        ("scripts/caller.py", 5, "tool.py push --forse"),
        ("scripts/caller.py", 6, "flat.py --revv")]
    message = verdict(found, ())
    assert "scripts/caller.py:5: tool.py push --forse names an option tool.py push does not define; " \
           "it defines --help, --redeliver" in message
    assert "scripts/caller.py:6: flat.py --revv" in message and "add an allow-list entry" in message


def test_command_options_follow_the_subcommand_words(made_up: Path) -> None:
    scripts = made_up / "scripts"
    assert "--redeliver" in references.command_options(scripts / "tool.py", ["push"])
    assert "--redeliver" not in references.command_options(scripts / "tool.py")
    assert "--rev" in references.command_options(scripts / "flat.py")
    assert references.command_options(scripts / "plain.py", ["push"]) == frozenset()


def test_an_allow_list_entry_that_matches_nothing_fails() -> None:
    message = verdict([], (("scripts/gone.py", "gone.py words", "a reason"),))
    assert "allow-list entry scripts/gone.py: 'gone.py words' matches nothing" in message


def test_the_scripts_name_only_commands_and_options_they_define(fake_git_door) -> None:
    scripts = ROOT / "scripts"
    with_subcommands = {path.name for path in scripts.glob("*.py") if references.command_tree(path)}
    assert {"work_tickets.py", "templates.py", "review.py"} <= with_subcommands
    assert "--rev" in references.command_options(scripts / "public_check.py")
    message = verdict(sweep(ROOT))
    if message:
        pytest.fail(message)
