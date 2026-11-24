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
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import git_door  # noqa: E402
import code_templates  # noqa: E402
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
    """What parse gives of a body, what check finds (or, where its adapter is written wrong for
    the body, the error it raises) and the digest of render."""
    document = templates.parse(template, body, title)
    case = {"body": body, "title": title, "fields": document.fields,
            "misses": sorted(document.misses), "recorded": document.recorded}
    try:
        case["findings"] = _findings(templates.check(template, document))
    except templates.TemplateError as error:
        case["error"] = str(error)
    return {**case, "render": _digest(templates.render(template, document))}


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


#: Texts naming SE's commands and scripts, each appended to the base document of a template whose
#: rule `dangling` is on: what exists, what does not, and the Requirements that create it. The
#: scripts named define a tree that rarely changes (review.py, se_plugin.py), as each finding lists it.
DANGLING = (
    "Run `review.py brief` and `<se>/scripts/review.py file`.\n",
    "Run `review.py nope` first.\n",
    "Run `uv run python scripts/review.py brief extra`, then `se_plugin.py check`.\n",
    "Run `se_plugin.py nope.` and `se_plugin.py Build`.\n",
    "Run `scripts/missing_tool.py` and `<se>/scripts/gone.py check`.\n",
    "Run `scripts/<name>.py` and `scripts/review.py:12`.\n",
    "Run ``review.py nope`` and `` `review.py` ``.\n",
    "A span over two lines: `review.py\nnope`.\n",
    "An unclosed `review.py nope\n\nAnd ``review.py nope` too.\n",
    "```sh\nuv run python <se>/scripts/review.py nope\nreview.py brief\n```\n",
    "~~~\nse_plugin.py nope\n```\nreview.py nope\n~~~\nreview.py `nope`\n",
    "````\nreview.py nope\n```\nreview.py gone\n````\n",
    "Run `review.py nope`.\n\n## Requirements\n\n1. Add the new `review.py nope`.\n",
    "Run `scripts/missing_tool.py`.\n\n## Requirements\n\n- It creates\n  missing_tool.py.\n",
    "Run `review.py nope`.\n\n## Requirements\n\n1. Keep `review.py nope` as it is.\n",
)


def _dangling(template: templates.Template, base: str) -> list[str]:
    """Bodies made from the base document with a text of DANGLING appended, for a template whose
    rule `dangling` is on."""
    if template.severity("dangling") == templates.OFF or not base:
        return []
    return [base.rstrip("\n") + "\n\n" + text for text in DANGLING]


# Adapters: the texts SE already writes, each checked by its own checker (templates.py "Adapters").


def _fenced(marker: str, data: object, fence: str = "```yaml") -> str:
    ticks = fence[:len(fence) - len(fence.lstrip("`"))]
    return f"Above.\n\n{marker}\n{fence}\n{json.dumps(data, indent=2, ensure_ascii=False)}\n{ticks}\n"


def _report(header: dict[str, str | None] | None = None, sections: dict[str, str | None] | None = None,
            before: str = "", after: str = "") -> str:
    """A field report between its markers: every section of SE's pull request template, filled,
    with `header` lines and `sections` changed (None drops one)."""
    lines = {"Work issue": "#12", "Branch": "`plain-issue-titles`", "Result": "complete"}
    head = {"Work issue": "**Work issue:** #12  **Branch:** `plain-issue-titles`  **Result:** complete",
            "Tested against": "**Tested against `main`:** `0123456789abcdef0123456789abcdef01234567`",
            "Branch tip": "**Branch tip:** `abcdef1`",
            "Release kind": "**Release kind:** patch — a fix of the title",
            "Re-integration kind": "**Re-integration kind:** patch"}
    del lines
    head.update(header or {})
    body = {
        "User requirement (quoted back)": "> Titles say what changes.",
        "Delivered": "| Work issue item | Result | Commits | Evidence |\n|---|---|---|---|\n"
                     "| 1 | done | abcdef1 | `pytest` passed |\n\n**Commit groupings:** None\n\n"
                     "**Suite time:** None",
        "Not delivered": "None",
        "Removed behaviour, deleted or weakened tests, and authored prose": "None",
        "Review responses": "None",
        "Decisions": "| Decision | Alternatives | Rationale | Confidence |\n|---|---|---|---|\n"
                     "| Keep it | none | simple | high |",
        "Spec gaps": "None.",
        "Tickets for other repositories": "None",
        "Retro": _questions(),
    }
    body.update(sections or {})
    text = "\n".join(line for line in head.values() if line is not None) + "\n"
    for heading, content in body.items():
        if content is not None:
            text += f"\n## {heading}\n\n{content}\n"
    return f"{before}<!-- se:field-report -->\n{text}<!-- se:field-report:end -->\n{after}"


def _questions(answer: str = "None.", drop: str = "", rename: str = "") -> str:
    """The standing questions as a field report's Retro section answers them: one `###` section
    each, `drop` left out and `rename` under another heading."""
    block = templates.own("standing-questions")
    parts = []
    for item in block.fields:
        if item.name == drop:
            continue
        heading = item.heading + "?" if item.name == rename else item.heading
        parts.append(f"### {heading}\n\n{answer}")
    return "\n\n".join(parts)


REVIEW = {"pull": 7, "verdict": "pass", "head": "0123456789abcdef0123456789abcdef01234567", "landed": False,
          "acceptance": [{"item": "Titles say what changes.", "evidence": "tests pass"}],
          "findings": [], "clean": ["the title code"]}
FINDING = {"title": "A title", "evidence": "x.py:3", "place": "x.py:3", "blocking": False, "why": "small"}
def _changed(data: dict, **changes: object) -> dict:
    """`data` with each key changed (a value of DROP removes the key); `<key>__<n>__<field>`
    changes item n of a list."""
    data = copy.deepcopy(data)
    for key, value in changes.items():
        target, name = data, key
        if "__" in key:
            path, index, name = key.split("__")
            target = data[path][int(index)]
        if value is DROP:
            target.pop(name, None)
        else:
            target[name] = value
    return data


DROP = object()


def _adapter_bodies(template: templates.Template) -> list[tuple[str, str | None]]:
    """The bodies each of SE's adapters is checked on, with their titles."""
    review, retro, overhaul = "<!-- se:review -->", "<!-- se:retro-yaml -->", "<!-- se:overhaul-yaml -->"
    if template.name == "field-report":
        bad_rows = "| Item | Result |\n|---|---|\n| 1 | done | extra |\n\n**Commit groupings:** None\n\n**Suite time:** None"
        return [(text, None) for text in (
            "Free text.\n", "<!-- se:field-report -->\n<!-- se:field-report:end -->\n",
            "<!-- se:field-report:end -->\n<!-- se:field-report -->\n",
            _report(), _report(before="A note above.\n\n", after="\nBelow.\n"),
            _report(header={"Result": None, "Work issue": "**Work issue:** #<n>  **Branch:** `<branch>`"}),
            _report(header={"Branch tip": "**Branch tip:** `<tip>`"}),
            _report(header={"Branch tip": "**Branch tip:** abcdef1234"}),
            _report(header={"Branch tip": "**Branch tip:** `abcdef`"}),
            _report(header={"Branch tip": "**Branch tip:** `" + "a" * 41 + "`"}),
            _report(header={"Branch tip": "**Branch tip:** `abcdef1`x"}),
            _report(header={"Branch tip": "**Branch tip:** abcdef1 \u2014 the tip"}),
            _report(header={"Release kind": None}),
            _report(header={"Release kind": "**Release kind:** huge"}),
            _report(header={"Release kind": "**Release kind:** minor: new titles"}),
            _report(header={"Release kind": "**Release kind:** patch <!-- a comment --> — why"}),
            _report(header={"Re-integration kind": "**Re-integration kind:** later"}),
            _report(header={"Re-integration kind": None}),
            _report(header={"Component kinds": "**Component kinds:** se patch, app minor — both"}),
            _report(header={"Component kinds": "**Component kinds:** se big"}),
            _report(header={"Component kinds": "**Component kinds:** se"}),
            _report(header={"Work issue": "**Work issue:** #12  **Branch:** `b`  **Result:** done"}),
            _report(header={"Work issue": "**Work issue:** #12  **Branch:** `b`  **Result:** partial  "}),
            _report(sections={"Removed behaviour, deleted or weakened tests, and authored prose":
                              "- **Breaking:** the old flag\n**Breaking:** the old name"}),
            _report(header={"Release kind": "**Release kind:** minor — a breaking change"},
                    sections={"Removed behaviour, deleted or weakened tests, and authored prose":
                              "- **Breaking:** the old flag"}),
            _report(sections={"Spec gaps": None, "Retro": None}),
            _report(sections={"Delivered": bad_rows}),
            _report(sections={"Delivered": "Done.\n\n**Commit groupings:** None"}),
            _report(sections={"Decisions": "None", "Review responses": "none."}),
            _report(sections={"Not delivered": "```\n## Retro\n```\nAll of it."}),
            _report(sections={"Retro": "- **Went well:** x"}),
            _report(sections={"Retro": _questions(drop="real_use")}),
            _report(sections={"Retro": _questions(answer="")}),
            _report(sections={"Retro": _questions(answer="TBD", rename="stale_process")}),
            _report(sections={"Retro": _questions(answer="We ran `review.py brief` by hand twice.")}),
            _report(sections={"Delivered": "| work issue ITEM | Result | Commits | Evidence |\n|---|---|---|---|\n"
                                           "| 1 \\| 2 | done | a | b |\n\n**Commit groupings:** a\n\n**Suite time:** 3 s"}),
            _report().replace("## Decisions", "## DECISIONS"),
            _report().replace("\n## Spec gaps", "\n##   Spec gaps  "),
        )]
    if template.name == "merge-message":
        long = "Integrate " + "word-" * 30 + "end: and **more** text"
        return [
            ("A body.\n\nRelease-kind: minor\n", "Integrate plain-issue-titles"),
            ("A body.\n\nRelease-kind: minor\n", None),
            ("A body.\n\nRelease-kind: minor\n", "Merge plain-issue-titles"),
            ("No trailer.\n", "Integrate plain-issue-titles"),
            ("Release-kind: patch\nRelease-kind: minor\n", "Integrate x"),
            ("Release-kind: huge\n", "Integrate x: the **thing**"),
            ("Release-kind:patch   \n", "Integrate x"),
            ("Release-kind: \n", "Integrate x"),
            ("Release-kind: minor more\n", "Integrate x"),
            ("Text.\n\nRelease-kind: major", long),
            ("", ""),
        ]
    if template.name == "review":
        def report(**changes: object) -> str:
            return _fenced(review, _changed(REVIEW, **changes))
        bodies = [
            "No marker.\n", f"{review}\nNo block.\n", f"{review}\n```\n\n```\n",
            report(), report(pull=DROP, landed=DROP), _fenced(review, REVIEW, "````json"),
            f"{review}\n```yaml\n{{}}\n```\n\n{review}\n```\n[]\n```\n",
            report(extra=1), report(verdict="passed"), report(verdict=None), report(verdict=3),
            report(verdict=["pass"]), report(verdict={"a": 1.5}), report(head="0123"),
            report(head=" 0123456789abcdef0123456789abcdef01234567 "), report(clean=[]),
            report(clean=["", "x"]), report(clean="x"), report(acceptance=[]),
            report(acceptance=["x"]), report(acceptance=[{"item": "x", "proof": "y"}]),
            report(acceptance=[{"item": " ", "evidence": "y"}]),
            report(acceptance=[{"item": "x"}]), report(findings="none"), report(findings=[1]),
            report(findings=[{**FINDING, "rank": 1}]), report(findings=[{**FINDING, "title": ""}]),
            report(findings=[{**FINDING, "evidence": ""}]), report(findings=[{**FINDING, "place": None}]),
            report(findings=[{**FINDING, "blocking": 1}]), report(findings=[{**FINDING, "why": " "}]),
            report(verdict="decline"), report(verdict="decline", findings=[{**FINDING, "blocking": True}]),
            report(findings=[FINDING]), report(findings=[{**FINDING, "blocking": True}] * 2),
            report(verdict="pass with open points"),
            report(verdict="pass with open points", findings=[FINDING, FINDING]),
        ]
        for broken in ("", "{", '{"a"', '{"a":', '{"a":1', '{"a":1,}', "[1,]", "[1 2]", '{1:2}',
                       '"abc', '"a\\x"', '"a\\u12"', '"a\u0001"', "[1] x", "nul", "-", "1e",
                       '{"é": "ü"  x}', "\n\n  [1,\n 2,]", "NaN", '[1e400, -0, 1.5e3, "\\ud83d\\ude00"]',
                       '{"verdict": "pass", "verdict": 1}', "\ufeff{}"):
            bodies.append(f"{review}\n```json\n{broken}\n```\n")
        return [(body, None) for body in bodies]
    if template.kind == templates.CODE:
        return [(body, None) for body in _code_bodies(template)]
    return []


def _code_bodies(template: templates.Template) -> list[str]:
    """A code template's bodies: each file it scaffolds as it writes it, then the claimed one
    without each line its shape needs in turn, with another major version, and a free text."""
    made = [text for _, text in sorted(code_templates.scaffold(template, Path("x") / "thing",
                                                                "Do the thing.", "thing").items())]
    claimed = [text for text in made if any(re.fullmatch(template.marker_pattern, line.strip())
                                            for line in text.splitlines())]
    bodies = list(made)
    for text in claimed[:1]:
        lines = text.splitlines(keepends=True)
        for line in template.adapter.get("lines", []):
            kept = [item for item in lines if re.fullmatch(line["pattern"], item.strip()) is None]
            bodies.append("".join(kept))
        bodies.append(text.replace(f" {template.version}", " 2.0.0", 1))
    return [*bodies, "Free text.\n", ""]


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
                                            *(bodies or {}).get(template.name, []),
                                            *_dangling(template, base)]]
            if any(item.source == "title" for item in template.fields):
                entry["bodies"] += [_body(template, base, other) for other in TITLES if other != title]
        else:
            entry["bodies"] = [_body(template, body, title) for body, title in _adapter_bodies(template)]
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


OVERLAID = """---
name: plan
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: "A plan."
applies:
  actions: ["issue.create"]
order: ["goal", "risks", "size"]
rules:
  required: refuse
  words: warn
fields:
  - name: goal
    kind: text
    required: true
    max_words: 40
  - name: risks
    kind: list
    none_ok: true
  - name: size
    kind: choice
    choices: ["small", "large"]
example:
  fields:
    goal: "Ship the plan."
    risks: ["None"]
    size: small
---

## Goal

<!-- goal: The goal. -->

## Risks

<!-- risks: What could go wrong. -->

## Size

<!-- size: Small or large. -->
"""
OVERLAY = """---
extends: plan
says: "Agents keep it short."
tags: ["meeting"]
rules:
  duplicate: refuse
  choice: refuse
fields:
  - name: goal
    max_words: 20
    actor: true
  - name: owner
    kind: line
    label: Owner
    required: true
    says: "Who owns it."
  - name: why
    kind: text
    required: true
  - name: size
    choices: ["small"]
example:
  fields:
    owner: alice
    why: "It is due."
---

## Goal

<!-- goal: Name who does it. -->

## Why

<!-- why: Why now. -->
"""
CHILD = MINIMAL.format(name="subplan", extra=f"extends: plan\n{ISSUE_CREATE}").replace(
    "fields:\n  - name: goal\n    kind: text\n    required: true\n", "fields:\n  - name: note\n    kind: text\n").replace(
    "## Goal\n\n<!-- goal: The goal. -->\n", "## Note\n\n<!-- note: A note. -->\n")


# Template manifests (templates.py "Template manifests"): obs's worked example of three template nodes
# (obs spec/capabilities/templates.md), an ordinary chapter beside them, and an overlay.

MANIFEST = """---
title: Requirements
obs:
  template: {name: requirements, version: "2", source: an exported requirements template}
---

- [[purpose|Purpose]]
- [[scope|Scope]]
- [[how-to-use|How to use it]]
- [[risks|Risks]]

Fill one document per product from this template.
"""
NODES = {
    "purpose": """---
obs:
  guidance:
    contents: The problem the product solves, and for whom.
    motivation: Every later section is judged against it.
    form: One paragraph of at most five sentences.
    sources: The product brief.
    gate: mandatory
---

{{slot}}
""",
    "scope": """---
obs:
  guidance:
    contents: What the product does and what it leaves to others.
    form: Two lists, in scope and out of scope.
    gate: mandatory
---

{{slot}}
""",
    "risks": """---
obs:
  guidance:
    contents: The risks that could stop the product, each with its owner.
    motivation: A risk without an owner is not handled.
    gate: judgment
---

{{slot}}
""",
    "how-to-use": "Copy the folder, then fill each section.\n",
}
MANIFEST_OVERLAY = """---
extends: requirements
says: "Agents quote the brief."
tags: ["requirements"]
fields:
  - name: risks
    required: true
example:
  fields:
    purpose: "The pump controller keeps the tank level between its limits for the plant operators."
    scope: "- In scope: the level loop and its alarms.\\n- Out of scope: the pump drives."
    risks: "The level sensor may drift; the instrument team owns its calibration."
---

## Risks

<!-- risks: Name each owner by role. -->
"""
CHECKS = """---
obs:
  template: {name: checks, version: "1.4"}
---

- [[done]]
"""
DONE = "---\nobs:\n  guidance: {contents: What is done., gate: judgment}\n---\n{{slot}}\n"


def _manifest_files(**changed: str | None) -> dict[str, str]:
    """The fixture's files, `templates/<name>` relative, each of `changed` (`__` for `/`, `_dot_`
    for `.`) replaced or, where None, left out."""
    files = {"requirements/manifest.md": MANIFEST, "requirements.overlay.md": MANIFEST_OVERLAY,
             **{f"requirements/{name}.md": text for name, text in NODES.items()}}
    for key, text in changed.items():
        name = key.replace("__", "/").replace("_dot_", ".")
        if text is None:
            files.pop(name, None)
        else:
            files[name] = text
    return files


def _manifest_broken() -> list[tuple[str, dict[str, str]]]:
    """Template manifests that do not load."""
    purpose = NODES["purpose"]
    return [
        ("manifest-no-template", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            "obs:\n  template", "obs:\n  other"))),
        ("manifest-no-front-matter", _manifest_files(requirements__manifest_dot_md="- [[purpose]]\n")),
        ("manifest-name", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            "name: requirements", "name: needs"))),
        ("manifest-version", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            'version: "2"', 'version: "v2"'))),
        ("manifest-version-missing", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            'version: "2", ', ""))),
        ("manifest-template-key", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            "source:", "colour: red, source:"))),
        ("manifest-flow-broken", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            'version: "2", ', 'version: "2" '))),
        ("manifest-chapter-missing", _manifest_files(requirements__scope_dot_md=None)),
        ("manifest-chapter-twice", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            "- [[risks|Risks]]", "- [[risks|Risks]]\n- [[scope|Scope again]]"))),
        ("manifest-no-nodes", {"requirements/manifest.md": MANIFEST, "requirements/purpose.md": "x\n",
                               "requirements/scope.md": "x\n", "requirements/how-to-use.md": "x\n",
                               "requirements/risks.md": "---\ntitle: Risks\n---\nx\n"}),
        ("manifest-and-note", {**_manifest_files(), "requirements.md": MINIMAL.format(
            name="requirements", extra=ISSUE_CREATE)}),
        ("node-no-slot", _manifest_files(requirements__purpose_dot_md=purpose.replace("{{slot}}", "Text."))),
        ("node-slot-twice", _manifest_files(requirements__purpose_dot_md=purpose + "\n{{slot}}\n")),
        ("node-slot-in-text", _manifest_files(requirements__purpose_dot_md=purpose.replace(
            "{{slot}}", "Write {{slot}} here."))),
        ("node-guidance-key", _manifest_files(requirements__purpose_dot_md=purpose.replace(
            "    gate:", "    colour: red\n    gate:"))),
        ("node-no-contents", _manifest_files(requirements__purpose_dot_md=purpose.replace(
            "    contents: The problem the product solves, and for whom.\n", ""))),
        ("node-gate", _manifest_files(requirements__purpose_dot_md=purpose.replace(
            "gate: mandatory", "gate: always"))),
        ("node-guidance-list", _manifest_files(requirements__purpose_dot_md="---\nobs:\n  guidance: [1]\n---\n{{slot}}\n")),
        ("node-name", _manifest_files(requirements__manifest_dot_md=MANIFEST.replace(
            "[[scope|Scope]]", "[[Scope 2!|Scope]]"), **{"requirements/Scope 2!.md": NODES["scope"]})),
        ("manifest-overlay-loosens", _manifest_files(requirements_dot_overlay_dot_md=MANIFEST_OVERLAY.replace(
            "  - name: risks\n    required: true\n", "  - name: purpose\n    required: false\n"))),
        ("manifest-key-in-note", {"one.md": MINIMAL.format(name="one", extra=f"{ISSUE_CREATE}manifest: true\n")}),
    ]


def _overlay_broken() -> list[tuple[str, dict[str, str]]]:
    """Overlays that do not load, each with the template it extends."""
    def overlay(front: str, body: str = "") -> dict[str, str]:
        return {"plan.md": OVERLAID, "plan.overlay.md": f"---\nextends: plan\n{front}---\n{body}"}
    return [
        ("overlay-unknown-key", overlay("reader: fleet\nversion: 2.0.0\n")),
        ("overlay-unknown-one", overlay("reader: fleet\n")),
        ("overlay-extends", {"plan.md": OVERLAID, "plan.overlay.md": "---\nextends: other\n---\n"}),
        ("overlay-no-extends", {"plan.md": OVERLAID, "plan.overlay.md": "---\nsays: x\n---\n"}),
        ("overlay-alone", {"plan.md": OVERLAID, "other.overlay.md": "---\nextends: other\n---\n"}),
        ("overlay-tags", overlay("tags: meeting\n")),
        ("overlay-rules", overlay("rules: [refuse]\n")),
        ("overlay-example", overlay("example: [1]\n")),
        ("overlay-fields", overlay("fields:\n  - kind: text\n")),
        ("overlay-heading", overlay("fields:\n  - name: goal\n    heading: Aim\n")),
        ("overlay-says", overlay("fields:\n  - name: why\n    kind: text\n    says: Why.\n")),
        ("overlay-section-unknown", overlay("", "\n## Aim\n\n<!-- aim: The aim. -->\n")),
        ("overlay-section-twice", overlay("", "\n## Goal\n\n<!-- goal: One. -->\n\n## Goal\n\n<!-- goal: Two. -->\n")),
        ("overlay-rename", overlay("", "\n## Aim\n\n<!-- goal: The aim. -->\n")),
        ("overlay-no-section", overlay("fields:\n  - name: why\n    kind: text\n")),
        ("overlay-loosens-rule", overlay("rules:\n  required: warn\n  words: \"off\"\n")),
        ("overlay-refuses-a-warning", overlay("rules:\n  words: refuse\n")),
        ("overlay-loosens-field", overlay("fields:\n  - name: goal\n    required: false\n    max_words: 80\n    kind: list\n"
                                         "  - name: risks\n    none_ok: false\n  - name: size\n    choices: [\"small\", \"huge\"]\n")),
        ("overlay-limit-off", overlay("fields:\n  - name: goal\n    max_words: 0\n")),
        ("overlay-none-ok-on", overlay("fields:\n  - name: goal\n    none_ok: true\n")),
        ("overlay-no-choices", overlay("fields:\n  - name: size\n    choices: []\n")),
    ]


# Template repositories: a project's checkout with its se.toml pins, se.lock and clones, the
# machine's local.toml and what git answers, resolved by `catalog` (docs/templates.md "Template
# repositories"). Paths in errors are written from `<tmp>`, the case's own folder.

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "89abcdef0123456789abcdef0123456789abcdef"


def _note(name: str) -> str:
    return MINIMAL.format(name=name, extra=ISSUE_CREATE)


def _manifest_note(name: str) -> dict[str, str]:
    """A template manifest of one node, `templates/<name>/` relative."""
    return {f"{name}/manifest.md": f'---\nobs:\n  template: {{name: {name}, version: "1"}}\n---\n- [[goal]]\n',
            f"{name}/goal.md": "---\nobs:\n  guidance: {contents: The goal., gate: mandatory}\n---\n{{slot}}\n"}


def _repository_sets() -> list[dict]:
    """Each case: its name, the files of the checkout `app/` and beside it, the local.toml, the
    HEAD of each clone and what origin's integration branch holds."""
    clone = ".se/modules/shared"
    pinned = {f"{clone}/.git/index": "", f"{clone}/templates/shared.md": _note("shared"),
              f"{clone}/templates/handover.md": _note("handover"),
              f"{clone}/templates/own.md": _note("own")}
    toml = 'project = {{}}\n\n[templates]\nrepositories = {listed}\n\n[components.shared]\n{pin}\n'
    def app(listed: str = '["shared"]', pin: str = f'ref = "{SHA}"', **files: str) -> dict[str, str]:
        made = {"se.toml": toml.format(listed=listed, pin=pin), "templates/own.md": _note("own")}
        made.update({key.replace("__", "/").replace("_dot_", "."): value for key, value in files.items()})
        return {f"app/{key}": value for key, value in made.items()}
    heads = {clone: SHA}
    lock = '[components.shared]\nversion = "1.3.0"\nref = "' + SHA + '"\n'
    return [
        {"name": "own-only", "files": {"app/templates/own.md": _note("own")}},
        {"name": "no-templates", "files": {"app/README.md": "An app.\n"}},
        {"name": "origin", "files": {"app/templates/own.md": _note("own")},
         "origin": {"origin/main": {"templates/own.md": _note("own").replace("A template.", "At origin."),
                                    "templates/extra.md": _note("extra"), "templates/sub/deep.md": _note("deep"),
                                    "templates/notes.txt": "x", "README.md": "x"}}},
        {"name": "origin-terms-only", "files": {"app/templates/own.md": _note("own")},
         "origin": {"origin/main": {"templates/terms.toml": "[[terms]]\nterm = \"x\"\n"}}},
        {"name": "integration-branch", "files": {"app/se.toml": '[project]\nintegration_branch = "trunk"\n',
                                                 "app/templates/own.md": _note("own")},
         "origin": {"origin/trunk": {"templates/trunk.md": _note("trunk")},
                    "origin/main": {"templates/main.md": _note("main")}}},
        {"name": "pinned", "files": {**app(), **{f"app/{key}": value for key, value in pinned.items()}}, "heads": heads},
        {"name": "pinned-path", "files": {**app(pin=f'ref = "{SHA}"\npath = "sub"'),
                                          f"app/{clone}/.git/index": "",
                                          f"app/{clone}/sub/templates/shared.md": _note("shared")}, "heads": heads},
        {"name": "version-locked", "files": {**app(pin='version = "^1.2"'), "app/se.lock": lock,
                                             **{f"app/{key}": value for key, value in pinned.items()}}, "heads": heads},
        {"name": "version-unlocked", "files": {**app(pin='version = "^2.0"'), "app/se.lock": lock,
                                               **{f"app/{key}": value for key, value in pinned.items()}}, "heads": heads},
        {"name": "go-pin", "files": {**app(pin='go = "go.mod"'), "app/go.mod": "module app\n\nrequire (\n\tshared v1.3.0 // the templates\n)\n",
                                     "app/se.lock": lock, **{f"app/{key}": value for key, value in pinned.items()}}, "heads": heads},
        {"name": "go-pin-no-require", "files": {**app(pin='go = true'), "app/go.mod": "module app\n"}},
        {"name": "not-a-component", "files": app(listed='["ghost"]')},
        {"name": "not-fetched", "files": {**app(), f"app/{clone}/templates/shared.md": _note("shared")}},
        {"name": "wrong-head", "files": {**app(), **{f"app/{key}": value for key, value in pinned.items()}},
         "heads": {clone: OTHER_SHA}},
        {"name": "head-fails", "files": {**app(), **{f"app/{key}": value for key, value in pinned.items()}}},
        {"name": "no-templates-folder", "files": {**app(), f"app/{clone}/.git/index": ""}, "heads": heads},
        {"name": "local-path", "files": {**app(), "checkouts/shared/templates/shared.md": _note("shared")},
         "local": '[paths]\nshared = "../../checkouts/shared"\n'},
        {"name": "local-path-missing", "files": app(), "local": '[paths]\nshared = "../../nowhere"\n'},
        {"name": "local-unknown", "files": app(), "local": "[colours]\nred = 1\n"},
        {"name": "local-paths-not-strings", "files": app(), "local": "[paths]\nshared = 1\n"},
        {"name": "list-not-list", "files": app(listed='"shared"')},
        {"name": "list-twice", "files": app(listed='["shared", "Shared"]')},
        {"name": "list-empty", "files": app(listed="[]")},
        {"name": "unknown-key", "files": app(pin=f'ref = "{SHA}"\ncolour = "red"')},
        {"name": "url", "files": app(pin=f'ref = "{SHA}"\nurl = "x"')},
        {"name": "short-ref", "files": app(pin='ref = "0123"')},
        {"name": "ref-and-version", "files": app(pin=f'ref = "{SHA}"\nversion = "^1"')},
        {"name": "bad-range", "files": app(pin='version = "latest"')},
        {"name": "bad-path", "files": app(pin=f'ref = "{SHA}"\npath = "../up"')},
        {"name": "renamed", "files": {"app/se.toml": '[templates]\nrepositories = ["shared"]\n\n[modules.shared]\nref = "x"\n'}},
        {"name": "overlay-in-repository", "files": {
            **app(), **{f"app/{key}": value for key, value in pinned.items()},
            f"app/{clone}/templates/plan.md": OVERLAID, f"app/{clone}/templates/plan.overlay.md": OVERLAY}, "heads": heads},
        {"name": "manifest-in-repository", "files": {
            **app(), **{f"app/{key}": value for key, value in pinned.items()},
            **{f"app/{clone}/templates/{key}": value for key, value in _manifest_note("req").items()},
            f"app/{clone}/templates/loose/goal.md": "x\n"}, "heads": heads},
        {"name": "project-manifest-wins", "files": {
            **app(), **{f"app/{key}": value for key, value in pinned.items()},
            **{f"app/templates/{key}": value for key, value in _manifest_note("shared").items()}}, "heads": heads},
        {"name": "origin-manifest", "files": {"app/templates/own.md": _note("own")},
         "origin": {"origin/main": {"templates/own.md": _note("own"),
                                    **{f"templates/{key}": value for key, value in _manifest_note("req").items()},
                                    "templates/loose/goal.md": "x\n", "templates/req/deep/x.md": "x\n"}}},
        {"name": "project-overlay-of-repository", "files": {
            **app(), **{f"app/{key}": value for key, value in pinned.items()},
            "app/templates/shared.overlay.md": "---\nextends: shared\n---\n"}, "heads": heads},
    ]


class CaseGit:
    """The git a repository case gives: each clone's HEAD and what origin's refs hold; any other
    command fails, as git without a repository does."""

    def __init__(self, root: Path, case: dict) -> None:
        self.root, self.case = root, case

    def run(self, argv: list[str], *, cwd=None, env=None, stdin=None, timeout=None):
        where = Path(cwd) if cwd is not None else None
        if argv[:1] == ["-C"]:
            where, argv = Path(argv[1]), argv[2:]
        relative = where.resolve().relative_to(self.root).as_posix() if where is not None and \
            where.resolve().is_relative_to(self.root) else None
        def done(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(argv, code, out.encode(), err.encode())
        if argv == ["rev-parse", "HEAD"] and relative is not None:
            head = self.case.get("heads", {}).get(relative.removeprefix("app/"))
            return done(0, head + "\n") if head else done(128, "", "fatal: not a git repository\n")
        origin = self.case.get("origin", {}) if relative == "app" else {}
        if argv[:3] == ["ls-tree", "-r", "--name-only"] and argv[3] in origin:
            return done(0, "".join(f"{path}\n" for path in sorted(origin[argv[3]])
                                   if path.startswith(argv[5] + "/")))
        if argv[:1] == ["show"] and ":" in argv[1]:
            ref, path = argv[1].split(":", 1)
            if path in origin.get(ref, {}):
                return done(0, origin[ref][path])
        return done(128, "", f"fatal: Not a valid object name {argv[-1]}\n")


@contextmanager
def _local(path: Path):
    modules = templates._sibling("se_modules")
    saved = modules.default_local_config
    modules.default_local_config = lambda: path
    try:
        yield
    finally:
        modules.default_local_config = saved


def _resolved(case: dict) -> dict:
    """What `catalog` resolves for the case's checkout: each template's name, repository, file and
    digest, or the error."""
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder).resolve()
        for path, text in case["files"].items():
            (tmp / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp / path).write_text(text, encoding="utf-8", newline="\n")
        local = tmp / "machine" / ".se" / "local.toml"
        if case.get("local") is not None:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(case["local"], encoding="utf-8", newline="\n")
        with git_door.use(CaseGit(tmp, case)), _local(local):
            try:
                loaded = templates.catalog(tmp / "app")
            except templates.TemplateError as error:
                return {**case, "error": str(error).replace(str(tmp), "<tmp>")}
    return {**case, "templates": [[template.name, template.repository, template.path, template.digest]
                                  for template in sorted(loaded.values(), key=lambda item: item.name)]}


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
    return sets + _overlay_broken() + _manifest_broken()


#: obs's worked example's filled document as one note (templates.py "Template manifests").
MANIFEST_DOCUMENT = """---
title: Pump controller requirements
derived_from: {template: requirements, version: "2"}
---

## Purpose

The pump controller keeps the tank level between its limits for the plant operators.

## Scope

- In scope: the level loop and its alarms.
- Out of scope: the pump drives, which the drive supplier owns.

## Risks

The level sensor may drift; the instrument team owns its calibration.
"""


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
        for body in (STEP, '---\nderived_from: {template: other, version: "1.0.0"}\n---\n',
                     '---\nderived_from: {template: project/risks, version: "1.0.0"}\n---\n',
                     "---\nderived_from: risks\n---\n", "id: S5B\n"):
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
        '---\nderived_from: {template: risks, version: "1.1.0"}\n---\n\n## Risks\n\n- One.\n',
        '---\nderived_from:\n  template: risks\n  version: "2.0.0"\nid: S5B\n---\n\n## Risks\n\n- One.\n']})
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
    overlaid_body = ("Owner: bob\n\n## Goal\n\nWe ship it.\n\n## Risks\n\nNone\n\n## Size\n\nlarge\n\n"
                     "## Why\n\nIt is due.\n")
    made["overlays.json"] = _fixture("overlays", {"plan.md": OVERLAID, "plan.overlay.md": OVERLAY,
                                                  "subplan.md": CHILD}, {"plan": [
        overlaid_body, overlaid_body.replace("Owner: bob\n\n", ""),
        overlaid_body.replace("We ship it.", " ".join(["word"] * 25))]})
    manifest_files = {**_manifest_files(), "checks/manifest.md": CHECKS, "checks/done.md": DONE}
    made["manifests.json"] = _fixture("manifests", manifest_files, {"requirements": [
        MANIFEST_DOCUMENT, MANIFEST_DOCUMENT.replace("drift;", "drift; {{slot}}"),
        MANIFEST_DOCUMENT.replace("drift;", "drift; `{{slot}}`"),
        MANIFEST_DOCUMENT.replace('version: "2"', 'version: "1"'),
        MANIFEST_DOCUMENT.replace('version: "2"', 'version: "2.0"'),
        MANIFEST_DOCUMENT.replace('version: "2"', 'version: "3.1"'),
        MANIFEST_DOCUMENT.replace('derived_from: {template: requirements, version: "2"}',
                                  'derived_from:\n  template: requirements\n  version: "1"'),
        MANIFEST_DOCUMENT.replace("## Scope\n\n- In scope: the level loop and its alarms.\n"
                                  "- Out of scope: the pump drives, which the drive supplier owns.\n\n", ""),
    ], "checks": ["---\nderived_from: {template: checks, version: 1.3}\n---\n\n## done\n\nAll.\n",
                  "---\nderived_from: {template: checks}\n---\n\n## done\n\n```\n{{slot}}\n```\n"]})
    made["repositories.json"] = {"generated": GENERATED.format(source="the checkouts below"),
                                 "set": "repositories",
                                 "cases": [_resolved(case) for case in _repository_sets()]}
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
