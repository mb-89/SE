"""The filing check (README "Retro due"): `work_tickets.py file` and `backlog file` run it first;
a due retro or overhaul is filed first and every other filing is refused while one is due or open,
naming it. Running work goes on: only filing runs the check."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

import overhaul
import retro
import work_tickets

REPO = "github.com/owner/repo"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def issue(number: int, title: str, closed: str | None = None, created: str = "",
          labels: tuple[str, ...] = ("work",), updated: str = "") -> dict:
    return {"number": number, "title": title, "state": "closed" if closed else "open",
            "closed_at": closed, "created_at": created, "updated_at": updated or closed or created,
            "state_reason": "completed" if closed else None, "body": "",
            "labels": [{"name": name} for name in labels]}


def landing(number: int, merged: str) -> dict:
    return {"number": 1000 + number, "title": f"n{number}", "body": f"Fixes #{number}",
            "base": {"ref": "main"}, "head": {"ref": f"n{number}", "sha": ""}, "merged_at": merged}


LAST_RETRO = issue(1, "retro-due-20261101", "2026-11-02T00:00:00Z", "2026-11-01T00:00:00Z",
                   ("retro",))
LAST_OVERHAUL = issue(2, "overhaul-20261101", "2026-11-02T00:00:00Z", "2026-11-01T00:00:00Z",
                      ("discovery",))


class Door:
    """The check's reads: the closed and open issues and the pull requests, as given."""

    def __init__(self, closed=(), opened=(), pulls=()) -> None:
        self.closed = [LAST_RETRO, LAST_OVERHAUL, *closed]
        self.opened, self.given_pulls, self.missing = list(opened), list(pulls), []

    def closed_issues(self):
        return self.closed

    def open_issues(self):
        return self.opened

    def pulls(self):
        return self.given_pulls

    def issue(self, number):
        return next(item for item in [*self.closed, *self.opened] if item["number"] == number)


def landed(count: int, when: str = "2026-11-10T00:00:00Z") -> dict:
    """`count` work issues that came back: closed and landed."""
    return {"closed": [issue(n, f"n{n}", when) for n in range(10, 10 + count)],
            "pulls": [landing(n, when) for n in range(10, 10 + count)]}


@pytest.fixture
def filed(monkeypatch, tmp_path) -> list[str]:
    """The runs the check files, recorded; the checkout's integration branch is main."""
    runs: list[str] = []
    monkeypatch.setattr(work_tickets, "integration_branch", lambda root: "main")
    monkeypatch.setattr(retro, "file_new", lambda root, repo: runs.append("retro")
                        or f"Filed work issue https://github.com/owner/repo/issues/9{len(runs)}")
    monkeypatch.setattr(overhaul, "file_new", lambda root, repo: runs.append("overhaul")
                        or f"Filed work issue https://github.com/owner/repo/issues/9{len(runs)}")
    return runs


def check(tmp_path: Path, door: Door, command: str = "file") -> None:
    work_tickets.filing_check(tmp_path, REPO, command, door, NOW)


def test_twenty_issues_opened_in_one_session_make_no_retro_due_and_filing_goes_on(tmp_path,
                                                                                   filed):
    """A productive session that files 20 issues is not held back by them: opening counts
    nothing."""
    opened = [issue(n, f"n{n}", created="2026-11-22T10:00:00Z") for n in range(10, 30)]
    check(tmp_path, Door(opened=opened))
    assert filed == []


def test_twenty_that_come_back_file_the_retro_first_and_refuse_the_filing(tmp_path, filed):
    with pytest.raises(work_tickets.ReviewDueError) as refused:
        check(tmp_path, Door(**landed(20)))
    assert filed == ["retro"]
    assert str(refused.value) == (
        "work_tickets.py file: a retro is due (20 came back since the last retro (due at 20)), "
        "filed first: Filed work issue https://github.com/owner/repo/issues/91; file files no "
        "other issue until the person has decided every finding of it in an SE session and it is "
        "closed; running work goes on (README \"Retro due\")")
    assert issubclass(work_tickets.ReviewDueError, work_tickets.QueueError)


def test_filing_is_refused_while_a_retro_is_open_naming_it_and_nothing_is_filed(tmp_path, filed):
    """The open retro holds every filing back, due or not, until it is closed; what keeps coming
    back while it is open counts towards the next one."""
    open_retro = issue(40, "retro-due-20261120", created="2026-11-20T00:00:00Z", labels=("retro",))
    for command in ("file", "backlog file"):
        with pytest.raises(work_tickets.ReviewDueError,
                           match=rf"^work_tickets.py {command}: the retro #40 is open; {command} "
                                 "files no other issue until the person has decided"):
            check(tmp_path, Door(opened=[open_retro], **landed(25)), command)
    assert filed == []
    found = retro.countdowns(Door(opened=[open_retro], **landed(3, "2026-11-21T00:00:00Z")),
                             REPO, "main", tmp_path, NOW)
    assert (found["retro"].count, found["retro"].open) == (3, [40])


def test_an_open_overhaul_holds_filing_back_too(tmp_path, filed):
    open_overhaul = issue(41, "overhaul-20261120", created="2026-11-20T00:00:00Z",
                          labels=("discovery",))
    with pytest.raises(work_tickets.ReviewDueError, match=r"the overhaul #41 is open"):
        check(tmp_path, Door(opened=[open_overhaul]))
    assert filed == []


def test_a_due_overhaul_is_filed_first_and_a_due_retro_before_it(tmp_path, filed):
    """Three retros closed since the last overhaul started (#1, #20, #21) make one due; where a retro is due as
    well, the retro is filed first, as the overhaul reads the closed retros."""
    retros = [issue(n, f"retro-due-202611{n}", f"2026-11-{n}T12:00:00Z", f"2026-11-{n}T00:00:00Z",
                    ("retro",)) for n in (20, 21)]
    with pytest.raises(work_tickets.ReviewDueError, match=r"^work_tickets.py file: an overhaul is "
                       r"due \(3 retros closed since the last overhaul \(due at 3\)\)"):
        check(tmp_path, Door(closed=retros))
    assert filed == ["overhaul"]
    filed.clear()
    late = {**landed(20, "2026-11-22T13:00:00Z")}
    with pytest.raises(work_tickets.ReviewDueError, match="a retro is due"):
        check(tmp_path, Door(closed=[*retros, *late["closed"]], pulls=late["pulls"]))
    assert filed == ["retro"]


def test_the_counters_reset_at_the_retros_start(tmp_path, filed):
    """Once the due retro has started (been filed) and closed, what it covered no longer counts:
    the next filing goes on."""
    door = Door(**landed(20))
    with pytest.raises(work_tickets.ReviewDueError):
        check(tmp_path, door)
    door.closed.append(issue(91, "retro-due-20261123", "2026-11-23T11:00:00Z",
                             "2026-11-23T10:00:00Z", ("retro",)))
    filed.clear()
    check(tmp_path, door)
    assert filed == []


def test_without_gh_or_relay_the_plan_names_the_check_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "filing_door", lambda root, repo: None)
    work_tickets.filing_check(tmp_path, REPO, "file")
    assert capsys.readouterr().out == (
        f"Before filing: run `uv run python {work_tickets.SE_ROOT.as_posix()}/scripts/retro.py "
        f"due --worktree {tmp_path.as_posix()}` and its plan; while it names a retro or an "
        "overhaul due or open, file nothing else (README \"Retro due\")\n")


def test_file_runs_the_check_first_and_fails_naming_the_open_retro(tmp_path, monkeypatch,
                                                                   capsys, fake_git_door):
    open_retro = issue(40, "retro-due-20261120", created="2026-11-20T00:00:00Z", labels=("retro",))
    monkeypatch.setattr(work_tickets, "integration_branch", lambda root: "main")
    monkeypatch.setattr(work_tickets, "filing_door", lambda root, repo: Door(opened=[open_retro]))
    monkeypatch.setattr(work_tickets, "filed_once",
                        lambda *a, **k: pytest.fail("nothing is filed while a retro is open"))
    body = tmp_path / "work.md"
    body.write_text("## Goal\n\nA package.\n", encoding="utf-8")
    for command in (["file", "--title", "a-package"], ["backlog", "file", "--title", "an-idea"]):
        assert work_tickets.main([*command, "--body-file", str(body), "--repo", REPO,
                                  "--worktree", str(tmp_path)]) == 1
        assert "the retro #40 is open" in capsys.readouterr().err


def test_a_retro_the_check_files_comes_from_its_template_with_no_ready_label(
        tmp_path, monkeypatch, capsys, fake_git_door):
    """The retro is filed from .github/ISSUE_TEMPLATE/retro.md, labelled retro and not ready (a
    retro agent runs it, never a worker), past the check that filed it."""
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "relay_door", lambda root, repo: None)
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261123")
    monkeypatch.setattr(work_tickets, "filing_check",
                        lambda *a, **k: pytest.fail("the run is filed past the check"))
    retro.file_new(tmp_path, REPO)
    out = capsys.readouterr().out
    assert "GitHub plan: file retro-due-20261123" in out
    assert '"labels": ["work", "repo:repo", "retro"]' in out
    assert "retro.py collect <this issue> --out <draft>" in out


def test_running_work_is_not_stopped_only_filing_runs_the_check():
    """Only the two filing commands call the check; start, deliver, integrate and every other
    command never do, so running work goes on while a retro is due or open."""
    tree = ast.parse((SCRIPTS / "work_tickets.py").read_text(encoding="utf-8"))
    callers = sorted(
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "filing_check" for call in ast.walk(node)))
    assert callers == ["backlog_file", "file_work_issue"]
