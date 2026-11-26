"""`retro.py collect`: a retro's window read through a fake door (gh) or, without gh, from the
answer files the session saved from the printed plans; the commits of main from git."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import retro
import templates
import se_component
import se_usage
import work_tickets
import git_door
import fake_git

REPO = "github.com/owner/repo"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
# The commits on main, oldest first: (subject, committer date).
COMMITS = (("Initial", "2026-01-01T00:00:00+00:00"),
           ("Integrate feat/a", "2026-11-02T10:00:00+00:00"),
           ("Integrate feat/b", "2026-11-03T10:00:00+00:00"),
           ("Tidy up (#25)", "2026-11-03T11:00:00+00:00"),
           ("Hotfix pushed by hand", "2026-11-04T10:00:00+00:00"))


def git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    result = git_door.run(*arguments, root=root, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def build_checkout(tmp_path: Path) -> None:
    """A bare origin whose main holds COMMITS, and a clone of it."""
    origin, work, root = tmp_path / "origin.git", tmp_path / "work", tmp_path / "main"
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, work)
    git(work, "config", "user.name", "alice")
    git(work, "config", "user.email", "alice@example.com")
    for index, (subject, date) in enumerate(COMMITS):
        (work / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", subject,
            env={**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})
    git(work, "push", "-q", "origin", "main")
    fake_git.clone(origin, root, "-b", "main")


@pytest.fixture
def checkout(tmp_path: Path, fake_git_door) -> Path:
    build_checkout(tmp_path)
    return tmp_path / "main"


# The retro docs the retro reports in the answers link, by (commit, path); the checkout's git
# reads every other.
DOCS: dict[tuple[str, str], str] = {}


@pytest.fixture(autouse=True)
def linked_docs(monkeypatch):
    real = retro.git_show
    monkeypatch.setattr(retro, "git_show", lambda root: lambda sha, path: DOCS.get(
        (sha, path)) or real(root)(sha, path))


def posted(number: int, block: dict) -> str:
    """Retro `number`'s report as it posts: a link to its committed doc, whose block is
    `block`, judged."""
    sha, path = f"{number:040x}", f"docs/retro-{number}.md"
    DOCS[(sha, path)] = (f"# Retro draft for #{number}\n\n{retro.BLOCK_MARKER}\n```yaml\n"
                         + json.dumps({"window": {"retro": number}, "findings": [],
                                       "classes": [], "went_well": ["w"], **block}) + "\n```\n")
    return f"Report.\n\n{retro.DOC_MARKER.format(sha=sha, path=path)}\n"


def commit_doc(checkout: Path, text: str, name: str = "docs/retro-30.md") -> Path:
    """`text` committed as the retro doc `name` on origin's main, as a landing leaves it."""
    doc = checkout / name
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text, encoding="utf-8")
    for setting in (("user.name", "alice"), ("user.email", "alice@example.com")):
        git(checkout, "config", *setting)
    git(checkout, "add", name)
    git(checkout, "commit", "-q", "-m", f"Land {name}")
    git(checkout, "push", "-q", "origin", "HEAD:main")
    return doc


def shas(checkout: Path) -> dict[str, str]:
    """Each commit's sha, by subject."""
    return {line.split(" ", 1)[1]: line.split(" ", 1)[0]
            for line in git(checkout, "log", "--format=%H %s", "origin/main").splitlines()}


def issue_url(number: int) -> str:
    return f"https://github.com/owner/repo/issues/{number}"


def report(retro_section: str, not_delivered: str) -> str:
    return (f"Fixes {issue_url(0)}\n\n<!-- se:field-report -->\n**Result:** complete\n\n"
            f"## Delivered\n\n| a | b |\n|---|---|\n\n## Not delivered\n\n{not_delivered}\n\n"
            f"## Decisions\n\nNone\n\n## Retro\n\n{retro_section}\n<!-- se:field-report:end -->\n")


def answered(**answers: str) -> str:
    """A field report's Retro section: each standing question, `answers` by its field, else None."""
    return "\n".join(f"### {item.heading}\n\n{answers.get(item.name, 'None.')}\n"
                     for item in retro.questions().fields)


def steps() -> str:
    """The five steps of the retro template, filled from its example."""
    template = retro.retro_template()
    return retro.templates().render(template, template.example["fields"])


def fill_steps(text: str) -> str:
    """The draft `text` with every standing question answered None and decisions left open."""
    text = re.sub(r"^(### [^\n]+\n\n)<!-- \w+: [^\n]*-->$", r"\1None.", text, flags=re.MULTILINE)
    return re.sub(r"^(<!-- decisions: [^\n]*-->)$", r"\1\n\nOpen: The deck carries the person's answer.",
                  text, count=1, flags=re.MULTILINE)


def issue(number: int, title: str, closed: str, reason: str = "completed",
          labels: tuple[str, ...] = ("work",)) -> dict:
    return {"number": number, "title": title, "state": "closed", "closed_at": closed,
            "state_reason": reason, "labels": [{"name": name} for name in labels], "body": ""}


def pull(number: int, head: str, body: str, merged: str | None = None, sha: str = "",
         title: str = "") -> dict:
    return {"number": number, "title": title or head, "body": body, "base": {"ref": "main"},
            "head": {"ref": head, "sha": f"{number:040d}"}, "merged_at": merged,
            "merge_commit_sha": sha or None}


def run(conclusion: str, completed: str | None, name: str = "check") -> dict:
    """A check run as the host's tools answer it, completed at `completed` (None: still running)."""
    return {"name": name, "status": "completed" if completed else "in_progress",
            "conclusion": conclusion if completed else None, "completed_at": completed}


def answers(checkout: Path) -> dict[str, object]:
    """A window after retro #5 closed: #11 landed after one refused delivery, #12 landed but
    escalated and its landing's check failed, #13 a duplicate, #14 closed without a field report;
    #25 landed naming no work issue and one commit reached main by hand."""
    commit = shas(checkout)
    previous = {"version": 1, "sizes": {"closed": 7, "landed": 5, "duplicates": 0, "escalated": 3}}
    work_a = report(answered(goes_well="the fake door", goes_badly="a slow fixture"),
                    "- The live run against GitHub: no token in the container.\n"
                    "- A second item\n  that wraps.").replace(issue_url(0), issue_url(11))
    work_b = report(answered(bad_output_cause="`src/agents/worker.md`: say it once"),
                    "None").replace(issue_url(0),
                                                                          issue_url(12))
    return {
        "issues.json": [
            issue(3, "feat/old", "2026-10-01T00:00:00Z"),
            issue(5, "docs/retro-20261101", "2026-11-01T00:00:00Z"),
            issue(11, "feat/a", "2026-11-02T12:00:00Z"),
            issue(12, "feat/b", "2026-11-03T12:00:00Z", labels=("work", "escalated")),
            issue(13, "feat/a-twin", "2026-11-03T13:00:00Z", reason="duplicate"),
            issue(14, "chore/lost", "2026-11-04T12:00:00Z"),
            issue(15, "Not a work issue", "2026-11-04T12:00:00Z", labels=()),
        ],
        "pulls.json": [
            pull(21, "land/feat/a", work_tickets.landing_description(
                "https://github.com/owner/repo/pull/22", 22, issue_url(11), "minor"),
                 "2026-11-02T10:00:00Z", commit["Integrate feat/a"], "Integrate feat/a"),
            pull(22, "feat/a", work_a),
            pull(23, "land/feat/b", work_tickets.landing_description(
                "https://github.com/owner/repo/pull/24", 24, issue_url(12), "minor"),
                 "2026-11-03T10:00:00Z", commit["Integrate feat/b"], "Integrate feat/b"),
            pull(24, "feat/b", work_b),
            pull(25, "chore/c", "Tidy up.", "2026-11-03T11:00:00Z", commit["Tidy up (#25)"],
                 "Tidy up"),
            pull(26, "feat/abandoned", "Refs #14"),
        ],
        "comments-5.json": [{"body": posted(5, previous)}],
        "comments-11.json": [
            {"body": "Integration stopped: Cannot merge feat/a; conflicts: x.py\n"},
            {"body": "Integrated in abc1234 from PR #22, landed through #21 (check: url). "
                     "Suite: 887 passed in 34.55s; 35.4 s (target 60 s, limit 120 s).\n"}],
        "comments-12.json": [{"body": "Which side wins?\n"},
                             {"body": "Integrated in def5678 from PR #24. Suite: 880 passed; "
                                      "40 s (target 60 s, limit 120 s).\n"}],
        "comments-3.json": [], "comments-13.json": [], "comments-14.json": [],
        "open-issues.json": [],
        "checks-21.json": {"total_count": 1, "check_runs": [
            run("success", "2026-11-02T09:50:00Z")]},
        "checks-23.json": {"check_runs": [run("failure", "2026-11-03T09:50:00Z")]},
        "checks-25.json": {"check_runs": [run("success", "2026-11-03T10:50:00Z")]},
    }


class FakeDoor:
    """The collect's reads, recorded, from `answers`."""

    def __init__(self, given: dict[str, object]) -> None:
        self.given, self.reads, self.missing = given, [], []

    def read(self, name: str) -> object:
        self.reads.append(name)
        return self.given[name]

    def closed_issues(self):
        return retro.listed(self.read("issues.json"), "issues")

    def open_issues(self):
        return retro.listed(self.read("open-issues.json"), "issues")

    def pulls(self):
        return retro.listed(self.read("pulls.json"), "pulls")

    def issue(self, number):
        return self.read(f"issue-{number}.json")

    def comments(self, number):
        return retro.listed(self.read(f"comments-{number}.json"), "comments")

    def checks(self, found):
        return retro.listed(self.read(f"checks-{found.number}.json"), "check_runs")

    def pull_comments(self, number):
        return retro.listed(self.read(f"pull-comments-{number}.json"), "comments")


def collected(checkout: Path, given: dict[str, object] | None = None, **window) -> retro.Collected:
    door = FakeDoor(given or answers(checkout))
    found = retro.collect(checkout, 30, door, REPO, "main", "origin/main", NOW, **window)
    assert found is not None
    return found


def test_the_window_gives_the_sizes_and_the_per_issue_counts(checkout):
    found = collected(checkout)

    assert found.window == retro.Window(30, "2026-11-01T00:00:00Z", 5, "2026-11-12T12:00:00Z",
                                        retro.CLOSED_RETRO)
    assert [item.number for item in found.issues] == [11, 12, 13, 14]
    assert found.sizes == {"closed": 4, "landed": 2, "duplicates": 1, "escalated": 2}
    by = {item.number: item for item in found.issues}
    assert (by[11].refused, by[11].escalations, by[11].suite_seconds) == (1, 1, 35.4)
    assert (by[11].landing_pull, by[11].report_pull) == (21, 22)
    assert (by[12].refused, by[12].escalations, by[12].suite_seconds) == (0, 1, 40.0)
    assert by[13].duplicate and not by[13].landed and not by[14].landed
    assert by[11].retro == {"goes_well": "the fake door", "goes_badly": "a slow fixture"}
    assert by[12].retro == {"bad_output_cause": "`src/agents/worker.md`: say it once"}
    assert by[11].not_delivered == ["The live run against GitHub: no token in the container.",
                                    "A second item that wraps."]
    assert by[12].not_delivered == []
    assert found.previous == {"retro": 5, "sizes": {"closed": 7, "landed": 5, "duplicates": 0,
                                                     "escalated": 3}, "findings": []}


def test_each_rule_check_names_what_broke_it_and_keeps_the_rest(checkout):
    checks = {check.name: check for check in collected(checkout).checks}
    hotfix = shas(checkout)["Hotfix pushed by hand"]

    assert checks["work-issue"].checked == 3 and checks["work-issue"].broken == [
        {"item": "#25", "what": "names no work issue (Fixes|Refs <issue url>)"}]
    assert checks["check"].checked == 3 and checks["check"].broken == [
        {"item": "#23", "what": "check failure"}]
    assert checks["outside-pr"].checked == 4 and checks["outside-pr"].broken == [
        {"item": hotfix[:12], "what": "Hotfix pushed by hand"}]
    assert checks["field-report"].checked == 3 and checks["field-report"].broken == [
        {"item": "#14", "what": "no pull request naming it carries a field report"}]

    given = answers(checkout)
    given["pulls.json"] = [item for item in given["pulls.json"] if item["number"] != 25]
    given["pulls.json"].append(pull(25, "chore/c", f"Refs {issue_url(40)}", "2026-11-03T11:00:00Z",
                                    shas(checkout)["Tidy up (#25)"], "Tidy up"))  # #40 is still open
    given["checks-23.json"] = given["checks-21.json"]
    checks = {check.name: check for check in collected(checkout, given).checks}
    assert checks["work-issue"].kept and checks["check"].kept
    assert not checks["outside-pr"].kept and not checks["field-report"].kept


def test_the_check_rule_judges_a_landing_by_the_run_that_gated_its_merge(checkout):
    """The `check` rule reads the last `check` run that completed before the landing merged: a
    scheduled run on the same commit that failed after the merge, a run still going or another
    check's run does not count; a landing with no run completed before its merge breaks it."""
    given = answers(checkout)
    given["checks-21.json"] = {"check_runs": [
        run("failure", "2026-11-03T02:00:00Z"),  # the nightly run, a day after the merge
        run("success", "2026-11-02T09:50:00Z"),
        run("failure", "2026-11-02T09:40:00Z"),  # an earlier push's run, rerun green
        run("failure", "2026-11-02T09:55:00Z", name="kern-platforms (windows-2025)"),
        run("failure", None)]}
    broken = {check.name: check for check in collected(checkout, given).checks}["check"].broken
    assert broken == [{"item": "#23", "what": "check failure"}]

    given["checks-21.json"] = {"check_runs": [run("success", "2026-11-02T10:05:00Z")]}
    broken = {check.name: check for check in collected(checkout, given).checks}["check"].broken
    head = f"{21:040d}"[:12]
    assert broken[0] == {"item": "#21", "what": f"no check run on {head} completed before it "
                                                 "merged at 2026-11-02T10:00:00Z"}


def test_a_landing_naming_a_closed_or_foreign_issue_breaks_the_work_issue_check(checkout):
    given = answers(checkout)
    commit = shas(checkout)["Tidy up (#25)"]
    given["pulls.json"][4] = pull(25, "chore/c", "Refs #3", "2026-11-03T11:00:00Z", commit, "Tidy up")
    broken = {check.name: check for check in collected(checkout, given).checks}["work-issue"].broken
    assert broken == [{"item": "#25", "what": "names #3, closed before the pull request merged"}]
    given["pulls.json"][4] = pull(25, "chore/c", "Refs #15", "2026-11-03T11:00:00Z", commit, "Tidy up")
    broken = {check.name: check for check in collected(checkout, given).checks}["work-issue"].broken
    assert broken == [{"item": "#25", "what": "names #15, which is not labelled work"}]


def test_without_a_closed_retro_the_window_is_the_whole_history(checkout):
    """No retro issue has closed: the window starts at the project's first issue, whatever retro
    issue is open, this one among them, so a first retro collects every landed issue."""
    given = answers(checkout)
    given["issues.json"] = [item for item in given["issues.json"] if item["number"] != 5]
    given["open-issues.json"] = [
        {**issue(30, "docs/retro-20261105", None), "state": "open",
         "created_at": "2026-11-05T00:00:00Z"},
        {**issue(31, "retro: fleet 20261102", None, labels=("retro",)), "state": "open",
         "createdAt": "2026-11-02T13:00:00Z"},
        {**issue(29, "feat/open", None), "state": "open", "created_at": "2026-10-01T00:00:00Z"}]
    found = collected(checkout, given)

    assert found.window == retro.Window(30, None, None, "2026-11-12T12:00:00Z", retro.HISTORY)
    assert [item.number for item in found.issues] == [3, 11, 12, 13, 14]
    assert [item.number for item in found.issues if item.landed] == [11, 12]
    assert found.previous is None
    checks = {check.name: check for check in found.checks}
    assert (checks["work-issue"].checked, checks["outside-pr"].checked) == (3, 5)
    assert "the whole history up to 2026-11-12T12:00:00Z; no retro issue has closed" in (
        retro.draft(found))


def test_since_narrows_the_window_and_the_rule_checks(checkout):
    """`--since` starts the window at its date: the work issues closed, the landings merged and the
    commits made after it alone; the previous retro is still the last closed one."""
    whole = {check.name: check for check in collected(checkout).checks}
    found = collected(checkout, since=retro.since_of("2026-11-03"))

    assert found.window == retro.Window(30, "2026-11-03T00:00:00Z", None, "2026-11-12T12:00:00Z",
                                        retro.GIVEN)
    assert [item.number for item in found.issues] == [12, 13, 14]
    checks = {check.name: check for check in found.checks}
    assert {name: (whole[name].checked, checks[name].checked) for name in checks} == {
        "work-issue": (3, 2), "check": (3, 2), "outside-pr": (4, 3), "field-report": (3, 2)}
    assert checks["work-issue"].broken == whole["work-issue"].broken  # #25 merged 3 Nov
    assert found.previous["retro"] == 5
    assert "after 2026-11-03T00:00:00Z, as --since gives" in retro.draft(found)

    found = collected(checkout, since=retro.since_of("2026-11-04T11:00:00+00:00"))
    assert [item.number for item in found.issues] == [14]
    assert {check.name: check.checked for check in found.checks} == {
        "work-issue": 0, "check": 0, "outside-pr": 0, "field-report": 1}
    with pytest.raises(work_tickets.QueueError, match="--since 3 Nov: give a date"):
        retro.since_of("3 Nov")


def test_retro_starts_the_window_where_that_retro_closed(checkout):
    given = answers(checkout)
    given["issues.json"].append(issue(4, "docs/retro-20261015", "2026-10-15T00:00:00Z"))
    given["comments-4.json"] = [{"body": posted(4, {"sizes": {"closed": 2}})}]

    found = collected(checkout, given, retro=4)
    assert found.window == retro.Window(30, "2026-10-15T00:00:00Z", 4, "2026-11-12T12:00:00Z",
                                        retro.CLOSED_RETRO)
    assert [item.number for item in found.issues] == [11, 12, 13, 14]
    assert found.previous == {"retro": 4, "sizes": {"closed": 2}, "findings": []}
    with pytest.raises(work_tickets.QueueError, match="--retro 11: #11 is no closed retro issue"):
        collected(checkout, given, retro=11)
    parsed = retro.make_parser().parse_args(["collect", "30", "--retro", "4"])
    assert (parsed.since_retro, parsed.since) == (4, None)
    with pytest.raises(SystemExit):
        retro.make_parser().parse_args(["collect", "30", "--retro", "4", "--since", "2026-11-01"])


def test_the_countdown_counts_the_landings_as_collect_does_from_the_lists(checkout):
    """The countdown of the next retro (se_start.py, the filing check) counts the landings of the
    work since retro #5 started as collect counts them, from the lists alone; a retro started
    since then resets it."""
    door = FakeDoor(answers(checkout))
    found = retro.countdowns(door, REPO, "main", checkout, NOW)
    assert found["retro"].landed == collected(checkout).sizes["landed"] == 2
    assert (found["retro"].since_run, found["retro"].count, found["retro"].due) == (5, 2, True)
    assert found["retro"].reason == "11 days since the last retro with 2 came back (due after 7 days)"
    assert door.reads == ["open-issues.json", "issues.json", "pulls.json"]

    given = answers(checkout)
    given["issues.json"].append(issue(31, "docs/retro-20261105", "2026-11-05T00:00:00Z",
                                      labels=("retro",)))
    found = retro.countdowns(FakeDoor(given), REPO, "main", checkout, NOW)
    assert (found["retro"].since_run, found["retro"].landed, found["retro"].due) == (31, 0, False)


def work(number: int, closed: str | None = None, updated: str = "", created: str = "",
         labels: tuple[str, ...] = ("work",)) -> retro.Issue:
    """A work issue: open, or closed at `closed`."""
    return retro.Issue(number, f"feat/n{number}", list(labels), closed or "",
                       "completed" if closed else "", updated_at=updated or closed or created,
                       created_at=created)


def landing(number: int, merged: str) -> retro.Pull:
    return retro.Pull(100 + number, f"feat/n{number}", f"Fixes #{number}", f"feat/n{number}", "",
                      "main", merged, "")


SETTINGS = {"due_after": 20, "failure_weight": 5, "days": 7}
LAST = retro.Issue(1, "retro-due-20261101", ["retro"], "2026-11-01T12:00:00Z", "completed",
                   created_at="2026-11-01T00:00:00Z")


def countdown(closed, opened=(), pulls=(), now=NOW, settings=SETTINGS) -> retro.Countdown:
    return retro.retro_countdown([LAST, *closed], list(opened), list(pulls), REPO, "main",
                                 settings, now)


def test_twenty_issues_opened_make_no_retro_due_and_twenty_come_back_do():
    """Opening issues counts nothing: a productive session that files 20 is no retro; 20 that
    come back (landed) make one due, 19 do not."""
    opened = [work(n, created="2026-11-11T10:00:00Z") for n in range(10, 30)]
    found = countdown([], opened, now=datetime(2026, 11, 30, tzinfo=timezone.utc))
    assert (found.count, found.due, found.reason) == (0, False, "")

    closed = [work(n, "2026-11-10T00:00:00Z") for n in range(10, 30)]
    pulls = [landing(n, "2026-11-10T00:00:00Z") for n in range(10, 30)]
    found = countdown(closed, pulls=pulls, now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert (found.landed, found.count, found.due) == (20, 20, True)
    assert found.reason == "20 came back since the last retro (due at 20)"
    found = countdown(closed[1:], pulls=pulls, now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert (found.count, found.due) == (19, False)


def test_a_failure_weighs_its_failure_weight_and_an_unlanded_close_nothing():
    """An escalated work issue (an escalation or a refused landing) adds failure_weight, open or
    closed; one closed without a landing adds nothing; four failures make a retro due at 20."""
    failed = [work(n, updated="2026-11-03T00:00:00Z", labels=("work", "escalated"))
              for n in range(10, 14)]
    unlanded = [work(20, "2026-11-03T00:00:00Z")]
    found = countdown(unlanded, failed, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert (found.landed, found.failed, found.count, found.due) == (0, 4, 20, True)
    found = countdown(unlanded, failed[:3], now=datetime(2026, 11, 4, tzinfo=timezone.utc),
                      settings={**SETTINGS, "failure_weight": 6})
    assert (found.count, found.due) == (18, False)


def test_a_retro_is_due_seven_days_after_the_last_started_where_anything_came_back():
    one = ([work(10, "2026-11-02T00:00:00Z")], (), [landing(10, "2026-11-02T00:00:00Z")])
    assert not countdown(*one, now=datetime(2026, 11, 7, tzinfo=timezone.utc)).due
    found = countdown(*one, now=datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert (found.elapsed_days, found.due) == (7, True)
    assert not countdown([], now=datetime(2026, 12, 30, tzinfo=timezone.utc)).due
    assert not countdown(*one, now=datetime(2026, 11, 30, tzinfo=timezone.utc),
                         settings={**SETTINGS, "days": 0}).due


def test_the_counters_reset_when_a_retro_starts_and_a_late_one_makes_none_due_at_once():
    """A retro counts from the newest retro's start (its creation), open or closed: what came back
    before it is its own, so a retro filed late leaves the next countdown at zero. While it is
    open, issues keep coming back and count towards the next."""
    closed = [work(n, "2026-11-10T00:00:00Z") for n in range(10, 40)]
    pulls = [landing(n, "2026-11-10T00:00:00Z") for n in range(10, 40)]
    late = retro.Issue(2, "retro-due-20261120", ["retro"], "", "", created_at="2026-11-20T00:00:00Z")
    now = datetime(2026, 11, 26, tzinfo=timezone.utc)
    assert countdown(closed, pulls=pulls, now=now).due
    found = countdown(closed, [late], pulls, now=now)
    assert (found.since_run, found.count, found.due, found.open) == (2, 0, False, [2])
    after = [work(50, "2026-11-21T00:00:00Z")]
    found = countdown([*closed, *after], [late], [*pulls, landing(50, "2026-11-21T00:00:00Z")],
                      now=now)
    assert (found.count, found.open) == (1, [2])


def test_the_settings_hold_the_thresholds_and_refuse_a_bad_one(tmp_path):
    assert retro.settings(tmp_path, "retro") == {"due_after": 20, "failure_weight": 5, "days": 7}
    assert retro.settings(tmp_path, "overhaul") == {"due_after": 3, "days": 30}
    assert retro.due_after(tmp_path) == retro.DUE_AFTER == 20
    (tmp_path / "se.toml").write_text("[retro]\ndue_after = 4\nfailure_weight = 2\ndays = 0\n"
                                      "[overhaul]\ndue_after = 0\ndays = 14\n", encoding="utf-8")
    assert retro.settings(tmp_path, "retro") == {"due_after": 4, "failure_weight": 2, "days": 0}
    assert retro.settings(tmp_path, "overhaul") == {"due_after": 0, "days": 14}
    (tmp_path / "se.toml").write_text("[retro]\ndue_after = 0\n", encoding="utf-8")
    with pytest.raises(retro.QueueError, match="retro.due_after .* positive whole number"):
        retro.due_after(tmp_path)
    (tmp_path / "se.toml").write_text("[retro]\nfailure_weight = -1\n", encoding="utf-8")
    with pytest.raises(retro.QueueError, match="retro.failure_weight .* 0 for off"):
        retro.settings(tmp_path, "retro")


def test_due_prints_each_countdown_and_without_gh_its_plan(checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    assert retro.main(["due", "--repo", REPO, "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the retro and overhaul countdowns" in out
    assert "list_issues" in out and "list_pull_requests" in out
    answers_dir = tmp_path / "answers"
    answers_dir.mkdir()
    given = answers(checkout)
    for name in ("issues.json", "open-issues.json", "pulls.json"):
        (answers_dir / name).write_text(json.dumps(given[name]), encoding="utf-8")
    for item in given["issues.json"]:
        (answers_dir / f"issue-{item['number']}.json").write_text(json.dumps(item), encoding="utf-8")
    assert retro.main(["due", "--answers", str(answers_dir), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("retro: 2 (2 landed, 0 failed) since #5 started ")
    assert "days since the last retro with 2 came back (due after 7 days)" in lines[0]
    assert lines[1].startswith("overhaul: 1 retros closed in the whole history")


def test_the_countdown_lines_are_the_retro_due_snippet_as_due_printed_them():
    """templates/retro-due.md shapes `retro due`: each state of a countdown keeps its line."""
    def countdown(kind, **changes):
        return retro.Countdown(**{"kind": kind, "since": "2026-11-01", "since_run": 30, "landed": 10,
                                  "failed": 2, "count": 12, "due_after": 10, "days": 14,
                                  "elapsed_days": 23, "due": False, "reason": "", "open": [],
                                  **changes})
    assert retro.countdown_lines({"retro": countdown("retro", due=True, reason="12 came back"),
                                  "overhaul": countdown("overhaul", count=2, since=None, since_run=None)}) == [
        "retro: 12 (10 landed, 2 failed) since #30 started 2026-11-01, 23 days; due: 12 came back",
        "overhaul: 2 retros closed in the whole history, 23 days; not due"]
    assert retro.countdown_lines({"retro": countdown("retro", open=[31, 32]),
                                  "overhaul": countdown("overhaul", count=0)}) == [
        "retro: 12 (10 landed, 2 failed) since #30 started 2026-11-01, 23 days; open: #31, #32",
        "overhaul: 0 retros closed since #30 started 2026-11-01, 23 days; not due"]
    lines = retro.countdown_lines({"retro": countdown("retro"), "overhaul": countdown("overhaul")})
    assert retro.sibling("interfaces").read(retro.DUE_TEMPLATE, "\n".join(lines))["overhaul_days"] == "23"


def test_the_draft_ends_in_the_block_that_parses_back(checkout):
    found = collected(checkout)
    text = retro.draft(found)

    assert "# Retro draft for #30\n" in text
    assert retro.templates().marked_version(retro.retro_template(), text) == retro.retro_template().version
    assert "| landed | 2 | 5 |" in text
    assert "| #11 feat/a | 1 | 1 | 35.4 s | #22 |" in text
    assert "- **check**: " in text and "broken 1 of 3\n  - #23: check failure" in text
    assert "#### What goes badly, each with its moment in the log?\n\n- #11: a slow fixture" in text
    assert ("### Planning misses\n\nWhat the field reports did not deliver:\n\n- #11: The live run "
            "against GitHub") in text
    assert text.rstrip().endswith("```")
    block = retro.read_block(text)
    assert block == json.loads(json.dumps(found.data()))
    assert block["version"] == retro.BLOCK_VERSION and block["sizes"]["landed"] == 2
    assert {check["name"]: check["kept"] for check in block["rule_checks"]} == {
        "work-issue": False, "check": False, "outside-pr": False, "field-report": False}


def run_line(start: str, wall: float, issue: int) -> dict:
    return {"command": "work_tickets.py integrate", "start": start, "wall_seconds": wall,
            "gh_calls": 3, "gh_refusals": 0, "gh_wait_seconds": 0.0, "exit_code": 0, "issue": issue}


def test_collect_reads_metrics_back_from_the_landings_and_counts_a_run_once(
        checkout, tmp_path, monkeypatch):
    """A cloud integrator's line survives only in its landing's description (#23's); a run the
    local file holds too (#21's) counts once, by its finished local line; a local line before the
    window is not the window's."""
    given = answers(checkout)
    landed_a = run_line("2026-11-02T09:00:00Z", 40.0, 11)
    landed_b = run_line("2026-11-03T09:00:00Z", 50.0, 12)
    for item, line in zip((given["pulls.json"][0], given["pulls.json"][2]), (landed_a, landed_b)):
        item["body"] = item["body"] + "\n" + work_tickets.metrics.text(line) + "\n"
    finished_a = {**landed_a, "wall_seconds": 95.0}
    local_only = {**run_line("2026-11-05T09:00:00Z", 10.0, 0), "command": "work_tickets.py sync"}
    before = run_line("2026-10-20T09:00:00Z", 70.0, 3)
    local = tmp_path / "metrics.jsonl"
    local.write_text("".join(json.dumps(line) + "\n" for line in (before, finished_a, local_only)),
                     encoding="utf-8")
    monkeypatch.setenv("SE_METRICS", str(local))

    found = collected(checkout, given)

    assert found.runs == [finished_a, landed_b, local_only]
    assert found.data()["metrics"] == {"landings": 2, "local": 2, "runs": 3}
    text = retro.draft(found)
    assert f"3 runs: 2 from the landing pull requests, 2 from {local}, each run once." in text
    assert "work_tickets.py integrate: 2 runs, 145.0 s wall, 6 GitHub calls" in text


def test_a_block_that_is_not_json_is_refused():
    assert retro.read_block("No block here.") is None
    with pytest.raises(work_tickets.QueueError, match="is not JSON"):
        retro.read_block(f"{retro.BLOCK_MARKER}\n```yaml\nsizes: [\n```\n")


def test_without_gh_the_plans_are_printed_and_the_answers_read(checkout, tmp_path, monkeypatch,
                                                                capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    directory, out = tmp_path / "answers", tmp_path / "retro-30.md"
    directory.mkdir()
    command = ["collect", "30", "--answers", str(directory), "--out", str(out), "--repo", REPO,
               "--worktree", str(checkout)]
    given = hosts_answers(answers(checkout))

    assert retro.main(command) == 0
    first = capsys.readouterr().out
    assert "GitHub plan: the window of retro #30" in first
    assert '1. list_issues {"owner": "owner", "perPage": 100, "repo": "repo", "state": "CLOSED"}' in first
    assert "2. list_pull_requests" in first and "issue_read" not in first
    assert f"Then: retro.py collect 30 --answers {directory} --out {out}" in first
    for name in ("issues.json", "pulls.json"):
        (directory / name).write_text(json.dumps(given[name]), encoding="utf-8")

    assert retro.main(command) == 0
    retros = capsys.readouterr().out
    assert '1. issue_read {"issue_number": 5, "method": "get"' in retros and "#11" not in retros
    (directory / "issue-5.json").write_text(json.dumps(given["issue-5.json"]), encoding="utf-8")

    assert retro.main(command) == 0
    window = capsys.readouterr().out
    assert '"issue_number": 11, "method": "get"' in window
    assert '"issue_number": 3,' not in window  # not updated since retro #5 closed
    for name in ("issue-11.json", "issue-12.json", "issue-13.json", "issue-14.json"):
        (directory / name).write_text(json.dumps(given[name]), encoding="utf-8")

    assert retro.main(command) == 0
    second = capsys.readouterr().out
    assert '"issue_number": 11, "method": "get_comments"' in second
    assert '"method": "get_check_runs", "owner": "owner", "pullNumber": 23' in second
    assert f"Save the answer as JSON to {directory / 'checks-23.json'}" in second
    assert not out.exists()
    for name, answer in given.items():
        (directory / name).write_text(json.dumps(answer), encoding="utf-8")

    assert retro.main(command) == 0
    assert "Wrote the retro draft of #30" in capsys.readouterr().out
    assert retro.read_block(out.read_text(encoding="utf-8"))["sizes"]["closed"] == 4


def hosts_answers(given: dict[str, object]) -> dict[str, object]:
    """`given` as the host's GitHub tools answer: list_issues names no close time or reason
    and its labels as strings (issue_read get names both), list_pull_requests no merge commit."""
    shaped = dict(given)
    listed = []
    for item in given["issues.json"]:
        updated = "2026-10-01T00:00:00Z" if item["number"] == 3 else item["closed_at"]
        listed.append({"number": item["number"], "title": item["title"], "state": "CLOSED",
                       "labels": [label["name"] for label in item["labels"]],
                       "updated_at": updated})
        shaped[f"issue-{item['number']}.json"] = item
    shaped["issues.json"] = [{"issues": listed, "pageInfo": {"hasNextPage": False}}]
    shaped["pulls.json"] = [{key: value for key, value in item.items()
                             if key != "merge_commit_sha"} for item in given["pulls.json"]]
    return shaped


def test_without_merge_commits_a_squash_matches_by_its_title_and_merge_time(checkout):
    given = hosts_answers(answers(checkout))
    checks = {check.name: check for check in collected(checkout, given).checks}
    assert checks["outside-pr"].checked == 4 and [item["what"] for item in
                                                   checks["outside-pr"].broken] == [
        "Hotfix pushed by hand"]
    for item in given["pulls.json"]:
        item["merged_at"] = item["merged_at"] and "2026-11-05T00:00:00Z"
    checks = {check.name: check for check in collected(checkout, given).checks}
    assert len(checks["outside-pr"].broken) == 4


def test_the_gh_door_reads_every_page_and_leaves_out_pull_requests(monkeypatch):
    calls = []

    class FakeGitHub:
        def __init__(self, root, repo):
            self.repo = repo

        def api(self, path):
            calls.append(path)
            if path.endswith("page=1"):
                return [{"number": n} for n in range(100)]
            return [{"number": 100}, {"number": 101, "pull_request": {}}]

    monkeypatch.setattr(work_tickets, "GitHub", FakeGitHub)
    monkeypatch.setattr(retro.GhDoor, "PAGE", 100)
    door = retro.GhDoor(Path("."), REPO, REPO)

    assert [item["number"] for item in door.closed_issues()][-2:] == [99, 100]
    assert calls == ["issues?state=closed&per_page=100&page=1",
                     "issues?state=closed&per_page=100&page=2"]


def run_item(number: int, title: str, created: str, closed: str = "", updated: str = "",
             labels: tuple[str, ...] = ("work",), reason: str = "completed") -> dict:
    """An issue as the REST API lists it: closed at `closed`, else open."""
    return {"number": number, "title": title, "state": "closed" if closed else "open",
            "created_at": created, "closed_at": closed or None,
            "updated_at": updated or closed or created, "state_reason": reason if closed else None,
            "labels": [{"name": name} for name in labels], "body": ""}


def run_pull(number: int, issue: int, merged: str, updated: str = "") -> dict:
    return {"number": number, "title": f"feat/n{issue}", "body": f"Fixes #{issue}",
            "base": {"ref": "main"}, "head": {"ref": f"feat/n{issue}", "sha": f"{number:040d}"},
            "merged_at": merged or None, "updated_at": updated or merged, "merge_commit_sha": None}


def run_history() -> dict[str, list[dict]]:
    """Two retros (#1, #4) and an overhaul (#2) between them, and a retro named by its title
    alone (#14) after the overhaul. #6 closed after retro #4 started but its landing merged just
    before; #9 closed long ago and was commented on since; #8
    escalated, #10 closed as not planned; #3, #5 and #11 lie before the cut-off."""
    return {
        "closed": [
            run_item(1, "docs/retro-20261001", "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z",
                     labels=("retro",)),
            run_item(2, "overhaul-20261010", "2026-10-10T00:00:00Z", "2026-10-12T00:00:00Z",
                     labels=("discovery",)),
            run_item(3, "feat/n3", "2026-10-03T00:00:00Z", "2026-10-05T00:00:00Z"),
            run_item(4, "docs/retro-20261101", "2026-11-01T00:00:00Z", "2026-11-03T00:00:00Z",
                     labels=("retro",)),
            run_item(5, "feat/n5", "2026-10-15T00:00:00Z", "2026-10-20T00:00:00Z"),
            run_item(6, "feat/n6", "2026-10-30T00:00:00Z", "2026-11-01T01:00:00Z"),
            run_item(7, "feat/n7", "2026-11-04T00:00:00Z", "2026-11-05T00:00:00Z"),
            run_item(8, "feat/n8", "2026-10-25T00:00:00Z", "2026-11-06T00:00:00Z",
                     labels=("work", "escalated")),
            run_item(9, "feat/n9", "2026-08-20T00:00:00Z", "2026-09-01T00:00:00Z",
                     "2026-11-07T00:00:00Z"),
            run_item(10, "feat/n10", "2026-11-02T00:00:00Z", "2026-11-08T00:00:00Z",
                     reason="not_planned"),
            run_item(11, "Not a work issue", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
                     labels=()),
            run_item(14, "docs/retro-20261018", "2026-10-18T00:00:00Z", "2026-10-19T00:00:00Z",
                     labels=()),
        ],
        "open": [run_item(12, "feat/n12", "2026-11-02T00:00:00Z", updated="2026-11-09T00:00:00Z",
                          labels=("work", "escalated")),
                 run_item(13, "feat/n13", "2026-11-09T00:00:00Z")],
        "pulls": [run_pull(103, 3, "2026-10-05T00:00:00Z"),
                  run_pull(105, 5, "2026-10-20T00:00:00Z"),
                  run_pull(106, 6, "2026-10-31T23:00:00Z"),
                  run_pull(107, 7, "2026-11-05T00:00:00Z"),
                  run_pull(108, 9, "2026-09-01T00:00:00Z"),
                  run_pull(199, 11, "", "2026-07-01T00:00:00Z")],
    }


def newest_first(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


class WholeDoor:
    """A door with no cut-off read over `history`: every list whole, as FileDoor reads it."""

    def __init__(self, history: dict[str, list[dict]]) -> None:
        self.history, self.missing, self.read = history, [], {"issues": [], "pulls": []}

    def closed_issues(self):
        self.read["issues"] += [item["number"] for item in self.history["closed"]]
        return list(self.history["closed"])

    def open_issues(self):
        return list(self.history["open"])

    def pulls(self):
        self.read["pulls"] += [item["number"] for item in self.history["pulls"]]
        return list(self.history["pulls"])

    def issue(self, number):
        return next(item for item in self.history["closed"] if item["number"] == number)


class CutOffDoor(WholeDoor):
    """The same history with the cut-off reads (retro.CUT_OFF_READS), as GitHub answers them:
    newest update first and by label; records what it handed over."""

    def until(self, kind: str, items: list[dict], stop) -> list[dict]:
        found = []
        for item in newest_first(items):
            if stop(item):
                break
            self.read[kind].append(item["number"])
            found.append(item)
        return found

    def closed_issues_until(self, stop):
        return self.until("issues", self.history["closed"], stop)

    def closed_issues_labelled(self, label):
        return [item for item in self.history["closed"] if label in retro.label_names(item)]

    def pulls_until(self, stop):
        return self.until("pulls", self.history["pulls"], stop)


def overhaul_off(root: Path) -> None:
    (root / "se.toml").write_text("[overhaul]\ndue_after = 0\ndays = 0\n", encoding="utf-8")


def test_the_cut_off_read_gives_the_countdowns_of_the_whole_read(tmp_path):
    """On one history with two retros and an overhaul, the cut-off read stops the closed issues
    at the older of the newest retro's and overhaul's starts and the pull requests at the newest
    retro's, read on past it for #6's landing, merged just before retro #4 started: the
    countdowns are those of the whole read. With the overhaul countdown off, the issues stop at
    the retro's start, and the retro countdown is the whole read's; the overhaul's, off, counts
    the retros the label read finds (docs/fleet.md "Retro due")."""
    whole, cut = WholeDoor(run_history()), CutOffDoor(run_history())
    expected = retro.countdowns(whole, REPO, "main", tmp_path, NOW)
    found = retro.countdowns(cut, REPO, "main", tmp_path, NOW)
    assert found == expected
    assert (found["retro"].since_run, found["retro"].landed, found["retro"].failed) == (4, 2, 2)
    assert (found["overhaul"].since_run, found["overhaul"].count) == (2, 2)
    assert cut.read == {"issues": [10, 9, 8, 7, 4, 6, 5, 14, 2], "pulls": [107, 106]}
    assert len(whole.read["issues"]) == 12 and len(whole.read["pulls"]) == 6

    overhaul_off(tmp_path)
    cut = CutOffDoor(run_history())
    found = retro.countdowns(cut, REPO, "main", tmp_path, NOW)
    expected = retro.countdowns(WholeDoor(run_history()), REPO, "main", tmp_path, NOW)
    assert found["retro"] == expected["retro"]
    assert (found["overhaul"].due, expected["overhaul"].due) == (False, False)
    assert (found["overhaul"].count, expected["overhaul"].count) == (1, 2)
    assert cut.read == {"issues": [10, 9, 8, 7, 4, 6], "pulls": [107, 106]}


def test_with_no_run_yet_the_cut_off_read_reads_the_whole_history(tmp_path):
    """Where no retro exists, nothing bounds what can count: every closed issue and pull request
    is read, with the countdowns of the whole read. Where retros exist but no overhaul, the read
    stops at the newest retro's start and the overhaul countdown counts the retros found by their
    label: the whole read's, as long as each older retro carries it."""
    history = run_history()
    history["closed"] = [item for item in history["closed"] if item["number"] not in (1, 2, 4, 14)]
    cut = CutOffDoor(history)
    found = retro.countdowns(cut, REPO, "main", tmp_path, NOW)
    assert found == retro.countdowns(WholeDoor(history), REPO, "main", tmp_path, NOW)
    assert found["retro"].since_run is None and found["overhaul"].since_run is None
    assert sorted(cut.read["issues"]) == [3, 5, 6, 7, 8, 9, 10, 11]
    assert sorted(cut.read["pulls"]) == [103, 105, 106, 107, 108, 199]

    history = run_history()
    history["closed"] = [item for item in history["closed"] if item["number"] != 2]
    cut = CutOffDoor(history)
    found = retro.countdowns(cut, REPO, "main", tmp_path, NOW)
    expected = retro.countdowns(WholeDoor(history), REPO, "main", tmp_path, NOW)
    assert found["retro"] == expected["retro"]
    assert cut.read["issues"] == [10, 9, 8, 7, 4, 6]
    assert (found["overhaul"].count, expected["overhaul"].count) == (2, 3)

    next(item for item in history["closed"] if item["number"] == 14)["labels"] = [{"name": "retro"}]
    found = retro.countdowns(CutOffDoor(history), REPO, "main", tmp_path, NOW)
    assert found == retro.countdowns(WholeDoor(history), REPO, "main", tmp_path, NOW)
    assert found["overhaul"].count == 3

class FakeRelay:
    """kern's relay door as the host's GitHub tools answer over `history`: list_issues in pages
    of `size` with a cursor, newest update first with orderBy, by label, without close times
    (the tools name none) and labels as names; list_pull_requests by page; issue_read whole."""

    def __init__(self, history: dict[str, list[dict]], size: int = 100) -> None:
        self.history, self.size, self.calls = history, size, []

    def ask(self, tool, arguments, note="", wait=""):
        self.calls.append((tool, dict(arguments)))
        if tool == "issue_read":
            return next(item for item in self.history["closed"]
                        if item["number"] == arguments["issue_number"])
        if tool == "list_pull_requests":
            items = self.history["pulls"]
            if arguments.get("sort") == "updated":
                items = newest_first(items)
            start = (arguments["page"] - 1) * arguments["perPage"]
            return items[start:start + arguments["perPage"]]
        items = self.history["closed" if arguments["state"] == "CLOSED" else "open"]
        if arguments.get("orderBy") == "UPDATED_AT":
            assert arguments["direction"] == "DESC"
            items = newest_first(items)
        if arguments.get("labels"):
            items = [item for item in items if set(arguments["labels"]) <= set(retro.label_names(item))]
        start = int(arguments.get("after") or 0)
        page = [{**{key: value for key, value in item.items() if key != "closed_at"},
                 "labels": retro.label_names(item)} for item in items[start:start + self.size]]
        more = start + self.size < len(items)
        return {"issues": page, "pageInfo": {"hasNextPage": more,
                                             "endCursor": str(start + self.size) if more else ""}}

    def issues(self, state):
        found, after = [], ""
        while True:
            data = self.ask("list_issues", {"state": state, "perPage": 100,
                                            **({"after": after} if after else {})})
            found += data["issues"]
            after = data["pageInfo"]["endCursor"]
            if not after:
                return found


def test_the_relay_and_gh_doors_read_cut_off_and_the_answer_files_whole(tmp_path, monkeypatch):
    """kern's relay door (ToolDoor) reads newest update first and by label, page by page up to
    where the countdowns stop it, and reads each close time its list does not name: the
    countdowns of the whole read. gh's door (GhDoor) asks the REST API sorted the same and
    stops within a page. The answer files (FileDoor) have no cut-off read and are read whole."""
    relay = FakeRelay(run_history(), size=3)
    found = retro.countdowns(retro.ToolDoor(relay), REPO, "main", tmp_path, NOW)
    assert found == retro.countdowns(WholeDoor(run_history()), REPO, "main", tmp_path, NOW)
    lists = [arguments for tool, arguments in relay.calls if tool == "list_issues"
             and arguments["state"] == "CLOSED"]
    assert [item.get("labels") for item in lists if "labels" in item] == [["retro"], ["discovery"]]
    ordered = [item for item in lists if item.get("orderBy") == "UPDATED_AT"]
    assert [item.get("after") for item in ordered] == [None, "3", "6", "9"]
    assert [arguments for tool, arguments in relay.calls if tool == "list_pull_requests"] == [
        {"state": "closed", "sort": "updated", "direction": "desc", "perPage": 100, "page": 1}]

    calls = []
    history = run_history()

    class FakeGitHub:
        def __init__(self, root, repo):
            pass

        def api(self, path):
            calls.append(path)
            if path.startswith("pulls?"):
                return newest_first(history["pulls"])
            if "labels=" in path:
                label = path.split("labels=")[1].split("&")[0]
                return [item for item in history["closed"] if label in retro.label_names(item)]
            if "state=open" in path:
                return history["open"]
            return newest_first(history["closed"]) + [{"number": 99, "pull_request": {},
                                                       "updated_at": "2026-01-01T00:00:00Z"}]

    monkeypatch.setattr(work_tickets, "GitHub", FakeGitHub)
    found = retro.countdowns(retro.GhDoor(tmp_path, REPO, REPO), REPO, "main", tmp_path, NOW)
    assert found == retro.countdowns(WholeDoor(run_history()), REPO, "main", tmp_path, NOW)
    assert "issues?state=closed&sort=updated&direction=desc&per_page=100&page=1" in calls
    assert "pulls?state=closed&sort=updated&direction=desc&per_page=100&page=1" in calls
    assert "issues?state=closed&labels=retro&per_page=100&page=1" in calls

    assert not any(hasattr(retro.FileDoor, name) for name in retro.CUT_OFF_READS)
    assert all(hasattr(door, name) for door in (retro.GhDoor, retro.ToolDoor)
               for name in retro.CUT_OFF_READS)


LOST_REPORTS = {"name": "Lost reports", "cause": "a landing need not name a field report",
                "fix": "`integrate` refuses a landing without one",
                "home": "scripts/work_tickets.py", "home_kind": "refusal"}


def judged_draft(checkout: Path, **changes: object) -> str:
    """The collect's draft of retro #30 with its block judged: two findings of one class, the
    second controversial; `changes` replace the judgment's lists."""
    data = collected(checkout).data()
    data.update({
        "classes": [LOST_REPORTS],
        "findings": [
            {"title": "Refuse a landing whose work issue has no field report",
             "body": "#14 closed without one.", "class": "Lost reports",
             "home": "scripts/work_tickets.py", "controversial": False, "check": "field-report"},
            {"title": "Make the field report a rule of the rule book",
             "body": "A rule, not a habit.", "class": "Lost reports",
             "home": retro.RULE_BOOK, "controversial": True, "why": "it changes a rule"}],
        "went_well": ["The fake door kept the tests fast."]})
    data.update(changes)
    text = fill_steps(retro.draft(collected(checkout)))
    return text[:text.rfind(retro.BLOCK_MARKER)] + retro.BLOCK_MARKER + "\n" + retro.review.fenced(
        json.dumps(data, indent=2), "yaml") + "\n"


def finding(**changes: object) -> dict:
    return {"title": "Refuse a landing whose work issue has no field report", "body": "#14.",
            "class": "Lost reports", "home": "scripts/work_tickets.py", "controversial": False,
            **changes}


@pytest.mark.parametrize(("changes", "refusal"), [
    ({"findings": [finding(title="Refuse lost reports")]},
     'finding 1 ("Refuse lost reports") needs a title of 5 words or more'),
    ({"findings": [finding(body="")]}, "has no body"),
    ({"findings": [finding(**{"class": ""})]}, "has no class"),
    ({"findings": [finding(**{"class": "Elsewhere"})]},
     'names the class "Elsewhere", which `classes` does not'),
    ({"findings": [finding(home="")]}, "has no home: the file it changes"),
    ({"classes": [{**LOST_REPORTS, "fix": " "}], "findings": [finding()]},
     'class "Lost reports" has no fix'),
    ({"classes": [{**LOST_REPORTS, "cause": ""}], "findings": [finding()]},
     'class "Lost reports" has no cause'),
    ({"classes": [{**LOST_REPORTS, "home": ""}], "findings": [finding()]},
     'class "Lost reports" has no home'),
    ({"classes": [{**LOST_REPORTS, "home_kind": "wish"}], "findings": [finding()]},
     'class "Lost reports": home_kind is the first of the home order that holds: check, refusal'),
    ({"findings": [finding(controversial=True)]}, "is controversial without a why"),
    ({"findings": [finding(home=retro.RULE_BOOK)]}, "changes a rule (its home is the rule book)"),
    ({"findings": [finding(check="speed")]}, 'names the check "speed", which is no rule check'),
    ({"findings": [finding(issue=40)]}, "has the unknown field issue"),
    ({"went_well": []}, "`went_well` is empty: record what went well"),
])
def test_file_refuses_an_incomplete_judgment_and_writes_nothing(checkout, tmp_path, monkeypatch,
                                                                changes, refusal):
    writes = []
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "run_plan", lambda plan, actions: writes.append(plan))
    draft = tmp_path / "draft.md"
    draft.write_text(judged_draft(checkout, **changes), encoding="utf-8")

    with pytest.raises(work_tickets.QueueError) as raised:
        retro.run_file(retro.make_parser().parse_args(["file", "30", "--draft", str(draft), "--repo",
                                                  REPO, "--worktree", str(checkout)]))
    assert "The judgment of retro #30 is not complete, so nothing was written" in str(raised.value)
    assert refusal in str(raised.value)
    assert writes == []


def built_deck(checkout: Path, tmp_path: Path, monkeypatch, text: str, *extra: str) -> tuple[int, dict]:
    """`retro.py deck 30` on the draft `text`, retro_deck's build replaced by a recorder (the real build
    is tests/test_retro_deck.py's): its exit code and what it was asked to build."""
    import retro_deck
    asked: dict = {}

    def build(written, destination, host=None, answers=None):
        asked.update(written=written, destination=destination, host=host, answers=answers)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("<html></html>", encoding="utf-8")
        return 0

    monkeypatch.setattr(retro_deck, "build", build)
    draft = tmp_path / "draft.md"
    draft.write_text(text, encoding="utf-8")
    code = retro.main(["deck", "30", "--draft", str(draft), "--destination", str(tmp_path / "out" / "retro-30.html"),
                       "--worktree", str(checkout), *extra])
    return code, asked


def test_the_deck_holds_every_step_then_finding_decisions_and_anything_else(checkout):
    """The retro's deck carries each report step once, its finding decisions, then one final default."""
    text = judged_draft(checkout)
    block = retro.judged(text, 30)
    steps, decisions = retro.deck_parts(block, text)
    assert [heading for heading, _ in steps] == ["Collect", "Table of what happened", "The standing questions",
                                                 "Classes and homes"]
    body = dict(steps)
    collect = body["Collect"]
    assert "## Sizes" in collect and "## Rule checks" in collect
    assert retro.LANDED_SECTION not in collect and retro.ANSWERS_SECTION not in collect
    table = body["Table of what happened"]
    assert [line for line in table.split("\n") if line.startswith("|---")] == ["|---|---|---|---|"]
    assert "| chapter | from | to | steps |" in table
    assert retro.STEP_TABLE not in table
    matrix = body["The standing questions"]
    assert matrix.startswith("| question |") and matrix.count("| question |") == 1
    assert ("\n## Answers to the standing questions\n\n### What came back from real use since the last retro?\n\n"
            "None.") in matrix
    classes = body["Classes and homes"]
    assert "### Lost reports (2)\n\nCause: a landing need not name a field report" in classes
    assert "Home: refusal (home 2 of 8), `scripts/work_tickets.py`" in classes and "### What went well" in classes
    assert ("Findings, each a decision at the end: 1. Refuse a landing whose work issue has no field report; "
            "2. Make the field report a rule of the rule book.") in classes
    assert "#14 closed without one." not in classes and "A rule, not a habit." not in classes
    assert [heading for heading, _ in decisions] == [
        "1. Refuse a landing whose work issue has no field report",
        "2. Make the field report a rule of the rule book",
        "Anything else?"]
    work, decision, anything_else = (text for _, text in decisions)
    # Each opens with its current situation, the finding as the judge wrote it, and asks last (SE#1826, 10).
    assert work.startswith("#14 closed without one.\n\nClass: Lost reports, its cause and fix under Classes and homes.")
    assert work.endswith("Home: `scripts/work_tickets.py`; check `field-report`.\n\n**Work, for your go**: Bless "
                         "sends it to SE, which bundles it into a work issue.")
    assert decision.startswith("A rule, not a habit.") and decision.endswith("**Decision, for your decision**: it changes a rule")
    assert "Cause:" not in decision
    assert anything_else == "Nothing else"


def test_a_retro_without_findings_still_ends_with_anything_else(checkout):
    text = judged_draft(checkout)
    block = retro.read_block(text)
    block["findings"] = []
    block["classes"] = []
    _, decisions = retro.deck_parts(block, text)
    assert decisions == [("Anything else?", "Nothing else")]


def test_deck_builds_the_one_report_from_the_judged_draft_and_never_waits(checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "repository_name", lambda _root: "example")
    code, asked = built_deck(checkout, tmp_path, monkeypatch, judged_draft(checkout), "--host", "copilot")
    assert code == 0
    assert asked["host"] == "copilot" and asked["answers"] is None
    template = templates.own("retro-deck")
    fields = templates.parse(template, asked["written"]).fields
    assert fields["title"] == "example: Retro #30" and fields["subtitle"] == "Retro report"
    assert [finding.fix for finding in templates.check(template, templates.parse(template, asked["written"]))
            if finding.severity == templates.REFUSE] == []
    assert [path.name for path in (tmp_path / "out").iterdir()] == ["retro-30.html"]
    out = capsys.readouterr().out
    assert "the report is the deck" in out and "a title page, 4 steps and 3 decision chapter(s)" in out


def test_deck_with_the_answers_builds_the_record(checkout, tmp_path, monkeypatch, capsys):
    answers = tmp_path / "answers.json"
    answers.write_text('{"verdicts": []}', encoding="utf-8")
    code, asked = built_deck(checkout, tmp_path, monkeypatch, judged_draft(checkout), "--answers", str(answers))
    assert code == 0 and asked["answers"] == answers
    assert "the person's answers recorded" in capsys.readouterr().out


def test_deck_refuses_an_incomplete_judgment_or_an_open_step_and_builds_nothing(checkout, tmp_path, monkeypatch,
                                                                               capsys):
    code, asked = built_deck(checkout, tmp_path, monkeypatch, judged_draft(checkout, went_well=[]))
    assert (code, asked) == (1, {})
    assert "The judgment of retro #30 is not complete" in capsys.readouterr().err
    text = re.sub(r"(## 2\. Table of what happened\n\n).*?(?=\n## 3\. The standing questions)",
                  r"\1", judged_draft(checkout), flags=re.DOTALL)
    code, asked = built_deck(checkout, tmp_path, monkeypatch, text)
    assert (code, asked) == (1, {})
    assert "leaves a step of the retro template" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_file_refuses_another_retros_draft_and_a_draft_without_its_block(checkout):
    with pytest.raises(work_tickets.QueueError, match="The draft is retro #30's, not #31's"):
        retro.judged(judged_draft(checkout), 31)
    with pytest.raises(work_tickets.QueueError, match="The draft has no"):
        retro.judged("# Retro draft for #30\n", 30)


def test_a_finding_on_a_recurred_check_is_controversial(checkout):
    draft = judged_draft(checkout)
    block = retro.read_block(draft)
    block["previous"]["findings"] = [{"finding": 1, "check": "field-report", "recurred": True}]
    text = draft[:draft.rfind(retro.BLOCK_MARKER)] + retro.BLOCK_MARKER + "\n```yaml\n" + \
        json.dumps(block) + "\n```\n"
    with pytest.raises(work_tickets.QueueError, match="recurred after the previous retro's fix"):
        retro.judged(text, 30)


class FakeTracker:
    """The issue writes of the gh door, recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def actions(self, root, repo):
        return {name: (lambda arguments, _, name=name: self.calls.append((name, arguments)))
                for name in ("comment_issue", "close_issue", "add_label", "remove_label")}


@pytest.fixture
def blessing(checkout, monkeypatch):
    class Tracker:
        missing = []

        def __init__(self):
            self.given = []
            self.closed = False
            self.calls = []
            self.fail_after = None
            self.seconds = 0.0
            self.gate_open_at_bless = False

        def issue(self, number):
            self.seconds += 0.2
            if number == 30:
                return {"number": 30, "title": "retro-due-20261126", "labels": ["retro"],
                        "created_at": "2026-11-26T09:00:00Z",
                        "closed_at": "2026-11-26T09:01:00Z" if self.closed else "",
                        "state": "closed" if self.closed else "open", "state_reason": "completed"}
            return {"number": number, "state": "open", "labels": ["work"],
                    "body": "retro #30 finding 1"}

        def comments(self, number):
            self.seconds += 0.2
            return self.given

        def open_issues(self):
            return [] if self.closed else [self.issue(30)]

        def closed_issues(self):
            return [self.issue(30)] if self.closed else []

        def pulls(self):
            return []

        def actions(self, root, tracker, door):
            def write(arguments, detail, name):
                self.seconds += 2
                self.calls.append((name, arguments))
                if name == "comment_issue":
                    self.given.append({"body": arguments["body"]})
                    if retro.BLESSED_DRAFT.search(arguments["body"]):
                        work_tickets.filing_check(root, REPO, "file", self,
                                                 datetime(2026, 11, 26, 9, 1, tzinfo=timezone.utc))
                        self.gate_open_at_bless = not self.closed
                else:
                    self.closed = True
                if self.fail_after == len(self.calls):
                    self.fail_after = None
                    raise work_tickets.QueueError("GitHub response lost after write")

            return {name: (lambda arguments, detail, name=name: write(arguments, detail, name))
                    for name in ("comment_issue", "close_issue")}

    tracker = Tracker()
    monkeypatch.setattr(work_tickets, "filing_door", lambda root, repo: tracker)
    monkeypatch.setattr(retro, "issue_actions", tracker.actions)
    monkeypatch.setattr(retro.time, "monotonic", lambda: tracker.seconds)
    return tracker


@pytest.mark.parametrize("old_form", [False, True])
def test_bless_goes_from_answered_draft_to_closed_with_gate_open_in_one_call(
        checkout, tmp_path, monkeypatch, blessing, old_form, capsys):
    text = judged_draft(checkout)
    if old_form:
        text = retro.templates().INPUTS_PATTERN.sub("", text)
        text = re.sub(r"^## ([1-5])\.", lambda match: f"## {int(match[1]) + 1}.",
                      text, flags=re.MULTILINE)
        text = text.replace("## 2. Collect", "## 1. Field feedback\n\n"
                            "<!-- field_feedback: Answer. -->\n\nRetros take too long.\n\n"
                            "## 2. Collect", 1)
    draft = tmp_path / "answered.md"
    draft.write_text(text, encoding="utf-8")
    before = draft.read_bytes()
    monkeypatch.setattr(work_tickets, "integration_ref",
                        lambda root: pytest.fail("bless must not need a landed doc or sync"))
    assert retro.main(["bless", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    assert blessing.seconds < 60
    assert blessing.closed and blessing.gate_open_at_bless
    assert retro.filing_state(blessing.given).phase == "blessed"
    assert draft.read_bytes() == before
    block = retro.posted_block([item["body"] for item in blessing.given], 30,
                              lambda sha, path: pytest.fail("no landed doc needed"))
    assert len(block["findings"]) == 2
    for finding in (None, retro.FindingRef("30:1")):
        work_tickets.filing_check(checkout, REPO, "file", blessing,
                                 datetime(2026, 11, 26, 9, 1, tzinfo=timezone.utc), finding)
    retro.record_outcome(checkout, REPO, retro.FindingRef("30:1"), "issue", "99", blessing)
    assert blessing.closed and retro.filing_state(blessing.given).phase == "blessed"
    assert "blessed and closed; filing gate open" in capsys.readouterr().out


@pytest.mark.parametrize("fail_after", [1, 2, 4])
def test_bless_resumes_after_a_lost_write_response_without_duplicate_comments(
        checkout, tmp_path, blessing, fail_after, capsys):
    draft = tmp_path / "answered.md"
    draft.write_text(judged_draft(checkout), encoding="utf-8")
    command = ["bless", "30", "--draft", str(draft), "--repo", REPO, "--worktree", str(checkout)]
    blessing.fail_after = fail_after
    assert retro.main(command) == 1
    assert "GitHub response lost" in capsys.readouterr().err
    assert blessing.gate_open_at_bless
    assert retro.main(command) == 0
    assert blessing.closed
    bodies = [item["body"] for item in blessing.given]
    assert len(bodies) == len(set(bodies)) == 3
    writes = len(blessing.calls)
    assert retro.main(command) == 0
    assert len(blessing.calls) == writes


def test_bless_refuses_an_incomplete_draft_before_opening_the_gate(
        checkout, tmp_path, blessing, capsys):
    draft = tmp_path / "answered.md"
    draft.write_text(judged_draft(checkout, went_well=[]), encoding="utf-8")
    assert retro.main(["bless", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 1
    assert not blessing.calls and not blessing.closed
    assert "not complete" in capsys.readouterr().err


def test_bless_caps_network_processes_at_the_remaining_minute(monkeypatch, capsys):
    processes = work_tickets.process_door

    class Timeout:
        def run(self, argv, options):
            assert options["timeout"] == 55
            raise retro.subprocess.TimeoutExpired(argv, options["timeout"])

    def blocked(args, deadline):
        monkeypatch.setattr(retro.time, "monotonic", lambda: 5)
        processes.run(["gh", "api", "rate_limit"])

    monkeypatch.setattr(retro.time, "monotonic", lambda: 0)
    monkeypatch.setattr(retro, "bless", blocked)
    with processes.use(Timeout()):
        assert retro.main(["bless", "30"]) == 1
    assert "one-minute network budget" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["collect", "file", "bless"])
def test_private_drafts_are_refused_before_writing_or_posting(
        checkout, tmp_path, monkeypatch, blessing, command, capsys):
    private = "\\".join(("C:", "Users", "alice", "private", "notes.txt"))
    text = judged_draft(checkout).replace("## 1. Collect", f"{private}\n\n## 1. Collect")
    path = tmp_path / "draft.md"
    if command == "collect":
        found = collected(checkout)
        monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
        monkeypatch.setattr(retro, "collect", lambda *args, **kwargs: found)
        monkeypatch.setattr(retro, "draft", lambda _: text)
        options = ["--out", str(path)]
    else:
        path.write_text(text, encoding="utf-8")
        options = ["--draft", str(path)]
    assert retro.main([command, "30", *options, "--repo", REPO,
                       "--worktree", str(checkout)]) == 1
    output = capsys.readouterr()
    assert "private material" in output.err
    assert private not in output.out + output.err
    assert not blessing.calls
    if command == "collect":
        assert not path.exists()


def test_record_outcome_closes_only_after_last_finding(monkeypatch, capsys):
    class Door(retro.GhDoor):
        missing = []

        def __init__(self):
            self.given = [{"body": retro.report_state_comment("report", 2)}]
            self.closed = False

        def comments(self, number):
            return self.given

        def issue(self, number):
            if number == 30:
                return {"number": 30, "state": "open", "labels": [{"name": "retro"}]}
            if number == 99:
                return {"number": 99, "state": "open", "labels": [{"name": "work"}],
                        "body": "retro #30 finding 2"}
            return {}

    door = Door()

    def actions(root, tracker, _):
        def comment(arguments, detail):
            door.given.append({"body": arguments["body"]})

        def close(arguments, detail):
            door.closed = True

        return {"comment_issue": comment, "close_issue": close}

    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(retro, "issue_actions", actions)
    first = retro.FindingRef("30:1")
    retro.record_outcome(Path("."), REPO, first, "declined", "not needed", door)
    assert retro.filing_state(door.given).phase == "report"
    assert door.closed is False
    retro.record_outcome(Path("."), REPO, retro.FindingRef("30:2"), "issue", "99", door)
    assert retro.filing_state(door.given).phase == "done"
    assert door.closed is True
    assert any("se:retro-state done findings=2" in item["body"] for item in door.given)
    assert "done and closed" in capsys.readouterr().out


def filed(checkout: Path, monkeypatch, text: str) -> list[tuple[str, dict]]:
    """`retro.py file 30` of the draft `text`, committed as the retro doc on main, through gh:
    the writes it made."""
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    draft = commit_doc(checkout, text)
    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    return tracker.calls


def test_file_posts_the_report_and_leaves_the_retro_open_for_finding_outcomes(
        checkout, monkeypatch, capsys):
    calls = filed(checkout, monkeypatch, judged_draft(checkout))

    assert [name for name, _ in calls] == ["comment_issue", "comment_issue"]
    assert all(arguments["issue_number"] == 30 for _, arguments in calls)
    comment = calls[0][1]["body"]
    assert comment.startswith(retro.REPORT_MARKER + "\n# Retro #30: the report\n")
    assert ("#### Lost reports (2)\n\nCause: a landing need not name a field report\n\n"
            "Fix: `integrate` refuses a landing without one\n" in comment)
    assert ("- **1. Refuse a landing whose work issue has no field report** (work, for SE to "
            "bundle; home `scripts/work_tickets.py`; check `field-report`)") in comment
    assert ("- **2. Make the field report a rule of the rule book** (decision, for the owner's "
            "decision list: it changes a rule; home `src/skills/work-model/") in comment
    assert "- The fake door kept the tests fast." in comment
    assert "The report is in; the retro stays open until every finding has an outcome." in comment
    assert "`retro #30 finding <k>`" in comment
    sha = git(checkout, "rev-parse", "origin/main")
    url = f"https://github.com/owner/repo/blob/{sha}/docs/retro-30.md"
    assert f"committed retro doc [docs/retro-30.md]({url}), at {sha[:12]}." in comment
    assert comment.endswith(retro.DOC_MARKER.format(sha=sha, path="docs/retro-30.md") + "\n")
    assert calls[1][1]["body"] == retro.report_state_comment("report", 2) + "\n" + (
        "The report is in; record an outcome for each of its 2 findings.")
    assert "#### Sizes" not in comment and retro.BLOCK_MARKER not in comment  # in the doc
    assert retro.JUDGE_BEGIN not in comment and "## Judgment" not in comment
    out = capsys.readouterr().out
    assert f"the report in 1 comment(s) of {len(comment)} characters (limit 65536)" in out
    assert "1 work and 1 decision finding(s); SE records an outcome for each" in out


def test_a_draft_of_130000_characters_posts_one_comment_under_the_limit(checkout, monkeypatch):
    """The first live retro's draft was 130,476 characters, most of it facts and block: the
    comment holds the report proper and links the doc for the rest."""
    text = judged_draft(checkout)
    head = text.index("### Landed issues")
    text = text[:head] + "### Long facts\n\n" + "- a landed issue's row\n" * 6000 + "\n" + text[head:]
    assert len(text) > 130000

    calls = filed(checkout, monkeypatch, text)

    comments = [arguments["body"] for name, arguments in calls if name == "comment_issue"]
    assert len(comments) == 2 and len(comments[0]) < retro.COMMENT_LIMIT
    assert "/blob/" in comments[0] and "docs/retro-30.md" in comments[0]
    assert "a landed issue's row" not in comments[0]
    assert comments[1].startswith("<!-- se:retro-state report findings=")
    assert [name for name, _ in calls] == ["comment_issue", "comment_issue"]
    assert calls[-1][1]["body"].startswith("<!-- se:retro-state report findings=")


def test_the_doc_marker_is_the_retro_doc_message_and_reads_back():
    """templates/retro-doc.md writes the line the report links its retro doc with, as before; the
    reading stays DOC_PATTERN, which takes a full commit only."""
    sha = "0123456789abcdef0123456789abcdef01234567"
    line = retro.doc_marker(sha, "docs/retro-30.md")
    assert line == f"<!-- se:retro-doc {sha} docs/retro-30.md -->"
    assert retro.DOC_PATTERN.fullmatch(line).groups() == (sha, "docs/retro-30.md")
    assert retro.DOC_PATTERN.fullmatch(retro.doc_marker("abc123", "docs/retro-30.md")) is None


def test_the_finding_reference_is_the_finding_ref_message_that_collect_finds():
    """templates/finding-ref.md writes the reference a work issue names a finding by, which
    FINDING_REFERENCE finds in free text, the retro's and the overhaul's alike."""
    assert retro.finding_reference("retro", 30) == "retro #30 finding <k>"
    assert retro.FINDING_REFERENCE.search(f"Takes {retro.finding_reference('retro', 30, 2)}.").groups() == (
        "30", "2")
    assert retro.sibling("overhaul").FINDING_REFERENCE.search(
        retro.finding_reference("overhaul", 50, 1)).groups() == ("50", "1")


def test_filing_state_is_done_only_after_every_outcome_is_recorded():
    comments = [{"body": retro.report_state_comment("report", 2)}]
    assert retro.filing_state(comments).phase == "report"
    comments.append({"body": retro.outcome_comment(1, "declined", "not needed")})
    assert retro.filing_state(comments).phase == "report"
    comments.append({"body": retro.outcome_comment(2, "merged", "1")})
    assert retro.filing_state(comments).phase == "done"
    with pytest.raises(work_tickets.QueueError, match="marked done with 0 of 2"):
        retro.filing_state([{"body": retro.report_state_comment("done", 2)}])


def test_finding_argument_is_a_positive_retro_and_finding_pair():
    assert (retro.FindingRef("30:2").retro, retro.FindingRef("30:2").finding) == (30, 2)
    for value in ("0:1", "3:0", "3:1:2", "x:1"):
        with pytest.raises(ValueError, match="must be <retro>:<finding>"):
            retro.FindingRef(value)


def test_the_next_retro_reports_each_finding_outcome():
    previous = {"findings": [
        {"finding": 1, "title": "Keep the report open", "class": "C", "kind": "work"},
        {"finding": 2, "title": "Record an outcome", "class": "C", "kind": "work"},
        {"finding": 3, "title": "Merge duplicates", "class": "C", "kind": "work"}]}
    rows = retro.scored_findings(
        previous, 5, [], {}, outcomes={1: ("issue", "11"), 2: ("declined", "not needed"),
                                       3: ("merged", "1")})
    assert [row["outcome"] for row in rows] == [
        "issue #11", "declined: not needed", "merged into finding 1"]


def test_a_report_proper_over_the_limit_posts_in_numbered_parts(checkout, monkeypatch):
    long = "\n".join(f"Line {index} of a long finding body." for index in range(4000))
    long += "\n" + "x" * 70000  # a line longer than a comment is cut within it, never dropped
    text = judged_draft(checkout, findings=[finding(body=long)])

    calls = filed(checkout, monkeypatch, text)

    all_comments = [arguments["body"] for name, arguments in calls if name == "comment_issue"]
    comments = all_comments[:-1]
    total = len(comments)
    assert total > 3 and len(all_comments) == total + 1
    assert [name for name, _ in calls] == ["comment_issue"] * (total + 1)
    assert all(len(comment) <= retro.COMMENT_LIMIT for comment in all_comments)
    assert all_comments[-1].startswith("<!-- se:retro-state report findings=")
    # Each part is unmarked, so the gate takes none for a whole report; file checked the whole.
    assert comments[0].startswith("# Retro #30: the report\n")
    assert not any(retro.REPORT_MARKER in comment or retro.templates().FLEET_MARKER in comment
                   for comment in comments)
    label = "\n\n_Part {} of %d of the report of retro #30._\n" % total
    assert all(comment.endswith(label.format(index)) for index, comment in
               enumerate(comments, 1))
    joined = "".join(comment[:-len(label.format(index))] for index, comment in
                     enumerate(comments, 1))
    assert "Line 3999 of a long finding body." in joined and "x" * 70000 in joined.replace("\n", "")
    assert retro.DOC_MARKER.split(" {")[0] in comments[-1]
    assert calls[-1][1]["body"].startswith("<!-- se:retro-state report findings=1 -->")


@pytest.mark.parametrize("where", ["outside", "uncommitted", "changed"])
def test_file_posts_the_block_on_the_issue_where_main_does_not_hold_the_draft(
        checkout, tmp_path, monkeypatch, capsys, where):
    """Filing needs no landing: where no commit of main holds the draft as it stands, the report
    carries the drafted facts and the block follows in its own comments, which the next collect
    reads back (`posted_block`)."""
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    monkeypatch.setattr(retro, "COMMENT_LIMIT", 2000)
    text = judged_draft(checkout)
    if where == "outside":
        draft = tmp_path / "draft.md"
    else:
        draft = checkout / "docs" / "retro-30.md"
        if where == "changed":
            commit_doc(checkout, text.replace("Lost reports", "Lost", 1))
        draft.parent.mkdir(exist_ok=True)
    draft.write_text(text, encoding="utf-8")

    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0

    bodies = [arguments["body"] for name, arguments in tracker.calls if name == "comment_issue"]
    assert not any(retro.DOC_PATTERN.search(body) for body in bodies)
    blocks = [body for body in bodies if body.startswith("<!-- se:retro-block ")]
    assert len(blocks) > 1 and all(len(body) <= 2000 for body in blocks)
    assert bodies[-1].startswith("<!-- se:retro-state report findings=2 -->")
    block = retro.posted_block(bodies, 30, lambda sha, path: None)
    assert [item["title"] for item in block["findings"]] == [
        item["title"] for item in retro.judged(text, 30)["findings"]]
    assert "carrying the facts and the block itself" in capsys.readouterr().out


def test_file_reads_a_draft_of_the_older_six_step_template_in_the_current_form(
        checkout, tmp_path, monkeypatch, capsys):
    """A draft answered under the six-step template (field feedback first) files: its field
    feedback moves under Collect and the steps take their current headings."""
    text = judged_draft(checkout)
    headings = {"## 1. Collect": "## 2. Collect", "## 2. Table of what happened":
                "## 3. Table of what happened", "## 3. The standing questions":
                "## 4. The standing questions", "## 4. Classes and homes": "## 5. Classes and homes",
                "## 5. The person decides": "## 6. The person decides"}
    old = retro.templates().INPUTS_PATTERN.sub("", text)
    for new, before in headings.items():
        old = old.replace(f"\n{new}\n", f"\n{before}\n", 1)
    first = old.index("## 2. Collect")
    old = (old[:first] + "## 1. Field feedback\n\n<!-- field_feedback: The person's answer. -->\n\n"
           "Retros take too long.\n\n" + old[first:])
    assert retro.steps_problems(old)
    converted = retro.current_form(old)
    assert converted is not None and not retro.steps_problems(converted)
    assert "### Field feedback\n\nRetros take too long." in converted
    assert retro.current_form(text) is None

    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    draft = tmp_path / "old.md"
    draft.write_text(old, encoding="utf-8")
    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    assert "follows an older retro template" in capsys.readouterr().out


def test_file_checks_the_template_inputs_recorded_at_collection_not_the_newest_form(
        checkout, tmp_path, monkeypatch):
    text = judged_draft(checkout)
    engine = retro.templates()
    old = retro.retro_template()
    assert engine.marked_version(old, text) == old.version
    latest = dataclasses.replace(old, version="99.0.0", fields=(*old.fields, engine.Field(
        name="later", kind="text", heading="Added after the answers", required=True)))
    own = engine.own
    monkeypatch.setattr(engine, "own", lambda name: latest if name == "retro" else own(name))
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    draft = tmp_path / "answered.md"
    draft.write_text(text, encoding="utf-8")
    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    report = tracker.calls[0][1]["body"]
    assert engine.parse(latest, report).recorded == old.version
    assert not retro.steps_problems(report)
    renewed = engine.renew(latest, text)
    assert any("Added after the answers" in problem for problem in retro.steps_problems(renewed))


def test_file_reads_the_draft_at_its_known_path_and_names_collect_where_none_is(
        checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    known = retro.draft_path(REPO, 30)
    assert known == tmp_path / "home" / ".se" / "retros" / "owner" / "repo" / "retro-30.md"
    command = ["file", "30", "--repo", REPO, "--worktree", str(checkout)]
    assert retro.main(command) == 1
    err = capsys.readouterr().err
    assert f"no draft of retro #30 at {known}" in err and "`retro.py collect 30`" in err
    known.parent.mkdir(parents=True)
    known.write_text(judged_draft(checkout), encoding="utf-8")
    assert retro.main(command) == 0
    assert "GitHub plan: the report of retro #30" in capsys.readouterr().out


def test_file_without_gh_posts_report_state_and_leaves_findings_open(checkout, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    draft = commit_doc(checkout, judged_draft(checkout))

    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the report of retro #30" in out
    assert '1. add_issue_comment {"body": "<!-- se:retro-report -->' in out
    assert '2. add_issue_comment {"body": "<!-- se:retro-state report findings=2 -->' in out
    assert "issue_write" not in out
    assert not re.search(r"^\d+\. (?:create_issue|issue_write) ", out, re.MULTILINE)


def test_the_next_collect_scores_the_previous_findings(checkout, monkeypatch):
    """Retro #5's posted report held four findings in its linked doc; in the window #11 took
    finding 1 and closed, #12 took finding 2 and closed, and the check finding 2 names broke
    again; open #16 takes finding 4. With the overhaul countdown off (`[overhaul]` due_after and
    days 0), finding 4 is scored as before it: none, and recurred. With it on (the built-in),
    finding 4 had no time to land: too early to score, not a failure, even though the check it
    names broke again."""
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    given = answers(checkout)
    block = {"version": 1, "sizes": {"closed": 7}, "window": {"retro": 5},
             "classes": [{**LOST_REPORTS, "name": "C"}], "went_well": ["Something went well."],
             "findings": [
                 finding(**{"class": "C", "title": "Name the fake door in every test"}),
                 finding(**{"class": "C", "check": "check",
                            "title": "Run the check job on every landing"}),
                 finding(**{"class": "C", "title": "A finding nobody took up yet"}),
                 finding(**{"class": "C", "check": "check",
                            "title": "Gate the landing on its check run"})]}
    draft = commit_doc(checkout, "# Retro draft for #5\n\n" + steps() + "\n" + retro.BLOCK_MARKER + "\n```yaml\n"
                       + json.dumps(block) + "\n```\n", "docs/retro-5.md")
    assert retro.main(["file", "5", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    given["comments-5.json"] = [
        {"body": tracker.calls[0][1]["body"]},
        {"body": tracker.calls[1][1]["body"]},
    ]
    for item in given["issues.json"]:
        if item["number"] == 11:
            item["body"] = "Takes retro #5 finding 1."
        if item["number"] == 12:
            item["body"] = "Takes Retro #5 finding 2 and retro #4 finding 3."
    given["open-issues.json"] = [{"number": 16, "title": "feat/gate", "state": "open",
                                  "labels": [{"name": "work"}], "body": "Takes retro #5 finding 4."}]

    (checkout / "se.toml").write_text("[overhaul]\ndue_after = 0\ndays = 0\n", encoding="utf-8")
    off = FakeDoor(given)
    unchanged = retro.collect(checkout, 30, off, REPO, "main", "origin/main", NOW)
    assert "open-issues.json" not in off.reads
    assert unchanged.previous["findings"][3] == {
        "finding": 4, "title": "Gate the landing on its check run", "class": "C", "kind": "work",
        "check": "check", "issues": [], "state": "none", "outcome": "not recorded",
        "recurred": True}
    assert ("| 4. Gate the landing on its check run | C | work | not recorded | none | none | "
            "yes (check) |"
            in retro.draft(unchanged))
    (checkout / "se.toml").unlink()

    given["comments-5.json"] = [
        {"body": tracker.calls[0][1]["body"]},
        {"body": tracker.calls[1][1]["body"]},
        {"body": retro.outcome_comment(1, "issue", "11")},
        {"body": retro.outcome_comment(2, "declined", "duplicate")},
        {"body": retro.outcome_comment(3, "merged", "2")},
        {"body": retro.outcome_comment(4, "issue", "16")},
        {"body": retro.report_state_comment("done", 4)},
    ]
    found = collected(checkout, given)
    assert found.previous["sizes"] == {"closed": 7}
    assert found.previous["findings"] == [
        {"finding": 1, "title": "Name the fake door in every test", "class": "C", "kind": "work",
         "check": "", "issues": [11], "state": "closed", "outcome": "issue #11",
         "recurred": False},
        {"finding": 2, "title": "Run the check job on every landing", "class": "C",
         "kind": "work", "check": "check", "issues": [12], "state": "closed",
         "outcome": "declined: duplicate", "recurred": True},
        {"finding": 3, "title": "A finding nobody took up yet", "class": "C", "kind": "work",
         "check": "", "issues": [], "state": "none", "outcome": "merged into finding 2",
         "recurred": False},
        {"finding": 4, "title": "Gate the landing on its check run", "class": "C", "kind": "work",
         "check": "check", "issues": [16], "state": "too early to score",
         "outcome": "issue #16", "recurred": False}]
    text = retro.draft(found)
    assert "### The findings of retro #5" in text
    assert ("| 2. Run the check job on every landing | C | work | declined: duplicate | #12 | closed | "
            "yes (check) |") in text
    assert ("| 3. A finding nobody took up yet | C | work | merged into finding 2 | none | none | "
            "no check named |") in text
    assert ("| 4. Gate the landing on its check run | C | work | issue #16 | #16 | "
            "too early to score | "
            "not scored (check) |") in text
    assert retro.read_block(text)["findings"] == []

    given["comments-5.json"] = [
        {"body": tracker.calls[0][1]["body"]},
        {"body": tracker.calls[1][1]["body"]},
        {"body": retro.outcome_comment(1, "issue", "11")},
        {"body": retro.outcome_comment(2, "declined", "duplicate")},
        {"body": retro.outcome_comment(3, "merged", "2")},
        {"body": retro.outcome_comment(4, "issue", "16")},
        {"body": retro.report_state_comment("done", 4)},
    ]

    given["comments-5.json"] = [{"body": retro.DOC_MARKER.format(sha="f" * 40,
                                                                  path="docs/retro-5.md")}]
    with pytest.raises(work_tickets.QueueError, match="which the checkout does not hold"):
        collected(checkout, given)


def test_the_retro_template_names_the_two_commands():
    template = (Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"
                / "retro.md").read_text(encoding="utf-8")
    assert "scripts/retro.py collect <this issue> --out <draft>" in template
    assert "scripts/retro.py bless <this issue> --draft <draft>" in template


def test_an_ad_hoc_component_used_in_enough_sessions_is_a_promotion_candidate(checkout):
    """The acceptance (issue #990): an ad hoc component scaffolded by `se component add`, used in
    PROMOTE_SESSIONS sessions in the window, is listed by retro.py collect as a candidate; one used
    in fewer is not."""
    se_component.add(checkout, "probe")
    se_component.add(checkout, "once")
    for session in range(se_usage.PROMOTE_SESSIONS):
        se_usage.record(checkout, "probe", session=f"s{session}", at="2026-11-05T00:00:00Z")
    se_usage.record(checkout, "once", session="s0", at="2026-11-05T00:00:00Z")
    # A use before the window (the last retro closed 2026-11-01) does not count.
    se_usage.record(checkout, "probe", session="old", at="2026-10-01T00:00:00Z")

    found = collected(checkout)

    assert [c["component"] for c in found.adhoc] == ["probe"]
    assert found.adhoc[0]["sessions"] == se_usage.PROMOTE_SESSIONS
    assert found.adhoc[0]["path"] == ".se/components/probe"
    text = retro.draft(found)
    assert "### Ad hoc components to promote" in text
    assert "| probe |" in text and "`.se/components/probe`" in text
    assert "once" not in text.split("### Ad hoc components to promote", 1)[1].split("###", 1)[0]


def test_the_most_run_ad_hoc_scripts_are_promotion_candidates_beside_the_components(checkout):
    """Requirement 2 (issue #1047): the scripts the use log shows run PROMOTE_RUNS or more times in
    the window are listed, by path and hash, the most-run first, with their counts and the window;
    a script run fewer times, or a run before the window, is not."""
    for _ in range(4):
        se_usage.record_run(checkout, "probe.py", "a" * 64, session="s1", at="2026-11-05T00:00:00Z")
    for session in ("s1", "s2", "s2"):
        se_usage.record_run(checkout, "<scratchpad>/fix.sh", "b" * 64, session=session,
                            at="2026-11-06T00:00:00Z")
    se_usage.record_run(checkout, "rare.py", "c" * 64, session="s1", at="2026-11-06T00:00:00Z")
    for _ in range(5):  # before the window (the last retro closed 2026-11-01)
        se_usage.record_run(checkout, "old.py", "d" * 64, session="s1", at="2026-10-01T00:00:00Z")
    se_usage.record(checkout, "probe", session="s1", at="2026-11-05T00:00:00Z")

    found = collected(checkout)

    assert [(s["script"], s["runs"], s["sessions"]) for s in found.scripts] == [
        ("probe.py", 4, 1), ("<scratchpad>/fix.sh", 3, 2)]
    assert found.data()["scripts"] == found.scripts
    assert found.adhoc == []  # a script's run is no component's use
    text = retro.draft(found)
    section = text.split("### Ad hoc scripts to promote", 1)[1].split("\n### ", 1)[0]
    assert f"since {found.window.since}" in section
    assert "| `probe.py` | 4 | 1 | `aaaaaaaaaaaa` |" in section
    assert "rare.py" not in section and "old.py" not in section


def test_no_ad_hoc_use_leaves_the_draft_section_empty(checkout):
    found = collected(checkout)
    assert found.adhoc == [] and found.scripts == []
    assert "### Ad hoc components to promote\n\nNone." in retro.draft(found)
    assert "### Ad hoc scripts to promote\n\nNone." in retro.draft(found)


# The two flags and the optional keys of a class: off by default, so the draft without them is
# the draft as before.

NEW_HEADINGS = ("### Session signals", "### Refused deliveries and declined reviews",
                "### The classes of retro")


def without_block(text: str, heading: str) -> str:
    """`text` without the section under `heading`, up to the next heading of its level or the
    judging note."""
    start = text.index("\n" + heading)
    depth = len(heading.split(" ", 1)[0])
    ends = [at for at in (*(text.find("\n" + "#" * level + " ", start + 1)
                            for level in range(1, depth + 1)),
                          text.find("\n" + retro.JUDGE_BEGIN, start))
            if at >= 0]
    return text[:start] + text[min(ends):]


def transcript(path: Path, *records: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def person(text: str, time: str) -> dict:
    return {"type": "user", "timestamp": time, "message": {"role": "user", "content": text}}


def test_without_the_flags_the_draft_carries_none_of_the_new_blocks(checkout):
    text = retro.draft(collected(checkout))
    assert not any(heading in text for heading in NEW_HEADINGS)
    found = collected(checkout)
    assert (found.signals, found.refusals, found.extras()) == (None, None, {})
    assert "classes" not in found.previous


def test_signals_adds_one_block_of_counts_with_a_line_per_source(checkout, tmp_path):
    plain = retro.draft(collected(checkout))
    one = transcript(tmp_path / "records" / "one.jsonl",
                     person("Do the thing.", "2026-11-02T10:00:00Z"),
                     {"type": "assistant", "timestamp": "2026-11-02T10:00:30Z",
                      "message": {"role": "assistant", "content": [
                          {"type": "tool_use", "id": "t1", "name": "Bash",
                           "input": {"command": "ls"}}]}},
                     person("no, not like that", "2026-11-02T10:01:00Z"))
    empty = transcript(tmp_path / "records" / "empty.jsonl")
    found = collected(checkout, signals=[one, empty, tmp_path / "gone.jsonl"])

    assert found.signals["given"] == 3 and found.signals["read"] == 1
    assert found.signals["signals"]["corrections"] == 1
    text = retro.draft(found)
    assert "### Session signals\n\n1 files read of 3 given" in text
    assert "- one.jsonl: 3 events, 2 hits\n- empty.jsonl: nothing read\n- gone.jsonl: not found" in text
    assert "| corrections | 1 |" in text
    assert without_block(text, "### Session signals") == plain
    assert retro.read_block(text) == retro.read_block(plain)


def test_signals_with_no_file_read_says_so_and_counts_nothing(checkout, tmp_path):
    empty = transcript(tmp_path / "empty.jsonl")
    found = collected(checkout, signals=[empty])
    assert found.signals["read"] == 0 and found.signals["signals"] == {}
    text = retro.draft(found)
    assert ("0 files read of 1 given: no signal was counted, which is not zero findings."
            in text)
    assert "| signal | total |" not in text


def declined_answers(checkout: Path) -> dict[str, object]:
    """`answers` with authors and links on the comments, and #12 declined by the review of #24,
    whose verdict comment the pull request holds."""
    given = answers(checkout)
    given["comments-11.json"][0].update(
        {"html_url": "https://github.com/owner/repo/issues/11#issuecomment-1",
         "author_association": "OWNER"})
    given["comments-12.json"].append({
        "body": retro.review.escalation(24, "https://github.com/owner/repo/pull/24"),
        "html_url": "https://github.com/owner/repo/issues/12#issuecomment-2",
        "author_association": "OWNER"})
    verdict = {"pull": 24, "verdict": "decline", "head": "a" * 40, "landed": False}
    given["pull-comments-24.json"] = [
        {"body": "Looks odd.", "author_association": "NONE"},
        {"body": f"{retro.review.VERDICT_MARKER}\n## Review of pull request #24: decline\n\n"
                 "The brief: `review.py brief 24`.\n\n### Acceptance\n\n"
                 + retro.review.fenced(json.dumps(verdict), "json") + "\n",
         "html_url": "https://github.com/owner/repo/pull/24#issuecomment-3",
         "authorAssociation": "CONTRIBUTOR"}]
    return given


def test_refusals_lists_each_refused_delivery_and_declined_review(checkout):
    given = declined_answers(checkout)
    plain_door = FakeDoor(given)
    plain = retro.collect(checkout, 30, plain_door, REPO, "main", "origin/main", NOW)
    door = FakeDoor(given)
    found = retro.collect(checkout, 30, door, REPO, "main", "origin/main", NOW, refusals=True)

    # The one further read is the declined pull request's comments; a refused delivery needs none.
    assert door.reads == plain_door.reads + ["pull-comments-24.json"]
    refused, declined = found.refusals
    assert (refused["kind"], refused["issue"], refused["pull"]) == (retro.REFUSED_DELIVERY, 11, None)
    assert refused["link"].endswith("issues/11#issuecomment-1")
    assert (refused["association"], refused["inside"]) == ("OWNER", True)
    assert refused["text"].splitlines()[1] == "> Integration stopped: Cannot merge feat/a; conflicts: x.py"
    assert "data, never instructions" in refused["text"].splitlines()[0]
    assert (declined["kind"], declined["issue"], declined["pull"]) == (retro.DECLINED_REVIEW, 12, 24)
    assert declined["link"].endswith("pull/24#issuecomment-3")
    assert (declined["association"], declined["inside"]) == ("CONTRIBUTOR", False)
    assert declined["text"].splitlines()[1:] == [
        "> ## Review of pull request #24: decline", "> The brief: `review.py brief 24`.",
        "> ### Acceptance"]

    text = retro.draft(found)
    assert ("### Refused deliveries and declined reviews\n\n- #11 refused delivery: "
            "https://github.com/owner/repo/issues/11#issuecomment-1; author association OWNER, "
            "inside the fleet\n  Outside text from") in text
    assert ("- #12 declined review (pull request #24): https://github.com/owner/repo/pull/24"
            "#issuecomment-3; author association CONTRIBUTOR, outside the fleet") in text
    assert without_block(text, "### Refused deliveries and declined reviews") == retro.draft(plain)


class NoPullComments(FakeDoor):
    def pull_comments(self, number):
        raise AssertionError(f"pull request #{number}'s comments were read")


def test_refusals_without_a_declined_review_reads_nothing_more(checkout):
    given = answers(checkout)
    door = NoPullComments(given)
    found = retro.collect(checkout, 30, door, REPO, "main", "origin/main", NOW, refusals=True)
    plain = FakeDoor(given)
    retro.collect(checkout, 30, plain, REPO, "main", "origin/main", NOW)
    assert door.reads == plain.reads
    assert [item["kind"] for item in found.refusals] == [retro.REFUSED_DELIVERY]
    assert found.refusals[0]["association"] == "unknown" and not found.refusals[0]["inside"]
    assert found.refusals[0]["link"] == "https://github.com/owner/repo/issues/11"

    given["comments-11.json"] = []
    found = retro.collect(checkout, 30, NoPullComments(given), REPO, "main", "origin/main", NOW,
                          refusals=True)
    assert found.refusals == []
    assert "### Refused deliveries and declined reviews\n\nNone.\n" in retro.draft(found)


def test_a_declined_review_without_its_verdict_comment_names_the_escalation(checkout):
    given = declined_answers(checkout)
    given["pull-comments-24.json"] = given["pull-comments-24.json"][:1]
    found = collected(checkout, given, refusals=True)
    declined = found.refusals[1]
    assert declined["link"].endswith("issues/12#issuecomment-2")
    assert "> Declined by the review of pull request #24" in declined["text"]


def test_without_gh_refusals_plans_the_declined_pull_requests_comments(checkout, tmp_path):
    given = declined_answers(checkout)
    directory = tmp_path / "answers"
    directory.mkdir()
    for name, answer in given.items():
        if name != "pull-comments-24.json":
            (directory / name).write_text(json.dumps(answer), encoding="utf-8")
    door = retro.FileDoor(directory, REPO, REPO)
    assert retro.collect(checkout, 30, door, REPO, "main", "origin/main", NOW,
                         refusals=True) is None
    assert [(step.tool, step.arguments["method"], step.arguments["pullNumber"])
            for step in door.missing] == [("pull_request_read", "get_comments", 24)]
    (directory / "pull-comments-24.json").write_text(
        json.dumps(given["pull-comments-24.json"]), encoding="utf-8")
    found = retro.collect(checkout, 30, retro.FileDoor(directory, REPO, REPO), REPO, "main",
                          "origin/main", NOW, refusals=True)
    assert found.refusals[1]["association"] == "CONTRIBUTOR"


def test_the_flags_parse_and_json_carries_their_blocks(checkout, tmp_path, monkeypatch, capsys):
    parsed = retro.make_parser().parse_args(["collect", "30", "--refusals", "--signals", "a.jsonl",
                                             "records"])
    assert parsed.refusals and parsed.signals == [Path("a.jsonl"), Path("records")]
    parsed = retro.make_parser().parse_args(["collect", "30"])
    assert (parsed.refusals, parsed.signals) == (False, None)

    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    directory = tmp_path / "answers"
    directory.mkdir()
    for name, answer in hosts_answers(declined_answers(checkout)).items():
        (directory / name).write_text(json.dumps(answer), encoding="utf-8")
    empty = transcript(tmp_path / "empty.jsonl")
    assert retro.main(["collect", "30", "--answers", str(directory), "--json", "--refusals",
                       "--repo", REPO, "--worktree", str(checkout), "--signals", str(empty)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["signals"]["read"] == 0 and len(data["refusals"]) == 2
    assert retro.main(["collect", "30", "--answers", str(directory), "--json", "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    assert "signals" not in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(("keys", "refusal"), [
    ({"status": ""}, 'class "Lost reports": status is a text'),
    ({"pattern": "(unclosed"}, 'class "Lost reports": pattern is no regular expression'),
    ({"pattern": 3}, "pattern is a regular expression, as a text"),
    ({"limits": [1]}, "limits is a text or a list of texts"),
    ({"owner": "alice"}, "class 1 has the unknown field owner"),
])
def test_a_class_s_optional_keys_are_checked(checkout, keys, refusal):
    classes = [{**LOST_REPORTS, **keys}]
    with pytest.raises(work_tickets.QueueError, match=re.escape(refusal)):
        retro.judged(judged_draft(checkout, classes=classes), 30)


def cases_of(test) -> list[dict]:
    """The judgment changes of a parametrized test's cases, as the test states them."""
    return [case[0] for mark in test.pytestmark if mark.name == "parametrize" for case in mark.args[1]]


def recurred_draft(checkout: Path) -> str:
    """The judged draft whose first finding names a check that recurred after the previous retro."""
    draft = judged_draft(checkout)
    block = retro.read_block(draft)
    block["previous"]["findings"] = [{"finding": 1, "check": "field-report", "recurred": True}]
    return draft[:draft.rfind(retro.BLOCK_MARKER)] + retro.BLOCK_MARKER + "\n```yaml\n" + \
        json.dumps(block) + "\n```\n"


def test_the_judged_block_s_adapter_finds_what_judgment_problems_finds(checkout):
    """templates/retro-judgment.md checks the block through judgment_problems: on the drafts of
    the refusal tests, the complete judgment among them, its problems are the same."""
    drafts = [judged_draft(checkout, **changes)
              for changes in cases_of(test_file_refuses_an_incomplete_judgment_and_writes_nothing)]
    drafts += [judged_draft(checkout, classes=[{**LOST_REPORTS, **keys}])
               for keys in cases_of(test_a_class_s_optional_keys_are_checked)]
    drafts += [judged_draft(checkout), recurred_draft(checkout)]
    for draft in drafts:
        assert retro.adapter_problems(retro.JUDGMENT_TEMPLATE, draft) == retro.judgment_problems(
            retro.read_block(draft))
    assert retro.adapter_problems(retro.JUDGMENT_TEMPLATE, drafts[-2]) == []
    assert retro.adapter_problems(retro.JUDGMENT_TEMPLATE, drafts[-1]) != []


def test_a_class_with_the_optional_keys_files_them_and_the_next_collect_measures_it_again(
        checkout, monkeypatch):
    """Retro #5 named two classes; the next collect measures each again, its rate before (its
    findings per issue #5 closed: 2 of 4) against its rate now (the issues its pattern matches, per
    issue), and checks it against the tree: Lost reports' mark is in its home, so fixed; Plain's
    is not, so open."""
    keys = {"status": "watch", "pattern": r"(?i)integration stopped", "limits": ["only merges"],
            "mark": "refuses a landing without a field report"}
    classes = [{**LOST_REPORTS, **keys},
               {**LOST_REPORTS, "name": "Plain", "home_kind": "sentence", "home": "README.md"}]
    plain = filed(checkout, monkeypatch, judged_draft(checkout))[0][1]["body"]
    calls = filed(checkout, monkeypatch, judged_draft(checkout, classes=classes))
    comment = calls[0][1]["body"]
    assert ("#### Lost reports (2)\n\nCause: a landing need not name a field report\n\n"
            "Fix: `integrate` refuses a landing without one\n\nHome: refusal (home 2 of 8), "
            "`scripts/work_tickets.py`; tree: open\n\nStatus: watch\nPattern: "
            "`(?i)integration stopped`\nLimits: only merges\nMark: `refuses a landing without a "
            "field report`\n\n- **1." in comment)
    assert "#### Plain (0)" in comment and "Open classes: Lost reports, Plain." in comment
    assert "Status:" not in plain and "Pattern:" not in plain

    given = answers(checkout)
    block = retro.read_block(judged_draft(checkout, classes=classes))
    block["window"]["retro"] = 5
    draft = commit_doc(checkout, "# Retro draft for #5\n\n" + steps() + "\n" + retro.BLOCK_MARKER
                       + "\n```yaml\n" + json.dumps(block) + "\n```\n", "docs/retro-5.md")
    given["comments-5.json"] = [{"body": retro.DOC_MARKER.format(
        sha=git(checkout, "rev-parse", "HEAD"), path=draft.relative_to(checkout).as_posix())}]
    given["issues.json"][3]["body"] = "Integration stopped twice before: integration stopped."
    home = checkout / "scripts" / "work_tickets.py"
    home.parent.mkdir(exist_ok=True)
    home.write_text("# integrate refuses a landing without a field report\n", encoding="utf-8")
    found = collected(checkout, given)
    assert found.previous["classes"] == [
        {"name": "Lost reports", "status": "watch", "home": "scripts/work_tickets.py",
         "home_kind": "refusal", "limits": ["only merges"], "before": 0.5,
         "pattern": r"(?i)integration stopped", "matches": 3, "issues": [11, 12], "now": 0.5,
         "tree": "fixed"},
        {"name": "Plain", "status": None, "home": "README.md", "home_kind": "sentence",
         "limits": None, "before": 0.0, "tree": "open"}]
    text = retro.draft(found)
    assert ("### The classes of retro #5, measured again\n\n" in text and
            "| class | status | rate before | rate now | pattern | matches | issues | limits |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| Lost reports | watch | 0.5 | 0.5 | `(?i)integration stopped` | 3 | #11, #12 | "
            "only merges |\n| Plain |  | 0 | no pattern | none |  |  |  |" in text)
    assert ("| class | home | tree |\n|---|---|---|\n| Lost reports | refusal "
            "`scripts/work_tickets.py` | fixed |\n| Plain | sentence `README.md` | open |") in text
    assert retro.read_block(text)["previous"]["classes"][0]["matches"] == 3


def test_a_retro_built_from_the_fixtures_shows_the_five_steps_the_matrix_and_a_class_with_its_home(
        checkout, monkeypatch):
    """The acceptance of SE#1678: the draft collect writes from the fixtures and the report file
    posts from it are documents of the retro template, its five steps in order, the standing
    questions against the timeline's chapters in step 3's matrix, and in step 4 each class with
    its home in the home order and its state against the tree."""
    template = retro.retro_template()
    headings = [item.heading for item in template.fields]
    assert headings == ["1. Collect", "2. Table of what happened", "3. The standing questions",
                        "Answers to the standing questions", "4. Classes and homes",
                        "5. The person decides"]
    text = retro.draft(collected(checkout))
    at = [text.index(f"\n## {heading}\n") for heading in headings]
    assert at == sorted(at)
    # The timeline: #11 landed 10:00 on 2 Nov, #12 10:00 on 3 Nov, #13 and #14 within six hours of it.
    assert ("| chapter | from | to | steps |\n|---|---|---|---|\n"
            "| 1 | 2026-11-02T10:00:00Z | 2026-11-02T10:00:00Z | #11 |\n"
            "| 2 | 2026-11-03T10:00:00Z | 2026-11-03T13:00:00Z | #12, #13 |\n"
            "| 3 | 2026-11-04T12:00:00Z | 2026-11-04T12:00:00Z | #14 |") in text
    assert ("| #11 feat/a | 1 | the fake door | landed; 1 refused, 1 escalated, suite 35.4 s |  |"
            in text)
    # The matrix names the issue whose field report answers a question in its chapter.
    assert ("| question | 1 (2026-11-02 10:00) | 2 (2026-11-03 10:00) | 3 (2026-11-04 12:00) |"
            in text)
    assert "| What goes well, and what makes it go well? | #11 |  |  |" in text
    assert ("| Which rule, prompt or tool made each bad output, and what change stops it? |  | "
            "#12 |  |") in text
    assert all(f"| {retro.cell(question.heading)} |" in text for question in retro.questions().fields)
    assert "Home order, strongest first: check, refusal, gate, prefill, checklist line, command, " \
           "setting, sentence." in text

    unfilled = re.sub(r"(## 1\. Collect\n\n).*?(?=\n## 2\.)", r"\1",
                      judged_draft(checkout), flags=re.DOTALL)
    assert any(problem.startswith("1. Collect is empty")
               for problem in retro.steps_problems(unfilled))
    with pytest.raises(work_tickets.QueueError, match="leaves a step of the retro template"):
        retro.run_file(retro.make_parser().parse_args(
            ["file", "30", "--draft", str(commit_doc(checkout, unfilled)), "--repo", REPO,
             "--worktree", str(checkout)]))
    comment = filed(checkout, monkeypatch, judged_draft(checkout))[0][1]["body"]
    at = [comment.index(f"\n## {heading}\n") for heading in headings]
    assert at == sorted(at)
    assert "## 1. Collect\n\nThe facts" in comment
    assert "| What goes well, and what makes it go well? | #11 |  |  |" in comment
    assert ("Home: refusal (home 2 of 8), `scripts/work_tickets.py`; tree: open" in comment)
    assert "Open classes: Lost reports." in comment
    assert [finding.fix for finding in templates.check(template, templates.parse(
        template, comment)) if finding.severity == templates.REFUSE] == []


def result_event(cost: float | None, input_tokens: int, output_tokens: int) -> dict:
    """One `list_events` result event, as the session tools answer it."""
    record = {"type": "result", "result": "Done.", "usage": {
        "input_tokens": input_tokens, "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 100, "output_tokens": output_tokens}}
    if cost is not None:
        record["total_cost_usd"] = cost
    return {"id": f"event-{input_tokens}", "data": record}


@pytest.mark.parametrize("numbered", [False, True])
def test_sessions_adds_each_cloud_session_s_cost_by_its_title_per_issue_role_and_repository(
        checkout, tmp_path, numbered):
    plain = retro.draft(collected(checkout))
    titles = {item.number: item.title for item in collected(checkout).issues}
    sessions = [
        {"id": "session_w1", "title": f"SE/SE/worker/{'11/' if numbered else ''}{titles[11]}",
         "events": [result_event(1.25, 1000, 200), result_event(0.75, 500, 100)]},
        {"id": "session_r1", "title": "SE/SE/reviewer/22" + ("/reviewed-branch" if numbered else ""),
         "events": [result_event(0.5, 300, 50)]},
        {"id": "session_i1", "title": "SE/SE/integrator", "events": [result_event(2.0, 4000, 800)]},
        {"id": "session_k1", "title": "SE/kern/integrator", "events": [result_event(None, 40, 8)]},
        {"id": "session_x1", "title": "an unrelated session", "events": [result_event(9.0, 1, 1)]},
    ]
    found = collected(checkout, sessions=sessions)

    costs = found.costs
    assert (costs["given"], costs["other"], len(costs["sessions"])) == (5, 1, 4)
    assert costs["per_issue"]["11"]["sessions"] == 2  # the worker's and the reviewer's of PR #22
    assert costs["per_issue"]["11"]["cost"] == 2.5
    assert costs["per_issue"]["11"]["tokens"]["input_tokens"] == 1800
    assert costs["per_issue"]["none"]["sessions"] == 2  # the integrators name no issue
    assert costs["per_role"]["worker"]["cost"] == 2.0
    assert costs["per_role"]["integrator"] == {
        "sessions": 2, "cost": 2.0, "tokens": {"input_tokens": 4040,
                                              "cache_creation_input_tokens": 20,
                                              "cache_read_input_tokens": 200,
                                              "output_tokens": 808}}
    assert costs["per_repository"]["SE"]["cost"] == 4.5
    assert costs["per_repository"]["kern"]["cost"] is None  # no result event named a cost
    assert found.extras() == {"costs": costs}

    text = retro.draft(found)
    assert "### Session costs\n\n4 sessions of 5 given carry an SE title; 1 other" in text
    assert "| #11 | 2 | 1800 | 30 | 300 | 350 | $2.50 |" in text
    assert "| kern | 1 | 40 | 10 | 100 | 8 | unknown |" in text
    assert without_block(text, "### Session costs") == plain
    assert retro.read_block(text) == retro.read_block(plain)


def test_collect_reads_the_session_tools_answers_from_a_file(checkout, tmp_path, monkeypatch):
    saved = tmp_path / "sessions.json"
    saved.write_text(json.dumps({"data": [{"id": "s", "title": "SE/SE/integrator",
                                           "events": [result_event(1.0, 10, 1)]}]}),
                     encoding="utf-8")
    args = retro.make_parser().parse_args(["collect", "30", "--sessions", str(saved)])
    seen: dict = {}
    monkeypatch.setattr(retro, "collect", lambda *arguments: seen.update(sessions=arguments[-1]))
    monkeypatch.setattr(retro.work_tickets, "resolve_repo", lambda root, repo: REPO)
    monkeypatch.setattr(retro.work_tickets, "hand_off", lambda: True)
    args.worktree = str(checkout)
    retro.run_collect(args)
    assert [session["title"] for session in seen["sessions"]] == ["SE/SE/integrator"]


# Every retro runs the breaking-release check (work issue 1719) and its draft records the result.


def run_collect_with(checkout, tmp_path, monkeypatch, found_breaking) -> tuple[str, dict, retro.Collected]:
    """run_collect over the window's fake answers, its check answered by `found_breaking`: the
    draft it writes, what the check was asked and the window."""
    asked: dict = {}
    se_modules = retro.sibling("se_modules")

    def check(root, local, finder=None):
        asked["root"] = root
        return found_breaking(se_modules)

    monkeypatch.setattr(se_modules, "breaking", check)
    window = collected(checkout)
    monkeypatch.setattr(retro, "collect", lambda *arguments: window)
    monkeypatch.setattr(retro.work_tickets, "resolve_repo", lambda root, repo: REPO)
    monkeypatch.setattr(retro.work_tickets, "hand_off", lambda: True)
    (checkout / "se.toml").write_text('[components.obs]\nversion = "^5.0"\n', encoding="utf-8")
    out = tmp_path / "draft.md"
    args = retro.make_parser().parse_args(["collect", "30", "--out", str(out)])
    args.worktree = str(checkout)
    assert retro.run_collect(args) == 0
    return out.read_text(encoding="utf-8"), asked, window


def test_collect_runs_the_breaking_release_check_and_the_draft_names_each_finding(checkout, tmp_path,
                                                                                  monkeypatch):
    def behind(se_modules):
        pin = se_modules.PinState(("SE",), se_modules.Module("obs", "", None, "^5.0"), (5, 0, 0), (10, 0, 0))
        return se_modules.Breaking([pin], [])

    text, asked, window = run_collect_with(checkout, tmp_path, monkeypatch, behind)

    assert asked["root"] == checkout
    assert ("### Breaking releases beyond a pin\n\n`se_modules.py breaking` over the project's component "
            "tree, as collect ran it; what to do about a finding is the person's decision.\n\n"
            "```text\nSE pins obs ^5.0, newest 10.0.0\n```\n") in text
    plain = retro.draft(dataclasses.replace(window, breaking=None))
    assert without_block(text, "### Breaking releases beyond a pin") == plain, "the rest is as before"


def test_a_breaking_release_check_that_fails_is_named_in_the_draft(checkout, tmp_path, monkeypatch):
    def fails(se_modules):
        raise se_modules.ModuleError("the required component obs is missing (SE -> obs).")

    text, _, _ = run_collect_with(checkout, tmp_path, monkeypatch, fails)

    assert ("### Breaking releases beyond a pin\n\n`se_modules.py breaking` over the project's component "
            "tree, as collect ran it; what to do about a finding is the person's decision.\n\n"
            "The check failed: the required component obs is missing (SE -> obs).\n") in text


def test_a_project_without_se_toml_pins_nothing_for_the_check(tmp_path):
    assert retro.breaking_releases(tmp_path) == {
        "lines": ["no breaking release beyond a pin: the project has no se.toml"], "error": None}
