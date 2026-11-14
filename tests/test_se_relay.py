"""SE's GitHub reads through kern's relay (README "Hand-offs through the relay"): a command reads a
GitHub answer from kern's snapshot names instead of a file the session retypes. The reads are held
to the snapshot shape kern's github component writes (`{repo, number, read, via, data}`) and to the
PostToolUse-landed answers a cloud session's hook hands kern, against a fake relay; the end-to-end
read from a real core is `tests/beside_se_relay.py`."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import se_relay  # noqa: E402
import work_tickets  # noqa: E402

NINE = datetime(2026, 11, 13, 9, 0, 0, tzinfo=timezone.utc)


def snapshot(number: int, data: object, read: datetime = NINE, via: str = "relay") -> dict:
    """A snapshot as kern's github component writes it to github/<family>/<key>."""
    return {"repo": "alice/demo", "number": number, "read": read.isoformat(), "via": via,
            "data": data}


class FakeRelay(se_relay.Relay):
    """kern's relay over a dict of snapshot names, as a running core's `get.github` answers."""

    def __init__(self, root: Path, names: dict[str, object], now: datetime = NINE):
        super().__init__(root, lambda name: names.get(name), now=lambda: now)


def test_answer_file_writes_the_tools_answer_unchanged(tmp_path: Path) -> None:
    body = {"number": 7, "title": "One issue", "body": "## Requirements\n\n1. One.\n"}
    relay = FakeRelay(tmp_path, {"github/issues/alice.demo.7": snapshot(7, body)})
    path = relay.answer_file("issues", "alice", "demo", 7, "work issue")
    assert json.loads(path.read_text(encoding="utf-8")) == body
    assert path == tmp_path / ".se" / ".runtime" / "relay" / "issues-alice.demo.7.json"


def test_a_missing_snapshot_names_the_tool_call_to_run(tmp_path: Path) -> None:
    relay = FakeRelay(tmp_path, {})
    with pytest.raises(se_relay.RelayError) as raised:
        relay.answer_file("pulls", "Alice", "Demo", 8, "pull request")
    message = str(raised.value)
    assert "holds no pull request of Alice/Demo#8" in message
    assert 'pull_request_read {"method": "get", "owner": "Alice", "pullNumber": 8, "repo": "Demo"}' in message


def test_a_stale_snapshot_is_read_again(tmp_path: Path) -> None:
    old = NINE - timedelta(seconds=se_relay.MAX_AGE_SECONDS + 1)
    relay = FakeRelay(tmp_path, {"github/comments/alice.demo.7": snapshot(7, [], read=old)})
    with pytest.raises(se_relay.RelayError, match="over 10 minutes ago"):
        relay.answer_file("comments", "alice", "demo", 7, "work issue comments")
    # One within the window is answered.
    fresh = FakeRelay(tmp_path, {"github/comments/alice.demo.7": snapshot(7, [])},
                      now=NINE + timedelta(seconds=se_relay.MAX_AGE_SECONDS - 1))
    assert fresh.answer_file("comments", "alice", "demo", 7, "work issue comments").is_file()


def test_the_key_is_lower_case_owner_repo_number() -> None:
    assert se_relay.key("Alice", "Demo", 8) == "alice.demo.8"


def test_relay_is_none_when_switched_off(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(se_relay.se_components.SWITCH, "off")
    assert se_relay.relay(tmp_path) is None


# The reads wired into the commands.

@pytest.fixture
def served(tmp_path: Path, monkeypatch):
    """A worktree whose GitHub reads come from a fake relay, gh unusable (the cloud)."""
    worktree = tmp_path / "wt"
    (worktree / ".git").mkdir(parents=True)
    names: dict[str, object] = {}
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: False)
    monkeypatch.setattr(work_tickets, "relay_for", lambda root: FakeRelay(Path(root), names))
    return worktree, names


def test_intake_reads_the_issue_and_comments_from_the_relay(served) -> None:
    worktree, names = served
    body = ("<!-- se:fleet -->\n## Goal\n\nG.\n\n## Base branch\n\nmain\n\n## Requirements\n\n"
            "1. One requirement.\n\n## Acceptance\n\n- [ ] It.\n")
    names["github/issues/alice.demo.42"] = snapshot(42, {
        "number": 42, "title": "feat/x", "body": body, "comments": 1,
        "html_url": "https://github.com/alice/demo/issues/42"})
    names["github/comments/alice.demo.42"] = snapshot(42, [
        {"id": 5, "body": "Started", "user": {"login": "mb-89"},
         "created_at": "2026-11-13T09:00:00Z", "html_url": "https://github.com/alice/demo/issues/42#c5"}])
    issue, created, _ = work_tickets.intake(worktree, 42, "alice/demo")
    assert issue["number"] == 42 and len(issue["comments"]) == 1
    assert any(ticket.startswith("r1-") for ticket in created)
    assert (worktree / ".se" / "work" / work_tickets.ISSUE_SNAPSHOT).is_file()


def test_intake_without_a_relay_falls_back_to_the_no_gh_message(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "wt"
    (worktree / ".git").mkdir(parents=True)

    def no_gh(*a, **k):
        raise work_tickets.MissingGhError("needs the GitHub CLI (gh)")

    monkeypatch.setattr(work_tickets, "fetch_issue", no_gh)
    monkeypatch.setattr(work_tickets, "relay_for", lambda root: None)
    # No gh and no relay: intake re-raises the standard no-gh error that names Without gh.
    with pytest.raises(work_tickets.MissingGhError, match="GitHub CLI"):
        work_tickets.intake(worktree, 42, "alice/demo")


def test_integrate_reads_the_pull_request_and_issue_from_the_relay(served, monkeypatch) -> None:
    worktree, names = served
    report = ("<!-- se:field-report -->\n**Work issue:** #42  **Branch:** `feat/x`\n"
              "<!-- se:field-report:end -->")
    names["github/pulls/alice.demo.9"] = snapshot(9, {
        "number": 9, "body": report, "head": {"ref": "feat/x", "sha": "deadbeef"},
        "html_url": "https://github.com/alice/demo/pull/9"})
    names["github/issues/alice.demo.42"] = snapshot(42, {
        "number": 42, "title": "feat/x", "body": "## Requirements\n\n1. One.\n",
        "html_url": "https://github.com/alice/demo/issues/42"})
    captured = {}

    def fake_report_problems(report_body, issue_body):
        captured["issue_body"] = issue_body
        return []

    monkeypatch.setattr(work_tickets, "field_report_problems", fake_report_problems)
    monkeypatch.setattr(work_tickets, "checked_git", lambda *a, **k: "")
    monkeypatch.setattr(work_tickets, "remote_head", lambda root, branch: "deadbeef")
    relay = work_tickets.relay_for(worktree)
    pull, report_text, work_issue, number = work_tickets.relay_pull_request(
        relay, worktree, 9, "alice/demo")
    assert number == 42 and pull["headRefName"] == "feat/x" and pull["headRefOid"] == "deadbeef"
    assert captured["issue_body"] == "## Requirements\n\n1. One.\n"


def test_the_work_issues_comments_are_read_where_the_tools_count_any(tmp_path: Path) -> None:
    """`issue_read get` names the comments only as their count: a count above 0 reads them as
    `issue_read get_comments`, and a missing read names that relay call, never a file; a count of
    0 reads none."""
    issue = {"number": 7, "title": "feat/x", "body": "B.", "comments": 2,
             "html_url": "https://github.com/alice/demo/issues/7"}
    names: dict[str, object] = {"github/issues/alice.demo.7": snapshot(7, issue)}
    relay = FakeRelay(tmp_path, names)
    with pytest.raises(se_relay.RelayError) as raised:
        work_tickets.relay_issue_read(relay, "alice", "demo", 7)
    assert 'issue_read {"issue_number": 7, "method": "get_comments"' in str(raised.value)
    assert "--comments-file" not in str(raised.value)
    names["github/comments/alice.demo.7"] = snapshot(7, [
        {"id": 1, "body": "One.", "user": {"login": "alice"}, "created_at": "2026-11-13T09:00:00Z"},
        {"id": 2, "body": "Two.", "user": {"login": "bob"}, "created_at": "2026-11-13T09:01:00Z"}])
    assert [c["body"] for c in work_tickets.relay_issue_read(relay, "alice", "demo", 7)["comments"]] == [
        "One.", "Two."]
    names.clear()
    names["github/issues/alice.demo.7"] = snapshot(7, {**issue, "comments": 0})
    assert work_tickets.relay_issue_read(relay, "alice", "demo", 7)["comments"] == []
