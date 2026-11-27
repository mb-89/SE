"""What finished work left behind (scripts/work_tickets.py find_leftovers, docs/fleet.md
"Leftovers"): each leftover by kind, the report with the one ref-maintenance run that deletes the
branches, and the start report's line, all against fake hosts."""

from __future__ import annotations

import contextlib
import io
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fake_git
import git_door
import se_start

work_tickets = se_start._load("work_tickets")

pytestmark = pytest.mark.usefixtures("fake_git_door")

NOW = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)
OLD, FRESH = NOW - timedelta(days=3), NOW - timedelta(hours=2)


class FakeLeftovers:
    """find_leftovers' door: origin's branches with tips and times, the commits on the integration
    branch, the pull requests' heads, the in-progress issues and the linked worktrees."""

    base = "main"

    def __init__(self, branches: dict[str, tuple[str, datetime | None]], merged: set[str] = frozenset(),
                 open_heads: set[str] = frozenset(), working: set[str] = frozenset(),
                 closed: dict[str, list[tuple[int, str]]] | None = None,
                 worktrees: list[tuple[str, str, str]] = ()) -> None:
        self.branch_tips, self.on_main = branches, set(merged)
        self.open, self.in_progress = set(open_heads), set(working)
        self.closed, self.trees = dict(closed or {}), list(worktrees)

    def __call__(self, root: Path, repo: str, base: str) -> "FakeLeftovers":
        return self

    def branches(self):
        return dict(self.branch_tips)

    def merged_shas(self, shas):
        return {sha for sha in shas if sha in self.on_main}

    def open_heads(self):
        return set(self.open)

    def working(self):
        return set(self.in_progress)

    def closed_heads(self):
        return dict(self.closed)

    def worktrees(self):
        return list(self.trees)


def sha(n: int) -> str:
    return f"{n:040x}"


FLEET = FakeLeftovers(
    {"main": (sha(1), OLD), "se": (sha(1), OLD), "landed": (sha(2), OLD), "merged": (sha(3), OLD),
     "unmerged": (sha(4), OLD), "moved": (sha(5), OLD), "ccr-abc": (sha(6), OLD),
     "fresh": (sha(7), FRESH), "delivered": (sha(8), OLD), "working": (sha(9), OLD)},
    merged={sha(3)}, open_heads={"delivered"}, working={"working"},
    closed={"landed": [(4, sha(2))], "moved": [(5, sha(10))], "done": [(6, sha(11))]},
    worktrees=[("/w/done", "done", sha(11)), ("/w/delivered", "delivered", sha(8)),
               ("/w/working", "working", sha(9))])


def test_each_leftover_is_named_by_its_kind_and_nothing_held_is():
    found = work_tickets.find_leftovers(FLEET, NOW)
    assert [(item.kind, item.name) for item in found] == [
        ("unmerged branch", "moved"),
        ("unmerged branch", "unmerged"),
        ("branch of a closed pull request", "landed"),
        ("merged branch", "merged"),
        ("session branch", "ccr-abc"),
        ("integrated worktree", "/w/done"),
    ]


def test_the_summary_is_one_line_by_kind():
    found = work_tickets.find_leftovers(FLEET, NOW)
    assert work_tickets.leftover_summary(found) == (
        "2 unmerged branches (moved, unmerged); 1 branch of a closed pull request (landed); "
        "1 merged branch (merged); 1 session branch (ccr-abc); 1 integrated worktree (/w/done)")


def test_the_report_gives_each_commit_and_age_and_one_ref_maintenance_run():
    found = work_tickets.find_leftovers(FLEET, NOW)
    lines = work_tickets.leftover_report(found, NOW).splitlines()
    assert lines[0] == f"unmerged branch: moved at {sha(5)[:12]}, 3 days"
    zero = "0" * 40
    assert lines[-3] == (f"{sha(5)} {zero} refs/heads/moved {sha(4)} {zero} refs/heads/unmerged "
                         f"{sha(2)} {zero} refs/heads/landed {sha(3)} {zero} refs/heads/merged "
                         f"{sha(6)} {zero} refs/heads/ccr-abc")
    assert "ref-maintenance" in lines[-4] and "dry_run off" in lines[-4]
    assert lines[-1].startswith("Remove each worktree: work_tickets.py close --remove")


def test_nothing_left_is_said_so():
    door = FakeLeftovers({"main": (sha(1), OLD), "fresh": (sha(2), FRESH)})
    assert work_tickets.find_leftovers(door, NOW) == []
    assert work_tickets.leftover_report([], NOW) == "No leftovers"


def test_finished_sessions_of_se_s_work_are_leftovers_past_a_day():
    sessions = [
        {"id": "s1", "title": "SE/SE/worker/7/done-thing", "status_bucket": "completed",
         "updated_at": "2026-11-25T10:00:00Z"},
        {"id": "s2", "title": "SE/SE/worker/8/fresh", "status_bucket": "completed",
         "updated_at": "2026-11-27T11:00:00Z"},
        {"id": "s3", "title": "SE/SE/integrator", "status_bucket": "working",
         "updated_at": "2026-11-20T10:00:00Z"},
        {"id": "s4", "title": "someone else's", "status_bucket": "completed",
         "updated_at": "2026-11-20T10:00:00Z"},
        {"id": "s5", "title": "SE/SE/retro/9/r", "status_bucket": "completed", "status": "archived",
         "updated_at": "2026-11-20T10:00:00Z"},
    ]
    door = FakeLeftovers({"main": (sha(1), OLD)})
    found = work_tickets.find_leftovers(door, NOW, sessions=sessions)
    assert [(item.kind, item.name, item.sha) for item in found] == [
        ("finished session", "SE/SE/worker/7/done-thing", "s1")]
    assert work_tickets.leftover_report(found, NOW).splitlines()[-1].startswith(
        "Archive each finished session")


def test_the_start_report_names_a_leftover_branch_of_a_closed_pull_request(tmp_path, monkeypatch):
    """The acceptance: the start's work check reads the fake host, and its line names the branch."""
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    door = FakeLeftovers({"main": (sha(1), OLD), "landed": (sha(2), OLD)},
                         closed={"landed": [(4, sha(2))]})
    retro = se_start._load("retro")
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "github.com/owner/repo")
    monkeypatch.setattr(work_tickets, "integration_branch", lambda root: "main")
    monkeypatch.setattr(work_tickets, "fleet_findings", lambda *args: [])
    monkeypatch.setattr(work_tickets, "Fleet", lambda *args: None)
    monkeypatch.setattr(retro, "countdowns", lambda *args: None)
    monkeypatch.setattr(work_tickets, "LeftoverDoor", door)
    work = se_start.work_check(project)
    assert work["leftovers"] == {"found": [{"kind": "branch of a closed pull request", "name": "landed"}]}
    report = types.SimpleNamespace(work=work, root=project)
    (line,) = [line for line in se_start.work_lines(report, Path("/se")) if line.startswith("Leftovers")]
    assert line == ("Leftovers: 1 branch of a closed pull request (landed); see each with its last "
                    "commit and age, and the one ref-maintenance run that deletes the branches: "
                    f"uv run python /se/scripts/work_tickets.py leftovers --worktree {project.as_posix()}")


def test_a_failed_read_is_named_in_the_start_report(tmp_path):
    report = types.SimpleNamespace(work={"leftovers": {"error": "gh api pulls failed"}}, root=None)
    (line,) = se_start.work_lines(report, Path("/se"))
    assert line.startswith("Leftovers not read: gh api pulls failed; ")


def git(root: Path, *args: str) -> str:
    identity = ("-c", "user.name=a", "-c", "user.email=a@example.com")
    done = git_door.run(*identity, *args, root=root)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_door_reads_origin_s_branches_and_the_worktrees_with_git(tmp_path):
    origin = tmp_path / "origin"
    fake_git.init(origin, "-b", "main")
    git(origin, "commit", "-q", "--allow-empty", "-m", "one")
    git(origin, "branch", "merged")
    git(origin, "checkout", "-q", "-b", "unmerged")
    git(origin, "commit", "-q", "--allow-empty", "-m", "two")
    git(origin, "checkout", "-q", "main")
    clone = tmp_path / "clone"
    fake_git.init(clone, "-b", "main")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "fetch", "-q", "origin")
    git(clone, "worktree", "add", "-b", "done", str(tmp_path / "done"), "origin/unmerged")
    door = work_tickets.LeftoverDoor.__new__(work_tickets.LeftoverDoor)
    door.root, door.base = clone, "main"
    branches = door.branches()
    assert sorted(branches) == ["main", "merged", "unmerged"]
    tips = {name: tip for name, (tip, _) in branches.items()}
    assert all(when is not None for _, when in branches.values())
    assert door.worktrees() == [((tmp_path / "done").as_posix(), "done", tips["unmerged"])]


def test_the_door_asks_github_which_commits_are_on_the_base():
    """Not git: a cloud clone is shallow, and git there finds no ancestor older than its history."""
    asked = []

    class GitHub:
        def api(self, path):
            asked.append(path)
            return {"ahead_by": 0 if path.endswith(sha(1)) else 2}

    door = work_tickets.LeftoverDoor.__new__(work_tickets.LeftoverDoor)
    door.base, door.github = "main", GitHub()
    assert door.merged_shas([sha(1), sha(2)]) == {sha(1)}
    assert asked == [f"compare/main...{sha(1)}", f"compare/main...{sha(2)}"]


def test_the_command_prints_the_report_and_fails_on_a_leftover(tmp_path, monkeypatch):
    door = FakeLeftovers({"main": (sha(1), OLD), "unmerged": (sha(4), OLD)})
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "github.com/owner/repo")
    monkeypatch.setattr(work_tickets, "integration_branch", lambda root: "main")
    monkeypatch.setattr(work_tickets, "LeftoverDoor", door)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = work_tickets.main(["leftovers", "--worktree", str(tmp_path)])
    assert code == 1
    assert out.getvalue().startswith("unmerged branch: unmerged at ")
