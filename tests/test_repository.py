"""Repository hygiene: what any repository should not track, checked on se's own tree.

Three rules hold for every tracked file: no binary file, no file over `MAX_BYTES`, and no
marker of unfinished work in `scripts/` or `tests/` that names no issue. A file that must break
the first two goes in its allow list below with the reason it may; an entry that no longer names
such a file is refused, so the lists stay true.

One rule holds for the suite itself, so it behaves on GitHub's runner as it does locally: no test
starts with a runner's variable set (tests/conftest.py).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from quiet_git import quiet

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
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    quiet(repo)
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
