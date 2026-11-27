#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""The `se` command: `uv run python <se>/scripts/se.py <command>`. Each command's module owns what it
does; this file only names them (docs/applications.md "New application")."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import se_script


_sibling = se_script.loader(__file__)


#: se.py's commands as one kern component (docs/start.md "Commands as components"); each command's usage
#: and help come from make_parser.
COMPONENTS = (_sibling("se_components").Group(
    "scaffold", "Scaffold",
    "What SE scaffolds: a new application on kern, and an ad hoc component in a checkout.",
    ("new app", "component add")),)
#: The commands that go through kern where it runs (se_components.routed): none, as both write.
INTERACTIVE_COMMANDS: frozenset[str] = frozenset()


def make_parser() -> argparse.ArgumentParser:
    top = se_script.parser(prog="se.py", description="SE's commands.")
    commands = top.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create something new").add_subparsers(dest="what", required=True)
    app = new.add_parser("app", help="create an application on kern from kern's template at SE's kern pin")
    app.add_argument("name", help="the application's name: lower-case letters, digits and dashes")
    app.add_argument("--path", required=True, type=Path, help="the new or empty folder it is created in")
    component = commands.add_parser("component", help="work with the checkout's components").add_subparsers(dest="action", required=True)
    add = component.add_parser("add", help="scaffold an ad hoc component under the ignored .se/components/")
    add.add_argument("name", help="the component's name: lower-case letters, digits and dashes")
    add.add_argument("--root", type=Path, help="the checkout it is added to (default: the one holding the working directory)")
    return top


def _checkout(start: Path) -> Path:
    """The checkout `start` is in: the nearest folder up that holds .git, else `start` itself."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return start


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    words = [args.command, args.what if args.command == "new" else args.action]
    routed = se_script.route(__file__, words, argv, INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    if args.command == "component":
        se_component = _sibling("se_component")
        root = (args.root or _checkout(Path.cwd())).resolve()
        try:
            lines = se_component.add(root, args.name)
        except se_component.ComponentError as error:
            print(f"se component add: {error}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        return 0
    se_new = _sibling("se_new")
    try:
        lines = se_new.create(args.name, args.path.resolve())
    except (se_new.NewError, _sibling("se_modules").ModuleError) as error:
        print(f"se new app: {error}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
