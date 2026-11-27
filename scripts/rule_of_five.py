#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""The rule of five (rule book doc-006): a surface a person sees holds at most five visible files
and five visible folders, checked.

- **Surfaces.** The root, `spec/` and `src/` of a checkout (SURFACES), each where it exists; a
  project names others in `se.toml` `[rule_of_five] surfaces`, paths relative to its root.
- **Visible.** An entry whose name does not start with a dot. The check reads the working tree as
  it is: the commit hook runs it on a copy of the staged tree (se.toml `[commit_checks]`), CI on a
  fresh checkout.
- **Level.** The rule's day-one path, no baseline: `se.toml` `[rule_of_five] level`, `error` where
  unset. At `error` each crowded surface is printed and refused. At `warn` each one is printed as a
  warning line and passes while the crowded surfaces are restructured; a `warn` level that finds no
  crowded surface is refused, naming the step left, `level = "error"`, so the rule never stays a
  warning once it holds.

`rule_of_five.py check [--root ROOT]` checks the checkout: exit code 0 passed, 1 refused, 2 a
setting cannot be read, naming it. SE runs it at commit (se.toml `[commit_checks]`) and in CI
(`scripts/hygiene.py`, its check `rule-of-five`).

Standard library only, and it reads files only: no git, no network, no subprocess.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import se_script

LIMIT = 5
SURFACES = (".", "spec", "src")
TABLE = "rule_of_five"
WARN, ERROR = "warn", "error"
LEVELS = (WARN, ERROR)
SETTINGS = "se.toml"


class SettingError(Exception):
    """A `[rule_of_five]` table the check cannot run from."""


@dataclass(frozen=True)
class Settings:
    level: str = ERROR
    surfaces: tuple[str, ...] = SURFACES


def settings(root: Path) -> Settings:
    """The checkout's `[rule_of_five]` settings; a missing `se.toml` or table is the defaults."""
    path = root / SETTINGS
    if not path.is_file():
        return Settings()
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get(TABLE, {})
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise SettingError(f"{SETTINGS}: {error}") from error
    if not isinstance(table, dict):
        raise SettingError(f"{SETTINGS}: [{TABLE}] must be a table")
    unknown = sorted(set(table) - {"level", "surfaces"})
    if unknown:
        raise SettingError(f"{SETTINGS}: [{TABLE}] has unknown key(s) {', '.join(unknown)}; "
                           "the keys are level and surfaces")
    level = table.get("level", ERROR)
    if level not in LEVELS:
        raise SettingError(f"{SETTINGS}: [{TABLE}] level must be one of {', '.join(LEVELS)}")
    surfaces = table.get("surfaces", list(SURFACES))
    if not (isinstance(surfaces, list) and surfaces and all(isinstance(s, str) and s for s in surfaces)):
        raise SettingError(f"{SETTINGS}: [{TABLE}] surfaces must be a non-empty array of paths")
    return Settings(level, tuple(surfaces))


def crowded(root: Path, surface: str) -> str | None:
    """What crowds `surface` of `root`, or None where it holds the rule or does not exist."""
    folder = root / surface
    if not folder.is_dir():
        return None
    visible = [entry for entry in folder.iterdir() if not entry.name.startswith(".")]
    files = sorted(entry.name for entry in visible if not entry.is_dir())
    folders = sorted(entry.name for entry in visible if entry.is_dir())
    over = [f"{len(names)} visible {kind} ({', '.join(names)})"
            for kind, names in (("files", files), ("folders", folders)) if len(names) > LIMIT]
    if not over:
        return None
    name = "the root" if surface in (".", "") else f"{surface.rstrip('/')}/"
    return f"{name} holds {' and '.join(over)}; at most {LIMIT} of each (rule book doc-006)"


def check(root: Path, found: Settings) -> tuple[list[str], list[str]]:
    """The warning lines and the refusals of the check of `root` at `found`'s level."""
    crowd = [line for surface in found.surfaces if (line := crowded(root, surface))]
    if found.level == ERROR:
        return [], crowd
    if not crowd:
        return [], [f"no crowded surface left at level warn: set level = \"error\" in {SETTINGS} [{TABLE}]"]
    return [f"warning: {line}" for line in crowd], []


def main(argv: list[str] | None = None) -> int:
    parser = se_script.parser(prog="rule_of_five.py", description="The rule of five (rule book "
                              "doc-006): at most five visible files and five visible folders on "
                              "each surface a person sees.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("check", help="refuse a crowded surface at its level; exit code 1 "
                              "with each finding")
    run.add_argument("--root", type=Path, default=Path.cwd(), help="the checkout (default: here)")
    args = parser.parse_args(argv)
    try:
        found = settings(args.root)
    except SettingError as error:
        print(f"rule_of_five.py: {error}", file=sys.stderr)
        return 2
    warnings, refused = check(args.root, found)
    for line in warnings + refused:
        print(f"rule_of_five.py: {line}")
    if refused:
        return 1
    print(f"rule_of_five.py: passed at level {found.level} in {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
