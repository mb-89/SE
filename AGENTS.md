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

- Each agent and skill is written once, in `src/agents/<name>.md` and `src/skills/<name>/`. Front
  matter keys prefixed `copilot.` or `claude.` go only into that host's layout.
- `uv run python scripts/se_plugin.py build` generates everything else from it: the Copilot layout
  (`.github/agents/`, `.github/skills/`) and the Claude Code plugin (`agents/`, `skills/`,
  `.claude-plugin/`). Never edit those by hand; `tests/test_se_plugin.py` checks they match.
- The outside skills a role relies on are one list, `se.toml` `[roles.<role>] skills`, never an
  agent's own front matter.
  - Each entry is `<plugin>@<marketplace>:<skill>`; a skill Claude Code ships loads by itself and
    is not listed.
  - The build preloads it into that agent's `skills` field where the host reads one (Claude Code;
    Copilot's agents have none).
  - The start greeting names an entry the session lacks
    ([README "Start and refresh"](README.md#start-and-refresh)).
- Every pytest run builds them first (`tests/conftest.py`, naming each file it wrote), so no suite
  tests stale layouts and nobody runs the build by hand before it; commit what it wrote.
- Installing SE is the README's [Install](README.md#install).

## Tests

- Focused: `uv run pytest -q tests/<file>.py` (add `-k <name>` for one test), the tests of what changed.
  - A change to Markdown the docs build publishes (`docs.md` and every note it lists) also runs
    `tests/test_docs.py`, whose build fails on obs's lints, a paragraph over five lines among them.
  - A change to `.github/workflows/check.yml` also runs `tests/test_public_check.py`, which holds
    the workflow's jobs and their order, beside the tests of the steps it changed (such as
    `tests/test_kern.py` for kern's, `tests/test_pr_issues.py` for the issue rule's).
- kern, the Go core under `kern/`: `cd kern && go vet ./... && go test ./...`. Its tests are
  declared beside the suite, `se.toml` `[tests.beside.kern]`, so the complete suite runs them too
  ([kern/README.md "Tests"](kern/README.md#tests)).
  - The `check` job vets kern in its own step and fails where `gofmt -l` lists one of its files;
    the job `kern-platforms` runs its vet and tests, with the tests of SE's start and hook scripts,
    on Windows and macOS, and on Windows those of `setup.ps1` (`tests/test_public_check.py -k
    powershell`).
- SE's Go components under `components/`: `cd components && go vet ./... && go test ./...`, declared
  beside the suite as `se.toml` `[tests.beside.go-components]`; their agreement test holds the Go fleet
  and retro-due components to the Python paths ([components/README.md](components/README.md#tests)).
- Complete: `uv run pytest -q` and kern's tests, declared with their time budgets in `se.toml`
  `[tests]`; `integrate` runs both against them, and `work_tickets.py suite --worktree <checkout>`
  runs them the same way ([README "Test budget"](README.md#test-budget)).
- Repository hygiene: `uv run python scripts/hygiene.py` checks SE's own checkout through git's real
  door, a step of the `check` job, not a test; its logic is unit-tested on the fake, each check
  failing on a fixture (`tests/test_repository.py`, `tests/test_references.py`).
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
    (`scripts/git_door.py`, `kern/git`).
  - Behind the door, `tests/conftest.py` refuses real git to every test outside its `REAL_GIT`
    list, and to the child processes it starts: only the contract suite, `tests/test_git_door.py`.
    A test that reaches real git without the fake fails, naming the command.
  - It also fails where SE's checkout fails its public check, with SE's own line of history
    ([Public safety](#public-safety)).
- Dangling references: the same command fails where the agents, the skills (the rule book among
  them), README.md or AGENTS.md name what the repository lacks.
  - A link to a missing file, a missing repository path in code (`scripts/…`, `src/…`, `tests/…`,
    `.github/…`), or a script subcommand its argument parser does not define.
  - `scripts/references.py` owns what counts; the issue-filing commands call it too
    ([Issues](src/skills/work-model/SKILL.md#issues)).
- Fixes: `uv run python scripts/work_tickets.py format` writes what the `check` job's generated
  checks refuse, the layouts (`se_plugin.py check`) and the README's command reference with its
  components' declarations (`work_tickets.py docs --check`); SE runs no code formatter or linter,
  and its other checks have no fix to apply.
- Test environment: none to load; `tests/conftest.py` clears the runner's variables (`CI`,
  `SE_CLOUD_AGENT`, every `GITHUB_*`) for the session, and a test that needs one sets it. Where uv warns that it cannot verify TLS behind a proxy, set
  `UV_SYSTEM_CERTS=1` in that shell.

## Public safety

The rules are the rule book's [`pub` section](src/skills/work-model/references/rules.md#pub-publishing-and-security); this
section owns the check that enforces them.

- Publishable at any time: [pub-001](src/skills/work-model/references/rules.md#pub-001-publishable-at-any-time). Use generic names
  (`<name>`, `alice`, `example.com`).
- A generic commit identity: [pub-002](src/skills/work-model/references/rules.md#pub-002-a-generic-commit-identity).

`scripts/public_check.py` enforces the rule on tracked file names and contents (binary files as bytes),
commit messages and author and committer identities. It prints locations and pattern labels, never the
matched text; exit code 0 passed, 1 hits, 2 setup error.

- Tracker references in commit messages,
  [pub-004](src/skills/work-model/references/rules.md#pub-004-no-tracker-references-in-commit-messages): the commit
  gates (`--message-file`, and the commits of a `--range`, as the hooks and `integrate` pass it)
  refuse them and, as they name nothing private, print the reference with its remedy. A full check
  leaves history already pushed alone; a commit already published passes by its reasoned message
  entry in `.public-check-allow`.
- Attribution trailers in commit messages,
  [pub-003](src/skills/work-model/references/rules.md#pub-003-no-attribution-trailers): the commit gates refuse a `Co-Authored-By:` or `Claude-Session:` line in any case, naming the commit and
  the remedy, reword before pushing. A full check leaves history already pushed alone.
  - Every author is refused, the owner included; a co-author line's hit also names the editor
    setting that writes it ([README "Install"](README.md#install)).
- CI: the job `check` of `.github/workflows/check.yml` runs the commit gates of a `--range` over
  the commits of every pull request and of every push to `main`, so a push the hooks did not see
  fails there; `check` is the check `main`'s ruleset requires.
  - The same job runs every other check an integration runs: `se_plugin.py check`,
    `work_tickets.py docs --check`, `hygiene.py`, `field-report --check` of a pull request's
    description against its work issue where it carries a report (a landing pull request's, from
    the work pull request it links, README [Landing on main](README.md#landing-on-main)), and
    `work_tickets.py suite` in budget.
  - On a pull request it also runs `pr_issues.py`, the work model's rule that the description
    names an open work issue ([Integration branch](src/skills/work-model/SKILL.md#integration-branch)).
- A `--range` on a shallow clone that reaches beyond the fetched history is refused with exit code
  2, naming `git fetch --unshallow`, so a gate never passes over commits it cannot see.
- The project identity ([pub-002](src/skills/work-model/references/rules.md#pub-002-a-generic-commit-identity)) in the commit
  gates of a `--range`: where the project sets an `identity`
  (or the machine a `public_identity`, which wins), a commit whose author or committer differs is
  refused, naming the commit, the identity found (redacted) and the remedy. A full check leaves
  history already pushed alone.
  - GitHub's web-flow identity (`GitHub`, `noreply` at `github.com`), the committer of a commit
    made on GitHub, passes as committer, never as author.
  - On such a commit, the author may be the account that owns `origin` on `github.com`, by its
    `users.noreply.github.com` address: the squash merge of a pull request into `main`. Every
    other account stays foreign.
  - A commit already published passes by its reasoned commit entry in `.public-check-allow`.
- The public list, `scripts/public-check-terms.toml`: the generic patterns every source is checked
  against, read from the se module the check runs from: user profile paths (`X:\Users\<name>`,
  `/home/<name>`, `/Users/<name>`), e-mail addresses other than `*@users.noreply.github.com` and
  `example.*`, enterprise GitHub hosts (GitHub Enterprise Cloud subdomains), machine names in UNC
  paths.
  - The fixed addresses services write into commits themselves, `noreply` at `github.com` and at
    `anthropic.com`, name no person and pass.
- The local list, `.public-check.local` at the root of each source (a repository or a vault), for
  terms that must never be written down here. Without it the check warns and runs the public list
  only, as on a public CI host. `#` starts a comment line; every other line is one of
  - a case-insensitive regex, a term this source keeps private; hits name only its line number;
  - `off:<label>  # reason`, which switches the public entries of that label off for this source.
  - It is never checked in ([pub-005](src/skills/work-model/references/rules.md#pub-005-private-terms-stay-local)): the check refuses to run while git tracks it, naming `git rm --cached`;
    `scripts/setup.sh` and `setup.ps1` add it to the source's `.gitignore`.
- The machine-level list (`~/.se/private-terms.txt`, `SE_PRIVATE_TERMS`) is retired: while one is
  configured, the check stops and names where its terms go, `<source>/.public-check.local`.
- One se version per check ([pub-007](src/skills/work-model/references/rules.md#pub-007-one-se-version-per-check)): every verdict names the se commit that ran it, and a repository that
  pins se (`[modules.se]` in its `se.toml`, [README "Modules"](README.md#modules)) is refused with
  exit code 2 when the running se is not at that pin: another commit than its `ref`, or a version
  outside its `version` range or none readable, naming both; `scripts/se_modules.py sync` brings
  the clone there.
- False positives: a reasoned entry in `.public-check-allow`, whose header owns their format and
  rules, for one harmless finding (a line, a file, a commit); an `off:` line in the local list for a
  public entry this source never treats as private.
- Hooks: run `scripts/setup.ps1` or `scripts/setup.sh` once per clone. They set `core.hooksPath` to
  `.githooks`: pre-commit checks the staged content, commit-msg the message and identity, pre-push
  every pushed commit. A repository that uses se as a module runs `scripts/setup.ps1 -Repo <path>`
  (or `scripts/setup.sh <path>`) and so runs se's check without copying it.
  - They also set the clone's commit identity as `work_tickets.py sync` does
    (`work_tickets.py identity`), so its first commit already carries it.
- Pushes of the integration branch: pre-push and `work_tickets.py push` also need the verdicts the
  [work model](src/skills/work-model/SKILL.md#integration-branch) names.
- By hand: `uv run python scripts/public_check.py --repo <path>` (`--help` for the options).
- History already pushed that the commit gates refuse is rewritten once, on a fresh clone, by
  `scripts/rewrite_history.py --repo <clone>`, whose docstring owns what it changes; it pushes
  nothing.

Never bypass the hooks: [pub-006](src/skills/work-model/references/rules.md#pub-006-never-bypass-the-hooks).
