# Templates: design

Reader: SE, filing the implementation packages, and each worker on one of them. This note owns the
design of the one template system for everything an agent writes in SE, obs and kern. The work
issues own the work; once a part is built, the code's docstring that the part names owns its
detail, and this note links to it.

The person decided on 22 Nov, in the decision deck "Templates across SE, obs and kern": one nested
template system for everything agents write; the names template, schema and document; and a
separate guidance system that templates use. The guidance system has its own design; this note
states only the one call a template makes to it ([Tags and guidance](#tags-and-guidance)).

Until the packages land, ["Templates"](templating.md#templates) describes the engine as it
runs today; the [Map](#map) says where each of its parts goes.

## Names

| word | meaning |
|---|---|
| **template** | the definition a person or an agent writes and keeps: its fields, its skeleton, its rules, its tags |
| **schema** | generated from a template, never written by hand: the shape code and tools read |
| **document** | a filled template: a file, an issue, a comment, a message, recording the template and version it implements |
| **overlay** | the agent-only additions a template repository keeps beside an imported template |
| **import adapter** | the code that brings a template from its source tool into the template repository |
| **template repository** | a repository that holds templates and their overlays, found and pinned like a plugin |

"Form" is retired: the word, the folder `forms/`, the engine `scripts/forms.py`, the tool `forms`
and the se.toml table `[forms]` each take the name template. No alias keeps the old names.

obs already uses "overlay" for the JSON files beside a manifest (comments and sync records); its
word stays its own, and SE's texts say "template overlay" wherever both could be meant.

## The template

A template is one Markdown note in a template repository, `templates/<name>.md`:

- Its front matter declares what the engine reads: `name`, `version` (semantic, `1.2.0`), `kind`
  (`document`, `block`, `entry` or `interface`), `reader`, `says`, `tags`, what it applies to
  (actions and claimed paths), its `fields` with their kinds and rules, and `extends`.
- Its body is the skeleton a filled document follows: the `##` sections in order, each with an
  instruction in a comment that the fill hands the agent and the document never shows.
- A template whose document is data only (an interface) has an empty body; its fields are the
  whole template.
- A template imported as obs's note types is a folder instead, a template manifest with its
  template nodes ([Template manifests](#template-manifests)).

The field kinds, the rules with their severities, `extends` and the selection order carried over
from the TOML files the notes replaced, as they were; the engine's docstring owns them, and the
front matter's YAML subset with them.

## The schema

The engine generates each template's schema: a JSON Schema of its fields, the shape a strict tool
call takes as it stands, and for a document template the headings and front matter its check
reads. Nothing writes a schema by hand.

- Where code reads a template's shape (kern's Go types, SE's scripts, obs's build), the schema is a
  generated file beside that code, and a test fails where it differs from the template, as
  `tests/test_se_plugin.py` holds the plugin layout to its sources.
- The engine's `schema <template>` action prints it; `draft --json` keeps giving it with the
  fields.

## The document

A document is a filled template. Where it is a file it records, in its front matter, the template
it derives from, as obs reads a filled document, and the digest:

```yaml
derived_from: {template: <name>, version: "1.2.0"}
overlay: sha256:<digest of the template and the overlay the fill applied>
```

An issue, a comment or a message records the same in its marker line,
`<!-- se:template <repository>/<name> 1.2.0 sha256:<digest> -->`. The digest covers the template
and the overlay the fill applied (the docstring of `scripts/templates.py`, Writing, owns it).

The check reads a document against the template and version it records. Where the template has
moved since, a new minor or patch version warns and a new major version refuses, naming both
versions and the fill that brings the document up.

When a template's version moves, `templates.py stale --path <folder>` lists each document in that
folder whose `derived_from` names an older version, with both versions: the documents to review and
fill again. It lists nothing while every document is at its template's version.

## Template manifests

The person decided on 24 Nov, in the templates deck, that an imported template becomes a template
manifest with template nodes, obs's note types (obs `spec/design_input/input-model.md`,
Templates). The engine reads such a template as a second source form, beside the note, and loads
it into the same template, so resolution, overlays, the fill, the check and the gate are one code
path for both.

- **The folder.** `templates/<name>/manifest.md` is the manifest; its front matter carries
  `obs.template`, the template's `name` (the folder's) and `version`, and its table of contents
  lists the nodes, one note each beside it, in reading order.
- **The nodes.** A chapter whose front matter carries `obs.guidance` is a template node: one
  section of the document, under the chapter's title. Its guidance (`contents`, `motivation`,
  `form`, `sources`) is the instruction the fill hands the agent, and `gate: mandatory` makes the
  section required. Any other chapter, such as a note on how to use the template, is no section.
- **The slot.** A node's body is its fill slot, `{{slot}}`, alone: where the agent writes. A filled
  section that still holds it outside code is refused, naming the section, as obs refuses it.
- **The document.** One note: its front matter `derived_from` and the digest, then one `##`
  section per node in the template's order, and none of the guidance. obs builds it as a filled
  document.
- **Resolution and overlays.** A manifest resolves by its folder's name in the order of
  [Template repositories](#template-repositories), and its overlay is `templates/<name>.overlay.md`
  beside the folder, adding or tightening as a note's does. One name is one template: a note and a
  manifest of the same name in one `templates/` do not load.

Not picked: converting a manifest into a note on import, as it loses each node's guidance fields.
The docstring of `scripts/templates.py` (Template manifests) owns the details; the shared cases
hold the Go component `template` to the same result.

## Nesting

Every template is one of four kinds, and the kinds nest.

- **block**: a small output inside a document: a decision's Pugh matrix, later a morphological
  box. Its document is a fence or a section, not a file.
- **document**: a manifest whose nodes name templates. Each `##` section of its skeleton is either
  free prose under its instruction or a node, `node: <template>`, filled by that template. An issue
  is a document of sections; a decision note is a document whose options node is the Pugh block;
  obs's manifest is a document whose chapter nodes are documents.
- **entry**: one entry of a register. A register is a document whose register node names its entry
  template; every entry of it is a document of that template. A RAID register is the example: its
  entry template has a `type` field with the choices risk, assumption, issue and dependency, and
  fields for owner, status and the text; the register's view lists them.
- **interface**: a message or a contract whose schema code uses: a delivery notice from a worker
  to its integrator, an escalation, the handover, kern's component declaration, a message on
  kern's bus. Its schema is generated into the code that sends and reads it, so the code and the
  agent both follow one template.

The check of a document checks each node by its own template, so a document is valid only where
every node in it is. A node records no provenance of its own: the document's names the template,
which names its nodes' templates at their versions.

A field names its node `node: <template>@<version>`, and a register its entries `entries:
<template>@<version>`; a block that is a fence, such as the Pugh block, takes the fence's word
too. The docstring of `scripts/templates.py` (Nesting) owns the rest. SE ships the RAID register
and its entry as `templates/raid-register.md` and `templates/raid-entry.md`.

## Fill

One command and one tool fill a template: `templates.py fill`, and the action `fill` of the MCP
door's tool `templates_write`. The docstrings of `scripts/templates.py` (`fill`, "Not in input", the
rule `quote`) and `scripts/se_templates.py` (its `fill`, `file_document`) own what is built.

- **Filing.** With `--repo`, a fill files an issue, or with `--number` a comment, through kern's
  GitHub component, after the same checks as any fill. It asks the template component's `fill`
  for the filled template and hands that value to the component's write verbs, never a body or
  fields. `templates.py fill --repo` hands its call to the tool's `fill`, so one place files.
- **What kern files is what was checked.** The write verbs ask the template component's `accept`
  through the port `github.template-accept`, which `wiring.toml` binds to `template.accept`, and
  write the title and document it answers as they stand; free text is refused before GitHub.
- **Not yet.** A message has no writing tool in kern's door, and the tool's `fill` writes no
  claimed file: `templates.py fill --path` writes it, until kern's files module takes only filled
  templates (The filled template is a type).
- **The marker.** Every fill and every filing writes the template's marker into the document it
  makes: `templates.py fill`, the tool's `fill`, and `file`, `backlog file` and `route`, whose
  body filed as given (`[templates] enforce = "off"`, or `--hold`) gets the marker line where
  the fill writes it (`templates.stamped`). A document so always says which template it is a
  value of ([Which template a write is judged by](#which-template-a-write-is-judged-by)).

- It takes the template, the prompt, the raw input and the agent's fields; it resolves the template
  ([Template repositories](#template-repositories)), applies the overlay, checks the fields against
  the result, renders the document and writes it to its path, or files it where its action is an
  issue, a comment or a message.
- A refusal names each finding and writes nothing; the agent fixes its fields and calls again,
  capped as the filing commands' refusals are today.
- The fill hands the agent the template's instructions and its guidance first
  ([Tags and guidance](#tags-and-guidance)); a call with no fields answers with those and the
  empty draft.

Fields stay honest about their source:

- Every field allows the value "Not in input", whatever its other rules; a required field so
  filled passes and shows the gap instead of an invented value.
- A field may declare `quote = true`: its value then carries at least one quote of the raw input,
  and the fill refuses a quote the raw input does not hold word for word.

The gate refuses writes that break a template. A template that claims paths owns them: a write, an
edit or a write through the tracker's tools of a claimed path is judged by the file it leaves,
never by its edit text, parsed as the fill parses it. One that parses passes; one that does not is
refused before it runs, naming every finding and the fill to use. The gate is on wherever a
template claims a path, with no se.toml switch to keep it off.

## The filled template is a type

The person decided on 22 Nov, in the deck "Files, templates and agent tools", that typed templates
are blessed: a filled template is a type that only the template component constructs, after
checking, and every templated target accepts only that type. Parse, don't validate
([parse-dont-validate](../guidance/parse-dont-validate.md)): the fill checks a document once, and
a target relies on its type and checks nothing again.

- **The type.** `template.Filled` in SE's Go components carries its template, version, digest,
  fields, title and document. Its fields are unexported, so only `template.Fill`, which makes one
  where nothing refuses, constructs it; the zero value is none. Across the bus its JSON carries a
  seal that decoding verifies, so JSON of its shape written by hand is no filled template.
- **The constructor.** The template component's verb `fill` answers it (components/README.md
  [The template engine in Go](../components/README.md#the-template-engine-in-go)); a refused fill
  answers every finding and makes nothing.
- **The targets.** A Go verb that takes a `template.Filled` is never handed a text: kern's index
  refuses a request of another type. A target that reads JSON calls `template.Accept`, which
  refuses free text, a body, field values and a value whose seal does not hold, naming the
  template to fill.
- **The gate across the bus.** A target in another component, kern's among them, cannot import
  SE's package, so it asks the template component's verb `accept`: it answers the document and
  title of the filled template it was handed, of the template required or of the one that claims
  the path written, refuses anything else, and answers a path no template claims as free.

The two targets the decision names are kern's, both released in kern 2.0.0:

- **The GitHub door's writing tools** (kern 2.0.0): `issue-create` and `issue-comment` take a filled
  template instead of a template's name and its fields, pass it to `accept` through a request port
  the wiring binds to the template component, and write the document and title it answers as they
  stand; a refusal reaches GitHub not at all.
- **The files module's template-only paths**: a `write` asks `accept` with its path; a path a
  template claims takes only a filled template of that template, and every other path stays free.

SE's wiring binds the GitHub door's port (`github.template-accept`); it places no files module,
so its gate keeps checking claimed paths after the fact, as [Fill](#fill) says.

### Which template a write is judged by

A document's template is a fact the document records, its marker line (a file's `derived_from`),
never a guess from one call. The gate (the docstring of `scripts/se_templates.py`, Which template)
judges each GitHub write by it:

- **An edit** of an issue or a comment is judged as the document it leaves behind: the issue or
  comment as it stands, read from kern's snapshot where a fresh one stands, else by one REST read,
  with the call's body, title and labels in place. A label change alone is judged too.
- **Its template** is the one the new body's marker names, else the one the current document's
  marker names (a template's own marker, such as `<!-- se:review -->`, names it too). An edit that
  drops the marker line, or leaves the document without the labels its template needs, is refused.
- **A document that names no template** is refused for an issue edit, naming the stamp below and
  the fill, and judged against no other template. A comment that names none stays free, as no
  template takes an unmarked comment.
- **A new document** with no marker is the one case labels and the templates' order decide
  (`templates.select`), as the filing commands choose its template.
- **Not read.** Where the document cannot be read, the new body's marker alone decides, and an
  edit without one passes and is logged. A pull request's edit is still selected from the call.

### Stamp an issue filed without a marker

An issue filed over raw REST, past the fill, names no template, so the gate refuses its edits.
`work_tickets.py stamp <issue> --worktree <checkout>` gives it the marker of the template it
derives from: `--template <name>`, else the one a new issue with its labels would take, the one
the gate's refusal names. It writes only where the stamped body passes that template's check with
the checks a filing runs, and it changes nothing but the marker line; without gh it prints the
edit as a step for the GitHub tools.

## Template repositories

A template repository is a plugin: public or private, found and pinned as plugins are, through
se.toml.

- se.toml lists them by name, `[templates] repositories = ["<name>", ...]`, each a component
  `[components.<name>]` pinned by `ref` or `version` as any other and placed by `se_modules.py
  sync` ([docs/modules.md "Modules"](modules.md#modules)); its templates are its `templates/`, under its
  `path` where it sets one.
- The engine resolves a template name in order: the project's own `templates/`, then each pinned
  template repository in the order se.toml lists them, then SE's own.
- A repository that does not resolve, or whose pin cannot be fetched, refuses the fill with the
  name and the remedy; it never falls back to another repository's template of the same name.
- `scripts/templates.py` (`catalog`) owns the resolution, `scripts/se_modules.py`
  (`template_repositories`) the list and its pins; the Go component `template` resolves the same
  way, held to it by shared cases
  ([components/README.md](../components/README.md#the-template-engine-in-go)).

Each imported template lives with its overlay in its template repository:

- `templates/<name>.md` holds the template as the import adapter brought it, Markdown, never
  edited by hand.
- `templates/<name>.overlay.md` holds the overlay: the explanations and rules for agents the
  outside template does not contain. It `extends` the template and only adds or tightens: it may
  add instructions, fields, tags and rules and make a rule stricter, never remove or loosen one.
- A template written in the repository itself, with no source tool, has no import adapter; it
  may still have an overlay.

Before every fill the engine brings an imported template up to date:

1. It asks the template's import adapter whether the template changed in its source tool.
2. Where it did, the adapter writes the change into the repository's Markdown.
3. Only then the overlay applies, and the agent fills the document from the result.

An import adapter is a component that reads one source tool's templates and writes the template
note: headings to sections, the source's instructions to comments, its fields to front matter.
Each source tool gets one adapter; a source with headings only gives sections without
instructions, which the overlay supplies.

A template owns the paths its `applies.paths` globs claim, in whichever repository it resolves
from; `templates.py list --owned` is the one listing of them, each glob with its template, and
SE's start publishes those globs for its hook, which refuses a write that leaves an owned file off
its template before it runs ([Fill](#fill)). SE's own templates own one, a work issue's body file (`work-file`).

The docstrings own the rest: `scripts/templates.py` (Overlays) what an overlay may say and what
refuses as a loosening, `scripts/template_import.py` the declaration `templates/imports.yaml`, the
adapters' interface and the first adapter, which reads a Markdown template note.

## Filling templates from material

The skill [fill-templates](../src/skills/fill-templates/SKILL.md) gives anyone using SE one
capability: hand the agent templates, raw material and maybe a prompt, and get the finished
documents back in a small repository of their own. The skill owns the steps; this section owns
the worked example, which `tests/test_templates.py` fills again and checks as it stands.

The engine adds two things to the fill and the check above:

- `templates.py fill --input <folder>` takes a folder of material as its raw input: each text file
  under it, outside hidden folders, after a line naming the file.
- `templates.py documents --path <folder>` checks every document under the folder against the
  template its `derived_from` names, then lists each section the material did not fill, by its
  heading. It refuses where a document does not pass, or where the folder holds none.

A section the material cannot fill holds `Not in input` ([Fill](#fill)), which passes the check,
so `documents` names it for the person; a slot left in a document refuses.

### The worked example

The request: "write me a label spec and a test plan for Pump X, the templates are label-spec and
test-plan, my raw data is in `material/`". The repository the agent sets up is
[examples/fill-templates/pump-x](../examples/fill-templates/pump-x/README.md), whole:

- `templates/`: the single note [label-spec](../examples/fill-templates/pump-x/templates/label-spec.md),
  which writes a file, and the template manifest
  [test-plan](../examples/fill-templates/pump-x/templates/test-plan/manifest.md) with two template nodes
  ([Template manifests](#template-manifests));
- `material/`: three raw notes, a [brief](../examples/fill-templates/pump-x/material/pump-brief.md), a
  [safety review](../examples/fill-templates/pump-x/material/safety-review.md) and a
  [test log](../examples/fill-templates/pump-x/material/test-log.md);
- `documents/`: [label-pump](../examples/fill-templates/pump-x/documents/label-pump.md) and
  [test-plan-pump](../examples/fill-templates/pump-x/documents/test-plan-pump.md), each recording its template in
  `derived_from` and linking the notes it comes from rather than repeating them;
- the README, naming each template and version, the material and the prompt.

The agent asks each fill for its instructions first, then fills it with its fields, run from the
repository's root with `<se>` SE's checkout; `--root .` resolves the names there first:

```sh
uv run python <se>/scripts/templates.py fill label-spec --root . --path documents/label-pump.md --input material
uv run python <se>/scripts/templates.py fill label-spec --root . --path documents/label-pump.md --input material \
  --fields-json '{"product": "...", "warnings": "...", "languages": "Not in input"}'
uv run python <se>/scripts/templates.py fill test-plan --root . --out documents/test-plan-pump.md \
  --input material --fields-json '{"scope": "...", "cases": "..."}'
```

The material names no language, so that section holds `Not in input`. The check passes both
documents and names the gap, which the agent reports to the person:

```sh
uv run python <se>/scripts/templates.py documents --root . --path documents --input material
```

```text
label-pump.md: Languages: not in input
2 documents: pass; 1 section the material did not fill, named above: tell the person each
```

## Tags and guidance

A template carries tags in its front matter, and makes one call to the guidance system: "collect
the guidance for this template". The fill makes it before it hands the agent the template; the
guidance system owns what that answers, in what order and how much at a time.

A template's tags are its only link to guidance: no template names a guidance note, and no
guidance note names a template.

## Map

Each of SE's template files, obs's note kinds and kern's contracts becomes a template, owned by the
repository named here.

### SE's templates

SE's templates are notes; the term list stays a TOML list until the guidance packages land.

| File | Template | Kind | Owner |
|---|---|---|---|
| `templates/ticket.md` | `ticket` | document | SE |
| `templates/work.md` | `work`, `extends` ticket | document | SE |
| `templates/work-file.md` | `work-file`, `extends` work: a work issue's body file, `.se/issues/<name>.md` | document | SE |
| `templates/decision.md` | `decision`, whose options node is the `pugh` block | document | SE |
| `templates/pugh.md` | `pugh`: what SE asks of obs's `pugh` fence | block | SE, until obs's block templates |
| `templates/raid-register.md` | `raid-register`, whose entries node names `raid-entry` | document | SE |
| `templates/raid-entry.md` | `raid-entry` | entry | SE |
| `templates/field-report.md` | `field-report` | document | SE |
| `templates/landing.md` | `landing` | document | SE |
| `templates/housekeeping.md` | `housekeeping` | document | SE |
| `templates/merge-message.md` | `merge-message` | interface | SE |
| `templates/delivery-notice.md` | `delivery-notice`: a worker's message to its integrator | interface | SE |
| `templates/escalation.md` | `escalation`: an integrator's message to SE | interface | SE |
| `templates/handover.md` | `handover`: the open handover issue | interface | SE |
| `templates/boot-report.md` | `boot-report`: SE's start report, a snippet | interface | SE |
| `templates/review.md` | `review`: prose, then its data node | document | SE |
| `templates/retro.md` | `retro`: the six steps, whose answers node is the `standing-questions` block | document | SE |
| `templates/overhaul.md` | `overhaul`, whose question nodes are the `standing-questions` and `overhaul-questions` blocks | document | SE |
| `templates/routed.md` | `routed`: the routing section of an outside issue | block | SE |
| `templates/standing-questions.md` | `standing-questions`: the questions the retro, the overhaul and the field report all ask | block | SE |
| `templates/overhaul-questions.md` | `overhaul-questions`: the overhaul's own questions | block | SE |
| `templates/terms.toml` | the term list, no template: guidance notes tagged with the rule's tag | guidance | SE |

An adapter (`checker` and `adapter`) stays one: its template names the check its code already
owns.

SE's free texts are interface templates: the worker's delivery notice, an escalation, the
handover and the start report; a design note's outline is still to come.

Fixed text SE shows the person comes from a template, short snippets included (the person's
decision of 23 Nov 2026). A snippet is a message of several lines: a `rows` field writes one line
per row, as a table's, and a `case` field one of its lines, such as "everything is current". Each one's schema is generated into
`scripts/interfaces/`, beside `scripts/work_tickets.py`, which writes the two messages through it;
the docstrings of `scripts/interfaces.py` and `scripts/templates.py` (Interfaces) own the rest.

### obs's note kinds

| Kind today | Template | Kind | Owner |
|---|---|---|---|
| the manifest and its cover metadata | `manifest`, whose chapter nodes are documents | document | obs |
| `kind: glossary` | `glossary` | entry | obs |
| `kind: quantity` | `quantity` | entry | obs |
| `kind: capability`, `kind: adapter-behavior` | `capability`, `adapter-behavior` | document | obs |
| a register, a `.base` view | `register`, whose entries name their entry template | document | obs |
| a `figure` fence by its kind (`pugh`, `timeline`, `plot` and the rest) | one block template each | block | obs |

obs owns the structure check of a document as it builds: headings, front matter, nodes and fences.
SE's engine calls it for every document template rather than repeating it. obs's build also checks
a document's recorded `template`, `version` and `overlay`, which replace the cover's free-text
`template` field.

### kern's contracts

| Contract today | Template | Kind | Owner |
|---|---|---|---|
| a component's declaration (`component.toml`, `contract = 1`), `contract/declarations.json` | `component` | interface | kern |
| the attach and write messages on the bus | `attach`, `writes` | interface | kern |
| the JSON types an application's components share (`kern/template/types/`) | one per type | interface | the application |
| `contract/cases.json`, `contract/subjects.json` | stay test tables: they test the templates' schemas, they are none | — | kern |

kern generates its Go and Python types from these templates' schemas; the contract suite holds both
to them.

## Ownership

| Part | Owner |
|---|---|
| the template format, the engine, `fill`, the gate, resolution, overlays, the import adapters' interface | SE |
| the structure check of a document, the provenance check at build, obs's note kinds and block templates | obs |
| the contract templates and the types generated from them | kern |
| what a template's guidance call answers | the guidance system |
