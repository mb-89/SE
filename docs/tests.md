# Tests and landings

## Test budget

```toml
[tests]
command = ["uv", "run", "pytest", "-q"]
target_seconds = 60
limit_seconds = 120
setup = ["uv", "sync"] # optional
tier = "tests.tiers:tier" # optional
over_limit = "fail" # optional, or "warn"
shards = 1 # optional: how many shards CI runs the suite in

[tests.beside.go-components] # optional, one table per suite in another toolchain
setup = ["go", "test", "-run", "^$", "./..."] # optional
command = ["go", "test", "./..."]
directory = "components"
target_seconds = 30
limit_seconds = 60
paths = ["components/", "se.lock"] # optional: run only where the change touches one
```

| Key | Default | Meaning |
|---|---|---|
| `command` | — | the project's complete suite, an argument array run without a shell from the project root. `work_tickets.py integrate` runs it at every integration, and `work_tickets.py suite` runs it the same way for a worker's before-and-after times. |
| `setup` | optional | of the same form as `command`; it installs the test dependencies (packages, browsers) and runs first. The gate prints its time and its last lines apart, and that time does not count against the budget. A failing setup stops the run before the suite, naming the command and its output. |
| `target_seconds` | 60 | above it the gate warns. |
| `limit_seconds` | 120 | the budget, judged on one reference run, CI's (below). |
| `over_limit` | `"fail"` | what a run over the limit does. One rule holds for every project: an overrun fails, as below. A project that declares `"warn"` takes the other side of the trade-off: no run is refused for its time, so a slow runner never blocks a landing, but nothing stops the suite from creeping past its budget; each overrun only warns, naming the setting. |
| `shards` | 1 | how many shards CI's `check` runs the suite in, side by side (below). SE's own suite, unsharded, keeps the default: its limit is the whole suite's. |
| `beside.<name>` | optional | a suite in another toolchain, such as SE's Go components' tests on kern at its pin (`setup` places it); kern's own tests run in kern's repository. Its `command` runs in `directory` (relative to the root, default `.`) after the complete suite, wherever the suite runs: `integrate`, `work_tickets.py suite` and CI's `check`. |

- `shards`:
  - Over 1, `target_seconds` and `limit_seconds` are each shard's, which CI's slowest shard is
    held to.
  - A run of the whole suite (`integrate`, a worker's `suite`) is judged against `shards` times
    each, and CI's time it reads is held to the limit per shard.
  - It must be the `shards:` a workflow passes the `suite-time` action: `se_workflows.py check`
    fails on another literal number, naming both files and both numbers ([Workflows](running.md#workflows)).
- `beside.<name>`:
  - Its `setup`, optional, runs first in the same folder, outside its budget, as the suite's
    does: for a Go suite, `go test -run '^$' ./...` builds every test binary, so a cold build
    (kern's took 35.1 s once on CI, while SE carried it) never counts as test time. A failing setup refuses the run, and the suite beside does not run.
  - Its `paths`, optional, keep a slow suite off the landing path: a file, or a folder ending
    with `/`, relative to the root. The suite then runs only where the change touches one: the
    commits since their merge base with origin's integration branch (a landing's merge, a pull
    request's merge on CI) and what the checkout holds uncommitted.
    - Elsewhere it is skipped, in one line of the output and of the result, naming the base and
      the paths. Where that branch is not fetched, it runs, saying why.
    - `work_tickets.py suite --full` runs it anyway, as CI's nightly run does (`check`'s
      `schedule`). On CI a failing suite beside is also an error annotation naming its failed
      tests.
  - A key the running scripts do not know is refused on the reference run (CI's `check`, which
    runs the merged tree's scripts) and elsewhere warns and is ignored. `integrate` runs the
    integration branch's scripts, so a branch can add a key and use it in one landing.
  - A suite beside that passed without running a test is named in one line after its time, and
    its verdict stands; `scripts/suite_runs.py` says which output counts as no test run.

Before either runs, a checkout that still holds a moved folder's output is refused: a folder
with ignored files and no tracked one, where git deleted tracked files before, as a move to another
repository leaves its tool environments and bytecode behind.

The refusal names each folder and its remedy, `git clean -fdX <folder>`; a folder git never
tracked, such as `.venv`, is no such folder.

A folder that holds only Python's cache (`__pycache__` folders, `.pyc` files), as a restored
container brings it back, refuses nothing: SE removes it and names it in one line.

The two budgets are apart, and neither spends the other's time:

- Each run prints and reports both times, `Suite: <result>; <time> (target, limit); go-components passed
  in <time> (target, limit)`, and the metrics line notes `beside_seconds` beside `suite_seconds`;
  `work_tickets.py metrics` flags a suite beside over its limit as it does the suite
  ([Metrics](running.md#metrics)).
- A failing suite beside refuses the run as a failing suite does, with its output. A suite beside
  over its target warns. Over its limit, only the reference run refuses it; elsewhere it warns, as
  it has no CI reading of its own; `over_limit = "warn"` holds for it too.
- `suite --compare` and the sharded suite's actions time the complete suite alone.

The budget's reference is the suite of the CI `check` job, on the same runner type every time, as
cloud hosts differ by about 25 s for the same tree. Over the limit there, `check` fails, naming the
test result (passed, with its counts), the time, the limit and the slowest tests. Every CI run
reports its time as a `se suite time` notice on its check run.

CI's suite time is the wall time of the run the budget judges. For an unsharded suite it is the
whole run's, the `suite` step of `check`. For a sharded suite, whose shards run side by side as
parallel jobs, it is the slowest shard's: that is the time `check` waits for, while the shards' sum
would count work nobody waits for.

A sharded project records it with SE's two actions, as the copies SE writes into it at the se
pin ([Workflows](running.md#workflows)), which the module command's `update se` moves with the pin:

```yaml
jobs:
  shard:
    strategy:
      matrix:
        shard: [one, two]
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@v7
      - uses: ./.github/actions/suite-shard
        with:
          name: ${{ matrix.shard }}
          command: uv run pytest -q tests/${{ matrix.shard }}
  check:
    needs: shard
    if: always()
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@v7
      - uses: ./.github/actions/suite-time
        with:
          shards: 2
```

- [`suite-shard`](../.github/actions/suite-shard/action.yml) runs in each shard:
  `work_tickets.py suite-shard` runs the shard's command, times it and writes its record, which
  the action uploads, also when the shard fails.
- [`suite-time`](../.github/actions/suite-time/action.yml) runs in `check`: `work_tickets.py
  suite-time` collects the records, lists each shard and prints the slowest shard's time as the
  `se suite time` notice, `Suite time: 66.1 s (limit 120 s; slowest of 2 shards: 66.1 s (shard
  1))`.
  - It fails `check` where a shard's record is missing, and over the limit as above.
  - Where a shard failed, it prints no time: the run failed, and a failed run's shorter time
    never stands as CI's.
  - Its refusals and warnings are `::error` and `::warning` annotations on the check run, printed
    after the shards' list.
- Both actions run SE's scripts with the runner's `python3`, which must be Python 3.11 or later
  (they read `se.toml` with `tomllib`); `ubuntu-26.04` has it, another runner sets it up first,
  for example with `actions/setup-python`. The actions they use run on Node 24.
- `check` runs with `if: always()`, so a failed shard fails the check the ruleset requires instead
  of skipping it.

Every other run (`integrate`, a worker's `suite`) runs the complete suite too. Over the limit it
reads CI's suite time on the integration branch through github.com's API without an account (so
`suite` needs no `gh`; a private repository's time reads as unknown).

The time it reads is the median of the last five successful `check` runs that report one, the
newest on each of the last eight first-parent commits, so one slow runner does not count and a
shorter failed run is never read; the run names the times it took the median of.

- Under 90% of the limit: it warns with the time, the host's load and CI's time, and passes; the
  landing pull request's `check` judges the budget.
- Within 10% of the limit, or unknown: it refuses, naming both, so a creeping suite is caught
  before it breaks.

The gate measures the suite's wall time and prints it with the last lines of the suite's own output
and the ten slowest tests (`suite --slowest N` lists N). Failed tests exit with code 1, a passing
suite the budget refuses with code 3. How tests are written is owned by the
[work model](../src/skills/work-model/SKILL.md#tests).

SE's own suite also bounds each test's time (`tests/time_bound.py`) and refuses its own process the
network beyond this machine (`tests/network_guard.py`), each failure naming the test and the remedy.

A runner of any kind may write JUnit XML reports into the directory named by the environment
variable `SE_TEST_REPORTS`, one file per part. The gate then lists the slowest tests across all
reports, each with its part (the file's name), and prints one line per part, so a speed issue names
the right lever, one long test or the part's total work:

```text
<part>: 84.2 s wall; 309.6 s test time / 4 workers = 77.4 s; slowest 17.5 s
```

The wall time is the report's own `time`, the worker count its `workers` testsuite property
(pytest's `record_testsuite_property`), 1 without one.

Where a test case carries a `setup_time` property (pytest's `record_property`, with `worker` and
optionally `fixture`), the part's line is followed by each test whose setup took over 2 s. Each
such setup, named by its fixture or else its module, that more than one worker paid follows too:
the signature of broken test grouping.

se's own suite writes such a report, `se.xml`, from `tests/conftest.py`.

```text
    slow setup 6.0 s tests.test_ui::test_a (browser, worker gw0)
    setup browser paid on 2 workers (gw0, gw1): 12.5 s; group its tests on one worker
```

CI's suite step keeps that report as the artifact `test-reports` (`suite --keep-test-reports DIR`,
also from a failed run), with the runner's `cpu` and each test's `started`, its seconds from the
session's start. `work_tickets.py test-seconds` prints, per run, its wall, cpu and when each worker
started and finished, then the slowest tests' medians over CI's recent runs.

Without reports the gate reads pytest's lines
(it adds `--durations=<N>` to a pytest command), and where neither names a test it says so and names
that remedy.

Where `tier` names the project's tier function, `<module>:<function>` with the module importable
from the project root, the gate calls it with each reported test's id (`<classname>::<name>`, as the
listing names it) and prints, per tier, from the reports, its slowest test and time:

```text
Slowest per tier:
  browser: 1.10s browser ui::page11
  unit: 2.50s unit tests.test_a::test_slow
```

A `tier` it cannot import is refused before the suite runs; without `tier`, nothing changes.

`work_tickets.py guard` checks deleted sentences in the configured project paths. Each configured
glob is relative to the project root. The field report must name every removed sentence in its
authored-prose section.

A sentence ends at a dot, `!` or `?` before whitespace, and at the start
and end of a fenced block, at a heading and at a block-id line, so a paragraph added or removed
between two unchanged blocks is that paragraph alone.

Generated text is not authored, and the guard leaves it out by the mark its generator writes with
it. That is a block from a `<!-- generated by <generator>: begin -->` line to a
`<!-- generated by <generator>: end -->` line (the command reference below), and the whole of a
file that holds the notice `se_plugin.py build` opens each generated Markdown file with.

## Trusted landings

`integrate` runs the complete suite on exactly the tree it lands, and CI's `check` would run it
again. For a private repository, billed by the minute, a project may trust that run instead:

```toml
[tests]
trust_integrator = true # default false: CI runs everything, as SE and obs do
full_every = 10 # optional: every 10th landing runs the full suite anyway
integrator = "<login>" # optional: the account that records; default the repository's owner
```

- **The record.** Where it is on, `integrate`'s landing plan dispatches the workflow
  `se-pass-record.yml` on `land/<branch>` before it opens the landing pull request, and waits for
  its run.
  - The run writes the check run `se integrator pass` on the landing head: the tree, the test
    command, the suite's hash (`[tests]` and the se pin), the result, the time and the integrator
    session (`SE_SESSION`, else `CLAUDE_CODE_SESSION_ID`).
  - Through `gh` the door dispatches it; in the cloud the plan carries it as two steps the GitHub
    tools make: `actions_run_trigger` (`method` `run_workflow`, `workflow_id`
    `se-pass-record.yml`, `ref` the landing branch, `inputs` the record) and `actions_list`
    (`list_workflow_runs` of that workflow, event `workflow_dispatch`) until the run completes.
  - A record that does not arrive stops nothing: `check` then runs the full suite.
- **The shortcut.** `check`'s job `trust` runs `ci_trust.py lookup` (the action
  [`integrator-pass`](../.github/actions/integrator-pass/action.yml)) and the suite runs only where it
  answers false. It trusts the newest record on the pull request's head, or on a push the head of
  the pull request that landed the commit, only where its tree is exactly the tree checked out, and
  names the record it trusted.
- **The trust boundary.** Only the integrator may write a record: `lookup` trusts one written by
  github-actions in a run of `se-pass-record.yml`, dispatched by the integrator's account, whose run
  name and head name the record's commit and tree. The record step itself refuses another account's
  dispatch, and inputs the commit it checked out does not bear out.
  - A record of another tree (a main that moved since, so a merge onto it), of another suite hash
    or record format (stale), by any other writer or with any other result is not trusted, and
    the full suite runs (`tests/test_ci_trust.py`).
- **The safety net.** The full suite runs every night on main (`check`'s `schedule`), and on
  every landing whose first-parent number on main is a multiple of `full_every`. After a full pass
  `full-pass` marks the commit with the check run `se full pass`.
  - After a failed full run `finding` reports the finding as an error annotation on the run: the
    trusted records of the landings since the last full pass, the records that let the change
    through.

A project's own `check` uses the action's copy at the se pin, as the sharded suite does
([Workflows](running.md#workflows)); its copy of `se-pass-record.yml` calls the same copy,
`./.github/actions/integrator-pass`, with `mode: record`:

```yaml
jobs:
  trust:
    runs-on: ubuntu-26.04
    outputs:
      trusted: ${{ steps.lookup.outputs.trusted }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - id: lookup
        uses: ./.github/actions/integrator-pass
        with:
          mode: lookup
  check:
    needs: trust
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@v7
      - if: needs.trust.outputs.trusted != 'true'
        run: uv run python <se>/scripts/work_tickets.py suite --worktree .
```

Its permissions are `checks: write` (the marks) and `actions: read` (the record's run). SE keeps
`trust_integrator` off: its `check` runs the full suite and kern-platforms on every pull request
and push.

A kern application gets the same shortcut from its battery: its copy of `kern-battery.yml`'s job
`trust` runs the action from SE at the pin the copy names ([Workflows](running.md#workflows)), and the vet
and tests run only where it answers false.

To turn it on, the application also grants those two permissions, adds the `schedule` and copies
`se-pass-record.yml` with the action's copy beside the battery's. kern's template keeps it off
(kern's README "The battery").

Free minutes for a private repository, which the owner sets up:

- Linux runners only (`ubuntu-*`): a Windows minute counts double.
- `check` on pull requests only, so a landing is not run again on its push to main; the nightly
  `schedule` keeps main covered.
- Never on data-only pushes: `paths-ignore` for the files no test reads.
- An Actions budget of $0 in the account's billing settings, so a month past the free minutes
  stops the runs instead of billing them.
- Each run's job is billed by the started minute: a trusted `check` and the record's run cost a
  minute each, against the full suite's own minutes.

### Landing without CI

Some hosts give a repository no runners (the host's administrator turned Actions off): no
`check` ever runs, and no record can be dispatched, so nothing lands. There the integrator's own
complete run is the verdict, through the same landing and the same code path:

```toml
[tests]
ci = false # default true: CI's check is the verdict, wherever the host has runners
```

- **Chosen once, by this setting alone.** se never infers it from the host's answer: a runner
  missing for an hour must not turn a landing with CI into one without. It is off unless set.
  - It is read from se.toml on the integration branch the landing starts from, and for the
    pre-push gate on the pushed commit's first parent, never from the branch landed: no branch
    switches its own verdict source.
  - `trust_integrator = true` beside it is refused, as the record needs a runner.
- **The verdict.** Once the complete suite, the project's checks and the public check passed on
  the landing head, the landing plan writes the commit status `se integrator verdict` on that
  head through the host's API, before it opens the landing pull request. No workflow, no runner.
  - Its state is `success` and its description `passed tree <tree> suite <suite hash>`: the
    tree and the suite's hash (`[tests]` and the se pin) as the [record](#trusted-landings)
    names them, the hash by its first 40 digits, so a sha256 tree fits the host's 140
    characters too.
  - The host and its API come from origin (`gh api`, with origin's host), as every step does.
- **Its check.** The plan's check step reads the newest status of that context on the head
  instead of the check run `check`, and merges only once it is accepted. The pause, the pull
  request, the squash at that head (or the fast-forward to it, where `[integrate] landing` says
  so) and the read-back are the landing above.
- **Accepted only where bound.** A status is accepted only where all of these hold:
  - its state is `success`, its context exactly `se integrator verdict`;
  - its tree is the commit's tree, and its suite hash the commit's;
  - its creator is the integrator (`[tests] integrator`, default the repository's owner).
    The host sets a status's creator from the token that wrote it, so no text in a status can
    claim it.
  - Any other status, or none, merges nothing and escalates (`tests/test_ci_trust.py`).
- **The pre-push gate.** Where it is on, `verified` and `push` accept a push of the integration
  branch whose tree lacks the local verdicts where that commit, or the head of the pull request
  that landed it, carries an accepted status. Where it is off, they read no status.
- **Through `gh` only.** The host's GitHub tools write no commit status, so where `gh` is not
  signed in `integrate` refuses before it merges anything, naming the setting.
- **The host's side, the owner's step.** The ruleset of the integration branch requires the
  status `se integrator verdict` in place of `check`; the token `gh` holds is the integrator's.


## Platform legs and their queue

kern-platforms runs SE's start, hook and setup tests and its worktree removal tests on a Windows
runner, and `check` needs every leg; kern's own tests on Windows run in kern's repository's
`check`. The job keeps its name, which `work_tickets.py`, `ci_queue.py` and `check-rerun.yml` read.
The `se` binary is built for darwin; neither it nor the start and hook scripts are tested there.

A job's `timeout-minutes` counts only from when a runner takes it, so it
bounds a leg that runs (45 minutes) and not one that waits: a leg that never gets a runner waits
until GitHub fails it after 24 hours, and `check` with it.

- **The queue bound.** The job kern-platforms-queue
  ([scripts/ci_queue.py](../scripts/ci_queue.py) `watch`) reads the run's jobs every 30 s. Once every
  leg has a runner it passes; a leg still queued after 20 minutes is reported as never run, an
  error naming the leg and in the job's summary, not as a test failure, and the run is cancelled.
- **Re-run once.** `.github/workflows/check-rerun.yml` hears each completed run of `check`
  (`ci_queue.py rerun`): a first attempt that was cancelled while a leg never had a runner is
  re-run; a second attempt, or a run that ended any other way, stays as it ended.
- **Tested** against a fake of the jobs API and a fake clock (`tests/test_ci_queue.py`); GitHub's
  own queue, cancel and re-run are not reproducible there.

## Edits reuse the suite

A pull request's description and labels change many times without a new commit: the worker
corrects its field report, the integrator moves labels. Each change starts `check` again, on a tree
already checked, so such a run checks again only what it can change and takes the rest from an
earlier run ([scripts/ci_reuse.py](../scripts/ci_reuse.py)).

- **What runs again.** On `edited`, `labeled` and `unlabeled` the gate of the commits, the issue
  rule, the field report and every other cheap step run as always.
- **What is taken.** The suite, the Go checks and kern-platforms: the job `trust` reads the runs of
  `check` for the same head, newest first, and takes the first result of the same reuse key.
  - The key is the tree checked out, the merge of the head into its base, so a base that moved is
    another tree; and the Component kinds the description gives the suite's release guard.
  - Each run names its decision step with its key, `Reuse an earlier result of this tree (reuse
    key <key>)`, which a later run reads in the jobs API; a run that took a result or stopped
    before the suite holds none, and the run before it is read.
- **A failure stays.** A failed suite, Go check or leg of that tree keeps `check` failed, as an
  error naming the run it came from; a pass is a notice naming it.
- **Everything runs** where no completed run of the head holds a result for the key, where the
  newest completed one was cancelled, on a re-run attempt (re-run all jobs to run them again), and
  where the runs cannot be read. Every other event runs everything, as always.
- **Tested** against a fake of the runs and jobs API and through a local GitHub
  (`tests/test_ci_reuse.py`), with the steps of `check` that act on the decision run as the runner
  runs them.
