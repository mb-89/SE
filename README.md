# SE

Reader: a person meeting SE for the first time.

SE is a Claude plugin with a Go program, `se`, behind it. While SE is on, the
plugin hands every event of a Claude session to `se`, the workspace's daemon.
SE also runs a fleet of unattended cloud sessions that take GitHub issues
labelled `se`, do them, and land each through one pull request.

## Install

    ./RUNME.sh

On Linux, macOS, or Windows under Git Bash, it installs every tool SE needs
that is missing into `~/.se`, without admin rights, and installs the plugin
for your user, so every Claude session on this machine has one command,
`/se`. Type `/se on` to switch SE on in a session. The fleet's commands need
a GitHub login; where gh has none, RUNME runs `gh auth login` for you, and
finishes without it if you skip it.

## Where to go next

- **Commands:** `/se help` in a session (`se help` on a terminal) lists them;
  `/se help <command>` shows one.
- **Working on SE itself**, its checks and debugging its daemon:
  [spec/development.md](spec/development.md).
- **Running SE on cloud boxes:** [spec/cloud.md](spec/cloud.md).
- **Why SE is built the way it is:** [spec/principles.md](spec/principles.md).

The agents, one per role, each reached as `@agent-se:<name>` in a session
(or by asking Claude for its role):

<!-- se:manifest agents -->
- [`se:worker`](src/plugin/agents/worker.md), for the kind leaf: an issue with no sub-issues: work, landed into its manifest's branch.
- [`se:coordinator`](src/plugin/agents/coordinator.md), for the kind parent: an issue with sub-issues, a manifest at the top: the box coordinates its tree and lands it as one PR, as it runs the queue and checks the fleet when nothing is ready.
- [`se:reviewer`](src/plugin/agents/reviewer.md), for the kind gate: an se-review parent ready for review: reviewed cold.
- [`se:retro`](src/plugin/agents/retro.md), for the kind retro: an issue labelled se-retro.
- [`se:overhaul`](src/plugin/agents/overhaul.md), for the kind overhaul: an issue labelled se-overhaul.
<!-- /se:manifest -->

The skills, `se:<name>` in a session:

<!-- se:manifest skills -->
- [`se:briefing`](src/plugin/skills/briefing/SKILL.md): Brief the person on where SE stands, what waits on them first, then what is in flight, what happened and what is next, and ask what they want to work on. It presents; it does not act.
<!-- /se:manifest -->

The rules, each file owning one part:

<!-- se:manifest spec -->
- [spec/budgets.yaml](spec/budgets.yaml)
- [spec/cloud.md](spec/cloud.md): Cloud boxes: SE in a cloud environment
- [spec/coordination.md](spec/coordination.md): Coordination: finding and repairing what is broken
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
- [spec/stop.yaml](spec/stop.yaml)
<!-- /se:manifest -->
