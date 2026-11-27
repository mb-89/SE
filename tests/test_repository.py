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
from conftest import (MACHINE_HOME, REAL_GIT, XDG_VARIABLES, RefusedGit, door_backend, door_variable,
                      machine_caches, runner_variables, use_machine_home)
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


def test_a_large_retro_report_passes_but_other_large_docs_do_not(tmp_path: Path, fake_git_door) -> None:
    repo = fixture_repo(
        tmp_path, {"docs/retro-2026-11-24.md": b"x" * 201, "docs/guide.md": b"x" * 201}
    )

    assert large_findings(repo, {}, limit=200) == [
        "docs/guide.md: 201 bytes, over 200; git rm --cached it and ignore it, split it, "
        "or allow it with a reason",
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
# the check, and passes a clean checkout; the public check, its child through the process door, is
# answered in-process by its main (tests/fake_processes.py), on the fake in memory.

# A README of the one-page shape (scripts/readme.py): its command, its documentation, its pitch.
ONE_PAGE = ("# Clean\n\n```sh\n./run --demo\n```\n\nThe line installs and runs it. The [documentation]"
            "(AGENTS.md) holds the rest.\n\n## What it is\n\nA clean tool.\n\n- [Agents](AGENTS.md)\n")


@pytest.fixture
def no_allow_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixture checkout has none of SE's allowed files, so SE's lists would be stale there."""
    for name in ("BINARY_ALLOWED", "LARGE_ALLOWED", "GIT_ALLOWED", "HOME_ALLOWED", "SECTIONS_SKIPPED"):
        monkeypatch.setattr(hygiene, name, {})


@pytest.mark.usefixtures("fake_git_door")
def test_hygiene_passes_a_clean_checkout(repo: Path, no_allow_lists: None, capsys) -> None:
    commit(repo, {"README.md": ONE_PAGE, "AGENTS.md": "# Agents\n\nSee README \"What it is\".\n",
                  "scripts/tool.py": "import git_door\ngit_door.run('status')\n"})
    assert hygiene.main(["--repo", str(repo)]) == 0, capsys.readouterr().out
    out = capsys.readouterr().out.splitlines()
    assert out[-1].startswith("hygiene: passed (10 checks) in ")
    assert out[0].startswith("hygiene: neutral-home: skipped: ") and "no origin remote" in out[0]


@pytest.mark.usefixtures("fake_git_door")
def test_hygiene_refuses_what_each_check_finds_naming_the_check(
        repo: Path, no_allow_lists: None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(hygiene, "MAX_BYTES", 100)
    marker = "TO" + "DO"
    commit(repo, {"tool.bin": b"\x7fELF\0\0", "dump.json": "x" * 101,
                  "scripts/tool.py": f"import subprocess\n# {marker}: retry\nsubprocess.run(['git', 'status'])\n",
                  "README.md": "# Leaky\n\nSee [gone](gone.md), copied from /" + "home/alice/notes.\n",
                  "docs/install.md": "Install from bob/project.\n",
                  "AGENTS.md": "# Agents\n\nSee README \"Gone\" and docs/install.md \"Gone\".\n"})
    git_door.run("remote", "add", "origin", "https://example.com/bob/project.git", root=repo)
    assert hygiene.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "hygiene: binary: tool.bin: a tracked binary file" in out
    assert "hygiene: large: dump.json: 101 bytes, over 100" in out
    assert "hygiene: marker: scripts/tool.py:2: names no issue" in out
    assert "hygiene: git-door: scripts/tool.py:3: 1 git subprocess(es) outside the door" in out
    assert "hygiene: references: README.md line 3: `gone.md`" in out
    assert "hygiene: public: " in out and "README.md:3:" in out and "user-profile-path" in out
    assert "alice" not in out, "the public check names locations and labels, never the matched text"
    assert "hygiene: neutral-home: docs/install.md:1: names the origin's owner" in out
    assert "bob" not in out, "the neutral-home check names locations, never the matched text"
    assert 'hygiene: sections: AGENTS.md line 3: `README "Gone"` names no section of README.md' in out
    assert 'hygiene: sections: AGENTS.md line 3: `docs/install.md "Gone"` names no section' in out
    assert "hygiene: readme: README.md: no code block of one command within its first 10 lines" in out
    assert out.splitlines()[-1].startswith(
        "hygiene: refused by binary, large, marker, git-door, references, public, neutral-home, "
        "sections, readme (")


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
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "tool.go").write_text('cmd := exec.CommandContext(ctx, "git", "-C", dir)\n',
                                                       encoding="utf-8")
    (tmp_path / "scripts" / "git_door.py").write_text("subprocess.run(['git', *argv])\n", encoding="utf-8")
    assert git_door_findings(tmp_path, {"components/tool.go": (1, "a reason"), "tests/gone.py": (2, "a reason")}) == [
        "scripts/tool.py:3: 2 git subprocess(es) outside the door, 0 allowed; run git through "
        "scripts/git_door.py (tests: the fake_git_door fixture)",
        "tests/gone.py: 0 git subprocess(es) outside the door, the allow list says 2; lower its entry (it may "
        "only shrink)",
    ]


# The runner's variables switch commands to their runner behaviour; tests/conftest.py clears them for
# the session, so a test sees a local machine wherever the suite runs.

def test_no_test_starts_with_a_runner_variable() -> None:
    assert runner_variables(os.environ) == []


def test_the_runner_variables_are_ci_se_cloud_agent_and_every_github_variable() -> None:
    environment = {"CI": "true", "SE_CLOUD_AGENT": "a", "GITHUB_ACTIONS": "true", "GITHUB_SHA": "1",
                   "PATH": "/bin", "SE_METRICS": "x", "CIRCLE": "y"}
    assert runner_variables(environment) == ["CI", "SE_CLOUD_AGENT", "GITHUB_ACTIONS", "GITHUB_SHA"]


def test_a_test_that_needs_a_runner_variable_sets_it_itself(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert runner_variables(os.environ) == ["GITHUB_ACTIONS"]


# Each test's home has no user data (tests/conftest.py `own_home`); the machine's caches stay
# where the machine keeps them (`machine_caches`).

def test_each_test_runs_in_an_empty_home_of_its_own_that_reads_no_git_configuration(own_home) -> None:
    assert Path.home() == own_home and os.environ["HOME"] == os.environ["USERPROFILE"] == str(own_home)
    if os.name == "nt":
        assert os.environ["APPDATA"] == str(own_home / "AppData" / "Roaming")
        assert os.environ["LOCALAPPDATA"] == str(own_home / "AppData" / "Local")
        assert sorted(path.name for path in (own_home / "AppData").iterdir()) == ["Local", "Roaming"]
        assert not list((own_home / "AppData" / "Local").iterdir())
        assert not list((own_home / "AppData" / "Roaming").iterdir())
        assert [path.name for path in own_home.iterdir()] == ["AppData"]
    else:
        assert list(own_home.iterdir()) == []
    assert own_home != Path(MACHINE_HOME["HOME"] or "/")
    assert [name for name in XDG_VARIABLES if name in os.environ] == []
    assert "GIT_CONFIG_GLOBAL" not in os.environ and os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    (own_home / ".se").mkdir()  # what a test writes under ~ is its own: the next test's home is empty


def test_the_next_test_finds_nothing_the_last_one_wrote_under_its_home(own_home) -> None:
    assert not (Path.home() / ".se").exists()


def test_obs_setup_restores_the_machines_windows_app_data(monkeypatch) -> None:
    for name in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, "isolated")
    use_machine_home(monkeypatch)
    for name in ("APPDATA", "LOCALAPPDATA"):
        assert os.environ.get(name) == MACHINE_HOME[name]


def test_the_machine_caches_are_where_each_tool_finds_them_without_its_variable() -> None:
    def at(*paths: str) -> tuple[str, ...]:
        return tuple(str(Path(path)) for path in paths)

    def found(environ: dict[str, str], platform: str, *names: str) -> tuple[str, ...]:
        caches = machine_caches(environ, platform)
        return tuple(caches[name] for name in names)

    every = ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "GOCACHE", "GOPATH", "GOMODCACHE", "npm_config_cache",
             "PLAYWRIGHT_BROWSERS_PATH")
    assert list(machine_caches({"HOME": "/u/alice"}, "linux")) == list(every)
    assert found({"HOME": "/u/alice"}, "linux", *every) == at(
        "/u/alice/.cache/uv", "/u/alice/.local/share/uv/python", "/u/alice/.cache/go-build", "/u/alice/go",
        "/u/alice/go/pkg/mod", "/u/alice/.npm", "/u/alice/.cache/ms-playwright")
    xdg = {"HOME": "/u/alice", "XDG_CACHE_HOME": "/c", "XDG_DATA_HOME": "/d", "GOPATH": "/g"}
    assert found(xdg, "linux", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "GOCACHE", "GOPATH", "GOMODCACHE") == (
        *at("/c/uv", "/d/uv/python", "/c/go-build"), "/g", *at("/g/pkg/mod"))
    assert found({"HOME": "/u/alice"}, "darwin", "UV_CACHE_DIR", "GOCACHE", "PLAYWRIGHT_BROWSERS_PATH") == at(
        "/u/alice/.cache/uv", "/u/alice/Library/Caches/go-build", "/u/alice/Library/Caches/ms-playwright")
    windows = {"USERPROFILE": "/u/alice", "LOCALAPPDATA": "/l", "APPDATA": "/r"}
    assert found(windows, "win32", *every) == at(
        "/l/uv/cache", "/r/uv/data/python", "/l/go-build", "/u/alice/go", "/u/alice/go/pkg/mod", "/l/npm-cache",
        "/l/ms-playwright")


# The neutral home (hygiene's neutral-home check): no tracked file names the origin's owner.

HOME = hygiene.se_home.Home("example.com", "alice", "project")


def test_the_neutral_home_check_passes_a_tree_that_names_no_owner_and_fails_a_planted_line(
        tmp_path: Path, fake_git_door) -> None:
    clean = {"README.md": b"Install from <owner>/<repository>.\n", "notes.md": b"malice and alice-x stay\n",
             "logo.png": b"\x89PNG\0alice/project"}
    repo = fixture_repo(tmp_path, clean)
    assert hygiene.home_findings(repo, {}, HOME) == []

    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_bytes(b"# Guide\n\nClone https://example.com/Alice/project.\n"
                                             b"Pages: alice.github.io/project.\n")
    git_door.run("add", "-A", root=repo)
    assert hygiene.home_findings(repo, {}, HOME) == [
        "docs/guide.md:3: names the origin's owner; derive it from origin (scripts/se_home.py) or write a placeholder",
        "docs/guide.md:4: names the origin's owner; derive it from origin (scripts/se_home.py) or write a placeholder",
    ]


def test_the_neutral_home_check_covers_workflows_even_in_an_allowed_folder_and_refuses_a_stale_entry(
        tmp_path: Path, fake_git_door) -> None:
    """A workflow calls SE's files as local copies (scripts/se_workflows.py), so a planted
    `uses: <owner>/<repository>/...` line fails, and no allowed folder covers a workflow or action."""
    repo = fixture_repo(tmp_path, {
        ".github/workflows/check.yml": b"jobs:\n  check:\n    uses: alice/project/.github/workflows/x.yml@v1\n",
        ".github/workflows/local.yml": b"jobs:\n  check:\n    uses: ./.github/workflows/x.yml\n",
        "frozen/go.mod": b"module example.com/alice/frozen\n",
        "frozen/template/.github/workflows/check.yml": b"    uses: alice/project/.github/workflows/x.yml@v1\n",
        "frozen/template/.github/actions/a/action.yml": b"# from alice/project\n",
    })
    allowed = {"frozen/": "frozen until part 3", "gone.toml": "removed"}
    workflow = "call SE's workflows and actions as local copies, uses: ./.github/... (scripts/se_workflows.py)"
    assert hygiene.home_findings(repo, allowed, HOME) == [
        f".github/workflows/check.yml:3: names the origin's owner; {workflow}",
        f"frozen/template/.github/actions/a/action.yml:1: names the origin's owner; {workflow}",
        f"frozen/template/.github/workflows/check.yml:1: names the origin's owner; {workflow}",
        "gone.toml: allowed to name the origin's owner but names it nowhere; remove the entry",
    ]


def test_without_an_origin_the_neutral_home_check_is_skipped_with_its_reason(
        tmp_path: Path, fake_git_door, monkeypatch, capsys) -> None:
    repo = fixture_repo(tmp_path, {"README.md": b"alice/project\n"})
    assert "no origin remote" in hygiene.home_skip(repo)
    monkeypatch.setattr(hygiene, "public_findings", lambda root: [])
    assert hygiene.checks(repo)["neutral-home"] == []
    git_door.run("remote", "add", "origin", "git@example.com:alice/project.git", root=repo)
    assert hygiene.home_skip(repo) == ""
    assert hygiene.checks(repo)["neutral-home"][0] == (
        "README.md:1: names the origin's owner; derive it from origin (scripts/se_home.py) or write a placeholder")


def test_ses_neutral_home_allow_list_is_empty() -> None:
    """kern, the Go components, their release.toml and the wiring derive SE's home from origin
    (kern/home, scripts/se_home.py), so the guard exempts nothing but what it never reads."""
    assert hygiene.HOME_ALLOWED == {}


def test_hygiene_refuses_a_generated_file_its_generator_does_not_declare(tmp_path: Path, fake_git_door,
                                                                          monkeypatch) -> None:
    """The generated check is a step of hygiene, on the tracked files (scripts/generated.py)."""
    repo = fixture_repo(tmp_path, {"out.toml": b"# Code generated by gen.py from src.txt. DO NOT EDIT.\n",
                                   "untracked.toml": b""})
    (repo / "loose.toml").write_text("# Code generated by gen.py from src.txt. DO NOT EDIT.\n")
    monkeypatch.setattr(hygiene, "public_findings", lambda root: [])
    assert hygiene.checks(repo)["generated"] == [
        "out.toml: marked as generated by gen.py, which generated.yaml does not declare it of; declare it "
        "among gen.py's outputs, or remove the marker from a hand-written file"]
    (repo / "generated.yaml").write_text("generators: 3\n")
    with pytest.raises(hygiene.HygieneError, match="one key, `generators`"):
        hygiene.checks(repo)


def test_a_stale_sections_entry_fails_and_a_skipped_file_is_not_read(tmp_path: Path, fake_git_door) -> None:
    repo = fixture_repo(tmp_path, {"README.md": b"# Tool\n\n## Use\n",
                                   "notes.md": b'See README "Use" and README "Gone".\n',
                                   "record.md": b'It said README "Gone".\n'})
    assert hygiene.section_findings(repo, {"record.md": "a dated record", "lost.md": "gone"}) == [
        "SECTIONS_SKIPPED lost.md: no such tracked file",
        'notes.md line 1: `README "Gone"` names no section of README.md']


def test_ses_readme_is_one_page_with_its_command_first() -> None:
    assert hygiene.readme_findings(ROOT) == []


def test_a_checkout_without_a_readme_fails_the_readme_check(tmp_path: Path) -> None:
    assert hygiene.readme_findings(tmp_path) == [
        "README.md: missing; every project opens with its one-page README"]
