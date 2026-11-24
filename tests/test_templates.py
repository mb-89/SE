"""SE's templates (scripts/templates.py, templates/): loading, reading, writing, selection, every rule with a
failing and a passing fixture, the command, and the contracts with the writers SE has today."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import build_docs
import deck
import fake_git
import git_door
import code_templates
import templates
import template_cases
import outside_text
import overhaul
import retro
import review
import test_deck
import test_overhaul
import test_retro
import test_review
import test_work_ticket_issues as issue_tests
import work_tickets
from manual import page

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "work.md"


@pytest.fixture(scope="module")
def catalog() -> dict[str, templates.Template]:
    return templates.load(ROOT, tree=True)


def findings(template: templates.Template, fields: dict, title: str | None = None) -> list[templates.Finding]:
    values = dict(fields)
    if title is not None:
        values["title"] = title
    return templates.check(template, templates.parse(template, templates.render(template, values), values.get("title")))


def rules(found: list[templates.Finding], severity: str | None = None) -> set[str]:
    return {finding.rule for finding in found if severity in (None, finding.severity)}


def ticket_fields(catalog) -> dict:
    return dict(catalog["ticket"].example["fields"])


def work_fields(catalog) -> dict:
    return dict(catalog["work"].example["fields"])


WORK_BODY = """<!-- se:fleet -->

## Situation

Issues follow a template nothing checks.

## Problem

An issue without its Problem is filed as it is.

## Goal

One engine checks the shape of every issue.

## Approach

A TOML file per template, read by one script.
Not picked: JSON Schema, which holds no headings.

## Package kind

standard

## Blocked by

<!-- Issues that must be closed first. -->

None

## User requirement (verbatim)

> make it   "work",
>    please

## Design owner

docs/design.md "Templates".

## Requirements

1. `make install-tools`: installs every tool.
   Continued line of the first requirement.
2. Issue tooling in `scripts/work_tickets.py`.

## Acceptance

- [ ] Setup reports every tool.
- [ ] Tooling has tests.

## Verification

```sh
uv run pytest
```
"""


# Loading


ISSUE_TEMPLATES = ("ticket", "work", "routed")
ADAPTERS = ("field-report", "landing", "housekeeping", "merge-message", "review", "pugh")
#: The documents whose nodes other templates check (docs/templates.md "Nesting"), and the entry.
NESTING = ("decision", "raid-register", "raid-entry", "retro", "overhaul", "standing-questions",
           "overhaul-questions")
#: The interface templates with fields: the texts SE's sessions pass to each other.
INTERFACES = ("boot-report", "delivery-notice", "escalation", "handover")
#: The templates that claim files (`file.write`): the work issue's body file.
FILES = ("work-file",)
#: The code templates (docs/templates.md "Code templates"): adapters whose body is the files their
#: scaffold writes, each claiming the scripts or modules it shapes.
CODE_TEMPLATES = ("python-script", "python-module", "python-component", "go-module")
EVERY = (*ISSUE_TEMPLATES, *ADAPTERS, *NESTING, *INTERFACES, *FILES, *CODE_TEMPLATES)


def test_every_template_loads_with_its_actions_and_the_terms(catalog):
    assert set(catalog) == set(EVERY)
    assert all(catalog[name].actions == templates.ISSUE_ACTIONS for name in ISSUE_TEMPLATES)
    assert all(catalog[name].is_adapter for name in ADAPTERS)
    assert not any(catalog[name].is_adapter for name in (*ISSUE_TEMPLATES, *NESTING, *INTERFACES))
    assert all(catalog[name].kind == "interface" for name in INTERFACES)
    assert all(catalog[name].actions == (templates.FILE_ACTION,) and catalog[name].paths for name in FILES)
    assert catalog["ticket"].terms and catalog["ticket"].severity("terms") == templates.WARN
    work = catalog["work"]
    assert [item.name for item in work.fields][:5] == ["title", "situation", "problem", "goal",
                                                         "approach"]
    assert work.field("steps") is None and work.field("requirements").exact_heading


def write_template(root: Path, name: str, text: str) -> None:
    (root / "templates").mkdir(exist_ok=True)
    (root / "templates" / f"{name}.md").write_text(text, encoding="utf-8")


#: A template note's first lines, which every template declares.
HEAD = 'name: {name}\nversion: 1.0.0\nkind: document\ntags: ["test"]\n'
ISSUE_CREATE = 'applies:\n  actions: ["issue.create"]\n'

MINIMAL = """---
name: {name}
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: A template.
{extra}fields:
  - name: goal
    kind: text
    required: true
---

## Goal

<!-- goal: The goal. -->
"""


@pytest.mark.parametrize("extra, error", [
    ("", "applies.actions is required"),
    (f'{ISSUE_CREATE}rules:\n  words: refuse\n', "only warns"),
    ('applies:\n  actions: ["issue.delete"]\n', "is none of"),
])
def test_a_template_that_breaks_the_format_does_not_load(tmp_path, extra, error):
    write_template(tmp_path, "one", MINIMAL.format(name="one", extra=extra))
    with pytest.raises(templates.TemplateError, match=error.replace("[", r"\[").replace("]", r"\]")):
        templates.load(tmp_path, tree=True)


def test_a_valid_minimal_template_loads(tmp_path):
    write_template(tmp_path, "one", MINIMAL.format(name="one", extra=ISSUE_CREATE))
    assert list(templates.load(tmp_path, tree=True)) == ["one"]


def test_an_extends_cycle_does_not_load(tmp_path):
    write_template(tmp_path, "a", MINIMAL.format(name="a", extra=f'extends: b\n{ISSUE_CREATE}'))
    write_template(tmp_path, "b", MINIMAL.format(name="b", extra=f'extends: a\n{ISSUE_CREATE}'))
    with pytest.raises(templates.TemplateError, match="cycle"):
        templates.load(tmp_path, tree=True)


def commit_all(repository: Path) -> None:
    fake_git.git("-C", str(repository), "add", "-A")
    fake_git.git("-C", str(repository), "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "-m", "templates")


def test_load_reads_templates_at_origin_where_the_ref_holds_them(tmp_path, fake_git_door):
    applies = ISSUE_CREATE
    fake_git.init(tmp_path)
    write_template(tmp_path, "landed", MINIMAL.format(name="landed", extra=applies))
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/main", "HEAD")
    (tmp_path / "templates" / "landed.md").unlink()
    write_template(tmp_path, "local", MINIMAL.format(name="local", extra=applies))
    assert list(templates.load(tmp_path)) == ["landed"]
    assert list(templates.load(tmp_path, tree=True)) == ["local"]


def test_load_reads_the_working_tree_without_the_ref(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    write_template(tmp_path, "local", MINIMAL.format(name="local", extra=ISSUE_CREATE))
    assert list(templates.load(tmp_path)) == ["local"]


# Reading and writing


def test_parse_skips_front_matter_and_accepts_heading_variants(catalog):
    ticket = catalog["ticket"]
    body = ("---\nname: x\n---\n# situation:\n\nA.\n\n#### PROBLEM\n\nB.\n\n##### Goal\n\nnot a field\n"
            "\n## Goal\n\n_No response_\n")
    document = templates.parse(ticket, body)
    assert document.fields["situation"] == "A."
    assert document.fields["problem"] == "B.\n\n##### Goal\n\nnot a field"
    assert document.fields["goal"] == ""
    assert "Goal is empty" in " ".join(f.fix for f in templates.check(ticket, document))


def test_exact_heading_counts_only_as_written(catalog):
    work = catalog["work"]
    document = templates.parse(work, WORK_BODY.replace("## Requirements", "### requirements"))
    assert "requirements" not in document.fields
    refused = [f for f in templates.check(work, document) if f.field == "requirements"]
    assert refused and "must be exactly `## Requirements`" in refused[0].fix
    assert not [f for f in templates.check(work, templates.parse(work, WORK_BODY)) if f.severity == "refuse"]


def test_html_comments_do_not_fill_a_field(catalog):
    ticket = catalog["ticket"]
    document = templates.parse(ticket, "## Situation\n\n<!-- what is true today -->\n")
    assert [f.fix for f in templates.check(ticket, document) if f.field == "situation"][0].startswith(
        "Situation is empty")


def test_the_marker_names_the_repository_the_template_its_version_and_its_digest(catalog, tmp_path):
    work = catalog["work"]
    texts = [(ROOT / "templates" / f"{name}.md").read_text(encoding="utf-8") for name in ("work", "ticket")]
    digest = hashlib.sha256("".join(text + "\0" for text in texts).encode("utf-8")).hexdigest()
    assert work.marker_line == f"<!-- se:template se/work 1.0.0 sha256:{digest} -->"
    assert templates.render(work, work_fields(catalog)).splitlines()[1] == work.marker_line
    assert templates.TEMPLATE_MARKER_PATTERN.findall(work.marker_line) == ["work"]
    assert templates.TEMPLATE_MARKER_PATTERN.findall("<!-- se:template work -->\n<!-- se:form work -->") == []
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    own = templates.load(tmp_path, tree=True)["work"]
    assert own.marker_line == f"<!-- se:template project/work 1.0.0 sha256:{digest} -->"


def test_render_writes_the_markers_once_and_keeps_unknown_and_verbatim_bytes(catalog):
    work = catalog["work"]
    odd = "## Notes  \n\n  kept   as\twritten  \n\n\n"
    body = WORK_BODY.replace("<!-- se:fleet -->\n", "<!-- se:fleet -->\n<!-- se:fleet -->\n") \
        .replace("## Design owner", odd + "## Design owner")
    rendered = templates.render(work, templates.parse(work, body))
    assert rendered.count(templates.FLEET_MARKER) == 1
    assert rendered.startswith(f"{templates.FLEET_MARKER}\n{catalog['work'].marker_line}\n")
    assert odd in rendered
    assert "> make it   \"work\",\n>    please" in rendered
    assert rendered == templates.render(work, templates.parse(work, rendered))


def test_parse_of_render_gives_each_example_back(catalog):
    for template in (catalog[name] for name in ISSUE_TEMPLATES):
        example = dict(template.example["fields"])
        title = example.get("title")
        document = templates.parse(template, templates.render(template, example), title)
        assert document.fields == example, template.name
        assert not templates.check(template, document), template.name


def adapter_examples() -> dict[str, tuple[str, str | None]]:
    """Each adapter's example, (body, title), as the SE writer it names writes it: an adapter's
    body is its writer's, so its template keeps no copy."""
    return {
        "field-report": (f"Refs {ISSUE_URL}\n\n{issue_tests.reported_at(issue_tests.TIP)}", "feat/x"),
        "landing": (work_tickets.landing_description(PULL_URL, 5, ISSUE_URL), "feat/x"),
        "housekeeping": ("Refresh the lock.\n", "Refresh the lock"),
        "merge-message": ("Release-kind: minor", merge_title()),
        "review": (review_comment(test_review.report()), None),
        "pugh": (test_deck.PUGH, None),
        **{name: (code_example(name), None) for name in CODE_TEMPLATES},
    }


def code_example(name: str) -> str:
    """The file a code template claims, as its scaffold writes it."""
    made = code_templates.scaffold(templates.own(name), Path("x") / "thing", "Do it.", "thing")
    return next(text for path, text in sorted(made.items())
                if len(made) == 1 or path.name in ("go.mod", "__init__.py"))


@pytest.mark.parametrize("name", EVERY)
def test_each_template_renders_and_parses_its_example_back(catalog, name):
    template = catalog[name]
    if template.is_adapter:
        body, title = adapter_examples()[name]
        document = templates.parse(template, body, title)
        assert templates.render(template, document) == body
    else:
        example = dict(template.example["fields"])
        document = templates.parse(template, templates.render(template, example), example.get("title"))
        assert document.fields == example
    assert [finding for finding in templates.check(template, document)
            if finding.severity == templates.REFUSE] == []
    assert len(catalog) == len(EVERY)


def test_every_template_is_a_note_whose_front_matter_any_yaml_reader_reads_alike():
    yaml = pytest.importorskip("yaml")
    notes = sorted((ROOT / "templates").glob("*.md"))
    assert sorted(path.stem for path in notes) == sorted(EVERY)
    assert sorted(path.name for path in (ROOT / "templates").iterdir()) == sorted(
        [path.name for path in notes] + [templates.TERMS_FILE])
    for path in notes:
        text = path.read_text(encoding="utf-8")
        front = text.split("---\n", 2)[1]
        assert templates.front_data(front, path.name) == yaml.safe_load(front), path.name
        data = templates.note_data(text, path.name)
        assert templates.SEMVER.match(data["version"]) and data["kind"] in templates.TEMPLATE_KINDS
        assert data["tags"] and all(isinstance(tag, str) for tag in data["tags"])


def test_a_note_s_skeleton_gives_each_field_its_heading_and_its_instruction(catalog):
    work = catalog["work"]
    assert (work.version, work.kind, work.tags) == ("1.0.0", "document", ("issue", "work"))
    assert catalog["routed"].kind == "block" and catalog["merge-message"].kind == "interface"
    goal = work.field("goal")
    assert goal.heading == "Goal" and goal.says.startswith("What is true once this is done")
    assert work.field("situation").says == catalog["ticket"].field("situation").says
    assert work.field("title").says.startswith("The name, its branch too")
    text = (ROOT / "templates" / "work.md").read_text(encoding="utf-8")
    assert "## Goal\n\n<!-- goal: What is true once this is done" in text
    assert "\n    heading:" not in text.split("---\n", 2)[1]
    routed = (ROOT / "templates" / "routed.md").read_text(encoding="utf-8")
    assert "\n### Package kind\n" in routed and "\n## " not in routed


@pytest.mark.parametrize("front, error", [
    ("name: one\n\tkind: x\n", "indented with a tab"),
    ("rules:\n  terms: off\n", "off is a plain value another YAML reader may read otherwise"),
    ("version: 1.5\n", "1.5 is a plain value"),
    ("says: The name: a title\n", "quote it as a JSON string"),
    ("name: one\nname: two\n", "name is given twice"),
    ("tags: [\"a\",\n", "is no JSON value"),
    ("applies:\nname: one\n", "applies has no value"),
    ("name: one\n  kind: x\n", "indented below a key that has its value"),
    ("- a\n", "the front matter is a list"),
], ids=["tab", "off", "float", "colon", "twice", "json", "empty", "indent", "list"])
def test_front_matter_outside_the_subset_is_refused_by_its_line(front, error):
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.front_data(front, "templates/one.md")


def test_front_matter_reads_nested_mappings_lists_and_scalars():
    front = ("# a comment\nname: one\nquoted: \"off\"\nsingle: 'it''s'\ncount: 3\nyes_no: true\n"
             "list: [\"a\", \"b\"]\nmapping:\n  inner: x\n  \".\": [\"y\"]\nitems:\n  - name: a\n"
             "    kind: text\n  - plain\n")
    assert templates.front_data(front, "one") == {
        "name": "one", "quoted": "off", "single": "it's", "count": 3, "yes_no": True,
        "list": ["a", "b"], "mapping": {"inner": "x", ".": ["y"]},
        "items": [{"name": "a", "kind": "text"}, "plain"]}


@pytest.mark.parametrize("change, error", [
    (lambda text: text.replace("    required: true\n---", "    required: true\n    heading: Goal\n---"),
     "which owns its heading; take heading out of the front matter"),
    (lambda text: text.replace("    required: true\n---", "    required: true\n    says: The goal.\n---"),
     "which owns its says"),
    (lambda text: text.replace("## Goal\n\n<!-- goal: The goal. -->\n", ""),
     "the skeleton's sections are none; they are one per field with a section"),
    (lambda text: text.replace("<!-- goal:", "<!-- aim:"), "the skeleton's sections are aim"),
    (lambda text: text.replace("<!-- goal: The goal. -->", "The goal."), "holds one comment alone"),
    (lambda text: text.replace("---\n\n## Goal", "---\n\nA note.\n\n## Goal"),
     "text before the skeleton's first section"),
    (lambda text: text.replace("## Goal", "# Goal"), "is no section of the skeleton"),
    (lambda text: text.replace("version: 1.0.0\n", ""), "version is None"),
    (lambda text: text.replace("version: 1.0.0", "version: \"1.0\""), "version is '1.0'"),
    (lambda text: text.replace("kind: document", "kind: page"), "kind is 'page'; one of document"),
    (lambda text: text.replace('tags: ["test"]\n', ""), "tags is a list of words"),
    (lambda text: text.removeprefix("---\n"), "a template opens with its front matter"),
], ids=["heading", "says", "no-section", "other-field", "no-comment", "text-before", "page-title",
        "no-version", "no-semver", "kind", "tags", "no-front-matter"])
def test_a_note_that_breaks_the_format_does_not_load(tmp_path, change, error):
    write_template(tmp_path, "one", change(MINIMAL.format(name="one", extra=ISSUE_CREATE)))
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.load(tmp_path, tree=True)


def test_load_reads_the_tree_where_origin_holds_no_template_note(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "old.toml").write_text('name = "old"\n', encoding="utf-8")
    shutil.copy(ROOT / "templates" / templates.TERMS_FILE, tmp_path / "templates" / templates.TERMS_FILE)
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/main", "HEAD")
    write_template(tmp_path, "local", MINIMAL.format(name="local", extra=ISSUE_CREATE))
    assert list(templates.load(tmp_path)) == ["local"]


OBJECT_TEMPLATE = f"""---
{HEAD.format(name="obj")}reader: fleet
says: x
{ISSUE_CREATE}fields:
  - name: meta
    kind: object
---

## Meta

<!-- meta: keys -->
"""


def test_an_object_field_reads_and_writes_key_value_lines(tmp_path):
    write_template(tmp_path, "obj", OBJECT_TEMPLATE)
    template = templates.load(tmp_path, tree=True)["obj"]
    values = {"meta": {"Owner": "SE", "Size": "small"}}
    assert templates.parse(template, templates.render(template, values)).fields == values


# Selection


def test_select_takes_the_marker_then_the_conditions_then_the_plain_template(catalog):
    routed = "Outside text\n\n<!-- se:handled -->\n## Routing\n\nRouted from: X\n"
    assert templates.select(catalog, "issue.create", routed, "feat/x-20261116").name == "routed"
    for title in ("templates-match-names-and-kinds", "feat/x-20261116"):
        assert templates.select(catalog, "issue.edit", WORK_BODY, title, labels=["work"]).name == "work"
    assert templates.select(catalog, "issue.create", WORK_BODY, "templates-match-names-and-kinds").name == \
        "ticket"
    assert templates.select(catalog, "issue.create", "## Situation\n", "plain-words").name == "ticket"
    named = catalog["ticket"].marker_line + "\n" + WORK_BODY
    assert templates.select(catalog, "issue.create", named, "feat/x-20261116").name == "ticket"
    with pytest.raises(templates.TemplateError, match="issue.delete"):
        templates.select(catalog, "issue.delete", "", "")


def test_select_without_a_template_for_the_action_is_free(tmp_path):
    write_template(tmp_path, "one", MINIMAL.format(name="one", extra='applies:\n  actions: ["issue.edit"]\n'))
    assert templates.select(templates.load(tmp_path, tree=True), "issue.create", "", "").template is None


# Refuse rules: one failing and one passing fixture each


@pytest.mark.parametrize("change, why", [
    ({"situation": None}, "Situation is missing"),
    ({"situation": "  "}, "Situation is empty"),
    ({"situation": "TBD"}, "Situation holds a placeholder"),
    ({"situation": "What is true today, as someone who has not followed the work would see it."},
     "Situation repeats its own description"),
])
def test_required_refuses_a_missing_empty_placeholder_or_pasted_field(catalog, change, why):
    fields = {**ticket_fields(catalog), **change}
    fields = {name: value for name, value in fields.items() if value is not None}
    found = findings(catalog["ticket"], fields)
    assert any(f.rule == "required" and f.severity == "refuse" and f.fix.startswith(why)
               for f in found), found
    assert "required" not in rules(findings(catalog["ticket"], ticket_fields(catalog)))


def test_choice_refuses_a_value_outside_its_set(catalog):
    assert "choice" in rules(findings(catalog["work"], {**work_fields(catalog),
                                                        "package_kind": "huge"}), "refuse")
    assert "choice" not in rules(findings(catalog["work"], {**work_fields(catalog),
                                                            "package_kind": "Standard, small."}))


def test_not_picked_refuses_an_approach_without_its_alternative(catalog):
    assert "not-picked" in rules(findings(catalog["ticket"], {**ticket_fields(catalog),
                                                              "approach": "SE writes it."}), "refuse")
    assert "not-picked" not in rules(findings(catalog["ticket"], ticket_fields(catalog)))


def test_duplicate_refuses_the_same_text_in_two_fields(catalog):
    fields = ticket_fields(catalog)
    assert "duplicate" in rules(findings(catalog["ticket"], {**fields, "problem": fields["situation"]}),
                                "refuse")
    assert "duplicate" not in rules(findings(catalog["ticket"], fields))


def test_dangling_refuses_a_command_se_does_not_have(catalog):
    fields = ticket_fields(catalog)
    found = findings(catalog["ticket"], {**fields, "goal": "Run `work_tickets.py frobnicate` once."})
    assert [f.field for f in found if f.rule == "dangling" and f.severity == "refuse"] == ["goal"]
    assert "dangling" not in rules(findings(catalog["ticket"], {
        **fields, "goal": "Run `work_tickets.py intake` once."}))


# Warn rules: one failing and one passing fixture each; none ever refuses


WARNS = [
    ("words", {"situation": " ".join(["word"] * 130)}, {}),
    ("actor", {"steps": ["Write the plain title."]}, {}),
    ("one-sentence", {"steps": ["SE writes it. Then SE ships it."]}, {}),
    ("bare-number", {"goal": "Every title is plain, as #12 asked."},
     {"goal": "Every title is plain, as [the titles issue](https://example.com/12) asked."}),
    ("board", {"situation": "Status: open\nIssues are titled by branch."}, {}),
    ("terms", {"goal": "Every worktree title is plain."}, {}),
    ("unnamed-entry", {"depends_on": ["#12"]}, {"depends_on": ["#12 the templates engine"]}),
    ("title-shape", {"title": "Templates-Match"}, {}),
]


@pytest.mark.parametrize("rule, failing, passing", WARNS, ids=[rule for rule, _, _ in WARNS])
def test_each_warn_rule_warns_and_never_refuses(catalog, rule, failing, passing):
    ticket = catalog["ticket"]
    fields = ticket_fields(catalog)
    found = findings(ticket, {**fields, **failing})
    assert rule in rules(found, "warn")
    assert not rules(found, "refuse")
    assert rule not in rules(findings(ticket, {**fields, **passing}))


def test_the_work_title_warns_where_it_is_no_branch_name(catalog):
    assert "title-shape" in rules(findings(catalog["work"], work_fields(catalog), "Plain words"), "warn")
    assert "title-shape" not in rules(findings(catalog["work"], work_fields(catalog)))


def test_the_ticket_title_warns_where_the_body_repeats_it(catalog):
    title = "Say in plain words what each issue is about"
    repeated = {**ticket_fields(catalog), "title": title, "situation": title + " is the ask."}
    found = findings(catalog["ticket"], repeated)
    assert any(finding.rule == "title-shape" and finding.severity == templates.WARN
               and "the body repeats the title" in finding.fix for finding in found), found


def test_the_work_template_warns_where_the_goal_s_first_sentence_runs_past_the_landing_title_width(
        catalog):
    work = catalog["work"]
    assert work.field("goal").first_sentence_chars == work_tickets.SUMMARY_WIDTH
    long = ("Where SE's templates are switched on, a GitHub write through the GitHub MCP tools whose "
            "body breaks its template is refused before it runs, naming the templates and every fix.")
    assert len(long) == 175
    found = findings(work, {**work_fields(catalog), "goal": long + " The refusal names the template."})
    assert [(finding.rule, finding.severity) for finding in found] == [("first-sentence", templates.WARN)]
    assert "175" in found[0].fix and "landing title" in found[0].fix
    short = "Every landing title is a complete statement."
    assert len(short) == 44
    assert findings(work, {**work_fields(catalog), "goal": short + " Why it matters."}) == []


#: Titles under the name rule, of its old form, and breaking it, as `checked_name` judges them.
TITLES = ["templates-match-names-and-kinds", "plain", "123", "a1-b2", "feat/plain-titles-20261116",
          "fix/routed-20261116", "one-two-three-four-five-six", "Templates-Match", "double--dash",
          "-leading", "scripts/templates.py", "docs/a/b-20261116", "Plain words", ""]


def test_the_templates_accept_exactly_the_titles_checked_name_accepts(catalog):
    def accepted(title: str) -> bool:
        try:
            work_tickets.checked_name("file", title)
        except work_tickets.QueueError:
            return False
        return True

    def warns(template: templates.Template, title: str) -> list[templates.Finding]:
        fields = {**template.example["fields"], "title": title}
        document = templates.parse(template, templates.render(template, fields), title)
        return [finding for finding in templates.check(template, document) if finding.rule == "title-shape"]

    expected = {title for title in TITLES if accepted(title)}
    assert expected >= {"templates-match-names-and-kinds", "123", "feat/plain-titles-20261116"}
    for name in ("work", "ticket"):
        assert {title for title in TITLES if title and not warns(catalog[name], title)} == \
            expected - {""}, name
    for title in ("Templates-Match", "one-two-three-four-five-six"):
        for name in ("work", "ticket"):
            found = warns(catalog[name], title)
            assert [finding.severity for finding in found] == [templates.WARN]
            assert found[0].fix == work_tickets.name_refusal(title)
            assert "yyyymmdd" not in found[0].fix


@pytest.mark.parametrize("kind, refused", [("fix", False), ("feat", False), ("standard", False),
                                           ("banana", True)])
def test_the_package_kind_takes_every_kind_of_work(catalog, kind, refused):
    found = findings(catalog["work"], {**work_fields(catalog), "package_kind": kind})
    assert ("choice" in rules(found, "refuse")) == refused
    assert set(work_tickets.RELEASE_KINDS) <= set(catalog["work"].field("package_kind").choices)
    assert catalog["routed"].field("package_kind").choices == \
        catalog["work"].field("package_kind").choices


def test_a_body_route_writes_with_its_default_type_passes_the_routed_template(tmp_path, capsys):
    routing = "## Requirements\n\n1. A routed requirement.\n"
    body = tmp_path / "body.md"
    body.write_text(work_tickets.routed_body(OUTSIDE, "Proposal: make it work", routing, "feat"),
                    encoding="utf-8")
    assert "### Package kind\n\nfeat" in body.read_text(encoding="utf-8")
    assert templates.main(["check", "routed", "--tree", "--body-file", str(body)]) == 0
    assert "choice" not in capsys.readouterr().out


NAMED = """---
name: one
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: A template.
applies:
  actions: ["issue.create"]
rules:
  title-shape: warn
fields:
  - name: title
    kind: line
    source: title
    {title}
  - name: kind
    kind: choice
    {kind}
---

## Kind

<!-- kind: The kind. -->
"""


@pytest.mark.parametrize("title, kind, error", [
    ("shape: work_tickets:NO_SUCH_RULE", 'choices: ["a"]',
     "templates/one.md: field title shape: work_tickets:NO_SUCH_RULE does not resolve"),
    ("shape: no_such_script:RULE", 'choices: ["a"]',
     "templates/one.md: field title shape: no_such_script:RULE does not resolve"),
    ("shape: work_tickets:NAME_WORDS", 'choices: ["a"]', "is no pattern or function"),
    ("", 'choices: ["a", "work_tickets:NO_SUCH_KINDS"]',
     "templates/one.md: field kind choices: work_tickets:NO_SUCH_KINDS does not resolve"),
    ("", 'choices: ["work_tickets:NAME_EXAMPLE"]', "is no list or mapping"),
])
def test_a_field_that_names_code_that_does_not_exist_does_not_load(tmp_path, title, kind, error):
    write_template(tmp_path, "one", NAMED.format(title=title, kind=kind))
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.load(tmp_path, tree=True)


def test_a_field_names_a_pattern_a_function_a_list_and_a_mapping(tmp_path):
    write_template(tmp_path, "one", NAMED.format(title="shape: work_tickets:NAME_PATTERN",
                                             kind='choices: ["x", "work_tickets:RELEASE_ORDER", '
                                                  '"work_tickets:RELEASE_KINDS"]'))
    one = templates.load(tmp_path, tree=True)["one"]
    assert one.field("kind").choices[:4] == ("x", "patch", "minor", "major")
    assert "feat" in one.field("kind").choices
    document = templates.parse(one, "## Kind\n\nfeat\n", "Not A Name")
    assert [finding.rule for finding in templates.check(one, document)] == ["title-shape"]
    assert templates.check(one, templates.parse(one, "## Kind\n\nfeat\n", "a-name")) == []


# Contracts with SE's own writers


def blocked(monkeypatch, body: str, blocker: int) -> str:
    """`work_tickets.block`'s edited body, its GitHub calls faked."""
    written: list[str] = []
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda *_: {"repo": "o/r", "body": body})
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "o/r")
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, arguments: "42")
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, arguments, text: written.append(text) or "")
    work_tickets.block(ROOT, 5, blocker, "o/r")
    return written[-1]


def test_blocks_output_passes_the_work_template(catalog, monkeypatch):
    work = catalog["work"]
    once = blocked(monkeypatch, WORK_BODY, 12)
    assert "## Blocked by\n\nNone\n#12\n" in once
    twice = blocked(monkeypatch, blocked(monkeypatch, WORK_BODY.replace("None\n", "#3\n"), 4), 5)
    assert "## Blocked by\n\n#3\n#4\n#5\n" in twice
    for body in (once, twice):
        document = templates.parse(work, body, "feat/templates-20261116")
        assert not rules(templates.check(work, document), "refuse")
    assert templates.parse(work, twice).fields["blocked_by"] == ["#3", "#4", "#5"]


def test_open_points_pass_the_work_template_and_survive_render(catalog):
    work = catalog["work"]
    body = work_tickets.with_open_points(WORK_BODY, "a" * 40, ["Name the field.", "Test it."])
    document = templates.parse(work, body, "feat/templates-20261116")
    assert not rules(templates.check(work, document), "refuse")
    block = body[body.index("<!-- se:open-points"):body.index("<!-- se:open-points:end -->") + 27]
    rendered = templates.render(work, document)
    assert block in rendered
    assert document.fields["changes_after_filing"][1:3] == ["Name the field.", "Test it."]
    edited = templates.Document(work.name, {**document.fields, "goal": "Another goal."}, document.parts,
                            read=document.read)
    assert block in templates.render(work, edited)
    assert work_tickets.requirement_items(rendered) == work_tickets.requirement_items(body)


ROUTING = "## Requirements\n\n1. A routed requirement.\n\n## Package kind\n\nStandard, small.\n"
OUTSIDE = ("Please make the example work.\n\n## Steps to reproduce\n\n1. Run it.\n\n"
           "## Requirements\n\n1. An outside requirement.\n")


@pytest.mark.parametrize("enveloped", [False, True], ids=["plain", "envelope"])
def test_routed_body_passes_the_routed_template_and_the_outside_text_stays_data(catalog, enveloped):
    routed = catalog["routed"]
    outside = outside_text.envelope(OUTSIDE, "an outside issue", "NONE")[0] if enveloped else OUTSIDE
    body = work_tickets.routed_body(outside, "Proposal: make it work", ROUTING)
    document = templates.parse(routed, body)
    assert not rules(templates.check(routed, document), "refuse")
    assert document.fields == {"routed_from": "Proposal: make it work",
                               "requirements": ["A routed requirement."],
                               "package_kind": "Standard, small."}
    assert all("Steps to reproduce" not in part.heading for part in document.parts
               if part.kind in ("field", "unknown"))
    rendered = templates.render(routed, document)
    assert rendered.startswith(body[:body.index(work_tickets.HANDLED_MARKER)])
    assert templates.FLEET_MARKER not in rendered
    assert templates.parse(routed, rendered).fields == document.fields


def test_the_routed_template_refuses_a_body_without_its_routing(catalog):
    routed = catalog["routed"]
    assert "required" in rules(templates.check(routed, templates.parse(routed, OUTSIDE)), "refuse")


HAND_WRITTEN = """## Situation

S.

## Problem

P.

## Goal

G.

## Approach

A.
Not picked: B.

## Blocked by

#7
#9

## Design owner

docs/x.md.

## Requirements

1. First.
2. Second.

## Acceptance

- [ ] It works.

## Verification

```sh
uv run pytest
```
"""


def test_a_work_issue_rendered_from_fields_reads_as_the_hand_written_one(catalog):
    fields = {"situation": "S.", "problem": "P.", "goal": "G.", "approach": "A.\nNot picked: B.",
              "blocked_by": ["#7", "#9"], "design_owner": "docs/x.md.",
              "requirements": ["First.", "Second."],
              "acceptance": [{"done": False, "text": "It works."}],
              "verification": "uv run pytest"}
    rendered = templates.render(catalog["work"], fields)

    def issue(body: str) -> dict:
        return {"title": "feat/x-20261116", "url": "https://example.com/1", "body": body, "labels": []}
    assert work_tickets.requirement_items(rendered) == work_tickets.requirement_items(HAND_WRITTEN)
    assert work_tickets.planned_tickets(issue(rendered)) == work_tickets.planned_tickets(issue(HAND_WRITTEN))
    assert work_tickets.blockers_of(issue(rendered)) == work_tickets.blockers_of(issue(HAND_WRITTEN)) == [7, 9]


# The command


def test_check_of_the_work_template_names_the_missing_situation_and_empty_requirements(capsys):
    assert templates.main(["check", "work", "--tree", "--body-file", str(TEMPLATE)]) == 1
    out = capsys.readouterr().out
    assert "Situation is empty" in out and "Requirements is empty" in out
    assert "is missing" not in out
    assert len(out.splitlines()) <= 10


def test_check_passes_a_good_body_and_caps_its_lines(tmp_path, capsys):
    body = tmp_path / "body.md"
    body.write_text(WORK_BODY, encoding="utf-8")
    assert templates.main(["check", "work", "--tree", "--body-file", str(body),
                       "--title", "feat/templates-20261116"]) == 0
    assert capsys.readouterr().out.strip() == "work: no findings"
    body.write_text("## Steps\n\n" + "".join(f"{n}. Step {n}.\n" for n in range(1, 13)),
                    encoding="utf-8")
    assert templates.main(["check", "ticket", "--tree", "--body-file", str(body)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 10 and lines[-1].startswith("... and ")
    assert lines[0].startswith("refuse: ")


def test_check_takes_fields_from_a_draft(tmp_path, capsys, catalog):
    assert templates.main(["draft", "ticket", "--json", "--tree"]) == 0
    drafted = json.loads(capsys.readouterr().out)
    assert drafted["fields"]["steps"] == [] and drafted["field_says"]["goal"]
    drafted["fields"].update(ticket_fields(catalog))
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps(drafted), encoding="utf-8")
    assert templates.main(["check", "ticket", "--tree", "--fields", str(fields)]) == 0
    capsys.readouterr()
    assert templates.main(["check", "ticket", "--tree", "--fields", str(fields), "--title",
                       "Not A Name"]) == 0
    assert "title-shape" in capsys.readouterr().out


@pytest.mark.parametrize("name", EVERY)
def test_schema_prints_the_schema_draft_json_gives(capsys, catalog, name):
    assert templates.main(["draft", name, "--json", "--tree"]) == 0
    drafted = json.loads(capsys.readouterr().out)["schema"]
    assert templates.main(["schema", name, "--tree"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == drafted == templates.schema(catalog[name])
    assert printed == json.dumps(drafted, indent=2) + "\n"


def test_schema_takes_the_template_that_claims_a_file_and_refuses_both_or_neither(tmp_path, capsys):
    step_templates(tmp_path, risks='marker_pattern: "id: S5B"')
    (tmp_path / "book" / "m1" / "steps").mkdir(parents=True)
    step = tmp_path / "book" / "m1" / "steps" / "51-S5B.md"
    step.write_text(STEP, encoding="utf-8")
    where = ["--templates", str(tmp_path / "templates"), "--root", str(tmp_path)]
    assert templates.main(["schema", "--path", str(step), *where]) == 0
    assert json.loads(capsys.readouterr().out)["required"] == ["risks"]
    assert templates.main(["schema", "--tree"]) == 2
    assert "templates.py schema: name a template, or give --path" in capsys.readouterr().err
    assert templates.main(["schema", "nothing", "--tree"]) == 2


def schema_errors(schema: dict, value: object, where: str = "$") -> list[str]:
    """What `value` breaks of `schema`, read with the eight keywords `templates.schema` writes: SE
    adds no validator dependency."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    if kind and not isinstance(value, types[kind]):
        return [f"{where}: {type(value).__name__} is no {kind}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} is none of the enum")
    if kind == "array":
        for index, item in enumerate(value):
            errors += schema_errors(schema.get("items", {}), item, f"{where}[{index}]")
    if kind == "object":
        properties = schema.get("properties", {})
        errors += [f"{where}: {name} is required" for name in schema.get("required", [])
                   if name not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{where}: {name} is no property" for name in value if name not in properties]
        for name, item in value.items():
            if name in properties:
                errors += schema_errors(properties[name], item, f"{where}.{name}")
    return errors


def keywords(schema: object) -> set[str]:
    """Every keyword `schema` uses, at every depth; the names under `properties` are none."""
    if not isinstance(schema, dict):
        return set()
    inner = [keywords(item) for item in schema.get("properties", {}).values()]
    return set(schema).union(*inner) | keywords(schema.get("items"))


def drafted(capsys, name: str) -> tuple[str, dict]:
    assert templates.main(["draft", name, "--json", "--tree"]) == 0
    out = capsys.readouterr().out
    return out, json.loads(out)


@pytest.mark.parametrize("name", ISSUE_TEMPLATES)
def test_draft_json_gives_each_shape_and_a_schema_its_example_passes(capsys, catalog, name):
    template = catalog[name]
    _, answer = drafted(capsys, name)
    shapes, schema = answer["field_shape"], answer["schema"]
    assert list(shapes) == [item.name for item in template.fields]
    for item in template.fields:
        assert shapes[item.name]["kind"] == item.kind
        assert shapes[item.name].get("required", False) is item.required
        assert shapes[item.name].get("choices", []) == list(item.choices)
        assert schema["properties"][item.name]["description"] == item.says
    assert schema["required"] == [item.name for item in template.fields if item.required]
    assert schema_errors(schema, template.example["fields"]) == []
    assert schema_errors(schema, {"title": 1, "nope": ""})  # the validator does refuse


def test_the_work_shape_names_its_choices_and_its_flags(capsys, catalog):
    _, answer = drafted(capsys, "work")
    kind = answer["field_shape"]["package_kind"]
    assert kind == {"kind": "choice", "heading": "Package kind",
                    "choices": list(catalog["work"].field("package_kind").choices)}
    assert "feat" in kind["choices"] and len(kind["choices"]) == 13
    assert answer["field_shape"]["title"] == {"kind": "line", "required": True, "source": "title"}
    assert answer["schema"]["properties"]["acceptance"]["items"]["required"] == ["done", "text"]


def test_the_schema_uses_only_the_keywords_strict_tool_use_takes(catalog):
    for template in catalog.values():
        assert keywords(templates.schema(template)) <= set(templates.SCHEMA_KEYWORDS), template.name


def test_an_adapter_drafts_no_shape_and_an_empty_schema(capsys):
    _, answer = drafted(capsys, "review")
    assert answer["field_shape"] == {} and answer["schema"]["properties"] == {}


def test_draft_json_keeps_its_old_keys_byte_for_byte(capsys, catalog):
    out, _ = drafted(capsys, "work")
    template = catalog["work"]
    empty = {"list": [], "issue": [], "checklist": [], "object": {}}
    old = json.dumps({"template": template.name, "says": template.says,
                      "fields": {item.name: empty.get(item.kind, "") for item in template.fields},
                      "field_says": {item.name: item.says for item in template.fields}}, indent=2)
    assert out.startswith(old.removesuffix("\n}") + ",\n  \"field_shape\": {")


def test_an_object_field_takes_the_schemas_key_value_pairs(tmp_path):
    write_template(tmp_path, "obj", OBJECT_TEMPLATE)
    template = templates.load(tmp_path, tree=True)["obj"]
    pairs = {"meta": [{"key": "Owner", "value": "SE"}, {"key": "Size", "value": "small"}]}
    assert schema_errors(templates.schema(template), pairs) == []
    assert templates.render(template, pairs) == templates.render(template, {"meta": {"Owner": "SE",
                                                                    "Size": "small"}})


def test_check_takes_fields_and_bodies_as_text_and_renders_what_it_would_file(tmp_path, capsys,
                                                                             catalog):
    template = catalog["work"]
    for values in (work_fields(catalog), {"title": "plain-titles"}):
        text = json.dumps(values)
        (tmp_path / "f.json").write_text(text, encoding="utf-8")
        code = templates.main(["check", "work", "--tree", "--fields", str(tmp_path / "f.json")])
        by_file = capsys.readouterr().out
        assert templates.main(["check", "work", "--tree", "--fields-json", text]) == code
        assert capsys.readouterr().out == by_file
    assert code == 1 and "refuse: " in by_file
    values = work_fields(catalog)
    assert templates.main(["check", "work", "--tree", "--fields-json", json.dumps(values),
                       "--render"]) == 0
    rendered = capsys.readouterr()
    assert rendered.out == templates.render(template, values)
    assert rendered.out.startswith(f"{templates.FLEET_MARKER}\n{catalog['work'].marker_line}\n")
    assert templates.main(["check", "work", "--tree", "--title", "Not A Name", "--body",
                       rendered.out, "--render"]) == 0
    warned = capsys.readouterr()
    assert warned.out == rendered.out and "title-shape" in warned.err
    assert templates.main(["check", "work", "--tree", "--fields-json", "{\"title\": \"x\"}",
                       "--render"]) == 1
    assert capsys.readouterr().out.startswith("refuse: ")


def test_check_selects_the_template_by_action_as_a_write_would(capsys, catalog):
    body = templates.render(catalog["work"], work_fields(catalog)).replace(
        catalog["work"].marker_line + "\n", "")
    assert templates.main(["check", "--tree", "--action", "issue.create", "--labels", "work",
                       "--title", "plain-titles", "--body", body]) == 0
    assert capsys.readouterr().out == "work: no findings\n"
    assert templates.main(["check", "--tree", "--action", "issue.create", "--title", "plain-titles",
                       "--body", body]) == 1
    assert "steps [required]" in capsys.readouterr().out  # the ticket template's own field
    assert templates.main(["check", "--tree", "--action", "comment.create", "--body", "Thanks."]) == 0
    assert capsys.readouterr().out == "free: no template applies (comment.create)\n"
    marked = catalog["work"].marker_line + "\nThanks.\n"
    assert templates.main(["check", "--tree", "--action", "comment.create", "--body", marked]) == 1
    assert "[template]" in capsys.readouterr().out


@pytest.mark.parametrize("arguments, error", [
    (["check", "work", "--action", "issue.create", "--body", "x"], "not both"),
    (["check", "--body", "x"], "give --action"),
    (["check", "work", "--labels", "work", "--body", "x"], "with --action"),
    (["check", "work", "--fields-json", "[1]"], "must hold an object"),
    (["check", "work", "--fields-json", "{"], "--fields-json is no JSON"),
])
def test_check_usage_errors_of_the_new_options_exit_2(capsys, arguments, error):
    assert templates.main([*arguments, "--tree"]) == 2
    assert error in capsys.readouterr().err


def test_draft_prints_the_empty_template_with_its_says(capsys, catalog):
    assert templates.main(["draft", "work", "--tree"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{templates.FLEET_MARKER}\n{catalog['work'].marker_line}\n")
    assert "## Requirements\n\n<!-- Numbered, checkable requirements" in out
    assert rules(templates.check(catalog["work"], templates.parse(catalog["work"], out)), "refuse")


def test_list_names_every_template_with_its_actions(capsys):
    assert templates.main(["list", "--tree"]) == 0
    out = capsys.readouterr().out.splitlines()
    names = [line.split(" ")[0] for line in out]
    assert sorted(names) == sorted(EVERY)
    assert all("issue.create, issue.edit" in line for line in out if line.split(" ")[0]
               in ISSUE_TEMPLATES)


def test_list_owned_names_each_glob_a_template_owns_with_its_template(capsys, tmp_path):
    """Requirement 1: the engine's one listing of the paths the templates own, SE's work issue body
    file's and its code templates' scripts and modules among them, and another folder's own."""
    assert templates.main(["list", "--owned", "--tree"]) == 0
    assert capsys.readouterr().out == ("**/go.mod: go-module\n.se/components/*/__init__.py: python-component\n"
                                       ".se/issues/*.md: work-file\ngo.mod: go-module\n"
                                       "scripts/*.py: python-module\nscripts/*.py: python-script\n")
    write_template(tmp_path, "steps", MINIMAL.format(
        name="steps", extra='applies:\n  actions: ["file.write"]\n  paths: ["book/*/steps/*.md", "a/*.md"]\n'))
    assert templates.main(["list", "--owned", "--templates", str(tmp_path / "templates")]) == 0
    assert capsys.readouterr().out == "a/*.md: steps\nbook/*/steps/*.md: steps\n"
    assert templates.owned({name: template for name, template in templates.load(ROOT, tree=True).items()
                            if not template.is_file}) == []


@pytest.mark.parametrize("arguments, error", [
    (["check", "nope", "--tree", "--body-file", "x.md"], "no template 'nope'"),
    (["check", "work", "--tree", "--body-file", "missing.md"], "cannot read --body-file"),
])
def test_usage_errors_exit_2(tmp_path, capsys, arguments, error):
    arguments = [str(tmp_path / a) if a.endswith(".md") else a for a in arguments]
    assert templates.main(arguments) == 2
    assert error in capsys.readouterr().err


def test_a_missing_argument_exits_2():
    with pytest.raises(SystemExit) as stopped:
        templates.main(["check", "work", "--tree"])
    assert stopped.value.code == 2


# Templates for files: a template claims files by their path (file.write)


STEP_TEMPLATE = """---
name: {name}
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: "Risks: what could go wrong."
applies:
  actions: ["file.write"]
  paths: [{paths}]
{extra}rules:
  required: refuse
fields:
  - name: risks
    kind: list
    required: true
    none_ok: true
---

## Risks

<!-- risks: One item per risk, or None. -->
"""

STEP = "---\nid: S5B\nname: Risks\n---\n\n# Risks\n\n## Risks\n\n- The scan misses a tool.\n"


def step_templates(root: Path, **templates_by_name: str) -> dict[str, templates.Template]:
    for name, extra in templates_by_name.items():
        write_template(root, name, STEP_TEMPLATE.format(name=name, paths='"book/*/steps/*.md"',
                                                extra="".join(f"  {line}\n" for line in extra.splitlines())))
    return templates.load(root, folder=root / "templates")


@pytest.mark.parametrize("applies, error", [
    ('  actions: ["issue.create"]\n  paths: ["*.md"]', "goes only with"),
    ('  actions: ["file.write", "issue.create"]\n  paths: ["*.md"]', "goes only with"),
    ('  actions: ["file.write"]', "needs applies.paths"),
    ('  actions: ["file.write"]\n  paths: "*.md"', "list of globs"),
])
def test_a_file_template_needs_its_paths_and_its_paths_need_file_write(tmp_path, applies, error):
    write_template(tmp_path, "one", MINIMAL.format(name="one", extra=f"applies:\n{applies}\n"))
    with pytest.raises(templates.TemplateError) as refused:
        templates.load(tmp_path, folder=tmp_path / "templates")
    assert error in str(refused.value) and str(tmp_path / "templates" / "one.md") in str(refused.value)


def test_a_file_template_loads_with_its_paths_and_its_globs_match_by_folder(tmp_path):
    write_template(tmp_path, "deep", STEP_TEMPLATE.format(name="deep", paths='"book/**/*.md"', extra=""))
    catalog = step_templates(tmp_path, step="")
    assert catalog["step"].actions == ("file.write",) and catalog["step"].is_file
    assert catalog["step"].claims("book/m1/steps/51-S5B.md")
    assert not catalog["step"].claims("book/m1/steps/deeper/51-S5B.md")
    assert not catalog["step"].claims("book/m1/notes.md")
    assert all(catalog["deep"].claims(path) for path in ("book/a.md", "book/a/b/c.md"))
    assert not catalog["deep"].claims("notes/a.md")


def test_select_for_a_file_takes_the_front_matter_then_the_conditions(tmp_path):
    catalog = step_templates(tmp_path, risks='marker_pattern: "id: S5B"', goals="order: 1\n"
                         'marker_pattern: "id: S1"')
    pick = lambda body, path="book/m1/steps/x.md": templates.select(catalog, "file.write", body,
                                                                 path=path)
    free = pick(STEP, "notes/x.md")
    assert free.template is None and not free.findings
    assert pick("---\nid: S5B\nderived_from: {template: goals, version: \"1.0.0\"}\n---\n").name == "goals"
    assert pick("---\nid: S5B\nderived_from:\n  template: goals\n  version: \"1.0.0\"\n---\n").name == "goals"
    assert pick("---\nid: S5B\n---\n").name == "risks"
    outside = pick("---\nid: S5B\nderived_from: {template: work, version: \"1.0.0\"}\n---\n")
    assert outside.name == "risks" and rules(list(outside.findings), "refuse") == {"template"}
    none = pick("---\nid: S9\n---\n\n# Other\n")
    assert none.template is None
    assert [finding.fix for finding in none.findings] == [
        "book/m1/steps/x.md: no template takes this file; name its template in the front matter, "
        "derived_from: {template: <name>, version: <version>} (one of goals, risks)"]
    with pytest.raises(templates.TemplateError, match="give path"):
        templates.select(catalog, "file.write", STEP)


def recorded(template: templates.Template) -> str:
    """The front matter lines a claimed file records its template by."""
    return (f'derived_from: {{template: {template.name}, version: "{template.version}"}}\n'
            f"overlay: {template.digest}\n")


def test_a_step_file_keeps_its_front_matter_and_title_and_gains_only_its_template(tmp_path):
    template = step_templates(tmp_path, risks="")["risks"]
    document = templates.parse(template, STEP)
    assert document.fields == {"risks": ["The scan misses a tool."]}
    rendered = templates.render(template, document)
    assert rendered == STEP.replace("name: Risks\n", "name: Risks\n" + recorded(template))
    assert templates.FLEET_MARKER not in rendered and "se:template" not in rendered
    assert templates.parse(template, rendered).fields == document.fields
    assert templates.render(template, templates.parse(template, rendered)) == rendered
    bare = templates.render(template, templates.parse(template, "# Risks\n\n## Risks\n\nNone\n"))
    assert bare == f"---\n{recorded(template)}---\n\n# Risks\n\n## Risks\n\nNone\n"
    fresh = templates.render(template, {"risks": ["One."]})
    assert fresh == f"---\n{recorded(template)}---\n\n## Risks\n\n- One.\n"
    assert templates.parse(template, fresh).fields == {"risks": ["One."]}


def test_render_records_derived_from_and_overlay_in_place_and_selection_reads_them(tmp_path):
    template = step_templates(tmp_path, risks="")["risks"]
    old = ("---\nderived_from:\n  template: risks\n  version: \"0.1.0\"\nid: S5B\noverlay: x\n---\n\n"
           "# Risks\n\n## Risks\n\nNone\n")
    assert templates.parse(template, old).recorded == "0.1.0"
    rendered = templates.render(template, templates.parse(template, old))
    assert rendered == ('---\nderived_from: {template: risks, version: "1.0.0"}\n'
                        f"id: S5B\noverlay: {template.digest}\n---\n\n"
                        "# Risks\n\n## Risks\n\nNone\n")
    crlf = templates.render(template, templates.parse(template, "---\r\nid: S5B\r\n---\r\n\r\n"
                                                         "## Risks\r\n\r\nNone\r\n"))
    assert crlf.startswith("---\r\nid: S5B\r\n" + recorded(template).replace("\n", "\r\n") + "---")
    assert templates.select(templates.load(tmp_path, folder=tmp_path / "templates"), "file.write",
                            rendered, path="book/m1/steps/x.md").name == "risks"
    assert templates.draft(template).startswith(f"---\n{recorded(template)}---\n")


def test_render_brings_an_issue_s_marker_up_to_the_template_s_version(catalog):
    work = catalog["work"]
    rendered = templates.render(work, work_fields(catalog))
    old = rendered.replace(work.marker_line, work.marker_line.replace(" 1.0.0 ", " 0.9.0 "))
    assert old != rendered
    assert templates.render(work, templates.parse(work, old)) == rendered


def test_a_page_title_that_reads_like_a_field_is_no_field(tmp_path):
    template = step_templates(tmp_path, risks="")["risks"]
    document = templates.parse(template, "---\nid: S5B\n---\n\n# Risks\n\n- The scan misses a tool.\n")
    assert document.fields == {}
    assert rules(templates.check(template, document), "refuse") == {"required"}


def test_check_and_draft_take_a_file_against_templates_outside_se(tmp_path, capsys):
    risks = step_templates(tmp_path, risks='marker_pattern: "id: S5B"')["risks"]
    steps = tmp_path / "book" / "m1" / "steps"
    steps.mkdir(parents=True)
    (steps / "51-S5B.md").write_text(STEP, encoding="utf-8")
    (steps / "90-S9.md").write_text("---\nid: S9\n---\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    where = ["--templates", str(tmp_path / "templates"), "--root", str(tmp_path)]
    run = lambda *arguments: (templates.main([*arguments, *where]), capsys.readouterr())
    code, out = run("check", "--path", str(steps / "51-S5B.md"), "--render")
    assert code == 0 and out.out == STEP.replace("name: Risks\n", "name: Risks\n" + recorded(risks))
    code, out = run("check", "--path", str(steps / "51-S5B.md"), "--body", "# Risks\n")
    assert code == 1 and "[required]" in out.out
    code, out = run("check", "--path", str(steps / "90-S9.md"))
    assert code == 1 and "derived_from: {template: <name>" in out.out
    assert run("check", "--path", str(tmp_path / "notes.md"))[1].out == \
        "free: no template claims notes.md\n"
    code, out = run("draft", "--path", str(steps / "51-S5B.md"), "--json")
    assert code == 0 and json.loads(out.out)["template"] == "risks"
    code, out = run("draft", "--path", str(steps / "51-S5B.md"))
    assert out.out.startswith(f"---\n{recorded(risks)}---\n\n## Risks\n") and "se:fleet" not in out.out
    assert run("draft", "--path", str(tmp_path / "notes.md"))[1].out == \
        "free: no template claims notes.md\n"
    assert templates.main(["list", "--templates", str(tmp_path / "templates")]) == 0
    assert capsys.readouterr().out.startswith(
        "risks (owner): file.write: book/*/steps/*.md: Risks:")


# The version a document records (docs/templates.md "The document"): its marker's or its front matter's


def at_version(template: templates.Template, version: str) -> templates.Template:
    """`template` as it would load once its version moved to `version`."""
    return replace(template, version=version)


def version_findings(template: templates.Template, body: str) -> list[templates.Finding]:
    return [finding for finding in templates.check(template, templates.parse(template, body))
            if finding.rule == templates.VERSION_RULE]


def test_a_document_at_its_template_s_current_version_passes(catalog, tmp_path):
    work = at_version(catalog["work"], "2.3.0")
    body = templates.render(work, work_fields(catalog))
    assert templates.parse(work, body).recorded == "2.3.0"
    assert version_findings(work, body) == []
    assert not [f for f in templates.check(work, templates.parse(work, body)) if f.severity == "refuse"]
    risks = at_version(step_templates(tmp_path, risks="")["risks"], "2.3.0")
    page = templates.render(risks, templates.parse(risks, STEP))
    assert 'version: "2.3.0"}\n' in page and version_findings(risks, page) == []


def test_a_document_that_records_no_version_passes(catalog, tmp_path):
    work = at_version(catalog["work"], "2.3.0")
    assert templates.parse(work, WORK_BODY).recorded == "" and version_findings(work, WORK_BODY) == []
    risks = step_templates(tmp_path, risks="")["risks"]
    assert version_findings(risks, STEP.replace("name: Risks\n", "derived_from: {template: risks}\n")) == []
    other = STEP.replace("name: Risks\n", "derived_from: {template: goals, version: \"0.1.0\"}\n")
    assert templates.parse(risks, other).recorded == ""


@pytest.mark.parametrize("recorded", ["2.3.1", "2.1.4", "2.4.0"])
def test_a_minor_or_patch_move_warns(catalog, tmp_path, recorded):
    work = at_version(catalog["work"], "2.3.0")
    body = templates.render(at_version(work, recorded), work_fields(catalog))
    found = version_findings(work, body)
    assert [(f.field, f.severity) for f in found] == [("template", "warn")]
    assert f"records work {recorded}; the template is at 2.3.0" in found[0].fix
    assert "templates.py check work --body-file <file> --render" in found[0].fix
    assert not [f for f in templates.check(work, templates.parse(work, body)) if f.severity == "refuse"]
    risks = at_version(step_templates(tmp_path, risks="")["risks"], "2.3.0")
    page = templates.render(at_version(risks, recorded), templates.parse(risks, STEP))
    assert [f.severity for f in version_findings(risks, page)] == ["warn"]
    assert "templates.py check --path <file> --render" in version_findings(risks, page)[0].fix


@pytest.mark.parametrize("recorded", ["1.9.0", "3.0.0", "two"])
def test_a_major_move_refuses_naming_both_versions_and_the_fill(catalog, tmp_path, capsys, recorded):
    work = at_version(catalog["work"], "2.3.0")
    body = templates.render(at_version(work, "1.0.0"), work_fields(catalog)).replace(
        " 1.0.0 ", f" {recorded} ", 1)
    found = version_findings(work, body)
    assert [f.severity for f in found] == ["refuse"]
    assert f"records work {recorded}; the template is at 2.3.0" in found[0].fix
    assert "`templates.py draft work --json`" in found[0].fix
    assert "`templates.py check work --fields <fields> --render`" in found[0].fix
    risks = step_templates(tmp_path, risks="")["risks"]
    page = templates.render(risks, templates.parse(risks, STEP)).replace(
        'version: "1.0.0"', f'version: "{recorded}"')
    moved = at_version(risks, "2.3.0")
    assert [f.severity for f in version_findings(moved, page)] == ["refuse"]
    assert "`templates.py draft --path <file> --json`" in version_findings(moved, page)[0].fix
    (tmp_path / "old.md").write_text(page, encoding="utf-8")
    (tmp_path / "templates" / "risks.md").write_text(
        (tmp_path / "templates" / "risks.md").read_text(encoding="utf-8").replace(
            "version: 1.0.0", "version: 2.3.0"), encoding="utf-8")
    code = templates.main(["check", "risks", "--body-file", str(tmp_path / "old.md"), "--render",
                           "--templates", str(tmp_path / "templates")])
    out = capsys.readouterr().out
    assert code == 1 and f"records risks {recorded}; the template is at 2.3.0" in out


def test_a_template_cannot_set_the_version_rule(tmp_path):
    write_template(tmp_path, "one", MINIMAL.format(name="one", extra='applies:\n  actions: ["issue.create"]\n'
                                                         "rules:\n  version: warn\n"))
    with pytest.raises(templates.TemplateError, match="rule 'version' is unknown"):
        templates.load(tmp_path, folder=tmp_path / "templates")


@pytest.mark.parametrize("arguments, error", [
    (["check", "--action", "file.write", "--body", "x"], "give --path"),
    (["check", "--action", "issue.create", "--path", "x.md"], "without --action"),
    (["check", "work", "--root", ".", "--body", "x"], "give --path"),
    (["draft"], "not both"),
    (["draft", "work", "--path", "x.md"], "not both"),
    (["check", "--path", "/elsewhere/x.md", "--root", "/nowhere", "--body", "x"],
     "not under the project root"),
    (["list", "--templates", "/nowhere"], "is no folder"),
])
def test_the_file_options_refuse_what_does_not_fit(capsys, arguments, error):
    assert templates.main([*arguments, "--tree"]) == 2
    assert error in capsys.readouterr().err


# Adapters: the texts SE already writes and checks, registered as they are


REPO = "github.com/o/r"
ISSUE_URL = f"https://{REPO}/issues/7"
PULL_URL = f"https://{REPO}/pull/5"
HOME = {REPO}


def adapter_verdict(template: templates.Template, body: str, title: str | None = None) -> list[str]:
    """The refusals of `template` on `body`, without the adapter's name before each."""
    return [finding.fix.removeprefix(f"{template.name}: ") for finding
            in templates.check(template, templates.parse(template, body, title)) if finding.severity == templates.REFUSE]


def parametrized(test, index: int = 0) -> list:
    """The cases an existing test is parametrized with, its own fixtures as they stand."""
    return list(test.pytestmark[index].args[1])


def test_list_shows_each_adapter_with_its_checker_and_actions(capsys):
    assert templates.main(["list", "--tree"]) == 0
    lines = {line.split(" ")[0]: line for line in capsys.readouterr().out.splitlines()}
    assert "pr.create, pr.edit: checker work_tickets:field_report_problems:" in lines["field-report"]
    assert "comment.create, comment.edit: checker review:checked_report:" in lines["review"]
    assert "comment.create, comment.edit: A retro's report and its draft:" in lines["retro"]
    assert "comment.create, comment.edit: An overhaul's report:" in lines["overhaul"]
    assert "a node of a document: checker deck:pugh_problems:" in lines["pugh"]
    assert "deck.build: A decision note:" in lines["decision"]
    assert ("pr.merge: checker work_tickets:merge_release_kind, title "
            "work_tickets:INTEGRATION_SUBJECT_PATTERN:") in lines["merge-message"]
    assert "pr.create, pr.edit: checker none, 3 lines:" in lines["landing"]
    assert "pr.create, pr.edit: checker none (no field required):" in lines["housekeeping"]


def test_every_name_an_adapter_gives_resolves(catalog):
    for name in ADAPTERS:
        template = catalog[name]
        for reference in (template.checker, template.adapter.get("extract"), template.adapter.get("when"),
                          template.adapter.get("title_rule")):
            if reference:
                assert templates.resolve(reference, template) is not None, (name, reference)


@pytest.mark.parametrize("top, tables, error", [
    ("checker: review:checked_report\n", "fields:\n  - name: goal\n    kind: text\n    label: Goal\n"
     "    says: The goal.\n", "a template with fields takes no checker"),
    ("checker: review.checked_report\n", "", "is no \"<module>:<name>\""),
    ("checker: review:checked_report\n", "adapter:\n  read: body\n",
     "adapter has unknown keys read"),
    ("checker: deck:_explains\n", "adapter:\n  result: truth\n", "needs its refusal"),
    ("checker: deck:_explains\n", "adapter:\n  result: maybe\n", "result is 'maybe'"),
    ("", "adapter:\n  lines:\n    - pattern: x\n", "each item of adapter.lines has a pattern and says"),
], ids=["fields-and-checker", "no-reference", "unknown-key", "truth-without-refusal",
        "unknown-result", "line-without-says"])
def test_an_adapter_that_breaks_the_format_does_not_load(tmp_path, top, tables, error):
    write_template(tmp_path, "one", f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n{top}'
               f'applies:\n  actions: ["comment.create"]\n{tables}---\n')
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.load(tmp_path, tree=True)


@pytest.mark.parametrize("applies, error", [
    ('  actions: ["pr.create"]\n  base: next\n', "the one base is \"integration\""),
    ('  actions: ["pr.create"]\n  branch: main\n', "applies has unknown keys branch"),
    ('  actions: ["pr.delete"]\n', "action 'pr.delete' is none of"),
])
def test_applies_refuses_what_selection_cannot_read(tmp_path, applies, error):
    write_template(tmp_path, "one", f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n'
               f'applies:\n{applies}---\n')
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.load(tmp_path, tree=True)


def test_an_adapter_body_is_never_marked_and_has_no_fields_to_render(catalog):
    body = work_tickets.landing_description(PULL_URL, 5, ISSUE_URL)
    landing = catalog["landing"]
    assert templates.render(landing, templates.parse(landing, body)) == body
    assert landing.marker_line not in templates.render(landing,
                                                                        templates.parse(landing, body))
    with pytest.raises(templates.TemplateError, match="landing is an adapter and has no fields"):
        templates.render(landing, {})
    assert templates.draft(landing).startswith("<!-- landing: ")


# Selection


def test_select_gives_landing_on_integrates_open_pull_step_and_merge_message_on_its_squash(catalog):
    title = work_tickets.integration_merge_message(
        "feat/templates-adapters-20261116", 7, 5, True, "## Goal\n\nEvery text selects a template.\n")
    message = "Release-kind: minor"
    description = work_tickets.landing_description(PULL_URL, 5, ISSUE_URL, {"took": 1})
    plan = work_tickets.landing_plan(REPO, "land/feat/x", "main", "a" * 40, "b" * 40, title,
                                     message, description, "then", REPO)
    steps = {step.action: step.arguments for step in plan.steps}
    opened, squashed = steps["open_pull"], steps["squash"]
    template, found = templates.verdict(catalog, "pr.create", opened["body"], opened["title"],
                                base=opened["base"], repo=REPO, home=HOME)
    assert template.name == "landing" and found == []
    template, found = templates.verdict(catalog, "pr.merge", squashed["commit_message"],
                                squashed["commit_title"], base="main", repo=REPO, home=HOME)
    assert template.name == "merge-message" and found == []


@pytest.mark.parametrize("title, message, refusal", [
    ("Merge feat/x", "Release-kind: minor", "does not match 'Integrate ([^\\\\s:()]+)'"),
    ("Integrate feat/x", "No trailer.", "it states no kind"),
    ("Integrate feat/x", "Release-kind: minor\n\nRelease-kind: patch", "it states 'minor', 'patch'"),
    ("Integrate feat/x", "Release-kind: huge", "it states 'huge'"),
], ids=["title", "no-trailer", "two-trailers", "unknown-kind"])
def test_the_merge_message_holds_its_title_and_merge_release_kinds_rule(catalog, title, message,
                                                                         refusal):
    refused = adapter_verdict(catalog["merge-message"], message, title)
    assert len(refused) == 1 and refusal in refused[0]
    if "Integrate" in title:
        with pytest.raises(work_tickets.QueueError) as raised:
            work_tickets.merge_release_kind("", title, message)
        assert refused == [str(raised.value)]


@pytest.mark.parametrize("change, says", [
    (lambda body: body.replace("Refs ", "See "), "the first line is `Refs <work issue url>`"),
    (lambda body: body.replace("Lands ", "Brings "), "a line `Lands <work pull request url>"),
], ids=["no-refs", "no-lands"])
def test_the_landing_needs_each_line_landing_description_writes(catalog, change, says):
    body = change(work_tickets.landing_description(PULL_URL, 5, ISSUE_URL))
    template, found = templates.verdict(catalog, "pr.create", body, "Integrate feat/x", base="main")
    assert template.name == "landing" and [finding.rule for finding in found] == ["line"]
    assert says in found[0].fix


def test_a_work_issue_carrying_the_decision_marker_is_refused(catalog):
    body = WORK_BODY.replace(templates.FLEET_MARKER, templates.FLEET_MARKER + "\n" + catalog["decision"].marker_line)
    template, found = templates.verdict(catalog, "issue.create", body, "feat/templates-20261116",
                                labels=["work"])
    assert template.name == "work"
    refused = [finding for finding in found if finding.rule == "template"]
    assert len(refused) == 1 and refused[0].severity == templates.REFUSE
    assert "the decision template does not apply to issue.create" in refused[0].fix


def test_a_housekeeping_pull_request_needs_no_field_report_and_main_without_the_label_does(catalog):
    body = "Tidy the README's wording.\n"
    template, found = templates.verdict(catalog, "pr.create", body, "Tidy the README", base="main",
                                labels=["housekeeping"])
    assert template.name == "housekeeping" and found == []
    template, found = templates.verdict(catalog, "pr.create", body, "Tidy the README", base="main")
    assert template.name == "field-report"
    assert [finding.rule for finding in found] == ["checker"]
    assert "holds no field report" in found[0].fix


def test_a_marker_narrows_within_the_allowed_set(catalog):
    body = f"Refs {ISSUE_URL}\n\n" + issue_tests.reported_at(issue_tests.TIP)
    chosen = templates.select(catalog, "pr.create", body, "feat/x", base="main", labels=["housekeeping"])
    assert chosen.name == "field-report" and chosen.findings == ()


@pytest.mark.parametrize("action, body, where", [
    ("comment.create", "Integrated in `abc1234`.\n", {}),
    ("comment.create", "<!-- se:fleet -->\n<!-- se:handled -->\nRouted.\n", {}),
    ("comment.edit", "<!-- se:open-points " + "a" * 40 + " -->\n1. A point.\n"
     "<!-- se:open-points:end -->\n", {}),
    ("comment.create", work_tickets.REFS_REQUEST_MARKER + "\nOne-way ref change.\n", {}),
    ("pr.create", "Any text.\n", {"base": "scratch"}),
    ("pr.create", "Any text.\n", {"base": "main", "repo": "github.com/elsewhere/x",
                                  "home": HOME}),
    ("issue.create", "Any text.\n", {"repo": "github.com/elsewhere/x", "home": HOME}),
], ids=["comment", "fleet-and-handled", "open-points", "refs", "other-branch", "other-repo-pull",
        "other-repo-issue"])
def test_free_texts_select_no_template(catalog, action, body, where):
    chosen = templates.select(catalog, action, body, "A title", **where)
    assert chosen.template is None and chosen.findings == ()


def test_an_adapter_marker_outside_the_allowed_set_is_refused(catalog):
    body = WORK_BODY.replace(templates.FLEET_MARKER, templates.FLEET_MARKER + "\n" + review.VERDICT_MARKER)
    chosen = templates.select(catalog, "issue.create", body, "feat/templates-20261116", labels=["work"])
    assert chosen.name == "work"
    assert [finding.fix for finding in chosen.findings] == [
        "the review template does not apply to issue.create: it shapes comment.create, comment.edit, "
        "and the body carries its marker"]


def test_home_is_origin_and_the_outside_repositories(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    fake_git.git("-C", str(tmp_path), "remote", "add", "origin", "https://github.com/o/r.git")
    (tmp_path / "se.toml").write_text('[outside]\n"github.com/other/side" = 12\n', encoding="utf-8")
    home = templates.home_repositories(tmp_path)
    assert home == {"github.com/o/r", "github.com/other/side"}
    catalog = templates.load(ROOT, tree=True)
    assert templates.select(catalog, "issue.create", WORK_BODY, "feat/x-20261116", repo="o/r",
                        home=home, labels=["work"]).name == "work"
    assert templates.select(catalog, "issue.create", WORK_BODY, "feat/x-20261116",
                        repo="github.com/other/side", home=home, labels=["work"]).name == "work"


# Same verdicts: each adapter answers as the check it names, on that check's own fixtures


def field_report_variants() -> dict[str, str]:
    """The field reports tests/test_work_ticket_issues.py checks, as descriptions carry them."""
    complete = issue_tests.reported_at(issue_tests.TIP)
    begin, end = work_tickets.REPORT_BEGIN, work_tickets.REPORT_END
    return {
        "complete": complete,
        "as-written": issue_tests.COMPLETE_REPORT,
        "unfilled": f"{begin}\n**Work issue:** #<n>  **Branch:** `<branch>` `<integration branch>` "
                    f"`<commit>`\n{end}\n",
        "unmarked": complete.replace(begin, ""),
        "placeholders-below": complete.replace(
            "## Spec gaps\n\nNone.", "## Spec gaps\n\nThe draft fills `#<n>`, `<branch>`."),
        **{f"result-{result}": complete.replace("**Result:** complete", f"**Result:** {result}")
           for result, _ in parametrized(issue_tests.test_field_report_requires_an_exact_result_header)},
        "no-decisions-table": complete.replace(
            "| Decision | Alternatives | Rationale | Confidence |\n|---|---|---|---|\n", ""),
        "wrong-kind": complete.replace("**Re-integration kind:** patch", "**Re-integration kind:** huge"),
    }


@pytest.mark.parametrize("name", list(field_report_variants()))
def test_the_field_report_adapter_gives_the_structure_checks_verdict(catalog, name):
    report = field_report_variants()[name]
    description = f"Refs {ISSUE_URL}\n\n{report}"
    try:
        expected = work_tickets.field_report_problems(
            work_tickets.report_in(description, "The pull request description"), None)
    except work_tickets.QueueError as error:
        expected = [str(error)]
    assert adapter_verdict(catalog["field-report"], description) == expected
    template, _ = templates.verdict(catalog, "pr.edit", description, "feat/x", base="main")
    assert template.name == "field-report"


def review_comment(given: object) -> str:
    """The comment `review.py file` posts for the report `given`, or, for one it refuses, the
    same comment shape around it."""
    try:
        return review.verdict_comment(5, review.checked_report(given), False)
    except work_tickets.QueueError:
        data = {"pull": 5, **given, "landed": False} if isinstance(given, dict) else given
        return (f"{review.VERDICT_MARKER}\n## Review of pull request #5\n\n"
                + review.fenced(json.dumps(data, indent=2), "json") + "\n")


REVIEW_CASES = [given for given, _ in parametrized(
    test_review.test_a_verdict_without_its_evidence_is_refused_and_writes_nothing)] + [
    test_review.report(),
    test_review.report(verdict="pass with open points", findings=[test_review.finding("x")]),
    test_review.report(verdict="decline", findings=[test_review.finding("Breaks", blocking=True)]),
]


@pytest.mark.parametrize("given", REVIEW_CASES)
def test_the_review_adapter_gives_checked_reports_verdict(catalog, given):
    try:
        review.checked_report(given)
        expected = []
    except work_tickets.QueueError as error:
        expected = [str(error)]
    body = review_comment(given)
    assert adapter_verdict(catalog["review"], body) == expected
    template, found = templates.verdict(catalog, "comment.create", body, repo=REPO, home=HOME)
    assert template.name == "review" and [finding.fix for finding in found
                                      if finding.severity == templates.REFUSE] == [
        f"review: {problem}" for problem in expected]


def retro_block(**changes: object) -> dict:
    """The judgment tests/test_retro.py's judged draft holds, `changes` applied."""
    block = {"window": {"retro": 30}, "previous": {},
             "classes": [test_retro.LOST_REPORTS],
             "findings": [test_retro.finding(),
                          test_retro.finding(title="Make the field report a rule of the rule book",
                                             home=retro.RULE_BOOK, controversial=True,
                                             why="it changes a rule")],
             "went_well": ["The fake door kept the tests fast."]}
    return {**block, **changes}


def marked_block(marker: str, block: dict) -> str:
    return f"# The draft\n\nThe facts.\n\n{marker}\n" + review.fenced(json.dumps(block, indent=2),
                                                                       "yaml") + "\n"


def test_the_retro_report_is_a_document_of_the_retro_template_and_passes(catalog):
    template, found = templates.verdict(catalog, "comment.create", retro_report(), repo=REPO,
                                        home=HOME)
    assert template.name == "retro"
    assert [finding for finding in found if finding.severity == templates.REFUSE] == []
    unfilled = retro_report().replace("> The integrator stalled twice on a red suite.", "")
    _, found = templates.verdict(catalog, "comment.create", unfilled, repo=REPO, home=HOME)
    assert [(finding.field, finding.rule) for finding in found
            if finding.severity == templates.REFUSE] == [("field_feedback", "required")]


def overhaul_block(**changes: object) -> dict:
    """The judgment tests/test_overhaul.py's judged draft holds, `changes` applied."""
    rules = [{"id": rule.id, "name": rule.name} for rule in overhaul.book_rules(ROOT)]
    block = {"overhaul": 50, "rules": rules, "verdicts": test_overhaul.verdicts(),
             "looked_at": {part: "Nothing to change." for part in overhaul.LOOKED_AT},
             "findings": [test_overhaul.finding(),
                          test_overhaul.finding(title="Name the speed of the suite as a rule",
                                                rule="tst-002", place=overhaul.BOOK.as_posix())],
             "went_well": ["The retros kept their blocks."]}
    return {**block, **changes}


def test_the_overhaul_report_passes_with_the_block_it_carries(catalog):
    template, found = templates.verdict(catalog, "comment.create", overhaul_report(), repo=REPO,
                                        home=HOME)
    assert template.name == "overhaul" and found == []


# The decks whose decision deck.py's section rule refuses: those its test names, and the silent
# decision, which the build refuses for its missing bless first and which has no sections either.
UNEXPLAINED = {*parametrized(
    test_deck.test_build_refuses_a_decision_that_does_not_explain_the_problem_before_its_options),
    "decision-without-bless"}


@pytest.mark.parametrize("name", list(test_deck.DECKS))
def test_the_decision_template_gives_the_section_rule_of_deck_py(catalog, name):
    """A note with a `pugh` fence is a decision, checked by the decision template as deck.py's build
    refuses it; a record chapter, without one, is free."""
    notes, _ = test_deck.DECKS[name]
    for note, text in notes.items():
        nodes = templates._nodes(text)
        template, found = templates.verdict(catalog, "deck.build", text)
        assert (template is not None) == deck._holds_pugh(nodes), (name, note)
        refused = [finding for finding in found if finding.severity == templates.REFUSE]
        assert bool(refused) == (template is not None and name in UNEXPLAINED), (name, note, refused)
        assert deck._explains(nodes) or not deck._holds_pugh(nodes) or refused


def test_deck_py_reads_its_sections_from_the_decision_template(catalog):
    decision = catalog["decision"]
    assert deck.sections() == tuple(item.heading for item in decision.fields if item.in_body)
    assert [item.name for item in decision.fields][-1] == "options"


# Contract over every body SE sends: each sending function, the bodies its command sends


FREE, NO_BODY = None, "no body"
SENDING_TOOLS = {"issue_write", "add_issue_comment", "create_pull_request", "update_pull_request",
                 "merge_pull_request"}


def senders(folder: Path) -> set[str]:
    """`<module>:<function>` of each function in `folder`'s scripts that sends a body: a call of
    run_gh_with_body, or a Step or an `ask` of a sending tool."""
    found: set[str] = set()
    for path in sorted(folder.glob("*.py")):
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def scope(self, node) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = scope

            def visit_Call(self, node: ast.Call) -> None:
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
                    node.func, "id", "")
                tool = {"Step": 1, "ask": 0}.get(name)
                sends = name == "run_gh_with_body" or (
                    tool is not None and len(node.args) > tool and isinstance(
                        node.args[tool], ast.Constant) and node.args[tool].value in SENDING_TOOLS)
                if sends and stack:
                    found.add(f"{path.stem}:{'.'.join(stack)}")
                self.generic_visit(node)

        Visitor().visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


@dataclass
class Case:
    """One body a command sends: its action, the template it selects (FREE, or NO_BODY for a write
    without one), the body and where it goes."""
    action: str
    template: str | None
    body: str | None = None
    title: str | None = None
    base: str | None = None
    labels: tuple[str, ...] = ()


def step_cases(plan, templates_by_step: dict[str, str | None], base: str = "main") -> list[Case]:
    """The cases of `plan`'s sending steps, each step's template named in `templates_by_step`."""
    cases = []
    for step in plan.steps:
        if step.tool not in SENDING_TOOLS:
            continue
        arguments = step.arguments
        if step.action not in templates_by_step:  # `comment_duplicate:<twin>` and its kin
            templates_by_step = {**templates_by_step, step.action: templates_by_step.get(
                step.action.split(":", 1)[0], NO_BODY if "body" not in arguments else "unnamed")}
        if step.tool == "merge_pull_request":
            cases.append(Case("pr.merge", templates_by_step[step.action], arguments["commit_message"],
                              arguments["commit_title"], base))
        elif "body" not in arguments:
            cases.append(Case("issue.edit", NO_BODY))
        elif step.tool == "add_issue_comment":
            cases.append(Case("comment.create", templates_by_step[step.action], arguments["body"]))
        elif step.tool == "create_pull_request":
            cases.append(Case("pr.create", templates_by_step[step.action], arguments["body"],
                              arguments["title"], arguments["base"]))
        elif step.tool == "update_pull_request":
            cases.append(Case("pr.edit", templates_by_step[step.action], arguments["body"],
                              arguments.get("title"), base))
        else:
            action = "issue.create" if arguments.get("method") == "create" else "issue.edit"
            labels = arguments.get("labels")
            cases.append(Case(action, templates_by_step[step.action], arguments["body"],
                              arguments.get("title"),
                              labels=tuple(labels) if isinstance(labels, list) else ()))
    return cases


WORK_TITLE = "feat/templates-20261116"
WORK_LABELS = ("work", "ready")


def work_issue(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.create", "work", WORK_BODY, WORK_TITLE, labels=WORK_LABELS)]


def backlog_issue(catalog, monkeypatch) -> list[Case]:
    ticket = catalog["ticket"]
    fields = ticket_fields(catalog)
    return [Case("issue.create", "ticket", work_tickets.fleet_marked(templates.render(ticket, fields)),
                 fields["title"])]


def routed_issue(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.edit", "routed", work_tickets.routed_body(
        OUTSIDE, "Proposal: make it work", ROUTING), "feat/make-it-work-20261116")]


def stamped_issue(catalog, monkeypatch) -> list[Case]:
    """A work issue filed without its marker, as `stamp` writes it back with the marker."""
    work = catalog["work"]
    bare = templates.render(work, dict(work.example["fields"])).replace(work.marker_line + "\n", "")
    return [Case("issue.edit", "work", templates.stamped(work, bare), work.example["title"],
                 labels=("work",))]


def comment(text: str):
    return lambda catalog, monkeypatch: [Case("comment.create", FREE, text)]


def no_body(action: str = "issue.edit"):
    return lambda catalog, monkeypatch: [Case(action, NO_BODY)]


def delivered(catalog, monkeypatch) -> list[Case]:
    report = work_tickets.report_in(issue_tests.reported_at(issue_tests.TIP), "the report")
    body = work_tickets.pull_request_body({"url": ISSUE_URL, "body": WORK_BODY}, report)
    return [Case(action, "field-report", body, WORK_TITLE, "main") for action in
            ("pr.create", "pr.edit")]


def merge_title() -> str:
    return work_tickets.integration_merge_message(WORK_TITLE, 7, 5, True, WORK_BODY)


def landing(catalog, monkeypatch) -> list[Case]:
    plan = work_tickets.landing_plan(
        REPO, f"land/{WORK_TITLE}", "main", "a" * 40, "b" * 40, merge_title(), "Release-kind: minor",
        work_tickets.landing_description(PULL_URL, 5, ISSUE_URL, {"took": 1}), "then", REPO)
    return step_cases(plan, {"open_pull": "landing", "squash": "merge-message"})


def landing_door(catalog, monkeypatch, action: str) -> list[Case]:
    if action == "pr.merge":
        return [Case(action, "merge-message", "Release-kind: minor", merge_title(), "main")]
    return [Case(action, "landing", work_tickets.landing_description(PULL_URL, 5, ISSUE_URL),
                 merge_title(), "main")]


def review_report() -> review.Report:
    return review.checked_report(test_review.report(
        verdict="pass with open points", findings=[test_review.finding("Name the field")]))


def open_points_body() -> str:
    found = review_report()
    return work_tickets.with_open_points(WORK_BODY, found.head,
                                         [item.point(5, found.head) for item in found.findings])


def review_steps(catalog, monkeypatch) -> list[Case]:
    plan = review.file_steps(REPO, REPO, 5, 7, review.verdict_comment(5, review_report(), False),
                             open_points_body(), True)
    cases = step_cases(plan, {"comment_pull": "review", "edit_body": "work", "comment_issue": FREE})
    for case in cases:
        case.title = WORK_TITLE if case.template == "work" else case.title
        case.labels = WORK_LABELS if case.template == "work" else case.labels
    return cases


def review_run(catalog, monkeypatch) -> list[Case]:
    return [Case("comment.create", "review", review.verdict_comment(5, review_report(), False)),
            Case("issue.edit", "work", open_points_body(), WORK_TITLE, labels=WORK_LABELS)]


def retro_report() -> str:
    text = "# Retro draft for #30\n\n" + test_retro.steps() + "\n" + marked_block(
        retro.BLOCK_MARKER, retro_block())
    return retro.report(retro.judged(text, 30), 30, "docs/retro-30.md",
                        f"https://{REPO}/blob/x/docs/retro-30.md", "a" * 40, text)


def overhaul_report() -> str:
    sections = "".join(
        f"## {item.heading}\n\n" + "".join(f"### {question.heading}\n\nNone.\n\n"
                                           for question in item.nested.fields)
        for item in (overhaul.overhaul_template().field(name) for name in overhaul.QUESTION_FIELDS))
    text = marked_block(overhaul.BLOCK_MARKER, overhaul_block()).replace(
        "The facts.\n\n", "The facts.\n\n" + sections, 1)
    return overhaul.report(text, overhaul.judged(text, 50), 50)


def retro_steps(catalog, monkeypatch) -> list[Case]:
    cases = []
    for text, template in ((retro_report(), "retro"), (overhaul_report(), "overhaul")):
        cases += step_cases(retro.file_steps(REPO, 30, [text]), {"comment_issue": template})
    parts = retro.parts(retro_report(), 30, limit=400)
    cases += step_cases(retro.file_steps(REPO, 30, parts[:1]), {"comment_issue": FREE})
    cases += step_cases(retro.file_steps(REPO, 30, parts[1:2]), {"comment_issue": FREE})
    return cases


def tracker_comment(catalog, monkeypatch) -> list[Case]:
    return [Case("comment.create", "retro", retro_report()),
            Case("comment.create", "overhaul", overhaul_report()),
            Case("comment.create", FREE, "Integration stopped: the suite failed.\n")]


def blocker_link(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.edit", "work", blocked(monkeypatch, WORK_BODY, 12), WORK_TITLE,
                 labels=WORK_LABELS)]


def plan_of(make, templates_by_step: dict[str, str | None]):
    return lambda catalog, monkeypatch: step_cases(make(), templates_by_step)


def filing(catalog, monkeypatch) -> list[Case]:
    step = work_tickets.work_issue_filing(REPO, WORK_TITLE, WORK_BODY, ["work", "ready"])
    plan = work_tickets.filing_plan(REPO, "file", WORK_TITLE, WORK_BODY, step)
    return step_cases(plan, {"create": "work", "comment_twin": FREE, "comment_duplicate": FREE})


def duplicates(catalog, monkeypatch) -> list[Case]:
    steps = work_tickets.close_duplicate_steps(REPO, 9, work_tickets.Later("twin", 1), "a twin",
                                               "where it has one")
    return step_cases(work_tickets.Plan("close", steps), {
        step.action: FREE for step in steps})


def beat_edit(catalog, monkeypatch) -> list[Case]:
    """What every beat sends (work_tickets.py beat, start, the close-out): the work issue's own body
    with its beat line set or removed, with its own labels, so the gate takes the work template."""
    beaten = work_tickets.with_beat(WORK_BODY, datetime(2026, 11, 23, 8, 30, tzinfo=timezone.utc))
    return [Case("issue.edit", "work", body, labels=WORK_LABELS)
            for body in (beaten, work_tickets.without_beat(beaten))]


def unclaimed(catalog, monkeypatch) -> list[Case]:
    """What `unclaim` sends: the work issue's own body without its beat line, and its one-line
    answer to the Started comment."""
    beaten = work_tickets.with_beat(WORK_BODY, datetime(2026, 11, 24, 14, 50, tzinfo=timezone.utc))
    return [Case("issue.edit", "work", work_tickets.without_beat(beaten), labels=WORK_LABELS),
            Case("comment.create", FREE, work_tickets.UNCLAIMED_COMMENT.format(
                started=f"{ISSUE_URL}#issuecomment-1", branch="feature/example"))]


def without_beats(plan):
    """`plan` without its beat steps, whose body stands for the issue's own (`beat_edit`)."""
    return work_tickets.Plan(plan.title, tuple(step for step in plan.steps
                                               if not step.action.startswith("beat:")), plan.then)


#: Each function in scripts/ that sends a body, and what the command it serves sends.
CONTRACT = {
    "work_tickets:work_issue_filing": ("file", work_issue),
    "work_tickets:stamp": ("stamp", stamped_issue),
    "work_tickets:filing_plan": ("file, backlog file and route", filing),
    "work_tickets:filed_once.create": ("file and backlog file",
                                       lambda c, m: work_issue(c, m) + backlog_issue(c, m)),
    "work_tickets:filed_once.route": ("route", routed_issue),
    "work_tickets:filed_once.comment_twin": ("file", comment("A twin of this would be filed.\n")),
    "work_tickets:filed_once.comment_duplicate": ("file", comment("Duplicate of #3.\n")),
    "work_tickets:filed_once.close_duplicate": ("file", no_body()),
    "work_tickets:close_duplicate_steps": ("file", duplicates),
    "work_tickets:backlog_file": ("backlog file", backlog_issue),
    "work_tickets:route_outside_issue": ("route", routed_issue),
    "work_tickets:block": ("the blocker linker", blocker_link),
    "work_tickets:delivered_pull_request": ("deliver", delivered),
    "work_tickets:start_plan": ("start", plan_of(
        lambda: without_beats(work_tickets.start_plan(REPO, 7, WORK_TITLE, "agent", False)),
        {"assign": NO_BODY, "comment_issue": FREE})),
    "work_tickets:beat_step": ("start and integrate", beat_edit),
    "work_tickets:beat_action_gh.run": ("start and integrate", beat_edit),
    "work_tickets:beat_action_door.run": ("start and integrate", beat_edit),
    "work_tickets:beat": ("beat", beat_edit),
    "work_tickets:start_handed_off.assign": ("start", no_body()),
    "work_tickets:unclaim": ("unclaim", unclaimed),
    "work_tickets:post_started": ("start", comment(
        work_tickets.STARTED_COMMENT.format(branch="feature/example"))),
    "work_tickets:escalate": ("escalate", comment("Which of the two templates wins here?\n")),
    "work_tickets:escalation_plan": ("integrate", plan_of(
        lambda: work_tickets.escalation_plan(REPO, 7, "the suite failed"), {"comment_issue": FREE})),
    "work_tickets:label_step": ("start and integrate", no_body()),
    "work_tickets:tracker_actions.comment": ("retro.py, overhaul.py and escalations", tracker_comment),
    "work_tickets:landing_plan": ("integrate", landing),
    "work_tickets:closeout_plan": ("integrate", plan_of(
        lambda: without_beats(work_tickets.closeout_plan(
            REPO, REPO, 5, 7, "abc1234", "Integrated in abc1234.\n", [])),
        {"comment_pull": FREE, "comment_issue": FREE})),
    "work_tickets:RelayDoor.create_pull": ("integrate", lambda c, m: landing_door(c, m, "pr.create")),
    "work_tickets:RelayDoor.update_pull": ("integrate", lambda c, m: landing_door(c, m, "pr.edit")),
    "work_tickets:RelayDoor.squash": ("integrate", lambda c, m: landing_door(c, m, "pr.merge")),
    "work_tickets:RelayDoor.comment": ("integrate", comment("Integrated in abc1234.\n")),
    "work_tickets:RelayDoor.close_pull": ("integrate", no_body("pr.edit")),
    "work_tickets:RelayDoor.set_labels": ("integrate and start", no_body()),
    "work_tickets:RelayDoor.edit_issue": ("route", routed_issue),
    "work_tickets:RelayDoor.close_issue": ("integrate", no_body()),
    "work_tickets:refs_request": ("refs request", comment(
        work_tickets.REFS_REQUEST_MARKER + "\nOne-way ref change for `ref-maintenance`.\n")),
    "work_tickets:refs_request_read_back": ("refs request", comment(
        work_tickets.REFS_DRY_RUN_MARKER + "\n<!-- se:refs-request-id 1 -->\nThe dry run.\n")),
    "work_tickets:refs_apply_read_back": ("refs apply", comment(
        work_tickets.REFS_APPLIED_MARKER + "\n<!-- se:refs-request-id 1 -->\nApplied.\n")),
    "review:file_steps": ("review.py file", review_steps),
    "review:run_file": ("review.py file", review_run),
    "retro:file_steps": ("retro.py file and overhaul.py file", retro_steps),
}


def test_every_function_that_sends_a_body_has_a_row():
    assert sorted(senders(ROOT / "scripts")) == sorted(CONTRACT)


def test_a_new_sender_without_a_row_fails_the_contract_naming_its_function(tmp_path):
    copy = tmp_path / "scripts"
    shutil.copytree(ROOT / "scripts", copy, ignore=shutil.ignore_patterns("__pycache__"))
    with (copy / "work_tickets.py").open("a", encoding="utf-8") as handle:
        handle.write("\n\ndef announce(root, number, text):\n"
                     "    run_gh_with_body(root, ['issue', 'comment', str(number)], text)\n")
    missing = sorted(senders(copy) - set(CONTRACT))
    assert missing == ["work_tickets:announce"]


@pytest.mark.parametrize("sender", list(CONTRACT))
def test_each_body_se_sends_selects_its_template_and_passes(catalog, monkeypatch, sender):
    command, cases = CONTRACT[sender]
    made = cases(catalog, monkeypatch)
    assert made, f"{sender} ({command}) has no case"
    for case in made:
        if case.template == NO_BODY:
            assert case.body is None
            continue
        template, found = templates.verdict(catalog, case.action, case.body, case.title, base=case.base,
                                    labels=case.labels, repo=REPO, home=HOME)
        assert (template.name if template else FREE) == case.template, (sender, case.action)
        refused = [str(finding) for finding in found if finding.severity == templates.REFUSE]
        assert refused == [], (sender, case.action, refused)


# Enforcing: the switch, the body a filing command files, private terms, the refusal, the count


def test_enforcement_defaults_to_off_and_reads_the_working_tree_without_the_ref(tmp_path,
                                                                                 fake_git_door):
    assert templates.enforcement(tmp_path) == templates.Enforcement("off", 2, "se.toml")
    (tmp_path / "se.toml").write_text('[templates]\nenforce = "warn"\nrefusals = 3\n', encoding="utf-8")
    assert templates.enforcement(tmp_path) == templates.Enforcement("warn", 3, "se.toml")


def test_enforcement_reads_the_integration_branch_where_its_ref_exists(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    (tmp_path / "se.toml").write_text('[project]\nintegration_branch = "dev"\n', encoding="utf-8")
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/dev", "HEAD")
    (tmp_path / "se.toml").write_text('[project]\nintegration_branch = "dev"\n[templates]\n'
                                      'enforce = "refuse"\n', encoding="utf-8")
    assert templates.enforcement(tmp_path) == templates.Enforcement("off", 2, "origin/dev:se.toml")
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/dev", "HEAD")
    assert templates.enforcement(tmp_path).enforce == "refuse"


@pytest.mark.parametrize("table", ['enforce = "on"', "enforce = true", "refusals = 0",
                                   "refusals = true", 'refusals = "2"'])
def test_enforcement_refuses_a_value_outside_the_switch(tmp_path, fake_git_door, table):
    (tmp_path / "se.toml").write_text(f"[templates]\n{table}\n", encoding="utf-8")
    with pytest.raises(templates.TemplateError, match=r"\[templates\]"):
        templates.enforcement(tmp_path)


def test_filled_keeps_a_body_with_enforce_off_and_renders_it_otherwise(catalog):
    work = catalog["work"]
    body = "## Goal\n\nG.\n\n## Odd section\n\nKept.\n"
    assert templates.filled(work, body=body) == body
    again = templates.filled(work, body=body, enforce="warn")
    assert again.startswith(f"{templates.FLEET_MARKER}\n{catalog['work'].marker_line}\n")
    assert "## Odd section\n\nKept.\n" in again
    fields = dict(work.example["fields"])
    assert templates.filled(work, fields=fields, enforce="off") == templates.render(work, fields)


def test_every_whole_document_a_fill_makes_carries_its_templates_marker(catalog):
    """A filled issue or comment names the template it derives from (docs/templates.md "The filled
    template is a type"), whichever of SE's templates filled it."""
    filled = [name for name, template in catalog.items()
              if template.example and set(template.actions) & {"issue.create", "comment.create"}
              and not (template.is_adapter or template.message or template.writes_file)]
    assert {"work", "ticket", "routed", "handover"} <= set(filled)
    for name in filled:
        template = catalog[name]
        rendered, _ = templates.fill(template, dict(template.example["fields"]), "raw input",
                                     title=template.example.get("title"))
        assert template.marker_line in rendered.splitlines(), name


def test_stamped_writes_the_marker_where_render_writes_it_and_keeps_every_other_byte(catalog):
    work, routed, review_template = catalog["work"], catalog["routed"], catalog["review"]
    fleet = templates.FLEET_MARKER
    body = f"{fleet}\n<!-- se:beat 2026-11-24T10:00Z -->\n\n## Goal\n\nG.\n"
    assert templates.stamped(work, body) == (
        f"{fleet}\n{work.marker_line}\n<!-- se:beat 2026-11-24T10:00Z -->\n\n## Goal\n\nG.\n")
    assert templates.stamped(work, "## Goal\n\nG.\n") == f"{fleet}\n{work.marker_line}\n\n## Goal\n\nG.\n"
    again = templates.stamped(work, body)
    assert templates.stamped(work, again) == again  # stamped once
    routing = "Please.\n\n<!-- se:handled -->\n## Routing\n\nRouted from: x\n"
    assert templates.stamped(routed, routing) == (
        f"Please.\n\n<!-- se:handled -->\n{routed.marker_line}\n## Routing\n\nRouted from: x\n")
    assert work_tickets.ROUTED_PATTERN.search(templates.stamped(routed, routing))
    with pytest.raises(templates.TemplateError, match="no `<!-- se:handled -->` line"):
        templates.stamped(routed, "Please.\n")
    assert templates.stamped(review_template, "A review.\n") == "A review.\n"  # an adapter's own text
    assert templates.parse(work, again).fields == templates.parse(work, body).fields


def test_private_findings_name_the_field_and_the_list_never_the_term(catalog, tmp_path):
    (tmp_path / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    work = catalog["work"]
    body = templates.render(work, dict(work.example["fields"], goal="For Quuxcorp."))
    found = templates.private_findings(work, "feat/quuxcorp-20261116", body, tmp_path)
    assert [(item.field, item.rule, item.severity) for item in found] == [
        ("title", "private", "refuse"), ("goal", "private", "refuse")]
    assert all("quux" not in item.fix.lower() and "local list" in item.fix for item in found)
    assert templates.private_findings(work, "feat/x-20261116", body, tmp_path / "none") == []


def test_report_fits_ten_lines_names_every_finding_and_counts_no_tries(catalog):
    work = catalog["work"]
    found = [templates.Finding(f"f{index}", "required", "refuse", f"fix {index}") for index in range(14)]
    found.append(templates.Finding("goal", "words", "warn", "Goal has 99 words; keep it to 60"))
    text = templates.report("file", work, found, refused=True, hold="off-template")
    lines = text.splitlines()
    assert len(lines) <= templates.REFUSAL_LINES
    assert all(f"fix {index}" in text for index in range(14))
    assert any(line.startswith(f"{templates.ALSO} Goal: has 99 words") for line in lines)
    assert "templates.py draft work" in text and "--hold" in text and "off-template" in text
    assert "--hold" not in templates.report("file", work, found, refused=True)
    assert "fix its text on the issue itself and run work_tickets.py unhold <issue>" in text
    assert "unhold" not in templates.report("file", work, found, refused=True)


def test_refusals_are_counted_per_session_and_target_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    one = templates.target("work", "git.example/O/R", "issue.create", title="Feat/X-20261116 ")
    assert one == templates.target("work", "git.example/o/r", "issue.create", title="feat/x-20261116")
    other = templates.target("routed", "git.example/o/r", "issue.edit", number=4)
    env = {"SE_SESSION": "a"}
    assert templates.refusals(one, env) == 0
    assert [templates.count_refusal(one, env), templates.count_refusal(one, env)] == [1, 2]
    assert templates.refusals(other, env) == 0 and templates.refusals(one, {"SE_SESSION": "b"}) == 0
    assert templates.counts_file(env).parent == tmp_path / ".se" / "templates"



def missing_from_readme(readme: str) -> list[str]:
    """The files under `templates/` that docs/templating.md's "Templates" section does not name
    with their `says`."""
    start = readme.index("\n## Templates\n")
    after = re.search(r"\n#{1,2} ", readme[start + 1:])
    section = " ".join(readme[start:start + 1 + after.start() if after else None].split())
    missing = []
    for path in sorted((ROOT / "templates").iterdir()):
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if path.suffix == ".toml" else templates.note_data(text, path.name)
        says = " ".join(data["says"].split())
        if f"`templates/{path.name}`" not in section or says not in section:
            missing.append(path.name)
    return missing


def test_readme_templates_names_every_file_under_templates_with_its_says():
    readme = page("templating")
    assert missing_from_readme(readme) == []
    assert "No command checks with them yet" not in readme


def test_the_readme_check_fails_when_a_file_is_removed_from_the_section():
    readme = page("templating")
    start = readme.index("| `templates/retro.md` |")
    end = readme.index("\n| `templates/review.md` |", start)
    assert missing_from_readme(readme[:start] + readme[end + 1:]) == ["retro.md"]


# Nesting (docs/templates.md "Nesting"): nodes, registers and the fence node


def raid_register(catalog) -> str:
    """The RAID register's example as an issue body, rendered."""
    register = catalog["raid-register"]
    return templates.render(register, register.example["fields"])


def test_the_raid_example_passes(catalog, tmp_path, capsys):
    register = catalog["raid-register"]
    body = raid_register(catalog)
    assert register.field("entries").nested is catalog["raid-entry"]
    assert [name for name, _ in templates.entries(register.example["fields"]["entries"])] == [
        "The release slips", "The mirror stays up"]
    assert templates.check(register, templates.parse(register, body)) == []
    path = tmp_path / "raid.md"
    path.write_text(body, encoding="utf-8")
    assert templates.main(["check", "raid-register", "--tree", "--body-file", str(path)]) == 0
    assert templates.main(["check", "--action", "issue.create", "--tree", "--body-file", str(path)]) == 0
    assert "free:" not in capsys.readouterr().out


def test_a_register_with_one_bad_entry_fails_naming_the_entry(catalog, tmp_path, capsys):
    register = catalog["raid-register"]
    body = raid_register(catalog).replace("Type: assumption", "Type: hazard")
    found = templates.check(register, templates.parse(register, body))
    assert [(finding.field, finding.rule, finding.severity) for finding in found] == [
        ("entries", "choice", templates.REFUSE)]
    assert found[0].fix.startswith("entry 'The mirror stays up' (raid-entry): Type is 'hazard': write one of risk")
    path = tmp_path / "raid.md"
    path.write_text(body, encoding="utf-8")
    assert templates.main(["check", "raid-register", "--tree", "--body-file", str(path)]) == 1
    out = capsys.readouterr().out
    assert "entry 'The mirror stays up'" in out and "The release slips" not in out


def test_each_bad_entry_is_named_by_its_own_heading_and_its_owner_line_by_its_label(catalog):
    register = catalog["raid-register"]
    body = raid_register(catalog).replace("Owner: alice\n", "").replace("Status: watched", "Status: gone")
    fixes = [finding.fix for finding in templates.check(register, templates.parse(register, body))]
    assert fixes[0].startswith("entry 'The release slips' (raid-entry): Owner is missing: write a `Owner:` line")
    assert fixes[1].startswith("entry 'The mirror stays up' (raid-entry): Status is 'gone'")
    assert len(fixes) == 2


def test_a_register_without_an_entry_refuses(catalog):
    register = catalog["raid-register"]
    body = templates.render(register, {**register.example["fields"], "entries": "Nothing yet."})
    found = templates.check(register, templates.parse(register, body))
    assert [(finding.rule, finding.severity) for finding in found] == [(templates.NODE_RULE, templates.REFUSE)]
    assert "Entries holds no entry: write each entry as a heading of its own, `### <name>`" in found[0].fix


def test_the_decision_template_s_options_node_is_the_pugh_block(catalog):
    options = catalog["decision"].field("options")
    assert (options.kind, options.node, options.pin, options.fence) == ("node", "pugh", "1.0.0", "pugh")
    assert options.nested is catalog["pugh"] and catalog["pugh"].kind == "block"
    assert not options.in_body and catalog["pugh"].actions == ()


def test_a_decision_s_pugh_fence_is_checked_by_the_pugh_block(catalog):
    decision = catalog["decision"]
    body = templates.render(decision, decision.example["fields"])
    one = re.sub(r"\n  - \{key: deck.*", "", body)
    found = templates.check(decision, templates.parse(decision, one))
    assert [(finding.field, finding.rule) for finding in found] == [("options", "checker")]
    assert found[0].fix == "pugh: the `pugh` fence's `candidates` lists 1; write at least 2"
    without = re.sub(r"```pugh.*```\n", "", body, flags=re.DOTALL)
    assert [finding.rule for finding in templates.check(decision, templates.parse(decision, without))] == [
        "required"]


def test_a_fence_node_reads_apart_from_the_section_that_holds_it_and_writes_back_in_place(catalog):
    decision = catalog["decision"]
    text = test_deck.EXAMPLE.read_text(encoding="utf-8")
    document = templates.parse(decision, text)
    assert "```pugh" not in document.fields["others"]
    assert document.fields["options"].startswith("```pugh\n") and document.fields["options"].endswith("```")
    assert templates.check(decision, document) == []
    document.fields["others"] = "Changed."
    written = templates.render(decision, document)
    assert "## What others do\n\nChanged.\n\n```pugh\n" in written
    assert written.count("```pugh") == 1


def test_a_fence_before_the_sections_it_follows_refuses_naming_each(catalog):
    decision = catalog["decision"]
    notes, _ = test_deck.DECKS["after-the-fence"]
    found = templates.check(decision, templates.parse(decision, notes["late"]))
    assert [finding.fix for finding in found] == [
        f"`## {heading}` comes after the `pugh` fence: write it before the fence"
        for heading in deck.sections()]


#: A document whose section is a node of another document, `part`.
WHOLE = f"""---
{HEAD.format(name="whole")}reader: owner
says: A whole.
{ISSUE_CREATE}rules:
  required: refuse
fields:
  - name: intro
    kind: text
    required: true
  - name: part
    node: {{node}}
    required: true
---

## Intro

<!-- intro: The intro. -->

## Part

<!-- part: The part, a document of its own. -->
"""
PART = """---
name: part
version: 1.2.0
kind: {kind}
tags: ["test"]
reader: owner
says: A part.
{applies}rules:
  required: refuse
fields:
  - name: owner
    kind: line
    label: Owner
    required: true
    says: Who owns it.
---
"""


def part(kind: str) -> str:
    """The part template of `kind`; one that is no block or entry shapes an action of its own."""
    return PART.format(kind=kind, applies="" if kind in templates.PART_KINDS else ISSUE_CREATE)


def nested(tmp_path: Path, node: str = "part@1.2.0", kind: str = "block") -> dict[str, templates.Template]:
    write_template(tmp_path, "whole", WHOLE.format(node=node))
    write_template(tmp_path, "part", part(kind))
    return templates.load(tmp_path, tree=True)


def test_a_section_node_is_checked_by_its_template_under_its_field(tmp_path):
    whole = nested(tmp_path)["whole"]
    good = templates.render(whole, {"intro": "Why.", "part": "Owner: alice"})
    assert templates.check(whole, templates.parse(whole, good)) == []
    bad = templates.render(whole, {"intro": "Why.", "part": "Nobody."})
    assert [str(finding) for finding in templates.check(whole, templates.parse(whole, bad))] == [
        "refuse: part [required]: part: Owner is missing: write a `Owner:` line: Who owns it. "
        f"(or `Not in input` where the input does not say) (why: {templates.REASONS['required']})"]


def test_a_document_s_digest_covers_its_nodes_templates(tmp_path):
    before = nested(tmp_path)
    (tmp_path / "templates" / "part.md").write_text(part("block").replace("A part.", "B part."),
                                                    encoding="utf-8")
    after = templates.load(tmp_path, tree=True)
    assert after["part"].digest != before["part"].digest
    assert after["whole"].digest != before["whole"].digest
    alone = templates._digest("whole", {"whole": {}}, {"whole": (tmp_path / "templates" / "whole.md").read_text(
        encoding="utf-8")})
    assert after["whole"].digest != alone


@pytest.mark.parametrize("node, kind, error", [
    ("gone@1.0.0", "block", "names gone, which is no template"),
    ("part@1.0.0", "block", "pins part 1.0.0, but part is at 1.2.0; pin part@1.2.0"),
    ("part", "block", "write the template and the version it pins"),
    ("part@1.2.0", "entry", "part is an entry; a node names a block or document template"),
    ("part@1.2.0", "interface", "part is an interface; a node names a block or document template"),
    ("whole@1.0.0", "block", "nests whole in a cycle"),
], ids=["no-template", "other-version", "no-pin", "entry-as-node", "interface-as-node", "cycle"])
def test_a_node_that_does_not_resolve_does_not_load(tmp_path, node, kind, error):
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        nested(tmp_path, node, kind)


@pytest.mark.parametrize("entry, kind, error", [
    ("    node: part@1.2.0\n    entries: part@1.2.0\n", "block", "is a node or a register, not both"),
    ("    entries: part@1.2.0\n", "block", "part is a block; a register names an entry template"),
    ("    node: part@1.2.0\n    fence: pugh\n    says: It.\n", "document",
     "part is a document; a node fence names a block template"),
    ("    kind: register\n", "block", "has kind register without its template"),
    ("    kind: text\n    fence: pugh\n    says: It.\n", "block", "has a fence but is no node"),
    ('    node: part@1.2.0\n    choices: ["a"]\n', "block", "is a node, checked by its template; take out choices"),
    ("    node: part@1.2.0\n    kind: text\n", "block", "is a node (node:) and takes no kind text"),
], ids=["both", "entries-of-a-block", "fence-of-a-document", "kind-alone", "fence-alone", "choices",
        "other-kind"])
def test_a_node_field_written_wrong_does_not_load(tmp_path, entry, kind, error):
    write_template(tmp_path, "part", part(kind))
    text = WHOLE.format(node="x").replace("    node: x\n", entry)
    if "fence" in entry:  # a fence has no section of its own
        text = text.replace("\n## Part\n\n<!-- part: The part, a document of its own. -->\n", "\n")
    write_template(tmp_path, "whole", text)
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.load(tmp_path, tree=True)


def test_only_a_block_or_an_entry_leaves_applies_out(tmp_path):
    write_template(tmp_path, "part", part("entry"))
    assert templates.load(tmp_path, tree=True)["part"].actions == ()
    write_template(tmp_path, "part", PART.format(kind="document", applies=""))
    with pytest.raises(templates.TemplateError, match="applies.actions is required"):
        templates.load(tmp_path, tree=True)


# Fields honest about their source (docs/templates.md "Fill"): "Not in input" and quotes


def every_field_not_in_input(template: templates.Template) -> dict[str, object]:
    """Every field of `template` filled with "Not in input", each in the form its kind takes."""
    forms = {"list": ["Not in input"], "issue": ["Not in input"],
             "checklist": [{"done": False, "text": "Not in input"}],
             "object": [{"key": "Not in input", "value": ""}]}
    return {item.name: forms.get(item.kind, templates.NOT_IN_INPUT) for item in template.fields}


def test_not_in_input_passes_every_field_of_every_template_whatever_its_rules(catalog):
    for template in catalog.values():
        if template.is_adapter or template.is_snippet:  # a snippet's writer is code, never a fill
            continue
        for values in (every_field_not_in_input(template),
                       {item.name: templates.NOT_IN_INPUT for item in template.fields}):
            values = templates.answer(template, values)
            title = next((values[item.name] for item in template.fields if item.source == "title"),
                         None)
            body = templates.render(template, values)
            found = templates.check(template, templates.parse(template, body, title))
            assert found == [], (template.name, found)
            assert body.count(templates.NOT_IN_INPUT) == sum(not item.source for item in template.fields)


def test_not_in_input_reads_back_from_a_section_of_any_kind(tmp_path):
    write_template(tmp_path, "obj", OBJECT_TEMPLATE)
    template = templates.load(tmp_path, tree=True)["obj"]
    body = templates.render(template, {"meta": "Not in input."})
    assert "## Meta\n\nNot in input.\n" in body
    document = templates.parse(template, body)
    assert document.fields == {"meta": "Not in input."}
    assert templates.check(template, document) == []
    assert templates.render(template, document) == body


def test_a_required_field_left_empty_still_refuses_beside_not_in_input(catalog):
    work = catalog["work"]
    values = every_field_not_in_input(work)
    values["goal"] = ""
    found = templates.check(work, templates.parse(work, templates.render(work, templates.answer(work, values)),
                                                  values["title"]))
    assert [(item.field, item.rule) for item in found if item.severity == "refuse"] == [("goal", "required")]
    assert "Not in input" in found[0].fix


def test_the_schema_offers_not_in_input_among_a_choice_s_values(catalog):
    shaped = templates.schema(catalog["work"])["properties"]["package_kind"]
    assert templates.NOT_IN_INPUT in shaped["enum"]


QUOTE_TEMPLATE = """---
name: {name}
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: "A finding: what was seen, in the reporter's words."
applies:
  actions: ["file.write"]
  paths: ["findings/*.md"]
rules:
  required: refuse
fields:
  - name: seen
    kind: text
    required: true
    quote: true
  - name: impact
    kind: list
    required: true
---

## Seen

<!-- seen: What the reporter saw, quoted word for word: "..." or a > line. -->

## Impact

<!-- impact: One item per effect. -->
"""

RAW = ("Ticket from Alice, Monday:\n\nThe export stops at row 1000 and the\nfile is cut off. "
       "It happens on every run since the update.\n")


def quote_template(root: Path) -> templates.Template:
    write_template(root, "finding", QUOTE_TEMPLATE.format(name="finding"))
    return templates.load(root, folder=root / "templates")["finding"]


def quote_findings(template: templates.Template, seen: object, raw: str | None = RAW) -> list[templates.Finding]:
    body = templates.render(template, {"seen": seen, "impact": ["Exports are incomplete."]})
    return [item for item in templates.check(template, templates.parse(template, body), raw=raw)
            if item.rule == templates.QUOTE_RULE]


@pytest.mark.parametrize("seen", [
    'Alice reports: "The export stops at row 1000".',
    '"stops at row 1000 and the file is cut off"',  # a line break in the input is a space
    "The reporter wrote:\n\n> It happens on every run since the update.",
    "“every run since the update”",
    "Not in input",
])
def test_a_quote_the_raw_input_holds_word_for_word_passes(tmp_path, seen):
    assert quote_findings(quote_template(tmp_path), seen) == []


@pytest.mark.parametrize("seen, named", [
    ('Alice reports: "The export stops at row 2000".', '"The export stops at row 2000"'),
    ('"The export stops" and "the screen goes black"', '"the screen goes black"'),
    ('"the export stops at row 1000"', '"the export stops at row 1000"'),  # case counts
    ("> It fails on every run.", '"It fails on every run."'),
])
def test_an_invented_quote_is_refused_naming_it(tmp_path, seen, named):
    found = quote_findings(quote_template(tmp_path), seen)
    assert [(item.field, item.severity) for item in found] == [("seen", "refuse")]
    assert named in found[0].fix and "does not hold" in found[0].fix


def test_a_quote_field_without_a_quote_is_refused_with_or_without_the_raw_input(tmp_path):
    template = quote_template(tmp_path)
    for raw in (RAW, None):
        found = quote_findings(template, "The export breaks.", raw)
        assert [item.severity for item in found] == ["refuse"]
        assert "quotes nothing" in found[0].fix
    assert quote_findings(template, '"anything at all"', None) == []


def test_a_field_s_quote_key_loads_and_shows_in_its_shape(tmp_path):
    template = quote_template(tmp_path)
    assert template.field("seen").quote and not template.field("impact").quote
    assert templates.field_shape(template.field("seen"))["quote"] is True
    assert "quote" not in templates.field_shape(template.field("impact"))


# Fill (docs/templates.md "Fill"): one command takes template, prompt, raw input and fields


FILLED = {"seen": 'Alice wrote: "The export stops at row 1000".', "impact": ["Exports are incomplete."]}


def fill_project(root: Path) -> tuple[templates.Template, Path, list[str]]:
    """The quote template in `root`'s templates/, a raw input file, and the options that read them."""
    template = quote_template(root)
    raw = root / "ticket.txt"
    raw.write_text(RAW, encoding="utf-8")
    return template, raw, ["--templates", str(root / "templates"), "--root", str(root)]


def test_a_fill_from_a_raw_input_file_writes_a_document_that_passes_check(tmp_path, capsys):
    template, raw, where = fill_project(tmp_path)
    target = tmp_path / "findings" / "export.md"
    code = templates.main(["fill", "finding", "--path", str(target), "--prompt", "File Alice's ticket.",
                           "--input", str(raw), "--fields-json", json.dumps(FILLED), *where])
    out = capsys.readouterr()
    assert code == 0, out
    assert out.out == "wrote findings/export.md: finding 1.0.0\n"
    written = target.read_text(encoding="utf-8")
    assert written == templates.render(template, FILLED)
    assert written.startswith(f"---\n{recorded(template)}---\n")
    assert templates.main(["check", "--path", str(target), *where]) == 0
    assert capsys.readouterr().out == "finding: no findings\n"


def test_a_fill_with_an_invented_quote_is_refused_and_writes_nothing(tmp_path, capsys):
    _, raw, where = fill_project(tmp_path)
    target = tmp_path / "findings" / "export.md"
    invented = {**FILLED, "seen": 'Alice wrote: "The export crashes the server".'}
    code = templates.main(["fill", "finding", "--path", str(target), "--input", str(raw),
                           "--fields-json", json.dumps(invented), *where])
    out = capsys.readouterr().out
    assert code == 1 and not target.exists()
    assert 'refuse: seen [quote]: Seen quotes "The export crashes the server", which the raw input ' \
           "does not hold" in out
    assert out.splitlines()[-1] == "templates.py fill: nothing was written; fix every finding and fill again"


def test_a_fill_names_every_finding_at_once(tmp_path, capsys):
    _, raw, where = fill_project(tmp_path)
    code = templates.main(["fill", "finding", "--path", str(tmp_path / "findings" / "x.md"),
                           "--input-text", RAW, "--fields-json", json.dumps({"seen": "No quote."}),
                           *where])
    out = capsys.readouterr().out
    assert code == 1 and "[quote]" in out and "impact [required]" in out


def test_a_fill_takes_not_in_input_for_a_field_the_raw_input_does_not_answer(tmp_path, capsys):
    _, raw, where = fill_project(tmp_path)
    target = tmp_path / "findings" / "gap.md"
    fields = {"seen": FILLED["seen"], "impact": "Not in input"}
    assert templates.main(["fill", "finding", "--path", str(target), "--input", str(raw),
                           "--fields-json", json.dumps(fields), *where]) == 0
    assert "## Impact\n\nNot in input\n" in target.read_text(encoding="utf-8")


def test_a_fill_keeps_the_head_of_the_file_it_fills_again(tmp_path, capsys):
    template, raw, where = fill_project(tmp_path)
    target = tmp_path / "findings" / "export.md"
    target.parent.mkdir()
    target.write_text("---\nid: F1\n---\n\n# Export\n\n## Seen\n\nOld.\n", encoding="utf-8")
    assert templates.main(["fill", "finding", "--path", str(target), "--input", str(raw),
                           "--fields-json", json.dumps(FILLED), *where]) == 0
    written = target.read_text(encoding="utf-8")
    assert written.startswith(f"---\nid: F1\n{recorded(template)}---\n\n# Export\n\n## Seen\n\n")
    assert "Old." not in written and templates.parse(template, written).fields == FILLED


def test_a_fill_without_fields_answers_the_instructions_guidance_and_empty_draft(tmp_path, capsys):
    template, _, where = fill_project(tmp_path)
    (tmp_path / "guidance").mkdir()
    (tmp_path / "guidance" / "quote-first.md").write_text(
        "---\nname: quote-first\ndescription: 'Quote before you summarise.'\n---\n\nQuote first.\n",
        encoding="utf-8")
    code = templates.main(["fill", "finding", "--prompt", "File Alice's ticket.", *where])
    answer = json.loads(capsys.readouterr().out)
    assert code == 0
    assert list(answer)[:5] == ["template", "prompt", "says", "rules", "guidance"]
    assert answer["template"] == "finding" and answer["prompt"] == "File Alice's ticket."
    assert any("Not in input" in rule for rule in answer["rules"])
    assert any(rule.startswith("Seen: quote the raw input word for word") for rule in answer["rules"])
    assert [note["name"] for note in answer["guidance"]] == ["quote-first"]
    assert answer["guidance"][0]["text"] == "Quote first."
    assert answer["draft"] == templates.draft(template)
    assert {key: answer[key] for key in ("fields", "field_says", "field_shape", "schema")} == {
        key: value for key, value in templates.draft_fields(template).items()
        if key in ("fields", "field_says", "field_shape", "schema")}


def test_a_fill_of_an_issue_template_prints_or_writes_the_markdown_to_file(tmp_path, capsys, catalog):
    work = catalog["work"]
    values = work_fields(catalog)
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps(values), encoding="utf-8")
    raw = ["--input-text", "The person asked for one fill command.", "--tree"]
    assert templates.main(["fill", "work", "--fields", str(fields), *raw]) == 0
    assert capsys.readouterr().out == templates.render(work, values)
    out = tmp_path / "issue.md"
    assert templates.main(["fill", "work", "--fields", str(fields), "--out", str(out), *raw]) == 0
    assert capsys.readouterr().out == f"wrote {out}: work {work.version}\n"
    assert out.read_text(encoding="utf-8") == templates.render(work, values)


@pytest.mark.parametrize("arguments, error", [
    (["finding", "--fields-json", "{}"], "give the raw input"),
    (["finding", "--input-text", "x", "--fields-json", "{}"], "writes its file: give --path"),
    (["--path", "notes/x.md", "--input-text", "x", "--fields-json", "{}"], "no template claims notes/x.md"),
    (["finding", "--path", "findings/x.md", "--out", "y.md", "--input-text", "x", "--fields-json", "{}"],
     "--out"),
    (["finding", "--path", "notes/x.md", "--input-text", "x", "--fields-json", "{}"],
     "finding claims no path notes/x.md"),
    (["finding", "--input", "missing.txt", "--fields-json", "{}"], "cannot read --input"),
])
def test_fill_usage_errors_exit_2_and_write_nothing(tmp_path, capsys, arguments, error):
    _, _, where = fill_project(tmp_path)
    for index, argument in enumerate(arguments):
        if argument in ("--path", "--input", "--out"):
            arguments[index + 1] = str(tmp_path / arguments[index + 1])
    code = templates.main(["fill", *arguments, *where])
    assert code == 2 and error in capsys.readouterr().err
    assert not (tmp_path / "findings").exists() and not (tmp_path / "y.md").exists()


# Template repositories (docs/templates.md "Template repositories"): se.toml [templates] repositories
# lists components pinned as any other; a name resolves from the project's templates/, then each
# repository in that order, then SE's, and a repository not placed at its pin refuses.


#: The project's origin, on a host SE lists nothing of, so a component is read beside it, at the
#: address the machine's [urls] rewrites to the fake upstreams (as tests/test_se_modules.py's world).
TEMPLATE_ORIGIN = "https://git.example.org/team/project"


def template_repository(folder: Path, templates_by_name: dict[str, str]) -> str:
    """A fake template repository at `folder` holding `templates/<name>.md`; its commit."""
    fake_git.init(folder, "-b", "main")
    for name, text in templates_by_name.items():
        write_template(folder, name, text)
    commit_all(folder)
    return git_door.run("-C", str(folder), "rev-parse", "HEAD").stdout.strip()


def template_project(tmp_path: Path, pins: dict[str, str], listed: list[str]) -> tuple[Path, Path]:
    """A project whose se.toml pins `pins` as components and lists `listed` as its template
    repositories, and the machine's local.toml that finds them under `tmp_path / "upstream"`."""
    project = fake_git.init(tmp_path / "project")
    fake_git.git("-C", str(project), "remote", "add", "origin", TEMPLATE_ORIGIN)
    tables = "".join(f'[components.{name}]\nref = "{ref}"\n\n' for name, ref in pins.items())
    (project / "se.toml").write_text(f"{tables}[templates]\nrepositories = {json.dumps(listed)}\n",
                                     encoding="utf-8")
    local = tmp_path / "home" / "local.toml"
    local.parent.mkdir(parents=True)
    local.write_text(f'[urls]\n"https://git.example.org/team/" = "{(tmp_path / "upstream").as_posix()}/"\n',
                     encoding="utf-8")
    return project, local


def synced(project: Path, local: Path, capsys) -> None:
    import se_modules
    capsys.readouterr()
    code = se_modules.main(["--root", str(project), "--local", str(local), "sync"])
    assert code == 0, capsys.readouterr()


def test_a_template_repository_s_template_fills(tmp_path, fake_git_door, capsys, monkeypatch):
    shared = template_repository(tmp_path / "upstream" / "shared", {
        "note": MINIMAL.format(name="note", extra=ISSUE_CREATE)})
    project, local = template_project(tmp_path, {"shared": shared}, ["shared"])
    synced(project, local, capsys)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    code = templates.main(["fill", "note", "--root", str(project), "--input-text", "Ship the export.",
                           "--fields-json", json.dumps({"goal": "Ship the export."})])
    out = capsys.readouterr()
    assert code == 0, out
    assert "<!-- se:template shared/note 1.0.0 sha256:" in out.out
    assert "## Goal\n\nShip the export." in out.out


def test_a_name_resolves_from_the_project_then_each_repository_in_order_then_se(
        tmp_path, fake_git_door, capsys, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    se_name = next(iter(templates.load(templates.ROOT)))
    first = template_repository(tmp_path / "upstream" / "first", {
        "note": MINIMAL.format(name="note", extra=ISSUE_CREATE),
        "own": MINIMAL.format(name="own", extra=ISSUE_CREATE),
        se_name: MINIMAL.format(name=se_name, extra=ISSUE_CREATE)})
    second = template_repository(tmp_path / "upstream" / "second", {
        "note": MINIMAL.format(name="note", extra=ISSUE_CREATE),
        "later": MINIMAL.format(name="later", extra=ISSUE_CREATE)})
    project, local = template_project(tmp_path, {"first": first, "second": second}, ["first", "second"])
    write_template(project, "own", MINIMAL.format(name="own", extra=ISSUE_CREATE))
    synced(project, local, capsys)
    resolved = templates.catalog(project, tree=True)
    assert {name: resolved[name].repository for name in ("own", "note", "later", se_name)} == {
        "own": "project", "note": "first", "later": "second", se_name: "first"}
    assert set(templates.load(templates.ROOT)) <= set(resolved)


def test_an_unfetchable_pin_refuses_the_fill_with_the_remedy(tmp_path, fake_git_door, capsys, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    template_repository(tmp_path / "upstream" / "shared", {
        "note": MINIMAL.format(name="note", extra=ISSUE_CREATE)})
    project, local = template_project(tmp_path, {"shared": "b" * 40}, ["shared"])
    import se_modules
    assert se_modules.main(["--root", str(project), "--local", str(local), "sync"]) == 1
    capsys.readouterr()
    code = templates.main(["fill", "note", "--root", str(project), "--input-text", "x",
                           "--fields-json", json.dumps({"goal": "x"})])
    err = capsys.readouterr().err
    assert code == 2
    assert "template repository shared: its pin ref bbbbbbbbbbbb is not fetched" in err
    assert "run `se_modules.py sync shared`" in err


@pytest.mark.parametrize("toml, error", [
    ('[templates]\nrepositories = ["absent"]\n', "declares no [components.absent]"),
    ('[templates]\nrepositories = "shared"\n', "must be a list of component names"),
    ('[components.shared]\nref = "' + "a" * 40 + '"\n\n[templates]\nrepositories = ["shared", "Shared"]\n',
     "names a repository twice"),
])
def test_a_template_repository_listed_wrong_refuses_naming_the_remedy(tmp_path, toml, error, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    (tmp_path / "se.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(templates.TemplateError, match=re.escape(error)):
        templates.catalog(tmp_path, tree=True)


def test_a_template_repository_without_templates_refuses(tmp_path, fake_git_door, capsys, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    folder = tmp_path / "upstream" / "bare"
    fake_git.init(folder, "-b", "main")
    (folder / "README.md").write_text("no templates\n", encoding="utf-8")
    commit_all(folder)
    ref = git_door.run("-C", str(folder), "rev-parse", "HEAD").stdout.strip()
    project, local = template_project(tmp_path, {"bare": ref}, ["bare"])
    synced(project, local, capsys)
    with pytest.raises(templates.TemplateError, match=r"holds no templates/ at its pin"):
        templates.catalog(project, tree=True)


def test_a_project_without_template_repositories_resolves_its_own_then_se_s(tmp_path, fake_git_door):
    write_template(tmp_path, "own", MINIMAL.format(name="own", extra=ISSUE_CREATE))
    resolved = templates.catalog(tmp_path, tree=True)
    assert resolved["own"].repository == "project"
    assert {template.repository for name, template in resolved.items() if name != "own"} == {"se"}


# Overlays (docs/templates.md "Template repositories"; scripts/templates.py: Overlays):
# templates/<name>.overlay.md extends its template and only adds or tightens; a loosening refuses.

#: A template with a choice, a limit and a rule an overlay can loosen, for the overlay tests.
OVERLAID = """---
name: note
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: A note.
applies:
  actions: ["issue.create"]
rules:
  required: refuse
  words: warn
fields:
  - name: goal
    kind: text
    required: true
    max_words: 40
  - name: status
    kind: choice
    label: Status
    says: "open or closed."
    choices: ["open", "closed"]
---

## Goal

<!-- goal: What the note is for. -->
"""


def overlay(root: Path, name: str, text: str) -> None:
    (root / "templates").mkdir(exist_ok=True)
    (root / "templates" / f"{name}.overlay.md").write_text(text, encoding="utf-8")


def test_an_overlay_adds_instructions_fields_tags_and_rules_and_its_digest_is_recorded(tmp_path):
    write_template(tmp_path, "note", OVERLAID)
    plain = templates.load(tmp_path, folder=tmp_path / "templates")["note"]
    overlay(tmp_path, "note", """---
extends: note
says: Agents keep it short.
tags: ["meeting"]
rules:
  duplicate: refuse
fields:
  - name: goal
    max_words: 20
  - name: owner
    kind: line
    required: true
---

## Goal

<!-- goal: One sentence. -->

## Owner

<!-- owner: Who keeps the note. -->
""")
    note = templates.load(tmp_path, folder=tmp_path / "templates")["note"]
    assert note.says == "A note. Agents keep it short."
    assert note.tags == ("test", "meeting")
    assert note.severity("duplicate") == "refuse" and note.severity("words") == "warn"
    assert [item.name for item in note.fields] == ["goal", "status", "owner"]
    assert note.field("goal").says == "What the note is for. One sentence."
    assert note.field("goal").max_words == 20
    assert (note.field("owner").heading, note.field("owner").required) == ("Owner", True)
    # The marker's digest covers the overlay, so a document records the overlay its fill applied.
    assert note.digest != plain.digest and note.version == plain.version
    text = (tmp_path / "templates" / "note.md").read_text(encoding="utf-8")
    added = (tmp_path / "templates" / "note.overlay.md").read_text(encoding="utf-8")
    assert note.digest == "sha256:" + hashlib.sha256(text.encode() + b"\0" + added.encode() + b"\0").hexdigest()
    found = templates.check(note, templates.parse(note, templates.render(note, {"goal": "Ship it."})))
    assert ("owner", "required", "refuse") in {(item.field, item.rule, item.severity) for item in found}


def test_a_template_that_extends_an_overlaid_one_inherits_what_the_overlay_adds(tmp_path):
    write_template(tmp_path, "note", OVERLAID)
    write_template(tmp_path, "child", """---
name: child
version: 1.0.0
kind: document
tags: ["test"]
extends: note
---
""")
    overlay(tmp_path, "note", "---\nextends: note\nfields:\n  - name: owner\n    kind: line\n---\n\n"
            "## Owner\n\n<!-- owner: Who keeps it. -->\n")
    loaded = templates.load(tmp_path, folder=tmp_path / "templates")
    assert [item.name for item in loaded["child"].fields] == ["goal", "status", "owner"]


@pytest.mark.parametrize("text, refusal", [
    ("rules:\n  required: warn\n", "it loosens rule required from refuse to warn"),
    ('rules:\n  words: "off"\n', "it loosens rule words from warn to off"),
    ("fields:\n  - name: goal\n    required: false\n", "field goal: required is turned off"),
    ("fields:\n  - name: goal\n    max_words: 80\n", "field goal: max_words is raised from 40 to 80"),
    ("fields:\n  - name: goal\n    max_words: 0\n", "field goal: max_words is raised from 40 to none"),
    ("fields:\n  - name: goal\n    none_ok: true\n", "field goal: none_ok is turned on"),
    ("fields:\n  - name: goal\n    kind: line\n", "field goal: kind changes from 'text' to 'line'"),
    ('fields:\n  - name: status\n    choices: ["open", "closed", "parked"]\n',
     "field status: choices widen from open, closed to open, closed, parked"),
    ('fields:\n  - name: status\n    says: "anything."\n', None),
    ("remove: [\"goal\"]\n", "an overlay only adds or tightens; remove is the template's to say"),
    ("applies:\n  actions: [\"issue.edit\"]\n", "applies is the template's to say"),
    ("version: 2.0.0\n", "version is the template's to say"),
])
def test_a_loosening_overlay_is_refused_naming_what_it_loosens(tmp_path, text, refusal):
    write_template(tmp_path, "note", OVERLAID)
    overlay(tmp_path, "note", f"---\nextends: note\n{text}---\n")
    if refusal is None:  # a says the overlay gives is added to the field's, never in its place
        assert templates.load(tmp_path, folder=tmp_path / "templates")["note"].field(
            "status").says == "open or closed. anything."
        return
    with pytest.raises(templates.TemplateError, match=re.escape(refusal)) as raised:
        templates.load(tmp_path, folder=tmp_path / "templates")
    assert str(raised.value).startswith(str(tmp_path / "templates" / "note.overlay.md"))


@pytest.mark.parametrize("text, refusal", [
    ("---\nextends: other\n---\n", "extends is 'other'; an overlay extends its template, `extends: note`"),
    ("---\nextends: note\n---\n\n## Aim\n\n<!-- goal: More. -->\n",
     "section Aim adds to field goal, whose heading is 'Goal'"),
    ("---\nextends: note\n---\n\n## Owner\n\n<!-- owner: Who. -->\n",
     "section Owner adds to field owner, which neither note nor the overlay's fields hold"),
    ("---\nextends: note\nfields:\n  - name: owner\n    kind: line\n---\n",
     "field owner is added without its section"),
])
def test_an_overlay_that_does_not_fit_its_template_is_refused_with_the_remedy(tmp_path, text, refusal):
    write_template(tmp_path, "note", OVERLAID)
    overlay(tmp_path, "note", text)
    with pytest.raises(templates.TemplateError, match=re.escape(refusal)):
        templates.load(tmp_path, folder=tmp_path / "templates")


def test_an_overlay_without_its_template_beside_it_is_refused(tmp_path):
    write_template(tmp_path, "note", OVERLAID)
    overlay(tmp_path, "other", "---\nextends: other\n---\n")
    with pytest.raises(templates.TemplateError, match=re.escape(
            "an overlay of 'other', which this templates/ does not hold")):
        templates.load(tmp_path, folder=tmp_path / "templates")


def test_an_overlay_applies_to_its_own_repository_s_template_only(tmp_path, fake_git_door, capsys,
                                                                   monkeypatch):
    """A name resolves to the first repository holding it; another repository's overlay of that
    name lies beside a template the name does not reach, and adds nothing."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    template_repository(tmp_path / "upstream" / "shared", {"note": OVERLAID})
    (tmp_path / "upstream" / "shared" / "templates" / "note.overlay.md").write_text(
        "---\nextends: note\ntags: [\"shared\"]\n---\n", encoding="utf-8")
    commit_all(tmp_path / "upstream" / "shared")
    shared = git_door.run("-C", str(tmp_path / "upstream" / "shared"), "rev-parse", "HEAD").stdout.strip()
    project, local = template_project(tmp_path, {"shared": shared}, ["shared"])
    synced(project, local, capsys)
    assert templates.catalog(project, tree=True)["note"].tags == ("test", "shared")
    write_template(project, "note", OVERLAID)
    assert templates.catalog(project, tree=True)["note"].tags == ("test",)


# Template manifests (templates.py "Template manifests"): obs's worked example, its three template
# nodes and an ordinary chapter, as the shared cases hold it (tests/template_cases.py)

#: Each guidance text of the fixture's nodes, which the fill hands the agent and the document never holds.
GUIDANCE = ("The problem the product solves, and for whom.", "Every later section is judged against it.",
            "One paragraph of at most five sentences.", "The product brief.",
            "What the product does and what it leaves to others.", "Two lists, in scope and out of scope.",
            "The risks that could stop the product, each with its owner.",
            "A risk without an owner is not handled.")
MANIFEST_FILLED = {"purpose": "The pump controller keeps the tank level between its limits for the plant operators.",
          "scope": "- In scope: the level loop and its alarms.\n- Out of scope: the pump drives.",
          "risks": "The level sensor may drift; the instrument team owns its calibration."}
BRIEF = "The product brief: the pump controller keeps the tank level for the plant operators."
OBS_BUILDS = ("tool: obs-document, in obs's own Python environment, builds the filled document, so only "
              "the real obs proves it reads the document's derived_from; it runs only as a process")


def manifest_folder(root: Path, **changed: str | None) -> Path:
    """The fixture's `templates/` under `root`, each of `changed` as `_manifest_files` takes it."""
    folder = root / "templates"
    for name, text in template_cases._manifest_files(**changed).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    return folder


def filled_by_main(capsys, folder: Path, *arguments: str) -> tuple[int, str, str]:
    code = templates.main(["fill", "requirements", "--templates", str(folder), *arguments])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_template_manifest_fills_a_document_that_derives_from_it_and_holds_none_of_its_guidance(
        tmp_path, capsys):
    folder = manifest_folder(tmp_path, requirements_dot_overlay_dot_md=None)
    code, out, _ = filled_by_main(capsys, folder)
    told = json.loads(out)
    assert code == 0 and told["version"] == "2"
    assert told["field_says"] == {
        "purpose": "The problem the product solves, and for whom. Why: Every later section is judged "
                   "against it. Form: One paragraph of at most five sentences. Sources: The product brief.",
        "scope": "What the product does and what it leaves to others. Form: Two lists, in scope and out "
                 "of scope.",
        "risks": "The risks that could stop the product, each with its owner. Why: A risk without an "
                 "owner is not handled."}
    assert all(text in told["draft"] for text in GUIDANCE)
    assert told["schema"]["required"] == ["purpose", "scope"]  # the mandatory gates; risks is judgment
    document = tmp_path / "documents" / "pump.md"
    code, out, _ = filled_by_main(capsys, folder, "--fields-json", json.dumps(MANIFEST_FILLED), "--input-text", BRIEF,
                                  "--out", str(document))
    assert (code, out) == (0, f"wrote {document}: requirements 2\n")
    text = document.read_text(encoding="utf-8")
    template = templates.load(tmp_path, folder=folder)["requirements"]
    assert text.startswith('---\nderived_from: {template: requirements, version: "2"}\n'
                           f"overlay: {template.digest}\n---\n")
    assert [line for line in text.splitlines() if line.startswith("#")] == ["## Purpose", "## Scope", "## Risks"]
    assert not [part for part in (*GUIDANCE, templates.SLOT, "<!--", "Why:") if part in text]
    parsed = templates.parse(template, text)
    assert (parsed.fields, parsed.recorded) == (MANIFEST_FILLED, "2")
    assert template.manifest and template.actions == () and template.kind == "document"


def test_a_missing_mandatory_section_and_a_leftover_slot_each_refuse_naming_the_section(tmp_path, capsys):
    folder = manifest_folder(tmp_path, requirements_dot_overlay_dot_md=None)
    document = tmp_path / "pump.md"
    missing = {key: value for key, value in MANIFEST_FILLED.items() if key != "scope"}
    code, out, _ = filled_by_main(capsys, folder, "--fields-json", json.dumps(missing), "--input-text", BRIEF,
                                  "--out", str(document))
    assert code == 1 and "scope [required]: Scope is missing: write `## Scope`" in out
    assert "nothing was written" in out and not document.exists()
    left = {**MANIFEST_FILLED, "risks": "The sensor may drift.\n\n{{slot}}"}
    code, out, _ = filled_by_main(capsys, folder, "--fields-json", json.dumps(left), "--input-text", BRIEF,
                                  "--out", str(document))
    assert code == 1 and "risks [slot]: section Risks still holds the fill slot {{slot}}" in out
    assert not document.exists()
    template = templates.load(tmp_path, folder=folder)["requirements"]
    quoted = {**MANIFEST_FILLED, "risks": "Write `{{slot}}` literally:\n\n```\n{{slot}}\n```"}
    assert templates.fill(template, quoted, BRIEF)[1] == []  # a slot in code is literal and no slot
    judged = {key: value for key, value in MANIFEST_FILLED.items() if key != "risks"}
    assert templates.fill(template, judged, BRIEF)[1] == []  # a judgment gate may stay empty


def test_stale_lists_a_document_only_once_its_template_s_version_moved(tmp_path, capsys):
    folder = manifest_folder(tmp_path, requirements_dot_overlay_dot_md=None)
    documents = tmp_path / "documents"
    assert filled_by_main(capsys, folder, "--fields-json", json.dumps(MANIFEST_FILLED), "--input-text", BRIEF,
                          "--out", str(documents / "pump.md"))[0] == 0
    (documents / "notes.md").write_text("# Notes\n\nNo template.\n", encoding="utf-8")
    (documents / ".hidden").mkdir()
    (documents / ".hidden" / "old.md").write_text(
        '---\nderived_from: {template: requirements, version: "1"}\n---\n', encoding="utf-8")
    stale = lambda: (templates.main(["stale", "--path", str(documents), "--templates", str(folder)]),
                     capsys.readouterr())
    code, out = stale()
    assert (code, out.out, out.err) == (0, "", "")
    manifest = folder / "requirements" / "manifest.md"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('version: "2"', 'version: "2.1"'),
                        encoding="utf-8")
    (documents / "gone.md").write_text('---\nderived_from: {template: gone, version: "1"}\n---\n',
                                       encoding="utf-8")
    code, out = stale()
    assert (code, out.out) == (0, "pump.md: derived from requirements 2; the template is at 2.1\n")
    assert out.err == "warning: gone.md: derived from gone 1, which is no template here\n"
    assert templates.main(["stale", "--path", str(tmp_path / "none"), "--templates", str(folder)]) == 2
    assert "is no folder" in capsys.readouterr().err


def test_an_overlay_adds_to_a_template_manifest_and_never_loosens_it(tmp_path):
    template = templates.load(tmp_path, folder=manifest_folder(tmp_path))["requirements"]
    risks = template.field("risks")
    assert risks.required and risks.says.endswith("not handled. Name each owner by role.")
    assert template.tags == ("requirements",) and template.says.endswith("Agents quote the brief.")
    plain = templates.load(tmp_path, folder=manifest_folder(tmp_path / "plain",
                                                            requirements_dot_overlay_dot_md=None))
    assert template.digest != plain["requirements"].digest
    loose = template_cases.MANIFEST_OVERLAY.replace("  - name: risks\n    required: true\n",
                                                    "  - name: purpose\n    required: false\n")
    with pytest.raises(templates.TemplateError, match="field purpose: required is turned off"):
        templates.load(tmp_path, folder=manifest_folder(tmp_path / "loose",
                                                        requirements_dot_overlay_dot_md=loose))


def test_a_project_s_template_manifest_resolves_before_se_s_templates(tmp_path):
    manifest_folder(tmp_path, requirements_dot_overlay_dot_md=None)
    resolved = templates.catalog(tmp_path, tree=True)
    assert resolved["requirements"].repository == templates.PROJECT_REPOSITORY
    assert resolved["requirements"].path == "templates/requirements/manifest.md"
    assert resolved["work"].repository == templates.SE_REPOSITORY


@pytest.mark.parametrize("front, named", [
    ('---\nderived_from: {template: requirements, version: "2"}\n---\n', ("requirements", "2")),
    ('---\ntitle: T\nderived_from:\n  template: se/work\n  version: "1.0.0"\nid: 1\n---\n', ("se/work", "1.0.0")),
    ("---\nderived_from: {template: x, version: 3}\n---\n", ("x", "3")),
    ("---\nderived_from: {template: x}\n---\n", ("", "")),
    ("---\nderived_from: x\n---\n", ("", "")),
    ("---\nderived_from: {template: x, version: 1.5}\n---\n", ("", "")),
])
def test_derived_from_reads_a_flow_mapping_or_an_indented_one(front, named):
    found = templates.derived_from(front)
    assert found is not None and found[2:] == named
    assert front[found[0]:found[1]].startswith("derived_from:")
    assert templates.derived_from("---\ntitle: T\n---\n") is None


@pytest.mark.spawns(OBS_BUILDS)
def test_obs_builds_the_document_se_fills_from_obs_s_worked_example(tmp_path, obs, capsys):
    note = (obs / "spec" / "capabilities" / "templates.md").read_text(encoding="utf-8")
    folder = tmp_path / "templates"
    for match in re.finditer(r"^```text template/(\S+)\n(.*?)^```$", note, re.MULTILINE | re.DOTALL):
        (folder / "requirements" / match.group(1)).parent.mkdir(parents=True, exist_ok=True)
        (folder / "requirements" / match.group(1)).write_text(match.group(2), encoding="utf-8")
    assert sorted(path.name for path in (folder / "requirements").iterdir()) == [
        "manifest.md", "purpose.md", "risks.md", "scope.md"]
    vault = tmp_path / "document"
    assert filled_by_main(capsys, folder, "--fields-json", json.dumps(MANIFEST_FILLED), "--input-text", BRIEF,
                          "--out", str(vault / "manifest.md"))[0] == 0
    parsed = tmp_path / "document.json"
    code = build_docs.obs_document(obs, ["--source", str(vault / "manifest.md"), "--document", str(parsed)],
                                   "templates", adapter=False)
    assert code == 0, capsys.readouterr().err
    built = parsed.read_text(encoding="utf-8")
    assert '"derived-from"' in built and '"guidance"' not in built and "{{slot}}" not in built



# Reasons and corrections (SE#1852): every rule says why it holds, and a fill corrects what cannot
# change the document's meaning, reports it and records it.


def brief() -> templates.Template:
    return templates._loaded([(templates.PROJECT_REPOSITORY, {"brief.md": template_cases.BRIEF_TEMPLATE},
                               lambda file: f"{templates.TEMPLATES}/{file}")])["brief"]


def brief_document() -> str:
    template = brief()
    return templates.fill(template, dict(template.example["fields"]), template_cases.RAW)[0]


#: A brief that deviates from its template only in what the correction pass corrects.
TRIVIAL = {"## Goal\n": "## goal\n", "## Blocked by\n\nNone": "### blocked by:\n\nnone.",
           "Every brief says what it is for.": "Every brief says what it is for.   ",
           "- It runs long.": "* It runs long.\n+ It costs time.  ", "1. Write it.": "1) Write it.",
           "Kept short.": ">Kept short."}


def trivially(text: str) -> str:
    for before, after in TRIVIAL.items():
        text = text.replace(before, after)
    return text


def content_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def test_every_rule_carries_its_reason_once_and_every_finding_and_refusal_line_names_it():
    import se_templates
    rules = {*templates.REFUSE_RULES, *templates.WARN_RULES, *templates.ADAPTER_RULES, templates.NODE_RULE,
             templates.VERSION_RULE, templates.QUOTE_RULE, templates.SLOT_RULE, templates.PRIVATE_RULE,
             se_templates.NAME_RULE, se_templates.DANGLING_RULE}
    assert set(templates.REASONS) == rules
    assert all(reason and not reason.endswith(".") for reason in templates.REASONS.values())
    finding = templates.Finding("goal", "required", templates.REFUSE, "Goal is empty: write `## Goal`")
    assert finding.why == templates.REASONS["required"]
    assert str(finding) == f"refuse: goal [required]: Goal is empty: write `## Goal` (why: {finding.why})"
    line = templates.report("x", brief(), [finding], refused=True).splitlines()[1]
    assert line == f"  Goal: empty: write `## Goal` (why: {finding.why})"


def test_a_fill_with_only_trivial_deviations_parses_lists_each_correction_and_is_the_corrected_document():
    template = brief()
    base = brief_document()
    document, found, corrections = templates.fill(template, {}, template_cases.RAW, body=trivially(base))
    assert [item for item in found if item.severity == templates.REFUSE] == []
    assert [(fix.field, fix.kinds) for fix in corrections] == [
        ("blocked_by", ("heading",)), ("goal", ("heading",)), ("goal", ("whitespace",)),
        ("steps", ("list-marker",)), ("risks", ("list-marker",)), ("risks", ("whitespace", "list-marker")),
        ("notes", ("quote-marker",)), ("blocked_by", ("none",))]
    assert ("goal", "## goal", "## Goal") in [(fix.field, fix.before, fix.after) for fix in corrections]
    corrected = base.replace("- It runs long.", "- It runs long.\n- It costs time.").replace(
        "Kept short.", "> Kept short.").replace("## Blocked by\n\nNone", "## Blocked by\n\nNone.")
    assert document == corrected.replace(
        template.marker_line, template.marker_line + "\n<!-- se:corrected whitespace heading list-marker "
                                                     "quote-marker none -->")
    assert templates.parse(template, document).fields["blocked_by"] == ["None."]
    windows, _, more = templates.fill(template, {}, template_cases.RAW, body=trivially(base).replace("\n", "\r\n"))
    assert windows == document.replace("corrected whitespace", "corrected line-ending whitespace")
    assert more[0] == templates.Correction("body", ("line-ending",), "\r\n", "\n")


def test_a_fill_with_a_substantive_error_refuses_makes_nothing_and_names_field_failure_reason_and_fix(
        tmp_path, capsys):
    template = brief()
    body = brief_document().replace("Every brief says what it is for.", template_cases.LONG_GOAL).replace(
        "## Steps\n\n1. Write it.\n2. Check it.\n\n", "")
    _, found, _ = templates.fill(template, {}, template_cases.RAW, body=body)
    assert [(item.field, item.rule, item.severity) for item in found] == [
        ("steps", "required", templates.REFUSE), ("goal", "first-sentence", templates.WARN)]
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "brief.md").write_text(template_cases.BRIEF_TEMPLATE, encoding="utf-8")
    (tmp_path / "brief.md").write_text(body, encoding="utf-8")
    out = tmp_path / "out.md"
    code = templates.main(["fill", "brief", "--templates", str(folder), "--body-file", str(tmp_path / "brief.md"),
                           "--input-text", template_cases.RAW, "--out", str(out)])
    lines = capsys.readouterr().out.splitlines()
    assert code == 1 and not out.exists()
    assert lines[0] == (f"refuse: steps [required]: Steps is missing: write `## Steps`: The steps in order. "
                        f"(or `Not in input` where the input does not say) (why: {templates.REASONS['required']})")
    assert lines[1].startswith("warn: goal [first-sentence]: Goal's first sentence has 79 characters; keep it "
                               "to 60") and lines[1].endswith(f"(why: {templates.REASONS['first-sentence']})")
    assert lines[-1] == "templates.py fill: nothing was written; fix every finding and fill again"


def test_a_fill_by_its_fields_corrects_them_and_reports_each_on_stderr(tmp_path, capsys):
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "brief.md").write_text(template_cases.BRIEF_TEMPLATE, encoding="utf-8")
    values = {**brief().example["fields"], "blocked_by": ["none."], "notes": "* One.  "}
    code = templates.main(["fill", "brief", "--templates", str(folder), "--fields-json", json.dumps(values),
                           "--input-text", template_cases.RAW])
    out = capsys.readouterr()
    assert code == 0 and "<!-- se:corrected whitespace list-marker none -->\n" in out.out
    assert out.err.splitlines() == ["corrected: blocked_by [none]: 'none.' -> 'None.'",
                                    "corrected: notes [whitespace, list-marker]: '* One.  ' -> '- One.'"]


def test_no_correction_changes_a_word_of_content():
    template = brief()
    texts = ["Line.  \r\nNext.\r\n\n", "* One.\n+ Two.\n1) Three.", ">Quoted.", "none.", "NONE",
             "not  in input.", "  An entry.  "]
    values = {"notes": texts[0], "risks": texts[1:3] + texts[6:], "blocked_by": [texts[3]],
              "done": [{"done": False, "text": texts[4]}], "meta": {"Size": texts[5]}}
    _, _, by_fields = templates.fill(template, {**template.example["fields"], **values}, template_cases.RAW)
    _, _, by_body = templates.fill(template, {}, template_cases.RAW,
                                   body=trivially(brief_document()).replace("\n", "\r\n"))
    corrections = by_fields + by_body
    assert {kind for fix in corrections for kind in fix.kinds} == set(templates.CORRECTIONS)
    for fix in corrections:
        assert content_words(fix.before) == content_words(fix.after), fix


def test_the_pass_keeps_code_fences_verbatim_fields_comments_and_titles_as_they_stand():
    template = brief()
    kept = {"said": "> keep it short  \n*  as said", "run": "echo ok  \n* x",
            "notes": "```\n* code  \n```\nnone <!-- a comment -->"}
    values, corrections = templates.correct(template, {**template.example["fields"], **kept})
    assert corrections == [] and {key: values[key] for key in kept} == kept
    work = templates.own("work")
    assert templates.correct(work, {"title": "a-title  "}) == ({"title": "a-title  "}, [])
    assert templates.corrected_text("* * *") == ("* * *", ())


def test_a_refused_fill_of_a_template_manifest_makes_nothing(tmp_path, capsys):
    folder = manifest_folder(tmp_path, requirements_dot_overlay_dot_md=None)
    out = tmp_path / "document" / "manifest.md"
    filled = {key: value for key, value in MANIFEST_FILLED.items() if key != "purpose"}
    code, printed, _ = filled_by_main(capsys, folder, "--fields-json", json.dumps(filled), "--input-text", BRIEF,
                                      "--out", str(out))
    assert code == 1 and not out.exists()
    assert f"(why: {templates.REASONS['required']})" in printed


def test_a_file_records_its_corrections_in_its_front_matter_and_a_refill_drops_the_record(tmp_path):
    template, _, _ = fill_project(tmp_path)
    values = {**FILLED, "seen": FILLED["seen"] + "  ", "impact": ["Exports are incomplete.  "]}
    corrected, found, corrections = templates.fill(template, values, RAW)
    assert len(corrections) == 2 and found == []
    front = templates.FRONT_MATTER.match(corrected).group(0)
    assert front.splitlines()[-2] == 'corrected: ["whitespace"]'
    assert corrected == templates.render(template, FILLED).replace(
        "\n---\n", '\ncorrected: ["whitespace"]\n---\n', 1)
    again, _, none = templates.fill(template, FILLED, RAW, existing=corrected)
    assert none == [] and "corrected:" not in again


# Filling templates from material (docs/templates.md "Filling templates from material"): the worked
# example, examples/fill-templates/pump-x, filled again and checked as it stands, and the
# fill-templates skill's two ends, every document passing and each gap named

EXAMPLE = ROOT / "examples" / "fill-templates" / "pump-x"


def example_repository(root: Path) -> Path:
    """The worked example's small repository under `root`, its templates and material alone: the
    documents are the fill's to write."""
    repository = root / "pump-x"
    for folder in ("templates", "material"):
        shutil.copytree(EXAMPLE / folder, repository / folder)
    return repository


def documents_by_main(capsys, repository: Path, *arguments: str) -> tuple[int, str]:
    code = templates.main(["documents", "--path", str(repository / "documents"), "--root", str(repository),
                           "--tree", *arguments])
    return code, capsys.readouterr().out


def test_the_worked_example_fills_two_documents_that_pass_link_the_material_and_name_their_templates(
        tmp_path, capsys):
    repository = example_repository(tmp_path)
    assert templates.main(["list", "--root", str(repository), "--tree"]) == 0
    listed = capsys.readouterr().out
    assert "label-spec (owner): file.write: documents/label-*.md: A product label" in listed
    assert "test-plan (owner): a node of a document: One test plan per product." in listed
    resolved = templates.catalog(repository, tree=True)
    readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    for document, named in (("label-pump.md", "label-spec"), ("test-plan-pump.md", "test-plan")):
        template = resolved[named]
        assert template.repository == templates.PROJECT_REPOSITORY
        expected = (EXAMPLE / "documents" / document).read_text(encoding="utf-8")
        fields = templates.parse(template, expected).fields
        target = repository / "documents" / document
        common = ["fill", named, "--path" if template.is_file else "--out", str(target), "--root",
                  str(repository), "--tree", "--input", str(repository / "material")]
        assert templates.main(common) == 0
        told = json.loads(capsys.readouterr().out)
        assert told["template"] == named and list(told["fields"]) == list(fields)
        assert templates.main([*common, "--fields-json", json.dumps(fields)]) == 0
        assert capsys.readouterr().out.endswith(f": {named} {template.version}\n")
        text = target.read_text(encoding="utf-8")
        assert text == expected
        assert templates.derived_from(text)[2:] == (named, template.version)
        links = re.findall(r"\]\((\.\./material/[^)]+)\)", text)
        assert links and all((target.parent / link).resolve().is_file() for link in links)
        assert templates.SLOT not in text and "<!--" not in text
        assert f"| [{document}](documents/{document}) | {named} | {template.version} |" in readme
    code, out = documents_by_main(capsys, repository, "--input", str(repository / "material"))
    assert (code, out) == (0, "label-pump.md: Languages: not in input\n2 documents: pass; 1 section the "
                              "material did not fill, named above: tell the person each\n")
    assert f"```text\n{out}```" in (ROOT / "docs" / "templates.md").read_text(encoding="utf-8")
    assert documents_by_main(capsys, EXAMPLE)[0] == 0  # the committed documents pass as they stand


def test_material_without_a_mandatory_section_s_content_ends_with_it_named_and_no_slot(tmp_path, capsys):
    repository = example_repository(tmp_path)
    resolved = templates.catalog(repository, tree=True)
    label, plan = resolved["label-spec"], resolved["test-plan"]
    documents = repository / "documents"
    documents.mkdir()
    no_review = {**templates.parse(label, (EXAMPLE / "documents" / "label-pump.md").read_text(
        encoding="utf-8")).fields,
                 "warnings": "Not in input", "languages": "Not in input"}
    (documents / "label-pump.md").write_text(templates.fill(label, no_review, "")[0], encoding="utf-8")
    plan_text = templates.fill(plan, {"scope": "Both warnings.", "cases": "Not in input"}, "")[0]
    (documents / "test-plan-pump.md").write_text(plan_text, encoding="utf-8")
    code, out = documents_by_main(capsys, repository)
    assert code == 0 and out.splitlines() == [
        "label-pump.md: Warnings: not in input", "label-pump.md: Languages: not in input",
        "test-plan-pump.md: Test cases: not in input",
        "2 documents: pass; 3 sections the material did not fill, named above: tell the person each"]
    left = plan_text.replace("Both warnings.", "Both warnings.\n\n{{slot}}")
    (documents / "test-plan-pump.md").write_text(left, encoding="utf-8")
    code, out = documents_by_main(capsys, repository)
    assert code == 1 and "test-plan-pump.md: refuse: scope [slot]: section Scope still holds the fill slot" in out
    assert out.splitlines()[-1].startswith("2 documents: refused; fix every finding and fill again")
    (documents / "test-plan-pump.md").write_text(plan_text.replace("## Scope\n\nBoth warnings.\n", ""),
                                                 encoding="utf-8")
    code, out = documents_by_main(capsys, repository)
    assert code == 1 and "test-plan-pump.md: refuse: scope [required]" in out


def test_documents_refuses_a_folder_without_documents_and_a_template_that_does_not_resolve(tmp_path, capsys):
    repository = example_repository(tmp_path)
    (repository / "documents").mkdir()
    (repository / "documents" / "notes.md").write_text("# Notes\n\nNo template.\n", encoding="utf-8")
    code, out = documents_by_main(capsys, repository)
    assert code == 1 and "no document here derives from a template" in out
    (repository / "documents" / "gone.md").write_text(
        '---\nderived_from: {template: gone, version: "1"}\n---\n', encoding="utf-8")
    code, out = documents_by_main(capsys, repository)
    assert code == 1 and out.startswith("gone.md: refuse: derived_from [template]: gone is no template here")
    assert templates.main(["documents", "--path", str(tmp_path / "none"), "--tree"]) == 2
    assert "is no folder" in capsys.readouterr().err


def test_a_folder_of_material_is_the_raw_input_each_text_file_named_and_hidden_ones_left_out(tmp_path):
    material = tmp_path / "material"
    (material / "notes").mkdir(parents=True)
    (material / ".hidden").mkdir()
    (material / "b.md").write_text("Second.\n", encoding="utf-8")
    (material / "notes" / "a.txt").write_text("First.\n", encoding="utf-8")
    (material / ".hidden" / "c.md").write_text("Hidden.\n", encoding="utf-8")
    (material / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert templates.raw_input(material) == "--- b.md ---\nSecond.\n\n--- notes/a.txt ---\nFirst.\n"
    assert templates.raw_input(material / "b.md") == "Second.\n"
    (tmp_path / "empty").mkdir()
    with pytest.raises(templates.TemplateError, match="holds no text file"):
        templates.raw_input(tmp_path / "empty")
