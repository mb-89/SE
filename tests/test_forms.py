"""SE's forms (scripts/forms.py, forms/): loading, reading, writing, selection, every rule with a
failing and a passing fixture, the command, and the contracts with the writers SE has today."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fake_git
import forms
import outside_text
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


def test_every_form_loads_with_its_actions_and_the_terms(catalog):
    assert set(catalog) == {"ticket", "work", "routed"}
    assert all(form.actions == forms.ACTIONS for form in catalog.values())
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
    for form in catalog.values():
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
    assert forms.select(forms.load(tmp_path, tree=True), "issue.create", "", "") is None


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
    assert [line.split(" ")[0] for line in out] == ["routed", "work", "ticket"]
    assert all("issue.create, issue.edit" in line for line in out)


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
