"""work_tickets.py reads work issues and pull requests, and writes pull requests whose descriptions
carry the field report, through gh (mocked here)."""
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)
TESTED_MAIN = work_tickets.tested_main
REAL_GITHUB = work_tickets.GitHub
REAL_HAND_OFF = work_tickets.hand_off

BRANCH = "feature/example-20261104"
URL = "https://git.example/owner/repo/issues/5"
BODY = """## Goal

Make the example work.

## User requirement (verbatim)

> make it "work", please

## Design owner

docs/design.md "Example".

## Requirements

1. `make install-tools`: installs every tool.
   Continued line of the first requirement.
2. Issue tooling in `scripts/work_tickets.py`.

## Acceptance

- [ ] Setup reports every tool.
- [ ] Tooling has tests.

## Verification

```powershell
## not a heading inside a fence
uv run pytest
```
"""

EVIDENCE_ROWS = """| Requirement 1 | complete | `abc1234` | `test`: passed |
| Requirement 2 | complete | `abc1234` | `test`: passed |
| Acceptance 1 | complete | `abc1234` | `test`: passed |
| Acceptance 2 | complete | `abc1234` | `test`: passed |"""


BEGIN, END = work_tickets.REPORT_BEGIN, work_tickets.REPORT_END
COMPLETE_REPORT = BEGIN + """
**Work issue:** #5  **Branch:** `feature/example-20261104`  **Result:** complete
**Tested against `main`:** `abc1234`
**Branch tip:** `abc1234`  **Re-integration kind:** patch
**Release kind:** minor — adds an example command

## User requirement (quoted back)

> make it "work", please

## Delivered

| Work issue item | Result | Commits | Evidence |
|---|---|---|---|
""" + EVIDENCE_ROWS + """

**Commit groupings:** None

**Suite time:** None

## Not delivered

None

## Removed behaviour, deleted or weakened tests, and authored prose

None

## Review responses

None

## Decisions

| Decision | Alternatives | Rationale | Confidence |
|---|---|---|---|

## Spec gaps

None.

## Tickets for other repositories

None

## Retro

- **Went well:** the tests.
- **Cost time:** nothing.
- **Proposed improvement:** none.
""" + END + "\n"


TIP = "fedcba9876543210fedcba9876543210fedcba98"


def reported_at(tip: str) -> str:
    """COMPLETE_REPORT describing the branch at `tip`."""
    return COMPLETE_REPORT.replace("**Branch tip:** `abc1234`", f"**Branch tip:** `{tip}`")

def fill_evidence_rows(report: str) -> str:
    """`report` with its evidence rows and its Release kind's reason filled in."""
    return report.replace("|---|---|---|---|", "|---|---|---|---|\n" + EVIDENCE_ROWS).replace(
        "<reason>", "adds an example command")


def draft_complete_field_report(worktree: Path) -> Path:
    report = worktree / ".se" / "work" / "field-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    work_tickets.draft_field_report(worktree, report)
    report.write_text(
        fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
            "**Result:** complete | partial", "**Result:** complete"
        ),
        encoding="utf-8",
    )
    return report


class FakeGh:
    def __init__(self) -> None:
        self.issue = {"number": 5, "title": BRANCH, "body": BODY, "url": URL,
                      "updatedAt": "2026-11-04T10:00:00Z", "comments": []}
        self.open_reports: list[dict] = []
        self.pull_request: dict | None = {
            "number": 7, "url": "https://git.example/owner/repo/pull/7",
        }
        self.pull_request_state = "open"
        self.calls: list[list[str]] = []
        self.bodies: list[str] = []

    def comment(self, identifier: str, body: str) -> None:
        self.issue["comments"].append({
            "id": identifier, "author": {"login": "dispatcher"}, "body": body,
            "createdAt": "2026-11-04T11:00:00Z", "url": f"{URL}#issuecomment-{identifier}"})

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)
        if "--body-file" in arguments:
            body_file = Path(arguments[arguments.index("--body-file") + 1])
            self.bodies.append(body_file.read_text(encoding="utf-8"))
        command = arguments[:2]
        if command == ["issue", "view"]:
            return json.dumps(self.issue)
        if command == ["pr", "list"]:
            return json.dumps(
                [self.pull_request]
                if self.pull_request is not None and self.pull_request_state == "open"
                else []
            )
        if command == ["pr", "view"]:
            return json.dumps(self.pull_request)
        if command == ["pr", "create"]:
            self.pull_request = {"number": 7, "url": "https://git.example/owner/repo/pull/7"}
            return self.pull_request["url"] + "\n"
        if command == ["issue", "list"]:
            return json.dumps(self.open_reports)
        if command == ["issue", "create"]:
            self.open_reports.append({
                "number": 8,
                "title": arguments[arguments.index("--title") + 1],
                "url": "https://git.example/owner/repo/issues/8",
            })
            return "https://git.example/owner/repo/issues/8\n"
        if command == ["api", "repos/owner/repo/issues/4"]:
            return "33412961\n"
        return ""


IDENTITY = '[project]\nidentity = "mb <mb>"\n'


@pytest.fixture(autouse=True)
def local_config(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "home" / ".se" / "local.toml"
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def local_runner(monkeypatch) -> None:
    """Every test starts on a local machine, whatever runs the suite: a GitHub Actions runner sets
    GITHUB_ACTIONS, which makes `start` a cloud start; a test that needs the cloud sets it."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("SE_CLOUD_AGENT", raising=False)


@pytest.fixture
def gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "current_branch", lambda root: BRANCH)
    monkeypatch.setattr(work_tickets, "tested_main", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "branch_tip", lambda root: TIP)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    # The worktree is no git repository; tests/test_work_tickets.py runs the guard on a real one.
    monkeypatch.setattr(work_tickets, "guard", lambda root, branch, report: [])
    return fake


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A worker's checkout; its se.toml sets the project identity that push needs."""
    root = tmp_path / "worktree"
    root.mkdir()
    (root / "se.toml").write_text(IDENTITY, encoding="utf-8")
    return root


def run(worktree: Path, *arguments: str) -> int:
    return work_tickets.main([*arguments, "--worktree", str(worktree)])


def test_intake_writes_one_ticket_per_requirement_and_a_delivery_ticket(worktree, gh, capsys):
    assert run(worktree, "intake", "--issue", "5", "--repo", "git.example/owner/repo") == 0
    assert gh.calls[0] == ["issue", "view", "5", "--json", work_tickets.ISSUE_FIELDS,
                           "--repo", "git.example/owner/repo"]
    todo = worktree / ".se" / "work" / "todo"
    assert sorted(path.name for path in todo.iterdir()) == [
        "delivery.md", "r1-make-install-tools-installs-every-tool.md",
        "r2-issue-tooling-in-scripts-work-tickets-py.md"]
    first = (todo / "r1-make-install-tools-installs-every-tool.md").read_text(encoding="utf-8")
    assert first.startswith("# r1-make-install-tools-installs-every-tool: `make install-tools`: ")
    assert "Continued line of the first requirement." in first
    assert 'docs/design.md "Example".' in first and URL in first
    second = (todo / "r2-issue-tooling-in-scripts-work-tickets-py.md").read_text(encoding="utf-8")
    assert "`r1-make-install-tools-installs-every-tool`" in second.split("## Dependencies")[1]
    delivery = (todo / "delivery.md").read_text(encoding="utf-8")
    assert "- [ ] Setup reports every tool.\n- [ ] Tooling has tests.\n" in delivery
    assert "## not a heading inside a fence" in delivery
    report = work_tickets.status_report(worktree)
    assert report["errors"] == [] and report["counts"]["todo"] == 3
    snapshot = json.loads((worktree / ".se" / "work" / "issue.json").read_text(encoding="utf-8"))
    assert snapshot["repo"] == "git.example/owner/repo" and snapshot["number"] == 5

    gh.issue["body"] = BODY.replace("2. Issue", "2. Changed issue")
    capsys.readouterr()
    assert run(worktree, "intake", "--issue", "5") == 0
    output = capsys.readouterr().out
    assert "created" not in output and output.count("kept existing ticket") == 3


def test_intake_warns_on_a_bare_cross_repository_reference(worktree, gh, capsys):
    gh.issue["body"] = BODY.replace("## Design owner", """See other/list#3 for the list.

Quoted from https://git.example/other/spec/issues/9:

> The spec passage the worker needs.

Our own owner/repo#4 and https://git.example/owner/repo/issues/2 need no quote.

Not repositories: https://docs.example.com/3/library/re.html, https://gitlab.example/a/b/issues/1
and https://github.com/a/b/releases/tag/v1.

Bare: https://github.com/a/b/issues/3 and https://git.example/c/d/blob/main/x.md.

## Design owner""")
    assert run(worktree, "intake", "--issue", "5", "--repo", "git.example/owner/repo") == 0
    warnings = [line for line in capsys.readouterr().err.splitlines() if "warning" in line]
    assert len(warnings) == 3
    assert "intake: work issue #5 cites other/list#3 with no quoted block" in warnings[0]
    assert "cites https://github.com/a/b/issues/3 with no quoted block" in warnings[1]
    assert "cites https://git.example/c/d/blob/main/x.md with no quoted block" in warnings[2]
    assert '"Writing work issues"' in warnings[0]


def test_discovery_intake_creates_an_evidence_index_and_probe_appends_to_it(worktree, gh):
    assert run(worktree, "intake", "--issue", "5", "--discovery") == 0

    evidence = worktree / ".se" / "work" / "probe" / "evidence.md"
    assert evidence.read_text(encoding="utf-8") == (
        "# Discovery evidence\n\n"
        "| Command | Output |\n"
        "|---|---|\n"
    )

    assert run(
        worktree, "probe", "--command", "uv run python inspect.py",
        "--output", ".se/work/probe/result.json",
    ) == 0
    assert "| `uv run python inspect.py` | `.se/work/probe/result.json` |" in evidence.read_text(
        encoding="utf-8"
    )


def test_discovery_label_creates_evidence_oriented_tickets(worktree, gh):
    gh.issue["labels"] = [{"name": "work"}, {"name": "discovery"}]

    assert run(worktree, "intake", "--issue", "5") == 0

    evidence = worktree / ".se" / "work" / "probe" / "evidence.md"
    ticket = next((worktree / ".se" / "work" / "todo").glob("r1-*.md"))
    delivery = (worktree / ".se" / "work" / "todo" / "delivery.md").read_text(encoding="utf-8")
    assert evidence.is_file()
    assert "Discovery evidence is recorded in the evidence index." in ticket.read_text(encoding="utf-8")
    assert "focused tests" not in ticket.read_text(encoding="utf-8")
    assert "Discovery evidence from the work issue." in delivery
    assert "Discovery evidence is complete and linked from the field report." in delivery
    assert "Tests:" not in delivery

    ticket.write_text(ticket.read_text(encoding="utf-8").replace(
        "- [ ] Requirement 1", "- [x] Requirement 1"
    ).replace(
        "- [ ] Discovery evidence", "- [x] Discovery evidence"
    ) + "\nEvidence collected.\n", encoding="utf-8")
    assert run(worktree, "move", "--id", ticket.stem, "--to", "held") == 0
    assert run(worktree, "move", "--id", ticket.stem, "--to", "done") == 0

    assert run(worktree, "move", "--id", "delivery", "--to", "held") == 0
    assert run(worktree, "move", "--id", "delivery", "--to", "done") == 1


def test_discovery_intake_uses_the_project_declared_probe_root(worktree, gh):
    assert run(
        worktree, "intake", "--issue", "5", "--discovery",
        "--probe-root", ".se/work/project-probe",
    ) == 0

    evidence = worktree / ".se" / "work" / "project-probe" / "evidence.md"
    assert evidence.is_file()
    assert json.loads((worktree / ".se" / "work" / "discovery.json").read_text(
        encoding="utf-8"
    )) == {"root": ".se/work/project-probe"}


def test_refresh_reports_edited_requirements_and_new_comments(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    capsys.readouterr()
    assert run(worktree, "refresh") == 0
    assert "unchanged since the last read" in capsys.readouterr().out

    gh.issue["body"] = BODY.replace("2. Issue tooling", "2. Issue tooling, changed").replace(
        "\n## Acceptance", "3. A new requirement.\n\n## Acceptance")
    gh.comment("C1", "Requirement 3 is new.")
    assert run(worktree, "refresh") == 0
    output = capsys.readouterr().out
    assert "CHANGED since the last read" in output
    assert "+2. Issue tooling, changed" in output and "-2. Issue tooling" in output
    assert "requirement 2 changed" in output and "requirement 3 added" in output
    assert "run intake again" in output
    assert "comment by dispatcher" in output and "  Requirement 3 is new." in output

    gh.issue["comments"][0]["body"] = "Requirement 3 is new and urgent."
    assert run(worktree, "refresh", "--json") == 0
    changes = json.loads(capsys.readouterr().out)
    assert changes["changed"] and not changes["body_diff"] and not changes["new_comments"]
    assert [c["body"] for c in changes["edited_comments"]] == ["Requirement 3 is new and urgent."]
    assert run(worktree, "refresh") == 0
    assert "unchanged" in capsys.readouterr().out


def test_refresh_needs_an_issue_until_one_is_recorded(worktree, gh, capsys):
    worktree.mkdir(exist_ok=True)
    assert run(worktree, "refresh") == 1
    assert "pass --issue N" in capsys.readouterr().err
    gh.comment("C1", "Read me first.")
    assert run(worktree, "refresh", "--issue", "5") == 0
    output = capsys.readouterr().out
    assert "first read" in output and "Read me first." in output
    assert run(worktree, "refresh") == 0
    assert "unchanged" in capsys.readouterr().out


def test_field_report_draft_writes_the_template_between_its_markers_and_files_no_issue(
        worktree, gh, capsys):
    gh.issue["labels"] = [{"name": "work"}, {"name": "repo:example"}, {"name": "discovery"}]
    run(worktree, "intake", "--issue", "5")
    gh.calls.clear()
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", str(report)) == 0
    draft = report.read_text(encoding="utf-8")
    assert draft.startswith(BEGIN + "\n") and draft.rstrip().endswith(END)
    assert "**Work issue:** #5  **Branch:** `feature/example-20261104`" in draft
    assert "Pull request:" not in draft  # the report is the pull request's own description
    assert "**Tested against `main`:** `abc1234`" in draft
    assert "**Release kind:** minor — <reason>" in draft  # the prefix only proposes the kind
    assert '## User requirement (quoted back)\n\n> make it "work", please\n' in draft
    delivered = draft.split("## Delivered", 1)[1].split("## Not delivered", 1)[0]
    assert "[Discovery evidence index](.se/work/probe/evidence.md)" in delivered
    assert "## Not delivered" in draft and "## Retro" in draft
    report.write_text(
        fill_evidence_rows(draft).replace(
            "**Result:** complete | partial", "**Result:** complete"
        ),
        encoding="utf-8",
    )

    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err
    assert all(call[:2] == ["issue", "view"] for call in gh.calls)  # reads only; no issue filed


def test_field_report_draft_names_the_configured_integration_branch_and_its_commit(
        worktree, gh, monkeypatch):
    monkeypatch.setattr(work_tickets, "tested_main", TESTED_MAIN)
    git_ok("init", "-q", "-b", "next", str(worktree))
    git_ok("-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "commit", "-q", "--allow-empty", "-m", "base")
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    git_ok("-C", str(worktree), "switch", "-q", "-c", BRANCH)
    (worktree / "se.toml").write_text('[project]\nintegration_branch = "next"\n', encoding="utf-8")
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"

    assert run(worktree, "field-report", "--draft", str(report)) == 0
    assert f"**Tested against `next`:** `{commit}`" in report.read_text(encoding="utf-8")


def test_field_report_draft_uses_the_se_template_when_project_has_none(worktree, gh):
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    report = worktree / "report.md"

    assert not (worktree / ".github" / "pull_request_template.md").exists()
    assert run(worktree, "field-report", "--draft", str(report)) == 0
    draft = report.read_text(encoding="utf-8")
    assert BEGIN in draft and "## Delivered" in draft


def test_field_report_refuses_unfilled_or_unmarked_reports(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    unfilled = "**Work issue:** #<n>  **Branch:** `<branch>` `<integration branch>` `<commit>`\n"
    report.write_text(f"{BEGIN}\n{unfilled}{END}\n", encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 1
    error = capsys.readouterr().err
    assert "unfilled placeholder #<n>" in error and "unfilled placeholder <branch>" in error
    assert "unfilled placeholder <commit>" in error
    assert "unfilled placeholder <integration branch>" in error

    report.write_text(COMPLETE_REPORT.replace(BEGIN, ""), encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 1
    assert (f"Field report report.md holds no field report: the report goes between the lines "
            f"{BEGIN} and {END}") in capsys.readouterr().err

    monkeypatch.setattr(work_tickets, "current_branch", lambda root: "main")
    assert run(worktree, "field-report", "--draft", str(worktree / "other.md")) == 1
    assert "does not match the work issue title" in capsys.readouterr().err


def test_field_report_refuses_a_placeholder_added_to_its_template(
    worktree, gh, monkeypatch, tmp_path, capsys
):
    text = work_tickets.field_report_template()
    monkeypatch.setattr(work_tickets, "field_report_template", lambda: text.replace(
        "**Result:**", "**Reviewed on:** <date>  **Result:**", 1))
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text(f"{BEGIN}\n**Work issue:** #5  **Reviewed on:** <date>  "
                      "**Result:** complete\n\n## Delivered\n\n"
                      "| Work issue item | Result | Commits | Evidence |\n|---|---|---|---|\n"
                      + EVIDENCE_ROWS + f"\n{END}\n", encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 1
    assert "unfilled placeholder <date>" in capsys.readouterr().err


def test_field_report_may_mention_placeholders_below_its_header(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT.replace(
        "## Spec gaps\n\nNone.", "## Spec gaps\n\nThe draft fills `#<n>`, `<branch>` and `<commit>`."
    ), encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err


@pytest.mark.parametrize(("result", "accepted"), [
    ("complete", True),
    ("partial", True),
    ("complete | partial", False),
    ("unknown", False),
])
def test_field_report_requires_an_exact_result_header(worktree, gh, capsys, result, accepted):
    run(worktree, "intake", "--issue", "5")
    report = draft_complete_field_report(worktree)
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "**Result:** complete", f"**Result:** {result}"
        ),
        encoding="utf-8",
    )

    assert run(worktree, "field-report", "--check", str(report)) == (0 if accepted else 1)
    if not accepted:
        assert "header (above the first section): Result must be exactly complete or partial" in (
            capsys.readouterr().err)


@pytest.mark.parametrize(("row", "replacement", "named"), [
    ("| Requirement 2 | complete | `abc1234` | `test`: passed |\n", "", "Requirement 2"),
    ("| Acceptance 2 | complete | `abc1234` | `test`: passed |",
     "| Acceptance 2 | complete | `abc1234` | |", "Acceptance 2"),
], ids=["missing-row", "empty-evidence-cell"])
def test_field_report_refuses_missing_or_empty_evidence(
        worktree, gh, capsys, row, replacement, named):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", str(report)) == 0
    report.write_text(fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
        row, replacement), encoding="utf-8")

    assert run(worktree, "field-report", "--check", str(report)) == 1
    assert named in capsys.readouterr().err


def test_field_report_accepts_not_delivered_requirement(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", str(report)) == 0
    report.write_text(
        fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
            "**Result:** complete | partial", "**Result:** partial"
        ).replace(
            "| Requirement 2 | complete | `abc1234` | `test`: passed |\n", ""
        ).replace("## Not delivered\n\n", "## Not delivered\n\nRequirement 2 was narrowed.\n"),
        encoding="utf-8",
    )

    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err



@pytest.mark.parametrize(("change", "message"), [
    (lambda report: report, None),
    (lambda report: report.replace("  **Result:** complete", ""),
     'header (above the first section): missing "**Result:**"; the template\'s line: '
     "**Work issue:** #<n>  **Branch:** `<branch>`  **Result:** complete | partial"),
    (lambda report: report.replace("**Tested against `main`:** `abc1234`\n", ""),
     'header (above the first section): missing "**Tested against `<integration branch>`:**"'),
    (lambda report: report.replace(
        "| Work issue item | Result | Commits | Evidence |\n|---|---|---|---|\n" + EVIDENCE_ROWS,
        "| Work issue item | Evidence |\n|---|---|\n"
        + "\n".join(f"| {item} | `test`: passed |" for item in (
            "Requirement 1", "Requirement 2", "Acceptance 1", "Acceptance 2"))),
     'section "## Delivered": table header | Work issue item | Evidence | does not match the '
     "template's | Work issue item | Result | Commits | Evidence |"),
    (lambda report: report.replace("| Acceptance 2 | complete | `abc1234` | `test`: passed |",
                                   "| Acceptance 2 | `test`: passed |"),
     'section "## Delivered": table row | Acceptance 2 | `test`: passed | has 2 columns; '
     "the template's table has 4"),
    (lambda report: report.replace("`test`: passed |", "`a \\| b`: passed |"), None),
    (lambda report: report.replace("## Review responses\n\nNone\n\n", ""),
     'missing section "## Review responses"; the template has the heading '
     '"## Review responses"'),
    (lambda report: report.replace("**Commit groupings:** None", ""),
     'section "## Delivered": missing "**Commit groupings:**"; the template\'s line: '
     "**Commit groupings:** None"),
    (lambda report: report.replace(
        "| Decision | Alternatives | Rationale | Confidence |\n|---|---|---|---|", "None"),
     None),
    (lambda report: report.replace(
        "| Decision | Alternatives | Rationale | Confidence |\n|---|---|---|---|", "Chose A."),
     'section "## Decisions": missing its table; the template\'s header row: '
     "| Decision | Alternatives | Rationale | Confidence |"),
    (lambda report: report.replace("**Branch:** `feature/example-20261104`", "**Branch:** `<branch>`"),
     "header (above the first section): unfilled placeholder <branch>"),
    (lambda report: report.replace("| Requirement 2 | complete | `abc1234` | `test`: passed |\n", ""),
     "missing evidence for: Requirement 2"),
], ids=["complete", "no-result", "no-tested-against", "two-column-table", "short-row", "escaped-pipe",
        "no-review-responses", "no-groupings", "decisions-none", "decisions-prose", "placeholder", "no-evidence"])
def test_field_report_check_validates_against_the_template_without_github(
        worktree, gh, capsys, change, message):
    run(worktree, "intake", "--issue", "5")
    gh.calls.clear()
    report = worktree / "report.md"
    report.write_text(change(COMPLETE_REPORT), encoding="utf-8")

    code = run(worktree, "field-report", "--check", str(report))
    captured = capsys.readouterr()
    assert all(call[:2] == ["issue", "view"] for call in gh.calls)  # reads only, for the comments
    if message is None:
        assert code == 0, captured.err
        assert "Field report report.md follows the template" in captured.out
    else:
        assert code == 1
        assert "Field report report.md does not follow the template" in captured.err
        assert "the se checkout's .github/pull_request_template.md:" in captured.err
        assert str(work_tickets.TEMPLATES) not in captured.err
        assert message in captured.err


def test_field_report_check_takes_the_issue_body_from_a_file_or_refuses_without_one(
        worktree, capsys):
    worktree.mkdir(exist_ok=True)
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT.replace(
        "| Requirement 2 | complete | `abc1234` | `test`: passed |\n", ""), encoding="utf-8")

    assert run(worktree, "field-report", "--check", str(report)) == 1
    assert "run intake, or save the work issue's body to a file and pass --issue-body" in (
        capsys.readouterr().err)

    issue = worktree / "issue.md"
    issue.write_text(BODY, encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report), "--issue-body", str(issue)) == 1
    assert "missing evidence for: Requirement 2" in capsys.readouterr().err
    issue.write_text(BODY.replace("2. Issue tooling in `scripts/work_tickets.py`.\n", ""),
                     encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report), "--issue-body", str(issue)) == 0


def with_requirement_3(report: str) -> str:
    row = "| Requirement 2 | complete | `abc1234` | `test`: passed |\n"
    return report.replace(row, row + row.replace("Requirement 2", "Requirement 3"))


SIX_REQUIREMENTS = BODY.replace(
    "2. Issue tooling in `scripts/work_tickets.py`.\n",
    "".join(f"{n}. Requirement text {n}.\n" for n in range(2, 6)),
).replace("## Acceptance", "## Changes after filing\n\n6. Added after filing.\n\n## Acceptance")


def six_requirement_report(rows: range) -> str:
    row = "| Requirement 1 | complete | `abc1234` | `test`: passed |\n"
    return COMPLETE_REPORT.replace(
        row + "| Requirement 2 | complete | `abc1234` | `test`: passed |\n",
        "".join(row.replace("Requirement 1", f"Requirement {n}") for n in rows),
    )


@pytest.mark.parametrize(("rows", "refused"), [(range(1, 6), True), (range(1, 7), False)],
                         ids=["lacks-row-6", "has-row-6"])
def test_field_report_check_counts_requirements_under_changes_after_filing(
        worktree, capsys, rows, refused):
    worktree.mkdir(exist_ok=True)
    issue = worktree / "issue.md"
    issue.write_text(SIX_REQUIREMENTS, encoding="utf-8")
    report = worktree / "report.md"
    report.write_text(six_requirement_report(rows), encoding="utf-8")

    code = run(worktree, "field-report", "--check", str(report), "--issue-body", str(issue))
    error = capsys.readouterr().err
    if refused:
        assert code == 1
        assert 'missing evidence for: Requirement 6 (under "Changes after filing")' in error
    else:
        assert code == 0, error


def test_intake_and_refresh_read_requirements_under_changes_after_filing(worktree, gh):
    gh.issue["body"] = SIX_REQUIREMENTS
    run(worktree, "intake", "--issue", "5")
    todo = sorted(path.name for path in (worktree / ".se" / "work" / "todo").iterdir())
    assert any(name.startswith("r6-added-after-filing") for name in todo), todo

    gh.issue["body"] = SIX_REQUIREMENTS.replace(
        "6. Added after filing.\n", "6. Added after filing.\n7. Added later.\n")
    assert work_tickets.refresh(worktree, 5, None)["requirements_added"] == [7]


def test_field_report_check_records_the_branch_tip_of_its_worktree(tmp_path, capsys):
    root = tmp_path / "worker"
    git_ok("init", "-q", "-b", BRANCH, str(root))
    git_ok("-C", str(root), "-c", "user.name=mb", "-c", "user.email=mb", "commit", "-q",
           "--allow-empty", "-m", "work")
    git_ok("-C", str(root), "branch", "main")  # the integration branch the check's guard diffs against
    tip = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    report, issue = tmp_path / "report.md", tmp_path / "issue.md"
    report.write_text(COMPLETE_REPORT.replace("`abc1234`  **Re", "`<tip>`  **Re"), encoding="utf-8")
    issue.write_text(BODY, encoding="utf-8")

    assert work_tickets.main(["field-report", "--check", str(report), "--issue-body", str(issue)]) == 1
    assert ("Branch tip must be the branch's commit; field-report --check --worktree <worktree> "
            "fills it from the branch") in capsys.readouterr().err
    assert work_tickets.main(["field-report", "--check", str(report), "--issue-body", str(issue),
                              "--worktree", str(root)]) == 0
    assert f"**Branch tip:** `{tip}`  **Re-integration kind:** patch" in report.read_text(
        encoding="utf-8")


def test_field_report_check_refuses_a_re_integration_kind_it_cannot_release(tmp_path, capsys):
    report, issue = tmp_path / "report.md", tmp_path / "issue.md"
    report.write_text(COMPLETE_REPORT.replace("kind:** patch", "kind:** large"), encoding="utf-8")
    issue.write_text(BODY, encoding="utf-8")
    assert work_tickets.main(["field-report", "--check", str(report), "--issue-body", str(issue)]) == 1
    assert "Re-integration kind 'large' must be one of patch, minor, major" in capsys.readouterr().err


def test_field_report_check_needs_no_worktree_and_names_the_option_where_it_needs_one(
        tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text(COMPLETE_REPORT, encoding="utf-8")
    issue = tmp_path / "issue.md"
    issue.write_text(BODY, encoding="utf-8")

    assert work_tickets.main(["field-report", "--check", str(report), "--issue-body", str(issue)]) == 0
    assert "Field report report.md follows the template" in capsys.readouterr().out

    assert work_tickets.main(["field-report", "--check", str(report)]) == 1
    assert ("pass --issue-body <file>, or --worktree <worktree> to read intake's snapshot"
            in capsys.readouterr().err)

    assert work_tickets.main(["field-report", "--draft", str(report)]) == 1
    assert "field-report --draft needs --worktree <worktree>" in capsys.readouterr().err


def test_the_integration_reads_the_report_from_the_pull_request_description(worktree, gh):
    def described(body: str) -> None:
        gh.pull_request = {"number": 7, "url": "https://git.example/owner/repo/pull/7",
                           "headRefName": BRANCH, "headRefOid": TIP, "body": body}

    described(f"Fixes {URL}\n\nNo report here.\n")
    with pytest.raises(work_tickets.QueueError,
                       match="The description of pull request #7 holds no field report"):
        work_tickets.pull_request_report(worktree, 7, "git.example/owner/repo")

    described(f"Fixes {URL}\n\n{BEGIN}\n**Work issue:** #5\n\n## Delivered\nComplete.\n{END}\n")
    with pytest.raises(work_tickets.QueueError, match='missing section "## Review responses"'):
        work_tickets.pull_request_report(worktree, 7, "git.example/owner/repo")

    described(f"Fixes {URL}\n\n{BEGIN}\n## Delivered\n{END}\n")
    with pytest.raises(work_tickets.QueueError, match="names no work issue"):
        work_tickets.pull_request_report(worktree, 7, "git.example/owner/repo")

    described(f"Fixes {URL}\n\n{COMPLETE_REPORT}")
    pull, report, work_issue, work = work_tickets.pull_request_report(
        worktree, 7, "git.example/owner/repo")
    assert pull["headRefName"] == BRANCH and work == 5 and work_issue["number"] == 5
    assert report.startswith("**Work issue:** #5") and BEGIN not in report
    assert ["pr", "view", "7"] == gh.calls[0][:3] and not any(
        call[:2] == ["issue", "create"] for call in gh.calls)


def test_escalate_comments_through_a_body_file_and_labels(worktree, gh):
    run(worktree, "intake", "--issue", "5")
    question = worktree / "question.md"
    question.write_text('Merge conflict in "table.js": which side wins?\n', encoding="utf-8")
    assert run(worktree, "escalate", "--issue", "8", "--file", str(question)) == 0
    comment, label = gh.calls[-2], gh.calls[-1]
    assert comment[:3] == ["issue", "comment", "8"] and "--body-file" in comment
    assert gh.bodies[-1] == 'Merge conflict in "table.js": which side wins?\n'
    assert label == ["issue", "edit", "8", "--add-label", "escalated",
                     "--repo", "git.example/owner/repo"]


def test_comments_print_on_a_legacy_console_encoding(worktree, gh, monkeypatch):
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    gh.comment("C1", "Order: first \u2192 second \u2705")
    assert run(worktree, "refresh", "--issue", "5") == 0
    console.flush()
    assert "Order: first ? second ?" in console.buffer.getvalue().decode("cp1252")


def test_missing_gh_names_the_command_the_tool_and_the_without_gh_section(worktree, monkeypatch, capsys):
    worktree.mkdir(exist_ok=True)
    monkeypatch.setattr(work_tickets.shutil, "which", lambda name: None)
    assert run(worktree, "intake", "--issue", "5", "--repo", "git.example/owner/repo") == 1
    error = capsys.readouterr().err
    assert error.startswith("error: work_tickets.py intake needs the GitHub CLI (gh), which is not on PATH.")
    assert "setup command" in error
    section = error.rstrip().removesuffix(" says").rsplit(" ", 1)[-1]
    path, anchor = section.split("#")
    assert anchor == "without-gh"
    assert path == "src/skills/work-model/SKILL.md"  # relative: no user profile path in logs
    assert "the se checkout's src/" in error
    se_root = Path(work_tickets.__file__).resolve().parents[1]
    assert "### Without gh" in (se_root / path).read_text(encoding="utf-8")


def test_field_report_check_refuses_comments_after_intake_until_they_are_recorded_as_read(
        worktree, gh, capsys):
    gh.comment("C1", "Started.")
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT, encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err

    gh.comment("C2", "Requirement 2 also covers the docs.")
    capsys.readouterr()
    assert run(worktree, "field-report", "--check", str(report)) == 1
    error = capsys.readouterr().err
    assert f"dispatcher: {URL}#issuecomment-C2" in error
    assert "issuecomment-C1" not in error
    assert ("Read them, apply them or answer them in the field report's Review responses, then "
            "record them as read: work_tickets.py comments-read --count 2 --newest C2") in error

    assert run(worktree, "comments-read", "--count", "2", "--newest", "C2") == 0
    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err


def test_field_report_check_takes_the_comments_by_hand_without_gh(worktree, gh, monkeypatch, capsys):
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT, encoding="utf-8")
    issue = worktree / "issue.md"
    issue.write_text(BODY, encoding="utf-8")
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: False)
    check = ["field-report", "--check", str(report), "--issue-body", str(issue)]

    assert run(worktree, "comments-read", "--count", "1", "--newest", "C1") == 0
    assert run(worktree, *check) == 1
    assert "body-read --body-file <file>" in capsys.readouterr().err
    assert run(worktree, "body-read", "--body-file", str(issue)) == 0
    assert run(worktree, *check) == 1
    assert "pass --comment-count <n> --newest-comment <id>" in capsys.readouterr().err
    assert run(worktree, *check, "--comment-count", "1", "--newest-comment", "C1") == 0
    assert run(worktree, *check, "--comment-count", "2", "--newest-comment", "C2") == 1
    error = capsys.readouterr().err
    assert "2 comment(s) now, 1 recorded as read; newest now C2, recorded C1" in error
    assert "comments-read --count 2 --newest C2 --worktree <worktree>" in error
    assert gh.calls == []


def test_field_report_check_refuses_a_body_edited_after_intake_until_it_is_recorded_as_read(
        worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT, encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err

    gh.issue["body"] = BODY + "\n## Changes after filing\n\n3. Also the docs.\n"
    capsys.readouterr()
    assert run(worktree, "field-report", "--check", str(report)) == 1
    error = capsys.readouterr().err
    assert f"The body of the work issue {URL} changed after it was last recorded as read" in error
    assert ('Read its "Changes after filing", apply them, add their evidence rows to the field '
            "report, then record the body as read: work_tickets.py body-read") in error

    assert run(worktree, "body-read") == 0
    assert run(worktree, "refresh") == 0
    assert run(worktree, "field-report", "--check", str(report)) == 1
    assert 'missing evidence for: Requirement 3 (under "Changes after filing")' in (
        capsys.readouterr().err)
    report.write_text(with_requirement_3(COMPLETE_REPORT), encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report)) == 0, capsys.readouterr().err


def test_field_report_check_takes_the_body_by_hand_without_gh(worktree, gh, monkeypatch, capsys):
    report = worktree / "report.md"
    report.write_text(with_requirement_3(COMPLETE_REPORT), encoding="utf-8")
    issue = worktree / "issue.md"
    issue.write_text(BODY.replace("\n", "\r\n") + "\n", encoding="utf-8", newline="")
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: False)
    check = ["field-report", "--check", str(report), "--issue-body", str(issue),
             "--comment-count", "0", "--newest-comment", ""]
    assert run(worktree, "comments-read", "--count", "0", "--newest", "") == 0
    assert run(worktree, "body-read", "--body-file", str(issue)) == 0
    assert run(worktree, *check) == 0, capsys.readouterr().err

    issue.write_text(BODY + "\n## Changes after filing\n\n3. Also the docs.\n", encoding="utf-8")
    assert run(worktree, *check) == 1
    error = capsys.readouterr().err
    assert "The body of the work issue #5 changed after it was last recorded as read" in error
    assert "add --body-file <file>" in error
    assert run(worktree, "body-read", "--body-file", str(issue)) == 0
    assert run(worktree, *check) == 0, capsys.readouterr().err
    assert gh.calls == []


def test_deliver_refuses_a_body_edited_after_intake_before_pushing(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "push", lambda root, branch: pytest.fail("pushed"))
    gh.issue["body"] = BODY + "\n## Changes after filing\n\n3. Also the docs.\n"
    assert run(worktree, "deliver") == 1
    assert "changed after it was last recorded as read" in capsys.readouterr().err
    assert not any(call[:2] in (["pr", "create"], ["issue", "create"]) for call in gh.calls)


def test_deliver_refuses_comments_after_intake_before_pushing(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "push", lambda root, branch: pytest.fail("pushed"))
    gh.comment("C1", "Change of plan.")
    assert run(worktree, "deliver") == 1
    assert f"{URL}#issuecomment-C1" in capsys.readouterr().err
    assert not any(call[:2] in (["pr", "create"], ["issue", "create"]) for call in gh.calls)


def test_a_gh_that_is_not_signed_in_takes_the_no_gh_path(worktree, monkeypatch, capsys):
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets.shutil, "which", lambda name: "/opt/unsigned/gh")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: (
            calls.append(arguments) or subprocess.CompletedProcess(arguments, 1, "", "not logged in")
        ),
    )
    assert work_tickets.gh_usable() is False
    assert run(worktree, "intake", "--issue", "5", "--repo", "git.example/owner/repo") == 1
    error = capsys.readouterr().err
    assert error.startswith("error: work_tickets.py intake needs the GitHub CLI (gh), which is "
                            "installed but not signed in")
    assert "counts as no gh" in error and "SKILL.md#without-gh" in error
    assert all(call == ["/opt/unsigned/gh", "auth", "status"] for call in calls)


def test_sync_fetches_and_merges_main_or_reports_conflicts(worktree, monkeypatch, capsys):
    (worktree / "se.toml").unlink()  # no identity: sync leaves the checkout's as it is
    calls: list[list[str]] = []

    def git(arguments, **kwargs):
        calls.append(arguments)
        if "rev-parse" in arguments:
            return subprocess.CompletedProcess(arguments, 0, "abc1234\n", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(work_tickets.subprocess, "run", git)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")

    assert run(worktree, "sync") == 0
    assert calls[:2] == [
        ["git", "-C", str(worktree), "fetch", "origin"],
        ["git", "-C", str(worktree), "merge", "--no-edit", "origin/main"],
    ]
    assert "Merged main abc1234" in capsys.readouterr().out

    def conflict(arguments, **kwargs):
        if arguments[-3:] == ["merge", "--no-edit", "origin/main"]:
            return subprocess.CompletedProcess(arguments, 1, "", "CONFLICT (content): conflict")
        return subprocess.CompletedProcess(arguments, 0, "abc1234\n", "")

    monkeypatch.setattr(work_tickets.subprocess, "run", conflict)
    assert run(worktree, "sync") == 1
    assert "merge conflict" in capsys.readouterr().err.lower()


def test_sync_without_origin_merges_local_main(worktree, monkeypatch, capsys):
    (worktree / "se.toml").unlink()  # no identity: sync leaves the checkout's as it is
    calls: list[list[str]] = []

    def git(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "abc1234\n" if "rev-parse" in arguments else "", "")

    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    monkeypatch.setattr(work_tickets.subprocess, "run", git)

    assert run(worktree, "sync") == 0
    assert calls == [
        ["git", "-C", str(worktree), "merge", "--no-edit", "main"],
        ["git", "-C", str(worktree), "rev-parse", "--short", "main"],
    ]
    assert "Merged main abc1234" in capsys.readouterr().out


def test_sync_sets_the_configured_public_identity_in_the_checkout(main_checkout, local_config):
    local_config.parent.mkdir(parents=True)
    local_config.write_text('public_identity = "mb <mb>"\n', encoding="utf-8")

    work_tickets.sync(main_checkout)
    git_ok("-C", str(main_checkout), "commit", "-q", "--allow-empty", "-m", "after sync")

    log = subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%an <%ae>|%cn <%ce>"],
        capture_output=True, text=True, check=True,
    )
    assert log.stdout.strip() == "mb <mb>|mb <mb>"


def commit_identity_after_sync(checkout: Path) -> str:
    work_tickets.sync(checkout)
    git_ok("-C", str(checkout), "commit", "-q", "--allow-empty", "-m", "after sync")
    log = subprocess.run(
        ["git", "-C", str(checkout), "log", "-1", "--format=%an <%ae>|%cn <%ce>"],
        capture_output=True, text=True, check=True,
    )
    return log.stdout.strip()


def test_sync_sets_the_project_identity_where_the_machine_sets_none(main_checkout, local_config):
    (main_checkout / "se.toml").write_text('[project]\nidentity = "proj <proj>"\n', encoding="utf-8")
    assert not local_config.exists()

    assert commit_identity_after_sync(main_checkout) == "proj <proj>|proj <proj>"


def test_sync_prefers_the_machine_public_identity_over_the_project_identity(main_checkout, local_config):
    (main_checkout / "se.toml").write_text('[project]\nidentity = "proj <proj>"\n', encoding="utf-8")
    local_config.parent.mkdir(parents=True)
    local_config.write_text('public_identity = "mb <mb>"\n', encoding="utf-8")

    assert commit_identity_after_sync(main_checkout) == "mb <mb>|mb <mb>"


def test_sync_refuses_a_malformed_project_identity_naming_the_file(worktree, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: pytest.fail(f"sync ran {arguments}"),
    )
    (worktree / "se.toml").write_text('[project]\nidentity = "proj"\n', encoding="utf-8")

    assert run(worktree, "sync") == 1
    error = capsys.readouterr().err
    assert str(worktree / "se.toml") in error
    assert "Name <email>" in error


def test_sync_refuses_a_malformed_public_identity_naming_the_file(
        worktree, local_config, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: pytest.fail(f"sync ran {arguments}"),
    )
    local_config.parent.mkdir(parents=True)
    local_config.write_text('public_identity = "mb"\n', encoding="utf-8")

    assert run(worktree, "sync") == 1
    error = capsys.readouterr().err
    assert str(local_config) in error
    assert "Name <email>" in error


def test_sync_fetches_and_merges_a_configured_mirror(main_checkout, local_config):
    mirror = main_checkout.parent / "mirror.git"
    source = main_checkout.parent / "mirror-source"
    git_ok("init", "-q", "--bare", "-b", "main", str(mirror))
    git_ok("-C", str(main_checkout), "remote", "add", "mirror", str(mirror))
    git_ok("-C", str(main_checkout), "push", "-q", "mirror", "main")
    git_ok("clone", "-q", str(mirror), str(source))
    git_ok("-C", str(source), "config", "user.name", "Mirror test")
    git_ok("-C", str(source), "config", "user.email", "mirror-test@example.invalid")
    (source / "from-mirror.txt").write_text("mirror\n", encoding="utf-8")
    git_ok("-C", str(source), "add", "from-mirror.txt")
    git_ok("-C", str(source), "commit", "-q", "-m", "mirror change")
    git_ok("-C", str(source), "push", "-q", "origin", "main")
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        f'[mirrors]\n"{main_checkout.name}" = ['
        '{ remote = "mirror", branch = "main", fetch = true, public = false }]\n',
        encoding="utf-8",
    )

    work_tickets.sync(main_checkout)

    assert (main_checkout / "from-mirror.txt").read_text(encoding="utf-8") == "mirror\n"


@pytest.mark.parametrize(
    "labels",
    [[{"name": "work"}], [{"name": "work"}, {"name": "discovery"}]],
    ids=["standard", "discovery"],
)
def test_deliver_is_idempotent_and_prints_configured_notification(
        worktree, gh, local_config, monkeypatch, capsys, labels):
    gh.issue["labels"] = labels
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    draft_complete_field_report(worktree)
    pushes: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: (
            pushes.append(arguments) or subprocess.CompletedProcess(arguments, 0, "", "")
        ),
    )
    local_config.parent.mkdir(parents=True)
    local_config.write_text('integrator_session = "ahp-session:/integrator"\n', encoding="utf-8")

    assert run(worktree, "deliver") == 0
    assert ["git", "-C", str(worktree), "push", "-u", "origin", BRANCH] in pushes
    assert any(call[:2] == ["pr", "create"] for call in gh.calls)
    assert not any(call[:2] in (["issue", "create"], ["issue", "edit"]) for call in gh.calls)
    assert f"Notify ahp-session:/integrator: field report in PR #7 for {BRANCH}" in (
        capsys.readouterr().out
    )
    description = gh.bodies[-1]
    assert description.startswith(f"Fixes {URL}\n\n{BEGIN}\n**Work issue:** #5")
    assert description.endswith(f"{END}\n") and "<!--" not in description.replace(
        BEGIN, "").replace(END, "") and "\n\n\n" not in description
    assert f"**Branch tip:** `{TIP}`" in description

    assert run(worktree, "deliver", "--integrator-session", "ahp-session:/other") == 0
    assert sum(call[:2] == ["pr", "create"] for call in gh.calls) == 1
    edit = next(call for call in gh.calls if call[:2] == ["pr", "edit"])
    assert edit[2] == "7" and gh.bodies[-1] == description
    assert not any(call[:2] == ["issue", "create"] for call in gh.calls)
    assert "Notify ahp-session:/other: field report in PR #7" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("state", "creates"),
    [("open", False), ("merged", True), ("closed", True), ("missing", True)],
)
def test_deliver_uses_only_an_open_pull_request(
        worktree, gh, monkeypatch, state, creates):
    run(worktree, "intake", "--issue", "5")
    if state == "missing":
        gh.pull_request = None
    else:
        gh.pull_request_state = state
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver") == 0
    assert any(call[:2] == ["pr", "create"] for call in gh.calls) is creates


def test_deliver_writes_the_report_into_the_pull_request_on_origin_and_files_no_issue(
        worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "source.example/owner/source")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver") == 0
    pr_create = next(call for call in gh.calls if call[:2] == ["pr", "create"])
    assert pr_create[pr_create.index("--repo") + 1] == "source.example/owner/source"
    assert BEGIN in gh.bodies[-1]
    assert not any(call[0] == "issue" and call[1] != "view" for call in gh.calls)


def test_deliver_without_origin_refuses_naming_the_remedy(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")

    assert run(worktree, "deliver") == 1
    assert "has no origin remote" in capsys.readouterr().err
    assert not any(call[0] == "pr" or call[:2] == ["issue", "create"] for call in gh.calls)


def test_deliver_refuses_report_without_evidence(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / ".se" / "work" / "field-report.md"
    work_tickets.draft_field_report(worktree, report)
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "**Result:** complete | partial", "**Result:** complete"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver") == 1
    assert "missing evidence for: Requirement 1" in capsys.readouterr().err
    assert not any(call[0] == "pr" and call[1] != "list" for call in gh.calls)


def test_deliver_refuses_a_report_with_an_invalid_result(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    report = draft_complete_field_report(worktree)
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "**Result:** complete", "**Result:** complete | partial"
        ),
        encoding="utf-8",
    )
    pushes: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: (
            pushes.append(arguments) or subprocess.CompletedProcess(arguments, 0, "", "")
        ),
    )

    assert run(worktree, "deliver") == 1
    assert "header (above the first section): Result must be exactly complete or partial" in (
        capsys.readouterr().err)
    assert not pushes


@pytest.mark.parametrize(("url", "repo"), [
    ("https://git.example/owner/repo.git", "git.example/owner/repo"),
    ("https://user:secret@example.com/owner/repo", "example.com/owner/repo"),
    ("git@git.example:owner/repo.git", "git.example/owner/repo"),
    ("ssh://git@git.example:2222/owner/repo.git", "git.example/owner/repo"),
    ("../local/repo", None),
])
def test_repository_comes_from_the_origin_remote(tmp_path, url, repo):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    assert subprocess.run(["git", "init", "-q", str(checkout)], check=False).returncode == 0
    assert work_tickets.remote_repo(checkout) is None
    assert subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", url],
                          check=False).returncode == 0
    assert work_tickets.remote_repo(checkout) == repo


def test_intake_uses_the_remote_and_needs_one_without_repo(worktree, gh, monkeypatch, capsys):
    assert run(worktree, "intake", "--issue", "5") == 0
    assert gh.calls[0][-2:] == ["--repo", "git.example/owner/repo"]

    other = worktree.parent / "other"
    other.mkdir()
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    assert run(other, "intake", "--issue", "5") == 1
    assert "--repo" in capsys.readouterr().err


def test_local_config_resolves_per_checkout_and_arguments_win(worktree, gh, local_config, capsys):
    assert run(worktree, "config") == 0
    output = capsys.readouterr().out
    assert "repository: git.example/owner/repo" in output
    assert f"worktree root: {worktree.parent / f'{worktree.name}.worktrees'}" in output
    assert "integrator session: (not set)" in output
    assert str(local_config) in output

    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        'integrator_session = "session-a"\n\n'
        '[worktree_roots]\n'
        'worktree = "/work/trees"\n\n'
        '[repos."git.example/owner/repo"]\n'
        'integrator_session = "session-b"\n\n'
        '[repos."git.example/owner/elsewhere"]\n'
        'integrator_session = "session-c"\n',
        encoding="utf-8")
    assert run(worktree, "config") == 0
    output = capsys.readouterr().out
    assert "worktree root: /work/trees" in output and "integrator session: session-b" in output

    local_config.write_text(
        local_config.read_text(encoding="utf-8").replace(
            'worktree = "/work/trees"', 'repo = "/remote-trees"'
        ),
        encoding="utf-8",
    )
    assert run(worktree, "config") == 0
    assert "worktree root: /remote-trees" in capsys.readouterr().out

    assert run(worktree, "config", "--worktree-root", "/given", "--integrator-session", "c") == 0
    output = capsys.readouterr().out
    assert "worktree root: /given" in output and "integrator session: c" in output

    local_config.write_text("worktree_root = [", encoding="utf-8")
    assert run(worktree, "config") == 1
    assert "local.toml" in capsys.readouterr().err


def test_configured_mirrors_are_scoped_to_the_checkout(worktree, local_config):
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        '[mirrors]\n'
        '"worktree" = [\n'
        '  { remote = "mirror", branch = "published", fetch = true, public = true },\n'
        '  { remote = "partner", branch = "main", fetch = false, public = false },\n'
        ']\n',
        encoding="utf-8",
    )

    assert work_tickets.configured_mirrors(worktree) == [
        work_tickets.Mirror("mirror", "published", True, True),
        work_tickets.Mirror("partner", "main", False, False),
    ]


@pytest.mark.parametrize("configured, error", [
    ('"worktree" = { remote = "mirror" }\n', "array of tables"),
    ('"worktree" = [{ remote = "", branch = "main", fetch = true, public = false }]\n', "remote"),
    ('"worktree" = [{ remote = "mirror", branch = "main", fetch = "yes", public = false }]\n', "boolean"),
])
def test_configured_mirrors_reject_invalid_entries(worktree, local_config, configured, error):
    local_config.parent.mkdir(parents=True)
    local_config.write_text(f"[mirrors]\n{configured}", encoding="utf-8")

    with pytest.raises(work_tickets.QueueError, match=error):
        work_tickets.configured_mirrors(worktree)


def test_tracker_from_local_config_overrides_origin(worktree, gh, local_config):
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        '[trackers]\n'
        '"worktree" = "tracker.example/owner/tracker"\n',
        encoding="utf-8",
    )
    assert work_tickets.resolve_repo(worktree, None) == "tracker.example/owner/tracker"
    assert work_tickets.resolve_repo(worktree, "given.example/owner/tracker") == (
        "given.example/owner/tracker"
    )


def test_repo_help_matches_the_work_model_resolution_order():
    documentation = (
        PROJECT / ".github" / "skills" / "work-model" / "SKILL.md"
    ).read_text(encoding="utf-8")
    documented_order = next(
        line for line in documentation.splitlines() if "`--repo` resolution order" in line
    )
    terms = ("argument", "[trackers]", "origin")

    for text in (documented_order, work_tickets.REPO.options["help"]):
        positions = [text.index(term) for term in terms]
        assert positions == sorted(positions)


def test_block_creates_native_dependency_and_updates_issue_body(worktree, gh):
    assert run(worktree, "block", "5", "--by", "4", "--repo", "git.example/owner/repo") == 0
    assert [
        "api", "repos/owner/repo/issues/4", "--hostname", "git.example", "--jq", ".id",
    ] in gh.calls
    assert [
        "api", "repos/owner/repo/issues/5/dependencies/blocked_by", "-X", "POST",
        "--hostname", "git.example", "-F", "issue_id=33412961",
    ] in gh.calls
    assert any(
        call[:3] == ["issue", "edit", "5"] and "--body-file" in call for call in gh.calls
    )
    assert "Blocked by" in gh.bodies[-1] and "#4" in gh.bodies[-1]


def test_ready_filters_blocked_existing_and_clashing_work(worktree, monkeypatch):
    candidates = [
        {"number": 1, "title": "feature/one", "body": "## File ownership\n\none.py\n"},
        {"number": 2, "title": "feature/two", "body": "## File ownership\n\ntwo.py\n"},
        {"number": 3, "title": "feature/three", "body": "## File ownership\n\nshared.py\n"},
        {"number": 4, "title": "feature/four", "body": "## File ownership\n\nshared.py\n"},
        {"number": 6, "title": "feature/six", "body": "", "labels": [{"name": "backlogged"}]},
    ]
    active = [{"number": 5, "title": "active", "body": "## File ownership\n\nshared.py\n"}]
    details = {1: 0, 2: 1, 3: 0, 4: 0, 6: 0}
    monkeypatch.setattr(
        work_tickets, "run_gh",
        lambda root, args: json.dumps(
            candidates if args[:2] == ["issue", "list"] and "ready" in args
            else active if args[:2] == ["issue", "list"] else
            {"issue_dependencies_summary": {"blocked_by": details[int(args[1].split("/")[-1])]}}
        ),
    )
    def git(args, **kwargs):
        if "show-ref" in args:
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[-1] == "feature/three":
            return subprocess.CompletedProcess(args, 0, "branch\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(work_tickets.subprocess, "run", git)
    assert [issue["number"] for issue in work_tickets.ready_issues(worktree, "git.example/owner/repo")] == [1]


def test_ready_uses_local_branches_without_an_origin(worktree, monkeypatch):
    candidate = {"number": 1, "title": "feature/one", "body": "## File ownership\n\none.py\n"}
    monkeypatch.setattr(
        work_tickets,
        "run_gh",
        lambda root, args: json.dumps(
            [candidate] if args[:2] == ["issue", "list"] and "ready" in args
            else [] if args[:2] == ["issue", "list"]
            else {"issue_dependencies_summary": {"blocked_by": 0}}
        ),
    )
    monkeypatch.setattr(
        work_tickets.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", ""),
    )
    assert work_tickets.ready_issues(worktree, "git.example/owner/repo") == [candidate]


def test_capacity_counts_running_work_issues(worktree, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert work_tickets.capacity(worktree, None) is None
    monkeypatch.delenv("GITHUB_ACTIONS")
    monkeypatch.setattr(work_tickets.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(work_tickets.sys, "platform", "not-windows")
    monkeypatch.setattr(
        work_tickets, "run_gh",
        lambda root, args: json.dumps([]),
    )
    assert work_tickets.capacity(worktree, "git.example/owner/repo") == 4
    monkeypatch.setattr(
        work_tickets, "run_gh",
        lambda root, args: json.dumps([{"number": 1}, {"number": 2}]),
    )
    assert work_tickets.capacity(worktree, "git.example/owner/repo") == 2


def test_queue_lists_delivered_pull_requests_escalations_and_startable_work(worktree, monkeypatch):
    def pull(number: int, body: str) -> dict:
        return {"number": number, "title": f"feature/n{number}", "url": f"https://example/{number}",
                "body": body}

    delivered = pull(7, f"Fixes {URL}\n\n{COMPLETE_REPORT}")
    pulls = [delivered,
             pull(10, f"Fixes {URL}\n"),  # no report: not delivered
             pull(11, f"Fixes {URL}\n\n{BEGIN}\n**Work issue:** #5\n{END}\n"),  # incomplete
             pull(12, None)]
    escalations = [{"number": 9, "title": "blocked release", "url": "https://example/9"}]
    ready = [{"number": 1, "title": "feature/one"}]
    calls: list[list[str]] = []

    def gh(root, args):
        calls.append(args)
        return json.dumps(pulls if args[:2] == ["pr", "list"] else escalations)

    monkeypatch.setattr(work_tickets, "run_gh", gh)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    synced: list[Path] = []
    monkeypatch.setattr(work_tickets, "sync", lambda root: synced.append(root) or "abc1234")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo, all_repos: ready)
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos: 2)
    assert work_tickets.queue(worktree, "git.example/owner/repo") == (
        [delivered], escalations, ready, 2
    )
    assert synced == [worktree]
    listing = next(call for call in calls if call[:2] == ["pr", "list"])
    assert listing[listing.index("--base") + 1] == "main"
    assert listing[listing.index("--state") + 1] == "open"
    assert not any("field-report" in call for call in calls)  # no field-report issue is read


def test_queue_filters_to_current_repository_unless_all_repositories(worktree, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        work_tickets,
        "run_gh",
        lambda root, args: (calls.append(args) or json.dumps([])),
    )
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo, all_repos: [])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos: 2)
    work_tickets.queue(worktree, "git.example/owner/repo")
    issues = [call for call in calls if call[0] == "issue"]
    assert issues and all("repo:worktree" in call for call in issues)
    calls.clear()
    work_tickets.queue(worktree, "git.example/owner/repo", all_repos=True)
    assert all(not any(value.startswith("repo:") for value in call) for call in calls)


class StartGh:
    def __init__(self, labels: tuple[str, ...] = ("work", "ready"), blocked_by: int = 0) -> None:
        self.labels, self.blocked_by = labels, blocked_by
        self.calls: list[list[str]] = []

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)
        if arguments[:2] == ["issue", "view"]:
            return json.dumps({"number": 5, "title": BRANCH, "url": URL,
                               "labels": [{"name": label} for label in self.labels],
                               "updatedAt": "2026-11-04T10:00:00Z"})
        if arguments[:2] == ["api", "repos/owner/repo/issues/5"]:
            return json.dumps({"issue_dependencies_summary": {"blocked_by": self.blocked_by}})
        return ""


def git_ok(*arguments: str) -> None:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


class FakeGitHub:
    """GitHub's pull requests and check runs on the bare origin of the checkout it is opened for:
    `squash` writes the squash commit onto origin's main as GitHub does, for the owning account
    (`owner`'s noreply author, the web-flow committer). `checks` are the check runs `check_run`
    returns, one per poll, the last one repeated."""

    def __init__(self) -> None:
        self.pulls: list[dict] = []
        self.calls: list[tuple] = []
        self.checks: list[dict | None] = [{"id": 1, "status": "completed", "conclusion": "success",
                                           "html_url": "https://git.example/owner/repo/runs/1"}]
        self.origin: Path | None = None

    def __call__(self, root: Path, repo: str) -> "FakeGitHub":
        self.origin = Path(subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True,
            text=True, check=True).stdout.strip())
        return self

    def git(self, *arguments: str, env: dict | None = None) -> str:
        return subprocess.run(["git", "--git-dir", str(self.origin), *arguments],
                              capture_output=True, text=True, check=True, env=env).stdout.strip()

    def pull(self, number: int) -> dict:
        self.calls.append(("pull", number))
        return next(pull for pull in self.pulls if pull["number"] == number)

    def open_pull(self, head: str, base: str) -> dict | None:
        self.calls.append(("open_pull", head, base))
        return next((pull for pull in self.pulls if pull["state"] == "open"
                     and (pull["head"], pull["base"]) == (head, base)), None)

    def create_pull(self, head: str, base: str, title: str, body: str) -> dict:
        self.calls.append(("create_pull", head, base, title))
        number = 20 + len(self.pulls)
        self.pulls.append({"number": number, "head": head, "base": base, "title": title,
                           "body": body, "state": "open", "merged": False,
                           "html_url": f"https://git.example/owner/repo/pull/{number}"})
        return self.pulls[-1]

    def update_pull(self, number: int, title: str, body: str) -> dict:
        self.calls.append(("update_pull", number, title))
        pull = next(pull for pull in self.pulls if pull["number"] == number)
        pull.update(title=title, body=body)
        return pull

    def comment(self, number: int, body: str) -> dict:
        self.calls.append(("comment", number, body))
        return {"id": 1}

    def close_pull(self, number: int) -> None:
        self.calls.append(("close_pull", number))

    def check_run(self, sha: str, name: str) -> dict | None:
        self.calls.append(("check_run", sha, name))
        return self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]

    def squash(self, number: int, sha: str, title: str, message: str) -> str:
        self.calls.append(("squash", number, sha, title, message))
        pull = next(pull for pull in self.pulls if pull["number"] == number)
        assert self.git("rev-parse", f"refs/heads/{pull['head']}") == sha
        main = self.git("rev-parse", f"refs/heads/{pull['base']}")
        env = {**os.environ, "GIT_AUTHOR_NAME": "owner",
               "GIT_AUTHOR_EMAIL": "1+owner@users.noreply.github.com",
               "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply" + "@github.com"}
        commit = self.git("commit-tree", f"{sha}^{{tree}}", "-p", main, "-m", title, "-m", message,
                          env=env)
        self.git("update-ref", f"refs/heads/{pull['base']}", commit, main)
        pull.update(state="closed", merged=True, merge_commit_sha=commit)
        return commit


def squashed_onto_origin(checkout: Path, commit: str) -> bool:
    """Whether `commit` is origin's main and the checkout's, one squash commit GitHub wrote for
    the owner on top of the main it was tested on."""
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(checkout), *arguments], capture_output=True,
                              text=True, check=True).stdout.strip()
    full = git("rev-parse", commit)
    return (full == git("rev-parse", "origin/main") == git("rev-parse", "main")
            and len(git("rev-list", "--parents", "-1", full).split()) == 2
            and git("log", "-1", "--format=%an %ce", full) == "owner noreply@github.com")


@pytest.fixture(autouse=True)
def github(monkeypatch) -> FakeGitHub:
    """Every integration lands through the fake GitHub; no test reaches the real one."""
    fake = FakeGitHub()
    monkeypatch.setattr(work_tickets, "GitHub", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)  # gh signed in: the local runner
    monkeypatch.setattr(work_tickets, "wait", lambda seconds: None)
    return fake


def suite_passed(root: Path, result: str | None) -> str | None:
    """A fake suite's pass on HEAD: its verdict recorded as run_suite records it; `result`."""
    work_tickets.sibling("verdicts").record(root, "suite", "HEAD", True)
    return result


def build_main_checkout(tmp_path: Path) -> None:
    origin, checkout = tmp_path / "origin.git", tmp_path / "main"
    git_ok("init", "-q", "--bare", "-b", "main", str(origin))
    git_ok("clone", "-q", str(origin), str(checkout))
    git_ok("-C", str(checkout), "config", "user.name", "mb")
    git_ok("-C", str(checkout), "config", "user.email", "mb")
    (checkout / "se.toml").write_text(IDENTITY, encoding="utf-8")
    git_ok("-C", str(checkout), "add", "se.toml")
    git_ok("-C", str(checkout), "commit", "-q", "-m", "base")
    git_ok("-C", str(checkout), "push", "-q", "origin", "HEAD:main")
    # The newest main exists only on origin; start must fetch it.
    git_ok("clone", "-q", str(origin), str(tmp_path / "other"))
    git_ok("-C", str(tmp_path / "other"), "-c", "user.name=Other", "-c",
           "user.email=other@example.invalid", "commit", "-q", "--allow-empty", "-m", "newest")
    git_ok("-C", str(tmp_path / "other"), "push", "-q", "origin", "HEAD:main")


@pytest.fixture
def main_checkout(tmp_path: Path, repositories) -> Path:
    repositories(build_main_checkout, tmp_path)
    return tmp_path / "main"


def start_fakes(monkeypatch, ready=lambda root, repo, allow_existing_branch=False: [
        {"number": 5, "title": BRANCH}], slots=1) -> "StartGh":
    """Fake gh for start: issue #5 ready (or `ready`), `slots` free; returns the fake."""
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "ready_issues", ready)
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: slots)
    return fake


def test_start_creates_a_worktree_from_the_newest_main_and_marks_the_issue(
        main_checkout, local_config, monkeypatch, capsys):
    fake = start_fakes(monkeypatch)
    trees = main_checkout.parent / "trees"
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        f'[worktree_roots]\n"{main_checkout.name}" = "{trees.as_posix()}"\n',
        encoding="utf-8",
    )

    assert run(main_checkout, "start", "5") == 0
    worktree = trees / "feature-example-20261104"
    assert f"Launch worker: agent=worker issue={URL} worktree={worktree}" in capsys.readouterr().out
    branch = subprocess.run(["git", "-C", str(worktree), "branch", "--show-current"],
                            capture_output=True, text=True, check=False).stdout.strip()
    assert branch == BRANCH
    subject = subprocess.run(["git", "-C", str(worktree), "log", "-1", "--format=%s"],
                             capture_output=True, text=True, check=False).stdout.strip()
    assert subject == "newest"
    assert ["issue", "edit", "5", "--remove-label", "ready", "--add-label", "in-progress",
            "--repo", "git.example/owner/repo"] in fake.calls


def test_start_argument_overrides_the_checkout_worktree_root(
        main_checkout, local_config, monkeypatch):
    fake = start_fakes(monkeypatch)
    configured = main_checkout.parent / "configured"
    explicit = main_checkout.parent / "explicit"
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        f'[worktree_roots]\n"{main_checkout.name}" = "{configured.as_posix()}"\n',
        encoding="utf-8",
    )

    assert run(main_checkout, "start", "5", "--worktree-root", str(explicit)) == 0
    assert (explicit / "feature-example-20261104").is_dir()
    assert not configured.exists()


@pytest.mark.parametrize(("ready", "slots", "message"), [
    ([], 1, "not startable"),
    ([{"number": 5, "title": BRANCH}], 0, "capacity is exhausted"),
])
def test_start_refuses_unstartable_issues(main_checkout, monkeypatch, capsys, ready, slots, message):
    fake = start_fakes(monkeypatch, ready=lambda root, repo: ready, slots=slots)
    assert run(main_checkout, "start", "5", "--worktree-root", str(main_checkout.parent)) == 1
    assert message in capsys.readouterr().err
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_uses_a_sibling_worktree_root_by_default(main_checkout, monkeypatch, capsys):
    fake = start_fakes(monkeypatch)
    assert run(main_checkout, "start", "5") == 0
    worktree = main_checkout.parent / f"{main_checkout.name}.worktrees" / (
        "feature-example-20261104"
    )
    assert worktree.is_dir()
    assert f"worktree={worktree}" in capsys.readouterr().out
    assert any(call[:2] == ["issue", "edit"] for call in fake.calls)

    listed = subprocess.run(["git", "-C", str(main_checkout), "worktree", "list"],
                            capture_output=True, text=True, check=False).stdout
    assert len(listed.strip().splitlines()) == 2


def test_start_no_create_uses_an_existing_issue_branch_worktree(
        main_checkout, monkeypatch, capsys):
    fake = start_fakes(monkeypatch)
    worker = main_checkout.parent / "existing-worker"
    git_ok("-C", str(main_checkout), "fetch", "origin")
    git_ok(
        "-C", str(main_checkout), "worktree", "add", "-b", BRANCH, str(worker), "origin/main"
    )

    assert run(main_checkout, "start", "5", "--no-create") == 0
    output = capsys.readouterr().out
    assert f"Launch worker: agent=worker issue={URL} worktree={worker}" in output
    assert subprocess.run(
        ["git", "-C", str(worker), "branch", "--show-current"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() == BRANCH
    assert subprocess.run(
        ["git", "-C", str(worker), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() == "newest"
    assert ["issue", "edit", "5", "--remove-label", "ready", "--add-label", "in-progress",
            "--repo", "git.example/owner/repo"] in fake.calls


def test_start_no_create_requires_a_worktree_on_the_issue_branch(
        main_checkout, monkeypatch, capsys):
    fake = start_fakes(monkeypatch)
    git_ok(
        "-C", str(main_checkout), "worktree", "add", "-b", "feature/other",
        str(main_checkout.parent / "other-worker"), "origin/main",
    )

    assert run(main_checkout, "start", "5", "--no-create") == 1
    assert f"no worktree exists for branch {BRANCH}" in capsys.readouterr().err.lower()
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_without_no_create_refuses_an_existing_issue_branch(
        main_checkout, monkeypatch, capsys):
    fake = start_fakes(monkeypatch, ready=lambda root, repo, allow_existing_branch=False: (
        [{"number": 5, "title": BRANCH}] if allow_existing_branch else []))
    git_ok(
        "-C", str(main_checkout), "worktree", "add", "-b", BRANCH,
        str(main_checkout.parent / "existing-worker"), "origin/main",
    )

    assert run(main_checkout, "start", "5") == 1
    assert "not startable" in capsys.readouterr().err
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_assigns_a_cloud_worker_without_creating_a_worktree(
        main_checkout, monkeypatch, capsys):
    fake = start_fakes(monkeypatch, slots=None)

    assert run(main_checkout, "start", "5", "--cloud-agent", "worker-login") == 0
    assert "Launch worker:" not in capsys.readouterr().out
    assert [
        "issue", "edit", "5", "--add-assignee", "worker-login", "--remove-label", "ready",
        "--add-label", "in-progress", "--repo", "git.example/owner/repo",
    ] in fake.calls


def test_integrate_merges_a_worker_from_a_bare_origin_and_starts_within_capacity(
        main_checkout, local_config, monkeypatch, capsys):
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        'commit_trailer = "Co-authored-by: Agent <agent@users.noreply.github.com>"\n',
        encoding="utf-8",
    )
    # A project without a public check: its merge message names the tracker items.
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    work_tickets.initialize(worker)
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    report = {"body": reported_at(head)}
    calls: list[list[str]] = []
    bodies: list[str] = []
    started: list[int] = []
    commands: list[tuple[str, str]] = []
    checks: list[tuple[list[list[str]], bool]] = []
    guarded: list[tuple[str, Path]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    def gh_call(root, args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefName": "feature/worker", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        return ""
    monkeypatch.setattr(
        work_tickets, "run_gh",
        gh_call,
    )
    monkeypatch.setattr(
        work_tickets, "run_gh_with_body",
        lambda root, args, body: (calls.append(args), bodies.append(body)),
    )
    monkeypatch.setattr(
        work_tickets, "run_project_command",
        lambda root, command, description: (commands.append((command, description)) or "214 passed"),
    )
    monkeypatch.setattr(
        work_tickets, "run_suite",
        lambda root: (commands.append(("suite", "Complete suite")) or suite_passed(root, "214 passed")),
    )
    monkeypatch.setattr(
        work_tickets, "run_project_checks",
        lambda root, check_commands, temporary: (checks.append((check_commands, temporary)) or "passed"),
    )
    monkeypatch.setattr(
        work_tickets, "guard", lambda root, branch, report: guarded.append((branch, report)) or [],
    )
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [{"number": 9}])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
    monkeypatch.setattr(
        work_tickets, "start", lambda root, number, repo, directory, create: started.append(number)
    )

    commit = work_tickets.integrate(main_checkout, 7, None, "build", [["check"]])
    assert (main_checkout / "worker.txt").is_file()
    assert squashed_onto_origin(main_checkout, commit)
    assert commit and started == [9]
    message = subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert "work issue #5, PR #7" in message
    assert message.rstrip().endswith("Co-authored-by: Agent <agent@users.noreply.github.com>")
    assert commands == [
        ("suite", "Complete suite"), ("build", "Output regeneration")
    ]
    assert checks == [([["check"]], False)]
    assert guarded and guarded[0][0] == "feature/worker"
    output = capsys.readouterr().out
    assert "Suite: 214 passed" in output
    assert "Cleanup: worker worktree removed" in output
    assert "Started: 1" in output
    closes = [call for call in calls if call[:2] == ["issue", "close"]]
    assert closes == [["issue", "close", "5", "--repo", "git.example/owner/tracker"]]  # only the work issue
    assert not any(call[0] == "issue" and call[1] in ("create", "list") for call in calls)
    assert [call[:3] for call in calls if call[:2] == ["issue", "comment"]] == [["issue", "comment", "5"]]
    assert bodies == [
        f"Integrated in {commit} from https://git.example/owner/repo/pull/7, landed through https://git.example/owner/repo/pull/20 (check: https://git.example/owner/repo/runs/1). "
        "Release: none. Suite: 214 passed.\n"]
    assert not worker.exists()
    assert subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "--verify", "feature/worker"],
        capture_output=True, text=True, check=False,
    ).returncode != 0
    assert subprocess.run(
        ["git", "--git-dir", str(main_checkout.parent / "origin.git"), "show-ref", "--verify",
         "refs/heads/feature/worker"],
        capture_output=True, text=True, check=False,
    ).returncode != 0


def test_delete_merged_branch_keeps_an_unmerged_tip(main_checkout, capsys):
    git_ok("-C", str(main_checkout), "checkout", "-q", "-b", "feature/unmerged")
    (main_checkout / "unmerged.txt").write_text("unmerged\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "unmerged.txt")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "unmerged")
    head = subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_ok("-C", str(main_checkout), "checkout", "-q", "main")

    work_tickets.delete_merged_branch(main_checkout, "feature/unmerged", head)

    assert subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "--verify", "feature/unmerged"],
        capture_output=True, text=True, check=False,
    ).returncode == 0
    assert "main does not contain its tip" in capsys.readouterr().err


def test_delete_merged_branch_keeps_origin_commits_beyond_reviewed_head(
        main_checkout, capsys):
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("reviewed\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "reviewed")
    reviewed_head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    git_ok("-C", str(main_checkout), "merge", "--no-ff", "-q", "feature/worker", "-m", "merge worker")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "main")
    (worker / "worker.txt").write_text("newer\n", encoding="utf-8")
    git_ok("-C", str(worker), "commit", "-aq", "-m", "newer")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    newer_head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    work_tickets.delete_merged_branch(main_checkout, "feature/worker", reviewed_head)

    origin_head = subprocess.run(
        ["git", "--git-dir", str(main_checkout.parent / "origin.git"), "rev-parse",
         "refs/heads/feature/worker"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert origin_head == newer_head
    assert "retained on origin" in capsys.readouterr().err


def test_integrate_accepts_an_empty_discovery_branch(main_checkout, monkeypatch):
    worker = main_checkout.parent / "empty-discovery-worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/discovery", str(worker))
    work_tickets.initialize(worker)
    head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    report = {"body": reported_at(head)}
    commands: list[tuple[str, str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(
        work_tickets,
        "run_gh",
        lambda root, args: json.dumps({"headRefName": "feature/discovery", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        if args[:2] == ["pr", "view"] else "",
    )
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: "")
    monkeypatch.setattr(
        work_tickets,
        "run_project_command",
        lambda root, command, description: (commands.append((command, description)) or "passed"),
    )
    monkeypatch.setattr(
        work_tickets, "run_suite",
        lambda root: (commands.append(("suite", "Complete suite")) or suite_passed(root, "passed")),
    )
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    commit = work_tickets.integrate(main_checkout, 7, None, None)
    assert commit and squashed_onto_origin(main_checkout, commit)
    assert commands == [("suite", "Complete suite")]
    assert not worker.exists()


@pytest.mark.parametrize("failed_step", ["Complete suite", "Output regeneration", "Project check"])
def test_integrate_failure_restores_pre_merge_main_and_escalates(
        main_checkout, monkeypatch, failed_step):
    worker = main_checkout.parent / "failure-worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/failure", str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    report = {"body": reported_at(head)}
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    def gh_call(root, args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefName": "feature/failure", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        return ""
    monkeypatch.setattr(work_tickets, "run_gh", gh_call)
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    def fail(root, command, description):
        if description == failed_step:
            raise work_tickets.QueueError(f"{description} failed: expected")
    monkeypatch.setattr(work_tickets, "run_project_command", fail)
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: fail(root, "suite", "Complete suite") or suite_passed(root, None))
    def fail_checks(root, commands, temporary):
        if failed_step == "Project check":
            raise work_tickets.QueueError("Project check failed: expected")
    monkeypatch.setattr(work_tickets, "run_project_checks", fail_checks)

    with pytest.raises(work_tickets.QueueError, match=failed_step):
        work_tickets.integrate(
            main_checkout, 7, None, "build",
            [["check"]] if failed_step == "Project check" else None,
        )
    after = subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    assert after
    assert subprocess.run(
        ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", head, "HEAD"],
        capture_output=True, check=False,
    ).returncode != 0
    assert not subprocess.run(
        ["git", "-C", str(main_checkout), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert not any(call[:3] == ["git", "-C", str(main_checkout)] for call in calls)
    assert any(call[:3] == ["issue", "comment", "5"] for call in calls)  # the work issue
    assert any(call[:5] == ["issue", "edit", "5", "--add-label", "escalated"] for call in calls)
    assert not any(call[:2] == ["issue", "close"] for call in calls)


@pytest.mark.parametrize("check_fails", [False, True])
def test_integrate_pushes_a_public_mirror_after_running_the_check(
        main_checkout, local_config, monkeypatch, capsys, check_fails):
    worker = main_checkout.parent / "worker"
    mirror = main_checkout.parent / "mirror.git"
    git_ok("init", "-q", "--bare", "-b", "main", str(mirror))
    git_ok("-C", str(main_checkout), "remote", "add", "mirror", str(mirror))
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        'public_identity = "mb <mb>"\n\n'
        f'[mirrors]\n"{main_checkout.name}" = ['
        '{ remote = "mirror", branch = "main", fetch = false, public = true }]\n',
        encoding="utf-8",
    )
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "push", "-q", "mirror", "main")
    mirror_baseline = subprocess.run(
        ["git", "--git-dir", str(mirror), "rev-parse", "main"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    work_tickets.initialize(worker)
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    git_ok("-C", str(worker), "push", "-q", "mirror", "feature/worker")
    (main_checkout / "synced.txt").write_text("synced\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "synced.txt")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "main change")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "main")
    git_ok("-C", str(worker), "fetch", "-q", "origin")
    git_ok("-C", str(worker), "merge", "--no-edit", "origin/main")
    head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    report = {"body": reported_at(head)}
    calls: list[list[str]] = []
    bodies: list[str] = []
    started: list[int] = []
    commands: list[tuple[str, str]] = []
    checks: list[tuple[list[list[str]], bool]] = []
    guarded: list[tuple[str, Path]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    # On github.com, so the mirror guard knows the owner whose squash commits GitHub writes.
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/owner/repo")
    # The work issue's Goal names the work; the branch's last commit subject ("worker") does not.
    issue = {"body": "## Goal\n\nShip the worker file to main (SE#3, PR #4). It matters.\n\n"
                     + report["body"]}
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: issue)
    def gh_call(root, args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefName": "feature/worker", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        return ""
    monkeypatch.setattr(
        work_tickets, "run_gh",
        gh_call,
    )
    monkeypatch.setattr(
        work_tickets, "run_gh_with_body",
        lambda root, args, body: (calls.append(args), bodies.append(body)),
    )
    def run_project_command(root, command, description):
        commands.append((command, description))
        return "214 passed"

    monkeypatch.setattr(work_tickets, "run_project_command", run_project_command)
    monkeypatch.setattr(
        work_tickets, "run_suite",
        lambda root: suite_passed(root, run_project_command(root, "suite", "Complete suite")))
    def run_project_checks(root, check_commands, temporary):
        checks.append((check_commands, temporary))
        if check_fails:
            raise work_tickets.QueueError("Project check failed")
        return "passed"
    monkeypatch.setattr(work_tickets, "run_project_checks", run_project_checks)
    monkeypatch.setattr(
        work_tickets, "guard", lambda root, branch, report: guarded.append((branch, report)) or [],
    )
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [{"number": 9}])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
    monkeypatch.setattr(
        work_tickets, "start", lambda root, number, repo, directory, create: started.append(number)
    )

    if check_fails:
        with pytest.raises(work_tickets.QueueError, match="Project check failed"):
            work_tickets.integrate(main_checkout, 7, None, "build", [["check"]])
        mirror_head = subprocess.run(
            ["git", "--git-dir", str(mirror), "rev-parse", "main"],
            capture_output=True, text=True, check=False,
        )
        assert mirror_head.returncode == 0
        assert mirror_head.stdout.strip() == mirror_baseline
        return

    commit = work_tickets.integrate(main_checkout, 7, None, "build", [["check"]])
    assert (main_checkout / "worker.txt").is_file()
    assert squashed_onto_origin(main_checkout, commit)
    assert commit and started == [9]
    message = subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert message.startswith("Integrate feature/worker: Ship the worker file to main.\n\n")
    assert "\n\nRelease-kind: minor\n" in message  # the trailer push releases by
    assert "#" not in message
    assert "git.example" not in message
    assert "Co-authored-by" not in message  # no commit_trailer configured: none by default
    assert commands == [
        ("suite", "Complete suite"), ("build", "Output regeneration")
    ]
    assert checks == [([["check"]], False)]
    assert guarded and guarded[0][0] == "feature/worker"
    output = capsys.readouterr().out
    assert "Suite: 214 passed" in output
    assert "Cleanup: worker worktree removed" in output
    assert "Started: 1" in output
    mirror_head = subprocess.run(
        ["git", "--git-dir", str(mirror), "rev-parse", "main"],
        capture_output=True, text=True, check=False,
    )
    assert mirror_head.returncode == 0
    assert mirror_head.stdout.strip() == subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    closes = [call for call in calls if call[:2] == ["issue", "close"]]
    assert closes == [["issue", "close", "5", "--repo", "git.example/owner/tracker"]]
    assert all("from https://git.example/owner/repo/pull/7, landed through https://git.example/owner/repo/pull/20 (check: https://git.example/owner/repo/runs/1). Release: none. "
               "Suite: 214 passed." in body for body in bodies)
    assert not worker.exists()
    assert subprocess.run(
        ["git", "--git-dir", str(mirror), "show-ref", "--verify", "refs/heads/feature/worker"],
        capture_output=True, text=True, check=False,
    ).returncode == 0


@pytest.mark.parametrize(
    ("message", "email", "error"),
    [
        ("worker #12", "mb", "tracker reference"),
        ("worker", "other@example.invalid", "author differs"),
    ],
)
def test_public_mirror_guard_rejects_references_and_mismatched_identities(
        main_checkout, local_config, message, email, error):
    mirror = main_checkout.parent / "mirror.git"
    git_ok("init", "-q", "--bare", "-b", "main", str(mirror))
    git_ok("-C", str(main_checkout), "remote", "add", "mirror", str(mirror))
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        'public_identity = "mb <mb>"\n\n'
        f'[mirrors]\n"{main_checkout.name}" = ['
        '{ remote = "mirror", branch = "main", fetch = false, public = true }]\n',
        encoding="utf-8",
    )
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "push", "-q", "mirror", "main")
    (main_checkout / "public.txt").write_text("public\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "public.txt")
    git_ok(
        "-C", str(main_checkout), "-c", "user.name=mb", f"-c", f"user.email={email}",
        "commit", "-q", "-m", message,
    )

    with pytest.raises(work_tickets.QueueError, match=error):
        work_tickets.guard_public_push(
            main_checkout, work_tickets.Mirror("mirror", "main", False, True)
        )


@pytest.mark.parametrize("goal", ["Ship the worker, see #12.", "Ship https://example.invalid/worker."])
def test_public_merge_message_leaves_out_a_goal_with_tracker_references_or_host_addresses(goal):
    body = f"## Goal\n\n{goal}\n"
    assert work_tickets.integration_merge_message("feature/worker", 5, 7, True, body) == (
        "Integrate feature/worker")


def test_public_merge_message_rejects_a_branch_with_a_host_address():
    with pytest.raises(work_tickets.QueueError, match="cannot contain"):
        work_tickets.integration_merge_message("feature/a@b", 5, 7, True, "## Goal\n\nShip it.\n")


def test_integrate_conflict_aborts_without_escalating(main_checkout, monkeypatch):
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    (main_checkout / "shared.txt").write_text("main\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "shared.txt")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "shared base")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "main")
    worker = main_checkout.parent / "conflict-worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/conflict", str(worker))
    (worker / "shared.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "commit", "-am", "worker conflict")
    (main_checkout / "shared.txt").write_text("main changed\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "commit", "-am", "main conflict")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "main")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {"body": reported_at(head)}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/conflict", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    with pytest.raises(work_tickets.QueueError, match="shared.txt"):
        work_tickets.integrate(main_checkout, 7, None, None)
    assert not subprocess.run(["git", "-C", str(main_checkout), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    assert not any(call[:3] == ["issue", "comment", "5"] for call in calls)
    assert not any(call[:5] == ["issue", "edit", "5", "--add-label", "escalated"] for call in calls)
    assert not any(call[:2] == ["issue", "close"] for call in calls)


def test_integrate_keeps_worktree_when_cleanup_refuses(main_checkout, monkeypatch, capsys):
    worker = main_checkout.parent / "blocked-worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/blocked", str(worker))
    work_tickets.initialize(worker)
    work_tickets.create_ticket(worker, "T-1", "Unfinished")
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {"body": reported_at(head)}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/blocked", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, description: None)
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: suite_passed(root, "passed"))
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    work_tickets.integrate(main_checkout, 7, None, None)
    assert worker.exists()
    assert "worker worktree was not removed" in capsys.readouterr().err
    assert [call[2] for call in calls if call[:2] == ["issue", "close"]] == ["5"]

def integration_fakes(monkeypatch, head: str, reported: str | None = None) -> list[list[str]]:
    """Fakes for integrating PR #7 at `head`, its description's report at `reported` (`head`)."""
    report = {"body": reported_at(reported or head)}
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (
        json.dumps({"headRefName": "feature/worker", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(
        work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args) or "")
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, label: "1 passed")
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: suite_passed(root, "1 passed"))
    monkeypatch.setattr(work_tickets, "guard", lambda root, branch, report: [])
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 0)
    return calls


def test_integrate_refuses_commits_after_the_reported_tip_unless_their_inclusion_is_stated(
        main_checkout, monkeypatch):
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("reported\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "reported")
    reported = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    (worker / "worker.txt").write_text("late\n", encoding="utf-8")
    git_ok("-C", str(worker), "commit", "-qam", "pushed after delivery")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    calls = integration_fakes(monkeypatch, head, reported)
    bodies: list[str] = []
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, args, body: calls.append(args) or bodies.append(body) or "")

    with pytest.raises(work_tickets.QueueError) as refused:
        work_tickets.integrate(main_checkout, 7, None, None)
    assert (f"Branch feature/worker has commits after the field report's Branch tip "
            f"{reported[:12]}:\n- {head[:7]} pushed after delivery\nNothing was merged.") in str(
                refused.value)
    assert "the worker updates the field report in place" in str(refused.value)
    assert subprocess.run(["git", "-C", str(main_checkout), "merge-base", "--is-ancestor",
                           reported, "HEAD"], capture_output=True, check=False).returncode == 1
    assert not bodies

    work_tickets.integrate(main_checkout, 7, None, None, included="it fixes a typo the review asked for")
    assert all("Includes 1 commit(s) after the field report's Branch tip: it fixes a typo the "
               "review asked for" in body for body in bodies) and len(bodies) == 1


@pytest.mark.parametrize("leak", [False, True], ids=["clean", "leak"])
def test_integrate_writes_the_configured_integration_branch_and_leaves_main(
        main_checkout, monkeypatch, leak):
    origin = main_checkout.parent / "origin.git"
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "switch", "-q", "-c", "next")
    (main_checkout / "se.toml").write_text(
        IDENTITY + 'integration_branch = "next"\npublic_check = true\n', encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "se.toml")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "integrate into next")
    git_ok("-C", str(main_checkout), "push", "-q", "-u", "origin", "next")
    main_before = subprocess.run(
        ["git", "--git-dir", str(origin), "rev-parse", "refs/heads/main"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    work_tickets.initialize(worker)
    content = ("/" + "home/alice/repo\n") if leak else "worker\n"
    (worker / "worker.txt").write_text(content, encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    head = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    integration_fakes(monkeypatch, head)

    def origin_contains(ref: str) -> bool:
        return subprocess.run(
            ["git", "--git-dir", str(origin), "cat-file", "-e", f"{ref}:worker.txt"],
            capture_output=True, check=False,
        ).returncode == 0

    assert work_tickets.integration_branch(main_checkout) == "next"
    if leak:
        with pytest.raises(work_tickets.QueueError, match="Public check failed.*nothing was pushed"):
            work_tickets.integrate(main_checkout, 7, None, None)
        assert not origin_contains("refs/heads/next")
        return
    work_tickets.integrate(main_checkout, 7, None, None)

    assert origin_contains("refs/heads/next")
    assert not origin_contains("refs/heads/main")
    assert subprocess.run(
        ["git", "--git-dir", str(origin), "rev-parse", "refs/heads/main"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() == main_before


def delivered_worker(main_checkout: Path, monkeypatch) -> tuple[str, list[list[str]]]:
    """A worker branch feature/worker pushed to origin and delivered as PR #7; (head, gh calls)."""
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "Add the worker file")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    return head, integration_fakes(monkeypatch, head)


# The landing pull request's description for PR #7 of work issue #5: it names both and carries the
# marker by which CI's field-report step reads the report from PR #7 (README "Landing on main").
LANDING_BODY = ("Refs https://git.example/owner/tracker/issues/5\n\n"
                "Lands https://git.example/owner/repo/pull/7, whose description is the field report."
                "\n\n<!-- se:field-report-in 7 -->\n")


def origin_main(checkout: Path) -> str:
    return subprocess.run(["git", "--git-dir", str(checkout.parent / "origin.git"), "rev-parse",
                           "refs/heads/main"], capture_output=True, text=True, check=True).stdout.strip()


def test_integrate_lands_through_a_squash_pull_request_after_waiting_for_check(
        main_checkout, monkeypatch, github, capsys):
    head, calls = delivered_worker(main_checkout, monkeypatch)
    pending = {"id": 1, "status": "in_progress", "conclusion": None}
    github.checks = [None, pending, {"id": 2, "status": "completed", "conclusion": "success",
                                     "html_url": "https://git.example/owner/repo/runs/2"}]
    waits: list[int] = []
    monkeypatch.setattr(work_tickets, "wait", waits.append)

    commit = work_tickets.integrate(main_checkout, 7, None, None)

    landing = "land/feature/worker"
    title = "Integrate feature/worker (work issue #5, PR #7)"  # without a public check
    assert [call[0] for call in github.calls] == [
        "open_pull", "create_pull", "check_run", "check_run", "check_run", "squash", "pull",
        "comment", "close_pull"]
    assert github.calls[1] == ("create_pull", landing, "main", title)
    pull = github.pulls[0]
    assert pull["body"] == LANDING_BODY  # a link to the work pull request, whose description is the report
    assert waits == [30, 30]  # two polls before the run completed
    _, number, sha, squash_title, message = github.calls[5]
    assert (number, squash_title, message) == (20, title, "Release-kind: minor")
    assert squashed_onto_origin(main_checkout, commit)
    body = subprocess.run(["git", "-C", str(main_checkout), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert body.rstrip() == f"{title}\n\nRelease-kind: minor"  # what the merge commit carried, no (#20)
    tree = lambda ref: subprocess.run(["git", "-C", str(main_checkout), "rev-parse", f"{ref}^{{tree}}"],
                                      capture_output=True, text=True, check=True).stdout.strip()
    assert tree("main") == tree(sha)  # the tree the checks passed
    assert github.calls[-2:] == [
        ("comment", 7, f"Landed on main in {origin_main(main_checkout)[:12]} "
                       "through https://git.example/owner/repo/pull/20."),
        ("close_pull", 7)]
    out = capsys.readouterr().out
    assert "Landing pull request opened: https://git.example/owner/repo/pull/20" in out
    assert "Check check: not started" in out and "Check check: in_progress" in out
    assert subprocess.run(["git", "-C", str(main_checkout), "rev-parse", "--verify", landing],
                          capture_output=True, check=False).returncode != 0
    assert subprocess.run(["git", "--git-dir", str(main_checkout.parent / "origin.git"),
                           "rev-parse", "--verify", f"refs/heads/{landing}"],
                          capture_output=True, check=False).returncode != 0


def test_integrate_reuses_the_open_landing_pull_request(main_checkout, monkeypatch, github, capsys):
    head, _ = delivered_worker(main_checkout, monkeypatch)
    github.pulls.append({"number": 31, "head": "land/feature/worker", "base": "main",
                         "title": "old", "body": "old", "state": "open", "merged": False,
                         "html_url": "https://git.example/owner/repo/pull/31"})

    work_tickets.integrate(main_checkout, 7, None, None)

    assert [call[0] for call in github.calls][:3] == ["open_pull", "update_pull", "check_run"]
    assert github.pulls == [github.pulls[0]] and github.pulls[0]["merged"]
    assert github.pulls[0]["body"] == LANDING_BODY
    assert "Landing pull request reused: https://git.example/owner/repo/pull/31" in capsys.readouterr().out


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_a_failed_check_merges_nothing_and_escalates(main_checkout, monkeypatch, github, conclusion):
    _, calls = delivered_worker(main_checkout, monkeypatch)
    before = origin_main(main_checkout)
    github.checks = [{"id": 3, "status": "completed", "conclusion": conclusion,
                      "html_url": "https://git.example/owner/repo/runs/3"}]

    with pytest.raises(work_tickets.QueueError,
                       match=f"check concluded {conclusion} .*runs/3.*nothing was merged"):
        work_tickets.integrate(main_checkout, 7, None, None)

    assert origin_main(main_checkout) == before
    assert not any(call[0] == "squash" for call in github.calls)
    assert subprocess.run(["git", "-C", str(main_checkout), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip() == "main"
    assert any(call[:5] == ["issue", "edit", "5", "--add-label", "escalated"] for call in calls)
    assert not any(call[:2] == ["issue", "close"] for call in calls)


def test_a_check_that_never_finishes_is_refused_after_the_last_poll(main_checkout, monkeypatch, github):
    delivered_worker(main_checkout, monkeypatch)
    github.checks = [{"id": 4, "status": "queued", "conclusion": None}]
    monkeypatch.setattr(work_tickets, "CHECK_POLLS", 3)

    with pytest.raises(work_tickets.QueueError, match="did not finish .* within 1 minutes"):
        work_tickets.integrate(main_checkout, 7, None, None)
    assert [call[0] for call in github.calls].count("check_run") == 3


def test_a_main_that_moved_during_the_wait_is_not_squashed_onto(main_checkout, monkeypatch, github):
    delivered_worker(main_checkout, monkeypatch)
    other = main_checkout.parent / "other"

    def moved(sha, name):
        git_ok("-C", str(other), "pull", "-q", "origin", "main")
        git_ok("-C", str(other), "-c", "user.name=mb", "-c", "user.email=mb", "commit", "-q",
               "--allow-empty", "-m", "elsewhere")
        git_ok("-C", str(other), "push", "-q", "origin", "HEAD:main")
        return {"id": 5, "status": "completed", "conclusion": "success"}
    github.check_run = moved

    with pytest.raises(work_tickets.QueueError, match="origin's main moved .*nothing was merged"):
        work_tickets.integrate(main_checkout, 7, None, None)
    assert not any(call[0] == "squash" for call in github.calls)


def test_a_squash_that_does_not_read_back_as_merged_is_refused(main_checkout, monkeypatch, github):
    delivered_worker(main_checkout, monkeypatch)
    squash = github.squash
    github.squash = lambda number, sha, title, message: (squash(number, sha, title, message), "0" * 40)[1]

    with pytest.raises(work_tickets.QueueError, match="reads back as merged=True .*not the squash commit"):
        work_tickets.integrate(main_checkout, 7, None, None)


def test_the_door_speaks_github_s_rest_api_through_gh(tmp_path, monkeypatch):
    calls: list[tuple[list[str], object]] = []

    def gh(root, arguments):
        sent = (json.loads(Path(arguments[arguments.index("--input") + 1]).read_text())
                if "--input" in arguments else None)
        calls.append((arguments, sent))
        path = arguments[3]
        if path.endswith("/merge"):
            return '{"sha": "abc", "merged": true}'
        if "check-runs" in path:
            return '{"check_runs": [{"id": 1, "status": "queued"}, {"id": 2, "status": "completed"}]}'
        if "pulls?" in path:
            return "[]"
        return '{"number": 9}'
    monkeypatch.setattr(work_tickets, "run_gh", gh)
    door = REAL_GITHUB(tmp_path, "github.com/owner/repo")

    assert door.open_pull("land/x", "main") is None
    assert door.create_pull("land/x", "main", "T", "B") == {"number": 9}
    assert door.check_run("abc", "check") == {"id": 2, "status": "completed"}
    assert door.squash(9, "abc", "T", "M") == "abc"
    door.comment(7, "Landed")
    door.close_pull(7)
    assert [(arguments[2], arguments[3], sent) for arguments, sent in calls] == [
        ("GET", "repos/owner/repo/pulls?state=open&head=owner:land/x&base=main", None),
        ("POST", "repos/owner/repo/pulls", {"head": "land/x", "base": "main", "title": "T", "body": "B"}),
        ("GET", "repos/owner/repo/commits/abc/check-runs?check_name=check", None),
        ("PUT", "repos/owner/repo/pulls/9/merge", {"merge_method": "squash", "sha": "abc",
                                                    "commit_title": "T", "commit_message": "M"}),
        ("POST", "repos/owner/repo/issues/7/comments", {"body": "Landed"}),
        ("PATCH", "repos/owner/repo/pulls/7", {"state": "closed"}),
    ]


# The hand-off: where gh is not signed in, integrate prints its GitHub steps as a plan, the
# session runs them with its own GitHub tools, and --read-back checks the result through git.


def handed_off_worker(main_checkout: Path, monkeypatch, github) -> tuple[str, list[str]]:
    """feature/worker delivered as PR #7 with gh not signed in; (head, the integrate arguments
    the session passes: the description and issue body it saved, the head branch)."""
    head, _ = delivered_worker(main_checkout, monkeypatch)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: pytest.fail(f"gh {args}"))
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, args, body: pytest.fail(f"gh {args}"))
    saved = main_checkout.parent / "saved"
    saved.mkdir()
    (saved / "pr.md").write_text(reported_at(head), encoding="utf-8")
    (saved / "issue.md").write_text(reported_at(head), encoding="utf-8")
    return head, ["integrate", "7", "--pr-description", str(saved / "pr.md"),
                  "--issue-body", str(saved / "issue.md"), "--branch", "feature/worker"]


def session_squash(checkout: Path, ref: str, tree_of: str | None = None) -> str:
    """What the session's merge_pull_request does: one squash commit of `ref` (or of the tree of
    `tree_of`) on origin's main, written for the owner by GitHub's web-flow identity."""
    origin = checkout.parent / "origin.git"
    def git(*arguments: str, env: dict | None = None) -> str:
        return subprocess.run(["git", "--git-dir", str(origin), *arguments], capture_output=True,
                              text=True, check=True, env=env).stdout.strip()
    main = git("rev-parse", "refs/heads/main")
    env = {**os.environ, "GIT_AUTHOR_NAME": "owner",
           "GIT_AUTHOR_EMAIL": "1+owner@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply" + "@github.com"}
    commit = git("commit-tree", f"{tree_of or ref}^{{tree}}", "-p", main, "-m", "squash", env=env)
    git("update-ref", "refs/heads/main", commit, main)
    return commit


def test_integrate_hands_off_a_plan_of_github_steps_where_gh_is_not_signed_in(
        main_checkout, monkeypatch, github, capsys):
    head, arguments = handed_off_worker(main_checkout, monkeypatch, github)
    base = origin_main(main_checkout)

    assert run(main_checkout, *arguments) == 0

    out = capsys.readouterr().out
    assert github.calls == []  # nothing reached GitHub: the session runs the steps
    landing = "land/feature/worker"
    origin = main_checkout.parent / "origin.git"
    landed = subprocess.run(["git", "--git-dir", str(origin), "rev-parse", f"refs/heads/{landing}"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert origin_main(main_checkout) == base  # main itself is GitHub's to move
    title = "Integrate feature/worker (work issue #5, PR #7)"
    plan = json.loads((main_checkout / ".se" / "handoff" / "feature-worker.json")
                      .read_text(encoding="utf-8"))["plan"]
    assert [step["tool"] for step in plan["steps"]] == [
        "create_pull_request", "pull_request_read", "merge_pull_request"]
    opened, checked, merged = (step["arguments"] for step in plan["steps"])
    assert opened == {"owner": "owner", "repo": "repo", "head": landing, "base": "main",
                      "title": title, "body": LANDING_BODY}
    assert checked == {"owner": "owner", "repo": "repo", "method": "get_check_runs",
                       "pullNumber": "<pull number from step 1>"}
    assert merged == {"owner": "owner", "repo": "repo", "pullNumber": "<pull number from step 1>",
                      "merge_method": "squash", "commit_title": title,
                      "commit_message": "Release-kind: minor", "expectedHeadSha": landed}
    assert "update_pull_request that one" in plan["steps"][0]["note"]
    assert f"check run check on {landed} completes" in plan["steps"][1]["note"]
    assert f"still {base}" in plan["steps"][2]["note"]
    assert plan["then"].startswith("work_tickets.py integrate --read-back feature/worker "
                                   "--landing-pull <pull number from step 1> --check-run")
    assert "GitHub plan: land land/feature/worker on main\n1. create_pull_request " in out
    assert '"expectedHeadSha": "' + landed + '"' in out
    assert "Run the plan's steps, then its last line for pull request #7" in out
    assert subprocess.run(["git", "-C", str(main_checkout), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip() == "main"


def test_the_hand_off_plan_titles_by_the_goal_and_links_a_report_over_the_body_limit(
        main_checkout, monkeypatch, github):
    """The plan runs unedited: its title names the work issue's Goal, not the branch's last commit
    subject, and its body stays small while the field report exceeds GitHub's body limit."""
    head, arguments = handed_off_worker(main_checkout, monkeypatch, github)
    saved = main_checkout.parent / "saved"
    report = reported_at(head).replace("## Spec gaps\n\nNone.",
                                       "## Spec gaps\n\n" + "A long finding. " * 5000)
    assert len(report) > 65536  # GitHub's limit on a pull request body
    (saved / "pr.md").write_text(report, encoding="utf-8")
    (saved / "issue.md").write_text(
        "## Goal\n\nLand the worker file on main (SE#3, PR #4). Why it matters.\n\n" + report,
        encoding="utf-8")

    assert run(main_checkout, *arguments) == 0

    title = "Integrate feature/worker: Land the worker file on main. (work issue #5, PR #7)"
    assert "Add the worker file" not in title  # the branch's last commit subject, unrelated
    plan = json.loads((main_checkout / ".se" / "handoff" / "feature-worker.json")
                      .read_text(encoding="utf-8"))["plan"]
    opened, _, merged = (step["arguments"] for step in plan["steps"])
    assert (opened["title"], merged["commit_title"]) == (title, title)
    assert opened["body"] == LANDING_BODY and len(opened["body"]) < 1024


@pytest.mark.parametrize(("goal", "summary"), [
    ("The first landing (SE#851, PR #853) showed two flaws. Fix both.",
     "The first landing showed two flaws."),
    ("<!-- template comment -->\nShip   it\nnow", "Ship it now"),
    ("See #12 for the cause.", ""),  # a tracker reference outside an aside: no summary
    ("", ""),
])
def test_the_goal_summary_is_the_goal_s_first_sentence_without_tracker_asides(goal, summary):
    assert work_tickets.goal_summary(f"## Goal\n\n{goal}\n\n## Package kind\n\npatch\n") == summary


def test_integrate_read_back_checks_the_landing_through_git_and_hands_off_the_close_out(
        main_checkout, monkeypatch, github, capsys):
    head, arguments = handed_off_worker(main_checkout, monkeypatch, github)
    assert run(main_checkout, *arguments) == 0
    landing = "land/feature/worker"
    commit = session_squash(main_checkout, f"refs/heads/{landing}")
    capsys.readouterr()

    assert run(main_checkout, "integrate", "--read-back", "feature/worker", "--landing-pull", "20",
               "--check-run", "https://git.example/owner/repo/runs/4") == 0

    out = capsys.readouterr().out
    assert squashed_onto_origin(main_checkout, commit)
    assert f"Landed: {commit[:12]} on main" in out
    assert "GitHub plan: close out #5\n" in out
    assert ('1. add_issue_comment {"body": "Landed on main in ' + commit[:12]
            + ' through https://git.example/owner/repo/pull/20.", "issue_number": 7') in out
    assert '2. update_pull_request {"owner": "owner", "pullNumber": 7, "repo": "repo", "state": "closed"}' in out
    assert ('3. add_issue_comment {"body": "Integrated in ' in out
            and "landed through https://git.example/owner/repo/pull/20 "
                "(check: https://git.example/owner/repo/runs/4)" in out)
    assert '"repo": "tracker"' in out  # the work issue lives in the tracker
    assert "<the issue's labels without in-progress>" in out
    assert '5. issue_write {"issue_number": 5, "method": "update", "owner": "owner", "repo": ' \
           '"tracker", "state": "closed", "state_reason": "completed"}' in out
    assert "Started: none here" in out
    assert not (main_checkout / ".se" / "handoff" / "feature-worker.json").exists()
    assert github.calls == []


@pytest.mark.parametrize("landing, message", [
    (None, "is still .*the squash merge has not landed"),
    ("other tree", "its tree is not the tree of"),
])
def test_integrate_read_back_refuses_a_main_that_is_not_the_tested_landing(
        main_checkout, monkeypatch, github, capsys, landing, message):
    _, arguments = handed_off_worker(main_checkout, monkeypatch, github)
    assert run(main_checkout, *arguments) == 0
    if landing:
        session_squash(main_checkout, "refs/heads/main", tree_of="refs/heads/main~1")
    capsys.readouterr()

    assert run(main_checkout, "integrate", "--read-back", "feature/worker", "--landing-pull", "20",
               "--check-run", "https://git.example/owner/repo/runs/4") == 1

    assert re.search(message, capsys.readouterr().err)
    assert (main_checkout / ".se" / "handoff" / "feature-worker.json").exists()  # read back again


def test_integrate_chooses_the_hand_off_where_gh_is_not_signed_in(
        main_checkout, monkeypatch, github, capsys):
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: False)
    assert REAL_HAND_OFF() is True
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    assert REAL_HAND_OFF() is False
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")

    assert run(main_checkout, "integrate", "7") == 1
    error = capsys.readouterr().err
    assert "hands its GitHub steps to the session, as gh is not signed in" in error
    assert "--pr-description <file> --issue-body <file> --branch" in error
    assert github.calls == []


def test_a_hand_off_escalation_is_a_plan_too(capsys):
    plan = work_tickets.escalation_plan("github.com/owner/tracker", 5, "conflicts")
    assert [step.tool for step in plan.steps] == ["add_issue_comment", "issue_write"]
    assert plan.steps[0].arguments == {"owner": "owner", "repo": "tracker", "issue_number": 5,
                                       "body": "Integration stopped: conflicts\n"}
    assert plan.steps[1].arguments["labels"] == "<the issue's labels with escalated>"


def test_integrate_refuses_a_checkout_off_the_integration_branch(main_checkout, monkeypatch):
    (main_checkout / "se.toml").write_text('[project]\nintegration_branch = "next"\n', encoding="utf-8")
    integration_fakes(monkeypatch, "0" * 40)

    with pytest.raises(work_tickets.QueueError, match="not on the integration branch next.*switch next"):
        work_tickets.integrate(main_checkout, 7, None, None)


def test_integration_branch_defaults_to_main_and_rejects_an_empty_name(worktree):
    assert work_tickets.integration_branch(worktree) == "main"
    (worktree / "se.toml").write_text('[project]\nintegration_branch = ""\n', encoding="utf-8")
    with pytest.raises(work_tickets.QueueError, match="se.toml.*remove it to use main"):
        work_tickets.integration_branch(worktree)


def test_delete_merged_branch_leaves_a_branch_the_host_refuses_to_delete(main_checkout, capsys):
    origin = main_checkout.parent / "origin.git"
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do\n"
        "  case $new in 0000000000000000000000000000000000000000) "
        "echo 'deletion refused' >&2; exit 1;; esac\ndone\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "branch", "feature/merged")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "feature/merged")
    head = subprocess.run(
        ["git", "-C", str(main_checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    work_tickets.delete_merged_branch(main_checkout, "feature/merged", head)

    err = capsys.readouterr().err
    assert err.count("refused deleting feature/merged") == 1
    assert "automatic head-branch deletion, not retried" in err
    assert subprocess.run(
        ["git", "--git-dir", str(origin), "rev-parse", "--verify", "refs/heads/feature/merged"],
        capture_output=True, check=False,
    ).returncode == 0


FAKE_SUITE = """\
import sys
print("warning: from the launcher", file=sys.stderr)
print("....")
print("==== slowest 10 durations ====")
print("0.20s call     tests/test_fast.py::test_quick")
print("3.10s call     tests/test_slow.py::test_sleepy")
print("0.90s setup    tests/test_slow.py::test_fixture")
print("3 passed")
"""


def fake_suite(worktree: Path, monkeypatch, seconds: float) -> None:
    """A fake suite in se.toml `[tests]` and a clock that says it took `seconds`."""
    (worktree / "suite.py").write_text(FAKE_SUITE, encoding="utf-8")
    (worktree / "se.toml").write_text(
        f"[tests]\ncommand = {json.dumps([sys.executable, 'suite.py'])}\n"
        "target_seconds = 60\nlimit_seconds = 120\n",
        encoding="utf-8",
    )
    readings = iter([0.0, seconds])
    monkeypatch.setattr(work_tickets, "clock", lambda: next(readings))


def test_suite_passing_over_the_limit_says_passed_and_refuses_with_its_own_exit_code(
        worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 130.0)

    assert run(worktree, "suite") == work_tickets.SUITE_OVER_LIMIT_EXIT_CODE != 1
    error = capsys.readouterr().err
    assert "Complete suite passed (3 passed) but took 130.0 s, over its limit of 120 s" in error
    assert "rerun it once on an idle host" in error
    assert "if it is still over, make the slowest tests above faster" in error
    assert error.index("test_sleepy") < error.index("test_fixture") < error.index("test_quick")


FAILING_SUITE = FAKE_SUITE.replace('print("3 passed")', 'print("1 failed, 2 passed")\nsys.exit(1)')


@pytest.mark.parametrize("seconds", [5.0, 130.0])
def test_suite_failing_says_failed_with_its_counts_and_exits_1(
        worktree, monkeypatch, capsys, seconds):
    fake_suite(worktree, monkeypatch, seconds)
    (worktree / "suite.py").write_text(FAILING_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 1
    error = capsys.readouterr().err
    assert f"Complete suite failed (1 failed, 2 passed; {seconds:.1f} s" in error
    assert "warning: from the launcher" in error  # stderr stays in a failure's full output
    assert "over its limit" not in error


def test_suite_between_target_and_limit_warns_and_names_the_slowest(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 90.0)

    assert run(worktree, "suite") == 0
    captured = capsys.readouterr()
    assert "warning: the complete suite took 90.0 s, over its target of 60 s" in captured.err
    assert "3.10s call tests/test_slow.py::test_sleepy" in captured.out
    assert "Suite: 3 passed; 90.0 s (target 60 s, limit 120 s)" in captured.out


def test_suite_under_the_target_passes_quietly(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)

    assert run(worktree, "suite") == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Suite time: 5.0 s (target 60 s, limit 120 s)" in captured.out
    tail = captured.out.split("Suite output (last lines):\n", 1)[1].split("Suite time:", 1)[0]
    assert "  3 passed" in tail and "test_sleepy" not in tail


PYTEST_SUITE = """\
import sys
print("warning: The `UV_NATIVE_TLS` environment variable is deprecated", file=sys.stderr)
print("........................................ [ 50%]")
print("....s...x............................... [100%]")
print("============================= slowest 10 durations =============================")
print("0.20s call     tests/test_fast.py::test_quick")
print("3 passed, 1 skipped, 1 xfailed in 1.20s")
"""


def test_suite_success_tail_shows_only_the_result_lines_of_stdout(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(PYTEST_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    tail = out.split("Suite output (last lines):\n", 1)[1].split("Suite time:", 1)[0]
    assert tail == "  3 passed, 1 skipped, 1 xfailed in 1.20s\n"


REPORTING_SUITE = """\
import os, pathlib
reports = pathlib.Path(os.environ["SE_TEST_REPORTS"])
(reports / "unit.xml").write_text(
    '<testsuites><testsuite name="pytest">'
    '<testcase classname="tests.test_a" name="test_quick" time="0.10"/>'
    '<testcase classname="tests.test_a" name="test_slow" time="2.50"/>'
    '</testsuite></testsuites>', encoding="utf-8")
(reports / "browser.xml").write_text(
    '<testsuite name="browser">'
    + "".join(f'<testcase classname="ui" name="page{i}" time="{i / 10}"/>' for i in range(1, 12))
    + '</testsuite>', encoding="utf-8")
print("13 passed")
"""


def test_suite_merges_the_slowest_ten_from_every_junit_report(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(REPORTING_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    listed = out.split("Slowest tests:\n", 1)[1].split("Suite:", 1)[0].splitlines()
    assert listed[0] == "  2.50s unit tests.test_a::test_slow"
    assert listed[1] == "  1.10s browser ui::page11"
    assert len(listed) == 10
    assert "test_quick" not in out and "page2" not in out


def test_suite_slowest_sets_how_many_tests_it_lists(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(REPORTING_SUITE, encoding="utf-8")

    assert run(worktree, "suite", "--slowest", "3") == 0
    out = capsys.readouterr().out
    listed = out.split("Slowest tests:\n", 1)[1].split("Suite:", 1)[0].splitlines()
    assert listed == [
        "  2.50s unit tests.test_a::test_slow", "  1.10s browser ui::page11", "  1.00s browser ui::page10",
    ]
    assert work_tickets.with_durations(["uv", "run", "pytest", "-q"], 3)[-1] == "--durations=3"


WORKER_SUITE = """\
import os, pathlib
reports = pathlib.Path(os.environ["SE_TEST_REPORTS"])
(reports / "adapters-html.xml").write_text(
    '<testsuites><testsuite name="pytest" time="84.2">'
    '<properties><property name="workers" value="4"/></properties>'
    '<testcase classname="tests.test_html" name="test_big" time="17.5"/>'
    + "".join(f'<testcase classname="tests.test_html" name="test_{i}" time="12.7"/>' for i in range(23))
    + '</testsuite></testsuites>', encoding="utf-8")
print("24 passed")
"""


def test_suite_shows_each_parts_test_time_per_worker_and_slowest(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(WORKER_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    parts = out.split("Parts:\n", 1)[1].split("Slowest tests:", 1)[0]
    assert parts == (
        "  adapters-html: 84.2 s wall; 309.6 s test time / 4 workers = 77.4 s; slowest 17.5 s\n"
    )


SETUP_SUITE = """\
import os, pathlib
reports = pathlib.Path(os.environ["SE_TEST_REPORTS"])
def case(name, seconds, setup, worker, fixture=""):
    props = f'<property name="setup_time" value="{setup}"/><property name="worker" value="{worker}"/>'
    if fixture:
        props += f'<property name="fixture" value="{fixture}"/>'
    return (f'<testcase classname="tests.test_ui" name="{name}" time="{seconds}">'
            f'<properties>{props}</properties></testcase>')
(reports / "ui.xml").write_text(
    '<testsuites><testsuite name="pytest" time="20.0">'
    '<properties><property name="workers" value="2"/></properties>'
    + case("test_a", 8.0, 6.0, "gw0", "browser") + case("test_b", 9.0, 6.5, "gw1", "browser")
    + case("test_c", 1.0, 0.1, "gw0") + case("test_d", 4.0, 2.5, "gw1")
    + '</testsuite></testsuites>', encoding="utf-8")
print("4 passed")
"""


def test_suite_lists_slow_setups_and_a_setup_paid_on_several_workers(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(SETUP_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    parts = out.split("Parts:\n", 1)[1].split("Slowest tests:", 1)[0]
    assert parts == (
        "  ui: 20.0 s wall; 22.0 s test time / 2 workers = 11.0 s; slowest 9.0 s\n"
        "    slow setup 6.5 s tests.test_ui::test_b (browser, worker gw1)\n"
        "    slow setup 6.0 s tests.test_ui::test_a (browser, worker gw0)\n"
        "    slow setup 2.5 s tests.test_ui::test_d (tests.test_ui, worker gw1)\n"
        "    setup browser paid on 2 workers (gw0, gw1): 12.5 s; group its tests on one worker\n"
    )


TIER_FUNCTION = """\
def tier(test):
    return "browser" if test.startswith("ui::") else "unit"
"""


def with_tier(worktree: Path, module: str) -> None:
    """A fixture tier function in `<module>.py` and `[tests] tier` naming it."""
    (worktree / f"{module}.py").write_text(TIER_FUNCTION, encoding="utf-8")
    with (worktree / "se.toml").open("a", encoding="utf-8") as config:
        config.write(f'tier = "{module}:tier"\n')


def test_suite_with_a_tier_function_prints_each_tiers_slowest_test(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(REPORTING_SUITE, encoding="utf-8")
    with_tier(worktree, "fixture_tiers_print")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    tiers = out.split("Slowest per tier:\n", 1)[1].split("Suite:", 1)[0]
    assert tiers == (
        "  browser: 1.10s browser ui::page11\n"
        "  unit: 2.50s unit tests.test_a::test_slow\n"
    )


def test_suite_without_a_tier_setting_prints_no_tiers(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(REPORTING_SUITE, encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    assert "Slowest per tier:" not in out
    assert out.split("Slowest tests:\n", 1)[1].split("Suite:", 1)[0].count("\n") == 10


@pytest.mark.parametrize("setting, refusal", [
    ('"no-colon"', 'tier must name the project\'s tier function as "<module>:<function>"'),
    ('"fixture_tiers_missing:tier"', "cannot import fixture_tiers_missing from the project root"),
    ('"fixture_tiers_refuse:other"', "fixture_tiers_refuse has no function other"),
])
def test_suite_refuses_a_tier_setting_it_cannot_load_before_running(
        worktree, monkeypatch, capsys, setting, refusal):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "fixture_tiers_refuse.py").write_text(TIER_FUNCTION, encoding="utf-8")
    with (worktree / "se.toml").open("a", encoding="utf-8") as config:
        config.write(f"tier = {setting}\n")

    assert run(worktree, "suite") == 1
    captured = capsys.readouterr()
    assert refusal in captured.err and "Suite time:" not in captured.out


def test_ses_own_suite_reports_its_parts_line_with_workers_and_setup_times(worktree, monkeypatch, capsys):
    """se's conftest writes the JUnit report `suite` reads (README "Test budget")."""
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "pytest", "-q", "-n", "1", "-p", "no:cacheprovider",
               "--rootdir", str(root), str(root / "tests" / "test_se_plugin.py"), "-k", "layouts_match or one_source"]
    (worktree / "se.toml").write_text(f"[tests]\ncommand = {json.dumps(command)}\n", encoding="utf-8")
    readings = iter([0.0, 5.0])
    monkeypatch.setattr(work_tickets, "clock", lambda: next(readings))
    monkeypatch.setattr(work_tickets, "SLOW_SETUP_SECONDS", -1.0)  # list every setup

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    parts = out.split("Parts:\n", 1)[1].split("Slowest tests:", 1)[0]
    assert parts.startswith("  se: ") and " / 1 worker = " in parts
    assert "    slow setup " in parts and ", worker gw0)" in parts


def test_suite_without_reports_or_durations_names_the_remedy_once(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text('print("1 passed")\n', encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    assert out.count("write JUnit XML to $SE_TEST_REPORTS") == 1
    assert "Parts:" not in out


SETUP = """\
import sys
print("installing browsers")
print("setup: 2 browsers ready")
"""


def fake_setup(worktree: Path, monkeypatch, setup_seconds: float, suite_seconds: float,
               script: str = SETUP) -> None:
    """The fake suite with a fake `[tests]` setup; the clock says how long each took."""
    fake_suite(worktree, monkeypatch, suite_seconds)
    (worktree / "setup.py").write_text(script, encoding="utf-8")
    with (worktree / "se.toml").open("a", encoding="utf-8") as config:
        config.write(f"setup = {json.dumps([sys.executable, 'setup.py'])}\n")
    readings = iter([0.0, setup_seconds, 100.0, 100.0 + suite_seconds])
    monkeypatch.setattr(work_tickets, "clock", lambda: next(readings))


def test_suite_setup_is_timed_apart_and_not_held_to_the_budget(worktree, monkeypatch, capsys):
    fake_setup(worktree, monkeypatch, setup_seconds=200.0, suite_seconds=5.0)

    assert run(worktree, "suite") == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Setup time: 200.0 s (not budgeted)" in captured.out
    assert "  setup: 2 browsers ready" in captured.out
    assert "Suite time: 5.0 s (target 60 s, limit 120 s)" in captured.out
    assert captured.out.index("Setup time") < captured.out.index("Suite time")


def test_suite_setup_failing_stops_the_run_with_its_output(worktree, monkeypatch, capsys):
    failing = SETUP + 'print("no network", file=sys.stderr)\nsys.exit(2)\n'
    fake_setup(worktree, monkeypatch, 3.0, 5.0, failing)
    (worktree / "suite.py").write_text('raise SystemExit("suite ran")\n', encoding="utf-8")

    assert run(worktree, "suite") == 1
    error = capsys.readouterr().err
    assert "Suite setup failed (exit code 2; 3.0 s) running" in error
    assert "setup.py ([tests] setup in se.toml)" in error
    assert "installing browsers" in error and "no network" in error
    assert "suite ran" not in error


def test_suite_passing_prints_the_last_lines_of_its_own_output(worktree, monkeypatch, capsys):
    fake_suite(worktree, monkeypatch, 5.0)
    (worktree / "suite.py").write_text(
        "".join(f'print("line {i}")\n' for i in range(20)) + 'print("browser part: 4 passed")\n'
        'print("3 passed")\n', encoding="utf-8")

    assert run(worktree, "suite") == 0
    out = capsys.readouterr().out
    assert "  browser part: 4 passed\n  3 passed" in out
    assert "line 19" in out and "line 0\n" not in out


def test_suite_budget_refuses_a_setup_that_is_not_an_argument_array(worktree):
    (worktree / "se.toml").write_text('[tests]\ncommand = ["pytest"]\nsetup = "make deps"\n',
                                      encoding="utf-8")
    with pytest.raises(work_tickets.QueueError, match=r"setup must be a non-empty argument array"):
        work_tickets.suite_budget(worktree)


def test_suite_budget_defaults_and_refuses_a_missing_command(worktree):
    (worktree / "se.toml").write_text('[tests]\ncommand = ["uv", "run", "pytest", "-q"]\n',
                                      encoding="utf-8")
    budget = work_tickets.suite_budget(worktree)
    assert (budget.target_seconds, budget.limit_seconds) == (60, 120)
    assert work_tickets.with_durations(budget.command, work_tickets.SLOWEST_TESTS)[-1] == "--durations=10"
    (worktree / "se.toml").write_text("[tests]\ntarget_seconds = 60\n", encoding="utf-8")
    with pytest.raises(work_tickets.QueueError, match=r"\[tests\] in .*se.toml must declare command"):
        work_tickets.suite_budget(worktree)


@pytest.fixture
def compare_checkout(main_checkout, monkeypatch):
    """A checkout whose se.toml declares a suite, committed as `base`, and a fake suite runner:
    each call takes the next set duration of its state ("HEAD" here, "base" in the temporary
    worktree of `base`) and is recorded in order; nothing runs and no clock is read."""
    (main_checkout / "se.toml").write_text('[tests]\ncommand = ["pytest"]\n', encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "se.toml")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "suite")
    git_ok("-C", str(main_checkout), "branch", "base")
    calls, durations = [], {"HEAD": [], "base": []}

    def time_suite(checkout, command):
        state = "HEAD" if checkout == main_checkout else "base"
        assert state == "HEAD" or (checkout / "se.toml").is_file()
        calls.append(state)
        part = work_tickets.SuitePart(f"part-{state}", 1.0, 1, [(1.0, "t")])
        return work_tickets.SuiteRun(durations[state].pop(0), 0, "1 passed", "1 passed", [part])

    monkeypatch.setattr(work_tickets, "time_suite", time_suite)
    return main_checkout, calls, durations


def test_suite_compare_interleaves_the_states_after_an_uncounted_warm_up(compare_checkout, capsys):
    checkout, calls, durations = compare_checkout
    durations["HEAD"] += [99.0, 10.0, 11.0, 12.0]
    durations["base"] += [77.0, 10.0, 10.5, 11.0]

    assert work_tickets.main(["suite", "--compare", "base", "--runs", "3",
                              "--worktree", str(checkout)]) == 0
    assert calls == ["HEAD", "base"] * 4
    out = capsys.readouterr().out
    head, base = out.split("HEAD:\n", 1)[1].split("base:\n", 1)
    assert "Wall times: 10.0 s, 11.0 s, 12.0 s\n  Mean: 11.0 s" in head and "99" not in head
    assert "Wall times: 10.0 s, 10.5 s, 11.0 s\n  Mean: 10.5 s" in base and "77" not in base
    assert "Parts (run 1):\n    part-HEAD: 1.0 s wall" in head
    assert "Difference of the means: +0.5 s (HEAD minus base); observed spread 2.0 s" in out
    assert out.rstrip().endswith("Verdict: not slower")
    assert subprocess.run(["git", "-C", str(checkout), "worktree", "list"], capture_output=True,
                          text=True, check=False).stdout.count("\n") == 1  # the temporary one is gone


@pytest.mark.parametrize(("head", "verdict"), [
    ([10.0, 11.0], "not slower"),  # means 10.5 against 9.5: 1.0 s, the spread exactly
    ([10.2, 11.0], "slower by 1.1 s"),  # means 10.6 against 9.5: 1.1 s, past the spread of 1.0
])
def test_suite_compare_verdict_at_the_edge_of_the_spread(compare_checkout, capsys, head, verdict):
    checkout, _, durations = compare_checkout
    durations["HEAD"] += [1.0, *head]
    durations["base"] += [1.0, 9.0, 10.0]

    assert work_tickets.main(["suite", "--compare", "base", "--worktree", str(checkout)]) == 0
    assert capsys.readouterr().out.rstrip().endswith(f"Verdict: {verdict}")


def test_suite_compare_measures_a_branch_as_published_not_its_stale_local_copy(
        compare_checkout, capsys):
    """A local branch that sync never moves predates [tests]; origin's copy declares it."""
    checkout, calls, durations = compare_checkout
    git_ok("-C", str(checkout), "branch", "stale", "HEAD~1")
    git_ok("-C", str(checkout), "push", "-q", "origin", "HEAD:refs/heads/stale")
    git_ok("-C", str(checkout), "fetch", "-q", "origin")
    durations["HEAD"] += [1.0, 10.0, 10.0]
    durations["base"] += [1.0, 10.0, 10.0]

    assert work_tickets.main(["suite", "--compare", "stale", "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "Suite compare: HEAD against stale (origin/stale at " in out
    assert out.rstrip().endswith("Verdict: not slower")
    assert calls == ["HEAD", "base"] * 3


def test_suite_compare_refuses_a_ref_that_predates_tests_naming_it_and_the_remedy(
        compare_checkout, capsys):
    checkout, calls, _ = compare_checkout

    assert work_tickets.main(["suite", "--compare", "HEAD~1", "--worktree", str(checkout)]) == 1
    err = capsys.readouterr().err
    assert "suite --compare: HEAD~1 (" in err
    assert "declares no [tests] command in its se.toml; it predates [tests]" in err
    assert "compare against a ref that declares it" in err
    assert calls == []
    assert subprocess.run(["git", "-C", str(checkout), "worktree", "list"], capture_output=True,
                          text=True, check=False).stdout.count("\n") == 1


def test_suite_compare_refuses_a_ref_it_cannot_check_out(compare_checkout, capsys):
    checkout, calls, _ = compare_checkout

    assert work_tickets.main(["suite", "--compare", "no-such-ref", "--worktree", str(checkout)]) == 1
    assert "suite --compare cannot check out no-such-ref" in capsys.readouterr().err
    assert calls == []


TRANSIENT = "remote: fatal error in commit_refs_rules\nerror: failed to push some refs"
NON_FAST_FORWARD = (
    " ! [rejected]        topic -> topic (non-fast-forward)\nerror: failed to push some refs"
)


@pytest.fixture
def fake_push(main_checkout, monkeypatch):
    """A fake git push answering from a script of (exit code, stderr); waits are recorded, not slept.

    Its checkout turns the public check off, so the retry tests reach the push; the gate's own
    tests set se.toml themselves."""
    (main_checkout / "se.toml").write_text(IDENTITY + "public_check = false\n", encoding="utf-8")
    calls, waits, script = [], [], []

    def run_git_push(root, arguments):
        calls.append(arguments)
        code, stderr = script.pop(0)
        return subprocess.CompletedProcess(["git", "push", *arguments], code, "", stderr)

    monkeypatch.setattr(work_tickets, "run_git_push", run_git_push)
    monkeypatch.setattr(work_tickets, "wait", waits.append)
    return calls, waits, script


def test_push_retries_a_transient_refusal_and_pushes_once(main_checkout, fake_push, capsys):
    calls, waits, script = fake_push
    script.extend([(1, TRANSIENT), (0, "")])
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 0
    assert calls == [["-u", "origin", "topic"]] * 2
    assert waits == [60]
    output = capsys.readouterr().out
    assert "Push attempt 1/10" in output and "commit_refs_rules, transient" in output
    assert output.count("Pushed: git push -u origin topic") == 1


def test_push_does_not_retry_a_non_fast_forward(main_checkout, fake_push, capsys):
    calls, waits, script = fake_push
    script.append((1, NON_FAST_FORWARD))
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 1
    assert len(calls) == 1 and waits == []
    error = capsys.readouterr().err
    assert "non-fast-forward, attempt 1, not retried" in error
    assert "work_tickets.py sync" in error


def test_push_does_not_retry_a_permission_refusal(main_checkout, fake_push, capsys):
    calls, waits, script = fake_push
    script.append((128, "remote: Permission to owner/repo.git denied to alice.\n"
                        "fatal: unable to access: The requested URL returned error: 403"))
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 1
    assert len(calls) == 1 and waits == []
    assert "(permission, attempt 1, not retried" in capsys.readouterr().err


@pytest.mark.parametrize("stderr", [
    "error: RPC failed; HTTP 502 curl 22 The requested URL returned error: 502",
    "fatal: unable to access: Connection reset by peer",
])
def test_push_retries_http_5xx_and_connection_reset(main_checkout, fake_push, stderr):
    calls, waits, script = fake_push
    script.extend([(1, stderr), (0, "")])
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 0
    assert len(calls) == 2 and waits == [60]


def test_push_ends_ten_transient_refusals_with_the_remedy(
    main_checkout, fake_push, capsys
):
    calls, waits, script = fake_push
    script.extend([(1, TRANSIENT)] * 10)
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 1
    assert len(calls) == 10 and waits == [60] * 9
    error = capsys.readouterr().err
    assert "(commit_refs_rules, transient) on all 10 attempts, one every 60 s" in error
    assert "Remedy: check GitHub's status page" in error
    assert "then run the same command again" in error


@pytest.mark.parametrize("settings", ["public_check = true\n", ""])
def test_push_runs_the_public_check_gate_first(main_checkout, fake_push, monkeypatch, capsys,
                                               settings):
    """The gate is on unless se.toml turns it off: without the key, too (fail closed)."""
    calls, _, _ = fake_push
    (main_checkout / "se.toml").write_text(IDENTITY + settings, encoding="utf-8")
    gate = []

    def public_check(arguments, **_):
        gate.append(arguments)
        return subprocess.CompletedProcess(arguments, 1, "hit: file.txt (e-mail address)", "")

    monkeypatch.setattr(work_tickets.subprocess, "run", lambda arguments, **kwargs: (
        public_check(arguments) if str(work_tickets.PUBLIC_CHECK) in arguments
        else subprocess.CompletedProcess(arguments, 1, "", "")
    ))
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 1
    assert calls == []
    assert gate[0][-4:] == ["--rev", "topic", "--range", "topic --not --remotes"]
    error = capsys.readouterr().err
    assert "Public check failed" in error
    assert error.rstrip().endswith(
        "a project without a public check sets `public_check = false` in `[project]` of "
        f"{main_checkout / 'se.toml'}"
    )


def test_push_with_the_public_check_off_says_so_and_where_to_turn_it_on(
        main_checkout, fake_push, monkeypatch, capsys):
    calls, _, script = fake_push
    script.append((0, ""))
    (main_checkout / "se.toml").write_text(IDENTITY + "public_check = false\n", encoding="utf-8")
    checked = []
    real_run = subprocess.run
    monkeypatch.setattr(work_tickets.subprocess, "run", lambda arguments, **kwargs: (
        checked.append(arguments) if str(work_tickets.PUBLIC_CHECK) in arguments
        else real_run(arguments, **kwargs)
    ))
    assert work_tickets.main(["push", "topic", "--worktree", str(main_checkout)]) == 0
    assert checked == [] and calls == [["-u", "origin", "topic"]]
    off = [line for line in capsys.readouterr().out.splitlines() if "Public check off" in line]
    assert off == [
        f"Public check off: project.public_check = false in {main_checkout / 'se.toml'}; "
        "set it to true (or remove it) to check every push"
    ]


OUTSIDE_CONFIG = """[outside]
"git.example/owner/repo" = 10
"git.example/owner/other" = 0
"""


def outside_issue(number: int, body: str = "From the other side.", labels=(), comments=()) -> dict:
    return {"number": number, "title": f"issue {number}", "url": f"https://git.example/owner/repo/issues/{number}",
            "body": body, "labels": {"nodes": [{"name": name} for name in labels]},
            "comments": {"nodes": [{"body": text} for text in comments]}}


def outside_answer(repo: list[dict], other: list[dict], more: bool = False) -> str:
    def repository(nodes):
        return {"issues": {"pageInfo": {"hasNextPage": more}, "nodes": nodes}}
    return json.dumps({"data": {"r0": repository(repo), "r1": repository(other)}})


def test_fleet_issues_carry_the_marker_and_the_field_report_is_no_issue(worktree, gh, capsys):
    for name in ("work", "retro"):
        _, body = work_tickets.issue_template(name)
        assert work_tickets.FLEET_MARKER in body, name
    assert not (work_tickets.TEMPLATES / "field-report.md").exists()
    run(worktree, "intake", "--issue", "5")
    by_hand = worktree / "by-hand.md"
    by_hand.write_text(COMPLETE_REPORT, encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(by_hand)) == 0
    assert by_hand.read_text(encoding="utf-8") == reported_at(TIP)  # only the tip is filled in
    assert "marker" not in capsys.readouterr().out


def test_intake_outside_lists_each_unmarked_unhandled_issue_once_from_one_query(
        worktree, gh, monkeypatch, capsys):
    (worktree / "se.toml").write_text(OUTSIDE_CONFIG, encoding="utf-8")
    answers = [outside_answer(
        [outside_issue(14), outside_issue(13, f"{work_tickets.FLEET_MARKER}\nA work issue."),
         outside_issue(12, labels=["field-report"]),
         outside_issue(15, labels=["backlogged", "se-person"]),
         outside_issue(11, comments=["seen", f"{work_tickets.HANDLED_MARKER}\nRouted."]),
         outside_issue(16, f"Please.\n\n{work_tickets.HANDLED_MARKER}\n## Routing\n"),
         outside_issue(10)],
        [outside_issue(1)],
    )]
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: calls.append(arguments) or answers[-1])

    assert run(worktree, "intake", "--outside") == 0
    output = capsys.readouterr().out
    assert len(calls) == 1 and calls[0][:2] == ["api", "graphql"]
    assert calls[0][calls[0].index("--hostname") + 1] == "git.example"
    query = calls[0][-1]
    assert 'r0: repository(owner: "owner", name: "repo")' in query
    assert 'r1: repository(owner: "owner", name: "other")' in query
    lines = output.splitlines()
    assert lines == [
        "Outside issues (2), not yet handled:",
        "  git.example/owner/repo#14 issue 14 https://git.example/owner/repo/issues/14",
        "  git.example/owner/other#1 issue 1 https://git.example/owner/repo/issues/1",
    ]

    answers.append(outside_answer(
        [outside_issue(14, comments=[f"{work_tickets.HANDLED_MARKER}\nEscalated."])],
        [outside_issue(1, comments=[work_tickets.HANDLED_MARKER])],
    ))
    assert run(worktree, "intake", "--outside") == 0
    assert capsys.readouterr().out == "No outside issues to handle.\n"


def test_intake_outside_refuses_without_cut_offs_or_with_issues_beyond_one_page(
        worktree, gh, monkeypatch, capsys):
    assert run(worktree, "intake", "--outside") == 1
    error = capsys.readouterr().err
    assert "[outside]" in error and "se.toml" in error and "work-model" in error

    (worktree / "se.toml").write_text(OUTSIDE_CONFIG, encoding="utf-8")
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: outside_answer(
        [outside_issue(number) for number in range(111, 11, -1)], [], more=True))
    assert run(worktree, "intake", "--outside") == 1
    assert "git.example/owner/repo has more than 100 open issues above its cut-off" in (
        capsys.readouterr().err)


def test_backlog_files_with_both_labels_and_lists_by_title_and_body(worktree, gh, monkeypatch, capsys):
    idea = worktree / "idea.md"
    idea.write_text("A far-out idea.\n", encoding="utf-8")
    assert run(worktree, "backlog", "file", "--title", "Idea: voice input", "--body-file", str(idea)) == 0
    assert capsys.readouterr().out == "Filed backlog issue https://git.example/owner/repo/issues/8\n"
    before, listed_labels, label, person, create, after = gh.calls[-6:]
    assert before[:2] == after[:2] == ["issue", "list"]
    assert listed_labels[:2] == ["label", "list"] and label[:3] == ["label", "create", "backlogged"]
    assert person[:3] == ["label", "create", "se-person"]
    assert create[:4] == ["issue", "create", "--title", "Idea: voice input"]
    assert [create[i + 1] for i, a in enumerate(create) if a == "--label"] == ["backlogged", "se-person"]
    assert gh.bodies[-1] == f"{work_tickets.FLEET_MARKER}\nA far-out idea.\n"

    labelled = FakeGh()
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: (
        '[{"name": "backlogged"}, {"name": "se-person"}]' if arguments[:2] == ["label", "list"]
        else labelled(root, arguments)))
    assert run(worktree, "backlog", "file", "--title", "Idea: two", "--body-file", str(idea)) == 0
    assert [call[:2] for call in labelled.calls] == [
        ["issue", "list"], ["issue", "create"], ["issue", "list"]]
    capsys.readouterr()
    monkeypatch.setattr(work_tickets, "run_gh", gh)

    gh.open_reports = [{"number": 8, "title": "Idea: voice input", "url": "https://git.example/owner/repo/issues/8"}]
    assert run(worktree, "backlog", "list", "--search", "voice") == 0
    listed = gh.calls[-1]
    assert listed[:2] == ["issue", "list"] and listed[listed.index("--label") + 1] == "backlogged"
    assert listed[listed.index("--search") + 1] == "voice in:title,body"
    assert capsys.readouterr().out == (
        "Backlog issues (1):\n  #8 Idea: voice input https://git.example/owner/repo/issues/8\n")

    gh.open_reports = []
    assert run(worktree, "backlog", "list") == 0
    assert "--search" not in gh.calls[-1] and capsys.readouterr().out == "No backlog issues.\n"
    idea.write_text("", encoding="utf-8")
    assert run(worktree, "backlog", "file", "--title", "Empty", "--body-file", str(idea)) == 1


class LabelledGh:
    """GitHub's issues and labels, as far as filing, routing and the queue use them."""

    def __init__(self, issues: dict[int, dict]) -> None:
        self.issues = issues
        self.labels: set[str] = set()
        self.comments: dict[int, list[str]] = {}
        self.blocked_by: dict[int, list[int]] = {}

    def __call__(self, root: Path, arguments: list[str]) -> str:
        def values(flag: str) -> list[str]:
            return [arguments[i + 1] for i, argument in enumerate(arguments) if argument == flag]
        body = (Path(values("--body-file")[0]).read_text(encoding="utf-8")
                if "--body-file" in arguments else None)
        command = arguments[:2]
        if command == ["label", "list"]:
            return json.dumps([{"name": name} for name in sorted(self.labels)])
        if command == ["label", "create"]:
            self.labels.add(arguments[2])
            return ""
        if command == ["issue", "create"]:
            assert set(values("--label")) <= self.labels, "gh refuses a label the repository lacks"
            number = max(self.issues) + 1
            self.issues[number] = {"number": number, "title": values("--title")[0], "body": body,
                                   "url": f"https://git.example/owner/repo/issues/{number}",
                                   "labels": values("--label")}
            return self.issues[number]["url"] + "\n"
        if command == ["issue", "edit"]:
            issue = self.issues[int(arguments[2])]
            assert set(values("--add-label")) <= self.labels, "gh refuses a label the repository lacks"
            issue["labels"] = [label for label in issue["labels"] if label not in values("--remove-label")]
            issue["labels"] += [label for label in values("--add-label") if label not in issue["labels"]]
            issue["title"] = (values("--title") or [issue["title"]])[0]
            issue["body"] = body if body is not None else issue["body"]
            return ""
        if command == ["issue", "comment"]:
            self.comments.setdefault(int(arguments[2]), []).append(body)
            return ""
        if command == ["issue", "view"]:
            issue = self.issues[int(arguments[2])]
            return json.dumps({**issue, "labels": [{"name": name} for name in issue["labels"]],
                               "updatedAt": "2026-11-06T10:00:00Z", "comments": []})
        if command == ["issue", "list"]:
            wanted = set(values("--label"))
            return json.dumps([
                {**issue, "labels": [{"name": name} for name in issue["labels"]]}
                for issue in self.issues.values()
                if wanted <= set(issue["labels"]) and issue.get("state", "open") == "open"])
        if arguments[:3] == ["api", "-X", "PATCH"]:
            issue = self.issues[int(arguments[3].split("/")[4])]
            issue.update(state=values("-f")[0].split("=")[1], state_reason=values("-f")[1].split("=")[1])
            return ""
        if arguments[0] == "api":
            path = arguments[1].split("/")
            number = int(path[4])
            if path[5:] == ["dependencies", "blocked_by"]:
                self.blocked_by.setdefault(number, []).append(int(values("-F")[0].split("=")[1]))
                return ""
            if "--jq" in arguments:
                return f"{number}\n"
            return json.dumps({"issue_dependencies_summary": {"blocked_by": len(self.blocked_by.get(number, []))}})
        raise AssertionError(f"unexpected gh call {arguments}")


def test_filed_and_routed_issues_are_ready_and_nothing_else_is(worktree, monkeypatch, capsys):
    github = LabelledGh({
        1: {"number": 1, "title": "Something from the other side", "body": "Please fix it.",
            "url": "https://git.example/owner/repo/issues/1", "labels": []},
        2: {"number": 2, "title": "Not routed yet", "body": "Another one.",
            "url": "https://git.example/owner/repo/issues/2", "labels": []},
        3: {"number": 3, "title": "feature/idea-20261106", "body": "",
            "url": "https://git.example/owner/repo/issues/3",
            "labels": ["work", "ready", "repo:repo", "backlogged"]},
        4: {"number": 4, "title": "field-report: feature/x-20261106", "body": "",
            "url": "https://git.example/owner/repo/issues/4",
            "labels": ["work", "ready", "repo:repo", "field-report"]},
        5: {"number": 5, "title": "feature/running-20261106", "body": "",
            "url": "https://git.example/owner/repo/issues/5",
            "labels": ["work", "ready", "repo:repo", "in-progress"]},
    })
    monkeypatch.setattr(work_tickets, "run_gh", github)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "branch_exists", lambda root, branch: False)
    body = worktree / "work.md"
    body.write_text("## Goal\n\nA filed package.\n", encoding="utf-8")
    routing = worktree / "route.md"
    routing.write_text("## Package kind\n\nStandard, small.\n", encoding="utf-8")

    assert run(worktree, "file", "--title", "feature/filed-20261106", "--body-file", str(body)) == 0
    assert capsys.readouterr().out == "Filed work issue https://git.example/owner/repo/issues/6\n"
    assert github.issues[6]["labels"] == ["work", "ready", "repo:repo"]
    assert github.issues[6]["body"] == f"{work_tickets.FLEET_MARKER}\n## Goal\n\nA filed package.\n"
    assert run(worktree, "route", "1", "--title", "fix/routed-20261106", "--routing-file", str(routing)) == 0
    assert github.issues[1]["title"] == "fix/routed-20261106"
    assert github.issues[1]["labels"] == ["work", "ready", "repo:repo"]
    assert github.issues[1]["body"].startswith("Please fix it.\n\n" + work_tickets.HANDLED_MARKER)
    assert 1 not in github.comments
    assert {"work", "ready", "repo:repo"} <= github.labels
    capsys.readouterr()

    assert run(worktree, "ready") == 0
    assert capsys.readouterr().out == "#1 fix/routed-20261106\n#6 feature/filed-20261106\n"

    assert run(worktree, "file", "--title", "feature/later-20261106", "--body-file", str(body),
               "--blocked-by", "6") == 0
    assert github.issues[7]["labels"] == ["work", "repo:repo", "ready"]
    assert github.blocked_by[7] == [6] and "#6" in github.issues[7]["body"]
    capsys.readouterr()
    assert run(worktree, "ready") == 0
    assert "#7" not in capsys.readouterr().out
    assert run(worktree, "route", "2", "--title", " ", "--routing-file", str(routing)) == 1
    assert github.issues[2]["labels"] == [] and github.issues[2]["body"] == "Another one."


OUTSIDE_BODY = BODY.split("## Requirements")[0].rstrip() + "\n"
ROUTING = BODY[BODY.index("## Requirements"):].replace(
    "2. Issue tooling in `scripts/work_tickets.py`.\n",
    "2. Issue tooling in `scripts/work_tickets.py`.\n3. A routed requirement.\n")


def routed_gh(monkeypatch) -> LabelledGh:
    github = LabelledGh({1: {"number": 1, "title": "Proposal: Make the example work!",
                             "body": OUTSIDE_BODY, "url": "https://git.example/owner/repo/issues/1",
                             "labels": []}})
    monkeypatch.setattr(work_tickets, "run_gh", github)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261109")
    return github


def test_route_retitles_labels_and_appends_the_routing_section_in_one_edit(
        worktree, monkeypatch, capsys):
    github = routed_gh(monkeypatch)
    routing = worktree / "route.md"
    routing.write_text(ROUTING, encoding="utf-8")

    assert run(worktree, "route", "1", "--routing-file", str(routing)) == 0
    assert capsys.readouterr().out == "Routed issue #1 as feat/make-the-example-work-20261109\n"
    issue = github.issues[1]
    assert issue["title"] == "feat/make-the-example-work-20261109"
    assert issue["labels"] == ["work", "ready", "repo:repo"] and 1 not in github.comments
    assert issue["body"].startswith(OUTSIDE_BODY + "\n" + work_tickets.HANDLED_MARKER + "\n## Routing\n\n"
                                    "Routed from: Proposal: Make the example work!\n\n### Requirements\n")
    assert "### Acceptance" in issue["body"] and "## not a heading inside a fence" in issue["body"]
    assert work_tickets.requirement_items(issue["body"])[3] == ("Routing", "A routed requirement.")

    assert run(worktree, "route", "1", "--routing-file", str(routing)) == 1
    assert "#1 is routed already" in capsys.readouterr().err
    assert run(worktree, "route", "1", "--type", "nope", "--routing-file", str(routing)) == 1


def dedupe_gh(monkeypatch) -> LabelledGh:
    github = LabelledGh({
        1: {"number": 1, "title": "Proposal: Make the example work!", "body": OUTSIDE_BODY,
            "url": "https://git.example/owner/repo/issues/1", "labels": []},
        2: {"number": 2, "title": "feature/twin-20261101", "body": "The first one.",
            "url": "https://git.example/owner/repo/issues/2", "labels": ["work", "ready", "repo:repo"]},
        3: {"number": 3, "title": "feature/closed-20261101", "body": "Done long ago.",
            "url": "https://git.example/owner/repo/issues/3", "labels": [], "state": "closed"},
    })
    monkeypatch.setattr(work_tickets, "run_gh", github)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261109")
    return github


def test_sameness_is_the_title_without_its_date_and_the_routed_from_line():
    key = work_tickets.purpose_key
    assert key("feature/twin-20261101", "") == key(" feature/twin-20261112 ", "any body")
    assert key("feature/twin-20261101", "") != key("feature/twin-2026110", "")
    assert key("Idea: voice input", "") == ("Idea: voice input", None)
    routed = "Body.\n\nRouted from: Proposal: one\n\nMore."
    assert key("feat/one-20261109", routed) == ("feat/one", "Proposal: one")
    assert key("feat/one-20261109", routed) != key("feat/one-20261110", routed.replace("one\n", "two\n"))
    assert key("feat/one-20261109", routed) != key("feat/one-20261109", "")
    issues = [{"number": 9, "title": "feat/one-20261101", "body": routed},
              {"number": 4, "title": "feat/one-20261102", "body": routed},
              {"number": 5, "title": "feat/one-20261102", "body": ""}]
    assert work_tickets.twins(issues, key("feat/one-20261109", routed)) == [4, 9]
    assert work_tickets.twins(issues, key("feat/one-20261109", routed), exclude=4) == [9]


@pytest.mark.parametrize("command", [
    ["file", "--title", "feature/twin-20261109"],
    ["backlog", "file", "--title", "feature/twin-20261109"],
], ids=["file", "backlog-file"])
def test_filing_a_twin_comments_on_the_open_issue_and_creates_nothing(
        worktree, monkeypatch, capsys, command):
    github = dedupe_gh(monkeypatch)
    body = worktree / "body.md"
    body.write_text("## Goal\n\nThe same purpose again.\n", encoding="utf-8")

    assert run(worktree, *command, "--body-file", str(body)) == 0
    assert capsys.readouterr().out == (
        "Not filed: #2 https://git.example/owner/repo/issues/2 has the same purpose; "
        "commented on it instead\n")
    assert sorted(github.issues) == [1, 2, 3]
    comment, = github.comments[2]
    assert f"`work_tickets.py {' '.join(command[:-2])}` would have filed" in comment
    assert "**feature/twin-20261109**\n\n> ## Goal\n>\n> The same purpose again.\n" in comment
    assert work_tickets.FLEET_MARKER not in comment


def test_filing_without_a_twin_creates_and_a_closed_issue_is_no_twin(worktree, monkeypatch, capsys):
    github = dedupe_gh(monkeypatch)
    body = worktree / "body.md"
    body.write_text("A new purpose.\n", encoding="utf-8")

    assert run(worktree, "file", "--title", "feature/closed-20261109", "--body-file", str(body)) == 0
    assert capsys.readouterr().out == "Filed work issue https://git.example/owner/repo/issues/4\n"
    assert github.issues[4]["title"] == "feature/closed-20261109"
    assert github.issues[4].get("state", "open") == "open" and not github.comments


def test_a_raced_twin_closes_the_later_issue_as_its_duplicate(worktree, monkeypatch, capsys):
    github = dedupe_gh(monkeypatch)
    create = github.__call__

    def racing(root: Path, arguments: list[str]) -> str:
        if arguments[:2] == ["issue", "create"] and 4 not in github.issues:
            # Another creator files the same purpose between our read and our create.
            github.issues[4] = {"number": 4, "title": "feature/raced-20261108", "body": "Theirs.",
                                "url": "https://git.example/owner/repo/issues/4", "labels": []}
        return create(root, arguments)

    monkeypatch.setattr(work_tickets, "run_gh", racing)
    body = worktree / "body.md"
    body.write_text("Ours.\n", encoding="utf-8")

    assert run(worktree, "file", "--title", "feature/raced-20261109", "--body-file", str(body),
               "--blocked-by", "2") == 0
    assert capsys.readouterr().out == (
        "Filed work issue https://git.example/owner/repo/issues/5, closed as a duplicate of #4\n")
    assert github.issues[5]["state"] == "closed" and github.issues[5]["state_reason"] == "duplicate"
    assert github.comments[5] == ["Duplicate of #4: filed in a race with it.\n"]
    assert github.issues[4].get("state", "open") == "open" and 4 not in github.comments
    assert 5 not in github.blocked_by and "ready" not in github.issues[5]["labels"]


def test_routing_dedupes_by_title_and_routed_from_line(worktree, monkeypatch, capsys):
    github = dedupe_gh(monkeypatch)
    routing = worktree / "route.md"
    routing.write_text(ROUTING, encoding="utf-8")
    github.issues[7] = {"number": 7, "title": "Proposal: Make the example work!", "body": OUTSIDE_BODY,
                        "url": "https://git.example/owner/repo/issues/7", "labels": []}

    assert run(worktree, "route", "7", "--routing-file", str(routing)) == 0
    assert capsys.readouterr().out == "Routed issue #7 as feat/make-the-example-work-20261109\n"

    # The same outside proposal, filed twice, routed again: its twin #7 gets the comment.
    assert run(worktree, "route", "1", "--routing-file", str(routing)) == 0
    assert capsys.readouterr().out == (
        "Not filed: #7 https://git.example/owner/repo/issues/7 has the same purpose; "
        "commented on it instead\n")
    comment, = github.comments[7]
    assert "would have routed #1 as a twin" in comment and "> Routed from: Proposal: Make" in comment
    assert github.issues[1]["title"] == "Proposal: Make the example work!"
    assert github.issues[1]["state"] == "closed" and github.issues[1]["state_reason"] == "duplicate"
    assert github.comments[1] == ["Duplicate of #7: routed as a twin of it.\n"]

    # The same branch name from another proposal is another purpose.
    github.issues[8] = {"number": 8, "title": "Proposal: make the example work", "body": "Other.",
                        "url": "https://git.example/owner/repo/issues/8", "labels": []}
    assert run(worktree, "route", "8", "--routing-file", str(routing)) == 0
    assert github.issues[8]["title"] == "feat/make-the-example-work-20261109"
    assert github.issues[8].get("state", "open") == "open"


def test_the_cloud_hand_off_prints_the_search_and_the_condition(worktree, monkeypatch, capsys):
    def no_gh(root: Path, arguments: list[str]) -> str:
        raise AssertionError(f"no gh call in the hand-off: {arguments}")

    monkeypatch.setattr(work_tickets, "run_gh", no_gh)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261109")
    body = worktree / "body.md"
    body.write_text("Idea body.\n", encoding="utf-8")

    assert run(worktree, "backlog", "file", "--title", "Idea: voice input", "--body-file", str(body)) == 0
    out = capsys.readouterr().out
    plan = out.split("\n")
    assert plan[0] == "GitHub plan: backlog file Idea: voice input"
    assert plan[-2] == "Run the GitHub plan above to file the backlog issue once"
    steps = [line.split(" ", 2)[1] for line in plan if re.match(r"\d+\. ", line)]
    assert steps == ["list_issues", "add_issue_comment", "issue_write", "list_issues",
                     "add_issue_comment", "issue_write"]
    assert '"state": "OPEN"' in out
    assert ("a twin is one whose title without a trailing -yyyymmdd is `Idea: voice input` and whose "
            "body has no `Routed from:` line") in out
    assert "Only where step 1 found a twin. Then stop: nothing is filed." in out
    assert "Only where step 1 found no twin." in out
    assert '"issue_number": "<twin from step 1>"' in out
    assert "lower number than #<number from step 3>" in out
    assert '"state_reason": "duplicate"' in out and '"duplicate_of": "<lower from step 4>"' in out

    assert run(worktree, "file", "--title", "feature/x-20261109", "--body-file", str(body),
               "--blocked-by", "2") == 1
    assert "gh, which is not signed in" in capsys.readouterr().err

    routing = worktree / "route.md"
    routing.write_text(ROUTING, encoding="utf-8")
    assert run(worktree, "route", "1", "--routing-file", str(routing)) == 1
    assert "--issue-title <title> --issue-body <file" in capsys.readouterr().err
    outside = worktree / "outside.md"
    outside.write_text(OUTSIDE_BODY, encoding="utf-8")
    assert run(worktree, "route", "1", "--routing-file", str(routing), "--issue-title",
               "Proposal: one", "--issue-body", str(outside)) == 0
    out = capsys.readouterr().out
    assert [line.split(" ", 2)[1] for line in out.split("\n") if re.match(r"\d+\. ", line)] == [
        "list_issues", "add_issue_comment", "add_issue_comment", "issue_write", "issue_write",
        "list_issues", "add_issue_comment", "issue_write"]
    assert "the line `Routed from: Proposal: one`" in out and "other than #1" in out
    assert "lower number than #1," in out and "Only where step 4 found a lower twin" not in out
    assert out.endswith("Run the GitHub plan above to route #1 as feat/one-20261109 once\n")


@pytest.mark.parametrize("rows", [EVIDENCE_ROWS, EVIDENCE_ROWS.replace(
    "| Acceptance 1", "| Requirement 3 | complete | `abc1234` | `test`: passed |\n| Acceptance 1")],
    ids=["lacks-row-3", "has-row-3"])
def test_field_report_check_enforces_the_routed_requirements_and_acceptance(
        worktree, monkeypatch, capsys, rows):
    github = routed_gh(monkeypatch)
    routing = worktree / "route.md"
    routing.write_text(ROUTING, encoding="utf-8")
    assert run(worktree, "route", "1", "--routing-file", str(routing)) == 0
    issue, report = worktree / "issue.md", worktree / "report.md"
    issue.write_text(github.issues[1]["body"], encoding="utf-8")
    report.write_text(COMPLETE_REPORT.replace(EVIDENCE_ROWS, rows), encoding="utf-8")
    capsys.readouterr()

    code = run(worktree, "field-report", "--check", str(report), "--issue-body", str(issue))
    error = capsys.readouterr().err
    if rows == EVIDENCE_ROWS:
        assert code == 1 and 'missing evidence for: Requirement 3 (under "Routing")' in error
    else:
        assert code == 0, error
    report.write_text(COMPLETE_REPORT.replace(EVIDENCE_ROWS, rows).replace(
        "| Acceptance 2 | complete | `abc1234` | `test`: passed |\n", ""), encoding="utf-8")
    assert run(worktree, "field-report", "--check", str(report), "--issue-body", str(issue)) == 1
    assert "Acceptance 2" in capsys.readouterr().err


POST_MERGE_BODY = BODY.replace("- [ ] Tooling has tests.", "- [ ] CI is green on main after the merge.")


@pytest.mark.parametrize(
    ("body", "keyword"), [(BODY, "Fixes"), (POST_MERGE_BODY, "Refs")], ids=["pre-merge", "post-merge"])
def test_deliver_names_the_issue_with_a_closing_keyword_only_for_pre_merge_acceptance(
        worktree, gh, monkeypatch, body, keyword):
    gh.issue["body"] = body
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver") == 0
    pr_body = gh.bodies[[call[:2] for call in gh.calls if "--body-file" in call].index(["pr", "create"])]
    assert pr_body.startswith(f"{keyword} {URL}\n")
    assert ("Fixes" in pr_body) is (keyword == "Fixes")


@pytest.mark.parametrize(
    ("body", "keyword"), [(BODY, "Fixes"), (POST_MERGE_BODY, "Refs")], ids=["pre-merge", "post-merge"])
def test_pr_body_prints_the_form_deliver_writes(tmp_path, capsys, body, keyword):
    issue_body = tmp_path / "issue.md"
    issue_body.write_text(body, encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text(COMPLETE_REPORT.replace("## Spec gaps", "<!-- a template comment -->\n## Spec gaps"),
                      encoding="utf-8")
    assert work_tickets.main(["pr-body", "--issue-body", str(issue_body), "--issue-url", URL,
                              "--field-report", str(report)]) == 0
    assert capsys.readouterr().out == f"{keyword} {URL}\n\n{COMPLETE_REPORT}"

    report.write_text("no markers\n", encoding="utf-8")
    assert work_tickets.main(["pr-body", "--issue-body", str(issue_body), "--issue-url", URL,
                              "--field-report", str(report)]) == 1
    assert "holds no field report" in capsys.readouterr().err


def test_integrate_leaves_an_issue_with_post_merge_acceptance_open_and_reports_github_states(
        main_checkout, monkeypatch, capsys):
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    calls = integration_fakes(monkeypatch, head)
    report = {"body": reported_at(head)}
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: (
        {"body": POST_MERGE_BODY} if number == 5 else report))
    closed: set[str] = set()
    bodies: list[str] = []

    def gh_call(root, args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefName": "feature/worker", "headRefOid": head, "body": report["body"],
                           "url": "https://git.example/owner/repo/pull/7"})
        if args[:2] == ["issue", "close"]:
            closed.add(args[2])
        if args[:2] == ["issue", "view"]:
            return "CLOSED\n" if args[2] in closed else "OPEN\n"
        return ""
    monkeypatch.setattr(work_tickets, "run_gh", gh_call)
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, args, body: calls.append(args) or bodies.append(body) or "")

    work_tickets.integrate(main_checkout, 7, None, None)
    assert [call[2] for call in calls if call[:2] == ["issue", "close"]] == []
    assert len(bodies) == 1 and "from https://git.example/owner/repo/pull/7, landed through https://git.example/owner/repo/pull/20 (check: https://git.example/owner/repo/runs/1). Release: none." in bodies[0]
    assert "Stays open until this acceptance is seen after the merge: " \
           "- [ ] CI is green on main after the merge." in bodies[0]
    output = capsys.readouterr().out
    assert "Issue #5: OPEN on GitHub after the merge" in output
    assert "Close #5 once its post-merge acceptance is seen" in output


@pytest.mark.parametrize(("old", "new", "refusal"), [
    ("**Release kind:** minor — adds an example command\n", "",
     'missing "**Release kind:**"'),
    ("**Release kind:** minor", "**Release kind:** huge",
     "Release kind 'huge' must be one of patch, minor, major"),
    ("## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone",
     "## Removed behaviour, deleted or weakened tests, and authored prose\n\n"
     "- **Breaking:** removed the --all option",
     "Release kind is minor, but section \"## Removed behaviour, deleted or weakened tests, and "
     "authored prose\" lists a breaking change, which is major: - **Breaking:** removed the --all "
     "option"),
], ids=["missing", "unknown", "breaking-as-minor"])
def test_field_report_check_refuses_a_release_kind_it_cannot_release(
        tmp_path, capsys, old, new, refusal):
    report, issue = tmp_path / "report.md", tmp_path / "issue.md"
    assert old in COMPLETE_REPORT
    report.write_text(COMPLETE_REPORT.replace(old, new), encoding="utf-8")
    issue.write_text(BODY, encoding="utf-8")
    assert work_tickets.main(["field-report", "--check", str(report), "--issue-body", str(issue)]) == 1
    assert refusal in capsys.readouterr().err


def test_integrate_closes_the_work_issue_with_a_comment_linking_the_pull_request_and_release(
        main_checkout, monkeypatch):
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "worker")
    git_ok("-C", str(worker), "push", "-q", "origin", "feature/worker")
    head = subprocess.run(["git", "-C", str(worker), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    calls = integration_fakes(monkeypatch, head)
    bodies: list[str] = []
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, args, body: calls.append(args) or bodies.append(body) or "")
    monkeypatch.setattr(work_tickets, "release", lambda root, branch, upstream: "v1.3.0")

    commit = work_tickets.integrate(main_checkout, 7, None, None)
    assert bodies == [f"Integrated in {commit} from https://git.example/owner/repo/pull/7"
                      ", landed through https://git.example/owner/repo/pull/20 (check: https://git.example/owner/repo/runs/1). "
                      "Release: https://git.example/owner/repo/releases/tag/v1.3.0. Suite: 1 passed.\n"]
    assert [call[:3] for call in calls if call[:2] == ["issue", "close"]] == [["issue", "close", "5"]]


class FlowGh:
    """GitHub for a whole worker-to-integrator run: one work issue and the pull requests made."""

    def __init__(self) -> None:
        self.issue = {"number": 5, "title": BRANCH, "body": BODY, "url": URL, "state": "OPEN",
                      "updatedAt": "2026-11-04T10:00:00Z", "comments": [], "labels": []}
        self.pulls: list[dict] = []
        self.calls: list[list[str]] = []

    def body(self, arguments: list[str]) -> str:
        return Path(arguments[arguments.index("--body-file") + 1]).read_text(encoding="utf-8")

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)
        command = arguments[:2]
        if command == ["issue", "view"] and "--jq" in arguments:
            return self.issue["state"] + "\n"
        if command == ["issue", "view"]:
            return json.dumps(self.issue)
        if command == ["issue", "close"]:
            self.issue["state"] = "CLOSED"
        if command == ["issue", "comment"]:
            self.issue["comments"].append({"id": "C9", "body": self.body(arguments)})
        if command == ["pr", "list"]:
            return json.dumps([pull for pull in self.pulls if pull["state"] == "open"])
        if command == ["pr", "create"]:
            self.pulls.append({"number": 7, "title": arguments[arguments.index("--title") + 1],
                               "url": "https://git.example/owner/repo/pull/7", "state": "open",
                               "headRefName": arguments[arguments.index("--head") + 1],
                               "body": self.body(arguments)})
            return self.pulls[-1]["url"] + "\n"
        if command == ["pr", "edit"]:
            self.pulls[0]["body"] = self.body(arguments)
        if command == ["pr", "view"]:
            return json.dumps(self.pulls[0])
        if command == ["issue", "list"]:
            return "[]"
        return ""


def test_dry_run_of_the_worker_to_integrator_flow_files_no_field_report_issue(
        main_checkout, monkeypatch, capsys):
    """Acceptance: draft, check, deliver, queue, release kind and integrate on fakes, from one work
    issue to its closing comment, with no field-report issue anywhere."""
    gh = FlowGh()
    monkeypatch.setattr(work_tickets, "run_gh", gh)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", BRANCH, str(worker))
    (worker / "tool.txt").write_text("tool\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "tool.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "Install every tool")

    # The worker: intake, draft, fill in, check, deliver.
    assert run(worker, "intake", "--issue", "5") == 0
    report = worker / ".se" / "work" / "field-report.md"
    assert run(worker, "field-report", "--draft", str(report)) == 0
    report.write_text(fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
        "**Result:** complete | partial", "**Result:** complete"), encoding="utf-8")
    assert run(worker, "field-report", "--check", str(report)) == 0, capsys.readouterr().err
    monkeypatch.setattr(work_tickets, "push",
                        lambda root, branch: git_ok("-C", str(root), "push", "-q", "origin", branch))
    assert run(worker, "deliver") == 0
    assert f"field report in PR #7 for {BRANCH}" in capsys.readouterr().out
    description = gh.pulls[0]["body"]
    assert description.startswith(f"Fixes {URL}\n\n{BEGIN}\n") and description.endswith(f"{END}\n")

    # The integrator: the queue, the release kind from the description, the merge.
    git_ok("-C", str(main_checkout), "fetch", "-q", "origin")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo, all_repos=False: [])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos=False: None)
    delivered, _, _, _ = work_tickets.queue(main_checkout, "git.example/owner/repo")
    assert [pull["number"] for pull in delivered] == [7]
    saved = main_checkout.parent / "description.md"
    saved.write_text(description, encoding="utf-8")
    issue = main_checkout.parent / "issue.md"
    issue.write_text(BODY, encoding="utf-8")
    assert work_tickets.main(["field-report", "--check", str(saved), "--issue-body", str(issue)]) == 0
    assert work_tickets.main(["release-trailer", BRANCH, "--issue-body", str(issue),
                              "--pr-description", str(saved), "--worktree", str(main_checkout)]) == 0
    assert capsys.readouterr().out.strip().endswith("Release-kind: minor")
    gh.pulls[0]["headRefOid"] = subprocess.run(
        ["git", "-C", str(worker), "rev-parse", "HEAD"], capture_output=True, text=True,
        check=True).stdout.strip()
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: suite_passed(root, "1 passed"))
    monkeypatch.setattr(work_tickets, "release", lambda root, branch, upstream: "v1.1.0")
    commit = work_tickets.integrate(main_checkout, 7, None, None)

    assert gh.issue["state"] == "CLOSED"
    assert gh.issue["comments"][-1]["body"].startswith(
        f"Integrated in {commit} from https://git.example/owner/repo/pull/7, landed through https://git.example/owner/repo/pull/20 (check: https://git.example/owner/repo/runs/1). "
        "Release: https://git.example/owner/repo/releases/tag/v1.1.0.")
    assert "Release-kind: minor" in subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%B"], capture_output=True,
        text=True, check=True).stdout
    assert not any(call[:2] == ["issue", "create"] or "field-report" in call for call in gh.calls)
