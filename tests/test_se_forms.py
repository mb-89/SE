"""SE's side of forms (scripts/se_forms.py), the command component `forms` kern's MCP door serves:
draft gives the engine's answer, check answers the verdict first and refuses exactly where the
filing commands refuse, and nothing it does writes."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import forms
import se_forms
import work_tickets
from test_work_ticket_issues import IDENTITY, FakeGh, forms_home, worktree  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = forms.load(ROOT, tree=True)
WORK = CATALOG["work"]
TITLE = WORK.example["title"]
FIELDS = dict(WORK.example["fields"])

# Its git is the fake in memory (tests/conftest.py `fake_git_door`): no worktree is a repository.
pytestmark = pytest.mark.usefixtures("fake_git_door")


@pytest.fixture
def gh(monkeypatch) -> FakeGh:
    """GitHub as test_work_ticket_issues fakes it, on the work_tickets se_forms.py imports."""
    fake = FakeGh()
    monkeypatch.setattr(work_tickets, "run_gh", fake)
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/owner/repo")
    return fake


@pytest.fixture(autouse=True)
def direct(monkeypatch):
    """Every command runs directly, never through a kern that may serve this checkout."""
    monkeypatch.setenv("SE_KERN", "off")


def run(capsys, *arguments: str) -> tuple[int, str, str]:
    code = se_forms.main([*arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_list_and_draft_answer_what_the_engine_answers(capsys):
    code, out, _ = run(capsys, "list", "--tree")
    assert code == 0 and out.splitlines() == forms.list_forms(CATALOG)
    code, out, _ = run(capsys, "draft", "work", "--tree")
    drafted = json.loads(out)
    assert code == 0 and drafted == forms.draft_fields(WORK)
    assert {"fields", "field_says", "field_shape", "schema"} <= set(drafted)
    assert drafted["field_shape"]["goal"]["required"] and drafted["schema"]["required"]
    code, out, _ = run(capsys, "draft", "work", "--markdown", "--tree")
    assert code == 0 and out == forms.draft(WORK)


def test_an_unknown_form_is_answered_with_the_list_of_forms(capsys):
    for command in (["draft", "nope"], ["check", "nope", "--body", "B."]):
        code, out, _ = run(capsys, *command, "--tree")
        assert code == 2, command
        assert "no form 'nope'; the forms are:" in out
        assert all(line in out for line in forms.list_forms(CATALOG))


def test_check_answers_its_verdict_first_and_exits_0(capsys, tmp_path, worktree, gh, forms_home):
    thin = tmp_path / "thin.md"
    thin.write_text("<!-- se:fleet -->\n<!-- se:form work -->\n\n## Situation\n\nIt is so.\n",
                    encoding="utf-8")
    code, out, _ = run(capsys, "check", "work", "--title", "thin-ticket", "--body-file",
                       str(thin), "--worktree", str(worktree), "--tree")
    lines = out.splitlines()
    assert code == 0 and lines[0].startswith("refused: ") and lines[0].endswith(" findings")
    assert any(line.startswith("  Problem: missing") for line in lines)
    assert len(lines) <= 1 + forms.REFUSAL_LINES
    assert lines[-1].endswith(f"{Path(se_forms.__file__).resolve()} draft work")

    code, out, err = run(capsys, "check", "work", "--fields-json", json.dumps(FIELDS),
                         "--render", "--worktree", str(worktree), "--tree")
    first, rendered = out.split("\n", 1)
    assert code == 0 and first == "passes"
    assert rendered == forms.render(WORK, FIELDS)
    code, out, _ = run(capsys, "check", "work", "--title", TITLE, "--body",
                       forms.render(WORK, FIELDS), "--worktree", str(worktree), "--tree")
    assert code == 0 and out.splitlines()[0] == "passes"


def test_check_selects_by_action_and_answers_free_texts_as_passing(capsys, worktree, gh,
                                                                    forms_home):
    code, out, _ = run(capsys, "check", "--action", "comment.create", "--body", "Thanks.",
                       "--worktree", str(worktree), "--tree")
    assert code == 0 and out.splitlines() == ["passes", "free: no form applies (comment.create)"]
    code, out, _ = run(capsys, "check", "--action", "issue.create", "--labels", "work",
                       "--body", "Only a line.", "--title", TITLE, "--worktree", str(worktree),
                       "--tree")
    assert code == 0 and out.startswith("refused: ") and "the work form refuses" in out


@pytest.mark.parametrize("arguments", [
    ["check", "--body", "B."],
    ["check", "work", "--action", "issue.create", "--body", "B."],
    ["check", "work", "--repo", "git.example/o/r", "--body", "B."],
    ["check", "work", "--fields-json", "[1]"],
])
def test_check_usage_errors_exit_2(capsys, arguments):
    code, out, _ = run(capsys, *arguments, "--tree")
    assert code == 2 and out.strip()


# The same title and body, through se_forms.py check and through work_tickets.py file with
# [forms] enforce = "refuse": both refuse in exactly the same cases.

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
def test_check_refuses_exactly_where_file_refuses(case, capsys, worktree, gh, forms_home):
    (worktree / "se.toml").write_text(f'{IDENTITY}\n[forms]\nenforce = "refuse"\n',
                                      encoding="utf-8")
    (worktree / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    title, fields, says = CASES[case]
    body = worktree / "body.md"
    body.write_text(forms.render(WORK, fields), encoding="utf-8")
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


# The gate (se_forms.py gate): SE's PreToolUse hook's judge of a write through the GitHub tools.

import io  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import review  # noqa: E402
from shell_paths import BASH, sh  # noqa: E402
from test_forms import field_report_variants, review_report  # noqa: E402

OWNER, REPO_NAME = "owner", "repo"
SESSION = "gate-session"
THIN = "<!-- se:fleet -->\n\n## Situation\n\nIt is so.\n"
GOOD_WORK = forms.render(WORK, FIELDS)
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
def project(worktree, home_repo, forms_home) -> Path:
    """The checkout holding the payload's cwd: its se.toml decides, its local list is read."""
    (worktree / ".git").mkdir()
    (worktree / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    return worktree


def gate(capsys, monkeypatch, text: str, *arguments: str) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert se_forms.main(["gate", *arguments]) == 0
    return capsys.readouterr().out


def denial(out: str) -> str:
    answer = json.loads(out)["hookSpecificOutput"]
    assert answer["hookEventName"] == "PreToolUse" and answer["permissionDecision"] == "deny"
    assert set(answer) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
    return answer["permissionDecisionReason"]


# One row of the gate's table each: tool, the call's other arguments, the off-form body, the form's
# own body and the form that refuses.
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
def test_the_gate_denies_an_off_form_write_of_each_tool_and_passes_its_form(
        row, capsys, monkeypatch, project, gh):
    tool, given, thin, good, form = ROWS[row]
    out = gate(capsys, monkeypatch, payload(f"mcp__github__{tool}", project, body=thin, **given),
               "--gate", "refuse")
    reason = denial(out)
    assert f"the {form} form refuses" in reason and f"in {OWNER}/{REPO_NAME}" in reason
    assert len(reason.splitlines()) <= forms.REFUSAL_LINES
    assert reason.splitlines()[-1].startswith(
        f"Get the form: the se server's forms tool, command \"se_forms.py draft\", args [\"{form}\"]")
    assert gate(capsys, monkeypatch, payload(f"mcp__github__{tool}", project, body=good, **given),
                "--gate", "refuse") == ""


@pytest.mark.parametrize("name", ["mcp__plugin_github_github__issue_write",
                                  "github-mcp-server-issue_write", "github/issue_write"])
def test_every_shape_of_a_guarded_name_is_gated(name, capsys, monkeypatch, project, gh):
    text = payload(name, project, method="create", title=TITLE, labels=["work"], body=THIN)
    assert "the work form refuses" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


def test_the_payloads_mcp_server_name_is_the_server_part(capsys, monkeypatch, project, gh):
    given = {"method": "create", "title": TITLE, "labels": ["work"], "body": THIN}
    data = json.loads(payload("mcp__gh__issue_write", project, **given))
    assert gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse") == ""
    data["mcp_server"] = {"name": "github", "source": "user"}
    assert "work form" in denial(gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse"))
    data["tool_name"], data["mcp_server"] = "mcp__github__issue_write", {"name": "files"}
    assert gate(capsys, monkeypatch, json.dumps(data), "--gate", "refuse") == ""


def test_copilots_payload_is_read_from_its_tool_args(capsys, monkeypatch, project, gh):
    given = {"owner": OWNER, "repo": REPO_NAME, "method": "create", "title": TITLE,
             "labels": ["work"], "body": THIN}
    text = json.dumps({"sessionId": SESSION, "cwd": str(project),
                       "toolName": "github-mcp-server-issue_write", "toolArgs": json.dumps(given)})
    assert "work form" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


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
    (project / "se.toml").write_text(f'{IDENTITY}\n[forms]\ngate = "refuse"\n', encoding="utf-8")
    assert "work form" in denial(gate(capsys, monkeypatch, thin))
    monkeypatch.setenv("SE_FORMS_GATE", "OFF")
    assert gate(capsys, monkeypatch, thin) == ""


def test_warn_hands_the_findings_to_the_agent_and_never_allows(capsys, monkeypatch, project, gh):
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    answer = json.loads(gate(capsys, monkeypatch, text, "--gate", "warn"))["hookSpecificOutput"]
    assert set(answer) == {"hookEventName", "additionalContext"}
    assert "([forms] gate = warn); sent anyway" in answer["additionalContext"]
    assert "Problem: missing" in answer["additionalContext"]


def test_a_wrong_gate_value_is_a_form_error_naming_the_file(worktree):
    (worktree / "se.toml").write_text('[forms]\ngate = "maybe"\n', encoding="utf-8")
    with pytest.raises(forms.FormError, match=r"\[forms\] gate = 'maybe' in se.toml"):
        forms.enforcement(worktree)


def test_the_second_refusal_offers_the_hold_and_the_held_write_then_passes(
        capsys, monkeypatch, project, gh):
    given = {"method": "create", "title": TITLE, "body": THIN}
    thin = payload("mcp__github__issue_write", project, labels=["work"], **given)
    held = payload("mcp__github__issue_write", project, labels=["work", "off-form"], **given)
    first = denial(gate(capsys, monkeypatch, thin, "--gate", "refuse"))
    assert "off-form" not in first
    assert "off-form" in denial(gate(capsys, monkeypatch, held, "--gate", "refuse"))
    assert gate(capsys, monkeypatch, held, "--gate", "refuse") == ""
    ready = payload("mcp__github__issue_write", project, labels=["work", "off-form", "ready"],
                    **given)
    assert denial(gate(capsys, monkeypatch, ready, "--gate", "refuse"))


def test_a_private_term_is_refused_every_time_and_never_printed(capsys, monkeypatch, project, gh):
    body = forms.render(WORK, {**FIELDS, "goal": "For Quuxcorp."})
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work", "off-form"], body=body)
    for _ in range(4):
        reason = denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
        assert "local list" in reason and "quux" not in reason.lower()
        assert "--hold" not in reason


def test_an_issue_edit_without_labels_is_checked_against_its_bodys_form(
        capsys, monkeypatch, project, gh):
    body = "<!-- se:form work -->\n" + THIN
    text = payload("mcp__github__issue_write", project, method="update", issue_number=7, body=body)
    assert "the work form refuses" in denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))


def test_a_crash_after_selection_denies_and_one_before_passes_and_logs(
        capsys, monkeypatch, project, gh):
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)

    def broken(*_):
        raise RuntimeError("the disk is gone")

    with monkeypatch.context() as patch:
        patch.setattr(se_forms, "findings", broken)
        reason = denial(gate(capsys, monkeypatch, text, "--gate", "refuse"))
    assert reason.startswith("SE's form gate failed on this write (RuntimeError), so it was not sent")
    assert "work_tickets.py file" in reason and "SE_FORMS_GATE=off" in reason
    log = project / ".se" / ".runtime" / "forms-gate.log"
    assert gate(capsys, monkeypatch, "{not json", "--gate", "refuse") == ""
    with monkeypatch.context() as patch:
        patch.setattr(se_forms, "deciding", broken)
        assert gate(capsys, monkeypatch, text, "--gate", "refuse") == ""
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "RuntimeError: the disk is gone" in lines[0]
    assert "It is so" not in log.read_text(encoding="utf-8")


def test_a_gate_past_its_bound_passes_and_logs(capsys, monkeypatch, project, gh):
    monkeypatch.setattr(se_forms, "GATE_SECONDS", 0.5)
    monkeypatch.setattr(se_forms, "deciding", lambda *_: time.sleep(5))
    text = payload("mcp__github__issue_write", project, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    started = time.monotonic()
    assert gate(capsys, monkeypatch, text, "--gate", "refuse") == ""
    assert time.monotonic() - started < 0.5 + 2
    assert "slow: no answer within 0.5 s" in (
        project / ".se" / ".runtime" / "forms-gate.log").read_text(encoding="utf-8")


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
    switch = f'[forms]\ngate = "{gate_value}"\n' if gate_value else ""
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
def test_the_plugins_hook_line_prints_exactly_the_deny(tmp_path, shared_fake_git):
    root = hook_project(tmp_path, "refuse")
    text = payload("mcp__github__issue_write", root, method="create", title=TITLE,
                   labels=["work"], body=THIN)
    result = hooked(tmp_path, text, CLAUDE_PROJECT_DIR=sh(root))
    assert result.returncode == 0
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("}\n")
    assert "the work form refuses" in denial(result.stdout)
    calls = (tmp_path / "hook-home" / "calls").read_text(encoding="utf-8")
    assert calls.startswith(f"hook PreToolUse --root {sh(root)} <<") and SESSION in calls


@pytest_hook
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
                            (thin, {"SE_FORMS_GATE": "off"})):
        result = hooked(tmp_path, text, CLAUDE_PROJECT_DIR=sh(root), **variables)
        assert result.returncode == 0 and result.stdout == '{"kern": "answer"}\n'
    assert pythons.read_text(encoding="utf-8").count(" gate") == 1


# check-files: the files a form claims (the module docstring: Claimed files).

STEP_FORM = '''name = "step-risks"
reader = "owner"
says = "Risks: what could go wrong."

[applies]
actions = ["file.write"]
paths = ["book/*/steps/*.md"]

[rules]
required = "refuse"

[[fields]]
name = "risks"
kind = "list"
heading = "Risks"
required = true
says = "One item per risk, or None."
'''
GOOD_STEP = "---\nform: step-risks\n---\n\n# Risks\n\n## Risks\n\n- The scan misses a tool.\n"
EMPTY_STEP = "---\nform: step-risks\n---\n\n# Risks\n\n## Risks\n\n"


def step_book(root: Path, **steps: str) -> Path:
    """`root` with forms/step-risks.toml and one step file per keyword, book/m1/steps/<name>.md."""
    (root / "forms").mkdir(parents=True, exist_ok=True)
    (root / "forms" / "step-risks.toml").write_text(STEP_FORM, encoding="utf-8")
    (root / "book" / "m1" / "steps").mkdir(parents=True, exist_ok=True)
    for name, text in steps.items():
        (root / "book" / "m1" / "steps" / f"{name}.md").write_text(text, encoding="utf-8")
    return root / "book" / "m1" / "steps"


def test_check_files_checks_each_claimed_file_given_and_names_path_form_and_field(capsys, tmp_path):
    steps = step_book(tmp_path, good=GOOD_STEP, empty=EMPTY_STEP)
    (tmp_path / "free.md").write_text("# Free\n", encoding="utf-8")
    given = ["--forms", str(tmp_path / "forms"), "--root", str(tmp_path)]
    assert run(capsys, "check-files", *given, str(steps / "good.md"))[:2] == (
        0, "se_forms.py check-files: 1 claimed file passes its form\n")
    assert run(capsys, "check-files", *given, str(tmp_path / "free.md"))[:2] == (
        0, "se_forms.py check-files: no form claims a file checked\n")
    code, out, _ = run(capsys, "check-files", *given, str(steps / "good.md"), str(steps / "empty.md"))
    lines = out.splitlines()
    assert code == 1
    assert lines[0].startswith("book/m1/steps/empty.md (step-risks): Risks: empty")
    assert lines[-1].startswith("The empty form of each: uv run python ")
    assert f"forms.py draft --path <file> --root {tmp_path.resolve()} --forms" in lines[-1]


def test_check_files_names_at_most_ten_lines_with_a_count_of_the_rest(capsys, tmp_path):
    step_book(tmp_path, **{f"s{number:02}": EMPTY_STEP for number in range(12)})
    files = sorted(str(path) for path in (tmp_path / "book" / "m1" / "steps").iterdir())
    code, out, _ = run(capsys, "check-files", "--root", str(tmp_path), *files)
    lines = out.splitlines()
    assert code == 1 and len(lines) == se_forms.CHECK_FILES_LINES
    assert lines[-2] == "... and 4 more findings"


def test_check_files_changed_finds_an_untracked_claimed_file_and_skips_a_deleted_one(
        capsys, tmp_path, fake_git_door):
    import fake_git
    import git_door
    steps = step_book(tmp_path, kept=GOOD_STEP, gone=GOOD_STEP)
    (tmp_path / "se.toml").write_text('[forms]\nfiles = "check"\n', encoding="utf-8")
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


def test_check_files_usage_errors_and_a_wrong_files_value(capsys, worktree):
    assert run(capsys, "check-files")[0] == 2
    assert run(capsys, "check-files", "a.md", "--changed", "origin/main")[0] == 2
    (worktree / "se.toml").write_text('[forms]\nfiles = "refuse"\n', encoding="utf-8")
    with pytest.raises(forms.FormError, match=r"\[forms\] files = 'refuse' in se.toml"):
        forms.enforcement(worktree)
    assert forms.enforcement(worktree.parent).files == forms.OFF  # unset: off


def test_no_form_of_ses_claims_a_path_and_ses_own_se_toml_leaves_files_off():
    """Requirement "SE's value": SE's own check-files has nothing to check yet."""
    assert not any(form.paths for form in CATALOG.values())
    assert "files" not in tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["forms"]


@pytest_hook
def test_se_tomls_own_gate_on_its_integration_branch_denies_through_the_hook(
        tmp_path, shared_fake_git):
    """SE's own se.toml, read from this checkout, at the fixture's `origin/main`: the hook denies an
    off-form `issue_write` naming Problem and passes the form's own body. The working tree's copy
    lacks the gate, so the integration branch's decides."""
    import git_door
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
    variables = {"CLAUDE_PROJECT_DIR": sh(root), git_door.VARIABLE: f"fake:{shared_fake_git.path}"}
    given = {"method": "create", "title": TITLE, "labels": ["work"]}
    result = hooked(tmp_path, payload("mcp__github__issue_write", root, body=THIN, **given),
                    **variables)
    assert result.returncode == 0 and "Problem" in denial(result.stdout)
    result = hooked(tmp_path, payload("mcp__github__issue_write", root, body=GOOD_WORK, **given),
                    **variables)
    assert result.returncode == 0 and result.stdout == ""
