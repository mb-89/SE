"""scripts/rewrite_history.py: the one-time history rewrite before se replaces main."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import rewrite_history
from quiet_git import quiet

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "public_check.py"
CLAUDE = ("Claude", "noreply" + "@anthropic.com")
WEB_FLOW = ("GitHub", "noreply" + "@github.com")
OWNER = ("mb", "mb")


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Git without the machine's configuration (no signing, no identity), and no ~/.se."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    for key, value in {"HOME": str(home), "GIT_CONFIG_GLOBAL": str(gitconfig),
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                       "GIT_ALLOW_PROTOCOL": "file"}.items():
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str, who: tuple[tuple[str, str], tuple[str, str]] | None = None) -> str:
    env = dict(os.environ)
    if who is not None:
        (an, ae), (cn, ce) = who
        env.update(GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae, GIT_COMMITTER_NAME=cn,
                   GIT_COMMITTER_EMAIL=ce)
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=env).stdout.strip()


def commit(repo: Path, name: str, message: str, author=OWNER, committer=OWNER) -> str:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message, who=(author, committer))
    return git(repo, "rev-parse", "HEAD")


def build(root: Path) -> None:
    """An se-like history: a clean root, a release by Claude with its session trailers, a commit with
    tracker references and a co-author line, a merge GitHub committed, lightweight and annotated
    tags, and a published commit's allow entry."""
    origin = root / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    quiet(origin)
    (origin / "se.toml").write_text('[project]\nidentity = "mb <mb>"\n', encoding="utf-8")
    git(origin, "add", "se.toml")
    git(origin, "commit", "-q", "-m", "Start", who=(OWNER, OWNER))
    git(origin, "tag", "v0.1.0")
    released = commit(origin, "release.txt", "Release v1.0.1\n\nCo-Authored-By: Claude <"
                      + CLAUDE[1] + ">\nClaude-Session: https://claude.ai/code/session_x\n",
                      author=CLAUDE, committer=CLAUDE)
    git(origin, "tag", "v1.0.1")
    git(origin, "switch", "-q", "-c", "feature")
    commit(origin, "feature.txt", "Add the feature (#593, requirement 3)\n\nIt follows #12, as "
           "asked (#7).\n\nco-authored-by: Copilot <copilot@example.com>\n")
    git(origin, "switch", "-q", "main")
    git(origin, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature", who=(OWNER, WEB_FLOW))
    (origin / ".public-check-allow").write_text(
        f"commit:{released} author  # published before the identity rule\n", encoding="utf-8")
    git(origin, "add", ".public-check-allow")
    git(origin, "commit", "-q", "-m", "Allow the published release", who=(OWNER, OWNER))
    git(origin, "tag", "-a", "-m", "Release v1.0.2", "v1.0.2", who=(OWNER, OWNER))
    git(origin, "tag", "v1")


@pytest.fixture
def clone(tmp_path, repositories) -> Path:
    repositories(build, tmp_path)
    fresh = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--no-local", str(tmp_path / "origin"), str(fresh))
    quiet(fresh)
    git(fresh, "branch", "-q", "feature", "origin/feature")
    return fresh


def gate(repo: Path, revisions: str) -> subprocess.CompletedProcess[str]:
    """The public check's commit gate of a --range over `revisions`."""
    return subprocess.run([sys.executable, str(CHECK), "--repo", str(repo), "--range", revisions],
                          capture_output=True, text=True, check=False)


def identities(repo: Path, revision: str) -> set[str]:
    return set(git(repo, "log", "--format=%an <%ae>|%cn <%ce>", revision).splitlines())


def tag_targets(repo: Path) -> dict[str, str]:
    return {name: git(repo, "rev-parse", f"{name}^{{commit}}")
            for name in git(repo, "tag").splitlines()}


def test_the_rewrite_drops_the_trailers_fixes_the_identity_and_moves_every_tag(clone, capsys):
    assert gate(clone, "main feature").returncode == 1  # the history as published fails the gates
    old_head, old_tree = git(clone, "rev-parse", "main"), git(clone, "rev-parse", "main^{tree}")
    old_tags = tag_targets(clone)

    assert rewrite_history.main(["--repo", str(clone)]) == 0
    out = capsys.readouterr().out

    checked = gate(clone, "main feature")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    messages = [m.lstrip("\n") for m in git(clone, "log", "--format=%B%x00", "main").split("\x00")]
    assert not any("co-authored-by" in m.lower() or "claude-session" in m.lower() for m in messages)
    assert "Add the feature (requirement 3)\n\nIt follows as asked.\n" in messages
    assert identities(clone, "main") == {"mb <mb>|mb <mb>", f"mb <mb>|{WEB_FLOW[0]} <{WEB_FLOW[1]}>"}
    assert git(clone, "rev-parse", "main^{tree}") == old_tree  # same content, new history
    assert git(clone, "status", "--porcelain") == ""

    mapping = dict(line.split() for line in
                   (clone / ".git" / rewrite_history.MAP_FILE).read_text().splitlines())
    new_tags = tag_targets(clone)
    assert new_tags == {name: mapping[old] for name, old in old_tags.items()}
    assert new_tags["v0.1.0"] == old_tags["v0.1.0"]  # the clean root keeps its id
    assert new_tags["v1.0.1"] != old_tags["v1.0.1"]
    assert git(clone, "cat-file", "-t", "v1.0.2") == "tag"  # an annotated tag stays annotated
    assert git(clone, "rev-parse", "main") == mapping[old_head]

    assert "5 commits rewritten, 4 with a new id; 3 trailer lines dropped from 2 commits, " \
           "3 tracker references from 1, the identity 'mb <mb>' set on 1" in out
    assert f"main {old_head[:12]} -> {mapping[old_head][:12]} (same tree)" in out
    assert "3 of 4 tags moved to their rewritten commits" in out
    assert "main: .public-check-allow line 1: commit:" in out and "delete it" in out


@pytest.mark.parametrize(("message", "cleaned"), [
    ("Fix it\n", "Fix it\n"),
    ("Fix it\n\nCo-Authored-By: A <a@example.com>\nClaude-Session: https://example.com/s\n",
     "Fix it\n"),
    ("Fix it\n\nBody.\n\nco-authored-by: A\n\nMore.\n", "Fix it\n\nBody.\n\nMore.\n"),
    ("Fix (#593, requirement 2)\n", "Fix (requirement 2)\n"),
    ("Fix (#593)\n", "Fix\n"),
    ("Fix it, as GH-4 asked, #5\n", "Fix it, as asked\n"),
    ("C# 5 and &#39; stay\n", "C# 5 and &#39; stay\n"),
])
def test_a_message_loses_only_its_trailers_and_tracker_references(message, cleaned):
    assert rewrite_history.clean_message(message)[0] == cleaned


def test_a_shallow_clone_is_refused_naming_the_fetch(clone, tmp_path, capsys):
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", clone.as_uri(), str(shallow))
    quiet(shallow)
    assert rewrite_history.main(["--repo", str(shallow)]) == 2
    assert "fetch --unshallow" in capsys.readouterr().err


def test_local_changes_are_refused_and_nothing_moves(clone, capsys):
    (clone / "se.toml").write_text("changed\n", encoding="utf-8")
    head = git(clone, "rev-parse", "main")
    assert rewrite_history.main(["--repo", str(clone)]) == 2
    assert "has local changes" in capsys.readouterr().err
    assert git(clone, "rev-parse", "main") == head
