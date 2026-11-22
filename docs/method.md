# Method: SE's method stays in SE

SE is the method for working on other things. A project SE works on, such as obs, kern or obs-html,
does not use SE: it carries no pin of SE, no file SE regenerates and no check of SE's. SE applies its
method when it works on a project, and an agent that is not SE works on the project without meeting
SE's rules (the person's direction of 22 Nov 2026).

This note owns that boundary: what a project keeps, what SE does in its place, and the packages
that move each project there, in order. It is a design: until each package lands, the README
describes what runs.

## Why

Today the dependency points the wrong way. Each project pins an SE version in `se.toml`
`[modules.se]` and `se.lock`, holds workflow copies that SE regenerates at that pin, and runs SE's
public check and work-model checks in its own CI.

- A project that pins SE and runs SE's checks argues about how an agent works on it. The method is
  the agent's: "obs doesn't argue about the way an agent works over it" (the person, 22 Nov 2026).
- An agent other than SE that works on the project meets SE's rules in the project's CI, as
  failures of a check it never chose.
- Every change to SE's method needs a pin move in every project before it reaches it.

Not picked: keeping the pin and only moving the checks. The pin is itself the project choosing SE's
version, so it goes with the checks.

## What a project keeps

| Piece | Today | After |
|---|---|---|
| `se.toml` | SE's settings for the project, its `[modules.se]` pin among them | stays as SE's configuration for the project, with no pin ([Project facts](#project-facts)) |
| `[modules.se]` and `se.lock` | the SE version that works on the project, and its locked commit | gone: SE works on every project at the SE version that runs ([The pin](#the-pin)) |
| Release tagging, branch cleanup, ref maintenance | copies SE regenerates at the pin (`release.yml`, `release-tag.yml`, `branch-cleanup.yml`, `ref-maintenance.yml`) | plain workflows the project owns, copied once and never regenerated ([The workflows](#the-workflows)) |
| The suite actions and the trust record | SE's `suite-time`, `suite-shard` and `integrator-pass` actions, `se-pass-record.yml` | gone: the project's CI runs its own tests its own way |
| CI's SE steps | SE cloned at the pin, its commit gate, issue rule, field-report check, layout check and suite runner | gone: `integrate` runs them before it lands ([The checks](#the-checks)) |
| CI's own steps | the project's tests, builds and lints, beside SE's | stay: the project's required check runs only these |

`docs/components.md` drops `se` from obs's and kern's component lists: SE is not a component, needs
no topic, and the finder needs no rule for it
([components.md "The requirement list"](components.md#the-requirement-list)).

## Project facts

SE needs facts about each project it works on: its test command and time budget, its commit
identity, its landing mode and its release mode. They stay in the project's `se.toml` (the person's
decision of 22 Nov 2026, on the issue's open point).

- **What it is**: SE's own configuration for that project. Its presence marks the project as one
  SE manages; it holds the values SE uses there (`[project]`, `[tests]`, `[integrate]`, the release
  setting).
- **What it is not**: it holds no SE pin and nothing that runs SE's method from the project.
  `[modules.se]` and `se.lock` go; a project's own modules, such as obs's adapters, stay its own.
- **Another agent ignores it**: no workflow, hook or check of the project reads it on SE's behalf,
  so an agent that is not SE meets a file it may leave alone.

The options the issue named, and why the decision fell as it did:

- **A plain file the project keeps, read by SE and holding no SE machinery**: picked, as `se.toml`
  itself, since it is already that file once the pin leaves it.
- **A list in SE**: not picked. It would put each project's facts in SE's tree, so a project's new
  test command would need an SE change, and SE's tree would name the projects it works on.

## The pin

Without a pin, the SE that works on a project is the SE that runs: the session's SE root.

- The public check's rule [pub-007](../src/skills/work-model/references/rules.md#pub-007-one-se-version-per-check)
  keeps its first half: every verdict names the SE commit that ran it. Its second half, refusing a
  running SE that is not at the project's pin, has no pin left to compare and goes.
- A breaking change in SE's method reaches every project the next time SE works on it, with no
  pin move anywhere; SE's own landing is where such a change is tested.
- `se_modules.py` refuses an entry `se` in a project's modules, naming this note, so a pin cannot
  come back by habit. SE's own `se.toml` pins its components (kern, obs) as before.

## The workflows

Release tagging, branch cleanup and ref maintenance are plain workflows that do a job on the
project's own events. They need no agent and no SE, so they stay, as the project's own files.

- **Copied once**: the project's package copies each file once, without the generated header that
  names a source, a pin and SE's place. From then on the project owns it and edits it like any
  other file.
- **Never regenerated**: `se_workflows.py check` and the regeneration at `update se` go. A later
  improvement to SE's copy reaches a project only as a change the project takes, like any outside
  fix.
- **What SE still ships**: the files a new project or application copies once (`se.py new app`), as
  plain files; nothing a project's workflow calls from SE at run time.
- The release workflow keeps reading the project's `se.toml` `[project] version`, since tagging
  that version is the project's release; it needs no other SE file.

## The checks

Today a landing is checked twice: `integrate` runs the complete suite, the project checks and the
public check on the landing head, and the project's CI `check` runs SE's steps again on the same
head. The second run goes; `integrate` gives the same assurance from SE alone.

### What integrate runs

Before it opens the landing pull request, `integrate` runs on the landing head every SE step the
project's CI ran:

- **The public check's commit gate** over the landing's range, and the full check of its tree, as
  today (`public_check.py --range`), at the running SE.
- **The issue rule** (`pr_issues.py`): the work pull request's description names an open work issue
  of the project.
- **The field report** (`field-report --check`) of the work pull request's description against its
  work issue, with its component kinds; the guard already runs here.
- **The suite in budget** (`work_tickets.py suite`), as today, and the project's own check
  commands (`--check-command`).

None of these needs a runner, so the landing's assurance no longer depends on what a project's CI
chose to run.

### The landing record

CI's `check` on the landing head is today the host's record that SE's steps passed on that tree. It
is replaced by the integrator's verdict, written where every host's tools can write it:

- **The verdict line**: the landing pull request's description ends in one line naming the SE commit
  that ran the checks, the landing head's tree, each check's verdict and the suite's hash, beside
  the metrics line it already ends in ([README "Metrics"](../README.md#metrics)).
- **Read back**: `integrate --read-back` refuses a landing whose description lacks that line, or
  whose line names another tree than the commit landed, and closes nothing.
- **The host's own record** stays the project's required check: the landing waits for it as today,
  by the name `se.toml` `[integrate]` gives it (default `check`), and merges only on its success.

### What CI still checks

The project's CI checks the project: its tests, its builds and its own lints, on every pull request
and every push, as the project chooses. It runs no SE step, clones no SE and reads no SE file.

- A push no SE session made, such as another agent's, meets only the project's own CI. That is the
  goal, not a gap: SE's rules bind SE's work.
- SE does not build on such a push unseen: SE's sync runs the public check on the tree it starts
  from, and a hit stops the work it would start, naming each finding, before SE commits on top.
- SE's hooks keep running the public check on every commit and push SE makes. They are local
  configuration of SE's checkout of the project (`core.hooksPath`, set by `scripts/setup.sh
  <path>` or SE's start), never a committed file of the project.

### What goes with the second run

- **Trusted landings** for a project ([README "Trusted landings"](../README.md#trusted-landings)):
  the shortcut let a project's CI skip SE's suite on a record of the integrator's pass. With no SE
  step in that CI there is nothing to skip; a project that wants fewer minutes trims its own CI.
- **Landing without CI** stays: where a host has no runners, the integrator's verdict is the only
  verdict, as today.
- SE itself is unchanged: SE's own `check` runs SE's checks, since SE is where its method lives.

## The packages

In order; each is one work issue. SE's packages (1 to 4) land first, so `integrate` runs every check before
a project's CI stops running it; each project's package follows SE's release of them.

1. **se: integrate runs the method's checks** (`integrate-runs-method-checks`).
   `scripts/work_tickets.py`: `integrate` runs `pr_issues.py` and `field-report --check` of the work
   pull request on the landing head, writes the verdict line into the landing description, and
   `--read-back` refuses a landing without it; the landing waits for the check `[integrate]` names.
   README [Landing on main](../README.md#landing-on-main); `tests/test_work_tickets.py`.
2. **se: no SE pin in a project** (`no-se-pin-in-projects`). `scripts/se_modules.py` refuses
   `[modules.se]` outside SE; `scripts/public_check.py` drops the pin comparison and keeps naming
   its SE commit; rule pub-007 in `src/skills/work-model/references/rules.md`; README
   [Modules](../README.md#modules) and [Project settings](../README.md#project-settings); the work
   model's [What the project provides](../src/skills/work-model/SKILL.md#what-the-project-provides).
3. **se: workflows copied once** (`workflows-copied-once`). `scripts/se_workflows.py`: `write`
   copies a plain file without the generated header, `check` and the regeneration at `update se`
   go, `SHIPPED` loses `integrator-pass`, `suite-shard` and `suite-time`; trusted landings for
   projects go (`scripts/ci_trust.py`, `se-pass-record.yml`); README
   [Workflows](../README.md#workflows), [Release tags](../README.md#release-tags) and
   [Trusted landings](../README.md#trusted-landings).
4. **se: the start check of a managed project** (`managed-project-start-check`). `work_tickets.py
   sync` runs the public check on the tree it starts from and stops on a hit; `scripts/setup.sh`
   and `setup.ps1` keep a project's hooks as local configuration only; their tests.

### Tickets for other repositories

Each follows SE's release of packages 1 to 4, and is filed in its own repository.

5. **kern: SE leaves kern** (kern's repository). `se.toml` loses `[modules.se]`; `se.lock` goes;
   `.github/workflows/check.yml` drops SE's clone, commit gate, issue rule, field-report step and
   suite runner, and runs kern's own vet and tests; `check-rerun.yml` becomes kern's own plain file
   or goes; `AGENTS.md` and README stop naming an SE pin.
6. **obs: SE leaves obs** (obs's repository). `se.toml` loses `[modules.se]`; `se.lock` goes;
   `.github/workflows/test.yml` drops SE's clone, `se_workflows.py check`, the commit gate, the
   issue rule, the field-report step and the `suite-time` and `suite-shard` actions, and runs obs's
   own suite command; `release.yml`, `release-tag.yml`, `branch-cleanup.yml`,
   `branch-cleanup-on-close.yml` and `ref-maintenance.yml` lose their generated headers and become
   obs's own.
7. **obs-html: SE leaves obs-html** (obs-html's repository). The same as obs's package, for each of
   those pieces it carries: no `[modules.se]` or `se.lock`, its workflow copies its own, its CI on
   its own tests.
