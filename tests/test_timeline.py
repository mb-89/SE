"""The Timeline builds from one batched read per repository, then from the snapshot alone, as one obs
table (scripts/timeline.py)."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fake_git
import git_door
import timeline

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)


def issue(number: int, *labels: str, state: str = "open", reason: str | None = None,
          closed: str | None = None, created: str = "2026-11-01T09:00:00Z",
          body: str = "## Goal\n\nThe goal.\n") -> dict:
    return {"number": number, "title": f"issue {number}", "url": f"https://github.com/o/a/issues/{number}",
            "state": state, "state_reason": reason, "created_at": created, "closed_at": closed,
            "labels": sorted(labels), "body": body}


def snapshot(*issues: dict, releases: tuple[dict, ...] = (), other: tuple[dict, ...] = ()) -> dict:
    return {"read_at": NOW.isoformat(), "repositories": {
        "o/a": {"issues": list(issues), "releases": list(releases)},
        "o/b": {"issues": list(other), "releases": []},
    }}


def placed(snap: dict, ages: bool = False) -> dict[object, str]:
    """Each row's number or tag of lane `a`, with its place."""
    return {row["number"]: row["place"] for row in timeline.rows(snap, ages) if row["repository"] == "a"}


def order(snap: dict) -> list[tuple[str, str, object]]:
    return [(row["place"], row["repository"], row["number"]) for row in timeline.rows(snap)]


# --- What shows where ---


def test_a_completed_issue_is_done_on_the_day_it_closed():
    snap = snapshot(issue(1, "work", state="closed", reason="completed", closed="2026-11-09T23:30:00Z"))
    assert placed(snap) == {1: "Done"}
    assert timeline.rows(snap)[0]["date"] == "2026-11-09"


@pytest.mark.parametrize("reason", ["not_planned", "duplicate"])
def test_an_issue_closed_as_not_planned_or_duplicate_is_hidden(reason):
    assert timeline.rows(snapshot(issue(1, state="closed", reason=reason, closed="2026-11-09T10:00:00Z"))) == []


@pytest.mark.parametrize(("labels", "where", "status"), [
    (("work", "in-progress"), "Today", "in progress"),
    (("work", "ready"), "Next", "ready"),
    (("se-person",), "Needs you", "needs you"),
    (("in-progress", "se-person"), "Today", "needs you"),
    (("backlogged", "se-person"), "Backlog", "waiting for your input"),
])
def test_an_open_issue_goes_to_the_place_its_labels_give_with_its_status(labels, where, status):
    row = timeline.rows(snapshot(issue(1, *labels)))[0]
    assert (row["place"], row["status"], row["date"]) == (where, status, "2026-11-01")


def test_field_reports_and_unlabelled_open_issues_are_left_out():
    snap = snapshot(issue(1, "field-report", state="closed", reason="completed", closed="2026-11-09T10:00:00Z"),
                    issue(2, "field-report", "in-progress"), issue(3))
    assert timeline.rows(snap) == []


def test_a_release_is_a_done_row_on_the_day_it_was_tagged():
    releases = ({"tag": "v1.0.0", "url": "u", "published_at": "2026-11-08T09:00:00Z"},
                {"tag": "v1.10.0", "url": "u", "published_at": "2026-11-08T09:00:00Z"},
                {"tag": "v1.2.0", "url": "u", "published_at": "2026-11-08T09:00:00Z"})
    rows = timeline.rows(snapshot(releases=releases))
    assert [(row["number"], row["place"], row["date"], row["subject"]) for row in rows] == [
        ("v1.10.0", "Done", "2026-11-08", "Release v1.10.0"), ("v1.2.0", "Done", "2026-11-08", "Release v1.2.0"),
        ("v1.0.0", "Done", "2026-11-08", "Release v1.0.0")]


# --- Newest first in every place (requirement 1, acceptance "the newest entry of each place is the first row") ---


def test_the_newest_entry_of_each_place_is_the_first_row_of_that_place():
    done = dict(state="closed", reason="completed")
    snap = snapshot(issue(1, "backlogged", "se-person", created="2026-10-01T09:00:00Z"),
                    issue(2, "backlogged", "se-person", created="2026-11-05T09:00:00Z"),
                    issue(3, "ready", created="2026-10-20T09:00:00Z"),
                    issue(4, "ready", created="2026-11-02T09:00:00Z"),
                    issue(5, closed="2026-11-03T08:00:00Z", **done),
                    issue(6, closed="2026-11-09T08:00:00Z", **done),
                    issue(7, "in-progress"),
                    releases=({"tag": "v1.0.0", "url": "u", "published_at": "2026-11-04T09:00:00Z"},),
                    other=(issue(8, "backlogged", "se-person", created="2026-11-03T09:00:00Z"),
                           issue(9, closed="2026-11-10T08:00:00Z", **done)))
    assert order(snap) == [
        ("Today", "a", 7),
        ("Next", "a", 4), ("Next", "a", 3),
        ("Backlog", "a", 2), ("Backlog", "b", 8), ("Backlog", "a", 1),
        ("Done", "b", 9), ("Done", "a", 6), ("Done", "a", "v1.0.0"), ("Done", "a", 5)]


def test_entries_of_one_day_put_the_higher_number_first():
    snap = snapshot(issue(1, "ready"), issue(2, "ready"), issue(3, "ready"))
    assert [number for _, _, number in order(snap)] == [3, 2, 1]


# --- The notes obs builds (requirements 1, 2 and 4) ---


def notes(snap: dict, ages: bool = False) -> dict[str, str]:
    return timeline.vault(snap, ages)


def table(files: dict[str, str]) -> dict:
    manifest = files["manifest.md"]
    return json.loads(manifest[manifest.index("```base\n") + 8:manifest.index("\n```\n")])


def front(note: str) -> dict:
    """A note's frontmatter, each line `key: <json>`."""
    lines = note.split("---\n")[1].splitlines()
    return {line.split(": ", 1)[0]: json.loads(line.split(": ", 1)[1]) for line in lines}


def test_the_timeline_is_one_obs_table_with_a_note_per_row():
    files = notes(snapshot(issue(1, "in-progress"), issue(2, "backlogged", "se-person"),
                           releases=({"tag": "v1.0.0", "url": "u", "published_at": "2026-11-04T09:00:00Z"},)))
    assert sorted(files) == ["entries/a-1.md", "entries/a-2.md", "entries/a-v1.0.0.md", "manifest.md"]
    assert files["manifest.md"].startswith("---\ntitle: \"Timeline\"\nobsHtml:\n  layout: scrolling\n")
    view = table(files)["views"][0]
    assert view["order"] == ["repository", "place", "date", "number", "subject", "status", "mark"]
    assert view["groupBy"] == {"property": "place", "direction": "ASC"}
    assert view["obsHtml"]["groupOrder"] == ["Today", "Needs you", "Next", "Backlog", "Done"]
    assert view["sort"][0] == {"property": "date", "direction": "DESC"}
    assert front(files["entries/a-1.md"]) == {
        "repository": "a", "place": "Today", "date": "2026-11-01", "number": 1, "subject": "issue 1",
        "status": "in progress", "state": "open", "labels": ["in-progress"], "rank": 0}
    assert front(files["entries/a-v1.0.0.md"])["number"] == "v1.0.0"


def test_the_table_pages_its_rows_with_obs():
    assert table(notes(snapshot(issue(1, "ready"))))["views"][0]["obsHtml"]["pageSize"] == timeline.PAGE_SIZE == 20


def test_a_backlog_row_is_marked_as_waiting_for_your_input():
    files = notes(snapshot(issue(1, "backlogged", "se-person"), issue(2, "ready")))
    assert front(files["entries/a-1.md"])["status"] == "waiting for your input"
    assert front(files["entries/a-2.md"])["status"] == "ready"
    assert "A backlog idea waits for your input before it is work." in files["manifest.md"]


def test_a_row_opens_on_the_first_paragraph_of_its_goal_and_its_link():
    body = "<!-- se:fleet -->\n## Goal\n\nA **timeline**\nof `SE`.\n\nMore.\n\n## Requirements\n\n1. x\n"
    files = notes(snapshot(issue(1, "ready", body=body)))
    assert files["entries/a-1.md"].endswith(
        "\nA timeline of SE\\.\n\n[Open \\#1 on GitHub](<https://github.com/o/a/issues/1>)\n")
    assert timeline.goal("No sections.\n\nSecond.") == "No sections."


def test_text_from_issues_shows_as_written_and_never_as_markup():
    files = notes(snapshot(issue(1, "ready", body="## Goal\n\n<script>x</script> [[note]] *a*")))
    assert "\n\\<script\\>x\\<\\/script\\> \\[\\[note\\]\\] \\*a\\*\n" in files["entries/a-1.md"]
    assert front(files["entries/a-1.md"])["subject"] == "issue 1"


def test_the_live_source_reads_each_repository_with_a_row_from_githubs_public_issue_list():
    files = notes(snapshot(issue(1, "ready")))
    live = table(files)["obsHtml"]["liveSource"]
    assert live["key"] == ["repository", "number"] and live["notePath"] == "entries/{repository}-{number}.md"
    assert live["changes"] == [{"provider": "web", "next": "link", "maxPages": 3, "requests": [
        {"set": {"repository": "a"},
         "url": "https://api.github.com/repos/o/a/issues?state=all&since={since}&sort=updated&direction=asc&per_page=100"}]}]
    assert live["exclude"] == [{"field": "pullRequest", "exists": True}]
    assert "the line under the table says it shows current data" in files["manifest.md"]


def test_a_snapshot_without_rows_declares_no_live_source():
    files = notes(snapshot())
    assert "obsHtml" not in table(files) and "asks GitHub" not in files["manifest.md"]


def derived(cases: list[dict], fields: dict):
    """The value obs's derive gives ``fields``: the first case whose conditions all match (equals ignores case)."""
    def matches(condition):
        value = fields.get(condition["field"])
        values = value if isinstance(value, list) else [value]
        return any(item is not None and str(item).casefold() == condition["equals"].casefold() for item in values)
    for case in cases:
        if all(matches(condition) for condition in case.get("where", [])):
            return case.get("value", "keep" if case.get("keep") else case.get("path"))
    return None


@pytest.mark.parametrize("labels", [(), ("ready",), ("in-progress",), ("se-person",), ("backlogged", "se-person"),
                                    ("in-progress", "se-person"), ("field-report",), ("ready", "backlogged")])
@pytest.mark.parametrize(("state", "reason"), [("open", None), ("closed", "completed"), ("closed", "not_planned"),
                                               ("closed", "duplicate"), ("open", "reopened")])
def test_the_live_derive_gives_every_issue_the_place_and_status_the_build_gives(labels, state, reason):
    live = timeline.live_source(["o/a"])
    entry = issue(1, *labels, state=state, reason=reason, closed="2026-11-09T10:00:00Z" if state == "closed" else None)
    fields = {"state": state, "state_reason": reason, "labels": list(labels)}
    rows = timeline.rows(snapshot(entry))
    assert derived(live["derive"]["place"], fields) == (rows[0]["place"] if rows else "hidden")
    if rows:
        assert derived(live["derive"]["status"], fields) == rows[0]["status"]


def test_a_repository_without_rows_gets_no_live_request():
    snap = snapshot(issue(1, "ready"))
    assert [request["set"] for request in table(notes(snap))["obsHtml"]["liveSource"]["changes"][0]["requests"]] == [
        {"repository": "a"}]


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
            "state": "OPEN", "stateReason": None, "createdAt": f"2026-10-{number % 28 + 1:02d}T10:00:00Z", "closedAt": None, "body": "", "labels": {"nodes": []}, **fields}


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
        "state_reason": "not_planned", "created_at": "2026-10-02T10:00:00Z", "closed_at": "2026-11-02T10:00:00Z", "labels": ["work"], "body": ""}


def test_more_issues_than_a_page_continue_the_same_pass_without_the_tags_read():
    github = FakeGitHub({"o/a": {"issues": [node(n) for n in range(1, 251)], "tags": []}}, page_size=100)
    snap = timeline.read(["o/a"], github, NOW)
    assert [(call["issues"], call["withIssues"], call["withTags"]) for call in github.calls] == [
        (None, True, True), ("100", True, False), ("200", True, False)]
    assert [entry["number"] for entry in snap["repositories"]["o/a"]["issues"]] == list(range(1, 251))


def test_the_query_names_every_field_the_snapshot_reads():
    for field in ("issues(first: 100", "refs(refPrefix: \"refs/tags/\", first: 100", "stateReason", "createdAt", "closedAt",
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


# --- The command (requirement 5) ---


@pytest.fixture
def captured(monkeypatch):
    """`timeline.build` without obs: each call writes the notes it was given to its destination as JSON
    and is recorded with its generation time."""
    calls = []

    def build(files, destination, read_at):
        calls.append(read_at)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(files, indent=1), encoding="utf-8")
        return 0

    monkeypatch.setattr(timeline, "build", build)
    return calls


def built_notes(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_page_builds_from_a_snapshot_with_no_network(tmp_path, monkeypatch, capsys, captured):
    def no_network(*args, **kwargs):
        raise AssertionError("the build from a snapshot opened a connection")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot(issue(1, "in-progress"))), encoding="utf-8")
    destination = tmp_path / "site" / "timeline.html"
    assert timeline.main(["--snapshot", str(source), "--destination", str(destination)]) == 0
    assert "entries/a-1.md" in built_notes(destination)
    assert captured == [NOW.isoformat()]
    assert "wrote" in capsys.readouterr().out


def absolute_config(tmp_path):
    """A se.toml naming its repositories as `<owner>/<repo>`, which needs no origin."""
    config = tmp_path / "se.toml"
    config.write_text('[timeline]\nrepositories = ["alice/SE", "alice/obs"]\n', encoding="utf-8")
    return config


def test_a_read_saves_its_snapshot_and_rebuilds_the_same_notes(tmp_path, captured):
    github = FakeGitHub({name: {"issues": [node(1, labels={"nodes": [{"name": "ready"}]})], "tags": []}
                         for name in ("alice/SE", "alice/obs")})
    config = absolute_config(tmp_path)
    saved, first, second = tmp_path / "snap.json", tmp_path / "a.html", tmp_path / "b.html"
    assert timeline.main(["--config", str(config), "--destination", str(first), "--save-snapshot", str(saved)],
                         post=github, now=NOW) == 0
    assert len(github.calls) == 2
    assert timeline.main(["--snapshot", str(saved), "--destination", str(second)]) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert captured == [NOW.isoformat(), NOW.isoformat()]


def test_a_read_without_a_token_is_a_setup_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert timeline.main(["--config", str(absolute_config(tmp_path)), "--destination", str(tmp_path / "t.html")]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_a_refused_read_writes_nothing(tmp_path, capsys, captured):
    def refuse(query, variables):
        raise timeline.ReadError("GitHub answered 502 to the GraphQL read")

    destination = tmp_path / "t.html"
    assert timeline.main(["--config", str(absolute_config(tmp_path)), "--destination", str(destination)],
                         post=refuse) == 1
    assert not destination.exists() and captured == []
    assert "502" in capsys.readouterr().err


def test_the_docs_workflow_still_builds_the_timeline_hourly_and_on_issue_events():
    workflow = (timeline.ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    assert 'python3 scripts/timeline.py --destination "$RUNNER_TEMP/site/timeline.html"' in workflow
    assert "schedule:" in workflow and "issues:" in workflow
    assert workflow.index("Build the documentation") < workflow.index("Build the Timeline")


# --- Planned days ---

FIXTURE = timeline.ROOT / "tests" / "fixtures" / "timeline-planned.json"


def fixture_rows() -> dict[tuple[str, object], dict]:
    return {(row["repository"], row["number"]): row for row in timeline.rows(json.loads(FIXTURE.read_text(encoding="utf-8")))}


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


def test_a_planned_open_issue_stays_in_its_place_and_its_mark_names_the_day():
    rows = fixture_rows()
    assert {key: (row["place"], row["mark"]) for key, row in rows.items() if row["mark"]} == {
        ("a", 10): ("Next", "planned 2026-11-13"), ("a", 11): ("Next", "planned 2026-11-13"),
        ("a", 21): ("Next", "planned 2027-01-05"), ("b", 30): ("Next", "planned 2026-11-13"),
        ("b", 12): ("Needs you", "planned 2026-11-14"),
        ("a", 13): ("Next", "late, planned 2026-11-10"), ("a", 14): ("Today", "planned 2026-11-12")}


def test_undated_ready_issues_and_other_places_have_no_mark():
    rows = fixture_rows()
    assert [rows[("a", number)]["mark"] for number in (15, 16, 19, 20)] == ["", "", "", ""]
    assert (rows[("a", 17)]["place"], rows[("a", 17)]["mark"]) == ("Backlog", "")
    assert (rows[("a", 18)]["place"], rows[("a", 18)]["mark"]) == ("Done", "")


# --- The page obs builds (requirements 1 to 4), in a browser ---

BROWSER = """
const {chromium} = require("playwright");
(async () => {
    const [file, answer, turn] = process.argv.slice(1);
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 844}});
        const asked = [];
        const answers = answer === "none" ? {} : JSON.parse(answer);
        await page.route("https://api.github.com/**", route => {
            const url = route.request().url();
            asked.push(url);
            const name = url.split("/repos/")[1].split("/issues")[0];
            return route.fulfill({status: 200, contentType: "application/json",
                                  headers: {"access-control-allow-origin": "*"},
                                  body: JSON.stringify(answers[name] || [])});
        });
        await page.goto("file://" + file);
        const rowsOf = 'th[data-column-key="repository"]';
        await page.waitForFunction(sel => !!document.querySelector(sel)?.closest("table").querySelector("tbody tr"), rowsOf);
        if (answer !== "none") {
            await page.waitForFunction(() => document.body.innerText.includes("Showing current data"),
                                       null, {timeout: 20000});
        }
        if (turn === "next") {
            await page.click('button[aria-label="Next table page"]');
        }
        await page.waitForTimeout(500);
        const read = await page.evaluate(sel => ({
            rows: [...document.querySelector(sel).closest("table").querySelectorAll("tbody tr")].map(row => row.innerText.split("\\t")
                .map(cell => cell.replace(/^[\\u25be\\u25b8]\\s*/, "").trim()).filter(Boolean)).filter(cells => cells.length),
            text: document.body.innerText,
            width: document.documentElement.scrollWidth,
        }), rowsOf);
        console.log(JSON.stringify({...read, asked}));
    } finally {
        await browser.close();
    }
})();
"""


def large_snapshot() -> dict:
    """25 ready issues of lane a, a backlog idea in each lane, an issue in progress and a closed one."""
    done = dict(state="closed", reason="completed")
    ready = [issue(n, "ready", created=f"2026-10-{n:02d}T09:00:00Z") for n in range(1, 26)]
    return snapshot(*ready, issue(40, "backlogged", "se-person", created="2026-11-02T09:00:00Z"),
                    issue(41, "in-progress"), issue(42, closed="2026-11-10T08:00:00Z", **done),
                    other=(issue(50, "backlogged", "se-person", created="2026-11-05T09:00:00Z"),))


def need_browser():
    if shutil.which("node") is None or subprocess.run(["node", "-e", "require('playwright')"],
                                                      capture_output=True).returncode:
        pytest.skip("node with playwright is not installed")


@pytest.fixture(scope="module")
def page(tmp_path_factory, obs):
    """The Timeline obs built from `large_snapshot`; every test of it opens a browser, so it skips
    before the build where none is installed."""
    need_browser()
    destination = tmp_path_factory.mktemp("timeline") / "timeline.html"
    snap = large_snapshot()
    assert timeline.build(timeline.vault(snap), destination, snap["read_at"]) == 0
    return destination


def opened(page: Path, answer: dict[str, list] | None = None, turn: bool = False) -> dict:
    """What a 390 px browser shows of ``page``: its table rows, its text and its width, with GitHub
    answering each repository's list from ``answer`` (an empty list where it has none), on the next
    table page where ``turn``."""
    need_browser()
    result = subprocess.run(["node", "-e", BROWSER, str(page), json.dumps(answer) if answer is not None else "none",
                             "next" if turn else "stay"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_obs_proves_the_live_declaration_against_every_saved_row(page, obs):
    build_docs = timeline.sibling("build_docs")
    adapter, refusal = build_docs.html_adapter(obs)
    assert refusal == ""
    result = subprocess.run(["uv", "run", "--quiet", "--project", adapter["folder"], "obs-html", "--check-rendered",
                             str(page)], capture_output=True, text=True, env=build_docs.child_environment(), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 console errors" in result.stdout


def test_the_page_opens_on_the_newest_row_of_each_place_and_pages_the_rest(page):
    seen = opened(page)
    rows = seen["rows"]
    captions = [cells[0] for cells in rows if cells[0].startswith("Place:")]
    assert captions == ["Place: Today (1)", "Place: Next (25)"]
    first = rows[rows.index(["Place: Next (25)"]) + 1]
    assert first[:5] == ["a", "Next", "2026-10-25", "25", "issue 25"]
    assert "Page 1 of 2" in seen["text"]
    assert seen["width"] == 390


def test_a_backlog_row_shows_as_waiting_for_your_input_in_the_page(page):
    seen = opened(page, turn=True)
    assert "Page 2 of 2" in seen["text"]
    rows = seen["rows"]
    backlog = rows[rows.index(["Place: Backlog (2)"]) + 1:rows.index(["Place: Backlog (2)"]) + 3]
    assert [cells[:4] for cells in backlog] == [["b", "Backlog", "2026-11-05", "50"], ["a", "Backlog", "2026-11-02", "40"]]
    assert all(cells[5].startswith("waiting for") for cells in backlog)


def test_the_page_shows_what_github_answers_when_it_opens(page):
    moved = {"number": 3, "title": "issue 3", "state": "open", "state_reason": None,
             "labels": [{"name": "in-progress"}, {"name": "ready"}], "created_at": "2026-10-03T09:00:00Z",
             "closed_at": None, "body": "Moved."}
    seen = opened(page, {"o/a": [moved]})
    assert [url.split("?")[0] for url in seen["asked"]] == [
        "https://api.github.com/repos/o/a/issues", "https://api.github.com/repos/o/b/issues"]
    assert all("since=2026-11-11T14%3A00%3A00Z" in url for url in seen["asked"])  # an hour before the read
    rows = seen["rows"]
    today = rows[rows.index(["Place: Today (2)"]) + 1:rows.index(["Place: Today (2)"]) + 3]
    assert [cells[:4] for cells in today] == [["a", "Today", "2026-11-01", "41"],
                                              ["a", "Today", "2026-10-03T09:00:00Z", "3"]]
    assert "Place: Next (24)" in [cells[0] for cells in rows]
    assert "Showing current data" in seen["text"]
    assert "from the snapshot read on 11 Nov 2026" in seen["text"]


# --- How long "needs you" has waited, [timeline] ages ---


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
def test_ages_absent_or_false_keep_the_query_the_snapshot_and_the_marks(tmp_path, ages, captured):
    github = AgesGitHub(AGES_REPOSITORIES)
    saved, page = tmp_path / "snap.json", tmp_path / "t.html"
    assert timeline.main(["--config", config(tmp_path, ages), "--destination", str(page),
                          "--save-snapshot", str(saved)], post=github) == 0
    assert github.queries == [timeline.QUERY, timeline.QUERY]
    snap = json.loads(saved.read_text(encoding="utf-8"))
    assert all("person_since" not in entry for entry in snap["repositories"]["o/a"]["issues"])
    assert built_notes(page) == timeline.vault(snap)
    assert [row["mark"] for row in timeline.rows(snap)] == ["", "", "", ""]


def test_ages_on_read_the_label_events_in_the_same_request_and_save_person_since(tmp_path, captured):
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


def test_ages_on_mark_how_long_each_needs_you_issue_has_waited(tmp_path, captured):
    destination = tmp_path / "t.html"
    assert timeline.main(["--config", config(tmp_path, "true"), "--destination", str(destination)],
                         post=AgesGitHub(AGES_REPOSITORIES), now=NOW) == 0
    marks = {front(note)["number"]: front(note).get("mark") for path, note in built_notes(destination).items()
             if path.startswith("entries/a-")}
    assert marks == {1: "needs you, 13 days", 2: "needs you, today", 3: None, 4: "needs you, 1 day"}


def test_the_age_counts_whole_utc_calendar_days_and_is_pure():
    read_at = "2026-11-11T15:00:00+00:00"
    assert timeline.waiting_days("2026-10-29T23:59:00Z", read_at) == 13
    assert timeline.waiting_days("2026-11-10T23:59:00-02:00", read_at) == 0
    assert timeline.waiting_days(None, read_at) is None
    assert [timeline.needs_you_mark(days) for days in (None, 0, 1, 2)] == [
        "needs you", "needs you, today", "needs you, 1 day", "needs you, 2 days"]


def test_ages_on_keep_no_age_for_a_snapshot_saved_without_person_since():
    snap = snapshot(issue(1, "se-person"), issue(2, "backlogged", "se-person"))
    assert [row["mark"] for row in timeline.rows(snap, ages=True)] == ["", ""]


def test_without_ages_the_rows_carry_no_age():
    snap = snapshot({**issue(1, "se-person"), "person_since": "2026-11-01T00:00:00Z"})
    assert timeline.rows(snap)[0]["mark"] == ""
    assert timeline.rows(snap, ages=True)[0]["mark"] == "needs you, 10 days"


@pytest.mark.parametrize("value", ['"yes"', "1", "[true]"])
def test_an_ages_value_other_than_true_or_false_is_refused(tmp_path, value, captured):
    with pytest.raises(SystemExit, match=r"\[timeline\] ages"):
        timeline.main(["--config", config(tmp_path, value), "--destination", str(tmp_path / "t.html")],
                      post=AgesGitHub(AGES_REPOSITORIES))
    assert not (tmp_path / "t.html").exists()


# --- kern's rows and a repository that cannot be read (work issue "timeline-shows-kern") ---


def test_a_snapshot_of_three_repositories_shows_each_with_kerns_release():
    snap = {"read_at": NOW.isoformat(), "repositories": {
        "alice/SE": {"issues": [issue(1, "ready")], "releases": []},
        "alice/obs": {"issues": [issue(2, "in-progress")], "releases": []},
        "alice/kern": {"issues": [issue(3, closed="2026-11-10T09:00:00Z", state="closed")], "releases": [
            {"tag": "v0.14.0", "url": "https://github.com/alice/kern/releases/tag/v0.14.0",
             "published_at": "2026-11-10T12:00:00Z"}]},
    }}
    files = timeline.vault(snap)
    assert {(front(note)["repository"], front(note)["number"]) for path, note in files.items() if path != "manifest.md"} == {
        ("SE", 1), ("obs", 2), ("kern", 3), ("kern", "v0.14.0")}
    assert "The issues and releases of SE\\, obs and kern, " in files["manifest.md"]
    assert "(<https://github.com/alice/kern/releases/tag/v0.14.0>)" in files["entries/kern-v0.14.0.md"]
    requests = table(files)["obsHtml"]["liveSource"]["changes"][0]["requests"]
    assert [request["set"]["repository"] for request in requests] == ["SE", "obs", "kern"]


def three_repositories_config(tmp_path):
    config = tmp_path / "se.toml"
    config.write_text('[timeline]\nrepositories = ["alice/SE", "alice/obs", "alice/kern"]\n', encoding="utf-8")
    return config


@pytest.mark.parametrize("refusal", ["refused", "no repository"])
def test_a_repository_that_cannot_be_read_is_named_and_the_page_still_builds(tmp_path, capsys, refusal, captured):
    github = FakeGitHub({name: {"issues": [node(1, labels={"nodes": [{"name": "ready"}]})], "tags": []}
                         for name in ("alice/SE", "alice/obs")})

    def post(query, variables):
        if variables["name"] != "kern":
            return github(query, variables)
        if refusal == "refused":
            raise timeline.ReadError("GitHub refused the read: Could not resolve to a Repository with the name 'alice/kern'.")
        return {"repository": None}

    destination, saved = tmp_path / "t.html", tmp_path / "snap.json"
    assert timeline.main(["--config", str(three_repositories_config(tmp_path)), "--destination", str(destination),
                          "--save-snapshot", str(saved)], post=post) == 0
    files = built_notes(destination)
    assert sorted(files) == ["entries/SE-1.md", "entries/obs-1.md", "manifest.md"]
    assert "\nNot shown: alice\\/kern could not be read (GitHub " in files["manifest.md"]
    assert "alice/kern could not be read" in capsys.readouterr().err
    snap = json.loads(saved.read_text(encoding="utf-8"))
    assert list(snap["repositories"]) == ["alice/SE", "alice/obs"] and list(snap["unreadable"]) == ["alice/kern"]
    rebuilt = tmp_path / "rebuilt.html"
    assert timeline.main(["--snapshot", str(saved), "--destination", str(rebuilt)]) == 0
    assert rebuilt.read_text(encoding="utf-8") == destination.read_text(encoding="utf-8")


def test_a_snapshot_with_every_repository_read_names_no_gap():
    assert "Not shown:" not in timeline.vault(snapshot(issue(1, "ready")))["manifest.md"]
