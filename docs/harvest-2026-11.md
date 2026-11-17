# Harvest of the older systems, November 2026

This record says what the harvest of 14 Nov 2026 read, what it takes into SE, what it leaves out and why, and the plan that builds what it takes. The plan itself lives in GitHub issues: each open issue carries a line `Planned: yyyy-mm-dd`, and the Timeline shows it on that day. This page is not kept up to date by hand; the issues are.

## What was read

Sixteen readers, with later passes over the design pages, worked through twenty reading units:

- quackitect, the system before SE, in five generations (v1 to v5), as nine units: the code, the design notes and the tooling of each.
- ctrl, a small product built by agents, read for its MCP door, its checks on built output and its record of the owner's words.
- SE itself: its first Go line (13 and 14 Oct, ending at commit ff01204) and SE as it is today.
- Two surveys of the state of the art on 14 Nov: agents with many skills, and systematic engineering, documents and slides.
- Six sets of design pages published between July and October.
- A few smaller repositories, which gave nothing that this plan takes.

Readers proposed about 510 candidate ideas. Grouped by area and merged, they became the counts below. Each area had two lenses: one asked whether SE already has the idea, the other gave the verdict, the value (1 to 5) and the effort. Two adversarial verifiers then checked every area.

| Area | Ideas | Adopt | Adapt | Covered by filed work | Dropped |
|---|---|---|---|---|---|
| copilot-host | 48 | 6 | 19 | 6 | 17 |
| kern-core | 48 | 4 | 27 | 3 | 14 |
| skills | 21 | 0 | 12 | 1 | 8 |
| fleet-process | 42 | 2 | 20 | 2 | 18 |
| docs-obs | 21 | 1 | 5 | 1 | 14 |
| systematic-engineering | 36 | 1 | 19 | 0 | 16 |
| slides | 11 | 0 | 6 | 1 | 4 |
| testing-quality | 30 | 3 | 18 | 0 | 9 |
| install-onboarding | 18 | 0 | 10 | 1 | 7 |
| other | 16 | 0 | 4 | 0 | 12 |
| **all ten areas** | **291** | **17** | **140** | **15** | **119** |
| design-pages (read later) | 93 | 2 | 38 | 3 | 50 |
| design-pages-fleet (read later) | 54 | 2 | 19 | 1 | 32 |

Of the ten areas' ideas, 125 have a part that can be built as a standalone module, and 92 carry a question only the owner can answer. The readers also wrote down the principles the old sources stated: 15 became questions for the rule book, 25 are already in SE and 63 were dropped.

## How the plan was chosen

Three plans were drafted from the same verified result: Monday first, foundations first and capabilities first. Two judges scored them, one through the owner's eyes and one through the integrator's. Both chose the Monday-first plan: it guards Monday's Copilot run, is the most selective and changes nothing the owner installs before the run. This plan is that one, with the judges' grafts and cuts applied and every defect they named fixed. The main fixes:

- Every issue is written in full before it is filed, so no empty spec can be started.
- A planned day holds nothing back, so order is native GitHub blocking links, and the freeze before Monday is a person step that blocks the binary and hook changes.
- Files are listed as bare paths, so the integrator's ownership guard can hold two issues on one file apart.
- Shared files are owned by one issue at a time: switches get one row file per module, host facts are sections of the one data file SE#1154 created, and README.md is edited by one bundle per milestone and by the few issues whose new flags regenerate its command reference.

## The rules the plan follows

- The owner's standing rule of 14 Nov: build standalone modules or code behind a switch that is off by default, pure and agnostic to form. Changes to the whole system (the rule book, role files, process, defaults, what agents are told) wait for the owner. So only module parts become issues; everything else is a question.
- The owner decides through a deck of at most nine questions, each with a recommendation.
- The status view is the Timeline built from GitHub issues, with no agent in between.
- Only the dispatcher files issues. One issue is one squash pull request with a green required check. Issues that touch the same file are ordered by a blocking link.
- Nothing beyond the Anthropic subscription is spent. GitHub is never the centre. kern with NATS stays. Every outside thing has one door, tested once against the real thing and faked elsewhere.

## What is taken, and why

Three harvest modules were filed and landed on 14 Nov while the plan was written: the host limits and size report (SE#1154), the hosts' own validators over SE's layouts (SE#1155) and the list of decisions workers took on their own (SE#1164). The plan builds on them and does not file them again.

### Copilot on Monday

Nothing can be proven against a real Copilot before the owner's own run. These make the run easy to read and build its likely remedies beforehand, each as one setting that is off: a doctor that sees a missing or doubled registration and prints the line that fixes it, the place of the Copilot manifest, a PowerShell entry for Windows, and a record of the run that a command reads.

- `chore/owner-copilot-cold-run-20261114` (SE, planned 2026-11-16): One person step holds this plan's freeze: the owner's Copilot cold run on Monday.
- `feat/windows-git-bash-handoff-20261114` (SE, planned 2026-11-15): On Windows, a PowerShell line stops depending on a bare `bash` on PATH, which there is missing or is WSL's launcher: one small hand-off finds the bash that Git ships and passes every argument to SE's one shell script.
- `feat/doctor-registration-probes-20261114` (SE, planned 2026-11-15): The doctor of SE#1133 gains rows that say, for each place a host reads SE from, whether the command it names resolves on this platform, whether the MCP door answers, whether an event is registered twice or shadowed, and when the host last called; a registration that is missing ends with the exact line that adds it.
- `feat/copilot-manifest-place-setting-20261114` (SE, planned 2026-11-15): Where SE's one Copilot manifest lies becomes a build setting, unset: .github/plugin/plugin.json as SE#1123 writes it, or the repository root, the only place VS Code's plugin reference names for the Copilot format.
- `feat/powershell-hooks-through-handoff-setting-20261114` (SE, planned 2026-11-15): Whether the PowerShell hook lines of .github/hooks/se.json call a bare `bash` or the hand-off of feat/windows-git-bash-handoff-20261114 becomes a build setting, unset.
- `docs/copilot-cold-run-record-20261114` (SE, planned 2026-11-15): The Monday checklist of SE#1124 gets the results a cold run has to show, and the run gets a place to be written down: the se agent hands work on and does not do it itself, the tools the session says it holds, which manifest the install picked, each step where the install rows were not enough, and the minutes per step.

### Host facts as data

Three generations of the old system called a host supported while nothing had been seen to work on it. Each fact about a host becomes a dated row marked documented or seen, in one file, and no check fails on it.

- `feat/copilot-run-on-record-20261114` (SE, planned 2026-11-17): After the owner's Monday run, what it showed is kept as data: the filled record is committed, each Copilot row of docs/copilot.md says where it was checked live or that it was not, and the session's own list of its tools, agents and skills is kept per host surface, with a report of host tool names SE writes that the host does not have.
- `feat/host-hook-probe-recorded-per-host-20261114` (SE, planned 2026-11-17): Give SE one probe that can be run again on any real host and shows what its hooks do there: which events fired, which project root the hook judged in and where that root came from, and whether a refusal at the stop reached the model.
- `feat/host-capability-rows-20261114` (SE, planned 2026-11-23): One section of scripts/host-limits.toml marks each thing SE relies on per host surface as documented, seen, silent or not measured, with its source and date, and `checked_on.py capabilities` prints the rows that rest on nothing seen.
- `docs/door-notes-mcp-and-copilot-20261114` (SE, planned 2026-11-17): Two short dated notes keep the outside facts SE's two new doors rely on: one for the MCP door, one for the Copilot layout and hooks.

### Switches and proof that off changes nothing

Every module lands switched off, so the owner needs one place that lists the switches and says which are on, and a cheap proof that a default changed nothing.

- `feat/switch-table-read-only-view-20261114` (SE, planned 2026-11-14): One list of SE's switches with their defaults, and one read-only command that prints for each whether it is on and which layer answered.
- `chore/recorded-outputs-prove-off-20261114` (SE, planned 2026-11-14): A small test helper keeps the text of a few outputs that no test pins today and holds the code to it, so that 'switched off means identical' is proven by a diff and not by hand in every issue.
- `docs/readme-names-the-new-reports-20261114` (SE, planned 2026-11-20): README.md names, once and in one change, every report command and every switched-off setting that landed since 14 Nov, and the switch table gains the row files those modules left out.
- `docs/readme-names-the-session-record-20261114` (SE, planned 2026-11-27): README.md names what milestone 3 added, once: the session record and how to switch it on, the retro's two flags, the local log of the person's words, the replay helper, the hooks switch and the capability rows.
- `docs/readme-names-the-skill-drafts-20261114` (SE, planned 2026-12-04): README.md names what milestone 4 added, once: the drafts folder and the one build setting that makes a draft callable by name, the requirement scanner and lint, the story checker, the slides command and the evaluation data.
- `docs/readme-names-the-checks-20261114` (SE, planned 2026-12-10): README.md names what milestone 5 added, and the owner can check in one place that every module this plan built is named and switched off: the switch view lists each switch, and 'Reports and probes' each command.

### The MCP door and kern

The door keeps 'the core starts on invoke' for every call, its tool list is measured, and one switched-off component records every hook event of a session. They change the binary, so they land one at a time after the owner's run; the move-out list lets kern move to its own repository without surprises.

- `fix/door-call-wakes-the-supervisor-20261114` (SE, planned 2026-11-17): A tool call through `se mcp` that finds the core gone has it started at once, instead of answering `starting` for up to 30 seconds while nothing is starting.
- `feat/mcp-surface-budget-20261114` (SE, planned 2026-11-18): The tool list the MCP door serves is measured and held: how many tools, in which order, and how many bytes each description and the whole list take.
- `feat/session-event-log-component-20261114` (SE, planned 2026-11-19): A kern component, off unless a wiring names it, appends every hook event the core hears to one file per session under the ignored runtime folder.
- `feat/door-names-its-client-and-build-20261114` (SE, planned 2026-11-23): The MCP door writes its client's name and version beside the session when it takes its lease, the standing file and `status` name the binary's path and version, and two or three contract cases hold a tool's structured answer equal to the command's --json.
- `feat/local-override-table-20261114` (SE, planned 2026-11-24): The ignored overlay .se/wiring.toml may carry an explicit `[overrides.<instance>]` table that sets `enabled` and config keys of an instance the tracked wiring already names.
- `feat/calls-and-hooks-timing-log-20261114` (SE, planned 2026-11-26): With one core config value set, the core appends one line per command call and per hook with its duration and its class.
- `chore/kern-move-out-report-20261114` (SE, planned 2026-11-15): A test prints everything under kern/ that names SE or one host (links into SE's docs, SE_GIT_DOOR, SE's workflows, release addresses, one host's hook shape) against the list as it stands today.

### Text from outside

SE is public and reads issues unattended. Text by an author without write access reaches a role only as marked data, behind a setting that is absent by default.

- `feat/outside-text-pure-module-20261114` (SE, planned 2026-11-14): One pure function wraps text that comes from outside the fleet in a marked envelope that names its origin, with its hidden content removed.
- `feat/outside-text-envelope-wired-20261114` (SE, planned 2026-11-19): Text written by someone without write access to the repository reaches a role only as marked data with its hidden content removed, and it can no longer pass for one of SE's own markers.

### Retros that read what happened

The retro can count what sessions did, not only what workers wrote about themselves; the person's words stay on the machine until the owner rules where they may live.

- `feat/transcript-readers-more-signals-20261114` (SE, planned 2026-11-15): The pure transcript reader of SE#1135 gains the readers a retro needs: repeated failures grouped by tool and clause, slow calls, gaps no tool accounts for, what the environment lacked (a command not found, a permission refused, a host blocked), whether the first message carried the greeting, and the list of web searches and fetches.
- `feat/retro-collect-signals-and-refusals-20261114` (SE, planned 2026-11-23): `retro.py collect` gains two blocks that are off by default: counts from the session records it is given, with a line per source, and a list of each refused delivery and each declined review of the window with its link, its author's association and its first lines.
- `feat/persons-words-local-log-20261114` (SE, planned 2026-11-16): A pure writer turns the person's turns of a session record into dated, numbered files that are never edited afterwards, with one index line each, in an ignored local folder.
- `feat/replay-recorded-host-events-20261114` (SE, planned 2026-11-24): A small test helper feeds a recorded hook post or MCP request to its handler and returns the answers that differ from the recording.
- `feat/hooks-off-switch-per-machine-20261114` (SE, planned 2026-11-25): One machine-local setting keeps SE's hooks from starting the core and from posting to it.
- `fix/windows-spawn-hides-its-console-20261114` (SE, planned 2026-11-25): On Windows, the background check that SE's start spawns no longer flashes a console window.

### Systematic engineering, slides and writing

SE is meant as an agent with many skills. The skills come as drafts that no host reads until the owner lists one in a build setting; obs gains a printed verdict from its one decision engine and its own authoring skill.

- `docs/systematic-skill-draft-20261114` (SE, planned 2026-11-14): A draft skill, outside src/skills and read by no generator, that turns a request into requirements: first an explicit list of open questions checked against the current tree, then one record per requirement (one concern, an EARS sentence, a kind, must or wish, the verify method named when written, a 'breaks if removed' line, the need it serves).
- `docs/systematic-method-cards-20261114` (SE, planned 2026-11-30): The draft skill gets its on-demand references: one short card per method the requirements procedure needs, a process checklist with an evidence form per gate, and templates in an example vault that one test builds.
- `feat/requirement-trace-and-lint-20261114` (SE, planned 2026-12-01): Two pure, report-only scripts: a scanner that reads requirement ids from Markdown notes and impl and verify markers from code and tests and answers which requirements are uncovered, untested or stale, and a lint over requirement text.
- `docs/writing-voice-skill-draft-20261114` (SE, planned 2026-12-01): One draft skill for answers and writing to the person: the fifteen voice rules (one thought per sentence, lists for three or more items, numbers over adjectives, uncertainty stated, what happens next last) with the twelve stance rules and the say-back, under about 1,000 tokens, called by name only.
- `feat/draft-skills-included-by-setting-20261114` (SE, planned 2026-11-24): One build setting lists draft skills to include in the generated layouts; unset, the build writes exactly today's files.
- `feat/story-evidence-deck-template-20261114` (SE, planned 2026-11-15): A template vault for a user story as a short deck (one named actor; the arc problem, starting state, at most six steps, result; each slide one claim on the left and its evidence on the right, with a fixed 'not yet run' block until the thing has run) and a pure checker over the note text.
- `feat/slides-command-asks-nothing-20261114` (SE, planned 2026-11-30): One named command in the render component builds a deck that asks nothing: it sets obs's screens layout and writes `<deck>.document.json`, without the decision deck's rule that some chapter must ask.
- `feat/timeline-as-text-20261114` (SE, planned 2026-12-02): `timeline.py --text` prints the Timeline's model as a few lines (planned per day, in flight, landed) for a chat answer, from the same issues the hourly workflow reads.
- `chore/eval-cases-triggers-and-outcomes-20261114` (SE, planned 2026-11-15): Data for two evaluations a person runs by hand: about twenty labelled prompts per skill (should trigger, and near-misses that should not) with a fixed split into train and validation, and three outcome cases with graders that call no judge and mock answers for the GitHub tools, to be compared with the same run without the plugin and with a smaller model.
- obs#670 (obs, landed 14 Nov as obs 3.4.0): obs prints the computed verdict of every decision in a Document as text and as JSON, without a reader's page: the verdict line, each runner-up's tie point with whether that change is reasonable, and each veto.
- obs#673 `feat/obs-authoring-skill-generated-20261114` (obs, pulled forward and started 14 Nov; first planned 2026-11-30): obs generates one skill folder that teaches an agent its Markdown dialect (fences, bases, queries, reference notes, pugh) from the authoring lines and tested examples its capability notes already own, with a check that the folder equals the notes.

### Checks that are measured themselves

'Every outside thing has one door' gets a list behind it, an empty test run is named instead of counted as a pass, and built pages can be checked for private text.

- `feat/door-declarations-as-data-20261114` (SE, planned 2026-11-16): Each door declares in a small file what it guards (the imports, calls and shell words that reach the outside thing, its own files, its contract tests), and one report lists every reach outside the declared door against a baseline that only shrinks.
- `feat/hygiene-reads-the-door-declarations-20261114` (SE, planned 2026-12-07): hygiene's git check takes its patterns from the git door's declaration instead of its own list, so the declaration is the one place that says what reaches git.
- `feat/suite-names-an-empty-run-20261114` (SE, planned 2026-12-08): `work_tickets.py suite` prints a notice where a suite beside passed without running a single test.
- `feat/built-pages-public-check-source-20261114` (SE, planned 2026-12-09): `public_check.py` gains a source that reads one built file or a folder of them against the public and the local list, so what SE publishes (documentation, decks) can be checked as built and not only as source.

## What is dropped, and why

The ten areas dropped 119 ideas and the design pages 82 more. They fall into five groups:

- **Already in SE.** For example: hooks that fail open, layouts generated from one source and checked, the Pugh rule that the datum is the strongest rival, the field report in the pull request. Nothing is left to build.
- **Superseded by SE's design.** The old cages (every native tool denied, guards that refused mid-walk), state machines walked by an engine, records on tagged branches and reading proofs. SE steers before the work and checks at the push, and keeps its record in issues and pull requests. The old record itself says these forms made the work slower without making it safer.
- **Against a decision the owner already made.** A SQLite mirror and editor front ends (the core speaks NATS alone), a second status page (the status view is the Timeline), Copilot's cloud agent as a worker and benchmark re-runs (no spending beyond the subscription), a root RUNME (the core starts on invoke; the owner brought RUNME back on 17 Nov as the generic installer every tool has, `des-016`: it installs what RUNME.conf declares and starts no core, SE's binary still arrives as a release, built only where none matches, and `build.sh` stays gone).
- **No reader or caller yet.** Pure functions with nothing to feed them, such as a dependency matrix with no matrix in SE, a quiet-span watch with no clock component, or a debugger hand-over with no user.
- **Duplicates.** The same idea from the same source filed under two or three areas; it is kept once.

Of the 125 module ideas, 61 are not planned now. The main reasons:

- Door features that pay only once the door offers commands that write or run for minutes, which is the owner's question; the five read-only tools need none of them.
- Guards on tool calls, which wait for the owner's answer on whether a new guard starts as a warning.
- Work that waits for tool events under Copilot and a recorded payload from a real session, which the session record of milestone 2 gives.
- Modules that do nothing until a role, a skill or a template names them, which is the owner's call.
- Ideas of value 2 with no first user; each is small enough to add to a bundle when a retro shows the case.
- Two cuts by the judges: a page limit per host (kept at today's 45,000 bytes until a host limit is measured) and a GitHub fake (until the owner says whether kern's GitHub component is the one GitHub door).

Each of them is listed with its reason in the plan's `notPlanned` list.

## Milestones

### M1: SE callable from GitHub Copilot (2026-11-16)

On Monday morning the owner picks the se agent in GitHub Copilot (the CLI first, then VS Code), sees the greeting and the status from the MCP door, hands on one request, and writes what happened into a record that a command reads. The filed chain carries it (SE#1121, SE#1122, SE#1154 and SE#1155 have landed; SE#1142, SE#1123 and SE#1124 are open); this plan adds a doctor that sees a dead or doubled registration, two remedies that are one setting each, a Windows hand-off and a record of the run.

| Planned | Issue | Repository | Waits for |
|---|---|---|---|
| 2026-11-15 | `docs/copilot-cold-run-record-20261114` | SE | SE#1124 |
| 2026-11-15 | `feat/copilot-manifest-place-setting-20261114` | SE | SE#1123, SE#1124 |
| 2026-11-15 | `feat/doctor-registration-probes-20261114` | SE | SE#1123 |
| 2026-11-15 | `feat/powershell-hooks-through-handoff-setting-20261114` | SE | `feat/copilot-manifest-place-setting-20261114`, `feat/windows-git-bash-handoff-20261114` |
| 2026-11-15 | `feat/windows-git-bash-handoff-20261114` | SE | SE#1123, SE#1162, SE#1165 |
| 2026-11-16 | `chore/owner-copilot-cold-run-20261114` | SE | SE#1124 |

Reached when: Before the run: SE#1142, SE#1123 and SE#1124 are closed, `se_plugin.py check` is green on main, `host_validate.py` (SE#1155) reports no refusal of a generated layout on main, and the doctor's probe answers in a cloud container. Reached: the owner's record, pasted on chore/owner-copilot-cold-run-20261114, shows on at least one Copilot surface the se agent selectable, the greeting, one `se` tool answering status and a request handed on with a clean checkout, and every step that differs has an issue. Freeze: no issue of this plan that changes a binary input or the hook scripts lands before that person step is closed (native blocks); the filed chain and the fleet's own fixes are exempt. An M1 addition that is not on main by Sunday 20:00 UTC gets 'Planned: 2026-11-17'; landing on Monday is harmless, because each is off or new files.

### M2: the run is on record; switches, host facts and door notes are data (2026-11-20)

The Monday run is on record in the repository and its findings are closed first. What was held back so that it could not change what the owner installs lands now: the door fix, the tool-list flag and the session log (they change the binary) and the hook probe (it edits the two hook scripts). The owner can read in one place which switches exist and that all are off, what each host was seen to do and how large the tool surface is; text from outside can be fenced by one setting, and obs prints a decision's computed verdict as text.

| Planned | Issue | Repository | Waits for |
|---|---|---|---|
| 2026-11-14 | `chore/recorded-outputs-prove-off-20261114` | SE | nothing |
| 2026-11-14 | `feat/outside-text-pure-module-20261114` | SE | nothing |
| 2026-11-14 | `feat/switch-table-read-only-view-20261114` | SE | nothing |
| 2026-11-17 | `docs/door-notes-mcp-and-copilot-20261114` | SE | SE#1123, SE#1142 |
| 2026-11-17 | `feat/copilot-run-on-record-20261114` | SE | `chore/owner-copilot-cold-run-20261114`, `docs/copilot-cold-run-record-20261114`, `feat/doctor-registration-probes-20261114`, SE#1124 |
| 2026-11-17 | `feat/host-hook-probe-recorded-per-host-20261114` | SE | `chore/owner-copilot-cold-run-20261114`, SE#1118, `feat/copilot-run-on-record-20261114` |
| 2026-11-14 | obs#670 (landed) | obs | obs#665 |
| 2026-11-17 | `fix/door-call-wakes-the-supervisor-20261114` | SE | `chore/owner-copilot-cold-run-20261114`, SE#1142 |
| 2026-11-18 | `feat/mcp-surface-budget-20261114` | SE | `fix/door-call-wakes-the-supervisor-20261114`, SE#1123 |
| 2026-11-19 | `feat/outside-text-envelope-wired-20261114` | SE | `feat/outside-text-pure-module-20261114`, `feat/switch-table-read-only-view-20261114`, SE#1147, SE#1165, SE#1118, SE#1162, SE#1150, SE#1120, SE#1124 |
| 2026-11-19 | `feat/session-event-log-component-20261114` | SE | `feat/mcp-surface-budget-20261114`, `feat/host-hook-probe-recorded-per-host-20261114` |
| 2026-11-20 | `docs/readme-names-the-new-reports-20261114` | SE | SE#1124, SE#1120, `feat/outside-text-envelope-wired-20261114`, `feat/copilot-run-on-record-20261114`, `feat/host-hook-probe-recorded-per-host-20261114`, `feat/powershell-hooks-through-handoff-setting-20261114`, `feat/doctor-registration-probes-20261114`, `docs/copilot-cold-run-record-20261114`, `feat/switch-table-read-only-view-20261114` |

Reached when: docs/copilot-cold-run.toml on main holds the owner's run, and every step that differed is closed or has an issue with a planned day. `se_switches.py` lists every switch landed since 14 Nov and all are off. scripts/host-limits.toml has a tools section for each surface the owner ran and a Claude Code probe row; the Copilot rows say probed or not probed. `se mcp --tools` prints the committed list and `host_size.py report --tools` measures it. obs prints a verdict as text. Deck 2, at most nine questions, goes to the owner.

### M3: sessions leave a record the retro reads; kern is ready to move (2026-11-27)

With one overlay entry on the desk, the owner gets a record of every hook event of a session on any host, and the retro, the replay helper and the capability rows read what really happened. Any switched-off component can be tried locally without a commit. The kern changes of the plan have landed one at a time, so kern can move to its own repository with no open branch, and the move-out list exists from this weekend on.

| Planned | Issue | Repository | Waits for |
|---|---|---|---|
| 2026-11-15 | `chore/kern-move-out-report-20261114` | SE | nothing |
| 2026-11-15 | `feat/transcript-readers-more-signals-20261114` | SE | nothing |
| 2026-11-16 | `feat/persons-words-local-log-20261114` | SE | nothing |
| 2026-11-23 | `feat/door-names-its-client-and-build-20261114` | SE | `feat/session-event-log-component-20261114` |
| 2026-11-23 | `feat/host-capability-rows-20261114` | SE | `feat/copilot-run-on-record-20261114`, `feat/host-hook-probe-recorded-per-host-20261114`, `docs/door-notes-mcp-and-copilot-20261114` |
| 2026-11-23 | `feat/retro-collect-signals-and-refusals-20261114` | SE | `feat/transcript-readers-more-signals-20261114`, `feat/outside-text-pure-module-20261114`, `docs/readme-names-the-new-reports-20261114` |
| 2026-11-24 | `feat/local-override-table-20261114` | SE | `feat/door-names-its-client-and-build-20261114` |
| 2026-11-24 | `feat/replay-recorded-host-events-20261114` | SE | `feat/session-event-log-component-20261114`, `feat/host-hook-probe-recorded-per-host-20261114` |
| 2026-11-25 | `feat/hooks-off-switch-per-machine-20261114` | SE | `feat/host-hook-probe-recorded-per-host-20261114`, `feat/switch-table-read-only-view-20261114` |
| 2026-11-25 | `fix/windows-spawn-hides-its-console-20261114` | SE | SE#1118, SE#1123, `chore/owner-copilot-cold-run-20261114`, `feat/windows-git-bash-handoff-20261114`, `feat/powershell-hooks-through-handoff-setting-20261114` |
| 2026-11-26 | `feat/calls-and-hooks-timing-log-20261114` | SE | `feat/local-override-table-20261114`, `feat/door-names-its-client-and-build-20261114` |
| 2026-11-27 | `docs/readme-names-the-session-record-20261114` | SE | `feat/retro-collect-signals-and-refusals-20261114`, `feat/persons-words-local-log-20261114`, `feat/hooks-off-switch-per-machine-20261114`, `feat/host-capability-rows-20261114`, `feat/replay-recorded-host-events-20261114`, `feat/session-event-log-component-20261114`, `docs/readme-names-the-new-reports-20261114` |

Reached when: One Copilot session and one Claude Code session with `[instances.session]` in the ignored overlay each leave a record file, and `retro.py collect --signals <those files> --refusals` prints both blocks with a line per source; without the flags the retro draft is byte-identical to main's. The capability rows carry at least one `seen` mark from the owner's run. No open issue of this plan edits kern/, and the move-out report lists what still names SE.

### M4: systematic engineering and slides the owner can try by name (2026-12-04)

The owner lists a draft skill in one build setting and calls it by name: systematic engineering (clarify against the tree, typed requirements, method cards) and the writing voice. A scanner answers which requirements are uncovered, untested or stale; one command builds a slide deck that asks nothing, and the first story deck shows the Copilot install pass with its evidence. The Timeline prints as text in a chat, and obs carries its own authoring skill. Nothing loads by itself.

| Planned | Issue | Repository | Waits for |
|---|---|---|---|
| 2026-11-14 | `docs/systematic-skill-draft-20261114` | SE | nothing |
| 2026-11-15 | `chore/eval-cases-triggers-and-outcomes-20261114` | SE | nothing |
| 2026-11-15 | `feat/story-evidence-deck-template-20261114` | SE | nothing |
| 2026-11-24 | `feat/draft-skills-included-by-setting-20261114` | SE | `feat/powershell-hooks-through-handoff-setting-20261114`, `docs/systematic-skill-draft-20261114`, `feat/switch-table-read-only-view-20261114`, `chore/owner-copilot-cold-run-20261114` |
| 2026-11-30 | `docs/systematic-method-cards-20261114` | SE | `docs/systematic-skill-draft-20261114`, `docs/readme-names-the-session-record-20261114` |
| 2026-11-14 | obs#673 `feat/obs-authoring-skill-generated-20261114` | obs | obs#670 |
| 2026-11-30 | `feat/slides-command-asks-nothing-20261114` | SE | `feat/story-evidence-deck-template-20261114`, `docs/readme-names-the-session-record-20261114` |
| 2026-12-01 | `docs/writing-voice-skill-draft-20261114` | SE | `docs/systematic-skill-draft-20261114`, `docs/readme-names-the-session-record-20261114` |
| 2026-12-01 | `feat/requirement-trace-and-lint-20261114` | SE | `docs/systematic-skill-draft-20261114`, `docs/readme-names-the-session-record-20261114` |
| 2026-12-02 | `feat/timeline-as-text-20261114` | SE | `feat/slides-command-asks-nothing-20261114`, `chore/recorded-outputs-prove-off-20261114` |
| 2026-12-04 | `docs/readme-names-the-skill-drafts-20261114` | SE | `feat/draft-skills-included-by-setting-20261114`, `docs/systematic-method-cards-20261114`, `feat/requirement-trace-and-lint-20261114`, `docs/writing-voice-skill-draft-20261114`, `feat/timeline-as-text-20261114`, `chore/eval-cases-triggers-and-outcomes-20261114`, `docs/readme-names-the-session-record-20261114` |

Reached when: With a draft listed in the build setting in a scratch copy, the systematic skill is callable by name in a Claude session, and the Copilot check is one line on the owner's next checklist. `deck.py slides` builds the story example, the look check passes it at phone and desktop width, and the story checker counts its 'not yet run' halves. The scanner reports on the example vault. SE's tracked se.toml lists no draft, and obs's check holds its generated skill to the capability notes.

### M5: the checks are measured themselves (2026-12-11)

The checks that hold the system are held in turn: doors declared as data with a list that only shrinks, hygiene reading the git door's declaration, an empty test run named, and built pages checked for private text. `se_switches.py` and README 'Reports and probes' tell the owner what was built since 14 Nov and what is still switched off.

| Planned | Issue | Repository | Waits for |
|---|---|---|---|
| 2026-11-16 | `feat/door-declarations-as-data-20261114` | SE | nothing |
| 2026-12-07 | `feat/hygiene-reads-the-door-declarations-20261114` | SE | `feat/door-declarations-as-data-20261114`, `docs/readme-names-the-skill-drafts-20261114` |
| 2026-12-08 | `feat/suite-names-an-empty-run-20261114` | SE | `feat/outside-text-envelope-wired-20261114`, `docs/readme-names-the-skill-drafts-20261114` |
| 2026-12-09 | `feat/built-pages-public-check-source-20261114` | SE | `docs/readme-names-the-skill-drafts-20261114` |
| 2026-12-10 | `docs/readme-names-the-checks-20261114` | SE | `feat/hygiene-reads-the-door-declarations-20261114`, `feat/suite-names-an-empty-run-20261114`, `feat/built-pages-public-check-source-20261114`, `docs/readme-names-the-skill-drafts-20261114` |

Reached when: hygiene's git check reads its declaration with unchanged results on main and every fixture; the door report prints today's reaches of GitHub and the MCP door as baselines and fails nothing; the suite names a suite beside that ran nothing; the public check reads a built page; `se_switches.py --drift` prints nothing and README names every module of this plan.

## How the plan is held

- **Filing.** The dispatcher files each work issue with `work_tickets.py file --blocked-by`, which gives it the labels work, ready and repo:SE, a `Planned:` line and a `## File ownership` section of bare paths. Every 'waits for' above becomes a native blocking link; a line in a body blocks nothing. The chain's missing link comes first: SE#1124 blocked by SE#1123.
- **The freeze.** The person step `chore/owner-copilot-cold-run-20261114` blocks every issue of this plan that changes the binary the launcher fetches or the two hook scripts, until the owner's run is on record. The filed chain and the fleet's own fixes are not held.
- **Gates.** Each milestone's README bundle is the gate for the next milestone's later issues, so the dispatcher can rewrite a gated issue from Monday's findings before it can start.
- **The Sunday cut.** A milestone 1 addition that is not on main by Sunday 20:00 UTC moves its planned day to 17 Nov. Landing on Monday does no harm, because each is off or new files.
- **Waves.** The weekend's new-file issues are filed in waves of at most three while a chain issue can start, and nothing more is filed if the queue is longer than two hours on Sunday evening.
- **The kern move.** Each kern issue says that it is refiled, in order, in kern's own repository if that exists on its start day. Nothing that edits kern/ may be in flight on the day of the move.

## Filed so far

The plan is filed in batches as blockers land. These issues carry a plan name; the rest are filed later under the names above.

| Issue | Plan name |
|---|---|
| SE#1172 | `chore/owner-copilot-cold-run-20261114` |
| SE#1173 | `feat/doctor-registration-probes-20261114` |
| SE#1174 | `feat/switch-table-read-only-view-20261114` |
| SE#1175 | `chore/recorded-outputs-prove-off-20261114` |
| SE#1176 | `feat/outside-text-pure-module-20261114` |
| SE#1177 | `chore/kern-move-out-report-20261114` |
| obs#670 | the pugh verdict as text (landed 14 Nov) |
| obs#673 | `feat/obs-authoring-skill-generated-20261114` |

## Questions that wait for the owner

Deck 1, now:

1. Under Copilot, where no scheduled integrator session exists, may the se agent start a worker itself (yes), or must it first open an integrator session (no)? PR #1161 of SE#1123 already writes 'yes' into the Copilot layout's work-model and catch-up text, so 'no' means a revert issue. Recommended: Yes, under Copilot only and through the same `work_tickets.py start` the integrator uses; the Claude fleet keeps 'never start workers directly'. (fleet-process/copilot-fleet-procedure)
2. How does VS Code get the MCP door on Monday: (a) the user-level line the doctor prints (~/.copilot/mcp-config.json or `copilot mcp add`), or (b) switching on SE#1123's root .mcp.json, which Claude Code reads too? Recommended: (a) for Monday, starting with the Copilot CLI, which reads .github/mcp.json; (b) only after a Claude session was seen unharmed with it. (copilot-host/mcp-spawn-starts-core)
3. If Monday's machine is Windows: may the Copilot hook lines and the first start go through the PowerShell hand-off instead of a bare `bash`? Recommended: Yes: switch the PowerShell hook setting on once the hand-off has passed the Windows leg; the line in the se agent's file follows after the run. (install-onboarding/windows-entry-without-bash)
4. Should Copilot count as supported only after one live run on it is on record (your filled cold-run record), with every Copilot install row saying 'not checked live' until then? Recommended: Yes. (p-supported-after-seen-refusal)
5. Until you rule otherwise: should the fleet take as instructions only issue text and comments whose author has write access, and hand all other text on as marked data (the setting `[outside-text] envelope`)? Recommended: Yes, and switch the setting on once its wiring has landed (planned 19 Nov). (fleet-process/outside-text-envelope)
6. Should every role except the integrator lose the GitHub tools that write commits on the server (push_files, create_or_update_file, delete_file)? Recommended: Yes, applied after Monday's run, so that no agent file changes before it. (p-deny-server-side-commit-tools)
7. Should your rule of 14 Nov enter the rule book: a new part ships switched off, and only you switch a default? Recommended: Yes, with your words quoted. (p-owner-holds-phase-switches)
8. Should the se agent become a short front door that does a request that is not fleet work itself, with the fitting skill, and treats cloud dispatch as one skill among others, instead of dispatching every request? Recommended: Yes, as one issue on the role text that takes effect after Monday's run; until then the se agent stays as SE#1123 writes it. (skills/front-door-router)
9. Where are your directions and answered decisions kept word for word, never edited and only superseded: (a) dated files tracked in the repository, (b) an untracked local folder only, or (c) nowhere beyond the issue, as today? Recommended: (a) for rulings and answered decisions, after the public check; raw session words and images stay local, as in (b), which feat/persons-words-local-log-20261114 builds. (p-owner-words-verbatim)

Order: the nine entries after this line are the proposed deck 2 (about 20 Nov, after the run), the next nine deck 3 (about 27 Nov); the rest follow by value, and a question of value 2 or less lapses unless its module has shown its worth.

Deck 2, about 20 Nov:

1. Should the agent that built a deck or page be told to run the look check and view its images before the page reaches you, and should a reported defect hold the page back? (slides/render-and-look-check)
2. Should wrk-001 and wrk-002 stop naming GitHub as the only shared state, so that the work record lives in the repository and GitHub only shows and carries it? (p-github-not-the-centre)
3. When you create kern's own repository: are the kern issues still open that day refiled there at once, in the same order (recommended), or do they finish in SE first? (kern-core/kern-move-out-check holds the move list)
4. May SE move its obs range from ^2.0 to ^3.0 (the lock is 2.1.8, obs is at 3.4.0; obs's new options stay off)? It gates `deck.py verdict`, the SE half of systematic-engineering/pugh-verdict-text.
5. Is kern's GitHub component the one GitHub door that the Python callers move behind, or does Python keep a door of its own with a shared fake, as git does? (testing-quality/github-door-fake-contract)
6. If the run showed a plugin install in VS Code picking the Claude layout: set the place of the Copilot manifest to the repository root (copilot-host/agent-plugins-1-0-layout)?
7. Add `[tests.beside.host-validators]`, so the hosts' validators of SE#1155 run at every integration (testing-quality/host-validators)?
8. Should gen-003 also say that a check which ran over nothing, or could not read its input, says so and never passes or shows zero? (p-unmeasured-is-not-zero)
9. Should it become a standing rule that every compatibility claim in SE's documents names the host and platform it was checked on, or says 'not checked live'? (install-onboarding/person-trial-real-host)

Deck 3, about 27 Nov:

1. After Monday, should the host tool names in the se agent, catch-up and work-model move into per-host blocks, so that each host reads only its own, or stay as they are with the Copilot section beside them? (copilot-host/per-host-text-blocks)
2. Should the register become the one store every tool reads its switches from (one lookup function), with a check that refuses an unregistered switch, or stay a read-only view beside the readers? (other/switch-register)
3. Does wrk-005 (no refusals during the work) still hold, so that every tool-call guard only warns until you switch that guard to refuse? (p-new-guard-starts-at-warn)
4. Should a new reference to SE or to one host under kern/ fail kern's tests, or only be listed until the move? (kern-core/kern-move-out-check)
5. Should the 'What if' answer of a decision (dec-007) be the engine's computed verdict and tie points instead of the decider's own arithmetic, and should SE's decks show the verdict by default? (systematic-engineering/pugh-verdict-text)
6. Should one decision deck hold at most nine questions, each naming the evidence it rests on, with the rest waiting for the next deck? (p-few-gates-for-the-person)
7. Should tiny changes get a shorter route than the full work issue, worker session and field report? (p-process-weight-follows-task-size)
8. May step 1 of the catch-up skill read one briefing command in place of the reads it makes by hand? And is that briefing fed by the Timeline, so that there stays one status view? (copilot-host/briefing-command)
9. Which model tier may run which kind of work (finding and reading, changing code, design and verdicts), and may a ticket with a deterministic check run on a cheaper model than its role's default? (fleet-process/model-by-task-class)

After those, 84 more questions wait in order of value. SE#865 holds older decisions for the owner's return; it is its own deck and this plan adds none of its questions.

## Where each taken idea came from

The source is the place the area's lenses named as the best form of the idea. A path is `repository:branch:path`; quackitect's generations are its branches v1 to v5, and `SE:ff01204` is SE's first Go line.

| Idea | Carried by | Source |
|---|---|---|
| `copilot-host/agent-plugins-1-0-layout` | `feat/copilot-manifest-place-setting-20261114` | https://github.blog/changelog/2026-08-12-agent-plugins-1-0-in-vs-code-copilot-cli-and-the-copilot-app with https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference |
| `copilot-host/copilot-cold-run-acceptance` | `chore/owner-copilot-cold-run-20261114`, `docs/copilot-cold-run-record-20261114` | quackitect:v1:product/quackitect/project_types/default/guides/milestone-review.md (The stranger's read) |
| `copilot-host/first-turn-receipt` | `feat/transcript-readers-more-signals-20261114` | quackitect:v5:spec/design_output/level0.md (The canary) with quackitect:v4:src/cage/first-turn.md (Say what you read) |
| `copilot-host/host-capability-table` | `feat/host-capability-rows-20261114` | quackitect:v4:src/cage/hooks-the-harness-fires.md (three marks) with quackitect:v3:spec/harness-portability.md Parts 1, 5, 7, 12, 19 (three tiers) |
| `copilot-host/live-tool-surface-probe` | `docs/copilot-cold-run-record-20261114`, `feat/copilot-run-on-record-20261114` | quackitect:v3:deliverable/cage/copilot-cage.json (_readme and probe command, verified live 30 Jul 2026) |
| `copilot-host/mcp-client-identity` | `feat/door-names-its-client-and-build-20261114` | quackitect:v3:spec/harness-portability.md Part 3 and Part 10 (M1) |
| `copilot-host/mcp-surface-budget` | `feat/mcp-surface-budget-20261114` | quackitect:v3:spec/harness-portability.md Parts 4, 14, 16, 18, 20 with quackitect:v4:spec/rationale/a-description-is-an-instruction.md |
| `copilot-host/session-event-log-component` | `feat/session-event-log-component-20261114`, `docs/readme-names-the-session-record-20261114` | SE:ff01204:src/internal/io/session/log.go, logmodule.go, posts.go |
| `copilot-host/tool-list-snapshot` | `feat/mcp-surface-budget-20261114` | quackitect:v4:src/cage/tools.json with src/mcp/colddoor_test.go |
| `fleet-process/outside-text-envelope` | `feat/outside-text-pure-module-20261114`, `feat/outside-text-envelope-wired-20261114` | https://code.claude.com/docs/en/hooks |
| `fleet-process/retro-loop-status-pattern` | `feat/retro-collect-signals-and-refusals-20261114` | quackitect:v5:spec/guidance/retro/effect.md; spec/guidance/retro/check.md |
| `fleet-process/retro-reads-each-failed-review` | `feat/retro-collect-signals-and-refusals-20261114` | quackitect:v3:guidance/method/retro.md (section 'Every failed gate review is read, one at a time') |
| `fleet-process/retro-session-signals` | `feat/retro-collect-signals-and-refusals-20261114` | quackitect:v5:spec/guidance/retro/signals.md |
| `fleet-process/timeline-from-kern` | `feat/timeline-as-text-20261114` | SE:main:scripts/timeline.py; docs/go-core.md 'Migration'; wiring.toml [wires] |
| `install-onboarding/doctor-report` | `feat/doctor-registration-probes-20261114` | quackitect:v5:src/quack/doctor_verb.go (probes: src/quack/hookprobe.go; the box half: quackitect:v4:src/cage/diagnose.mjs) |
| `install-onboarding/door-explains-itself` | `feat/doctor-registration-probes-20261114` | ctrl:main:mcp/mcp.mjs (explain; test/mcp-zip.test.mjs lines 117 and 135) |
| `install-onboarding/lacked-recorder` | `feat/transcript-readers-more-signals-20261114` | SE:ff01204:spec/landing.yaml (key `lacked`; spec/retro.md, the matrix) |
| `install-onboarding/launcher-any-verb` | `docs/copilot-cold-run-record-20261114` | quackitect:v4:RUNME.sh (twin: RUNME.ps1) |
| `install-onboarding/off-switches-core-start-and-refresh` | `feat/hooks-off-switch-per-machine-20261114` | SE:main:scripts/bootstrap.sh (with scripts/se_hook.sh and scripts/se_start.py start_refresh) |
| `install-onboarding/one-switch-table` | `feat/switch-table-read-only-view-20261114` | https://code.claude.com/docs/en/plugins-reference (userConfig, CLAUDE_PLUGIN_OPTION_<KEY>, defaultEnabled) |
| `install-onboarding/person-trial-real-host` | `chore/owner-copilot-cold-run-20261114`, `docs/copilot-cold-run-record-20261114`, `feat/copilot-run-on-record-20261114` | quackitect:v5:spec/tickets/copilot-shell-trial.md |
| `install-onboarding/windows-entry-without-bash` | `feat/windows-git-bash-handoff-20261114`, `feat/powershell-hooks-through-handoff-setting-20261114` | quackitect:v5:RUNME.ps1 (v2's owner decision: quackitect:v2:product/spec/ledger/se/decision-one-click-means-runme-on-three-platforms.md) |
| `kern-core/call-and-hook-timing-log` | `feat/calls-and-hooks-timing-log-20261114` | SE:ff01204:src/internal/battery/calls.go; spec/budgets.yaml (`classes`, `command_classes`, `hook_classes`) |
| `kern-core/door-notes` | `docs/door-notes-mcp-and-copilot-20261114` | ctrl:main:design/research/mcp.md |
| `kern-core/host-identity-on-record` | `feat/door-names-its-client-and-build-20261114` | quackitect:v3:spec/harness-portability.md Part 3 and Part 10 (M1); deliverable/tests/harness-identity.test.ts |
| `kern-core/kern-move-out-check` | `chore/kern-move-out-report-20261114` | SE:main:docs/go-core.md ('Incubated in SE until the kern repository exists'); kern/README.md |
| `kern-core/local-switch-layer` | `feat/local-override-table-20261114` | quackitect:v5:src/q/layers.go (SE's fit: SE:main:kern/index/wiring.go Merge) |
| `kern-core/session-event-record` | `feat/session-event-log-component-20261114` | quackitect:v5:src/q/event.go; src/modules/session/session.go (SE's own design: SE:main:docs/go-core.md 'Nobody starts the index by hand') |
| `kern-core/session-trail-readers` | `feat/transcript-readers-more-signals-20261114` | quackitect:v3:deliverable/engine/failure-shapes.ts; guidance/method/retro.md step 8 ('Mine the record') |
| `kern-core/standing-names-build` | `feat/door-names-its-client-and-build-20261114` | quackitect:v5:src/index/swap/swap.go (Watches); src/index/main.go (displaced) |
| `kern-core/start-on-invoke` | `fix/door-call-wakes-the-supervisor-20261114` | SE:main:docs/go-core.md ('Nobody starts the index by hand', 'Lifetime: bound to the session') (v4's form: quackitect:v4:src/mcp/start.go) |
| `kern-core/windows-no-console-flash` | `fix/windows-spawn-hides-its-console-20261114` | quackitect:v2:commit 5adfe2b25 (windowsHide everywhere plus a lint); product/deliverable/tests/i12-no-console-flash.test.ts |
| `other/switch-patterns` | `feat/switch-table-read-only-view-20261114`, `docs/readme-names-the-new-reports-20261114` | SE:main:kern/index/wiring.go (with scripts/se_components.py, se.toml, AGENTS.md 'Public safety', README.md 'Machine-local') |
| `other/switch-register` | `feat/switch-table-read-only-view-20261114`, `docs/readme-names-the-new-reports-20261114`, `docs/readme-names-the-session-record-20261114`, `docs/readme-names-the-checks-20261114` | quackitect:v4:spec/config/parameters.json (with spec/rationale/one-tree-holds-every-parameter.md); SE side: SE:main:scripts/work_tickets.py run_config |
| `skills/engineering-conduct-reference` | `docs/systematic-method-cards-20261114` | quackitect:v4:spec/guidance/behaviour.md (116 lines) |
| `skills/obs-authoring-skill` | `feat/obs-authoring-skill-generated-20261114` | obs:origin/main:spec/capabilities/*.md (front matter `summary` and `authoring`); pattern from https://github.com/kepano/obsidian-skills |
| `skills/stance-rules` | `docs/writing-voice-skill-draft-20261114` | quackitect:v5:spec/guidance/arguing.md (12 rules in 28 lines; rationale in spec/rationales/arguing.md). Earlier form: quackitect:v1:product/brand/voice.md 'The sycophancy guard'. |
| `skills/writing-voice-skill` | `feat/draft-skills-included-by-setting-20261114`, `docs/writing-voice-skill-draft-20261114` | quackitect:v3:guidance/voice.md (242 lines; generated into .claude/output-styles/voice.md). Later short forms: quackitect:v4:spec/guidance/voice.md (100 lines) and quackitect:v5:spec/guidance/voice.md (15 rules in 37 lines). |
| `slides/deck-lint` | `feat/story-evidence-deck-template-20261114` | https://arxiv.org/abs/2603.07244 |
| `slides/slideshow-skill` | `feat/draft-skills-included-by-setting-20261114`, `feat/slides-command-asks-nothing-20261114`, `docs/readme-names-the-skill-drafts-20261114` | SE:origin/main:scripts/deck.py |
| `slides/story-evidence-deck` | `feat/story-evidence-deck-template-20261114` | quackitect:v3:deliverable/machines/methods/meth-story-slideshow.md |
| `systematic-engineering/design-brief-shape` | `docs/systematic-method-cards-20261114` | quackitect:v4:spec/design_input/one-core-many-satellites.md |
| `systematic-engineering/method-card-library` | `docs/systematic-method-cards-20261114` | quackitect:v3:deliverable/machines/methods/ |
| `systematic-engineering/pugh-verdict-text` | obs#670 | ctrl:main:tools/pugh.mjs (with src/core/pugh.js renderMarkdown and bottomLine) |
| `systematic-engineering/raid-register` | `docs/systematic-method-cards-20261114` | quackitect:v3:deliverable/machines/methods/meth-raid.md |
| `systematic-engineering/requirement-lint` | `feat/requirement-trace-and-lint-20261114` | quackitect:v3:deliverable/machines/methods/meth-requirement-authoring.md (what to count); https://kiro.dev/docs/specs/correctness/ (EARS patterns) |
| `systematic-engineering/requirement-trace-scanner` | `feat/requirement-trace-and-lint-20261114` | https://github.com/bearcove/tracey |
| `systematic-engineering/requirements-skill` | `docs/systematic-skill-draft-20261114`, `feat/draft-skills-included-by-setting-20261114`, `docs/readme-names-the-skill-drafts-20261114` | quackitect:v3:deliverable/machines/methods/meth-requirement-authoring.md |
| `systematic-engineering/research-ledger` | `feat/transcript-readers-more-signals-20261114` | quackitect:v3:deliverable/engine/bin/se-hook-websearch.ts |
| `systematic-engineering/systematic-process-checklist` | `docs/systematic-method-cards-20261114` | quackitect:v2:product/spec/ledger/se/machine-systematic-*.md (gates and evidence forms); compact form in quackitect:v1:product/quackitect/method/rigor/systematic/checklist.md |
| `systematic-engineering/thin-criticality-scaled-trace` | `feat/requirement-trace-and-lint-20261114` | quackitect:v3:spec/overhauls/2026-08-20/findings.md |
| `systematic-engineering/verbatim-input-log` | `feat/persons-words-local-log-20261114` | ctrl:main:design/input/README.md |
| `systematic-engineering/verification-matrix-base-view` | `docs/systematic-method-cards-20261114` | obs:origin/main:spec/capabilities/bases.md (with registers.md and queries.md); field model after https://strictdoc.readthedocs.io/en/latest/traceability_matrix.html |
| `testing-quality/built-output-public-check` | `feat/built-pages-public-check-source-20261114` | ctrl:main:test/provenance.test.mjs; tools/strip-comments.mjs |
| `testing-quality/door-declarations-walkaround-check` | `feat/door-declarations-as-data-20261114`, `feat/hygiene-reads-the-door-declarations-20261114` | SE:ff01204:spec/io.md ('A door declares what it guards'); src/internal/io/*/owns.yaml; src/internal/rules/doors.go, iomodule.go; v5 twin: quackitect:v5:src/owns/owns.go, src/imports/walkaround.go |
| `testing-quality/guards-are-whitelists` | `feat/suite-names-an-empty-run-20261114`, `docs/readme-names-the-checks-20261114` | quackitect:v2:product/spec/ledger/se/law-whitelist-guards.md; raid-required-args-unvalidated-at-dispatch.md; adr-engine-promotes-to-trunk.md |
| `testing-quality/host-hook-probe` | `feat/host-hook-probe-recorded-per-host-20261114` | quackitect:v3:deliverable/engine/bin/se-hook-stop.ts (comment on the hook's root); spec/iterations/i36-the-harness-is-not-claude-measure-what-e/evidence/copilot-stop-contract.md |
| `testing-quality/mcp-cli-parity-test` | `feat/door-names-its-client-and-build-20261114` | ctrl:main:test/mcp.test.mjs (lines 68-144); src/core/ops.js; tools/mcp-client.mjs |
| `testing-quality/off-means-identical-fingerprint` | `chore/recorded-outputs-prove-off-20261114` | ctrl:main:tools/library-fingerprints.mjs; test/fixtures/library-fingerprints.json; design/output/decisions.md ('feature freeze, then an overhaul') |
| `testing-quality/plugin-outcome-evals` | `chore/eval-cases-triggers-and-outcomes-20261114` | https://code.claude.com/docs/en/plugin-evals (needs Claude Code 2.1.269 or later) |
| `testing-quality/ratchet-baseline-guards` | `feat/door-declarations-as-data-20261114` | quackitect:v5:src/imports/guards.go with src/imports/baseline/*.txt; design in spec/design_output/model.md ('The guards hold a baseline'); v3 rules in guidance/method/overhaul.md ('A new lint lands frozen') |
| `testing-quality/replay-fixtures` | `feat/replay-recorded-host-events-20261114` | quackitect:v5:src/modules/mcp/mcp.go (Replay, Mismatch); test/replay/cage/*.jsonl, command-cases.json, stop-cases.json |
| `testing-quality/skill-trigger-evals` | `chore/eval-cases-triggers-and-outcomes-20261114` | https://agentskills.io/skill-creation/optimizing-descriptions |
| `testing-quality/smaller-model-walk` | `chore/eval-cases-triggers-and-outcomes-20261114` | quackitect:v3: commit 73c95ed45 (19 Aug 2026) and merge 2a3f1cb45 (20 Aug 2026) |
| `testing-quality/three-failure-kinds` | `feat/host-hook-probe-recorded-per-host-20261114` | quackitect:v2:product/spec/bootstrap/se-v2-design.md ('Failure kinds - do not conflate'); product/spec/ledger/se/machine-tutorial-aborted.md |
