# Templating

## Templates

[docs/templates.md](templates.md) owns the template system: its names, the template, the
document and the packages that build it. This section holds the commands of the engine as it runs
today.

One Markdown note per template under `templates/`, its front matter the fields and its body the
skeleton with an instruction per section, is read by one engine, `scripts/templates.py`, whose
docstring owns the note's format, the field kinds, the selection order, the two severities and the
marker a rendered document carries, `<!-- se:template <repository>/<name> <version> <digest> -->`.

The templates own the shape of issues; the GitHub issue templates in `.github/ISSUE_TEMPLATE/`
are advice beside them.

The texts `overhaul.py` and `retro.py` file pass the work template as they stand, and the GitHub
issue template `work.md` has a section for every part the work template requires; the tests check
both.

| Template | What it shapes |
|---|---|
| `templates/decision.md` | A decision note: the situation, the problem and what others do, then the options' pugh fence. |
| `templates/boot-report.md` | SE's start report: its version, what it loaded with links into the documentation, each component's loaded and newest version, and the one update command. |
| `templates/delivery-notice.md` | A worker's delivery: the pull request whose description is its field report, and its branch. |
| `templates/escalation.md` | An escalation to SE: the escalated issue and its question in one line. |
| `templates/generated-marker.md` | A generated file's marker words. |
| `templates/field-report.md` | A work pull request's description: the field report between its markers. |
| `templates/finding-ref.md` | A finding's reference in a work issue: the run's kind and number and the finding's number in its report. |
| `templates/go-module.md` | A Go module: its go.mod, its package with the entry Run, a test, and slots for its own content. |
| `templates/handover.md` | Where the work stands for the next session: state, open work, branches, parked decisions, how to resume. |
| `templates/housekeeping.md` | The owner's housekeeping pull request: no field report, no field required. |
| `templates/landing.md` | A landing pull request: it names the work issue, the work pull request and its report. |
| `templates/merge-message.md` | An integration's squash commit: `Integrate <branch>` and one Release-kind trailer. |
| `templates/overhaul.md` | An overhaul's report: verdicts, both question blocks, the findings and the judged block the next one reads. |
| `templates/overhaul-judgment.md` | An overhaul's judged block: a verdict on every rule, what it looked at, the findings and what went well, as JSON under its marker. |
| `templates/overhaul-questions.md` | The questions an overhaul asks beside the standing questions, one section each. |
| `templates/pugh.md` | A Pugh matrix in obs's `pugh` fence: weighted criteria and at least two options. |
| `templates/python-component.md` | An ad hoc Python component: its component.toml with one command, and its __init__.py answering it. |
| `templates/python-module.md` | A Python module other scripts import: its template marker, its docstring, and a slot for its code. |
| `templates/python-script.md` | A Python script: the uv entry, argparse help and logging through se_script, and slots for its own part. |
| `templates/raid-entry.md` | One RAID entry: a risk, an assumption, an issue or a dependency, with its owner and status. |
| `templates/raid-register.md` | A RAID register: its risks, assumptions, issues and dependencies, one raid-entry each. |
| `templates/retro-judgment.md` | A retro's judged block: the findings, the classes and what went well, as JSON under its marker. |
| `templates/retro-doc.md` | A retro report's link to its committed retro doc: the commit and the doc's path in the checkout. |
| `templates/retro-due.md` | The retro and overhaul countdowns: per kind what it counted since where it starts, the days, and whether it is due or open. |
| `templates/retro-part.md` | The label a part of a split retro report ends in: which part of how many, of which retro's report. |
| `templates/retro.md` | A retro's report and its draft: the six steps, the standing questions nested in step 4. |
| `templates/review.md` | A cold review's one comment: what a person reads, then the JSON block the retro reads. |
| `templates/routed.md` | The routing block SE appends to an outside issue: where it came from and what it lacks. |
| `templates/rules-page.md` | The page `docs/rules.md`. |
| `templates/skills-page.md` | The page `docs/skills.md`. |
| `templates/standing-questions.md` | The standing questions every retro, overhaul and field report answers, one section each. |
| `templates/sub-agents-page.md` | The page `docs/sub-agents.md`. |
| `templates/terms.toml`, the term list and no template | Inside terms and the plain words to use instead. They only warn. |
| `templates/ticket.md` | An issue the owner reads: what is, what is wrong, what should be, how, and how we know. |
| `templates/work.md` | One package for one worker: the ticket's why, then numbered requirements and acceptance. |
| `templates/work-file.md` | A work issue's body file, `.se/issues/<name>.md`. |

Templates nest ([docs/templates.md "Nesting"](templates.md#nesting)):

- a field `node: <template>@<version>` is a part another template checks, such as the decision's
  options, the `pugh` block;
- a field `entries: <template>@<version>` is a register whose every entry that template checks,
  such as the RAID register's raid-entry;
- a finding of a part names its field, and of an entry also the entry's heading.

`check` refuses a missing, empty or placeholder field, a choice outside its set, an Approach
without its alternative, the same text in two fields and an SE command that does not exist; the
writing rules (word counts, actors, one sentence per step, bare issue numbers, board lines, inside
terms, unnamed blockers, the title's shape) only warn.

`templates.py check <template> --body-file <file>` (or `--fields <file>`, the JSON `draft --json` prints)
prints at most ten findings and exits 1 where one refuses; `templates.py draft <template>` prints the empty
template and `templates.py list` names every template with its actions. They read `templates/` at `origin/main`
where it holds them, else the working tree (`--tree` always).

`draft --json` also gives each field's shape (its kind, heading, whether it is required, its
choices) and the template's JSON Schema, which a model's strict tool use takes as it stands;
`templates.py schema <template>` prints that schema alone, generated from the template.

The interface templates (`boot-report`, `delivery-notice`, `escalation`, `finding-ref`,
`generated-marker`, `handover`, `retro-doc`, `retro-due`, `retro-part`, `rules-page`,
`skills-page`, `sub-agents-page`) shape the texts SE shows, writes and its sessions pass to each
other.

`templates.py interfaces` writes each one's schema beside the code that uses it,
`scripts/interfaces/<name>.json`, and `--check` names a file that differs from its template.

Through `scripts/interfaces.py`:

- `work_tickets.py deliver` and `escalate` write their messages;
- `se_start.py` its start report, a snippet of several lines with a table and a line of three
  cases;
- `se_plugin.py build` the three layout pages, and `generated.py` every generated file's marker;
- `retro.py due` its two countdown lines, `retro.py file` its report's link to the retro doc and the
  label of each part of a split report, and both reports the finding reference work issues name.

A `file.write` template claims files by its `applies.paths` globs, such as a milestone's steps.
`templates.py list --owned` names each owned glob.

`templates.py check --path <file>` checks one against the template its front matter's
`derived_from` names or the conditions pick, refuses one none picks and leaves unclaimed files free.

The front matter and `#` title stay as they are, but for the `derived_from` and `overlay` lines the
front matter records its template by.

A document is checked against the template version its marker or front matter records: another
minor or patch version warns, another major version refuses, naming both versions and the fill
that writes it again ([docs/templates.md "The document"](templates.md#the-document)).

`--templates <folder>` reads the templates from another folder.

A claimed file that breaks its template cannot be written by a file tool
([docs/templates.md "Fill"](templates.md#fill)), end a turn, be pushed or pass CI; each
refusal names the file, the template and each finding.

- `scripts/se_templates.py check-files` with `--changed` and a ref checks every claimed file changed
  since that ref's merge base, committed or not, untracked ones too; its docstring owns the answer.
- `work_tickets.py stop-check` and `push` run it against `origin/<integration branch>`, CI's
  `check` job against the pull request's base. Where no template claims a path outside `.se/`, it
  checks nothing.
- Under Copilot the Stop hook only advises.
- SE's template gate parses the file each file tool's write leaves, never the edit text, and
  denies one that breaks its template, naming each finding and `templates.py fill <template> --path`.
  - SE's start writes `.se/.runtime/templates-files` where a template claims a path, `claimed`
    and each owned glob, so `scripts/se_hook.sh` picks with builtins only calls on a path a glob
    matches; a template added during a session is guarded from the next session's start. `scripts/se_templates.py`'s docstring (The
    file tools) owns the rest.

An agent asks for a template through the MCP door's tool `templates`, `scripts/se_templates.py`: `list`
names the templates, `draft <template>` gives `draft --json`'s answer, and `check` finds all the filing
commands below would refuse (private terms, the name rule, SE's commands too) or gives the
Markdown to file.

It only reads; `check`'s first line is `passes` or `refused: <n> findings`.

- `draft` and `fill` give the template's guidance first, as
  [docs/guidance.md "Delivery"](guidance.md#delivery) states: once per session (`--session`),
  in pages of kern's page limit, the template on the last page.

`fill` is one step from raw input to document ([docs/templates.md "Fill"](templates.md#fill)):
it takes the template, the prompt, the raw input and the agent's fields.

- Without fields it answers the template's instructions, its guidance and the empty draft.
- With them it checks the document against the template and the raw input. Every field takes
  `Not in input` where the input does not say, and a field with `quote: true` refuses a quote the
  raw input does not hold word for word.
- `templates.py fill` writes a claimed file to its `--path`, or the document to `--out` or stdout;
  a refusal names every finding and writes nothing. The tool's `fill` answers as `check --render`
  and writes nothing; filing stays the filing commands' and the GitHub tools'.
- `templates.py` resolves a name for the project `--root` names, else the checkout holding
  `--path`: its own `templates/`, the template repositories its se.toml pins, then SE's
  ([docs/templates.md "Template repositories"](templates.md#template-repositories)).
- A template overlay, `templates/<name>.overlay.md` beside its template, adds instructions,
  fields, tags and rules or makes a rule stricter; one that loosens its template does not load.
- Before each fill, `templates.py fill` brings every template a `templates/imports.yaml` imports up
  to date from its source tool, then the overlay applies (`scripts/template_import.py`; its
  `refresh` does the same alone).

The commands that file issues check with them where se.toml `[templates] enforce` says so: `file`
against `work`, `backlog file` against `ticket` and `route` against `routed`. Each takes
`--body-file` (for `route`, `--routing-file`) or `--fields <file>`, the JSON `draft --json` prints,
always rendered through the template.

- `enforce` is `off` (the default: a `--body-file` body is filed byte for byte as before), `warn`
  (the findings go to stderr and the issue is filed) or `refuse` (nothing is printed, asked or
  written; the refusal lists every finding in at most ten lines). With `warn` or `refuse` a
  `--body-file` body is parsed and rendered again, its unknown sections kept.
- They read `[templates]` from `se.toml` at `origin/<integration branch>`, the working tree's only
  where that ref does not exist, so a branch cannot switch its own check off.
- `refusals` (default 2) caps the retries: refusals are counted per session, template and issue in
  `~/.se/templates/`. From that count on each refusal names `--hold`, which files the text as given,
  labelled `off-template` and not `ready`; `ready` and `start` take no such issue. Before that count
  `--hold` is refused.
  - The way back: fix the title or body on the issue itself, since filing it again only comments
    on it, then run `work_tickets.py unhold` with its number, which checks it against its template
    and lifts the hold where it passes.
- The check also runs the two layers of `scripts/public_check.py` over the title and the body
  ([Public safety](../AGENTS.md#public-safety)): the committed public list, and the checkout's
  private `.public-check.local`, which nothing committed refers to, where it holds one.
  - A hit names the field and the list, never the term: stop and ask the owner. `--hold` never
    files such a text.

SE's template gate holds the writes an agent sends through the GitHub MCP tools (`issue_write`,
`add_issue_comment`, `create_pull_request` and the other five of `scripts/se_templates.py`'s table)
to the same checks, where se.toml `[templates] gate` says so.

The gate is `off` (the default), `warn` (the agent gets the findings) or `refuse` (the call is
denied, naming the template, every finding and the templates tool).

- `scripts/se_hook.sh` picks the guarded calls with bash builtins and runs `se_templates.py gate` for
  them alone, whose docstring owns the table, the answers and the failure rule.
- A shell call that names `gh` is guarded too: the gate reads each `gh issue`, `gh pr` and `gh api`
  write in it as the same write through the GitHub tools; its docstring owns the commands it reads.
  - A body it cannot read, such as one from `$(...)` or `--fill`, is refused where a template applies,
    naming `--body-file`.
  - It does not see `gh api graphql`, `curl` or another program that calls GitHub's API.
- It reads `[templates] gate` as `enforce` is read, from the se.toml of the project whose home holds
  the target, else of SE itself; a write elsewhere, without a body or that no template covers runs as
  before. `SE_TEMPLATES_GATE=off` turns it off for a machine.
- From `refusals` on, a refused issue write may be sent again labelled `off-template` and without
  `ready`, the hold `--hold` files; a private term is never held.
- It fails open when it is slow: past 10 s, or where the host cancels it, the call runs.
  It fails open where it cannot judge (no Python 3.11, a payload it cannot read), and logs it in
  `.se/.runtime/templates-gate.log`; it fails closed only on a crash once it knows a template applies.

SE's templates backstop marks what reaches GitHub past every hook, where se.toml `[templates] backstop` is
`on` (default `off`): a person's write on github.com, a session without SE's hooks, a label change.

The workflow `.github/workflows/templates.yml` runs on each issue and comment event and hands the event
to `scripts/se_templates.py backstop`, whose docstring owns what it checks and its plan.

- A fleet issue (the fleet marker, or labelled `work`) whose text breaks its template gets the label
  `off-template`, and the run's summary lists the findings and the `unhold` line; a marked comment that
  breaks its template gets a failed run, as `unhold` reads the issue's body alone.
- Outside reporters' issues, unmarked comments and passing text are left alone. The workflow never
  comments and never removes a label; `work_tickets.py unhold` stays the way back.
- SE's own se.toml leaves it `off`: open issues SE's commands filed from an older template would be
  labelled.
