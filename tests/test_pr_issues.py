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

REPO = "carol/SE"
TOKEN = "actions-token"
ISSUE_URL = f"https://github.com/{REPO}/issues"
PULL_URL = f"https://github.com/{REPO}/pull"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "check.yml"


class FakeGitHub:
    """GET /repos/<repo>/issues/<n> from `items`; refuses a request without the token."""

    def __init__(self) -> None:
        self.items: dict[int, dict] = {}
        self.requests: list[str] = []
        self.failures: list[int] = []  # the statuses of the next requests, before any answer
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server's name
                fake.requests.append(self.path)
                if fake.failures:
                    self.send_response(fake.failures.pop(0))
                    self.end_headers()
                    return
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
        head: str = "topic", gate: str | None = None,
        capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The job's step: the event file, the token and the repository as Actions passes them."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "pull_request": {"number": 900, "body": body, "base": {"ref": base},
                         "head": {"ref": head}, "user": {"login": author},
                         "labels": [{"name": label} for label in labels]},
        "repository": {"full_name": REPO, "owner": {"login": "carol"}},
    }), encoding="utf-8")
    env = {"GITHUB_EVENT_PATH": str(event), "GITHUB_TOKEN": token, "GITHUB_REPOSITORY": REPO,
           "GITHUB_API_URL": github.url}
    code = pr_issues.main(["--repo", str(tmp_path), *((gate,) if gate else ())], env)
    return code, capsys.readouterr().out


def test_a_pull_request_naming_no_issue_is_refused_with_the_remedy(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, "Some work done outside the issue system.", capsys=capsys)
    assert code == 1, out
    assert "::error::pr-issues: pull request #900 names no open issue of carol/SE labelled work" in out
    assert "Refs <issue url>" in out
    assert github.requests == [f"/repos/{REPO}/issues/900"]  # read once as it is now, not found


def authorized_fix_body() -> str:
    report = (
        "<!-- se:field-report -->\n"
        "**Work issue:** none, authorized fix  **Branch:** `fix/example`  "
        "**Result:** complete\n"
        "<!-- se:field-report:end -->"
    )
    return f"Work issue: none, authorized fix\n\n{report}"


def test_an_explicit_authorized_fix_passes_without_reading_an_issue(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, authorized_fix_body(), capsys=capsys)
    assert code == 0, out
    assert "Work issue: none, authorized fix" in out
    assert github.requests == []


def test_an_authorized_fix_declaration_does_not_hide_an_issue_reference(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = authorized_fix_body() + "\nRefs #8\n"
    assert not pr_issues.authorized_fix(body, REPO)
    report = tmp_path / "report.md"
    report.write_text(body, encoding="utf-8")

    code = pr_issues.main(["--work-issue", str(report), "--repository", REPO], {})

    assert code == 1
    assert capsys.readouterr().out == ""


def test_a_landing_passes_when_its_work_pull_request_declares_an_authorized_fix(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.pull(20, authorized_fix_body())
    code, out = run(github, tmp_path, f"Lands {PULL_URL}/20", capsys=capsys)
    assert code == 0, out
    assert "Work issue: none, authorized fix" in out


def test_a_retro_report_pull_request_needs_its_open_retro_issue(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(50, "retro")
    github.items[50]["title"] = "retro-due-20261125"
    body = "Refs #50\n\n<!-- se:retro-report 50 -->"
    code, out = run(github, tmp_path, body, capsys=capsys)
    assert code == 0, out
    assert "Retro report #50: open retro issue" in out
    assert "passed" in out
    assert run(github, tmp_path, "Refs #50\n\n", capsys=capsys)[0] == 1
    github.items[50]["state"] = "closed"
    code, out = run(github, tmp_path, body, capsys=capsys)
    assert code == 1 and "is closed, does not count" in out


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
    code, out = run(github, tmp_path, "Tidy up.", author="carol", labels=("housekeeping",),
                    capsys=capsys)
    assert (code, out.strip()) == (0, "pr-issues: pull request #900 is the owner's housekeeping: exempt")
    assert run(github, tmp_path, "Tidy up.", author="alice", labels=("housekeeping",),
               capsys=capsys)[0] == 1
    assert run(github, tmp_path, "Tidy up.", author="carol", capsys=capsys)[0] == 1


def test_the_owners_release_landing_is_exempt_and_no_one_elses_nor_another_branch(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """docs/settings.md "Project settings": `work_tickets.py release` lands `land/release-v<version>`,
    which names no work issue."""
    code, out = run(github, tmp_path, "Release v1.2.4", author="carol",
                    head="land/release-v1.2.4", capsys=capsys)
    assert (code, out.strip()) == (
        0, "pr-issues: pull request #900 is the owner's release landing land/release-v1.2.4: exempt")
    assert github.requests == []
    assert run(github, tmp_path, "Release v1.2.4", author="alice", head="land/release-v1.2.4",
               capsys=capsys)[0] == 1
    for head in ("land/release-v1.2", "land/release-v1.2.4-x", "land/topic", "release-v1.2.4"):
        assert run(github, tmp_path, "Release v1.2.4", author="carol", head=head,
                   capsys=capsys)[0] == 1, head


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


def test_a_single_server_error_is_read_again_once_and_the_rule_judges(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr_issues, "RETRY_SECONDS", 0)
    github.issue(8, "work")
    github.failures = [502]
    code, out = run(github, tmp_path, "Refs #8", capsys=capsys)
    assert code == 0 and len(github.requests) == 2
    assert "::warning::pr-issues: GET issue #8: HTTP 502; reading it once more" in out


def test_a_second_server_error_fails_the_check_as_a_setup_error(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr_issues, "RETRY_SECONDS", 0)
    github.issue(8, "work")
    github.failures = [503, 502]
    code, out = run(github, tmp_path, "Refs #8", capsys=capsys)
    assert code == 2 and len(github.requests) == 2
    assert "::error::pr-issues: GET issue #8: HTTP 502" in out


def test_the_check_job_runs_the_rule_on_pull_requests_with_the_actions_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text[text.index("python3 scripts/pr_issues.py") - 600:text.index("python3 scripts/pr_issues.py")]
    assert "if: github.event_name == 'pull_request'" in step
    assert "GITHUB_TOKEN: ${{ github.token }}" in step
    assert "issues: read" in text


def test_the_field_report_job_skips_issue_body_fetch_for_the_authorized_fix_sentinel() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: The pull request's field report follows the template")
    end = text.index("\n      - name:", start + 1)
    step = text[start:end]
    authorized = step.index('if [ "$issue" = none ]; then')
    issue_fetch = step.index('gh api "repos/$REPOSITORY/issues/$issue"')
    issue_argument = step.index('issue_args=(--issue-body "$RUNNER_TEMP/issue-body.md")')

    assert authorized < issue_fetch < issue_argument


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


def test_field_report_step_returns_the_authorized_fix_sentinel(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = tmp_path / "body.md"
    body.write_text(authorized_fix_body(), encoding="utf-8")
    code = pr_issues.main(["--work-issue", str(body), "--repository", REPO], {})
    assert (code, capsys.readouterr().out.strip()) == (0, "none")


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


def test_a_pull_request_created_with_its_label_passes_on_its_opened_event(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # gh pr create --label opens the pull request, then labels it: the opened event has no label.
    github.items[900] = {"number": 900, "state": "open", "body": "Tidy the docs.",
                         "labels": [{"name": "housekeeping"}],
                         "pull_request": {"url": f"{PULL_URL}/900"}}
    code, out = run(github, tmp_path, "Tidy the docs.", author="carol", capsys=capsys)
    assert code == 0, out
    assert "as it is now" in out and "is the owner's housekeeping: exempt" in out


def test_a_pull_request_whose_description_names_its_issue_after_opening_passes(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.issue(5, "work")
    github.items[900] = {"number": 900, "state": "open", "body": f"Refs {ISSUE_URL}/5",
                         "labels": [], "pull_request": {"url": f"{PULL_URL}/900"}}
    code, out = run(github, tmp_path, "", capsys=capsys)
    assert code == 0, out
    assert "Refs #5: open work issue" in out


# CI's release-kind gate (pr_issues.py --release-kind): every pull request into the integration
# branch states its kind, whichever way it is merged.

KIND = "--release-kind"
ACTION = Path(__file__).resolve().parents[1] / ".github" / "actions" / "release-kind" / "action.yml"


@pytest.mark.parametrize("author, labels", [("alice", ()), ("carol", ("housekeeping",))],
                         ids=["anyone", "the-owners-housekeeping"])
def test_a_pull_request_stating_no_kind_is_refused_naming_the_line_to_add(
        github: FakeGitHub, tmp_path: Path, author: str, labels: tuple[str, ...],
        capsys: pytest.CaptureFixture[str]) -> None:
    # #1812 and #1813 of 24 Nov: a quick fix's description, merged by GitHub's own squash.
    body = "Integrate fix/retro-doc-size-exemption: retro reports are exempt from the size cap.\n"
    code, out = run(github, tmp_path, body, author=author, labels=labels, gate=KIND, capsys=capsys)
    assert code == 1, out
    assert ("::error::release-kind: pull request #900 into main states no release kind: add the "
            "line `Release-kind: major|minor|patch` to the description") in out
    assert github.requests == [f"/repos/{REPO}/issues/900"]  # read once as it is now, not found


def test_a_field_report_a_landing_and_a_release_each_pass_by_the_kind_they_state(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import work_tickets  # scripts/ is on the path (tests/conftest.py)

    bodies = {
        "patch": f"Refs {ISSUE_URL}/5\n\n<!-- se:field-report -->\n**Release kind:** patch — a fix\n",
        "minor": work_tickets.landing_description(f"{PULL_URL}/7", 7, f"{ISSUE_URL}/5", "minor"),
        "major": work_tickets.release_description("v2.0.0", "feat/x: major", "major"),
    }
    for kind, body in bodies.items():
        code, out = run(github, tmp_path, body, gate=KIND, capsys=capsys)
        assert code == 0 and f"release-kind: pull request #900 into main states {kind}" in out, out
    assert github.requests == []  # the event's description states it: nothing is read


@pytest.mark.parametrize("body, said", [
    ("Release-kind: minor\n\nRelease-kind: patch\n", "states 'minor', 'patch'"),
    ("Release-kind: huge\n", "states 'huge'"),
    ("<!-- **Release kind:** patch|minor|major — <reason> -->\n", "states no release kind"),
], ids=["two", "unknown", "in-a-comment"])
def test_two_kinds_an_unknown_one_or_one_in_a_comment_is_refused(
        github: FakeGitHub, tmp_path: Path, body: str, said: str,
        capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(github, tmp_path, body, gate=KIND, capsys=capsys)
    assert code == 1 and f"into main {said}: add the line" in out, out


def test_a_kind_stated_after_opening_passes_and_another_branch_is_not_checked(
        github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.items[900] = {"number": 900, "state": "open", "body": "Tidy.\n\nRelease-kind: patch\n",
                         "labels": [], "pull_request": {"url": f"{PULL_URL}/900"}}
    code, out = run(github, tmp_path, "Tidy.", gate=KIND, capsys=capsys)
    assert code == 0 and "as it is now" in out and "states patch" in out, out
    code, out = run(github, tmp_path, "Tidy.", base="next", gate=KIND, capsys=capsys)
    assert code == 0 and "targets next, not main: not checked" in out


def test_the_check_job_calls_the_release_kind_action_and_it_runs_the_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    at = text.index("uses: ./.github/actions/release-kind")
    step = text[text.rindex("- name:", 0, at):at]
    assert "if: github.event_name == 'pull_request'" in step
    action = ACTION.read_text(encoding="utf-8")
    assert ('python3 "$GITHUB_ACTION_PATH/../../../scripts/pr_issues.py" --release-kind '
            '--repo "$WORKTREE"') in action
    assert "GITHUB_TOKEN: ${{ inputs.token }}" in action and "default: ${{ github.token }}" in action
