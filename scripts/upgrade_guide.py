#!/usr/bin/env python3
"""The upgrade guides (docs/upgrading.md "How the guide is kept"): one owner for their shape.

A guide is `docs/upgrading.md` in a repository: one section per breaking release, headed
`## <name> <version>`, where `<name>` is the repository's (`SE`, `obs`, `kern`) and `<version>` the
release's major (`SE 12`), or below 1.0 its major and minor (`obs-html 0.5`), the part a breaking
release raises (work_tickets.py `released_version`). A section may also follow a minor release
whose consumers must act; the release check requires only the breaking ones.

`sections` answers the sections between two versions, for any pair; `missing` is the refusal the
release check (work_tickets.py `release`) raises where a breaking release has no section yet.

    uv run python scripts/upgrade_guide.py show --name SE --from 5.134.2 --to 12.0.1
    uv run python scripts/upgrade_guide.py show --guide <clone>/docs/upgrading.md --name obs --from 5.0.0 --to 10.3.2

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Where a repository keeps its guide, relative to its root.
GUIDE = Path("docs") / "upgrading.md"
#: A section's heading: `## <name> <version>`, the version a major or `0.<minor>`.
HEADING = re.compile(r"^## (?P<name>\S+) (?P<version>\d+(?:\.\d+)?)[ \t]*$", re.M)

Version = tuple[int, int, int]


@dataclass(frozen=True)
class Section:
    """One section of a guide: its heading's name and version, and its text, heading included."""

    name: str
    version: Version
    text: str
    #: The heading's version as written: `12`, `0.5`, or `2.1` for a minor's own section.
    written: str = ""

    @property
    def title(self) -> str:
        return f"{self.name} {self.written or label(self.version)}"


def parse(text: str) -> Version:
    """`1.2.3`, `1.2` or `1` (a leading `v` allowed) as a version; ValueError otherwise."""
    found = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text.strip())
    if found is None:
        raise ValueError(f"{text!r} is not a version (MAJOR[.MINOR[.PATCH]])")
    return int(found[1]), int(found[2] or 0), int(found[3] or 0)


def label(version: Version) -> str:
    """The heading's version of the breaking release `version`: its major, below 1.0 `0.<minor>`."""
    return f"0.{version[1]}" if version[0] == 0 else str(version[0])


def read(text: str) -> list[Section]:
    """Every section of a guide, in the order it holds them; a section ends where the next `## `
    heading starts."""
    headings = list(HEADING.finditer(text))
    starts = [m.start() for m in re.finditer(r"^## ", text, re.M)] + [len(text)]
    found = []
    for match in headings:
        end = next(start for start in starts if start > match.start())
        found.append(Section(match["name"], parse(match["version"]), text[match.start():end].rstrip() + "\n",
                             match["version"]))
    return found


def sections(text: str, name: str, running: Version, newest: Version) -> list[Section]:
    """The sections named `name` (case-insensitive) that lead from `running` to `newest`: each whose
    version is above `running` and at most `newest`, oldest first."""
    own = [s for s in read(text) if s.name.lower() == name.lower() and running < s.version <= newest]
    return sorted(own, key=lambda s: s.version)


def missing(root: Path, name: str, version: Version) -> str | None:
    """The refusal of a breaking release `version` of `name` in `root` whose guide holds no section
    for it, None where it does."""
    path = root / GUIDE
    want = f"## {name} {label(version)}"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    breaking = parse(label(version))
    if any(s.name.lower() == name.lower() and s.version == breaking for s in read(text)):
        return None
    return (f"{GUIDE.as_posix()} has no section `{want}` for this breaking release: add it, with "
            "each change, the steps a project takes and the check that each is done, in the "
            "landing that makes the change (docs/upgrading.md \"How the guide is kept\"), then "
            "release again")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="print the sections of a guide between two versions, "
                                            "oldest first, to follow in that order")
    show.add_argument("--guide", type=Path, default=Path(__file__).resolve().parents[1] / GUIDE,
                      help="the guide to read (default: this SE's docs/upgrading.md)")
    show.add_argument("--name", required=True, help="the name its sections carry: SE, obs, kern")
    show.add_argument("--from", dest="running", required=True, help="the version in use")
    show.add_argument("--to", dest="newest", required=True, help="the version to reach")
    args = parser.parse_args(argv)
    try:
        running, newest = parse(args.running), parse(args.newest)
        text = args.guide.read_text(encoding="utf-8")
    except (ValueError, OSError) as error:
        print(f"upgrade_guide.py show: {error}", file=sys.stderr)
        return 2
    found = sections(text, args.name, running, newest)
    if not found:
        print(f"{args.name}: no section of {args.guide.as_posix()} lies between "
              f"{'.'.join(map(str, running))} and {'.'.join(map(str, newest))}")
        return 0
    print(f"{args.name}: {len(found)} section(s) of {args.guide.as_posix()}, follow in order: "
          + ", ".join(s.title for s in found) + "\n")
    print("\n".join(s.text for s in found), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
