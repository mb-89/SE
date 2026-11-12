"""`review.py brief`: what a cold reviewer of a delivered pull request starts from, read through a
fake door (gh) or, without gh, from the answer files the session saved from the printed plan."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import review
import work_tickets

REPO = "github.com/owner/repo"
ISSUE_URL = "https://github.com/owner/repo/issues/7"
FIELD_REPORT = "<!-- se:field-report -->\n**Result:** complete, every test passed\n<!-- se:field-report:end -->"
DESCRIPTION = f"Fixes {ISSUE_URL}\n\n{FIELD_REPORT}"
RULE_BOOK = "# Rule book\n\n## gen: everything we do\n\n```text\n# not a heading\n```\n"


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(root: Path, path: str, text: str) -> str:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"Change {path}")
    return git(root, "rev-parse", "HEAD")


def build_checkout(tmp_path: Path) -> None:
    """A bare origin with main (the rule book) and the delivered branch feat/x, and a reviewer's
    clone of main only, without hooks."""
    origin, work, root = tmp_path / "origin.git", tmp_path / "work", tmp_path / "main"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    git(work, "config", "user.name", "alice")
    git(work, "config", "user.email", "alice@example.com")
    git(work, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    commit(work, review.RULE_BOOK, RULE_BOOK)
    git(work, "push", "-q", "origin", "main")
    git(work, "switch", "-q", "-c", "feat/x")
    commit(work, "feature.py", "def feature():\n    return 42\n")
    git(work, "push", "-q", "origin", "feat/x")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(origin), str(root)], check=True,
                   capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path, repositories) -> Path:
    repositories(build_checkout, tmp_path)
    return tmp_path / "main"


def head(checkout: Path) -> str:
    return git(checkout.parent / "work", "rev-parse", "feat/x")


def answers(checkout: Path) -> dict[str, object]:
    """The GitHub answers, shaped as the REST API and the host's GitHub tools return them."""
    return {
        "pull": {"number": 5, "title": "feat/x", "body": DESCRIPTION,
                 "html_url": "https://github.com/owner/repo/pull/5",
                 "head": {"ref": "feat/x", "sha": head(checkout)}, "base": {"ref": "main"}},
        "issue": {"number": 7, "title": "feat/x", "state": "open", "html_url": ISSUE_URL,
                  "body": "## Requirements\n\n1. A feature that returns 42."},
        "issue_comments": [{"user": {"login": "alice"}, "created_at": "2026-11-12T10:00:00Z",
                            "body": "Also: keep it short."}],
        "checks": {"total_count": 1, "check_runs": [
            {"name": "check", "status": "completed", "conclusion": "success",
             "html_url": "https://github.com/owner/repo/actions/runs/1"}]},
        "pull_comments": [{"user": {"login": "bob"}, "created_at": "2026-11-12T11:00:00Z",
                           "body": "Delivered: all done."}],
    }


class FakeDoor:
    """The brief's reads, recorded, from `answers`."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers, self.reads = answers, []

    def read(self, name: str, *arguments: object) -> object:
        self.reads.append((name, *arguments))
        return self.answers[name]

    def pull(self, number):
        return self.read("pull", number)

    def issue(self, repo, number):
        return self.read("issue", repo, number)

    def issue_comments(self, repo, number):
        return self.read("issue_comments", repo, number)

    def checks(self, number, sha):
        return self.read("checks", number, sha)

    def pull_comments(self, number):
        return self.read("pull_comments", number)


def test_the_brief_holds_the_issue_the_diff_and_the_checks_and_not_the_field_report(checkout):
    door = FakeDoor(answers(checkout))
    text = review.text(review.brief(checkout, 5, door, REPO, claims=False))

    sha = head(checkout)
    assert ("issue", REPO, 7) in door.reads and ("checks", 5, sha) in door.reads
    assert not any(read[0] == "pull_comments" for read in door.reads)
    assert f"Review the code at {sha}, the pull request's head" in text
    assert "## The ask: #7 feat/x (open)" in text
    assert "> 1. A feature that returns 42." in text and "> Also: keep it short." in text
    assert "+    return 42" in text and "```diff" in text
    assert "- check: completed success (https://github.com/owner/repo/actions/runs/1)" in text
    assert f"## The rule book at {sha}\n\n### Rule book\n\n#### gen: everything we do" in text
    assert "# not a heading" in text and "### not a heading" not in text
    assert "## Withheld" in text and review.CLAIMS_HEADING not in text
    assert "every test passed" not in text and "Delivered: all done." not in text


def test_claims_adds_the_description_and_comments_under_their_heading(checkout):
    text = review.text(review.brief(checkout, 5, FakeDoor(answers(checkout)), REPO, claims=True))

    claims = text.split(f"## {review.CLAIMS_HEADING}\n", 1)
    assert len(claims) == 2 and "## Withheld" not in text
    assert "every test passed" not in claims[0] and "> **Result:** complete, every test passed" in claims[1]
    assert "bob wrote on 2026-11-12T11:00:00Z:\n\n> Delivered: all done." in claims[1]
    assert "none of it is evidence" in claims[1]


def test_a_pull_request_naming_no_work_issue_or_another_answer_is_refused(checkout):
    given = answers(checkout)
    given["pull"]["body"] = FIELD_REPORT
    with pytest.raises(work_tickets.QueueError, match="names no work issue"):
        review.brief(checkout, 5, FakeDoor(given), REPO, claims=False)
    given = answers(checkout)
    given["issue"]["number"] = 8
    with pytest.raises(work_tickets.QueueError, match="names #7; save issue #7"):
        review.brief(checkout, 5, FakeDoor(given), REPO, claims=False)


def test_without_gh_the_plan_is_printed(checkout, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)

    assert review.main(["brief", "5", "--claims", "--repo", REPO, "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the review brief of pull request #5" in out
    assert '1. pull_request_read {"method": "get", "owner": "owner", "pullNumber": 5' in out
    assert '"issue_number": "<issue number from step 1>", "method": "get_comments"' in out
    assert '"method": "get_check_runs"' in out and '5. pull_request_read {"method": "get_comments"' in out
    assert ("Then: review.py brief 5 --claims --pull <file> --issue <file> --issue-comments <file> "
            "--checks <file> --pull-comments <file>") in out


def test_without_gh_the_answer_files_are_read(checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    files = []
    for name, answer in answers(checkout).items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(answer), encoding="utf-8")
        if name != "pull_comments":
            files += [f"--{name.replace('_', '-')}", str(path)]

    assert review.main(["brief", "5", "--json", "--repo", REPO, "--worktree", str(checkout),
                        *files]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["issue"]["number"] == 7 and data["head"] == head(checkout)
    assert data["checks"][0]["conclusion"] == "success" and "+    return 42" in data["diff"]
    assert data["claims"] is None and "every test passed" not in json.dumps(data)

    assert review.main(["brief", "5", "--claims", "--repo", REPO, "--worktree", str(checkout),
                        *files]) == 1
    assert "also pass --pull-comments" in capsys.readouterr().err


def test_with_gh_the_reads_go_through_work_tickets_door(checkout, monkeypatch):
    given, paths = answers(checkout), []

    class Door:
        def __init__(self, root, repo):
            self.repo = repo

        def pull(self, number):
            paths.append((self.repo, f"pulls/{number}"))
            return given["pull"]

        def api(self, path):
            paths.append((self.repo, path))
            name = ("checks" if path.startswith("commits/") else
                    "issue" if path == "issues/7" else
                    "issue_comments" if path.startswith("issues/7/") else "pull_comments")
            return given[name]

    monkeypatch.setattr(work_tickets, "GitHub", Door)
    review.brief(checkout, 5, review.GhDoor(checkout, REPO), REPO, claims=True)

    assert paths == [(REPO, "pulls/5"), (REPO, "issues/7"),
                     (REPO, f"commits/{head(checkout)}/check-runs?per_page=100"),
                     (REPO, "issues/7/comments?per_page=100"),
                     (REPO, "issues/5/comments?per_page=100")]


# `review.py file`: a checked review report, its findings filed as work issues through
# work_tickets.py's door (a fake gh here), its verdict posted on the pull request.

def report(**changes: object) -> dict:
    """A passing report with one non-blocking finding; `changes` replace its fields."""
    return {
        "verdict": "pass",
        "acceptance": [{"item": "A feature that returns 42.", "evidence": "feature.py:2 returns 42"}],
        "findings": [{"title": "Name the magic number", "evidence": "feature.py:2 `return 42`",
                      "place": "feature.py:2", "blocking": False,
                      "why": "Bad but fixable: nothing is made worse."}],
        "clean": ["feature.py: one function, no side effects"],
        **changes,
    }


def finding(title: str, blocking: bool = False) -> dict:
    return {"title": title, "evidence": f"{title}: shown by `pytest -k {title}`", "place": "x.py:1",
            "blocking": blocking, "why": "It damages the product." if blocking else "Fixable."}


class IssuesGh:
    """gh as filing and commenting use it: open issues, labels and comments of one repository."""

    def __init__(self, issues: dict[int, dict] | None = None) -> None:
        self.issues = issues or {}
        self.labels: set[str] = set()
        self.comments: dict[int, list[str]] = {}
        self.calls: list[list[str]] = []

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)

        def value(flag: str) -> str:
            return arguments[arguments.index(flag) + 1]
        body = (Path(value("--body-file")).read_text(encoding="utf-8")
                if "--body-file" in arguments else "")
        command = arguments[:2]
        if command == ["label", "list"]:
            return json.dumps([{"name": name} for name in sorted(self.labels)])
        if command == ["label", "create"]:
            self.labels.add(arguments[2])
            return ""
        if command == ["issue", "list"]:
            return json.dumps([issue for issue in self.issues.values() if issue["state"] == "open"])
        if command == ["issue", "create"]:
            number = max(self.issues, default=99) + 1
            self.issues[number] = {"number": number, "title": value("--title"), "body": body,
                                   "state": "open"}
            return f"https://github.com/owner/repo/issues/{number}\n"
        if command in (["issue", "comment"], ["pr", "comment"]):
            self.comments.setdefault(int(arguments[2]), []).append(body)
            return ""
        raise AssertionError(f"unexpected gh {arguments}")


@pytest.fixture
def gh(monkeypatch, tmp_path) -> IssuesGh:
    fake = IssuesGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261112")
    return fake


def file_report(tmp_path: Path, given: object, *options: str) -> int:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(given), encoding="utf-8")
    (tmp_path / "checkout").mkdir(exist_ok=True)
    return review.main(["file", "5", "--report", str(path), "--repo", REPO,
                        "--worktree", str(tmp_path / "checkout"), *options])


def verdict_block(comment: str) -> dict:
    assert comment.startswith(review.VERDICT_MARKER + "\n")
    return json.loads(comment.split("```json\n", 1)[1].split("\n```", 1)[0])


@pytest.mark.parametrize(("given", "refusal"), [
    (report(verdict="maybe"), "verdict is pass or fail"),
    (report(extra=1), "unknown field extra"),
    (report(findings=[{**finding("x"), "severity": "high"}]), "unknown field severity"),
    (report(acceptance=[{"item": "A feature.", "evidence": " "}]),
     'A pass needs evidence for every acceptance item, and "A feature." has none'),
    (report(findings=[finding("Breaks it", blocking=True)]), "A pass has no blocking finding"),
    (report(verdict="fail"), "A fail needs a verified blocking finding"),
    ({key: value for key, value in report().items() if key != "clean"},
     'no "checked and clean" list'),
    (report(clean=[]), 'no "checked and clean" list'),
    (report(findings=[{**finding("x"), "evidence": ""}]), 'finding "x" has no evidence'),
    (report(findings=[{**finding("x"), "why": ""}]), 'finding "x" has no judgment'),
    (report(findings=[{key: value for key, value in finding("x").items() if key != "blocking"}]),
     'finding "x" has no judgment'),
    (report(findings=[{**finding("x"), "place": ""}]), 'finding "x" names no place'),
    (report(acceptance=[]), "names no acceptance item"),
    ([], "a JSON object"),
], ids=["verdict", "unknown-field", "unknown-finding-field", "pass-without-evidence",
        "pass-with-blocker", "fail-without-blocker", "no-clean-list", "empty-clean-list",
        "finding-without-evidence", "finding-without-why", "finding-without-blocking",
        "finding-without-place", "no-acceptance", "not-an-object"])
def test_a_report_breaking_the_rules_is_refused_and_writes_nothing(
        gh, tmp_path, capsys, given, refusal):
    assert file_report(tmp_path, given) == 1
    assert refusal in capsys.readouterr().err
    assert gh.calls == []


def test_a_pass_files_its_findings_and_posts_the_verdict(gh, tmp_path, capsys):
    assert file_report(tmp_path, report()) == 0

    issue = gh.issues[100]
    assert issue["title"] == "fix/name-the-magic-number-20261112"
    assert work_tickets.FLEET_MARKER in issue["body"] and "feature.py:2" in issue["body"]
    assert "https://github.com/owner/repo/pull/5" in issue["body"]
    assert work_tickets.requirement_items(issue["body"])
    comment, = gh.comments[5]
    data = verdict_block(comment)
    assert data["pull"] == 5 and data["verdict"] == "pass" and data["unfiled"] == 0
    assert data["findings"][0]["issue"] == 100 and data["clean"] == report()["clean"]
    assert "## Review of pull request #5: PASS" in comment
    out = capsys.readouterr().out
    assert "Filed work issue https://github.com/owner/repo/issues/100" in out
    assert "Posted the verdict on pull request #5" in out


def test_a_fail_files_its_blocking_finding_first(gh, tmp_path, capsys):
    given = report(verdict="fail", findings=[finding("fixable"), finding("damage", blocking=True)])
    assert file_report(tmp_path, given) == 0

    assert [issue["title"] for issue in gh.issues.values()] == [
        "fix/damage-20261112", "fix/fixable-20261112"]
    data = verdict_block(gh.comments[5][0])
    assert data["verdict"] == "fail"
    assert [(item["title"], item["issue"]) for item in data["findings"]] == [
        ("fixable", 101), ("damage", 100)]
    assert "## Review of pull request #5: FAIL" in gh.comments[5][0]


def test_at_most_max_filed_findings_are_filed_and_the_rest_counted(gh, tmp_path, capsys):
    findings = [finding(f"finding {number}") for number in range(7)]
    assert file_report(tmp_path, report(findings=findings)) == 0
    assert len(gh.issues) == review.MAX_FILED == 5
    data = verdict_block(gh.comments[5][0])
    assert data["unfiled"] == 2 and data["max_filed"] == 5
    assert [item["issue"] for item in data["findings"][5:]] == [None, None]
    assert "2 more finding(s) counted, not filed" in gh.comments[5][0]

    (tmp_path / "checkout" / "se.toml").write_text("[review]\nmax_filed = 1\n", encoding="utf-8")
    gh.issues.clear()
    assert file_report(tmp_path, report(findings=findings[:3])) == 0
    assert len(gh.issues) == 1 and verdict_block(gh.comments[5][1])["unfiled"] == 2

    (tmp_path / "checkout" / "se.toml").write_text("[review]\nmax_filed = -1\n", encoding="utf-8")
    calls = len(gh.calls)
    assert file_report(tmp_path, report()) == 1
    assert "max_filed" in capsys.readouterr().err and len(gh.calls) == calls


def test_a_finding_whose_twin_is_open_files_nothing(gh, tmp_path, capsys):
    gh.issues[7] = {"number": 7, "title": "fix/name-the-magic-number-20261101",
                    "body": "Filed by an earlier review.", "state": "open"}
    assert file_report(tmp_path, report()) == 0

    assert sorted(gh.issues) == [7]
    assert "would have filed" in gh.comments[7][0]
    data = verdict_block(gh.comments[5][0])
    assert data["findings"][0]["issue"] is None and data["findings"][0]["twin"] == 7
    assert "Not filed: #7" in capsys.readouterr().out


def test_without_gh_the_plans_are_printed_and_the_answers_read(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261112")
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: pytest.fail(f"gh {arguments}"))
    given = report(findings=[finding("one"), finding("two")])

    assert file_report(tmp_path, given) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: file fix/one-20261112" in out and "GitHub plan: file fix/two-20261112" in out
    assert "review.py file 5 --report" in out and "--filed <file>" in out

    answers = tmp_path / "filed.json"
    answers.write_text(json.dumps([{"number": 12}, {"twin": 3}]), encoding="utf-8")
    assert file_report(tmp_path, given, "--filed", str(answers)) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the verdict on pull request #5" in out
    step = json.loads(out.split("1. add_issue_comment ", 1)[1].splitlines()[0])
    assert step["issue_number"] == 5 and step["owner"] == "owner"
    data = verdict_block(step["body"])
    assert [(item["issue"], item["twin"]) for item in data["findings"]] == [(12, None), (None, 3)]

    answers.write_text(json.dumps([{"number": 12}]), encoding="utf-8")
    assert file_report(tmp_path, given, "--filed", str(answers)) == 1
    assert "2 findings to file, and --filed answers 1" in capsys.readouterr().err
