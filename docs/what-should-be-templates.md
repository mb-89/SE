# What should be templates: a survey, November 2026

Reader: SE, filing the work this survey proposes, and the person deciding its backlog. This record
is the findings of the discovery package `what-should-be-templates` (#1884): every shape SE builds
or checks by hand that the template engine ([templates.md](templates.md)) should hold instead, each
rated and given its migration test. It is not kept up to date by hand; the issues filed from it are.

## How the survey was made

- **Engine baseline.** The engine at `55bbca5`, as `scripts/templates.py`'s docstring and
  [templates.md](templates.md) describe it, was read first; "trivial" below means the engine holds
  the shape at that commit and the output stays byte for byte the same (a check: the same
  findings). `uv run python -m pytest tests/test_templates.py -q` passed there, 405 tests.
- **Every script, mechanically.** Each of the 74 Python scripts under `scripts/` was counted for heading
  literals (`"## "`, `"# "`), section constants (`*HEADING*`, `*SECTION*`, `*TITLE*`), SE markers
  (`<!-- se:`), table rows (`"| "`), bullets (`"- "`), `json.dump` and `write_text`, and its first
  docstring line read. The commands are in [Scripts searched](#scripts-searched).
- **Every candidate, by reading.** The candidates fell into five clusters, each read whole with
  its tests, templates, skill and agent text by a read-only reader of its own: the decision deck;
  the retro family; the documentation, plugin, guidance and rule book; `work_tickets.py` lines 1
  to 6700; and the rest of `work_tickets.py` with the fleet's messages. `components/` was searched
  for Go code that repeats a Python shape.
- **Ratings checked.** Every trivial rating was checked again against the engine's code
  (`interfaces.line` and `text`, `templates.check` of an adapter), and every line its row and
  proposal cite was opened. T1, T2, T3, T8 and T9 were run in a scratch prototype against today's
  output: the three layout pages came out byte for byte equal to the committed ones. Ratings of
  "not trivial" rest on the readers' reading, with the engine's missing capability named.

## Scripts searched

The mechanical pass, run from the checkout's root:

```sh
for f in scripts/*.py; do
  grep -cE "[\"'](#{1,3} |\`\`\`)" $f; grep -cE "json\.dump" $f; grep -cE "<!-- se:" $f
  grep -cE "[\"']\| " $f; grep -cE "f?[\"']- " $f; sed -n 2p $f
done
grep -nE "^[A-Z_]*(HEADING|SECTION|CHAPTER|TITLE)[A-Z_]* *[:=]" scripts/*.py
grep -nE "json\.dump|write_text\(" scripts/<each script below>.py
grep -rlE '"## |"# ' components --include=*.go
```

It sorted the 74 Python scripts, the 9 shell scripts and the deck's two page scripts into three groups.

- **Read whole, with their tests, templates and skill text** (they write or check a document,
  block, message or JSON a reader reads): `build_docs.py`, `ci_queue.py`, `ci_reuse.py`,
  `comment_authors.py`, `component_versions.py`, `decision_rows.py`, `deck.py`, `deck_look.py`,
  `dispatch.py`, `generated.py`, `input_log.py`, `interfaces.py`, `late_push.py`,
  `limit_restart.py`, `metrics.py`, `outside_text.py`, `overhaul.py`, `pr_issues.py`,
  `references.py`, `retro.py`, `review.py`, `review_gate.py`, `rule_book.py`, `se_component.py`,
  `se_components.py`, `se_doctor.py`, `se_guidance.py`, `se_new.py`, `se_plugin.py`,
  `se_start.py`, `se_templates.py`, `se_workflows.py`, `session_cost.py`, `story_check.py`,
  `suite_runs.py`, `template_import.py`, `templates.py`, `timeline.py`, `transcript_signals.py`,
  `upgrade_guide.py`, `agent_lint.py`, `work_tickets.py`, the deck's page scripts `deck_answers.js`
  and `deck_look.js`; and in `components/`,
  `template/checkers.go`, `template/write.go` and `fleet/fleet.go`.
- **Searched, no document shape: configuration and machine state.** They write TOML, JSON or
  lines that a program reads and no template should shape, since their format is the reading
  program's (settings files, locks, caches, logs, verdicts): `adapter_sync.py`, `ci_trust.py`,
  `claude_settings.py`, `copilot.py` (`.github` settings, the `[components.se]` pin),
  `host_size.py`, `se_switches.py`, `se_usage.py`, `verdicts.py`, `se_relay.py` (relay
  snapshots), `se_runtimes.py` (`RUNME.conf`), `se_modules.py` (`se.lock`), `gh_rest.py`
  (gh's own output shape), `rewrite_history.py` (a commit map).
- **Searched, nothing written but lines to a terminal or exit codes:** `copilot_guards.py`,
  `host_validate.py`, `hosts.py`, `host_registrations.py`, `feedback.py`, `door_report.py`,
  `ratchet.py`, `kern_names.py`, `fleet_settings.py`, `cold_run.py`, `commit_checks.py`,
  `hygiene.py`, `public_check.py`, `se.py`, `se_home.py`, `git_door.py`, `process_door.py`,
  `shell_door.py`, `spawn_guard.py`, and the shell scripts (`bootstrap.sh`, `setup.sh`,
  `setup.ps1`, `se_hook.sh`, `se_mcp.sh`, `se_mcp.ps1`, `hosts.sh`, `bash.ps1`,
  `copilot_smoke.sh`). Their findings lines are one-line messages; where one is shown to the
  person it is listed in the inventory under its writer.

## The inventory

### How to read it

- **The person's model, and where it stands.** "Fill the template with content, then call its
  toJSON." Today a filled template's JSON is its fields object: `templates.py fill --fields-json`
  and `check --fields-json --render` take it and render the Markdown, and kern's
  `template.Filled` carries it, sealed, on the bus. The way back, a filled document to its fields
  as JSON, is `templates.parse` in Python and has no command: capability C1 below. Where the JSON
  route of a row says "C1", that is what it takes. The files under `scripts/interfaces/` are
  generated schemas, the shape of that JSON, never data.
- **The person's examples, mapped.**
  - "The questions that come in a deck" are the nine-item checklist inside each `pugh` fence and
    the bless each decision note asks for (D1, D3).
  - "A document with and without a title page" is a switch on a document template (C2, C3). The
    deck (D5) and the documentation pages (P1 to P5) both need it. With it, a deck is the
    document template `decision-deck`, its title page switched on. Its register holds `decision`
    nodes, each nesting the `pugh` block, and the `pugh` block holds the questions.
- **Trivial** means the engine at `55bbca5` holds the shape and the output stays byte for byte the
  same (a check: the same findings). Each trivial row names its proposal, T1 to T14. Every other row
  names the capability it waits for (C1 to C14) or the output that would change.
- **Where** gives `file:lines` at `55bbca5`. "Agent text" means the lines of `src/` that state
  the same shape in prose.

### The decision deck and its notes

| # | Shape | Where | Template it becomes (kind; parent; nested; switches) | JSON route | Migration test | Trivial? |
|---|---|---|---|---|---|---|
| D1 | A decision note: `obs: {bless: pending}` only when it asks; `# <decision>`; `## Current situation`, `## The problem`, `## What others do` in order; the `pugh` fence; tabs after it | `scripts/deck.py:263-293` (`sections`, `_named_sections`, `_explains`), `:344-360` (`_refusal`: no bless, unexplained, no chapter asks); `templates/decision.md:1-52`; agent text `src/skills/decision/SKILL.md:23-37,70-75` | `decision` (document; parent `decision-deck` D5; nests `pugh` D2; switches: bless asked or a record, the `#` title). Today `decision@2.0.0` holds the three sections and the options node. `deck.py` reads only their headings from it (`:270`), and checks their order on obs's built nodes and the bless with its own code. | obs's Document, `json.loads` at `deck.py:98`, copied to `<deck>.document.json` at `:115`; via the template, C1 | `tests/test_templates.py:1627-1638` already compares `templates.verdict(..., "deck.build")` with `deck._explains` over `test_deck.DECKS`; the refusal text is pinned at `tests/test_deck.py:135-153`; a parse and render of `references/decision-deck.md` gives the note back | No. The verdicts agree, but the refusal changes: the engine gives one finding per section, `deck.py` one combined line. The bless needs C3 and C8, the title C2. Render adds SE's markers and drops the `obs:` front matter (shown by a parse and render of the worked example). |
| D2 | The `pugh` fence: `context`, `concern`, `criteria`, `datum`, `candidates` (`key`, `label`, `short`, `what`, `marks{mark, because}`, `wins`, `losses`, `success`), `chosen`, `checklist` | `deck.py:296-341` (`pugh_problems`, its Go port in `components/template/checkers.go`), `:204-260` (`_warnings`: no `success`, a mark without `because`, cross-naming); agent text `SKILL.md:38-68` | `pugh` (block, fence `pugh`; parent `decision`; nests the checklist D3). Today an adapter, `checker: deck:pugh_problems` (at least one criterion, at least two candidates). The warnings are made by hand and run in `build` alone. | inside obs's matrix, `chapters[].content[pugh].attrs.matrix`; via the template, none until C10 | the adapter: `test_deck.py:815-827`, `test_templates.py:2143-2152` (the same findings today); the warnings: `test_deck.py:178-185`, `:349-372`, `:156-160` | The adapter part is done. The rest is not: there is no data model of a fence's YAML (C10) and no rule across items (C12). The adapter input `sections` hands over `pugh` nodes with empty `attrs` (`templates.py:3205`), so the warnings cannot be wrapped as they stand. |
| D3 | The nine-item checklist, the deck's questions: `- item / answer / pass / options`, in a fixed order; only items 3, 4, 6, 8 and 9 name letters | written in `src/skills/decision/references/decision-deck.md:75-103`; agent text `SKILL.md:91-108,67-68`; checked only on the skill text, `tests/test_agent_definitions.py:823-853` | a field of `pugh`, its items a fixed choice of nine in order, `options` allowed only on items 3, 4, 6, 8 and 9 | inside obs's matrix | render the worked example's checklist and compare it with `decision-deck.md:75-103` | No: C10. The `checklist` kind writes `- [x] text` (`templates.py:2277-2280`), not obs's entries. |
| D4 | The build's warnings and refusals (`deck: warning: <note>, option <L>: …`, `… ask for no bless; …`, `… do not explain …`) | `deck.py:100-101,106,116,219-226,257-259,302,310-312,347-359`; pinned at `test_deck.py:139-153,182-185,349-372,815-827` | interfaces `deck-warning` and `deck-refusal`, a `case` per reason | none | the pinned lines in `test_deck.py` | No: the texts name one field twice ("has no `{key}:`; write its {key}"), and a message names each field once, so the wording changes. |
| D5 | The deck's manifest: `title:` front matter, one `- [[note\|Label]]` per chapter, `obsHtml: {layout: screens}` added unless the author set a layout | `deck.py:163-197` (`_screens`, YAML edited by line); agent text `SKILL.md:150-151` | `decision-deck` (document, a file; its register holds `decision`, record and tasks notes; switches: the title page, the default layout) | obs's Document `manifest`, recorded in `tests/recorded/decision-deck.txt` | `tests/test_recorded_outputs.py:26-36` against `tests/recorded/decision-deck.txt`; `test_deck.py:374-386` | No: C8 (obs's keys written and merged), C3 (a default unless set), C5 (the link list from the entries). |
| D6 | Record and tasks chapters: a record without bless or fence; tasks "Task 1 of 2", each with what, where and what it unblocks | agent text `SKILL.md:136-140,147-148`; fixture `RECORD` at `test_deck.py:66`; nothing checks them | `deck-record`, `deck-tasks` (documents; parent `decision-deck`) | none | no tasks fixture exists; one is written first | No: C4 ("Task 1 of 2"), C5. |
| D7 | `deck.py answers`: `<chapter>: <verdict>` lines, each with indented lines for the comment, weights, marks, vetoes, lifts, datum, rulings and winner | `deck.py:376-421`; pinned at `test_deck.py:426-464,793-812` | interface `deck-answers` (snippet) | input `json.loads` at `deck.py:426`; output text only | `PAYLOAD` at `test_deck.py:388-397` and its exact lines | No: rows nested three deep (C5), conditional lines (C3). |
| D8 | The page's data, `globalThis.seDeck = Object.freeze({title, decisions})` | `deck.py:120-127`; `test_deck.py:499-511` | at most the schema of what `deck_answers.js` reads | `json.dumps` at `:126` | `test_deck.py:499-511` | No: a script, not a message (C13). Low value. |
| D9 | `deck_look` findings and summary (`look: <chapter> (<views>): <element>: <what>`) | `scripts/deck_look.py:123-160,188`; `tests/test_deck_look.py:40-165` | interfaces `look-finding`, `look-summary` | input `json.loads` at `:171`; output text | the expected lines of `test_deck_look.py` | No: a JavaScript error of several lines or spaces would be folded by `interfaces.line` (`interfaces.py:76-79`), an output change no test covers (C9). |
| D10 | The field report's `## Decisions` table, which `decision_rows.py` reads across landings | `scripts/decision_rows.py:51-69,95-166` (parse), `:230-255` (text), `:211-227` (JSON); `.github/pull_request_template.md:58-63`; `tests/test_decision_rows.py:30-87,132-165` | a `decisions` table field of `field-report` (W9), plus interface `decision-rows` | `json.dumps` at `decision_rows.py:311`; via the template, C1 | `test_decision_rows.py:152-165` (JSON), `:132-149` (text) | No: C6, and `field-report` has no fields yet (W9). Note: `SKILL.md:110-119` gives an agent's own decision a full decision note, while the field report records it as a row of four cells, two shapes for one thing. |

### The retro family

| # | Shape | Where | Template it becomes (kind; parent; nested; switches) | JSON route | Migration test | Trivial? |
|---|---|---|---|---|---|---|
| R1 | The retro's report, its closing comment | `scripts/retro.py:1817-1869`, checked again at `:1970-1974` | `retro` (document) covers its sections today. Still made by hand: the title `# Retro #N: the report`, `REPORT_MARKER` first and `DOC_MARKER` last (`:1868-1869`), and the `collect` and `decisions` values written as fixed prose (`:1848-1860`). | none: its data is in the linked doc | `tests/test_retro.py:1260` (the filed comment, `:1298-1306`), `:761`, `:805` | No: C2, C4. |
| R2 | The retro's draft | `retro.py:1352-1356,1535-1562`; agent text `src/agents/retro.md:47-53` | `retro-draft` (document), or a draft mode of `retro`. By hand today: its title, no markers, an instruction comment above each body, the judging note and the fenced block. | `json.dumps(found.data())` at `:1548`; `collect --json` at `:2043` | `test_retro.py:500`, `:1260` (`:1271-1289`) | No: a render that keeps the instruction comments and writes no marker (C11), C2, C4. |
| R3 | Step 2, collect: the sizes table, previous findings, classes measured again, landed issues, rule checks, metrics, breaking changes, ad hoc components and scripts, the field reports' answers, planning misses | `retro.py:1425-1517` with `:1565-1588,1035-1046,1414-1422,1591-1610,1613-1627,1292-1310` | `retro-collect` (block; parent `retro`, the `collect` node; one `###` part each; switches: a previous retro or none, `--signals`, `--refusals`, `--sessions`) | in `data()` and `extras()`, `:2043` | `test_retro.py:500,994,1030,1038,1060,1092,1255,1319,1398,1414` | No: C3, C6, C4 (headings with values, "The findings of retro #864"), C5. |
| R4 | Step 3, the timeline tables; step 4, the matrix | `retro.py:1369-1411`; chapters `:578-593` | `retro-timeline`, `retro-matrix` (blocks; parent `retro`) | `data()["chapters"]`, `:571` | `test_retro.py:1275-1287` | No: C6, with columns taken from the data. |
| R5 | Step 5, the classes and their findings | `retro.py:1827-1844,1788-1814,1520-1532` | `retro-class` (entry; a register under `retro.classes`, nesting `retro-finding` entries) | the block's `classes` and `findings` | `test_retro.py:1303`, `:761` | No: C5 (`#### {name} ({count})` per class, sorted by home), C7 (`Cause:`, `Fix:`). |
| R6 | The retro's judged block, the data under `<!-- se:retro-yaml -->` | `retro.py:1669-1730` (`judgment_problems`), `:596-611` (`read_block`), `:1733-1757` (`judged`); restated at `:1549-1561` | `retro-judgment` (block; adapter `json_after: "<!-- se:retro-yaml -->"`, `checker: retro:judgment_problems`, `result: problems`, a `when` that the data is an object). The retro-number check stays in `judged`. | it is JSON already | the adapter's problems equal `judgment_problems(read_block(draft))` on the drafts of `test_retro.py:705,728,1203`. Tried in the scratch prototype: the same problems, each prefixed `retro-judgment: ` as every adapter's finding is (the `pugh` adapter's too) | **Yes, T8.** |
| R7 | `retro due`, one countdown line per kind | `retro.py:2065-2077` | interface `retro-due` (snippet; `rows` `{kind}: {counted} {start}, {days} days; {state}`, its cells computed by the code as today) | `asdict` at `:2101` | `test_retro.py:479` | **Yes, T10.** |
| R8 | The report's part label, `_Part {index} of {total} of the report of retro #{number}._` | `retro.py:1892-1893` | interface `retro-part` (message) | none | `test_retro.py:805` | **Yes, T11.** |
| R9 | The retro doc marker, `<!-- se:retro-doc {sha} {path} -->` | `retro.py:124-125` (`DOC_MARKER`, `DOC_PATTERN`) | interface `retro-doc` (message); reading stays `DOC_PATTERN`, which is stricter than the interface's `.+?` | none | `test_retro.py:761,868` | **Writing, yes, T12.** |
| R10 | A finding's reference, `retro\|overhaul #<n> finding <k>`, which SE writes by hand into each work issue it files from a finding | spelled inside the reports' prose at `retro.py:1850-1853`, `overhaul.py:1086-1091`; found by `FINDING_REFERENCE` at `retro.py:132`, `overhaul.py:565`; agent text `src/agents/retro.md:62-63`, `src/agents/se.md:123-124,130-131` | interface `finding-ref` (message; `kind` a choice of retro and overhaul) | none | `test_retro.py:868`, `tests/test_overhaul.py:653` | **Writing, yes, T13.** Finding it stays a search in free text. |
| R11 | "Not delivered", read out of field reports | `retro.py:442-446,476-485` | a `not_delivered` field of `field-report` (W9) | none | `test_retro.py:509` | No: `field-report` has no fields yet (W9). |
| R12 | The overhaul's report | `scripts/overhaul.py:1054-1106` | `overhaul` (document) covers its sections. By hand: the title and `REPORT_MARKER` (`:1106`), the verdicts table (`:1062-1068`), the findings with their "what follows" prose (`:1069-1091`), the facts' marker and JSON (`:1101-1103`) | `json.dumps(block)` at `:1103` | `test_overhaul.py:597` | No: C2, C6, C4. |
| R13 | The overhaul's draft: the "since" line, the rule book (`(N rules)`, a bullet per rule), the retros and previous findings tables, the facts, the two question nodes, the judging note, the block | `overhaul.py:840-923` (only the questions, `:905-908`, come from templates) | `overhaul-draft` (document; nests `overhaul-facts` R16, `standing-questions`, `overhaul-questions`) | `:909`, `--json` at `:1148` | `test_overhaul.py:358,376` | No: C5, C6, C4, C2. |
| R14 | The overhaul's question check: sections cut out by regular expression, each fix rewritten from `## ` to `### ` | `overhaul.py:931-956` | `check` of `overhaul-draft`'s question fields alone | none | `test_overhaul.py:642` (it matches the message text) | No: C14, and the message text changes. |
| R15 | The overhaul's judged block | `overhaul.py:964-1023`, `judged` at `:1026-1051` | `overhaul-judgment` (block; adapter `json_after: "<!-- se:overhaul-yaml -->"`, `checker: overhaul:judgment_problems`) | JSON already | the same comparison as R6 on `test_overhaul.py:562,579`; tried in the prototype | **Yes, T9.** |
| R16 | The overhaul's facts, `# Overhaul facts` and nine lists | `overhaul.py:508-533` | `overhaul-facts` (document; nested in `overhaul-draft` and the report) | `asdict` at `:1165` | `test_overhaul.py:136,152` | No: C4 (headings with values, "Lines of code and of tests ({total} and {tested})"), C2, "none" for an empty list, no markers (C11). |
| R17 | The story deck and its slides, and their check | `scripts/story_check.py:99-213`; skeletons `components/render/story/template/slide.md` and `deck.md` | `story-deck` (document, a file; a register of slide links), `story-slide` (entry; `part` a choice, title, claim, evidence, a fixed "not yet run" block) | none | `tests/test_story_check.py:66-175` | No: C8, C12 (the order of parts across slides: problem, start, one to six steps, result), C4. An adapter is no shortcut: the check reads the manifest and the other notes. |
| R18 | The Timeline's vault: manifest, one note per entry, the `.base` view | `scripts/timeline.py:464-558` | `timeline-manifest` (document), `timeline-entry` (entry) | the snapshot, `json.dumps` at `:664`; the base at `:552` | `tests/test_timeline.py:135,162,381` with `tests/fixtures/timeline-planned.json` | No: front matter written from data as JSON values (C8), prose with values (C4), and a file template adds `derived_from` (an output change). |
| R19 | The input log: a file per turn, a line per turn in the index | `scripts/input_log.py:206-219,252` | interfaces `input-turn`, `input-index` | none | `tests/test_input_log.py:103,188` | No: the index line folds whitespace inside `first` (C9); a turn's file spans lines (C9). |
| R20 | Metrics: the line `Metrics: {json}`, the record, the report of top spenders and overruns | `scripts/metrics.py:155-157,93-103,231-265` | interface `metrics-line`, snippet `metrics-report` | the record, written at `:122` | `tests/test_work_tickets.py:2431-2490` | No: a JSON value's strings may hold whitespace runs, which fold (C9); optional header parts (C3). |
| R21 | `session_cost.py` and `transcript_signals.py` text reports | `scripts/session_cost.py:337-367`, `scripts/transcript_signals.py:649-663` | snippets | `json.dumps` at `session_cost.py:321-322`, `transcript_signals.py:645-646` | `tests/test_session_cost.py:143,269`, `tests/test_transcript_signals.py:199,213` | No: rows nested in blocks (C5). |
| R22 | The start greeting, read back by hand | `transcript_signals.py:94-96` (`GREETING`) | `interfaces.read("boot-report", …)` | none | `test_transcript_signals.py:397` | No: the regular expression accepts "1 skill" and older greetings without the components table; the template's message has neither, so old transcripts stop matching. |

### The documentation, the plugin layout, guidance and the rule book

| # | Shape | Where | Template it becomes (kind; parent; nested; switches) | JSON route | Migration test | Trivial? |
|---|---|---|---|---|---|---|
| P1 | The three layout pages `docs/skills.md`, `docs/rules.md`, `docs/sub-agents.md`: the generated notice, `# <title>`, an intro with counts, a two-column table | `scripts/se_plugin.py:673-681,699-717,729-752` (`PAGES`, `inventory`, `_cell`, `pages`); its docstring `:55-60` | three interfaces, snippets: `skills-page`, `rules-page`, `sub-agents-page`. Each has a `notice` line field, its fixed title, its fixed intro with count fields, the table's head, and `rows` `` \| `{name}` \| {text} \| ``. `se_plugin.py` keeps escaping `\|` in the cells. | none (`se_start.py:104` reads `layout_inventory`); via the template, its schema in `scripts/interfaces/` | in the scratch prototype, `interfaces.text` of each, plus `"\n"`, equals `se_plugin.pages(layout_inventory(ROOT))` and the committed page byte for byte (all three); `tests/test_se_plugin.py:41,818-834,893` hold the pages | **Yes, T1.** `interfaces.line` folds whitespace as `_cell` does. |
| P2 | The rule book's shape and its check: `## <prefix>: <title>` sections, `### <id> <name>` rules, a lead sentence, `- **Why:**`, `**Without it:**`, `**Prevents:**`, `**Implementations:**`, `**Related:**`, `**Retired:**` | `src/skills/work-model/references/rules.md:9-50`; `scripts/rule_book.py:26-38,81-199` | `rule-book` (document; a register of `rule-section` entries, each a register of `rule` entries) | none (a `Rule` dataclass) | the fixtures of `tests/test_rule_book.py:49-144` and SE's own book (`:149`), comparing findings | No: C5 at document level, C7, C4, C12 (unique ids, `Related` ids exist, prefix matches section, a retired id never reused). An adapter needs a wrapper, since `check` answers lines and a judgment list, not texts. |
| P3 | The rule book's documentation page and a note per rule | `rule_book.py:202-309`; `scripts/build_docs.py:279-312` | `rule-note` (document; front matter `title`, `kind`, `name`, `section`, `why`) | front matter values by `json.dumps`, `rule_book.py:218-220` | `test_rule_book.py:158-184`, `tests/test_docs.py:125-163` | No: C8, C4 (a fixed `base` fence). |
| P4 | The upgrade guide `docs/upgrading.md`: `## <name> <version>` sections of `### <title>` changes, each `- **Change:**`, `- **Steps:**`, `- **Check:**` | `docs/upgrading.md:55-70,316-318`; `scripts/upgrade_guide.py:27-30,63-98` | `upgrade-guide` (document with a fixed head; a register of `upgrade-section` entries, each a register of `upgrade-change` entries; a switch for a minor release's section) | none | parse `docs/upgrading.md` and compare with `upgrade_guide.read`; `tests/test_upgrade_guide.py:56,68,84,103` | No: C5, C7, C4. A template's check would add findings today's code does not make (Change, Steps and Check are unchecked). |
| P5 | The README's command reference: a `#### <group>` per component, a wrapped paragraph, a table of commands | `README.md:2094-2270` (since moved to `docs/work-commands.md`); `scripts/se_components.py:410-423` (`REFERENCE_WIDTH` at `:107`); spliced by `scripts/work_tickets.py:13032-13061,13151-13159` | `command-reference` (block; one entry per component) | the data is `component.toml`, read by kern's catalog | render SE's catalog and compare with the README block; `tests/test_work_tickets.py:1392-1407,491` | No: C5, C6, wrapping at 100 columns, and begin and end markers that are not `render`'s. |
| P6 | Generated non-Markdown files: `components/*/component.toml`, the plugin's JSON manifests and hooks, `tests/guidance-pins.yaml`, the `se component add` scaffolds, workflow copies | `se_components.py:160-185,362-394`; `se_plugin.py:530-531,586-631`; `se_guidance.py:493-547`; `scripts/se_component.py:34-74`; `scripts/se_workflows.py:147-180` | none: their format is the reading program's | they are TOML, JSON or YAML | — | No: C13, which this survey recommends the engine leaves out. |
| P7 | The generated-file marker, `Code generated by {generator} from {source}. DO NOT EDIT.` | `scripts/generated.py:56-66,112-160` (`WORDING`, `SYNTAXES`, `PATTERNS`) | interface `generated-marker` (message); the comment syntax stays `SYNTAXES`; reading keeps `PATTERNS`, stricter than `.+?` | none | `tests/test_generated.py:55` | **Writing, yes, T7.** |
| P8 | Agent and skill front matter: `name`, `description`, `claude.`/`copilot.` keys, skills from se.toml, `disable-model-invocation` on drafts | `se_plugin.py:317-346,480-502`; `scripts/agent_lint.py:19-35,62-88` | `agent`, `skill` (documents) | none | the generated `agents/*.md` and `skills/*/SKILL.md` through it, comparing findings; `tests/test_se_plugin.py:362,371,388,411,867`, `tests/test_agent_lint.py:27-80` | No: C8, C2, C3 (each agent has its own sections), and the checker needs the file's path (C12). |
| P9 | Guidance notes: front matter `name`, `description`, `tags`, `overrides`; `implements <path>` fences | `docs/guidance.md:29-60`; `scripts/se_guidance.py:7-24,117-121,229-360` | `guidance-note` (document) | `collect --json`, `se_guidance.py:803` | `tests/test_guidance.py:157,236,280` | No: C8, tags taken from folder names, checks across files (C12). |
| P10 | `se_guidance collect`'s answer: `## <name>`, a line of path, depth and tags, the body, in pages | `se_guidance.py:668-750` | snippet `guidance-collect` | `--json` | `test_guidance.py:105,372,412,443` | No: C5 and pagination. |
| P11 | The template note `template_import.py` writes | `scripts/template_import.py:234-256` | it writes templates; its shape is the engine's own | none | `tests/test_template_import.py:90` | No: C8 (a `fields` list from data). |
| P12 | The manifest `docs.md` and the build's front matter edit | `docs.md:1-25`; `build_docs.py:315-363` (`without_verdict`) | obs's template-manifest form, with the title-page switch | obs's Document, `--document` at `build_docs.py:236` | `test_docs.py:360-371` | No: it is written by hand, with no generator to compare against, and C8. |
| P13 | Messages agent text states and no code writes: `review of PR #<n>: <verdict>, <comment URL>`, `<retro\|overhaul> #<n> closed: <report link>` | agent text `src/agents/reviewer.md:80-82`, `src/agents/retro.md:61` | interfaces `review-done`, `run-closed` (messages) | none | each template's example renders the line its agent text states | **Yes, T14.** |
| P14 | The integrator's report per integration | agent text `src/agents/integrator.md:291-295` | snippet | none | none: no code writes it | No: rows of statements, C3. |
| P15 | `**Component kinds:**` in a field report | `scripts/component_versions.py:29-31,62-89` | already inside the `field-report` adapter's checker (`work_tickets.py:5434`) | none | — | Already done. |

### work_tickets.py and the fleet's texts

| # | Shape | Where | Template it becomes (kind; parent; nested; switches) | JSON route | Migration test | Trivial? |
|---|---|---|---|---|---|---|
| W1 | A local ticket, `# <id>: <title>` then Design, Scope, Dependencies, Acceptance, Evidence | `scripts/work_tickets.py:419-457` (`create_ticket`), `:289-300,351-369` (read), `:487-501,660-665` (refusals) | `queue-ticket` (document, a file, `.se/work/{todo,held,done}/*.md`) | none | `tests/test_work_tickets.py:1076,1101,1159` | No: C2 (the first line is the `#` title `read_ticket` reads), C4 ("Link to the approved design owner."), an empty `## Evidence` that `render` leaves out (C3), a rule that holds only in `done`. |
| W2 | The tickets intake writes, `r<n>-<slug>` and `delivery` | `work_tickets.py:1889-1945,1971-1980` | `queue-ticket`, filled from the work issue's fields | none | `tests/test_work_ticket_issues.py:366,994,626` | No: W1's, plus C4 (prose with values), C3 (discovery), C5 (a line per owner step). |
| W3 | The discovery evidence index, `# Discovery evidence` and a row per probe | `work_tickets.py:264-267,284-285` | snippet `discovery-evidence` | none | `test_work_ticket_issues.py:626,645` | No: a command with whitespace runs is folded (C9); today rows are appended one at a time. |
| W4 | A note's `Disposition: <text> (backlog-ref: <ref>)` | `work_tickets.py:406-411,372-383`; agent text `src/skills/work-model/SKILL.md:695` | interface `disposition` | none | `test_work_tickets.py:1240` | No: an optional suffix (C3). |
| W5 | The open points inside "Changes after filing" | `work_tickets.py:1769-1790,51-53,1753-1766` | block `open-points`, a node inside `work`'s `changes_after_filing` | none | `tests/test_templates.py:688`, `test_work_ticket_issues.py:7157`, `tests/test_review.py:344` | No: a node bounded by markers inside a list field, numbered after another field's last number. |
| W6 | Editing a work issue's `## Blocked by` | `work_tickets.py:4272-4287` (a regular expression) | `parse(work, body)`, then `blocked_by` extended, then `render` | none | `test_work_ticket_issues.py:1797` | No: `render` writes the markers into the body (C11); in a routed body the section sits at `###`. |
| W7 | The beat marker and `beat.yaml` | `work_tickets.py:4531-4565,137-138,4685-4699` | a marker the engine places; snippet `beat-record` | none | `test_work_ticket_issues.py:8863,8794,8890` | No: placement after the leading markers, an optional `error:` line (C3). |
| W8 | The field report's draft, filled by string replacement from `.github/pull_request_template.md` | `work_tickets.py:5322-5355,5315-5319`; the standing questions at `:2421-2430` (already `templates.sections`) | `field-report` (document): header label fields (work issue, branch, result, tested against, tip, release kind, component kinds, re-integration kind), its sections, the `standing-questions` node, an owner-step switch | none | `test_work_ticket_issues.py:737,781,797,496,994,6848` | No: C7 (labels sharing one line), C6, C4, C3. |
| W9 | The field report's check and the header regular expressions that read it | `work_tickets.py:5384-5470,3058-3123`, patterns `:88-99` read at `:3149-3157,5568-5573,5633-5641,6660-6665`; repeated in Go, `components/template/checkers.go:471-556` | `field-report`'s fields with `required`, `choice` and `exact_heading`, replacing the patterns by `parse`; the cross-document parts (evidence against the issue, owner steps, breaking against the kind, the git guard) stay a checker | none; C1 | identical findings on `tests/test_templates.py:1506` (`field_report_variants`) and `test_work_ticket_issues.py:893,948,829` | No: C7, C6, a rule that a section holds `None` alone, and the finding texts change. |
| W10 | The work pull request's description: `Fixes\|Refs <issue>`, a blank line, the report between its markers | `work_tickets.py:3639-3648,2448-2465`; read by `scripts/pr_issues.py:61-80` | `work-pull-request` (document; a keyword choice, the issue line, a `field-report` node between its markers) | none | `test_work_ticket_issues.py:4810,4874`, `tests/test_templates.py:1759`, `tests/test_pr_issues.py:121,132` | No: a line before the markers that is no section, a marker pair around a node. |
| W11 | The routing block of an outside issue | `work_tickets.py:6472-6485` (`routed_body`, the `--routing-file` path) beside `routed_fields` `:6488-6500`, which renders `routed` | one path: the routing file parsed into `routed`'s fields, then rendered | none | `test_work_ticket_issues.py:6675,6712,6879` | No: with `[templates] enforce` off the hand path's output differs (Package kind moves into field order, unknown sections are placed again). |
| W12 | The Started and Claim-undone comments | `STARTED_COMMENT` at `work_tickets.py:4915` (used at `:4849,4933`), `UNCLAIMED_COMMENT` at `:4486-4488` (`:4521`); read by prefix at `:4515-4517`; agent text `SKILL.md:67,619,629`, `src/agents/integrator.md:239` | interfaces `started-comment`, `claim-undone` (messages); the readers keep their prefix | none | in the prototype, `interfaces.line` plus `"\n"` equals the `.format` of each; `tests/test_work_ticket_issues.py:2687,2732,2928`, `tests/test_rest_commands.py:224` | **Yes, T3.** |
| W13 | The Started comment SE writes by hand when it starts a worker in the cloud, `Started: worker session <id> on branch <b> (claimed on origin, from main at <sha>), integrator <id>. …` | no code: SE wrote it through the GitHub tools, as on #1884; agent text `src/skills/catch-up/SKILL.md` and `src/agents/se.md` describe the start | the same `started-comment`, its session and integrator a switch | none | the comment on #1884 against the template | No: two shapes of one comment, joined only with C3. |
| W14 | Twin and duplicate comments | `work_tickets.py:5833-5844,5861,6322` | snippet `twin-comment`, interface `duplicate-comment` | none | `test_work_ticket_issues.py:6732,6854` | No: the duplicate's issue field holds a placeholder (`Later`) that `:6322` replaces after writing, which the schema would have to accept. |
| W15 | The release commit, its stated kinds and the `Release-kind:` trailer | `work_tickets.py:3463-3466,3283-3285,3126-3133`; read at `:3015,3020,3106-3110,3314` | interface `release-trailer`, `Release-kind: {kind}`, `kind` a choice of the release kinds; snippet `release-commit` | none | `tests/test_releases.py` (`:451` and the `Release-kind` lines) | **The trailer, yes, T6.** The commit message is not: its optional paragraphs need C3. |
| W16 | The delivery notice and `escalate`'s escalation | `work_tickets.py:11790-11797,6630-6645` through `interface_message` (`:6618-6625`) | `delivery-notice`, `escalation` | the generated schemas | `tests/test_interfaces.py:115` | Already done. |
| F1 | The escalation line, written by hand in three more places | `scripts/review.py:680-682`, `work_tickets.py:9724-9725` and `:10233-10235` (its prefix `after these steps, ` stays outside) | `escalation`, through `interface_message` | `scripts/interfaces/escalation.json` | in the prototype, `interfaces.line` of the template equals `review.py`'s line; `test_review.py:364`, `test_work_tickets.py:1664`, `test_work_ticket_issues.py:1155` | **Yes, T2.** |
| F2 | `queue` and turn-start's listing `escalated #N <title> <url>` | `work_tickets.py:12546,12632` | none: a listing | none | — | No change proposed, but the line matches `escalation`'s `marker_pattern` (`escalated #.+: .+`) wherever a title holds ": ". |
| F3 | The "Integration stopped" comment | `work_tickets.py:8556-8561`; read by `retro.py:166` | interface `integration-stopped` | none | `test_work_ticket_issues.py:5346` | No: the reason spans lines (`:9662-9668`), and a trailing newline (C9). |
| F4 | The closing comments, "Integrated in …" and "Landed on …" | `work_tickets.py:9671-9692,7988-8003`; read by `retro.py:170-172` | snippet `closing` | none | `test_work_ticket_issues.py:7220,3026,7335`, `test_retro.py:185` | No: four optional "Stays open" lines (C3), a list inside a sentence (C4). |
| F5 | The landing description | `work_tickets.py:8155-8165`, its metrics line checked at `:9441-9457`; markers read by `scripts/ci_reuse.py:43`, `retro.py:172`, `.github/workflows/check.yml:119` | `landing` (today an adapter of its lines) as a snippet | the metrics line | `tests/test_templates.py:1380-1431`, `test_work_ticket_issues.py:7833`, `tests/test_public_check.py:1868` | No: an optional metrics line (C3), a trailing newline (C9). |
| F6 | The review's verdict comment and its JSON block | `review.py:542-574`; parsed back by `scripts/review_gate.py:126-142` | `review` (document; verdict, acceptance, findings, clean, what follows, the JSON block) | `json.dumps` at `review.py:559` | `test_review.py:330,364,376`, `tests/test_review_gate.py:88` | No: a heading with values (C4), `###` per finding (C5), items of several lines, the JSON block from the fields (C10). |
| F7 | The decline comment on the work issue, `Declined by the review of pull request #{number} ({url}): …` | `review.py:575-580`; read by `retro.py:168` | interface `review-declined` (message) | none | `test_review.py:364` | **Yes, T4.** One line of fixed prose after the fields; the code adds `"\n"`. |
| F8 | A review's open point | `review.py:424-428` | interface `open-point` | none | `test_work_ticket_issues.py:7157` | No: evidence of several lines folds (C9). |
| F9 | The review's brief | `review.py:291-362` | `review-brief` (document; switchable "Withheld" and "Claims" sections) | `--json`, `Brief.data()` at `:215` | `test_review.py:108,126,455` | No: C2, C4, C5, C3. |
| F10 | The refs request, dry-run and applied comments | `work_tickets.py:10191-10308` | three snippets | none | `test_work_tickets.py:1544-1723,3118` | No: git's lines carry runs of spaces (C9), a trailing newline. |
| F11 | Turn-start, queue and the outside-issues line | `work_tickets.py:12536-12666,10971-10974`; agent text `src/agents/se.md:88` | snippet `turn-start` | none | `test_rest_commands.py:274,305` | No: each part is "not read" or a list (C3). |
| F12 | The fleet report with the usage-limit findings | `work_tickets.py:10777-10790`; `scripts/limit_restart.py:174-196` | snippet `fleet-report` | `json.dumps` at `:10781` | `test_work_tickets.py:1818`, `tests/test_limit_restart.py:58,73` | No: rows of two lines, an optional `PR #n`, a "healthy" switch (C3). |
| F13 | The comment `Restarted after a usage limit: session {session}`, which the remedy tells the integrator to write | `limit_restart.py:31,180-183`; read by prefix at `:145-150` | interface `limit-restart` (message); the remedy writes the line through it; the reader keeps its prefix | none | `test_limit_restart.py:73` | **Writing, yes, T5.** |
| F14 | The suite's report, its result and CI's notice | `work_tickets.py:7362-7745` | interface `suite-notice`; snippet for the report | `metrics.note` | `test_work_tickets.py:2748,2874,2895` | No: conditional lines and an optional detail (C3). |
| F15 | The release's landing description | `work_tickets.py:12063-12070`, its title `:12155` | snippet `release-landing` | none | none pins it; a test is written first | No: a trailing newline (C9) and no test. |
| F16 | The start report's neighbours: the session lines, the "for the session" block, the pin rows, the update lines | `scripts/se_start.py:645-855,1673-1832,1894-1975,2028-2061` (the report itself, `:579-642`, already goes through `boot-report`) | snippets `start-handover`, `boot` | the hook's JSON, `:2059-2060` | `tests/test_se_start.py:247,272,281,407,418` | No: switches and verdicts computed into rows (C3). |
| F17 | The doctor's report | `scripts/se_doctor.py:893-902` | snippet `doctor` | `render_json`, `:905` | `tests/test_se_doctor.py:289`, `tests/test_recorded_outputs.py:76` | No: padding `{area:<8}` folds, text of several lines (C9), plurals. |
| F18 | The dispatcher's report | `scripts/dispatch.py:145-167` | snippet | `json.dumps` at `:103` | `tests/test_dispatch.py:77,111` | No: "Startable: none" or rows (C3). |
| F19 | The outside-text envelope, also in `review.py:291-296` | `scripts/outside_text.py:24-26,76-86` | snippet, `> {line}` rows | none | `tests/test_outside_text.py:24,84` | No: an empty line becomes `>` and indentation folds (C9). |
| F20 | The late-push line | `scripts/late_push.py:90-98` | interface, a case for error or warning | none | `test_work_ticket_issues.py:1527` | No: the case names fields that stand in another line, which the snippet rule refuses. |
| F21 | The GitHub plan's text | `work_tickets.py:8430-8443` | snippet | `Plan.data()`, `:8423` | `test_work_ticket_issues.py:4757`, `test_rest_commands.py:325` | No: rows of several lines with JSON inside (C9). |
| F22 | `status` and `close` reports | `work_tickets.py:10899-10950` | snippets | `json.dumps` at `:10902,10939` | the status tests of `test_work_tickets.py` | No: optional lines (C3). |
| F23 | Marker reads in CI and `ci_queue`'s summary | `ci_reuse.py:43-62`; `scripts/ci_queue.py:101-108` | the reads through the templates' `marker_pattern`; a snippet for the summary | none | `tests/test_ci_reuse.py`, `tests/test_ci_queue.py:60` | Not rated trivial here. Its reader judged the marker reads identical but this survey did not check it; the summary needs a trailing newline (C9). |
| I1 | The generated files under `scripts/interfaces/`: `boot-report`, `delivery-notice`, `escalation`, `handover` | written by `templates.py interfaces`; used through `interfaces.write` by `se_start.py:642` and `work_tickets.py:6642,11795`; `handover` is written by SE through the GitHub tools under the template gate | they are the templates' generated schemas, the shape of each message's JSON | the schema; a message's data is the object `interfaces.read` gives | `tests/test_interfaces.py` | Already done. Finding: `interfaces.read` has no caller outside the tests; every reader of these messages parses them by hand (R22, W12, F13). |

### GitHub's own skeletons

| # | Shape | Where | Template it becomes (kind; parent; nested; switches) | JSON route | Migration test | Trivial? |
|---|---|---|---|---|---|---|
| G1 | GitHub's work issue form, written by hand beside `templates/work.md` | `.github/ISSUE_TEMPLATE/work.md` (108 lines); named by `src/agents/se.md:222-224` and `src/skills/work-model/SKILL.md:256` as the sections a routed issue gets | generated from `work` by its draft, with GitHub's `name` and `about` keys in the front matter | none | `templates.py draft work` against the file: the headings differ today, as the form lacks `## Base branch` and `## Changes after filing`, which the template has. The only test, `tests/test_work_ticket_issues.py:6347-6351`, checks that the fleet marker is there. | No: C8 (GitHub's keys), and the output changes. The drift is live: a work issue filed from GitHub's form misses two of the template's sections. |
| G2 | The retro's and the overhaul's issue bodies | `.github/ISSUE_TEMPLATE/retro.md` (75), `overhaul.md` (61); filed by `retro.py:2056` and `overhaul.py:549` through `overhaul.file_run` | `retro-issue`, `overhaul-issue` (documents; `retro` and `overhaul` are their reports, not the issues) | none | the bodies `retro.py new` and `overhaul.py new` file, against the forms | No: C8, and no template holds them yet. |
| G3 | The pull request template, the field report's skeleton | `.github/pull_request_template.md` (86); read as the `field-report` adapter's template (`work_tickets.py:113`, `components/template/checkers.go:471-556`) | generated from `field-report` once W9 gives it fields | none | `field-report --draft` against it | No: W8 and W9 first. |

## Engine capabilities the non-trivial rows need

Each capability is named once, with the rows that wait for it (the inventory's last column). The
person named C1, C2 and C3.

| # | Capability | What it adds to the engine | Rows waiting |
|---|---|---|---|
| C1 | **toJSON of a filled document** | `templates.py json (<template> \| --path FILE) --body-file FILE` prints `parse`'s fields as the object `fill --fields-json` takes, the round trip of the person's model: fill with content, render; read back, get JSON. The tool `templates` answers the same. Today only `parse` in Python does this, and `draft --json` gives the empty fields. | the JSON route of every row; the first step of D10, R11, W9 |
| C2 | **A title line and a title page** | a `title` field rendered as the document's `#` line (today a title is only an issue's title), and a switch between a document with a title page (obs's cover keys in the front matter) and without one | D1, R1, R2, R12, R13, R16, P8, W1, F9; the title page: D5, P12 |
| C3 | **Switches** | a section, a line of a snippet or a front matter key present only where a field or a flag says so, the absent one leaving no line; for example a field-report owner-step section, a retro's sections for a previous retro, the deck's bless | 23 rows: D1, D5, D7, R3, R20, P8, P14, W1, W2, W4, W7, W8, W13, W15, F4, F5, F9, F11, F12, F14, F16, F18, F22 |
| C4 | **Fixed prose with values** | text in a document template's skeleton that the document keeps, and `{field}` inside it and inside headings, as a message line has today ("The findings of retro #{number}", "Task {n} of {total}") | 18 rows: D6, R1, R2, R3, R12, R13, R16, R17, R18, P2, P3, P4, W1, W2, W8, F4, F6, F9 |
| C5 | **Repeated parts rendered from a list** | a register or a node list rendered from a list of field objects, each with a heading built from its fields (`#### {name} ({count})`) and an order; today a register is read and checked, its text kept as it stands | 14 rows: D5, D6, D7, R3, R5, R13, R21, P2, P4, P5, P10, W2, F6, F9 |
| C6 | **Tables** | a `table` field kind: its columns (fixed, or taken from the data), the header, cell escaping, rows parsed back; today only a snippet's `rows` writes one | D10, R3, R4, R12, R13, P5, W8, W9 |
| C7 | **Label fields** | `**Label:** value` on a shared line and `- **Label:** value` bullets as fields, as the field report's header and the rule book use | R5, P2, P4, W8, W9 |
| C8 | **Front matter fields** | fields written into and read from the front matter beside `derived_from`, merged with keys the author set (obs's `bless`, `obsHtml`, a skill's `name`, GitHub's `name` and `about`) | D1, D5, R17, R18, P3, P8, P9, P11, P12, G1, G2 |
| C9 | **Values kept as written** | a snippet field that keeps its whitespace and its lines (`verbatim`, as a document field has), a snippet that ends in a newline, and an empty case that leaves no line | 13 rows: D9, R19, R20, W3, F3, F5, F8, F10, F15, F17, F19, F21, F23 |
| C10 | **Data inside a fence** | a fence node whose YAML or JSON body is fields: the `pugh` matrix with its checklist, the review's JSON block written from the fields | D2, D3, F6 |
| C11 | **Writing a field into a document as it stands** | set one field of an existing document and write the rest byte for byte, with no marker added: the `## Blocked by` edit, a draft that keeps its instruction comments | R2, R16, W6 |
| C12 | **Rules across entries and files** | rules over a register's entries (unique ids, references that exist, an order of kinds) and a checker that is handed the path or the folder | D2, R17, P2, P8, P9 |
| C13 | **Files that are not Markdown** | TOML, JSON, YAML and scripts. This survey recommends the engine stays out of them: their format is their reader's, and a generator plus `generated.py`'s marker already holds them | D8, P6 |
| C14 | **Checking part of a document** | `check` of some fields alone, with the other sections left unread | R14 |

## Proposed work issues, one per trivial row

Each proposal is in the work template's fields (`templates/work.md`). Every one is a `standard`
package, blocked by nothing and changing no release kind beyond a patch, and carries the same user
requirement:

> For the parts of this that are trivial, you can just do them. (24 Nov)

Each proposal's equivalence test renders through the template from today's inputs and compares
with today's output, in the test file its Verification names. T1, T2, T3, T8 and T9 were tried in the
survey's scratch prototype (the inventory's rows say how).

#### T1: layout-pages-from-templates

- **Situation:** `se_plugin.py build` writes `docs/skills.md`, `docs/rules.md` and
  `docs/sub-agents.md` from f-strings (`scripts/se_plugin.py:729-752`).
- **Problem:** the pages' title, intro and table head live in code, beside the template engine
  that owns every fixed text SE shows.
- **Goal:** the three pages are written through three interface templates, and their bytes do not
  change.
- **Approach:** three snippets, `skills-page`, `rules-page` and `sub-agents-page`, each with a
  `notice` line field, its fixed title and intro with count fields, the table's head and a `rows`
  field `` | `{name}` | {text} | ``. `pages` fills them through `interfaces.write` and keeps
  escaping `|` in the cells. Not picked: one snippet with `case` fields for the three intros, as
  each intro names different counts.
- **Design owner:** `docs/templates.md` "SE's templates"; `scripts/se_plugin.py` docstring.
- **Requirements:**
  1. `templates/skills-page.md`, `templates/rules-page.md`, `templates/sub-agents-page.md`, and
     their generated schemas in `scripts/interfaces/`.
  2. `se_plugin.pages` writes each page through `interfaces.write`, plus a final newline.
  3. `docs/templates.md`'s map lists the three templates.
- **Acceptance:**
  - [ ] A test renders each page through its template from `layout_inventory(ROOT)` and finds it
    byte for byte equal to the committed page and to `pages`' output before the change.
  - [ ] `se_plugin.py check` passes with the committed pages unchanged.
- **Verification:** `uv run pytest -q tests/test_se_plugin.py tests/test_interfaces.py`

#### T2: escalation-lines-through-template

- **Situation:** `work_tickets.py escalate` writes `escalated #{issue}: {question}` through
  `templates/escalation.md`. Three other writers build the same line by hand:
  `scripts/review.py:680-682`, `scripts/work_tickets.py:9724-9725` and `:10233-10235`.
- **Problem:** if the template changes, the three hand-written copies stay as they are.
- **Goal:** every escalation line SE writes comes from the `escalation` template.
- **Approach:** each writer calls `interface_message("escalation", issue=..., question=...)`.
  `refs request` keeps its prefix `after these steps, ` outside the message. Not picked: a second
  template for the prefixed line, which is the same message.
- **Design owner:** `templates/escalation.md`; `src/agents/integrator.md` "Escalate and improve".
- **Requirements:**
  1. `review.py`'s decline, `integrate`'s partial delivery and `refs request` write the line
     through the template.
- **Acceptance:**
  - [ ] The pinned lines of `tests/test_review.py:364`, `tests/test_work_tickets.py:1664` and
    `tests/test_work_ticket_issues.py:1155` pass unchanged.
  - [ ] `git grep -n 'f"escalated #' scripts/` finds nothing.
- **Verification:** `uv run pytest -q tests/test_review.py tests/test_work_tickets.py tests/test_work_ticket_issues.py -k "escalat or declin or refs"`

#### T3: started-comments-as-templates

- **Situation:** `STARTED_COMMENT` and `UNCLAIMED_COMMENT` are format strings in
  `scripts/work_tickets.py:4915` and `:4486-4488`.
- **Problem:** two comments that the fleet reads back by their prefix are shaped in code.
- **Goal:** the Started and Claim-undone comments are interface templates, their bytes unchanged.
- **Approach:** messages `started-comment` (`branch`) and `claim-undone` (`started`, `branch`),
  written through `interface_message` plus `"\n"`. The readers keep their prefix match, since the
  start SE writes by hand in the cloud (inventory W13) has a longer form. Not picked: reading
  through `interfaces.read`, which would stop matching that form.
- **Design owner:** `src/skills/work-model/SKILL.md` (claim and start).
- **Requirements:**
  1. The two templates and their schemas.
  2. `start`, `claim` and `unclaim` write through them.
- **Acceptance:**
  - [ ] A test renders each through its template and finds it equal to the old `.format` output.
  - [ ] `tests/test_work_ticket_issues.py:2687,2732,2928` and `tests/test_rest_commands.py:224`
    pass unchanged.
- **Verification:** `uv run pytest -q tests/test_work_ticket_issues.py tests/test_rest_commands.py tests/test_interfaces.py`

#### T4: decline-comment-as-template

- **Situation:** `review.py` writes the decline comment on a work issue from an f-string
  (`scripts/review.py:575-580`), and `retro.py:168` reads it back.
- **Problem:** a text two scripts share is shaped in one of them.
- **Goal:** the decline comment is the interface `review-declined`, its bytes unchanged.
- **Approach:** a message `Declined by the review of pull request #{number} ({url}): the change is
  fundamentally wrong and does not land. The review comment there holds the findings; SE
  re-scopes this issue or takes it to the owner.`, written plus `"\n"`. Not picked: moving
  `retro.py`'s `DECLINED` reader onto `interfaces.read` in the same package.
- **Design owner:** `src/agents/reviewer.md`.
- **Requirements:**
  1. `templates/review-declined.md` and its schema.
  2. `review.escalation` writes through it.
- **Acceptance:**
  - [ ] `tests/test_review.py:364` passes unchanged, and a test finds the template's line equal to
    the old f-string's for the same values.
- **Verification:** `uv run pytest -q tests/test_review.py tests/test_retro.py -k "declin"`

#### T5: limit-restart-comment-template

- **Situation:** `limit_restart.py` tells the integrator, in its remedy, to comment
  `Restarted after a usage limit: session {id}` (`scripts/limit_restart.py:180-183`), and reads it
  back by its prefix (`:145-150`).
- **Problem:** an agent writes the line from prose, and nothing holds its shape.
- **Goal:** the comment is the interface `limit-restart`, and the remedy quotes the line the
  template writes.
- **Approach:** a message `Restarted after a usage limit: session {session}`. The remedy's text
  takes the line from `interfaces.write`. The reader keeps its prefix. Not picked: a command that
  posts the comment, which would be a new behaviour.
- **Design owner:** `docs/fleet.md "Fleet check"`; `scripts/limit_restart.py` docstring.
- **Requirements:**
  1. `templates/limit-restart.md` and its schema.
  2. `limit_restart.py`'s remedy names the line through it.
- **Acceptance:**
  - [ ] `tests/test_limit_restart.py:58,73` pass unchanged.
- **Verification:** `uv run pytest -q tests/test_limit_restart.py tests/test_interfaces.py`

#### T6: release-trailer-template

- **Situation:** `release_trailer` writes `Release-kind: <kind>` (`scripts/work_tickets.py:3126-3133`),
  and `RELEASE_TRAILER_PATTERN` reads it.
- **Problem:** the one line that carries every merge's release kind is shaped in code.
- **Goal:** the trailer is the interface `release-trailer`, `kind` a choice of the release kinds.
- **Approach:** a message `Release-kind: {kind}`, with `choices` from `work_tickets:RELEASE_KINDS`.
  `release_trailer` writes through it. Not picked: the whole release commit, whose optional
  paragraphs wait for C3.
- **Design owner:** `src/skills/work-model/SKILL.md` "Release kind"; `templates/merge-message.md`.
- **Requirements:**
  1. `templates/release-trailer.md` and its schema.
  2. `release_trailer` writes through it.
- **Acceptance:**
  - [ ] `tests/test_releases.py` passes unchanged.
  - [ ] A kind outside the choices is refused by the schema, naming the template.
- **Verification:** `uv run pytest -q tests/test_releases.py tests/test_interfaces.py`

#### T7: generated-marker-template

- **Situation:** `generated.py` writes `Code generated by {generator} from {source}. DO NOT EDIT.`
  from `WORDING` (`scripts/generated.py:63`) inside each comment syntax.
- **Problem:** every generated file's first line is shaped by a constant, beside the engine.
- **Goal:** the marker's words are the interface `generated-marker`, and every generated file's
  first line is unchanged.
- **Approach:** a message `Code generated by {generator} from {source}. DO NOT EDIT.`. `SYNTAXES`
  keeps the comment's opening and closing, and `PATTERNS` keeps reading, as it is stricter than a
  message's `.+?`. Not picked: reading through `interfaces.read`.
- **Design owner:** the guidance note `generated-files-are-marked`.
- **Requirements:**
  1. `templates/generated-marker.md` and its schema.
  2. `generated.py` writes the words through it.
- **Acceptance:**
  - [ ] `tests/test_generated.py` passes unchanged, and `hygiene.py`'s generated check finds no
    drift.
- **Verification:** `uv run pytest -q tests/test_generated.py && uv run python scripts/hygiene.py`

#### T8: retro-judged-block-adapter

- **Situation:** a retro draft ends in a JSON block under `<!-- se:retro-yaml -->`, whose shape
  `retro.judgment_problems` checks (`scripts/retro.py:1669-1730`). No template names it.
- **Problem:** the draft's one machine-read part is a shape no template declares.
- **Goal:** the block is the adapter template `retro-judgment`, and `judged` checks it through
  `templates.check`, with the same problems.
- **Approach:** a block template with no fields, `checker: retro:judgment_problems`, adapter
  `json_after: "<!-- se:retro-yaml -->"`, `result: problems`, and a `when` that holds for an
  object. `judged` keeps its retro-number check and its refusal's wording, taking the problems
  without the adapter's `retro-judgment: ` prefix. Not picked: a template with fields for the
  block, which waits for C10 and C12.
- **Design owner:** `templates/retro.md`; `scripts/retro.py` docstring.
- **Requirements:**
  1. `templates/retro-judgment.md`.
  2. `judged` checks through it.
- **Acceptance:**
  - [ ] A test finds, on each draft of `tests/test_retro.py:705,728,1203`, the adapter's problems
    equal to `judgment_problems(read_block(draft))`.
  - [ ] Those tests pass unchanged.
- **Verification:** `uv run pytest -q tests/test_retro.py tests/test_templates.py`

#### T9: overhaul-judged-block-adapter

- **Situation:** an overhaul draft ends in a JSON block under `<!-- se:overhaul-yaml -->`, checked
  by `overhaul.judgment_problems` (`scripts/overhaul.py:964-1023`).
- **Problem:** as T8, for the overhaul.
- **Goal:** the block is the adapter template `overhaul-judgment`, checked with the same problems.
- **Approach:** as T8, `checker: overhaul:judgment_problems`, `json_after: "<!-- se:overhaul-yaml -->"`.
  `judged` keeps its overhaul-number check and `question_problems`. Not picked: joining T8 and T9
  into one template, as their blocks differ.
- **Design owner:** `templates/overhaul.md`; `scripts/overhaul.py` docstring.
- **Requirements:**
  1. `templates/overhaul-judgment.md`.
  2. `judged` checks through it.
- **Acceptance:**
  - [ ] A test finds, on the drafts of `tests/test_overhaul.py:562,579`, the adapter's problems
    equal to `judgment_problems(read_block(draft))`.
- **Verification:** `uv run pytest -q tests/test_overhaul.py tests/test_templates.py`

#### T10: retro-due-rows-template

- **Situation:** `retro due` prints one countdown line per kind from an f-string
  (`scripts/retro.py:2065-2077`).
- **Problem:** a report the person reads is shaped in code.
- **Goal:** the countdown is the snippet `retro-due`, its lines unchanged.
- **Approach:** a snippet with a `rows` field `{kind}: {counted} {start}, {days} days; {state}`.
  The code computes the cells as today. Not picked: `case` fields for the phrases, which a row
  cannot hold.
- **Design owner:** `scripts/retro.py` docstring (due).
- **Requirements:**
  1. `templates/retro-due.md` and its schema.
  2. `countdown_lines` writes through it.
- **Acceptance:**
  - [ ] `tests/test_retro.py:479` passes unchanged.
- **Verification:** `uv run pytest -q tests/test_retro.py -k due`

#### T11: retro-part-label-template

- **Situation:** a retro report too long for one comment is split, each part ending in
  `_Part {index} of {total} of the report of retro #{number}._` (`scripts/retro.py:1892-1893`).
- **Problem:** the label is shaped in code.
- **Goal:** the label is the message `retro-part`, unchanged.
- **Approach:** the message as it stands, written through `interfaces.write`. Not picked: a
  template for the whole part.
- **Design owner:** `scripts/retro.py` docstring (file).
- **Requirements:**
  1. `templates/retro-part.md` and its schema.
  2. The split writes each label through it.
- **Acceptance:**
  - [ ] `tests/test_retro.py:805` passes unchanged.
- **Verification:** `uv run pytest -q tests/test_retro.py -k part`

#### T12: retro-doc-marker-template

- **Situation:** the retro's report links its committed doc with `<!-- se:retro-doc {sha} {path} -->`
  (`DOC_MARKER`, `scripts/retro.py:124-125`), read back by `DOC_PATTERN`.
- **Problem:** the marker is shaped in code.
- **Goal:** the marker is written through the message `retro-doc`, unchanged.
- **Approach:** the message as it stands. Reading keeps `DOC_PATTERN`, which demands a 40-digit
  sha where a message reads `.+?`. Not picked: reading through `interfaces.read`.
- **Design owner:** `scripts/retro.py` docstring (file).
- **Requirements:**
  1. `templates/retro-doc.md` and its schema.
  2. `retro.py file` writes the marker through it.
- **Acceptance:**
  - [ ] `tests/test_retro.py:761,868` pass unchanged.
- **Verification:** `uv run pytest -q tests/test_retro.py`

#### T13: finding-reference-template

- **Situation:** SE names a retro's or overhaul's finding `retro #<n> finding <k>` in each work
  issue it files from it. The reports' prose spells the form (`scripts/retro.py:1850-1853`,
  `scripts/overhaul.py:1086-1091`), the agents' text states it (`src/agents/retro.md:62-63`,
  `src/agents/se.md:123-124,130-131`), and `FINDING_REFERENCE` finds it (`retro.py:132`,
  `overhaul.py:565`).
- **Problem:** one form is stated in four places.
- **Goal:** the form is the message `finding-ref`, `kind` a choice of retro and overhaul; the
  reports' prose writes it through the template (`finding` given as `<k>`), and the agents' text
  names the template.
- **Approach:** a message `{kind} #{number} finding {finding}`. Finding a reference stays a search
  in free text. Not picked: reading through `interfaces.read`, which matches whole lines.
- **Design owner:** `src/agents/retro.md`; `src/agents/se.md`.
- **Requirements:**
  1. `templates/finding-ref.md` and its schema.
  2. The reports' prose in `retro.py` and `overhaul.py` writes the form through it.
  3. The agents' text names the template instead of spelling the form.
- **Acceptance:**
  - [ ] `tests/test_retro.py:868` and `tests/test_overhaul.py:653` pass unchanged.
- **Verification:** `uv run pytest -q tests/test_retro.py tests/test_overhaul.py tests/test_agent_definitions.py`

#### T14: agent-end-messages-templates

- **Situation:** the reviewer ends with `review of PR #<n>: <verdict>, <comment URL>`
  (`src/agents/reviewer.md:80-82`), and the retro with `<retro|overhaul> #<n> closed: <report link>`
  (`src/agents/retro.md:61`). No code writes either line.
- **Problem:** two messages between sessions exist only as prose, while the delivery notice and
  the escalation are templates.
- **Goal:** both are interface templates, and the agents' text names them.
- **Approach:** messages `review-done` (`pr`, `verdict` a choice of the review's verdicts, `url`)
  and `run-closed` (`kind`, `number`, `link`). Not picked: a command that sends them, which kern's
  door does not offer.
- **Design owner:** `src/agents/reviewer.md`; `src/agents/retro.md`; `docs/templates.md` "SE's
  templates".
- **Requirements:**
  1. The two templates and their schemas.
  2. `reviewer.md` and `retro.md` name the templates.
- **Acceptance:**
  - [ ] Each template's `example` renders the line its agent text states today.
- **Verification:** `uv run pytest -q tests/test_templates.py tests/test_interfaces.py tests/test_agent_definitions.py`

## Proposed backlog issue

One backlog issue, titled `template-engine-growth`, holds the rest in this order. The capabilities
come first, each followed by the rows it frees; a row that needs several capabilities waits for
the last of them. The order puts first what the person named and what the most rows wait for.

1. **C1, toJSON.** The person's model, a small command over `parse`; every row's JSON route uses it.
2. **C3, switches.** The person named it; 23 rows wait for it. It frees D4's rewording, W4, W7,
   W13, W15's commit, F5, F11, F12, F14, F18, F22.
3. **C9, values kept as written.** 13 rows; with C3 it frees most of the fleet's comments: W3, F3,
   F8, F10, F15, F17, F19, F21, D9, R19, R20, F23's summary.
4. **C2, a title line and a title page.** The person named it. With C3 and C8 it frees the decision
   note (D1); with C4 and C5 the retro's and overhaul's reports (R1, R12).
5. **C4, fixed prose with values.** 18 rows: the tickets (W1, W2), D6, R16, P3.
6. **C5, repeated parts.** 14 rows: the deck's manifest (D5, with C8), the answers (D7), the rule
   book and the upgrade guide (P2, P4, with C7), the command reference (P5, with C6), P10, R5, R21.
7. **C6, tables.** With C7 it frees the field report (W8, W9), then D10 and R11, which read it,
   and W10, its pull request's description. The retro's and overhaul's drafts follow (R2, R3, R4,
   R13, with C11).
8. **C7, label fields.** The field report's header and the rule book's bullets (with C6, C5).
9. **C8, front matter fields.** The deck's manifest, the agents', skills' and guidance notes'
   front matter (P8, P9, with C12), the Timeline (R18), P11, P12, R17.
10. **C10, data inside a fence.** The `pugh` matrix and its nine questions (D2, D3), the review's
    JSON block (F6, F9).
11. **C11, writing a field into a document as it stands.** W6, R2, R16.
12. **C12, rules across entries and files.** D2's warnings, the story check (R17), the rule book's
    check (P2), P8, P9.
13. **C14, checking part of a document.** R14.
14. **GitHub's skeletons (G1 to G3)** with C8: generated from their templates, so they cannot
    drift; G1 first, as its drift is live.
15. **The rows whose output changes on purpose, for the person to decide:**
    - W11: one routing path for both enforce settings;
    - W13: SE's own Started comment joining the code's;
    - R22: old transcripts' greetings no longer read;
    - D1's and D4's refusal wording.
16. **Not to do, C13:** TOML, JSON, YAML and scripts (D8, P6) stay their generators', marked by
    `generated.py`.

## Skills and agents that get smaller

Lines of the agents' and skills' text that state a shape a template would hold instead. A
template's field instruction (`says`) is what the fill hands the agent before it writes, so the
text can name the template and stop repeating the shape. Counted at `55bbca5`; "now" means the
template exists today, or comes with a trivial proposal.

| File (lines) | Lines that state a shape | Its template | Count | When |
|---|---|---|---|---|
| `src/skills/decision/SKILL.md` (184) | `23-37` front matter, title, the three sections; `42-43,56-68` the fence's fields and marks; `70-75` nothing before the fence; `96-108` the nine items; `136-140` the tasks | `decision`, `pugh`, `decision-deck` | 51 (75 if the policy of `44-55`, the verdict's wording, effort and the datum, moves into the fields' instructions too) | `23-37` and `70-75` now (`decision` exists); the rest after C10 |
| `src/skills/decision/references/decision-deck.md` (104) | none removed: the whole file is one filled note | `decision` | 0 | it becomes the `decision` template's `example`, replacing the toy one at `templates/decision.md:34-39` |
| `src/skills/work-model/SKILL.md` (1115) | `100-111` the name rule; `154-156` the Planned line; `252-258` the Routing section; `284-292` a pull request names its issue; `695` the disposition line | `work`, `routed`, `landing`, `disposition` | 32 | `252-258` now (`routed` exists); the rest after C3 and C7 |
| `src/agents/worker.md` (209) | `139-141,151-154,161-166` the field report's shape; `193-198` the delivery notice | `field-report`, `delivery-notice` | 19 | `193-198` now; the rest after C6 and C7 |
| `src/agents/integrator.md` (296) | `89-92` the delivery notice; `278-284` the escalation; `291-295` its report's fields | `delivery-notice`, `escalation` | 16 | `89-92` and `278-284` now |
| `src/agents/retro.md` (63) | `43-44` quoting the feedback; `47-53` the draft's steps; `55-57` recording answers and decisions; `61-63` the hand-back and the finding's name | `retro`, `standing-questions`, `run-closed`, `finding-ref` | 15 | `61-63` with T13 and T14; the rest after C4 and C5 |
| `src/agents/se.md` (233) | `50-56` the start report; `123-124,130-131` the finding's name; `222-224` the routing file | `boot-report`, `finding-ref`, `routed` | 14 | `50-56` and `222-224` now; the rest with T13 |
| `src/agents/reviewer.md` (82) | `50-51` acceptance; `74-78` the report's fields; `80-82` the end message | `review`, `review-done` | 10 | `80-82` with T14; the rest after C10 |
| `src/skills/fill-templates/SKILL.md` (74) | `59-60` Not in input; `66-72` the finding line and the README's contents | the engine's own | 9 | now |
| `src/skills/catch-up/SKILL.md` (158) | `53-54` the "Your input needed" heading; `153-158` the handover | `handover` | 8 | `153-158` now |
| `src/skills/update/SKILL.md` (33) | `19-20,23-25` the guide's sections in order | `upgrade-guide` | 5 | after C5 and C7 |
| **Total** (2,551) | | | **179** (203 with the decision policy) | 80 now or with T13 and T14 |

The decision skill shrinks most: about 28 % of it states the note's and the fence's shape.
