"""Repository hygiene: what any repository should not track, checked on se's own tree.

Three rules hold for every tracked file: no binary file, no file over `MAX_BYTES`, and no
marker of unfinished work in `scripts/` or `tests/` that names no issue. A file that must break
the first two goes in its allow list below with the reason it may; an entry that no longer names
such a file is refused, so the lists stay true.

Two rules hold for the suite itself, so it behaves on GitHub's runner as it does locally: every git
repository a test creates or clones comes from the quiet helper (tests/quiet_git.py), and no test
starts with a runner's variable set (tests/conftest.py).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest
import quiet_git
from conftest import runner_variables

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
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    return [p for p in out.decode().split("\0") if p and (repo / p).is_file()]


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
    quiet_git.init(repo)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
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


# A git repository created or cloned without tests/quiet_git.py runs background maintenance, whose lock
# files fail a copy on the runner. Its `init` and `clone` are the only ones in tests/.
QUIET_HELPER = "quiet_git.py"
UNQUIET = ("init", "clone")
VALUED_OPTIONS = ("-C", "-c")  # git's options before the subcommand that take a value


def git_subcommand(arguments: list[ast.expr]) -> str | None:
    """The subcommand among git's `arguments`: the first literal that is no option or option value."""
    skip = False
    for argument in arguments:
        if skip:
            skip = False
        elif isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if argument.value in VALUED_OPTIONS:
                skip = True
            elif not argument.value.startswith("-"):
                return argument.value
    return None


def called_name(call: ast.Call) -> str:
    function = call.func
    return function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")


def unquiet_git_findings(root: Path) -> list[str]:
    """Each git `init` or `clone` under `root`/tests outside the quiet helper: a call to a function
    named like git (`git`, `git_ok`), or a command list that starts with "git"."""
    found = []
    for path in sorted((root / "tests").rglob("*.py")):
        if path.name == QUIET_HELPER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in sorted(ast.walk(tree), key=lambda node: getattr(node, "lineno", 0)):
            arguments = None
            if isinstance(node, ast.Call) and "git" in called_name(node).lower():
                arguments = node.args
            elif isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) \
                    and node.elts[0].value == "git":
                arguments = node.elts[1:]
            command = git_subcommand(arguments) if arguments else None
            if command in UNQUIET:
                where = path.relative_to(root).as_posix()
                found.append(f"{where}:{node.lineno}: git {command} outside the quiet helper; "
                             f"use quiet_git.{command} (tests/{QUIET_HELPER})")
    return found


def test_se_creates_and_clones_git_repositories_only_through_the_quiet_helper() -> None:
    assert unquiet_git_findings(ROOT) == []


def test_a_bare_git_init_or_clone_in_a_fixture_fails(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "test_fixture.py"
    fixture.parent.mkdir()
    fixture.write_text(
        "import subprocess\n"
        "import quiet_git\n"
        "def origin(path):\n"
        "    subprocess.run([\"git\", \"init\", \"-q\", \"--bare\", str(path)], check=True)\n"
        "def checkout(path):\n"
        "    git(path.parent, \"clone\", \"-q\", str(path / \"origin\"), str(path))\n"
        "    git_ok(\"-C\", str(path), \"-c\", \"user.name=alice\", \"init\")\n"
        "    git(path, \"commit\", \"-m\", \"init\")\n"
        "    quiet_git.init(path / \"quiet\")\n"
        "    quiet_git.clone(path, path / \"copy\")\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / QUIET_HELPER).write_text('git("init", "-q")\n', encoding="utf-8")

    assert unquiet_git_findings(tmp_path) == [
        "tests/test_fixture.py:4: git init outside the quiet helper; use quiet_git.init (tests/quiet_git.py)",
        "tests/test_fixture.py:6: git clone outside the quiet helper; use quiet_git.clone (tests/quiet_git.py)",
        "tests/test_fixture.py:7: git init outside the quiet helper; use quiet_git.init (tests/quiet_git.py)",
    ]


def test_the_quiet_helper_creates_and_clones_quiet_repositories(tmp_path: Path) -> None:
    origin = quiet_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    checkout = quiet_git.clone(origin, tmp_path / "checkout")
    for repository in (origin, checkout):
        read = lambda key: subprocess.run(["git", "-C", str(repository), "config", key],  # noqa: E731
                                          capture_output=True, text=True, check=True).stdout.strip()
        assert (read("maintenance.auto"), read("gc.auto")) == ("false", "0")
    with pytest.raises(RuntimeError, match="git clone .* failed: "):
        quiet_git.clone(tmp_path / "missing", tmp_path / "nothing")


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
