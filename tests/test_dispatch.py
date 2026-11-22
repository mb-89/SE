"""The dispatcher (README "Dispatcher"): `work_tickets.py dispatch` reads the startable work and
whether an integrator runs from GitHub alone, and fires the scheduled task at most once."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)
dispatcher = work_tickets.sibling("dispatch")

pytestmark = pytest.mark.usefixtures("fake_git_door")

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
REPO = "git.example/owner/repo"
WORKFLOW = PROJECT / ".github" / "workflows" / "dispatch.yml"


def stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    root.mkdir()
    (root / "se.toml").write_text("", encoding="utf-8")
    return root


def run_dispatch(worktree, mode, fleet):
    return dispatcher.dispatch(work_tickets, worktree, REPO, mode, fleet.pause, fleet.startable,
                               slots=fleet.slots)


class Fleet:
    """What dispatch reads, faked: the pause switch, the startable issues, the capacity the worker
    limit leaves (`slots`, None where none limits), the integrator's signs; every fire is recorded,
    and a fire raises where `fires` is False."""

    def __init__(self, monkeypatch, startable=(), running=(), paused=(), fires=True, slots=None):
        self.fired: list[tuple[str, str, str]] = []
        self.pause, self.startable, self.slots = list(paused), list(startable), slots
        monkeypatch.setattr(work_tickets, "pause_issues", lambda root, repo: self.pause)
        monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: self.startable)
        monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: self.slots)
        monkeypatch.setattr(dispatcher, "integrator_activity",
                            lambda wt, root, repo, now=None: list(running))

        def fire(trigger, token, text):
            if not fires:
                raise AssertionError("dispatch fired the scheduled task")
            self.fired.append((trigger, token, text))
            return {"claude_code_session_url": "https://example.com/session_1"}

        monkeypatch.setattr(dispatcher, "fire", fire)


STARTABLE = [{"number": 7, "title": "feature-seven"}]
TRIGGER = "https://example.com/v1/routines/trig_01abc/fire"


def test_no_startable_issue_fires_nothing_and_makes_no_model_call(worktree, monkeypatch):
    monkeypatch.setenv(dispatcher.TRIGGER_VARIABLE, TRIGGER)
    monkeypatch.setenv(dispatcher.TOKEN_VARIABLE, "secret")
    fleet = Fleet(monkeypatch, fires=False)
    assert run_dispatch(worktree, "fire", fleet) == [
        "Startable: none", "Integrator runs: none seen", "Fires nothing: no startable work"]


def test_dry_run_with_startable_work_and_no_integrator_prints_exactly_one_fire(
        worktree, monkeypatch, capsys):
    monkeypatch.delenv(dispatcher.TRIGGER_VARIABLE, raising=False)
    Fleet(monkeypatch, startable=STARTABLE, fires=False)
    assert work_tickets.main(["dispatch", "--dry-run", "--worktree", str(worktree),
                              "--repo", REPO]) == 0
    out = capsys.readouterr().out
    fires = [line for line in out.splitlines() if "fire the scheduled task" in line]
    assert fires == ["Would fire the scheduled task once: Startable work waits and no integrator "
                     "runs: #7"]
    assert "Startable: #7 feature-seven" in out


def test_fire_fires_once_with_the_secrets_and_names_the_session(worktree, monkeypatch):
    monkeypatch.setenv(dispatcher.TRIGGER_VARIABLE, TRIGGER)
    monkeypatch.setenv(dispatcher.TOKEN_VARIABLE, "secret")
    fleet = Fleet(monkeypatch, startable=STARTABLE)
    lines = run_dispatch(worktree, "fire", fleet)
    assert fleet.fired == [(TRIGGER, "secret",
                            "Startable work waits and no integrator runs: #7")]
    assert lines[-1] == "Fired the scheduled task once: https://example.com/session_1"
    assert not any("secret" in line or "trig_01abc" in line for line in lines)


@pytest.mark.parametrize("kind", ["running", "paused"])
def test_a_running_integrator_or_the_pause_fires_nothing(worktree, monkeypatch, kind):
    monkeypatch.setenv(dispatcher.TRIGGER_VARIABLE, TRIGGER)
    monkeypatch.setenv(dispatcher.TOKEN_VARIABLE, "secret")
    held = {"running": ["#3 feature-three is in progress"]} if kind == "running" else {
        "paused": [{"number": 9, "title": "pause", "url": "https://example.com/9"}]}
    fleet = Fleet(monkeypatch, startable=STARTABLE, fires=False, **held)
    assert run_dispatch(worktree, "fire", fleet)[-1].startswith("Fires nothing: ")


def test_a_reached_worker_limit_fires_nothing_and_room_left_fires(worktree, monkeypatch, capsys):
    monkeypatch.setenv(dispatcher.TRIGGER_VARIABLE, TRIGGER)
    monkeypatch.setenv(dispatcher.TOKEN_VARIABLE, "secret")
    full = Fleet(monkeypatch, startable=STARTABLE, fires=False, slots=0)
    lines = run_dispatch(worktree, "fire", full)
    assert "Capacity: 0" in lines
    assert lines[-1] == "Fires nothing: the worker limit is reached ([workers] in se.toml)"

    room = Fleet(monkeypatch, startable=STARTABLE, slots=1)
    assert work_tickets.main(["dispatch", "--fire", "--worktree", str(worktree), "--repo", REPO]) == 0
    assert "Capacity: 1" in capsys.readouterr().out
    assert len(room.fired) == 1


@pytest.mark.parametrize("trigger", [None, "trig_01abc", "http://example.com/v1/routines/trig_1/fire"])
def test_fire_without_a_fire_url_is_refused_before_anything_fires(worktree, monkeypatch, trigger):
    if trigger is None:
        monkeypatch.delenv(dispatcher.TRIGGER_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(dispatcher.TRIGGER_VARIABLE, trigger)
    monkeypatch.setenv(dispatcher.TOKEN_VARIABLE, "secret")
    fleet = Fleet(monkeypatch, startable=STARTABLE, fires=False)
    with pytest.raises(dispatcher.FireError, match=dispatcher.TRIGGER_VARIABLE):
        run_dispatch(worktree, "fire", fleet)


def test_integrator_activity_counts_recent_landings_and_moving_work_only(worktree, monkeypatch):
    pulls = [
        {"number": 1, "headRefName": "land/feature-one", "updatedAt": stamp(1)},
        {"number": 2, "headRefName": "land/feature-two", "updatedAt": stamp(30)},  # stale
        {"number": 3, "headRefName": "feature-three", "updatedAt": stamp(0)},  # a work PR
    ]
    active = [
        {"number": 4, "title": "feature-four", "updatedAt": stamp(1)},  # just started
        {"number": 5, "title": "feature-five", "updatedAt": stamp(30)},  # pushed an hour ago
        {"number": 6, "title": "feature-six", "updatedAt": stamp(30)},  # stuck
        {"number": 8, "title": "feature-eight", "updatedAt": stamp(30)},  # no branch, stuck
    ]
    tips = {"feature-four": stamp(30), "feature-five": stamp(1), "feature-six": stamp(30)}
    calls: list[list[str]] = []

    def gh(root, args):
        calls.append(args)
        if args[:2] == ["pr", "list"]:
            return json.dumps(pulls)
        if args[:2] == ["issue", "list"]:
            return json.dumps(active)
        branch = args[1].rsplit("/", 1)[-1]
        if branch not in tips:
            raise work_tickets.QueueError("gh api repos failed: gh: Not Found (HTTP 404)")
        return json.dumps({"commit": {"commit": {"committer": {"date": tips[branch]}}}})

    monkeypatch.setattr(work_tickets, "run_gh", gh)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: REPO)
    assert dispatcher.integrator_activity(work_tickets, worktree, REPO, NOW) == [
        "landing pull request #1 (land/feature-one) is open",
        "#4 feature-four is in progress",
        "#5 feature-five is in progress",
    ]
    listing = next(call for call in calls if call[:2] == ["issue", "list"])
    assert "in-progress" in listing and "work" in listing


def test_ready_skips_issues_that_wait_on_a_person(worktree, monkeypatch, fake_git_door):
    candidates = [
        {"number": 1, "title": "feature-one", "body": ""},
        {"number": 2, "title": "feature-two", "body": "", "labels": [{"name": "se-person"}]},
        {"number": 3, "title": "feature-three", "body": "", "labels": [{"name": "escalated"}]},
        {"number": 4, "title": "feature-four", "body": "", "assignees": [{"login": "alice"}]},
    ]
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: json.dumps(
        candidates if args[:2] == ["issue", "list"] and "ready" in args
        else [] if args[:2] == ["issue", "list"]
        else {"issue_dependencies_summary": {"blocked_by": 0}}))
    monkeypatch.setattr(work_tickets, "branch_exists", lambda root, branch: False)
    assert [issue["number"] for issue in work_tickets.ready_issues(worktree, REPO)] == [1]


def test_the_workflow_runs_dispatch_on_a_four_hourly_cron_with_no_model():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "' in text and "*/4 * * *" in text
    assert "work_tickets.py dispatch" in text
    for name in (dispatcher.TRIGGER_VARIABLE, dispatcher.TOKEN_VARIABLE):
        assert f"secrets.{name}" in text
    assert "--dry-run" in text and "--fire" in text
    # No model: the workflow calls no Claude action and holds no host but GitHub's own.
    assert "claude" not in text.lower() and "anthropic" not in text.lower()
    assert "http" not in text.lower()


def test_fire_posts_once_to_the_fire_url_with_the_token_and_the_text(monkeypatch):
    sent = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"claude_code_session_url": "https://example.com/session_1"}'

    monkeypatch.setattr(dispatcher.urllib.request, "urlopen",
                        lambda request, timeout: sent.append(request) or Answer())
    answer = dispatcher.fire(TRIGGER, "secret", "Startable: #7")
    assert answer == {"claude_code_session_url": "https://example.com/session_1"}
    (request,) = sent
    assert (request.full_url, request.get_method()) == (TRIGGER, "POST")
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert json.loads(request.data) == {"text": "Startable: #7"}


def test_the_command_reports_a_refused_fire_as_an_error_and_fires_nothing(worktree, monkeypatch, capsys):
    monkeypatch.delenv(dispatcher.TRIGGER_VARIABLE, raising=False)
    monkeypatch.delenv(dispatcher.TOKEN_VARIABLE, raising=False)
    Fleet(monkeypatch, startable=STARTABLE, fires=False)
    assert work_tickets.main(["dispatch", "--fire", "--worktree", str(worktree), "--repo", REPO]) != 0
    assert dispatcher.TRIGGER_VARIABLE in capsys.readouterr().err
