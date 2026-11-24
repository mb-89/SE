"""Source parity, `work_tickets.py parity` (docs/fleet.md "Source parity"): two commits' trees compare
path by path, dependency lockfiles excluded by one rule, every other difference named by path."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import fake_git
import git_door
import work_tickets  # scripts/ is on the path (tests/conftest.py)

IDENTITY = ("alice", "alice@example.com")
BASE = {
    "README.md": "# project\n",
    "src/app.py": "print('app')\n",
    "skills/app/SKILL.md": "generated\n",
    "se.lock": "[modules.obs]\ncommit = \"a\"\n",
    "uv.lock": "version = 1\n",
    "kern/template/uv.lock": "version = 1\n",
}


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, f"git {' '.join(arguments)}: {result.stderr.strip()}"
    return result.stdout.strip()


def tree(root: Path, files: dict[str, str]) -> str:
    """A commit holding exactly `files`, on a branch of its own from an empty start."""
    for path in git(root, "ls-files").splitlines():
        (root / path).unlink()
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "tree")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def project(fake_git_door, tmp_path: Path) -> Path:
    root = fake_git.init(tmp_path / "project", "-b", "main")
    assert git_door.set_identity(root, IDENTITY) is None
    return root


def parity(root: Path, left: str, right: str, capsys) -> tuple[int, str]:
    code = work_tickets.run_parity(root, argparse.Namespace(left=left, right=right))
    return code, capsys.readouterr().out


def test_the_rule_matches_se_lock_and_uv_lock_by_name_at_any_depth() -> None:
    assert work_tickets.PARITY_LOCKFILES == {"se.lock", "uv.lock"}
    for path in ("se.lock", "uv.lock", "kern/template/uv.lock", "a/b/se.lock"):
        assert work_tickets.is_parity_lockfile(path), path
    for path in ("se.lock.md", "my-uv.lock", "uv.lock/readme", "se.toml", "go.sum", "lock"):
        assert not work_tickets.is_parity_lockfile(path), path


def test_lockfile_only_differences_pass_and_are_named(project: Path, capsys) -> None:
    left = tree(project, BASE)
    changed = {**BASE, "se.lock": "[modules.obs]\ncommit = \"b\"\n",
               "kern/template/uv.lock": "version = 2\n"}
    del changed["uv.lock"]  # a lockfile one side lacks is excluded too
    right = tree(project, {**changed, "components/uv.lock": "version = 1\n"})
    code, out = parity(project, left, right, capsys)
    assert code == 0, out
    assert "lockfiles excluded: components/uv.lock, kern/template/uv.lock, se.lock, uv.lock" in out
    assert f"{left} and {right} match apart from lockfiles" in out


def test_identical_trees_pass_without_naming_lockfiles(project: Path, capsys) -> None:
    left = tree(project, BASE)
    code, out = parity(project, left, left, capsys)
    assert code == 0 and "lockfiles excluded" not in out


@pytest.mark.parametrize("path", ["src/app.py", "skills/app/SKILL.md", "se.toml.lock"])
def test_a_changed_source_or_generated_path_fails_by_its_path(project: Path, capsys, path: str) -> None:
    left = tree(project, {**BASE, "se.toml.lock": "a\n"})
    right = tree(project, {**BASE, "se.toml.lock": "a\n", path: "different\n",
                           "se.lock": "moved\n"})
    code, out = parity(project, left, right, capsys)
    assert code == 1, out
    assert f"changed: {path}\n" in out and "lockfiles excluded: se.lock" in out
    assert "differ in 1 path(s) apart from lockfiles" in out


def test_added_and_removed_paths_fail_naming_the_side_that_holds_them(project: Path, capsys) -> None:
    left = tree(project, BASE)
    right_files = {**BASE, "src/new.py": "new\n"}
    del right_files["README.md"]
    right = tree(project, right_files)
    code, out = parity(project, left, right, capsys)
    assert code == 1, out
    assert out.splitlines()[:2] == [f"only in {left}: README.md", f"only in {right}: src/new.py"]
    assert "differ in 2 path(s) apart from lockfiles" in out


def test_whitespace_is_a_difference_not_normalized_away(project: Path, capsys) -> None:
    left = tree(project, BASE)
    right = tree(project, {**BASE, "src/app.py": "print('app')  \n"})
    code, out = parity(project, left, right, capsys)
    assert code == 1 and "changed: src/app.py" in out


def test_parity_only_reads(project: Path, capsys) -> None:
    left = tree(project, BASE)
    right = tree(project, {**BASE, "src/app.py": "other\n"})
    before = (git(project, "rev-parse", "HEAD"), git(project, "status", "--porcelain"))
    parity(project, left, right, capsys)
    assert (git(project, "rev-parse", "HEAD"), git(project, "status", "--porcelain")) == before


def test_parity_is_a_registered_read_only_integration_command() -> None:
    parsed = work_tickets.make_parser().parse_args(["parity", "origin/main", "mirror/main"])
    assert (parsed.left, parsed.right) == ("origin/main", "mirror/main")
    assert "parity" in work_tickets.READ_ONLY_COMMANDS
    assert any("parity" in group.commands for group in work_tickets.COMPONENTS)
