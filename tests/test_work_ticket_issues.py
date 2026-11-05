"""work_tickets.py reads work issues and writes field reports through gh (mocked here)."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)

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
    assert "**Tested against main:** `abc1234`" in draft
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
    report.write_text("**Work issue:** #<n>  **Branch:** `<branch>` main `<commit>`\n",
                      encoding="utf-8")
    assert run(worktree, "field-report", "--file", str(report)) == 1
    error = capsys.readouterr().err
    assert "unfilled placeholder #<n>" in error and "unfilled placeholder <branch>" in error
    assert "unfilled placeholder <commit>" in error
    assert "does not link work issue #5" in error and "does not link pull request #7" in error
    assert not any(call[:2] == ["issue", "create"] for call in gh.calls)

    monkeypatch.setattr(work_tickets, "current_branch", lambda root: "main")
    assert run(worktree, "field-report", "--file", str(report)) == 1
    assert "does not match the work issue title" in capsys.readouterr().err


def test_field_report_may_mention_placeholders_below_its_header(worktree, gh, capsys):
    run(worktree, "intake", "--issue", "5")
    report = worktree / "report.md"
    report.write_text("**Work issue:** #5  **Pull request:** #7  main `abc1234`  **Result:** complete\n\n"
                      "## Delivered\n\n| Work issue item | Result | Commits | Evidence |\n"
                      "|---|---|---|---|\n" + EVIDENCE_ROWS + "\n\n"
                      "## Spec gaps\n\nThe draft fills `#<n>`, `<branch>` and `<commit>`.\n",
                      encoding="utf-8")
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
        assert "header Result must be exactly complete or partial" in capsys.readouterr().err
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


def test_validate_field_report_requires_template_sections_and_references(worktree, gh, monkeypatch):
    report = work_tickets.fetch_issue(worktree, 8, "git.example/owner/repo")
    report["body"] = "**Work issue:** #5  **Pull request:** #7\n\n## Delivered\nComplete."
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)

    with pytest.raises(work_tickets.QueueError, match="missing sections"):
        work_tickets.validate_field_report(worktree, 8, "git.example/owner/repo")

    report["body"] = (
        "**Work issue:** #5  **Pull request:** #7\n\n"
        + "\n\n".join(f"## {heading}\nComplete." for heading in work_tickets.FIELD_REPORT_SECTIONS)
    )
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


def test_missing_gh_points_to_setup(worktree, monkeypatch, capsys):
    worktree.mkdir(exist_ok=True)
    monkeypatch.setattr(work_tickets.shutil, "which", lambda name: None)
    assert run(worktree, "intake", "--issue", "5", "--repo", "git.example/owner/repo") == 1
    assert "setup command" in capsys.readouterr().err


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


def test_sync_merges_with_the_configured_public_identity(worktree, local_config, monkeypatch):
    calls: list[list[str]] = []

    def git(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "abc1234\n" if "rev-parse" in arguments else "", "")

    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)
    monkeypatch.setattr(work_tickets.subprocess, "run", git)
    local_config.parent.mkdir(parents=True)
    local_config.write_text('public_identity = "mb <mb>"\n', encoding="utf-8")

    assert run(worktree, "sync") == 0
    assert calls[0] == [
        "git", "-C", str(worktree), "-c", "user.name=mb", "-c", "user.email=mb",
        "merge", "--no-edit", "main",
    ]


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
        main_checkout, monkeypatch, capsys):
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
    report = {
        "body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(
            f"## {heading}\nComplete." for heading in work_tickets.FIELD_REPORT_SECTIONS
        )
    }
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

    commit = work_tickets.integrate(main_checkout, 8, None, "suite", "build", [["check"]])
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
    assert "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" in message
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
    report = {
        "body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(
            f"## {heading}\nComplete." for heading in work_tickets.FIELD_REPORT_SECTIONS
        )
    }
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
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    commit = work_tickets.integrate(main_checkout, 8, None, "suite", None)
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
    report = {"body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(
        f"## {heading}\nComplete." for heading in work_tickets.FIELD_REPORT_SECTIONS)}
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
    def fail_checks(root, commands, temporary):
        if failed_step == "Project check":
            raise work_tickets.QueueError("Project check failed: expected")
    monkeypatch.setattr(work_tickets, "run_project_checks", fail_checks)

    with pytest.raises(work_tickets.QueueError, match=failed_step):
        work_tickets.integrate(
            main_checkout, 8, None, "suite", "build",
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
    report = {
        "body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(
            f"## {heading}\nComplete." for heading in work_tickets.FIELD_REPORT_SECTIONS
        )
    }
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
            work_tickets.integrate(main_checkout, 8, None, "suite", "build", [["check"]])
        mirror_head = subprocess.run(
            ["git", "--git-dir", str(mirror), "rev-parse", "main"],
            capture_output=True, text=True, check=False,
        )
        assert mirror_head.returncode == 0
        assert mirror_head.stdout.strip() == mirror_baseline
        return

    commit = work_tickets.integrate(main_checkout, 8, None, "suite", "build", [["check"]])
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
    assert "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" in message
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
    report = {"body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(f"## {h}\nComplete." for h in work_tickets.FIELD_REPORT_SECTIONS)}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/conflict", "headRefOid": head}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    with pytest.raises(work_tickets.QueueError, match="shared.txt"):
        work_tickets.integrate(main_checkout, 8, None, "suite", None)
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
    report = {"body": "**Work issue:** #5  **Pull request:** #7\n\n" + "\n\n".join(f"## {h}\nComplete." for h in work_tickets.FIELD_REPORT_SECTIONS)}
    calls = []
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "git.example/owner/tracker")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: report)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: calls.append(args) or (json.dumps({"headRefName": "feature/blocked", "headRefOid": head}) if args[:2] == ["pr", "view"] else ""))
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, args, body: calls.append(args))
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, description: None)
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])

    work_tickets.integrate(main_checkout, 8, None, "suite", None)
    assert worker.exists()
    assert "worker worktree was not removed" in capsys.readouterr().err
    assert [call[2] for call in calls if call[:2] == ["issue", "close"]] == ["5", "8"]