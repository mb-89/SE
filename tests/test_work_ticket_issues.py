"""work_tickets.py reads work issues and writes field reports through gh (mocked here)."""
import importlib.util
import io
import json
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


COMPLETE_REPORT = """**Work issue:** #5  **Pull request:** #7  **Branch:** `feature/example-20261104`  **Result:** complete
**Tested against `main`:** `abc1234`

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
"""

def fill_evidence_rows(report: str) -> str:
    return report.replace("|---|---|---|---|", "|---|---|---|---|\n" + EVIDENCE_ROWS)


def draft_complete_field_report(worktree: Path, pr: int | None = None) -> Path:
    report = worktree / ".se" / "work" / "field-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    work_tickets.draft_field_report(worktree, report, pr)
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


@pytest.fixture(autouse=True)
def local_config(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "home" / ".se" / "local.toml"
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: path)
    return path


@pytest.fixture
def gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "current_branch", lambda root: BRANCH)
    monkeypatch.setattr(work_tickets, "tested_main", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    return fake


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    root.mkdir()
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


def test_field_report_fills_the_template_and_creates_a_labelled_issue(worktree, gh, capsys):
    gh.issue["labels"] = [{"name": "work"}, {"name": "repo:example"}, {"name": "discovery"}]
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    draft = report.read_text(encoding="utf-8")
    assert "**Work issue:** #5  **Pull request:** #7  **Branch:** `feature/example-20261104`" in draft
    assert "**Tested against `main`:** `abc1234`" in draft
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

    assert run(worktree, "field-report", "--file", str(report)) == 0
    create = gh.calls[-1]
    assert create[:5] == ["issue", "create", "--title", f"field-report: {BRANCH}", "--label"]
    assert create[5] == "field-report" and "--body-file" in create
    assert "repo:example" in create
    assert create[create.index("--repo") + 1] == "git.example/owner/repo"
    body = gh.bodies[-1]
    assert "<!--" not in body and "\n\n\n" not in body and body.startswith("**Work issue:** #5")
    assert "Field report created: https://git.example/owner/repo/issues/8" in capsys.readouterr().out

    gh.open_reports = [{"number": 8, "title": f"field-report: {BRANCH}",
                        "url": "https://git.example/owner/repo/issues/8"}]
    assert run(worktree, "field-report", "--file", str(report)) == 0
    assert gh.calls[-1][:3] == ["issue", "edit", "8"] and "--body-file" in gh.calls[-1]
    assert "Field report updated" in capsys.readouterr().out


def test_field_report_draft_names_the_configured_integration_branch_and_its_commit(
        worktree, gh, monkeypatch):
    monkeypatch.setattr(work_tickets, "tested_main", TESTED_MAIN)
    git_ok("init", "-q", "-b", "se", str(worktree))
    git_ok("-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "commit", "-q", "--allow-empty", "-m", "base")
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    git_ok("-C", str(worktree), "switch", "-q", "-c", BRANCH)
    (worktree / "se.toml").write_text('[project]\nintegration_branch = "se"\n', encoding="utf-8")
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"

    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    assert f"**Tested against `se`:** `{commit}`" in report.read_text(encoding="utf-8")


def test_field_report_draft_uses_the_se_template_when_project_has_none(worktree, gh):
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    report = worktree / "report.md"

    assert not (worktree / ".github" / "ISSUE_TEMPLATE" / "field-report.md").exists()
    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    draft = report.read_text(encoding="utf-8")
    assert "**Pull request:** none" in draft and "## Delivered" in draft


def test_field_report_refuses_unfilled_or_unlinked_reports(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text("**Work issue:** #<n>  **Branch:** `<branch>` "
                      "`<integration branch>` `<commit>`\n", encoding="utf-8")
    assert run(worktree, "field-report", "--file", str(report)) == 1
    error = capsys.readouterr().err
    assert "unfilled placeholder #<n>" in error and "unfilled placeholder <branch>" in error
    assert "unfilled placeholder <commit>" in error
    assert "unfilled placeholder <integration branch>" in error
    assert "does not link work issue #5" in error and "does not link pull request #7" in error
    assert not any(call[:2] == ["issue", "create"] for call in gh.calls)

    monkeypatch.setattr(work_tickets, "current_branch", lambda root: "main")
    assert run(worktree, "field-report", "--file", str(report)) == 1
    assert "does not match the work issue title" in capsys.readouterr().err


def test_field_report_refuses_a_placeholder_added_to_its_template(
    worktree, gh, monkeypatch, tmp_path, capsys
):
    templates = tmp_path / "templates"
    shutil.copytree(work_tickets.TEMPLATES, templates)
    template = templates / "field-report.md"
    text = template.read_text(encoding="utf-8")
    template.write_text(text.replace("**Result:**", "**Reviewed on:** <date>  **Result:**", 1),
                        encoding="utf-8")
    monkeypatch.setattr(work_tickets, "TEMPLATES", templates)
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text("**Work issue:** #5  **Pull request:** #7  **Reviewed on:** <date>  "
                      "**Result:** complete\n\n## Delivered\n\n"
                      "| Work issue item | Result | Commits | Evidence |\n|---|---|---|---|\n"
                      + EVIDENCE_ROWS + "\n", encoding="utf-8")
    assert run(worktree, "field-report", "--file", str(report)) == 1
    assert "unfilled placeholder <date>" in capsys.readouterr().err


def test_field_report_may_mention_placeholders_below_its_header(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text(COMPLETE_REPORT.replace(
        "## Spec gaps\n\nNone.", "## Spec gaps\n\nThe draft fills `#<n>`, `<branch>` and `<commit>`."
    ), encoding="utf-8")
    assert run(worktree, "field-report", "--file", str(report)) == 0, capsys.readouterr().err
    assert gh.calls[-1][:2] == ["issue", "create"]


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

    assert run(worktree, "field-report", "--file", str(report)) == (0 if accepted else 1)
    if accepted:
        assert any(call[:2] == ["issue", "create"] for call in gh.calls)
    else:
        assert "header (above the first section): Result must be exactly complete or partial" in (
            capsys.readouterr().err)
        assert not any(call[:2] == ["issue", "create"] for call in gh.calls)


def test_field_report_refuses_missing_requirement_evidence(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    report.write_text(fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
        "| Requirement 2 | complete | `abc1234` | `test`: passed |\n", ""
    ), encoding="utf-8")

    assert run(worktree, "field-report", "--file", str(report)) == 1
    assert "Requirement 2" in capsys.readouterr().err


def test_field_report_refuses_empty_evidence_cell(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    report.write_text(fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
        "| Acceptance 2 | complete | `abc1234` | `test`: passed |",
        "| Acceptance 2 | complete | `abc1234` | |",
    ), encoding="utf-8")

    assert run(worktree, "field-report", "--file", str(report)) == 1
    assert "Acceptance 2" in capsys.readouterr().err


def test_field_report_accepts_not_delivered_requirement(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    assert run(worktree, "field-report", "--draft", "--file", str(report)) == 0
    report.write_text(
        fill_evidence_rows(report.read_text(encoding="utf-8")).replace(
            "**Result:** complete | partial", "**Result:** partial"
        ).replace(
            "| Requirement 2 | complete | `abc1234` | `test`: passed |\n", ""
        ).replace("## Not delivered\n\n", "## Not delivered\n\nRequirement 2 was narrowed.\n"),
        encoding="utf-8",
    )

    assert run(worktree, "field-report", "--file", str(report)) == 0, capsys.readouterr().err



@pytest.mark.parametrize(("change", "message"), [
    (lambda report: report, None),
    (lambda report: report.replace("  **Result:** complete", ""),
     'header (above the first section): missing "**Result:**"; the template\'s line: '
     "**Work issue:** #<n>  **Pull request:** #<n>  **Branch:** `<branch>`  "
     "**Result:** complete | partial"),
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
    assert gh.calls == []
    if message is None:
        assert code == 0, captured.err
        assert "Field report report.md follows the template" in captured.out
    else:
        assert code == 1
        assert "Field report report.md does not follow the template" in captured.err
        assert "the se checkout's .github/ISSUE_TEMPLATE/field-report.md:" in captured.err
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

    assert work_tickets.main(["field-report", "--file", str(report)]) == 1
    assert "field-report --file needs --worktree <worktree>" in capsys.readouterr().err

def test_validate_field_report_requires_template_sections_and_references(worktree, gh, monkeypatch):
    report = work_tickets.fetch_issue(worktree, 8, "git.example/owner/repo")
    report["body"] = "**Work issue:** #5  **Pull request:** #7\n\n## Delivered\nComplete."
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)

    with pytest.raises(work_tickets.QueueError, match='missing section "## Review responses"'):
        work_tickets.validate_field_report(worktree, 8, "git.example/owner/repo")

    report["body"] = COMPLETE_REPORT
    validated, work, pull = work_tickets.validate_field_report(
        worktree, 8, "git.example/owner/repo"
    )
    assert validated is report and (work, pull) == (5, 7)


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


def test_sync_fetches_and_merges_main_or_reports_conflicts(worktree, monkeypatch, capsys):
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
    assert any(call[:2] == ["issue", "create"] for call in gh.calls)
    assert "Notify ahp-session:/integrator: field report https://git.example/owner/repo/issues/8" in (
        capsys.readouterr().out
    )

    assert run(worktree, "deliver", "--integrator-session", "ahp-session:/other") == 0
    assert sum(call[:2] == ["pr", "create"] for call in gh.calls) == 1
    assert any(call[:2] == ["pr", "edit"] for call in gh.calls)
    assert any(call[:2] == ["issue", "edit"] for call in gh.calls)
    assert "Notify ahp-session:/other:" in capsys.readouterr().out


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


def test_deliver_updates_a_pre_pull_request_draft(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    report = draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver") == 0
    assert "**Pull request:** #7" in report.read_text(encoding="utf-8")
    assert "Notify <integrator session>: field report" in capsys.readouterr().out


def test_deliver_uses_origin_for_the_pull_request_and_tracker_for_the_report(
        worktree, gh, monkeypatch):
    run(worktree, "intake", "--issue", "5")
    gh.pull_request = None
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "source.example/owner/source")
    monkeypatch.setattr(
        work_tickets.subprocess, "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""),
    )

    assert run(worktree, "deliver", "--tracker", "tracker.example/owner/tracker") == 0
    pr_create = next(call for call in gh.calls if call[:2] == ["pr", "create"])
    report_create = next(call for call in gh.calls if call[:2] == ["issue", "create"])
    assert pr_create[pr_create.index("--repo") + 1] == "source.example/owner/source"
    assert report_create[report_create.index("--repo") + 1] == "tracker.example/owner/tracker"


def test_deliver_without_origin_files_report_on_the_given_tracker(
        worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    draft_complete_field_report(worktree)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")

    assert run(worktree, "deliver", "--tracker", "tracker.example/owner/tracker") == 0
    report = (worktree / ".se" / "work" / "field-report.md").read_text(encoding="utf-8")
    assert "**Pull request:** none" in report
    assert not any(call[0] == "pr" for call in gh.calls)
    assert any(
        call[:2] == ["issue", "create"]
        and call[call.index("--repo") + 1] == "tracker.example/owner/tracker"
        for call in gh.calls
    )
    assert "Notify <integrator session>: field report" in capsys.readouterr().out


def test_deliver_refuses_report_without_evidence(worktree, gh, monkeypatch, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / ".se" / "work" / "field-report.md"
    work_tickets.draft_field_report(worktree, report, 7)
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
    assert not any(call[:2] == ["issue", "create"] for call in gh.calls)


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
    assert "header Result must be exactly complete or partial" in capsys.readouterr().err
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

    for text in (documented_order, work_tickets.REPO_HELP):
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
    ]
    active = [{"number": 5, "title": "active", "body": "## File ownership\n\nshared.py\n"}]
    details = {1: 0, 2: 1, 3: 0, 4: 0}
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


def test_queue_lists_open_reports_escalations_and_startable_work(worktree, monkeypatch):
    reports = [{"number": 8, "title": "field-report: feature/one", "url": "https://example/8"}]
    escalations = [{"number": 9, "title": "blocked release", "url": "https://example/9"}]
    ready = [{"number": 1, "title": "feature/one"}]
    monkeypatch.setattr(
        work_tickets,
        "run_gh",
        lambda root, args: json.dumps(escalations if "escalated" in args else reports),
    )
    synced: list[Path] = []
    monkeypatch.setattr(work_tickets, "sync", lambda root: synced.append(root) or "abc1234")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo, all_repos: ready)
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos: 2)
    assert work_tickets.queue(worktree, "git.example/owner/repo") == (
        reports, escalations, ready, 2
    )
    assert synced == [worktree]


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
    assert all("repo:worktree" in call for call in calls)
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


@pytest.fixture
def main_checkout(tmp_path: Path) -> Path:
    origin, checkout = tmp_path / "origin.git", tmp_path / "main"
    git_ok("init", "-q", "--bare", "-b", "main", str(origin))
    git_ok("clone", "-q", str(origin), str(checkout))
    git_ok("-C", str(checkout), "config", "user.name", "Start test")
    git_ok("-C", str(checkout), "config", "user.email", "start-test@example.invalid")
    git_ok("-C", str(checkout), "commit", "-q", "--allow-empty", "-m", "base")
    git_ok("-C", str(checkout), "push", "-q", "origin", "HEAD:main")
    # The newest main exists only on origin; start must fetch it.
    git_ok("clone", "-q", str(origin), str(tmp_path / "other"))
    git_ok("-C", str(tmp_path / "other"), "-c", "user.name=Other", "-c",
           "user.email=other@example.invalid", "commit", "-q", "--allow-empty", "-m", "newest")
    git_ok("-C", str(tmp_path / "other"), "push", "-q", "origin", "HEAD:main")
    return checkout


def test_start_creates_a_worktree_from_the_newest_main_and_marks_the_issue(
        main_checkout, local_config, monkeypatch, capsys):
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets, "ready_issues",
        lambda root, repo, allow_existing_branch=False: [{"number": 5, "title": BRANCH}],
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
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

    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])
    assert run(main_checkout, "start", "5") == 1
    assert "not startable" in capsys.readouterr().err


def test_start_argument_overrides_the_checkout_worktree_root(
        main_checkout, local_config, monkeypatch):
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets,
        "ready_issues",
        lambda root, repo, allow_existing_branch=False: [{"number": 5, "title": BRANCH}],
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
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
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: ready)
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: slots)
    assert run(main_checkout, "start", "5", "--worktree-root", str(main_checkout.parent)) == 1
    assert message in capsys.readouterr().err
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_uses_a_sibling_worktree_root_by_default(main_checkout, monkeypatch, capsys):
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets, "ready_issues",
        lambda root, repo, allow_existing_branch=False: [{"number": 5, "title": BRANCH}],
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
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
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets, "ready_issues",
        lambda root, repo, allow_existing_branch=False: [{"number": 5, "title": BRANCH}],
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
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
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets, "ready_issues",
        lambda root, repo, allow_existing_branch=False: [{"number": 5, "title": BRANCH}],
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
    git_ok(
        "-C", str(main_checkout), "worktree", "add", "-b", "feature/other",
        str(main_checkout.parent / "other-worker"), "origin/main",
    )

    assert run(main_checkout, "start", "5", "--no-create") == 1
    assert f"no worktree exists for branch {BRANCH}" in capsys.readouterr().err.lower()
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_without_no_create_refuses_an_existing_issue_branch(
        main_checkout, monkeypatch, capsys):
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets,
        "ready_issues",
        lambda root, repo, allow_existing_branch=False: (
            [{"number": 5, "title": BRANCH}] if allow_existing_branch else []
        ),
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)
    git_ok(
        "-C", str(main_checkout), "worktree", "add", "-b", BRANCH,
        str(main_checkout.parent / "existing-worker"), "origin/main",
    )

    assert run(main_checkout, "start", "5") == 1
    assert "not startable" in capsys.readouterr().err
    assert not any(call[:2] == ["issue", "edit"] for call in fake.calls)


def test_start_assigns_a_cloud_worker_without_creating_a_worktree(
        main_checkout, monkeypatch, capsys):
    fake = StartGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(
        work_tickets, "ready_issues", lambda root, repo: [{"number": 5, "title": BRANCH}]
    )
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: None)

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
    report = {"body": COMPLETE_REPORT}
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
            return json.dumps({"headRefName": "feature/worker", "headRefOid": head})
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
        lambda root: (commands.append(("suite", "Complete suite")) or "214 passed"),
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

    commit = work_tickets.integrate(main_checkout, 8, None, "build", [["check"]])
    assert (main_checkout / "worker.txt").is_file()
    assert subprocess.run(
        ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", head, "main"],
        capture_output=True, check=False,
    ).returncode == 0
    assert commit and started == [9]
    message = subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert "work issue #5, field report #8, PR #7" in message
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
    assert closes == [
        ["issue", "close", "5", "--repo", "git.example/owner/tracker"],
        ["issue", "close", "8", "--repo", "git.example/owner/tracker"],
    ]
    assert all("PR #7. Suite: 214 passed." in body for body in bodies)
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
    report = {"body": COMPLETE_REPORT}
    commands: list[tuple[str, str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(
        work_tickets,
        "run_gh",
        lambda root, args: json.dumps({"headRefName": "feature/discovery", "headRefOid": head})
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
        lambda root: (commands.append(("suite", "Complete suite")) or "passed"),
    )
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    commit = work_tickets.integrate(main_checkout, 8, None, None)
    assert commit
    assert subprocess.run(
        ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", head, "main"],
        capture_output=True, check=False,
    ).returncode == 0
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
    report = {"body": COMPLETE_REPORT}
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    def gh_call(root, args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefName": "feature/failure", "headRefOid": head})
        return ""
    monkeypatch.setattr(work_tickets, "run_gh", gh_call)
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    def fail(root, command, description):
        if description == failed_step:
            raise work_tickets.QueueError(f"{description} failed: expected")
    monkeypatch.setattr(work_tickets, "run_project_command", fail)
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: fail(root, "suite", "Complete suite"))
    def fail_checks(root, commands, temporary):
        if failed_step == "Project check":
            raise work_tickets.QueueError("Project check failed: expected")
    monkeypatch.setattr(work_tickets, "run_project_checks", fail_checks)

    with pytest.raises(work_tickets.QueueError, match=failed_step):
        work_tickets.integrate(
            main_checkout, 8, None, "build",
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
    assert any(call[:3] == ["issue", "comment", "8"] for call in calls)
    assert any(call[:5] == ["issue", "edit", "8", "--add-label", "escalated"] for call in calls)
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
        'public_identity = "Start test <start-test@example.invalid>"\n\n'
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
    report = {"body": COMPLETE_REPORT}
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
            return json.dumps({"headRefName": "feature/worker", "headRefOid": head})
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
        work_tickets, "run_suite", lambda root: run_project_command(root, "suite", "Complete suite"))
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
            work_tickets.integrate(main_checkout, 8, None, "build", [["check"]])
        mirror_head = subprocess.run(
            ["git", "--git-dir", str(mirror), "rev-parse", "main"],
            capture_output=True, text=True, check=False,
        )
        assert mirror_head.returncode == 0
        assert mirror_head.stdout.strip() == mirror_baseline
        return

    commit = work_tickets.integrate(main_checkout, 8, None, "build", [["check"]])
    assert (main_checkout / "worker.txt").is_file()
    assert subprocess.run(
        ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", head, "main"],
        capture_output=True, check=False,
    ).returncode == 0
    assert commit and started == [9]
    message = subprocess.run(
        ["git", "-C", str(main_checkout), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert "Integrate feature/worker: worker" in message
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
    assert closes == [
        ["issue", "close", "5", "--repo", "git.example/owner/tracker"],
        ["issue", "close", "8", "--repo", "git.example/owner/tracker"],
    ]
    assert all("PR #7. Suite: 214 passed." in body for body in bodies)
    assert not worker.exists()
    assert subprocess.run(
        ["git", "--git-dir", str(mirror), "show-ref", "--verify", "refs/heads/feature/worker"],
        capture_output=True, text=True, check=False,
    ).returncode == 0


@pytest.mark.parametrize(
    ("message", "email", "error"),
    [
        ("worker #12", "start-test@example.invalid", "tracker reference"),
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
        'public_identity = "Start test <start-test@example.invalid>"\n\n'
        f'[mirrors]\n"{main_checkout.name}" = ['
        '{ remote = "mirror", branch = "main", fetch = false, public = true }]\n',
        encoding="utf-8",
    )
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "push", "-q", "mirror", "main")
    (main_checkout / "public.txt").write_text("public\n", encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "public.txt")
    git_ok(
        "-C", str(main_checkout), "-c", "user.name=Start test", f"-c", f"user.email={email}",
        "commit", "-q", "-m", message,
    )

    with pytest.raises(work_tickets.QueueError, match=error):
        work_tickets.guard_public_push(
            main_checkout, work_tickets.Mirror("mirror", "main", False, True)
        )


@pytest.mark.parametrize("subject", ["worker #12", "https://example.invalid/worker"])
def test_public_merge_message_rejects_tracker_references_and_host_addresses(
        main_checkout, monkeypatch, subject):
    def summary(arguments, **kwargs):
        return subprocess.CompletedProcess(arguments, 0, subject + "\n", "")

    monkeypatch.setattr(work_tickets.subprocess, "run", summary)

    with pytest.raises(work_tickets.QueueError, match="cannot contain"):
        work_tickets.integration_merge_message(
            main_checkout, "feature/worker", 5, 8, 7, True
        )


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
    report = {"body": COMPLETE_REPORT}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/conflict", "headRefOid": head}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    with pytest.raises(work_tickets.QueueError, match="shared.txt"):
        work_tickets.integrate(main_checkout, 8, None, None)
    assert not subprocess.run(["git", "-C", str(main_checkout), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    assert not any(call[:3] == ["issue", "comment", "8"] for call in calls)
    assert not any(call[:5] == ["issue", "edit", "8", "--add-label", "escalated"] for call in calls)
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
    report = {"body": COMPLETE_REPORT}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/blocked", "headRefOid": head}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, description: None)
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: "passed")
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    work_tickets.integrate(main_checkout, 8, None, None)
    assert worker.exists()
    assert "worker worktree was not removed" in capsys.readouterr().err
    assert [call[2] for call in calls if call[:2] == ["issue", "close"]] == ["5", "8"]

def integration_fakes(monkeypatch, head: str) -> list[list[str]]:
    report = {"body": COMPLETE_REPORT}
    calls: list[list[str]] = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (
        json.dumps({"headRefName": "feature/worker", "headRefOid": head})
        if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(
        work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args) or "")
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, label: "1 passed")
    monkeypatch.setattr(work_tickets, "run_suite", lambda root: "1 passed")
    monkeypatch.setattr(work_tickets, "guard", lambda root, branch, report: [])
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 0)
    return calls


@pytest.mark.parametrize("leak", [False, True], ids=["clean", "leak"])
def test_integrate_writes_the_configured_integration_branch_and_leaves_main(
        main_checkout, monkeypatch, leak):
    origin = main_checkout.parent / "origin.git"
    git_ok("-C", str(main_checkout), "pull", "-q", "--ff-only", "origin", "main")
    git_ok("-C", str(main_checkout), "switch", "-q", "-c", "se")
    (main_checkout / "se.toml").write_text(
        '[project]\nintegration_branch = "se"\npublic_check = true\n', encoding="utf-8")
    git_ok("-C", str(main_checkout), "add", "se.toml")
    git_ok("-C", str(main_checkout), "commit", "-q", "-m", "integrate into se")
    git_ok("-C", str(main_checkout), "push", "-q", "-u", "origin", "se")
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
            ["git", "--git-dir", str(origin), "merge-base", "--is-ancestor", head, ref],
            capture_output=True, check=False,
        ).returncode == 0

    assert work_tickets.integration_branch(main_checkout) == "se"
    if leak:
        with pytest.raises(work_tickets.QueueError, match="Public check failed.*nothing was pushed"):
            work_tickets.integrate(main_checkout, 8, None, None)
        assert not origin_contains("refs/heads/se")
        return
    work_tickets.integrate(main_checkout, 8, None, None)

    assert origin_contains("refs/heads/se")
    assert not origin_contains("refs/heads/main")
    assert subprocess.run(
        ["git", "--git-dir", str(origin), "rev-parse", "refs/heads/main"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() == main_before


def test_integrate_refuses_a_checkout_off_the_integration_branch(main_checkout, monkeypatch):
    (main_checkout / "se.toml").write_text('[project]\nintegration_branch = "se"\n', encoding="utf-8")
    integration_fakes(monkeypatch, "0" * 40)

    with pytest.raises(work_tickets.QueueError, match="not on the integration branch se.*switch se"):
        work_tickets.integrate(main_checkout, 8, None, None)


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


TRANSIENT = "remote: fatal error in commit_refs_rules\nerror: failed to push some refs"
NON_FAST_FORWARD = (
    " ! [rejected]        topic -> topic (non-fast-forward)\nerror: failed to push some refs"
)


@pytest.fixture
def fake_push(main_checkout, monkeypatch):
    """A fake git push answering from a script of (exit code, stderr); waits are recorded, not slept.

    Its checkout turns the public check off, so the retry tests reach the push; the gate's own
    tests set se.toml themselves."""
    (main_checkout / "se.toml").write_text("[project]\npublic_check = false\n", encoding="utf-8")
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


@pytest.mark.parametrize("settings", ["[project]\npublic_check = true\n", None])
def test_push_runs_the_public_check_gate_first(main_checkout, fake_push, monkeypatch, capsys,
                                               settings):
    """The gate is on unless se.toml turns it off: without the key, too (fail closed)."""
    calls, _, _ = fake_push
    if settings is None:
        (main_checkout / "se.toml").unlink()
    else:
        (main_checkout / "se.toml").write_text(settings, encoding="utf-8")
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
    (main_checkout / "se.toml").write_text("[project]\npublic_check = false\n", encoding="utf-8")
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
