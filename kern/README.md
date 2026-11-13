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
| `cmd/kern/` | the bare binary: `kern start`, `kern status`, `kern stop`, `kern serve` | |
| `contract/` | the contract suite: the built binary held to the bus's and the host's promises | |

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

- **The standing file**, `.se/.runtime/standing.json`, readable by its owner alone: the bus's
  address, the pid, the contract version and every bus user with its password. A pid that runs
  nowhere reads as absent; the core removes the claim once it has written the file.
- **Leases.** Each `hook.<event>` with a `session_id` takes or renews that session's lease and
  `hook.SessionEnd` returns it. A component beats on `lease.<i>` every 5 s; a placed instance's
  names read `stale` once three beats are missed.
- **Placements.** A wiring instance with `command = [...]` runs in a process of its own, started
  with `CORE_BUS`, `CORE_USER` and `CORE_TOKEN`; it commits on `commit.<i>` and the core checks
  each write against the component's declaration. Until a placed process answers `run.<i>` and
  `cmd.<i>.>`, the core refuses to place a component that declares a derivation or a command.
- **The idle end.** The core ends 60 s after the last session's lease is returned (or after its
  start, where none took one), or after 30 minutes without a hook event or a call.

## Tests

```sh
cd kern && go vet ./... && go test ./...
```

SE declares kern's tests beside its Python suite, `se.toml` `[tests.beside.kern]`, with their own
time and budget (SE's [README "Test budget"](../README.md#test-budget)): `integrate`,
`work_tickets.py suite` and the `check` job, the check `main`'s ruleset requires, run them after
the suite, so a red kern test refuses the integration and the Python suite's budget is untouched.
`check` vets kern in its own step. The job `kern-windows` runs
kern's vet and tests on Windows, where the detached start and the stop differ; `check` needs it
and fails unless it passed.

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
