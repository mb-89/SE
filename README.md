# SE

Reader: a person meeting SE for the first time.

SE is a Claude plugin with a Go program, `se`, behind it. While SE is on, the
plugin hands every event of a Claude session to `se`, the workspace's daemon.
SE also runs a fleet of unattended cloud sessions that take GitHub issues
labelled `se`, do them, and land each through one pull request.

## Install

    ./RUNME.sh

It names anything it needs that is missing, and installs the plugin for your
user, so every Claude session on this machine has one command, `/se`. Type
`/se on` to switch SE on in a session.

## Where to go next

- **Commands:** `/se help` in a session (`se help` on a terminal) lists them;
  `/se help <command>` shows one.
- **Working on SE itself**, its checks and debugging its daemon:
  [spec/development.md](spec/development.md).
- **Running SE on cloud boxes:** [spec/cloud.md](spec/cloud.md).
- **Why SE is built the way it is:** [spec/principles.md](spec/principles.md).

The skills, `se:<name>` in a session:

<!-- se:manifest skills -->
- [`se:briefing`](src/plugin/skills/briefing/SKILL.md): Brief the person on where SE stands, what waits on them first, then what is in flight, what happened and what is next, and ask what they want to work on. It presents; it does not act.
- [`se:coordination`](src/plugin/skills/coordination/SKILL.md): When se issue pull --take takes nothing, check what is broken in the fleet and fix it before ending. The work skill hands over to it.
- [`se:overhaul`](src/plugin/skills/overhaul/SKILL.md): Start an SE overhaul, or, as the box that took one, judge SE against every principle and the outside world and file its report. The work skill hands an issue labelled se-overhaul to it.
- [`se:retro`](src/plugin/skills/retro/SKILL.md): Start an SE retro, or, as the box that took one, collect its window, judge it, and file its report. The work skill hands an issue labelled se-retro to it.
- [`se:review`](src/plugin/skills/review/SKILL.md): Review an se-review gate whose sub-issues have closed, cold, as an agent that worked none of its tree. Find, then verify, then judge; block only on damage; end with se issue review pass|fail and its report. The work skill starts it as a fresh sub-agent on the reviewer model.
- [`se:work`](src/plugin/skills/work/SKILL.md): Run an SE box - pull each ready se issue and hand it to a fresh sub-agent in its own worktree, up to the box's cap, until nothing is ready and none is running. Every SE box runs this; the routine SE work starts it.
<!-- /se:manifest -->

The rules, each file owning one part:

<!-- se:manifest spec -->
- [spec/budgets.yaml](spec/budgets.yaml)
- [spec/cloud.md](spec/cloud.md): Cloud boxes: SE in a cloud environment
- [spec/coordination.md](spec/coordination.md): Coordination: a box that finds nothing to take
- [spec/development.md](spec/development.md): Development: working on SE
- [spec/index.md](spec/index.md): Index: the core and the module contract
- [spec/io.md](spec/io.md): I/O modules: the shape every one follows
- [spec/issues.md](spec/issues.md): Issues: how the fleet picks its work
- [spec/landing.yaml](spec/landing.yaml)
- [spec/models.yaml](spec/models.yaml)
- [spec/overhaul.md](spec/overhaul.md): Overhaul: is the design still right?
- [spec/principles.md](spec/principles.md): Design principles
- [spec/retro.md](spec/retro.md): Retro: do SE's rules hold across what landed?
- [spec/review.md](spec/review.md): Review: how a gate is reviewed
<!-- /se:manifest -->
