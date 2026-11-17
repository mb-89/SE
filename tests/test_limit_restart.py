"""Worker sessions stopped on a usage limit (scripts/limit_restart.py): the session tools' answers,
the in-progress issues, the delivered branches and the setting in, the findings out. The fleet
check's wiring is tested in tests/test_work_tickets.py."""

from datetime import datetime, timedelta, timezone

import pytest

import work_tickets

limits = work_tickets.sibling("limit_restart")
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
BRANCH = "feat/limited-20261114"


def result(text: str) -> dict:
    return {"id": "e", "data": {"result": {"subtype": "error", "is_error": True, "result": text}}}


def rejected(resets: object = None) -> dict:
    info = {"status": "rejected", **({"resetsAt": resets} if resets is not None else {})}
    return {"id": "r", "data": {"rate_limit_event": {"type": "rate_limit_event",
                                                      "rate_limit_info": info}}}


def session(*events: dict, status: str = "idle", title: str = f"Work {BRANCH}",
            ident: str = "session_a", updated: str = "2026-11-14T10:00:00Z") -> dict:
    return {"id": ident, "title": title, "status_bucket": status, "updated_at": updated,
            "events": {"data": list(events)}}


def found(sessions, on=False, delivered=(), comments=None, in_progress=None):
    return limits.findings(sessions, in_progress or {7: BRANCH}, set(delivered),
                           lambda number: comments, NOW, on)


@pytest.mark.parametrize("events", [
    (result("Claude usage limit reached. Your limit will reset at 3pm"),),
    (rejected(),),
    (result("done"), rejected(int((NOW + timedelta(hours=1)).timestamp()))),
])
def test_a_session_whose_newest_signal_is_a_limit_stopped_on_it(events):
    assert limits.stopped(session(*events)) is not None


@pytest.mark.parametrize(("events", "status"), [
    ((), "idle"),
    ((result("Delivered: field report in PR #9"),), "idle"),
    ((result("You've hit your usage limit"), result("continued and delivered")), "idle"),
    ((result("You've hit your usage limit"),), "working"),
    (({"data": {"rate_limit_event": {"rate_limit_info": {"status": "allowed_warning"}}}},),
     "idle"),
])
def test_a_session_working_or_past_its_limit_did_not_stop_on_one(events, status):
    assert limits.stopped(session(*events, status=status)) is None


def test_the_limit_stop_is_reported_and_restarted_only_when_on():
    lifts = NOW - timedelta(minutes=5)
    stop = [session(rejected(lifts.isoformat()))]
    off, = found(stop)
    assert (off.issue, off.branch) == (7, BRANCH)
    assert off.what == (f"worker session session_a stopped on a usage limit at 2026-11-14T10:00Z "
                        f"without delivering {BRANCH}; the limit lifts at 2026-11-14T11:55Z")
    assert off.remedy.startswith("none: reported only, as se.toml [fleet] restart_after_limit is "
                                 "off")
    on, = found(stop, on=True)
    assert on.remedy == ("the limit has lifted: resume session session_a with one message to "
                         "continue #7 and deliver, then comment `Restarted after a usage limit: "
                         "session session_a` on #7; once per issue")


def test_a_restart_waits_for_the_limit_and_happens_once_per_issue():
    later = int((NOW + timedelta(hours=2)).timestamp() * 1000)  # milliseconds
    waiting, = found([session(rejected(later))], on=True)
    assert waiting.remedy.startswith("once the limit lifts at 2026-11-14T14:00Z, resume session")
    unknown, = found([session(result("Usage limit reached"))], on=True)
    assert unknown.remedy.startswith("once the limit lifts, resume session session_a")
    assert "its events do not say when the limit lifts" in unknown.what
    once = [{"body": "Restarted after a usage limit: session session_a"}]
    again, = found([session(result("Usage limit reached"))], on=True, comments=once)
    assert again.remedy.startswith("none: #7 was restarted after a usage limit once already")


def test_only_an_undelivered_in_progress_issue_a_session_names_is_reported():
    stop = session(result("Usage limit reached"))
    assert found([stop], delivered=[BRANCH]) == []
    assert found([session(result("Usage limit reached"), title="Work on something else")]) == []
    assert found([stop], in_progress={8: "feat/other"}) == []
    newer = session(result("Usage limit reached"), ident="session_b",
                    updated="2026-11-14T11:00:00Z")
    one, = found([stop, newer, "not a session"])
    assert "session_b" in one.what  # one finding per issue, its newest stopped session


@pytest.mark.parametrize("branch", [BRANCH, "limited-worker"])
def test_a_stopped_session_titled_by_the_session_scheme_is_found_by_its_branch(branch):
    title = work_tickets.session_title("worker", "obs", branch)
    one, = found([session(result("Usage limit reached"), title=title)], in_progress={7: branch})
    assert one.branch == branch and "session_a" in one.what


def test_the_setting_is_off_unless_set_true():
    assert limits.restart({}) is False
    assert limits.restart({"restart_after_limit": True}) is True
    with pytest.raises(limits.SettingError, match=r"fleet\.restart_after_limit"):
        limits.restart({"restart_after_limit": "yes"})
