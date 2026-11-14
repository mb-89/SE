# The Go core: design and plan

Reader: the dispatcher filing the core's build, and each worker on one of its issues. This note
owns the design of the core, its bus, its components and how SE starts it. The work issues own the
work; once built, the core's own repository owns its contract.

The owner decided on 13 Nov that SE gets a Go core again: the index, with a NATS bus. Everything
that can be mechanized becomes a component of it; what is judgment stays a skill. Nobody starts
the core by hand: the SE plugin's hooks start it in the background, in the cloud too. The core
gets a repository of its own and becomes the template every new application starts from.

This decision overturns the 12 Nov port plan's verdict that the index, the daemon and the bus
were obsolete; [The Go line](#the-go-line) says what of it comes back and what does not. Every
number below was measured on
13 Nov in a Claude Code cloud container (4 cores, 15 GB, Go 1.24.7 preinstalled), in
[Measurements](#measurements).

## Naming

| word | meaning |
|---|---|
| **module** | a pinned repository: `se.toml [modules.<name>]`, synced by `se_modules.py` |
| **component** | a part that plugs into the core: it declares inputs, outputs, config and commands |
| **command** | what a component or a script offers a person or an agent |
| **core** | the index (names, store, snapshots, catalog), its bus and its host process |
| **application** | a repository built on the core; SE is one |

The Go line's word for a plug-in, "module", is not reused. The core's repository is itself a
module of every application that pins it.

## The core

The core is the Go line's index, nearly unchanged, hosted on quackitect v5's bus. It holds no
business logic and no line of it names a component.

### What comes back from the Go line

From `ff01204` (`spec/index.md`, `src/index/index.go`, `module.go`, `catalog.go`, `wiring.go`,
`indextest/`), about 1,600 lines of Go with their tests:

| part | as it was | what changes |
|---|---|---|
| names | a path of segments with exactly one writer, a type and a built-in value | unchanged |
| families | `session/<id>/events`: keys come and go inside one declared name | unchanged |
| store and revision | one revision for the whole store, raised by every commit | unchanged |
| snapshots | a run reads all its inputs at one revision | unchanged |
| pushes and waves | a changed name runs its readers once, lowest height first | unchanged; a run may now be in another process |
| built-in values | an unprovided name reads its writer's built-in value, marked `not provided` | unchanged; a component that is down or switched off reads the same way |
| catalog check at start | refuses two writers, an unbound input, two types on a wire, a cycle, a missing built-in or help | gains two refusals: an input or a request port wired to a component that is switched off |
| collector | commands declared by modules, rendered by every surface | unchanged; it now gathers Python components' commands too |
| actions | specified in `spec/index.md` alone; `ff01204` has no code for them | built new, as [Actions](#actions) says; still no undo |
| wiring file | `src/index/wiring.yaml`, embedded in the binary | `wiring.toml` in the application, read at start: a Python component is not compiled in, and Python's `tomllib` reads it for the fake core |
| fake index | `indextest`: seed by local name, run, assert writes and requests | comes back twice, in Go and in Python, held to one contract suite |
| host | `se serve`, a daemon on loopback HTTP with a token, idle exit | the core process; NATS replaces HTTP, see below |

### Actions

An action is a command that reaches the outside. kern builds it from the Go line's spec, in
`kern/index`:

- **Request ports.** A component declares a local request port with its request and answer
  types and its help (`index.Request[Req, Ans](port, help)`, `[requests]` in `component.toml`).
  The wiring binds it to a verb of an I/O component (`index.Verb[Req, Ans](verb, help, fn)`), as
  `"clerk.file" = "ledger.append"`; the catalog check refuses a type mismatch and an unbound port.
- **A result in steps.** A command answers an `index.Result`: `Text`, `Writes` and `Requests`.
  The core commits the writes first, then sends the requests in order, each to its bound verb.
- **The continuation.** Where the result sets `Then`, the core hands it the answers in the order
  of `Requests`; it answers the next step's result. The command's text is every step's text, in
  order, and the command ends with the first step that sets no `Then`.
- **No undo.** A failed request stops the list and fails the command with its reason; the writes
  already committed and the requests already answered stay.
- **The fake core.** The fake hands each request the answer the test gives it, so a
  continuation runs without an I/O component ([The fake core](#the-fake-core)).

The Go line's GitHub snapshot comes back as names the GitHub component writes
([GitHub in the cloud](#github-in-the-cloud)). Its I/O modules for the clock, the disk, processes
and sessions come back as shared I/O components ([The core's repository](#the-cores-repository)).
git is one of them, kern's git door: today the package `kern/git`, which `kern/host`,
`kern/tools/release` and `components/origin` call, its fake `kern/git/gitfake` held to the same
contract cases as real git, as `tests/test_git_door.py` holds SE's git door. It becomes an I/O
component once a caller needs git as an action rather than a call it waits on.

### What comes from quackitect v5

From v5's `src/index/bus.go` and `spec/design_output/model.md` ("The inner protocol",
"Processes", "Watchdogs"):

| part | in v5 | taken |
|---|---|---|
| embedded NATS server | `server.NewServer` on `127.0.0.1`, `RANDOM_PORT`, a 24-byte token, `NoLog`, `NoSigs`, no JetStream, no disk | yes, as it is |
| subjects | `get.`, `val.`, `run.`, `in.`, `commit.`, `act.`, `io.`, `lease.` | yes, renamed and reduced in [Subjects](#subjects) |
| the standing file | `.se/.runtime/standing.json`: bus port, token, pid, stamp | yes; a `pid` that runs nowhere, or whose bus accepts no connection, reads as absent |
| detached start | `Setsid` on Unix, a detached process on Windows (`src/index/detach_*.go`); a claim file while one caller starts it | yes, for the hooks' start |
| leases | a heartbeat on `lease.<part>` from the work loop itself; a lapsed lease marks names stale | yes, for components and for sessions: a component beats every 5 s and its lease lapses 15 s (three beats) after its last beat; a session's lease is the hooks' ([Lifetime](#lifetime-bound-to-the-session)) |
| placements | instances grouped into processes by config | yes: Go components run inside the core by default, other languages in their own process; a placed process that exits is not restarted, and the health shows it with its exit |
| the stamp | the hash of the Go type package; a peer with another stamp is refused | becomes the contract version, since Python peers cannot share Go types |
| SQLite, the `files/` mirror, folds, views, chunks, the LSP relay, operations, the cage | | not taken; each can return as a component when an application needs it |

The one decision that is SE's own: v5 lets clients in over HTTP `/v1` and keeps NATS for its own
processes. The core speaks NATS alone, to components and clients alike. One protocol means one
client library per language, and NATS's text protocol needs about 150 lines of standard-library
Python (measured: attach and round trip in 2.3 to 2.8 ms).

### Single writer, enforced by the bus

v5 shows one shared token to every peer. The core gives each component instance a user of its
own, with NATS permissions that let it publish only on its own subjects. A Python component cannot
commit another's name even by mistake; the Go line's "a commit names the module instance" becomes
a refusal of the server itself.

| user | may publish | may subscribe |
|---|---|---|
| `core` | everything | everything |
| a component instance `<i>` | `commit.<i>`, `lease.<i>`, `in.<i>`, `say.<i>.>`, `get.>`, `call.>` | `run.<i>`, `cmd.<i>.>`, `io.<i>.>` for an I/O component, `val.>`, its own inbox |
| `client` (commands, hooks) | `call.>`, `get.>`, `hook.>` | `val.>`, its own inbox |

Each user hears the replies to its own asks on its own inbox, `_INBOX.<user in hex>.>` (the
core's is `_INBOX.>`). Hex makes the user one token, so no inbox lies inside another's: `issues`'s
does not hold `issues/pull`'s. An instance answers the core's `cmd.` and `io.` requests with one
reply each on the subject the request names.

The core writes the users and their random passwords into the standing file and hands each
spawned component its own through its environment (`CORE_BUS`, `CORE_USER`, `CORE_TOKEN`). The
file is for the owner of the checkout alone:

- on Unix by its mode, `0600`, in `.se/.runtime/`, whose mode is `0700`;
- on Windows by the ACL it inherits from the checkout's folder, as the core sets none of its own:
  it is as private as the checkout is.

## The component contract

### A component declares itself in one file

Each component has a `component.toml` beside its code. The core reads every declaration at start
and checks the whole catalog before any component process runs, so the check costs milliseconds
and a broken catalog never starts. The process, once attached, must declare the same hash.

The check's budget is 20 ms for a catalog of 200 instances, about ten times the 1.54 to 1.74 ms
measured ([Measurements](#measurements)). Its owner is `CheckBudget` in
`kern/index/budget_test.go`, which `TestTheCatalogCheckKeepsItsBudget` holds the median of nine
checks to, so a slower check fails kern's tests before a merge.

```toml
name = "fleet"
contract = 1
io = false                       # an I/O component sets true; only it reaches the outside
help = "What is stuck or stray, with its remedy."

[inputs]
issues = "github.issues"         # local port = type; the wiring binds the port to a name
pulls  = "github.pulls"

[outputs.findings]
type = "fleet.findings"
builtin = []
help = "Each stuck or stray piece of work, with its remedy."

[config.lease_hours]
type = "int"
builtin = 3
help = "How long in-progress work may go without a push."

[commands.fleet-check]
usage = "fleet-check [--json]"
summary = "List what is stuck or stray."
group = "Fleet"
help = "Each finding names the work issue or branch, why it is stuck and the remedy."
class = "interactive"            # a person waits on it: first line within 1 s
session = true                   # offered to the agent as a command

[requests.comment]               # a local request port, bound to an I/O verb by the wiring
type = "github.comment"
help = "Comments a finding's remedy on its work issue."
```

The catalog check refuses a component, an output, a config key, a command, a request port or a
verb without its `help`, and a command without its `usage`, `summary`, `group` or `class`.

Types are named JSON shapes. The core's repository owns the shared ones (`github.issues`,
`session.event`); an application's own live in its `types/` folder. The Go side generates structs
from them, the Python side reads them as dicts, and the contract suite round-trips each.

### Subjects

A name's segments become tokens: `fleet/findings` rides as `fleet.findings`. A segment, a command
name or a verb rides percent-encoded beyond letters, digits, dashes and underscores, so a command
with a space (`tally%20note`) and a family key with a dot (`v1%2E2`) are one token each (settled
in step 4, [kern/README.md](../kern/README.md#a-component-in-python)).

| subject | shape | sender, answerer |
|---|---|---|
| `get.<name>` | request: the value, its revision, `not provided` or `stale` | any peer, the core |
| `val.<name>` | publish: each new value, its revision and the name's previous revision | the core, after a commit |
| `run.<i>` | publish: an input of `<i>` moved, with the snapshot's revision | the core, to the instance |
| `in.<i>` | request: the instance's inputs at that revision | the instance, the core |
| `commit.<i>` | request: writes and requests; answer accepted or refused with the reason | the instance, the core |
| `cmd.<i>.<command>` | request: arguments and the revision; answer a result: text, writes, requests. Without a reply, `{"call", "stop"}`: the core gave that call up | the core, the instance |
| `call.<command>` | request with a reply inbox, and a progress subject in it where the caller streams: each line and a beat there, then the result | a client, the core |
| `call.core.abandon` | request: `{"call": <reply subject>}`, a call in the asker's own inbox; answer whether one ran | a client, the core |
| `say.<i>.<call>` | publish: a progress line, or a beat, of the step of one call the instance runs | the instance, the core |
| `io.<i>.<verb>` | request: one request going out | the core alone, the I/O component |
| `hook.<event>` | request: a host's hook event; answer the effects | the hook client, the core |
| `lease.<i>` | publish: a heartbeat from the work loop | any part, the core |

A watch is a subscription: `val.github.>` sees every GitHub name. A subscriber that misses a push
sees a previous revision that does not match its own and sends a `get` (v5's "A push names its
predecessor").

`call.` streams so a command keeps the [feedback budgets](../README.md#feedback-budgets): every
`Phase: <what>` a long command announces reaches its caller as it is said.

### Progress and long calls

A call that runs for minutes, such as `integrate`, streams its progress and waits as long as it
lives, not a fixed time:

- **The caller names a progress subject** in its own inbox: `{"args": [...], "progress":
  "_INBOX.<user in hex>.<...>"}`. The core refuses one outside the inbox the reply names, so a
  caller streams only to itself. There the core publishes `{"line"}` for each line as a step says
  it and `{"beat": true}` every `CallBeat` (5 s) while the call runs, then answers on the reply as
  before, every line included. The caller waits out silence (the Python SDK's `Peer.call`, `idle`),
  never the call's length.
- **A declared step says its lines live.** The Python runner publishes each line on
  `say.<i>.<call>`, `{"line"}`, as the command says it, and while a step runs it beats there, `{}`,
  and on `lease.<i>` every 5 s. The core reads its call's `say.<i>.<call>` and the step's answer
  on one channel, so the lines come before the answer, in order.
- **Calls run side by side.** The core runs each call in its own goroutine, and the Python runner
  each step in its own thread, so a long call never holds another of the same component. Each
  call's words ride its own subject, so each caller hears only its own call's lines.
- **The step wait counts silence.** `StepWait` (60 s, `KERN_STEP_WAIT` for a served core) is the
  longest the core waits for word from a step: its answer, a line or a beat. A step that beats runs
  as long as its process does; a process that hangs or dies fails its step after 60 s of silence.
- **An in-process verb waits on its own.** The GitHub component's `step` verb waits up to its
  `step-wait` (60 minutes) for the session's tool call, while the core beats to the caller, so a
  command that asks it, `integrate` among them, waits out a real check run in one call.

Proven by `kern/host/stream_test.go` (lines and beats before the answer, a foreign subject
refused), `kern/contract/stream_test.go` (the real core and a Python step that outlives a 1 s step
wait by talking, and one that fails it by staying silent),
`kern/python/tests/test_kern_stream.py` (the runner's live lines and beats) and the contract case
of two overlapping calls (`kern/contract/cases.json`), against both fakes and the real core.

### A call given up

A call ends early when its caller gives it up, when one of its steps or requests fails, or when
the core ends. Nothing in the component's process may then wait on it, so the core tells it:

- **The caller gives it up** on `call.core.abandon`, naming the call by its reply subject: the
  Python SDK's `Peer.request` with `give_up` and `Peer.call` do so when they stop waiting, by
  timeout or interrupt. The core refuses a call outside the asker's inbox, and the call answers
  its error at once, naming the cause.
- **A caller killed outright** sends no abandon. Every `CallBeat` (5 s) the core asks its bus
  whether a connection still hears the call's reply subject; where none does, it gives the call
  up as if the caller had sent `call.core.abandon`, so the call ends within the lease lapse.
- **A request already out** is handed the call's context (the `ctx` of `Verb` and `JSONVerb`),
  so its verb lets go of what it holds: the GitHub component's `step` leaves the outbox at once,
  and no session is pointed at a step that no one waits for. A declared process's verb hears the
  stop word below on its `io.<i>.<verb>`; the answer is dropped either way.
- **The stop word.** Where a declared component's step runs or its continuation waits, the core
  publishes `{"call", "stop"}` on the command's `cmd.<i>.<command>`, without a reply. The Python
  runner drops that call's continuation and sets the call's `Abandon` (`kern.abandoned()` in the
  call's code), so what waits on the call ends at once instead of at its own timeout.
  - A request to a declared process's verb carries its own `call`, `{"call", "request"}` on
    `io.<i>.<verb>`; where the core stops waiting for it, given up or past its wait, it publishes
    `{"call", "stop"}` there, without a reply. The runner hears it at once, beside the request it
    serves, and sets that request's `Abandon` (`kern.abandoned()` in the verb's code); a request
    it names that has not run yet is answered as given up without running.
- **In the Go fake core.** `kerntest`'s `Begin` and `BeginServe` run a command or a verb as a
  call its test gives up: `Abandon` as `call.core.abandon` does, `Gone` as the dead-caller check
  does, each with the core's cause (`host.ErrCallerGaveUp`, `host.ErrCallerGone`).
- **Only that call.** Every other call of the component, of the same command or not, runs on.
  SE's streamed commands (`Stepped`) end their thread on it, and a call waiting for the process's
  working directory leaves the line.

Proven by `kern/index/abandon_test.go` (the cause, and the stop word of one call of two),
`kern/host/stream_test.go` (`call.core.abandon`, and the stop word on the bus, a command's and a
declared verb's), `kern/kerntest/abandon_test.go` (the fake's),
`kern/host/caller_test.go` (a caller process killed outright),
`kern/components/github/step_test.go` (a given-up call's step leaves the outbox),
`kern/python/tests/test_kern_stream.py` (the runner and the peer) and SE's
`tests/test_se_components.py` (one of two overlapping streamed calls).

### How a component in another language attaches

A component in any language with a NATS client attaches the same way:

1. The core spawns it as the wiring's placement says (`command = ["uv", "run", "python", "-m",
   "<pkg>"]`), with its bus address, user and token in the environment.
2. It connects, publishes its declaration hash on `commit.<i>`, and the core refuses a hash that
   differs from `component.toml`'s. The hash is the SHA-256 of the file's bytes, line ends read as
   LF, and the attach names the contract version too, `contract: 1`, as the standing file and the
   health do (settled in step 4).
3. It subscribes to `run.<i>` and `cmd.<i>.>`, reads `in.<i>` on each run, answers with
   `commit.<i>`, and beats on `lease.<i>` from its own loop; a step says its lines on
   `say.<i>.<call>`
   ([Progress and long calls](#progress-and-long-calls)), and the stop word on
   `cmd.<i>.<command>` ends what waits on a call ([A call given up](#a-call-given-up)).

Python comes first, with a standard-library SDK in the core's repository (`python/kern/`): the
NATS peer, a runner that reads `component.toml` and dispatches to decorated functions, and the fake
core. It adds no dependency to SE, whose scripts run on the standard library today.

```python
from kern import component

fleet = component("fleet")            # reads component.toml beside this file

@fleet.derived("findings")
def findings(issues, pulls, config):
    return stuck(issues, pulls, config["lease_hours"])

@fleet.command("fleet-check")
def fleet_check(args, inputs, say):
    say("Phase: reading")             # a progress line on the caller's inbox
    return render(inputs["findings"])
```

A Go component is a package that registers the same declaration; it runs inside the core's
process unless a placement moves it out. The Go contract and the Python contract are one contract:
one suite runs against both.

### The fake core

Every component is tested alone, against a fake core, and never against a running bus:

| step | Go (`kerntest`) | Python (`kern.fake`) |
|---|---|---|
| build | a catalog from the component's `component.toml` alone, checked | the same |
| seed | inputs and config by local name | `fake.seed(issues=[...], lease_hours=3)` |
| run | a derivation, or a command with its arguments | `fake.run("fleet-check", "--json")` |
| assert | the writes and the requests, by local name; the progress lines | the same |
| answer | each request gets the answer the case hands it, so a continuation runs | the same |

One contract suite, in the core's repository, runs against the Go fake, the Python fake and the
real core with a fixture component attached over the bus. A fake that drifts fails there. SE's
own suite tests its components against the Python fake only, so it needs no Go and keeps its 60 s
budget; the real-core runs are the core's CI.

## Start on invoke

### How the binary arrives

| path | cost measured | verdict |
|---|---|---|
| a prebuilt release per platform, downloaded and checked against its checksum | an equal-sized release (nats-server, 6.35 MB) in 0.43 to 0.71 s; SE's core is about 12.0 MB gzipped, so about 1 s | **chosen** |
| built by the environment's setup script | 18.7 to 18.9 s cold compile, 23.0 s with module downloads; plus 2.5 s for a toolchain where the image lacks the version | fallback only |
| built at session start | the same 19 to 23 s on every new container | refused: twenty times the budget |

The core's release workflow builds `linux`, `darwin` and `windows` for `amd64` and `arm64`,
attaches them with a `SHA256SUMS` file to the core's tag, and an application's release does the
same for its own binary (core plus its Go components). The binary is fetched into
`~/.se/bin/<app>-<version>` and kept: a version already there costs nothing.

- **Cloud:** the environment's setup script fetches it beside the SE clone, before Claude starts,
  outside any budget. A failed fetch prints one line and the session starts without the core.
- **Local:** `bootstrap.sh` fetches it on the first start of a new version, in the background; that
  session works without the core until it lands, and the greeting says so.
- **Which pins:** the installed SE's `release.toml`, after the refresh at start moved it to its
  latest release (README ["Start and refresh"](../README.md#start-and-refresh)); where the
  session's working tree is SE's own checkout, that checkout's, so a session on `main` tests `main`.
- **A checkout of the core or of an application's Go code:** built from source (warm build 0.12 s,
  one changed file 0.9 to 1.0 s), so its own changes run.
- **The release matches the checkout:** a session runs the release its `release.toml` names, so
  a change to the binary's code without a new version runs the old binary against the new wiring
  (`se-v0.1.0` predated the component `retro-due`, and its core refused main's wiring). SE's suite
  refuses that change, `se.toml` `[tests.beside.release-guard]` ([kern/README.md
  "Release"](../kern/README.md#release)): a release is built from one commit and is never changed, so
  the files it is built from are the release's own contents, and the guard needs no download. The
  raised version is cut by the landing; a session that starts before its release is published
  builds it from source.

### Lifetime: bound to the session

One core runs per checkout and serves every session in it; a cloud container has one checkout,
so each cloud session has its own core.

- Each session holds a lease the hooks renew (SessionStart takes it, each hook event renews it,
  SessionEnd returns it). A sub-agent renews its session's lease and starts nothing.
- The core ends when no session holds a lease, after a grace of 60 s, or after `idle` (built in
  30 minutes) without any event, whichever comes first.
  - The grace starts at the core's start, until a session takes its first lease, and again each
    time the last lease is returned.
  - The events that count for `idle` are the hook events and `call.core.stop`. Gets, leases and
    commits do not: a placed component's beats and commits would keep an unused core up for ever.
- `call.core.stop` answers the core's pid, then the bus stays up until the asker hangs up (1 s at
  most), so the asker has the answer before the bus closes.
- A call lives no longer than its caller: one whose caller's connection is gone, a process killed
  outright, is given up within the lease lapse ([A call given up](#a-call-given-up)).
- It ends with the container in the cloud whatever the lease says; nothing in it needs to
  survive, because GitHub and the disk own every durable fact.

### The start budget: feedback within 1 s

| step | measured | budget left of 1 s |
|---|---|---|
| SessionStart hook spawns the core detached and returns | Go hook client 5 to 6 ms | 994 ms |
| the core's process start to a bus that accepts connections | 27.0 to 28.2 ms embedded (v5's `ReadyForConnections` polls every 25 ms); 7.6 to 8.9 ms for a standalone server | 966 ms |
| first request answered over the bus | 28.4 to 32.8 ms after process start | 967 ms |
| a Python component attached and answering | 2.3 to 2.8 ms over the bus, 36 to 40 ms with the interpreter's start, 46 to 61 ms through `uv run` | about 900 ms |

The greeting stays `se_start.py status`'s, within its 1 s budget; it reads `get.core.health` with a
200 ms wait and says `core: starting` where none answers yet. Nothing waits for Python components:
their names read as `not provided` until they attach.

## Nobody starts the index by hand

The SE plugin's hooks start the core and post every event to it. Each hook is one command,
`<app> hook <event>`, the application's own binary as a client: it reads the host's JSON on
stdin, sends it on `hook.<event>` with a 500 ms wait, and prints the answer as the host's hook
JSON. Where no core answers, it prints nothing and exits 0: a hook fails open, measured at 5 ms.

A core that ends at its start is not silent. Its `serve` writes the cause to the core's log and to
`.se/.runtime/core.died` before it gives up the start's claim; `<app> status` names it (`died` in
`--json`), and the greeting says `failed: the core ended at its start` with its first lines. The
first `UserPromptSubmit` or `PostToolUse` hook after it tells the session the same once, as
context; SessionStart does not, since the start posts it and shows nothing of its output. A core
that stands removes the file. A core that stood and ended without its end, killed or crashed,
leaves a standing file naming a pid that runs nowhere: the first such hook tells the session the
last lines of the core's log, once, and removes that file.

A pid alone does not prove a core. A machine restarted with the checkout's files kept, as a cloud
environment restored from its snapshot is, gives its processes the last boot's pids, the start's
own among them. So a standing file whose pid runs and whose bus accepts no connection within 1 s
names no core either, and a hook tells it as a core that ended without its end. The start spawns
a core, and the core that serves writes the file anew.

| hook | posts | what it gains |
|---|---|---|
| SessionStart | the session id, the checkout, the agent | spawns the core detached where the standing file names none (v5's claim file keeps two hooks from starting two), takes the session's lease; the greeting gains live names: what is due, stuck or waiting |
| SubagentStart | the agent id and type under the session | the sub-agent shares the session's core; the core knows its role, so a worker is handed its ticket queue and its work issue's freshness |
| UserPromptSubmit | the prompt's id | context the core holds back for it: a work issue changed since it was read, an escalation pending |
| PreToolUse | the tool and its input | guards the rules mechanically, as the cage did: a hand-typed `git push` (`work_tickets.py push` is the door), `--no-verify` ([pub-006](../src/skills/work-model/references/rules.md#pub-006-never-bypass-the-hooks)), a write outside the worker's box; each guard is a component, switched on per role |
| PostToolUse | the tool, its input and its response | the GitHub component reads the session's GitHub tool answers ([GitHub in the cloud](#github-in-the-cloud)); a ticket move or a commit updates the delivery names |
| Stop, SubagentStop | the stop | the delivery component's `stop-check` answers within the hook, in its warm process: 24 to 57 ms after the first, against 434 to 586 ms through `uv` (README "Stop hook") |
| SessionEnd | the end | returns the lease; the last one out stops the core after its grace |

Every event lands in the family `session/<id>/events`, which the session I/O component also
appends to `.se/.runtime/sessions/<id>.jsonl`, so the core reads a session's history back after a
restart.

From v5 carries over: the detached start, the claim file, the standing file, the post and its
effects (`pass`, `context`, `block`, `result`), and the rule that a hook fails open. v5's hooks
module is JavaScript for its host; Claude Code's hooks are commands, so the client is the core's
own Go binary.

### What the hooks carry, probed in a cloud session

Probed on 13 Nov by a worker in a Claude Code cloud session, its hooks writing each payload to a
file (step 6):

- **PostToolUse carries a GitHub tool's answer.** After `mcp__github__issue_read` (method
  `get_labels`), the payload held `tool_name`, `tool_input` (`method`, `owner`, `repo`,
  `issue_number`), `tool_use_id`, `duration_ms`, `mcp_server` (`name` `github`, `source` `dynamic`)
  and `tool_response`: the tool's whole answer as MCP content, `[{"type": "text", "text": <the JSON
  the session read>}]`, which parsed to the same labels. The relay backend can match it.
- **SubagentStart carries the parent's session id.** Its `session_id` is the parent session's,
  equal to the one on the parent's own PostToolUse; beside it come `agent_id` and `agent_type`
  (`general-purpose`), and no field of its own for the parent. A sub-agent renews its session's lease
  by that id.
- Both also carried `transcript_path`, `cwd`, `prompt_id` and `hook_event_name`.

## GitHub in the cloud

No token reaches code in a cloud session; the session's GitHub tools reach GitHub, and `git`
reaches it through the session's proxy. The GitHub component is one I/O component with two
backends, chosen at start:

- **token**, where `gh auth token` or `GH_TOKEN` gives one: the Go line's REST client, in process,
  with ETags, a refresh every 2 minutes and the rate-limit pacing of SE#750.
- **relay**, where none does: a request going out becomes an entry of `github/outbox`, with the
  same tool names and arguments as today's hand-off plan. The agent runs it with its GitHub tools.
  The PostToolUse hook hands the tool's response to the core, which matches it to the entry,
  answers the request and runs the command's continuation.

Every GitHub tool answer the session receives, a plan's or not, lands in the snapshot
(`github/issues/<key>`, `github/pulls/<key>`, `github/checks/<key>`, `github/comments/<key>`) or
the list (`github/issue-lists/<key>`, `github/pull-lists/<key>`, every page), with the time it was
read, so the next command reads it from the core instead of asking for a file.

A snapshot's key is `<owner>.<repo>.<number>` and a list's `<owner>.<repo>.<state>`, then each
label, all in lower case: SE's issue 1036 stands at `github/issues/mb-89.se.1036`; neither
`github/issues/1036` nor `github/issues/mb-89.SE.1036` names it
([kern/components/github/README.md](../kern/components/github/README.md) owns the names). The core hands the agent the next
outbox step as context on the hook that follows each tool call, and `<app> github next` prints it.

### Measured against today's `integrate` hand-off

| what the session does | today, without gh | with the relay |
|---|---|---|
| GitHub tool calls | about 13 and the check polls: read the pull request and the issue, the pause search, open or update, the check runs every 30 s, the merge, read the landing pull request, then five close-out calls | the same: the tools are the only door, so no call goes away |
| command runs | two: `integrate ... --pr-description --issue-body --branch`, then `integrate --read-back ...` | one: the read-back is the continuation of the merge's answer |
| tool answers retyped into files | three: the pull request's description, the issue, the landing description | none |
| what each retyping costs | this issue's JSON is 9,000 bytes; this worker wrote it twice, before and after a body change | nothing |
| a step done wrong | a file saved from a summary, a stale body | the core holds the tool's own answer |

The gain is the retyped answers and the second run, not fewer GitHub calls. The same relay serves
every command that hands off today: `intake`, `field-report --check`, `deliver`, `fleet-check`,
`refs`, `route` and `file`.

## Scripts are ad hoc, components are long-term

A script is what an agent writes while working. Once something is judged useful to the whole
system, it becomes a component and attaches through the core, in Go or in another language.

- **Ad hoc, kept out of the repository:** a script goes in the session's scratch directory, as
  today. An ad hoc component goes under `.se/components/<name>/` (ignored), with its
  `component.toml`; `se component add <name>` scaffolds one (a Python component over NATS) and
  places it in the ad hoc wiring overlay `.se/wiring.toml`, which the core reads after
  `wiring.toml` (kern/index/wiring.go `Merge`). Restarting the core picks it up in about 30 ms, for
  this checkout alone; an agent may write one at any time.
- **Promoted:** a component the system keeps goes to `components/<name>/` in the application, or
  into the core's repository when every application needs it. It is tested against the fake core
  like any other.
- **Python may stay Python.** It is ported to Go only where porting pays, below.

| port a Python component to Go when | keep it Python when |
|---|---|
| it is on a hook's or the greeting's path: an interpreter costs 30 to 60 ms a run, a Go call 5 ms | it wraps Python itself: pytest, the overhaul's AST facts |
| a person waits on it and it runs often | it renders a page or a deck |
| it moves into the core's repository: a shared component needs no Python on the application's machines | only this application uses it, and it meets its budgets |

**The rule it changes.** The rule book's
[gen-001](../src/skills/work-model/references/rules.md#gen-001-mechanize-first) and SE's AGENTS.md
now own it: an ad hoc solution stays in the scratch directory or `.se/components/`, never tracked;
what is tracked under `components/` is a component, with its declaration and its tests. gen-001's
"Go line (frozen)" note keeps citing that line's `src/scripts/`.

**Promotion is mechanical.** The core counts each call of an ad hoc component — one whose
`component.toml` is under `.se/components/` — into the use log `.se/usage/adhoc.jsonl`, by the
component's path, attributing the session the hook stream named last (so the count is from
PostToolUse). One record is one line of JSON: `at` (RFC3339), `session`, `component` and `path`;
`scripts/se_usage.py` owns that shape for the Python side, as Go and Python agree on the
declaration hash. `retro.py collect` reads the log: a component used in three or more sessions
since the last retro is a promotion candidate in the retro's facts, which SE files as work. The
overhaul reads the components' call times against their budgets and names the port candidates.

**Scripts are counted too.** On a shell tool's PostToolUse the core reads the command and counts
each run of a script git neither tracks nor ignores, or one in a scratch place, into the same log:
`at`, `session`, `script` (its path) and `hash` (its content's sha256), never its arguments or
output. Only a script named by its path, run directly or by an interpreter, counts; `git`,
`uv run pytest` and SE's own tracked scripts never do (kern/host/scripts.go owns the parsing).

`retro.py collect` lists the scripts run three or more times in the window beside the components,
the most-run first, with their runs and sessions: the scripts that deserve to become components.

## The core's repository

The core gets a repository of its own; creating it is the owner's step, since no session here can.

- **Name:** `mb-89/kern`, Go module `github.com/mb-89/kern`. The binary an application builds is
  named after the application (`se` for SE); the bare one is `kern`.
- **What belongs in it:** what every application needs, and nothing that names an application:
  the core, the bus, the fakes, the contract suite, the Python SDK, the template, the reusable CI,
  and the generic components.
- **What stays in an application:** every component that knows its domain. SE's work issues, field
  reports, fleet check, retro and review stay in SE.

```text
kern/
  go.mod                  github.com/mb-89/kern
  index/                  names, store, snapshots, catalog, waves (from ff01204)
  bus/                    embedded NATS, users and permissions, standing file
  host/                   start, detach, leases, placements, idle end, hook client
  kerntest/               the Go fake core
  python/kern/            the Python SDK and fake core
  contract/               the one contract suite, run against both fakes and the real core
  components/             clock, disk, proc, git, session, github: generic, each switchable
  types/                  the shared JSON types
  template/               the bare application
  .github/workflows/      check.yml, release.yml, battery.yml (reusable)
```

### Incubated in SE until `mb-89/kern` exists

Until the owner creates `mb-89/kern` (step 1 of [the plan](#the-plan)), kern grows in SE under
`kern/`, as its own Go module `github.com/mb-89/kern`, so the move changes no import path. Nothing
in SE outside `kern/` imports it. Meanwhile SE runs kern's tests beside its Python suite (`se.toml`
`[tests.beside.kern]`, README [Test budget](../README.md#test-budget)), and SE's `check` job vets
it. The move is one work issue, once the repository exists:

1. kern's history goes over with `git subtree split --prefix kern`, pushed as the new
   repository's `main`; `kern/` becomes its root, and nothing in it changes.
2. kern's CI moves with it: its vet, its tests and their Windows run become the new repository's
   `check.yml`, with a ruleset like SE's.
3. SE then removes `kern/`, `[tests.beside.kern]` and the vet step in one pull request, and pins
   the new repository's first tag as `[modules.kern]`, step 6's pin below.

**Pinning it.** An application pins the core in `se.toml [modules.kern]`, as SE pins obs. Its
`go.mod` also requires it; `se_modules.py` reads the version from `go.mod` where the module says
`go = true`, so the pin has one owner.

While kern is incubated, SE pins it by `kern/release.toml`'s `version`, which
`se_modules.kern_pin` reads; `[modules.kern]` replaces it with the move. Every session hook runs
`scripts/se_hook.sh <event>`, which execs that kern: bash builtins up to one exec, not Python,
whose interpreter start alone costs about twice kern's whole hook, and through `uv` six to ten
times (README [Kern](../README.md#kern) owns the measurements).

**When kern is released.** A push to `main` that changes `release.toml`'s `version` cuts the
release ([kern/README.md "Release"](../kern/README.md#release)); nothing else does. A change under
`kern/`, its template's included, reaches sessions and new applications (`se new app` takes the
template at the pin) only with the next release, so the pull request that needs it out bumps
`version`.

### Switching components on and off

The application's `wiring.toml` names its instances; a shared component runs only where an
instance names it, and `enabled = false` switches one off without deleting its wires:

```toml
[instances.github]
component = "kern/github"
config = { refresh = "2m" }

[instances.clock]
component = "kern/clock"
enabled = false

[wires]
"fleet.issues" = "github/issues"
```

The core refuses to start on a wiring whose input is bound to an output of a switched-off or
missing component, naming the wire's line and the switch's line. An input that may go without
says so on its wire: `builtin = true` goes in the wire's table, not on the instance, and the
input then reads its writer's built-in value, marked `not provided`:

```toml
[wires]
"report.ticks" = { to = "clock/ticks", builtin = true }
```

A switched-off instance keeps its names and their place in the catalog; what it answers:

| asked | answer |
|---|---|
| a read of one of its names | the name's built-in value, marked `not provided` |
| its derivations | none runs, on any wave |
| a commit to its names | refused, naming the instance and the switch's line |
| its commands | none is offered: the collector leaves them out, so no surface lists them, and `call.<command>` answers that no such command exists |
| its verbs | none is reached: the start refuses a request port bound to a verb of a switched-off instance, naming both lines; a request has no `builtin` way out, since a built-in value cannot answer it |

### A bare application, and `se new app`

A bare application contains the core pinned, an empty `wiring.toml`, `cmd/<name>/main.go` (the
core plus the application's Go components, none yet), `components/`, `types/`, `se.toml` with its
`[project]`, `[tests]` budget and `[modules.kern]`, an `AGENTS.md`, a `tests/` folder whose
battery starts the bare core, and a `check.yml` that calls the core's reusable `battery.yml`.

`se new app <name> --path <dir>` copies the core's `template/` at its pin, fills in the name,
initializes git with the project identity and makes the first commit. Creating the GitHub
repository, its ruleset and its first push stay the owner's steps, which SE names as one line.
While kern is incubated, no module `github.com/mb-89/kern` can be fetched, so the application
carries kern's source at the pin in `kern/` and its `go.mod` replaces the module by it; the move
drops both (README [New application](../README.md#new-application)). A
new application then gets components by adding instances, CI from the reusable workflow, and its
test budget from `se.toml [tests]`, in the same shape as SE's.

SE becomes one application on the core: its binary is `se`, its components live in SE's
`components/`, and its Python scripts attach as components ([Migration](#migration)).

## Migration

SE works after every step: until a command's component exists, its script runs as today, and where
no core answers, every hook and command falls back to today's path. Each step is one issue in the
[plan](#the-plan).

| today | first | then | stays a skill |
|---|---|---|---|
| `work_tickets.py` | attaches as Python components, one per group (tickets, issues, delivery, integration), at step 8; the CLI keeps its words | its GitHub reads and writes go through the GitHub component (step 9); `queue`, `status` and `ready` port to Go when the greeting needs them | writing the field report, judging a delivery, the dispatcher's choices |
| `review.py` | Python component (`brief`, `file`) at step 8 | stays Python | the reviewer's find, verify and judge |
| `retro.py` | Python component at step 8; done, `components/retro/` | `retro due` ports to Go (step 10): the greeting reads it; done, SE's `retro-due` component ([components/README.md](../components/README.md)) | the retro's judgment |
| `overhaul.py` | Python component at step 8; done, `components/overhaul/` | stays Python: its facts are Python's AST | whether the design is still right |
| `fleet-check` | Python component at step 8 | ports to Go (step 10): a derivation over the GitHub names, pushed to the greeting and the integrator; done, SE's `fleet` component, which the greeting and `fleet-check` read live ([components/README.md](../components/README.md)) | which remedy to apply |
| `stop-check` | the Stop hook calls it as today | ports to Go (step 11): answered from the delivery names within the hook | none |
| `timeline.py` | Python component at step 8; done, `components/render/` with `deck.py` | reads the GitHub names instead of its own calls (step 9); stays Python: it renders a page | none |
| `deck.py` | Python component at step 8; done, `components/render/` | stays Python: it renders the deck | the decision skill |

The public check, its hooks and `se_plugin.py` stay scripts: git hooks and CI run them where no core
runs.

## What the Markdown gains

Once the core runs, the skills, agents and specs read from it instead of restating or recomputing:

- **The catalog:** every command's usage, summary and help from its one declaration, through
  `<app> help <command>`. The README's command reference is rendered from the catalog, Python and
  Go components alike, so no skill copies a usage line.
- **The greeting and SE's first turn:** what is due (a retro, an overhaul), stuck (the fleet
  findings), waiting on the person (escalations), live instead of from an hour-old cache.
- **The work model:** a worker's ticket queue, its work issue's freshness (a comment or body edit
  since it was read, pushed on UserPromptSubmit), and whether its delivery passes the Stop hook,
  as names it reads, not commands it reruns.
- **The integrator:** the queue from the GitHub names within 1 s, instead of about three GitHub
  round trips per run; a landing's state as the continuation holds it.
- **The rule book:** each rule's live state (`rules/<id>/hits`: the public check's last verdict, the
  dangling references) next to its prose, so a skill links the rule and the core says whether it
  holds now.
- **Specs and notes:** their links and anchors resolved by a references component as files change,
  so a dangling link shows during the edit, not first in `scripts/hygiene.py`'s references check.
- **In the cloud:** every GitHub answer the session read, readable by the next command, so no
  skill tells the agent to save a tool's answer to a file.

## The Go line

The Go line is `main`'s history at `ff01204`: about 28,000 lines of Go plus 17,000 of tests, a
Claude plugin, a per-workspace daemon and a fleet of unattended cloud boxes. Read it with
`git show ff01204:<path>` and `git ls-tree -r ff01204`, which need no tag: origin has no
`archive/go-line`. In a shallow clone, first `git fetch origin ff01204`; never check it out over a
branch.

What the 12 Nov port rebuilt in Python (review, retro, overhaul, fleet check, the Stop hook, the
hygiene checks) stays and is the [Migration](#migration)'s input. Of the Go line's own rules, the
core's contract suite holds components to `io-module`, `module-imports`, `library-users` and
`fake-contract` ([The fake core](#the-fake-core)).

Not coming back, and no issue brings them back without the owner:

- branch claims, leases on claims, takeover markers, manifests, coordinator trees, `issue keep`,
  `fleet refresh`, `fleet rules`, `fleet fix`, the routine and its fan-out: one integrator assigns
  and lands each work issue;
- landing answers (`landing.yaml`) and the battery record `tests/passed`: the field report and the
  push gate's verdicts replace them;
- the queue estimate of `issue tree`, and the session panel's pane;
- the Go line's other `se rules` and its `golangci-lint`, `biome` and `deadcode` steps;
- `RUNME.sh` and `build.sh`: the binary arrives as a release ([How the binary arrives](#how-the-binary-arrives)).

## Measurements

Measured on 13 Nov in a Claude Code cloud container: 4 cores, 15 GB, Linux amd64, Go 1.24.7
preinstalled, every host reachable through the session's proxy (proxy.golang.org, github.com
releases, go.dev). The probe is a 40-line Go program that starts an embedded NATS server on
loopback with a token, dials it and answers one request; nothing of it is in SE.

| what | command | wall time |
|---|---|---|
| module download for NATS | `go get github.com/nats-io/nats-server/v2@v2.11.9 github.com/nats-io/nats.go@v1.45.0` | 7.1 s |
| cold build, no module or build cache | `go clean -modcache; rm -rf $GOCACHE; go build -o probe .` | 23.0 s (user 52.7 s) |
| cold compile, modules present | `rm -rf $GOCACHE; go build -o probe .` (twice) | 18.7 s, 18.9 s |
| warm build, nothing changed | `go build -o probe .` (3 runs) | 0.118 to 0.125 s |
| warm build, one file changed | `echo '// edit' >> main.go; go build -o probe .` (3 runs) | 0.90 to 1.03 s |
| the Go line's `se`, for comparison | `go build ./cmd/se` at `ff01204`: cold, cold compile, warm | 13.0 s, 12.7 s, 0.12 s |
| binary size | the probe; gzipped | 22.6 MB; 12.0 MB |
| release download | `curl -L -o n.tgz https://github.com/nats-io/nats-server/releases/download/v2.11.9/nats-server-v2.11.9-linux-amd64.tar.gz` (6.35 MB, 3 runs) | 0.71 s, 0.64 s, 0.43 s |
| unpack | `tar xzf n.tgz` | 0.12 s |
| a Go toolchain download | `curl -L https://go.dev/dl/go1.25.4.linux-amd64.tar.gz` (59.8 MB) | 2.49 s |
| embedded NATS start | `./probe`: server ready, client dialled, first request answered (5 runs) | ready 27.0 to 28.2 ms, answered 28.4 to 32.8 ms, process 33 to 38 ms |
| standalone NATS start | `nats-server -a 127.0.0.1 -p 14222 --auth <token>` until its `INFO` line (3 runs) | 7.6 to 8.9 ms |
| a Python peer on the bus | standard-library socket: `CONNECT`, `SUB`, `PUB`, the `MSG` back (3 runs) | 2.3 to 2.8 ms; 36 to 40 ms with `python3 -I` |
| Python start | `python3 -I -c "import socket,json"`; `uv run -q python -c pass` | 30 to 31 ms; 46 to 61 ms |
| a Go hook client | dial, `hook.Stop` request, answer from a Python responder (5 runs); with no server | 5 to 6 ms; 5 ms, failing open |
| today's Stop hook | `uv run --no-project python scripts/work_tickets.py stop-check` (3 runs) | 0.35 to 0.39 s |
| kern's catalog check | `cd kern && go test -run XXX -bench . -benchtime 200x -count 5 ./index/`: 20 and 200 instances | 0.16 to 0.20 ms; 1.54 to 1.74 ms |

The NATS server adds about 6 s to a cold compile against the Go line's `se`, and 10 MB to the
binary. quackitect v5 asks for Go 1.25, which this image lacks; the core's `go.mod` names the
version the images carry, or the fallback build fetches the toolchain (2.5 s).

## Risks and open points

- **PostToolUse and MCP answers.** The relay assumes the PostToolUse hook carries a GitHub tool's
  response in the cloud. Step 6 probes it first; where it does not, the relay keeps today's files
  as its fallback and the gain of [GitHub in the cloud](#github-in-the-cloud) is lost.
- **A release pipeline.** Each application that has Go components builds six binaries per release;
  the core's reusable release workflow carries it, and an application without Go components runs
  the core's own binary.
- **Windows.** The detached start and the hook client run on Windows in v5; the core's CI runs its
  contract suite on Windows from step 2.
- **Two languages in one application.** SE's suite stays Python against the Python fake; the Go
  side is tested in the core's repository. An application with Go components runs both in its
  `battery.yml`, under one budget.

## The plan

The steps, in order; the field report of SE#971 proposes each as a worker-sized issue with its
goal and blockers, and the dispatcher files them.

| step | what | repository |
|---|---|---|
| 1 | the core's repository exists, with a ruleset like SE's | the owner |
| 2 | the index from `ff01204`, in process, with its fake and fixture components | kern |
| 3 | the bus, users and permissions, the standing file, detached start, leases, idle end | kern |
| 4 | the Python SDK, the Python fake core, the contract suite against both fakes and the real core | kern |
| 5 | the release workflow, `battery.yml` and the bare template | kern |
| 6 | SE pins the core, fetches its release, SessionStart starts it and the greeting names it; the hook client posts every event, probing PostToolUse | SE |
| 7 | the GitHub component: token and relay backends, the snapshot names | kern |
| 8 | SE's script commands attach as Python components; the README's command reference renders from the catalog | SE |
| 9 | `integrate` and every hand-off run through the relay: no retyped files | SE |
| 10 | fleet check and retro due as Go components, read live by the greeting | SE |
| 11 | `stop-check` answered from the core within the hook | SE |
| 12 | ad hoc components, `usage/adhoc`, and the promotion facts in the retro | SE |
| 13 | `se new app` | SE |
