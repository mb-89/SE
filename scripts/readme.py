#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""The one-page README: the shape every README of a project SE serves has (the guidance note
readme-is-one-page, SE#1796), checked, and its one command printed for CI to run.

A README is a landing page, the elevator pitch of its software, no manual:

- **One page.** At most MAX_LINES lines and MAX_CHARACTERS characters, headings included.
- **The command first.** Within its first OPENING lines, a fenced code block that holds one command,
  the one that gets the software, installs it and runs its showcase, and so smoke-tests it: it exits
  non-zero when anything is broken. Beside it, within the same lines, a link to the full
  documentation: a Markdown link whose text names the documentation.
- **What it is.** The prose after the opening's last paragraph, up to the first list item: the idea,
  who it is for and its big value propositions, in at most MAX_SENTENCES sentences; never feature,
  command or mechanism detail, which the documentation holds.
- **Links to the rest.** After it, a list that links to the rest.

`readme.py check [--root ROOT]` checks `<root>/README.md`: exit code 0 where it has the shape, 1 with
each finding on its own line, 2 where there is no README. SE runs it on its own checkout at commit
(se.toml `[commit_checks]`) and in CI (`scripts/hygiene.py`, its check `readme`).

`readme.py showcase [--root ROOT] [--url URL] [--branch BRANCH]` prints the README's one command, for
CI's fresh runner to run as a person would. `--url` puts the clone address in place of the first one
that holds a placeholder (`https://github.com/<owner>/<repository>`), and `--branch` clones that
branch, so a pull request's run gets the code under review. Exit code 0, 1 where the README has no
command block, 2 where there is no README.

Standard library only: the fresh runner has Python and nothing installed beside it.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
import se_script

MAX_LINES = 60
MAX_CHARACTERS = 3_500
OPENING = 10
MAX_SENTENCES = 5

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^#{1,6}\s")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
CODE_SPAN = re.compile(r"`+[^`]*`+")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
PLACEHOLDER_URL = re.compile(r"\S*<[^<>\s]+>/<[^<>\s]+>\S*")


@dataclass(frozen=True)
class Readme:
    """A README's text and the parts its shape names."""
    text: str

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    def blocks(self) -> list[tuple[int, int, list[str]]]:
        """Each fenced block as (first line, last line, its body lines), lines counted from 1."""
        found, start, body = [], None, []
        for number, line in enumerate(self.lines, 1):
            if FENCE.match(line):
                if start is None:
                    start, body = number, []
                else:
                    found.append((start, number, body))
                    start = None
            elif start is not None:
                body.append(line)
        return found

    def command(self) -> str | None:
        """The command of the first fenced block within the opening, where it holds exactly one."""
        for start, end, body in self.blocks():
            if end > OPENING:
                return None
            commands = [line.strip() for line in body if line.strip() and not line.lstrip().startswith("#")]
            return commands[0] if len(commands) == 1 else None
        return None

    def documentation_line(self) -> int | None:
        """The first line within the opening that links the documentation, outside code."""
        for number, line in enumerate(self.prose_lines(), 1):
            if number > OPENING:
                return None
            if line and any("documentation" in text.casefold() for text, _ in LINK.findall(line)):
                return number
        return None

    def prose_lines(self) -> list[str]:
        """Each line, a fenced block's lines blanked, so a line number keeps its place."""
        out, inside = [], False
        for line in self.lines:
            if FENCE.match(line):
                inside = not inside
                out.append("")
            else:
                out.append("" if inside else line)
        return out

    def description(self, after: int) -> tuple[str, int | None]:
        """The prose after the paragraph holding line `after`, up to the first list item, and that
        item's line number (None where no list follows)."""
        lines = self.prose_lines()
        index = after
        while index < len(lines) and lines[index].strip():
            index += 1
        prose = []
        for number in range(index + 1, len(lines) + 1):
            line = lines[number - 1]
            if LIST_ITEM.match(line):
                return " ".join(prose), number
            if line.strip() and not HEADING.match(line):
                prose.append(line.strip())
        return " ".join(prose), None


def sentences(prose: str) -> int:
    """The sentences of `prose`: code spans and link targets hold no sentence end."""
    plain = LINK.sub(lambda match: match.group(1), CODE_SPAN.sub("code", prose))
    return len(SENTENCE_END.findall(plain)) + (1 if plain.strip() and not SENTENCE_END.search(plain.rstrip()[-1:]) else 0)


def findings(text: str) -> list[str]:
    """What keeps `text`, a README, from the one-page shape, each as one line."""
    readme = Readme(text)
    found = []
    if len(readme.lines) > MAX_LINES:
        found.append(f"{len(readme.lines)} lines; a README holds at most {MAX_LINES}: move the rest "
                     "to the documentation it links")
    if len(text) > MAX_CHARACTERS:
        found.append(f"{len(text)} characters; a README holds at most {MAX_CHARACTERS}: move the "
                     "rest to the documentation it links")
    if readme.command() is None:
        found.append(f"no code block of one command within its first {OPENING} lines: open with the "
                     "one command that gets, installs and runs the showcase")
    documentation = readme.documentation_line()
    if documentation is None:
        found.append(f"no link to the full documentation within its first {OPENING} lines: a link "
                     "whose text names the documentation")
        return found
    prose, links = readme.description(documentation)
    if not prose:
        found.append("no description after the opening: say what it is, who it is for and its big "
                     f"value propositions in at most {MAX_SENTENCES} sentences")
    elif (count := sentences(prose)) > MAX_SENTENCES:
        found.append(f"{count} sentences say what it is; at most {MAX_SENTENCES}: keep the pitch, move "
                     "feature, command and mechanism detail to the documentation")
    if links is None or not LINK.search(" ".join(readme.lines[links - 1:])):
        found.append("no list of links after the description: link the rest")
    return found


def showcase(text: str, url: str | None = None, branch: str | None = None) -> str | None:
    """The README's one command, with `url` in place of its placeholder clone address and `branch`
    cloned; None where it has none."""
    command = Readme(text).command()
    if command is None:
        return None
    if url:
        command = PLACEHOLDER_URL.sub(lambda _: url, command, count=1)
    if branch:
        command = re.sub(r"\bgit clone\b", f"git clone --branch {branch}", command, count=1)
    return command


def main(argv: list[str] | None = None) -> int:
    parser = se_script.parser(prog="readme.py", description="The one-page README: its check, "
                                     "and its one command for CI (the guidance note readme-is-one-page).")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="refuse a README that is not one page with its command "
                                "first; exit code 1 with each finding")
    check.add_argument("--root", type=Path, default=Path.cwd(), help="the checkout (default: here)")
    run = commands.add_parser("showcase", help="print the README's one command, for CI to run")
    run.add_argument("--root", type=Path, default=Path.cwd(), help="the checkout (default: here)")
    run.add_argument("--url", help="the clone address in place of the placeholder one")
    run.add_argument("--branch", help="the branch to clone")
    args = parser.parse_args(argv)
    path = args.root / "README.md"
    if not path.is_file():
        print(f"readme.py: no README.md in {args.root}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    if args.command == "showcase":
        command = showcase(text, args.url, args.branch)
        if command is None:
            print(f"readme.py: {path.name} has no code block of one command within its first "
                  f"{OPENING} lines", file=sys.stderr)
            return 1
        print(command)
        return 0
    found = findings(text)
    for finding in found:
        print(f"README.md: {finding}")
    if found:
        return 1
    print("README.md: one page, its command first")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
