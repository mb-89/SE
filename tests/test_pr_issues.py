"""CI's issue rule: a pull request into main names an open work issue (scripts/pr_issues.py), run as
the job runs it, against a fake GitHub REST API that checks the Actions token."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

import pr_issues

REPO = "mb-89/SE"
TOKEN = "actions-token"
ISSUE_URL = f"https://github.com/{REPO}/issues"
PULL_URL = f"https://github.com/{REPO}/pull"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "check.yml"


class FakeGitHub:
    """GET /repos/<repo>/issues/<n> from `items`; refuses a request without the token."""

    def __init__(self) -> None:
        self.items: dict[int, dict] = {}
        self.requests: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server's name
                fake.requests.append(self.path)
                prefix = f"/repos/{REPO}/issues/"
                number = self.path.removeprefix(prefix)
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self.send_response(401)
                    self.end_headers()
                    return
                item = fake.items.get(int(number)) if number.isdigit() else None
                if not self.path.startswith(prefix) or item is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(item).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def issue(self, number: int, *labels: str, state: str = "open") -> None:
        self.items[number] = {"number": number, "state": state,
                              "labels": [{"name": label} for label in labels]}

    def pull(self, number: int, body: str) -> None:
        self.items[number] = {"number": number, "state": "open", "labels": [], "body": body,
                              "pull_request": {"url": f"{PULL_URL}/{number}"}}


@pytest.fixture
def github() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    # serve_forever looks for shutdown every poll_interval; its default, 0.5 s, cost each test as much.
    thread = threading.Thread(target=fake.server.serve_forever, kwargs={"poll_interval": 0.01},
                              daemon=True)
    thread.start()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def run(github: FakeGitHub, tmp_path: Path, body: str, *, base: str = "main",
        author: str = "alice", labels: tuple[str, ...] = (), token: str = TOKEN,
        capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The job's step: the event file, the token and the repository as Actions passes them."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "pull_request": {"number": 900, "body": body, "base": {"ref": base},
                         "user": {"login": author},
                         "labels": [{"name": label} for label in labels]},
        "repository": {"full_name": REPO, "owner": {"login": "mb-89"}},
    }), encoding="utf-8")
    env = {"GITHUB_EVENT_PATH": str(event), "GITHUB_TOKEN": token, "GITHUB_REPOSITORY": REPO,
           "GITHUB_API_URL": github.url}
    code = pr_issues.main(["--repo", str(tmp_path)], env)
    return code, capsys.readouterr().out


def test_a_pull_request_naming_no_issue_is_refused_with_the_remedy(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, "Some work done outside the issue system.", capsys=capsys)
    assert code == 1, out
    assert "::error::pr-issues: pull request #900 names no open issue of mb-89/SE labelled work" in out
    assert "Refs <issue url>" in out
    assert github.requests == []


def test_a_closed_or_unlabelled_issue_does_not_count(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(5, "work", state="closed")
    github.issue(6, "design")
    code, out = run(github, tmp_path, f"Fixes {ISSUE_URL}/5\nRefs #6\nCloses #7", capsys=capsys)
    assert code == 1, out
    assert "Fixes #5: is closed, does not count" in out
    assert "Refs #6: is not labelled work, does not count" in out
    assert "Closes #7: does not exist, does not count" in out


def test_an_open_work_issue_passes_among_several_by_number_or_url(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(5, "work", state="closed")
    github.issue(8, "work", "in-progress")
    body = f"Refs #5\n\nfixes {ISSUE_URL}/8, and Refs https://github.com/other/repo/issues/9"
    code, out = run(github, tmp_path, body, capsys=capsys)
    assert code == 0, out
    assert "Fixes #8: open work issue" in out and "passed" in out
    assert f"/repos/{REPO}/issues/9" not in github.requests


def test_a_landing_passes_by_the_work_pull_request_it_lands(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(8, "work")
    github.pull(20, f"Refs {ISSUE_URL}/8\n\n<!-- se:field-report -->")
    body = f"Lands {PULL_URL}/20, whose description is the field report.\n\n<!-- se:field-report-in 20 -->\n"
    code, out = run(github, tmp_path, body, capsys=capsys)
    assert code == 0, out
    assert "Lands #20: pull request, its description:" in out and "Refs #8: open work issue" in out


def test_a_landing_whose_work_pull_request_names_no_work_issue_is_refused(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(8, "work", state="closed")
    github.pull(20, f"Refs {ISSUE_URL}/8")
    github.pull(21, "Lands #20")
    code, out = run(github, tmp_path, "Lands #21\nRefs #20", capsys=capsys)
    assert code == 1, out
    assert "Lands #20: a landing's landing does not count" in out
    assert "Refs #20: is a pull request, does not count" in out


def test_the_owners_housekeeping_pull_request_is_exempt_and_no_one_elses(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, "Tidy up.", author="mb-89", labels=("housekeeping",),
                    capsys=capsys)
    assert (code, out.strip()) == (0, "pr-issues: pull request #900 is the owner's housekeeping: exempt")
    assert run(github, tmp_path, "Tidy up.", author="alice", labels=("housekeeping",),
               capsys=capsys)[0] == 1
    assert run(github, tmp_path, "Tidy up.", author="mb-89", capsys=capsys)[0] == 1


def test_a_pull_request_into_another_branch_is_not_checked(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "se.toml").write_text('[project]\nintegration_branch = "next"\n', encoding="utf-8")
    assert run(github, tmp_path, "Anything.", base="next", capsys=capsys)[0] == 1
    code, out = run(github, tmp_path, "Anything.", base="main", capsys=capsys)
    assert code == 0 and "targets main, not next: not checked" in out


def test_a_refused_token_is_a_setup_error_not_a_verdict(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, "Refs #8", token="wrong", capsys=capsys)
    assert code == 2 and "::error::pr-issues: GET issue #8: HTTP 401" in out


def test_the_check_job_runs_the_rule_on_pull_requests_with_the_actions_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text[text.index("python3 scripts/pr_issues.py") - 600:text.index("python3 scripts/pr_issues.py")]
    assert "if: github.event_name == 'pull_request'" in step
    assert "GITHUB_TOKEN: ${{ github.token }}" in step
    assert "issues: read" in text


@pytest.mark.parametrize("first_line, number", [
    ("Refs #627", 627),
    (f"Refs {ISSUE_URL}/627", 627),
    (f"Fixes {ISSUE_URL}/627", 627),
    ("Closes #627", 627),
    (f"Lands {PULL_URL}/628", 628),
    ("Refs https://github.com/other/repo/issues/627", None),
    ("Work on it\nRefs #627", None),  # only the first line names the work issue
])
def test_one_parser_names_the_work_issue_for_both_checks(first_line: str, number: int | None,
                                                         tmp_path: Path,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    assert pr_issues.work_issue(first_line, REPO) == number
    body = tmp_path / "body.md"
    body.write_text(f"{first_line}\n\n<!-- se:field-report -->\n", encoding="utf-8")
    code = pr_issues.main(["--work-issue", str(body), "--repository", REPO], {})
    assert (code, capsys.readouterr().out.strip()) == ((0, str(number)) if number else (1, ""))


@pytest.mark.parametrize("body, passed", [
    ("Refs #8", True),
    (f"Refs {ISSUE_URL}/8", True),
    ("Refs https://github.com/other/repo/issues/8", False),
])
def test_pr_issues_takes_the_short_and_the_full_form_of_its_own_repository_only(
        github: FakeGitHub, tmp_path: Path, body: str, passed: bool,
        capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(8, "work")
    assert run(github, tmp_path, body, capsys=capsys)[0] == (0 if passed else 1)
