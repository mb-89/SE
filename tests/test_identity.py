"""The identity step (`work_tickets.py identity`, as setup, the session start and sync run it):
the checkout's local config carries the project identity and commits unsigned, so a host's global
`commit.gpgsign` signs nothing with a key that matches no project identity (docs/settings.md
"Project settings")."""

from __future__ import annotations

from pathlib import Path

import fake_git
import git_door
import work_tickets


def test_the_identity_step_sets_the_project_identity_and_turns_signing_off(fake_git_door, tmp_path: Path) -> None:
    root = fake_git.init(tmp_path / "project", "-b", "main")
    (root / "se.toml").write_text('[project]\nidentity = "alice <alice@example.com>"\n', encoding="utf-8")
    git_door.run("config", "commit.gpgsign", "true", root=root)

    assert work_tickets.main(["identity", "--worktree", str(root)]) == 0

    def local(key: str) -> str:
        return git_door.run("config", "--local", "--get", key, root=root).stdout.strip()

    assert (local("user.name"), local("user.email")) == ("alice", "alice@example.com")
    assert local("commit.gpgsign") == "false"
