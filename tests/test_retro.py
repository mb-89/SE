"""`retro.py collect`: a retro's window read through a fake door (gh) or, without gh, from the
answer files the session saved from the printed plans; the commits of main from git."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import retro
import work_tickets
from quiet_git import quiet

REPO = "github.com/owner/repo"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
# The commits on main, oldest first: (subject, committer date).
COMMITS = (("Initial", "2026-01-01T00:00:00+00:00"),
           ("Integrate feat/a", "2026-11-02T10:00:00+00:00"),
           ("Integrate feat/b", "2026-11-03T10:00:00+00:00"),
           ("Tidy up (#25)", "2026-11-03T11:00:00+00:00"),
           ("Hotfix pushed by hand", "2026-11-04T10:00:00+00:00"))


def git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            check=False, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def build_checkout(tmp_path: Path) -> None:
    """A bare origin whose main holds COMMITS, and a clone of it, without hooks."""
    origin, work, root = tmp_path / "origin.git", tmp_path / "work", tmp_path / "main"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    quiet(origin)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    quiet(work)
    git(work, "config", "user.name", "alice")
    git(work, "config", "user.email", "alice@example.com")
    git(work, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    for index, (subject, date) in enumerate(COMMITS):
        (work / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", subject,
            env={**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})
    git(work, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(origin), str(root)], check=True,
                   capture_output=True)
    quiet(root)


@pytest.fixture
def checkout(tmp_path: Path, repositories) -> Path:
    repositories(build_checkout, tmp_path)
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
    for setting in (("user.name", "alice"), ("user.email", "alice@example.com"),
                    ("core.hooksPath", str(checkout.parent / "no-hooks"))):
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


def issue(number: int, title: str, closed: str, reason: str = "completed",
          labels: tuple[str, ...] = ("work",)) -> dict:
    return {"number": number, "title": title, "state": "closed", "closed_at": closed,
            "state_reason": reason, "labels": [{"name": name} for name in labels], "body": ""}


def pull(number: int, head: str, body: str, merged: str | None = None, sha: str = "",
         title: str = "") -> dict:
    return {"number": number, "title": title or head, "body": body, "base": {"ref": "main"},
            "head": {"ref": head, "sha": f"{number:040d}"}, "merged_at": merged,
            "merge_commit_sha": sha or None}


def answers(checkout: Path) -> dict[str, object]:
    """A window after retro #5 closed: #11 landed after one refused delivery, #12 landed but
    escalated and its landing's check failed, #13 a duplicate, #14 closed without a field report;
    #25 landed naming no work issue and one commit reached main by hand."""
    commit = shas(checkout)
    previous = {"version": 1, "sizes": {"closed": 7, "landed": 5, "duplicates": 0, "escalated": 3}}
    work_a = report("- **Went well:** the fake door\n- **Cost time:** a slow fixture\n"
                    "- **Proposed improvement:** None",
                    "- The live run against GitHub: no token in the container.\n"
                    "- A second item\n  that wraps.").replace(issue_url(0), issue_url(11))
    work_b = report("- **Went well:** \n- **Cost time:** none\n- **Proposed improvement:** "
                    "`src/agents/worker.md`: say it once", "None").replace(issue_url(0),
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
                "https://github.com/owner/repo/pull/22", 22, issue_url(11)),
                 "2026-11-02T10:00:00Z", commit["Integrate feat/a"], "Integrate feat/a"),
            pull(22, "feat/a", work_a),
            pull(23, "land/feat/b", work_tickets.landing_description(
                "https://github.com/owner/repo/pull/24", 24, issue_url(12)),
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
        "checks-21.json": {"total_count": 1, "check_runs": [
            {"name": "check", "status": "completed", "conclusion": "success"}]},
        "checks-23.json": {"check_runs": [
            {"name": "check", "status": "completed", "conclusion": "failure"}]},
        "checks-25.json": {"check_runs": [
            {"name": "check", "status": "completed", "conclusion": "success"}]},
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
    assert by[11].retro == {"Went well": "the fake door", "Cost time": "a slow fixture"}
    assert by[12].retro == {"Proposed improvement": "`src/agents/worker.md`: say it once"}
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


def test_a_landing_naming_a_closed_or_foreign_issue_breaks_the_work_issue_check(checkout):
    given = answers(checkout)
    commit = shas(checkout)["Tidy up (#25)"]
    given["pulls.json"][4] = pull(25, "chore/c", "Refs #3", "2026-11-03T11:00:00Z", commit, "Tidy up")
    broken = {check.name: check for check in collected(checkout, given).checks}["work-issue"].broken
    assert broken == [{"item": "#25", "what": "names #3, closed before the pull request merged"}]
    given["pulls.json"][4] = pull(25, "chore/c", "Refs #15", "2026-11-03T11:00:00Z", commit, "Tidy up")
    broken = {check.name: check for check in collected(checkout, given).checks}["work-issue"].broken
    assert broken == [{"item": "#25", "what": "names #15, which is not labelled work"}]


def test_without_a_closed_retro_the_window_starts_at_the_oldest_open_retro(checkout):
    """No retro issue has closed: the window starts when the oldest open one was created, and the
    rule checks judge that window alone; with no retro issue at all, it is the whole history."""
    given = answers(checkout)
    given["issues.json"] = [item for item in given["issues.json"] if item["number"] != 5]
    given["open-issues.json"] = [
        {**issue(31, "docs/retro-20261105", None), "state": "open",
         "created_at": "2026-11-05T00:00:00Z"},
        {**issue(30, "retro: fleet 20261102", None, labels=("retro",)), "state": "open",
         "createdAt": "2026-11-02T13:00:00Z"},
        {**issue(29, "feat/open", None), "state": "open", "created_at": "2026-10-01T00:00:00Z"}]
    found = collected(checkout, given)

    assert found.window == retro.Window(30, "2026-11-02T13:00:00Z", 30, "2026-11-12T12:00:00Z",
                                        retro.OPEN_RETRO)
    assert [item.number for item in found.issues] == [12, 13, 14]
    assert found.previous is None
    checks = {check.name: check for check in found.checks}
    assert (checks["work-issue"].checked, checks["outside-pr"].checked) == (2, 3)
    assert "when retro #30, the oldest open retro issue, was created" in retro.draft(found)

    given["open-issues.json"] = given["open-issues.json"][2:]
    found = collected(checkout, given)
    assert found.window.since is None and found.window.start == retro.HISTORY
    assert [item.number for item in found.issues] == [3, 11, 12, 13, 14]
    assert {check.name: check for check in found.checks}["outside-pr"].checked == 5
    assert "the whole history up to" in retro.draft(found)


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
    parsed = retro.parser().parse_args(["collect", "30", "--retro", "4"])
    assert (parsed.since_retro, parsed.since) == (4, None)
    with pytest.raises(SystemExit):
        retro.parser().parse_args(["collect", "30", "--retro", "4", "--since", "2026-11-01"])


def test_the_landed_count_is_the_collects_and_reads_only_the_lists(checkout):
    """The start's count of work landed since the last retro (se_start.py check) is the next
    retro's window, counted as collect counts it, from the two lists alone."""
    door = FakeDoor(answers(checkout))
    assert retro.landed_since_retro(door, REPO, "main") == collected(checkout).sizes["landed"] == 2
    assert door.reads == ["issues.json", "pulls.json"]

    given = answers(checkout)
    given["issues.json"].append(issue(31, "docs/retro-20261105", "2026-11-05T00:00:00Z",
                                      labels=("retro",)))
    assert retro.landed_since_retro(FakeDoor(given), REPO, "main") == 0


def test_a_retro_is_due_after_ten_landed_issues_or_what_se_toml_sets(tmp_path):
    assert retro.due_after(tmp_path) == retro.DUE_AFTER == 10
    (tmp_path / "se.toml").write_text("[retro]\ndue_after = 4\n", encoding="utf-8")
    assert retro.due_after(tmp_path) == 4
    (tmp_path / "se.toml").write_text("[retro]\ndue_after = 0\n", encoding="utf-8")
    with pytest.raises(retro.QueueError, match="retro.due_after .* positive whole number"):
        retro.due_after(tmp_path)


def test_the_draft_ends_in_the_block_that_parses_back(checkout):
    found = collected(checkout)
    text = retro.draft(found)

    assert text.startswith("# Retro draft for #30\n")
    assert "| landed | 2 | 5 |" in text
    assert "| #11 feat/a | 1 | 1 | 35.4 s | #22 |" in text
    assert "- **check**: " in text and "broken 1 of 3\n  - #23: check failure" in text
    assert "### Cost time\n\n- #11: a slow fixture" in text
    assert "## Not delivered\n\n- #11: The live run against GitHub" in text
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


def judged_draft(checkout: Path, **changes: object) -> str:
    """The collect's draft of retro #30 with its block judged: two findings of one class, the
    second controversial; `changes` replace the judgment's lists."""
    data = collected(checkout).data()
    data.update({
        "classes": [{"name": "Lost reports", "fix": "`integrate` refuses a landing without one"}],
        "findings": [
            {"title": "Refuse a landing whose work issue has no field report",
             "body": "#14 closed without one.", "class": "Lost reports",
             "home": "scripts/work_tickets.py", "controversial": False, "check": "field-report"},
            {"title": "Make the field report a rule of the rule book",
             "body": "A rule, not a habit.", "class": "Lost reports",
             "home": retro.RULE_BOOK, "controversial": True, "why": "it changes a rule"}],
        "went_well": ["The fake door kept the tests fast."]})
    data.update(changes)
    text = retro.draft(collected(checkout))
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
    ({"classes": [{"name": "Lost reports", "fix": " "}], "findings": [finding()]},
     'class "Lost reports" has no fix'),
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
        retro.run_file(retro.parser().parse_args(["file", "30", "--draft", str(draft), "--repo",
                                                  REPO, "--worktree", str(checkout)]))
    assert "The judgment of retro #30 is not complete, so nothing was written" in str(raised.value)
    assert refusal in str(raised.value)
    assert writes == []


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


def test_file_posts_the_report_proper_as_the_closing_comment_and_files_nothing(
        checkout, monkeypatch, capsys):
    calls = filed(checkout, monkeypatch, judged_draft(checkout))

    assert [name for name, _ in calls] == ["comment_issue", "close_issue"]
    assert all(arguments["issue_number"] == 30 for _, arguments in calls)
    comment = calls[0][1]["body"]
    assert comment.startswith(retro.REPORT_MARKER + "\n## Retro #30: the report\n")
    assert ("#### Lost reports (2)\n\nFix: `integrate` refuses a landing without one\n" in comment)
    assert ("- **1. Refuse a landing whose work issue has no field report** (work, for SE to "
            "bundle; home `scripts/work_tickets.py`; check `field-report`)") in comment
    assert ("- **2. Make the field report a rule of the rule book** (decision, for the owner's "
            "decision list: it changes a rule; home `src/skills/work-model/") in comment
    assert "- The fake door kept the tests fast." in comment
    assert "This retro filed no issue." in comment and "`retro #30 finding <k>`" in comment
    sha = git(checkout, "rev-parse", "origin/main")
    url = f"https://github.com/owner/repo/blob/{sha}/docs/retro-30.md"
    assert f"committed retro doc [docs/retro-30.md]({url}), at {sha[:12]}." in comment
    assert comment.endswith(retro.DOC_MARKER.format(sha=sha, path="docs/retro-30.md") + "\n")
    assert "#### Sizes" not in comment and retro.BLOCK_MARKER not in comment  # in the doc
    assert retro.JUDGE_BEGIN not in comment and "## Judgment" not in comment
    out = capsys.readouterr().out
    assert f"the report in 1 comment(s) of {len(comment)} characters (limit 65536)" in out
    assert "1 work and 1 decision finding(s); no issue filed" in out


def test_a_draft_of_130000_characters_posts_one_comment_under_the_limit(checkout, monkeypatch):
    """The first live retro's draft was 130,476 characters, most of it facts and block: the
    comment holds the report proper and links the doc for the rest."""
    text = judged_draft(checkout)
    head = text.index("## Landed issues")
    text = text[:head] + "## Long facts\n\n" + "- a landed issue's row\n" * 6000 + "\n" + text[head:]
    assert len(text) > 130000

    calls = filed(checkout, monkeypatch, text)

    comments = [arguments["body"] for name, arguments in calls if name == "comment_issue"]
    assert len(comments) == 1 and len(comments[0]) < retro.COMMENT_LIMIT
    assert "/blob/" in comments[0] and "docs/retro-30.md" in comments[0]
    assert "a landed issue's row" not in comments[0]
    assert [name for name, _ in calls][-1] == "close_issue"


def test_a_report_proper_over_the_limit_posts_in_numbered_parts(checkout, monkeypatch):
    long = "\n".join(f"Line {index} of a long finding body." for index in range(4000))
    long += "\n" + "x" * 70000  # a line longer than a comment is cut within it, never dropped
    text = judged_draft(checkout, findings=[finding(body=long)])

    calls = filed(checkout, monkeypatch, text)

    comments = [arguments["body"] for name, arguments in calls if name == "comment_issue"]
    total = len(comments)
    assert total > 3 and [name for name, _ in calls] == ["comment_issue"] * total + ["close_issue"]
    assert all(len(comment) <= retro.COMMENT_LIMIT for comment in comments)
    assert comments[0].startswith(retro.REPORT_MARKER)
    label = "\n\n_Part {} of %d of the report of retro #30._\n" % total
    assert all(comment.endswith(label.format(index)) for index, comment in
               enumerate(comments, 1))
    joined = "".join(comment[:-len(label.format(index))] for index, comment in
                     enumerate(comments, 1))
    assert "Line 3999 of a long finding body." in joined and "x" * 70000 in joined.replace("\n", "")
    assert retro.DOC_MARKER.split(" {")[0] in comments[-1]


@pytest.mark.parametrize("where", ["outside", "uncommitted", "changed"])
def test_file_refuses_a_draft_main_does_not_hold_and_writes_nothing(checkout, tmp_path,
                                                                     monkeypatch, where):
    writes = []
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "run_plan", lambda plan, actions: writes.append(plan))
    text = judged_draft(checkout)
    if where == "outside":
        draft = tmp_path / "draft.md"
        draft.write_text(text, encoding="utf-8")
        refusal = "is not in the checkout"
    else:
        draft = checkout / "docs" / "retro-30.md"
        if where == "changed":
            commit_doc(checkout, text.replace("Lost reports", "Lost", 1))
        draft.parent.mkdir(exist_ok=True)
        draft.write_text(text, encoding="utf-8")
        refusal = "does not hold the draft docs/retro-30.md as it stands"

    with pytest.raises(work_tickets.QueueError, match=refusal):
        retro.run_file(retro.parser().parse_args(["file", "30", "--draft", str(draft), "--repo",
                                                  REPO, "--worktree", str(checkout)]))
    assert writes == []


def test_file_without_gh_prints_the_comment_and_the_close(checkout, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    draft = commit_doc(checkout, judged_draft(checkout))

    assert retro.main(["file", "30", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the report of retro #30" in out
    assert '1. add_issue_comment {"body": "<!-- se:retro-report -->' in out
    assert ('2. issue_write {"issue_number": 30, "method": "update", "owner": "owner", '
            '"repo": "repo", "state": "closed", "state_reason": "completed"}') in out
    assert "create" not in out.replace("created", "")


def test_the_next_collect_scores_the_previous_findings(checkout, monkeypatch):
    """Retro #5's posted report held three findings in its linked doc; in the window #11 took
    finding 1 and closed, #12 took finding 2 and closed, and the check finding 2 names broke
    again."""
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    given = answers(checkout)
    block = {"version": 1, "sizes": {"closed": 7}, "window": {"retro": 5},
             "classes": [{"name": "C", "fix": "F"}], "went_well": ["Something went well."],
             "findings": [
                 finding(**{"class": "C", "title": "Name the fake door in every test"}),
                 finding(**{"class": "C", "check": "check",
                            "title": "Run the check job on every landing"}),
                 finding(**{"class": "C", "title": "A finding nobody took up yet"})]}
    draft = commit_doc(checkout, "# Retro draft for #5\n\n" + retro.BLOCK_MARKER + "\n```yaml\n"
                       + json.dumps(block) + "\n```\n", "docs/retro-5.md")
    assert retro.main(["file", "5", "--draft", str(draft), "--repo", REPO,
                       "--worktree", str(checkout)]) == 0
    given["comments-5.json"] = [{"body": tracker.calls[0][1]["body"]}]
    for item in given["issues.json"]:
        if item["number"] == 11:
            item["body"] = "Takes retro #5 finding 1."
        if item["number"] == 12:
            item["body"] = "Takes Retro #5 finding 2 and retro #4 finding 3."

    found = collected(checkout, given)
    assert found.previous["sizes"] == {"closed": 7}
    assert found.previous["findings"] == [
        {"finding": 1, "title": "Name the fake door in every test", "class": "C", "kind": "work",
         "check": "", "issues": [11], "state": "closed", "recurred": False},
        {"finding": 2, "title": "Run the check job on every landing", "class": "C",
         "kind": "work", "check": "check", "issues": [12], "state": "closed", "recurred": True},
        {"finding": 3, "title": "A finding nobody took up yet", "class": "C", "kind": "work",
         "check": "", "issues": [], "state": "none", "recurred": False}]
    text = retro.draft(found)
    assert "## The findings of retro #5" in text
    assert "| 2. Run the check job on every landing | C | work | #12 | closed | yes (check) |" in text
    assert "| 3. A finding nobody took up yet | C | work | none | none | no check named |" in text
    assert retro.read_block(text)["findings"] == []

    given["comments-5.json"] = [{"body": retro.DOC_MARKER.format(sha="f" * 40,
                                                                  path="docs/retro-5.md")}]
    with pytest.raises(work_tickets.QueueError, match="which the checkout does not hold"):
        collected(checkout, given)


def test_the_retro_template_names_the_two_commands():
    template = (Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"
                / "retro.md").read_text(encoding="utf-8")
    assert "scripts/retro.py collect <this issue> --out <draft>" in template
    assert "scripts/retro.py file <this issue> --draft <draft>" in template
