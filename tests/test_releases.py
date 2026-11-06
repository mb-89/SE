"""work_tickets.py push releases the integration branch: it bumps se.toml's version and tags it."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def settings(version: str | None) -> str:
    line = f'version = "{version}"\n' if version is not None else ""
    return f"[project]\n# the released version\n{line}public_check = false\n"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch) -> Path:
    """A clone of a bare origin on main, the integration branch, with se.toml at 1.2.3 tagged."""
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: tmp_path / "no-local.toml")
    origin, root = tmp_path / "origin.git", tmp_path / "main"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(root)], check=True,
                   capture_output=True)
    git(root, "config", "user.name", "mb")
    git(root, "config", "user.email", "mb")
    (root / "se.toml").write_text(settings("1.2.3"), encoding="utf-8")
    git(root, "add", "se.toml")
    git(root, "commit", "-q", "-m", "base")
    git(root, "tag", "v1.2.3")
    git(root, "push", "-q", "origin", "main", "v1.2.3")
    return root


def integrate(root: Path, branch: str, breaking: bool = False) -> None:
    git(root, "switch", "-q", "-c", branch)
    (root / f"{branch.replace('/', '-')}.txt").write_text(branch, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", branch)
    git(root, "switch", "-q", "main")
    trailer = ["-m", work_tickets.BREAKING_TRAILER] if breaking else []
    git(root, "merge", "-q", "--no-ff", "-m", f"Integrate {branch}: work", *trailer, branch)


def push(root: Path) -> int:
    return work_tickets.main(["push", "--worktree", str(root)])


def released(root: Path) -> tuple[str, str]:
    """The version in se.toml on origin's main and origin's newest tag."""
    origin = root.parent / "origin.git"
    text = subprocess.run(["git", "--git-dir", str(origin), "show", "main:se.toml"],
                          capture_output=True, text=True, check=True).stdout
    tags = subprocess.run(["git", "--git-dir", str(origin), "tag", "--sort=-v:refname"],
                          capture_output=True, text=True, check=True).stdout.split()
    return text.split('version = "')[1].split('"')[0], tags[0]


@pytest.mark.parametrize(("branch", "breaking", "version"), [
    ("feature/topic-20261106", False, "1.3.0"),
    ("fix/topic-20261106", False, "1.2.4"),
    ("perf/topic-20261106", False, "1.2.4"),
    ("chore/topic-20261106", False, "1.2.4"),
    ("docs/topic-20261106", False, "1.2.4"),
    ("fix/topic-20261106", True, "2.0.0"),
])
def test_each_package_kind_bumps_its_part_and_the_tag_is_pushed_with_the_merge(
        checkout, capsys, branch, breaking, version):
    integrate(checkout, branch, breaking)
    assert push(checkout) == 0
    assert released(checkout) == (version, f"v{version}")
    assert git(checkout, "rev-parse", f"v{version}") == git(checkout, "rev-parse", "origin/main")
    assert git(checkout, "log", "-1", "--format=%s", "main") == f"Release v{version}"
    assert (checkout / "se.toml").read_text(encoding="utf-8") == settings(version)
    assert f"Release: v{version} (" in capsys.readouterr().out


def test_several_integrations_release_once_by_the_highest_kind(checkout):
    integrate(checkout, "fix/one-20261106")
    integrate(checkout, "feature/two-20261106")
    integrate(checkout, "docs/three-20261106")
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")
    # Pushing again releases nothing new: the integrations are behind the tag.
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")


def test_a_failed_push_is_retried_without_a_second_bump(checkout, monkeypatch):
    integrate(checkout, "feature/topic-20261106")
    real = work_tickets.run_git_push
    refusals = [subprocess.CompletedProcess(["git", "push"], 1, "", "error: permission denied (403)")]
    monkeypatch.setattr(work_tickets, "run_git_push",
                        lambda root, arguments: refusals.pop() if refusals else real(root, arguments))
    assert push(checkout) == 1
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")


def test_an_untagged_version_is_tagged_as_it_is(checkout, capsys):
    (checkout / "se.toml").write_text(settings("2.0.0"), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "start at 2.0.0")
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert released(checkout) == ("2.0.0", "v2.0.0")
    assert "v2.0.0 tagged, the first tag of project.version" in capsys.readouterr().out


def test_other_branches_and_merges_release_nothing(checkout, capsys):
    integrate(checkout, "feature/topic-20261106")
    git(checkout, "switch", "-q", "-c", "fix/other-20261106")
    assert work_tickets.main(["push", "fix/other-20261106", "--worktree", str(checkout)]) == 0
    git(checkout, "switch", "-q", "main")
    git(checkout, "reset", "-q", "--hard", "origin/main")
    integrate(checkout, "side")  # a merge named like no integration
    git(checkout, "commit", "-q", "--amend", "-m", "Merge branch 'side'")
    assert push(checkout) == 0
    assert released(checkout) == ("1.2.3", "v1.2.3")
    assert "is no integration; it bumps nothing" in capsys.readouterr().out


def test_an_unknown_branch_prefix_is_refused_before_anything_is_written(checkout, capsys):
    integrate(checkout, "refactor/topic-20261106")
    before = git(checkout, "rev-parse", "HEAD")
    assert push(checkout) == 1
    assert git(checkout, "rev-parse", "HEAD") == before
    error = capsys.readouterr().err
    assert "Cannot release refactor/topic-20261106: its prefix 'refactor' names no package kind" in error
    assert "feature, feat, fix, perf, chore, docs" in error


def test_without_a_version_push_says_how_to_release(checkout, capsys):
    (checkout / "se.toml").write_text(settings(None), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "no version")
    assert push(checkout) == 0
    assert (f"Release off: no project.version in {checkout / 'se.toml'}; write it as "
            'version = "MAJOR.MINOR.PATCH" under [project]') in capsys.readouterr().out


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "01.2.3", "1.2.3-rc1", "", 1])
def test_a_malformed_version_is_an_error_naming_the_file_and_the_remedy(checkout, capsys, version):
    value = f'"{version}"' if isinstance(version, str) else str(version)
    (checkout / "se.toml").write_text(f"[project]\nversion = {value}\npublic_check = false\n",
                                      encoding="utf-8")
    assert push(checkout) == 1
    error = capsys.readouterr().err
    assert f"project.version in {checkout / 'se.toml'} is {version!r}, not MAJOR.MINOR.PATCH" in error
    assert 'write it as version = "MAJOR.MINOR.PATCH" under [project]' in error


@pytest.mark.parametrize(("kind", "breaking"), [
    ("Standard, medium.", False),
    ("Standard, medium, **breaking**: removes the old flag.", True),
    ("<!-- mark a breaking change here -->\nStandard.", False),
])
def test_the_work_issue_marks_a_breaking_change_in_its_package_kind(kind, breaking):
    assert work_tickets.is_breaking(f"## Goal\n\nx\n\n## Package kind\n\n{kind}\n\n## Blocked by\n") is breaking
