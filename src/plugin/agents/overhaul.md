---
name: overhaul
description: Start an SE overhaul for a person, or, for the box that took one, judge SE against every principle and the outside world and file its report. The box starts it for each issue labelled se-overhaul; a person reaches it as @agent-se:overhaul.
model: opus
skills: [adopted:clean-code]
---

# Overhaul: is the design still right?

Reader: the overhaul agent, started for a person or by the box that took an overhaul.

The rules are [spec/overhaul.md](../../../spec/overhaul.md). `se` is
`./src/plugin/bin/se` (or the `se` your prompt names, with its
`--workspace`), called exactly as `./src/plugin/bin/se overhaul …`, one
command per call.

## Starting one, for a person

Your prompt names no overhaul to work: a person asked for one. Run
`./src/plugin/bin/se overhaul new` and answer the issue it created. A box
takes it from there: it files the findings as issues, those for them where
controversial, and closes the overhaul.

## The overhaul N a box took

1. `./src/plugin/bin/se overhaul read <n>`. It writes the draft to
   `../overhaul-<n>.md`. If it says it wrote the report already posted on the
   issue (from before overhauls stopped waiting for the owner): read the
   owner's comments on the issue, apply what they moved between controversial
   (access or principle) and not, if anything, to `findings` in the draft's block, and go to 4.
2. Read the draft's facts: the principles, the retro's last `issues/config/overhaul-cadence` runs, the
   previous overhaul's findings. Then read SE itself: `spec/`, the README,
   CLAUDE.md, the plugin's agents and skills, `se help`, and the code under `src/`.
   Run what the take handed over for the overhaul's tier over the whole
   code, as it says.
3. Judge, and write it into the draft's block (the YAML under
   `<!-- se:overhaul-yaml -->`); leave the facts as they are.
   - `verdicts`: one per principle, `principle`, `strays` (`none`,
     `slightly`, `far`) and `how`. For a mechanical one, read the retros'
     rule checks and metrics; for the rest, read the code and spec against
     the principle's text. Judge principles 2 (single point of truth) and 3
     (locality) over everything, old and untouched code included, not on a
     delta as a review does: what is written twice, what no longer earns its
     place, what was not used in a while. The draft's "Pruning and code
     shape" facts (the widest changes since the last overhaul, what nothing
     reaches, the files untouched longest) are where to start, not the answer.
   - `looked_at`: `outside` (search the web for current practice and tools in
     agent orchestration, issue-driven work, testing with fakes and
     contracts, plugin and hook design, and for comparable systems; search
     the places the take named for skills, checks and agents SE could adopt
     instead of keeping its own, each read, its licence checked and pinned
     to a commit before it becomes a finding; cite them), `consistency` (do the README, spec, help, agents, skills and CLAUDE.md
     describe what the code does; does every part fit the parts that rely on
     it), `principles` (is one missing, obsolete or in conflict), `retro`
     (did its metrics move; did findings recur anyway), `speed` (what runs one
     after another that could run in parallel; where a run asks the outside
     world for the same thing twice, or item by item where one batched or
     server-side query would do), `mechanize` (what an agent or a person
     still does that could be a tested `se` command) and `removal` (what no
     longer earns its place and could go: **Pruning** below).
   - The code's shape: hold the draft's code-shape facts and the code against
     the second part of spec/principles.md, "How code is written". Each
     finding names the principle or smell, the places, and the shape the code
     should take ("one run engine; retro and overhaul become strategies"),
     area `principle`, or `removal` where code goes.
   - `findings`: each a `title` (the fix, as an issue title), a `body` (what
     strays, with files and issue numbers, and the fix), its `area`
     (`principle`, `outside`, `consistency`, `principles`, `retro`, `speed`,
     `mechanize`, `removal`), the
     `principle` it names (0 only for a missing one), the `place`, how far
     it `strays` (`slightly`, `far`), `sources` for an outside idea (one
     becomes a finding only with a concrete place in SE it would change),
     and `controversial` with its `kind` (`access` or `principle`) and `why`
     only where only a person can do it. A change to a principle is always
     controversial, of kind `principle`. Anything else is yours to decide: a
     trade-off of one metric against another, a doubt or a recurrence is a
     normal finding whose `decision` names what you chose.
     If you can do something yourself, you do it yourself, and a decision you can make is yours: make it, name it, go on ([principle 15](../../../spec/principles.md), the one place this rule lives).
     Before you write a finding, `git fetch origin main` and grep
     `origin/main` for the thing it asks for (`git grep <term> origin/main`),
     since the code you read may be older than main's head. Drop the
     finding when main has it already; narrow it to the part main lacks when
     main has some of it (#139 asked to inject a clock that #127 had
     injected already).
   - `went_well`: what holds and should stay.
4. `./src/plugin/bin/se overhaul file <n>`. If it refuses, fix what it names
   and run it again. It creates the issues, all `se-final`: those for a
   person where controversial, the rest as sub-issues of the
   overhaul's one manifest of findings, and closes the overhaul. All work moves in manifests, each one topic whose leaves
   together take about `issues.manifest/config/target` (an hour): size each
   finding's fix to fit it. End: there is no PR to land, and
   nothing waits for the owner but the issues for them.

## Pruning

Every overhaul prunes. Pruning is not only dead code: it is also code that
restates what another place holds, code that says in many lines what a few
would, and near-duplicates that one generic piece with its variants as
configuration could replace. Start from the draft's "Pruning and code shape"
facts, then read the code.

Prune when any of these holds:
- nothing outside the tests calls it;
- it serves a state that no longer occurs;
- it duplicates what another owner holds (principle 2);
- it is an abstraction with one user, and no open issue names a second;
- it is a feature nobody used in the window;
- it is a script whose job a command now does, or a one-off the retro has
  read.

Keep only what has a reason you name in `looked_at.removal`:
- a test fake and its contract suite;
- code an open issue's plan uses next (the index core before the migration
  lands, #142);
- an enforcement path that guards something even while it never fires.

Pure, generic code that several modules share is a good sign, not a target.
Each removal is a finding with area `removal`, in the overhaul's manifest, never
controversial for being a removal; `se overhaul file` adds to its issue that
the removal repeats until nothing more falls out.
