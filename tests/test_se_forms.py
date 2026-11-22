"""SE's side of forms (scripts/se_forms.py), the command component `forms` kern's MCP door serves:
draft gives the engine's answer, check answers the verdict first and refuses exactly where the
filing commands refuse, and nothing it does writes."""

from __future__ import annotations

import json
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
