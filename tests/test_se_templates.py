"""SE's side of templates (scripts/se_templates.py), the command component `templates` kern's MCP door serves:
draft gives the engine's answer, check answers the verdict first and refuses exactly where the
filing commands refuse, and nothing it does writes."""

from __future__ import annotations

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

import templates
import se_templates
import work_tickets
from test_work_ticket_issues import IDENTITY, FakeGh, templates_home, worktree  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = templates.load(ROOT, tree=True)
WORK = CATALOG["work"]
TITLE = WORK.example["title"]
FIELDS = dict(WORK.example["fields"])

# Its git is the fake in memory (tests/conftest.py `fake_git_door`): no worktree is a repository.
pytestmark = pytest.mark.usefixtures("fake_git_door")


class DocumentGh(FakeGh):
    """FakeGh that also answers the REST reads of the documents the gate's edits leave behind
    (`gh api repos/<owner>/<repo>/issues/<n>`, `.../issues/comments/<id>`), from `documents`:
    issue #7 a good work issue labelled work, unless a test changes it."""

    def __init__(self) -> None:
        super().__init__()
        self.documents: dict[str, dict] = {"issues/7": {"number": 7, "title": TITLE, "body": GOOD_WORK,
                                                        "labels": [{"name": "work"}]}}

    def __call__(self, root: Path, arguments: list[str]) -> str:
        path = arguments[1].removeprefix(f"repos/{OWNER}/{REPO_NAME}/") if arguments[:1] == ["api"] else ""
        if path in self.documents:
            self.calls.append(arguments)
            return json.dumps(self.documents[path])
        return super().__call__(root, arguments)


@pytest.fixture
def gh(monkeypatch) -> DocumentGh:
    """GitHub as test_work_ticket_issues fakes it, on the work_tickets se_templates.py imports,
    with the documents an edit reads (DocumentGh)."""
    fake = DocumentGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    return fake


@pytest.fixture(autouse=True)
def direct(monkeypatch):
    """Every command runs directly, never through a kern that may serve this checkout."""
    monkeypatch.setenv("SE_KERN", "off")


def run(capsys, *arguments: str) -> tuple[int, str, str]:
    code = se_templates.main([*arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def drafted_template(out: str, name: str = "work") -> str:
    """What an answer gives after its guidance: the template, on its last page."""
    guidance, heading, template = out.partition(f"\n{se_templates.TEMPLATE_HEADING.format(name=name)}\n\n")
    assert heading and guidance.startswith(f"Guidance for the template {name}: "), out[:200]
    return template


def test_list_and_draft_answer_what_the_engine_answers(capsys):
    code, out, _ = run(capsys, "list", "--tree")
    assert code == 0 and out.splitlines() == templates.list_templates(CATALOG)
    code, out, _ = run(capsys, "draft", "work", "--tree")
    drafted = json.loads(drafted_template(out))
    assert code == 0 and drafted == templates.draft_fields(WORK)
    assert {"fields", "field_says", "field_shape", "schema"} <= set(drafted)
    assert drafted["field_shape"]["goal"]["required"] and drafted["schema"]["required"]
    code, out, _ = run(capsys, "draft", "work", "--markdown", "--tree")
    assert code == 0 and drafted_template(out) == templates.draft(WORK)


def guided_project(root: Path) -> Path:
    """A project whose guidance tree holds one note at depth 0 and one for issues."""
    import test_guidance
    root.mkdir(parents=True, exist_ok=True)
    test_guidance.note(root, "guidance/first.md", "first", body="Read me first.")
    test_guidance.note(root, "guidance/issue/issues.md", "issues", body="Issues say why.")
    return root


def test_a_draft_prints_the_templates_guidance_before_the_template(capsys, tmp_path):
    root = guided_project(tmp_path / "project")
    code, out, _ = run(capsys, "draft", "work", "--worktree", str(root), "--tree")
    assert code == 0
    assert out.splitlines()[0] == "Guidance for the template work: 2 notes, general before specific."
    heading = se_templates.TEMPLATE_HEADING.format(name="work")
    assert out.index("## first") < out.index("Read me first.") < out.index("## issues") \
        < out.index("Issues say why.") < out.index(heading)
    assert json.loads(drafted_template(out)) == templates.draft_fields(WORK)


def test_a_second_draft_in_a_session_names_the_notes_already_printed(capsys, tmp_path):
    root = guided_project(tmp_path / "project")
    asked = ["--worktree", str(root), "--session", "s-1", "--tree"]
    code, first, _ = run(capsys, "draft", "work", *asked)
    assert code == 0 and "Read me first." in first
    code, second, _ = run(capsys, "draft", "ticket", *asked)
    assert code == 0 and "Read me first." not in second and "Issues say why." not in second
    assert "already printed this session: first, issues" in second
    assert second.splitlines()[0].endswith("; 2 already printed this session.")
    # The template still comes, whole, after the names; fill names them as draft does.
    assert json.loads(drafted_template(second, "ticket")) == templates.draft_fields(CATALOG["ticket"])
    code, filled, _ = run(capsys, "fill", "work", *asked)
    assert "already printed this session: first, issues" in filled and "Read me first." not in filled


def test_a_draft_whose_guidance_passes_a_page_comes_in_pages_the_template_on_the_last(
        capsys, tmp_path, monkeypatch):
    import se_guidance
    import test_guidance
    root = guided_project(tmp_path / "project")
    for index in range(4):
        test_guidance.note(root, f"guidance/issue/n{index}.md", f"n{index}",
                           body=f"n{index} " + "word " * 1200)
    monkeypatch.setattr(se_guidance, "page_limit", lambda: 15000)
    heading = se_templates.TEMPLATE_HEADING.format(name="work")
    pages, page = [], 1
    while True:
        code, out, _ = run(capsys, "draft", "work", "--worktree", str(root), "--page", str(page),
                           "--tree")
        assert code == 0
        pages.append(out)
        if heading in out:
            break
        assert f"and --page {page + 1} for the next.]" in out
        page += 1
    assert len(pages) > 1 and all(len(text.encode("utf-8")) <= 15000 for text in pages)
    # Pages break between notes: each note's text whole on one page.
    for index in range(4):
        assert sum((f"n{index} " + "word " * 1200).rstrip() in text for text in pages) == 1
    assert json.loads(pages[-1].partition(f"\n{heading}\n\n")[2]) == templates.draft_fields(WORK)


def test_an_unknown_template_is_answered_with_the_list_of_templates(capsys):
    for command in (["draft", "nope"], ["check", "nope", "--body", "B."]):
        code, out, _ = run(capsys, *command, "--tree")
        assert code == 2, command
        assert "no template 'nope'; the templates are:" in out
        assert all(line in out for line in templates.list_templates(CATALOG))


def test_check_answers_its_verdict_first_and_exits_0(capsys, tmp_path, worktree, gh, templates_home):
    thin = tmp_path / "thin.md"
    thin.write_text(f"<!-- se:fleet -->\n{CATALOG['work'].marker_line}\n\n## Situation\n\nIt is so.\n",
                    encoding="utf-8")
    code, out, _ = run(capsys, "check", "work", "--title", "thin-ticket", "--body-file",
                       str(thin), "--worktree", str(worktree), "--tree")
    lines = out.splitlines()
    assert code == 0 and lines[0].startswith("refused: ") and lines[0].endswith(" findings")
    assert any(line.startswith("  Problem: missing") for line in lines)
    assert len(lines) <= 1 + templates.REFUSAL_LINES
    assert lines[-1].endswith(f"{Path(se_templates.__file__).resolve()} draft work")

    code, out, err = run(capsys, "check", "work", "--fields-json", json.dumps(FIELDS),
                         "--render", "--worktree", str(worktree), "--tree")
    first, rendered = out.split("\n", 1)
    assert code == 0 and first == "passes"
    assert rendered == templates.render(WORK, FIELDS)
    code, out, _ = run(capsys, "check", "work", "--title", TITLE, "--body",
                       templates.render(WORK, FIELDS), "--worktree", str(worktree), "--tree")
    assert code == 0 and out.splitlines()[0] == "passes"


def test_check_selects_by_action_and_answers_free_texts_as_passing(capsys, worktree, gh,
                                                                    templates_home):
    code, out, _ = run(capsys, "check", "--action", "comment.create", "--body", "Thanks.",
                       "--worktree", str(worktree), "--tree")
    assert code == 0 and out.splitlines() == ["passes", "free: no template applies (comment.create)"]
    code, out, _ = run(capsys, "check", "--action", "issue.create", "--labels", "work",
                       "--body", "Only a line.", "--title", TITLE, "--worktree", str(worktree),
                       "--tree")
    assert code == 0 and out.startswith("refused: ") and "the work template refuses" in out


@pytest.mark.parametrize("arguments", [
    ["check", "--body", "B."],
    ["check", "work", "--action", "issue.create", "--body", "B."],
    ["check", "work", "--repo", "git.example/o/r", "--body", "B."],
    ["check", "work", "--fields-json", "[1]"],
])
def test_check_usage_errors_exit_2(capsys, arguments):
    code, out, _ = run(capsys, *arguments, "--tree")
    assert code == 2 and out.strip()


# The same title and body, through se_templates.py check and through work_tickets.py file with
# [templates] enforce = "refuse": both refuse in exactly the same cases.

def fields_with(**changes) -> dict:
    values = {key: value for key, value in FIELDS.items() if changes.get(key, "") is not None}
    values.update({key: value for key, value in changes.items() if value is not None})
    return values


CASES = {
    "passes": (TITLE, fields_with(), None),
    "missing field": (TITLE, fields_with(problem=None), "Problem: missing"),
    "broken name": ("Plain Titles For Every Issue Here", fields_with(), "breaks the name rule"),
    "dangling command": (TITLE, fields_with(goal="Run `work_tickets.py frobnicate` once."),
                         "frobnicate"),
    "private term": (TITLE, fields_with(goal="For Quuxcorp."), "local list"),
}


@pytest.mark.parametrize("case", CASES)
def test_check_refuses_exactly_where_file_refuses(case, capsys, worktree, gh, templates_home):
    (worktree / "se.toml").write_text(f'{IDENTITY}\n[templates]\nenforce = "refuse"\n',
                                      encoding="utf-8")
    (worktree / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    title, fields, says = CASES[case]
    body = worktree / "body.md"
    body.write_text(templates.render(WORK, fields), encoding="utf-8")
    code, out, _ = run(capsys, "check", "work", "--title", title, "--body-file", str(body),
                       "--worktree", str(worktree), "--tree")
    assert code == 0
    filed = work_tickets.main(["file", "--title", title, "--body-file", str(body),
                               "--worktree", str(worktree)])
    refusal = capsys.readouterr().err
    if says is None:
        assert out.splitlines()[0] == "passes" and filed == 0
        return
    assert out.splitlines()[0].startswith("refused: ") and says in out
    assert filed == 1 and gh.bodies == []
    assert says.split(":")[0] in refusal or says in refusal
    assert "quux" not in out.lower()


@pytest.mark.parametrize("recorded, filed_code", [("1.0.0", 0), ("1.0.1", 0), ("0.9.0", 1)])
def test_file_reads_the_version_the_body_as_given_records(recorded, filed_code, capsys, worktree,
                                                          gh, templates_home):
    """`render` marks the filed body with the template's version now, so the filing reads the
    version of the body as given: a minor or patch move files with its warning, a major one refuses."""
    (worktree / "se.toml").write_text(f'{IDENTITY}\n[templates]\nenforce = "refuse"\n',
                                      encoding="utf-8")
    body = worktree / "body.md"
    body.write_text(templates.INPUTS_PATTERN.sub("", templates.render(WORK, FIELDS)).replace(
        f" {WORK.version} ", f" {recorded} ", 1), encoding="utf-8")
    filed = work_tickets.main(["file", "--title", TITLE, "--body-file", str(body),
                               "--worktree", str(worktree)])
    refusal = capsys.readouterr().err
    assert filed == filed_code
    named = f"records work {recorded}; the template is at {WORK.version}"
    assert (named in refusal) == (recorded != WORK.version)
    if filed_code:
        assert gh.bodies == [] and "refuses this text" in refusal
    else:
        assert WORK.marker_line in gh.bodies[0]


# The gate (se_templates.py gate): SE's PreToolUse hook's judge of a write through the GitHub tools.

import datetime  # noqa: E402
import io  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402

import review  # noqa: E402
from shell_paths import BASH, sh  # noqa: E402
from test_templates import field_report_variants, review_report  # noqa: E402

OWNER, REPO_NAME = "owner", "repo"
SESSION = "gate-session"
THIN = "<!-- se:fleet -->\n\n## Situation\n\nIt is so.\n"
WORK_MARKER = CATALOG["work"].marker_line
GOOD_WORK = templates.render(WORK, FIELDS)
GOOD_REVIEW = review.verdict_comment(5, review_report(), False)
THIN_REVIEW = f"{review.VERDICT_MARKER}\n## Review of pull request #5\n\nLooks fine.\n"
REPORTS = field_report_variants()


def payload(tool: str, cwd: Path, **given) -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(cwd),
                       "tool_name": tool, "tool_input": {"owner": OWNER, "repo": REPO_NAME,
                                                         **given}})


@pytest.fixture
def home_repo(monkeypatch):
    """`owner/repo` is the home of every checkout: its origin, as the filing commands read it."""
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: f"git.example/{OWNER}/{REPO_NAME}")


@pytest.fixture
def project(worktree, home_repo, templates_home) -> Path:
    """The checkout holding the payload's cwd: its se.toml decides, its local list is read."""
    (worktree / ".git").mkdir()
    (worktree / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    return worktree


def gate(capsys, monkeypatch, text: str, *arguments: str) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert se_templates.main(["gate", *arguments]) == 0
    return capsys.readouterr().out


def denial(out: str) -> str:
    answer = json.loads(out)["hookSpecificOutput"]
    assert answer["hookEventName"] == "PreToolUse" and answer["permissionDecision"] == "deny"
    assert set(answer) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
    return answer["permissionDecisionReason"]


# One row of the gate's table each: tool, the call's other arguments, the off-template body, the template's
# own body and the template that refuses.
ROWS = {
    "issue_write create": ("issue_write", {"method": "create", "title": TITLE, "labels": ["work"]},
                           THIN, GOOD_WORK, "work"),
    "issue_write update": ("issue_write", {"method": "update", "issue_number": 7, "title": TITLE,
                                           "labels": ["work"]}, THIN, GOOD_WORK, "work"),
    "add_issue_comment": ("add_issue_comment", {"issue_number": 7}, THIN_REVIEW, GOOD_REVIEW,
                          "review"),
    "update_issue_comment": ("update_issue_comment", {"comment_id": 9}, THIN_REVIEW, GOOD_REVIEW,
                             "review"),
    "create_pull_request": ("create_pull_request", {"title": "A change", "base": "main",
                                                    "head": "a-change"},
                            REPORTS["unfilled"], REPORTS["complete"], "field-report"),
    "update_pull_request": ("update_pull_request", {"pullNumber": 5, "base": "main"},
                            REPORTS["unfilled"], REPORTS["complete"], "field-report"),
    "pull_request_review_write": ("pull_request_review_write", {"method": "create",
                                                                "pullNumber": 5},
                                  THIN_REVIEW, GOOD_REVIEW, "review"),
    "add_comment_to_pending_review": ("add_comment_to_pending_review", {"pullNumber": 5},
                                      THIN_REVIEW, GOOD_REVIEW, "review"),
    "add_reply_to_pull_request_comment": ("add_reply_to_pull_request_comment",
                                          {"pullNumber": 5, "commentId": 3},
                                          THIN_REVIEW, GOOD_REVIEW, "review"),
}


@pytest.mark.parametrize("row", ROWS)
def test_the_gate_denies_an_off_template_write_of_each_tool_and_passes_its_template(
        row, capsys, monkeypatch, project, gh):
    tool, given, thin, good, template = ROWS[row]
    out = gate(capsys, monkeypatch, payload(f"mcp__github__{tool}", project, body=thin, **given),
               "--gate", "refuse")
    reason = denial(out)
    assert f"the {template} template refuses" in reason and f"in {OWNER}/{REPO_NAME}" in reason
    assert len(reason.splitlines()) <= templates.REFUSAL_LINES
    assert reason.splitlines()[-1].startswith(
        f"Get the template: the se server's templates tool, command \"se_templates.py draft\", args [\"{template}\"]")
    assert gate(capsys, monkeypatch, payload(f"mcp__github__{tool}", project, body=good, **given),
                "--gate", "refuse") == ""


@pytest.mark.parametrize("name", ["mcp__plugin_github_github__issue_write",
                                  "github-mcp-server-issue_write", "github/issue_write"])
def test_every_shape_of_a_guarded_name_is_gated(name, capsys, monkeypatch, project, gh):
    text = payload(name, project, method="create", title=TITLE, labels=["work"], body=THIN)
    assert "the work template refuses" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


def test_the_payloads_mcp_server_name_is_the_server_part(capsys, monkeypatch, project, gh):
    given = {"method": "create", "title": TITLE, "labels": ["work"], "body": THIN}
    data = json.loads(payload("mcp__gh__issue_write", project, **given))
    assert gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse") == ""
    data["mcp_server"] = {"name": "github", "source": "user"}
    assert "work template" in denial(gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse"))
    data["tool_name"], data["mcp_server"] = "mcp__github__issue_write", {"name": "files"}
    assert gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse") == ""


def test_copilots_payload_is_read_from_its_tool_args(capsys, monkeypatch, project, gh):
    given = {"owner": OWNER, "repo": REPO_NAME, "method": "create", "title": TITLE,
             "labels": ["work"], "body": THIN}
    text = json.dumps({"sessionId": SESSION, "cwd": str(project),
                       "toolName": "github-mcp-server-issue_write", "toolArgs": json.dumps(given)})
    assert "work template" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


def test_free_writes_and_the_switch_off_print_nothing(capsys, monkeypatch, project, gh):
    given = {"method": "create", "title": TITLE, "labels": ["work"]}
    thin = payload("mcp__github__issue_write", project, body=THIN, **given)
    away = json.loads(thin)
    away["tool_input"].update(owner="someone", repo="elsewhere")
    bodiless = payload("mcp__github__issue_write", project, **given)
    unguarded = json.loads(thin)
    unguarded["tool_name"] = "mcp__github__get_me"
    for text, switch in ((json.dumps(away), ["--gate", "refuse"]), (bodiless, ["--gate", "refuse"]),
                         (json.dumps(unguarded), ["--gate", "refuse"]), (thin, ["--gate", "off"]),
                         (thin, [])):
        assert gate(capsys, monkeypatch, text, *switch) == "", (text, switch)
    (project / "se.toml").write_text(f'{IDENTITY}\n[templates]\ngate = "refuse"\n', encoding="utf-8")
    assert "work template" in denial(gate(capsys, monkeypatch, thin))
    monkeypatch.setenv("SE_TEMPLATES_GATE", "OFF")
    assert gate(capsys, monkeypatch, thin) == ""


def test_warn_hands_the_findings_to_the_agent_and_never_allows(capsys, monkeypatch, project, gh):
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    answer = json.loads(gate(capsys, monkeypatch, text, "--gate", "warn"))["hookSpecificOutput"]
    assert set(answer) == {"hookEventName", "additionalContext"}
    assert "([templates] gate = warn); sent anyway" in answer["additionalContext"]
    assert "Problem: missing" in answer["additionalContext"]


def test_a_wrong_gate_value_is_a_template_error_naming_the_file(worktree):
    (worktree / "se.toml").write_text('[templates]\ngate = "maybe"\n', encoding="utf-8")
    with pytest.raises(templates.TemplateError, match=r"\[templates\] gate = 'maybe' in se.toml"):
        templates.enforcement(worktree)


def test_the_second_refusal_offers_the_hold_and_the_held_write_then_passes(
        capsys, monkeypatch, project, gh):
    given = {"method": "create", "title": TITLE, "body": THIN}
    thin = payload("mcp__github__issue_write", project, labels=["work"], **given)
    held = payload("mcp__github__issue_write", project, labels=["work", "off-template"], **given)
    first = denial(gate(capsys, monkeypatch, thin, "--gate", "refuse"))
    assert "off-template" not in first
    assert "off-template" in denial(gate(capsys, monkeypatch, held, "--gate", "refuse"))
    assert gate(capsys, monkeypatch, held, "--gate", "refuse") == ""
    ready = payload("mcp__github__issue_write", project, labels=["work", "off-template", "ready"],
                    **given)
    assert denial(gate(capsys, monkeypatch, ready, "--gate", "refuse"))


def test_a_private_term_is_refused_every_time_and_never_printed(capsys, monkeypatch, project, gh):
    body = templates.render(WORK, {**FIELDS, "goal": "For Quuxcorp."})
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work", "off-template"], body=body)
    for _ in range(4):
        reason = denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
        assert "local list" in reason and "quux" not in reason.lower()
        assert "--hold" not in reason


def test_an_issue_edit_without_labels_is_checked_against_its_bodys_template(
        capsys, monkeypatch, project, gh):
    body = WORK_MARKER + "\n" + THIN
    text = payload("mcp__github__issue_write", project, method="update", issue_number=7, body=body)
    assert "the work template refuses" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


def unmarked(body: str) -> str:
    """`body` without its template marker lines: a document filed over raw REST."""
    return "".join(line for line in body.splitlines(keepends=True)
                   if not templates.TEMPLATE_MARKER_PATTERN.fullmatch(line.rstrip("\n")))


def edit(project: Path, **given) -> str:
    return payload("mcp__github__issue_write", project, method="update", issue_number=7, **given)


def test_an_edit_without_labels_is_judged_by_the_template_its_issue_names(capsys, monkeypatch,
                                                                          project, gh):
    """The issue edited is a work issue whose body carries the work marker: an edit that names no
    labels is the work template's, whatever the guess by labels and order would take (ticket)."""
    changed = templates.render(WORK, {**FIELDS, "goal": "Every title names its change."})
    assert gate(capsys, monkeypatch, edit(project, body=changed), "--gate", "refuse") == ""
    assert ["api", f"repos/{OWNER}/{REPO_NAME}/issues/7"] in gh.calls
    reason = denial(gate(capsys, monkeypatch, edit(project, body=unmarked(changed)), "--gate", "refuse"))
    assert "the work template refuses" in reason and "ticket" not in reason
    assert f"drops the line that names its template (work); keep `{WORK_MARKER}`" in reason
    thin = denial(gate(capsys, monkeypatch, edit(project, body=WORK_MARKER + "\n" + THIN), "--gate", "refuse"))
    assert "the work template refuses" in thin and "Problem: missing" in thin


def test_an_edit_of_an_issue_that_names_no_template_is_refused_naming_the_stamp(
        capsys, monkeypatch, project, gh):
    gh.documents["issues/7"]["body"] = unmarked(GOOD_WORK)
    found = []
    monkeypatch.setattr(se_templates, "judged", lambda *given: found.append(given) or "")
    reason = denial(gate(capsys, monkeypatch, edit(project, body=unmarked(GOOD_WORK)), "--gate", "refuse"))
    assert reason.startswith(f"issue.edit in {OWNER}/{REPO_NAME}: #7 names no template")
    assert f"work_tickets.py stamp 7 --worktree {project} --repo {OWNER}/{REPO_NAME} --template work" in reason
    assert "work_tickets.py file" in reason and "template refuses" not in reason
    assert found == []  # judged against no template at all
    labels_only = denial(gate(capsys, monkeypatch, edit(project, labels=["work", "in-progress"]),
                              "--gate", "refuse"))
    assert "#7 names no template" in labels_only
    body = body_file(project, unmarked(GOOD_WORK))  # the edit SE made over raw REST
    shell = shell_payload(f"gh api -X PATCH repos/{OWNER}/{REPO_NAME}/issues/7 -F body=@{body}", project)
    assert "#7 names no template" in denial(gate(capsys, monkeypatch, shell, "--gate", "refuse"))
    warned = json.loads(gate(capsys, monkeypatch, edit(project, body=THIN), "--gate", "warn"))
    assert "#7 names no template" in warned["hookSpecificOutput"]["additionalContext"]
    assert gh.documents["issues/7"]["body"] == unmarked(GOOD_WORK)  # the gate writes nothing


def test_a_label_only_edit_is_judged_by_the_document_it_leaves(capsys, monkeypatch, project, gh):
    assert gate(capsys, monkeypatch, edit(project, labels=["work", "in-progress"]), "--gate", "refuse") == ""
    reason = denial(gate(capsys, monkeypatch, edit(project, labels=["ready"]), "--gate", "refuse"))
    assert "the work template refuses" in reason and "it needs the labels work" in reason
    shell = shell_payload(f"gh issue edit 7 -R {OWNER}/{REPO_NAME} --remove-label work", project)
    assert "it needs the labels work" in denial(gate(capsys, monkeypatch, shell, "--gate", "refuse"))
    shell = shell_payload(f"gh issue edit 7 -R {OWNER}/{REPO_NAME} --add-label in-progress", project)
    assert gate(capsys, monkeypatch, shell, "--gate", "refuse") == ""
    gh.documents["issues/7"]["body"] = WORK_MARKER + "\n" + THIN  # its body breaks its template
    reason = denial(gate(capsys, monkeypatch, edit(project, labels=["work", "in-progress"]), "--gate", "refuse"))
    assert "the work template refuses" in reason and "Problem: missing" in reason
    closing = edit(project, state="closed")
    assert gate(capsys, monkeypatch, closing, "--gate", "refuse") == ""  # the document stays as it is


def test_a_comment_edit_keeps_its_comments_template_and_an_unmarked_comment_stays_free(
        capsys, monkeypatch, project, gh):
    gh.documents["issues/comments/9"] = {"id": 9, "body": GOOD_REVIEW}
    text = payload("mcp__github__update_issue_comment", project, comment_id=9, body="Looks fine.\n")
    reason = denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
    assert "the review template refuses" in reason and "keep `<!-- se:review -->`" in reason
    gh.documents["issues/comments/9"]["body"] = "A plain comment.\n"
    assert gate(capsys, monkeypatch, text, "--gate", "refuse") == ""


def test_an_edit_whose_document_cannot_be_read_is_judged_by_its_body_alone(capsys, monkeypatch,
                                                                            project, gh):
    gh.documents.clear()
    assert gate(capsys, monkeypatch, edit(project, body=unmarked(GOOD_WORK)), "--gate", "refuse") == ""
    log = (project / ".se" / ".runtime" / "templates-gate.log").read_text(encoding="utf-8").splitlines()
    assert len(log) == 1 and "issue.edit in owner/repo: the document it edits cannot be read" in log[0]
    assert "the work template refuses" in denial(
        gate(capsys, monkeypatch, edit(project, body=WORK_MARKER + "\n" + THIN), "--gate", "refuse"))


def test_a_fresh_snapshot_of_kerns_answers_the_document_and_a_stale_one_reads_it_again(
        capsys, monkeypatch, project, gh):
    import se_relay
    now = datetime.datetime(2026, 11, 24, 12, 0, tzinfo=datetime.timezone.utc)
    held = {"data": {"number": 7, "title": TITLE, "body": unmarked(GOOD_WORK), "labels": ["work"]},
            "read": "2026-11-24T11:58:00Z"}
    asked = []

    def get(name: str):
        asked.append(name)
        return held

    monkeypatch.setattr(se_relay, "relay", lambda root: se_relay.Relay(root, get, lambda: now))
    reason = denial(gate(capsys, monkeypatch, edit(project, labels=["work"]), "--gate", "refuse"))
    assert "#7 names no template" in reason and asked == [f"github/issues/{OWNER}.{REPO_NAME}.7"]
    assert not any(call[:1] == ["api"] for call in gh.calls)
    held["read"] = "2026-11-24T11:00:00Z"  # older than se_relay.MAX_AGE_SECONDS: GitHub answers
    assert gate(capsys, monkeypatch, edit(project, labels=["work"]), "--gate", "refuse") == ""
    assert ["api", f"repos/{OWNER}/{REPO_NAME}/issues/7"] in gh.calls


def test_a_crash_after_selection_denies_and_one_before_passes_and_logs(
        capsys, monkeypatch, project, gh):
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)

    def broken(*_):
        raise RuntimeError("the disk is gone")

    with monkeypatch.context() as patch:
        patch.setattr(se_templates, "findings", broken)
        reason = denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
    assert reason.startswith("SE's template gate failed on this write (RuntimeError), so it was not sent")
    assert "work_tickets.py file" in reason and "SE_TEMPLATES_GATE=off" in reason
    log = project / ".se" / ".runtime" / "templates-gate.log"
    assert gate(capsys, monkeypatch, "{not json", "--gate", "refuse") == ""
    with monkeypatch.context() as patch:
        patch.setattr(se_templates, "deciding", broken)
        assert gate(capsys, monkeypatch, text, "--gate", "refuse") == ""
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "RuntimeError: the disk is gone" in lines[0]
    assert "It is so" not in log.read_text(encoding="utf-8")


def test_a_gate_past_its_bound_passes_and_logs(capsys, monkeypatch, project, gh):
    """A judgement still running at the bound: the bound is zero and the judgement waits until
    the gate has answered, so the order, not the clock, makes it late. The gate's wait starts once
    the judgement is deciding, past finding the project, as no scheduler promises that order:
    without it the gate may give up before the judgement knows the project, and its line goes to
    SE's own checkout. Only se_templates' threads are the test's, and its judgement, released as a
    free write, ends before the test does, so no thread of it outlives the test."""
    released, reached = threading.Event(), threading.Event()
    runners: list[threading.Thread] = []

    class Started(threading.Thread):
        def start(self) -> None:
            runners.append(self)
            super().start()
            assert reached.wait(60), "the judgement never reached deciding"

    def deciding(*_) -> None:
        reached.set()
        assert released.wait(60), "the test never released the judgement"

    monkeypatch.setattr(se_templates, "GATE_SECONDS", 0)
    monkeypatch.setattr(se_templates, "deciding", deciding)
    monkeypatch.setattr(se_templates, "threading", types.SimpleNamespace(Thread=Started))
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    try:
        assert gate(capsys, monkeypatch, text, "--gate", "refuse") == ""
        assert not released.is_set()  # answered while the judgement still ran
    finally:
        released.set()
        for runner in runners:
            runner.join(60)
    assert [runner.is_alive() for runner in runners] == [False]
    lines = (project / ".se" / ".runtime" / "templates-gate.log").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith("passed unjudged: slow: no answer within 0 s")


# The hook: se_hook.sh runs the gate for a guarded call only, its answer the hook's whole stdout.

HOOK = ROOT / "scripts" / "se_hook.sh"
FAKE_KERN = '#!/bin/sh\necho "$* <<$(cat)" >> "$HOME/calls"\necho \'{"kern": "answer"}\'\n'


def hooked(tmp_path: Path, text: str, **variables: str) -> subprocess.CompletedProcess:
    """The plugin's own hook line, with python3 the one Python (no uv) and kern a fake."""
    home = tmp_path / "hook-home"
    tools = home / "bin"
    tools.mkdir(parents=True, exist_ok=True)
    python = tools / "python3"
    python.write_text(f'#!/bin/sh\necho "$*" >> "$HOME/pythons"\nexec "{sys.executable}" "$@"\n',
                      encoding="utf-8", newline="\n")
    python.chmod(0o755)
    env = {"HOME": sh(home), "PATH": f"{sh(tools)}:/usr/bin:/bin", **variables}
    return subprocess.run([BASH, "-c", f'bash "{sh(HOOK)}" PreToolUse || true'], env=env,
                          input=text, capture_output=True, text=True, timeout=60)


def hook_project(tmp_path: Path, gate_value: str | None) -> Path:
    root = tmp_path / "hooked"
    (root / ".git").mkdir(parents=True)
    switch = f'[templates]\ngate = "{gate_value}"\n' if gate_value else ""
    (root / "se.toml").write_text(f'{IDENTITY}{switch}\n[outside]\n"{OWNER}/{REPO_NAME}" = 1\n',
                                  encoding="utf-8")
    kern = tmp_path / "kern"
    kern.write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern.chmod(0o755)
    (root / ".se" / ".runtime").mkdir(parents=True)
    (root / ".se" / ".runtime" / "kern.path").write_text(f"{sh(kern)}\n", encoding="utf-8")
    return root


pytest_hook = pytest.mark.skipif(BASH is None or sys.platform == "win32",
                                 reason="the hook runs in bash; its fake python3 is a shell script")


@pytest_hook
@pytest.mark.spawns("shell: scripts/se_hook.sh hands a guarded GitHub write to se_templates.py gate, prints its "
                    "deny as its whole stdout and still posts kern the payload; that wiring is bash, run only "
                    "as a process")
def test_the_plugins_hook_line_prints_exactly_the_deny(tmp_path, shared_fake_git):
    root = hook_project(tmp_path, "refuse")
    text = payload("mcp__github__issue_write", root, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    result = hooked(tmp_path, text, CLAUDE_PROJECT_DIR=sh(root))
    assert result.returncode == 0
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("}\n")
    assert "the work template refuses" in denial(result.stdout)
    calls = (tmp_path / "hook-home" / "calls").read_text(encoding="utf-8")
    assert calls.startswith(f"hook PreToolUse --root {sh(root)} <<") and SESSION in calls


@pytest_hook
@pytest.mark.spawns("shell: scripts/se_hook.sh's `guarded` test and its SE_TEMPLATES_GATE switch, bash builtins, "
                    "pick which calls run the gate; run only as a process")
def test_the_hook_runs_no_gate_for_another_call_nor_with_the_switch_off(tmp_path, shared_fake_git):
    root = hook_project(tmp_path, None)
    thin = payload("mcp__github__issue_write", root, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    result = hooked(tmp_path, thin, CLAUDE_PROJECT_DIR=sh(root))
    assert result.returncode == 0 and result.stdout == ""
    pythons = tmp_path / "hook-home" / "pythons"
    assert pythons.read_text(encoding="utf-8").count(" gate") == 1
    for text, variables in ((payload("mcp__github__get_me", root, body=THIN), {}),
                            (payload("mcp__files__issue_write", root, body=THIN), {}),
                            (thin, {"SE_TEMPLATES_GATE": "off"})):
        result = hooked(tmp_path, text, CLAUDE_PROJECT_DIR=sh(root), **variables)
        assert result.returncode == 0 and result.stdout == '{"kern": "answer"}\n'
    assert pythons.read_text(encoding="utf-8").count(" gate") == 1


# The shell reader: a gh write in a shell call is held to its template as the GitHub tools' call is.

MARKED_THIN = WORK_MARKER + "\n" + THIN


def shell_payload(command: str, cwd: Path, tool: str = "Bash", key: str = "command") -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(cwd),
                       "tool_name": tool, "tool_input": {key: command}})


# One row each of the gh writes the reader reads: the command with {file} for the body file, the
# off-template body, the template's own body and the template that refuses.
GH_ROWS = {
    "issue create": (f"gh issue create --title {TITLE} --label work --body-file {{file}}",
                     THIN, GOOD_WORK, "work"),
    "issue edit": ("gh issue edit 7 --body-file {file}", MARKED_THIN, GOOD_WORK, "work"),
    "issue comment": ("gh issue comment 7 -F {file}", THIN_REVIEW, GOOD_REVIEW, "review"),
    "pr create": ("gh pr create -B main -t 'A change' --body-file {file}", REPORTS["unfilled"],
                  REPORTS["complete"], "field-report"),
    "pr edit": ("gh pr edit 5 --base main --body-file {file}", REPORTS["unfilled"],
                REPORTS["complete"], "field-report"),
    "pr comment": ("gh pr comment 5 --body-file {file}", THIN_REVIEW, GOOD_REVIEW, "review"),
    "pr review": ("gh pr review 5 -c --body-file={file}", THIN_REVIEW, GOOD_REVIEW, "review"),
    "api issues": (f"gh api repos/{OWNER}/{REPO_NAME}/issues -f title={TITLE} -F body=@{{file}} "
                   "-f 'labels[]=work'", THIN, GOOD_WORK, "work"),
    "api issue": (f"gh api -X PATCH /repos/{OWNER}/{REPO_NAME}/issues/7 -F body=@{{file}}",
                  MARKED_THIN, GOOD_WORK, "work"),
    "api comments": (f"gh api repos/{OWNER}/{REPO_NAME}/issues/7/comments -F body=@{{file}}",
                     THIN_REVIEW, GOOD_REVIEW, "review"),
    "api comment": ("gh api --method PATCH repos/{owner}/{repo}/issues/comments/9 "
                    "-F body=@{file}", THIN_REVIEW, GOOD_REVIEW, "review"),
    "api pulls": (f"gh api repos/{OWNER}/{REPO_NAME}/pulls -f base=main -f title=x "
                  "-F body=@{file}", REPORTS["unfilled"], REPORTS["complete"], "field-report"),
    "api pull": (f"gh api -X PATCH repos/{OWNER}/{REPO_NAME}/pulls/5 -f base=main "
                 "-F body=@{file}", REPORTS["unfilled"], REPORTS["complete"], "field-report"),
}


def body_file(folder: Path, text: str, name: str = "body.md") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("row", GH_ROWS)
def test_each_gh_write_is_denied_off_template_and_passes_its_template(row, capsys, monkeypatch, project,
                                                              gh):
    command, thin, good, template = GH_ROWS[row]
    path = body_file(project, thin, "thin.md")
    reason = denial(gate(capsys, monkeypatch, shell_payload(command.replace("{file}", path.as_posix()),
                                                            project), "--gate", "refuse"))
    assert f"the {template} template refuses" in reason
    path = body_file(project, good, "good.md")
    assert gate(capsys, monkeypatch, shell_payload(command.replace("{file}", path.as_posix()), project),
                "--gate", "refuse") == ""


@pytest.mark.parametrize("command", [
    f"gh issue create --title {TITLE} --label work --body {{quoted}}",
    f"cd /tmp && env A=1 timeout -s KILL 30 nohup command gh issue create -R {OWNER}/{REPO_NAME} "
    f"-l bug,work -t {TITLE} -b {{quoted}} 2>&1 | tail -n 3",
    f"ls; /usr/local/bin/gh issue create --title={TITLE} --label=work --body-file thin.md",
    f"gh issue create --title {TITLE} -l work --body-file - < thin.md",
    f"gh issue create --title {TITLE} -l work --body-file - <<< {{quoted}}",
])
def test_a_gh_write_is_read_behind_prefixes_separators_and_quotes(command, capsys, monkeypatch,
                                                                  project, gh):
    import shlex
    body_file(project, THIN, "thin.md")
    text = command.replace("{quoted}", shlex.quote(THIN))
    assert "the work template refuses" in denial(
        gate(capsys, monkeypatch, shell_payload(text, project), "--gate", "refuse"))


def test_a_powershell_command_keeps_the_backslashes_of_a_windows_path():
    command = r"gh issue create -t x --body-file C:\Users\me\body.md; gh pr create -F 'D:\a b\r.md'"
    assert [words for words, _ in se_templates.shell_parts(command, powershell=True)] == [
        ["gh", "issue", "create", "-t", "x", "--body-file", r"C:\Users\me\body.md"],
        ["gh", "pr", "create", "-F", r"D:\a b\r.md"]]
    assert se_templates.shell_parts(command)[0][0][-1] == "C:Usersmebody.md", "bash drops them"


def test_gh_api_input_is_read_as_json_and_reads_pass(capsys, monkeypatch, project, gh):
    data = body_file(project, json.dumps({"title": TITLE, "body": THIN, "labels": ["work"]}),
                     "issue.json")
    api = f"gh api repos/{OWNER}/{REPO_NAME}/issues --input {data.as_posix()}"
    assert "the work template refuses" in denial(
        gate(capsys, monkeypatch, shell_payload(api, project), "--gate", "refuse"))
    data.write_text(json.dumps({"title": TITLE, "body": GOOD_WORK, "labels": ["work"]}),
                    encoding="utf-8")
    assert gate(capsys, monkeypatch, shell_payload(api, project), "--gate", "refuse") == ""
    for command in ("gh issue list", f"gh api repos/{OWNER}/{REPO_NAME}/issues",
                    f"gh api -X GET repos/{OWNER}/{REPO_NAME}/issues -f state=open",
                    "gh issue view 7 --json body", "gh api graphql -f query='mutation {x}'",
                    f"gh api repos/{OWNER}/{REPO_NAME}/labels -f name=x"):
        assert gate(capsys, monkeypatch, shell_payload(command, project), "--gate", "refuse") == ""


UNREADABLE = {
    "a command substitution": (f"--body \"$(cat thin.md)\"", "the shell computes it"),
    "backticks": ("--body \"`cat thin.md`\"", "the shell computes it"),
    "a variable": ("--body \"$BODY\"", "the shell computes it"),
    "a pipe": ("--body-file - ", "a pipe into --body-file -"),
    "an unquoted heredoc with $": ("--body-file - <<EOF\n## Situation\n\n$HOME\nEOF",
                                   "an unquoted heredoc"),
    "a computed path": ("--body-file \"$file\"", "its file's path"),
    "a missing file": ("--body-file later.md", "later.md does not exist before the command runs"),
    "--editor": ("--editor", "gh writes it itself (--editor)"),
    "--template": ("--template Bug", "gh writes it itself (--template)"),
}


@pytest.mark.parametrize("case", UNREADABLE)
def test_a_body_the_gate_cannot_read_is_denied_naming_body_file(case, capsys, monkeypatch, project,
                                                                gh):
    tail, why = UNREADABLE[case]
    command = f"gh issue create --title {TITLE} --label work {tail}"
    if case == "a pipe":
        command = "cat thin.md | " + command
    reason = denial(gate(capsys, monkeypatch, shell_payload(command, project), "--gate", "refuse"))
    assert reason.startswith("gh issue create: SE cannot read this body (") and why in reason
    assert reason.endswith("against the work template. Write the body to a file and pass "
                           "--body-file <file>.")


def test_gh_fill_into_the_integration_branch_is_denied_and_a_quoted_heredoc_is_read(
        capsys, monkeypatch, project, gh):
    for command in ("gh pr create --fill", "gh pr create -B main --fill-first",
                    f"gh api repos/{OWNER}/{REPO_NAME}/pulls -f title=x -f body=\"$(cat r.md)\""):
        reason = denial(gate(capsys, monkeypatch, shell_payload(command, project),
                             "--gate", "refuse"))
        assert "against the field-report template" in reason, command
    assert "-F body=@<file>" in reason
    assert gate(capsys, monkeypatch, shell_payload("gh pr create -B other --fill", project),
                "--gate", "refuse") == ""
    quoted = f"gh issue create -t {TITLE} -l work --body-file - <<'EOF'\n{{body}}EOF\necho done"
    assert "the work template refuses" in denial(gate(
        capsys, monkeypatch, shell_payload(quoted.replace("{body}", THIN), project),
        "--gate", "refuse"))
    assert gate(capsys, monkeypatch, shell_payload(quoted.replace("{body}", GOOD_WORK), project),
                "--gate", "refuse") == ""


def test_other_commands_and_writes_elsewhere_print_nothing(capsys, monkeypatch, project, gh):
    thin = body_file(project, THIN, "thin.md")
    for command in ("ls -la", "git status", "echo through high enough ",
                    f"gh issue create -R someone/elsewhere -t x -l work --body-file {thin.as_posix()}",
                    f"gh api repos/someone/elsewhere/issues -F body=@{thin.as_posix()}",
                    "echo 'unclosed"):
        assert gate(capsys, monkeypatch, shell_payload(command, project), "--gate", "refuse") == ""
    text = shell_payload(f"gh issue create -t {TITLE} -l work --body-file {thin.as_posix()}", project)
    assert gate(capsys, monkeypatch, text, "--gate", "off") == ""
    assert "work template" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
    copilot = json.dumps({"sessionId": SESSION, "cwd": str(project), "toolName": "powershell",
                          "toolArgs": json.dumps({"input": json.loads(text)["tool_input"][
                              "command"]})})
    assert "work template" in denial(gate(capsys, monkeypatch, copilot, "--gate", "refuse"))


def test_an_unreadable_comment_passes_and_logs_one_line(capsys, monkeypatch, project, gh):
    command = "gh issue comment 7 --body \"$(cat review.md)\""
    assert gate(capsys, monkeypatch, shell_payload(command, project), "--gate", "refuse") == ""
    lines = (project / ".se" / ".runtime" / "templates-gate.log").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 1 and "gh issue comment" in lines[0] and "cannot read" in lines[0]


def test_the_hold_is_read_from_the_label(capsys, monkeypatch, project, gh):
    thin = body_file(project, THIN, "thin.md")
    plain = shell_payload(f"gh issue create -t {TITLE} -l work --body-file {thin.as_posix()}", project)
    held = shell_payload(f"gh issue create -t {TITLE} -l work -l off-template --body-file {thin.as_posix()}",
                         project)
    assert "off-template" not in denial(gate(capsys, monkeypatch, plain, "--gate", "refuse"))
    assert "off-template" in denial(gate(capsys, monkeypatch, held, "--gate", "refuse"))
    assert gate(capsys, monkeypatch, held, "--gate", "refuse") == ""


@pytest_hook
@pytest.mark.spawns("shell: scripts/se_hook.sh's `shelled` test, bash builtins, finds `gh` as a word in a shell "
                    "call's command; run only as a process")
def test_the_hook_gates_a_gh_shell_call_and_no_other(tmp_path, shared_fake_git):
    root = hook_project(tmp_path, "refuse")
    thin = body_file(root, THIN, "thin.md")
    command = f"gh issue create -R {OWNER}/{REPO_NAME} -t {TITLE} -l work --body-file {thin.as_posix()}"
    result = hooked(tmp_path, shell_payload(command, root), CLAUDE_PROJECT_DIR=sh(root))
    assert result.returncode == 0 and "the work template refuses" in denial(result.stdout)
    pythons = tmp_path / "hook-home" / "pythons"
    assert pythons.read_text(encoding="utf-8").count(" gate") == 1
    for text in (shell_payload("echo through high enough ", root),
                 shell_payload("ls -la", root), shell_payload("git status", root, tool="bash"),
                 shell_payload("cat ./thigh", root, key="script")):
        result = hooked(tmp_path, text, CLAUDE_PROJECT_DIR=sh(root))
        assert result.returncode == 0 and result.stdout == '{"kern": "answer"}\n'
    assert pythons.read_text(encoding="utf-8").count(" gate") == 1


# check-files: the files a template claims (the module docstring: Claimed files).

STEP_TEMPLATE = '''---
name: step-risks
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: "Risks: what could go wrong."
applies:
  actions: ["file.write"]
  paths: ["book/*/steps/*.md"]
rules:
  required: refuse
fields:
  - name: risks
    kind: list
    required: true
---

## Risks

<!-- risks: One item per risk, or None. -->
'''
GOOD_STEP = "---\nderived_from: {template: step-risks, version: \"1.0.0\"}\n---\n\n# Risks\n\n## Risks\n\n- The scan misses a tool.\n"
EMPTY_STEP = "---\nderived_from: {template: step-risks, version: \"1.0.0\"}\n---\n\n# Risks\n\n## Risks\n\n"


def step_book(root: Path, **steps: str) -> Path:
    """`root` with templates/step-risks.md and one step file per keyword, book/m1/steps/<name>.md."""
    (root / "templates").mkdir(parents=True, exist_ok=True)
    (root / "templates" / "step-risks.md").write_text(STEP_TEMPLATE, encoding="utf-8")
    (root / "book" / "m1" / "steps").mkdir(parents=True, exist_ok=True)
    for name, text in steps.items():
        (root / "book" / "m1" / "steps" / f"{name}.md").write_text(text, encoding="utf-8")
    return root / "book" / "m1" / "steps"


def test_check_files_checks_each_claimed_file_given_and_names_path_template_and_field(capsys, tmp_path):
    steps = step_book(tmp_path, good=GOOD_STEP, empty=EMPTY_STEP)
    (tmp_path / "free.md").write_text("# Free\n", encoding="utf-8")
    given = ["--templates", str(tmp_path / "templates"), "--root", str(tmp_path)]
    assert run(capsys, "check-files", *given, str(steps / "good.md"))[:2] == (
        0, "se_templates.py check-files: 1 claimed file passes its template\n")
    assert run(capsys, "check-files", *given, str(tmp_path / "free.md"))[:2] == (
        0, "se_templates.py check-files: no template claims a file checked\n")
    code, out, _ = run(capsys, "check-files", *given, str(steps / "good.md"), str(steps / "empty.md"))
    lines = out.splitlines()
    assert code == 1
    assert lines[0].startswith("book/m1/steps/empty.md (step-risks): Risks: empty")
    assert lines[-1].startswith("The empty template of each: uv run python ")
    assert f"templates.py draft --path <file> --root {tmp_path.resolve()} --templates" in lines[-1]


def test_check_files_names_at_most_ten_lines_with_a_count_of_the_rest(capsys, tmp_path):
    step_book(tmp_path, **{f"s{number:02}": EMPTY_STEP for number in range(12)})
    files = sorted(str(path) for path in (tmp_path / "book" / "m1" / "steps").iterdir())
    code, out, _ = run(capsys, "check-files", "--root", str(tmp_path), *files)
    lines = out.splitlines()
    assert code == 1 and len(lines) == se_templates.CHECK_FILES_LINES
    assert lines[-2] == "... and 4 more findings"


def test_check_files_changed_finds_an_untracked_claimed_file_and_skips_a_deleted_one(
        capsys, tmp_path, fake_git_door):
    import fake_git
    import git_door
    steps = step_book(tmp_path, kept=GOOD_STEP, gone=GOOD_STEP)
    fake_git.init(tmp_path, "-b", "main")
    for arguments in (("config", "user.name", "alice"), ("config", "user.email", "alice@example.com"),
                      ("add", "."), ("commit", "-q", "-m", "steps"),
                      ("update-ref", "refs/remotes/origin/main", "HEAD")):
        assert git_door.run(*arguments, root=tmp_path).returncode == 0
    (steps / "gone.md").unlink()
    (steps / "kept.md").write_text(EMPTY_STEP, encoding="utf-8")
    (steps / "new.md").write_text(EMPTY_STEP, encoding="utf-8")
    code, out, _ = run(capsys, "check-files", "--changed", "origin/main", "--root", str(tmp_path))
    assert code == 1
    assert "book/m1/steps/kept.md (step-risks): Risks" in out
    assert "book/m1/steps/new.md (step-risks): Risks" in out
    assert "gone.md" not in out
    assert run(capsys, "check-files", "--changed", "no-such-ref", "--root", str(tmp_path))[0] == 2


def test_check_files_usage_errors(capsys):
    assert run(capsys, "check-files")[0] == 2
    assert run(capsys, "check-files", "a.md", "--changed", "origin/main")[0] == 2


def test_check_files_changed_reads_no_git_where_no_template_claims_a_path(capsys, tmp_path):
    """No git checkout at all: where no template claims a path outside .se/ (SE's templates without
    work-file and the code templates that claim scripts and modules; python-component claims under
    .se/ alone), it answers before it reads one."""
    folder = tmp_path / "templates"
    folder.mkdir()
    for note in (ROOT / "templates").iterdir():
        if note.name not in ("work-file.md", "python-script.md", "python-module.md", "go-module.md"):
            (folder / note.name).write_bytes(note.read_bytes())
    assert run(capsys, "check-files", "--changed", "origin/main", "--root", str(tmp_path),
               "--templates", str(folder))[:2] == (
        0, "se_templates.py check-files: no template claims a path outside .se/; nothing checked\n")


WORK_FILE_GLOB = ".se/issues/*.md"
#: Every glob SE's own templates own: the work issue body file's and the code templates' (sorted).
SE_OWNED = [("**/go.mod", "go-module"), (".se/components/*/__init__.py", "python-component"),
            (".se/handover.md", "handover"), (WORK_FILE_GLOB, "work-file"), ("go.mod", "go-module"), ("scripts/*.py", "python-module"),
            ("scripts/*.py", "python-script")]


def test_ses_owned_paths_are_the_work_issue_body_file_and_the_code_templates_and_no_switch_turns_the_file_gate():
    """SE's own templates claim the work issue body file (work-file), the handover (handover) and,
    through its code templates,
    its scripts, its ad hoc components and every go.mod; no `files` switch is left."""
    assert templates.owned(CATALOG) == SE_OWNED
    assert se_templates.claims_a_path(CATALOG)
    assert "files" not in tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["templates"]
    assert not hasattr(templates.Enforcement(), "files") and not hasattr(templates, "FILES_VALUES")


# The work issue body file (templates/work-file.md): only its fill writes it, and what it writes files
# as the work issue it shapes.

def test_a_direct_write_of_a_work_issue_body_file_passes_where_it_parses_and_else_names_the_finding_and_the_fill(
        capsys, monkeypatch, tmp_path):
    """The acceptance, against SE's own templates, as SE's comment of 24 Nov narrows it: the gate judges
    the file a write leaves. An Edit, a MultiEdit or a Write that leaves the body file parsing passes;
    one that leaves it broken, or a new file naming no template, is refused, naming each finding and
    `templates.py fill work-file --path <file>`."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    body = root / ".se" / "issues" / f"{TITLE}.md"
    body.parent.mkdir(parents=True)
    on_template = templates.render(CATALOG["work-file"], dict(FIELDS))
    body.write_text(on_template, encoding="utf-8")
    relative = body.relative_to(root).as_posix()

    def judged(tool: str, **given) -> str:
        return gate(capsys, monkeypatch, file_payload(tool, root, **given), "--templates", str(ROOT / "templates"),
                    "--root", str(root))

    passing = [
        judged("Edit", file_path=str(body), old_string=FIELDS["goal"], new_string="Every title reads plainly."),
        judged("MultiEdit", file_path=str(body), edits=[{"old_string": FIELDS["situation"], "new_string": "Titles."},
                                                         {"old_string": "plain title", "new_string": "title"}]),
        judged("Write", file_path=str(body), content=on_template),
        judged("Edit", file_path=str(body), old_string="not in the file", new_string="x"),
    ]
    assert passing == ["", "", "", ""]
    fill = (f"  {relative}: its fill: uv run python {ROOT / 'scripts' / 'templates.py'} fill work-file "
            f"--path {body} --root {root} --templates {(ROOT / 'templates').resolve()}")
    broken = denial(judged("Edit", file_path=str(body), old_string="## Requirements", new_string="## Wishes"))
    assert broken.splitlines() == [
        f"Edit of {relative}: the file it leaves breaks the template that claims its path:",
        f"  {relative} (work-file): Requirements: missing: write `## Requirements`: Numbered requirements "
        "in the order to do them, each one checkable statement (the requirement template); the Acceptance "
        "section carries how each is checked. (or `Not in input` where the input does not say) "
        f"(why: {templates.REASONS['required']})",
        fill,
        "Fix the write so the file parses, or fill it: without --fields the fill answers the template's "
        "instructions; with --fields and --input it writes the file"]
    emptied = denial(judged("MultiEdit", file_path=str(body), edits=[
        {"old_string": FIELDS["goal"], "new_string": ""}, {"old_string": FIELDS["problem"], "new_string": ""}]))
    assert f"  {relative} (work-file): Goal: " in emptied and f"  {relative} (work-file): Problem: " in emptied
    fresh = body.parent / "new-package.md"
    named = denial(judged("Write", file_path=str(fresh), content="## Goal\n\nx\n"))
    assert ".se/issues/new-package.md (no template): body: .se/issues/new-package.md: no template takes this " \
           "file; name its template in the front matter" in named
    assert f"fill work-file --path {fresh} --root {root}" in named
    assert body.read_text(encoding="utf-8") == on_template and not fresh.exists()


def test_a_fill_and_templates_write_pass_the_gate_and_the_fills_file_files_as_its_work_issue(
        capsys, monkeypatch, tmp_path):
    """Requirement 3: the fill's shell call and the door's templates_write reach no deny; the file the
    fill writes holds its template in the front matter and files, through `work`, as the work issue."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    body = root / ".se" / "issues" / f"{TITLE}.md"
    fill = ["fill", "work-file", "--path", str(body), "--root", str(root), "--templates", str(ROOT / "templates"),
            "--input-text", FIELDS["user_requirement"], "--fields-json", json.dumps(FIELDS)]
    passing = [
        json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(root),
                    "tool_name": "Bash", "tool_input": {"command": " ".join(
                        ["uv", "run", "python", str(ROOT / "scripts" / "templates.py"), *fill[:5]])}}),
        json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(root),
                    "tool_name": "mcp__plugin_se_se__templates_write",
                    "tool_input": {"action": "fill", "args": ["work", "--repo", f"{OWNER}/{REPO_NAME}"]}}),
    ]
    for text in passing:
        assert gate(capsys, monkeypatch, text, "--gate", "refuse", "--templates", str(ROOT / "templates"),
                    "--root", str(root)) == ""
    monkeypatch.chdir(root)
    assert templates.main(fill) == 0
    assert capsys.readouterr().out == f"wrote .se/issues/{TITLE}.md: work-file 1.0.0\n"
    written = body.read_text(encoding="utf-8")
    assert templates.front_matter_template(written) == "work-file"
    filed = templates.filled(WORK, body=written, enforce=templates.REFUSE)
    assert filed == templates.render(WORK, dict(FIELDS)) and "template: se/work-file" not in filed
    assert not [found for found in templates.check(WORK, templates.parse(WORK, filed, TITLE))
                if found.severity == templates.REFUSE]


def test_se_tomls_own_gate_on_its_integration_branch_decides_the_gate(capsys, monkeypatch, tmp_path):
    """SE's own se.toml, read from this checkout, at the fixture's `origin/main`: the gate the hook runs
    (test_the_plugins_hook_line_prints_exactly_the_deny holds the hook's hand-off) denies an
    off-template `issue_write` naming Problem and passes the template's own body. The working tree's copy
    lacks the gate, so the integration branch's decides."""
    import fake_git

    own = (ROOT / "se.toml").read_text(encoding="utf-8")
    root = hook_project(tmp_path, None)
    fake_git.init(root)
    fake_git.git("-C", str(root), "remote", "add", "origin",
                 f"https://git.example/{OWNER}/{REPO_NAME}.git")
    (root / "se.toml").write_text(own, encoding="utf-8")
    fake_git.git("-C", str(root), "add", "se.toml")
    fake_git.git("-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "-m", "SE's se.toml")
    fake_git.git("-C", str(root), "update-ref", "refs/remotes/origin/main", "HEAD")
    (root / "se.toml").write_text(own.replace('gate = "refuse"', ""), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    given = {"method": "create", "title": TITLE, "labels": ["work"]}
    assert "Problem" in denial(gate(capsys, monkeypatch, payload("mcp__github__issue_write", root, body=THIN,
                                                                 **given)))
    assert gate(capsys, monkeypatch, payload("mcp__github__issue_write", root, body=GOOD_WORK, **given)) == ""


# The file tools: wherever a template claims a path, the gate denies every write of it but the fill's.

def file_payload(tool: str, cwd: Path, **given) -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(cwd),
                       "tool_name": tool, "tool_input": given})


def file_gate(capsys, monkeypatch, root: Path, text: str) -> str:
    return gate(capsys, monkeypatch, text, "--gate", "refuse", "--templates", str(root / "templates"),
                "--root", str(root))


def test_a_write_of_a_claimed_path_is_judged_by_the_file_it_leaves_never_by_the_edit_text(
        capsys, monkeypatch, tmp_path):
    """SE's comment of 24 Nov: Write's content, the file with an Edit's or a MultiEdit's replacements
    applied, parsed as its template; a result that parses passes, one that does not is denied naming
    each finding and the fill. A call the tool itself would refuse writes nothing and passes."""
    steps = step_book(tmp_path, step=GOOD_STEP)
    step = steps / "step.md"
    passing = {
        "Write": {"file_path": str(step), "content": GOOD_STEP},
        "Edit": {"file_path": str(step), "old_string": "misses a tool", "new_string": "misses two"},
        "Edit missing": {"file_path": str(step), "old_string": "not there", "new_string": ""},
        "Edit no file": {"file_path": str(steps / "none.md"), "old_string": "a", "new_string": "b"},
        "MultiEdit": {"file_path": str(step), "edits": [{"old_string": "scan", "new_string": "search"},
                                                        {"old_string": "tool", "new_string": "file"}]},
        "Write new": {"file_path": str(steps / "new.md"), "content": GOOD_STEP},
    }
    for name, given in passing.items():
        assert file_gate(capsys, monkeypatch, tmp_path, file_payload(name.split()[0], tmp_path, **given)) == "", name
    denied = {
        "Write": {"file_path": str(step), "content": EMPTY_STEP},
        "Edit": {"file_path": str(step), "old_string": "- The scan misses a tool.\n", "new_string": ""},
        "MultiEdit": {"file_path": str(step), "edits": [{"old_string": "scan", "new_string": "search"},
                                                        {"old_string": "## Risks\n\n- The search", "new_string": "## Gone\n\n- The"}]},
        "Write new": {"file_path": str(steps / "new.md"), "content": EMPTY_STEP},
        "Edit all": {"file_path": str(step), "old_string": "Risks", "new_string": "Gone", "replace_all": True},
    }
    for name, given in denied.items():
        tool = name.split()[0]
        reason = denial(file_gate(capsys, monkeypatch, tmp_path, file_payload(tool, tmp_path, **given)))
        relative = Path(given["file_path"]).relative_to(tmp_path).as_posix()
        assert reason.startswith(f"{tool} of {relative}: the file it leaves breaks the template that claims "
                                 "its path:"), name
        assert f"  {relative} (step-risks): Risks: " in reason, name
        assert (f"  {relative}: its fill: uv run python {ROOT / 'scripts' / 'templates.py'} fill step-risks "
                f"--path {tmp_path / relative} --root {tmp_path} --templates {(tmp_path / 'templates').resolve()}"
                ) in reason, name
    free = [
        file_payload("Write", tmp_path, file_path=str(tmp_path / "notes.md"), content="# Notes\n"),
        file_payload("Edit", tmp_path, file_path=str(tmp_path / "notes.md"), old_string="a",
                     new_string="b"),
        file_payload("Write", tmp_path, file_path=str(tmp_path.parent / "elsewhere.md"),
                     content=EMPTY_STEP),
        file_payload("Write", tmp_path, content=EMPTY_STEP),
        file_payload("Read", tmp_path, file_path=str(step)),
    ]
    for text in free:
        assert file_gate(capsys, monkeypatch, tmp_path, text) == ""
    assert step.read_text(encoding="utf-8") == GOOD_STEP
    assert not (steps / "new.md").exists()


def test_a_github_file_write_names_each_claimed_file_that_breaks_its_template_and_passes_else(
        capsys, monkeypatch, tmp_path, home_repo):
    step_book(tmp_path)
    files = [{"path": "book/m1/steps/s1.md", "content": GOOD_STEP},
             {"path": "book/m1/steps/s2.md", "content": EMPTY_STEP},
             {"path": "notes.md", "content": "# Notes\n"}]
    text = json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(tmp_path),
                       "tool_name": "mcp__github__push_files",
                       "tool_input": {"owner": OWNER, "repo": REPO_NAME, "branch": "b",
                                      "files": files, "message": "m"}})
    reason = denial(file_gate(capsys, monkeypatch, tmp_path, text))
    assert reason.startswith(f"push_files in {OWNER}/{REPO_NAME}: the file it leaves breaks the template")
    assert "  book/m1/steps/s2.md (step-risks): Risks: " in reason
    assert "s1.md" not in reason and "notes.md" not in reason
    one = {"owner": OWNER, "repo": REPO_NAME, "branch": "b", "message": "m",
           "path": "book/m1/steps/s1.md", "content": GOOD_STEP}
    single = json.dumps({"hook_event_name": "PreToolUse", "session_id": SESSION, "cwd": str(tmp_path),
                         "tool_name": "mcp__github__create_or_update_file", "tool_input": one})
    assert file_gate(capsys, monkeypatch, tmp_path, single) == ""
    broken = single.replace(json.dumps(GOOD_STEP), json.dumps(EMPTY_STEP))
    assert "s1.md (step-risks): Risks: " in denial(file_gate(capsys, monkeypatch, tmp_path, broken))
    free = broken.replace("book/m1/steps/s1.md", "notes.md")
    assert file_gate(capsys, monkeypatch, tmp_path, free) == ""


def test_a_file_gate_crash_after_the_claim_denies_and_one_before_passes_and_logs(
        capsys, monkeypatch, tmp_path):
    steps = step_book(tmp_path, step=GOOD_STEP)
    (tmp_path / ".git").mkdir()
    text = file_payload("Write", tmp_path, file_path=str(steps / "step.md"), content=EMPTY_STEP)

    def broken(*_):
        raise RuntimeError("the disk is gone")

    with monkeypatch.context() as patch:
        patch.setattr(se_templates, "judged_write", broken)
        reason = denial(file_gate(capsys, monkeypatch, tmp_path, text))
    assert reason.startswith("SE's template gate failed on this write (RuntimeError)")
    assert "templates.py fill <template> --path <file>" in reason and "SE_TEMPLATES_GATE=off" in reason
    with monkeypatch.context() as patch:
        patch.setattr(se_templates, "claim_templates", broken)
        assert file_gate(capsys, monkeypatch, tmp_path, text) == ""
    log = (tmp_path / ".se" / ".runtime" / "templates-gate.log").read_text(encoding="utf-8")
    assert "RuntimeError: the disk is gone" in log and "Risks" not in log


def test_the_file_gate_needs_no_se_toml_switch_and_counts_its_refusals(capsys, monkeypatch, tmp_path):
    """Requirement 2: no se.toml at all, and one whose old `files` says off, deny alike."""
    steps = step_book(tmp_path, step=GOOD_STEP)
    (tmp_path / ".git").mkdir()
    text = file_payload("Write", tmp_path, file_path=str(steps / "step.md"), content=EMPTY_STEP)
    plain = ("--gate", "refuse", "--templates", str(tmp_path / "templates"))
    assert "(step-risks)" in denial(gate(capsys, monkeypatch, text, *plain))
    (tmp_path / "se.toml").write_text('[templates]\nfiles = "off"\n', encoding="utf-8")
    assert "(step-risks)" in denial(gate(capsys, monkeypatch, text, *plain))
    monkeypatch.setenv("SE_TEMPLATES_GATE", "off")
    assert gate(capsys, monkeypatch, text, *plain) == ""
    monkeypatch.delenv("SE_TEMPLATES_GATE")
    key = templates.target("step-risks", str(tmp_path), templates.FILE_ACTION, title="book/m1/steps/step.md")
    assert templates.refusals(key, {"SE_SESSION": SESSION}) == 2


def test_the_starts_runtime_line_is_written_only_where_a_template_claims_a_path(capsys, monkeypatch, tmp_path):
    """The start publishes the owned globs after the line claimed: SE's own, the work issue body
    file's and the code templates', for a project without templates of its own; the project's where
    it has them; none and no file where nothing is claimed."""
    line = tmp_path / ".se" / ".runtime" / "templates-files"
    assert se_templates.main(["gate", "--runtime", str(tmp_path)]) == 0
    assert line.read_text(encoding="utf-8") == "".join(
        f"{text}\n" for text in (se_templates.FILES_CLAIMED, *sorted({glob for glob, _ in SE_OWNED})))
    step_book(tmp_path)
    (tmp_path / "se.toml").write_text('[templates]\nfiles = "off"\n', encoding="utf-8")
    assert se_templates.main(["gate", "--runtime", str(tmp_path)]) == 0
    owned = sorted({glob for glob, _ in templates.owned(templates.load(tmp_path))})
    assert "book/*/steps/*.md" in owned
    assert line.read_text(encoding="utf-8") == "".join(f"{text}\n" for text in (se_templates.FILES_CLAIMED,
                                                                                *owned))
    monkeypatch.setattr(templates, "owned", lambda catalog: [])
    assert se_templates.main(["gate", "--runtime", str(tmp_path)]) == 0 and not line.exists()
    assert capsys.readouterr().out == ""


@pytest_hook
@pytest.mark.spawns("shell: scripts/se_hook.sh's `filed` test, bash builtins, sends a Write of a project file to "
                    "the gate only where templates-files says claimed, and the fill's shell call past it; run "
                    "only as a process")
def test_the_hook_denies_a_write_that_breaks_a_claimed_file_and_lets_its_fill_write_it(
        capsys, monkeypatch, tmp_path, shared_fake_git):
    """Through SE's hook as the plugin runs it, a Write that leaves a claimed file off its template is
    denied naming the fill, and the fill of the same path passes the hook and writes it on template."""
    root = hook_project(tmp_path, None)
    steps = step_book(root)
    step = steps / "s1.md"
    assert se_templates.main(["gate", "--runtime", str(root)]) == 0
    write = file_payload("Write", root, file_path=str(step), content=EMPTY_STEP)
    result = hooked(tmp_path, write, CLAUDE_PROJECT_DIR=sh(root))
    reason = denial(result.stdout)
    assert result.returncode == 0 and reason.startswith(
        "Write of book/m1/steps/s1.md: the file it leaves breaks the template that claims its path:")
    assert "  book/m1/steps/s1.md (step-risks): Risks: " in reason
    assert f"  book/m1/steps/s1.md: its fill: uv run python " in reason
    assert f"templates.py fill step-risks --path {step} --root {root}" in reason
    assert not step.exists()
    fill = ["fill", "step-risks", "--path", str(step), "--root", str(root), "--templates", str(root / "templates"),
            "--input-text", "The scan misses a tool.", "--fields-json",
            json.dumps({"risks": ["The scan misses a tool."]})]
    command = shell_payload(shlex.join([sys.executable, str(ROOT / "scripts" / "templates.py"), *fill]), root)
    result = hooked(tmp_path, command, CLAUDE_PROJECT_DIR=sh(root))
    assert result.returncode == 0 and result.stdout == '{"kern": "answer"}\n'
    capsys.readouterr()
    monkeypatch.chdir(root)  # the fill as the shell call runs it, in-process
    code = templates.main(fill)
    filled = capsys.readouterr()
    assert code == 0, filled.out + filled.err
    assert filled.out == "wrote book/m1/steps/s1.md: step-risks 1.0.0\n"
    assert run_check_files(capsys, step, root) == "se_templates.py check-files: 1 claimed file passes its template"


def run_check_files(capsys, path: Path, root: Path) -> str:
    se_templates.main(["check-files", "--templates", str(root / "templates"), "--root", str(root), str(path)])
    return capsys.readouterr().out.strip()


# The backstop (se_templates.py backstop, .github/workflows/templates.yml): an event file in, a plan out.

def event_file(folder: Path, name: str, *, action: str = "opened", body: str = THIN,
               title: str = TITLE, labels=("work",), comment: str | None = None) -> Path:
    """An issues or issue_comment event as GitHub writes it to $GITHUB_EVENT_PATH."""
    data = {"action": action, "repository": {"full_name": f"{OWNER}/{REPO_NAME}"},
            "issue": {"number": 7, "title": title, "body": body,
                      "labels": [{"name": label} for label in labels]}}
    if comment is not None:
        data["comment"] = {"id": 9, "body": comment}
    path = folder / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def backstop(capsys, project: Path, name: str, event: Path, *switch: str) -> dict:
    code, out, _ = run(capsys, "backstop", "--event-name", name, "--event", str(event),
                       "--worktree", str(project), *switch)
    assert code == 0, out
    plan = json.loads(out)
    assert {"repo", "number", "add_labels", "summary", "failed"} <= set(plan)
    return plan


def test_backstop_labels_an_off_template_fleet_issue_and_leaves_the_rest_alone(
        capsys, tmp_path, project, gh):
    plan = backstop(capsys, project, "issues", event_file(tmp_path, "thin"), "--backstop", "on")
    assert plan["add_labels"] == ["off-template"] and plan["failed"] is False
    assert plan["repo"] == f"{OWNER}/{REPO_NAME}" and plan["number"] == 7
    lines = plan["summary"].splitlines()
    assert "issue #7 in owner/repo" in lines[0] and any("Problem: missing" in line
                                                        for line in lines)
    assert len(lines) <= templates.REFUSAL_LINES + 1
    assert lines[-1] == "Fix its title or body on the issue itself, then run work_tickets.py " \
                        "unhold 7"
    marked = event_file(tmp_path, "marked", body=THIN, labels=(), action="edited")
    assert backstop(capsys, project, "issues", marked, "--backstop", "on")["add_labels"] == [
        "off-template"]
    held = event_file(tmp_path, "held", labels=("work", "off-template"), action="labeled")
    plan = backstop(capsys, project, "issues", held, "--backstop", "on")
    assert plan["add_labels"] == [] and "Problem: missing" in plan["summary"]
    empty = {"repo": f"{OWNER}/{REPO_NAME}", "number": 7, "add_labels": [], "summary": "",
             "failed": False}
    for event, switch in (
            (event_file(tmp_path, "good", body=GOOD_WORK), "on"),
            (event_file(tmp_path, "outside", body="The page breaks on my phone.\n", labels=()),
             "on"),
            (event_file(tmp_path, "closed", action="closed"), "on"),
            (event_file(tmp_path, "thin"), "off")):
        assert backstop(capsys, project, "issues", event, "--backstop", switch) == empty, event


def test_reopening_renews_inputs_but_an_edit_keeps_the_existing_acceptance(
        capsys, tmp_path, project, gh, monkeypatch):
    body = templates.render(WORK, FIELDS)
    latest = replace(WORK, version="99.0.0", fields=(*WORK.fields, templates.Field(
        name="later", kind="text", heading="Added later", required=True)))
    monkeypatch.setattr(templates, "load", lambda *args, **kwargs: {**CATALOG, "work": latest})
    edited = event_file(tmp_path, "edit", body=body, action="edited")
    assert backstop(capsys, project, "issues", edited, "--backstop", "on")["add_labels"] == []
    reopened = event_file(tmp_path, "reopen", body=body, action="reopened")
    plan = backstop(capsys, project, "issues", reopened, "--backstop", "on")
    assert plan["renew_template"] == "work"
    assert plan["add_labels"] == ["off-template"]
    assert "Added later" in plan["summary"]


def test_backstop_names_a_private_term_by_field_and_list_only(capsys, tmp_path, project, gh):
    body = templates.render(WORK, {**FIELDS, "goal": "For Quuxcorp."})
    plan = backstop(capsys, project, "issues", event_file(tmp_path, "private", body=body),
                    "--backstop", "on")
    assert plan["add_labels"] == ["off-template"]
    assert "local list" in plan["summary"] and "quux" not in plan["summary"].lower()


def test_backstop_fails_the_run_for_an_off_template_marked_comment_and_labels_nothing(
        capsys, tmp_path, project, gh):
    def comment(name: str, text: str, action: str = "created") -> dict:
        event = event_file(tmp_path, name, body=GOOD_WORK, action=action, comment=text)
        return backstop(capsys, project, "issue_comment", event, "--backstop", "on")

    plan = comment("thin-review", THIN_REVIEW, "edited")
    assert plan["failed"] is True and plan["add_labels"] == []
    assert "the review template refuses" in plan["summary"] and "unhold" not in plan["summary"]
    for name, text in (("good-review", GOOD_REVIEW), ("unmarked", "Thanks, looks fine.")):
        plan = comment(name, text)
        assert plan["failed"] is False and plan["add_labels"] == [] and not plan["summary"]


def test_backstop_reads_its_switch_from_the_checkouts_se_toml(capsys, tmp_path, project, gh):
    thin = event_file(tmp_path, "thin")
    assert backstop(capsys, project, "issues", thin)["add_labels"] == []
    (project / "se.toml").write_text(f'{IDENTITY}\n[templates]\nbackstop = "on"\n', encoding="utf-8")
    assert backstop(capsys, project, "issues", thin)["add_labels"] == ["off-template"]
    (project / "se.toml").write_text(f'{IDENTITY}\n[templates]\nbackstop = "maybe"\n',
                                     encoding="utf-8")
    code, out, _ = run(capsys, "backstop", "--event-name", "issues", "--event", str(thin),
                       "--worktree", str(project))
    assert code == 2 and "[templates] backstop = 'maybe'" in out and str(project / "se.toml") in out
    (tmp_path / "broken.json").write_text("[1]", encoding="utf-8")
    code, out, _ = run(capsys, "backstop", "--event-name", "issues", "--event",
                       str(tmp_path / "broken.json"), "--worktree", str(project))
    assert code == 2 and "no JSON object" in out


# fill, the templates tool's action: the engine's fill with SE's checks, answering and writing nothing

RAW = "The person asked for one fill command that checks, renders and files."


@pytest.mark.parametrize("case", CASES)
def test_fill_refuses_exactly_where_check_refuses(case, capsys, worktree, gh, templates_home):
    (worktree / "se.toml").write_text(f'{IDENTITY}\n[templates]\nenforce = "refuse"\n',
                                      encoding="utf-8")
    (worktree / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    title, fields, says = CASES[case]
    given = ["--title", title, "--fields-json", json.dumps(fields), "--worktree", str(worktree), "--tree"]
    before = sorted(path.name for path in worktree.iterdir())
    _, checked, _ = run(capsys, "check", "work", *given)
    code, filled, _ = run(capsys, "fill", "work", "--prompt", "File it.", "--input-text", RAW, *given)
    assert code == 0 and filled.splitlines()[0] == checked.splitlines()[0]
    assert sorted(path.name for path in worktree.iterdir()) == before
    if says is None:
        assert filled == "passes\n" + templates.render(WORK, {**FIELDS, "title": title})
    else:
        assert says in filled and "quux" not in filled.lower()
        assert filled.splitlines()[-1].endswith(f"{Path(se_templates.__file__).resolve()} fill work")


def test_fill_without_fields_answers_the_instructions_first(capsys, worktree):
    code, out, _ = run(capsys, "fill", "work", "--prompt", "File it.", "--worktree", str(worktree),
                       "--tree")
    answer = json.loads(drafted_template(out))
    expected = templates.instructions(WORK, "File it.", worktree.resolve())
    # The guidance's text comes before the template, so the instructions name its notes alone.
    expected["guidance"] = [{"name": note["name"], "path": note["path"]} for note in expected["guidance"]]
    assert code == 0 and answer == expected
    assert list(answer)[:5] == ["template", "prompt", "says", "rules", "guidance"]


def test_fill_refuses_an_invented_quote_against_the_raw_input(capsys, tmp_path, worktree, gh,
                                                            templates_home):
    import test_templates
    template = test_templates.quote_template(tmp_path)
    fields = {"seen": '"The export crashes the server"', "impact": ["Exports are incomplete."]}
    given = ["finding", "--templates", str(tmp_path / "templates"), "--worktree", str(worktree)]
    code, out, _ = run(capsys, "fill", *given, "--input-text", test_templates.RAW,
                       "--fields-json", json.dumps(fields))
    assert code == 0 and out.splitlines()[0] == "refused: 1 findings"
    assert '"The export crashes the server", which the raw input does not hold' in out
    fields["seen"] = '"The export stops at row 1000"'
    code, out, _ = run(capsys, "fill", *given, "--input-text", test_templates.RAW,
                       "--fields-json", json.dumps(fields))
    assert code == 0 and out == "passes\n" + templates.render(template, fields)


@pytest.mark.parametrize("arguments, error", [
    (["fill", "work", "--fields-json", "{}"], "give the raw input"),
    (["fill", "nope", "--input-text", "x", "--fields-json", "{}"], "no template 'nope'"),
])
def test_fill_usage_errors_exit_2(capsys, arguments, error):
    code, out, _ = run(capsys, *arguments, "--tree")
    assert code == 2 and error in out


def test_fill_is_a_writing_command_of_the_templates_component_with_its_request_ports():
    """The door serves fill in the tool templates_write: it writes only through the request ports
    fill-template, which the wiring binds to the template component's fill, and file-issue and
    file-comment, bound to the GitHub component's write verbs, whose port template-accept the
    wiring binds to the template component's accept."""
    assert "fill" in se_templates.WRITING_COMMANDS and "fill" not in se_templates.READ_ONLY_COMMANDS
    assert "fill" in se_templates.INTERACTIVE_COMMANDS and "fill" in se_templates.COMPONENTS[0].commands
    declared = tomllib.loads((ROOT / "components" / "templates" / "component.toml").read_text(
        encoding="utf-8"))
    assert declared["commands"]["se_templates.py fill"]["writes"] is True
    assert {port: request["type"] for port, request in declared["requests"].items()} == {
        "fill-template": "template.fill", "file-issue": "github.issue-create",
        "file-comment": "github.issue-comment"}
    wires = tomllib.loads((ROOT / "wiring.toml").read_text(encoding="utf-8"))["wires"]
    assert wires["templates.fill-template"] == "template.fill"
    assert wires["templates.file-issue"] == "github.issue-create"
    assert wires["templates.file-comment"] == "github.issue-comment"
    assert wires["github.template-accept"] == "template.accept"


# Filing through kern (docs/templates.md "Fill"): a fill with --repo files the document it checked
# through kern's GitHub component, answered here from the component's own expectations.

KERN_TEMPLATES = ROOT / "components" / "templates"
#: The raw input the work example's fields come from.
WORK_RAW = "\n".join(str(value) for value in FIELDS.values())


def filing_fake():
    """The templates component, its requests answered from its own expectation file
    (components/templates/expect.toml), as kern's fake answers a reader's tests."""
    import se_components

    se_components.sdk()
    from kern.fake import expecting

    return expecting(se_components.attach("templates", "se_templates", KERN_TEMPLATES),
                     KERN_TEMPLATES / "expect.toml")


def made_by_fill() -> dict:
    """The filled template the template component's fill answers in the expectations."""
    expectations = tomllib.loads((KERN_TEMPLATES / "expect.toml").read_text(encoding="utf-8"))["expect"]
    return next(item["answer"] for item in expectations if item["request"] == "fill-template")


def checkout(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_a_fill_of_the_work_template_files_an_issue_through_kern_s_github_component(tmp_path):
    """Acceptance: the work fill passes SE's checks, then asks the request port fill-template,
    the template component's fill, for the filled template of its fields and raw input, and hands
    that value to file-issue, the GitHub component's verb issue-create, never a body or fields;
    the answer links the issue."""
    import se_components

    root = checkout(tmp_path)
    fake = filing_fake()
    out = fake.run("se_templates.py fill", se_components.CWD + str(root), "work", "--tree",
                   "--worktree", str(root), "--repo", "alice/demo", "--label", "work",
                   "--input-text", WORK_RAW, "--fields-json", json.dumps(FIELDS))
    assert out == "passes\nfiled alice/demo#21: https://github.com/alice/demo/issues/21"
    fill, asked = fake.requests
    assert fill.port == "fill-template"
    assert fill.value == {"template": "work", "fields": FIELDS, "raw": WORK_RAW, "title": TITLE}
    assert asked.port == "file-issue"
    assert asked.value == {"owner": "alice", "repo": "demo", "labels": ["work"],
                           "filled": made_by_fill()}
    assert not {"body", "title", "template", "fields"} & set(asked.value)


def test_a_fill_the_checks_refuse_files_nothing(tmp_path):
    import se_components

    root = checkout(tmp_path)
    fake = filing_fake()
    fields = {**FIELDS, "requirements": []}
    out = fake.run("se_templates.py fill", se_components.CWD + str(root), "work", "--tree",
                   "--worktree", str(root), "--repo", "alice/demo",
                   "--input-text", WORK_RAW, "--fields-json", json.dumps(fields))
    assert out.splitlines()[0] == "refused: 1 findings" and "requirements" in out
    assert fake.requests == []


def test_a_comment_template_s_fill_comments_through_kern_after_its_quote_check(tmp_path):
    """--number files a comment through file-comment; the raw-input rule quote still refuses an
    invented quote first, and then nothing is posted."""
    import se_components
    import test_templates

    root = checkout(tmp_path)
    test_templates.write_template(root, "work", test_templates.QUOTE_TEMPLATE.format(name="work").replace(
        'actions: ["file.write"]\n  paths: ["findings/*.md"]', 'actions: ["comment.create"]'))
    where = [se_components.CWD + str(root), "work", "--templates", str(root / "templates"),
             "--worktree", str(root), "--repo", "alice/demo", "--number", "7",
             "--input-text", test_templates.RAW]
    fake = filing_fake()
    invented = {**test_templates.FILLED, "seen": '"The export crashes the server"'}
    out = fake.run("se_templates.py fill", *where, "--fields-json", json.dumps(invented))
    assert out.splitlines()[0] == "refused: 1 findings" and fake.requests == []
    out = fake.run("se_templates.py fill", *where, "--fields-json", json.dumps(test_templates.FILLED))
    assert out == "passes\ncommented on alice/demo#7: https://github.com/alice/demo/issues/7#issuecomment-99"
    fill, asked = fake.requests
    assert fill.port == "fill-template" and fill.value["fields"] == test_templates.FILLED
    assert asked.port == "file-comment" and asked.value["number"] == 7
    assert asked.value["filled"] == made_by_fill() and "fields" not in asked.value


def test_a_fill_run_directly_files_nothing_and_names_kern(capsys, tmp_path):
    root = checkout(tmp_path)
    code, out, _ = run(capsys, "fill", "work", "--tree", "--worktree", str(root), "--repo",
                       "alice/demo", "--input-text", WORK_RAW, "--fields-json", json.dumps(FIELDS))
    assert code == 2 and "nothing was filed" in out and "kern" in out


@pytest.mark.parametrize("arguments, error", [
    (["--repo", "alice"], "--repo is OWNER/REPO"),
    (["--number", "7"], "give --repo OWNER/REPO"),
    (["--repo", "alice/demo", "--number", "7"], "work serves issue.create, issue.edit, not comment.create"),
    (["--repo", "alice/demo", "--number", "7", "--label", "x"], "a comment carries no label"),
])
def test_filing_usage_errors_exit_2(capsys, arguments, error):
    code, out, _ = run(capsys, "fill", "work", "--tree", "--input-text", WORK_RAW,
                       "--fields-json", json.dumps(FIELDS), *arguments)
    assert code == 2 and error in out, out


def test_a_template_that_makes_no_whole_issue_is_not_filed(capsys):
    code, out, _ = run(capsys, "fill", "review", "--tree", "--repo", "alice/demo", "--number", "7",
                       "--input-text", "x", "--fields-json", "{}")
    assert code == 2 and "kern cannot file review: review is an adapter template" in out, out
    code, out, _ = run(capsys, "fill", "decision", "--tree", "--repo", "alice/demo",
                       "--input-text", "x", "--fields-json", "{}")
    assert code == 2 and out.strip().endswith("decision serves deck.build, not issue.create"), out


def test_the_engine_s_fill_with_repo_is_the_tool_s_fill(monkeypatch):
    """templates.py fill --repo hands its call to se_templates.py fill, the one place that files."""
    handed = []
    monkeypatch.setattr(se_templates, "main", lambda argv: handed.append(argv) or 0)
    assert templates.main(["fill", "work", "--tree", "--repo", "alice/demo", "--label", "work",
                           "--input-text", "raw", "--fields-json", "{}"]) == 0
    assert handed == [["fill", "work", "--repo", "alice/demo", "--label", "work", "--input-text",
                       "raw", "--fields-json", "{}", "--tree"]]


# Merges (se_templates.py's docstring, Merges): every merge into the integration branch states its
# release kind, the merge call without a message judged as the description GitHub takes.

UNKINDED = "Integrate fix/retro-doc-size-exemption: retro reports are exempt from the size cap.\n"
KINDED_REPORT = "<!-- se:field-report -->\n**Release kind:** patch — a fix\n<!-- se:field-report:end -->\n"
KIND_LINE = "Release-kind: major|minor|patch"


@pytest.fixture
def pull(gh):
    """Pull request #5 into main as GitHub holds it; a test sets its description."""
    def held(body: str, base: str = "main", title: str = "Integrate feat/x: a change") -> None:
        gh.documents["pulls/5"] = {"number": 5, "title": title, "body": body, "base": {"ref": base}}
    return held


def merge_payload(project: Path, **given) -> str:
    return payload("mcp__github__merge_pull_request", project, pullNumber=5, merge_method="squash",
                   **given)


def test_a_merge_without_a_message_is_judged_by_the_description_github_takes(capsys, monkeypatch,
                                                                             project, gh, pull):
    pull(UNKINDED)
    reason = denial(gate(capsys, monkeypatch, merge_payload(project), "--gate", "refuse"))
    assert "the merge-message template refuses" in reason and f"pr.merge in {OWNER}/{REPO_NAME}" in reason
    assert "it states no kind" in reason and f"end with one trailer {KIND_LINE}" in reason
    assert ["api", f"repos/{OWNER}/{REPO_NAME}/pulls/5"] in gh.calls
    pull(KINDED_REPORT)  # a field report stating its kind: its own marker is no finding
    assert gate(capsys, monkeypatch, merge_payload(project), "--gate", "refuse") == ""


def test_a_merge_with_a_message_is_judged_by_it_and_one_elsewhere_is_free(capsys, monkeypatch,
                                                                          project, gh, pull):
    pull(UNKINDED)
    given = {"commit_title": "Integrate feat/x: a change", "commit_message": "Release-kind: minor"}
    assert gate(capsys, monkeypatch, merge_payload(project, **given), "--gate", "refuse") == ""
    given["commit_message"] = "Squashed."
    assert "it states no kind" in denial(gate(capsys, monkeypatch, merge_payload(project, **given),
                                              "--gate", "refuse"))
    pull(UNKINDED, base="next")
    assert gate(capsys, monkeypatch, merge_payload(project), "--gate", "refuse") == ""


def test_a_merge_whose_pull_request_cannot_be_read_is_refused_without_a_message(capsys, monkeypatch,
                                                                                project, gh):
    reason = denial(gate(capsys, monkeypatch, merge_payload(project), "--gate", "refuse"))
    assert "it states no kind" in reason and KIND_LINE in reason
    log = (project / se_templates.GATE_LOG).read_text(encoding="utf-8")
    assert "the pull request it merges cannot be read" in log


@pytest.mark.parametrize("command", [
    "gh pr merge 5 --squash",
    "gh pr merge 5 --squash --subject 'Integrate feat/x' --body-file {file}",
    f"gh api -X PUT repos/{OWNER}/{REPO_NAME}/pulls/5/merge -f commit_title='Integrate feat/x' "
    "-F commit_message=@{file}",
], ids=["gh-pr-merge-bare", "gh-pr-merge-with-body", "gh-api-merge"])
def test_a_gh_merge_is_judged_like_the_tools_merge(command, capsys, monkeypatch, project, gh, pull):
    pull(UNKINDED)
    path = body_file(project, "Squashed.\n", "thin.md")
    reason = denial(gate(capsys, monkeypatch, shell_payload(command.replace("{file}", path.as_posix()),
                                                            project), "--gate", "refuse"))
    assert "the merge-message template refuses" in reason and "it states no kind" in reason
    if "{file}" in command:
        path = body_file(project, "Release-kind: patch\n", "good.md")
        assert gate(capsys, monkeypatch, shell_payload(command.replace("{file}", path.as_posix()),
                                                       project), "--gate", "refuse") == ""


def test_the_hooks_list_of_guarded_tools_is_the_gates():
    text = HOOK.read_text(encoding="utf-8")
    listed = text[text.index("GATE_TOOLS=(") + len("GATE_TOOLS=("):]
    assert listed[:listed.index(")")].split() == list(se_templates.GATE_TOOLS)
