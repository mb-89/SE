"""scripts/claude_settings.py: the permission rules SE merges into a repository's
`.claude/settings.json`, so a release passes a session's permission check (issue: releases follow
the work)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_settings  # noqa: E402


def allows(rules: list[str], command: str) -> bool:
    """Whether one of the Claude Code Bash rules allows `command`: `*` stands for any text, and a
    prefix rule `<prefix>:*` for the prefix and any arguments after it."""
    for rule in rules:
        found = re.fullmatch(r"Bash\((.*)\)", rule)
        if found is None:
            continue
        pattern = found[1]
        if pattern.endswith(":*"):
            prefix = pattern[:-2]
            if command == prefix or command.startswith(prefix + " "):
                return True
        elif re.fullmatch(".*".join(map(re.escape, pattern.split("*"))), command):
            return True
    return False


def test_each_rule_alone_allows_the_cloud_release() -> None:
    cloud = "uv run python /root/.claude/skills/se/scripts/work_tickets.py release --worktree /home/user/obs"
    for rule in claude_settings.ALLOW:
        assert allows([rule], cloud), rule
        assert not allows([rule], cloud.replace(" release ", " integrate ")), rule


def test_rules_prints_the_rules_for_an_integrator_session(capsys) -> None:
    assert claude_settings.main(["rules"]) == 0
    assert json.loads(capsys.readouterr().out) == list(claude_settings.ALLOW)


RELEASES = [
    "uv run python /root/.claude/skills/se/scripts/work_tickets.py release --worktree /home/user/obs",
    "uv run python ~/.claude/skills/se/scripts/work_tickets.py release --worktree . --read-back v10.4.0",
    "uv run python .se/modules/se/scripts/work_tickets.py release --worktree /work/obs --repo alice/obs",
    "uv run python scripts/work_tickets.py release --worktree /home/user/SE",
]
OTHERS = [
    "uv run python scripts/work_tickets.py integrate --worktree . 12",
    "uv run python scripts/work_tickets.py release-trailer --issue-body body.md feature",
    "uv run python scripts/rewrite_history.py --repo .",
]


def settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_allow_writes_a_rule_that_passes_every_release_and_nothing_else(tmp_path: Path) -> None:
    assert claude_settings.main(["allow", "--repo", str(tmp_path)]) == 0
    rules = settings(tmp_path)["permissions"]["allow"]
    assert rules == list(claude_settings.ALLOW)
    for command in RELEASES:
        assert allows(rules, command), command
    for command in OTHERS:
        assert not allows(rules, command), command


def test_allow_keeps_every_other_key_and_rule_and_adds_nothing_twice(tmp_path: Path, capsys) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"model": "x", "permissions": {"allow": ["Read(docs/**)"], "deny": ["Bash(rm:*)"]}}),
                    encoding="utf-8")
    assert claude_settings.main(["allow", "--repo", str(tmp_path)]) == 0
    assert "allows SE's release" in capsys.readouterr().out
    written = path.read_text(encoding="utf-8")
    assert claude_settings.main(["allow", "--repo", str(tmp_path)]) == 0
    assert "already allows SE's release" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == written
    assert settings(tmp_path) == {"model": "x", "permissions": {"allow": ["Read(docs/**)", *claude_settings.ALLOW],
                                                                "deny": ["Bash(rm:*)"]}}


@pytest.mark.parametrize("text, refusal", [
    ("{not json", "not JSON"),
    ("[]", "no JSON object"),
    ('{"permissions": []}', "`permissions` is no object"),
    ('{"permissions": {"allow": "Bash(x)"}}', "`permissions.allow` is no list"),
])
def test_allow_refuses_a_file_it_cannot_merge_into_and_writes_nothing(tmp_path: Path, capsys, text: str,
                                                                     refusal: str) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    assert claude_settings.main(["allow", "--repo", str(tmp_path)]) == 1
    assert refusal in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == text

