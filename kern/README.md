# kern

kern is the Go core every application builds on: the index (names, the store, snapshots, the
catalog), its NATS bus and its host. Its design is SE's
[docs/go-core.md](../docs/go-core.md) until kern owns its contract.

**Incubated in SE.** kern's own repository, `mb-89/kern`, does not exist yet; the owner creates
it. Until then kern grows in SE under `kern/`, as its own Go module `github.com/mb-89/kern`, so the
move changes no import path. Nothing in SE outside `kern/` imports it.

## Layout

The design's layout ("The core's repository"), relative to `kern/`; the parts later steps add are
named in the design's plan.

| path | what | from |
|---|---|---|
| `go.mod` | the module and its pinned Go version, which CI reads | |
| `index/` | names, families, the store, snapshots, a single writer per name, built-in values, the catalog check at start, waves, actions, the collector, and `wiring.toml` read at start | `src/index` at `ff01204` |
| `index/fixture/` | the fixture components the index and the fake core are tested with | `src/index/fixture` |
| `kerntest/` | the Go fake core: seed by local name, run, assert writes and requests, answer each request | `src/index/indextest` |
| `bus/` | the embedded NATS server on loopback, a user and permissions per component instance, so the bus refuses a second writer | quackitect v5 `src/index/bus.go` |
| `host/` | the core's process: the standing file, the detached start and its claim file, leases, placements, the idle end | v5 `src/index/detach*.go`, `start.go`, `door.go` |
| `cli/` | the core's command line, the same for the bare core and every application: `<name> start`, `status`, `stop`, `serve`, `hook` | |
| `cmd/kern/` | the bare binary: `kern start`, `kern status`, `kern stop`, `kern serve`, `kern hook`, carrying kern's shared components | |
| `components/github/` | the GitHub component: the token and relay backends and the snapshot names ([its README](components/github/README.md)) | the design's step 7 |
| `contract/` | the contract suite: the built binary held to the bus's and the host's promises, and `cases.json` held against the Go fake, the Python fake and the real core with a Python component attached | |
| `contract/fixture/` | tally, the suite's fixture and the sample Python component (`component.toml`, `__init__.py`), and the declarations of the two peers the real leg plays | |
| `python/kern/` | the Python SDK, standard library only: the NATS peer, `component.toml`'s reader, the component and its decorators, the fake core, the runner `python -m kern run <folder>` | |
| `python/tests/` | the Python fake's leg of the contract suite and the sample component's test, run by SE's Python suite | |
| `release.toml` | kern's version and the one URL its release is published under ([Release](#release)) | |
| `tools/release/` | builds the release: six archives and `SHA256SUMS` | |
| `template/` | the bare application every new application starts from ([The template](#the-template)) | |

The NATS server is a Go dependency, `github.com/nats-io/nats-server/v2` v2.11.9 with
`github.com/nats-io/nats.go` v1.45.0, v5's versions; `go.mod` owns them.

## The host

One core runs per checkout, the nearest folder up from the working directory that holds `.git`
(or `--root`). Nobody needs to start it by hand: a hook runs `kern start`, which returns at once.

| command | what |
|---|---|
| `kern start [--grace D] [--idle D]` | where no core runs and no other caller's claim stands, claims the start (`.se/.runtime/start.claim`) and spawns `kern serve` detached; says `started`, `starting` or `running` |
| `kern status [--wait D] [--json]` | `running` with the health (`get.core.health`, 200 ms wait), `starting`, or `not running` (exit 1) |
| `kern stop` | asks `call.core.stop` and waits until the process has exited |
| `kern serve [--grace D] [--idle D]` | the core in the foreground: reads `wiring.toml` where the checkout has one |
| `kern hook <event> [--wait D] [--unanswered N]` | posts the host's hook JSON from stdin on `hook.<event>`, waiting up to 500 ms for a core whose start's claim stands; prints the answer as the host's hook JSON: the bound command's output, else the context the components told on `PostToolUse`, `UserPromptSubmit` and `SessionStart` (the [GitHub component](components/github/README.md)'s waiting tool calls) as `additionalContext`, nothing for a `pass` with nothing told; where no core answers, prints nothing; exits 0, or N where no command answered the event and nothing was told |

- **The standing file**, `.se/.runtime/standing.json`, readable by its owner alone: the bus's
  address, the pid, the contract version and every bus user with its password. A pid that runs
  nowhere reads as absent; the core removes the claim once it has written the file.
- **Leases.** Each `hook.<event>` with a `session_id` takes or renews that session's lease and
  `hook.SessionEnd` returns it. A component beats on `lease.<i>` every 5 s; a placed instance's
  names read `stale` once three beats are missed.
- **Placements.** A wiring instance with `command = [...]` runs in a process of its own, started
  with `CORE_BUS`, `CORE_USER` and `CORE_TOKEN`; it commits on `commit.<i>` and the core checks
  each write against the component's declaration. A Go component placed out of process may
  declare no derivation or command; a declared component's process answers both.
- **Declared components.** A component no binary carries is declared by its `component.toml`
  alone, in `components/<name>/` or `.se/components/<name>/` of the checkout, one instance each.
  Its process attaches first, and the core runs its derivations, commands and verbs over the bus,
  as [A component in Python](#a-component-in-python) says.
- **The host's events.** An I/O component that declares `index.Hears` hears each `hook.<event>`
  with its payload before the core answers it; what it refuses goes to the core's log, and the
  hook passes. One that declares `index.Inlet` is handed its instance's commit at start, so it
  writes what comes in on its own. The [GitHub component](components/github/README.md) does both.
- **Hooks a command answers.** The wiring's `[hooks]` binds a host's event to a command, such as
  `Stop = "work_tickets.py stop-check"`; the core refuses to start where no instance declares it.
  The core runs it with one argument, `--hook=` and the event's JSON, and answers the effect
  `output` with the command's text, which `kern hook` prints as the hook's output. Where the
  command's process has not attached yet, or the command fails, the core answers `pass` with the
  reason at once, so the caller can answer the event another way (`--unanswered`).
- **The idle end.** The core ends 60 s after the last session's lease is returned (or after its
  start, where none took one), or after 30 minutes without a hook event or a call.

## A component in Python

`python/kern/` is the SDK, standard library only (SE's
[docs/go-core.md](../docs/go-core.md), "How a component in another language attaches"). A
component is a folder: its `component.toml`, and an `__init__.py` that makes it with
`kern.component("<name>")` and decorates its functions; `contract/fixture/tally/` is the sample.
The wiring places it with `command = ["python", "-m", "kern", "run", "components/<name>"]`, the
SDK on `PYTHONPATH`.

| subject | the process | the core |
|---|---|---|
| `commit.<i>` | first `{"attach": {"contract": 1, "hash": "sha256:<hex>"}}`, then `{"writes": [...]}` | refuses another contract, another declaration, and a write before the attach |
| `run.<i>` | hears that an input moved: reads `in.<i>`, commits each derivation's value | sends it after each commit that moves an input, and on the attach |
| `in.<i>` | asks its inputs | answers them by local port, `config/<key>` among them, at the newest revision |
| `cmd.<i>.<command>` | answers one step: `text`, `writes`, `requests`, `then`, or `error`; its lines go out on `say.<i>.<call>`. A message without a reply, `{"call", "stop"}`, is the stop word: it drops that call's continuation and sets its `kern.abandoned()` | sends the first step with the arguments and inputs, each later one with the answers; the stop word once it gives up a call whose step runs or whose continuation waits ([docs/go-core.md "A call given up"](../docs/go-core.md#a-call-given-up)) |
| `io.<i>.<verb>` | an I/O component answers `{"answer": ...}` or `{"error": ...}` | sends a request bound to the verb |
| `say.<i>.<call>` | says a step's line as it goes, `{"line"}`, and beats `{}` every 5 s while the step runs, on its own call's subject | hands each line on to the call's caller; each word restarts the step's wait, `StepWait` (60 s, `KERN_STEP_WAIT` for a served core), so a step that beats runs as long as its process |
| `call.<command>` | | a client's call: `{"args": [...], "progress"?}`, answered with the lines, the text or the error; with a progress subject in the caller's inbox, each line goes there as it is said and a beat every 5 s ([docs/go-core.md "Progress and long calls"](../docs/go-core.md#progress-and-long-calls)); `call.core.abandon`, `{"call": <its reply subject>}`, gives up a call in the asker's own inbox; a call whose reply subject no connection hears any more, its caller killed, is given up the same way |

- **The declaration hash** is the SHA-256 of `component.toml`'s bytes, line ends read as LF,
  written `sha256:<hex>`: the bytes, not what they parse to, so Go and Python answer one hash.
- **Subject tokens.** A name's segments are one token each, and every byte of a segment, a command
  name or a verb but letters, digits, dashes and underscores rides percent-encoded:
  `tally note` rides as `tally%20note`, the family key `v1.2` as `v1%2E2`. `get.<name>` also reads
  the name from its body. `contract/subjects.json` holds Go and Python to it.
- **Types** are `int`, `float`, `string`, `bool`, `[T]` or a named JSON shape such as
  `github.issues`, which Go reads as `any`; a wire joins equal types and equal shapes.
- **A family read whole.** A Go input of type `map[string]T` bound to a family of `T` reads every
  key standing, `{}` where none does, and its derivation runs once for a change at any key; an input
  of type `T` reads the family at the key that changed, once per key. A command may read a family
  only whole.

## Tests

```sh
cd kern && go vet ./... && go test ./...
```

SE declares kern's tests beside its Python suite, `se.toml` `[tests.beside.kern]`, with their own
time and budget (SE's [README "Test budget"](../README.md#test-budget)): `integrate`,
`work_tickets.py suite` and the `check` job, the check `main`'s ruleset requires, run them after the
suite, so a red kern test refuses the integration and the Python suite's budget is untouched.
`check` vets kern in its own step, and fails where `gofmt -l` lists a file of kern's. The job
`kern-platforms` runs kern's vet and tests on Windows and macOS, where the detached start and the
stop differ, and there also the tests of SE's start and hook scripts (`tests/test_bootstrap.py`,
`tests/test_se_hook.py`), whose paths differ too: a zip on Windows, `shasum` and no `setsid` on
macOS. `check` needs it and fails unless every platform passed.

The contract suite runs `contract/cases.json` three times: against the Go fake
(`contract/fake_test.go`), against the real core with tally's Python process placed and attached
(`contract/real_test.go`, Python 3.11 or later, from `KERN_PYTHON` or the path), and against the
Python fake (`python/tests/`, in SE's Python suite through `pyproject.toml`'s `testpaths`, so its
time counts against SE's budget and needs no Go).

## Release

`release.toml` owns kern's version and where its release is published:

```toml
version = "0.3.0"
download = "https://github.com/mb-89/SE/releases/download/kern-v{version}"
```

- **The assets:** `<binary>-<version>-<os>-<arch>.tar.gz` for `linux` and `darwin`, `.zip` for
  `windows`, each on `amd64` and `arm64`, each holding the one binary (`<binary>.exe` on windows),
  and `SHA256SUMS` over the six, which `sha256sum -c SHA256SUMS` checks. `go run ./tools/release
  build --dir <folder> --out <dir>` builds them, the same bytes for the same commit. The binary is
  `kern` from `./cmd/kern` by default; an application names its own with `binary` and `package` in
  its `release.toml`, and the tool builds its folder (`--dir`).
- **The workflow is reusable:** `.github/workflows/kern-release.yml` builds the six for the folder
  it is called with (the bare core by default), on every pull request and push to `main` that
  touches kern, and runs [the template](#the-template)'s battery for the bare core. On `main` it
  publishes the release that folder's `release.toml` names, where it does not exist yet, so the push
  that changes `version` cuts it; a release that exists is never changed. A rerun is
  `workflow_dispatch`. An application calls it for its own binary (SE's `se-release.yml` does, for
  `se`):

```yaml
  jobs:
    release:
      uses: mb-89/SE/.github/workflows/kern-release.yml@kern-v<version>
      with:
        directory: <the application's binary folder>
```
- **Fetching it:** `<download>/kern-<version>-<os>-<arch>.tar.gz` and `<download>/SHA256SUMS`, the
  archive checked against its line, then unpacked.

| asset | measured on 13 Nov in a Claude Code cloud container, 4 cores, Linux amd64, 5 runs |
|---|---|
| `kern-0.1.0-linux-amd64.tar.gz`, 6.44 MB (16.0 MB unpacked), built by `tools/release` and served from loopback: download, `SHA256SUMS`, `sha256sum -c`, `tar -xzf`, first run | 157 to 176 ms |
| nats-server v2.11.9 linux-amd64, 6.35 MB, from its GitHub release through the container's proxy: the same steps | 0.68 to 1.27 s |
| building the six, `go run ./tools/release build`, warm module cache | 17.5 to 18.7 s each, 110 s in all |

**The move to `mb-89/kern` changes one URL:** `release.toml`'s `download`, to
`https://github.com/mb-89/kern/releases/download/v{version}`. The workflow reads its tag and its
repository from that URL and refuses to publish into another repository than the one it runs in,
so it moves with kern's other workflows (the design's move, step 2), as `release.yml`, and
`battery.yml` below moves beside it.

## The battery

SE's `.github/workflows/kern-battery.yml` is the reusable CI every kern application calls:

```yaml
jobs:
  check:
    uses: mb-89/SE/.github/workflows/kern-battery.yml@kern-v<version>
```

It sets up the Go of the application's `go.mod` and uv, vets the Go code, and runs the
application's `se.toml` `[tests]` command, its Go tests and its Python tests, held to that table's
one budget: over `target_seconds` it warns, over `limit_seconds` or on a failed test it fails, as
SE's own suite (SE's [README "Test budget"](../README.md#test-budget)). Its input `directory`
names the application's folder, `.` by default.

## The template

`template/` is the bare application ([its README](template/README.md)): the core with no
components, an empty `wiring.toml`, `components/`, `types/`, `se.toml` with its `[tests]` budget
and `[modules.kern]`, an `AGENTS.md`, a battery that starts the bare core, and a `check.yml` that
calls the battery. It is a Go module of its own, so kern's `go test ./...` leaves it out; the
release workflow runs its battery on every change to kern.

## The catalog check's budget

The start reads `wiring.toml` and checks the whole catalog before anything runs. The budget is
`CheckBudget` in `index/budget_test.go`, which a test holds the median of nine checks of a
200-instance catalog to; `go test -run XXX -bench . ./index/` measures it.

| catalog | measured on 13 Nov, 4 cores, Go 1.24.7, 5 runs |
|---|---|
| 20 instances | 0.16 to 0.20 ms |
| 200 instances | 1.54 to 1.74 ms |

## The start

From the core's process start until a client's first request is answered. Measured on 13 Nov in a
Claude Code cloud container, 4 cores, Linux amd64, Go 1.24.7, 5 runs each, the binary built warm
with `go build -o kern ./cmd/kern`:

| what | command | wall time |
|---|---|---|
| process start to the standing file, then a client's `get.core.health` answered | a probe that starts `kern serve --root <tmp>` and reads the standing file every 100 µs, then dials as `client` and asks | standing file 9.8 to 13.0 ms, answered 11.0 to 14.5 ms |
| the same with v5's one wait for the bus, `ReadyForConnections(10s)` | the probe against a build with that wait | standing file 33.4 to 36.5 ms, answered 34.4 to 38.0 ms |
| a hook's view: `kern start` returns, then `kern status --wait 5s` says running | `kern start --root $R; kern status --root $R --wait 5s`, timed with `date +%s%N` | start returns in 6.5 to 8.7 ms, running 15.8 to 20.8 ms after the start began |

The server's own wait sleeps 25 ms between looks at its listener for any wait above 25 ms, so the
bus looks in waits of 20 ms (`bus/bus.go`, `readyLook`), and stands as soon as it listens.
