"""Standalone validators for agent and skill files: a file in, its findings out, for any repository.

`copilot_agent` holds a Copilot custom agent (`<name>.agent.md`) to Copilot's fields;
`skill` holds a skill (`<name>/SKILL.md`) to the agentskills.io rules. Each takes the file's path
and text and returns one line per finding, naming the path; none means the host loads it. The SE
build (scripts/se_plugin.py) runs them on its generated layouts.

    agent_lint.py <file>...    exit code 0 without findings, 1 with them, 2 for an unreadable file
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePath

# Copilot's custom agent fields: VS Code's custom agent file reference and the Copilot CLI's and cloud
# agent's own (the dispatcher's fact-check of 14 Nov). `handoffs` and `agents` work only in VS Code's
# local harness and are not offered. An unknown tool name is no finding: Copilot ignores it.
COPILOT_AGENT_FIELDS = frozenset({
    "name", "description", "tools", "model", "model-policy", "hooks", "target", "user-invocable",
    "disable-model-invocation", "argument-hint", "skills", "mcp-servers", "metadata", "reasoning-effort",
    "deferred-tool-loading", "include-custom-instructions", "github", "strict-tools-list"})
COPILOT_TARGETS = frozenset({"vscode", "github-copilot"})
# The agentskills.io rules: a name of lowercase letters, digits and single hyphens, at most 64
# characters, equal to its folder (VS Code skips a skill whose name breaks them); a description of
# at most 1024 characters.
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX = 64
SKILL_DESCRIPTION_MAX = 1024


def fields(text: str) -> dict[str, str]:
    """The front matter of a Markdown file, one `key: value` per line, each value as written; a
    checkout with CRLF line endings (git on Windows) reads as one with LF."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    head = text[4:end if end >= 0 else len(text)]
    return {key.strip(): value.strip() for key, sep, value in (line.partition(":") for line in head.splitlines())
            if sep}


def scalar(value: str) -> str:
    """A YAML scalar as front matter writes one: plain, 'single-quoted' or "double-quoted"."""
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except ValueError:
            return value[1:-1]
    return value


def copilot_agent(path: PurePath, text: str) -> list[str]:
    """The findings of one Copilot custom agent file."""
    found = fields(text)
    findings = [f"{path}: {key} is no Copilot agent field" for key in found if key not in COPILOT_AGENT_FIELDS]
    if not scalar(found.get("description", "")):
        findings.append(f"{path}: a Copilot agent needs a description")
    if "target" in found and scalar(found["target"]) not in COPILOT_TARGETS:
        findings.append(f"{path}: target is one of {', '.join(sorted(COPILOT_TARGETS))}")
    return findings


def skill(path: PurePath, text: str) -> list[str]:
    """The findings of one SKILL.md, whose folder is the skill's."""
    found = fields(text)
    name, description = scalar(found.get("name", "")), scalar(found.get("description", ""))
    findings = []
    if not SKILL_NAME.match(name) or len(name) > SKILL_NAME_MAX:
        findings.append(f"{path}: skill name {name!r} is not 1 to {SKILL_NAME_MAX} lowercase letters, digits "
                        "and single hyphens")
    if name != path.parent.name:
        findings.append(f"{path}: skill name {name!r} differs from its folder {path.parent.name!r}")
    if not description or len(description) > SKILL_DESCRIPTION_MAX:
        findings.append(f"{path}: skill description has {len(description)} characters, not 1 to "
                        f"{SKILL_DESCRIPTION_MAX}")
    return findings


def lint(path: PurePath, text: str) -> list[str]:
    """The findings of a file by its kind: a `SKILL.md`, a `*.agent.md`; nothing for any other."""
    if path.name == "SKILL.md":
        return skill(path, text)
    if path.name.endswith(".agent.md"):
        return copilot_agent(path, text)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_lint.py", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="a Copilot `*.agent.md` or a skill's `SKILL.md`")
    args = parser.parse_args(argv)
    findings = []
    for path in args.files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            print(f"error: agent_lint.py: {path}: {error}", file=sys.stderr)
            return 2
        findings += lint(path, text)
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
