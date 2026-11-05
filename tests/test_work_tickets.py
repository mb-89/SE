import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[1]
HELPER = PROJECT / "scripts" / "work_tickets.py"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    # Nested Git repositories add over 100 characters below the case root; rooted in the
    # checkout they exceeded the Windows path limit in deep worktrees.
    root = tmp_path / "worktree"
    root.mkdir()
    return root


def run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )


def command(worktree: Path, *args: str) -> list[str]:
    return [*args, "--worktree", str(worktree)]


def initialize(worktree: Path) -> None:
    result = run_helper(*command(worktree, "init"))
    assert result.returncode == 0, result.stderr


def create(worktree: Path, ticket_id: str = "T-1") -> Path:
    result = run_helper(
        *command(worktree, "create"), "--id", ticket_id, "--title", "Example ticket"
    )
    assert result.returncode == 0, result.stderr
    return worktree / ".se" / "work" / "todo" / f"{ticket_id}.md"


def move(worktree: Path, ticket_id: str, state: str) -> subprocess.CompletedProcess[str]:
    return run_helper(*command(worktree, "move"), "--id", ticket_id, "--to", state)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def git_worktree(case_root: Path) -> tuple[Path, Path]:
    coordinator = case_root / "coordinator"
    worker = case_root / "worker"
    coordinator.mkdir(parents=True)
    assert git(coordinator, "init", "-b", "coordinator").returncode == 0
    assert git(coordinator, "config", "user.name", "Worker test").returncode == 0
    assert git(coordinator, "config", "user.email", "worker-test@example.invalid").returncode == 0
    (coordinator / ".gitignore").write_text("/.se/\n", encoding="utf-8")
    (coordinator / "README").write_text("baseline\n", encoding="utf-8")
    assert git(coordinator, "add", ".").returncode == 0
    assert git(coordinator, "commit", "-m", "baseline").returncode == 0
    assert git(coordinator, "worktree", "add", "-b", "worker", str(worker)).returncode == 0
    return coordinator, worker


def test_guard_reports_removed_tests_until_field_report_names_them(worktree: Path) -> None:
    repository = worktree.parent / "guard-case"
    repository.mkdir()
    assert git(repository, "init", "-b", "main").returncode == 0
    assert git(repository, "config", "user.name", "Guard test").returncode == 0
    assert git(repository, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (repository / "test_example.py").write_text(
        "def test_removed_python():\n    pass\n\n"
        "def test_kept_python():\n    pass\n",
        encoding="utf-8",
    )
    (repository / "example.test.js").write_text(
        'it("removed JavaScript", () => {});\n'
        'test("kept JavaScript", () => {});\n',
        encoding="utf-8",
    )
    assert git(repository, "add", ".").returncode == 0
    assert git(repository, "commit", "-m", "baseline tests").returncode == 0
    assert git(repository, "checkout", "-b", "remove-tests").returncode == 0
    (repository / "test_example.py").write_text(
        "def test_kept_python():\n    pass\n",
        encoding="utf-8",
    )
    (repository / "example.test.js").write_text(
        'test("kept JavaScript", () => {});\n',
        encoding="utf-8",
    )
    assert git(repository, "commit", "-am", "remove protected tests").returncode == 0
    report = repository / "field-report.md"
    report.write_text(
        "## Removed behaviour and deleted or weakened tests\n\nNone\n",
        encoding="utf-8",
    )

    guarded = run_helper(
        "guard", "--branch", "remove-tests", "--field-report", str(report),
        "--worktree", str(repository),
    )
    assert guarded.returncode != 0
    assert "test_removed_python" in guarded.stderr
    assert "removed JavaScript" in guarded.stderr

    report.write_text(
        "## Removed behaviour and deleted or weakened tests\n\n"
        "- `test_removed_python`: user approved its removal.\n"
        '- "removed JavaScript": user approved its removal.\n',
        encoding="utf-8",
    )
    approved = run_helper(
        "guard", "--branch", "remove-tests", "--field-report", str(report),
        "--worktree", str(repository),
    )
    assert approved.returncode == 0, approved.stderr
    assert "test_removed_python" in approved.stdout
    assert "removed JavaScript" in approved.stdout


def test_queue_lifecycle_requires_checklist_and_evidence(worktree: Path) -> None:
    initialize(worktree)
    initialize(worktree)
    queue = worktree / ".se" / "work"
    assert {path.name for path in queue.iterdir()} == {"todo", "held", "done", "notes"}
    empty_status = run_helper(*command(worktree, "status"), "--json")
    assert empty_status.returncode == 0
    empty_report = json.loads(empty_status.stdout)
    assert empty_report["initialized"] is True
    assert empty_report["complete"] is True

    ticket = create(worktree)
    body = ticket.read_text(encoding="utf-8")
    assert all(f"## {heading}" in body for heading in (
        "Design", "Scope", "Dependencies", "Acceptance", "Evidence"
    ))
    assert "- [ ]" in body

    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = queue / "held" / "T-1.md"
    assert held_ticket.exists() and not ticket.exists()
    held_status = run_helper(*command(worktree, "status"), "--json")
    assert json.loads(held_status.stdout)["complete"] is False
    assert move(worktree, "T-1", "done").returncode != 0
    assert "not found" in move(worktree, "missing", "held").stderr.lower()
    returned = move(worktree, "T-1", "todo")
    assert returned.returncode == 0, returned.stderr
    assert ticket.exists() and not held_ticket.exists()
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = queue / "held" / "T-1.md"

    body = held_ticket.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
    held_ticket.write_text(body, encoding="utf-8")
    assert move(worktree, "T-1", "done").returncode != 0
    held_ticket.write_text(body + "\nEvidence: focused test passed.\n", encoding="utf-8")
    completed = move(worktree, "T-1", "done")
    assert completed.returncode == 0, completed.stderr

    (queue / "notes" / "result.txt").write_text("validated", encoding="utf-8")
    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["initialized"] is True
    assert status["counts"] == {"todo": 0, "held": 0, "done": 1}
    assert status["tickets"] == {"todo": [], "held": [], "done": ["T-1"]}
    assert status["notes"] == ["result.txt"]
    assert status["note_counts"] == {"resolved": 0, "unresolved": 1}
    assert "validated" not in result.stdout
    assert status["complete"] is False
    assert "percent" not in result.stdout.lower()
    assert move(worktree, "T-1", "todo").returncode != 0
    reviewed = run_helper(
        *command(worktree, "review-note"),
        "--note", "result.txt", "--disposition", "Review complete",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    reviewed_status = run_helper(*command(worktree, "status"), "--json")
    assert json.loads(reviewed_status.stdout)["complete"] is True


def test_done_validation_checks_every_acceptance_section(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    content = ticket.read_text(encoding="utf-8")
    content = content.replace(
        "## Evidence\n",
        "## Acceptance: additional criteria\n\n"
        "- [ ] Complete the additional criterion.\n\n"
        "## Evidence\n",
    ).replace("- [ ] Add a checkable acceptance criterion.", "- [x] Add a checkable acceptance criterion.")
    ticket.write_text(content, encoding="utf-8")
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = worktree / ".se" / "work" / "held" / "T-1.md"
    held_ticket.write_text(
        held_ticket.read_text(encoding="utf-8") + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )

    incomplete = move(worktree, "T-1", "done")
    assert incomplete.returncode != 0
    assert "unchecked" in incomplete.stderr.lower()

    held_ticket.write_text(
        held_ticket.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    complete = move(worktree, "T-1", "done")
    assert complete.returncode == 0, complete.stderr


def test_done_validation_lists_unchecked_acceptance_items(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    ticket.write_text(
        ticket.read_text(encoding="utf-8") + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr

    incomplete = move(worktree, "T-1", "done")
    assert incomplete.returncode != 0
    assert "Add a checkable acceptance criterion." in incomplete.stderr


def test_done_validation_allows_tickets_without_checklists(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    ticket.write_text(
        ticket.read_text(encoding="utf-8")
        .replace("- [ ] Add a checkable acceptance criterion.", "No checklist needed.")
        + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr

    completed = move(worktree, "T-1", "done")
    assert completed.returncode == 0, completed.stderr


def test_move_rejects_acceptance_override_flag(worktree: Path) -> None:
    initialize(worktree)
    result = run_helper(
        *command(worktree, "move"),
        "--id",
        "T-1",
        "--to",
        "done",
        "--force",
    )
    assert result.returncode != 0
    assert "unrecognized arguments: --force" in result.stderr


def test_status_uninitialized_does_not_create_queue(worktree: Path) -> None:
    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["initialized"] is False
    assert status["complete"] is False
    assert status["cleanup_eligible"] is False
    assert status["note_counts"] == {"resolved": 0, "unresolved": 0}
    assert status["errors"]
    assert not (worktree / ".se").exists()


@pytest.mark.parametrize("ticket_id", ["../escape", "..", "bad/name", ""])
def test_create_rejects_unsafe_ids(worktree: Path, ticket_id: str) -> None:
    initialize(worktree)
    result = run_helper(
        *command(worktree, "create"), "--id", ticket_id, "--title", "Unsafe"
    )
    assert result.returncode != 0
    assert not (worktree / "escape.md").exists()


def test_create_and_move_never_overwrite_existing_ticket(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    original = ticket.read_text(encoding="utf-8")
    duplicate = run_helper(
        *command(worktree, "create"), "--id", "T-1", "--title", "Replacement"
    )
    assert duplicate.returncode != 0
    assert ticket.read_text(encoding="utf-8") == original

    collision = worktree / ".se" / "work" / "held" / "T-1.md"
    collision.write_text("do not overwrite", encoding="utf-8")
    result = move(worktree, "T-1", "held")
    assert result.returncode != 0
    assert collision.read_text(encoding="utf-8") == "do not overwrite"


def test_duplicate_ids_are_reported_and_move_is_ambiguous(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    duplicate = worktree / ".se" / "work" / "held" / "copy.md"
    duplicate.write_text(ticket.read_text(encoding="utf-8"), encoding="utf-8")

    status = run_helper(*command(worktree, "status"), "--json")
    assert status.returncode != 0
    report = json.loads(status.stdout)
    assert any("duplicate" in error.lower() for error in report["errors"])
    assert report["complete"] is False
    moved = move(worktree, "T-1", "held")
    assert moved.returncode != 0
    assert "ambiguous" in moved.stderr.lower()


def test_status_reports_malformed_state(worktree: Path) -> None:
    initialize(worktree)
    (worktree / ".se" / "work" / "todo" / "broken.md").write_text(
        "not a ticket", encoding="utf-8"
    )

    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert any("malformed" in error.lower() for error in report["errors"])
    assert report["complete"] is False


def test_symlinked_state_directory_cannot_escape_worktree(worktree: Path) -> None:
    initialize(worktree)
    outside = worktree.parent / "outside"
    outside.mkdir()
    todo = worktree / ".se" / "work" / "todo"
    todo.rmdir()
    if os.name == "nt":
        link_path = str(todo).replace("'", "''")
        target_path = str(outside).replace("'", "''")
        junction = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"New-Item -ItemType Junction -Path '{link_path}' "
                f"-Target '{target_path}' | Out-Null",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(
                "directory junctions are unavailable: "
                f"{junction.stdout}{junction.stderr}".strip()
            )
    else:
        try:
            os.symlink(outside, todo, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks are unavailable")

    result = run_helper(
        *command(worktree, "create"), "--id", "T-escape", "--title", "Escape"
    )
    assert result.returncode != 0
    assert list(outside.iterdir()) == []


def test_review_note_appends_local_disposition_without_leaking_text(worktree: Path) -> None:
    initialize(worktree)
    note = worktree / ".se" / "work" / "notes" / "private.txt"
    private_text = "PRIVATE unfiltered finding: credentials and details"
    note.write_text(private_text, encoding="utf-8")

    before = run_helper(*command(worktree, "status"), "--json")
    assert before.returncode == 0, before.stderr
    report = json.loads(before.stdout)
    assert report["note_counts"] == {"resolved": 0, "unresolved": 1}
    assert report["complete"] is False
    assert private_text not in before.stdout

    reviewed = run_helper(
        *command(worktree, "review-note"),
        "--note", "private.txt",
        "--disposition", "Resolved after owner review",
        "--backlog-ref", "backlog/future.md",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    assert "Resolved after owner review" not in reviewed.stdout
    assert private_text in note.read_text(encoding="utf-8")
    assert "Disposition: Resolved after owner review" in note.read_text(encoding="utf-8")
    assert "backlog-ref: backlog/future.md" in note.read_text(encoding="utf-8")

    after = run_helper(*command(worktree, "status"), "--json")
    report = json.loads(after.stdout)
    assert report["note_counts"] == {"resolved": 1, "unresolved": 0}
    assert report["complete"] is True
    assert report["notes"] == ["private.txt"]
    assert private_text not in after.stdout
    assert "Resolved after owner review" not in after.stdout
    assert "backlog/future.md" not in after.stdout


def test_close_refuses_active_queue_and_unresolved_notes(worktree: Path) -> None:
    initialize(worktree)
    create(worktree)
    unresolved = worktree / ".se" / "work" / "notes" / "question.txt"
    unresolved.write_text("private question", encoding="utf-8")

    result = run_helper(*command(worktree, "close"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["cleanup_eligible"] is False
    assert report["complete"] is False
    assert "todo" in " ".join(report["cleanup_reasons"]).lower()
    assert "unresolved" in " ".join(report["cleanup_reasons"]).lower()
    assert unresolved.read_text(encoding="utf-8") == "private question"


def test_close_refuses_invalid_completed_ticket(worktree: Path) -> None:
    initialize(worktree)
    create(worktree)
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0
    held_path = worktree / ".se" / "work" / "held" / "T-1.md"
    body = held_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
    held_path.write_text(body + "\nEvidence: present.\n", encoding="utf-8")
    assert move(worktree, "T-1", "done").returncode == 0
    done_path = worktree / ".se" / "work" / "done" / "T-1.md"
    done_path.write_text(
        done_path.read_text(encoding="utf-8").replace("- [x]", "- [ ]"),
        encoding="utf-8",
    )

    result = run_helper(*command(worktree, "close"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert any("invalid completed ticket" in error.lower() for error in report["errors"])
    assert report["complete"] is False
    assert report["cleanup_eligible"] is False


def test_close_checks_git_cleanliness_primary_and_integration(worktree: Path) -> None:
    coordinator, worker = git_worktree(worktree.parent / "git-case")
    initialize(worker)
    (worker / "unintegrated.txt").write_text("not yet integrated\n", encoding="utf-8")
    assert git(worker, "add", "unintegrated.txt").returncode == 0
    assert git(worker, "commit", "-m", "unintegrated worker change").returncode == 0

    not_integrated = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert not_integrated.returncode != 0
    assert "integrat" in not_integrated.stdout.lower()

    (worker / "change.txt").write_text("worker change\n", encoding="utf-8")
    assert git(worker, "add", "change.txt").returncode == 0
    assert git(worker, "commit", "-m", "worker change").returncode == 0
    (worker / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    dirty = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert dirty.returncode != 0
    assert "dirty" in dirty.stdout.lower()
    (worker / "dirty.txt").unlink()

    assert git(coordinator, "merge", "--no-ff", "worker", "-m", "integrate worker").returncode == 0
    note = worker / ".se" / "work" / "notes" / "reviewed.txt"
    note.write_text("short local reminder", encoding="utf-8")
    reviewed_note = run_helper(
        *command(worker, "review-note"),
        "--note", note.name,
        "--disposition", "No follow-up required",
    )
    assert reviewed_note.returncode == 0, reviewed_note.stderr
    clean = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    clean_report = json.loads(clean.stdout)
    assert clean_report["cleanup_eligible"] is True
    assert clean_report["note_counts"] == {"resolved": 1, "unresolved": 0}

    primary = run_helper(
        *command(coordinator, "close"), "--integration-target", "coordinator", "--json"
    )
    assert primary.returncode != 0
    assert "primary" in primary.stdout.lower()


def test_close_remove_requires_explicit_target_and_removes_normally(worktree: Path) -> None:
    coordinator, worker = git_worktree(worktree.parent / "remove-case")
    initialize(worker)
    (worker / "change.txt").write_text("integrated\n", encoding="utf-8")
    assert git(worker, "add", "change.txt").returncode == 0
    assert git(worker, "commit", "-m", "worker work").returncode == 0
    assert git(coordinator, "merge", "--no-ff", "worker", "-m", "integrate worker").returncode == 0

    missing_target = run_helper(*command(worker, "close"), "--remove", "--json")
    assert missing_target.returncode != 0
    assert worker.exists()

    removed = run_helper(
        *command(worker, "close"),
        "--remove",
        "--integration-target", "coordinator",
        "--json",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout)["removed"] is True
    assert not worker.exists()


def test_se_is_ignored_in_full() -> None:
    result = git(PROJECT, "check-ignore", ".se/work/notes/private.txt")
    assert result.returncode == 0
