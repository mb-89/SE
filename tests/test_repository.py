"""Repository hygiene's logic, on the git door's fake: the checks themselves are
`scripts/hygiene.py`, a step of CI's `check` job that reads SE's own checkout through the real door
(AGENTS.md "Tests"); here each fails on a fixture.

Three rules hold for every tracked file: no binary file, no file over `MAX_BYTES`, and no marker
of unfinished work in `scripts/` or `tests/` that names no issue. One holds for scripts, tests, kern
and the components: git runs only through its door (scripts/git_door.py). And the checkout passes
its public check (pub-001), with its history.

One rule holds for the suite itself, so it behaves on GitHub's runner as it does locally: no test
starts with a runner's variable set (tests/conftest.py); and its door refuses real git outside the
contract suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import git_door
import fake_git
import hygiene
import pytest
from conftest import REAL_GIT, RefusedGit, door_backend, door_variable, runner_variables
from hygiene import binary_findings, git_door_findings, large_findings, marker_findings
from test_public_check import commit, repo, se_checkout  # noqa: F401  (repo: the public check's fixture)

ROOT = Path(__file__).resolve().parents[1]


def fixture_repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """A git repository in `tmp_path`, in the door's fake, tracking `files`."""
    repo = tmp_path / "repo"
    for name, data in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
    fake_git.init(repo)
    assert git_door.run("add", "-A", root=repo).returncode == 0
    return repo


def test_a_tracked_binary_file_fails_and_a_stale_entry_too(tmp_path: Path, fake_git_door) -> None:
    repo = fixture_repo(
        tmp_path, {"tool": b"\x7fELF\0\0\0", "logo.png": b"\x89PNG\0", "a.txt": b"text\n"}
    )

    assert binary_findings(repo, {"logo.png": "the logo", "gone.bin": "removed"}) == [
        "tool: a tracked binary file; git rm --cached it and ignore it, or allow it with a reason",
        "gone.bin: allowed as binary but no tracked binary file; remove the entry",
    ]


def test_a_tracked_file_over_the_bound_fails_and_a_stale_entry_too(tmp_path: Path, fake_git_door) -> None:
    repo = fixture_repo(
        tmp_path, {"dump.json": b"x" * 201, "kept.json": b"x" * 201, "small.py": b"x" * 200}
    )

    assert large_findings(repo, {"kept.json": "needed", "small.py": "shrank"}, limit=200) == [
        "dump.json: 201 bytes, over 200; git rm --cached it and ignore it, split it, "
        "or allow it with a reason",
        "small.py: allowed as large but no tracked file over 200 bytes; remove the entry",
    ]


def test_a_marker_without_an_issue_fails(tmp_path: Path, fake_git_door) -> None:
    todo, fixme = "TO" + "DO", "FIX" + "ME"
    repo = fixture_repo(
        tmp_path,
        {
            "scripts/a.py": f"# {todo}: retry\n# {todo}(#12): owned\n".encode(),
            "tests/b.py": f"x = 1  # {fixme} later\n# {fixme} example.com/o/r/issues/7\n".encode(),
            "docs/c.md": f"{todo}: outside the rule's directories\n".encode(),
        },
    )

    assert marker_findings(repo) == [
        "scripts/a.py:1: names no issue; write the issue that owns it, #<n>",
        "tests/b.py:1: names no issue; write the issue that owns it, #<n>",
    ]


def test_the_allow_lists_say_why() -> None:
    assert all(reason.strip() for reason in [*hygiene.BINARY_ALLOWED.values(), *hygiene.LARGE_ALLOWED.values(),
                                             *(reason for _, reason in hygiene.GIT_ALLOWED.values())])


# The command CI's `check` job runs (scripts/hygiene.py): it refuses what each check finds, naming
# the check, and passes a clean checkout; the public check runs as its child, on the shared fake.

@pytest.fixture
def no_allow_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixture checkout has none of SE's allowed files, so SE's lists would be stale there."""
    for name in ("BINARY_ALLOWED", "LARGE_ALLOWED", "GIT_ALLOWED"):
        monkeypatch.setattr(hygiene, name, {})


def test_hygiene_passes_a_clean_checkout(repo: Path, no_allow_lists: None, capsys) -> None:
    commit(repo, {"README.md": "# Clean\n\nSee [agents](AGENTS.md).\n", "AGENTS.md": "# Agents\n",
                  "scripts/tool.py": "import git_door\ngit_door.run('status')\n"})
    assert hygiene.main(["--repo", str(repo)]) == 0, capsys.readouterr().out
    assert capsys.readouterr().out.splitlines()[-1].startswith("hygiene: passed (6 checks) in ")


def test_hygiene_refuses_what_each_check_finds_naming_the_check(
        repo: Path, no_allow_lists: None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(hygiene, "MAX_BYTES", 100)
    marker = "TO" + "DO"
    commit(repo, {"tool.bin": b"\x7fELF\0\0", "dump.json": "x" * 101,
                  "scripts/tool.py": f"import subprocess\n# {marker}: retry\nsubprocess.run(['git', 'status'])\n",
                  "README.md": "# Leaky\n\nSee [gone](gone.md), copied from /" + "home/alice/notes.\n"})
    assert hygiene.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "hygiene: binary: tool.bin: a tracked binary file" in out
    assert "hygiene: large: dump.json: 101 bytes, over 100" in out
    assert "hygiene: marker: scripts/tool.py:2: names no issue" in out
    assert "hygiene: git-door: scripts/tool.py:3: 1 git subprocess(es) outside the door" in out
    assert "hygiene: references: README.md line 3: `gone.md`" in out
    assert "hygiene: public: " in out and "README.md:3:" in out and "user-profile-path" in out
    assert "alice" not in out, "the public check names locations and labels, never the matched text"
    assert out.splitlines()[-1].startswith(
        "hygiene: refused by binary, large, marker, git-door, references, public (")


class Item:
    """What tests/conftest.py's door_backend reads of a collected test."""

    def __init__(self, path: Path) -> None:
        self.path, self.nodeid = path, f"{path.relative_to(ROOT).as_posix()}::test_example"


def test_a_test_reaching_real_git_through_the_door_fails_outside_the_contract_suite(tmp_path: Path) -> None:
    outside = door_backend(Item(ROOT / "tests" / "test_example.py"))
    assert isinstance(outside, RefusedGit)
    with git_door.use(outside), pytest.raises(pytest.fail.Exception) as refused:
        fake_git.init(tmp_path / "repo", "-b", "main")
    assert "tests/test_example.py::test_example ran real git (git init -q -b main" in str(refused.value)
    assert "fake_git_door" in str(refused.value) and not (tmp_path / "repo").exists()
    with git_door.use(outside), pytest.raises(pytest.fail.Exception):
        git_door.popen("fast-export", "--all", root=tmp_path)
    assert isinstance(door_backend(Item(ROOT / "tests" / "test_git_door.py")), git_door.RealGit)
    # A child process the test starts is told the same: refused outside the contract suite.
    assert door_variable(Item(ROOT / "tests" / "test_example.py")) == "refused"
    assert door_variable(Item(ROOT / "tests" / "test_git_door.py")) == "real"


def test_only_the_contract_suite_is_allowed_real_git_and_says_why() -> None:
    assert list(REAL_GIT) == ["tests/test_git_door.py"] and (ROOT / "tests" / "test_git_door.py").is_file()
    assert all(reason.strip() for reason in REAL_GIT.values())


def test_a_git_subprocess_outside_the_door_fails_and_an_entry_too_high_too(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text(
        "import subprocess\n"
        "feedback.reading('the remote', ['git', 'fetch'])\n"
        "subprocess.run(['git', '-C', root, 'status'])\n"
        "subprocess.run('git status', shell=True)\n"
        "git_door.run('status', root=root)\n", encoding="utf-8")
    (tmp_path / "kern").mkdir()
    (tmp_path / "kern" / "tool.go").write_text('cmd := exec.CommandContext(ctx, "git", "-C", dir)\n',
                                                 encoding="utf-8")
    (tmp_path / "scripts" / "git_door.py").write_text("subprocess.run(['git', *argv])\n", encoding="utf-8")
    assert git_door_findings(tmp_path, {"kern/tool.go": (1, "a reason"), "tests/gone.py": (2, "a reason")}) == [
        "scripts/tool.py:3: 2 git subprocess(es) outside the door, 0 allowed; run git through "
        "scripts/git_door.py (tests: the fake_git_door fixture)",
        "tests/gone.py: 0 git subprocess(es) outside the door, the allow list says 2; lower its entry (it may "
        "only shrink)",
    ]


# The runner's variables switch commands to their runner behaviour; tests/conftest.py clears them for
# the session, so a test sees a local machine wherever the suite runs.

def test_no_test_starts_with_a_runner_variable() -> None:
    assert runner_variables(os.environ) == []


def test_the_runner_variables_are_ci_se_cloud_agent_every_cloud_mark_and_every_github_variable() -> None:
    environment = {"CI": "true", "SE_CLOUD_AGENT": "a", "GITHUB_ACTIONS": "true", "GITHUB_SHA": "1",
                   "CLAUDE_CODE_REMOTE": "true", "COPILOT_AGENT_PROMPT": "p", "SE_CLOUD": "true",
                   "PATH": "/bin", "SE_METRICS": "x", "CIRCLE": "y"}
    assert runner_variables(environment) == ["CI", "SE_CLOUD_AGENT", "GITHUB_ACTIONS", "GITHUB_SHA",
                                             "CLAUDE_CODE_REMOTE", "COPILOT_AGENT_PROMPT", "SE_CLOUD"]


def test_a_test_that_needs_a_runner_variable_sets_it_itself(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert runner_variables(os.environ) == ["GITHUB_ACTIONS"]
