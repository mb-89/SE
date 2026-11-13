<!-- Generated from src/skills/work-model/references/rules.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->
# Rule book

Reader: whoever designs, reviews or judges a change to se or a project that uses it, and every
place that cites a rule.

Every rule lives here once, cited by its id. Other places name the id and link here; they never
restate the rule. `uv run python <se>/scripts/rule_book.py` checks the book, and the suite runs it.

## Ids

An id is `<area>-<number>` for a cross-cutting rule and `p-<project>-<number>` for a project's
rule, lowercase, the number with at least three digits: `gen-001`, `p-se-001`. A number may grow
past 999.

- **Areas:** `gen` (everything we do), `des` (software design), `tst` (testing and quality), `doc`
  (documentation and surfaces), `wrk` (work and fleet), `dec` (decisions), `pub` (publishing and
  security). No area starts with `p-`.
- **Projects:** each project has its own section, `p-` and its short name in lowercase letters and
  digits: `p-se`, `p-obs`, `p-go` for the frozen Go line. Any number of projects can be added.
- **Never reused:** a retired rule keeps its id and says why it was retired.
- **Assigned by integrators:** a worker that needs a new rule proposes it with a placeholder name
  in its field report; the integrator gives it the next free number of its section.

## The shape of a rule

Each section is a `## <prefix>: <title>` heading, and each rule a `### <id> <name>` heading in its
section, followed by:

- one sentence stating the rule;
- **Why:** the reason;
- **Without it:** what we lose if the rule is dropped;
- **Prevents:** the kinds of defects it prevents, named as defect classes, not single incidents;
- **Implementations:** one item per language or project, each linking the check, script or skill
  passage that does it, or saying "by judgment"; an item labelled `Go line (frozen):` records how
  the frozen Go line did it and does not count as a live implementation;
- **Related:** the ids of related rules, or "none";
- **Retired:** only on a retired rule, the reason.

The check refuses a malformed id, a project id without `p-`, a duplicate or reused retired id, a
rule outside its section and a rule missing any of these fields; it lists, without failing, every
rule whose only implementation is "by judgment".

## gen: everything we do

### gen-001 Mechanize first

Every step that can be a deterministic, tested command is one, written ad hoc as a script or an ad
hoc component while it serves one agent and promoted to a tracked component once the whole system
needs it, and agents keep only judgment.

- **Why:** a command does the same thing every time and its tests say so; an agent following prose
  does it a little differently each time; and an ad hoc solution left untracked never becomes a
  lasting cost until it has earned its place.
- **Without it:** repeated procedures stay prose, and each run of them is a new chance to skip a
  step; or every quick fix is tracked and tested at once, so none is quick.
- **Prevents:** a step skipped or done differently by hand; a procedure whose prose and practice
  drift apart; an ad hoc script committed before it was worth keeping.
- **Implementations:**
  - se: the work model's [Mechanical first](../SKILL.md#rules-for-all-roles), the commands of
    [`<se>/scripts/work_tickets.py`](../../../scripts/work_tickets.py) with their tests.
  - se, ad hoc: an ad hoc solution stays untracked — a script, or a component
    [`se component add`](../../../scripts/se_component.py) scaffolds under `.se/components/`,
    whose uses kern counts so [`retro.py collect`](../../../scripts/retro.py) names what to
    promote to a tracked `components/` (`docs/go-core.md` weighs Python against a port to Go).
  - Go line (frozen): the retro counted `by-hand` answers and the scripts in the Go line's
    src/scripts/ directory.
- **Related:** gen-002, wrk-006

### gen-002 Single point of truth

Every fact has one owner, and everything else links to it or is generated from it.

- **Why:** a fact written twice drifts, and nobody can tell which copy is right.
- **Without it:** every change to a fact must find all its copies, and the ones it misses
  contradict it.
- **Prevents:** drift between two copies; a change applied in one place and missed in another.
- **Implementations:**
  - se: [`AGENTS.md`](../../../AGENTS.md) ("SPOT everywhere");
    [`<se>/scripts/se_plugin.py`](../../../scripts/se_plugin.py) generates both host layouts from
    `src/`, every pytest run builds them first (`tests/conftest.py`), and
    `tests/test_se_plugin.py` checks they match; otherwise by judgment in review.
  - Go line (frozen): `se overhaul read` listed duplicates and near-duplicates.
- **Related:** des-005, doc-001, gen-005

### gen-003 Fail open for advice, closed for enforcement

Logging and help never block, and a check that guards something refuses when it cannot decide.

- **Why:** advice that blocks stops work for nothing, and a guard that passes when unsure guards
  nothing.
- **Without it:** a broken log stops a release, or a gate that could not see the commits lets them
  through.
- **Prevents:** a gate that passes what it could not check; work blocked by an optional helper.
- **Implementations:**
  - se: [`<se>/scripts/public_check.py`](../../../scripts/public_check.py) exits 2 on a setup
    error, on a shallow clone that hides commits and on a running se off its pin
    ([Public safety](../../../AGENTS.md#public-safety)); `field-report --check` refuses a report
    it cannot match to the issue.
- **Related:** pub-001, pub-007, wrk-006

### gen-004 Blameless

Fix what produced a bad outcome (a rule, a tool, a prompt), never just the outcome.

- **Why:** an outcome fixed by hand comes back; the rule or tool that produced it is still there.
- **Without it:** the same defect recurs with every package that meets the same cause.
- **Prevents:** a recurring defect whose cause is never fixed; blame in place of a fix.
- **Implementations:**
  - se: the field report's Retro, whose proposed improvement names a target file and the change
    ([pull request template](../../../.github/pull_request_template.md)); otherwise by judgment.
- **Related:** gen-001, gen-005

### gen-005 Consistency

The system agrees with itself: every part fits the parts that rely on it, and no prose describes
behaviour other than what the code does.

- **Why:** a reader trusts what they read; a part that disagrees with another misleads whoever
  reads it.
- **Without it:** documentation, generated files and code drift apart until none of them can be
  trusted.
- **Prevents:** prose that describes behaviour the code does not have; a generated file out of date
  with its source; a link to an anchor that no longer exists.
- **Implementations:**
  - se: the suite builds the generated layouts before its tests (`tests/conftest.py`), and
    `tests/test_se_plugin.py` checks they match their source; `tests/test_agent_definitions.py`
    (every link and anchor resolves), [this book's check](../../../scripts/rule_book.py); the
    reviewer, by judgment, for its change.
  - Go line (frozen): the battery's mechanical checks and generated manifests; the retro and the
    overhaul.
- **Related:** gen-002, doc-001

## des: software design

### des-001 Locality

One change happens in one place, and the system picks it up everywhere by registration, never by
hand-kept lists.

- **Why:** understanding or making a change should mean reading one place.
- **Without it:** every addition needs edits in several lists, and a missed list is a silent bug.
- **Prevents:** shotgun surgery; a hand-kept list that misses a new entry.
- **Implementations:**
  - se: [`<se>/scripts/se_plugin.py`](../../../scripts/se_plugin.py) finds every agent and skill
    under `src/` by itself; otherwise by judgment.
  - Go line (frozen): `se overhaul read` counted files touched per change.
- **Related:** des-002, des-008

### des-002 Modularity

Behaviour lives in modules with a small contract, so a change to one module needs only that
module and its contract.

- **Why:** a contract is smaller than the whole system; an agent that needs only it works faster
  and breaks less.
- **Without it:** every change needs the whole system in the head of whoever makes it.
- **Prevents:** a change that breaks a far part of the system; a framework that depends on an
  application.
- **Implementations:**
  - se: projects use se and obs as pinned modules ([README "Modules"](../../../README.md#modules));
    framework and application repositories are kept apart
    ([Rules for all roles](../SKILL.md#rules-for-all-roles)).
  - Go line (frozen): v5's index and modules registering with a small core.
- **Related:** des-001, des-003

### des-003 Thin adapters

The logic lives in one place, and each host adapter is thin and generated from it.

- **Why:** a host is a way in, not a second implementation; logic in an adapter is logic written
  twice.
- **Without it:** each host behaves a little differently, and fixes reach only one of them.
- **Prevents:** drift between host layouts; behaviour that exists only on one host.
- **Implementations:**
  - se: one source in `src/`, generated into the Copilot layout and the Claude Code plugin by
    [`<se>/scripts/se_plugin.py`](../../../scripts/se_plugin.py); the
    [adapter sync contract](../SKILL.md#adapter-sync-contract).
  - Go line (frozen): the Go program owned the logic; the plugin, the CLI and the generated UI were
    thin.
- **Related:** gen-002, des-002

### des-004 One door per outside thing

Each outside thing (processes, disk, the network, GitHub) is reached through one door, and a run
reads its inputs once, computes, then writes its outputs.

- **Why:** one door is one place to fake, to measure and to fix; inputs read at different times
  disagree, and reading again what a run already has is slow.
- **Without it:** outside calls spread through the code, tests need the real world, and a run acts
  on a mix of old and new state.
- **Prevents:** a test that needs a real service; a run that acts on inputs read at different
  times; one call per item where one batched read would do.
- **Implementations:**
  - se: [`<se>/scripts/work_tickets.py`](../../../scripts/work_tickets.py) reaches GitHub only
    through its `run_gh` functions, and without `gh` a role uses the host's GitHub tools
    ([Without gh](../SKILL.md#without-gh)); otherwise by judgment.
  - Go line (frozen): the battery's `io-module` and `programs` rules (`proc.Programs`; GitHub
    through its own HTTP client, never `gh`); a box's take, local work and land.
- **Related:** tst-001, des-009

### des-005 Once and only once

Generalize repeated code at the third repetition, not the second, since a little copying is better
than a little dependency.

- **Why:** a fact in code has one owner like any other, but a premature abstraction costs more than
  the copy it removes.
- **Without it:** either copies drift, or every pair of similar lines grows a shared helper nobody
  can change.
- **Prevents:** duplicated and near-duplicated code; an abstraction with one real user.
- **Implementations:**
  - se: by judgment, the reviewer for its change; an overhaul reads the duplicate blocks and
    near-duplicate functions [`<se>/scripts/overhaul.py facts`](../../../scripts/overhaul.py) lists.
  - Go line (frozen): `se overhaul read` listed duplicates and near-duplicates.
- **Related:** gen-002, des-006

### des-006 KISS and YAGNI

Build nothing for a second user or a case that does not exist yet.

- **Why:** speculative generality is code to read, test and keep that serves nobody.
- **Without it:** the code grows options and layers whose only effect is to slow every change.
- **Prevents:** speculative generality; unused surfaces; a one-user abstraction.
- **Implementations:**
  - se: by judgment, the reviewer for its change; an overhaul reads the script commands no
    authored text names, which [`<se>/scripts/overhaul.py facts`](../../../scripts/overhaul.py) lists.
  - Go line (frozen): `se overhaul read` listed one-user abstractions and unused surfaces.
- **Related:** des-005, des-015

### des-007 Single responsibility

Each function and module does one thing, keeps its concerns apart and either answers a question or
changes state, not both.

- **Why:** a part that does one thing can be named, tested and replaced on its own.
- **Without it:** parts grow until a change to one concern breaks another.
- **Prevents:** long functions and large modules; divergent change; a query with a side effect.
- **Implementations:**
  - se: by judgment, the reviewer for its change; an overhaul reads the longest functions, files
    and parameter lists [`<se>/scripts/overhaul.py facts`](../../../scripts/overhaul.py) lists.
  - Go line (frozen): `se overhaul read` listed the longest functions and files.
- **Related:** des-008, des-014

### des-008 Open for extension by registration

New behaviour is added by registering it, I/O stays behind small interfaces, and an interface is
as small as its users need.

- **Why:** registration keeps a change in one place, and a small interface is a strong abstraction.
- **Without it:** each extension edits the core, and wide interfaces tie every user to every
  method.
- **Prevents:** a core edited for every extension; an interface whose users each need a different
  part of it.
- **Implementations:**
  - se: by judgment, the reviewer for its change.
  - Go line (frozen): the battery's `io-module` rule.
- **Related:** des-001, des-004

### des-009 Functional core, imperative shell

The computing between reading inputs and writing outputs is pure and works on what was read.

- **Why:** pure code is tested without fakes, and its result depends only on its inputs.
- **Without it:** logic and I/O mix, and every test of the logic needs the outside world.
- **Prevents:** logic that can be tested only against a real service; results that depend on when
  they were computed.
- **Implementations:**
  - se: by judgment, the reviewer for its change.
- **Related:** des-004, tst-002

### des-010 Fail fast

Wrong input is refused at the edge, with where it came from and the remedy.

- **Why:** an error found where it enters is cheap to explain; found later, it hides its cause.
- **Without it:** bad input travels inward and fails far from where it came in.
- **Prevents:** an error reported far from its cause; a message that names neither source nor
  remedy.
- **Implementations:**
  - se: every error message names its source and, where possible, the remedy
    ([Rules for all roles](../SKILL.md#rules-for-all-roles)); otherwise by judgment.
- **Related:** gen-003

### des-011 Clear is better than clever

Write the code a reader understands at first reading.

- **Why:** code is read far more often than it is written, mostly by someone else.
- **Without it:** every change starts with deciphering, and the cleverness hides bugs.
- **Prevents:** code that only its author understands; bugs hidden in a compact trick.
- **Implementations:**
  - se: by judgment, the reviewer for its change.
- **Related:** doc-002

### des-012 Reuse before you write

Before building a check, a skill or an agent, look for one that exists and integrate it.

- **Why:** a maintained tool is tested by its other users; a rewrite starts with none.
- **Without it:** se grows its own copies of tools others maintain better.
- **Prevents:** a home-grown copy of a published tool; maintenance spent on solved problems.
- **Implementations:**
  - se: by judgment, the reviewer for its change.
  - Go line (frozen): the overhaul's `looked_at.outside`.
- **Related:** des-006

### des-013 Patterns where they fit

Use a known pattern where the code has its shape: strategy, table-driven code, template method,
registry, adapter, command and state machine.

- **Why:** a known pattern is a shape the reader already understands.
- **Without it:** the same problems are solved in new ways each time, each one to learn.
- **Prevents:** a switch on a kind repeated across the code; a lifecycle kept in scattered flags.
- **Implementations:**
  - se: by judgment, the reviewer for its change.
  - Go line (frozen): `se overhaul read` listed switches on a kind.
- **Related:** des-003, des-008

### des-014 Find the smells

Find and remove the known smells: shotgun surgery, divergent change, duplicated code, long function,
large module, long parameter list, data clumps, primitive obsession, feature envy and switch on a
kind.

- **Why:** a smell is a cheap sign of a design problem, visible before it causes a defect.
- **Without it:** design problems are found only when a change breaks on them.
- **Prevents:** the design defects each smell signals, found late.
- **Implementations:**
  - se: by judgment, the reviewer for its change; an overhaul reads the sizes, duplicates and
    longest pieces [`<se>/scripts/overhaul.py facts`](../../../scripts/overhaul.py) lists.
  - Go line (frozen): `se overhaul read` listed files touched per change, duplicates, longest
    functions, files and parameter lists, sizes and switches on a kind.
- **Related:** des-001, des-005, des-007

### des-015 The less code, the less to maintain

Remove code nothing reaches, code for a state that no longer occurs and code that restates what
another place holds.

- **Why:** every line is read, tested and kept; a line that does nothing still costs that.
- **Without it:** dead code accumulates and misleads readers about what the system does.
- **Prevents:** dead code; code for a retired state; a second copy of a fact in code.
- **Implementations:**
  - se: "No backwards compatibility unless asked" ([`AGENTS.md`](../../../AGENTS.md)); otherwise
    by judgment, from what [`<se>/scripts/overhaul.py facts`](../../../scripts/overhaul.py) finds nothing but tests reaches.
  - Go line (frozen): the battery's `deadcode -test`; `se overhaul read`'s pruning facts.
- **Related:** des-006, gen-002

## tst: testing and quality

### tst-001 Fakes that behave

Every outside service the code reaches has a fake that behaves like it, and the real service is
called only in its own contract tests and once for each affected command at delivery.

- **Why:** a fake that does not behave like the service tests the fake; only the real call shows
  what the service refuses.
- **Without it:** tests pass on fakes while the real service refuses the same call.
- **Prevents:** a change that passes on fakes and fails against the real service.
- **Implementations:**
  - se: the work model's [Tests](../SKILL.md#tests); the worker runs the affected real command once
    against the real service ([worker procedure](../../../agents/worker.md#procedure)).
  - Go line (frozen): the battery's `fake-contract` rule ran one contract suite against fake and
    real.
- **Related:** des-004, tst-002

### tst-002 Fast tests

Test a behaviour once, at the outermost interface, on fakes, with no wall clock and no sleeping,
in parallel.

- **Why:** a fast suite runs on every change; a slow one is skipped.
- **Without it:** the suite grows slow and flaky until people stop running it.
- **Prevents:** a flaky test that depends on timing; a behaviour tested many times at many levels; a
  suite too slow to run on every change.
- **Implementations:**
  - se: the work model's [Tests](../SKILL.md#tests); the suite runs in parallel
    (`pyproject.toml`).
  - Go line (frozen): the battery's `fast-test` rule; `se overhaul read`'s test ratio, test code
    at or under code size.
- **Related:** tst-001, tst-003

### tst-003 Measured performance, no blind waits

Durations are measured against declared budgets, and anything a person waits on gives feedback
within one second.

- **Why:** what is not measured grows unnoticed, and a person who waits blind cannot tell slow from
  stuck.
- **Without it:** the suite and the commands slow down a little with each change, and nobody sees it
  until it hurts.
- **Prevents:** a slow regression nobody notices; a command that leaves a person waiting with no
  feedback.
- **Implementations:**
  - se: the suite's budget in `se.toml` `[tests]` ([Test budget](../../../README.md#test-budget)),
    enforced by `integrate`, and `work_tickets.py suite --compare`; feedback within a second, by
    judgment.
  - Go line (frozen): `spec/budgets.yaml`, interactive and batch command classes, and answers from
    the daemon's snapshot.
- **Related:** tst-002

### tst-004 Every mechanical rule is a check

A rule that can be checked mechanically is a check in the suite, and nothing reaches the
integration branch past a failing one.

- **Why:** a check holds a rule on every change; prose holds it only when someone remembers.
- **Without it:** rules are followed until they are forgotten.
- **Prevents:** a rule broken because nobody remembered it; a change that passes locally and fails
  in CI.
- **Implementations:**
  - se: the suite (`uv run pytest -q`) that `integrate` runs before each integration push, the
    [public check](../../../AGENTS.md#public-safety) on every push, and this book's check.
  - Go line (frozen): the battery, with SE's own rules as checks.
- **Related:** gen-001, wrk-006

## doc: documentation and surfaces

### doc-001 Talk only about what you own

Each element either owns content and talks only about itself, or is a generated map that points at
owners.

- **Why:** a hand-written description of what something else owns drifts from it.
- **Without it:** a reader finds two descriptions of one thing that disagree.
- **Prevents:** drift between two copies; prose that restates a rule it does not own.
- **Implementations:**
  - se: generated layouts name their source
    ([`<se>/scripts/se_plugin.py`](../../../scripts/se_plugin.py)); every place that names a rule
    links to it in this book; otherwise by judgment in review.
  - Go line (frozen): manifests regenerated identically, and every command, path and link named in
    prose existed (`se help manifest`).
- **Related:** gen-002, doc-002

### doc-002 Write for your reader

Before writing prose, name who reads it and what they need, put the bottom line first and give
detail further down, only as far as that reader needs.

- **Why:** prose serves a reader; prose for nobody in particular serves nobody.
- **Without it:** documents grow detail their readers do not need and bury what they do.
- **Prevents:** the key line buried under detail; prose that serves no named reader; explanation
  that repeats what another place owns.
- **Implementations:**
  - se: a `Reader:` line under the title of a skill or reference, by judgment.
  - Go line (frozen): the battery checked each prose file's `Reader:` line.
- **Related:** doc-001

## wrk: work and fleet

### wrk-001 GitHub is the only shared state

What a later session needs lives on GitHub, never only in a session or on a machine.

- **Why:** sessions and containers end; GitHub stays.
- **Without it:** work, decisions and reports die with the session that made them.
- **Prevents:** a decision or report lost with its session; a later session that cannot see what an
  earlier one did.
- **Implementations:**
  - se: work issues, and pull requests whose descriptions are the field reports
    ([Roles and flow](../SKILL.md#roles-and-flow)); local tickets only as a worker's scratch
    ([Local tickets and notes](../SKILL.md#local-tickets-and-notes)).
- **Related:** wrk-002

### wrk-002 One work system

Work is a GitHub issue and an issue is always work, while reports, questions and findings travel in
their own outputs.

- **Why:** one queue can be counted, ordered and closed; an issue that is not work clogs it.
- **Without it:** work hides in messages and the queue fills with reports that change nothing.
- **Prevents:** work lost in a message; an issue that asks or reports instead of naming work.
- **Implementations:**
  - se: the work issue template and `work_tickets.py` (`file`, `route`, `intake`)
    ([Issues](../SKILL.md#issues)); the field report is the pull request's description, never an
    issue; a worker acts on its work issue and its comments, not on messages
    ([the box](../../../agents/worker.md#the-box)).
  - Go line (frozen): issues created only through `se issue new`; the retro's rule checks.
- **Related:** wrk-001, dec-011

### wrk-003 Every session starts at the newest integration branch

Both the code being worked on and the se that runs the session start at the newest integration
branch, or at the pin the project sets.

- **Why:** work on an old base meets conflicts and rules that have already changed.
- **Without it:** sessions act on stale code and stale rules, and their results conflict.
- **Prevents:** work done on a stale base; a check run by another se version than the project pins.
- **Implementations:**
  - se: `work_tickets.py sync` merges the newest integration branch before intake and every ticket;
    the public check refuses an se off the project's pin
    ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** pub-007, wrk-001

### wrk-004 The fleet works, sessions discuss

An interactive session with a person is for deciding what to build and how, and clear work goes
to the fleet as a work issue.

- **Why:** the person's time goes to what only they can decide; work that is clear needs no person.
- **Without it:** the conversation stalls while the session does work the fleet could do.
- **Prevents:** a person waiting on work an agent could do alone; work done outside the queue.
- **Implementations:**
  - se: SE dispatches through integrators and never starts workers directly
    ([catch-up](../../catch-up/SKILL.md)); otherwise by judgment.
- **Related:** dec-011, wrk-002

### wrk-005 Steer before, check at the push

What an agent gets is settled before it starts, and what must hold is checked when the work is
pushed, with nothing steering it in between.

- **Why:** an agent works best on a complete brief, and a check at the push sees the whole change.
- **Without it:** agents are interrupted mid-work by refusals that see only part of the change.
- **Prevents:** a brief completed piecemeal during the work; a rule enforced on half a change.
- **Implementations:**
  - se: the session prompt names the agent and its work issue, and the agent reads its definition
    and `AGENTS.md`; the hooks, `work_tickets.py push` and `integrate` check at the push
    ([Public safety](../../../AGENTS.md#public-safety)).
  - Go line (frozen): `se issue pull --take` handed the issue's skills over; `se issue land`.
- **Related:** wrk-006, tst-004

### wrk-006 Gates at the push are commands

Every push goes through a command that runs its gates, and a gate is never bypassed.

- **Why:** a gate that can be skipped by hand is skipped when it is inconvenient.
- **Without it:** a push that the hooks would refuse reaches the integration branch.
- **Prevents:** a change that passes locally and fails in CI; a hook bypassed with `--no-verify`.
- **Implementations:**
  - se: `work_tickets.py push` (never `git push` by hand) and `deliver`
    ([worker procedure](../../../agents/worker.md#procedure)); pre-push hooks and CI
    ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** wrk-005, pub-006

### wrk-007 One piece of work, one issue; no command files issues on its own

Each piece of work has exactly one issue, a review, retro, overhaul or check writes one report on
the issue or pull request it concerns, and only the `se` role files new issues, after reading such
a report.

- **Why:** an issue is chosen work; a finding becomes work only when someone weighs it against the
  rest, and related findings are one package, not one issue each.
- **Without it:** the old fleet minted an issue per finding and flooded the queue: every review,
  retro and check filed its own, and the queue held more reports than work.
- **Prevents:** issue spam; twins of one piece of work; work nobody chose.
- **Implementations:**
  - se: `work_tickets.py file`, `backlog file` and `route` are the only paths to the issue-create
    door, which `tests/test_issue_creation.py` checks.
  - se: `review.py file` posts one comment on the reviewed pull request and files no issue
    (README [Work commands](../../../README.md#work-commands)).
  - se: `retro.py file` and `overhaul.py file` post one report on their own issue and close it,
    filing no issue; an overhaul's rule changes are marked for the owner's decision list
    (README [Work commands](../../../README.md#work-commands)).
  - se: SE, reading a report, bundles related findings into one work issue and sends rule or
    principle changes to the owner's decision list, never as separate issues
    ([Issues](../SKILL.md#issues)).
- **Related:** wrk-002, dec-011

## dec: decisions

Rules `dec-001` to `dec-009` are the decision skill's [checklist](../../decision/SKILL.md#the-checklist),
in its order: every decision note answers each of them as one checklist entry in its `pugh` fence.

### dec-001 Class or case

Where a case is one instance of a general mechanism, decide the mechanism and let the case be its
example.

- **Why:** an answer about the mechanism settles every later case of the class; an answer about the
  instance settles only this one.
- **Without it:** the same kind of question comes back case by case, and the answers disagree.
- **Prevents:** inconsistent answers to cases of one class; the same decision taken again and again.
- **Implementations:**
  - se: checklist item 1 and [One level up](../../decision/SKILL.md#one-level-up) in the decision
    skill.
- **Related:** dec-009

### dec-002 Is the problem real

A decision names what shows its problem exists: a failure, a measurement or the person's words.

- **Why:** a decision about an imagined problem spends effort and adds rules for nothing.
- **Without it:** rules and features grow for problems nobody had.
- **Prevents:** speculative fixes; rules for a problem that never occurred.
- **Implementations:**
  - se: checklist item 2 and the note's `## The problem` section, which `deck.py build` requires
    ([decision note](../../decision/SKILL.md#the-decision-note)).
- **Related:** des-006

### dec-003 Keep what we have

Where something exists, keeping it is an option, and the datum every option is marked against is
the strongest rival.

- **Why:** change costs something, so a new option must beat what exists, and against a weak datum
  every option looks good.
- **Without it:** decisions replace what works with what merely sounds better.
- **Prevents:** churn that replaces a working solution; a matrix rigged by a weak datum.
- **Implementations:**
  - se: checklist item 3 of the [decision skill](../../decision/SKILL.md#the-checklist).
- **Related:** dec-004

### dec-004 A named loser

Each losing option names the reason it lost.

- **Why:** a reader who sees why an option lost does not propose it again.
- **Without it:** rejected options come back, and nobody remembers why they were dropped.
- **Prevents:** a rejected option proposed again without new facts.
- **Implementations:**
  - se: checklist item 4 of the [decision skill](../../decision/SKILL.md#the-checklist).
- **Related:** dec-003

### dec-005 Fair criteria

Criteria are weighted before any option is marked, each names the benefit it stands for, and none
is counted twice.

- **Why:** weights set after marking follow the preferred option, and a benefit counted twice
  decides alone.
- **Without it:** the matrix confirms whatever the decider already wanted.
- **Prevents:** a matrix fitted to its answer; one benefit, usually effort, counted under several
  names.
- **Implementations:**
  - se: checklist item 5 of the [decision skill](../../decision/SKILL.md#the-checklist).
- **Related:** dec-006

### dec-006 Right before cheap

Being right and consistent outweighs effort, and effort never decides alone.

- **Why:** effort is paid once, and a wrong or inconsistent choice is paid for on every later use.
- **Without it:** the cheapest option wins, and its inconsistencies are paid for again and again.
- **Prevents:** a shortcut that leaves the system inconsistent; a decision won on effort alone.
- **Implementations:**
  - se: checklist item 6 of the [decision skill](../../decision/SKILL.md#the-checklist).
- **Related:** dec-005, gen-005

### dec-007 What if

For each other option, name the weights under which it wins, and give a world that could happen a
tripwire and a fallback.

- **Why:** a decision that holds only under some weights should say which, so a change in the world
  is noticed.
- **Without it:** a decision outlives the conditions it was right under, and nobody sees it turn
  wrong.
- **Prevents:** a decision kept after its conditions changed; no fallback when a risk comes true.
- **Implementations:**
  - se: checklist item 7 and [Your own decisions](../../decision/SKILL.md#your-own-decisions) in
    the decision skill.
- **Related:** dec-005

### dec-008 Undo cost

A one-way decision goes to the person.

- **Why:** what can be reversed may be decided and corrected later; what cannot needs the authority
  of the person who bears it.
- **Without it:** agents take irreversible decisions that only the person may take.
- **Prevents:** an irreversible change made without the person.
- **Implementations:**
  - se: checklist item 8 of the [decision skill](../../decision/SKILL.md#the-checklist); the
    [escalation ladder](../SKILL.md#escalation-ladder).
- **Related:** dec-011

### dec-009 Consistency

A decision names the rule or earlier decision it contradicts and the one it replaces.

- **Why:** a decision that silently contradicts a rule leaves two answers to one question.
- **Without it:** rules and decisions contradict each other, and each reader picks one.
- **Prevents:** a decision that contradicts a rule unnoticed; two live answers to one question.
- **Implementations:**
  - se: checklist item 9 of the [decision skill](../../decision/SKILL.md#the-checklist); SE checks
    every outside issue against this book ([SE](../../../agents/se.md#outside-issues)).
- **Related:** gen-005, dec-001

### dec-010 A success criterion

Every option says what marks it successful once it is done.

- **Why:** without a criterion, nobody can tell later whether the decision worked.
- **Without it:** decisions are never checked against their outcome, and bad ones stay.
- **Prevents:** a decision whose outcome is never checked; an option chosen without knowing what it
  should achieve.
- **Implementations:**
  - se: each option's `success` field ([decision note](../../decision/SKILL.md#the-decision-note)),
    which `deck.py build` warns of when missing.
- **Related:** dec-007

### dec-011 Persons decide, agents execute

Anything controversial goes to a person, and everything else flows without one.

- **Why:** a person's time is the scarce resource; spending it on what an agent may decide wastes
  it, and an agent taking a person's decision takes their authority.
- **Without it:** either every step waits on a person, or agents decide what only the person may.
- **Prevents:** a one-way decision taken without the person; a person asked about what an agent
  could decide.
- **Implementations:**
  - se: the [escalation ladder](../SKILL.md#escalation-ladder); decisions reach the person as
    decision notes in a deck ([decision skill](../../decision/SKILL.md)), never as issues.
  - Go line (frozen): the retro counted `se-person` answers.
- **Related:** wrk-004, dec-012

### dec-012 Only SE asks the person

Every question and approval for the person goes through SE, and no other role's procedure has a
step that needs the person in its session.

- **Why:** the person talks to one session, and a host counts an approval only in the session it
  was given; a step another role needs approved must therefore run in SE's session.
- **Without it:** the person is sent into integrator and worker sessions they do not monitor, and
  a step waits there for a yes, or runs under a relayed one.
- **Prevents:** a person asked outside SE's session; a one-way step stuck on an approval no one
  gives; a one-way step run on an approval given elsewhere.
- **Implementations:**
  - se: [Steps only the person approves](../SKILL.md#steps-only-the-person-approves) in the work
    model; `work_tickets.py refs request` and `refs apply`; `tests/test_agent_definitions.py`
    refuses a non-SE agent or skill file that has the person act outside SE's session.
- **Related:** dec-008, dec-011

## pub: publishing and security

The public check enforces these rules on tracked files, commit messages and identities; its
behaviour, lists and hooks are owned by [Public safety](../../../AGENTS.md#public-safety).

### pub-001 Publishable at any time

Nothing in a public repository identifies an employer, a work project, a person, a machine, an
account or an internal host.

- **Why:** a public repository is copied and indexed the moment it is pushed; nothing can be taken
  back.
- **Without it:** private names leak into public history, where removing them means rewriting it.
- **Prevents:** a leaked name, path, address or host; work content in a framework repository.
- **Implementations:**
  - se: [`<se>/scripts/public_check.py`](../../../scripts/public_check.py) with the public and the
    local list, run by the hooks, by `work_tickets.py push` and in CI
    ([Public safety](../../../AGENTS.md#public-safety)); work-specific content lives in separate
    repositories that use se as a module.
- **Related:** pub-002, pub-005, gen-003

### pub-002 A generic commit identity

Every commit carries the machine's `public_identity`, else the project's `identity` (`mb <mb>` for
se), and never a real e-mail address.

- **Why:** a commit's author and committer are published with it and outlive every rewrite of the
  files.
- **Without it:** each commit publishes whoever made it and their address.
- **Prevents:** a personal e-mail address in public history; commits by an identity the project does
  not use.
- **Implementations:**
  - se: `work_tickets.py sync` writes the identity into the checkout
    ([Commit identity and public check](../SKILL.md#what-the-project-provides)); the public check's
    commit gates refuse another identity ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** pub-001, pub-003

### pub-003 No attribution trailers

Commit messages carry no `Co-Authored-By:` or `Claude-Session:` line and no e-mail address, whatever
a host's attribution reminder says.

- **Why:** the owner's rule takes precedence over a host's reminder, and a trailer publishes an
  address or a session.
- **Without it:** every commit made by an agent publishes the host's attribution.
- **Prevents:** an address or session link in public history; a host's default overriding the
  owner's rule.
- **Implementations:**
  - se: the public check's commit gates ([Public safety](../../../AGENTS.md#public-safety));
    `commit_trailer` is the one trailer a machine may set
    ([What the project provides](../SKILL.md#what-the-project-provides)).
- **Related:** pub-002

### pub-004 No tracker references in commit messages

Commit messages carry no tracker reference (`#<n>`, `<repo>#<n>`, `<owner>/<repo>#<n>`, `GH-<n>`,
an issue or pull request URL).

- **Why:** a commit outlives its tracker, and a reference names a tracker that may be private.
- **Without it:** history fills with references that point nowhere or reveal a private tracker.
- **Prevents:** a dangling reference in history; a private tracker named in a public repository.
- **Implementations:**
  - se: the public check's commit gates ([Public safety](../../../AGENTS.md#public-safety));
    `integrate` writes its merge messages without them
    ([What the project provides](../SKILL.md#what-the-project-provides)).
- **Related:** pub-001

### pub-005 Private terms stay local

The terms a source keeps private live in its untracked `.public-check.local`, never in a tracked
file.

- **Why:** a list of private terms checked in publishes exactly what it protects.
- **Without it:** the private list leaks, or the check runs without it.
- **Prevents:** a private term published by the list that guards it.
- **Implementations:**
  - se: the public check refuses to run while git tracks the local list; `<se>/scripts/setup.sh` and
    `setup.ps1` add it to `.gitignore` ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** pub-001

### pub-006 Never bypass the hooks

A finding is fixed by removing the content or by a reasoned allow entry, never by `--no-verify`.

- **Why:** a bypassed hook checks nothing, and a reasoned entry records why a finding is harmless.
- **Without it:** a hit is waved through once and every later one with it.
- **Prevents:** a leak pushed past a hook; a false positive silenced without a reason.
- **Implementations:**
  - se: `.public-check-allow`, whose header owns its format; CI runs the commit gates on every push
    to `main` ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** wrk-006, pub-001

### pub-007 One se version per check

A repository that pins se is checked only by se at that pin.

- **Why:** two se versions apply two sets of rules; a verdict must say which one it used.
- **Without it:** a check passes under one se and fails under another, and nobody can tell which
  is right.
- **Prevents:** a change that passes locally and fails in CI because the se versions differ.
- **Implementations:**
  - se: the public check refuses an se off the pin with exit code 2 and names the se commit in every
    verdict; `<se>/scripts/se_modules.py sync` brings the clone there
    ([Public safety](../../../AGENTS.md#public-safety)).
- **Related:** wrk-003, gen-003

## p-go: the Go line on main (frozen)

### p-go-001 The rule of five

A surface a person sees (the root, `spec/` and `src/`) holds at most five visible files and five
visible folders.

- **Why:** a person looking at the project sees what is there for them, not the tools it is built
  with.
- **Without it:** the surface fills with build files and the person cannot find their way in.
- **Prevents:** a surface cluttered with tooling; a cluttered root that only grows.
- **Implementations:**
  - Go line (frozen): the battery's `rule-of-five` rule, configured in
    the Go line's src/internal/rules/five.yaml, with an allowlist that only shrinks.
- **Related:** doc-002

## Old principle numbers

The 22 design principles that came over from `main` and the rules they became.

| Principle | Rule | Name |
|---|---|---|
| 1 | gen-001 | Mechanize first |
| 2 | gen-002 | Single point of truth |
| 3 | des-001 | Locality |
| 4 | des-002 | Modularity |
| 5 | des-003 | Thin adapters |
| 6 | des-004 | One door per outside thing |
| 7 | tst-001 | Fakes that behave |
| 8 | tst-002 | Fast tests |
| 9 | tst-003 | Measured performance, no blind waits |
| 10 | tst-004 | Every mechanical rule is a check |
| 11 | wrk-001 | GitHub is the only shared state |
| 12 | wrk-002 | One work system |
| 13 | wrk-003 | Every session starts at the newest integration branch |
| 14 | gen-003 | Fail open for advice, closed for enforcement |
| 15 | dec-011 | Persons decide, agents execute |
| 16 | gen-004 | Blameless |
| 17 | gen-005 | Consistency |
| 18 | doc-001 | Talk only about what you own |
| 19 | doc-002 | Write for your reader |
| 20 | wrk-004 | The fleet works, sessions discuss |
| 21 | p-go-001 | The rule of five |
| 22 | wrk-005 | Steer before, check at the push |

The principles file's "How code is written" became `des-005` to `des-015`.
