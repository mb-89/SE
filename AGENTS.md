# Agent guide (se)

- This repository is common and open source; it must stay publishable
  ([pub-001](src/skills/work-model/references/rules.md#pub-001-publishable-at-any-time)); its check is owned by
  [Public safety](#public-safety).
- SPOT everywhere: one owner per fact; everything else links to it
  ([gen-002](src/skills/work-model/references/rules.md#gen-002-single-point-of-truth)).
- No backwards compatibility unless asked.
- Scripts are ad hoc, components are long-term
  ([gen-001](src/skills/work-model/references/rules.md#gen-001-mechanize-first)): an ad hoc solution
  stays untracked, a script in the scratch directory or an ad hoc Python component `se component add`
  scaffolds under `.se/components/`; what the whole system keeps is a tracked component under
  `components/`, with its declaration and tests ([docs/go-core.md](docs/go-core.md)).

## Agents and skills

- Each agent and skill is written once, in `src/agents/<name>.md` and `src/skills/<name>/`, for
  both hosts: its body serves Claude Code and Copilot (prose for one host says so, such as "Under
  Copilot").
  - Each agent becomes one file, `agents/<name>.md`, which both hosts read: Copilot reads Claude
    Code's agent format, and a second copy would list every agent twice in VS Code.
  - An agent has no `tools` list (Claude Code would read it as an allow-list and take tools from
    the agent); a key prefixed `claude.` loses its prefix, and one prefixed `copilot.` is refused.
- `uv run python scripts/se_plugin.py build` generates everything else from it:
  - the Claude Code plugin (`agents/`, `skills/`, `.claude-plugin/`), which Copilot's manifest
    names too;
  - Copilot's manifest with its own hooks (`.github/plugin/`, `.github/hooks/`,
    `.github/mcp.json`); both hosts load the one `agents/` and the one `skills/`.
  - Never edit those by hand; `tests/test_se_plugin.py` checks they match.
- Each guidance note, `guidance/**/<file>.md`, is also a skill: the build writes it into
  `skills/<name>/SKILL.md`, `<name>` its front matter's
  ([docs/guidance.md "Notes in folders"](docs/guidance.md#notes-in-folders)).
  `se_plugin.py check` also runs `scripts/se_guidance.py check`, so an orphan note fails there.
- The outside skills a role relies on are one list, `se.toml` `[roles.<role>] skills`, never an
  agent's own front matter.
  - Each entry is `<plugin>@<marketplace>:<skill>`; a skill Claude Code ships loads by itself and
    is not listed.
  - The build preloads it into that agent's `skills` field.
  - The start greeting names an entry the session lacks
    ([docs/start.md "Start and refresh"](docs/start.md#start-and-refresh)).
- Every pytest run builds them first (`tests/conftest.py`, naming each file it wrote), so no suite
  tests a stale layout and nobody runs the build by hand before it; commit what it wrote.
- Installing SE on a clean machine is [Getting it running](docs/install.md#getting-it-running);
  on a host, its [Install](docs/install.md#install).

## Tests

| Suite | Command | When it runs |
|---|---|---|
| Focused | `uv run pytest -q tests/<file>.py` (add `-k <name>` for one test) | the tests of what changed |
| SE's Go components under `components/` | `uv run python scripts/se_modules.py sync kern`, then `cd components && go vet ./... && go test ./...` | on kern at the pin `se.toml` `[components.kern]` reads from `components/go.mod`, in `.se/modules/kern` (every pytest run places it first, `tests/conftest.py`); declared beside the suite as `se.toml` `[tests.beside.go-components]`; their agreement test holds the Go fleet and retro-due components to the Python paths ([components/README.md](components/README.md#tests)); kern's own tests run in kern's repository |
| Complete | `uv run pytest -q` and the suites beside it | declared with their time budgets in `se.toml` `[tests]`; `integrate` runs both against them, and `work_tickets.py suite --worktree <checkout>` runs them the same way ([docs/tests.md "Test budget"](docs/tests.md#test-budget)) |
| Repository hygiene | `uv run python scripts/hygiene.py` | a step of the `check` job, not a test: it checks SE's own checkout through git's real door; its logic is unit-tested on the fake, each check failing on a fixture (`tests/test_repository.py`, `tests/test_references.py`) |
| Dangling references | the same command | it fails where the agents, the skills (the rule book among them), README.md or AGENTS.md name what the repository lacks |

- Focused, also run:
  - on a change to Markdown the docs build publishes (`docs.md` and every note it lists),
    `tests/test_docs.py`, whose build fails on obs's lints, a paragraph over five lines among them;
  - on a change to `.github/workflows/check.yml`, `tests/test_public_check.py`, which holds the
    workflow's jobs and their order, beside the tests of the steps it changed (such as
    `tests/test_kern.py` for kern's, `tests/test_pr_issues.py` for the issue rule's).
- Processes: a test starts none; it calls the code under test in-process, a script through its
  `main(argv)`, a hook through its logic (the guidance note
  [tests-spawn-no-processes](guidance/pull-request/field-report/tests-spawn-no-processes.md)).
  - Every program but git starts through `scripts/process_door.py`; a test's code reaches the
    fake, `tests/fake_processes.py`, which answers SE's scripts and hooks in-process and `gh` or a
    suite command by the test's handlers (`fake_processes` fixture).
  - The shell is a door, like git, gh and the network; a test never starts a shell. Every shell
    starts through `scripts/shell_door.py`, to which the process door hands a shell command; a
    test's code reaches its fake (`fake_shell` fixture). Only the shell door's contract,
    `tests/test_shell_door.py`, and a shell script's one entry-point test start a real one.
  - The spawn guard, `scripts/spawn_guard.py`, refuses a start outside a door's contract
    (`@pytest.mark.spawns("contract: <door>")`) or a script's one entry-point test (`entry:
    <script>`), naming each call. There is no baseline: `pyproject.toml` sets it to `warn` while
    the tests that still start processes are converted, and the landing that converts the last
    sets `error`.
- File order: `tests/file-seconds.json` holds CI's seconds per test file, as CI's runner runs the
  PowerShell cases and skips the Playwright ones; a change that moves a test file's time by
  several seconds refreshes it from its pull request's `check` run with
  `uv run python scripts/work_tickets.py file-seconds`, and that run names each file that drifted.
- kern: the `check` job syncs kern at its pin and fails where the committed `se.lock` lags
  `components/go.mod`'s `require kern`; the job `kern-platforms` runs the tests of SE's start and
  hook scripts on Windows, with those of `setup.ps1` (`tests/test_public_check.py -k powershell`);
  darwin is built, not tested. kern's vet, gofmt and Windows run are kern's repository's `check`.
- Repository hygiene:
  - It fails on a tracked binary file, a tracked file over 200 KB, or a `TODO`/`FIXME` in
    `scripts/` or `tests/` naming no issue; a file that must break the first two goes in its allow
    list there, with its reason.
  - It also fails on a git subprocess outside `scripts/git_door.py`, git's one door, in scripts,
    tests, kern and the components; a test that needs git uses the door's fake (`fake_git_door`
    fixture, `tests/fake_git.py`), which `tests/test_git_door.py` holds to real git. Its allow
    list of other git subprocesses is empty.
  - A shell script runs git through the door as a command, `git_door.py <git arguments>`: the
    hooks, `scripts/setup.sh`, `setup.ps1` and the `check` job's gate. The check reads no shell.
  - A test whose scripts or kern binaries run as child processes takes `shared_fake_git`: the
    fake behind a state file that `SE_GIT_DOOR=fake:<file>` names to both doors
    (`scripts/git_door.py`, kern's Go door `kern/git` in kern's repository).
  - A test that starts none takes `fake_git_door`, in memory: `shared_fake_git` fails one that
    ran git through it and started no child, unless `tests/conftest.py` `IN_PROCESS_STATE_FILE`
    names its file.
  - Behind the door, `tests/conftest.py` refuses real git to every test outside its `REAL_GIT`
    list, and to the child processes it starts: only the contract suite, `tests/test_git_door.py`.
    A test that reaches real git without the fake fails, naming the command.
  - It also fails where a file a program writes is not marked, a marked file is not declared in
    `generated.yaml`, or a generator's fresh run differs (`scripts/generated.py`, the guidance
    note `generated-files-are-marked`); the commit hook runs the same check without the fresh runs
    (`se.toml` `[commit_checks]`).
  - It also fails where README.md is not one page with its one command first (`scripts/readme.py`,
    the guidance note [readme-is-one-page](guidance/readme-is-one-page.md)); the commit hook runs the
    same check, and the `check` job's `showcase` runs that command on a fresh runner.
  - It also fails where SE's checkout fails its public check, with SE's own line of history
    ([Public safety](#public-safety)).
- Dangling references:
  - A section reference, `<page>.md "<section>"` or `README "<section>"`, in any tracked text file
    whose page holds no such heading (the check `sections`).
  - A link to a missing file, a missing repository path in code (`scripts/…`, `src/…`, `tests/…`,
    `.github/…`), or a script subcommand its argument parser does not define.
  - `scripts/references.py` owns what counts; the issue-filing commands call it too
    ([Issues](src/skills/work-model/SKILL.md#issues)).
- Fixes: `uv run python scripts/work_tickets.py format` writes what the `check` job's generated
  checks refuse; SE runs no code formatter or linter, and its other checks have no fix to apply.
  - the layout (`se_plugin.py check`);
  - the interface templates' generated schemas (`templates.py interfaces --check`, held by
    `tests/test_interfaces.py`);
  - the command reference (`docs/work-commands.md`) with its components' declarations (`work_tickets.py docs
    --check`).
- Test environment: none to load; `tests/conftest.py` clears the runner's variables (`CI`,
  `SE_CLOUD_AGENT`, `SE_DEFAULT_AGENT`, every `GITHUB_*`) for the session, and a test that needs one sets it. Where uv warns that it cannot verify TLS behind a proxy, set
  `UV_SYSTEM_CERTS=1` in that shell.
  - Each test runs in an empty home of its own (`own_home`, no global or system git config, obs's
    components in `.se/obs-local`); the machine's tool caches stay (`machine_caches`).
    On Windows the home starts with empty local and roaming app-data folders for child processes.

## Neutral home

- No tracked file names where SE lives: no host, owner or repository of SE. The same tree may live
  on more than one Git host, and only a machine that holds both remotes knows that; how changes
  move between them is the work model's
  [More than one remote](src/skills/work-model/SKILL.md#more-than-one-remote).
- Where SE needs its own location, it derives it from the checkout's origin through
  `scripts/se_home.py`, one helper for every Python reader: the home, the tracker, the docs URL and
  module URLs relative to origin (`../obs.git`). Docs write `<owner>/<repository>`, explained once.
  - Go asks kern's `kern/home`, which answers the same; both suites read one table, kern's
    `home/testdata/origins.json`, from kern's clone at its pin (`.se/modules/kern`).
  - Go module paths name no host (`kern`, `se/components`), and a `release.toml` names its
    download as a path under the home (`releases/download/<tag>`).
- `uv run python scripts/hygiene.py` enforces it (its check `neutral-home`, tested in
  `tests/test_repository.py`): a tracked line that names origin's owner fails, naming file and
  line; its `HOME_ALLOWED` is empty.

## Public safety

The rules are the rule book's [`pub` section](src/skills/work-model/references/rules.md#pub-publishing-and-security); this
section owns the check that enforces them.

- Publishable at any time: [pub-001](src/skills/work-model/references/rules.md#pub-001-publishable-at-any-time). Use generic names
  (`<name>`, `alice`, `example.com`).
- A generic commit identity: [pub-002](src/skills/work-model/references/rules.md#pub-002-a-generic-commit-identity).

`scripts/public_check.py` enforces the rule on tracked file names and contents (binary files as bytes),
commit messages and author and committer identities. It prints locations and pattern labels, never the
matched text; exit code 0 passed, 1 hits, 2 setup error.

The commit gates are `--message-file` and the commits of a `--range`, as the hooks and `integrate`
pass it; they refuse:

| Check | Rule | What it refuses | Remedy | History already pushed |
|---|---|---|---|---|
| Tracker references in commit messages | [pub-004](src/skills/work-model/references/rules.md#pub-004-no-tracker-references-in-commit-messages) | a tracker reference; as it names nothing private, the gate prints the reference | printed with the reference | a full check leaves it alone; a commit already published passes by its reasoned message entry in `.public-check-allow` |
| Attribution trailers in commit messages | [pub-003](src/skills/work-model/references/rules.md#pub-003-no-attribution-trailers) | a `Co-Authored-By:` or `Claude-Session:` line in any case, naming the commit and the remedy | reword before pushing | a full check leaves it alone |
| E-mail addresses in commit messages | — | a message line that holds one, whatever the address (a service's `noreply`, `example.*` included), naming the commit and the line, never the address | reword before pushing | a full check leaves it alone |
| The project identity, in the commit gates of a `--range` only | [pub-002](src/skills/work-model/references/rules.md#pub-002-a-generic-commit-identity) | where the project sets an `identity` (or the machine a `public_identity`, which wins), a commit whose author or committer differs, naming the commit, the identity found (redacted) and the remedy | named in the refusal | a full check leaves it alone; a commit already published passes by its reasoned commit entry in `.public-check-allow` |

- Attribution trailers: every author is refused, the owner included; a co-author line's hit also
  names the editor setting that writes it ([docs/install.md "Install"](docs/install.md#install)).
- The project identity:
  - Where `se.toml` `[integrate] landing` is `"fast-forward"`, the gate is strict: a commit
    GitHub made is foreign like any other, its web-flow committer (`GitHub`, `noreply` at
    `github.com`) and a squash merge's account author alike, as every landing is the
    integrator's own commit ([docs/settings.md "Landing on main"](docs/settings.md#landing-on-main)).
  - While it is `"squash"`, the built-in, GitHub's web-flow identity passes as committer, never
    as author. On such a commit the author may be the account that owns `origin` on
    `github.com`, by its `users.noreply.github.com` address: the squash merge of a pull request
    into `main`. Every other account stays foreign.
- CI: the job `check` of `.github/workflows/check.yml` runs the commit gates of a `--range` over
  the commits of every pull request and of every push to `main`, so a push the hooks did not see
  fails there; `check` is the check `main`'s ruleset requires.
  - A pull request's gate scans the checked-out merge of its head into its base, the tree its
    landing lands, by that tree's allow list (`--rev HEAD`); its range is the commits its head
    holds and its base does not.
  - A push's range is `public_check.py --push`'s, by branch. To the integration branch: the
    commits after its old tip, or where that tip is unknown those no other branch holds, gated
    whole.
  - To a work branch, where the integration branch is the default branch and origin's ref for it
    exists: the commits after its old tip, or all its commits where that tip is unknown, without
    those the integration branch holds, which are not gated again; otherwise as to the
    integration branch.
  - The same job runs every other check an integration runs: `se_plugin.py check`,
    `work_tickets.py docs --check`, `hygiene.py`, `field-report --check` of a pull request's
    description against its work issue where it carries a report (a landing pull request's, from
    the work pull request it links, [Landing on main](docs/settings.md#landing-on-main)), and
    `work_tickets.py suite` in budget.
  - On a pull request it also runs `pr_issues.py`, the work model's rule that the description
    names an open work issue ([Integration branch](src/skills/work-model/SKILL.md#integration-branch)).
  - On a pull request it also runs the action `release-kind` (`pr_issues.py --release-kind`), the
    work model's rule that the description states its release kind
    ([Release kind](src/skills/work-model/SKILL.md#release-kind)).
- A `--range` on a shallow clone that reaches beyond the fetched history is refused with exit code
  2, naming `git fetch --unshallow`, so a gate never passes over commits it cannot see.
- Two layers, and no third: the public list is committed and holds every term that may be
  public; the local list is never committed, holds what is private and may switch a public entry
  off. Nothing committed refers to the local list's content, since knowing it says what is meant
  to stay hidden; in doubt, a term stays local. No setting, variable or secret holds terms.

| List | Where it lives | What it holds |
|---|---|---|
| The public list | `scripts/public-check-terms.toml`, read from the se module the check runs from | the generic patterns every source is checked against: user profile paths (`X:\Users\<name>`, `/home/<name>`, `/Users/<name>`), e-mail addresses other than `*@users.noreply.github.com` and `example.*`, enterprise GitHub hosts (GitHub Enterprise Cloud subdomains), machine names in UNC paths |
| The local list | `.public-check.local` at the root of each source (a repository or a vault); a linked git worktree without one uses its main checkout's | terms that must never be written down here |
| The machine-level list (retired) | `~/.se/private-terms.txt`, `SE_PRIVATE_TERMS` | while one is configured, the check stops and names where its terms go, `<source>/.public-check.local` |

- The public list: the fixed addresses services write into commits themselves, `noreply` at
  `github.com` and at `anthropic.com`, name no person and pass.
- The local list: without it the check warns and runs the public list only, as on a public CI
  host. `#` starts a comment line; every other line is one of
  - a case-insensitive regex, a term this source keeps private; hits name only its line number;
  - `remote:<remote name> <regex>`, a term only of a push to that remote;
    - the pre-push hook and `work_tickets.py push` name the destination
      (`public_check.py --remote`), and its gate is every commit that remote does not hold yet,
      so a commit fetched from another remote is checked on its way there;
    - a check for another remote than origin records no verdict, as its terms are not origin's;
    - a line naming no remote of the checkout is warned about, by its line;
  - `off:<label>  # reason`, which switches the public entries of that label off for this source;
  - `allow:<path> local-term:<n>  # reason`, which allows this list's term of line `<n>` in that
    file, on any line, as no committed entry may say where a private term sits.
  - It is never checked in ([pub-005](src/skills/work-model/references/rules.md#pub-005-private-terms-stay-local)): the check refuses to run while git tracks it, naming `git rm --cached`;
    `scripts/setup.sh` and `setup.ps1` add it to the source's `.gitignore`.
- One se version per check ([pub-007](src/skills/work-model/references/rules.md#pub-007-one-se-version-per-check)): every verdict names the se commit that ran it, and a repository that
  pins se (`[components.se]` in its `se.toml`, [Modules](docs/modules.md#modules)) is refused with
  exit code 2 when the running se is not at that pin: another commit than its `ref`, or a version
  outside its `version` range or none readable, naming both; `scripts/se_modules.py sync` brings
  the clone there.
- False positives, each with its reason:
  - an entry in `.public-check-allow`, whose header owns their format and rules, for one harmless
    finding: a line, a file, a commit, or a text keyed by its digest,
    `<path> <label> sha256:<digest>`, which `--digests` prints;
  - an `allow:<path> local-term:<n>` line in the local list, for one of its own terms;
  - an `off:` line in the local list, for a public entry this source never treats as private.
- Hooks: run `scripts/setup.ps1` or `scripts/setup.sh` once per clone. They set `core.hooksPath` to
  `.githooks`: pre-commit checks the staged content and then runs the project's own
  [commit checks](docs/settings.md#commit-checks) on the staged tree, commit-msg the message and
  identity, pre-push every pushed commit the destination remote does not hold yet.
  - They also set the merge driver of generated files, and post-merge regenerates them after a
    merge (the guidance note generated-files-are-marked, "The merge").
  - A repository that uses se as a module runs `scripts/setup.ps1 -Repo <path>` (or
    `scripts/setup.sh <path>`) and so runs se's check without copying it.
  - A commit already published, such as main's merged into a branch, was gated where it was
    pushed and by CI's gate, so a push gates only its own.
  - They also set the clone's commit identity as `work_tickets.py sync` does
    (`work_tickets.py identity`), so its first commit already carries it.
  - A session's start (`scripts/bootstrap.sh --hook`) sets `core.hooksPath` the same way where it
    is unset, so a fresh clone's first commit already runs the check; a set one stays
    (`scripts/se_start.py start-hooks`).
- Pushes of the integration branch: pre-push and `work_tickets.py push` also need the verdicts the
  [work model](src/skills/work-model/SKILL.md#integration-branch) names.
- By hand: `uv run python scripts/public_check.py --repo <path>` (`--help` for the options).
- History already pushed that the commit gates refuse is rewritten once, on a fresh clone, by
  `scripts/rewrite_history.py --repo <clone>`, whose docstring owns what it changes; it pushes
  nothing.

Never bypass the hooks: [pub-006](src/skills/work-model/references/rules.md#pub-006-never-bypass-the-hooks).
