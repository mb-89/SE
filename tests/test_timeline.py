"""The Timeline builds from one batched read per repository, then from the snapshot alone (scripts/timeline.py)."""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone

import pytest

import timeline

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)


def issue(number: int, *labels: str, state: str = "open", reason: str | None = None,
          closed: str | None = None, body: str = "## Goal\n\nThe goal.\n") -> dict:
    return {"number": number, "title": f"issue {number}", "url": f"https://github.com/o/a/issues/{number}",
            "state": state, "state_reason": reason, "closed_at": closed, "labels": sorted(labels), "body": body}


def snapshot(*issues: dict, releases: tuple[dict, ...] = (), other: tuple[dict, ...] = ()) -> dict:
    return {"read_at": NOW.isoformat(), "repositories": {
        "o/a": {"issues": list(issues), "releases": list(releases)},
        "o/b": {"issues": list(other), "releases": []},
    }}


def placed(page: dict, number: int) -> list[str]:
    """Every place an issue of lane o/a shows in: done days by date, or open places by name."""
    where = [date for date, stops in page["days"].items()
             if any(entry["number"] == number for entry in stops.get("o/a", {}).get("issues", []))]
    where += [key for key, lanes in page["places"].items() if any(entry["number"] == number for entry in lanes["o/a"])]
    return where


# --- What shows where (requirement 2) ---


def test_a_completed_issue_is_done_on_the_day_it_closed():
    page = timeline.model(snapshot(issue(1, "work", state="closed", reason="completed",
                                         closed="2026-11-09T23:30:00Z")))
    assert placed(page, 1) == ["2026-11-09"]


@pytest.mark.parametrize("reason", ["not_planned", "duplicate"])
def test_an_issue_closed_as_not_planned_or_duplicate_is_hidden(reason):
    page = timeline.model(snapshot(issue(1, state="closed", reason=reason, closed="2026-11-09T10:00:00Z")))
    assert placed(page, 1) == []
    assert page["days"] == {}


def test_an_in_progress_issue_is_today():
    page = timeline.model(snapshot(issue(1, "work", "in-progress")))
    assert placed(page, 1) == ["today"]


def test_a_ready_issue_is_next():
    page = timeline.model(snapshot(issue(1, "work", "ready")))
    assert placed(page, 1) == ["next"]


def test_a_backlogged_issue_is_backlog_and_never_marked():
    page = timeline.model(snapshot(issue(1, "backlogged", "se-person")))
    assert placed(page, 1) == ["backlog"]
    assert page["places"]["backlog"]["o/a"][0]["needs_you"] is False


def test_a_person_issue_not_backlogged_needs_you_and_is_marked():
    page = timeline.model(snapshot(issue(1, "se-person"), issue(2, "in-progress", "se-person")))
    assert placed(page, 1) == ["needs-you"]
    assert placed(page, 2) == ["today"]
    assert [entry["needs_you"] for entry in page["places"]["today"]["o/a"]] == [True]
    html = timeline.render(page)
    assert html.count('<span class="mark">needs you</span>') == 2


def test_field_reports_and_unlabelled_open_issues_are_left_out():
    page = timeline.model(snapshot(issue(1, "field-report", state="closed", reason="completed",
                                         closed="2026-11-09T10:00:00Z"),
                                   issue(2, "field-report", "in-progress"), issue(3)))
    assert placed(page, 1) == placed(page, 2) == placed(page, 3) == []


def test_a_release_is_a_marker_on_the_day_it_was_tagged():
    releases = ({"tag": "v1.0.0", "url": "u", "published_at": "2026-11-08T09:00:00Z"},
                {"tag": "v1.1.0", "url": "u", "published_at": "2026-11-08T09:00:00Z"})
    page = timeline.model(snapshot(releases=releases))
    assert [release["tag"] for release in page["days"]["2026-11-08"]["o/a"]["releases"]] == ["v1.0.0", "v1.1.0"]
    html = timeline.render(page)
    assert re.search(r'class="lane release"><span class="dot"></span><span class="label">v1\.1\.0 \+1</span>', html)


# --- The map (requirement 3) ---


def test_each_past_day_is_one_stop_per_lane_with_a_count_and_its_issues():
    done = dict(state="closed", reason="completed")
    page = timeline.model(snapshot(issue(1, closed="2026-11-09T08:00:00Z", **done),
                                   issue(2, closed="2026-11-09T20:00:00Z", **done),
                                   issue(3, closed="2026-11-10T08:00:00Z", **done),
                                   other=(issue(7, closed="2026-11-09T12:00:00Z", **done),)))
    assert list(page["days"]) == ["2026-11-09", "2026-11-10"]
    assert [len(page["days"]["2026-11-09"][lane]["issues"]) for lane in ("o/a", "o/b")] == [2, 1]
    assert "o/b" not in page["days"]["2026-11-10"]
    html = timeline.render(page)
    rows = re.findall(r'<details class="row past">.*?</details></li></ul></div></details>', html, flags=re.S)
    assert len(rows) == 2
    assert '<span class="count">2</span>' in rows[0] and '<span class="count">1</span>' in rows[0]
    assert "#1 issue 1" in rows[0] and "#7 issue 7" in rows[0] and "#3 issue 3" not in rows[0]


def test_an_issue_shows_the_first_paragraph_of_its_goal_and_its_link():
    body = "<!-- se:fleet -->\n## Goal\n\nA **timeline**\nof `SE`.\n\nMore.\n\n## Requirements\n\n1. x\n"
    page = timeline.model(snapshot(issue(1, "ready", body=body)))
    html = timeline.render(page)
    assert "<p>A timeline of SE.</p>" in html
    assert '<a class="link" href="https://github.com/o/a/issues/1">Open #1 on GitHub</a>' in html
    assert timeline.goal("No sections.\n\nSecond.") == "No sections."


def test_the_page_is_called_timeline_and_ends_with_the_backlog_section():
    page = timeline.model(snapshot(issue(1, "in-progress"), issue(2, "backlogged")))
    html = timeline.render(page)
    assert "<title>Timeline</title>" in html and "<h1>Timeline</h1>" in html
    assert html.index('id="today"') < html.index("Needs you") < html.index(">Next<") < html.index("<h2>Backlog</h2>")
    backlog = html[html.index("<h2>Backlog</h2>"):]
    assert "#2 issue 2" in backlog and "#1 issue 1" not in backlog
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "prefers-color-scheme: dark" in html


def test_text_from_issues_is_escaped():
    page = timeline.model(snapshot(issue(1, "ready", body="## Goal\n\n<script>x</script>")))
    assert "<script>x</script>" not in timeline.render(page)


# --- One read, then pure (requirement 1) ---


class FakeGitHub:
    """GraphQL on fake repositories: answers each query with the pages its cursors ask for."""

    def __init__(self, repositories: dict[str, dict[str, list]], page_size: int = 100):
        self.repositories = repositories
        self.page_size = page_size
        self.calls: list[dict] = []

    def page(self, items: list, cursor: str | None) -> dict:
        start = int(cursor or 0)
        end = start + self.page_size
        return {"nodes": items[start:end], "pageInfo": {"hasNextPage": end < len(items), "endCursor": str(end)}}

    def __call__(self, query: str, variables: dict) -> dict:
        assert query == timeline.QUERY
        self.calls.append(variables)
        data = self.repositories[f"{variables['owner']}/{variables['name']}"]
        repository = {}
        if variables["withIssues"]:
            repository["issues"] = self.page(data["issues"], variables["issues"])
        if variables["withTags"]:
            repository["refs"] = self.page(data["tags"], variables["tags"])
        return {"repository": repository}


def node(number: int, **fields) -> dict:
    return {"number": number, "title": f"t{number}", "url": f"https://github.com/o/a/issues/{number}",
            "state": "OPEN", "stateReason": None, "closedAt": None, "body": "", "labels": {"nodes": []}, **fields}


def test_the_read_is_one_batched_request_per_repository():
    github = FakeGitHub({
        "o/a": {"issues": [node(n) for n in range(1, 61)],
                "tags": [{"name": "v1.0.0", "target": {"committedDate": "2026-11-01T10:00:00Z"}},
                         {"name": "v1", "target": {"committedDate": "2026-11-01T10:00:00Z"}}]},
        "o/b": {"issues": [node(1, state="CLOSED", stateReason="NOT_PLANNED", closedAt="2026-11-02T10:00:00Z",
                                labels={"nodes": [{"name": "work"}]})],
                "tags": [{"name": "v2.0.0", "target": {"tagger": {"date": "2026-11-03T10:00:00Z"},
                                                       "target": {"committedDate": "2026-10-01T10:00:00Z"}}}]},
    })
    snap = timeline.read(["o/a", "o/b"], github, NOW)
    assert [call["owner"] + "/" + call["name"] for call in github.calls] == ["o/a", "o/b"]
    assert all(call["withIssues"] and call["withTags"] for call in github.calls)
    assert len(snap["repositories"]["o/a"]["issues"]) == 60
    assert [release["tag"] for release in snap["repositories"]["o/a"]["releases"]] == ["v1.0.0"]
    assert snap["repositories"]["o/b"]["releases"][0]["published_at"] == "2026-11-03T10:00:00Z"
    assert snap["repositories"]["o/b"]["issues"][0] == {
        "number": 1, "title": "t1", "url": "https://github.com/o/a/issues/1", "state": "closed",
        "state_reason": "not_planned", "closed_at": "2026-11-02T10:00:00Z", "labels": ["work"], "body": ""}


def test_more_issues_than_a_page_continue_the_same_pass_without_the_tags_read():
    github = FakeGitHub({"o/a": {"issues": [node(n) for n in range(1, 251)], "tags": []}}, page_size=100)
    snap = timeline.read(["o/a"], github, NOW)
    assert [(call["issues"], call["withIssues"], call["withTags"]) for call in github.calls] == [
        (None, True, True), ("100", True, False), ("200", True, False)]
    assert [entry["number"] for entry in snap["repositories"]["o/a"]["issues"]] == list(range(1, 251))


def test_the_query_names_every_field_the_snapshot_reads():
    for field in ("issues(first: 100", "refs(refPrefix: \"refs/tags/\", first: 100", "stateReason", "closedAt",
                  "labels(first: 30)", "tagger { date }", "committedDate"):
        assert field in timeline.QUERY


def test_the_repositories_come_from_se_toml():
    assert timeline.repositories() == ["mb-89/SE", "mb-89/obs"]


# --- The command (requirements 1 and 5) ---


def test_the_page_builds_from_a_snapshot_with_no_network(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("the build from a snapshot opened a connection")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot(issue(1, "in-progress"))), encoding="utf-8")
    destination = tmp_path / "site" / "timeline.html"
    assert timeline.main(["--snapshot", str(source), "--destination", str(destination)]) == 0
    assert "<title>Timeline</title>" in destination.read_text(encoding="utf-8")
    assert "wrote" in capsys.readouterr().out


def test_a_read_saves_its_snapshot_and_rebuilds_the_same_page(tmp_path):
    github = FakeGitHub({name: {"issues": [node(1, labels={"nodes": [{"name": "ready"}]})], "tags": []}
                         for name in ("mb-89/SE", "mb-89/obs")})
    saved, first, second = tmp_path / "snap.json", tmp_path / "a.html", tmp_path / "b.html"
    assert timeline.main(["--destination", str(first), "--save-snapshot", str(saved)], post=github) == 0
    assert len(github.calls) == 2
    assert timeline.main(["--snapshot", str(saved), "--destination", str(second)]) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_a_read_without_a_token_is_a_setup_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert timeline.main(["--destination", str(tmp_path / "t.html")]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_a_refused_read_writes_nothing(tmp_path, capsys):
    def refuse(query, variables):
        raise timeline.ReadError("GitHub answered 502 to the GraphQL read")

    destination = tmp_path / "t.html"
    assert timeline.main(["--destination", str(destination)], post=refuse) == 1
    assert not destination.exists()
    assert "502" in capsys.readouterr().err
