"""Repository hygiene: what any repository should not track, checked on se's own tree.

Three rules hold for every tracked file: no binary file, no file over `MAX_BYTES`, and no
marker of unfinished work in `scripts/` or `tests/` that names no issue. A file that must break
the first two goes in its allow list below with the reason it may; an entry that no longer names
such a file is refused, so the lists stay true.

One rule holds for the suite itself, so it behaves on GitHub's runner as it does locally: no test
starts with a runner's variable set (tests/conftest.py).

One rule holds for scripts, tests, kern and the components: git runs only through its door
(scripts/git_door.py); today's other git subprocesses sit on an allow list that may only shrink.

And se's own checkout passes its public check (pub-001), with its history.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import git_door
import fake_git
import pytest
from conftest import REAL_GIT, RefusedGit, door_backend, door_variable, runner_variables

ROOT = Path(__file__).resolve().parents[1]

# The most bytes a tracked file holds outside LARGE_ALLOWED: source stays well under it, a build
# output, a data dump or a vendored bundle does not.
MAX_BYTES = 200_000

# Tracked binary files (a NUL byte in the first BINARY_PEEK bytes, git's own test), each with the
# reason it is tracked.
BINARY_ALLOWED: dict[str, str] = {}

# Tracked files over MAX_BYTES, each with the reason it is tracked.
LARGE_ALLOWED: dict[str, str] = {
    "scripts/work_tickets.py": "the work model's one command; its split is a package of its own",
    "tests/test_work_ticket_issues.py": "the issue tests of work_tickets.py, which follow its size",
}

BINARY_PEEK = 8000

# The markers are spelled in two halves, so this file does not break its own rule.
MARKER = re.compile(r"\b(?:" + "TO" + "DO" + "|" + "FIX" + "ME" + r")\b")
# An issue a marker names: `#<n>`, `<repo>#<n>` or an issue URL.
ISSUE = re.compile(r"#\d+|/issues/\d+")
MARKED_DIRS = ("scripts/", "tests/")


def tracked(repo: Path) -> list[str]:
    """The files git tracks in `repo` that exist in its working tree."""
    listed = git_door.run("ls-files", "-z", root=repo)
    assert listed.returncode == 0, listed.stderr
    return [p for p in listed.stdout.split("\0") if p and (repo / p).is_file()]


def binary_findings(repo: Path, allowed: dict[str, str]) -> list[str]:
    """Tracked binary files outside `allowed`, and entries of `allowed` that name none."""
    binaries = set()
    for p in tracked(repo):
        with open(repo / p, "rb") as f:
            if b"\0" in f.read(BINARY_PEEK):
                binaries.add(p)
    return [
        f"{p}: a tracked binary file; git rm --cached it and ignore it, or allow it with a reason"
        for p in sorted(binaries - set(allowed))
    ] + [
        f"{p}: allowed as binary but no tracked binary file; remove the entry"
        for p in sorted(set(allowed) - binaries)
    ]


def large_findings(repo: Path, allowed: dict[str, str], limit: int = MAX_BYTES) -> list[str]:
    """Tracked files over `limit` bytes outside `allowed`, and entries of `allowed` naming none."""
    sizes = {p: (repo / p).stat().st_size for p in tracked(repo)}
    large = {p for p, size in sizes.items() if size > limit}
    return [
        f"{p}: {sizes[p]} bytes, over {limit}; git rm --cached it and ignore it, split it, "
        "or allow it with a reason"
        for p in sorted(large - set(allowed))
    ] + [
        f"{p}: allowed as large but no tracked file over {limit} bytes; remove the entry"
        for p in sorted(set(allowed) - large)
    ]


def marker_findings(repo: Path) -> list[str]:
    """Lines in `scripts/` and `tests/` whose marker of unfinished work names no issue."""
    found = []
    for p in tracked(repo):
        if not p.startswith(MARKED_DIRS):
            continue
        data = (repo / p).read_bytes()
        if b"\0" in data[:BINARY_PEEK]:
            continue
        for number, line in enumerate(data.decode(errors="replace").splitlines(), 1):
            if MARKER.search(line) and not ISSUE.search(line):
                found.append(f"{p}:{number}: names no issue; write the issue that owns it, #<n>")
    return found


def fixture_repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """A git repository in `tmp_path` tracking `files`."""
    repo = tmp_path / "repo"
    for name, data in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
    fake_git.init(repo)
    assert git_door.run("add", "-A", root=repo).returncode == 0
    return repo


def test_se_tracks_no_binary_file_outside_its_allow_list() -> None:
    assert binary_findings(ROOT, BINARY_ALLOWED) == []
    assert all(reason.strip() for reason in BINARY_ALLOWED.values())


def test_a_tracked_binary_file_fails_and_a_stale_entry_too(tmp_path: Path) -> None:
    repo = fixture_repo(
        tmp_path, {"tool": b"\x7fELF\0\0\0", "logo.png": b"\x89PNG\0", "a.txt": b"text\n"}
    )

    assert binary_findings(repo, {"logo.png": "the logo", "gone.bin": "removed"}) == [
        "tool: a tracked binary file; git rm --cached it and ignore it, or allow it with a reason",
        "gone.bin: allowed as binary but no tracked binary file; remove the entry",
    ]


def test_se_tracks_no_file_over_the_bound_outside_its_allow_list() -> None:
    assert large_findings(ROOT, LARGE_ALLOWED) == []
    assert all(reason.strip() for reason in LARGE_ALLOWED.values())


def test_a_tracked_file_over_the_bound_fails_and_a_stale_entry_too(tmp_path: Path) -> None:
    repo = fixture_repo(
        tmp_path, {"dump.json": b"x" * 201, "kept.json": b"x" * 201, "small.py": b"x" * 200}
    )

    assert large_findings(repo, {"kept.json": "needed", "small.py": "shrank"}, limit=200) == [
        "dump.json: 201 bytes, over 200; git rm --cached it and ignore it, split it, "
        "or allow it with a reason",
        "small.py: allowed as large but no tracked file over 200 bytes; remove the entry",
    ]


def test_se_has_no_marker_without_an_issue_in_scripts_or_tests() -> None:
    assert marker_findings(ROOT) == []


def test_a_marker_without_an_issue_fails(tmp_path: Path) -> None:
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


def called_name(call: ast.Call) -> str:
    function = call.func
    return function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")


# git is an outside thing with one door (rule book des-004): scripts/git_door.py runs every git command,
# tests/fake_git.py is its fake, and tests/test_git_door.py holds both to one contract. A git subprocess
# anywhere else fails: a command list that starts with "git" (not one announced with `.reading`), a
# command string that does, or Go's exec.Command of "git".
GIT_DOOR = ("scripts/git_door.py", "tests/fake_git.py", "kern/git/git.go")  # the last, kern's Go door
GIT_SCANNED = ("scripts", "tests", "components", "kern")
GO_GIT = re.compile(r'exec\.Command(?:Context)?\((?:\w+, )?"git"')
SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}
# Git subprocesses outside the door, each with how many its file holds and why it may: none is left.
# The list may only shrink: a file with more fails, and one with fewer fails until its count is lowered.
GIT_ALLOWED: dict[str, tuple[int, str]] = {}


def git_subprocess_lines(path: Path) -> list[int]:
    """The lines of `path` (Python or Go) that start a git subprocess."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".go":
        return [number for number, line in enumerate(text.splitlines(), 1) if GO_GIT.search(line)]
    tree = ast.parse(text, str(path))
    announced = {id(argument) for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and called_name(node) == "reading" for argument in node.args}
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) \
                and node.elts[0].value == "git" and id(node) not in announced:
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and called_name(node) in SUBPROCESS_CALLS and node.args \
                and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith("git "):
            lines.append(node.lineno)
    return sorted(lines)


def git_door_findings(root: Path, allowed: dict[str, tuple[int, str]]) -> list[str]:
    """Each file under `root` that starts more git subprocesses outside the door than `allowed` lets it,
    and each entry of `allowed` whose file now starts fewer."""
    found, counts = [], {}
    for folder in GIT_SCANNED:
        for path in sorted((root / folder).rglob("*")):
            name = path.relative_to(root).as_posix()
            if path.suffix in (".py", ".go") and path.is_file() and name not in GIT_DOOR \
                    and not {".venv", "testdata", "__pycache__"} & set(path.parts):
                if lines := git_subprocess_lines(path):
                    counts[name] = lines
    for name, lines in counts.items():
        limit = allowed.get(name, (0, ""))[0]
        if len(lines) > limit:
            found.append(f"{name}:{lines[0]}: {len(lines)} git subprocess(es) outside the door, {limit} allowed; "
                         f"run git through scripts/git_door.py (tests: the fake_git_door fixture)")
    for name, (limit, _) in allowed.items():
        if len(counts.get(name, [])) < limit:
            found.append(f"{name}: {len(counts.get(name, []))} git subprocess(es) outside the door, the allow "
                         f"list says {limit}; lower its entry (it may only shrink)")
    return found


def test_se_runs_git_only_through_its_door() -> None:
    assert git_door_findings(ROOT, GIT_ALLOWED) == []
    assert all(reason.strip() for _, reason in GIT_ALLOWED.values())


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


def test_the_files_allowed_real_git_exist_and_say_why() -> None:
    assert [name for name in REAL_GIT if not (ROOT / name).is_file()] == []
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


def test_the_runner_variables_are_ci_se_cloud_agent_and_every_github_variable() -> None:
    environment = {"CI": "true", "SE_CLOUD_AGENT": "a", "GITHUB_ACTIONS": "true", "GITHUB_SHA": "1",
                   "PATH": "/bin", "SE_METRICS": "x", "CIRCLE": "y"}
    assert runner_variables(environment) == ["CI", "SE_CLOUD_AGENT", "GITHUB_ACTIONS", "GITHUB_SHA"]


def test_a_test_that_needs_a_runner_variable_sets_it_itself(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert runner_variables(os.environ) == ["GITHUB_ACTIONS"]


def test_se_itself_passes() -> None:
    """se must stay publishable; uses se's local list when the checkout has one. History is SE's
    own line (tests/test_public_check.py `se_line`). It reads SE's own checkout through real git."""
    from test_public_check import run_check, se_line
    result = run_check("--repo", str(ROOT), "--history", se_line(ROOT))
    assert result.returncode == 0, result.stdout
