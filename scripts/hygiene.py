#!/usr/bin/env python3
"""SE's own checkout's hygiene: the checks of the repository, not of its code (AGENTS.md "Tests").

They read SE's checkout through git's real door, so they are a step of CI's `check` job, not tests;
their logic is unit-tested on the door's fake (`tests/test_repository.py`, `tests/test_references.py`).
`uv run python scripts/hygiene.py` runs them all on SE's checkout: exit code 0 passed, 1 findings,
each named with its check.

- binary: no tracked binary file (a NUL byte in its first BINARY_PEEK bytes, git's own test) outside
  BINARY_ALLOWED;
- large: no tracked file over MAX_BYTES outside LARGE_ALLOWED;
- marker: no marker of unfinished work in `scripts/` or `tests/` that names no issue;
- git-door: git runs only through its door (rule book des-004): `scripts/git_door.py` runs every git
  command, `tests/fake_git.py` is its fake and `kern/git/git.go` kern's door; a git subprocess anywhere
  else in scripts, tests, kern and the components fails, beyond GIT_ALLOWED;
- references: the agents, the skills (the rule book among them), README.md and AGENTS.md name no
  missing file and no undefined subcommand (`scripts/references.py`);
- public: the checkout passes its public check (pub-001), with its history: SE's own line (`se_line`).

An allow list's entry that no longer names such a file is refused, so the lists stay true.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

import git_door
import references

ROOT = Path(__file__).resolve().parents[1]

# The most bytes a tracked file holds outside LARGE_ALLOWED: source stays well under it, a build
# output, a data dump or a vendored bundle does not.
MAX_BYTES = 200_000

# Tracked binary files, each with the reason it is tracked.
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

GIT_DOOR = ("scripts/git_door.py", "tests/fake_git.py", "kern/git/git.go")  # the last, kern's Go door
GIT_SCANNED = ("scripts", "tests", "components", "kern")
GO_GIT = re.compile(r'exec\.Command(?:Context)?\((?:\w+, )?"git"')
SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}
# Git subprocesses outside the door, each with how many its file holds and why it may: none is left.
# The list may only shrink: a file with more fails, and one with fewer fails until its count is lowered.
GIT_ALLOWED: dict[str, tuple[int, str]] = {}

# The file whose presence in a commit's tree marks SE's own line (`se_line`).
SE_LINE_MARKER = "scripts/public_check.py"


class HygieneError(Exception):
    """A check that could not run, naming why."""


def tracked(repo: Path) -> list[str]:
    """The files git tracks in `repo` that exist in its working tree."""
    listed = git_door.run("ls-files", "-z", root=repo)
    if listed.returncode != 0:
        raise HygieneError(f"git ls-files in {repo}: {listed.stderr.strip()}")
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


def called_name(call: ast.Call) -> str:
    function = call.func
    return function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")


def git_subprocess_lines(path: Path) -> list[int]:
    """The lines of `path` (Python or Go) that start a git subprocess: a command list that starts
    with "git" (not one announced with `.reading`), a command string that does, or Go's
    exec.Command of "git"."""
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


def scanned_texts(root: Path) -> list[Path]:
    """The texts the references check scans: agents, skills (the rule book among them), README.md
    and AGENTS.md, those `root` has."""
    sources = [path for folder in ("src/agents", "src/skills")
               for path in sorted((root / folder).rglob("*.md"))]
    return [*sources, *(path for path in (root / "README.md", root / "AGENTS.md") if path.is_file())]


def reference_findings(root: Path) -> list[str]:
    """Each dangling reference of the scanned texts, named by its file."""
    return [f"{path.relative_to(root).as_posix()} {finding}"
            for path in scanned_texts(root)
            for finding in references.dangling(path.read_text(encoding="utf-8"), root, path)]


def se_line(root: Path) -> str:
    """The history revisions of SE's own line in `root`: every commit reachable from HEAD whose
    tree carries the public check itself (SE_LINE_MARKER), stopping at the parents that do not.

    main keeps the old Go line below SE's switch commit, by the owner's decision. That line never
    carried the public check, was published before it existed, and publishes an address this
    check refuses; blessing it with an allow entry would bless a real address (pub-002). So SE's
    own check covers SE's line only, and the CI gate on main checks every new commit. The rule is
    structural, so it holds on the rewritten se branch (no Go line), on GitHub's merge ref of a
    pull request into main (a merge of the Go line's tip and the switch commits on top of it) and
    on main after the squash merge (the Go line, then squash commits)."""
    listed = git_door.run("rev-list", "--parents", "HEAD", root=root)
    if listed.returncode != 0:
        raise HygieneError(f"git rev-list in {root}: {listed.stderr.strip()}")
    parents = {line.split()[0]: line.split()[1:] for line in listed.stdout.splitlines()}
    query = "".join(f"{sha}:{SE_LINE_MARKER}\n" for sha in parents)
    found = git_door.run("cat-file", "--batch-check", root=root, stdin=query.encode()).stdout.splitlines()
    own = {sha for sha, line in zip(parents, found) if not line.endswith(" missing")}
    tips = sorted({parent for sha in own for parent in parents[sha] if parent not in own})
    return " ".join(["HEAD", "--not", *tips]) if tips else "HEAD"


def public_findings(root: Path) -> list[str]:
    """The public check's verdict on `root` with SE's own line of history, where it refuses: its
    lines, which name locations and pattern labels, never the matched text."""
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "public_check.py"), "--repo", str(root),
         "--history", se_line(root)], capture_output=True, text=True, check=False)
    if done.returncode == 0:
        return []
    return [line for line in (done.stdout + done.stderr).splitlines() if line.strip()] or [
        f"public_check.py exited with {done.returncode}"]


def checks(root: Path) -> dict[str, list[str]]:
    """Each check's findings on `root`, in the order the module's docstring names them."""
    return {
        "binary": binary_findings(root, BINARY_ALLOWED),
        "large": large_findings(root, LARGE_ALLOWED, MAX_BYTES),
        "marker": marker_findings(root),
        "git-door": git_door_findings(root, GIT_ALLOWED),
        "references": reference_findings(root),
        "public": public_findings(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hygiene.py", description="SE's own checkout's hygiene: the checks of the repository, "
        "not of its code, through git's real door. Exit code 0 passed, 1 findings, 2 a check could not run.")
    parser.add_argument("--repo", type=Path, default=ROOT, help="the checkout checked (default: SE's own)")
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    try:
        found = checks(root)
    except HygieneError as error:
        print(f"hygiene: could not run: {error}")
        return 2
    for name, findings in found.items():
        for finding in findings:
            print(f"hygiene: {name}: {finding}")
    failed = [name for name, findings in found.items() if findings]
    if failed:
        print(f"hygiene: refused by {', '.join(failed)} ({sum(map(len, found.values()))} finding(s)) in {root}")
        return 1
    print(f"hygiene: passed ({len(found)} checks) in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
