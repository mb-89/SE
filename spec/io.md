# I/O modules: the shape every one follows

Reader: an agent writing, moving or testing an I/O module, or code that needs one.

Processes, the disk, the clock, the network and GitHub are each reached
through exactly one I/O module ([principles 6 to 8](principles.md)). The
clock, `src/internal/io/clock`, is the first and the model for the rest.
The disk, `src/internal/io/disk`, covers reading, writing, listing,
locking and atomically replacing files, its fake a filesystem in memory that
fails as the real one does.
The network, `src/internal/io/http`, serves and calls the daemon protocol
(health, event, value, shutdown) and fires the routine; its fake is a network inside
the process, and its real one is tested on loopback.
`src/internal/io/proc` runs programs: git, go, check.sh, the se a session
hands over to and the detached daemon. It starts only the programs
`proc.Programs` lists, the one place that list lives: `proc.Listed`, which se
and the battery run on, refuses any other. gh is GitHub's, not proc's. Its fake
is a machine that holds only the programs a case installs, each a function
that does what the real one would, and records every run. It also says which
program is running now (`Self`): the real one asks the system, the fake
answers what the case made it run as (`RunAs`).
GitHub, `src/internal/io/github`, is read and written by REST path through
gh. Its fake, `github.NewFake(clock)`, is seeded from recorded gh answers
(`Seed`), each read for what it says about the repository, and keeps issues,
comments, labels, links, sub-issues, branches and pull requests, so a write
is read back. What GitHub comes to hold later, such as a PR's mergeability,
is seeded for a time on the fake's clock (`SeedAt`). Its real contract test
writes issues, branches and pull requests, so it runs only against the
scratch repository `SE_GITHUB_CONTRACT_REPO` names
([below](#the-real-github-contract)).

## The layout

Each I/O module is one package, `src/internal/io/<name>`, holding four parts:

| part | what it is |
|---|---|
| the interface | what SE asks of the outside thing, and nothing more. The clock's is `Clock`: `Now`, `Sleep`, `After` |
| the real implementation | the one place SE reaches that thing. The clock's is `clock.Real()` |
| the fake | an implementation that behaves, in the same package. The clock's is `clock.NewFake(at)` |
| the contract suite | one function in a `_test.go` file, called by both the fake's test and the real one's |

Code takes the module as an argument: a struct field or a parameter, set
once where the program starts (`cmd/se` hands every command `clock.Real()`
and `github.Real()`).
Nothing reaches for the real thing itself, so a test hands in the fake and a
case replays.

## Fakes behave

A fake keeps its own state and answers from it as the real thing would. It
never scripts answers: a test does not tell it what the next call returns. The
fake clock stands still until it is told to move: `Advance` moves it and fires
every `After` whose time has come, and `Sleep` passes its time at once.

Fakes keep time too: `github.Fake.Delay` and `proc.Fake.Delay` make each
request and each process start pass the latency
[spec/budgets.yaml](budgets.yaml) names on a fake clock, and the battery runs
every interactive command on them against its budgets.

## One contract suite per fake

The contract suite is what the module promises, written once. It takes a way
to make a fresh instance and runs every case against it; the fake's test and
the real one's test each call it. A fake that passes the suite stands in for
the real thing; a fake without one drifts. The clock's suite is `contract` in
`src/internal/io/clock/contract_test.go`.

## The real GitHub contract

GitHub's contract suite runs on its fake in the battery, and against the real
GitHub in the `contract` workflow (`.github/workflows/contract.yml`), on the
scratch repository `mb-89/SE-contract` and never on SE itself. It writes
there: issues labelled `se-contract` with their comments, labels, sub-issues
and blocked-by links; a branch `se-contract-<n>` with one commit, and a pull
request from it. Each case cleans up what it made: issues and pull requests
closed, branches deleted.

The job is gated: it runs when started by hand (workflow dispatch) and once a
week (Monday, 05:29 UTC), never on a pull request, so no PR waits on GitHub
or writes to another repository. It writes with the secret
`SE_CONTRACT_TOKEN`, a token that reaches the scratch repository alone, and
fails rather than skips without it. The scratch repository holds a `main`
branch and allows issues; nothing else is asked of it.

## Test on fakes, real only in contract tests

Every other test runs on fakes: no wall clock, no sleeping, no network. The
real implementation runs in its contract test alone, kept short.

Two tests are the exceptions, named here. The first,
`TestRestartRunsTheCheckoutsOwnSource` in `src/cmd/se/checkout_test.go`, builds se and stops the real daemon
processes it starts, over the real network, by `clock.Real()`. It is what
shows a restart runs the checkout's own source, which no fake can, and
`go test -short` skips it. The second,
`TestStatusAndStopReachTheDaemonOverTheNetwork` in `src/cmd/se/stop_test.go`
hands se stop the real clock: it polls for the daemon's endpoint to go, which a fake
clock passes at once, before the daemon has removed it.

## The rules

The `fake-contract` rule (`src/internal/rules/fakecontract.go`) refuses a fake,
a type `Fake` or a `NewFake` under `src/internal/io/<name>`, whose package has
no contract suite: a function in one of its `_test.go` files that a test in
`fake_test.go` and a test in `real_test.go` both call.

The `test-swap` rule (`src/internal/rules/testswap.go`) refuses a test that
assigns a package-level func variable, its own package's or an imported one's.
A test does not swap how code reaches the outside; it hands the code a fake,
as an argument or a field, such as the `World` `cmd/se` hands every call.

The `io-module` rule (`src/internal/rules/iomodule.go`) holds the line: outside
`src/internal/io/`, no Go file imports `os/exec` or `net/http`, runs `gh`, calls the
clock through `time` (`Now`, `Sleep`, `After` and their kin), or opens, reads
or writes files through `os`. Test files are held by the `fast-test` rule
(`src/internal/rules/fasttest.go`) instead: every test calls `t.Parallel`
first, and outside `src/internal/io/` no test reads the clock through `time`
or takes `clock.Real`. What still breaks it is named in
`src/internal/rules/serial.txt`, which only shrinks as the allowlist below does.

The plugin has its clock too, `$.clock`. The `plugin-clock` rule
(`src/internal/rules/pluginclock.go`) refuses, in the plugin's hooks and their
helpers under `src/plugin/`, a read of the wall clock past it: `Date.now` and
a `new Date` with no argument. The plugin's tests, which drive the mock clock,
are aside.

What broke it while the modules landed was named in one allowlist,
`src/internal/io/allowlist.txt`, one file and what it reaches per line. Each
I/O module removed its own entries as it landed, and GitHub's, the last,
emptied it. It only shrinks: the rule refuses an entry that matches nothing.

The `programs` rule (`src/internal/rules/programs.go`) holds principle 6's
"no process does what a library call can do": no Go file names a program
`proc.Programs` does not list, and none but proc calls `os/exec`. What still
breaks it is named in `src/internal/rules/programs.txt`, which only shrinks:
today gh, until the GitHub module speaks HTTP itself (#186).
