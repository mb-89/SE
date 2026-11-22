# Guidance: design

Reader: each worker on one of the guidance packages, and SE filing them. This note owns the design
of SE's guidance system: where guidance lives, which notes reach which template, how they reach
the agent, and how SE's present guidance moves into it. The work issues own the work; once built,
the code's docstrings own its formats.

The person decided on 22 Nov that guidance is a system of its own, which templates use and which
also works without a template. Today SE's guidance lives in its skills, the rule book, the agent
definitions and each project's `AGENTS.md`, and an agent reads it when it chooses to. A weak model
skips what it may skip, so the guidance that matters must stand in the agent's way to the work.

The template system that uses guidance is designed beside this one, in
[docs/templates.md](templates.md). This note relies on one fact of it only: a template carries
tags and calls "collect the guidance for this template"
([Tags and guidance](templates.md#tags-and-guidance)). Until templates exist, SE's forms
(README [Forms](../README.md#forms)) are the templates: each form gains its tags.

## Words

| word | meaning |
|---|---|
| **guidance note** | one Markdown file of guidance, with front matter; also a skill in both hosts |
| **guidance tree** | the folder `guidance/` at the root of a repository, and everything under it |
| **tag** | a word a note applies to; every folder name is one, and the front matter adds more |
| **resolution** | the ordered list of notes one template, or one set of tags, gets |
| **session record** | the list of notes already printed to one session, kept by the tool |

## Notes in folders

- **General to specific.** A guidance tree's folders nest from general to specific:
  `guidance/work/` holds what every role needs, `guidance/work/testing/` what testing needs,
  `guidance/work/testing/go/` what testing Go code needs. A note's depth is the number of folders
  between it and `guidance/`; a note directly in `guidance/` has depth 0.
- **Every folder name is a tag.** A note in `guidance/work/testing/go/` carries the tags `work`,
  `testing` and `go`. Folder names are lowercase words joined by `-`, so a tag is never spelled
  two ways.
- **The front matter adds tags.** A note's own tags extend those its folders give, for what the
  folders cannot say: a testing note that only the integrator needs adds `integrator`. Its tag set
  is the union of both.
- **Every note is also a skill.** Its front matter carries the two keys a skill needs, `name` and
  `description`, beside `tags` and the optional `overrides`. The build that writes SE's agents and
  skills into both hosts' layouts ([AGENTS.md "Agents and skills"](../AGENTS.md#agents-and-skills))
  writes each note as one skill, so a host that offers skills to the agent offers each note too.

```markdown
---
name: testing-go-repeat-count
description: 'How to tell a flake from your own failure in Go tests. Load it before treating a red Go test as yours.'
tags: [worker, integrator]
---

Rerun the one test at the integration branch with `go test -count=500 -run <test>` ...
```

- **Names are unique across the tree**, as they are across a host's skills: the check refuses a
  second note of one name, naming both files.
- **Two keys more, never a third.** `tags` and `overrides` are the only keys beyond a skill's;
  the check refuses any other, so a note cannot grow a second mechanism of its own.

## Resolution

A template carries a set of tags in its front matter ([docs/templates.md](templates.md#tags-and-guidance)). Resolution gives it its
notes:

1. **A note reaches every template that carries all of its tags.** A note tagged `work`,
   `testing` reaches a template tagged `work`, `testing`, `worker`, and not one tagged `work`
   alone. A note directly in `guidance/` with no front-matter tags reaches every template.
2. **General before specific.** The notes print by depth, lowest first; at equal depth by the
   number of tags, fewest first; then by path. A specific note thus comes after the general rule
   it narrows, and wins where they differ.
3. **A note may override another.** `overrides: <name>` drops the named note from every
   resolution the overriding note is in, and prints the overriding note in its place. The check
   refuses an override whose note does not carry every tag of the note it overrides: only a more
   specific note may replace a general one, so an override never reaches a template the
   overridden note did not.
4. **Modules come first.** A project's resolution reads the guidance trees of its modules
   (README [Modules](../README.md#modules)), se's among them, then its own. At equal rank a
   module's note prints before the project's, and a project note may override a module's note;
   a module never overrides the project.

Two checks hold the tree to its templates:

- **No orphan note.** A note that reaches no template is refused, naming the note and its tags,
  with the remedy: fix its tags, or delete it. The check runs where SE's generated layouts are
  checked today, in `se_plugin.py check`, so the `check` job fails on it.
- **The resolutions are pinned.** One committed table, `tests/guidance-pins.toml`, names for each
  template the notes it gets, in order. A test resolves every template and compares: a change
  that moves a note into or out of a template fails until the table is rewritten by the guidance
  command's `pin` action, and that diff is what a reviewer reads.

These are the resolution rules #1580 records as settled by the system before SE; SE takes the
rules, not that system's code.

## Delivery

### The template command prints guidance first

The command that hands an agent its template (`templates.py fill` and the fill tool,
[docs/templates.md "Fill"](templates.md#fill); until they exist, `se_forms.py draft` and the
forms tool's `draft`) prints the template's resolved guidance
before the template itself. The agent cannot reach the template's fields without reading past the
guidance, so reading it is the only way to the work.

No evidence of a read is asked for: no quiz, no digest the agent repeats, no proof in the report.
The system before SE tried reading proofs and settled on this; its record says they slowed the
work without making it safer ([Harvest](harvest-2026-11.md), "Superseded by SE's design").

### Once per session

- **The tool keeps the session record**, never the agent. Each note printed to a session is
  recorded by its name and the digest of its text.
- **A note already printed is named, not printed again**: the answer lists
  `already printed this session: <name>, <name>` where the note would stand. A note whose text
  changed since it was printed has another digest and prints again.
- **The record lives in kern**, one name family `session/<id>/guidance` beside the session's
  other names (kern's README "The host", its leases); it ends with the session's lease. Without a
  core, the record falls back to one file under the session's runtime folder, as the door's other
  fallbacks do.
- **A compaction clears it.** After the host compacts a session, the notes are gone from the
  agent's context, so the hook that sees the compaction (a session start from a compaction)
  clears the record, and the next call prints everything again.
- **The session is the caller's.** The door knows its session's id from the lease its start hook
  took; a command run from a shell names it with `--session <id>`, and without one keeps no record
  and prints everything.

### The answer's size

- **The cap.** A host saves a tool's text answer longer than about 50,000 characters to a file
  instead of showing it ([`scripts/host-limits.toml`](../scripts/host-limits.toml),
  `tool-output-offload`); guidance the agent finds only in a file is guidance it may skip.
- **The margin.** Each answer stays under kern's page limit, 45,000 bytes, the margin kern's door
  already keeps below that cap (kern's README "The MCP door", "Long answers come in pages").
  The guidance tool uses the same constant, never a second one.
- **More is split across the next calls.** Pages break between notes, never inside one. Each page
  says how many follow and how to ask for the next, and the template itself comes on the last, so
  the agent pages through the guidance to reach it. Each page's notes enter the session record as
  that page is printed.
- **No note outgrows a page.** The check refuses a note over a quarter of the page limit, naming
  its size: such a note is split into more specific notes, which is what the folders are for.

## Guidance without a template

The same command resolves guidance for any tags, at any point, without a template:
`collect --tags testing` prints every note tagged `testing`, general before specific, under the
same session record and the same pages. Before talking about testing, the agent (or SE on the
person's word) runs it, and every testing note is in the context.

- **The direction is the other way round.** A template's resolution takes the notes whose tags it
  carries all of; a tag query takes the notes that carry all the asked tags. `--tags testing,go`
  prints the notes tagged both.
- **The general notes come along.** A tag query also prints the notes at depth 0 not yet in the
  record, so a topic is never read without the rules every topic sits under.
- **`collect --template <name>`** prints a template's guidance without the template, for an agent
  that wants it before it has its input.
- **A tag nothing carries** is named in the answer with the tags that exist, never answered with
  silence.

The command is one component, `guidance`, with read-only commands `collect` and `check` and the
writing command `pin` ([docs/go-core.md](go-core.md), components). Its read-only commands are
also tools of the MCP door, so an agent reaches it without a shell.

## Implementations and projections

The person decided on 22 Nov that the notes are the single source of truth, and everything else
is generated from them: "But the truth is always in the markdown."

- **Implementations live in the note.** A note may carry implementations of itself for other
  tools, one per target: a linter's setting, a check's configuration, a test command.
- **Tool files are projections.** One command, the guidance command's `project`, writes each
  file the notes implement, in a part whose header says it is generated. The check refuses a file
  that no longer matches its notes, so nobody edits it by hand.
- **Lists are views, never files.** The rule book, all guidance or the notes for one step are
  queries over the notes (`collect`), made when asked; no list is stored.

The note "Short lines" carries `[tool.ruff] line-length = 100` for `pyproject.toml`, and
`project` writes it there, beside the project's own settings. The block's form and the part's
header are owned by the docstring of
[scripts/se_guidance.py](../scripts/se_guidance.py).

## Moving SE's guidance into notes

No guidance stays where it is: what is guidance becomes notes, what a host must read by itself
shrinks to a pointer. No backwards compatibility: links move with the text.

| today | becomes |
|---|---|
| The rule book, `src/skills/work-model/references/rules.md` | one note per rule, its id its name (`pub-001`), each section a folder (`guidance/rules/pub/`); the rule-book skill goes |
| The work model, `src/skills/work-model/SKILL.md` | one note per section, in the folders of its topics (`guidance/work/issues/`, `guidance/work/tests/`), tagged with the roles each applies to |
| The catch-up and decision skills | notes under `guidance/se/` and `guidance/decision/`; the decision deck's guidance becomes the guidance of the decision template |
| The agent definitions, `src/agents/*.md` | only the box and the role's tags stay; their procedure steps become notes tagged with the role |
| A project's `AGENTS.md` | the project's own `guidance/` tree; `AGENTS.md` keeps what a host reads before any tool runs: the setup command and the line that the guidance command comes first |
| Draft skills under `drafts/skills/` | notes in a folder its setting switches on, as the drafts are included today |

- **One owner still.** A rule that several notes need lives in one note, at the depth where all
  of them sit; the others link to it, as SPOT asks
  ([gen-002](../src/skills/work-model/references/rules.md#gen-002-single-point-of-truth)).
- **Size is the measure.** The work model's skill is 65 KB and the rule book 51 KB, each over the
  cap a single answer may hold; a note over a quarter page is split by topic until it fits.
- **The skill references move too.** Every link to a rule's anchor becomes a link to its note;
  `scripts/references.py` learns the guidance tree, so a link to a missing note fails the
  dangling-reference check as a missing file does today.

Not picked: guidance as skills alone, with no command in the way. A skill is read when the agent
chooses to, which is the problem this system exists to solve; the notes stay skills only so a host
can still offer them by name.
