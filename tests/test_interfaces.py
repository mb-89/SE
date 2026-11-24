"""The interface templates' generated schemas, held to their templates, and the code that writes
and reads the texts SE's sessions pass through them (scripts/interfaces.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import interfaces
import templates

ROOT = Path(__file__).resolve().parents[1]
#: The interface templates with fields, and the messages among them.
INTERFACES = ("boot-report", "delivery-notice", "escalation", "generated-marker", "handover", "rules-page",
              "skills-page", "sub-agents-page", "retro-due", "retro-part", "retro-doc", "finding-ref",
              "started-comment", "claim-undone", "review-declined", "limit-restart")
MESSAGES = ("delivery-notice", "escalation", "generated-marker", "retro-part", "retro-doc",
            "finding-ref", "started-comment", "claim-undone", "review-declined", "limit-restart")


@pytest.fixture(scope="module")
def catalog() -> dict[str, templates.Template]:
    return templates.load(ROOT, tree=True)


def test_each_generated_schema_is_its_template_s_as_the_engine_generates_it(catalog):
    on_disk = sorted(path.name for path in interfaces.GENERATED.glob("*"))
    assert on_disk == sorted(f"{name}.json" for name in INTERFACES)
    assert templates.interfaces_drift(catalog, interfaces.GENERATED) == []
    for name in INTERFACES:
        template = catalog[name]
        data = interfaces.generated(name)
        assert data == json.loads(templates.interface_files(catalog)[f"{name}.json"])
        assert data["schema"] == templates.schema(template)
        assert (data["template"], data["version"], data["says"]) == (
            f"se/{name}", template.version, template.says)
        assert data.get("message", "") == template.message
        assert set(data["schema"]["properties"]) == {item.name for item in template.fields}


def test_the_check_names_a_generated_file_that_differs_is_missing_or_stray_and_the_write_mends_it(
        catalog, tmp_path):
    folder = tmp_path / "interfaces"
    shutil.copytree(interfaces.GENERATED, folder)
    edited = json.loads((folder / "escalation.json").read_text(encoding="utf-8"))
    edited["schema"]["required"] = ["issue"]
    (folder / "escalation.json").write_text(json.dumps(edited), encoding="utf-8")
    (folder / "handover.json").unlink()
    (folder / "old.json").write_text("{}", encoding="utf-8")
    assert templates.interfaces_drift(catalog, folder) == [
        "interfaces/handover.json: missing",
        "interfaces/escalation.json: differs from templates/escalation.md",
        "interfaces/old.json: no interface template makes it"]
    assert templates.write_interfaces(catalog, folder) == ["old.json", "escalation.json",
                                                            "handover.json"]
    assert templates.interfaces_drift(catalog, folder) == []
    assert templates.write_interfaces(catalog, folder) == []


def test_the_command_checks_the_committed_files(capsys):
    assert templates.main(["interfaces", "--check"]) == 0
    assert capsys.readouterr().out == "interfaces: every generated schema matches its template\n"


@pytest.mark.parametrize("name", MESSAGES)
def test_a_message_written_through_its_schema_reads_back_and_the_engine_reads_it_alike(catalog, name):
    template = catalog[name]
    values = dict(template.example["fields"])
    line = interfaces.write(name, values)
    assert "\n" not in line and line + "\n" == templates.render(template, values)
    assert interfaces.read(name, f"before\n{line}\nafter") == values
    assert templates.parse(template, line).fields == values


def test_a_snippet_writes_its_rows_and_its_case_and_reads_back_through_schema_and_engine(catalog):
    template = catalog["boot-report"]
    values = dict(template.example["fields"])
    text = interfaces.write("boot-report", values)
    assert text.splitlines()[-6:] == ["| SE | 12.0.1 | 13.0.0 |", "| kern | 2.1.0 | 2.1.0 |", "| obs | 10.3.2 | 10.3.2 |",
                                      "| obs-html | 0.5.2 | 0.5.2 |", "", "To update: /se:update"]
    assert text + "\n" == templates.render(template, values)
    assert interfaces.read("boot-report", text) == values
    assert templates.parse(template, text).fields == values
    assert templates.check(template, templates.parse(template, text)) == []
    one = [{"name": "SE", "loaded": "12.0.1", "newest": "12.0.1"}]
    current = interfaces.write("boot-report", {**values, "components": one, "update": "current"})
    assert current.endswith("|---|---|---|\n| SE | 12.0.1 | 12.0.1 |\n\nEverything is current.")
    assert interfaces.read("boot-report", current)["components"] == one
    assert interfaces.read("boot-report", text + "\nmore text") is None


def test_a_snippet_refuses_a_case_it_does_not_hold_and_a_row_without_its_columns(catalog):
    values = dict(catalog["boot-report"].example["fields"])
    with pytest.raises(interfaces.InterfaceError, match="update is 'maybe'; one of due, current, unknown"):
        interfaces.write("boot-report", {**values, "update": "maybe"})
    with pytest.raises(interfaces.InterfaceError, match="components item 1: loaded is required"):
        interfaces.write("boot-report", {**values, "components": [{"name": "SE"}]})


def test_the_engine_refuses_a_snippet_that_names_a_field_twice_or_a_rows_field_inside_a_line(tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    head = ("---\nname: s\nversion: 1.0.0\nkind: interface\nreader: owner\nsays: \"S.\"\ntags: [\"message\"]\n"
            "applies:\n  actions: [\"message.send\"]\n")
    rows = ("fields:\n  - name: r\n    kind: rows\n    row: \"- {a}\"\n    says: \"Rows.\"\n"
            "  - name: c\n    kind: case\n    cases:\n      yes: \"Yes.\"\n    says: \"Case.\"\n---\n")
    (folder / "s.md").write_text(head + 'message: "Rows: {r}\\n{c}"\n' + rows, encoding="utf-8")
    with pytest.raises(templates.TemplateError, match="rows field r stands alone on its line"):
        templates.load(tmp_path, tree=True)
    (folder / "s.md").write_text(head + 'message: "{r}\\n{c} {c}"\n' + rows, encoding="utf-8")
    with pytest.raises(templates.TemplateError, match="names each field once"):
        templates.load(tmp_path, tree=True)


def test_the_delivery_notice_and_the_escalation_keep_the_lines_the_agents_send(catalog):
    assert interfaces.write("delivery-notice", {"pr": "7", "branch": "feat-x"}) == (
        "field report in PR #7 for feat-x")
    assert interfaces.write("escalation", {"issue": "9", "question": "Which  side\nwins?"}) == (
        "escalated #9: Which side wins?")
    assert interfaces.read("delivery-notice", "Delivered: something else") is None


@pytest.mark.parametrize("values, problem", [
    ({"pr": "7"}, "branch is required"),
    ({"pr": "", "branch": "b"}, "pr is required"),
    ({"pr": 7, "branch": "b"}, "pr is int; the schema takes a string"),
    ({"pr": "7", "branch": "b", "session": "s"}, "session is no field of the schema"),
])
def test_the_schema_refuses_a_message_it_does_not_describe(values, problem):
    with pytest.raises(interfaces.InterfaceError, match="se/delivery-notice 1.0.0") as raised:
        interfaces.write("delivery-notice", values)
    assert problem in str(raised.value)


def test_the_schema_checks_lists_choices_and_the_handover_is_no_message():
    schema = {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "string"}},
        "pick": {"type": "string", "enum": ["a", "b"]}}, "required": [], "additionalProperties": False}
    assert interfaces.problems(schema, {"items": ["x", 2], "pick": "c"}) == [
        "items item 2 is int; the schema takes a string", "pick is 'c'; one of a, b"]
    with pytest.raises(interfaces.InterfaceError, match="handover is no message"):
        interfaces.write("handover", {})
    with pytest.raises(interfaces.InterfaceError, match="templates.py interfaces"):
        interfaces.generated("nope")


def test_the_handover_is_the_template_a_handover_issue_is_checked_by(catalog):
    template = catalog["handover"]
    body = templates.render(template, template.example["fields"])
    chosen = templates.select(catalog, "issue.create", body, "Handover 2026-11-22", labels=["handover"])
    assert chosen.name == "handover"
    assert templates.select(catalog, "issue.create", "## Goal\n\nShip.\n", "x", labels=[]).name != "handover"
    found = templates.check(template, templates.parse(template, "<!-- se:fleet -->\n\n## State\n\nAll in.\n",
                                                      "Handover 2026-11-22"))
    assert {finding.field for finding in found if finding.severity == templates.REFUSE} == {
        "open_issues", "branches", "decisions", "resume"}


def test_a_message_selects_its_template_by_its_line(catalog):
    assert templates.select(catalog, "message.send", "field report in PR #7 for b").name == "delivery-notice"
    assert templates.select(catalog, "message.send", "escalated #7: Which?").name == "escalation"
    assert templates.select(catalog, "message.send", "hello").name is None


INTERFACE = """---
name: note
version: 1.0.0
kind: interface
tags: ["test"]
reader: fleet
says: A message.
{extra}applies:
  actions: ["message.send"]
fields:
  - name: pr
    kind: {kind}
    says: The number.
{field}---
{body}"""


@pytest.mark.parametrize("extra, kind, field, body, error", [
    ('message: "PR #{pr}"\n', "line", "", "\n## Text\n", "an interface's body is empty"),
    ('message: "PR #{pr} and {other}"\n', "line", "", "", "message names pr, other"),
    ('message: "PR #{pr}"\n', "text", "", "", "field pr of a message is a line or a choice"),
    ('message: "PR #{pr}"\n', "line", "    heading: PR\n", "", "message line, which has no headings"),
    ("", "line", "", "", "field pr needs a heading"),
    ('message: "PR #{pr}"\nkind_note: x\n', "line", "", "", "unknown keys kind_note"),
])
def test_an_interface_template_that_is_no_message_or_no_data_does_not_load(tmp_path, extra, kind,
                                                                             field, body, error):
    (tmp_path / "note.md").write_text(INTERFACE.format(extra=extra, kind=kind, field=field, body=body),
                                      encoding="utf-8")
    with pytest.raises(templates.TemplateError, match=error):
        templates.load(ROOT, folder=tmp_path)


def test_an_interface_field_says_what_belongs_there_in_its_front_matter(tmp_path):
    text = INTERFACE.format(extra='message: "PR #{pr}"\n', kind="line", field="", body="")
    (tmp_path / "note.md").write_text(text.replace("    says: The number.\n", ""), encoding="utf-8")
    with pytest.raises(templates.TemplateError, match="says what belongs there"):
        templates.load(ROOT, folder=tmp_path)


def test_the_draft_of_a_message_is_its_line_and_each_field_s_instruction(catalog):
    assert templates.draft(catalog["delivery-notice"]) == (
        "field report in PR #{pr} for {branch}\n"
        "<!-- pr: The number of the work pull request, digits alone. -->\n"
        "<!-- branch: The work branch, named like the work issue's title. -->\n")


def test_every_comment_syntax_wraps_the_generated_marker_s_words_and_reads_them_back():
    import generated

    words = interfaces.write("generated-marker", {"generator": "se_plugin.py build", "source": "src/a.md"})
    assert words == "Code generated by se_plugin.py build from src/a.md. DO NOT EDIT."
    for syntax, (opening, closing) in generated.SYNTAXES.items():
        line = generated.line("se_plugin.py build", "src/a.md", syntax)
        assert line == opening + words + closing
        assert generated.marker_at(line + "\n", syntax) == generated.Marker("se_plugin.py build", "src/a.md")
    with pytest.raises(interfaces.InterfaceError, match="source is required"):
        generated.line("g", "", "hash")


def test_the_started_and_claim_undone_comments_are_the_lines_start_and_unclaim_wrote_by_hand():
    import work_tickets

    branch, started = "feature/x", "https://example.com/issues/7#issuecomment-1"
    assert work_tickets.started_comment(branch) == "Started: worker session on branch `{branch}`\n".format(
        branch=branch)
    assert interfaces.write("claim-undone", {"started": started, "branch": branch}) + "\n" == (
        "Claim undone: {started} started no worker; `ready`, `claim` and `start` take its branch "
        "`{branch}` again.\n").format(started=started, branch=branch)
    assert work_tickets.started_comment(branch).startswith(work_tickets.STARTED_PREFIX)
    assert interfaces.write("claim-undone", {"started": started, "branch": branch}).startswith(
        work_tickets.UNCLAIMED_MARK)


def test_the_decline_comment_is_the_line_review_wrote_by_hand_and_the_retro_reads_it():
    import retro
    import review

    number, url = 5, "https://example.com/pull/5"
    comment = review.escalation(number, url)
    assert comment == (f"Declined by the review of pull request #{number} ({url}): the change is "
                       "fundamentally wrong and does not land. The review comment there holds the findings; "
                       "SE re-scopes this issue or takes it to the owner.\n")
    assert retro.DECLINED.match(comment).groups() == ("5", url)


def test_the_limit_restart_comment_is_the_line_the_remedy_named_by_hand_and_its_reader_finds_it():
    import limit_restart

    comment = limit_restart.restarted_comment("session_a")
    assert comment == f"{limit_restart.RESTARTED} session session_a"
    assert limit_restart.restarted([{"body": comment}])
