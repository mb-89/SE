#!/usr/bin/env python3
"""Forms: the shape of the text SE writes, kept as data, read, checked and written by one engine.

The commands that file issues (`work_tickets.py file`, `backlog file` and `route`) check with it
where se.toml `[forms] enforce` is on (README "Forms"); this module owns that switch's reading
(`enforcement`), the private-term findings (`private_findings`), the refusal text (`report`) and
the count of refusals behind `--hold` (`target`, `refusals`, `count_refusal`).

**Form files.** One TOML file per form, `forms/<name>.toml`; `forms/terms.toml` is no form but the
list of inside terms (below). A form declares:

- `name`, `reader` (`owner` or `fleet`: who reads what it shapes) and `says`, one line;
- `[applies] actions`, the actions it shapes (ACTIONS: `issue.create`, `issue.edit`, `pr.create`,
  `pr.edit`, `pr.merge`, `comment.create`, `comment.edit`, `deck.build`): required, so a form
  without it does not load; `order`, the conditions `marker`, `marker_pattern` (a regular
  expression a whole line matches) and `title`, and the filters `labels` (every one present) and
  `base = "integration"` (a pull request into the integration branch); `fallback` (selection,
  below);
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

**Adapters.** A form without `[[fields]]` is an adapter: a text SE already writes and already
checks elsewhere. It names that check, `checker = "<module>:<function>"` (a script beside this
one), and the engine calls it instead of field rules of its own; `[adapter]` says how:

- what the checker gets: the body, or `extract` (`"<module>:<function>"`, called with the body and
  `extract_with`), or `json_after` (the data of the last fenced block after the last line that is
  that marker), or `sections = true` (the body's headings and `pugh` fences as the obs nodes
  deck.py reads); `drop` maps `"."` (the data itself) or a key (its list's items) to the keys the
  writer adds beside what the checker reads, left out; `missing` (`refuse`, `warn` or `pass`)
  where there is none;
- how it is called: the value first, or as `text_as`; the title as `title_as`; `with`, constant
  keyword arguments, and `none`, the ones passed as None; `when` (`"<module>:<function>"`), only
  where that holds for the value;
- what it answers (`result`): `problems` (a list of texts, each a refusal), `raises` (its error is
  the refusal) or `truth` (false refuses with `refusal`);
- besides or instead: `title_rule`, a `"<module>:<NAME>"` pattern the title must match from its
  start, and `[[adapter.lines]]`, each a `pattern` a whole line (with `first`, the first line)
  must match, and what it `says`.

The engine never adds `<!-- se:form <name> -->` to an adapter's body: `render` gives it back as it
stands, and its findings name the field `body`.

**Fields**, `[[fields]]`: `name`, `kind`, `heading`, `required`, `none_ok` (the value "None"
fills it), `says` (what belongs there, the fix's wording and the draft's comment), `exact_heading`
(only `## <heading>`, at the form's level, counts) and `verbatim` (the text is kept and written
back as it stands). Besides: `source = "title"` (the field is the issue's title, never in the body),
`label` (a `<label>: <value>` line before the first section), `choices` (kind `choice`),
`numbered`, `continue_numbers` and `markers` (kind `list`), `lang` (kind `code`), `max_words`,
`actor`, `one_sentence`, `not_picked` and `shape`, a title's (rule `title-shape`).

A field may name code as `"<module>:<NAME>"`, a script beside this one, as an adapter's keys do;
`load` resolves it and refuses one that does not resolve, naming the form file and the key.
`shape` is `words` (plain words: no path, branch name or number) or such a reference: a pattern
the whole title matches, or a function of the title whose answer, where not empty, is the warning.
An entry of `choices` may be such a reference too: it stands for the items of that list or the
keys of that mapping.

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

**Selection** (`select(forms, action, body, title, labels=, base=, integration=, repo=, home=)`),
in this order:

1. Free where `repo` is given and is not in `home`, the repositories SE writes to (origin and
   se.toml `[outside]`, `home_repositories`).
2. The allowed forms: those that name the action, whose `labels` the text carries and, with
   `base = "integration"`, whose pull request goes into the integration branch.
3. A marker only narrows the choice within the allowed set: a body's own
   `<!-- se:form <name> -->` naming an allowed form wins. Such a line naming a form outside the
   allowed set, or an adapter's marker of an adapter outside it, is a refused finding (rule
   `form`), and selection goes on without it. SE's other markers (`se:fleet`, `se:handled` in a
   comment, `se:open-points`, `se:refs-*`) name no form and select nothing on their own.
4. By `[applies] order` (then name), the first allowed form with conditions that all hold
   (`marker`, `marker_pattern`: the body has that line; `title`: the title matches).
5. The first allowed form without conditions, or with `fallback = true`.
6. None: free form. For a pull request into the integration branch this tries `landing` and
   `housekeeping` before `field-report`; an unmarked comment, and a pull request into any other
   branch, are free.

**Severities.** `check` returns every finding at once, each with its field, rule, severity and fix.
Refuse rules: `required` (missing, empty or placeholder, or the field's own `says` pasted back),
`choice`, `not-picked` (no `Not picked:` line), `duplicate` (the same text in two fields) and
`dangling` (an SE command that does not exist, through `references.dangling` as
`work_tickets.refuse_dangling` calls it); an adapter refuses with `checker`, `line` and `title`.
Warn-only rules, never refused: `words`, `actor`, `one-sentence`, `bare-number`, `board` (Status,
Labels, Priority, Assignee or Milestone lines), `terms` (`forms/terms.toml`), `unnamed-entry` (a
blocker without a name) and `title-shape`.

**Interface** for the pieces that build on it: `load(root, tree=False)` reads `forms/` at
`origin/<integration branch>` through `git_door` where that ref holds forms, else from the working
tree; `parse(form, body, title)` gives a `Document`; `render(form, document_or_fields)`;
`check(form, document)` gives `Finding`s; `select(...)` gives a `Selection`, its form (None: free)
and its findings; `verdict(forms, action, body, title, ...)` both at once; `draft(form)`;
`list_forms(forms)` (named so beside Python's `list`). All but `load` (which also imports the scripts
a field names) and `home_repositories` are pure, but for the checkers an adapter names and the
functions a field's shape names.

**Command.** `forms.py check <form> (--body-file FILE | --fields FILE) [--title TEXT] [--tree]`
prints at most 10 lines of findings and exits 0 when nothing refuses, 1 when something does, 2 on a
usage error; `forms.py draft <form> [--json]` prints the empty form; `forms.py list` names every
form with its actions and, for an adapter, its checker. `--tree` reads the working tree's `forms/`.
None writes a file, calls GitHub or starts a model.
"""

from __future__ import annotations

import argparse
import hashlib
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

ISSUE_ACTIONS = ("issue.create", "issue.edit")
ACTIONS = (*ISSUE_ACTIONS, "pr.create", "pr.edit", "pr.merge", "comment.create", "comment.edit",
           "deck.build")
READERS = ("owner", "fleet")
KINDS = ("line", "text", "choice", "list", "object", "issue", "checklist", "code")
REFUSE, WARN, OFF = "refuse", "warn", "off"
REFUSE_RULES = ("required", "choice", "not-picked", "duplicate", "dangling")
ADAPTER_RULES = ("checker", "line", "title", "form")  # always refuse; an adapter has no [rules]
WARN_RULES = ("words", "actor", "one-sentence", "bare-number", "board", "terms", "unnamed-entry",
              "title-shape")
FIELD_KEYS = {"name", "kind", "heading", "required", "none_ok", "says", "exact_heading",
              "verbatim", "source", "label", "choices", "numbered", "continue_numbers", "markers",
              "lang", "max_words", "actor", "one_sentence", "not_picked", "shape"}
FORM_KEYS = {"name", "reader", "says", "applies", "extends", "remove", "order", "keep_unknown",
             "rules", "actors", "example", "scope", "fields", "checker", "adapter"}
APPLIES_KEYS = {"actions", "order", "marker", "marker_pattern", "title", "labels", "base",
                "fallback"}
ADAPTER_KEYS = {"extract", "extract_with", "json_after", "sections", "drop", "missing", "text_as",
                "title_as", "with", "none", "when", "result", "refusal", "title_rule", "lines"}
RESULTS = ("problems", "raises", "truth")
REFERENCE = re.compile(r"^[a-z_][a-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*$")

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
    #: What `shape` names, loaded: a pattern or a function (the module docstring: Fields).
    rule: object = dataclass_field(default=None, compare=False, repr=False)

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
    marker_pattern: str = ""
    labels: tuple[str, ...] = ()
    base: str = ""
    fallback: bool = False
    checker: str = ""
    adapter: dict = dataclass_field(default_factory=dict)

    @property
    def is_adapter(self) -> bool:
        """Whether the form is an adapter: no fields of its own, a check SE already has."""
        return not self.fields

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
    if isinstance(applies, dict) and set(applies) - APPLIES_KEYS:
        raise FormError(f"{where}: [applies] has unknown keys "
                        f"{', '.join(sorted(set(applies) - APPLIES_KEYS))}; the keys are "
                        f"{', '.join(sorted(APPLIES_KEYS))}")
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
    adapter = _adapter(data, where, fields, parent)
    base_branch = str(applies.get("base", parent.base if parent else ""))
    if base_branch not in ("", "integration"):
        raise FormError(f"{where}: [applies] base is {base_branch!r}; the one base is "
                        "\"integration\", the integration branch")
    marker_pattern = str(applies.get("marker_pattern", ""))
    try:
        re.compile(marker_pattern)
    except re.error as error:
        raise FormError(f"{where}: [applies] marker_pattern is no regular expression "
                        f"({error})") from error
    return Form(
        name=name, reader=reader, says=str(data.get("says", parent.says if parent else "")),
        actions=actions, fields=tuple(fields), rules=rules,
        order=int(applies.get("order", parent.order if parent else 100)),
        marker=str(applies.get("marker", "")), title_pattern=str(applies.get("title", "")),
        keep_unknown=bool(data.get("keep_unknown", parent.keep_unknown if parent else True)),
        actors=tuple(data.get("actors", parent.actors if parent else ())),
        example=example if example else {}, scope=dict(data.get("scope", {})),
        terms=terms, path=where, marker_pattern=marker_pattern,
        labels=tuple(str(label) for label in applies.get("labels", parent.labels if parent else ())),
        base=base_branch, fallback=bool(applies.get("fallback", False)),
        checker=str(data.get("checker", "")), adapter=adapter)


def _adapter(data: dict, where: str, fields: list[Field], parent: Form | None) -> dict:
    """An adapter's `[adapter]` table, checked as far as it can be without importing its
    checker; a form with fields takes none."""
    adapter = data.get("adapter", {})
    if fields:
        if "checker" in data or adapter:
            raise FormError(f"{where}: a form with fields takes no checker or [adapter]; an "
                            "adapter is a form without [[fields]]")
        return {}
    if parent is not None:
        raise FormError(f"{where}: an adapter extends no form")
    if not isinstance(adapter, dict) or set(adapter) - ADAPTER_KEYS:
        extra = sorted(set(adapter) - ADAPTER_KEYS) if isinstance(adapter, dict) else ["?"]
        raise FormError(f"{where}: [adapter] has unknown keys {', '.join(extra)}; the keys are "
                        f"{', '.join(sorted(ADAPTER_KEYS))} (scripts/forms.py's docstring)")
    references = [data.get("checker", ""), adapter.get("extract", ""), adapter.get("when", ""),
                  adapter.get("title_rule", "")]
    for reference in references:
        if reference and not REFERENCE.match(str(reference)):
            raise FormError(f"{where}: {reference!r} is no \"<module>:<name>\" of a script "
                            "beside scripts/forms.py")
    if adapter.get("result", "problems") not in RESULTS:
        raise FormError(f"{where}: [adapter] result is {adapter.get('result')!r}; one of "
                        f"{', '.join(RESULTS)}")
    if adapter.get("missing", REFUSE) not in (REFUSE, WARN, "pass"):
        raise FormError(f"{where}: [adapter] missing is {adapter.get('missing')!r}; one of "
                        "refuse, warn, pass")
    if adapter.get("result") == "truth" and not adapter.get("refusal"):
        raise FormError(f"{where}: [adapter] result \"truth\" needs its refusal, the fix a "
                        "false answer gives")
    for line in adapter.get("lines", []):
        if set(line) - {"pattern", "first", "says"} or not line.get("pattern") or \
                not line.get("says"):
            raise FormError(f"{where}: each [[adapter.lines]] has a pattern and says, and may "
                            "set first")
        try:
            re.compile(line["pattern"])
        except re.error as error:
            raise FormError(f"{where}: [[adapter.lines]] pattern {line['pattern']!r} is no "
                            f"regular expression ({error})") from error
    return dict(adapter)


def _field(entry: dict, where: str) -> Field:
    unknown = set(entry) - FIELD_KEYS
    name = entry.get("name", "?")
    if unknown:
        raise FormError(f"{where}: field {name} has unknown keys {', '.join(sorted(unknown))}")
    if entry.get("kind") not in KINDS:
        raise FormError(f"{where}: field {name} has kind {entry.get('kind')!r}; one of "
                        f"{', '.join(KINDS)}")
    choices: list[str] = []
    for choice in entry.get("choices", ()):
        if REFERENCE.match(str(choice)):
            named = _named(str(choice), where, f"field {name} choices")
            if isinstance(named, dict):
                named = list(named)
            if not isinstance(named, (list, tuple, set, frozenset)):
                raise FormError(f"{where}: field {name} choices: {choice} is no list or mapping; "
                                "name one whose items or keys are the choices")
            choices += [str(item) for item in named]
        else:
            choices.append(str(choice))
    shape = str(entry.get("shape", ""))
    rule = None
    if REFERENCE.match(shape):
        rule = _named(shape, where, f"field {name} shape")
        if not isinstance(rule, re.Pattern) and not callable(rule):
            raise FormError(f"{where}: field {name} shape: {shape} is no pattern or function; "
                            "name a compiled pattern or a function that gives the warning")
    made = Field(**{**entry, "choices": tuple(dict.fromkeys(choices))}, rule=rule)
    if made.in_body and not made.heading:
        raise FormError(f"{where}: field {name} needs a heading (or source = \"title\", or a label)")
    if made.kind == "choice" and not made.choices:
        raise FormError(f"{where}: field {name} is a choice without choices")
    return made


def _named(reference: str, where: str, key: str):
    """What `"<module>:<NAME>"` names in a script beside this one, refused where it does not
    resolve, naming the form file and the key."""
    module, name = reference.split(":", 1)
    try:
        return getattr(_sibling(module), name)
    except (ImportError, AttributeError, OSError) as error:
        raise FormError(f"{where}: {key}: {reference} does not resolve ({error}); name a script "
                        "beside scripts/forms.py and what it defines") from error


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
    if form.is_adapter:  # the body as it stands: its own check reads it
        fields = {} if title is None else {"title": title}
        return Document(form=form.name, fields=fields, source=body, read=dict(fields))
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
    if form.is_adapter:
        if not isinstance(document, Document):
            raise FormError(f"forms: {form.name} is an adapter and has no fields to render; the "
                            "command that writes it writes its body")
        return document.source  # never marked: the adapter's own writer owns its text
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
    """The empty form as Markdown, each field's `says` as a comment; an adapter's says what
    writes and checks it."""
    if form.is_adapter:
        return f"<!-- {form.name}: {form.says} -->\n<!-- {_checked_by(form)} -->\n"
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


def _checked_by(form: Form) -> str:
    """What checks an adapter: its checker, its title rule and its lines."""
    parts = [f"checker {form.checker or 'none'}"]
    if form.adapter.get("title_rule"):
        parts.append(f"title {form.adapter['title_rule']}")
    if form.adapter.get("lines"):
        parts.append(f"{len(form.adapter['lines'])} lines")
    return ", ".join(parts) + ("" if len(parts) > 1 or form.checker else " (no field required)")


def list_forms(forms: dict[str, Form]) -> list[str]:
    """One line per form: its name, reader, actions, an adapter's checker, and what it says."""
    return [f"{form.name} ({form.reader}): {', '.join(form.actions)}: "
            + (f"{_checked_by(form)}: " if form.is_adapter else "") + form.says
            for form in sorted(forms.values(), key=lambda item: (item.order, item.name))]


@dataclass(frozen=True)
class Selection:
    """What `select` chose: the form (None: free form) and the refused markers it met."""
    form: Form | None
    findings: tuple[Finding, ...] = ()

    @property
    def name(self) -> str | None:
        return self.form.name if self.form else None


def _repository(name: str) -> str:
    return name.strip().strip("/").removesuffix(".git").casefold()


def _at_home(repo: str, home) -> bool:
    """Whether `repo` (`<host>/<owner>/<repo>` or `<owner>/<repo>`) is one of `home`."""
    wanted = _repository(repo)
    for known in map(_repository, home):
        if wanted == known or (wanted.count("/") == 1 and known.endswith("/" + wanted)) or (
                known.count("/") == 1 and wanted.endswith("/" + known)):
            return True
    return False


def home_repositories(root: Path = ROOT) -> set[str]:
    """The repositories SE writes forms for: origin's, and each one se.toml `[outside]` lists."""
    found = set()
    origin = _sibling("work_tickets").remote_repo(root)
    if origin:
        found.add(origin)
    try:
        outside = tomllib.loads((root / "se.toml").read_text(encoding="utf-8")).get("outside", {})
    except (OSError, tomllib.TOMLDecodeError):
        outside = {}
    found.update(str(name) for name in (outside if isinstance(outside, dict) else {}))
    return found


def _carries(form: Form, lines: set[str]) -> bool:
    """Whether the body's stripped `lines` hold `form`'s marker condition."""
    if form.marker and form.marker in lines:
        return True
    return bool(form.marker_pattern) and any(re.fullmatch(form.marker_pattern, line)
                                             for line in lines)


def _why_not(form: Form, action: str) -> str:
    if action not in form.actions:
        return (f"the {form.name} form does not apply to {action}: it shapes "
                f"{', '.join(form.actions)}")
    return (f"the {form.name} form does not apply here: it needs the labels "
            f"{', '.join(form.labels) or 'none'}"
            + (" and a pull request into the integration branch" if form.base else ""))


def select(forms: dict[str, Form], action: str, body: str, title: str | None = None, *,
           labels=(), base: str | None = None, integration: str = "main",
           repo: str | None = None, home=None) -> Selection:
    """The form that shapes `body` for `action`, in the order the module docstring's
    "Selection" gives; its form None is free form."""
    if action not in ACTIONS:
        raise FormError(f"select: action {action!r} is none of {', '.join(ACTIONS)}")
    if repo is not None and home is not None and not _at_home(repo, home):
        return Selection(None)
    have = {str(label).casefold() for label in labels}

    def allowed(form: Form) -> bool:
        return (action in form.actions
                and all(label.casefold() in have for label in form.labels)
                and (not form.base or base == integration))

    candidates = sorted((form for form in forms.values() if allowed(form)),
                        key=lambda form: (form.order, form.name))
    lines = {line.strip() for line in body.splitlines()}
    refused: list[Finding] = []
    for named in dict.fromkeys(FORM_MARKER_PATTERN.findall(body)):
        if named in forms and forms[named] not in candidates:
            refused.append(Finding("body", "form", REFUSE, _why_not(forms[named], action)
                                   + f"; take out `{FORM_MARKER.format(name=named)}`"))
    for form in sorted(forms.values(), key=lambda item: item.name):
        if form.is_adapter and form not in candidates and _carries(form, lines):
            refused.append(Finding("body", "form", REFUSE, _why_not(form, action)
                                   + ", and the body carries its marker"))
    named = next((form for form in candidates for name in FORM_MARKER_PATTERN.findall(body)
                  if form.name == name), None)
    if named is not None:
        return Selection(named, tuple(refused))
    for form in candidates:
        if not form.marker and not form.marker_pattern and not form.title_pattern:
            continue
        if (form.marker or form.marker_pattern) and not _carries(form, lines):
            continue
        if form.title_pattern and not re.search(form.title_pattern, title or ""):
            continue
        return Selection(form, tuple(refused))
    plain = next((form for form in candidates if form.fallback or (
        not form.marker and not form.marker_pattern and not form.title_pattern)), None)
    return Selection(plain, tuple(refused))


def verdict(forms: dict[str, Form], action: str, body: str, title: str | None = None,
            **where) -> tuple[Form | None, list[Finding]]:
    """The form `select` takes for `body` and every finding: its refused markers, then the
    form's check; (None, the refused markers) where the body is free."""
    chosen = select(forms, action, body, title, **where)
    found = list(chosen.findings)
    if chosen.form is not None:
        found += check(chosen.form, parse(chosen.form, body, title))
    return chosen.form, found


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
    """Every finding of `document` against `form`, refusals first, in field order; an adapter's
    are its own check's."""
    if form.is_adapter:
        return adapter_findings(form, document)
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


class _Refused(Exception):
    """What an adapter's reading of a body refuses: its message is the finding's fix."""


#: The errors that mean an adapter is written wrong, never that the text is: they stop the check.
_MISCONFIGURED = (TypeError, AttributeError, NameError, ImportError, KeyError)


def resolve(reference: str, form: Form):
    """`"<module>:<name>"`, a function or a value of a script beside this one."""
    module, name = reference.split(":", 1)
    try:
        found = getattr(_sibling(module), name)
    except (ImportError, AttributeError, OSError) as error:
        raise FormError(f"{form.path}: {reference} does not resolve ({error}); name a script "
                        "beside scripts/forms.py and what it defines") from error
    return found


def _json_after(body: str, marker: str):
    """The data of the last fenced block after the last line that is `marker`; None without
    the marker."""
    lines = body.splitlines(keepends=True)
    at = max((index for index, line in enumerate(lines) if line.strip() == marker), default=None)
    if at is None:
        return None
    blocks = re.findall(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", "".join(lines[at + 1:]),
                        re.MULTILINE | re.DOTALL)
    if not blocks:
        raise _Refused(f"the {marker} block has no fenced block under it")
    try:
        return json.loads(blocks[-1][1])
    except json.JSONDecodeError as error:
        raise _Refused(f"the {marker} block is not JSON: {error}") from error


def _nodes(body: str) -> list[dict]:
    """The body's headings and `pugh` fences as obs's Document nodes, as deck.py reads a
    chapter's content: sections with their level and text, and the fences."""
    nodes: list[dict] = []
    fence: str | None = None
    for line in FRONT_MATTER.sub("", body, count=1).splitlines():
        marker = FENCE.match(line)
        if fence is None and marker:
            fence = marker.group(1)
            if line.strip()[len(fence):].strip().startswith("pugh"):
                nodes.append({"type": "pugh", "attrs": {}, "children": []})
        elif fence is not None:
            if marker and marker.group(1).startswith(fence) and not line.strip()[len(fence):]:
                fence = None
        elif heading := HEADING.match(line):
            nodes.append({"type": "section", "attrs": {"level": len(heading.group(1))},
                          "children": [{"type": "text", "text": heading.group(2), "children": []}]})
    return nodes


def _dropped(value: object, drop: dict) -> object:
    """`value` without the keys `drop` names: `"."` its own, a key its list's items'."""
    if not isinstance(value, dict):
        return value
    value = dict(value)
    for path, names in drop.items():
        if path == ".":
            value = {key: item for key, item in value.items() if key not in names}
        elif isinstance(value.get(path), list):
            value[path] = [{key: item for key, item in entry.items() if key not in names}
                           if isinstance(entry, dict) else entry for entry in value[path]]
    return value


def adapter_findings(form: Form, document: Document) -> list[Finding]:
    """An adapter's findings: its lines, its title rule, then its checker's answer, called as
    `[adapter]` says (the module docstring: adapters)."""
    spec, body = form.adapter, document.source
    title = document.fields.get("title")
    found: list[Finding] = []

    def refuse(rule: str, fix: str, severity: str = REFUSE) -> None:
        found.append(Finding("body", rule, severity, f"{form.name}: {fix}"))

    lines = [line.strip() for line in body.splitlines()]
    for line in spec.get("lines", []):
        pattern = re.compile(line["pattern"])
        if line.get("first"):
            held = bool(lines) and pattern.fullmatch(lines[0]) is not None
        else:
            held = any(pattern.fullmatch(text) for text in lines)
        if not held:
            refuse("line", line["says"])
    if spec.get("title_rule"):
        rule = resolve(spec["title_rule"], form)
        rule = rule if isinstance(rule, re.Pattern) else re.compile(str(rule))
        if title is None or rule.match(title) is None:
            refuse("title", f"the title {title!r} does not match {rule.pattern!r} "
                   f"({spec['title_rule']})")
    if not form.checker:
        return found
    try:
        if spec.get("extract"):
            value = resolve(spec["extract"], form)(body, **dict(spec.get("extract_with", {})))
        elif spec.get("json_after"):
            value = _json_after(body, spec["json_after"])
        elif spec.get("sections"):
            value = _nodes(body)
        else:
            value = body
    except _MISCONFIGURED as error:
        raise FormError(f"{form.path}: its reading failed ({type(error).__name__}: {error}); "
                        "fix [adapter]") from error
    except Exception as error:  # the extractor's own refusal, such as a QueueError
        refuse("checker", str(error))
        return found
    if value is None:
        missing = spec.get("missing", REFUSE)
        if missing != "pass":
            refuse("checker", f"the body holds nothing for {form.checker} to check"
                   + (f" (no {spec['json_after']} block)" if spec.get("json_after") else ""),
                   missing)
        return found
    value = _dropped(value, dict(spec.get("drop", {})))
    if spec.get("when") and not resolve(spec["when"], form)(value):
        return found
    keywords = {**dict(spec.get("with", {})), **{name: None for name in spec.get("none", [])}}
    if spec.get("title_as"):
        keywords[spec["title_as"]] = title or ""
    arguments = [] if spec.get("text_as") else [value]
    if spec.get("text_as"):
        keywords[spec["text_as"]] = value
    checker = resolve(form.checker, form)
    result = spec.get("result", "problems")
    try:
        answer = checker(*arguments, **keywords)
    except _MISCONFIGURED as error:
        raise FormError(f"{form.path}: {form.checker} failed ({type(error).__name__}: {error}); "
                        "fix [adapter]") from error
    except Exception as error:  # the checker's refusal
        if result != "raises":
            raise
        refuse("checker", str(error))
        return found
    if result == "problems":
        for problem in answer or []:
            refuse("checker", str(problem))
    elif result == "truth" and not answer:
        refuse("checker", spec["refusal"])
    return found


def _title(form: Form, item: Field, title: str, document: Document, add) -> None:
    text = title.strip()
    if isinstance(item.rule, re.Pattern):
        if not item.rule.fullmatch(text):
            add("title-shape", item.name, f"the title {text!r} does not match {item.shape}: "
                f"{item.says}")
    elif item.rule is not None:
        problem = str(item.rule(text) or "")
        if problem:
            add("title-shape", item.name, problem)
    elif PATH_LIKE.match(text) or re.fullmatch(r"#?\d+", text):
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


# Enforcing: the switch the filing commands read, the private terms, the refusal and its count


#: se.toml `[forms] enforce`: the values the filing commands know, `off` the default.
ENFORCE_VALUES = (OFF, WARN, REFUSE)
#: se.toml `[forms] refusals`: how many refusals of one issue open `--hold`.
DEFAULT_REFUSALS = 2
PRIVATE_RULE = "private"
REFUSAL_LINES = 10
ALSO = "Also (does not block):"


@dataclass(frozen=True)
class Enforcement:
    """se.toml `[forms]` as the filing commands read it, and where it was read."""
    enforce: str = OFF
    refusals: int = DEFAULT_REFUSALS
    where: str = "se.toml"


def enforcement(root: Path) -> Enforcement:
    """`[forms]` of `root`'s se.toml at `origin/<integration branch>` through git_door, so a branch
    cannot switch its own check off; the working tree's only where that ref does not exist. A value
    outside the switch's set is a FormError naming the file."""
    door = _sibling("git_door")
    ref = f"origin/{_integration_branch(root)}"
    known = door.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", root=root)
    if known.returncode == 0:
        where = f"{ref}:se.toml"
        shown = door.run("show", where, root=root)
        text = shown.stdout if shown.returncode == 0 else ""
    else:
        where = "se.toml"
        path = root / "se.toml"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        table = tomllib.loads(text).get("forms", {})
    except tomllib.TOMLDecodeError as error:
        raise FormError(f"forms: {where} is no TOML ({error}); fix it") from error
    if not isinstance(table, dict):
        raise FormError(f"forms: [forms] in {where} must be a table")
    enforce = table.get("enforce", OFF)
    if enforce not in ENFORCE_VALUES:
        raise FormError(f"forms: [forms] enforce = {enforce!r} in {where} is none of "
                        f"{', '.join(ENFORCE_VALUES)}; set one of them (README \"Forms\")")
    refusals = table.get("refusals", DEFAULT_REFUSALS)
    if isinstance(refusals, bool) or not isinstance(refusals, int) or refusals < 1:
        raise FormError(f"forms: [forms] refusals = {refusals!r} in {where} must be a whole "
                        "number of at least 1")
    return Enforcement(enforce, refusals, where)


def formed(form: Form, *, body: str | None = None, fields: dict | None = None,
           enforce: str = OFF) -> str:
    """The body a filing command files: `fields` always rendered through `render`; `body` as it
    stands with `enforce` off, else parsed and rendered again, its unknown sections kept."""
    if fields is not None:
        return render(form, fields)
    if body is None:
        raise FormError("forms: give a body or fields")
    if enforce == OFF or form.is_adapter:
        return body
    return render(form, parse(form, body))


def private_findings(form: Form, title: str, body: str, root: Path) -> list[Finding]:
    """A refused finding for every term of the lists `public_check.py` reads (its public list, the
    local list of `root` where it holds one, and the cloud list where its variable is set) in the
    title or the body: each names the field and the list's label, never the term. A list that
    does not load is a FormError naming only its line."""
    check = _sibling("public_check")
    try:
        local = check.load_local(root)
        cloud = check.load_cloud()
    except check.SetupError as error:
        raise FormError(f"forms: {error}") from error
    lists = [("public", pattern) for pattern in check.GENERIC_PATTERNS
             if local is None or pattern.label not in local.off]
    lists += [("local", pattern) for pattern in (local.terms if local is not None else [])]
    lists += [("cloud", pattern) for pattern in (cloud or [])]
    document = parse(form, body, title) if not form.is_adapter else None
    found: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for where, text in (("title", title), ("body", body)):
        for line, _, label in check.find(text, [pattern for _, pattern in lists]):
            kind = next(name for name, pattern in lists if pattern.label == label)
            field_name = (where if where == "title" or document is None
                          else _field_at(form, document, line))
            key = (field_name, label)
            if key in seen:
                continue
            seen.add(key)
            line_of = label.split(":", 1)[-1]
            named = {"local": f"the local list ({check.LOCAL_FILE} line {line_of})",
                     "cloud": f"the cloud list ({check.CLOUD_ENV} line {line_of})"}.get(
                         kind, f"the public list ({label})")
            found.append(Finding(field_name, PRIVATE_RULE, REFUSE,
                                 f"holds a term of {named}: stop and ask the owner before "
                                 "anything is filed"))
    return found


def _heading(form: Form, name: str) -> str:
    item = form.field(name)
    return (item.heading or item.name) if item is not None else name


def _line(form: Form, finding: Finding) -> str:
    """A finding as `<field>: <what is wrong>: <the fix>`."""
    heading = _heading(form, finding.field)
    fix = finding.fix
    if fix.startswith(f"{heading} "):
        fix = fix[len(heading) + 1:]
        fix = fix[3:] if fix.startswith("is ") else fix
    return f"{heading}: {fix}"


def _fit(head: list[str], lines: list[str], tail: list[str]) -> list[str]:
    """`head`, `lines` and `tail` in at most REFUSAL_LINES lines: lines beyond the room are joined
    onto the last one, so every finding is still named."""
    room = max(1, REFUSAL_LINES - len(head) - len(tail))
    if len(lines) > room:
        lines = lines[:room - 1] + ["; ".join(lines[room - 1:])]
    return head + lines + tail


def report(command: str, form: Form, findings: list[Finding], *, refused: bool,
           hold: str = "", scripts: Path = ROOT / "scripts") -> str:
    """The text a filing command prints for `findings` against `form`, at most REFUSAL_LINES
    lines: every refused finding with its fix, the warnings after ALSO, the `draft` command with
    the real path of SE's scripts and, with `hold` (the label it files with), the `--hold` way
    out. It never counts tries."""
    refusing = [f"  {_line(form, item)}" for item in findings if item.severity == REFUSE]
    warning = [_line(form, item) for item in findings if item.severity != REFUSE]
    if refused:
        head = [f"{command}: the {form.name} form refuses this text; fix every finding and run "
                "it again:"]
        lines = refusing
        tail = [f"{ALSO} {'; '.join(warning)}"] if warning else []
    else:
        head = [f"{command}: the {form.name} form finds this ([forms] enforce = warn); filed "
                "anyway:"]
        lines = [f"  {_line(form, item)}" for item in findings]
        tail = []
    tail.append(f"The empty form: uv run python {scripts / 'forms.py'} draft {form.name}")
    if hold:
        tail.append("Or run it again with --hold: it files the text as given, labelled "
                    f"{hold} and not ready, and nobody starts it until it is fixed")
    return "\n".join(_fit(head, lines, tail))


def target(form: str, repo: str, action: str, *, number: int | None = None,
           title: str = "") -> str:
    """What one count of refusals is about: the form, the repository and the action, then the
    issue's number, or the normalised title of a new issue."""
    what = f"#{number}" if number is not None else " ".join(title.casefold().split())
    return f"{form}|{repo.casefold()}|{action}|{what}"


def counts_file(environ: dict[str, str] | None = None) -> Path:
    """The session's count of refusals: `~/.se/forms/<session>.json`, never inside a checkout.
    The session is the one the variables `ci_trust.SESSION_VARIABLES` name."""
    _sibling("git_door")
    name = _sibling("ci_trust").session(environ)
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".se" / "forms" / f"{digest}.json"


def _counts(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): int(value) for key, value in data.items()
            if isinstance(value, int)} if isinstance(data, dict) else {}


def refusals(key: str, environ: dict[str, str] | None = None) -> int:
    """How many times this session's filing of `key` was refused."""
    return _counts(counts_file(environ)).get(key, 0)


def count_refusal(key: str, environ: dict[str, str] | None = None) -> int:
    """Count one more refusal of `key` in this session; gives the count now."""
    path = counts_file(environ)
    counts = _counts(path)
    counts[key] = counts.get(key, 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return counts[key]


# Command


def fields_file(path: Path, command: str = "forms.py check") -> dict[str, object]:
    """The field values of a `--fields` file: an object of them, or `draft --json`'s answer."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FormError(f"{command}: --fields {path} is no JSON file ({error})") from error
    if isinstance(data, dict) and isinstance(data.get("fields"), dict):
        data = data["fields"]
    if not isinstance(data, dict):
        raise FormError(f"{command}: --fields {path} must hold an object of field values")
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
            values = fields_file(options.fields)
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
