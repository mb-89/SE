# The Go line: inventory and port plan

Reader: a worker on one of the port issues listed under [The plan](#the-plan), and SE dispatching
them. It is the one place that says what each Go capability became; the port issues own the work,
the commands they add own the behaviour.

The Go line is `main`'s history at ff01204 (tag `archive/go-line`): about 28,000 lines of Go plus
17,000 of tests, a Claude plugin, a per-workspace daemon and a fleet of unattended cloud boxes.
Read it with `git show ff01204:<path>` and `git ls-tree -r ff01204` after
`git fetch origin tag archive/go-line`; never check it out over a branch.

## What SE does today

SE dispatches and integrates work, and builds its documentation through obs:

- SE (the dispatcher, `src/agents/se.md`) talks with the person, files work issues
  (`work_tickets.py file`, `route`, `backlog file`) and starts worker and integrator sessions;
- a worker turns one work issue into one pull request whose description is its field report
  (`work_tickets.py intake`, `field-report`, `deliver`);
- the integrator is the merge queue: `work_tickets.py queue`, `integrate`, the complete suite in its
  budget, releases;
- the public check, its hooks and CI's `check` job keep the repository publishable;
- `se_start.py` greets and refreshes SE and its modules; `se_modules.py` pins repositories such as
  obs, which builds the documentation; `timeline.py` and `deck.py` show the work and the decisions.

The Go line did all of this in another model (issues labelled `se`, claims as `issue-<n>`
branches, boxes started by a routine, manifests, landing answers) and more: review, retro,
overhaul, fleet diagnosis, a Stop hook, a daemon with an index and a snapshot. The model is gone;
what is worth having of the rest is filed below.

## Inventory

Verdicts: **covered** (SE does it today), **obsolete** (the cloud fleet or today's work model has no
place for it, with the reason), **port the idea** (rebuilt for today's model), **port the code**
(the Go logic carried over). Sizes: S, M, L. Issue numbers are the port issues.

### The platform: index, daemon, I/O

| Go capability | What it did | SE today | Verdict | Size |
|---|---|---|---|---|
| index core (`src/index`) | names with one writer, a store, snapshots, pushes, built-in values | nothing | obsolete: one process per command, no shared in-memory state to guard; single point of truth is the rule book's [gen-002](../src/skills/work-model/references/rules.md#gen-002-single-point-of-truth) | L |
| wiring file and modules (`wiring.yaml`, `module.go`) | binds module ports to names; one package per module | nothing | obsolete with the index; the migration it planned never moved a module | M |
| collector (`commands.go`, `help.md`, `se manifest`) | one command registry renders the CLI, `/se`, help and manifests | `work_tickets.py docs` renders the README from its argparse registry; `se_plugin.py build` renders the host layouts | covered | S |
| daemon (`se serve`, `start`, `stop`, `restart`, `internal/daemon`) | per-workspace process holding the index, loopback HTTP, idle exit | nothing | obsolete: cloud containers are short-lived, a cold Go build takes 13 s, and no state needs a host | M |
| session switch and panel (`on`, `off`, `ui`, `hooks/register.tsx`) | forwards every session event to the daemon; a button grid in a pane | SessionStart hook only (`bootstrap.sh --hook`) | obsolete: SE is on whenever its plugin loads; no pane is used | M |
| snapshot (`snapshot.go`, `github/snapshot`) | warm copy of what `issue pull` reads, refreshed every 2 minutes | nothing | idea covered by SE#748 (a cache with stated freshness); no daemon | M |
| `status` | whether a daemon answers and which commits SE came from | `se_start.py status` (version, modules, update check) | covered | S |
| `update`, stale-se refusal (`update`, `stale.go`, `checkout.go`, `commit.go`) | pull main, rebuild, refuse an se older than main | `se_start.py refresh`; pinned se per check ([pub-007](../src/skills/work-model/references/rules.md#pub-007-one-se-version-per-check)) | covered | S |
| clock, disk, proc, http, session I/O (`internal/io/*`) | one module per outside thing, with fakes held to contract suites | tests fake `run_gh`, git in temporary repositories, injected clocks (work model "Tests") | covered as a test rule; the module layer is obsolete | M |
| GitHub client (`io/github`) | REST in process, ETags, the owner's token, a recorded fake | `work_tickets.py`'s door (gh) and, without gh, the hand-off plan for the session's GitHub tools | covered; in the cloud no token reaches code, so the Go client could not run there | L |
| rate-limit pacing (`github.Limit`, `quota-floor`) | back off on 403/429, pace writes, keep a quota floor | nothing | open as SE#750 (discovery: likely moot) | M |
| budgets and call timing (`budgets.yaml`, `calls.jsonl`) | soft and hard budgets per command class; every call timed | `se.toml [tests]` budget; `se_start.py status` 1 s budget | open as SE#749 and SE#748 | M |
| `guidance`, skills line (`internal/guidance`) | hands an issue's skills and the principles to an agent | plugin skills and agents; AGENTS.md | covered; per-role outside skills open as SE#754 | S |
| outside plugins (`fleet plugins`, `internal/reuse`) | pinned outside plugins and skills, a list per agent tier | nothing | open as SE#754 | M |
| models (`models.yaml`, rule `agents`) | one model per agent, held equal to the front matter | each agent's front matter in `src/agents/` | covered | S |
| Go build and setup (`build.sh`, `RUNME.sh`, `cloud.md`) | installs Go tools into `~/.se`, builds `se` in the setup script | `bootstrap.sh` (uv, Python, modules); README "Install" | covered | S |
| development guide (`development.md`: two clones, Windows check, daemon debugging) | how to work on the Go line | AGENTS.md | obsolete with the daemon | S |

### The work model: issues and the fleet

| Go capability | What it did | SE today | Verdict | Size |
|---|---|---|---|---|
| `issue new`, the mark, `--blocked-by` | the one way to create fleet issues, with blockers and a mark | `work_tickets.py file` (labels, dedupe, `<!-- se:fleet -->`), `block` | covered | S |
| `issue edit`, `supersede`, duplicates | rewrite keeping the mark; close by a successor or as duplicate | GitHub edit; dedupe closes twins | covered | S |
| `issue pull`, `--take`, claims as branches | the next ready issue, claimed by an atomic branch push | `work_tickets.py ready`, `start`; the integrator starts sessions | covered in today's model; branch claims obsolete (one integrator assigns work) | L |
| kinds registry (`kinds.go`) | which agent works an issue: worker, coordinator, reviewer, retro, overhaul | SE, integrator, worker; `discovery` label | covered; reviewer, retro and overhaul return as commands and an agent (#873 to #879) | S |
| manifests and nesting (`fanout.go`, `land.go`, coordinator) | all work in manifests landed as one PR; parents coordinate trees | one work issue, one pull request; the integrator lands each | obsolete: the integrator is the merge queue | L |
| `issue land`, landing answers (`landing.yaml`) | check, push, PR, and fifteen questions every landing answers | `work_tickets.py deliver`, the field report and its `--check` | covered: the field report is the record | M |
| `issue keep` | stay with a PR until it merges, merging main in | the integrator merges into the newest main | obsolete | M |
| `issue close --fixed-by` | close an issue whose fix is on main | `integrate` closes the work issue | covered | S |
| `issue tree` | the open queue and when its last issue closes | `timeline.py` (Planned days), `queue` | covered; the estimate is pruned | M |
| `briefing` skill, pending sources | what waits on the person, in flight, happened, next | the catch-up skill, `queue` escalations, the decision deck | covered | M |
| stuck work, lease, takeovers (`stuck.go`, `takeover.go`) | a quiet claim is taken over after its lease | the integrator restarts a stuck worker from its session events | port the idea as part of fleet check (#880) | M |
| routine and fan-out (`SE work`, `SE_ROUTINE_FIRE_URL`) | starts boxes on merges, every 4 hours, and when boxes are full | the integrator starts workers with `create_session`; scheduled tasks | obsolete | M |
| pause switch (`fleet.box/config/paused`) | a take reads it and starts nothing | nothing | open as SE#756 | S |
| Stop hook (`hook stop`, `hook prompt`, `stop.yaml`) | refuses a box's stop while an issue it took is open | `work_tickets.py stop-check`, the plugin's Stop and SubagentStop hook (README "Stop hook") | ported as an idea (#881): it holds a worker to a delivered pull request | M |
| `fleet check`, `fleet fix` | every stuck or stray piece of work, with its remedy | the integrator's judgment | port the idea (#880); `fix` pruned | M |
| `fleet prune` | deletes stray `issue-<n>` and `claude/*` branches | `integrate` deletes the branch it landed | covered; branches of closed issues reported by #880 | S |
| `fleet refresh` | merges main into every open manifest branch | nothing | obsolete with manifests | S |
| `fleet rules` | tells each open PR the rules a new rule breaks | the integrator runs the suite on each merge into the newest main | obsolete | M |
| `fleet trust`, `tests/passed` | CI trusts a battery record of the exact tree | the push gate's recorded verdicts (`work_tickets.py verified`); CI runs the suite in budget | covered | S |
| merging into main (`coordination.md`) | a PR merges once green; red main first | `integrate` lands through a squash PR once `check` passes | covered | S |

### The judgment runs: review, retro, overhaul

| Go capability | What it did | SE today | Verdict | Size |
|---|---|---|---|---|
| review brief (`review brief`) | everything a cold reviewer starts from; the workers' accounts withheld | nothing (the integrator reviews the field report, not cold) | port the code: its brief rules, rewritten in Python (#873) | M |
| issue review (`issue review pass` and `fail`) | validates a review report, files findings, bounds the loop at one retry | nothing | port the code: its report schema and refusals, rewritten in Python (#874) | M |
| se:reviewer | find, verify and judge as separate steps; only damage blocks | nothing | port the idea (#875); whether it gates integration is the owner's | S |
| retro collect | the window from GitHub, metrics, rule checks, the previous retro's score | a retro template and a discovery worker reading by hand (SE#864) | port the idea (#876) | M |
| retro report, `retro new` | refuses an incomplete judgment, files findings, closes the retro | the retro worker files by hand | port the idea (#877) | M |
| retro and overhaul cadence (`cadence.go`) | starts a retro every N closed issues, an overhaul every M retros | nothing | the owner's, with SE#752 | S |
| overhaul new, read, file | is the design still right: principles, retro trend, pruning facts | nothing | port the idea (#879) | M |
| shape (`internal/shape`) | dead code, duplicates, sizes, untouched files, long functions | nothing | port the idea for Python (#878) | M |
| principles (`principles.md`, 22 of them) | what review, retro and overhaul measure against | the rule book (`gen`, `pub`, `tst` sections) | the owner's: which principles join the rule book (SE#865) | S |

### The battery and its rules

| Go capability | What it did | SE today | Verdict | Size |
|---|---|---|---|---|
| battery (`tests/check.sh`, `internal/battery`) | lint, `go test`, deadcode, plugin validation, budgets, a decoy | `uv run pytest -q` in budget; CI `check` | covered | M |
| `se rules`: `go-in-src`, `io-module`, `module-imports`, `library-users`, `plugin-clock`, `fake-contract`, `test-package`, `test-swap`, `fast-test`, `rule-of-five`, `programs`, `help-sentences`, `budgeted` | Go and index layout rules | the suite's budget; test rules in the work model | obsolete with the Go code | M |
| `se rules`: `agents`, `manifest`, `reader` | agents' models, generated sections, a reader line per spec | `se_plugin.py check`, `work_tickets.py docs --check`, agent-definition tests | covered | S |
| `se rules`: `repo-path`, `se-command` | no path or command that does not exist | nothing | open as SE#755 | S |
| `se rules`: `no-binary`, `large-file`, `todo-issue` | no tracked binaries, no oversized files, no TODO without an issue | `tests/test_repository.py`, with reasoned allow lists | ported (#882) | S |

## Start on invoke

The se agent gets every ported capability as a **command its scripts provide**, run in the
session's own process when needed: `review.py`, `retro.py`, `overhaul.py` and
`work_tickets.py fleet-check`. Nothing new runs in the background, and no daemon, index or
snapshot is started.

What starts at session start is what starts today, plus lines read from a cache:

| step | when | cost |
|---|---|---|
| `bootstrap.sh --hook`: uv, Python, modules, then `se_start.py status` | every session start | 0.24 to 0.35 s measured on a cloud container (3 runs) |
| `se_start.py check` in the background | a cache older than an hour | none at start; the next start shows its result |
| retro due and fleet findings (#883) | from the same cache | none at start: `status` stays within its 1 s budget |

Where gh is signed in, the background check also counts what landed since the last retro and runs
the fleet check. In the cloud no token reaches SE's code, so the greeting adds nothing there and
the se agent runs the fleet check's plan through its GitHub tools at its first turn.

Why no daemon: a cloud container lives for one session; a Go program would have to be built at
start (12.8 s with a cold cache, 13.8 s with module downloads, 0.55 s warm, measured on ff01204) or
downloaded as a per-platform release; and the snapshot it kept needs a GitHub token the cloud does
not give to code.

## Language

Every part to port is Python inside SE's scripts; nothing calls for Go. Recommended for the whole
port:

- what runs today is Python on the standard library, installed by `bootstrap.sh` with no admin
  rights on every platform; Go adds a toolchain or a release pipeline per platform;
- the cloud path to GitHub, the hand-off plan for the session's GitHub tools, exists in
  `work_tickets.py`; the Go client assumed a token;
- one suite, one budget, one CI job; a second language doubles each;
- what is worth porting is rules and procedures (review, retro, overhaul, fleet check) that must be
  rewritten for today's model anyway: field reports instead of landing answers, work issues instead
  of manifests. Little Go code would carry over as it is.

New commands go into scripts of their own (`review.py`, `retro.py`, `overhaul.py`) that load
`work_tickets.py` for its door and filing, as `se_start.py` loads its siblings, so
`work_tickets.py` does not grow further. The owner decides the direction in the deck (SE#865).

## Naming

The collision goes away with the index: the Go line's "modules" (plug-ins of the index) are pruned,
so **module** keeps its one meaning, a pinned repository (`se.toml [modules.<name>]`,
`se_modules.py`), which projects outside SE already use. The ported capabilities are **commands**
of SE's **scripts**. Should index-like plug-ins return, they would be **components**, never modules.

## The plan

Filed 12 Nov as work issues, in this order, each worker-sized; `Planned:` is the day the dispatcher
runs it, ahead of the remaining cleanup items. Blockers are named in each body.

| order | issue | what the owner gets | planned |
|---|---|---|---|
| 1 | #873 feat/review-brief | `review.py brief`: a cold review brief of a delivered PR | 13 Nov |
| 2 | #874 feat/review-report-files-findings | `review.py file`: a checked verdict, findings filed | 13 Nov |
| 3 | #875 feat/reviewer-agent | "review PR #n" to the se agent | 14 Nov |
| 4 | #876 feat/retro-collect | `retro.py collect`: a retro's facts in one command | 14 Nov |
| 5 | #877 feat/retro-file | `retro.py file`: a retro that files itself | 15 Nov |
| 6 | #878 feat/overhaul-code-facts | `overhaul.py facts`: pruning facts for Python | 15 Nov |
| 7 | #879 feat/overhaul-read-and-file | the overhaul: is the design still right? | 16 Nov |
| 8 | #880 feat/fleet-check | `work_tickets.py fleet-check`: what is stuck, with remedies | 16 Nov |
| 9 | #881 feat/worker-stop-hook | a worker cannot stop without a delivered PR | 17 Nov |
| 10 | #882 chore/repository-hygiene-checks | no binaries, no oversized files, no orphan TODO | 17 Nov |
| 11 | #883 feat/start-names-whats-due | the greeting names a retro due and fleet findings | 18 Nov |
| 12 | #884 chore/retire-go-line-inventory | this file removed | 19 Nov |

Already filed and not repeated here: SE#748 (feedback within a second, the snapshot's idea),
SE#749 (cost per command), SE#750 (rate limits), SE#754 (outside plugins per role), SE#755
(dangling references), SE#756 (pause switch), SE#752 (review cadence, the owner's).

## Pruned for good

Not ported, and no issue will bring them back without the owner:

- the index core, the wiring file, families, the collector's adapters and the module migration;
- the daemon and everything that needs it: `serve`, `start`, `stop`, `restart`, `on`, `off`, `ui`,
  the session event log, the bridgehead hooks and the snapshot keeper;
- the Go I/O modules and their contract suites, the program allow list, the GitHub REST client;
- branch claims, leases on claims, takeover markers, manifests, coordinator trees, `issue keep`,
  `fleet refresh`, `fleet rules`, `fleet fix`, the routine and its fan-out;
- landing answers (`landing.yaml`) and the battery record `tests/passed`;
- the Go-specific battery rules, `golangci-lint`, `biome` and `deadcode` steps;
- the queue estimate of `issue tree`;
- `RUNME.sh`, `build.sh` and the setup script that built `se` in the cloud.

The remote has no tag `archive/go-line`; commit `ff01204`, an ancestor of `main`, keeps all of
it readable.

## Its end

This file has a reader only while the port runs: #884 deletes it once the issues above are closed.
