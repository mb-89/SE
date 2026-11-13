"""The git door's contract (scripts/git_door.py): what SE's code relies on git to do, held once
against real git and against the fake every other test uses (tests/fake_git.py). This file is the
only test that runs real git on purpose; its real run sets its own home, global config and
identity, so a runner's bare git config cannot change what it sees (rule book des-004, tst-001).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fake_git
import git_door
import quiet_git
import work_tickets  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]
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


@pytest.fixture(params=["fake", "state", "real"])
def door(request, tmp_path: Path):
    """The door's backend for one contract case: the fake in memory, the fake behind a state file
    as the door's variable names it (what a child process gets), or real git."""
    if request.param == "fake":
        backend = fake_git.FakeGit()
    elif request.param == "state":
        backend = git_door.from_environment({git_door.VARIABLE: f"fake:{tmp_path / 'git-door.json'}"})
        assert isinstance(backend, fake_git.StateFile)
    else:
        backend = isolated_git(tmp_path / "home")
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
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD") == "main" == git(root, "branch", "--show-current")
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
    assert git(root, "remote") == ""
    git(root, "remote", "add", "origin", "https://github.com/alice/project.git")
    assert git(root, "remote", "get-url", "origin") == "https://github.com/alice/project.git"
    assert git(root, "remote") == "origin"


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


def test_clone_brings_the_branches_and_tags_and_checks_out_the_branch_asked(door, tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    empty = quiet_git.clone(origin, tmp_path / "empty")
    assert git_door.set_identity(empty, IDENTITY) is None
    first = commit(empty, {"a.txt": "a\n"})
    git(empty, "push", "-q", "origin", "main")
    assert git(empty, "rev-parse", "refs/remotes/origin/main") == first, "a push moves the tracking ref"
    git(empty, "switch", "-q", "-c", "feat/x")
    feature = commit(empty, {"b.txt": "b\n"})
    git(empty, "tag", "v1.0.0")
    git(empty, "push", "-q", "origin", "feat/x", "refs/tags/v1.0.0")
    clone = quiet_git.clone(origin, tmp_path / "clone", "-b", "main")
    assert (clone / "a.txt").read_text(encoding="utf-8") == "a\n" and not (clone / "b.txt").exists()
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(clone, "rev-parse", "refs/remotes/origin/feat/x") == feature
    assert git(clone, "rev-parse", "v1.0.0^{commit}") == feature
    git(clone, "fetch", "-q", "origin", "+refs/heads/feat/x:refs/remotes/origin/feat/x")
    assert git_door.run("clone", "-q", str(tmp_path / "none.git"), str(tmp_path / "nothing")).returncode != 0


def test_log_formats_the_dates_subjects_and_changed_paths(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    when = {"GIT_AUTHOR_DATE": "2026-11-02T10:00:00Z", "GIT_COMMITTER_DATE": "2026-11-02T10:00:00+00:00"}
    commit(root, {"a.txt": "a\n", "b.txt": "b\n"}, "first")
    (root / "a.txt").write_text("a2\n", encoding="utf-8")
    git(root, "add", "-A")
    environment = {**git_door.identity_environment(IDENTITY), **when}
    assert git_door.run("commit", "-q", "-m", "second", root=root, env=environment).returncode == 0
    second = git(root, "rev-parse", "HEAD")
    sha, date, subject = git(root, "log", "-1", "--format=%H%x09%cI%x09%s").split("\t")
    # git prints a UTC %cI as +00:00 (2.43) or Z (2.56.1, CI's runner): the instant is the contract.
    when = datetime.fromisoformat(date.replace("Z", "+00:00"))
    assert (sha, when, subject) == (second, datetime(2026, 11, 2, 10, tzinfo=timezone.utc), "second")
    assert git(root, "log", "--first-parent", "--format=%s", "HEAD").splitlines() == ["second", "first"]
    names = git_door.run("log", "--format=%x00%ct", "--name-only", "HEAD", root=root).stdout
    assert names.startswith("\0" + "1793613600\n\na.txt\n\0"), names
    assert names.endswith("\n\na.txt\nb.txt\n")


def test_cat_file_merge_base_and_diff_compare_two_commits(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    base = commit(root, {"a.txt": "a\n", "gone.txt": "g\n"})
    assert git_door.run("cat-file", "-e", f"{base}^{{commit}}", root=root).returncode == 0
    assert git_door.run("cat-file", "-e", f"{'0' * 40}^{{commit}}", root=root).returncode != 0
    git(root, "switch", "-q", "-c", "feat/x")
    (root / "gone.txt").unlink()
    head = commit(root, {"a.txt": "a2\n", "new.py": "def feature():\n    return 42\n"})
    git(root, "switch", "-q", "main")
    commit(root, {"main.txt": "m\n"})
    assert git(root, "merge-base", "main", head) == base
    diff = git(root, "diff", f"{base}..{head}").splitlines()
    assert [line for line in diff if line.startswith("diff --git")] == [
        "diff --git a/a.txt b/a.txt", "diff --git a/gone.txt b/gone.txt", "diff --git a/new.py b/new.py"]
    assert {"-a", "+a2", "-g", "+    return 42", "--- /dev/null", "+++ /dev/null"} <= set(diff)


def test_ls_files_status_and_archive_read_the_tracked_files(door, tmp_path: Path) -> None:
    import io
    import tarfile
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n", "kern/x.go": "package x\n", "kern/t/y.go": "package y\n"})
    assert git_door.run("ls-files", "-z", root=root).stdout.split("\0") == ["a.txt", "kern/t/y.go", "kern/x.go", ""]
    assert git(root, "status", "--porcelain") == ""
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    (root / "new.txt").write_text("new\n", encoding="utf-8")
    assert git_door.run("status", "--porcelain", root=root).stdout.splitlines() == [" M a.txt", "?? new.txt"]
    (root / "kern" / "t" / "new.go").write_text("package t\n", encoding="utf-8")
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (root / "kern" / "out.log").write_text("log\n", encoding="utf-8")
    others = ("ls-files", "--others", "--exclude-standard")
    assert git(root, *others).splitlines() == [".gitignore", "kern/t/new.go", "new.txt"]
    assert git(root / "kern", *others).splitlines() == ["t/new.go"]
    assert git(root / "kern", *others, "--full-name", "--", "t").splitlines() == ["kern/t/new.go"]
    assert git(root, *others, "--", "kern/x.go") == ""
    archive = git_door.run("archive", "--format=tar", first, "kern", root=root, binary=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        files = {member.name: tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()}
    assert files == {"kern/x.go": b"package x\n", "kern/t/y.go": b"package y\n"}


def test_commit_all_takes_the_tracked_files_and_leaves_new_ones(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    commit(root, {"a.txt": "a\n", "b.txt": "b\n"})
    (root / "a.txt").write_text("a2\n", encoding="utf-8")
    (root / "b.txt").unlink()
    (root / "new.txt").write_text("new\n", encoding="utf-8")
    git(root, "commit", "-qam", "all")
    assert git_door.run("show", "HEAD:a.txt", root=root).stdout == "a2\n"
    assert git_door.run("show", "HEAD:b.txt", root=root).returncode != 0
    assert git_door.run("show", "HEAD:new.txt", root=root).returncode != 0
    assert git(root, "status", "--porcelain") == "?? new.txt"


def test_init_without_a_path_makes_the_working_directory_a_repository(door, tmp_path: Path) -> None:
    place = tmp_path / "app"
    place.mkdir()
    assert git_door.run("init", "-q", "-b", "main", cwd=place).returncode == 0
    assert git_door.run("config", "user.name", IDENTITY[0], cwd=place).returncode == 0
    assert git_door.run("branch", "--show-current", cwd=place).stdout.strip() == "main"


# Worktrees, branches and the landing guard's reads


def test_checkout_and_switch_start_a_branch_at_a_commit_and_rm_and_add_stage_paths(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n", "b.txt": "b\n"})
    commit(root, {"a.txt": "a2\n"})
    git(root, "checkout", "-q", "-b", "old", first)
    assert (root / "a.txt").read_text(encoding="utf-8") == "a\n" and git(root, "branch", "--show-current") == "old"
    git(root, "checkout", "-q", "main")
    assert (root / "a.txt").read_text(encoding="utf-8") == "a2\n"
    git(root, "switch", "-q", "-c", "older", first)
    assert git(root, "rev-parse", "HEAD") == first
    assert git_door.run("checkout", "-q", "-b", "old", root=root).returncode != 0, "the branch exists"
    git(root, "rm", "-q", "b.txt")
    assert not (root / "b.txt").exists()
    (root / "a.txt").write_text("staged\n", encoding="utf-8")
    (root / "c.txt").write_text("not staged\n", encoding="utf-8")
    git(root, "add", "a.txt")
    assert git_door.run("status", "--porcelain", root=root).stdout.splitlines() == ["M  a.txt", "D  b.txt", "?? c.txt"]
    assert git_door.run("status", "--porcelain=v1", "-z", "--untracked-files=no", root=root).stdout == "M  a.txt\0D  b.txt\0"
    assert git_door.run("rm", "-q", "none.txt", root=root).returncode != 0


def test_a_worktree_shares_the_branches_and_is_listed_until_it_is_removed(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    base = commit(root, {"a.txt": "a\n"})
    worker = tmp_path / "worker"
    git(root, "worktree", "add", "-q", "-b", "worker", str(worker))
    assert (worker / ".git").is_file() and (worker / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert Path(git(worker, "rev-parse", "--show-toplevel")).resolve() == worker.resolve()
    common = Path(git(worker, "rev-parse", "--git-common-dir"))
    assert (common if common.is_absolute() else worker / common).resolve() == (root / ".git").resolve()
    head = commit(worker, {"b.txt": "b\n"})
    assert git(root, "rev-parse", "worker") == head, "a worktree's commit moves the shared branch"
    detached = tmp_path / "detached"
    git(root, "worktree", "add", "-q", "--detach", str(detached), base)
    listing = git(root, "worktree", "list", "--porcelain").split("\n\n")
    entries = [dict(line.partition(" ")[::2] for line in entry.splitlines()) for entry in listing]
    assert Path(entries[0]["worktree"]).resolve() == root.resolve(), "the main worktree first"
    by_path = {Path(entry["worktree"]).resolve(): entry for entry in entries}
    assert set(by_path) == {root.resolve(), worker.resolve(), detached.resolve()}
    assert by_path[root.resolve()]["branch"] == "refs/heads/main"
    assert (by_path[worker.resolve()]["branch"], by_path[worker.resolve()]["HEAD"]) == ("refs/heads/worker", head)
    assert "branch" not in by_path[detached.resolve()] and "detached" in by_path[detached.resolve()]
    assert by_path[detached.resolve()]["HEAD"] == base
    assert git_door.run("branch", "-D", "worker", root=root).returncode != 0, "a worktree has it out"
    (worker / "untracked.txt").write_text("u\n", encoding="utf-8")
    assert git_door.run("worktree", "remove", str(worker), root=root).returncode != 0, "untracked files"
    git(root, "worktree", "remove", "--force", str(worker))
    git(root, "worktree", "remove", str(detached))
    assert not worker.exists() and not detached.exists()
    assert len(git(root, "worktree", "list", "--porcelain").split("\n\n")) == 1
    git(root, "branch", "-D", "worker")
    assert git_door.run("rev-parse", "--verify", "--quiet", "refs/heads/worker", root=root).returncode != 0


def test_a_three_dot_diff_names_the_branch_changes_since_the_merge_base(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    base = commit(root, {"keep.txt": "same\n", "move.txt": "moved unchanged\n", "drop.txt": "d\n", "edit.txt": "e\n"})
    git(root, "switch", "-q", "-c", "feat/x")
    (root / "move.txt").rename(root / "moved.txt")
    (root / "drop.txt").unlink()
    commit(root, {"edit.txt": "e2\n", "add.txt": "new\n"})
    git(root, "switch", "-q", "main")
    commit(root, {"keep.txt": "main changed it\n"})
    assert git_door.run("merge-base", "--is-ancestor", base, "feat/x", root=root).returncode == 0
    assert git_door.run("merge-base", "--is-ancestor", "feat/x", "main", root=root).returncode == 1
    fields = git_door.run("diff", "--name-status", "-z", "main...feat/x", root=root).stdout.split("\0")
    assert fields == ["A", "add.txt", "D", "drop.txt", "M", "edit.txt", "R100", "move.txt", "moved.txt", ""]
    lines = git(root, "diff", "--unified=0", "main...feat/x").splitlines()
    assert {"-e", "+e2", "-d", "+new"} <= set(lines) and "keep.txt" not in "\n".join(lines)
    assert not [line for line in lines if line[:1] == " "], "no context lines"


def test_a_merge_takes_both_sides_line_changes_and_lists_a_conflict_until_aborted(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    commit(root, {"guide.md": "First.\nMiddle one.\nMiddle two.\nLast.\n", "other.txt": "o\n"})
    git(root, "switch", "-q", "-c", "side")
    side = commit(root, {"guide.md": "First, reworded.\nMiddle one.\nMiddle two.\nLast.\n", "other.txt": "side\n"})
    git(root, "switch", "-q", "main")
    commit(root, {"guide.md": "First.\nMiddle one.\nMiddle two.\nLast, as main has it.\n"})
    git(root, "merge", "-q", "--no-ff", "-m", "Title", "-m", "Body.", side)
    assert (root / "guide.md").read_text(encoding="utf-8") == "First, reworded.\nMiddle one.\nMiddle two.\nLast, as main has it.\n"
    assert git(root, "log", "-1", "--format=%B") == "Title\n\nBody."
    git(root, "switch", "-q", "-c", "again")
    again = commit(root, {"other.txt": "again\n"})
    git(root, "switch", "-q", "main")
    commit(root, {"other.txt": "main\n"})
    assert git_door.run("merge", "-q", "-m", "merge", again, root=root).returncode != 0
    assert git(root, "diff", "--name-only", "--diff-filter=U") == "other.txt"
    git(root, "merge", "--abort")
    assert git(root, "diff", "--name-only", "--diff-filter=U") == ""
    assert (root / "other.txt").read_text(encoding="utf-8") == "main\n"


def test_update_ref_moves_and_deletes_a_ref_only_from_the_old_value_named(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n"})
    second = commit(root, {"a.txt": "a2\n"})
    zero = "0" * 40
    git(root, "update-ref", "refs/heads/next", first, zero)
    assert git_door.run("update-ref", "refs/heads/next", second, zero, root=root).returncode != 0, "it exists"
    assert git_door.run("update-ref", "refs/heads/next", second, second, root=root).returncode != 0, "not there"
    git(root, "update-ref", "refs/heads/next", second, first)
    assert git(root, "rev-parse", "refs/heads/next") == second
    git(root, "update-ref", "refs/heads/next", zero, second)
    assert git_door.run("rev-parse", "--verify", "--quiet", "refs/heads/next", root=root).returncode != 0


def test_ls_remote_reads_a_named_remote_by_pattern(door, tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    root = project(tmp_path)
    git(root, "remote", "add", "origin", str(origin))
    first = commit(root, {"a.txt": "a\n"})
    git(root, "tag", "v1")
    git(root, "push", "-q", "origin", "main", f"{first}:refs/heads/feat/main", "refs/tags/v1")
    assert git(root, "ls-remote", "origin", "refs/heads/main").splitlines() == [f"{first}\trefs/heads/main"]
    assert git(root, "ls-remote", "--heads", "origin", "main").splitlines() == [
        f"{first}\trefs/heads/feat/main", f"{first}\trefs/heads/main"]
    assert git(root, "ls-remote", "--heads", "origin", "none") == ""


def test_check_ignore_and_add_follow_the_root_gitignore(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / ".gitignore").write_text("/.se/\nbuild/\n*.pyc\n", encoding="utf-8")
    for name in (".se/work/notes/private.txt", "src/build/out.txt", "src/x.pyc", "src/x.py", "build.txt"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x\n", encoding="utf-8")
    for name in (".se/work/notes/private.txt", "src/build/out.txt", "src/x.pyc"):
        assert git_door.run("check-ignore", "-q", name, root=root).returncode == 0, name
    for name in ("src/x.py", "build.txt"):
        assert git_door.run("check-ignore", "-q", name, root=root).returncode == 1, name
    git(root, "add", "-A")
    assert git_door.run("ls-files", "-z", root=root).stdout.split("\0") == [".gitignore", "build.txt", "src/x.py", ""]


# What `integrate`, `sync` and `start` ask of git (tests/test_work_ticket_issues.py)


def test_log_and_rev_list_leave_out_excluded_revisions_and_merges(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    base = commit(root, {"a.txt": "a\n"}, "base")
    git(root, "switch", "-q", "-c", "side")
    side = commit(root, {"b.txt": "b\n"}, "side work")
    git(root, "switch", "-q", "main")
    ahead = commit(root, {"c.txt": "c\n"}, "main work")
    git(root, "switch", "-q", "side")
    git(root, "merge", "-q", "--no-edit", "main")
    merge = git(root, "rev-parse", "HEAD")
    late = commit(root, {"d.txt": "d\n"}, "late work")
    assert git(root, "log", "--no-merges", "--format=%h %s", "side", f"^{side}", "^main").splitlines() == [
        f"{late[:7]} late work"]
    assert git(root, "log", "--format=%s", f"{side}..side").splitlines()[-1] == "main work"
    assert set(git(root, "rev-list", f"{base}..side").split()) == {side, ahead, merge, late}
    parents = dict(line.split(" ", 1) for line in git(root, "rev-list", "--parents", "-1", merge).splitlines())
    assert set(parents[merge].split()) == {side, ahead}
    assert git(root, "rev-list", "--first-parent", "--reverse", "side").split() == [base, side, merge, late]
    assert git_door.run("log", "-1", "--format=%H%x00%s%x1e", late, root=root).stdout == f"{late}\0late work\x1e\n"
    shown = git(root, "show", "-s", "--format=%B%x00%an%x00%ce", late).split("\0")
    assert [shown[0].strip(), *shown[1:]] == ["late work", IDENTITY[0], IDENTITY[1]]


def test_merge_base_of_several_commits_and_a_fast_forward_only_merge(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    base = commit(root, {"a.txt": "a\n"})
    git(root, "branch", "one")
    git(root, "branch", "stale", base)
    middle = commit(root, {"b.txt": "b\n"})
    git(root, "switch", "-q", "-c", "two")
    commit(root, {"c.txt": "c\n"})
    git(root, "switch", "-q", "main")
    tip = commit(root, {"d.txt": "d\n"})
    assert git(root, "merge-base", "HEAD", "one") == base
    assert git(root, "merge-base", "HEAD", "one", "two") == middle, "the base of HEAD and a merge of both"
    assert git(root, "rev-parse", "stale") == base
    assert git_door.run("branch", "stale", root=root).returncode != 0, "it exists"
    git(root, "switch", "-q", "one")
    assert git_door.run("merge", "-q", "--ff-only", "two", root=root).returncode == 0
    assert git_door.run("merge", "-q", "--ff-only", tip, root=root).returncode != 0, "diverged"
    assert git(root, "rev-parse", "HEAD") == git(root, "rev-parse", "two")


def test_a_merge_keeps_an_uncommitted_change_it_does_not_touch_and_refuses_one_it_does(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    commit(root, {"a.txt": "a\n", "b.txt": "b\n"})
    git(root, "switch", "-q", "-c", "side")
    side = commit(root, {"a.txt": "a2\n"})
    git(root, "switch", "-q", "main")
    (root / "b.txt").write_text("local\n", encoding="utf-8")
    git(root, "merge", "-q", "--ff-only", side)
    assert (root / "a.txt").read_text(encoding="utf-8") == "a2\n"
    assert (root / "b.txt").read_text(encoding="utf-8") == "local\n"
    git(root, "checkout", "HEAD", "--", "b.txt")
    assert (root / "b.txt").read_text(encoding="utf-8") == "b\n" and git(root, "status", "--porcelain") == ""
    git(root, "switch", "-q", "-c", "other", "HEAD~1")
    git(root, "switch", "-q", "-C", "other", side)
    newer = commit(root, {"a.txt": "a3\n"})
    git(root, "switch", "-q", "main")
    (root / "a.txt").write_text("mine\n", encoding="utf-8")
    assert git_door.run("merge", "-q", newer, root=root).returncode != 0
    assert (root / "a.txt").read_text(encoding="utf-8") == "mine\n" and git(root, "rev-parse", "HEAD") == side


def test_push_deletes_a_branch_under_a_lease_and_a_declining_remote_keeps_it(door, tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    root = project(tmp_path)
    git(root, "remote", "add", "origin", str(origin))
    first = commit(root, {"a.txt": "a\n"})
    second = commit(root, {"a.txt": "a2\n"})
    git(root, "push", "-q", "origin", "main", f"{first}:refs/heads/done", f"{first}:refs/heads/kept")
    stale = git_door.run("push", f"--force-with-lease=refs/heads/done:{second}", "origin", ":refs/heads/done", root=root)
    assert stale.returncode != 0 and git(origin, "rev-parse", "refs/heads/done") == first
    git(root, "push", "-q", f"--force-with-lease=refs/heads/done:{first}", "origin", ":refs/heads/done")
    assert git_door.run("show-ref", "--verify", "--quiet", "refs/heads/done", root=origin).returncode == 1
    assert git_door.run("show-ref", "--verify", "refs/heads/done", root=origin).returncode == 128
    assert git(origin, "show-ref", "--verify", "refs/heads/kept") == f"{first} refs/heads/kept"
    hook = origin / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'deletion refused' >&2\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    if isinstance(git_door.BACKEND, fake_git.FakeGit):
        git_door.BACKEND.declining[origin.resolve()] = "deletion refused"
    elif isinstance(git_door.BACKEND, fake_git.StateFile):
        with git_door.BACKEND.edit() as fake:
            fake.declining[origin.resolve()] = "deletion refused"
    declined = git_door.run("push", "origin", ":refs/heads/kept", root=root)
    assert declined.returncode != 0 and "pre-receive hook declined" in declined.stderr
    assert git(origin, "rev-parse", "refs/heads/kept") == first


def test_fetch_mirrors_the_remote_branches_with_prune_and_pull_merges_one(door, tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    root = project(tmp_path)
    git(root, "remote", "add", "origin", str(origin))
    first = commit(root, {"a.txt": "a\n"})
    git(root, "push", "-q", "origin", "main", f"{first}:refs/heads/gone")
    git(root, "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    assert git(root, "rev-parse", "refs/remotes/origin/gone") == first
    git(root, "push", "-q", "origin", ":refs/heads/gone")
    git(root, "update-ref", "refs/remotes/origin/gone", first)
    git(root, "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    assert git_door.run("rev-parse", "--verify", "--quiet", "refs/remotes/origin/gone", root=root).returncode != 0
    other = quiet_git.clone(origin, tmp_path / "other")
    assert git_door.set_identity(other, IDENTITY) is None
    newer = commit(other, {"b.txt": "b\n"})
    git(other, "push", "-q", "origin", "main")
    git(root, "pull", "-q", "--ff-only", "origin", "main")
    assert git(root, "rev-parse", "HEAD") == newer and (root / "b.txt").is_file()


def test_commit_tree_for_each_ref_and_plain_worktree_list(door, tmp_path: Path) -> None:
    root = project(tmp_path)
    first = commit(root, {"a.txt": "a\n"})
    second = commit(root, {"a.txt": "a2\n"})
    env = git_door.identity_environment(("bob", "bob@example.com"))
    made = git_door.run("commit-tree", f"{second}^{{tree}}", "-p", first, "-m", "Title", "-m", "Body.",
                        root=root, env=env)
    squash = made.stdout.strip()
    assert made.returncode == 0 and SHA.fullmatch(squash) and git(root, "rev-parse", "HEAD") == second
    assert git(root, "log", "-1", "--format=%P|%B|%an", squash) == f"{first}|Title\n\nBody.\n|bob"
    assert git(root, "rev-parse", f"{squash}^{{tree}}") == git(root, "rev-parse", f"{second}^{{tree}}")
    assert git_door.run("cat-file", "-e", f"{squash}:a.txt", root=root).returncode == 0
    assert git_door.run("cat-file", "-e", f"{squash}:none.txt", root=root).returncode != 0
    git(root, "update-ref", "refs/remotes/origin/feat/x", squash)
    git(root, "update-ref", "refs/remotes/origin/main", first)
    listed = git(root, "for-each-ref", "--format=%(refname:lstrip=3)%09%(committerdate:iso-strict)",
                 "refs/remotes/origin/").splitlines()
    assert [line.split("\t")[0] for line in listed] == ["feat/x", "main"]
    assert all(datetime.fromisoformat(line.split("\t")[1]).tzinfo for line in listed)
    git(root, "worktree", "add", "-q", "-b", "worker", str(tmp_path / "worker"))
    lines = git(root, "worktree", "list").splitlines()
    assert len(lines) == 2 and Path(lines[1].split()[0]).resolve() == (tmp_path / "worker").resolve()
    assert lines[1].split()[1] == second[:len(lines[1].split()[1])] and lines[1].endswith("[worker]")


# The door's variable: one fake for a test and the processes it starts

STATE_TESTDATA = ROOT / "kern" / "git" / "gitfake" / "testdata" / "state"
STATE_ANSWERS = [  # what kern's door asks of a state file, in the repository `repo`
    ["for-each-ref", "--format=%(refname)%09%(objectname)", "refs/"],
    ["ls-files", "--others", "--exclude-standard"],
    ["rev-parse", "HEAD"],
    ["config", "--get", "remote.origin.url"],
]


def build_state(folder: Path) -> fake_git.StateFile:
    """The testdata state: a repository with two commits, a tag, a remote branch and a file it
    does not track, with fixed identities and dates, so the Python fake writes it byte for byte."""
    state = fake_git.StateFile(folder / "git-door.json")
    env = {**git_door.identity_environment(IDENTITY), "GIT_AUTHOR_DATE": "2026-01-02T03:04:05+00:00",
           "GIT_COMMITTER_DATE": "2026-01-02T03:04:05+00:00"}
    with git_door.use(state):
        root = folder / "repo"
        git_door.run("init", "-q", "-b", "main", str(root))
        for name, text in {"a.txt": "a\n", "dir/b.txt": "b\n"}.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8", newline="\n")
            git(root, "add", "-A")
            assert git_door.run("commit", "-q", "-m", f"add {name}", root=root, env=env).returncode == 0
        git(root, "tag", "v1")
        git(root, "remote", "add", "origin", "https://example.com/alice/repo.git")
        git(root, "update-ref", "refs/remotes/origin/main", "HEAD~1")
        (root / "notes.txt").write_text("not tracked\n", encoding="utf-8", newline="\n")
    return state


def state_answers(folder: Path) -> list[dict]:
    return [{"args": args, "out": git(folder / "repo", *args) + "\n"} for args in STATE_ANSWERS]


def state_json(path: Path) -> dict:
    state = json.loads(path.read_text(encoding="utf-8"))
    state.pop("calls", None)
    return state


def test_the_state_file_is_the_format_kern_reads(tmp_path: Path) -> None:
    """kern/git/gitfake reads the state file the Python fake writes: the testdata state is what
    the Python fake writes for build_state, and both fakes answer answers.json from it (the Go side
    is kern/git/gitfake/state_test.go)."""
    state = build_state(tmp_path)
    with git_door.use(state):
        answers = state_answers(tmp_path)
    remedy = f"rewrite {STATE_TESTDATA.relative_to(ROOT).as_posix()} from build_state ({tmp_path})"
    assert state_json(state.path) == state_json(STATE_TESTDATA / "git-door.json"), remedy
    assert sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "repo").rglob("*")
                  if p.is_file() and ".git" not in p.parts) == \
        sorted(p.relative_to(STATE_TESTDATA).as_posix() for p in (STATE_TESTDATA / "repo").rglob("*") if p.is_file())
    assert answers == json.loads((STATE_TESTDATA / "answers.json").read_text(encoding="utf-8")), remedy


def test_a_child_process_reaches_the_fake_its_test_names_and_is_refused_without_it(tmp_path: Path) -> None:
    state = fake_git.StateFile(tmp_path / "git-door.json")
    root = tmp_path / "project"
    child = ("import sys, git_door; done = git_door.run(*sys.argv[1:]); "
             "sys.stdout.write(done.stdout); sys.exit(done.returncode)")

    def run_child(variable: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, git_door.VARIABLE: variable, "PYTHONPATH": str(ROOT / "scripts")}
        return subprocess.run([sys.executable, "-c", child, *arguments], env=env, capture_output=True,
                              text=True, check=False)

    assert run_child(f"fake:{state.path}", "init", "-q", "-b", "main", str(root)).returncode == 0
    with git_door.use(state):
        assert git(root, "rev-parse", "--abbrev-ref", "HEAD") == "main", "the child's init reached the test's fake"
        git(root, "config", "user.name", "alice")
    assert run_child(f"fake:{state.path}", "-C", str(root), "config", "user.name").stdout == "alice\n"
    refused = run_child("refused", "-C", str(root), "status")
    assert refused.returncode == 1 and f"git -C {root} status" in refused.stderr and "SE_GIT_DOOR" in refused.stderr
    unknown = run_child("other", "status")
    assert unknown.returncode == 1 and "none of real, refused or fake" in unknown.stderr
