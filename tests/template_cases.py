"""The template engine's shared cases (SE#1683): the Python engine, scripts/templates.py, answers each
case, and the Go engine, components/template, is held to the same answers by its test
(components/template/cases_test.go). One set of cases, so the two engines cannot drift.

`build()` gives every file of components/template/testdata/cases/, by name, as its text: one per
template set, each a JSON object whose first key, `generated`, names this module and what it read.
JSON, as it is the one format both standard libraries read. `tests/test_template_cases.py` fails
where a committed file differs; `uv run python tests/template_cases.py` writes them.

A set is the templates one load reads (SE's own `templates/`, or a fixture's files) and, per
template, what it loaded to and how it answers:

- `template`: its name, version, kind, digest, marker line, actions, the line `list` gives, its
  fields as `field_shape` gives them with `says`, and, but for an adapter, `draft` and
  `draft_fields`;
- `fills`: field values (with a title and the raw input) and what `fill` answers: the document's
  digest, the fields its parse gives back, and every finding; the base case, the example, keeps its
  document as text, which the body cases start from;
- `bodies`: a body (with a title) and what `parse` gives (fields, misses, recorded version), what
  `check` finds, and the digest of `render` of that parse.

A set's `select` cases name a body by the template whose base document it is, and give what
`select` answers. A set's `error` is the load error its files give, where they do not load.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import templates  # noqa: E402

OUT = ROOT / "components" / "template" / "testdata" / "cases"
GENERATED = ("by tests/template_cases.py from scripts/templates.py (the Python engine) and {source}; "
             "do not edit, run `uv run python tests/template_cases.py`")

#: The texts each field is filled with in turn, beside its own `says` and another field's value.
PROBES = (
    "",
    "TBD",
    "None",
    "Not in input",
    "_No response_",
    "See #12 and the plan.\nStatus: open",
    "We keep the worktree beside kern here.",
    "First thing done. Second thing done as well.",
    'The person said "keep the raw text" twice.',
    "> keep the raw text",
    "The owner runs it, and SE reads it.",
    "standard",
    "breaking, as the person said",
    "1. One.\n2. Two.",
)
RAW = 'The person asked: keep the raw text, please. Ship it "standard".'
TITLES = (None, "fix-the-thing", "Fix the Thing", "scripts/x.py", "#12", "a-b-c-d-e-f-g",
          "the plan stays put")


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _findings(found) -> list[list[str]]:
    return [[item.field, item.rule, item.severity, item.fix] for item in found]


def _as_kind(item: templates.Field, text: str) -> object:
    """`text` as a value of `item`'s kind, as an agent's fields give it."""
    if item.kind in ("list", "issue"):
        return [text]
    if item.kind == "checklist":
        return [{"done": False, "text": text}]
    if item.kind == "object":
        return {"Key": text}
    return text


def _template(template: templates.Template, templates_by_name: dict) -> dict:
    data = {
        "name": template.name, "version": template.version, "kind": template.kind,
        "digest": template.digest, "marker": template.marker_line, "actions": list(template.actions),
        "repository": template.repository, "adapter": template.is_adapter,
        "list": templates.list_templates({template.name: template})[0],
        "fields": [{**templates.field_shape(item), "name": item.name, "says": item.says}
                   for item in template.fields],
    }
    if not template.is_adapter:
        data["draft"] = templates.draft(template)
        data["draft_fields"] = templates.draft_fields(template)
    return data


def _fill(template: templates.Template, example: dict, title: str | None, raw: str, *,
          change: dict | None = None, drop: str = "", keep: bool = False) -> dict:
    """The fill of `example` with `change` applied and `drop` left out."""
    values = {key: copy.deepcopy(value) for key, value in example.items() if key != drop}
    values.update(copy.deepcopy(change or {}))
    case = {"change": change or {}, "drop": drop, "title": title, "raw": raw}
    try:
        document, found = templates.fill(template, values, raw, title=title)
    except templates.TemplateError as error:
        return {**case, "error": str(error)}
    title_field = next((item.name for item in template.fields if item.source == "title"), None)
    named = (title if title is not None else values.get(title_field)) if title_field else None
    parsed = templates.parse(template, document, named if isinstance(named, str) else None)
    case.update({"digest": _digest(document), "findings": _findings(found)})
    if keep:
        case.update({"document": document, "parsed": parsed.fields})
    return case


def _body(template: templates.Template, body: str, title: str | None) -> dict:
    document = templates.parse(template, body, title)
    found = templates.check(template, document)
    rendered = templates.render(template, document)
    return {"body": body, "title": title, "fields": document.fields,
            "misses": sorted(document.misses), "recorded": document.recorded,
            "findings": _findings(found), "render": _digest(rendered)}


def _fills(template: templates.Template, example: dict, title: str | None) -> list[dict]:
    """The base fill, then each field filled with each probe, its own `says`, another field's
    value, or left out (`_fill_inputs`)."""
    return [_fill(template, example, *given, **options)
            for given, options in _fill_inputs(template, example, title)]


def _fill_inputs(template: templates.Template, example: dict, title: str | None
                 ) -> list[tuple[tuple, dict]]:
    """What each of `_fills`' cases fills: the title and raw input, and `_fill`'s options."""
    cases: list[tuple[tuple, dict]] = [((title, RAW), {"keep": True})]
    others = [item for item in template.fields if item.source != "title"]
    for item in others:
        probes = [*PROBES, item.says]
        other = next((field for field in others if field.name != item.name and field.name in example
                      and isinstance(example[field.name], type(_as_kind(item, "")))), None)
        values = [_as_kind(item, probe) for probe in probes]
        if other is not None:
            values.append(copy.deepcopy(example[other.name]))
        if item.kind == "text" and item.max_words:
            values.append(" ".join(["word"] * (item.max_words + 3)))
        if item.first_sentence_chars:
            values.append("A first sentence " + "that runs " * item.first_sentence_chars + ". Then more.")
        for value in values:
            cases.append(((title, RAW), {"change": {item.name: value}}))
        cases.append(((title, RAW), {"drop": item.name}))
    if any(item.source == "title" for item in template.fields):
        cases += [((other, RAW), {}) for other in TITLES if other != title]
    cases.append(((title, "Nothing of it."), {}))
    return cases


def _variants(template: templates.Template, document: str) -> list[str]:
    """Bodies made from the base document: its headings in other spellings, a section emptied, an
    unknown section, front matter above it, its version moved, and the bare document of a draft."""
    hashes = "#" * template.level
    sections = [item for item in template.fields if item.in_body]
    found = [document]
    if sections:
        first = sections[0]
        heading = f"{hashes} {first.heading}\n"
        if heading in document:
            found.append(document.replace(heading, f"### {first.heading.lower()}:\n", 1))
            found.append(document.replace(heading, f"#### {first.heading.upper()}\n", 1))
            found.append(document.replace(heading, f"{hashes} {first.heading}s\n", 1))
            start = document.index(heading) + len(heading)
            end = document.find(f"\n{hashes} ", start)
            end = len(document) if end < 0 else end + 1
            found.append(document[:start] + "\n_No response_\n\n" + document[end:])
            found.append(document[:start] + "\n<!-- only a comment -->\n\n" + document[end:])
            found.append(document[:start] + "\nNone.\n\n" + document[end:])
        found.append(document.rstrip("\n") + f"\n\n{hashes} Notes\n\nKept as it is.\n")
        found.append(document.rstrip("\n") + f"\n\n{hashes} {sections[-1].heading}\n\nAgain.\n")
    found.append("---\nid: X1\n---\n" + document)
    if template.version and template.marker_line in document:
        major, minor, patch = template.version.split(".")
        for version in (f"{major}.{int(minor) + 1}.{patch}", f"{int(major) + 1}.0.0", "next"):
            found.append(document.replace(f" {template.version} ", f" {version} ", 1))
    if any(item.fence for item in template.fields):
        found.append(document.replace("candidates:", "options:", 1))
        found.append(document.replace("criteria:", "criteria: []\nold_criteria:", 1))
    found.append(templates.draft(template))
    found.append(document.replace("\n", "\r\n"))
    return found


def _set(name: str, loaded: dict[str, templates.Template], source: str, files: dict | None = None,
         repository: str = "", bodies: dict[str, list[str]] | None = None) -> dict:
    data: dict[str, object] = {"generated": GENERATED.format(source=source), "set": name}
    if files is not None:
        data["files"] = files
        data["repository"] = repository
    made = {}
    bases: dict[str, str] = {}
    for template in sorted(loaded.values(), key=lambda item: item.name):
        entry = {"template": _template(template, loaded)}
        if not template.is_adapter:
            example = dict(template.example.get("fields", {})) if template.example else {}
            title = template.example.get("title") if template.example else None
            fills = _fills(template, example, title)
            entry["example"] = example
            entry["fills"] = fills
            base = fills[0].get("document") or ""
            bases[template.name] = base
            entry["bodies"] = [_body(template, body, title)
                               for body in [*_variants(template, base),
                                            *(bodies or {}).get(template.name, [])]]
            if any(item.source == "title" for item in template.fields):
                entry["bodies"] += [_body(template, base, other) for other in TITLES if other != title]
        made[template.name] = entry
    data["templates"] = made
    data["select"] = _select(loaded, bases)
    return data


def _select(loaded: dict[str, templates.Template], bases: dict[str, str]) -> list[dict]:
    cases = []
    every = sorted({label for template in loaded.values() for label in template.labels})
    label_sets = [[], every] if every else [[]]
    for action in templates.ACTIONS:
        if action == templates.FILE_ACTION:
            continue
        for body_of in ["", *sorted(bases)]:
            body = bases.get(body_of, "Free text.\n")
            for labels in label_sets:
                for base in (None, "main"):
                    chosen = templates.select(loaded, action, body, None, labels=list(labels), base=base)
                    cases.append({"action": action, "body_of": body_of, "labels": list(labels),
                                  "base": base, "selected": chosen.name,
                                  "findings": _findings(chosen.findings)})
            for repo in ("example/outside", "ex/se") if body_of in ("", "work") else ():
                chosen = templates.select(loaded, action, body, None, repo=repo,
                                          home={"github.com/ex/se"})
                cases.append({"action": action, "body_of": body_of, "repo": repo,
                              "home": ["github.com/ex/se"], "selected": chosen.name,
                              "findings": _findings(chosen.findings)})
    return cases


# Fixtures: templates outside SE's own


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
example:
  fields:
    risks: ["The scan misses a tool."]
---

## Risks

<!-- risks: One item per risk, or None. -->
"""
STEP = "---\nid: S5B\nname: Risks\n---\n\n# Risks\n\n## Risks\n\n- The scan misses a tool.\n"
KINDS_TEMPLATE = """---
name: kinds
version: 2.1.0
kind: document
tags: ["test"]
reader: fleet
says: "Every kind of field."
applies:
  actions: ["comment.create"]
  marker: "<!-- se:kinds -->"
keep_unknown: false
rules:
  required: refuse
  choice: refuse
  duplicate: refuse
  words: warn
  bare-number: warn
  board: warn
  unnamed-entry: warn
fields:
  - name: owner
    kind: line
    label: Owner
    required: true
    says: "Who owns it."
  - name: pick
    kind: choice
    choices: ["red", "green"]
    required: true
  - name: steps
    kind: list
    numbered: true
    markers: true
  - name: more
    kind: list
    numbered: true
    continue_numbers: true
  - name: done
    kind: checklist
  - name: refs
    kind: issue
    none_ok: true
  - name: meta
    kind: object
  - name: run
    kind: code
    lang: py
  - name: quote
    kind: text
    quote: true
  - name: exact
    kind: text
    exact_heading: true
  - name: keep
    kind: text
    verbatim: true
example:
  fields:
    owner: alice
    pick: red
    steps: ["One.", "<!-- a marker -->", "Two."]
    more: ["Three."]
    done: [{"done": true, "text": "Built."}, {"done": false, "text": "Shipped."}]
    refs: ["#3 the parser"]
    meta: {"Area": "core", "Size": "small"}
    run: "print(1)"
    quote: 'They said "keep the raw text".'
    exact: "Only as written."
    keep: "  kept   as\\n  it is  "
---

## Pick

<!-- pick: Red or green. -->

## Steps

<!-- steps: The steps. -->

## More

<!-- more: More steps, numbered on. -->

## Done

<!-- done: What is done. -->

## Refs

<!-- refs: Issues it refers to. -->

## Meta

<!-- meta: Key: value lines. -->

## Run

<!-- run: The code. -->

## Quote

<!-- quote: A quote of the raw input. -->

## Exact

<!-- exact: Only under its exact heading. -->

## Keep

<!-- keep: Kept as written. -->
"""
SCOPED_TEMPLATE = """---
name: scoped
version: 1.0.0
kind: block
tags: ["test"]
reader: owner
says: "A section after a marker."
applies:
  actions: ["issue.edit"]
  marker: "<!-- se:scoped -->"
scope:
  after: "<!-- se:scoped -->"
  section: Routing
  level: 3
rules:
  required: refuse
fields:
  - name: kind
    kind: choice
    choices: ["bug", "idea"]
    required: true
  - name: why
    kind: text
example:
  fields:
    kind: bug
    why: "It breaks."
---

### Kind

<!-- kind: Bug or idea. -->

### Why

<!-- why: Why. -->
"""
SCOPED_BODY = ("The outside text, kept.\n\n## Their heading\n\nTheirs.\n\n<!-- se:scoped -->\n\n"
               "## Routing\n\n### Kind\n\nidea\n\n### Why\n\nIt helps.\n\n## After\n\nKept too.\n")


def _broken() -> list[tuple[str, dict[str, str]]]:
    """Template sets that do not load, each named, with its files."""
    minimal = MINIMAL.format(name="one", extra=ISSUE_CREATE)
    notes = {
        "no-applies": MINIMAL.format(name="one", extra=""),
        "warn-refused": MINIMAL.format(name="one", extra=f"{ISSUE_CREATE}rules:\n  words: refuse\n"),
        "unknown-action": MINIMAL.format(name="one", extra='applies:\n  actions: ["issue.delete"]\n'),
        "unknown-rule": MINIMAL.format(name="one", extra=f"{ISSUE_CREATE}rules:\n  shout: warn\n"),
        "heading": minimal.replace("    required: true\n---", "    required: true\n    heading: Goal\n---"),
        "says": minimal.replace("    required: true\n---", "    required: true\n    says: The goal.\n---"),
        "no-section": minimal.replace("## Goal\n\n<!-- goal: The goal. -->\n", ""),
        "other-field": minimal.replace("<!-- goal:", "<!-- aim:"),
        "no-comment": minimal.replace("<!-- goal: The goal. -->", "The goal."),
        "text-before": minimal.replace("---\n\n## Goal", "---\n\nA note.\n\n## Goal"),
        "page-title": minimal.replace("## Goal", "# Goal"),
        "no-version": minimal.replace("version: 1.0.0\n", ""),
        "no-semver": minimal.replace("version: 1.0.0", 'version: "1.0"'),
        "kind": minimal.replace("kind: document", "kind: page"),
        "tags": minimal.replace('tags: ["test"]\n', ""),
        "no-front-matter": minimal.removeprefix("---\n"),
        "tab": minimal.replace("reader: owner\n", "reader: owner\n\tkind: x\n"),
        "off": minimal.replace("reader: owner\n", "reader: owner\nkeep_unknown: off\n"),
        "float": minimal.replace("version: 1.0.0", "version: 1.5"),
        "colon": minimal.replace("says: A template.", "says: The name: a title"),
        "twice": minimal.replace("reader: owner\n", "reader: owner\nreader: fleet\n"),
        "empty-key": minimal.replace("reader: owner\n", "reader: owner\nactors:\n"),
        "indent": minimal.replace("reader: owner\n", "reader: owner\n  kind: x\n"),
        "unknown-key": minimal.replace("reader: owner\n", "reader: owner\ncolour: red\n"),
        "reader": minimal.replace("reader: owner", "reader: everyone"),
        "field-kind": minimal.replace("kind: text", "kind: prose"),
        "field-key": minimal.replace("    required: true\n---", "    required: true\n    colour: red\n---"),
        "choice-without": minimal.replace("kind: text", "kind: choice"),
        "order": minimal.replace("reader: owner\n", "reader: owner\norder: [\"goal\", \"aim\"]\n"),
        "base": minimal.replace(ISSUE_CREATE, 'applies:\n  actions: ["pr.create"]\n  base: next\n'),
        "applies-key": minimal.replace(ISSUE_CREATE, 'applies:\n  actions: ["pr.create"]\n  branch: main\n'),
        "paths-alone": minimal.replace(ISSUE_CREATE, 'applies:\n  actions: ["issue.create"]\n  paths: ["*.md"]\n'),
        "file-without-paths": minimal.replace(ISSUE_CREATE, 'applies:\n  actions: ["file.write"]\n'),
        "paths-no-list": minimal.replace(ISSUE_CREATE, 'applies:\n  actions: ["file.write"]\n  paths: "*.md"\n'),
        "node-bad-pin": minimal.replace("    kind: text\n", "    node: pugh\n"),
        "node-and-kind": minimal.replace("    kind: text\n", "    kind: text\n    node: two@1.0.0\n"),
        "node-missing": minimal.replace("    kind: text\n", "    node: two@1.0.0\n"),
        "node-kind-alone": minimal.replace("    kind: text\n", "    kind: node\n"),
        "fence-alone": minimal.replace("    kind: text\n", "    kind: text\n    fence: pugh\n"),
        "adapter-fields": minimal.replace("reader: owner\n", "reader: owner\nchecker: deck:pugh_problems\n"),
        "adapter-reference": f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n'
                             'checker: review.checked_report\napplies:\n  actions: ["comment.create"]\n---\n',
        "adapter-key": f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n'
                       'checker: deck:pugh_problems\napplies:\n  actions: ["comment.create"]\n'
                       'adapter:\n  read: body\n---\n',
        "adapter-truth": f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n'
                         'checker: deck:pugh_problems\napplies:\n  actions: ["comment.create"]\n'
                         'adapter:\n  result: truth\n---\n',
        "adapter-line": f'---\n{HEAD.format(name="one")}reader: fleet\nsays: A text.\n'
                        'applies:\n  actions: ["comment.create"]\nadapter:\n  lines:\n    - pattern: x\n---\n',
        "name": minimal.replace("name: one", "name: two"),
    }
    sets = [(name, {"one.md": text}) for name, text in notes.items()]
    sets.append(("extends-cycle", {
        "a.md": MINIMAL.format(name="a", extra=f"extends: b\n{ISSUE_CREATE}"),
        "b.md": MINIMAL.format(name="b", extra=f"extends: a\n{ISSUE_CREATE}")}))
    sets.append(("extends-missing", {"a.md": MINIMAL.format(name="a", extra=f"extends: z\n{ISSUE_CREATE}")}))
    two = MINIMAL.format(name="two", extra='kind: block\n').replace("kind: document\n", "")
    sets.append(("node-version", {
        "one.md": minimal.replace("    kind: text\n", "    node: two@2.0.0\n"), "two.md": two}))
    sets.append(("node-entry-kind", {
        "one.md": minimal.replace("    kind: text\n", "    entries: two@1.0.0\n"), "two.md": two}))
    return sets


def _fixture(name: str, files: dict[str, str], bodies: dict[str, list[str]] | None = None) -> dict:
    loaded = templates._loaded([(templates.PROJECT_REPOSITORY, files,
                                 lambda file: f"{templates.TEMPLATES}/{file}")])
    return _set(name, loaded, f"its files below", files, templates.PROJECT_REPOSITORY, bodies)


def _file_cases(files: dict[str, str]) -> list[dict]:
    """A file template's selection by path, and its fill of a file that exists."""
    loaded = templates._loaded([(templates.PROJECT_REPOSITORY, files,
                                 lambda file: f"{templates.TEMPLATES}/{file}")])
    cases = []
    for path in ("book/m1/steps/51-S5B.md", "book/m1/notes.md", "book\\m1\\steps\\x.md", "/book/a/steps/b.md"):
        for body in (STEP, "---\ntemplate: other\n---\n", "---\ntemplate: project/risks\n---\n",
                     "id: S5B\n"):
            chosen = templates.select(loaded, templates.FILE_ACTION, body, None, path=path)
            cases.append({"action": templates.FILE_ACTION, "path": path, "body": body,
                          "selected": chosen.name, "findings": _findings(chosen.findings)})
    return cases


def _existing(files: dict[str, str]) -> list[dict]:
    loaded = templates._loaded([(templates.PROJECT_REPOSITORY, files,
                                 lambda file: f"{templates.TEMPLATES}/{file}")])
    template = loaded["risks"]
    cases = []
    for existing in (STEP, "# Risks\n\nIntro.\n\n## Other\n\nKept.\n", ""):
        for values in ({"risks": ["One."]}, {"risks": "None"}):
            document, found = templates.fill(template, values, RAW, existing=existing or None)
            cases.append({"existing": existing, "fields": values, "document": document,
                          "findings": _findings(found)})
    return cases


def build() -> dict[str, str]:
    """Every case file, by its name, as its text."""
    made: dict[str, dict] = {}
    se = _set("se", templates.load(ROOT, tree=True), "SE's templates/")
    for name, entry in se["templates"].items():
        made[f"se-{name}.json"] = {"generated": se["generated"], "set": "se", "templates": {name: entry}}
    made["se-select.json"] = {"generated": se["generated"], "set": "se", "templates": {},
                              "select": se["select"]}
    step_files = {
        "risks.md": STEP_TEMPLATE.format(name="risks", paths='"book/*/steps/*.md"',
                                         extra='  marker_pattern: "id: S5B"\n'),
        "plain.md": STEP_TEMPLATE.format(name="plain", paths='"book/**/*.md"', extra="  order: 200\n"),
    }
    step = _fixture("files", step_files, {"risks": [
        STEP, "---\nid: S5B\n---\n\n# Risks\n\n- The scan misses a tool.\n", "# Risks\n\n## Risks\n\nNone\n",
        "---\ntemplate: project/risks\nversion: 1.1.0\n---\n\n## Risks\n\n- One.\n",
        "---\ntemplate: risks\nversion: 2.0.0\n---\n\n## Risks\n\n- One.\n"]})
    step["files_select"] = _file_cases(step_files)
    step["existing"] = _existing(step_files)
    made["files.json"] = step
    kinds_body = ("<!-- se:kinds -->\nOwner: bob\n\n## Pick\n\ngreen, of course\n\n## Steps\n\n1. A.\n"
                  "<!-- kept -->\n2. B\n   continued.\n\n## More\n\n3. C.\n\n## Done\n\n- [x] X.\n- [ ] Y.\n\n"
                  "## Refs\n\n- #4\n- owner/repo#5 the fix\n\n## Meta\n\n- Area: core\nSize : small\n\n"
                  "## Run\n\n```py\nprint(2)\n```\n\n## Quote\n\n> keep the raw text\n\n"
                  "### Exact\n\nNot exact.\n\n## Keep\n\n  as   it\n    stands\n\n## Unknown\n\nDropped.\n")
    made["kinds.json"] = _fixture("kinds", {"kinds.md": KINDS_TEMPLATE}, {"kinds": [
        kinds_body, kinds_body.replace("green, of course", "blue"),
        kinds_body.replace("Owner: bob\n", ""), kinds_body.replace("- #4\n", "None\n")]})
    made["scoped.json"] = _fixture("scoped", {"scoped.md": SCOPED_TEMPLATE}, {"scoped": [
        SCOPED_BODY, SCOPED_BODY.replace("idea", "plan"), "No marker here.\n",
        "Text.\n\n<!-- se:scoped -->\n\nNo section.\n"]})
    errors = []
    for name, files in _broken():
        try:
            templates._loaded([(templates.PROJECT_REPOSITORY, files,
                                lambda file: f"{templates.TEMPLATES}/{file}")])
        except templates.TemplateError as error:
            errors.append({"name": name, "files": files, "error": str(error)})
        else:
            raise AssertionError(f"template_cases: the broken set {name} loads")
    made["load-errors.json"] = {"generated": GENERATED.format(source="the broken sets below"),
                                "set": "load-errors", "errors": errors}
    return {name: json.dumps(data, ensure_ascii=False) + "\n" for name, data in made.items()}


def drift(wanted: dict[str, str] | None = None) -> list[str]:
    """One line per case file that differs from what `build` makes (or `wanted`, what it made), is
    missing, or that it does not make."""
    wanted = build() if wanted is None else wanted
    present = {path.name: path.read_text(encoding="utf-8") for path in sorted(OUT.glob("*.json"))} \
        if OUT.is_dir() else {}
    return ([f"{name}: missing" for name in wanted if name not in present]
            + [f"{name}: differs from what tests/template_cases.py makes" for name in wanted
               if name in present and present[name] != wanted[name]]
            + [f"{name}: tests/template_cases.py makes no such file" for name in present if name not in wanted])


def write() -> list[str]:
    """Write every case file and remove those `build` does not make; the names it changed."""
    wanted = build()
    OUT.mkdir(parents=True, exist_ok=True)
    changed = []
    for path in sorted(OUT.glob("*.json")):
        if path.name not in wanted:
            path.unlink()
            changed.append(path.name)
    for name, text in wanted.items():
        path = OUT / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(name)
    return changed


if __name__ == "__main__":
    for name in write():
        print(f"wrote {OUT.relative_to(ROOT).as_posix()}/{name}")
