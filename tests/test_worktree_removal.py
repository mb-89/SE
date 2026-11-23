"""SE's worktree clean-up leaves every link alone.

Holds the bullet "Removal happens only after integration" of `src/skills/work-model/SKILL.md`
"Worktrees", and its words "never `git worktree remove --force` (it follows links into other
checkouts)", for SE's own clean-up steps and forced removals:

- the two steps before `git worktree remove`, `work_tickets.remove_private_queue` and
  `work_tickets.make_worktree_removable`, change nothing outside the worktree through a symbolic
  link or, on Windows, a directory junction, also when a deletion is retried;
- every forced worktree removal in SE's scripts is one of `FORCED_REMOVALS`, each with its reason.

It runs no git: a worktree here is a plain folder under `tmp_path`.
"""

from __future__ import annotations

import ast
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

import work_tickets

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"

# Each forced worktree removal SE's scripts may make, keyed by file and enclosing function.
FORCED_REMOVALS = {
    ("scripts/work_tickets.py", "ref_checkout"): (
        "the temporary worktree of `suite --compare`, made by SE under a temporary folder and "
        "removed in a `finally`"
    ),
    ("scripts/se_start.py", "_trial"): (
        "the start refresh's trial worktree, made by SE under a temporary folder and removed in "
        "a `finally`"
    ),
}

LINK_KINDS = [
    "symlink",
    pytest.param("junction", marks=pytest.mark.skipif(os.name != "nt", reason="junctions are Windows'")),
]


def make_link(kind: str, link: Path, target: Path) -> None:
    """A link of `kind` at `link` to the folder `target`, or the case is skipped."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks are unavailable")
        return
    # A junction made in this process, as tests/test_work_tickets.py
    # test_symlinked_state_directory_cannot_escape_worktree makes it: no PowerShell starts.
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as error:
        pytest.skip(f"directory junctions are unavailable: {error}")


def snapshot(outside: Path) -> dict[str, object]:
    held = outside / "held.txt"
    return {
        "mode": stat.S_IMODE(os.stat(outside).st_mode),
        "entries": sorted(os.listdir(outside)),
        "bytes": held.read_bytes(),
        "file mode": stat.S_IMODE(os.stat(held).st_mode),
    }


@pytest.fixture
def outside(tmp_path: Path) -> Iterator[Path]:
    """A read-only folder beside the worktree that holds one read-only file."""
    folder = tmp_path / "outside"
    folder.mkdir()
    held = folder / "held.txt"
    held.write_bytes(b"another checkout's object\n")
    held.chmod(stat.S_IREAD)
    folder.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        yield folder
    finally:
        # Write access back, so tmp_path can be cleaned whatever the step did.
        folder.chmod(stat.S_IRWXU)
        held.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "worktree"
    folder.mkdir()
    return folder


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_removing_the_private_folder_leaves_a_linked_folder_alone(kind: str, root: Path, outside: Path) -> None:
    make_link(kind, root / ".se" / "linked", outside)
    before = snapshot(outside)
    work_tickets.remove_private_queue(root / ".se")
    assert not os.path.lexists(root / ".se")
    assert snapshot(outside) == before


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_a_deletion_that_fails_once_leaves_a_linked_folder_alone(
    kind: str, root: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = root / ".se" / "linked"
    make_link(kind, link, outside)
    real_unlink = os.unlink
    failed: list[str] = []

    def unlink_failing_once(path, *args, **kwargs):
        if Path(os.fsdecode(path)).name == link.name and not failed:
            failed.append(os.fsdecode(path))
            raise PermissionError(f"{path}: refused once by the test")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink_failing_once)
    before = snapshot(outside)
    try:
        work_tickets.remove_private_queue(root / ".se")
    except OSError:
        pass  # the outside folder is unchanged whether or not the step raises
    finally:
        monkeypatch.undo()
    assert failed, "the deletion of the link never failed: the error handler did not run"
    assert snapshot(outside) == before


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_making_the_worktree_removable_leaves_a_linked_folder_alone(kind: str, root: Path, outside: Path) -> None:
    make_link(kind, root / "sub" / "linked", outside)
    own = root / "sub" / "own.txt"
    own.write_text("the worktree's own\n", encoding="utf-8")
    own.chmod(stat.S_IREAD)
    before = snapshot(outside)
    work_tickets.make_worktree_removable(root)
    assert snapshot(outside) == before
    assert os.stat(own).st_mode & stat.S_IWUSR, "the step still makes the worktree's own files writable"


def forced_removals(source: str, name: str) -> list[tuple[str, str, int]]:
    """Each call in `source` (the file `name`) whose string arguments, directly or inside a list or
    tuple argument, hold "worktree", "remove" and "--force" or "-f": (file, enclosing function, line)."""
    found: list[tuple[str, str, int]] = []

    def strings(node: ast.expr) -> list[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [s for element in node.elts for s in strings(element)]
        if isinstance(node, ast.Starred):
            return strings(node.value)
        return []

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Call):
            held = {s for argument in node.args for s in strings(argument)}
            if {"worktree", "remove"} <= held and held & {"--force", "-f"}:
                found.append((name, function, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source, filename=name), "<module>")
    return found


def test_every_forced_worktree_removal_is_listed_with_its_reason() -> None:
    found = [
        hit
        for path in sorted(SCRIPTS.rglob("*.py"))
        for hit in forced_removals(path.read_text(encoding="utf-8"), path.relative_to(PROJECT).as_posix())
    ]
    unlisted = [f"{file}:{line} ({function})" for file, function, line in found if (file, function) not in FORCED_REMOVALS]
    assert not unlisted, f"forced worktree removals not in FORCED_REMOVALS: {unlisted}"
    stale = sorted(set(FORCED_REMOVALS) - {(file, function) for file, function, _ in found})
    assert not stale, f"FORCED_REMOVALS entries that match no call: {stale}"
    assert all(reason.strip() for reason in FORCED_REMOVALS.values())
    shell = [
        f"{path.relative_to(PROJECT).as_posix()}:{number}"
        for pattern in ("*.sh", "*.ps1")
        for path in sorted(SCRIPTS.glob(pattern))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "worktree remove" in line and {"--force", "-f"} & set(line.split())
    ]
    assert not shell, f"forced worktree removals in SE's shell scripts: {shell}"


def test_a_third_forced_removal_is_named_with_its_file_and_line() -> None:
    source = (
        "def ref_checkout(root, path):\n"
        "    run_git(root, 'worktree', 'remove', '--force', str(path))\n"
        "\n"
        "def tidy(root, path):\n"
        "    git_door.run(['worktree', 'remove', '-f', str(path)], cwd=root)\n"
    )
    found = forced_removals(source, "scripts/work_tickets.py")
    assert found == [
        ("scripts/work_tickets.py", "ref_checkout", 2),
        ("scripts/work_tickets.py", "tidy", 5),
    ]
    assert [(f, fn, line) for f, fn, line in found if (f, fn) not in FORCED_REMOVALS] == [
        ("scripts/work_tickets.py", "tidy", 5)
    ]
