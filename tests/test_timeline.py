"""The Timeline builds from one batched read per repository, then from the snapshot alone (scripts/timeline.py)."""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone

import pytest

import fake_git
import git_door
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


def test_the_repositories_come_from_se_toml_beside_the_home():
    home = timeline.sibling("se_home").Home("example.com", "alice", "project")
    assert timeline.repositories(home=home) == ["alice/SE", "alice/obs", "alice/kern"]


def test_a_bare_repository_takes_the_owner_of_the_config_checkout_origin(tmp_path, fake_git_door):
    config = fake_git.init(tmp_path / "project") / "se.toml"
    config.write_text('[timeline]\nrepositories = ["project", "bob/tool"]\n', encoding="utf-8")
    git_door.run("remote", "add", "origin", "git@example.com:alice/project.git", root=config.parent)
    assert timeline.repositories(config) == ["alice/project", "bob/tool"]


def test_a_bare_repository_without_an_origin_is_a_setup_error(tmp_path, fake_git_door):
    config = fake_git.init(tmp_path / "project") / "se.toml"
    config.write_text('[timeline]\nrepositories = ["project"]\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="no origin remote"):
        timeline.repositories(config)


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


def absolute_config(tmp_path):
    """A se.toml naming its repositories as `<owner>/<repo>`, which needs no origin."""
    config = tmp_path / "se.toml"
    config.write_text('[timeline]\nrepositories = ["alice/SE", "alice/obs"]\n', encoding="utf-8")
    return config


def test_a_read_saves_its_snapshot_and_rebuilds_the_same_page(tmp_path):
    github = FakeGitHub({name: {"issues": [node(1, labels={"nodes": [{"name": "ready"}]})], "tags": []}
                         for name in ("alice/SE", "alice/obs")})
    config = absolute_config(tmp_path)
    saved, first, second = tmp_path / "snap.json", tmp_path / "a.html", tmp_path / "b.html"
    assert timeline.main(["--config", str(config), "--destination", str(first), "--save-snapshot", str(saved)],
                         post=github) == 0
    assert len(github.calls) == 2
    assert timeline.main(["--snapshot", str(saved), "--destination", str(second)]) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_a_read_without_a_token_is_a_setup_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert timeline.main(["--config", str(absolute_config(tmp_path)), "--destination", str(tmp_path / "t.html")]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_a_refused_read_writes_nothing(tmp_path, capsys):
    def refuse(query, variables):
        raise timeline.ReadError("GitHub answered 502 to the GraphQL read")

    destination = tmp_path / "t.html"
    assert timeline.main(["--config", str(absolute_config(tmp_path)), "--destination", str(destination)],
                         post=refuse) == 1
    assert not destination.exists()
    assert "502" in capsys.readouterr().err


# --- Planned days (work issue "timeline shows planned days") ---

FIXTURE = timeline.ROOT / "tests" / "fixtures" / "timeline-planned.json"


def fixture_page() -> dict:
    return timeline.model(json.loads(FIXTURE.read_text(encoding="utf-8")))


def planned_on(page: dict, lane: str) -> dict[str, list[int]]:
    return {date: [entry["number"] for entry in stops[lane]["issues"]]
            for date, stops in page["planned"].items() if lane in stops}


@pytest.mark.parametrize(("body", "date"), [
    ("Planned: 2026-11-13\n", "2026-11-13"),
    ("<!-- se:fleet -->\r\n\r\nPlanned:  2026-11-13  \r\n\r\n## Goal\r\n", "2026-11-13"),
    ("Planned: someday\n", None),
    ("Planned: 2026-02-30\n", None),
    ("Was Planned: 2026-11-13 in a sentence.\n", None),
    ("Planned: 2026-11-13 maybe\n", None),
    ("", None),
])
def test_the_planned_line_is_parsed_in_one_place(body, date):
    assert timeline.planned(body) == date


def test_an_open_issue_planned_after_today_is_a_stop_on_that_day_in_its_lane():
    page = fixture_page()
    assert planned_on(page, "o/a") == {"2026-11-13": [10, 11], "2027-01-05": [21]}
    assert planned_on(page, "o/b") == {"2026-11-13": [30], "2026-11-14": [12]}
    assert list(page["planned"]) == ["2026-11-13", "2026-11-14", "2027-01-05"]
    assert page["planned"]["2026-11-14"]["o/b"]["issues"][0]["needs_you"] is True
    html = timeline.render(page)
    rows = re.findall(r'<details class="row open planned">.*?</details></li></ul></div></details>', html, flags=re.S)
    assert [re.search(r'<span class="when">(.*?)</span>', row)[1] for row in rows] == ["13 Nov", "14 Nov", "5 Jan"]
    assert '<span class="count">2</span><span class="label">issue 11</span>' in rows[0]
    assert html.index('id="today"') < html.index(">13 Nov<") < html.index(">5 Jan<") < html.index("Needs you")
    assert html.index(">14 Nov<") < html.index('<div class="year">2027</div>') < html.index(">5 Jan<")


def test_a_planned_date_in_the_past_on_an_open_issue_is_today_marked_late():
    page = fixture_page()
    today = {entry["number"]: entry["late"] for entry in page["places"]["today"]["o/a"]}
    assert today == {13: True, 14: False}
    html = timeline.render(page)
    row = re.search(r'<details class="row open today" id="today">.*?</details></li></ul></div></details>', html, flags=re.S)[0]
    assert '<span class="lane late">' in row
    assert row.count('<span class="mark">late</span>') == 2  # the stop and issue #13
    assert "#14 issue 14</summary>" in row


def test_undated_ready_issues_stay_next_and_other_places_ignore_the_line():
    page = fixture_page()
    assert [entry["number"] for entry in page["places"]["next"]["o/a"]] == [20, 19, 16, 15]
    assert page["places"]["needs-you"]["o/b"] == []
    assert [entry["number"] for entry in page["places"]["backlog"]["o/a"]] == [17]
    assert [entry["number"] for entry in page["days"]["2026-11-11"]["o/a"]["issues"]] == [18]


PHONE = """
const {chromium} = require("playwright");
(async () => {
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 844}});
        await page.goto("file://" + process.argv[1]);
        const closed = await page.evaluate(() => document.documentElement.scrollWidth);
        await page.evaluate(() => document.querySelectorAll("details").forEach(box => { box.open = true; }));
        const open = await page.evaluate(() => document.documentElement.scrollWidth);
        console.log(JSON.stringify({closed, open}));
    } finally {
        await browser.close();
    }
})();
"""


def test_the_page_has_no_horizontal_scroll_on_a_390_px_phone(tmp_path):
    if shutil.which("node") is None or subprocess.run(["node", "-e", "require('playwright')"],
                                                      capture_output=True).returncode:
        pytest.skip("node with playwright is not installed")
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap["repositories"]["o/a"]["issues"][0]["title"] = "a-very-long-title-without-any-break-" * 4
    destination = tmp_path / "timeline.html"
    destination.write_text(timeline.render(timeline.model(snap)), encoding="utf-8")
    result = subprocess.run(["node", "-e", PHONE, str(destination)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"closed": 390, "open": 390}


# --- How long "needs you" has waited, [timeline] ages (work issue "timeline needs-you age") ---


def config(tmp_path, ages: str | None) -> str:
    """A --config file naming the two fake repositories, with `ages = <ages>` where given."""
    path = tmp_path / "se.toml"
    lines = ["[timeline]", 'repositories = ["o/a", "o/b"]'] + ([f"ages = {ages}"] if ages is not None else [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class AgesGitHub(FakeGitHub):
    """The fake GraphQL server, answering whichever query the setting picks."""

    def __call__(self, query: str, variables: dict) -> dict:
        self.queries = [*getattr(self, "queries", []), query]
        return super().__call__(timeline.QUERY, variables)


def labelled(name: str, at: str) -> dict:
    return {"createdAt": at, "label": {"name": name}}


def person_node(number: int, *events: dict, labels: tuple[str, ...] = ("se-person",)) -> dict:
    return node(number, labels={"nodes": [{"name": label} for label in labels]},
                timelineItems={"nodes": list(events)})


AGES_REPOSITORIES = {
    "o/a": {"issues": [person_node(1, labelled("se-person", "2026-10-29T23:59:00Z")),
                       person_node(2, labelled("se-person", "2026-10-01T10:00:00Z"),
                                   labelled("work", "2026-11-11T09:00:00Z"),
                                   labelled("se-person", "2026-11-11T00:01:00Z")),
                       person_node(3),
                       person_node(4, labelled("se-person", "2026-11-10T10:00:00Z"),
                                   labels=("ready", "se-person"))],
            "tags": []},
    "o/b": {"issues": [], "tags": []},
}


def test_the_query_without_ages_asks_for_no_label_events():
    assert timeline.query() == timeline.query(False) == timeline.QUERY
    assert "timelineItems" not in timeline.QUERY


@pytest.mark.parametrize("ages", [None, "false"])
def test_ages_absent_or_false_keep_the_query_the_snapshot_and_the_page(tmp_path, ages):
    github = AgesGitHub(AGES_REPOSITORIES)
    saved, page = tmp_path / "snap.json", tmp_path / "t.html"
    assert timeline.main(["--config", config(tmp_path, ages), "--destination", str(page),
                          "--save-snapshot", str(saved)], post=github) == 0
    assert github.queries == [timeline.QUERY, timeline.QUERY]
    snap = json.loads(saved.read_text(encoding="utf-8"))
    assert all("person_since" not in entry for entry in snap["repositories"]["o/a"]["issues"])
    assert page.read_text(encoding="utf-8") == timeline.render(timeline.model(snap))
    assert page.read_text(encoding="utf-8").count('<span class="mark">needs you</span>') == 4


def test_ages_on_read_the_label_events_in_the_same_request_and_save_person_since(tmp_path):
    github = AgesGitHub(AGES_REPOSITORIES)
    saved = tmp_path / "snap.json"
    assert timeline.main(["--config", config(tmp_path, "true"), "--destination", str(tmp_path / "t.html"),
                          "--save-snapshot", str(saved)], post=github) == 0
    assert github.queries == [timeline.AGES_QUERY, timeline.AGES_QUERY]
    assert [call["owner"] + "/" + call["name"] for call in github.calls] == ["o/a", "o/b"]
    assert "timelineItems(itemTypes: [LABELED_EVENT], last: 10)" in timeline.AGES_QUERY
    assert "createdAt label { name }" in timeline.AGES_QUERY
    snap = json.loads(saved.read_text(encoding="utf-8"))
    assert [entry["person_since"] for entry in snap["repositories"]["o/a"]["issues"]] == [
        "2026-10-29T23:59:00Z", "2026-11-11T00:01:00Z", None, "2026-11-10T10:00:00Z"]


def test_ages_on_mark_how_long_each_needs_you_issue_has_waited(tmp_path):
    destination = tmp_path / "t.html"
    assert timeline.main(["--config", config(tmp_path, "true"), "--destination", str(destination)],
                         post=AgesGitHub(AGES_REPOSITORIES), now=NOW) == 0
    html = destination.read_text(encoding="utf-8")
    assert "#1 t1<span class=\"mark\">needs you, 13 days</span>" in html
    assert "#2 t2<span class=\"mark\">needs you, today</span>" in html
    assert "#3 t3<span class=\"mark\">needs you</span></summary>" in html
    next_row = re.search(r'<details class="row open next">.*?</details></li></ul></div></details>', html, flags=re.S)[0]
    assert "#4 t4<span class=\"mark\">needs you, 1 day</span>" in next_row


def test_the_age_counts_whole_utc_calendar_days_and_is_pure():
    read_at = "2026-11-11T15:00:00+00:00"
    assert timeline.waiting_days("2026-10-29T23:59:00Z", read_at) == 13
    assert timeline.waiting_days("2026-11-10T23:59:00-02:00", read_at) == 0
    assert timeline.waiting_days(None, read_at) is None
    assert [timeline.needs_you_mark(days) for days in (None, 0, 1, 2)] == [
        "needs you", "needs you, today", "needs you, 1 day", "needs you, 2 days"]


def test_ages_on_keep_the_bare_mark_for_a_snapshot_saved_without_person_since(tmp_path):
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot(issue(1, "se-person"), issue(2, "backlogged", "se-person"))),
                      encoding="utf-8")
    destination = tmp_path / "t.html"
    assert timeline.main(["--config", config(tmp_path, "true"), "--snapshot", str(source),
                          "--destination", str(destination)]) == 0
    assert destination.read_text(encoding="utf-8").count('<span class="mark">needs you</span>') == 1
    page = timeline.model(json.loads(source.read_text(encoding="utf-8")), ages=True)
    assert page["places"]["needs-you"]["o/a"][0]["waiting_days"] is None
    assert "waiting_days" not in page["places"]["backlog"]["o/a"][0]


def test_without_ages_the_model_sets_no_waiting_days():
    page = timeline.model(snapshot({**issue(1, "se-person"), "person_since": "2026-11-01T00:00:00Z"}))
    assert "waiting_days" not in page["places"]["needs-you"]["o/a"][0]


@pytest.mark.parametrize("value", ['"yes"', "1", "[true]"])
def test_an_ages_value_other_than_true_or_false_is_refused(tmp_path, value):
    with pytest.raises(SystemExit, match=r"\[timeline\] ages"):
        timeline.main(["--config", config(tmp_path, value), "--destination", str(tmp_path / "t.html")],
                      post=AgesGitHub(AGES_REPOSITORIES))
    assert not (tmp_path / "t.html").exists()
