"""SE's forms (scripts/forms.py, forms/): loading, reading, writing, selection, every rule with a
failing and a passing fixture, the command, and the contracts with the writers SE has today."""

from __future__ import annotations

import ast
import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

import deck
import fake_git
import forms
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

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "work.md"


@pytest.fixture(scope="module")
def catalog() -> dict[str, forms.Form]:
    return forms.load(ROOT, tree=True)


def findings(form: forms.Form, fields: dict, title: str | None = None) -> list[forms.Finding]:
    values = dict(fields)
    if title is not None:
        values["title"] = title
    return forms.check(form, forms.parse(form, forms.render(form, values), values.get("title")))


def rules(found: list[forms.Finding], severity: str | None = None) -> set[str]:
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

A TOML file per form, read by one script.
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

docs/design.md "Forms".

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


ISSUE_FORMS = ("ticket", "work", "routed")
ADAPTERS = ("field-report", "landing", "housekeeping", "merge-message", "review", "retro",
            "overhaul", "decision")


def test_every_form_loads_with_its_actions_and_the_terms(catalog):
    assert set(catalog) == {*ISSUE_FORMS, *ADAPTERS}
    assert all(catalog[name].actions == forms.ISSUE_ACTIONS for name in ISSUE_FORMS)
    assert all(catalog[name].is_adapter for name in ADAPTERS)
    assert not any(catalog[name].is_adapter for name in ISSUE_FORMS)
    assert catalog["ticket"].terms and catalog["ticket"].severity("terms") == forms.WARN
    work = catalog["work"]
    assert [item.name for item in work.fields][:5] == ["title", "situation", "problem", "goal",
                                                         "approach"]
    assert work.field("steps") is None and work.field("requirements").exact_heading


def write_form(root: Path, name: str, text: str) -> None:
    (root / "forms").mkdir(exist_ok=True)
    (root / "forms" / f"{name}.toml").write_text(text, encoding="utf-8")


MINIMAL = """name = "{name}"
reader = "owner"
says = "A form."
{extra}
[[fields]]
name = "goal"
kind = "text"
heading = "Goal"
required = true
says = "The goal."
"""


@pytest.mark.parametrize("extra, error", [
    ("", "[applies] actions is required"),
    ('[applies]\nactions = ["issue.create"]\n[rules]\nwords = "refuse"\n', "only warns"),
    ('[applies]\nactions = ["issue.delete"]\n', "is none of"),
])
def test_a_form_that_breaks_the_format_does_not_load(tmp_path, extra, error):
    write_form(tmp_path, "one", MINIMAL.format(name="one", extra=extra))
    with pytest.raises(forms.FormError, match=error.replace("[", r"\[").replace("]", r"\]")):
        forms.load(tmp_path, tree=True)


def test_a_valid_minimal_form_loads(tmp_path):
    write_form(tmp_path, "one", MINIMAL.format(name="one", extra='[applies]\nactions = ["issue.create"]\n'))
    assert list(forms.load(tmp_path, tree=True)) == ["one"]


def test_an_extends_cycle_does_not_load(tmp_path):
    applies = '[applies]\nactions = ["issue.create"]\n'
    write_form(tmp_path, "a", MINIMAL.format(name="a", extra=f'extends = "b"\n{applies}'))
    write_form(tmp_path, "b", MINIMAL.format(name="b", extra=f'extends = "a"\n{applies}'))
    with pytest.raises(forms.FormError, match="cycle"):
        forms.load(tmp_path, tree=True)


def commit_all(repository: Path) -> None:
    fake_git.git("-C", str(repository), "add", "-A")
    fake_git.git("-C", str(repository), "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "-m", "forms")


def test_load_reads_forms_at_origin_where_the_ref_holds_them(tmp_path, fake_git_door):
    applies = '[applies]\nactions = ["issue.create"]\n'
    fake_git.init(tmp_path)
    write_form(tmp_path, "landed", MINIMAL.format(name="landed", extra=applies))
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/main", "HEAD")
    (tmp_path / "forms" / "landed.toml").unlink()
    write_form(tmp_path, "local", MINIMAL.format(name="local", extra=applies))
    assert list(forms.load(tmp_path)) == ["landed"]
    assert list(forms.load(tmp_path, tree=True)) == ["local"]


def test_load_reads_the_working_tree_without_the_ref(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    write_form(tmp_path, "local", MINIMAL.format(name="local", extra='[applies]\nactions = ["issue.create"]\n'))
    assert list(forms.load(tmp_path)) == ["local"]


# Reading and writing


def test_parse_skips_front_matter_and_accepts_heading_variants(catalog):
    ticket = catalog["ticket"]
    body = ("---\nname: x\n---\n# situation:\n\nA.\n\n#### PROBLEM\n\nB.\n\n##### Goal\n\nnot a field\n"
            "\n## Goal\n\n_No response_\n")
    document = forms.parse(ticket, body)
    assert document.fields["situation"] == "A."
    assert document.fields["problem"] == "B.\n\n##### Goal\n\nnot a field"
    assert document.fields["goal"] == ""
    assert "Goal is empty" in " ".join(f.fix for f in forms.check(ticket, document))


def test_exact_heading_counts_only_as_written(catalog):
    work = catalog["work"]
    document = forms.parse(work, WORK_BODY.replace("## Requirements", "### requirements"))
    assert "requirements" not in document.fields
    refused = [f for f in forms.check(work, document) if f.field == "requirements"]
    assert refused and "must be exactly `## Requirements`" in refused[0].fix
    assert not [f for f in forms.check(work, forms.parse(work, WORK_BODY)) if f.severity == "refuse"]


def test_html_comments_do_not_fill_a_field(catalog):
    ticket = catalog["ticket"]
    document = forms.parse(ticket, "## Situation\n\n<!-- what is true today -->\n")
    assert [f.fix for f in forms.check(ticket, document) if f.field == "situation"][0].startswith(
        "Situation is empty")


def test_render_writes_the_markers_once_and_keeps_unknown_and_verbatim_bytes(catalog):
    work = catalog["work"]
    odd = "## Notes  \n\n  kept   as\twritten  \n\n\n"
    body = WORK_BODY.replace("<!-- se:fleet -->\n", "<!-- se:fleet -->\n<!-- se:fleet -->\n") \
        .replace("## Design owner", odd + "## Design owner")
    rendered = forms.render(work, forms.parse(work, body))
    assert rendered.count(forms.FLEET_MARKER) == 1
    assert rendered.startswith(f"{forms.FLEET_MARKER}\n<!-- se:form work -->\n")
    assert odd in rendered
    assert "> make it   \"work\",\n>    please" in rendered
    assert rendered == forms.render(work, forms.parse(work, rendered))


def test_parse_of_render_gives_each_example_back(catalog):
    for form in (catalog[name] for name in ISSUE_FORMS):
        example = dict(form.example["fields"])
        title = example.get("title")
        document = forms.parse(form, forms.render(form, example), title)
        assert document.fields == example, form.name
        assert not forms.check(form, document), form.name


def test_an_object_field_reads_and_writes_key_value_lines(tmp_path):
    write_form(tmp_path, "obj", 'name = "obj"\nreader = "fleet"\nsays = "x"\n[applies]\n'
               'actions = ["issue.create"]\n[[fields]]\nname = "meta"\nkind = "object"\n'
               'heading = "Meta"\nsays = "keys"\n')
    form = forms.load(tmp_path, tree=True)["obj"]
    values = {"meta": {"Owner": "SE", "Size": "small"}}
    assert forms.parse(form, forms.render(form, values)).fields == values


# Selection


def test_select_takes_the_marker_then_the_conditions_then_the_plain_form(catalog):
    routed = "Outside text\n\n<!-- se:handled -->\n## Routing\n\nRouted from: X\n"
    assert forms.select(catalog, "issue.create", routed, "feat/x-20261116").name == "routed"
    for title in ("forms-match-names-and-kinds", "feat/x-20261116"):
        assert forms.select(catalog, "issue.edit", WORK_BODY, title, labels=["work"]).name == "work"
    assert forms.select(catalog, "issue.create", WORK_BODY, "forms-match-names-and-kinds").name == \
        "ticket"
    assert forms.select(catalog, "issue.create", "## Situation\n", "plain-words").name == "ticket"
    named = "<!-- se:form ticket -->\n" + WORK_BODY
    assert forms.select(catalog, "issue.create", named, "feat/x-20261116").name == "ticket"
    with pytest.raises(forms.FormError, match="issue.delete"):
        forms.select(catalog, "issue.delete", "", "")


def test_select_without_a_form_for_the_action_is_free_form(tmp_path):
    write_form(tmp_path, "one", MINIMAL.format(name="one", extra='[applies]\nactions = ["issue.edit"]\n'))
    assert forms.select(forms.load(tmp_path, tree=True), "issue.create", "", "").form is None


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
    ("unnamed-entry", {"depends_on": ["#12"]}, {"depends_on": ["#12 the forms engine"]}),
    ("title-shape", {"title": "Forms-Match"}, {}),
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
    assert any(finding.rule == "title-shape" and finding.severity == forms.WARN
               and "the body repeats the title" in finding.fix for finding in found), found


def test_the_work_form_warns_where_the_goal_s_first_sentence_runs_past_the_landing_title_width(
        catalog):
    work = catalog["work"]
    assert work.field("goal").first_sentence_chars == work_tickets.SUMMARY_WIDTH
    long = ("Where SE's forms are switched on, a GitHub write through the GitHub MCP tools whose "
            "body breaks its form is refused before it runs, naming the forms and every fix.")
    assert len(long) == 163
    found = findings(work, {**work_fields(catalog), "goal": long + " The refusal names the form."})
    assert [(finding.rule, finding.severity) for finding in found] == [("first-sentence", forms.WARN)]
    assert "163" in found[0].fix and "landing title" in found[0].fix
    short = "Every landing title is a complete statement."
    assert len(short) == 44
    assert findings(work, {**work_fields(catalog), "goal": short + " Why it matters."}) == []


#: Titles under the name rule, of its old form, and breaking it, as `checked_name` judges them.
TITLES = ["forms-match-names-and-kinds", "plain", "123", "a1-b2", "feat/plain-titles-20261116",
          "fix/routed-20261116", "one-two-three-four-five-six", "Forms-Match", "double--dash",
          "-leading", "scripts/forms.py", "docs/a/b-20261116", "Plain words", ""]


def test_the_forms_accept_exactly_the_titles_checked_name_accepts(catalog):
    def accepted(title: str) -> bool:
        try:
            work_tickets.checked_name("file", title)
        except work_tickets.QueueError:
            return False
        return True

    def warns(form: forms.Form, title: str) -> list[forms.Finding]:
        fields = {**form.example["fields"], "title": title}
        document = forms.parse(form, forms.render(form, fields), title)
        return [finding for finding in forms.check(form, document) if finding.rule == "title-shape"]

    expected = {title for title in TITLES if accepted(title)}
    assert expected >= {"forms-match-names-and-kinds", "123", "feat/plain-titles-20261116"}
    for name in ("work", "ticket"):
        assert {title for title in TITLES if title and not warns(catalog[name], title)} == \
            expected - {""}, name
    for title in ("Forms-Match", "one-two-three-four-five-six"):
        for name in ("work", "ticket"):
            found = warns(catalog[name], title)
            assert [finding.severity for finding in found] == [forms.WARN]
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


def test_a_body_route_writes_with_its_default_type_passes_the_routed_form(tmp_path, capsys):
    routing = "## Requirements\n\n1. A routed requirement.\n"
    body = tmp_path / "body.md"
    body.write_text(work_tickets.routed_body(OUTSIDE, "Proposal: make it work", routing, "feat"),
                    encoding="utf-8")
    assert "### Package kind\n\nfeat" in body.read_text(encoding="utf-8")
    assert forms.main(["check", "routed", "--tree", "--body-file", str(body)]) == 0
    assert "choice" not in capsys.readouterr().out


NAMED = """name = "one"
reader = "owner"
says = "A form."
[applies]
actions = ["issue.create"]
[rules]
title-shape = "warn"
[[fields]]
name = "title"
kind = "line"
source = "title"
{title}
[[fields]]
name = "kind"
kind = "choice"
heading = "Kind"
{kind}
"""


@pytest.mark.parametrize("title, kind, error", [
    ('shape = "work_tickets:NO_SUCH_RULE"', 'choices = ["a"]',
     "forms/one.toml: field title shape: work_tickets:NO_SUCH_RULE does not resolve"),
    ('shape = "no_such_script:RULE"', 'choices = ["a"]',
     "forms/one.toml: field title shape: no_such_script:RULE does not resolve"),
    ('shape = "work_tickets:NAME_WORDS"', 'choices = ["a"]', "is no pattern or function"),
    ("", 'choices = ["a", "work_tickets:NO_SUCH_KINDS"]',
     "forms/one.toml: field kind choices: work_tickets:NO_SUCH_KINDS does not resolve"),
    ("", 'choices = ["work_tickets:NAME_EXAMPLE"]', "is no list or mapping"),
])
def test_a_field_that_names_code_that_does_not_exist_does_not_load(tmp_path, title, kind, error):
    write_form(tmp_path, "one", NAMED.format(title=title, kind=kind))
    with pytest.raises(forms.FormError, match=re.escape(error)):
        forms.load(tmp_path, tree=True)


def test_a_field_names_a_pattern_a_function_a_list_and_a_mapping(tmp_path):
    write_form(tmp_path, "one", NAMED.format(title='shape = "work_tickets:NAME_PATTERN"',
                                             kind='choices = ["x", "work_tickets:RELEASE_ORDER", '
                                                  '"work_tickets:RELEASE_KINDS"]'))
    one = forms.load(tmp_path, tree=True)["one"]
    assert one.field("kind").choices[:4] == ("x", "patch", "minor", "major")
    assert "feat" in one.field("kind").choices
    document = forms.parse(one, "## Kind\n\nfeat\n", "Not A Name")
    assert [finding.rule for finding in forms.check(one, document)] == ["title-shape"]
    assert forms.check(one, forms.parse(one, "## Kind\n\nfeat\n", "a-name")) == []


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


def test_blocks_output_passes_the_work_form(catalog, monkeypatch):
    work = catalog["work"]
    once = blocked(monkeypatch, WORK_BODY, 12)
    assert "## Blocked by\n\nNone\n#12\n" in once
    twice = blocked(monkeypatch, blocked(monkeypatch, WORK_BODY.replace("None\n", "#3\n"), 4), 5)
    assert "## Blocked by\n\n#3\n#4\n#5\n" in twice
    for body in (once, twice):
        document = forms.parse(work, body, "feat/forms-20261116")
        assert not rules(forms.check(work, document), "refuse")
    assert forms.parse(work, twice).fields["blocked_by"] == ["#3", "#4", "#5"]


def test_open_points_pass_the_work_form_and_survive_render(catalog):
    work = catalog["work"]
    body = work_tickets.with_open_points(WORK_BODY, "a" * 40, ["Name the field.", "Test it."])
    document = forms.parse(work, body, "feat/forms-20261116")
    assert not rules(forms.check(work, document), "refuse")
    block = body[body.index("<!-- se:open-points"):body.index("<!-- se:open-points:end -->") + 27]
    rendered = forms.render(work, document)
    assert block in rendered
    assert document.fields["changes_after_filing"][1:3] == ["Name the field.", "Test it."]
    edited = forms.Document(work.name, {**document.fields, "goal": "Another goal."}, document.parts,
                            read=document.read)
    assert block in forms.render(work, edited)
    assert work_tickets.requirement_items(rendered) == work_tickets.requirement_items(body)


ROUTING = "## Requirements\n\n1. A routed requirement.\n\n## Package kind\n\nStandard, small.\n"
OUTSIDE = ("Please make the example work.\n\n## Steps to reproduce\n\n1. Run it.\n\n"
           "## Requirements\n\n1. An outside requirement.\n")


@pytest.mark.parametrize("enveloped", [False, True], ids=["plain", "envelope"])
def test_routed_body_passes_the_routed_form_and_the_outside_text_stays_data(catalog, enveloped):
    routed = catalog["routed"]
    outside = outside_text.envelope(OUTSIDE, "an outside issue", "NONE")[0] if enveloped else OUTSIDE
    body = work_tickets.routed_body(outside, "Proposal: make it work", ROUTING)
    document = forms.parse(routed, body)
    assert not rules(forms.check(routed, document), "refuse")
    assert document.fields == {"routed_from": "Proposal: make it work",
                               "requirements": ["A routed requirement."],
                               "package_kind": "Standard, small."}
    assert all("Steps to reproduce" not in part.heading for part in document.parts
               if part.kind in ("field", "unknown"))
    rendered = forms.render(routed, document)
    assert rendered.startswith(body[:body.index(work_tickets.HANDLED_MARKER)])
    assert forms.FLEET_MARKER not in rendered
    assert forms.parse(routed, rendered).fields == document.fields


def test_the_routed_form_refuses_a_body_without_its_routing(catalog):
    routed = catalog["routed"]
    assert "required" in rules(forms.check(routed, forms.parse(routed, OUTSIDE)), "refuse")


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
    rendered = forms.render(catalog["work"], fields)

    def issue(body: str) -> dict:
        return {"title": "feat/x-20261116", "url": "https://example.com/1", "body": body, "labels": []}
    assert work_tickets.requirement_items(rendered) == work_tickets.requirement_items(HAND_WRITTEN)
    assert work_tickets.planned_tickets(issue(rendered)) == work_tickets.planned_tickets(issue(HAND_WRITTEN))
    assert work_tickets.blockers_of(issue(rendered)) == work_tickets.blockers_of(issue(HAND_WRITTEN)) == [7, 9]


# The command


def test_check_of_the_work_template_names_the_missing_situation_and_empty_requirements(capsys):
    assert forms.main(["check", "work", "--tree", "--body-file", str(TEMPLATE)]) == 1
    out = capsys.readouterr().out
    assert "Situation is empty" in out and "Requirements is empty" in out
    assert "is missing" not in out
    assert len(out.splitlines()) <= 10


def test_check_passes_a_good_body_and_caps_its_lines(tmp_path, capsys):
    body = tmp_path / "body.md"
    body.write_text(WORK_BODY, encoding="utf-8")
    assert forms.main(["check", "work", "--tree", "--body-file", str(body),
                       "--title", "feat/forms-20261116"]) == 0
    assert capsys.readouterr().out.strip() == "work: no findings"
    body.write_text("## Steps\n\n" + "".join(f"{n}. Step {n}.\n" for n in range(1, 13)),
                    encoding="utf-8")
    assert forms.main(["check", "ticket", "--tree", "--body-file", str(body)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 10 and lines[-1].startswith("... and ")
    assert lines[0].startswith("refuse: ")


def test_check_takes_fields_from_a_draft(tmp_path, capsys, catalog):
    assert forms.main(["draft", "ticket", "--json", "--tree"]) == 0
    drafted = json.loads(capsys.readouterr().out)
    assert drafted["fields"]["steps"] == [] and drafted["field_says"]["goal"]
    drafted["fields"].update(ticket_fields(catalog))
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps(drafted), encoding="utf-8")
    assert forms.main(["check", "ticket", "--tree", "--fields", str(fields)]) == 0
    capsys.readouterr()
    assert forms.main(["check", "ticket", "--tree", "--fields", str(fields), "--title",
                       "Not A Name"]) == 0
    assert "title-shape" in capsys.readouterr().out


def schema_errors(schema: dict, value: object, where: str = "$") -> list[str]:
    """What `value` breaks of `schema`, read with the eight keywords `forms.schema` writes: SE
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
    assert forms.main(["draft", name, "--json", "--tree"]) == 0
    out = capsys.readouterr().out
    return out, json.loads(out)


@pytest.mark.parametrize("name", ISSUE_FORMS)
def test_draft_json_gives_each_shape_and_a_schema_its_example_passes(capsys, catalog, name):
    form = catalog[name]
    _, answer = drafted(capsys, name)
    shapes, schema = answer["field_shape"], answer["schema"]
    assert list(shapes) == [item.name for item in form.fields]
    for item in form.fields:
        assert shapes[item.name]["kind"] == item.kind
        assert shapes[item.name].get("required", False) is item.required
        assert shapes[item.name].get("choices", []) == list(item.choices)
        assert schema["properties"][item.name]["description"] == item.says
    assert schema["required"] == [item.name for item in form.fields if item.required]
    assert schema_errors(schema, form.example["fields"]) == []
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
    for form in catalog.values():
        assert keywords(forms.schema(form)) <= set(forms.SCHEMA_KEYWORDS), form.name


def test_an_adapter_drafts_no_shape_and_an_empty_schema(capsys):
    _, answer = drafted(capsys, "review")
    assert answer["field_shape"] == {} and answer["schema"]["properties"] == {}


def test_draft_json_keeps_its_old_keys_byte_for_byte(capsys, catalog):
    out, _ = drafted(capsys, "work")
    form = catalog["work"]
    empty = {"list": [], "issue": [], "checklist": [], "object": {}}
    old = json.dumps({"form": form.name, "says": form.says,
                      "fields": {item.name: empty.get(item.kind, "") for item in form.fields},
                      "field_says": {item.name: item.says for item in form.fields}}, indent=2)
    assert out.startswith(old.removesuffix("\n}") + ",\n  \"field_shape\": {")


def test_an_object_field_takes_the_schemas_key_value_pairs(tmp_path):
    write_form(tmp_path, "obj", 'name = "obj"\nreader = "fleet"\nsays = "x"\n[applies]\n'
               'actions = ["issue.create"]\n[[fields]]\nname = "meta"\nkind = "object"\n'
               'heading = "Meta"\nsays = "keys"\n')
    form = forms.load(tmp_path, tree=True)["obj"]
    pairs = {"meta": [{"key": "Owner", "value": "SE"}, {"key": "Size", "value": "small"}]}
    assert schema_errors(forms.schema(form), pairs) == []
    assert forms.render(form, pairs) == forms.render(form, {"meta": {"Owner": "SE",
                                                                    "Size": "small"}})


def test_check_takes_fields_and_bodies_as_text_and_renders_what_it_would_file(tmp_path, capsys,
                                                                             catalog):
    form = catalog["work"]
    for values in (work_fields(catalog), {"title": "plain-titles"}):
        text = json.dumps(values)
        (tmp_path / "f.json").write_text(text, encoding="utf-8")
        code = forms.main(["check", "work", "--tree", "--fields", str(tmp_path / "f.json")])
        by_file = capsys.readouterr().out
        assert forms.main(["check", "work", "--tree", "--fields-json", text]) == code
        assert capsys.readouterr().out == by_file
    assert code == 1 and "refuse: " in by_file
    values = work_fields(catalog)
    assert forms.main(["check", "work", "--tree", "--fields-json", json.dumps(values),
                       "--render"]) == 0
    rendered = capsys.readouterr()
    assert rendered.out == forms.render(form, values)
    assert rendered.out.startswith(f"{forms.FLEET_MARKER}\n<!-- se:form work -->\n")
    assert forms.main(["check", "work", "--tree", "--title", "Not A Name", "--body",
                       rendered.out, "--render"]) == 0
    warned = capsys.readouterr()
    assert warned.out == rendered.out and "title-shape" in warned.err
    assert forms.main(["check", "work", "--tree", "--fields-json", "{\"title\": \"x\"}",
                       "--render"]) == 1
    assert capsys.readouterr().out.startswith("refuse: ")


def test_check_selects_the_form_by_action_as_a_write_would(capsys, catalog):
    body = forms.render(catalog["work"], work_fields(catalog)).replace(
        "<!-- se:form work -->\n", "")
    assert forms.main(["check", "--tree", "--action", "issue.create", "--labels", "work",
                       "--title", "plain-titles", "--body", body]) == 0
    assert capsys.readouterr().out == "work: no findings\n"
    assert forms.main(["check", "--tree", "--action", "issue.create", "--title", "plain-titles",
                       "--body", body]) == 1
    assert "steps [required]" in capsys.readouterr().out  # the ticket form's own field
    assert forms.main(["check", "--tree", "--action", "comment.create", "--body", "Thanks."]) == 0
    assert capsys.readouterr().out == "free: no form applies (comment.create)\n"
    marked = "<!-- se:form work -->\nThanks.\n"
    assert forms.main(["check", "--tree", "--action", "comment.create", "--body", marked]) == 1
    assert "[form]" in capsys.readouterr().out


@pytest.mark.parametrize("arguments, error", [
    (["check", "work", "--action", "issue.create", "--body", "x"], "not both"),
    (["check", "--body", "x"], "give --action"),
    (["check", "work", "--labels", "work", "--body", "x"], "with --action"),
    (["check", "work", "--fields-json", "[1]"], "must hold an object"),
    (["check", "work", "--fields-json", "{"], "--fields-json is no JSON"),
])
def test_check_usage_errors_of_the_new_options_exit_2(capsys, arguments, error):
    assert forms.main([*arguments, "--tree"]) == 2
    assert error in capsys.readouterr().err


def test_draft_prints_the_empty_form_with_its_says(capsys, catalog):
    assert forms.main(["draft", "work", "--tree"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{forms.FLEET_MARKER}\n<!-- se:form work -->\n")
    assert "## Requirements\n\n<!-- Numbered, checkable requirements" in out
    assert rules(forms.check(catalog["work"], forms.parse(catalog["work"], out)), "refuse")


def test_list_names_every_form_with_its_actions(capsys):
    assert forms.main(["list", "--tree"]) == 0
    out = capsys.readouterr().out.splitlines()
    names = [line.split(" ")[0] for line in out]
    assert sorted(names) == sorted((*ISSUE_FORMS, *ADAPTERS))
    assert all("issue.create, issue.edit" in line for line in out if line.split(" ")[0]
               in ISSUE_FORMS)


@pytest.mark.parametrize("arguments, error", [
    (["check", "nope", "--tree", "--body-file", "x.md"], "no form 'nope'"),
    (["check", "work", "--tree", "--body-file", "missing.md"], "cannot read --body-file"),
])
def test_usage_errors_exit_2(tmp_path, capsys, arguments, error):
    arguments = [str(tmp_path / a) if a.endswith(".md") else a for a in arguments]
    assert forms.main(arguments) == 2
    assert error in capsys.readouterr().err


def test_a_missing_argument_exits_2():
    with pytest.raises(SystemExit) as stopped:
        forms.main(["check", "work", "--tree"])
    assert stopped.value.code == 2


# Forms for files: a form claims files by their path (file.write)


STEP_FORM = """name = "{name}"
reader = "owner"
says = "Risks: what could go wrong."

[applies]
actions = ["file.write"]
paths = [{paths}]
{extra}
[rules]
required = "refuse"

[[fields]]
name = "risks"
kind = "list"
heading = "Risks"
required = true
none_ok = true
says = "One item per risk, or None."
"""

STEP = "---\nid: S5B\nname: Risks\n---\n\n# Risks\n\n## Risks\n\n- The scan misses a tool.\n"


def step_forms(root: Path, **forms_by_name: str) -> dict[str, forms.Form]:
    for name, extra in forms_by_name.items():
        write_form(root, name, STEP_FORM.format(name=name, paths='"book/*/steps/*.md"',
                                                extra=extra))
    return forms.load(root, folder=root / "forms")


@pytest.mark.parametrize("applies, error", [
    ('actions = ["issue.create"]\npaths = ["*.md"]', "goes only with"),
    ('actions = ["file.write", "issue.create"]\npaths = ["*.md"]', "goes only with"),
    ('actions = ["file.write"]', "needs [applies] paths"),
    ('actions = ["file.write"]\npaths = "*.md"', "list of globs"),
])
def test_a_file_form_needs_its_paths_and_its_paths_need_file_write(tmp_path, applies, error):
    write_form(tmp_path, "one", MINIMAL.format(name="one", extra=f"[applies]\n{applies}\n"))
    with pytest.raises(forms.FormError) as refused:
        forms.load(tmp_path, folder=tmp_path / "forms")
    assert error in str(refused.value) and str(tmp_path / "forms" / "one.toml") in str(refused.value)


def test_a_file_form_loads_with_its_paths_and_its_globs_match_by_folder(tmp_path):
    write_form(tmp_path, "deep", STEP_FORM.format(name="deep", paths='"book/**/*.md"', extra=""))
    catalog = step_forms(tmp_path, step="")
    assert catalog["step"].actions == ("file.write",) and catalog["step"].is_file
    assert catalog["step"].claims("book/m1/steps/51-S5B.md")
    assert not catalog["step"].claims("book/m1/steps/deeper/51-S5B.md")
    assert not catalog["step"].claims("book/m1/notes.md")
    assert all(catalog["deep"].claims(path) for path in ("book/a.md", "book/a/b/c.md"))
    assert not catalog["deep"].claims("notes/a.md")


def test_select_for_a_file_takes_the_front_matter_then_the_conditions(tmp_path):
    catalog = step_forms(tmp_path, risks="marker_pattern = 'id: S5B'", goals="order = 1\n"
                         "marker_pattern = 'id: S1'")
    pick = lambda body, path="book/m1/steps/x.md": forms.select(catalog, "file.write", body,
                                                                 path=path)
    free = pick(STEP, "notes/x.md")
    assert free.form is None and not free.findings
    assert pick("---\nid: S5B\nform: goals\n---\n").name == "goals"
    assert pick("---\nid: S5B\n---\n").name == "risks"
    outside = pick("---\nid: S5B\nform: work\n---\n")
    assert outside.name == "risks" and rules(list(outside.findings), "refuse") == {"form"}
    none = pick("---\nid: S9\n---\n\n# Other\n")
    assert none.form is None
    assert [finding.fix for finding in none.findings] == [
        "book/m1/steps/x.md: no form takes this file; name its form in the front matter, "
        "form: <name> (one of goals, risks)"]
    with pytest.raises(forms.FormError, match="give path"):
        forms.select(catalog, "file.write", STEP)


def test_a_step_file_keeps_its_front_matter_and_title_and_gains_only_its_form(tmp_path):
    form = step_forms(tmp_path, risks="")["risks"]
    document = forms.parse(form, STEP)
    assert document.fields == {"risks": ["The scan misses a tool."]}
    rendered = forms.render(form, document)
    assert rendered == STEP.replace("name: Risks\n", "name: Risks\nform: risks\n")
    assert forms.FLEET_MARKER not in rendered and "se:form" not in rendered
    assert forms.parse(form, rendered).fields == document.fields
    assert forms.render(form, forms.parse(form, rendered)) == rendered
    bare = forms.render(form, forms.parse(form, "# Risks\n\n## Risks\n\nNone\n"))
    assert bare == "---\nform: risks\n---\n\n# Risks\n\n## Risks\n\nNone\n"
    fresh = forms.render(form, {"risks": ["One."]})
    assert fresh == "---\nform: risks\n---\n\n## Risks\n\n- One.\n"
    assert forms.parse(form, fresh).fields == {"risks": ["One."]}


def test_a_page_title_that_reads_like_a_field_is_no_field(tmp_path):
    form = step_forms(tmp_path, risks="")["risks"]
    document = forms.parse(form, "---\nid: S5B\n---\n\n# Risks\n\n- The scan misses a tool.\n")
    assert document.fields == {}
    assert rules(forms.check(form, document), "refuse") == {"required"}


def test_check_and_draft_take_a_file_against_forms_outside_se(tmp_path, capsys):
    step_forms(tmp_path, risks="marker_pattern = 'id: S5B'")
    steps = tmp_path / "book" / "m1" / "steps"
    steps.mkdir(parents=True)
    (steps / "51-S5B.md").write_text(STEP, encoding="utf-8")
    (steps / "90-S9.md").write_text("---\nid: S9\n---\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    where = ["--forms", str(tmp_path / "forms"), "--root", str(tmp_path)]
    run = lambda *arguments: (forms.main([*arguments, *where]), capsys.readouterr())
    code, out = run("check", "--path", str(steps / "51-S5B.md"), "--render")
    assert code == 0 and out.out == STEP.replace("name: Risks\n", "name: Risks\nform: risks\n")
    code, out = run("check", "--path", str(steps / "51-S5B.md"), "--body", "# Risks\n")
    assert code == 1 and "[required]" in out.out
    code, out = run("check", "--path", str(steps / "90-S9.md"))
    assert code == 1 and "form: <name>" in out.out
    assert run("check", "--path", str(tmp_path / "notes.md"))[1].out == \
        "free: no form claims notes.md\n"
    code, out = run("draft", "--path", str(steps / "51-S5B.md"), "--json")
    assert code == 0 and json.loads(out.out)["form"] == "risks"
    code, out = run("draft", "--path", str(steps / "51-S5B.md"))
    assert out.out.startswith("---\nform: risks\n---\n\n## Risks\n") and "se:fleet" not in out.out
    assert run("draft", "--path", str(tmp_path / "notes.md"))[1].out == \
        "free: no form claims notes.md\n"
    assert forms.main(["list", "--forms", str(tmp_path / "forms")]) == 0
    assert capsys.readouterr().out.startswith(
        "risks (owner): file.write: book/*/steps/*.md: Risks:")


@pytest.mark.parametrize("arguments, error", [
    (["check", "--action", "file.write", "--body", "x"], "give --path"),
    (["check", "--action", "issue.create", "--path", "x.md"], "without --action"),
    (["check", "work", "--root", ".", "--body", "x"], "give --path"),
    (["draft"], "not both"),
    (["draft", "work", "--path", "x.md"], "not both"),
    (["check", "--path", "/elsewhere/x.md", "--root", "/nowhere", "--body", "x"],
     "not under the project root"),
    (["list", "--forms", "/nowhere"], "is no folder"),
])
def test_the_file_options_refuse_what_does_not_fit(capsys, arguments, error):
    assert forms.main([*arguments, "--tree"]) == 2
    assert error in capsys.readouterr().err


# Adapters: the texts SE already writes and checks, registered as they are


REPO = "github.com/o/r"
ISSUE_URL = f"https://{REPO}/issues/7"
PULL_URL = f"https://{REPO}/pull/5"
HOME = {REPO}


def adapter_verdict(form: forms.Form, body: str, title: str | None = None) -> list[str]:
    """The refusals of `form` on `body`, without the adapter's name before each."""
    return [finding.fix.removeprefix(f"{form.name}: ") for finding
            in forms.check(form, forms.parse(form, body, title)) if finding.severity == forms.REFUSE]


def parametrized(test, index: int = 0) -> list:
    """The cases an existing test is parametrized with, its own fixtures as they stand."""
    return list(test.pytestmark[index].args[1])


def test_list_shows_each_adapter_with_its_checker_and_actions(capsys):
    assert forms.main(["list", "--tree"]) == 0
    lines = {line.split(" ")[0]: line for line in capsys.readouterr().out.splitlines()}
    assert "pr.create, pr.edit: checker work_tickets:field_report_problems:" in lines["field-report"]
    assert "comment.create, comment.edit: checker review:checked_report:" in lines["review"]
    assert "checker retro:judgment_problems" in lines["retro"]
    assert "checker overhaul:judgment_problems" in lines["overhaul"]
    assert "deck.build: checker deck:_explains:" in lines["decision"]
    assert ("pr.merge: checker work_tickets:merge_release_kind, title "
            "work_tickets:INTEGRATION_SUBJECT_PATTERN:") in lines["merge-message"]
    assert "pr.create, pr.edit: checker none, 3 lines:" in lines["landing"]
    assert "pr.create, pr.edit: checker none (no field required):" in lines["housekeeping"]


def test_every_name_an_adapter_gives_resolves(catalog):
    for name in ADAPTERS:
        form = catalog[name]
        for reference in (form.checker, form.adapter.get("extract"), form.adapter.get("when"),
                          form.adapter.get("title_rule")):
            if reference:
                assert forms.resolve(reference, form) is not None, (name, reference)


@pytest.mark.parametrize("top, tables, error", [
    ('checker = "review:checked_report"\n', '[[fields]]\nname = "goal"\nkind = "text"\n'
     'heading = "Goal"\n', "a form with fields takes no checker"),
    ('checker = "review.checked_report"\n', "", "is no \"<module>:<name>\""),
    ('checker = "review:checked_report"\n', '[adapter]\nread = "body"\n',
     "[adapter] has unknown keys read"),
    ('checker = "deck:_explains"\n', '[adapter]\nresult = "truth"\n', "needs its refusal"),
    ('checker = "deck:_explains"\n', '[adapter]\nresult = "maybe"\n', "result is 'maybe'"),
    ("", '[[adapter.lines]]\npattern = "x"\n', "each [[adapter.lines]] has a pattern and says"),
], ids=["fields-and-checker", "no-reference", "unknown-key", "truth-without-refusal",
        "unknown-result", "line-without-says"])
def test_an_adapter_that_breaks_the_format_does_not_load(tmp_path, top, tables, error):
    write_form(tmp_path, "one", f'name = "one"\nreader = "fleet"\nsays = "A text."\n{top}\n'
               f'[applies]\nactions = ["comment.create"]\n\n{tables}')
    with pytest.raises(forms.FormError, match=re.escape(error)):
        forms.load(tmp_path, tree=True)


@pytest.mark.parametrize("applies, error", [
    ('actions = ["pr.create"]\nbase = "next"\n', "the one base is \"integration\""),
    ('actions = ["pr.create"]\nbranch = "main"\n', "[applies] has unknown keys branch"),
    ('actions = ["pr.delete"]\n', "action 'pr.delete' is none of"),
])
def test_applies_refuses_what_selection_cannot_read(tmp_path, applies, error):
    write_form(tmp_path, "one", f'name = "one"\nreader = "fleet"\nsays = "A text."\n\n'
               f'[applies]\n{applies}')
    with pytest.raises(forms.FormError, match=re.escape(error)):
        forms.load(tmp_path, tree=True)


def test_an_adapter_body_is_never_marked_and_has_no_fields_to_render(catalog):
    body = work_tickets.landing_description(PULL_URL, 5, ISSUE_URL)
    landing = catalog["landing"]
    assert forms.render(landing, forms.parse(landing, body)) == body
    assert forms.FORM_MARKER.format(name="landing") not in forms.render(landing,
                                                                        forms.parse(landing, body))
    with pytest.raises(forms.FormError, match="landing is an adapter and has no fields"):
        forms.render(landing, {})
    assert forms.draft(landing).startswith("<!-- landing: ")


# Selection


def test_select_gives_landing_on_integrates_open_pull_step_and_merge_message_on_its_squash(catalog):
    title = work_tickets.integration_merge_message(
        "feat/forms-adapters-20261116", 7, 5, True, "## Goal\n\nEvery text selects a form.\n")
    message = "Release-kind: minor"
    description = work_tickets.landing_description(PULL_URL, 5, ISSUE_URL, {"took": 1})
    plan = work_tickets.landing_plan(REPO, "land/feat/x", "main", "a" * 40, "b" * 40, title,
                                     message, description, "then", REPO)
    steps = {step.action: step.arguments for step in plan.steps}
    opened, squashed = steps["open_pull"], steps["squash"]
    form, found = forms.verdict(catalog, "pr.create", opened["body"], opened["title"],
                                base=opened["base"], repo=REPO, home=HOME)
    assert form.name == "landing" and found == []
    form, found = forms.verdict(catalog, "pr.merge", squashed["commit_message"],
                                squashed["commit_title"], base="main", repo=REPO, home=HOME)
    assert form.name == "merge-message" and found == []


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
    form, found = forms.verdict(catalog, "pr.create", body, "Integrate feat/x", base="main")
    assert form.name == "landing" and [finding.rule for finding in found] == ["line"]
    assert says in found[0].fix


def test_a_work_issue_carrying_the_decision_marker_is_refused(catalog):
    body = WORK_BODY.replace(forms.FLEET_MARKER, forms.FLEET_MARKER + "\n<!-- se:form decision -->")
    form, found = forms.verdict(catalog, "issue.create", body, "feat/forms-20261116",
                                labels=["work"])
    assert form.name == "work"
    refused = [finding for finding in found if finding.rule == "form"]
    assert len(refused) == 1 and refused[0].severity == forms.REFUSE
    assert "the decision form does not apply to issue.create" in refused[0].fix


def test_a_housekeeping_pull_request_needs_no_field_report_and_main_without_the_label_does(catalog):
    body = "Tidy the README's wording.\n"
    form, found = forms.verdict(catalog, "pr.create", body, "Tidy the README", base="main",
                                labels=["housekeeping"])
    assert form.name == "housekeeping" and found == []
    form, found = forms.verdict(catalog, "pr.create", body, "Tidy the README", base="main")
    assert form.name == "field-report"
    assert [finding.rule for finding in found] == ["checker"]
    assert "holds no field report" in found[0].fix


def test_a_marker_narrows_within_the_allowed_set(catalog):
    body = f"Refs {ISSUE_URL}\n\n" + issue_tests.reported_at(issue_tests.TIP)
    chosen = forms.select(catalog, "pr.create", body, "feat/x", base="main", labels=["housekeeping"])
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
def test_free_texts_select_no_form(catalog, action, body, where):
    chosen = forms.select(catalog, action, body, "A title", **where)
    assert chosen.form is None and chosen.findings == ()


def test_an_adapter_marker_outside_the_allowed_set_is_refused(catalog):
    body = WORK_BODY.replace(forms.FLEET_MARKER, forms.FLEET_MARKER + "\n" + review.VERDICT_MARKER)
    chosen = forms.select(catalog, "issue.create", body, "feat/forms-20261116", labels=["work"])
    assert chosen.name == "work"
    assert [finding.fix for finding in chosen.findings] == [
        "the review form does not apply to issue.create: it shapes comment.create, comment.edit, "
        "and the body carries its marker"]


def test_home_is_origin_and_the_outside_repositories(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    fake_git.git("-C", str(tmp_path), "remote", "add", "origin", "https://github.com/o/r.git")
    (tmp_path / "se.toml").write_text('[outside]\n"github.com/other/side" = 12\n', encoding="utf-8")
    home = forms.home_repositories(tmp_path)
    assert home == {"github.com/o/r", "github.com/other/side"}
    catalog = forms.load(ROOT, tree=True)
    assert forms.select(catalog, "issue.create", WORK_BODY, "feat/x-20261116", repo="o/r",
                        home=home, labels=["work"]).name == "work"
    assert forms.select(catalog, "issue.create", WORK_BODY, "feat/x-20261116",
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
    form, _ = forms.verdict(catalog, "pr.edit", description, "feat/x", base="main")
    assert form.name == "field-report"


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
    form, found = forms.verdict(catalog, "comment.create", body, repo=REPO, home=HOME)
    assert form.name == "review" and [finding.fix for finding in found
                                      if finding.severity == forms.REFUSE] == [
        f"review: {problem}" for problem in expected]


def retro_block(**changes: object) -> dict:
    """The judgment tests/test_retro.py's judged draft holds, `changes` applied."""
    block = {"window": {"retro": 30}, "previous": {},
             "classes": [{"name": "Lost reports", "fix": "`integrate` refuses a landing without one"}],
             "findings": [test_retro.finding(),
                          test_retro.finding(title="Make the field report a rule of the rule book",
                                             home=retro.RULE_BOOK, controversial=True,
                                             why="it changes a rule")],
             "went_well": ["The fake door kept the tests fast."]}
    return {**block, **changes}


def marked_block(marker: str, block: dict) -> str:
    return f"# The draft\n\nThe facts.\n\n{marker}\n" + review.fenced(json.dumps(block, indent=2),
                                                                       "yaml") + "\n"


@pytest.mark.parametrize("changes", [{}] + [changes for changes, _ in parametrized(
    test_retro.test_file_refuses_an_incomplete_judgment_and_writes_nothing)])
def test_the_retro_adapter_gives_judgment_problems_verdict(catalog, changes):
    block = retro_block(**changes)
    assert adapter_verdict(catalog["retro"], marked_block(retro.BLOCK_MARKER, block)) == \
        retro.judgment_problems(block)


def test_the_retro_report_links_its_block_and_warns_without_refusing(catalog):
    block = retro.judged(marked_block(retro.BLOCK_MARKER, retro_block()), 30)
    text = retro.report(block, 30, "docs/retro-30.md", f"https://{REPO}/blob/x/docs/retro-30.md",
                        "a" * 40)
    form, found = forms.verdict(catalog, "comment.create", text, repo=REPO, home=HOME)
    assert form.name == "retro"
    assert [(finding.rule, finding.severity) for finding in found] == [("checker", forms.WARN)]
    assert f"no {retro.BLOCK_MARKER} block" in found[0].fix


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


@pytest.mark.parametrize("changes", [{}] + [changes for changes, _ in parametrized(
    test_overhaul.test_file_refuses_an_incomplete_judgment_and_writes_nothing)])
def test_the_overhaul_adapter_gives_judgment_problems_verdict(catalog, changes):
    block = overhaul_block(**changes)
    assert adapter_verdict(catalog["overhaul"], marked_block(overhaul.BLOCK_MARKER, block)) == \
        overhaul.judgment_problems(block)


def test_the_overhaul_report_passes_with_the_block_it_carries(catalog):
    text = marked_block(overhaul.BLOCK_MARKER, overhaul_block())
    posted = overhaul.report(text, overhaul.judged(text, 50), 50)
    form, found = forms.verdict(catalog, "comment.create", posted, repo=REPO, home=HOME)
    assert form.name == "overhaul" and found == []


# The decks whose decision deck.py's section rule refuses: those its test names, and the silent
# decision, which the build refuses for its missing bless first and which has no sections either.
UNEXPLAINED = {*parametrized(
    test_deck.test_build_refuses_a_decision_that_does_not_explain_the_problem_before_its_options),
    "decision-without-bless"}


@pytest.mark.parametrize("name", list(test_deck.DECKS))
def test_the_decision_adapter_gives_the_section_rule_of_deck_py(catalog, name):
    notes, _ = test_deck.DECKS[name]
    for note, text in notes.items():
        nodes = forms._nodes(text)
        expected = deck._holds_pugh(nodes) and name in UNEXPLAINED
        refused = adapter_verdict(catalog["decision"], text)
        assert bool(refused) == expected, (name, note)
        assert deck._explains(nodes) or not deck._holds_pugh(nodes) or refused
    form, _ = forms.verdict(catalog, "deck.build", next(iter(notes.values())))
    assert form.name == "decision"


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
    """One body a command sends: its action, the form it selects (FREE, or NO_BODY for a write
    without one), the body and where it goes."""
    action: str
    form: str | None
    body: str | None = None
    title: str | None = None
    base: str | None = None
    labels: tuple[str, ...] = ()


def step_cases(plan, forms_by_step: dict[str, str | None], base: str = "main") -> list[Case]:
    """The cases of `plan`'s sending steps, each step's form named in `forms_by_step`."""
    cases = []
    for step in plan.steps:
        if step.tool not in SENDING_TOOLS:
            continue
        arguments = step.arguments
        if step.action not in forms_by_step:  # `comment_duplicate:<twin>` and its kin
            forms_by_step = {**forms_by_step, step.action: forms_by_step.get(
                step.action.split(":", 1)[0], NO_BODY if "body" not in arguments else "unnamed")}
        if step.tool == "merge_pull_request":
            cases.append(Case("pr.merge", forms_by_step[step.action], arguments["commit_message"],
                              arguments["commit_title"], base))
        elif "body" not in arguments:
            cases.append(Case("issue.edit", NO_BODY))
        elif step.tool == "add_issue_comment":
            cases.append(Case("comment.create", forms_by_step[step.action], arguments["body"]))
        elif step.tool == "create_pull_request":
            cases.append(Case("pr.create", forms_by_step[step.action], arguments["body"],
                              arguments["title"], arguments["base"]))
        elif step.tool == "update_pull_request":
            cases.append(Case("pr.edit", forms_by_step[step.action], arguments["body"],
                              arguments.get("title"), base))
        else:
            action = "issue.create" if arguments.get("method") == "create" else "issue.edit"
            labels = arguments.get("labels")
            cases.append(Case(action, forms_by_step[step.action], arguments["body"],
                              arguments.get("title"),
                              labels=tuple(labels) if isinstance(labels, list) else ()))
    return cases


WORK_TITLE = "feat/forms-20261116"
WORK_LABELS = ("work", "ready")


def work_issue(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.create", "work", WORK_BODY, WORK_TITLE, labels=WORK_LABELS)]


def backlog_issue(catalog, monkeypatch) -> list[Case]:
    ticket = catalog["ticket"]
    fields = ticket_fields(catalog)
    return [Case("issue.create", "ticket", work_tickets.fleet_marked(forms.render(ticket, fields)),
                 fields["title"])]


def routed_issue(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.edit", "routed", work_tickets.routed_body(
        OUTSIDE, "Proposal: make it work", ROUTING), "feat/make-it-work-20261116")]


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
        case.title = WORK_TITLE if case.form == "work" else case.title
        case.labels = WORK_LABELS if case.form == "work" else case.labels
    return cases


def review_run(catalog, monkeypatch) -> list[Case]:
    return [Case("comment.create", "review", review.verdict_comment(5, review_report(), False)),
            Case("issue.edit", "work", open_points_body(), WORK_TITLE, labels=WORK_LABELS)]


def retro_report() -> str:
    block = retro.judged(marked_block(retro.BLOCK_MARKER, retro_block()), 30)
    return retro.report(block, 30, "docs/retro-30.md", f"https://{REPO}/blob/x/docs/retro-30.md",
                        "a" * 40)


def overhaul_report() -> str:
    text = marked_block(overhaul.BLOCK_MARKER, overhaul_block())
    return overhaul.report(text, overhaul.judged(text, 50), 50)


def retro_steps(catalog, monkeypatch) -> list[Case]:
    cases = []
    for text, form in ((retro_report(), "retro"), (overhaul_report(), "overhaul")):
        cases += step_cases(retro.file_steps(REPO, 30, [text]), {"comment_issue": form})
    parts = retro.parts(retro_report(), 30, limit=400)
    cases += step_cases(retro.file_steps(REPO, 30, parts[:1]), {"comment_issue": "retro"})
    cases += step_cases(retro.file_steps(REPO, 30, parts[1:2]), {"comment_issue": FREE})
    return cases


def tracker_comment(catalog, monkeypatch) -> list[Case]:
    return [Case("comment.create", "retro", retro_report()),
            Case("comment.create", "overhaul", overhaul_report()),
            Case("comment.create", FREE, "Integration stopped: the suite failed.\n")]


def blocker_link(catalog, monkeypatch) -> list[Case]:
    return [Case("issue.edit", "work", blocked(monkeypatch, WORK_BODY, 12), WORK_TITLE,
                 labels=WORK_LABELS)]


def plan_of(make, forms_by_step: dict[str, str | None]):
    return lambda catalog, monkeypatch: step_cases(make(), forms_by_step)


def filing(catalog, monkeypatch) -> list[Case]:
    step = work_tickets.work_issue_filing(REPO, WORK_TITLE, WORK_BODY, ["work", "ready"])
    plan = work_tickets.filing_plan(REPO, "file", WORK_TITLE, WORK_BODY, step)
    return step_cases(plan, {"create": "work", "comment_twin": FREE, "comment_duplicate": FREE})


def duplicates(catalog, monkeypatch) -> list[Case]:
    steps = work_tickets.close_duplicate_steps(REPO, 9, work_tickets.Later("twin", 1), "a twin",
                                               "where it has one")
    return step_cases(work_tickets.Plan("close", steps), {
        step.action: FREE for step in steps})


#: Each function in scripts/ that sends a body, and what the command it serves sends.
CONTRACT = {
    "work_tickets:work_issue_filing": ("file", work_issue),
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
        lambda: work_tickets.start_plan(REPO, 7, WORK_TITLE, "agent", False),
        {"assign": NO_BODY, "comment_issue": FREE})),
    "work_tickets:start_handed_off.assign": ("start", no_body()),
    "work_tickets:escalate": ("escalate", comment("Which of the two forms wins here?\n")),
    "work_tickets:escalation_plan": ("integrate", plan_of(
        lambda: work_tickets.escalation_plan(REPO, 7, "the suite failed"), {"comment_issue": FREE})),
    "work_tickets:label_step": ("start and integrate", no_body()),
    "work_tickets:tracker_actions.comment": ("retro.py, overhaul.py and escalations", tracker_comment),
    "work_tickets:landing_plan": ("integrate", landing),
    "work_tickets:closeout_plan": ("integrate", plan_of(
        lambda: work_tickets.closeout_plan(REPO, REPO, 5, 7, "abc1234", "Integrated in abc1234.\n",
                                           []),
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
def test_each_body_se_sends_selects_its_form_and_passes(catalog, monkeypatch, sender):
    command, cases = CONTRACT[sender]
    made = cases(catalog, monkeypatch)
    assert made, f"{sender} ({command}) has no case"
    for case in made:
        if case.form == NO_BODY:
            assert case.body is None
            continue
        form, found = forms.verdict(catalog, case.action, case.body, case.title, base=case.base,
                                    labels=case.labels, repo=REPO, home=HOME)
        assert (form.name if form else FREE) == case.form, (sender, case.action)
        refused = [str(finding) for finding in found if finding.severity == forms.REFUSE]
        assert refused == [], (sender, case.action, refused)


# Enforcing: the switch, the body a filing command files, private terms, the refusal, the count


def test_enforcement_defaults_to_off_and_reads_the_working_tree_without_the_ref(tmp_path,
                                                                                 fake_git_door):
    assert forms.enforcement(tmp_path) == forms.Enforcement("off", 2, "se.toml")
    (tmp_path / "se.toml").write_text('[forms]\nenforce = "warn"\nrefusals = 3\n', encoding="utf-8")
    assert forms.enforcement(tmp_path) == forms.Enforcement("warn", 3, "se.toml")


def test_enforcement_reads_the_integration_branch_where_its_ref_exists(tmp_path, fake_git_door):
    fake_git.init(tmp_path)
    (tmp_path / "se.toml").write_text('[project]\nintegration_branch = "dev"\n', encoding="utf-8")
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/dev", "HEAD")
    (tmp_path / "se.toml").write_text('[project]\nintegration_branch = "dev"\n[forms]\n'
                                      'enforce = "refuse"\n', encoding="utf-8")
    assert forms.enforcement(tmp_path) == forms.Enforcement("off", 2, "origin/dev:se.toml")
    commit_all(tmp_path)
    fake_git.git("-C", str(tmp_path), "update-ref", "refs/remotes/origin/dev", "HEAD")
    assert forms.enforcement(tmp_path).enforce == "refuse"


@pytest.mark.parametrize("table", ['enforce = "on"', "enforce = true", "refusals = 0",
                                   "refusals = true", 'refusals = "2"'])
def test_enforcement_refuses_a_value_outside_the_switch(tmp_path, fake_git_door, table):
    (tmp_path / "se.toml").write_text(f"[forms]\n{table}\n", encoding="utf-8")
    with pytest.raises(forms.FormError, match=r"\[forms\]"):
        forms.enforcement(tmp_path)


def test_formed_keeps_a_body_with_enforce_off_and_renders_it_otherwise(catalog):
    work = catalog["work"]
    body = "## Goal\n\nG.\n\n## Odd section\n\nKept.\n"
    assert forms.formed(work, body=body) == body
    again = forms.formed(work, body=body, enforce="warn")
    assert again.startswith(f"{forms.FLEET_MARKER}\n<!-- se:form work -->\n")
    assert "## Odd section\n\nKept.\n" in again
    fields = dict(work.example["fields"])
    assert forms.formed(work, fields=fields, enforce="off") == forms.render(work, fields)


def test_private_findings_name_the_field_and_the_list_never_the_term(catalog, tmp_path):
    (tmp_path / ".public-check.local").write_text("quuxcorp\n", encoding="utf-8")
    work = catalog["work"]
    body = forms.render(work, dict(work.example["fields"], goal="For Quuxcorp."))
    found = forms.private_findings(work, "feat/quuxcorp-20261116", body, tmp_path)
    assert [(item.field, item.rule, item.severity) for item in found] == [
        ("title", "private", "refuse"), ("goal", "private", "refuse")]
    assert all("quux" not in item.fix.lower() and "local list" in item.fix for item in found)
    assert forms.private_findings(work, "feat/x-20261116", body, tmp_path / "none") == []


def test_report_fits_ten_lines_names_every_finding_and_counts_no_tries(catalog):
    work = catalog["work"]
    found = [forms.Finding(f"f{index}", "required", "refuse", f"fix {index}") for index in range(14)]
    found.append(forms.Finding("goal", "words", "warn", "Goal has 99 words; keep it to 60"))
    text = forms.report("file", work, found, refused=True, hold="off-form")
    lines = text.splitlines()
    assert len(lines) <= forms.REFUSAL_LINES
    assert all(f"fix {index}" in text for index in range(14))
    assert any(line.startswith(f"{forms.ALSO} Goal: has 99 words") for line in lines)
    assert "forms.py draft work" in text and "--hold" in text and "off-form" in text
    assert "--hold" not in forms.report("file", work, found, refused=True)
    assert "fix its text on the issue itself and run work_tickets.py unhold <issue>" in text
    assert "unhold" not in forms.report("file", work, found, refused=True)


def test_refusals_are_counted_per_session_and_target_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    one = forms.target("work", "git.example/O/R", "issue.create", title="Feat/X-20261116 ")
    assert one == forms.target("work", "git.example/o/r", "issue.create", title="feat/x-20261116")
    other = forms.target("routed", "git.example/o/r", "issue.edit", number=4)
    env = {"SE_SESSION": "a"}
    assert forms.refusals(one, env) == 0
    assert [forms.count_refusal(one, env), forms.count_refusal(one, env)] == [1, 2]
    assert forms.refusals(other, env) == 0 and forms.refusals(one, {"SE_SESSION": "b"}) == 0
    assert forms.counts_file(env).parent == tmp_path / ".se" / "forms"



def missing_from_readme(readme: str) -> list[str]:
    """The files under `forms/` that README's "Forms" section does not name with their `says`."""
    start = readme.index("\n### Forms\n")
    after = re.search(r"\n#{1,3} ", readme[start + 1:])
    section = " ".join(readme[start:start + 1 + after.start() if after else None].split())
    missing = []
    for path in sorted((ROOT / "forms").glob("*.toml")):
        says = " ".join(tomllib.loads(path.read_text(encoding="utf-8"))["says"].split())
        if f"`forms/{path.name}`" not in section or says not in section:
            missing.append(path.name)
    return missing


def test_readme_forms_names_every_file_under_forms_with_its_says():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert missing_from_readme(readme) == []
    assert "No command checks with them yet" not in readme


def test_the_readme_check_fails_when_a_file_is_removed_from_the_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index("| `forms/retro.toml` |")
    end = readme.index("\n| `forms/review.toml` |", start)
    assert missing_from_readme(readme[:start] + readme[end + 1:]) == ["retro.toml"]
