#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Claude Code's project settings SE writes: the permission rules a repository's
`.claude/settings.json` needs so that SE's steps that run without a person pass a session's
permission check, auto mode's among them.

    claude_settings.py allow --repo <repo>
    claude_settings.py rules

`allow` merges `ALLOW` into `<repo>/.claude/settings.json` `permissions.allow`, keeping every other
key and rule and the order of those already there; a rule already present is not added again.
Exit code 0 written or already in place, 1 a file it cannot merge into (nothing is written).

`rules` prints `ALLOW` as one JSON list, the `extra_allowed_tools` SE gives each integrator session
it starts with `create_session` (se.md "Sessions"): a release SE asks for comes as a message from
another session, which auto mode's check does not count as the person's, so the integrator's own
session carries the rule. Exit code 0.

It widens what every session of the repository may run, so it is a step only the person approves
(the work model's "Steps only the person approves"): the person, or SE on the person's yes, runs it
once per repository and commits the file, as a cloud session reads only what its clone holds. No
setup step and no agent's own session runs it: auto mode's check refuses a session that widens its
own permissions ("Undermining Oversight"), and setup would stop at it.

`ALLOW` is the one list. A release is the integrator's step on SE's message, never a question to
the person (the work model's "Roles and flow"), so it runs in a session no one watches:
`work_tickets.py release` and its `--read-back`, wherever se's scripts live (the plugin's
`~/.claude/skills/se`, a module's `.se/modules/se`, se's own `scripts/`), and in the prefix form
for the path a cloud session runs se from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
import se_script

SETTINGS = PurePosixPath(".claude/settings.json")
#: The permission rules SE needs in every repository and integrator session, each a Claude Code
#: rule. In the first `*` stands for any text, so it holds every path of se's scripts and every
#: argument of a release (`--worktree`, `--repo`, `--read-back <tag>`); the second is the prefix
#: rule (`:*`) for the plugin's path in a cloud session, `/root/.claude/skills/se`.
ALLOW = ("Bash(uv run python *work_tickets.py release *)",
         "Bash(uv run python /root/.claude/skills/se/scripts/work_tickets.py release:*)")


class SettingsError(Exception):
    """A settings file `allow` cannot merge into; the message names it and nothing is written."""


def merged(existing: dict) -> dict:
    """`existing` with every rule of `ALLOW` in `permissions.allow`, every other key kept."""
    permissions = existing.get("permissions", {})
    if not isinstance(permissions, dict):
        raise SettingsError(f"{SETTINGS}: `permissions` is no object")
    rules = permissions.get("allow", [])
    if not isinstance(rules, list):
        raise SettingsError(f"{SETTINGS}: `permissions.allow` is no list")
    return {**existing, "permissions": {**permissions, "allow": rules + [r for r in ALLOW if r not in rules]}}


def allow(repo: Path) -> str:
    """Merge `ALLOW` into the repository's settings; the line to print."""
    path = repo / SETTINGS
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError as error:
        raise SettingsError(f"{SETTINGS}: not JSON ({error.msg}, line {error.lineno}); fix it and "
                            "run setup again") from error
    if not isinstance(existing, dict):
        raise SettingsError(f"{SETTINGS}: no JSON object")
    wanted = merged(existing)
    if wanted == existing:
        return f"{SETTINGS}: already allows SE's release"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")
    return f"{SETTINGS}: allows SE's release ({', '.join(ALLOW)})"


def main(argv: list[str] | None = None) -> int:
    parser = se_script.parser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    allow_parser = commands.add_parser("allow", help="merge SE's permission rules into the repository's "
                                                     ".claude/settings.json")
    allow_parser.add_argument("--repo", type=Path, required=True)
    commands.add_parser("rules", help="print SE's permission rules as one JSON list, the extra_allowed_tools "
                                      "of an integrator session SE starts")
    args = parser.parse_args(argv)
    if args.command == "rules":
        print(json.dumps(list(ALLOW)))
        return 0
    try:
        print(f"claude settings: {allow(args.repo)}")
    except SettingsError as error:
        print(f"claude settings: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
