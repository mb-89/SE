"""`review.py brief`: what a cold reviewer of a delivered pull request starts from, read through a
fake door (gh) or, without gh, from the answer files the session saved from the printed plan."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import review
import work_tickets
from quiet_git import quiet

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
    quiet(origin)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    quiet(work)
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
    quiet(root)


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


# `review.py file`: a checked review report posted as one comment on the pull request, through
# work_tickets.py's door (a fake gh here); no issue is ever created.

HEAD = "c0ffee" + "0" * 34
WORK_BODY = "## Goal\n\nA feature.\n\n## Requirements\n\n1. A feature that returns 42.\n"


def report(**changes: object) -> dict:
    """A pass without findings; `changes` replace its fields."""
    return {
        "verdict": "pass",
        "head": HEAD,
        "acceptance": [{"item": "A feature that returns 42.", "evidence": "feature.py:2 returns 42"}],
        "findings": [],
        "clean": ["feature.py: one function, no side effects"],
        **changes,
    }


def finding(title: str, blocking: bool = False) -> dict:
    return {"title": title, "evidence": f"{title}: shown by `pytest -k {title}`", "place": "x.py:1",
            "blocking": blocking, "why": "It damages the product." if blocking else "Fixable."}


class ReviewGh:
    """gh as `review.py file` uses it: the pull request and its work issue through the API, the
    comments, the body edit and the labels; an issue create fails the test."""

    def __init__(self, state: str = "open") -> None:
        self.pull = {"number": 5, "state": state, "head": {"sha": HEAD, "ref": "feat/x"},
                     "body": DESCRIPTION, "html_url": "https://github.com/owner/repo/pull/5"}
        self.issue = {"number": 7, "title": "feat/x", "state": "open", "body": WORK_BODY}
        self.comments: dict[int, list[str]] = {}
        self.labels: dict[int, list[str]] = {}
        self.calls: list[list[str]] = []

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)
        body = (Path(arguments[arguments.index("--body-file") + 1]).read_text(encoding="utf-8")
                if "--body-file" in arguments else None)
        if arguments[0] == "api":
            path = next(part for part in arguments if "/pulls/" in part or "/issues/" in part)
            return json.dumps(self.pull if "/pulls/5" in path else self.issue)
        command = arguments[:2]
        assert command != ["issue", "create"], "review.py file created an issue"
        if command in (["issue", "comment"], ["pr", "comment"]):
            self.comments.setdefault(int(arguments[2]), []).append(body)
            return "https://github.com/owner/repo/pull/5#issuecomment-1\n"
        if command == ["issue", "edit"] and body is not None:
            self.issue["body"] = body
            return ""
        if command == ["issue", "edit"] and "--add-label" in arguments:
            self.labels.setdefault(int(arguments[2]), []).append(
                arguments[arguments.index("--add-label") + 1])
            return ""
        raise AssertionError(f"unexpected gh {arguments}")


@pytest.fixture
def gh(monkeypatch) -> ReviewGh:
    fake = ReviewGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
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
    (report(verdict="fail"), "verdict is pass, pass with open points or decline"),
    (report(extra=1), "unknown field extra"),
    (report(findings=[{**finding("x"), "severity": "high"}]), "unknown field severity"),
    (report(head="c0ffee"), "names no head"),
    (report(acceptance=[{"item": "A feature.", "evidence": " "}]),
     'every acceptance item needs its evidence, and "A feature." has none'),
    (report(verdict="pass with open points", findings=[finding("x")],
            acceptance=[{"item": "A feature.", "evidence": ""}]),
     'every acceptance item needs its evidence, and "A feature." has none'),
    (report(findings=[finding("Breaks it", blocking=True)]), "so its verdict is decline"),
    (report(verdict="pass with open points", findings=[finding("Breaks it", blocking=True)]),
     "so its verdict is decline"),
    (report(findings=[finding("x")]), "its verdict is pass with open points"),
    (report(verdict="pass with open points"), "has none: its verdict is pass"),
    (report(verdict="decline", findings=[finding("x")]), "a verified blocking finding"),
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
], ids=["verdict", "unknown-field", "unknown-finding-field", "no-head", "pass-without-evidence",
        "open-points-without-evidence", "pass-with-blocker", "open-points-with-blocker",
        "pass-with-findings", "open-points-without-findings", "decline-without-blocker",
        "no-clean-list", "empty-clean-list", "finding-without-evidence", "finding-without-why",
        "finding-without-blocking", "finding-without-place", "no-acceptance", "not-an-object"])
def test_a_verdict_without_its_evidence_is_refused_and_writes_nothing(
        gh, tmp_path, capsys, given, refusal):
    assert file_report(tmp_path, given) == 1
    assert refusal in capsys.readouterr().err
    assert gh.calls == []


def test_the_refusals_set_no_quota():
    source = Path(review.__file__).read_text(encoding="utf-8").casefold()
    assert "rubber stamp" not in source and "quota" in source


def test_a_pass_without_findings_posts_one_comment_and_files_nothing(gh, tmp_path, capsys):
    assert file_report(tmp_path, report()) == 0

    comment, = gh.comments[5]
    assert list(gh.comments) == [5] and gh.labels == {} and gh.issue["body"] == WORK_BODY
    data = verdict_block(comment)
    assert data["pull"] == 5 and data["verdict"] == "pass" and data["findings"] == []
    assert data["head"] == HEAD and data["clean"] == report()["clean"]
    assert "## Review of pull request #5: pass" in comment
    assert f"`review.py brief 5`, at the head `{HEAD}`" in comment
    out = capsys.readouterr().out
    assert "Posted the review on pull request #5: pass" in out and "lands as is" in out


def test_a_pass_with_open_points_adds_them_to_the_work_issue_and_leaves_it_open(
        gh, tmp_path, capsys):
    given = report(verdict="pass with open points",
                   findings=[finding("Name the magic number"), finding("Test the edge")])
    assert file_report(tmp_path, given) == 0

    comment, = gh.comments[5]
    assert "## Review of pull request #5: pass with open points" in comment
    assert "**Name the magic number** (not blocking)" in comment
    body = gh.issue["body"]
    items = work_tickets.requirement_items(body)
    assert items[2][0] == "Changes after filing" and items[2][1].startswith(
        "Name the magic number, at x.py:1 (open point of the review of pull request #5")
    assert items[3][1].startswith("Test the edge")
    assert work_tickets.open_points(body, HEAD) == [f"{n}. {items[n][1]}" for n in (2, 3)]
    assert gh.labels == {} and list(gh.comments) == [5]
    assert not any(call[:2] == ["issue", "close"] for call in gh.calls)
    assert '#7 has 2 open point(s) under "Changes after filing"' in capsys.readouterr().out


def test_a_decline_escalates_the_work_issue_to_se(gh, tmp_path, capsys):
    given = report(verdict="decline", findings=[finding("Breaks it", blocking=True)],
                   acceptance=[{"item": "A feature that returns 42.", "evidence": ""}])
    assert file_report(tmp_path, given) == 0

    assert "## Review of pull request #5: decline" in gh.comments[5][0]
    escalation, = gh.comments[7]
    assert "Declined by the review of pull request #5" in escalation
    assert gh.labels == {7: ["escalated"]} and gh.issue["body"] == WORK_BODY
    assert "escalated #7: the review declined pull request #5" in capsys.readouterr().out


def test_a_review_of_a_landed_pull_request_waits_in_its_comment_for_se(
        monkeypatch, tmp_path, capsys):
    fake = ReviewGh(state="closed")
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    given = report(verdict="pass with open points", findings=[finding("Name it")])
    assert file_report(tmp_path, given) == 0

    comment, = fake.comments[5]
    assert verdict_block(comment)["landed"] is True and "waits here for SE" in comment
    assert list(fake.comments) == [5] and fake.labels == {} and fake.issue["body"] == WORK_BODY
    assert "the report waits on it for SE" in capsys.readouterr().out


def test_a_review_of_another_head_is_refused(gh, tmp_path, capsys):
    gh.pull["head"]["sha"] = "f" * 40
    assert file_report(tmp_path, report()) == 1
    assert "review the new head" in capsys.readouterr().err
    assert gh.comments == {}


def test_without_gh_the_reads_and_then_the_writes_are_planned(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: pytest.fail(f"gh {arguments}"))
    given = report(verdict="pass with open points", findings=[finding("Name it")])

    assert file_report(tmp_path, given) == 0
    out = capsys.readouterr().out
    assert "1. pull_request_read" in out and "2. issue_read" in out
    assert "--pull <file> --issue <file>" in out

    fake = ReviewGh()
    pull, issue = tmp_path / "pull.json", tmp_path / "issue.json"
    pull.write_text(json.dumps(fake.pull), encoding="utf-8")
    issue.write_text(json.dumps(fake.issue), encoding="utf-8")
    assert file_report(tmp_path, given, "--pull", str(pull), "--issue", str(issue)) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the review of pull request #5" in out
    comment = json.loads(out.split("1. add_issue_comment ", 1)[1].splitlines()[0])
    assert comment["issue_number"] == 5 and verdict_block(comment["body"])["verdict"] == (
        "pass with open points")
    edit = json.loads(out.split("2. issue_write ", 1)[1].splitlines()[0])
    assert edit["issue_number"] == 7 and edit["method"] == "update"
    assert work_tickets.open_points(edit["body"], HEAD)
    assert "issue_create" not in out and '"create"' not in out

    assert file_report(tmp_path, given, "--pull", str(pull)) == 1
    assert "also pass --issue" in capsys.readouterr().err
