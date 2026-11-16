#!/usr/bin/env python3
"""Forms: the shape of the text SE writes, kept as data, read, checked and written by one engine.

No command checks with forms yet: nothing calls this module but its tests and its own command line.
A later piece switches the check on for the commands that file and edit issues.

**Form files.** One TOML file per form, `forms/<name>.toml`; `forms/terms.toml` is no form but the
list of inside terms (below). A form declares:

- `name`, `reader` (`owner` or `fleet`: who reads what it shapes) and `says`, one line;
- `[applies] actions`, the actions it shapes (`issue.create`, `issue.edit`): required, so a form
  without it does not load; `order` and the conditions `marker` and `title` (selection, below);
- `extends`, another form whose fields, rules, actors and `[applies]` it inherits; `remove` names
  inherited fields it drops, a field of the same name replaces the inherited one, and `order`
  lists its final field order (every field once) where the inherited order does not fit;
- `keep_unknown` (default true): whether `render` keeps the sections the form does not declare;
- `[rules]`, each writing rule it uses marked `refuse`, `warn` or `off`; a rule it does not name is
  off. A warn-only rule marked `refuse` does not load;
- `actors`, the names a step or a check may name (rule `actor`), and `[example]`, a `title` and
  `fields` that pass the form, which the tests render and parse back;
- `[scope]` (optional): `after`, a marker line, `section`, the heading under it, and `level`, the
  heading level of its fields. Only that section is read; the text above the marker is data, never
  checked or read into a field, and kept as it is.

**Fields**, `[[fields]]`: `name`, `kind`, `heading`, `required`, `none_ok` (the value "None"
fills it), `says` (what belongs there, the fix's wording and the draft's comment), `exact_heading`
(only `## <heading>`, at the form's level, counts) and `verbatim` (the text is kept and written
back as it stands). Besides: `source = "title"` (the field is the issue's title, never in the body),
`label` (a `<label>: <value>` line before the first section), `choices` (kind `choice`),
`numbered`, `continue_numbers` and `markers` (kind `list`), `lang` (kind `code`), `max_words`,
`actor`, `one_sentence`, `not_picked` and `shape` (`words` or `branch`, a title's).

**Field kinds** and their values: `line` and `choice` a string, its first line; `text` a string;
`list` a list of strings, its items without their numbers or bullets (with `markers`, a line that
is one whole HTML comment is an item of its own, kept as it is); `object` a mapping of `Key: value`
lines; `issue` a list of entries, one per line (`#12`, a link, `None`); `checklist` a list of
`{"done": bool, "text": str}`; `code` the text of its first fenced block.

**Reading.** `parse` skips front matter and accepts a field's heading at `#` to `####`, in any case
and with a trailing colon, and `_No response_` as empty, except where a field sets `exact_heading`.
A heading that names no field is a section of its own, unless it is deeper than the section it sits
in. Emptiness is judged without HTML comments.

**Writing.** `render` writes SE's fleet marker once, then `<!-- se:form <name> -->` (with a scope,
the form marker alone, after the scope's marker), then `## ` headings. A section the form does not
declare, and a field whose value did not change, are written back byte for byte in their place;
a `verbatim` field is never reflowed.

**Selection** (`select`, for `issue.create` and `issue.edit`): among the forms that name the
action, a body's own `<!-- se:form <name> -->` wins; then, by `[applies] order` (then name), the
first form with conditions that all hold (`marker`: the body has that line; `title`: the title
matches that regular expression); then the first form without conditions. None is free form.

**Severities.** `check` returns every finding at once, each with its field, rule, severity and fix.
Refuse rules: `required` (missing, empty or placeholder, or the field's own `says` pasted back),
`choice`, `not-picked` (no `Not picked:` line), `duplicate` (the same text in two fields) and
`dangling` (an SE command that does not exist, through `references.dangling` as
`work_tickets.refuse_dangling` calls it). Warn-only rules, never refused: `words`, `actor`,
`one-sentence`, `bare-number`, `board` (Status, Labels, Priority, Assignee or Milestone lines),
`terms` (`forms/terms.toml`), `unnamed-entry` (a blocker without a name) and `title-shape`.

**Interface** for the pieces that build on it: `load(root, tree=False)` reads `forms/` at
`origin/<integration branch>` through `git_door` where that ref holds forms, else from the working
tree; `parse(form, body, title)` gives a `Document`; `render(form, document_or_fields)`;
`check(form, document)` gives `Finding`s; `select(forms, action, body, title)`; `draft(form)`;
`list_forms(forms)` (named so beside Python's `list`). All but `load` are pure.

**Command.** `forms.py check <form> (--body-file FILE | --fields FILE) [--title TEXT] [--tree]`
prints at most 10 lines of findings and exits 0 when nothing refuses, 1 when something does, 2 on a
usage error; `forms.py draft <form> [--json]` prints the empty form; `forms.py list` names every
form with its actions. `--tree` reads the working tree's `forms/`. None writes a file, calls GitHub
or starts a model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMS = "forms"
TERMS_FILE = "terms.toml"

FLEET_MARKER = "<!-- se:fleet -->"
FORM_MARKER = "<!-- se:form {name} -->"
FORM_MARKER_PATTERN = re.compile(r"^[ \t]*<!-- se:form ([\w-]+) -->[ \t]*$", re.MULTILINE)

ACTIONS = ("issue.create", "issue.edit")
READERS = ("owner", "fleet")
KINDS = ("line", "text", "choice", "list", "object", "issue", "checklist", "code")
REFUSE, WARN, OFF = "refuse", "warn", "off"
REFUSE_RULES = ("required", "choice", "not-picked", "duplicate", "dangling")
WARN_RULES = ("words", "actor", "one-sentence", "bare-number", "board", "terms", "unnamed-entry",
              "title-shape")
FIELD_KEYS = {"name", "kind", "heading", "required", "none_ok", "says", "exact_heading",
              "verbatim", "source", "label", "choices", "numbered", "continue_numbers", "markers",
              "lang", "max_words", "actor", "one_sentence", "not_picked", "shape"}
FORM_KEYS = {"name", "reader", "says", "applies", "extends", "remove", "order", "keep_unknown",
             "rules", "actors", "example", "scope", "fields"}

FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
HEADING = re.compile(r"^(#{1,4})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
WHOLE_COMMENT = re.compile(r"^[ \t]*<!--.*-->[ \t]*$")
NUMBERED = re.compile(r"^(\d+)[.)](?:[ \t]+(.*?))?[ \t]*$")
BULLET = re.compile(r"^[-*+](?:[ \t]+(.*?))?[ \t]*$")
CHECKBOX = re.compile(r"^[-*+][ \t]+\[([ xX])\](?:[ \t]+(.*?))?[ \t]*$")
NO_RESPONSE = "_no response_"
PLACEHOLDERS = {"", NO_RESPONSE, "tbd", "tba", "...", "…", "-", "?", "n/a", ">", "1."}
NONE = "none"
NOT_PICKED = re.compile(r"^[ \t>*_-]*not picked[*_]*:[*_]*[ \t]*\S", re.IGNORECASE | re.MULTILINE)
BOARD = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?\**(status|labels?|priority|assignee|milestone)\**[ \t]*:",
                   re.IGNORECASE | re.MULTILINE)
BARE_NUMBER = re.compile(r"(?<![\w/&#\[])#\d+\b")
CODE_SPAN = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")
BRANCH = re.compile(r"^[a-z][a-z0-9]*/[a-z0-9][a-z0-9.-]*-\d{8}$")
BRANCH_LIKE = re.compile(r"^[\w.-]+/[\w./-]+$")
PATH_LIKE = re.compile(r"^\S*[/\\]\S*$|^\S+\.(py|md|toml|go|json|yml|yaml|sh|ps1)$")
BARE_ISSUE = re.compile(r"^(?:[\w.-]+/[\w.-]+)?#\d+$|^<?https?://\S+>?$")
SENTENCE_END = re.compile(r"[.!?](?=[ \t]+[A-Z(\"'`])")


class FormError(Exception):
    """A form that does not load, or a usage the command refuses: the message names the file or
    the argument and the remedy."""


@dataclass(frozen=True)
class Field:
    """One field of a form; the module docstring owns what each key means."""
    name: str
    kind: str
    heading: str = ""
    required: bool = False
    none_ok: bool = False
    says: str = ""
    exact_heading: bool = False
    verbatim: bool = False
    source: str = ""
    label: str = ""
    choices: tuple[str, ...] = ()
    numbered: bool = False
    continue_numbers: bool = False
    markers: bool = False
    lang: str = "sh"
    max_words: int = 0
    actor: bool = False
    one_sentence: bool = False
    not_picked: bool = False
    shape: str = ""

    @property
    def in_body(self) -> bool:
        """Whether the field has a section of its own (not the title, not a label line)."""
        return not self.source and not self.label


@dataclass(frozen=True)
class Term:
    """An inside term (`forms/terms.toml`) and the plain words a reader outside knows."""
    term: str
    plain: str


@dataclass(frozen=True)
class Form:
    """A loaded form, its `extends` resolved."""
    name: str
    reader: str
    says: str
    actions: tuple[str, ...]
    fields: tuple[Field, ...]
    rules: dict[str, str]
    order: int = 100
    marker: str = ""
    title_pattern: str = ""
    keep_unknown: bool = True
    actors: tuple[str, ...] = ()
    example: dict = dataclass_field(default_factory=dict)
    scope: dict = dataclass_field(default_factory=dict)
    terms: tuple[Term, ...] = ()
    path: str = ""

    def field(self, name: str) -> Field | None:
        return next((item for item in self.fields if item.name == name), None)

    def severity(self, rule: str) -> str:
        return self.rules.get(rule, OFF)

    @property
    def level(self) -> int:
        """The heading level of the form's sections: 2, or the scope's."""
        return int(self.scope.get("level", 2)) if self.scope else 2


@dataclass(frozen=True)
class Finding:
    """One problem `check` found: the field, the rule, `refuse` or `warn`, and the fix."""
    field: str
    rule: str
    severity: str
    fix: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.field} [{self.rule}]: {self.fix}"


@dataclass
class Part:
    """A piece of a parsed body: `preamble`, `prefix`, `gap`, `scope` or `suffix` text, or a
    `field` or `unknown` section (its heading line, then its raw text up to the next section)."""
    kind: str
    raw: str = ""
    heading: str = ""
    name: str = ""


@dataclass
class Document:
    """A body read into a form's fields; `parts` keeps its layout so `render` can write the rest
    back as it was. `fields` holds the fields present, the title among them."""
    form: str
    fields: dict[str, object]
    parts: list[Part] = dataclass_field(default_factory=list)
    source: str = ""
    misses: dict[str, str] = dataclass_field(default_factory=dict)
    read: dict[str, object] = dataclass_field(default_factory=dict)


# Loading


def _form_files(root: Path, tree: bool) -> dict[str, str]:
    """`forms/<file>` -> its text, at origin's integration branch where that holds forms, else
    from the working tree."""
    if not tree:
        files = _git_files(root)
        if files:
            return files
    folder = root / FORMS
    if not folder.is_dir():
        raise FormError(f"forms: {folder} does not exist; run from an SE checkout")
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.toml"))}


def _integration_branch(root: Path) -> str:
    try:
        project = tomllib.loads((root / "se.toml").read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return "main"
    branch = project.get("integration_branch", "main") if isinstance(project, dict) else "main"
    return branch.strip() if isinstance(branch, str) and branch.strip() else "main"


def _git_files(root: Path) -> dict[str, str]:
    door = _sibling("git_door")
    ref = f"origin/{_integration_branch(root)}"
    listed = door.run("ls-tree", "-r", "--name-only", ref, "--", FORMS, root=root)
    if listed.returncode != 0:
        return {}
    files = {}
    for path in listed.stdout.splitlines():
        if path.startswith(f"{FORMS}/") and path.endswith(".toml") and path.count("/") == 1:
            shown = door.run("show", f"{ref}:{path}", root=root)
            if shown.returncode == 0:
                files[path.split("/", 1)[1]] = shown.stdout
    return files


def _sibling(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load(root: Path = ROOT, *, tree: bool = False) -> dict[str, Form]:
    """Every form of `root`'s `forms/`, by name (the module docstring: where it reads them)."""
    files = _form_files(root, tree)
    raw: dict[str, dict] = {}
    terms: tuple[Term, ...] = ()
    for name, text in files.items():
        where = f"{FORMS}/{name}"
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise FormError(f"{where}: not TOML ({error}); fix the file") from error
        if name == TERMS_FILE:
            terms = tuple(Term(str(item["term"]), str(item.get("plain", "")))
                          for item in data.get("terms", []))
            continue
        form_name = data.get("name")
        if form_name != name.removesuffix(".toml"):
            raise FormError(f"{where}: name = {form_name!r} must be the file's name, "
                            f"{name.removesuffix('.toml')!r}")
        data["path"] = where
        raw[form_name] = data
    return {name: _build(name, raw, terms, ()) for name in sorted(raw)}


def _build(name: str, raw: dict[str, dict], terms: tuple[Term, ...],
           seen: tuple[str, ...]) -> Form:
    data = raw[name]
    where = data["path"]
    unknown = set(data) - FORM_KEYS - {"path"}
    if unknown:
        raise FormError(f"{where}: unknown keys {', '.join(sorted(unknown))}; the form file format "
                        "is scripts/forms.py's docstring")
    parent: Form | None = None
    if "extends" in data:
        base = data["extends"]
        if base in seen or base == name:
            raise FormError(f"{where}: extends {base!r} in a cycle ({' -> '.join((*seen, name))})")
        if base not in raw:
            raise FormError(f"{where}: extends {base!r}, which is no form in {FORMS}/")
        parent = _build(base, raw, terms, (*seen, name))
    applies = data.get("applies")
    if not isinstance(applies, dict) or not applies.get("actions"):
        if parent is None:
            raise FormError(f"{where}: [applies] actions is required; name the actions the form "
                            f"shapes ({', '.join(ACTIONS)})")
        applies = {"actions": list(parent.actions), **(applies or {})}
    actions = tuple(applies["actions"])
    for action in actions:
        if action not in ACTIONS:
            raise FormError(f"{where}: action {action!r} is none of {', '.join(ACTIONS)}")
    reader = data.get("reader", parent.reader if parent else "")
    if reader not in READERS:
        raise FormError(f"{where}: reader {reader!r} is none of {', '.join(READERS)}")
    inherited = list(parent.fields) if parent else []
    removed = set(data.get("remove", []))
    fields = [item for item in inherited if item.name not in removed]
    for entry in data.get("fields", []):
        made = _field(entry, where)
        index = next((i for i, item in enumerate(fields) if item.name == made.name), None)
        if index is None:
            fields.append(made)
        else:
            fields[index] = made
    if "order" in data:
        order = list(data["order"])
        names = [item.name for item in fields]
        if sorted(order) != sorted(names):
            raise FormError(f"{where}: order must list every field once: "
                            f"{', '.join(names)}")
        fields.sort(key=lambda item: order.index(item.name))
    rules = {**(parent.rules if parent else {}), **data.get("rules", {})}
    for rule, severity in rules.items():
        if rule not in REFUSE_RULES + WARN_RULES:
            raise FormError(f"{where}: rule {rule!r} is unknown; the rules are "
                            f"{', '.join(REFUSE_RULES + WARN_RULES)}")
        if severity not in (REFUSE, WARN, OFF):
            raise FormError(f"{where}: rule {rule} is {severity!r}; mark it refuse, warn or off")
        if rule in WARN_RULES and severity == REFUSE:
            raise FormError(f"{where}: rule {rule} only warns, never refuses; mark it warn")
    example = data.get("example", {})
    return Form(
        name=name, reader=reader, says=str(data.get("says", parent.says if parent else "")),
        actions=actions, fields=tuple(fields), rules=rules,
        order=int(applies.get("order", parent.order if parent else 100)),
        marker=str(applies.get("marker", "")), title_pattern=str(applies.get("title", "")),
        keep_unknown=bool(data.get("keep_unknown", parent.keep_unknown if parent else True)),
        actors=tuple(data.get("actors", parent.actors if parent else ())),
        example=example if example else {}, scope=dict(data.get("scope", {})),
        terms=terms, path=where)


def _field(entry: dict, where: str) -> Field:
    unknown = set(entry) - FIELD_KEYS
    name = entry.get("name", "?")
    if unknown:
        raise FormError(f"{where}: field {name} has unknown keys {', '.join(sorted(unknown))}")
    if entry.get("kind") not in KINDS:
        raise FormError(f"{where}: field {name} has kind {entry.get('kind')!r}; one of "
                        f"{', '.join(KINDS)}")
    made = Field(**{**entry, "choices": tuple(entry.get("choices", ()))})
    if made.in_body and not made.heading:
        raise FormError(f"{where}: field {name} needs a heading (or source = \"title\", or a label)")
    if made.kind == "choice" and not made.choices:
        raise FormError(f"{where}: field {name} is a choice without choices")
    return made


# Reading


def _norm(heading: str) -> str:
    return " ".join(heading.strip().rstrip(":").strip().casefold().split())


def _matches(item: Field, line: str, level: int, base: int, own: int) -> bool:
    """Whether heading `line` (at `level`, below `base`) names `item`; `own` is the form's level."""
    if item.exact_heading:
        return line.rstrip() == f"{'#' * own} {item.heading}"
    if level <= base:
        return False
    match = HEADING.match(line)
    name, want = _norm(match.group(2)), _norm(item.heading)
    return name == want or name.startswith(want + " (")


def _split(text: str, form: Form, base: int) -> tuple[str, list[Part]]:
    """`text` as its preamble and its sections at levels deeper than `base`."""
    preamble: list[str] = []
    parts: list[Part] = []
    current: tuple[Part, int, list[str]] | None = None
    fence: str | None = None
    seen: set[str] = set()

    def close() -> None:
        if current is not None:
            current[0].raw = "".join(current[2])

    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        marker = FENCE.match(bare)
        heading = None
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None and marker and marker.group(1).startswith(fence):
            fence = None
        elif fence is None:
            heading = HEADING.match(bare)
        if heading and len(heading.group(1)) > base:
            level = len(heading.group(1))
            found = next((item for item in form.fields if item.in_body and item.name not in seen
                          and _matches(item, bare, level, base, form.level)), None)
            if found is not None or current is None or level <= current[1]:
                close()
                part = Part("field" if found else "unknown", heading=bare,
                            name=found.name if found else _norm(heading.group(2)))
                if found:
                    seen.add(found.name)
                current = (part, level, [])
                parts.append(part)
                continue
        (current[2] if current is not None else preamble).append(line)
    close()
    return "".join(preamble), parts


def _uncomment(text: str, keep_markers: bool = False) -> str:
    """`text` without HTML comments; with `keep_markers`, a comment that is a whole line stays."""
    if not keep_markers:
        return COMMENT.sub("", text)

    def drop(match: re.Match) -> str:
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        line = text[start:len(text) if end < 0 else end]
        return match.group(0) if "\n" not in match.group(0) and WHOLE_COMMENT.match(line) else ""
    return COMMENT.sub(drop, text)


def _items(text: str, pattern: re.Pattern, markers: bool) -> list[tuple[str, str]]:
    """The items of a list as (kind, text): kind is `marker` for a whole-line comment kept with
    `markers`, a checkbox's mark for a checklist, else `item`; the text has its continuation
    lines. Items without text are dropped."""
    items: list[list[str]] = []
    for line in text.splitlines():
        if markers and WHOLE_COMMENT.match(line):
            items.append(["marker", line.strip()])
            continue
        match = pattern.match(line)
        if match is None:
            if items and items[-1][0] != "marker":
                items[-1].append(line)
            continue
        if pattern is CHECKBOX:
            items.append([match.group(1), match.group(2) or ""])
        else:
            items.append(["item", match.group(pattern.groups) or ""])
    result = []
    for kind, *lines in items:
        body = lines[0] if kind == "marker" else "\n".join(lines).strip()
        if body:
            result.append((kind, body))
    return result


def value_of(item: Field, raw: str) -> object:
    """A field's value read from its section's raw text (the module docstring: field kinds)."""
    if item.verbatim:
        return raw.strip("\n")
    text = _uncomment(raw, keep_markers=item.markers)
    if text.strip().casefold() == NO_RESPONSE:
        text = ""
    if item.kind in ("line", "choice"):
        return next((line.strip() for line in text.splitlines() if line.strip()), "")
    if item.kind == "text":
        return text.strip()
    if item.kind == "list":
        return [body for _, body in _items(text, NUMBERED if item.numbered else BULLET,
                                           item.markers)]
    if item.kind == "checklist":
        return [{"done": mark in "xX", "text": body}
                for mark, body in _items(text, CHECKBOX, False)]
    if item.kind == "issue":
        entries = []
        for line in text.splitlines():
            entry = re.sub(r"^[-*+][ \t]+", "", line.strip())
            if entry:
                entries.append(entry)
        return entries
    if item.kind == "object":
        found: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"^[ \t]*(?:[-*+][ \t]+)?([^:\n]+?)[ \t]*:[ \t]*(.*?)[ \t]*$", line)
            if match:
                found[match.group(1)] = match.group(2)
        return found
    # code: the first fenced block's text, else the section's text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        opening = FENCE.match(line)
        if opening:
            inner = []
            for later in lines[index + 1:]:
                closing = FENCE.match(later)
                if closing and closing.group(1).startswith(opening.group(1)):
                    break
                inner.append(later)
            return "\n".join(inner).strip("\n")
    return text.strip()


def parse(form: Form, body: str, title: str | None = None) -> Document:
    """`body` read into `form`'s fields (the module docstring: reading)."""
    text = FRONT_MATTER.sub("", body, count=1)
    document = Document(form=form.name, fields={}, source=text)
    if form.scope:
        parts, region = _scoped(form, text)
    else:
        region = text
        preamble, sections = _split(text, form, 0)
        parts = [Part("preamble", raw=preamble), *sections]
    document.parts = parts
    preamble = next((part.raw for part in parts if part.kind == "preamble"), "")
    for item in form.fields:
        if item.source == "title":
            if title is not None:
                document.fields[item.name] = title
        elif item.label:
            match = re.search(rf"^[ \t]*{re.escape(item.label)}[ \t]*:[ \t]*(.*?)[ \t]*$",
                              preamble, re.MULTILINE | re.IGNORECASE)
            if match:
                document.fields[item.name] = match.group(1)
    for part in parts:
        if part.kind == "field":
            document.fields[part.name] = value_of(form.field(part.name), part.raw)
    document.read = dict(document.fields)
    for item in form.fields:
        if item.in_body and item.name not in document.fields:
            near = next((line for line in region.splitlines() if (match := HEADING.match(line))
                         and _norm(match.group(2)) == _norm(item.heading)), None)
            if near is not None:
                document.misses[item.name] = near
    document.source = region
    return document


def _scoped(form: Form, text: str) -> tuple[list[Part], str]:
    """A scoped form's parts: the data above its marker, then its section's own parts."""
    after = form.scope.get("after", "")
    lines = text.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.strip() == after), None)
    if index is None:
        return [Part("prefix", raw=text)], ""
    prefix = "".join(lines[:index + 1])
    rest = lines[index + 1:]
    want = _norm(form.scope.get("section", ""))
    start = None
    fence = None
    for i, line in enumerate(rest):
        marker = FENCE.match(line)
        if fence is None and marker:
            fence = marker.group(1)
            continue
        if fence is not None:
            if marker and marker.group(1).startswith(fence):
                fence = None
            continue
        heading = HEADING.match(line.rstrip("\r\n"))
        if heading and _norm(heading.group(2)) == want:
            start, level = i, len(heading.group(1))
            break
    if start is None:
        return [Part("prefix", raw=prefix), Part("gap", raw="".join(rest))], ""
    end, fence = len(rest), None
    for i in range(start + 1, len(rest)):
        marker = FENCE.match(rest[i])
        if fence is None and marker:
            fence = marker.group(1)
            continue
        if fence is not None:
            if marker and marker.group(1).startswith(fence):
                fence = None
            continue
        heading = HEADING.match(rest[i].rstrip("\r\n"))
        if heading and len(heading.group(1)) <= level:
            end = i
            break
    region = "".join(rest[start + 1:end])
    preamble, sections = _split(region, form, form.level - 1)
    return [Part("prefix", raw=prefix), Part("gap", raw="".join(rest[:start])),
            Part("scope", heading=rest[start].rstrip("\r\n")), Part("preamble", raw=preamble),
            *sections, Part("suffix", raw="".join(rest[end:]))], "".join(rest[start:end])


# Writing


def _format(item: Field, value: object, first: int) -> str:
    """A field's value as Markdown; `first` is the number a numbered list starts at."""
    if item.verbatim or item.kind in ("line", "choice", "text"):
        return str(value)
    if item.kind == "list":
        lines, number = [], first
        for entry in value:
            if WHOLE_COMMENT.match(str(entry)):
                lines.append(str(entry))
            elif item.numbered:
                lines.append(f"{number}. {entry}")
                number += 1
            else:
                lines.append(f"- {entry}")
        return "\n".join(lines)
    if item.kind == "checklist":
        return "\n".join(
            f"- [{'x' if isinstance(entry, dict) and entry.get('done') else ' '}] "
            f"{entry.get('text', '') if isinstance(entry, dict) else entry}" for entry in value)
    if item.kind == "issue":
        return "\n".join(str(entry) for entry in value)
    if item.kind == "object":
        return "\n".join(f"{key}: {text}" for key, text in value.items())
    return f"```{item.lang}\n{value}\n```"


def _count(item: Field, value: object) -> int:
    """How many numbers a numbered list's value uses."""
    if item.kind != "list" or not item.numbered or not isinstance(value, list):
        return 0
    return sum(1 for entry in value if not WHOLE_COMMENT.match(str(entry)))


def _without_markers(text: str) -> str:
    kept = [line for line in text.splitlines(keepends=True)
            if line.strip() != FLEET_MARKER and not FORM_MARKER_PATTERN.match(line.rstrip("\r\n"))]
    return "".join(kept)


def render(form: Form, document: Document | dict) -> str:
    """Canonical Markdown of `document` (a parsed Document, or a mapping of field values), as the
    module docstring's "Writing" says."""
    if not isinstance(document, Document):
        document = Document(form=form.name, fields=dict(document))
    values = document.fields
    marker = FORM_MARKER.format(name=form.name)
    hashes = "#" * form.level
    parts = list(document.parts)
    if form.scope and not any(part.kind == "scope" for part in parts):
        data = "".join(part.raw for part in parts if part.kind in ("prefix", "gap"))
        if form.scope.get("after", "") in data.splitlines():  # the marker without its section
            data = "\n".join(line for line in data.splitlines()
                             if line.strip() != form.scope.get("after", ""))
        parts = [*([Part("data", raw=_end(data))] if data.strip() else []),
                 Part("prefix", raw=form.scope.get("after", "") + "\n"), Part("gap"),
                 Part("scope", heading=f"## {form.scope.get('section', '')}"),
                 Part("preamble"), Part("suffix")]
    elif not parts:
        parts = [Part("preamble")]
    # Fields with a value but no section yet go after the nearest earlier field that has one.
    placed = {part.name for part in parts if part.kind == "field"}
    for item in form.fields:
        if not item.in_body or item.name in placed or values.get(item.name) in (None, "", [], {}):
            continue
        names = [other.name for other in form.fields]
        earlier = names[:names.index(item.name)]
        index = max((i for i, part in enumerate(parts) if part.kind == "field"
                     and part.name in earlier), default=None)
        if index is None:
            index = max((i for i, part in enumerate(parts)
                         if part.kind in ("preamble", "scope")), default=-1)
        parts.insert(index + 1, Part("field", name=item.name, heading=f"{hashes} {item.heading}",
                                     raw=None))
        placed.add(item.name)
    out: list[str] = []
    number = 1
    for part in parts:
        if part.kind == "prefix":
            out.append(_end(part.raw) if part.raw else "")
            out.append(marker + "\n")
        elif part.kind == "gap":
            out.append(_without_markers(part.raw))
        elif part.kind == "scope":
            out.append(part.heading + "\n")
        elif part.kind == "preamble":
            preamble = _labels(form, document, _without_markers(part.raw))
            if not form.scope:
                out.append(f"{FLEET_MARKER}\n{marker}\n")
                preamble = preamble.lstrip("\n")
                out.append("\n" + _end(preamble) if preamble.strip() else "\n")
            else:
                out.append(preamble if preamble.strip() else "\n")
        elif part.kind in ("suffix", "data"):
            out.append(part.raw + ("\n" if part.kind == "data" and part.raw.strip() else ""))
        elif part.kind == "unknown":
            if form.keep_unknown:
                out.append(part.heading + "\n" + part.raw)
        else:
            item = form.field(part.name)
            if part.name not in values:
                continue
            value = values[part.name]
            used = _count(item, value)
            if item.numbered and not item.continue_numbers:
                number = 1
            if part.raw is not None and document.read.get(part.name, object()) == value:
                out.append(f"{hashes} {item.heading}\n" + part.raw)
            else:
                out.append(f"{hashes} {item.heading}\n\n{_format(item, value, number)}\n\n")
            number += used
        if out and out[-1] and not out[-1].endswith("\n"):
            out[-1] += "\n"
    return "".join(out).rstrip("\n") + "\n"


def _end(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _labels(form: Form, document: Document, preamble: str) -> str:
    """The preamble with each label field's line as its value now."""
    for item in form.fields:
        if not item.label or item.name not in document.fields:
            continue
        value = document.fields[item.name]
        if document.read.get(item.name) == value and document.parts:
            continue
        line = f"{item.label}: {value}"
        pattern = re.compile(rf"^[ \t]*{re.escape(item.label)}[ \t]*:.*$", re.MULTILINE | re.IGNORECASE)
        if pattern.search(preamble):
            preamble = pattern.sub(line, preamble, count=1)
        else:
            preamble = f"\n{line}\n" + (preamble if preamble.strip() else "\n")
    return preamble


def draft(form: Form) -> str:
    """The empty form as Markdown, each field's `says` as a comment."""
    lines = []
    if form.scope:
        lines += [form.scope.get("after", ""), FORM_MARKER.format(name=form.name),
                  f"## {form.scope.get('section', '')}", ""]
    else:
        lines += [FLEET_MARKER, FORM_MARKER.format(name=form.name), ""]
    hashes = "#" * form.level
    for item in form.fields:
        if item.source == "title":
            lines += [f"<!-- title: {item.says} -->", ""]
        elif item.label:
            lines += [f"{item.label}: <!-- {item.says} -->", ""]
    for item in form.fields:
        if item.in_body:
            lines += [f"{hashes} {item.heading}", "", f"<!-- {item.says} -->", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def draft_fields(form: Form) -> dict[str, object]:
    """The empty form as data: each field's empty value and its `says`."""
    empty = {"list": [], "issue": [], "checklist": [], "object": {}}
    return {"form": form.name, "says": form.says,
            "fields": {item.name: empty.get(item.kind, "") for item in form.fields},
            "field_says": {item.name: item.says for item in form.fields}}


def list_forms(forms: dict[str, Form]) -> list[str]:
    """One line per form: its name, reader, actions and what it says."""
    return [f"{form.name} ({form.reader}): {', '.join(form.actions)}: {form.says}"
            for form in sorted(forms.values(), key=lambda item: (item.order, item.name))]


def select(forms: dict[str, Form], action: str, body: str, title: str | None = None) -> Form | None:
    """The form that shapes `body` for `action` (the module docstring: selection); None is free
    form."""
    if action not in ACTIONS:
        raise FormError(f"select: action {action!r} is none of {', '.join(ACTIONS)}")
    candidates = sorted((form for form in forms.values() if action in form.actions),
                        key=lambda form: (form.order, form.name))
    named = FORM_MARKER_PATTERN.search(body)
    if named:
        chosen = next((form for form in candidates if form.name == named.group(1)), None)
        if chosen is not None:
            return chosen
    lines = {line.strip() for line in body.splitlines()}
    for form in candidates:
        if not form.marker and not form.title_pattern:
            continue
        if form.marker and form.marker not in lines:
            continue
        if form.title_pattern and not re.search(form.title_pattern, title or ""):
            continue
        return form
    return next((form for form in candidates if not form.marker and not form.title_pattern), None)


# Checking


def _plain(value: object) -> str:
    """A value as one text, for comparing and searching."""
    if isinstance(value, dict):
        return "\n".join(f"{key}: {text}" for key, text in value.items())
    if isinstance(value, list):
        return "\n".join(entry.get("text", "") if isinstance(entry, dict) else str(entry)
                         for entry in value if not WHOLE_COMMENT.match(str(entry)))
    return str(value or "")


def _squash(text: str) -> str:
    return " ".join(COMMENT.sub("", text).split()).casefold()


def _emptiness(item: Field, value: object) -> str:
    """Why a value does not fill its field, or "" where it does."""
    if value is None:
        return "missing"
    text = _plain(value)
    bare = "\n".join(line.lstrip("> ").rstrip() for line in COMMENT.sub("", text).splitlines())
    squashed = " ".join(bare.split()).casefold()
    if squashed.rstrip(".") == NONE:
        return "" if item.none_ok else "placeholder"
    if item.kind == "issue" and isinstance(value, list) and value and all(
            _squash(str(entry)).rstrip(".") == NONE for entry in value):
        return "" if item.none_ok else "placeholder"
    if squashed in PLACEHOLDERS:
        return "empty" if not squashed or squashed in (NO_RESPONSE, ">", "1.") else "placeholder"
    says = _squash(item.says)
    if says and (squashed == says or (len(says) >= 30 and says in squashed)):
        return "says"
    return ""


def _prose(text: str) -> str:
    return LINK.sub(" ", CODE_SPAN.sub(" ", text))


def _entries(value: object) -> list[str]:
    if isinstance(value, list):
        return [entry.get("text", "") if isinstance(entry, dict) else str(entry)
                for entry in value if not WHOLE_COMMENT.match(str(entry))]
    return [line for line in str(value or "").splitlines() if line.strip()]


def check(form: Form, document: Document, *, root: Path = ROOT,
          bare_scripts: bool = True) -> list[Finding]:
    """Every finding of `document` against `form`, refusals first, in field order."""
    found: list[Finding] = []

    def add(rule: str, item: str, fix: str) -> None:
        severity = form.severity(rule)
        if severity != OFF:
            found.append(Finding(item, rule, severity, fix))

    values = document.fields
    filled: dict[str, object] = {}
    hashes = "#" * form.level
    for item in form.fields:
        if item.source == "title" and item.name not in values:
            continue  # no title given: the body alone is checked
        value = values.get(item.name)
        why = _emptiness(item, value)
        where = (f"the title" if item.source == "title" else
                 f"a `{item.label}:` line" if item.label else f"`{hashes} {item.heading}`")
        if why == "missing" and item.name in document.misses:
            if item.required:
                add("required", item.name, f"{item.heading} is missing: the heading "
                    f"`{document.misses[item.name]}` must be exactly `{hashes} {item.heading}`")
            continue
        if why and item.required:
            text = {"missing": "is missing", "empty": "is empty", "placeholder": "holds a placeholder",
                    "says": "repeats its own description"}[why]
            add("required", item.name, f"{item.heading or item.name} {text}: write {where}: "
                f"{item.says}")
            continue
        if why:
            continue
        filled[item.name] = value
        text = _plain(value)
        if item.kind == "choice":
            word = re.split(r"[\s,.;:]+", text.strip().casefold(), maxsplit=1)[0]
            if word not in item.choices:
                add("choice", item.name, f"{item.heading} is {text.strip()!r}: write one of "
                    f"{', '.join(item.choices)}")
        if item.not_picked and not NOT_PICKED.search(COMMENT.sub("", text)):
            add("not-picked", item.name, f"{item.heading} names no alternative: add a line "
                "`Not picked: <what and why not>`")
        if item.max_words:
            words = len(_prose(COMMENT.sub("", text)).split())
            if words > item.max_words:
                add("words", item.name, f"{item.heading} has {words} words; keep it to "
                    f"{item.max_words}")
        if item.actor and form.actors:
            names = [re.compile(rf"\b{re.escape(actor)}\b", re.IGNORECASE) for actor in form.actors]
            for number, entry in enumerate(_entries(value), 1):
                if not any(name.search(entry) for name in names):
                    add("actor", item.name, f"{item.heading} item {number} names nobody: say who "
                        f"does it ({', '.join(form.actors)})")
        if item.one_sentence:
            for number, entry in enumerate(_entries(value), 1):
                if SENTENCE_END.search(_prose(entry)):
                    add("one-sentence", item.name, f"{item.heading} item {number} has more than "
                        "one sentence: one sentence per step")
        if item.kind == "issue":
            for entry in _entries(value):
                if BARE_ISSUE.match(entry.strip()):
                    add("unnamed-entry", item.name, f"{item.heading} entry {entry.strip()} has no "
                        "name: add what it is, `#12 the forms engine`")
        if item.kind not in ("issue", "code") and item.source != "title":
            if BARE_NUMBER.search(_prose(text)):
                add("bare-number", item.name, f"{item.heading} names an issue by its number "
                    "alone: link it or name it in words")
            if BOARD.search(text):
                add("board", item.name, f"{item.heading} repeats the board (Status, Labels, "
                    "Priority, Assignee, Milestone): leave those to the tracker")
            if not item.verbatim:
                prose = _prose(COMMENT.sub("", text))
                for term in form.terms:
                    if re.search(rf"\b{re.escape(term.term)}\b", prose, re.IGNORECASE):
                        add("terms", item.name, f"{item.heading} uses the inside term "
                            f"{term.term!r}: say {term.plain}")
        if item.source == "title":
            _title(form, item, text, document, add)
    seen: dict[str, str] = {}
    for item in form.fields:
        if item.name not in filled or item.source == "title":
            continue
        key = _squash(_plain(filled[item.name]))
        if key and key.rstrip(".") != NONE:
            if key in seen:
                add("duplicate", item.name, f"{item.heading} repeats {seen[key]} word for word: "
                    "say in each what only it says")
            else:
                seen[key] = form.field(item.name).heading or item.name
    if document.source:
        for finding in _sibling("references").dangling(document.source, root, paths=False,
                                                         created=True, bare_scripts=bare_scripts):
            add("dangling", _field_at(form, document, finding.line), f"{finding}: correct it, "
                "or say in Requirements that this issue adds it")
    order = {item.name: index for index, item in enumerate(form.fields)}
    return sorted(found, key=lambda finding: (finding.severity != REFUSE,
                                              order.get(finding.field, len(order))))


def _title(form: Form, item: Field, title: str, document: Document, add) -> None:
    text = title.strip()
    if item.shape == "branch":
        if not BRANCH.match(text):
            add("title-shape", item.name, f"the title {text!r} is no branch name: write "
                "`<kind>/<topic>-<yyyymmdd>`")
        return
    if BRANCH_LIKE.match(text) or PATH_LIKE.match(text) or re.fullmatch(r"#?\d+", text):
        add("title-shape", item.name, f"the title {text!r} is a branch name, a path or a number: "
            "say in plain words what changes")
    body = _squash("\n".join(part.raw for part in document.parts if part.kind == "preamble")
                   + "\n" + "\n".join(_plain(value) for name, value in document.fields.items()
                                      if name != item.name))
    if text and re.search(rf"(?:^|\s){re.escape(_squash(text))}(?:\s|$)", body) and \
            len(text.split()) >= 3:
        add("title-shape", item.name, "the body repeats the title: the title is the GitHub title "
            "alone")


def _field_at(form: Form, document: Document, line: int) -> str:
    """The field whose section holds `line` of the document's checked text."""
    count, name = 1, "body"
    for part in document.parts:
        if part.kind in ("prefix", "gap", "suffix"):
            continue
        lines = (part.heading + "\n" if part.heading else "") + (part.raw or "")
        if part.kind == "scope":
            lines = part.heading + "\n"
        size = lines.count("\n")
        if count <= line < count + size:
            return part.name if part.kind == "field" else name
        count += size
    return name


# Command


def _fields_file(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FormError(f"forms.py check: --fields {path} is no JSON file ({error})") from error
    if isinstance(data, dict) and isinstance(data.get("fields"), dict):
        data = data["fields"]
    if not isinstance(data, dict):
        raise FormError(f"forms.py check: --fields {path} must hold an object of field values")
    return data


def _form(forms: dict[str, Form], name: str) -> Form:
    if name not in forms:
        raise FormError(f"forms.py: no form {name!r}; the forms are {', '.join(sorted(forms))}")
    return forms[name]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forms.py", description="SE's forms: check, draft, list")
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="check a body or a set of fields against a form")
    checking.add_argument("form")
    given = checking.add_mutually_exclusive_group(required=True)
    given.add_argument("--body-file", type=Path)
    given.add_argument("--fields", type=Path)
    checking.add_argument("--title")
    checking.add_argument("--tree", action="store_true", help="read the working tree's forms/")
    drafting = commands.add_parser("draft", help="print the empty form")
    drafting.add_argument("form")
    drafting.add_argument("--json", action="store_true")
    drafting.add_argument("--tree", action="store_true", help="read the working tree's forms/")
    listing = commands.add_parser("list", help="name every form with its actions")
    listing.add_argument("--tree", action="store_true", help="read the working tree's forms/")
    options = parser.parse_args(arguments)
    try:
        forms = load(ROOT, tree=options.tree)
        if options.command == "list":
            print("\n".join(list_forms(forms)))
            return 0
        form = _form(forms, options.form)
        if options.command == "draft":
            print(json.dumps(draft_fields(form), indent=2) if options.json else draft(form), end=""
                  if not options.json else "\n")
            return 0
        if options.body_file is not None:
            try:
                body = options.body_file.read_text(encoding="utf-8")
            except OSError as error:
                raise FormError(f"forms.py check: cannot read --body-file {options.body_file} "
                                f"({error})") from error
            document = parse(form, body, options.title)
        else:
            values = _fields_file(options.fields)
            title = next((item.name for item in form.fields if item.source == "title"), None)
            if options.title is not None and title:
                values[title] = options.title
            document = parse(form, render(form, values), values.get(title) if title else None)
    except FormError as error:
        print(error, file=sys.stderr)
        return 2
    findings = check(form, document)
    lines = [str(finding) for finding in findings]
    if len(lines) > 10:
        rest = len(lines) - 9
        lines = lines[:9] + [f"... and {rest} more findings"]
    refused = sum(finding.severity == REFUSE for finding in findings)
    print("\n".join(lines) if lines else f"{form.name}: no findings")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
