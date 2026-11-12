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
