#!/usr/bin/env python3
"""Templates: the shape of the text SE writes, kept as data, read, checked and written by one engine.

The commands that file issues (`work_tickets.py file`, `backlog file` and `route`) check with it
where se.toml `[templates] enforce` is on (README "Templates"); this module owns that switch's reading
(`enforcement`), the private-term findings (`private_findings`), the refusal text (`report`) and
the count of refusals behind `--hold` (`target`, `refusals`, `count_refusal`).

**Template files.** One Markdown note per template, `templates/<name>.md` (docs/templates.md "The
template"); `templates/terms.toml` is no template but the list of inside terms (below). A note
opens with its front matter between `---` lines, then its skeleton.

The front matter is YAML in the subset `front_data` reads, so every YAML reader reads it alike:
`key: value` lines and `- ` list items, nested by indenting with spaces; `#` starts a comment
line; a value is JSON where it opens with `"`, `[` or `{` (a quoted string, a list, a mapping, on
one line), a single-quoted string, `true`, `false`, a whole number or plain words. Plain words
another reader takes for something else (`off`, `yes`, `null`, `1.5`), or that hold `: ` or ` #`,
are refused until quoted. It declares:

- `name`, the file's; `version`, the template's semantic version (`1.2.0`), which its marker
  writes; `kind` (TEMPLATE_KINDS: `document`, `block`, `entry` or `interface`); `tags`, a list of
  words, the template's one link to guidance, which `scripts/se_guidance.py` reads
  (docs/guidance.md "Resolution"); `reader` (`owner` or `fleet`: who reads what it
  shapes) and `says`, one line. `version`, `kind` and `tags` are every template's own, never
  inherited;
- `applies.actions`, the actions it shapes (ACTIONS: `issue.create`, `issue.edit`, `pr.create`,
  `pr.edit`, `pr.merge`, `comment.create`, `comment.edit`, `deck.build`, `file.write`): required,
  so a template without it does not load; `paths`, the globs of the files a `file.write` template claims,
  relative to the project root (`*` and `?` within a folder, `**` across folders), which goes only
  with `actions: ["file.write"]` and which `file.write` needs; `order`, the conditions `marker`, `marker_pattern` (a regular
  expression a whole line matches) and `title`, and the filters `labels` (every one present) and
  `base: integration` (a pull request into the integration branch); `fallback` (selection,
  below);
- `extends`, another template whose fields, rules, actors and `applies` it inherits; `remove` names
  inherited fields it drops, a field of the same name replaces the inherited one, and `order`
  lists its final field order (every field once) where the inherited order does not fit;
- `keep_unknown` (default true): whether `render` keeps the sections the template does not declare;
- `rules`, each writing rule it uses marked `refuse`, `warn` or `"off"`; a rule it does not name is
  off. A warn-only rule marked `refuse` does not load;
- `actors`, the names a step or a check may name (rule `actor`), and `example`, a `title` and
  `fields` that pass the template, which the tests render and parse back;
- `scope` (optional): `after`, a marker line, `section`, the heading under it, and `level`, the
  heading level of its fields. Only that section is read; the text above the marker is data, never
  checked or read into a field, and kept as it is;
- `fields`, a list of the fields (below), in order.

**The skeleton**, the note's body, is the empty document: one section per field that has one (not
the title, not a label line), in the order `fields` lists them, each its heading at the template's
level (`##`, or the scope's) and one comment alone, `<!-- <field>: <instruction> -->`. The section
owns the field's `heading` and its `says`, the instruction, so the front matter repeats neither; a
title or label field keeps its `says` in the front matter. An inherited field's section stays in
the note it is declared in. Outside the sections the body holds nothing but blank lines; an
adapter's body is empty.

**Adapters.** A template without `fields` is an adapter: a text SE already writes and already
checks elsewhere. It names that check, `checker: <module>:<function>` (a script beside this
one), and the engine calls it instead of field rules of its own; `adapter` says how:

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
  start, and `lines`, each a `pattern` a whole line (with `first`, the first line)
  must match, and what it `says`.

The engine never adds its template marker to an adapter's body: `render` gives it back as it
stands, and its findings name the field `body`.

**Fields**, the items of `fields`: `name`, `kind`, `heading`, `required`, `none_ok` (the value "None"
fills it), `says` (what belongs there, the fix's wording and the draft's comment), `exact_heading`
(only `## <heading>`, at the template's level, counts) and `verbatim` (the text is kept and written
back as it stands). Besides: `source: title` (the field is the issue's title, never in the body),
`label` (a `<label>: <value>` line before the first section), `choices` (kind `choice`),
`numbered`, `continue_numbers` and `markers` (kind `list`), `lang` (kind `code`), `max_words`,
`first_sentence_chars` (rule `first-sentence`: the most characters the field's first sentence
should have, 0 for none), `actor`, `one_sentence`, `not_picked`, `shape`, a title's (rule
`title-shape`), and `quote` (rule `quote`: the value quotes the raw input word for word).

A field may name code as `"<module>:<NAME>"`, a script beside this one, as an adapter's keys do;
`load` resolves it and refuses one that does not resolve, naming the template file and the key.
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

**Files.** For a `file.write` template the text is a file: its front matter and its page title, the
first `#` line above the first field, are its head. `parse` never reads the page title as a field,
even where its text is a field's heading; `render` keeps the head as it stands and writes neither
marker, its fields as `## ` headings below the title. Into the front matter it writes the marker's
three as the lines a file records its template by (`Template.front_lines`): `template:
<repository>/<name>`, `version: <version>` and `overlay: <digest>`, each in its place where the
front matter holds it, a missing one after the last of them (a new block where the file has none).

**Writing.** `render` writes SE's fleet marker once, then the template marker,
`<!-- se:template <repository>/<name> <version> <digest> -->` (with a scope, the template marker
alone, after the scope's marker), then `## ` headings. The marker says what the engine knows:
the repository `se` for SE's own templates and `project` for any other `templates/` or
`--templates` folder, the template's `version`, and
`sha256:<hex>` of the template's file text, then those of the templates it `extends`, each ended
by a NUL byte (`Template.marker_line`); the digest stands where docs/templates.md "The document"
puts the overlay's until templates have overlays. Selection reads the name alone. A section the template does not
declare, and a field whose value did not change, are written back byte for byte in their place;
a `verbatim` field is never reflowed.

**Selection** (`select(templates, action, body, title, labels=, base=, integration=, repo=, home=,
path=)`), in this order; for `file.write` the order below it:

1. Free where `repo` is given and is not in `home`, the repositories SE writes to (origin and
   se.toml `[outside]`, `home_repositories`).
2. The allowed templates: those that name the action, whose `labels` the text carries and, with
   `base: integration`, whose pull request goes into the integration branch.
3. A marker only narrows the choice within the allowed set: a body's own
   template marker naming an allowed template wins. Such a line naming a template outside the
   allowed set, or an adapter's marker of an adapter outside it, is a refused finding (rule
   `template`), and selection goes on without it. SE's other markers (`se:fleet`, `se:handled` in a
   comment, `se:open-points`, `se:refs-*`) name no template and select nothing on their own.
4. By `applies.order` (then name), the first allowed template with conditions that all hold
   (`marker`, `marker_pattern`: the body has that line; `title`: the title matches).
5. The first allowed template without conditions, or with `fallback = true`.
6. None: free. For a pull request into the integration branch this tries `landing` and
   `housekeeping` before `field-report`; an unmarked comment, and a pull request into any other
   branch, are free.

For a file, `path` (relative to the project root) selects:

1. The allowed templates: the `file.write` templates whose `paths` match it; none, and the file is free.
2. The front matter's `template: <name>` (or `<repository>/<name>`, as `render` writes it) naming an
   allowed template chooses it, as a body's template marker does; one naming another template is a
   refused finding (rule `template`).
3. By `applies.order` (then name), the first allowed template whose conditions all hold, matched
   against every line, the front matter's too.
4. None: a refused finding, `<path>: no template takes this file; name its template in the front matter,
   template: <name>`.

**Severities.** `check` returns every finding at once, each with its field, rule, severity and fix.
Refuse rules: `required` (missing, empty or placeholder, or the field's own `says` pasted back),
`choice`, `not-picked` (no `Not picked:` line), `duplicate` (the same text in two fields) and
`dangling` (an SE command that does not exist, through `references.dangling` as
`work_tickets.refuse_dangling` calls it); an adapter refuses with `checker`, `line` and `title`.
A `quote` field always refuses (QUOTE_RULE, never a template's to set) a value that quotes nothing
and, given the raw input (`check(raw=)`, as `fill` gives it), a quote the raw input does not hold
word for word (`quoted`). A quote is a span in `"..."` or `“...”` on one line, or a run of `>`
lines (`quotes`); whitespace and line breaks aside, case counts.
Warn-only rules, never refused: `words`, `first-sentence` (the first sentence, taken as
`work_tickets.goal_summary` takes it, runs past `first_sentence_chars`: a work issue's Goal's
becomes its landing title), `actor`, `one-sentence`, `bare-number`, `board` (Status, Labels,
Priority, Assignee or Milestone lines), `terms` (`templates/terms.toml`), `unnamed-entry` (a blocker
without a name) and `title-shape`.

**Not in input** (NOT_IN_INPUT, docs/templates.md "Fill"): every field takes the value `Not in input`
where the raw input does not answer it, whatever its kind and rules (`not_in_input`): the text
alone, or a list of that one item, a checklist of that one entry, an object of that one key without
a value; case and a closing period aside. `check` applies none of the field's rules to it, so a
required field so filled passes and shows the gap; `parse` reads the section back as that text and
`render` writes it so, and the schema's `enum` of a choice holds it beside the choices. The fix of a
`required` refusal names it.

**Version** (rule `version`, `provenance`): `check` reads a document against the version it records,
its template marker's or, for a file, the front matter's `version:` where its `template:` names the
template. None recorded, or the template's own, passes; another minor or patch version warns;
another major version, or one that is no semantic version, refuses, naming both versions and the
fill that writes the document again. The move sets the severity, never the template's `rules`.
`render` records the template's version now, so the filing commands also read the version of the
text as it was given (`work_tickets.template_findings`).

**Interface** for the pieces that build on it: `load(root, tree=False)` reads `templates/` at
`origin/<integration branch>` through `git_door` where that ref holds a template note, else from the working
tree; `parse(template, body, title)` gives a `Document`; `render(template, document_or_fields)`;
`check(template, document)` gives `Finding`s; `select(...)` gives a `Selection`, its template (None: free)
and its findings; `verdict(templates, action, body, title, ...)` both at once; `draft(template)`;
`list_templates(templates)` (named so beside Python's `list`). All but `load` (which also imports the scripts
a field names) and `home_repositories` are pure, but for the checkers an adapter names and the
functions a field's shape names.

**Command.** `templates.py check <template> (--body-file FILE | --fields FILE | --body TEXT |
--fields-json TEXT) [--title TEXT] [--render] [--tree]` prints at most 10 lines of findings and
exits 0 when nothing refuses, 1 when something does, 2 on a usage error.

- `--fields-json` takes the object `--fields` reads (or `draft --json`'s answer) as text; both take
  an object field as a mapping or as the schema's list of `{"key", "value"}` pairs (`answer`).
- `--render`: where nothing refuses, stdout is only the Markdown `render` writes, its markers
  included, and the warnings go to stderr.
- Without `<template>`, `--action <action>` with `--repo`, `--labels` (comma-separated), `--base` and
  `--title` checks against the template `select` picks; where it picks none it prints
  `free: no template applies (<action>)` and exits 0 (with `--render`, that line on stderr and the
  body as given on stdout). A template and `--action` together are a usage error.

- `--path FILE`, without `<template>`: the template that claims the file (`file.write`), whose text it
  checks unless `--body`, `--body-file`, `--fields` or `--fields-json` gives one; on a file no
  template claims it prints `free: no template claims <path>` and exits 0. `--root DIR` is the project
  root the globs are relative to: by default the git checkout holding the path, else the working
  directory.

`templates.py draft (<template> | --path FILE [--root DIR]) [--json]` prints the empty template. Its JSON holds `template`, `says`, `fields`
(each field's empty value) and `field_says`, then `field_shape`, each field's `kind` and, where
the field sets them, its `heading`, `required`, `none_ok`, `choices` (resolved), `max_words`,
`first_sentence_chars`, `numbered`, `label` and `source` (`field_shape`), and `schema`, a JSON Schema 2020-12 of the
fields written with SCHEMA_KEYWORDS alone, which strict tool use on the Claude API accepts
(`schema`). `templates.py schema (<template> | --path FILE [--root DIR])` prints that schema
alone, the generated one: no template writes its schema by hand. `templates.py list` names every template with its actions, then the paths it claims and, for an
adapter, its checker. `--tree` reads the working tree's `templates/`; `--templates DIR`, on all four, reads
the templates and `terms.toml` from that folder instead, for that run alone (`load(folder=)`). None writes a file, calls GitHub or starts a model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field as dataclass_field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = "templates"
TERMS_FILE = "terms.toml"
TEMPLATE_SUFFIX = ".md"  # a template is the note templates/<name>.md

FLEET_MARKER = "<!-- se:fleet -->"
TEMPLATE_MARKER = "<!-- se:template {repository}/{name} {version} {digest} -->"
TEMPLATE_MARKER_PATTERN = re.compile(r"^[ \t]*<!-- se:template [\w.-]+(?:/[\w.-]+)*/([\w-]+) [\w.+-]+ "
                                     r"sha256:[0-9a-f]+ -->[ \t]*$", re.MULTILINE)
SE_REPOSITORY = "se"  # the repository of SE's own templates in the marker
PROJECT_REPOSITORY = "project"  # that of a project's own, or a --templates folder's

ISSUE_ACTIONS = ("issue.create", "issue.edit")
FILE_ACTION = "file.write"
ACTIONS = (*ISSUE_ACTIONS, "pr.create", "pr.edit", "pr.merge", "comment.create", "comment.edit",
           "deck.build", FILE_ACTION)
READERS = ("owner", "fleet")
KINDS = ("line", "text", "choice", "list", "object", "issue", "checklist", "code")
REFUSE, WARN, OFF = "refuse", "warn", "off"
#: The rule of a document's recorded version against its template's (`provenance`): its severity is
#: the move's, never a template's to set.
VERSION_RULE = "version"
#: The rule of a `quote` field's quotes against the raw input (`quoted`): it always refuses, never
#: a template's to set.
QUOTE_RULE = "quote"
#: A quote in a field's value: a span in straight or curly double quotes on one line, or a run of
#: `>` lines.
QUOTE_SPANS = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
QUOTE_LINE = re.compile(r"^[ \t]*>[ \t]?(.*?)[ \t]*$")
REFUSE_RULES = ("required", "choice", "not-picked", "duplicate", "dangling")
ADAPTER_RULES = ("checker", "line", "title", "template")  # always refuse; an adapter has no rules
WARN_RULES = ("words", "first-sentence", "actor", "one-sentence", "bare-number", "board", "terms",
              "unnamed-entry", "title-shape")
FIELD_KEYS = {"name", "kind", "heading", "required", "none_ok", "says", "exact_heading",
              "verbatim", "source", "label", "choices", "numbered", "continue_numbers", "markers",
              "lang", "max_words", "first_sentence_chars", "actor", "one_sentence", "not_picked", "shape",
              "quote"}
TEMPLATE_KEYS = {"name", "version", "kind", "tags", "reader", "says", "applies", "extends", "remove", "order", "keep_unknown",
             "rules", "actors", "example", "scope", "fields", "checker", "adapter"}
APPLIES_KEYS = {"actions", "order", "marker", "marker_pattern", "title", "labels", "base",
                "fallback", "paths"}
ADAPTER_KEYS = {"extract", "extract_with", "json_after", "sections", "drop", "missing", "text_as",
                "title_as", "with", "none", "when", "result", "refusal", "title_rule", "lines"}
RESULTS = ("problems", "raises", "truth")
REFERENCE = re.compile(r"^[a-z_][a-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*$")

FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
FRONT_TEMPLATE = re.compile(r"^template[ \t]*:[ \t]*['\"]?(?:[\w.-]+/)*([\w-]+)['\"]?[ \t]*$",
                            re.MULTILINE)
#: The three front matter keys a claimed file records its template by (`Template.front_lines`).
PROVENANCE_KEYS = ("template", "version", "overlay")
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
#: The value every field takes where the raw input does not answer it (docs/templates.md "Fill"):
#: it passes whatever the field's rules, and shows the gap instead of an invented value.
NOT_IN_INPUT = "Not in input"
NOT_PICKED = re.compile(r"^[ \t>*_-]*not picked[*_]*:[*_]*[ \t]*\S", re.IGNORECASE | re.MULTILINE)
BOARD = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?\**(status|labels?|priority|assignee|milestone)\**[ \t]*:",
                   re.IGNORECASE | re.MULTILINE)
BARE_NUMBER = re.compile(r"(?<![\w/&#\[])#\d+\b")
CODE_SPAN = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")
PATH_LIKE = re.compile(r"^\S*[/\\]\S*$|^\S+\.(py|md|toml|go|json|yml|yaml|sh|ps1)$")
BARE_ISSUE = re.compile(r"^(?:[\w.-]+/[\w.-]+)?#\d+$|^<?https?://\S+>?$")
SENTENCE_END = re.compile(r"[.!?](?=[ \t]+[A-Z(\"'`])")
#: Where a text's list starts, and where its first sentence ends, as `work_tickets.goal_summary`
#: reads a Goal (rule `first-sentence`).
LIST_START = re.compile(r"\n[ \t]*(?:[-*+]|\d+[.)])[ \t]")
FIRST_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


class TemplateError(Exception):
    """A template that does not load, or a usage the command refuses: the message names the file or
    the argument and the remedy."""


@dataclass(frozen=True)
class Field:
    """One field of a template; the module docstring owns what each key means."""
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
    first_sentence_chars: int = 0
    actor: bool = False
    one_sentence: bool = False
    not_picked: bool = False
    shape: str = ""
    quote: bool = False
    #: What `shape` names, loaded: a pattern or a function (the module docstring: Fields).
    rule: object = dataclass_field(default=None, compare=False, repr=False)

    @property
    def in_body(self) -> bool:
        """Whether the field has a section of its own (not the title, not a label line)."""
        return not self.source and not self.label


@dataclass(frozen=True)
class Term:
    """An inside term (`templates/terms.toml`) and the plain words a reader outside knows."""
    term: str
    plain: str


@dataclass(frozen=True)
class Template:
    """A loaded template, its `extends` resolved."""
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
    paths: tuple[str, ...] = ()
    repository: str = SE_REPOSITORY
    version: str = ""
    kind: str = "document"
    tags: tuple[str, ...] = ()
    digest: str = ""

    @property
    def marker_line(self) -> str:
        """The template's marker line, `<!-- se:template <repository>/<name> <version> <digest> -->`."""
        return TEMPLATE_MARKER.format(repository=self.repository, name=self.name,
                                      version=self.version, digest=self.digest)

    @property
    def front_lines(self) -> tuple[tuple[str, str], ...]:
        """What a claimed file's front matter records: `template: <repository>/<name>`, `version`
        and `overlay`, the marker's three in turn."""
        return tuple(zip(PROVENANCE_KEYS, (f"{self.repository}/{self.name}", self.version,
                                           self.digest)))

    @property
    def is_file(self) -> bool:
        """Whether the template shapes files (`file.write`), claimed by its `paths`."""
        return FILE_ACTION in self.actions

    def claims(self, path: str) -> bool:
        """Whether one of the template's `paths` matches `path`, relative to the project root."""
        return any(glob_pattern(glob).fullmatch(path) for glob in self.paths)

    @property
    def is_adapter(self) -> bool:
        """Whether the template is an adapter: no fields of its own, a check SE already has."""
        return not self.fields

    def field(self, name: str) -> Field | None:
        return next((item for item in self.fields if item.name == name), None)

    def severity(self, rule: str) -> str:
        return self.rules.get(rule, OFF)

    @property
    def level(self) -> int:
        """The heading level of the template's sections: 2, or the scope's."""
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
    """A body read into a template's fields; `parts` keeps its layout so `render` can write the rest
    back as it was. `fields` holds the fields present, the title among them."""
    template: str
    fields: dict[str, object]
    parts: list[Part] = dataclass_field(default_factory=list)
    source: str = ""
    misses: dict[str, str] = dataclass_field(default_factory=dict)
    read: dict[str, object] = dataclass_field(default_factory=dict)
    #: The template version the body records, in its marker line or its front matter; "" for none.
    recorded: str = ""


# Loading


def _template_files(root: Path, tree: bool, folder: Path | None = None) -> dict[str, str]:
    """`templates/<file>` -> its text, at origin's integration branch where that holds templates, else
    from the working tree; with `folder`, the template notes and the term list of that folder alone."""
    if folder is not None:
        if not folder.is_dir():
            raise TemplateError(f"templates: --templates {folder} is no folder; name the folder that holds "
                            "the templates")
        return _folder_files(folder)
    if not tree:
        files = _git_files(root)
        if files:
            return files
    folder = root / TEMPLATES
    if not folder.is_dir():
        raise TemplateError(f"templates: {folder} does not exist; run from an SE checkout")
    return _folder_files(folder)


def _template_file(name: str) -> bool:
    """Whether a file of `templates/` is read: a template note, or the term list."""
    return name.endswith(TEMPLATE_SUFFIX) or name == TERMS_FILE


def _folder_files(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())
            if path.is_file() and _template_file(path.name)}


def _integration_branch(root: Path) -> str:
    try:
        project = tomllib.loads((root / "se.toml").read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return "main"
    branch = project.get("integration_branch", "main") if isinstance(project, dict) else "main"
    return branch.strip() if isinstance(branch, str) and branch.strip() else "main"


def _git_files(root: Path) -> dict[str, str]:
    """`templates/<file>` -> its text at origin's integration branch; none where that ref holds no
    template note (no `templates/`, or a term list alone)."""
    door = _sibling("git_door")
    ref = f"origin/{_integration_branch(root)}"
    listed = door.run("ls-tree", "-r", "--name-only", ref, "--", TEMPLATES, root=root)
    if listed.returncode != 0:
        return {}
    files = {}
    for path in listed.stdout.splitlines():
        if path.startswith(f"{TEMPLATES}/") and path.count("/") == 1 and _template_file(path.split("/", 1)[1]):
            shown = door.run("show", f"{ref}:{path}", root=root)
            if shown.returncode == 0:
                files[path.split("/", 1)[1]] = shown.stdout
    return files if any(name.endswith(TEMPLATE_SUFFIX) for name in files) else {}


def _sibling(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module



#: A front matter line: its key and what follows it.
YAML_KEY = re.compile(r'^("(?:[^"\\]|\\.)*"|[A-Za-z_][\w.-]*):(?:[ \t]+(.*?))?[ \t]*$')
YAML_INT = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
#: Plain words another YAML reader takes for something else than a string: quote them.
YAML_AMBIGUOUS = re.compile(r"^(?:null|~|y|n|yes|no|on|off|true|false|-?[0-9][0-9_]*\.[0-9_]*"
                            r"|[-+]?\.(?:inf|nan)|0[xo][0-9a-f]+)$", re.IGNORECASE)
YAML_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"
#: A section of a template's skeleton: its heading, then the comment `<!-- <field>: <instruction> -->`.
INSTRUCTION = re.compile(r"\A[ \t\r\n]*<!--[ \t\r\n]*([a-z_][a-z0-9_]*):[ \t\r\n]*(.*?)[ \t\r\n]*-->[ \t\r\n]*\Z",
                         re.DOTALL)
SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
TEMPLATE_KINDS = ("document", "block", "entry", "interface")


def _yaml_lines(text: str, where: str, first: int) -> list[tuple[int, int, str]]:
    """The front matter's lines that hold data, as (line number, indentation, text)."""
    lines = []
    for number, line in enumerate(text.splitlines(), first):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise TemplateError(f"{where}:{number}: front matter is indented with a tab; indent with spaces")
        lines.append((number, len(line) - len(line.lstrip(" ")), stripped))
    return lines


def _yaml_scalar(text: str, where: str) -> object:
    """One value of the front matter: JSON where it opens with `"`, `[` or `{`, a single-quoted
    string, `true`, `false`, a whole number, or a plain string."""
    if text[:1] in "\"[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise TemplateError(f"{where}: {text} is no JSON value ({error.msg}); write a quoted "
                                "string, a list or a mapping as JSON") from error
    if text[:1] == "'":
        if len(text) < 2 or not text.endswith("'") or "'" in text[1:-1].replace("''", ""):
            raise TemplateError(f"{where}: {text} is no single-quoted string; double a quote inside it")
        return text[1:-1].replace("''", "'")
    if text in ("true", "false"):
        return text == "true"
    if YAML_INT.match(text):
        return int(text)
    if (YAML_AMBIGUOUS.match(text) or text[0] in YAML_INDICATORS or ": " in text or " #" in text
            or text.endswith(":")):
        raise TemplateError(f"{where}: {text} is a plain value another YAML reader may read "
                            "otherwise; quote it as a JSON string")
    return text


def _yaml_block(lines: list[tuple[int, int, str]], index: int, indent: int,
                where: str) -> tuple[object, int]:
    """The mapping or the list that starts at `lines[index]`, at `indent`, and where it ends."""
    number, own, text = lines[index]
    if own != indent:
        raise TemplateError(f"{where}:{number}: indented {own} spaces where {indent} are expected")
    if text == "-" or text.startswith("- "):
        items: list[object] = []
        while index < len(lines) and lines[index][1] == indent and (
                lines[index][2] == "-" or lines[index][2].startswith("- ")):
            number, _, text = lines[index]
            rest = text[1:].strip()
            if not rest:
                raise TemplateError(f"{where}:{number}: an empty list item; write its value after `- `")
            if YAML_KEY.match(rest) and rest[:1] not in "[{":
                lines = [*lines[:index], (number, indent + 2, rest), *lines[index + 1:]]
                value, index = _yaml_block(lines, index, indent + 2, where)
                items.append(value)
                continue
            items.append(_yaml_scalar(rest, f"{where}:{number}"))
            index += 1
        if index < len(lines) and lines[index][1] > indent:
            raise TemplateError(f"{where}:{lines[index][0]}: indented deeper than its list's items")
        return items, index
    mapping: dict[str, object] = {}
    while index < len(lines) and lines[index][1] == indent:
        number, _, text = lines[index]
        match = YAML_KEY.match(text)
        if match is None or text.startswith("- "):
            raise TemplateError(f"{where}:{number}: {text} is no `key: value` line")
        key = json.loads(match.group(1)) if match.group(1).startswith('"') else match.group(1)
        if key in mapping:
            raise TemplateError(f"{where}:{number}: {key} is given twice")
        if match.group(2):
            mapping[key] = _yaml_scalar(match.group(2), f"{where}:{number}")
            index += 1
            if index < len(lines) and lines[index][1] > indent:
                raise TemplateError(f"{where}:{lines[index][0]}: indented below a key that has its value")
            continue
        if index + 1 >= len(lines) or lines[index + 1][1] <= indent:
            raise TemplateError(f"{where}:{number}: {key} has no value; write it after the colon, "
                                "or indent its mapping or list below it")
        mapping[key], index = _yaml_block(lines, index + 1, lines[index + 1][1], where)
    if index < len(lines) and lines[index][1] > indent:
        raise TemplateError(f"{where}:{lines[index][0]}: indented deeper than the keys above it")
    return mapping, index


def front_data(text: str, where: str, first: int = 2) -> dict[str, object]:
    """The front matter `text` (without its `---` lines) as data, in the YAML subset the module
    docstring names (Template files); `first` is its first line's number in the file."""
    lines = _yaml_lines(text, where, first)
    if not lines:
        return {}
    data, index = _yaml_block(lines, 0, 0, where)
    if not isinstance(data, dict):
        raise TemplateError(f"{where}:{lines[0][0]}: the front matter is a list; write `key: value` lines")
    if index < len(lines):
        raise TemplateError(f"{where}:{lines[index][0]}: {lines[index][2]} is outside the front matter's keys")
    return data


def note_data(text: str, where: str) -> dict[str, object]:
    """A template note as the data `_build` reads: its front matter, each field of its skeleton
    given its `heading` and its `says` from its section (the module docstring: Template files)."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise TemplateError(f"{where}: a template opens with its front matter between `---` lines")
    end = text.find("\n---\n", 3)
    if end < 0 and text.endswith("\n---"):
        end = len(text) - 4
    if end < 0:
        raise TemplateError(f"{where}: the front matter has no closing `---` line")
    data = front_data(text[4:end + 1], where)
    body = text[end + 5:]
    first = text.count("\n", 0, end + 5) + 1
    fields = data.get("fields", [])
    if not isinstance(fields, list) or not all(isinstance(entry, dict) for entry in fields):
        raise TemplateError(f"{where}: fields is a list of mappings, one per field")
    scope = data.get("scope", {})
    level = int(scope.get("level", 2)) if isinstance(scope, dict) and scope else 2
    sections = _skeleton(body, where, first, level)
    in_body = [entry for entry in fields if not entry.get("source") and not entry.get("label")]
    for entry in in_body:
        for key in ("heading", "says"):
            if key in entry:
                raise TemplateError(f"{where}: field {entry.get('name', '?')} has its section in the "
                                    f"skeleton, which owns its {key}; take {key} out of the front matter")
    named = [entry.get("name") for entry in in_body]
    listed = [name for name, _, _ in sections]
    if listed != named:
        raise TemplateError(f"{where}: the skeleton's sections are {', '.join(listed) or 'none'}; they "
                            f"are one per field with a section, in the front matter's order: "
                            f"{', '.join(map(str, named)) or 'none'}")
    for entry, (_, heading, says) in zip(in_body, sections):
        entry["heading"], entry["says"] = heading, says
    return data


def _skeleton(body: str, where: str, first: int, level: int) -> list[tuple[str, str, str]]:
    """The skeleton's sections as (field, heading, instruction); outside them only blank lines."""
    sections: list[tuple[str, str, str, int]] = []
    current: list[str] | None = None
    heading_line = 0
    texts: list[list[str]] = []
    hashes = "#" * level
    for number, line in enumerate(body.splitlines(), first):
        match = HEADING.match(line)
        if match and len(match.group(1)) == level:
            current = []
            texts.append(current)
            sections.append(("", match.group(2), "", number))
            continue
        if match:
            raise TemplateError(f"{where}:{number}: {line} is no section of the skeleton; its sections "
                                f"are `{hashes} <heading>` lines")
        if current is None:
            if line.strip():
                raise TemplateError(f"{where}:{number}: text before the skeleton's first section; "
                                    "a comment on the template goes in the front matter, after `#`")
            continue
        current.append(line)
    made = []
    for (_, heading, _, number), lines in zip(sections, texts):
        instruction = INSTRUCTION.match("\n".join(lines))
        if instruction is None:
            raise TemplateError(f"{where}:{number}: section {heading} holds one comment alone, "
                                "`<!-- <field>: <instruction> -->`")
        made.append((instruction.group(1), heading, " ".join(instruction.group(2).split())))
    return [(name, heading, says) for name, heading, says in made]


def load(root: Path = ROOT, *, tree: bool = False, folder: Path | None = None) -> dict[str, Template]:
    """Every template of `root`'s `templates/`, by name (the module docstring: where it reads them); with
    `folder`, the templates and the terms of that folder instead, for one run (`--templates`)."""
    files = _template_files(root, tree, folder)
    own = folder is None and root.resolve() == ROOT.resolve()
    repository = SE_REPOSITORY if own else PROJECT_REPOSITORY
    raw: dict[str, dict] = {}
    texts: dict[str, str] = {}
    terms: tuple[Term, ...] = ()
    for name, text in files.items():
        where = str(folder / name) if folder is not None else f"{TEMPLATES}/{name}"
        if name == TERMS_FILE:
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError as error:
                raise TemplateError(f"{where}: not TOML ({error}); fix the file") from error
            terms = tuple(Term(str(item["term"]), str(item.get("plain", "")))
                          for item in data.get("terms", []))
            continue
        data = note_data(text, where)
        template_name = data.get("name")
        if template_name != name.removesuffix(TEMPLATE_SUFFIX):
            raise TemplateError(f"{where}: name: {template_name!r} must be the file's name, "
                            f"{name.removesuffix(TEMPLATE_SUFFIX)!r}")
        data["path"] = where
        raw[template_name] = data
        texts[template_name] = text
    built = {name: _build(name, raw, terms, ()) for name in sorted(raw)}
    return {name: replace(template, repository=repository,
                          digest=_digest(name, raw, texts)) for name, template in built.items()}


def _digest(name: str, raw: dict[str, dict], texts: dict[str, str]) -> str:
    """`sha256:<hex>` of the template's file text and those of the templates it extends, in turn."""
    chain = hashlib.sha256()
    while name in texts:
        chain.update(texts[name].encode("utf-8") + b"\0")
        name = raw[name].get("extends", "")
    return f"sha256:{chain.hexdigest()}"


def _build(name: str, raw: dict[str, dict], terms: tuple[Term, ...],
           seen: tuple[str, ...]) -> Template:
    data = raw[name]
    where = data["path"]
    unknown = set(data) - TEMPLATE_KEYS - {"path"}
    if unknown:
        raise TemplateError(f"{where}: unknown keys {', '.join(sorted(unknown))}; the template file format "
                        "is scripts/templates.py's docstring")
    parent: Template | None = None
    if "extends" in data:
        base = data["extends"]
        if base in seen or base == name:
            raise TemplateError(f"{where}: extends {base!r} in a cycle ({' -> '.join((*seen, name))})")
        if base not in raw:
            raise TemplateError(f"{where}: extends {base!r}, which is no template in {TEMPLATES}/")
        parent = _build(base, raw, terms, (*seen, name))
    applies = data.get("applies")
    if isinstance(applies, dict) and set(applies) - APPLIES_KEYS:
        raise TemplateError(f"{where}: applies has unknown keys "
                        f"{', '.join(sorted(set(applies) - APPLIES_KEYS))}; the keys are "
                        f"{', '.join(sorted(APPLIES_KEYS))}")
    if not isinstance(applies, dict) or not applies.get("actions"):
        if parent is None:
            raise TemplateError(f"{where}: applies.actions is required; name the actions the template "
                            f"shapes ({', '.join(ACTIONS)})")
        applies = {"actions": list(parent.actions), **(applies or {})}
    actions = tuple(applies["actions"])
    for action in actions:
        if action not in ACTIONS:
            raise TemplateError(f"{where}: action {action!r} is none of {', '.join(ACTIONS)}")
    version, kind, tags = data.get("version"), data.get("kind"), data.get("tags")
    if not isinstance(version, str) or not SEMVER.match(version):
        raise TemplateError(f"{where}: version is {version!r}; write the template's semantic version, "
                            "such as 1.2.0")
    if kind not in TEMPLATE_KINDS:
        raise TemplateError(f"{where}: kind is {kind!r}; one of {', '.join(TEMPLATE_KINDS)}")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise TemplateError(f"{where}: tags is a list of words, the template's link to guidance, "
                            "such as [\"issue\"]")
    reader = data.get("reader", parent.reader if parent else "")
    if reader not in READERS:
        raise TemplateError(f"{where}: reader {reader!r} is none of {', '.join(READERS)}")
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
            raise TemplateError(f"{where}: order must list every field once: "
                            f"{', '.join(names)}")
        fields.sort(key=lambda item: order.index(item.name))
    rules = {**(parent.rules if parent else {}), **data.get("rules", {})}
    for rule, severity in rules.items():
        if rule not in REFUSE_RULES + WARN_RULES:
            raise TemplateError(f"{where}: rule {rule!r} is unknown; the rules are "
                            f"{', '.join(REFUSE_RULES + WARN_RULES)}")
        if severity not in (REFUSE, WARN, OFF):
            raise TemplateError(f"{where}: rule {rule} is {severity!r}; mark it refuse, warn or off")
        if rule in WARN_RULES and severity == REFUSE:
            raise TemplateError(f"{where}: rule {rule} only warns, never refuses; mark it warn")
    example = data.get("example", {})
    adapter = _adapter(data, where, fields, parent)
    base_branch = str(applies.get("base", parent.base if parent else ""))
    if base_branch not in ("", "integration"):
        raise TemplateError(f"{where}: applies.base is {base_branch!r}; the one base is "
                        "\"integration\", the integration branch")
    paths = applies.get("paths", list(parent.paths) if parent else [])
    if not isinstance(paths, list) or not all(isinstance(glob, str) and glob.strip()
                                              for glob in paths):
        raise TemplateError(f"{where}: applies.paths is a list of globs relative to the project "
                        "root, such as \"book/*/steps/*.md\"")
    if paths and set(actions) != {FILE_ACTION}:
        raise TemplateError(f"{where}: applies.paths claims files and goes only with "
                        f"actions: [\"{FILE_ACTION}\"]; take out paths, or the other actions")
    if FILE_ACTION in actions and not paths:
        raise TemplateError(f"{where}: action {FILE_ACTION} needs applies.paths, the globs of the "
                        "files the template claims")
    marker_pattern = str(applies.get("marker_pattern", ""))
    try:
        re.compile(marker_pattern)
    except re.error as error:
        raise TemplateError(f"{where}: applies.marker_pattern is no regular expression "
                        f"({error})") from error
    return Template(
        name=name, version=version, kind=kind, tags=tuple(tags), reader=reader, says=str(data.get("says", parent.says if parent else "")),
        actions=actions, fields=tuple(fields), rules=rules,
        order=int(applies.get("order", parent.order if parent else 100)),
        marker=str(applies.get("marker", "")), title_pattern=str(applies.get("title", "")),
        keep_unknown=bool(data.get("keep_unknown", parent.keep_unknown if parent else True)),
        actors=tuple(data.get("actors", parent.actors if parent else ())),
        example=example if example else {}, scope=dict(data.get("scope", {})),
        terms=terms, path=where, marker_pattern=marker_pattern,
        labels=tuple(str(label) for label in applies.get("labels", parent.labels if parent else ())),
        base=base_branch, fallback=bool(applies.get("fallback", False)),
        checker=str(data.get("checker", "")), adapter=adapter,
        paths=tuple(glob.strip().strip("/") for glob in paths))


def glob_pattern(glob: str) -> re.Pattern:
    """A path glob as a pattern of a whole `/`-separated path: `*` and `?` within one folder,
    `**` across folders (`**/` also none)."""
    out, index = [], 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:[^/]*/)*")
            index += 3
        elif glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out))


def _adapter(data: dict, where: str, fields: list[Field], parent: Template | None) -> dict:
    """An adapter's `adapter` mapping, checked as far as it can be without importing its
    checker; a template with fields takes none."""
    adapter = data.get("adapter", {})
    if fields:
        if "checker" in data or adapter:
            raise TemplateError(f"{where}: a template with fields takes no checker or adapter; an "
                            "adapter is a template without fields")
        return {}
    if parent is not None:
        raise TemplateError(f"{where}: an adapter extends no template")
    if not isinstance(adapter, dict) or set(adapter) - ADAPTER_KEYS:
        extra = sorted(set(adapter) - ADAPTER_KEYS) if isinstance(adapter, dict) else ["?"]
        raise TemplateError(f"{where}: adapter has unknown keys {', '.join(extra)}; the keys are "
                        f"{', '.join(sorted(ADAPTER_KEYS))} (scripts/templates.py's docstring)")
    references = [data.get("checker", ""), adapter.get("extract", ""), adapter.get("when", ""),
                  adapter.get("title_rule", "")]
    for reference in references:
        if reference and not REFERENCE.match(str(reference)):
            raise TemplateError(f"{where}: {reference!r} is no \"<module>:<name>\" of a script "
                            "beside scripts/templates.py")
    if adapter.get("result", "problems") not in RESULTS:
        raise TemplateError(f"{where}: adapter.result is {adapter.get('result')!r}; one of "
                        f"{', '.join(RESULTS)}")
    if adapter.get("missing", REFUSE) not in (REFUSE, WARN, "pass"):
        raise TemplateError(f"{where}: adapter.missing is {adapter.get('missing')!r}; one of "
                        "refuse, warn, pass")
    if adapter.get("result") == "truth" and not adapter.get("refusal"):
        raise TemplateError(f"{where}: adapter.result \"truth\" needs its refusal, the fix a "
                        "false answer gives")
    for line in adapter.get("lines", []):
        if set(line) - {"pattern", "first", "says"} or not line.get("pattern") or \
                not line.get("says"):
            raise TemplateError(f"{where}: each item of adapter.lines has a pattern and says, and may "
                            "set first")
        try:
            re.compile(line["pattern"])
        except re.error as error:
            raise TemplateError(f"{where}: adapter.lines pattern {line['pattern']!r} is no "
                            f"regular expression ({error})") from error
    return dict(adapter)


def _field(entry: dict, where: str) -> Field:
    unknown = set(entry) - FIELD_KEYS
    name = entry.get("name", "?")
    if unknown:
        raise TemplateError(f"{where}: field {name} has unknown keys {', '.join(sorted(unknown))}")
    if entry.get("kind") not in KINDS:
        raise TemplateError(f"{where}: field {name} has kind {entry.get('kind')!r}; one of "
                        f"{', '.join(KINDS)}")
    choices: list[str] = []
    for choice in entry.get("choices", ()):
        if REFERENCE.match(str(choice)):
            named = _named(str(choice), where, f"field {name} choices")
            if isinstance(named, dict):
                named = list(named)
            if not isinstance(named, (list, tuple, set, frozenset)):
                raise TemplateError(f"{where}: field {name} choices: {choice} is no list or mapping; "
                                "name one whose items or keys are the choices")
            choices += [str(item) for item in named]
        else:
            choices.append(str(choice))
    shape = str(entry.get("shape", ""))
    rule = None
    if REFERENCE.match(shape):
        rule = _named(shape, where, f"field {name} shape")
        if not isinstance(rule, re.Pattern) and not callable(rule):
            raise TemplateError(f"{where}: field {name} shape: {shape} is no pattern or function; "
                            "name a compiled pattern or a function that gives the warning")
    chars = entry.get("first_sentence_chars", 0)
    if type(chars) is not int or chars < 0:
        raise TemplateError(f"{where}: field {name} first_sentence_chars is {chars!r}; write a whole "
                        "number, 0 for none")
    made = Field(**{**entry, "choices": tuple(dict.fromkeys(choices))}, rule=rule)
    if made.in_body and not made.heading:
        raise TemplateError(f"{where}: field {name} needs a heading (or source = \"title\", or a label)")
    if made.kind == "choice" and not made.choices:
        raise TemplateError(f"{where}: field {name} is a choice without choices")
    return made


def _named(reference: str, where: str, key: str):
    """What `"<module>:<NAME>"` names in a script beside this one, refused where it does not
    resolve, naming the template file and the key."""
    module, name = reference.split(":", 1)
    try:
        return getattr(_sibling(module), name)
    except (ImportError, AttributeError, OSError) as error:
        raise TemplateError(f"{where}: {key}: {reference} does not resolve ({error}); name a script "
                        "beside scripts/templates.py and what it defines") from error


# Reading


def _norm(heading: str) -> str:
    return " ".join(heading.strip().rstrip(":").strip().casefold().split())


def _matches(item: Field, line: str, level: int, base: int, own: int) -> bool:
    """Whether heading `line` (at `level`, below `base`) names `item`; `own` is the template's level."""
    if item.exact_heading:
        return line.rstrip() == f"{'#' * own} {item.heading}"
    if level <= base:
        return False
    match = HEADING.match(line)
    name, want = _norm(match.group(2)), _norm(item.heading)
    return name == want or name.startswith(want + " (")


def _split(text: str, template: Template, base: int) -> tuple[str, list[Part]]:
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
            found = next((item for item in template.fields if item.in_body and item.name not in seen
                          and _matches(item, bare, level, base, template.level)), None)
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
    if not_in_input(text):
        return text.strip()
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


def parse(template: Template, body: str, title: str | None = None) -> Document:
    """`body` read into `template`'s fields (the module docstring: reading)."""
    if template.is_adapter:  # the body as it stands: its own check reads it
        fields = {} if title is None else {"title": title}
        return Document(template=template.name, fields=fields, source=body, read=dict(fields))
    if template.is_file:
        return _parse_file(template, body)
    text = FRONT_MATTER.sub("", body, count=1)
    document = Document(template=template.name, fields={}, source=text,
                        recorded=marked_version(template, body))
    if template.scope:
        parts, region = _scoped(template, text)
    else:
        region = text
        preamble, sections = _split(text, template, 0)
        parts = [Part("preamble", raw=preamble), *sections]
    document.parts = parts
    preamble = next((part.raw for part in parts if part.kind == "preamble"), "")
    for item in template.fields:
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
            document.fields[part.name] = value_of(template.field(part.name), part.raw)
    document.read = dict(document.fields)
    for item in template.fields:
        if item.in_body and item.name not in document.fields:
            near = next((line for line in region.splitlines() if (match := HEADING.match(line))
                         and _norm(match.group(2)) == _norm(item.heading)), None)
            if near is not None:
                document.misses[item.name] = near
    document.source = region
    return document


def _title_end(template: Template, text: str) -> int:
    """Where a file's head ends: just after its page title, the first `#` line above the first
    field; 0 where a field's heading comes first or there is no `#` line."""
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        marker = FENCE.match(bare)
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None:
            if marker and marker.group(1).startswith(fence):
                fence = None
        elif heading := HEADING.match(bare):
            level = len(heading.group(1))
            if level == 1:
                return offset + len(line)
            if any(item.in_body and _matches(item, bare, level, 0, template.level)
                   for item in template.fields):
                return 0
        offset += len(line)
    return 0


def _parse_file(template: Template, body: str) -> Document:
    """A claimed file read into `template`'s fields: its front matter and its page title are its
    head, kept as they stand and never a field (the module docstring: Files)."""
    front = FRONT_MATTER.match(body)
    head = front.group(0) if front else ""
    rest = body[len(head):]
    end = _title_end(template, rest)
    title, rest = rest[:end], rest[end:]
    preamble, sections = _split(rest, template, 0)
    document = Document(template=template.name, fields={}, source=rest,
                        parts=[Part("front", raw=head), Part("head", raw=title),
                               Part("preamble", raw=preamble), *sections],
                        recorded=front_version(template, head))
    for part in sections:
        if part.kind == "field":
            document.fields[part.name] = value_of(template.field(part.name), part.raw)
    document.read = dict(document.fields)
    for item in template.fields:
        if item.in_body and item.name not in document.fields:
            near = next((line for line in rest.splitlines() if (match := HEADING.match(line))
                         and _norm(match.group(2)) == _norm(item.heading)), None)
            if near is not None:
                document.misses[item.name] = near
    return document


def front_matter_template(body: str) -> str | None:
    """The template a file's front matter names on its `template:` line, or None."""
    front = FRONT_MATTER.match(body)
    found = FRONT_TEMPLATE.search(front.group(0)) if front else None
    return found.group(1) if found else None


def _front_key(key: str) -> re.Pattern:
    """A front matter line of `key`, its value the first group, unquoted."""
    return re.compile(rf"^{key}[ \t]*:[ \t]*['\"]?([^'\"\r\n]*?)['\"]?[ \t]*$", re.MULTILINE)


def front_version(template: Template, front: str) -> str:
    """The version front matter `front` records for `template`: its `version:` line, read only where
    its `template:` line names `template`, else ""."""
    if not front or FRONT_TEMPLATE.search(front) is None or \
            FRONT_TEMPLATE.search(front).group(1) != template.name:
        return ""
    found = _front_key("version").search(front)
    return found.group(1).strip() if found else ""


def marked_version(template: Template, body: str) -> str:
    """The version the body's template marker naming `template` records, else ""."""
    for match in TEMPLATE_MARKER_PATTERN.finditer(body):
        if match.group(1) == template.name:
            return match.group(0).split()[3]
    return ""


def _with_template(front: str, template: Template) -> str:
    """Front matter `front` recording `template` (`Template.front_lines`), every other byte kept: a
    line of the three already there is written in its place, a missing one after the last of them,
    else before the closing `---`; a new block where `front` is empty."""
    lines = template.front_lines
    if not front:
        return "---\n" + "".join(f"{key}: {value}\n" for key, value in lines) + "---\n\n"
    newline = "\r\n" if "\r\n" in front else "\n"
    after = None  # just after the last of the three written so far
    for key, value in lines:
        closing = front.rstrip("\r\n").rfind("\n") + 1
        line = f"{key}: {value}"
        found = (FRONT_TEMPLATE if key == "template" else _front_key(key)).search(front, 0, closing)
        if found:
            front = front[:found.start()] + line + front[found.end():]
            after = found.start() + len(line) + len(newline)
        else:
            at = closing if after is None else after
            front = front[:at] + line + newline + front[at:]
            after = at + len(line) + len(newline)
    return front


def _scoped(template: Template, text: str) -> tuple[list[Part], str]:
    """A scoped template's parts: the data above its marker, then its section's own parts."""
    after = template.scope.get("after", "")
    lines = text.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.strip() == after), None)
    if index is None:
        return [Part("prefix", raw=text)], ""
    prefix = "".join(lines[:index + 1])
    rest = lines[index + 1:]
    want = _norm(template.scope.get("section", ""))
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
    preamble, sections = _split(region, template, template.level - 1)
    return [Part("prefix", raw=prefix), Part("gap", raw="".join(rest[:start])),
            Part("scope", heading=rest[start].rstrip("\r\n")), Part("preamble", raw=preamble),
            *sections, Part("suffix", raw="".join(rest[end:]))], "".join(rest[start:end])


# Writing


def _format(item: Field, value: object, first: int) -> str:
    """A field's value as Markdown; `first` is the number a numbered list starts at."""
    if item.verbatim or item.kind in ("line", "choice", "text") or (
            isinstance(value, str) and not_in_input(value)):
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
            if line.strip() != FLEET_MARKER and not TEMPLATE_MARKER_PATTERN.match(line.rstrip("\r\n"))]
    return "".join(kept)


def render(template: Template, document: Document | dict) -> str:
    """Canonical Markdown of `document` (a parsed Document, or a mapping of field values), as the
    module docstring's "Writing" says."""
    if template.is_adapter:
        if not isinstance(document, Document):
            raise TemplateError(f"templates: {template.name} is an adapter and has no fields to render; the "
                            "command that writes it writes its body")
        return document.source  # never marked: the adapter's own writer owns its text
    if not isinstance(document, Document):
        document = Document(template=template.name, fields=answer(template, document))
    values = document.fields
    marker = template.marker_line
    hashes = "#" * template.level
    parts = list(document.parts)
    if template.scope and not any(part.kind == "scope" for part in parts):
        data = "".join(part.raw for part in parts if part.kind in ("prefix", "gap"))
        if template.scope.get("after", "") in data.splitlines():  # the marker without its section
            data = "\n".join(line for line in data.splitlines()
                             if line.strip() != template.scope.get("after", ""))
        parts = [*([Part("data", raw=_end(data))] if data.strip() else []),
                 Part("prefix", raw=template.scope.get("after", "") + "\n"), Part("gap"),
                 Part("scope", heading=f"## {template.scope.get('section', '')}"),
                 Part("preamble"), Part("suffix")]
    elif not parts:
        parts = [Part("front"), Part("head"), Part("preamble")] if template.is_file else \
            [Part("preamble")]
    # Fields with a value but no section yet go after the nearest earlier field that has one.
    placed = {part.name for part in parts if part.kind == "field"}
    for item in template.fields:
        if not item.in_body or item.name in placed or values.get(item.name) in (None, "", [], {}):
            continue
        names = [other.name for other in template.fields]
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
        if part.kind == "front":
            out.append(_with_template(part.raw, template))
        elif part.kind == "head":
            out.append(_without_markers(part.raw))
        elif part.kind == "prefix":
            out.append(_end(part.raw) if part.raw else "")
            out.append(marker + "\n")
        elif part.kind == "gap":
            out.append(_without_markers(part.raw))
        elif part.kind == "scope":
            out.append(part.heading + "\n")
        elif part.kind == "preamble":
            preamble = _labels(template, document, _without_markers(part.raw))
            if template.is_file:
                out.append(preamble)
            elif not template.scope:
                out.append(f"{FLEET_MARKER}\n{marker}\n")
                preamble = preamble.lstrip("\n")
                out.append("\n" + _end(preamble) if preamble.strip() else "\n")
            else:
                out.append(preamble if preamble.strip() else "\n")
        elif part.kind in ("suffix", "data"):
            out.append(part.raw + ("\n" if part.kind == "data" and part.raw.strip() else ""))
        elif part.kind == "unknown":
            if template.keep_unknown:
                out.append(part.heading + "\n" + part.raw)
        else:
            item = template.field(part.name)
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


def _labels(template: Template, document: Document, preamble: str) -> str:
    """The preamble with each label field's line as its value now."""
    for item in template.fields:
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


def draft(template: Template) -> str:
    """The empty template as Markdown, each field's `says` as a comment; an adapter's says what
    writes and checks it."""
    if template.is_adapter:
        return f"<!-- {template.name}: {template.says} -->\n<!-- {_checked_by(template)} -->\n"
    lines = []
    if template.is_file:
        lines += ["---", *(f"{key}: {value}" for key, value in template.front_lines), "---", ""]
    elif template.scope:
        lines += [template.scope.get("after", ""), template.marker_line,
                  f"## {template.scope.get('section', '')}", ""]
    else:
        lines += [FLEET_MARKER, template.marker_line, ""]
    hashes = "#" * template.level
    for item in template.fields:
        if item.source == "title":
            lines += [f"<!-- title: {item.says} -->", ""]
        elif item.label:
            lines += [f"{item.label}: <!-- {item.says} -->", ""]
    for item in template.fields:
        if item.in_body:
            lines += [f"{hashes} {item.heading}", "", f"<!-- {item.says} -->", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def draft_fields(template: Template) -> dict[str, object]:
    """The empty template as data: each field's empty value and its `says`, then each field's shape
    (`field_shape`) and the template's JSON Schema (`schema`)."""
    empty = {"list": [], "issue": [], "checklist": [], "object": {}}
    return {"template": template.name, "says": template.says,
            "fields": {item.name: empty.get(item.kind, "") for item in template.fields},
            "field_says": {item.name: item.says for item in template.fields},
            "field_shape": {item.name: field_shape(item) for item in template.fields},
            "schema": schema(template)}


#: The keys `field_shape` gives, each where the field sets it.
SHAPE_KEYS = ("kind", "heading", "required", "none_ok", "choices", "max_words",
              "first_sentence_chars", "numbered", "label", "source", "quote")
#: The only keywords `schema` writes: none that strict tool use on the Claude API refuses.
SCHEMA_KEYWORDS = ("$schema", "type", "properties", "required", "additionalProperties", "items",
                   "enum", "description")
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def field_shape(item: Field) -> dict[str, object]:
    """A field's shape as `draft --json` gives it: its kind, and each other key of SHAPE_KEYS
    where the field sets it (choices resolved as `load` resolved them, in their order)."""
    shape: dict[str, object] = {}
    for key in SHAPE_KEYS:
        value = getattr(item, key)
        if key == "kind" or value:
            shape[key] = list(value) if key == "choices" else value
    return shape


def _pairs(keys: tuple[str, ...]) -> dict[str, object]:
    """A closed object of string properties, every one required."""
    return {"type": "object", "properties": {key: {"type": "string"} for key in keys},
            "required": list(keys), "additionalProperties": False}


def _property(item: Field) -> dict[str, object]:
    """One field's property of `schema`, by its kind."""
    strings = {"type": "array", "items": {"type": "string"}}
    if item.kind == "choice":
        made: dict[str, object] = {"type": "string", "enum": [*item.choices, NOT_IN_INPUT]}
    elif item.kind in ("list", "issue"):
        made = strings
    elif item.kind == "checklist":
        made = {"type": "array", "items": {
            "type": "object", "properties": {"done": {"type": "boolean"},
                                             "text": {"type": "string"}},
            "required": ["done", "text"], "additionalProperties": False}}
    elif item.kind == "object":  # pairs, as strict mode takes no open mapping
        made = {"type": "array", "items": _pairs(("key", "value"))}
    else:  # line, text and code
        made = {"type": "string"}
    return {**made, "description": item.says}


def schema(template: Template) -> dict[str, object]:
    """A JSON Schema 2020-12 of `template`'s fields, written with SCHEMA_KEYWORDS alone, so it can be
    handed to a model as it is; an adapter's has no property."""
    return {"$schema": SCHEMA_DIALECT, "type": "object",
            "properties": {item.name: _property(item) for item in template.fields},
            "required": [item.name for item in template.fields if item.required],
            "additionalProperties": False}


def answer(template: Template, values: dict[str, object]) -> dict[str, object]:
    """Field values as `render` takes them: an object field given as the schema's list of
    `{"key", "value"}` pairs becomes the mapping of today."""
    given = dict(values)
    for item in template.fields:
        value = given.get(item.name)
        if item.kind == "object" and isinstance(value, list) and all(
                isinstance(pair, dict) and set(pair) == {"key", "value"} for pair in value):
            given[item.name] = {str(pair["key"]): str(pair["value"]) for pair in value}
    return given


def _checked_by(template: Template) -> str:
    """What checks an adapter: its checker, its title rule and its lines."""
    parts = [f"checker {template.checker or 'none'}"]
    if template.adapter.get("title_rule"):
        parts.append(f"title {template.adapter['title_rule']}")
    if template.adapter.get("lines"):
        parts.append(f"{len(template.adapter['lines'])} lines")
    return ", ".join(parts) + ("" if len(parts) > 1 or template.checker else " (no field required)")


def list_templates(templates: dict[str, Template]) -> list[str]:
    """One line per template: its name, reader, actions, the paths it claims, an adapter's checker,
    and what it says."""
    return [f"{template.name} ({template.reader}): {', '.join(template.actions)}: "
            + (f"{', '.join(template.paths)}: " if template.paths else "")
            + (f"{_checked_by(template)}: " if template.is_adapter else "") + template.says
            for template in sorted(templates.values(), key=lambda item: (item.order, item.name))]


@dataclass(frozen=True)
class Selection:
    """What `select` chose: the template (None: free) and the refused markers it met."""
    template: Template | None
    findings: tuple[Finding, ...] = ()

    @property
    def name(self) -> str | None:
        return self.template.name if self.template else None


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
    """The repositories SE writes templates for: origin's, and each one se.toml `[outside]` lists."""
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


def _carries(template: Template, lines: set[str]) -> bool:
    """Whether the body's stripped `lines` hold `template`'s marker condition."""
    if template.marker and template.marker in lines:
        return True
    return bool(template.marker_pattern) and any(re.fullmatch(template.marker_pattern, line)
                                             for line in lines)


def _why_not(template: Template, action: str) -> str:
    if action not in template.actions:
        return (f"the {template.name} template does not apply to {action}: it shapes "
                f"{', '.join(template.actions)}")
    return (f"the {template.name} template does not apply here: it needs the labels "
            f"{', '.join(template.labels) or 'none'}"
            + (" and a pull request into the integration branch" if template.base else ""))


def select(templates: dict[str, Template], action: str, body: str, title: str | None = None, *,
           labels=(), base: str | None = None, integration: str = "main",
           repo: str | None = None, home=None, path: str | None = None) -> Selection:
    """The template that shapes `body` for `action`, in the order the module docstring's
    "Selection" gives; its template None is free. For `file.write`, `path` is the file's,
    relative to the project root."""
    if action not in ACTIONS:
        raise TemplateError(f"select: action {action!r} is none of {', '.join(ACTIONS)}")
    if action == FILE_ACTION:
        if path is None:
            raise TemplateError(f"select: {FILE_ACTION} selects by the file's path; give path")
        return _select_file(templates, body, title, path)
    if repo is not None and home is not None and not _at_home(repo, home):
        return Selection(None)
    have = {str(label).casefold() for label in labels}

    def allowed(template: Template) -> bool:
        return (action in template.actions
                and all(label.casefold() in have for label in template.labels)
                and (not template.base or base == integration))

    candidates = sorted((template for template in templates.values() if allowed(template)),
                        key=lambda template: (template.order, template.name))
    lines = {line.strip() for line in body.splitlines()}
    refused: list[Finding] = []
    marked = {match.group(1): match.group(0).strip() for match in TEMPLATE_MARKER_PATTERN.finditer(body)}
    for named, line in marked.items():
        if named in templates and templates[named] not in candidates:
            refused.append(Finding("body", "template", REFUSE, _why_not(templates[named], action)
                                   + f"; take out `{line}`"))
    for template in sorted(templates.values(), key=lambda item: item.name):
        if template.is_adapter and template not in candidates and _carries(template, lines):
            refused.append(Finding("body", "template", REFUSE, _why_not(template, action)
                                   + ", and the body carries its marker"))
    named = next((template for template in candidates for name in TEMPLATE_MARKER_PATTERN.findall(body)
                  if template.name == name), None)
    if named is not None:
        return Selection(named, tuple(refused))
    for template in candidates:
        if not template.marker and not template.marker_pattern and not template.title_pattern:
            continue
        if (template.marker or template.marker_pattern) and not _carries(template, lines):
            continue
        if template.title_pattern and not re.search(template.title_pattern, title or ""):
            continue
        return Selection(template, tuple(refused))
    plain = next((template for template in candidates if template.fallback or (
        not template.marker and not template.marker_pattern and not template.title_pattern)), None)
    return Selection(plain, tuple(refused))


def _select_file(templates: dict[str, Template], body: str, title: str | None, path: str) -> Selection:
    """The template that claims the file at `path` (the module docstring: Selection, for a file)."""
    path = path.replace("\\", "/").strip("/")
    candidates = sorted((template for template in templates.values() if FILE_ACTION in template.actions
                         and template.claims(path)), key=lambda template: (template.order, template.name))
    if not candidates:
        return Selection(None)
    names = ", ".join(template.name for template in candidates)
    refused: list[Finding] = []
    named = front_matter_template(body)
    if named is not None:
        chosen = next((template for template in candidates if template.name == named), None)
        if chosen is not None:
            return Selection(chosen)
        refused.append(Finding("body", "template", REFUSE, f"{path}: the front matter names "
                               f"template: {named}, which does not claim this file; name one of "
                               f"{names}"))
    lines = {line.strip() for line in body.splitlines()}
    for template in candidates:
        if not template.marker and not template.marker_pattern and not template.title_pattern:
            continue
        if (template.marker or template.marker_pattern) and not _carries(template, lines):
            continue
        if template.title_pattern and not re.search(template.title_pattern, title or ""):
            continue
        return Selection(template, tuple(refused))
    refused.append(Finding("body", "template", REFUSE, f"{path}: no template takes this file; name its "
                           f"template in the front matter, template: <name> (one of {names})"))
    return Selection(None, tuple(refused))


def verdict(templates: dict[str, Template], action: str, body: str, title: str | None = None,
            **where) -> tuple[Template | None, list[Finding]]:
    """The template `select` takes for `body` and every finding: its refused markers, then the
    template's check; (None, the refused markers) where the body is free."""
    chosen = select(templates, action, body, title, **where)
    found = list(chosen.findings)
    if chosen.template is not None:
        found += check(chosen.template, parse(chosen.template, body, title))
    return chosen.template, found


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


def not_in_input(value: object) -> bool:
    """Whether `value` is NOT_IN_INPUT, in any form a kind gives it: the text alone, a list of that
    one item or one checklist entry, or an object of that one key without a value; case, a closing
    period or colon and comments aside."""
    if isinstance(value, dict):
        return len(value) == 1 and not_in_input(next(iter(value))) and not str(
            next(iter(value.values())) or "").strip()
    if isinstance(value, list):
        entries = [entry for entry in value if not WHOLE_COMMENT.match(str(entry))]
        return len(entries) == 1 and not_in_input(
            entries[0].get("text", "") if isinstance(entries[0], dict) else entries[0])
    return isinstance(value, str) and _squash(value).rstrip(".:").strip() == NOT_IN_INPUT.casefold()


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


def first_sentence(text: str) -> str:
    """The first sentence of `text` as `work_tickets.goal_summary` takes a Goal's: HTML comments
    dropped, a list's lead-in where the text opens with one, up to the first ".", "!" or "?"
    before a space, its whitespace joined."""
    text = COMMENT.sub("", text)
    lead = LIST_START.split("\n" + text.strip(), maxsplit=1)[0]
    text = " ".join((lead if lead.strip() else text).split())
    return FIRST_SENTENCE_END.split(text, maxsplit=1)[0]


def quotes(text: str) -> list[str]:
    """The quotes of `text`, in order: each span in double quotes ("..." or “...”) on one line, and
    each run of `>` lines as one quote, its lines joined by a space; comments dropped."""
    text = COMMENT.sub("", text)
    found: list[str] = []
    run: list[str] = []
    for line in [*text.splitlines(), ""]:
        quoted = QUOTE_LINE.match(line)
        if quoted:
            run.append(quoted.group(1))
            continue
        if run and " ".join(run).strip():
            found.append(" ".join(" ".join(run).split()))
        run = []
        found += [" ".join((match.group(1) or match.group(2)).split())
                  for match in QUOTE_SPANS.finditer(line)]
    return [quote for quote in found if quote]


def quoted(item: Field, text: str, raw: str | None) -> list[str]:
    """The fixes of a `quote` field's value `text` against the raw input (rule `quote`): it quotes
    nothing; or, where `raw` is given, a quote the raw input does not hold word for word, whitespace
    and line breaks aside, case counting."""
    found = quotes(text)
    heading = item.heading or item.name
    if not found:
        return [f"{heading} quotes nothing: quote the raw input word for word, in \"...\" or as a "
                f"`>` line (or write `{NOT_IN_INPUT}` where the input does not say)"]
    if raw is None:
        return []
    held = " ".join(COMMENT.sub("", raw).split())
    return [f"{heading} quotes \"{quote}\", which the raw input does not hold: quote it word for word, "
            f"or drop the quote" for quote in found if quote not in held]


def _entries(value: object) -> list[str]:
    if isinstance(value, list):
        return [entry.get("text", "") if isinstance(entry, dict) else str(entry)
                for entry in value if not WHOLE_COMMENT.match(str(entry))]
    return [line for line in str(value or "").splitlines() if line.strip()]


def check(template: Template, document: Document, *, root: Path = ROOT,
          bare_scripts: bool = True, raw: str | None = None) -> list[Finding]:
    """Every finding of `document` against `template`, refusals first, in field order; an adapter's
    are its own check's. `raw`, the raw input a fill takes, is what a `quote` field's quotes must
    hold (`quoted`); without it a quote field must only quote."""
    if template.is_adapter:
        return adapter_findings(template, document)
    found: list[Finding] = provenance(template, document)

    def add(rule: str, item: str, fix: str) -> None:
        severity = template.severity(rule)
        if severity != OFF:
            found.append(Finding(item, rule, severity, fix))

    values = document.fields
    filled: dict[str, object] = {}
    hashes = "#" * template.level
    for item in template.fields:
        if item.source == "title" and item.name not in values:
            continue  # no title given: the body alone is checked
        value = values.get(item.name)
        if not_in_input(value):
            continue  # every field takes it, whatever its rules: the gap shows
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
                f"{item.says} (or `{NOT_IN_INPUT}` where the input does not say)")
            continue
        if why:
            continue
        filled[item.name] = value
        text = _plain(value)
        if item.quote:
            found += [Finding(item.name, QUOTE_RULE, REFUSE, fix) for fix in quoted(item, text, raw)]
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
        if item.first_sentence_chars:
            chars = len(first_sentence(text))
            if chars > item.first_sentence_chars:
                add("first-sentence", item.name, f"{item.heading}'s first sentence has {chars} "
                    f"characters; keep it to {item.first_sentence_chars}, one complete statement: "
                    "it becomes the landing title")
        if item.actor and template.actors:
            names = [re.compile(rf"\b{re.escape(actor)}\b", re.IGNORECASE) for actor in template.actors]
            for number, entry in enumerate(_entries(value), 1):
                if not any(name.search(entry) for name in names):
                    add("actor", item.name, f"{item.heading} item {number} names nobody: say who "
                        f"does it ({', '.join(template.actors)})")
        if item.one_sentence:
            for number, entry in enumerate(_entries(value), 1):
                if SENTENCE_END.search(_prose(entry)):
                    add("one-sentence", item.name, f"{item.heading} item {number} has more than "
                        "one sentence: one sentence per step")
        if item.kind == "issue":
            for entry in _entries(value):
                if BARE_ISSUE.match(entry.strip()):
                    add("unnamed-entry", item.name, f"{item.heading} entry {entry.strip()} has no "
                        "name: add what it is, `#12 the templates engine`")
        if item.kind not in ("issue", "code") and item.source != "title":
            if BARE_NUMBER.search(_prose(text)):
                add("bare-number", item.name, f"{item.heading} names an issue by its number "
                    "alone: link it or name it in words")
            if BOARD.search(text):
                add("board", item.name, f"{item.heading} repeats the board (Status, Labels, "
                    "Priority, Assignee, Milestone): leave those to the tracker")
            if not item.verbatim:
                prose = _prose(COMMENT.sub("", text))
                for term in template.terms:
                    if re.search(rf"\b{re.escape(term.term)}\b", prose, re.IGNORECASE):
                        add("terms", item.name, f"{item.heading} uses the inside term "
                            f"{term.term!r}: say {term.plain}")
        if item.source == "title":
            _title(template, item, text, document, add)
    seen: dict[str, str] = {}
    for item in template.fields:
        if item.name not in filled or item.source == "title":
            continue
        key = _squash(_plain(filled[item.name]))
        if key and key.rstrip(".") != NONE:
            if key in seen:
                add("duplicate", item.name, f"{item.heading} repeats {seen[key]} word for word: "
                    "say in each what only it says")
            else:
                seen[key] = template.field(item.name).heading or item.name
    if document.source:
        for finding in _sibling("references").dangling(document.source, root, paths=False,
                                                         created=True, bare_scripts=bare_scripts):
            add("dangling", _field_at(template, document, finding.line), f"{finding}: correct it, "
                "or say in Requirements that this issue adds it")
    order = {item.name: index for index, item in enumerate(template.fields)}
    return sorted(found, key=lambda finding: (finding.severity != REFUSE,
                                              order.get(finding.field, len(order))))


def provenance(template: Template, document: Document) -> list[Finding]:
    """The finding of the version `document` records against `template`'s own (rule `version`,
    docs/templates.md "The document"): none where it records none or the same; a minor or patch
    move warns; a major move, or a recorded version that is none, refuses, naming both versions and
    the fill that brings the document up."""
    recorded, current = document.recorded, template.version
    if not recorded or not current or recorded == current:
        return []
    named = f"the document records {template.name} {recorded}; the template is at {current}"
    where = "--path <file>" if template.is_file else template.name
    given = "" if template.is_file else " --body-file <file>"
    if SEMVER.match(recorded) and recorded.split(".")[0] == current.split(".")[0]:
        return [Finding("template", VERSION_RULE, WARN, f"{named}, another minor or patch version: "
                        f"render it again to record {current}: `templates.py check {where}{given} "
                        "--render`")]
    why = (f"and {recorded} is no semantic version" if not SEMVER.match(recorded) else
           "another major version, which the document no longer fits")
    return [Finding("template", VERSION_RULE, REFUSE, f"{named}, {why}: fill it again at {current}: "
                    f"`templates.py draft {where} --json` gives its fields, and `templates.py check "
                    f"{where} --fields <fields> --render` writes it")]


class _Refused(Exception):
    """What an adapter's reading of a body refuses: its message is the finding's fix."""


#: The errors that mean an adapter is written wrong, never that the text is: they stop the check.
_MISCONFIGURED = (TypeError, AttributeError, NameError, ImportError, KeyError)


def resolve(reference: str, template: Template):
    """`"<module>:<name>"`, a function or a value of a script beside this one."""
    module, name = reference.split(":", 1)
    try:
        found = getattr(_sibling(module), name)
    except (ImportError, AttributeError, OSError) as error:
        raise TemplateError(f"{template.path}: {reference} does not resolve ({error}); name a script "
                        "beside scripts/templates.py and what it defines") from error
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


def adapter_findings(template: Template, document: Document) -> list[Finding]:
    """An adapter's findings: its lines, its title rule, then its checker's answer, called as
    `adapter` says (the module docstring: adapters)."""
    spec, body = template.adapter, document.source
    title = document.fields.get("title")
    found: list[Finding] = []

    def refuse(rule: str, fix: str, severity: str = REFUSE) -> None:
        found.append(Finding("body", rule, severity, f"{template.name}: {fix}"))

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
        rule = resolve(spec["title_rule"], template)
        rule = rule if isinstance(rule, re.Pattern) else re.compile(str(rule))
        if title is None or rule.match(title) is None:
            refuse("title", f"the title {title!r} does not match {rule.pattern!r} "
                   f"({spec['title_rule']})")
    if not template.checker:
        return found
    try:
        if spec.get("extract"):
            value = resolve(spec["extract"], template)(body, **dict(spec.get("extract_with", {})))
        elif spec.get("json_after"):
            value = _json_after(body, spec["json_after"])
        elif spec.get("sections"):
            value = _nodes(body)
        else:
            value = body
    except _MISCONFIGURED as error:
        raise TemplateError(f"{template.path}: its reading failed ({type(error).__name__}: {error}); "
                        "fix its adapter") from error
    except Exception as error:  # the extractor's own refusal, such as a QueueError
        refuse("checker", str(error))
        return found
    if value is None:
        missing = spec.get("missing", REFUSE)
        if missing != "pass":
            refuse("checker", f"the body holds nothing for {template.checker} to check"
                   + (f" (no {spec['json_after']} block)" if spec.get("json_after") else ""),
                   missing)
        return found
    value = _dropped(value, dict(spec.get("drop", {})))
    if spec.get("when") and not resolve(spec["when"], template)(value):
        return found
    keywords = {**dict(spec.get("with", {})), **{name: None for name in spec.get("none", [])}}
    if spec.get("title_as"):
        keywords[spec["title_as"]] = title or ""
    arguments = [] if spec.get("text_as") else [value]
    if spec.get("text_as"):
        keywords[spec["text_as"]] = value
    checker = resolve(template.checker, template)
    result = spec.get("result", "problems")
    try:
        answer = checker(*arguments, **keywords)
    except _MISCONFIGURED as error:
        raise TemplateError(f"{template.path}: {template.checker} failed ({type(error).__name__}: {error}); "
                        "fix its adapter") from error
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


def _title(template: Template, item: Field, title: str, document: Document, add) -> None:
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


def _field_at(template: Template, document: Document, line: int) -> str:
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


#: se.toml `[templates] enforce`: the values the filing commands know, `off` the default.
ENFORCE_VALUES = (OFF, WARN, REFUSE)
#: se.toml `[templates] gate`: the values SE's template gate on GitHub writes knows (se_templates.py gate),
#: `off` the default.
GATE_VALUES = (OFF, WARN, REFUSE)
#: se.toml `[templates] files`: whether SE's checks before work is done check the files a template claims
#: (se_templates.py check-files), and with `write` also the gate at each write; `off` the default.
CHECK, WRITE = "check", "write"
FILES_VALUES = (OFF, CHECK, WRITE)
#: se.toml `[templates] refusals`: how many refusals of one issue open `--hold`.
DEFAULT_REFUSALS = 2
PRIVATE_RULE = "private"
REFUSAL_LINES = 10
ALSO = "Also (does not block):"


@dataclass(frozen=True)
class Enforcement:
    """se.toml `[templates]` as the filing commands read it, and where it was read."""
    enforce: str = OFF
    refusals: int = DEFAULT_REFUSALS
    where: str = "se.toml"
    gate: str = OFF
    files: str = OFF


def enforcement(root: Path) -> Enforcement:
    """`[templates]` of `root`'s se.toml at `origin/<integration branch>` through git_door, so a branch
    cannot switch its own check off; the working tree's only where that ref does not exist. A value
    outside the switch's set is a TemplateError naming the file."""
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
        table = tomllib.loads(text).get("templates", {})
    except tomllib.TOMLDecodeError as error:
        raise TemplateError(f"templates: {where} is no TOML ({error}); fix it") from error
    if not isinstance(table, dict):
        raise TemplateError(f"templates: [templates] in {where} must be a table")
    enforce = table.get("enforce", OFF)
    if enforce not in ENFORCE_VALUES:
        raise TemplateError(f"templates: [templates] enforce = {enforce!r} in {where} is none of "
                        f"{', '.join(ENFORCE_VALUES)}; set one of them (README \"Templates\")")
    gate = table.get("gate", OFF)
    if gate not in GATE_VALUES:
        raise TemplateError(f"templates: [templates] gate = {gate!r} in {where} is none of "
                        f"{', '.join(GATE_VALUES)}; set one of them (README \"Templates\")")
    files = table.get("files", OFF)
    if files not in FILES_VALUES:
        raise TemplateError(f"templates: [templates] files = {files!r} in {where} is none of "
                        f"{', '.join(FILES_VALUES)}; set one of them (README \"Templates\")")
    refusals = table.get("refusals", DEFAULT_REFUSALS)
    if isinstance(refusals, bool) or not isinstance(refusals, int) or refusals < 1:
        raise TemplateError(f"templates: [templates] refusals = {refusals!r} in {where} must be a whole "
                        "number of at least 1")
    return Enforcement(enforce, refusals, where, gate, files)


def filled(template: Template, *, body: str | None = None, fields: dict | None = None,
           enforce: str = OFF) -> str:
    """The body a filing command files: `fields` always rendered through `render`; `body` as it
    stands with `enforce` off, else parsed and rendered again, its unknown sections kept."""
    if fields is not None:
        return render(template, fields)
    if body is None:
        raise TemplateError("templates: give a body or fields")
    if enforce == OFF or template.is_adapter:
        return body
    return render(template, parse(template, body))


def private_findings(template: Template, title: str, body: str, root: Path) -> list[Finding]:
    """A refused finding for every term of the lists `public_check.py` reads (its public list and
    the local list of `root` where it holds one) in the title or the body: each names the field and
    the list's label, never the term. A list that does not load is a TemplateError naming only its
    line."""
    check = _sibling("public_check")
    try:
        local = check.load_local(root)
    except check.SetupError as error:
        raise TemplateError(f"templates: {error}") from error
    lists = [("public", pattern) for pattern in check.GENERIC_PATTERNS
             if local is None or pattern.label not in local.off]
    lists += [("local", pattern) for pattern in (local.terms if local is not None else [])]
    document = parse(template, body, title) if not template.is_adapter else None
    found: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for where, text in (("title", title), ("body", body)):
        for line, _, label in check.find(text, [pattern for _, pattern in lists]):
            kind = next(name for name, pattern in lists if pattern.label == label)
            field_name = (where if where == "title" or document is None
                          else _field_at(template, document, line))
            key = (field_name, label)
            if key in seen:
                continue
            seen.add(key)
            line_of = label.split(":", 1)[-1]
            named = (f"the local list ({check.LOCAL_FILE} line {line_of})" if kind == "local"
                     else f"the public list ({label})")
            found.append(Finding(field_name, PRIVATE_RULE, REFUSE,
                                 f"holds a term of {named}: stop and ask the owner before "
                                 "anything is filed"))
    return found


def _heading(template: Template, name: str) -> str:
    item = template.field(name)
    return (item.heading or item.name) if item is not None else name


def _line(template: Template, finding: Finding) -> str:
    """A finding as `<field>: <what is wrong>: <the fix>`."""
    heading = _heading(template, finding.field)
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


def report(command: str, template: Template, findings: list[Finding], *, refused: bool,
           hold: str = "", scripts: Path = ROOT / "scripts", gate: bool = False) -> str:
    """The text a filing command prints for `findings` against `template`, at most REFUSAL_LINES
    lines: every refused finding with its fix, the warnings after ALSO, the `draft` command with
    the real path of SE's scripts and, with `hold` (the label it files with), the `--hold` way
    out. It never counts tries. With `gate` (se_templates.py gate, a write through the GitHub tools)
    its tail lines name the MCP door's templates tool before the `draft` command, and the hold names
    both ways out: the filing command with `--hold`, or the same issue write labelled `hold` and
    without `ready`."""
    refusing = [f"  {_line(template, item)}" for item in findings if item.severity == REFUSE]
    warning = [_line(template, item) for item in findings if item.severity != REFUSE]
    if refused:
        head = [f"{command}: the {template.name} template refuses this text; fix every finding and run "
                "it again:"]
        lines = refusing
        tail = [f"{ALSO} {'; '.join(warning)}"] if warning else []
    else:
        head = [f"{command}: the {template.name} template finds this ([templates] enforce = warn); filed "
                "anyway:"]
        lines = [f"  {_line(template, item)}" for item in findings]
        tail = []
    if gate:
        tail.append(f"Get the template: the se server's templates tool, command \"se_templates.py draft\", "
                    f"args [\"{template.name}\"] (or uv run python {scripts / 'templates.py'} draft "
                    f"{template.name} --json)")
    else:
        tail.append(f"The empty template: uv run python {scripts / 'templates.py'} draft {template.name}")
    if hold and gate:
        tail.append("Or file it with the filing command and --hold, or send the same issue write "
                    f"with the label {hold} and without ready; then fix its text on the issue "
                    "itself and run work_tickets.py unhold <issue>")
    elif hold:
        tail.append("Or run it again with --hold: it files the text as given, labelled "
                    f"{hold} and not ready; then fix its text on the issue itself and run "
                    "work_tickets.py unhold <issue>")
    return "\n".join(_fit(head, lines, tail))


def target(template: str, repo: str, action: str, *, number: int | None = None,
           title: str = "") -> str:
    """What one count of refusals is about: the template, the repository and the action, then the
    issue's number, or the normalised title of a new issue."""
    what = f"#{number}" if number is not None else " ".join(title.casefold().split())
    return f"{template}|{repo.casefold()}|{action}|{what}"


def counts_file(environ: dict[str, str] | None = None) -> Path:
    """The session's count of refusals: `~/.se/templates/<session>.json`, never inside a checkout.
    The session is the one the variables `ci_trust.SESSION_VARIABLES` name."""
    _sibling("git_door")
    name = _sibling("ci_trust").session(environ)
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".se" / "templates" / f"{digest}.json"


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


def fields_file(path: Path, command: str = "templates.py check") -> dict[str, object]:
    """The field values of a `--fields` file: an object of them, or `draft --json`'s answer."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TemplateError(f"{command}: --fields {path} is no JSON file ({error})") from error
    return fields_data(text, f"--fields {path}", command)


def fields_data(text: str, given: str, command: str = "templates.py check") -> dict[str, object]:
    """The field values of JSON `text` (`given` names where it came from): an object of them, or
    `draft --json`'s answer."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise TemplateError(f"{command}: {given} is no JSON ({error})") from error
    if isinstance(data, dict) and isinstance(data.get("fields"), dict):
        data = data["fields"]
    if not isinstance(data, dict):
        raise TemplateError(f"{command}: {given} must hold an object of field values")
    return data


def _template(templates: dict[str, Template], name: str) -> Template:
    if name not in templates:
        raise TemplateError(f"templates.py: no template {name!r}; the templates are {', '.join(sorted(templates))}")
    return templates[name]


def _root(path: Path, root: Path | None) -> Path:
    """The project root `path`'s globs are relative to: `--root`, else the git checkout holding
    the path, else the working directory."""
    if root is not None:
        return root
    for folder in path.resolve().parents:
        if (folder / ".git").exists():
            return folder
    return Path.cwd()


def _relative(path: Path, root: Path, command: str) -> str:
    """`path` relative to `root`, with `/`, as a template's `paths` match it."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise TemplateError(f"{command}: --path {path} is not under the project root {root}; give "
                        "--root, the folder the templates' paths are relative to") from error


def _file_text(path: Path, command: str, *, missing_ok: bool = False) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        if missing_ok:
            return ""
        raise TemplateError(f"{command}: cannot read --path {path} ({error})") from error
    except OSError as error:
        raise TemplateError(f"{command}: cannot read --path {path} ({error})") from error


def _claimed(templates: dict[str, Template], options: argparse.Namespace, command: str,
             body: str | None = None) -> tuple[str, Selection]:
    """The file `--path` names, relative to its root, and the template `select` picks for it; the
    file's own text selects where it exists, else `body`."""
    relative = _relative(options.path, _root(options.path, options.root), command)
    text = _file_text(options.path, command, missing_ok=True) or body or ""
    return relative, select(templates, FILE_ACTION, text, getattr(options, "title", None),
                            path=relative)


def _given(options: argparse.Namespace) -> tuple[str | None, dict[str, object] | None]:
    """The body or the field values `check` was given, by whichever of its four options, else
    the text of `--path`."""
    if all(value is None for value in (options.body, options.body_file, options.fields,
                                       options.fields_json)):
        if options.path is None:
            raise TemplateError("templates.py check: give the text: --body-file, --fields, --body, "
                            "--fields-json or --path")
        return _file_text(options.path, "templates.py check"), None
    if options.body is not None:
        return options.body, None
    if options.body_file is not None:
        try:
            return options.body_file.read_text(encoding="utf-8"), None
        except OSError as error:
            raise TemplateError(f"templates.py check: cannot read --body-file {options.body_file} "
                            f"({error})") from error
    if options.fields_json is not None:
        return None, fields_data(options.fields_json, "--fields-json")
    return None, fields_file(options.fields)


def _selected(templates: dict[str, Template], options: argparse.Namespace,
              body: str) -> Selection:
    """The template `select` picks for `check --action`, as a write would."""
    labels = [label.strip() for label in (options.labels or "").split(",") if label.strip()]
    where: dict[str, object] = {"labels": labels, "base": options.base,
                                "integration": _integration_branch(ROOT)}
    if options.repo is not None:
        where.update(repo=options.repo, home=home_repositories(ROOT))
    return select(templates, options.action, body, options.title, **where)


def _check(templates: dict[str, Template], options: argparse.Namespace):
    """What `check` checks: the template (None: free), the Markdown it would file, the document and
    the refused markers selection met."""
    if options.template is None and options.action is None and options.path is None:
        raise TemplateError("templates.py check: name a template, or give --action to select one as a write "
                        "would (--path for a file)")
    if options.template is not None and options.action is not None:
        raise TemplateError("templates.py check: give a template or --action, not both")
    if options.action is None and any(value is not None for value in
                                      (options.repo, options.labels, options.base)):
        raise TemplateError("templates.py check: --repo, --labels and --base select a template; give them "
                        "with --action")
    if options.action == FILE_ACTION and options.path is None:
        raise TemplateError(f"templates.py check: {FILE_ACTION} selects by the file; give --path")
    if options.path is not None and options.action not in (None, FILE_ACTION):
        raise TemplateError(f"templates.py check: --path selects a template for {FILE_ACTION}; give it "
                        f"without --action {options.action}")
    if options.root is not None and options.path is None:
        raise TemplateError("templates.py check: --root is the root of --path; give --path")
    named = _template(templates, options.template) if options.template is not None else None
    body, values = _given(options)
    met: tuple[Finding, ...] = ()
    if named is not None:
        template: Template | None = named
    elif options.path is not None:
        _, chosen = _claimed(templates, options, "templates.py check", body)
        template, met = chosen.template, chosen.findings
    else:
        chosen = _selected(templates, options, body or "")
        template, met = chosen.template, chosen.findings
    if template is None:
        return None, body or "", None, met
    if values is None:
        document = parse(template, body, options.title)
        return template, render(template, document), document, met
    values = answer(template, values)
    title = next((item.name for item in template.fields if item.source == "title"), None)
    if options.title is not None and title:
        values[title] = options.title
    rendered = render(template, values)
    return template, rendered, parse(template, rendered, values.get(title) if title else None), met


def _capped(findings: list[Finding]) -> list[str]:
    lines = [str(finding) for finding in findings]
    if len(lines) > 10:
        rest = len(lines) - 9
        lines = lines[:9] + [f"... and {rest} more findings"]
    return lines


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="templates.py", description="SE's templates: check, draft, schema, list")
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="check a body or a set of fields against a template")
    checking.add_argument("template", nargs="?",
                          help="the template; without it, --action or --path selects one")
    given = checking.add_mutually_exclusive_group()
    given.add_argument("--body-file", type=Path)
    given.add_argument("--fields", type=Path)
    given.add_argument("--body", help="the body as text")
    given.add_argument("--fields-json", help="the field values as JSON text, as --fields holds")
    checking.add_argument("--title")
    checking.add_argument("--render", action="store_true",
                          help="print the Markdown to file where nothing refuses")
    checking.add_argument("--action", choices=ACTIONS,
                          help="select the template as a write of this action would")
    checking.add_argument("--repo", help="with --action: the repository written to")
    checking.add_argument("--labels", help="with --action: the labels, comma-separated")
    checking.add_argument("--base", help="with --action: a pull request's base branch")
    drafting = commands.add_parser("draft", help="print the empty template")
    drafting.add_argument("template", nargs="?", help="the template; without it, --path selects one")
    drafting.add_argument("--json", action="store_true")
    schemas = commands.add_parser("schema", help="print the JSON Schema generated from a template")
    schemas.add_argument("template", nargs="?", help="the template; without it, --path selects one")
    listing = commands.add_parser("list", help="name every template with its actions")
    for command in (checking, drafting, schemas):
        command.add_argument("--path", type=Path,
                             help=f"the file: the template that claims it ({FILE_ACTION})")
        command.add_argument("--root", type=Path, help="the project root of --path's globs "
                             "(default: the git checkout holding it, else the working directory)")
    for command in (checking, drafting, schemas, listing):
        command.add_argument("--tree", action="store_true", help="read the working tree's templates/")
        command.add_argument("--templates", type=Path, help="read the templates and terms.toml from this "
                             "folder instead of SE's templates/")
    options = parser.parse_args(arguments)
    if options.command == "check" and options.path is None and all(
            value is None for value in (options.body, options.body_file, options.fields,
                                        options.fields_json)):
        checking.error("one of the arguments --body-file --fields --body --fields-json --path "
                       "is required")
    try:
        templates = load(ROOT, tree=options.tree, folder=options.templates)
        if options.command == "list":
            print("\n".join(list_templates(templates)))
            return 0
        if options.command in ("draft", "schema"):
            command = f"templates.py {options.command}"
            if (options.template is None) == (options.path is None):
                raise TemplateError(f"{command}: name a template, or give --path to take the template "
                                "that claims the file, not both")
            if options.root is not None and options.path is None:
                raise TemplateError(f"{command}: --root is the root of --path; give --path")
            if options.path is not None:
                relative, chosen = _claimed(templates, options, command)
                if chosen.template is None:
                    if chosen.findings:
                        print("\n".join(_capped(list(chosen.findings))))
                        return 1
                    print(f"free: no template claims {relative}")
                    return 0
                template = chosen.template
            else:
                template = _template(templates, options.template)
            if options.command == "schema":
                print(json.dumps(schema(template), indent=2))
            else:
                print(json.dumps(draft_fields(template), indent=2) if options.json else draft(template),
                      end="" if not options.json else "\n")
            return 0
        template, rendered, document, met = _check(templates, options)
    except TemplateError as error:
        print(error, file=sys.stderr)
        return 2
    findings = [*met, *(check(template, document) if template is not None else ())]
    refused = sum(finding.severity == REFUSE for finding in findings)
    lines = _capped(findings)
    if template is None and not findings:
        free = (f"free: no template claims "
                f"{_relative(options.path, _root(options.path, options.root), 'templates.py check')}"
                if options.path is not None and options.template is None
                else f"free: no template applies ({options.action})")
        if options.render:
            print(free, file=sys.stderr)
            print(rendered, end="")
        else:
            print(free)
        return 0
    if options.render and not refused:
        if lines:
            print("\n".join(lines), file=sys.stderr)
        print(rendered, end="")
        return 0
    print("\n".join(lines) if lines else f"{template.name}: no findings")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
