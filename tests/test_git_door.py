"""The git door's contract (scripts/git_door.py): what SE's code relies on git to do, held once
against real git and against the fake every other test uses (tests/fake_git.py). This file is the
only test that runs real git on purpose; its real run sets its own home, global config and
identity, so a runner's bare git config cannot change what it sees (rule book des-004, tst-001).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import fake_git
import git_door
import quiet_git
import work_tickets  # scripts/ is on the path (tests/conftest.py)

SHA = re.compile(r"[0-9a-f]{40}")
IDENTITY = ("alice", "alice@example.com")
RUNNER_VARIABLES = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                    "GIT_COMMITTER_EMAIL", "EMAIL", "GIT_DIR", "GIT_WORK_TREE")


def isolated_git(home: Path) -> git_door.RealGit:
    """Real git with nothing of the machine's configuration: like CI's bare runner, it knows no
    identity, and it may not guess one."""
    home.mkdir(parents=True, exist_ok=True)
    config = home / "gitconfig"
    config.write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    return git_door.RealGit({"HOME": str(home), "XDG_CONFIG_HOME": str(home),
                             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(config),
                             **{name: None for name in RUNNER_VARIABLES}})


@pytest.fixture(params=["fake", "real"])
def door(request, tmp_path: Path):
    backend = fake_git.FakeGit() if request.param == "fake" else isolated_git(tmp_path / "home")
    with git_door.use(backend):
        yield request.param


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, f"git {' '.join(arguments)}: {result.stderr.strip()}"
    return result.stdout.strip()


def commit(root: Path, files: dict[str, str], message: str = "change") -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def project(tmp_path: Path) -> Path:
    root = quiet_git.init(tmp_path / "project", "-b", "main")
    assert git_door.set_identity(root, IDENTITY) is None
    return root


# The identity a commit carries


def test_a_commit_and_a_merge_without_an_identity_are_refused(door, tmp_path: Path) -> None:
    root = quiet_git.init(tmp_path / "project", "-b", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    git(root, "add", "-A")
    refused = git_door.run("commit", "-q", "-m", "first", root=root)
    assert refused.returncode != 0 and "identity" in refused.stderr.lower()
    git(root, "-c", f"user.name={IDENTITY[0]}", "-c", f"user.email={IDENTITY[1]}", "commit", "-q", "-m", "first")
    git(root, "switch", "-q", "-c", "side")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", f"user.name={IDENTITY[0]}", "-c", f"user.email={IDENTITY[1]}", "commit", "-q", "-m", "side")
    git(root, "switch", "-q", "main")
    merged = git_door.run("merge", "-q", "--no-ff", "-m", "merge", "side", root=root)
    assert merged.returncode != 0 and "identity" in merged.stderr.lower()


def test_a_commit_carries_the_identity_the_door_sets_or_the_environment_names(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    commit(root, {"a.txt": "a\n"})
    assert git(root, "log", "-1", "--format=%an <%ae>") == "alice <alice@example.com>"
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    git(root, "add", "-A")
    environment = git_door.identity_environment(("bob", "bob@example.com"))
    assert git_door.run("commit", "-q", "-m", "by bob", root=root, env=environment).returncode == 0
    assert git(root, "log", "-1", "--format=%an <%ae> %cn <%ce>") == "bob <bob@example.com> bob <bob@example.com>"


# Reading a repository


def test_rev_parse_names_commits_trees_branches_and_the_git_directory(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n"})
    assert SHA.fullmatch(first)
    missing = git_door.run("rev-parse", "--verify", "--quiet", "refs/tags/v9^{commit}", root=root)
    assert (missing.returncode, missing.stdout) == (1, "")
    tree = git(root, "rev-parse", "--verify", "--quiet", "HEAD^{tree}")
    second = commit(root, {"b.txt": "b\n"})
    assert git(root, "rev-parse", "HEAD~1") == first and git(root, "rev-parse", "--short=12", second) == second[:12]
    assert git(root, "rev-parse", f"{second}^{{tree}}") != tree
    (root / "b.txt").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "back")
    assert git(root, "rev-parse", "HEAD^{tree}") == tree, "the same files are the same tree"
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    assert (common if common.is_absolute() else root / common).resolve() == (root / ".git").resolve()


def test_show_reads_a_file_at_a_commit_and_refuses_a_missing_one(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"se.toml": "[tests]\n", "dir/b.txt": "b\n"})
    commit(root, {"se.toml": "[project]\n"})
    assert git_door.run("show", f"{first}:se.toml", root=root).stdout == "[tests]\n"
    assert git_door.run("show", "HEAD:dir/b.txt", root=root, binary=True).stdout == b"b\n"
    assert git_door.run("show", "HEAD:none.txt", root=root).returncode != 0


def test_config_sets_and_gets_and_a_missing_key_fails(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    assert git(root, "config", "--get", "user.name") == "alice"
    assert git_door.run("config", "--get", "se.none", root=root).returncode != 0
    assert git_door.run("remote", "get-url", "origin", root=root).returncode != 0
    git(root, "remote", "add", "origin", "https://github.com/alice/project.git")
    assert git(root, "remote", "get-url", "origin") == "https://github.com/alice/project.git"


# Branches, merges and the main line


def test_switch_brings_the_branch_files_and_a_no_ff_merge_makes_the_main_line(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n"}, "first landing")
    git(root, "update-ref", "refs/remotes/origin/main", "main")
    git(root, "switch", "-q", "-c", "land/b")
    head = commit(root, {"b.txt": "b\n", "a.txt": "a2\n"}, "land b")
    git(root, "switch", "-q", "main")
    assert (root / "a.txt").read_text(encoding="utf-8") == "a\n" and not (root / "b.txt").exists()
    git(root, "merge", "-q", "--no-ff", "-m", "merge", head)
    assert (root / "b.txt").read_text(encoding="utf-8") == "b\n"
    merge = git(root, "rev-parse", "HEAD")
    assert git(root, "rev-list", "--count", "--first-parent", "main") == "2"
    assert git(root, "rev-list", "--first-parent", "--max-count=5", "main").split() == [merge, first]
    assert git(root, "rev-parse", "refs/remotes/origin/main") == first
    assert git(root, "rev-list", "--count", "HEAD", "--not", "--remotes", "--tags") == "2"


def test_a_conflicting_merge_fails_naming_the_file(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    commit(root, {"a.txt": "a\n"})
    git(root, "switch", "-q", "-c", "side")
    side = commit(root, {"a.txt": "side\n"})
    git(root, "switch", "-q", "main")
    commit(root, {"a.txt": "main\n"})
    conflict = git_door.run("merge", "-q", "-m", "merge", side, root=root)
    assert conflict.returncode != 0 and "a.txt" in conflict.stdout + conflict.stderr
    git(root, "merge", "--abort")


# Remotes


def test_push_fetch_and_ls_remote_against_a_bare_origin(door, tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    root = project(tmp_path)
    git(root, "remote", "add", "origin", str(origin))
    first = commit(root, {"a.txt": "a\n"})
    git(root, "tag", "v1.0.0")
    assert work_tickets.run_git_push(root, ["-q", "origin", "main", "refs/tags/v1.0.0"]).returncode == 0
    listed = git_door.run("ls-remote", "--tags", "--refs", origin.as_uri(), no_prompt=True).stdout
    assert listed.splitlines() == [f"{first}\trefs/tags/v1.0.0"]
    other = project(tmp_path / "other")
    git(other, "remote", "add", "origin", str(origin))
    git(other, "fetch", "-q", "origin", "refs/tags/v1.0.0:refs/tags/v1.0.0")
    assert git(other, "rev-parse", "v1.0.0^{commit}") == first
    commit(other, {"x.txt": "x\n"})
    refused = git_door.push(other, ["-q", "origin", "HEAD:refs/heads/main"])
    assert refused.returncode != 0
    assert work_tickets.push_refusal(refused.stderr + refused.stdout) == ("non-fast-forward", False)


def test_ls_remote_of_a_missing_remote_fails(door, tmp_path: Path) -> None:
    missing = git_door.run("ls-remote", "--tags", "--refs", (tmp_path / "none.git").as_uri(), no_prompt=True)
    assert missing.returncode != 0 and missing.stdout == ""
