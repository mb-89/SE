"""SE's forms (scripts/forms.py, forms/): loading, reading, writing, selection, every rule with a
failing and a passing fixture, the command, and the contracts with the writers SE has today."""

from __future__ import annotations

import ast
import json
import re
import shutil
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
    assert forms.select(catalog, "issue.edit", WORK_BODY, "feat/x-20261116").name == "work"
    assert forms.select(catalog, "issue.create", "## Situation\n", "Plain words").name == "ticket"
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
    ("title-shape", {"title": "feat/plain-titles-20261116"}, {}),
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
    fields = ticket_fields(catalog)
    repeated = {**fields, "situation": fields["title"] + " is the ask."}
    assert "title-shape" in rules(findings(catalog["ticket"], repeated), "warn")


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
    assert "Situation is missing" in out and "Requirements is empty" in out
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
    assert forms.main(["check", "ticket", "--tree", "--fields", str(fields), "--title", "42"]) == 0
    assert "title-shape" in capsys.readouterr().out


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
    form, found = forms.verdict(catalog, "issue.create", body, "feat/forms-20261116")
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
    chosen = forms.select(catalog, "issue.create", body, "feat/forms-20261116")
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
                        home=home).name == "work"
    assert forms.select(catalog, "issue.create", WORK_BODY, "feat/x-20261116",
                        repo="github.com/other/side", home=home).name == "work"


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
