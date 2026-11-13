"""The `se` command: `uv run python <se>/scripts/se.py <command>`. Each command's module owns what it
does; this file only names them (README "New application")."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _sibling(name: str):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


#: se.py's commands as one kern component (README "Commands as components"); each command's usage
#: and help come from make_parser.
COMPONENTS = (_sibling("se_components").Group(
    "scaffold", "Scaffold",
    "What SE scaffolds: a new application on kern, and an ad hoc component in a checkout.",
    ("new app", "component add")),)
#: The commands that go through kern where it runs (se_components.routed): none, as both write.
INTERACTIVE_COMMANDS: frozenset[str] = frozenset()


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="se.py", description="SE's commands.")
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
    routed = _sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        " ".join(words) in INTERACTIVE_COMMANDS)
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
    sys.exit(main())
