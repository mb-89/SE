# se: systematic engineering

A process plugin for AI agents. Its main agent, **SE**, is the one a person talks to; its sub-agents
are the integrator, the worker and the reviewer. With them come their skills, issue templates and the scripts they
call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Install

One step per place. What each agent does is in its own file in [src/agents/](src/agents/).

| Place | Install | Choose SE | Check that it loaded |
| --- | --- | --- | --- |
| Claude Code | `claude plugin install se --marketplace mb-89/SE` | `claude --agent se:se`, or `"agent": "se:se"` in a project's `.claude/settings.json` | `claude plugin list` shows `se@se`; `/agents` lists `se:se`, `se:integrator`, `se:reviewer` and `se:worker` |
| Claude Code cloud (claude.ai/code) | the environment's [setup script](#claude-code-cloud) | each session's first prompt ([below](#claude-code-cloud)) | `claude plugin list` shows `se@skills-dir`; ask the session which `se:` agents and skills it has: `se:se`, `se:integrator`, `se:reviewer`, `se:worker`, `se:catch-up`, `se:decision`, `se:work-model` |
| GitHub Copilot in VS Code, in se's own checkout | `git clone https://github.com/mb-89/SE` and open it: VS Code reads its `.github/agents/` and `.github/skills/` | pick `se` in the Agent dropdown of the Chat view | the dropdown lists `se`, `integrator`, `reviewer` and `worker`; **Configure Skills** lists `catch-up`, `decision` and `work-model` |
| GitHub Copilot in VS Code, every repository | **Chat: Install Plugin from Source** with `https://github.com/mb-89/SE` (agent plugins, `chat.plugins.enabled`); or copy `.github/agents/*.agent.md` to `~/.copilot/agents/` and `.github/skills/*` to `~/.copilot/skills/` | as above | as above |

SE's skills read files in the plugin's folder and run its scripts with `uv run python`, and that
folder is outside your project. Claude Code asks you to allow this the first time. A headless
`claude -p` session cannot ask, so it refuses them unless you allow them in advance, for example
`--allowedTools Read Glob Grep Write Edit "Bash(uv run python:*)"`.

Commits carry no co-author lines: in VS Code, set `git.addAICoAuthor` to `off`
([VS Code 1.110 release notes](https://code.visualstudio.com/updates/v1_110)), as the
[public check](AGENTS.md#public-safety) refuses a `Co-authored-by` line in every pushed commit.

**Everything else arrives by itself.** At the first start SE runs
[scripts/bootstrap.sh](scripts/bootstrap.sh) (Claude Code runs it at every session start; it is quiet
when nothing is missing): it installs `uv` into the user's home, Python 3.11 or newer through `uv`,
and the project's [modules](#modules).

The one tool it cannot install without admin rights is `git`; it then names the one line to run. An
interrupted first start finishes when run again.

### Claude Code cloud

Marketplace plugins do not load in a cloud session; a plugin cloned into `~/.claude/skills/` does
(it shows as `se@skills-dir`). Remove the environment's own SE plugin, if it has one (a
`CLAUDE_CODE_PLUGIN_DIRS` naming another plugin `se`), so the two do not collide: while it is set,
the other plugin wins and `claude --agent se:se` stops with `--agent 'se:se' not found`.

The environment's setup script, all of it; it runs before Claude starts, each time a container is
built, touches no repository and holds no secret:

```bash
rm -rf ~/.claude/skills/se
git clone --depth 1 https://github.com/mb-89/SE ~/.claude/skills/se || echo "SE: clone failed, this session starts without SE" >&2
```

It replaces any older SE line (a clone into `/opt/se` that runs `src/build.sh`). A failed clone
starts the session without SE instead of stopping it.

A cloud session takes no `--agent` flag, `create_session` takes no agent, and an `agent` key in the
repository's `.claude/settings.json` gives every session of that repository SE's instructions,
workers included. So each session's first prompt names its role's file, `<se>` being
`~/.claude/skills/se`:

- SE: `Act as the se agent defined in <se>/.github/agents/se.agent.md.`
- Worker and integrator: the session prompt the work model's
  [Without gh](src/skills/work-model/SKILL.md#without-gh) names.
- Reviewer, started by SE on "review PR #n": the line
  `Act as the reviewer agent defined in <se>/.github/agents/reviewer.agent.md.`, then the pull
  request, its repository and SE's session, one per line.

The greeting needs no permission rule: the plugin's start hook hands it over, and SE opens its
first message with it. A session whose permission mode asks before commands, and that no one
watches, needs SE's scripts and files allowed in the repository's `.claude/settings.json`:
`"permissions": {"allow": ["Bash(uv run python:*)", "Read(~/.claude/skills/se/**)"]}`.

## Start and refresh

SE's first message is its greeting, for example `SE 1.2.0 started: 3 skills, 5 rules, 2 sub-agents.
Documentation: <docs_url>`. Under it, and only then, one line per module or SE itself with a newer
version, and the refresh command. [scripts/se_start.py](scripts/se_start.py) implements this
section:

```sh
uv run python <se>/scripts/se_start.py status [--greeting]
uv run python <se>/scripts/se_start.py check
uv run python <se>/scripts/se_start.py refresh
```

- Where it runs: in Claude Code, the plugin's start hook (`bootstrap.sh --hook`) shows the greeting
  to the person and hands it to the session, together with SE's root (`SE root: <path>`), where the
  skills find SE's scripts; elsewhere SE's [instructions](src/agents/se.md) run `status --greeting`
  first.
- The counts are what loaded: the skills and agents of the plugin's layout (every agent but SE is a
  sub-agent) and the rules the [public check](AGENTS.md#public-safety) enforces.
- `status` reads only the disk and the last update check, cached in `~/.se/start-check.json`
  (`--cache`, or `SE_START_CACHE`), so it answers within a second. A check older than an hour, or
  none, starts `check` in the background; the next start shows its result.
- `check` reads the version tags of SE's own remote and of every module's remote, once each and in
  parallel. A failed read is named in the greeting with its remote, its cause and the command to see
  it; the greeting still appears.
- What is due: the highest version a module's `version` range admits above its locked one, and for
  SE the highest version of its major. A newer version outside the range is shown apart and never
  applied.
- A local path (`[paths]` of `~/.se/local.toml`, SE's own under the name `se`) is reported as local
  and never touched. A module pinned by commit is reported, and only the module command's
  [`update`](#commands) moves it.
- `refresh` takes no choices. It checks now, then moves each due item: it checks the new version
  out into a temporary worktree first, checks that it starts (its `se.toml` names that version; for
  SE, `status` runs there) and only then switches. A module's lock moves in `se.lock`; commit it.
- SE itself moves the way it was [installed](#install):
  - a git checkout, including the cloud's setup-script clone, is fast-forwarded, or checked out
    where it is detached;
  - an installed Claude Code plugin is updated with `claude plugin update`, then `status` runs in
    the new install; where it does not start, Claude Code's record of the plugin is put back to the
    old install. Restart Claude Code to load the new one;
  - any other copy (a Copilot copy) is checked against the `repository` of its plugin manifest;
    VS Code alone updates it and has no command line for it, so `refresh` names the command to run
    there.
- What fails stays at the version in use, with the cause and the command to try again. An se
  checkout with local changes or its own commits is a development checkout and is left alone. Run
  twice, the second `refresh` moves nothing.

## Documentation

se's documentation is one HTML file, published at the `docs_url` of `se.toml` `[project]`
(<https://mb-89.github.io/SE/>), the one setting that names it. `docs.md` is its manifest: it lists
se's notes as chapters and restates none of them. The [obs](https://github.com/mb-89/obs) module
(`[modules.obs]` in `se.toml`) builds it:

```sh
uv run python scripts/build_docs.py --destination <file outside the repository>.html
```

Any obs warning fails the build, so a broken link, a missing note or a paragraph longer than obs's
default limit fails it. The suite runs the build (`tests/test_docs.py`),
and the workflow `.github/workflows/docs.yml` builds and publishes it to GitHub Pages on each push
to `main`; a failed build publishes nothing, so the previous artifact stays.

The Timeline, <https://mb-89.github.io/SE/timeline.html>, builds itself from the issues and
releases of the repositories in `se.toml` `[timeline]`; [scripts/timeline.py](scripts/timeline.py)
owns what shows where, and the same workflow rebuilds it hourly and on each issue event.

## Modules

A repository pulls its dependencies (se itself, format tools, styles, other repositories) as modules
pinned to commits or to semantic version ranges, from any Git host. `scripts/se_modules.py`
implements this section; its invocation is in [Commands](#commands).

### `se.toml`

The consuming repository declares its modules in `se.toml` at its root:

```toml
[modules.obs]
url = "https://github.com/<owner>/obs.git"   # public form of the clone URL
ref = "<40-hex commit SHA>"                  # the pin
path = "skills"                              # optional: the part of the module that is used

[modules.style]
url = "https://github.com/<owner>/style.git"
version = "^1.4"                             # in place of ref: a semver range of the module's tags
```

- `url`: the clone URL in its public form. Machine-specific forms (mirrors, credentials) belong in
  the machine-local file below, never here.
- `ref`: the pin, a full commit SHA. Any commit on the module's `main` can be pinned, not only
  releases; `update` moves it.
- `version`: in place of `ref`, a semantic version range of the module's release tags
  `vMAJOR.MINOR.PATCH` ([Project settings](#project-settings) says how a module releases):
  `^1.4` (1.4.0 up to 2.0.0), `~1.4.2` (up to 1.5.0), `1.4` (any 1.4.x) or `1.4.2` (exactly).
  A module pins one of `ref` and `version`.
- `se.lock`: next to `se.toml`, it records the highest tag matching each `version` range, with its
  version and commit; `sync` and `update` write it and the repository commits it.
- `path`: optional relative directory inside the module; without it the whole module is used.
- Module names use letters, digits, `.`, `_` and `-`. Other keys are errors.
- The module named `se` is se itself; its pin is the se the [public check](AGENTS.md#public-safety)
  must run: exactly its `ref`, or any se whose `se.toml` version its `version` range admits.

A common repository declares only modules that are public. Work-only modules on private hosts are
declared the same way, in a work repository that consumes the common ones; a common repository never
names them.

### Project settings

`se.toml` also holds every project setting owned by se. Each se tool validates only the settings it
owns.

```toml
[project]
authored_content = ["README.md", "docs/**/*.md"]
identity = "mb <mb>"
integration_branch = "main"
public_check = true
release = "workflow"
release_build = ["uv", "run", "python", "scripts/se_plugin.py", "build"]
version = "1.4.2"
```

`identity = "Name <email>"` is the project's commit identity. `work_tickets.py sync` writes it into
the checkout's git config (`user.name`, `user.email`), so every later commit and merge there
carries it, unless the machine sets `public_identity`, which wins. Unset, sync leaves the checkout's
identity as it is.

`work_tickets.py push` and its release commit with that identity explicitly, whatever the
checkout's configuration or environment says, and refuse without one. The
[public check](AGENTS.md#public-safety) refuses a commit not yet pushed whose author or committer
differs from it.

`integration_branch` is owned by the
[work model](src/skills/work-model/SKILL.md#integration-branch).

`public_check` makes `work_tickets.py integrate` run se's
[public check](AGENTS.md#public-safety) on the merged tree and every merged commit before it pushes
its landing branch; on a failure it pushes nothing, leaves the integration branch as it was and
escalates. `work_tickets.py push` runs its push gate first.

Default `true`, so a project that never set it is still checked; a project without a public check
sets `public_check = false`, and `push` then prints one line saying the check is off and where to
turn it on.

`version = "MAJOR.MINOR.PATCH"` is the project's one semantic version, published as the git tag
`vMAJOR.MINOR.PATCH` on its integration branch; consumers pin ranges of it
([`se.toml`](#setoml)). Nobody types it after the first: `integrate` releases, on its landing
branch, what was integrated since origin and the last tag, as `work_tickets.py push` of the
integration branch does.

Each integration is a first-parent commit whose message starts `Integrate <branch>` and states its
kind in the trailer `Release-kind: major|minor|patch`: the merge `integrate` builds, and on the
integration branch the squash commit it lands as ([Landing on main](#landing-on-main)).
`integrate` writes it, and `work_tickets.py release-trailer` prints it:

- on a re-integration (an integration `Integrate <branch>` of the same branch is already on the
  integration branch) the field report's "Re-integration kind", `patch` unless it says otherwise;
- else the field report's "Release kind", which the
  [work model](src/skills/work-model/SKILL.md#release-kind) owns; a missing or unknown kind is
  refused before anything is merged. The branch prefix only proposes it (`field-report --draft`):
  `feature` (or `feat`) `minor`; `fix`, `perf`, `chore` or `docs` `patch`; `major` where the work
  issue's "Package kind" says "breaking".

An integration without the trailer is refused, naming the merge and the remedy; push never guesses.

One push bumps once, by its integrations' highest kind: it rewrites only `version`, runs
`release_build` where set, commits `Release v<new>` with what that regenerated, tags it and pushes
the tag with the branch.

A version without its tag yet is tagged as it is, which is how a project
starts versioning. Without `version` push releases nothing and says so; a malformed one is refused,
naming the file.

`release_build` is the command that regenerates what copies the version (se's plugin manifests:
`["uv", "run", "python", "scripts/se_plugin.py", "build"]`), an argument array run without a shell
from the project root. Where it fails, push restores `se.toml`, commits nothing and shows its output.

#### Landing on main

Every integration lands on the integration branch through a squash pull request, which se's `main`
requires: its ruleset allows no direct push, no force push and no deletion, keeps the history
linear, merges pull requests by squash only and requires the check `check`
([AGENTS.md "Public safety"](AGENTS.md#public-safety)). `work_tickets.py integrate <pull request>`
does all of it:

1. It merges the work branch into origin's newest integration branch on `land/<branch>` (the
   `Integrate <branch>` merge with its `Release-kind` trailer), runs the complete suite, the
   output regeneration, the project checks and the public check, and releases there.
2. It pushes `land/<branch>` and opens a pull request of it into the integration branch, or reuses
   the one still open from an earlier attempt.
   - Its title is the merge's title, `Integrate <branch>: <the first sentence of the work issue's
     Goal>`, never a commit's subject. Tracker references (pub-004's forms) are dropped from it,
     with an aside such as `(PR #<n>)` that holds one, and its punctuation tidied; without a
     usable Goal, or with fewer than two words left, it is `Integrate <branch>` alone.
   - Its description is always a link, never the report, so it fits GitHub's body limit and any
     tool argument whatever the report's size: `Refs <work issue>`, the work pull request, and the
     marker `<!-- se:field-report-in <n> -->`.
   - The check's field-report step reads that marker and checks the description of work pull
     request `<n>`, the field report, against its work issue
     ([AGENTS.md "Public safety"](AGENTS.md#public-safety)).
3. It waits for the check `check` on the landing head, polling every 30 s for up to an hour; a
   conclusion other than success merges nothing and escalates.
4. It squash-merges at exactly that head with the merge's message as the commit title and message,
   so the squash commit carries `Integrate <branch>: <goal>` and the `Release-kind` trailer, and
   no ` (#<number>)` or `Co-authored-by:` line GitHub's defaults would add. Where origin's
   integration branch moved while it waited, it merges nothing: integrate again.
5. It reads the merge back: the pull request merged at that commit, which is origin's integration
   branch, on the base it tested and with the tree its checks passed.
6. It closes the work pull request with a line naming the landing one, closes the work issue and
   cleans up.

Steps 2 to 4 and the GitHub half of step 6 are one plan: numbered GitHub steps, each a tool of the
host's GitHub tools (the GitHub MCP server's names) with its arguments, and later steps taking what
earlier ones give (`<pull number from step 1>`). Both paths run that one plan:

- **Where `gh` is signed in**, `integrate` runs it itself through one door, the class `GitHub` in
  `work_tickets.py` (`gh api`), which the tests replace with a fake.
- **Where it is not** (Claude's cloud, where `gh` has no account), `integrate` hands it off:
  - `integrate <pull request> --pr-description <file> --issue-body <file> --branch <head branch>`,
    from what the session's GitHub tools read, does step 1, pushes `land/<branch>`, keeps what the
    read-back needs in `.se/handoff/` and prints the plan.
  - The plan: `create_pull_request` (or `update_pull_request` on the one `list_pull_requests`
    finds open), `pull_request_read` `get_check_runs` until `check` passes, and
    `merge_pull_request` with `merge_method` squash, the exact title and message and
    `expectedHeadSha` at the landing head;
  - the session runs those steps with its GitHub tools;
  - `integrate --read-back <branch> --landing-pull <number> --check-run <url>` then reads step 5
    back through `git fetch` alone (origin's integration branch one commit on the tested base,
    with the tested tree), finishes everything local of step 6 and prints its close-out plan:
    the work pull request's comment and close, and the work issue's comment, label and close.
- A failure on the way prints the escalation as a plan too: the comment and the `escalated`
  label.

The same split holds for `refs request` and `refs apply` (the work model's
[Steps only the person approves](src/skills/work-model/SKILL.md#steps-only-the-person-approves)):
without a signed-in `gh` each prints its comment, dispatch and run steps, and `--read-back` checks
the refs through `git ls-remote` and prints the rest.

The squash commit carries the release's `se.toml` version, so the release workflow tags it and the
docs workflow publishes it, as both run on every push to `main`. GitHub commits it for the merging
account (web-flow committer, the account's `users.noreply.github.com` author), which the identity
gate and a public mirror's guard pass for the account that owns the repository.

#### Release tags

`release = "workflow"` hands the tags to se's release workflow, for hosts that may push branches but
not tags (Claude's cloud sessions).

- `push` still bumps and commits the version, pushes the branch only and names the workflow; it
  reads the released versions from origin's tags (`git ls-remote --tags`), never from local ones,
  so a version without its tag on origin is left for the workflow, not bumped.
- On each push to the integration branch the workflow walks its first-parent history and tags
  every version `se.toml` carried without a tag, `v<version>` on the first commit that carried it,
  so a missed release is backfilled; a second run changes nothing.
- An existing tag never moves: where it names another commit, the run warns and leaves it. The one
  exception is the major tag `v<major>` (`v2`) of the version `se.toml` carries: each run creates
  or force-updates it to the newest release of that major, so others follow se's reusable workflows
  by major version. An older major's tag is its own releases' to push; a run never creates or moves
  it.
- Each tag is pushed on its own: a refused one fails the run with one line naming the tag, origin's
  reason and the remedy (the repository's tag rulesets), and the others still land.
- Without `release`, `push` pushes the tags itself; another value is refused, naming the file.

A repository turns it on with `release = "workflow"` and a copy of se's own
[`.github/workflows/release-tag.yml`](.github/workflows/release-tag.yml), changed only in
`branches` to name its integration branch (se's names `main`), so that worker branches run nothing,
and in `uses`, which calls `mb-89/SE/.github/workflows/release.yml@v<major>`.

Other repositories reference se's reusable workflows and actions at `@v<major>`, never at a branch,
so a breaking change reaches them only with the major they choose.

### Fleet check

```toml
[fleet]
lease_hours = 3
```

`work_tickets.py fleet-check` lists what is stuck or stray, each with its remedy (its `--help`
names the kinds), and says `healthy` otherwise; it only reads.

`lease_hours` is how long in-progress work may go without a push to its branch, built in 3. The
time of a push is the committer time of the branch's tip, as git fetches it.

Blocks are the `## Blocked by` section of each open issue's body, where `work_tickets.py block`
writes them.

Without gh it prints its GitHub plan; the session runs it with its GitHub tools, saves the three
lists as JSON and passes them as `--open-issues`, `--closed-issues` and `--pulls`.

### Stop hook

```toml
[stop]
refusals = 5
```

The plugin hands every `Stop` and `SubagentStop` to `work_tickets.py stop-check`, so a worker's turn
ends only with its work issue delivered:

- Where it refuses: a checkout whose ticket queue (`.se/work/`) is for a work issue (intake's
  snapshot, or what was recorded as read of it), on a branch other than the integration branch.
- What it refuses: the stop, while the branch has no open pull request whose description carries a
  field report that passes `field-report --check` at the branch tip. The refusal names what is
  missing and the commands that deliver.
- `refusals` is how often in a row it refuses, built in 5; then it lets the turn end and says so,
  and counts afresh. A passing stop resets the count.
- A `SubagentStop` is judged only for a worker sub-agent (`worker`, `se:worker`).
- Anywhere else (SE's own session, a person's session) it never refuses. Where it cannot judge it
  lets the turn end and says why: advice fails open.
- Without gh it judges by the answer file `.se/work/pull-request.json`, which
  `stop-check --pull <number> --pr-description <file>` writes from the pull request the session's
  GitHub tools opened; without either, it cannot judge.

### Test budget

```toml
[tests]
command = ["uv", "run", "pytest", "-q"]
target_seconds = 60
limit_seconds = 120
setup = ["uv", "sync"] # optional
tier = "tests.tiers:tier" # optional
```

- `command`: the project's complete suite, an argument array run without a shell from the project
  root. `work_tickets.py integrate` runs it at every integration, and `work_tickets.py suite` runs
  it the same way for a worker's before-and-after times.
- `setup`: optional and of the same form; it installs the test dependencies (packages, browsers)
  and runs first. The gate prints its time and its last lines apart, and that time does not count
  against the budget. A failing setup stops the run before the suite, naming the command and its
  output.
- `target_seconds` (default 60): above it the gate warns.
- `limit_seconds` (default 120): above it the gate refuses the integration, naming the test result
  (passed, with its counts), the time, the limit, the slowest tests and the remedy: rerun once on
  an idle host, as a loaded host can push a passing suite over the limit, and if it is still over,
  make those tests faster.

The gate measures the suite's wall time and prints it with the last lines of the suite's own output
and the ten slowest tests (`suite --slowest N` lists N). Failed tests exit with code 1, a passing
suite over the limit with code 3. How tests are written is owned by the
[work model](src/skills/work-model/SKILL.md#tests).

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

### Machine-local `~/.se/local.toml`

`public_identity = "Name <email>"` pins the author and committer identity allowed in every
commit pushed to a configured public mirror. If it is omitted, `integrate` uses the project's
`identity`, else the selected checkout's configured Git identity. When it is set, `sync` writes it into the checkout's git
config in place of the project's `identity` ([Project settings](#project-settings)).

Each machine may adapt modules without touching tracked files. se only reads this file; it never
writes it, and nothing from it is written into `se.toml`.

The file is shared with `work_tickets.py`. `se_modules.py` owns `[paths]` and `[urls]`;
`work_tickets.py` owns the top-level `integrator_session`, `public_identity` and `commit_trailer`
settings, and the `[trackers]`, `[worktree_roots]`, `[repos]`, and `[mirrors]` tables. Each tool ignores sections
owned by the other.

```toml
[paths]
obs = "~/src/obs"                     # use this checkout of module obs if the directory exists

[urls]
"https://github.com/" = "https://mirror.example.com/github/"   # prefix rewrite, longest wins
```

- `[paths]`: a local checkout per module name. If the directory exists, the module comes from it as
  it is (working tree, any commit, no git step) and is never updated. If the directory is missing,
  the pin is used. Relative paths are relative to the file, `~` is expanded.
- A local checkout's version: `sync` and `status` report the version its `se.toml` sets, and
  whether the module's `version` range admits it. A malformed version, or none where the module pins
  a range, is an error naming that file.
- `[urls]`: prefix rewrites applied to `url` before any git step, for example a private mirror of a
  public host. The longest matching prefix wins.

Work queue tracker, worktree and mirror settings are documented in the
[work model](src/skills/work-model/SKILL.md#what-the-project-provides), the `[outside]` table in its
[Outside issues](src/skills/work-model/SKILL.md#outside-issues).

### Commands

One invocation on every platform; a project copies it as it is into its `AGENTS.md`, with `<se>`
the path where se lives in the project (`.` in se itself):

```sh
uv run python <se>/scripts/se_modules.py sync [<name>...]
uv run python <se>/scripts/se_modules.py status [<name>...]
uv run python <se>/scripts/se_modules.py update <name> [--to <ref>]
uv run python <se>/scripts/se_modules.py update --all
uv run python <se>/scripts/se_modules.py path <name>
```

- `sync`: a module with an existing local path is used from there; any other is cloned or fetched into
  `.se/modules/<name>` and checked out (detached) at its pin. A `version` range without a lock entry
  that admits it is resolved and locked first; a locked one stays where it is until `update`. A clone with local changes is never
  overwritten. Consuming repositories ignore `.se/`.
- `status`: one line per module with its source (`local` or `pinned`), the directory it is used from,
  the pin and the drift. It never fetches. The drift is:
  - for a local path, the commits ahead of and behind the pin, uncommitted changes, or a pin the
    checkout does not have yet;
  - for a pinned module, whether the clone is at the pin and, for a `version` range, a newer
    matching tag the clone knows ("run update").
- `update`: fetches the module (through `.se/modules/<name>`, also when a local path is used),
  resolves the newest commit on its `main` (or `--to` a branch, tag or commit), rewrites only that
  `ref` in `se.toml`, prints the commits added (and dropped, if the pin moves back) and syncs. It
  does not commit; commit the new pin with the commit list.
  - A `version` range moves to its highest matching tag in `se.lock` instead (`--to` is refused
    there; change the range).
- `path`: prints the directory a module is used from (its `path` included), for tools that load it.
- `--root <dir>` names the repository (default: the nearest ancestor with `se.toml`); `--local <file>`
  reads another machine-local file than `~/.se/local.toml`.
- Git runs without prompts; credentials come from the machine's git setup.

## Work commands

`scripts/work_tickets.py` runs the [work model](src/skills/work-model/SKILL.md): its tickets, issues,
deliveries and integrations. Each command's `--help` names its arguments in full. The reference
below is generated from the script's command registry by
`uv run python scripts/work_tickets.py docs`; change a command there, never here.

<!-- generated by `work_tickets.py docs` from its command registry: begin -->
```text
work_tickets.py init --worktree WORKTREE
    initialize the ticket queue

work_tickets.py create --worktree WORKTREE --id ID --title TITLE [--acceptance ACCEPTANCE]
    create a ticket in todo

work_tickets.py move --worktree WORKTREE --id ID --to {todo,held,done}
    move a ticket between states

work_tickets.py status --worktree WORKTREE [--json] [--integration-target INTEGRATION_TARGET]
    report queue status

work_tickets.py review-note --worktree WORKTREE --note NOTE --disposition DISPOSITION
                            [--backlog-ref BACKLOG_REF]
    append a local note disposition

work_tickets.py close --worktree WORKTREE [--integration-target INTEGRATION_TARGET]
                      [--remove] [--json]
    check or close an integrated worktree

work_tickets.py intake --worktree WORKTREE (--issue ISSUE | --outside) [--repo REPO]
                       [--discovery] [--probe-root PROBE_ROOT]
    read the work issue with gh and write its tickets into todo

work_tickets.py probe --worktree WORKTREE --command PROBE_COMMAND --output OUTPUT
    append a command and output path to the discovery evidence index

work_tickets.py refresh --worktree WORKTREE [--issue ISSUE] [--repo REPO] [--json]
    re-read the work issue and its comments and report changes

work_tickets.py comments-read --worktree WORKTREE --count COUNT --newest NEWEST
    record the work issue's comments as read: their count and the newest one's id (intake records
    them; field-report --check and deliver refuse comments after it)

work_tickets.py body-read --worktree WORKTREE [--body-file FILE]
    record the work issue's body as read (intake records it; field-report --check and deliver refuse
    a body changed after it)

work_tickets.py field-report [--worktree WORKTREE] (--draft FILE | --check FILE)
                             [--issue-body FILE] [--comment-count N] [--newest-comment ID]
    draft or check the field report a pull request description carries, in the form of
    .github/pull_request_template.md

work_tickets.py escalate --worktree WORKTREE --issue ISSUE --file FILE [--repo REPO]
    comment a question on an issue and label it escalated

work_tickets.py file --worktree WORKTREE --title TITLE --body-file BODY_FILE [--blocked-by N]
                     [--label LABEL] [--repo REPO]
    for SE: file a work issue labelled work, ready and repo:<name>; with --blocked-by, ready only
    once its blockers are linked

work_tickets.py route --worktree WORKTREE [--title TITLE] [--type TYPE]
                      --routing-file ROUTING_FILE [--issue-title ISSUE_TITLE]
                      [--issue-body ISSUE_BODY] [--repo REPO]
                      issue
    for SE: route a checked outside issue as a work issue in one edit: retitle it to its branch
    name, label it work, ready and repo:<name>, and append the routing section with the handled
    record to its body

work_tickets.py backlog file --worktree WORKTREE --title TITLE --body-file BODY_FILE
                             [--repo REPO]
    file one backlog issue with both labels, creating backlogged where missing

work_tickets.py backlog list --worktree WORKTREE [--search SEARCH] [--repo REPO]
    list the open backlog issues, or those whose title or body matches --search

work_tickets.py refs request --worktree WORKTREE --triples-file TRIPLES_FILE [--repo REPO]
                             [--read-back] [--request-id REQUEST_ID] [--run-url RUN_URL]
                             [--conclusion CONCLUSION] [--log-file LOG_FILE]
                             issue
    for the integrator: post the triples on the issue, run ref-maintenance's dry run, post its
    output and label the issue escalated; prints the line for SE. Where gh is not signed in it
    prints these GitHub steps as a plan for the session's GitHub tools; --read-back then checks the
    refs and finishes

work_tickets.py refs apply --worktree WORKTREE [--repo REPO] [--comments-file COMMENTS_FILE]
                           [--read-back] [--run-url RUN_URL] [--conclusion CONCLUSION]
                           issue
    for SE, on the person's yes: run ref-maintenance for real with the triples the issue's newest
    request posted, read the refs back and post the result; prints the line for the integrator.
    Where gh is not signed in it prints these GitHub steps as a plan for the session's GitHub tools;
    --read-back then checks the refs and finishes

work_tickets.py sync --worktree WORKTREE
    merge the newest integration branch (se.toml project.integration_branch, default main) from
    origin, or locally without origin

work_tickets.py suite --worktree WORKTREE [--slowest N] [--compare REF] [--runs N]
    run se.toml's complete suite against its [tests] time budget, as integrate does; exit code 1
    when tests fail, 3 when they pass over the limit

work_tickets.py guard --worktree WORKTREE --branch BRANCH --pr-description FILE
    require the field report to name removed protected content, against origin/<integration branch>
    as sync fetched it (the local branch without origin)

work_tickets.py deliver --worktree WORKTREE [--integrator-session INTEGRATOR_SESSION]
    sync, check the field report, push, and create or update the pull request whose description
    carries it; files no issue

work_tickets.py push [--worktree WORKTREE] [branch]
    public check's push gate, then git push -u origin <branch>; retries a transient refusal once a
    minute, ten attempts; the integration branch needs a passing suite and public check recorded on
    the tree pushed

work_tickets.py verified [--worktree WORKTREE] remote_ref commit
    the pre-push hook's guard: refuse a push of <commit> to <remote ref> where the ref is the
    integration branch and no passing suite and public check are recorded on its tree; push runs the
    same check

work_tickets.py pr-body [--worktree WORKTREE] --issue-body ISSUE_BODY --issue-url ISSUE_URL
                        --field-report FILE
    print the pull request description deliver writes: Fixes <issue> where all its acceptance shows
    before the merge, else Refs <issue>, then the field report between its markers

work_tickets.py release-trailer [--worktree WORKTREE] --issue-body ISSUE_BODY
                                [--pr-description FILE] [--include-late REASON]
                                branch
    print the Release-kind trailer an integration merge of <branch> carries, from its field report's
    Release kind (a re-integration's from its Re-integration kind); push requires it

work_tickets.py integrate --worktree WORKTREE [--repo REPO] [--pr-description FILE]
                          [--issue-body FILE] [--branch BRANCH] [--read-back BRANCH]
                          [--landing-pull LANDING_PULL] [--check-run CHECK_RUN]
                          [--build-command BUILD_COMMAND] [--include-late REASON]
                          [--check-command JSON] [--check-command-temporary-directory]
                          [pull_request]
    validate the field report a pull request's description carries, merge it on land/<branch>, test,
    land it through a squash pull request once check passes, and close the work issue. Where gh is
    not signed in it pushes land/<branch> and prints the GitHub steps as a plan for the session's
    GitHub tools; --read-back <branch> then checks the landing through git and finishes the close-
    out

work_tickets.py config --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT]
                       [--integrator-session INTEGRATOR_SESSION]
    show the repository and the machine-local settings in effect

work_tickets.py start --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT]
                      [--no-create] [--cloud-agent CLOUD_AGENT]
                      issue
    start a ready work issue: worktree from the newest main, label in-progress

work_tickets.py block --worktree WORKTREE --by BLOCKER [--repo REPO] issue
    link an issue to a native blocker

work_tickets.py ready [--worktree WORKTREE] [--repo REPO] [--all-repos]
    list startable ready work issues

work_tickets.py capacity [--worktree WORKTREE] [--repo REPO] [--all-repos]
    show local worker capacity or cloud unlimited capacity

work_tickets.py queue [--worktree WORKTREE] [--repo REPO] [--all-repos]
    list delivered pull requests (open, to the integration branch, with a complete field report),
    escalations and startable work issues

work_tickets.py fleet-check [--worktree WORKTREE] [--repo REPO] [--json]
                            [--open-issues OPEN_ISSUES] [--closed-issues CLOSED_ISSUES]
                            [--pulls PULLS]
    list every stuck or stray piece of work, each with its issue, pull request and remedy: in-
    progress work without a branch or a push within the lease, a delivered pull request whose check
    failed or that conflicts, a branch of a closed issue, a block by an issue closed as not planned
    or by itself, an se-person issue and what it holds up; 'healthy' and exit code 0 when there is
    none, exit code 1 otherwise. It only reads. Without gh it prints its GitHub plan and takes the
    answers from files

work_tickets.py stop-check [--worktree WORKTREE] [--pull NUMBER] [--pr-description FILE]
    the plugin's Stop and SubagentStop hook: in a checkout whose ticket queue is for a work issue,
    refuse the turn's end while its branch has no open pull request whose description carries a
    field report that passes field-report --check at the branch tip, naming what is missing and the
    commands; at most [stop] refusals times in a row (se.toml, built in 5). Anywhere else, for a
    sub-agent that is no worker, and where it cannot judge (no gh and no recorded pull request) it
    lets the turn end. It reads the hook's JSON on stdin and answers the hook's JSON on stdout

work_tickets.py docs [--check]
    write the README's command reference from this registry; with --check, only refuse a README that
    differs
```
<!-- generated by `work_tickets.py docs`: end -->

`scripts/review.py` holds the review commands, which load `work_tickets.py` for its GitHub door.
`uv run python scripts/review.py brief <pull request> [--claims] [--json]` prints what a cold
reviewer starts from:

- the work issue the pull request names, with its comments;
- the diff against its base at the pull request's head commit, which it names;
- the check runs on that commit;
- the rule book at that commit.

It withholds the pull request's description (the field report) and its comments, because a
worker's own account misleads a reviewer most. `--claims` adds them under a heading that calls
them claims to check, never evidence. Without gh it prints its GitHub steps as a plan and reads
the answers from files ([Without gh](src/skills/work-model/SKILL.md#without-gh)).

`uv run python scripts/review.py file <pull request> --report <file>` keeps a reviewer's findings
out of the chat and out of the queue: it posts the review as one comment on the reviewed pull
request and files no issue
([wrk-007](src/skills/work-model/references/rules.md#wrk-007-one-piece-of-work-one-issue-no-command-files-issues-on-its-own)).
It reads the review report as JSON:

- `verdict`: `pass`, `pass with open points` or `decline`;
- `head`: the commit reviewed, the head the brief named;
- `acceptance`: each acceptance item of the work issue, `{"item", "evidence"}`;
- `findings`: each verified finding, `{"title", "evidence", "place", "blocking", "why"}`, empty
  where none was found; only damage blocks: the product made worse, or against what it is about;
- `clean`: the "checked and clean" list, what was examined and found sound.

There is no quota: a review without findings is a pass. What it refuses, writing nothing, is a
verdict without its evidence or one its findings contradict:

- a report with an unknown field, or without its "checked and clean" list;
- a finding without evidence, place or judgment;
- a pass or pass with open points with an acceptance item lacking evidence, or with a blocking
  finding (that is a decline);
- a pass with findings (that is a pass with open points), and a pass with open points without any;
- a decline without a blocking finding;
- a review of another commit than the pull request's head.

What each verdict writes besides the comment:

- **pass**: nothing; the change lands as is.
- **pass with open points**: the findings, as numbered open points, at the end of the work issue's
  "Changes after filing", marked with the head they passed. That head lands without them, so the
  issue stays open after the landing (`integrate` says so) and goes back to a worker on the same
  issue, whose next delivery delivers them.
- **decline**: the work issue is escalated one rank, to SE: a comment and the label `escalated`.
  The command prints the line the integrator sends SE, which re-scopes the issue or takes it to the
  owner.

On a pull request that is no longer open, the comment alone is written: it waits there for SE.
The comment opens with `<!-- se:review -->` and ends in a JSON block the retro reads. Without gh it
prints its reads as a plan, then, given the answers with `--pull <file> --issue <file>`, its
writes.

`scripts/retro.py` holds the retro commands, which load `work_tickets.py` for its GitHub door.
`uv run python scripts/retro.py collect <retro issue> [--out FILE] [--json]` is a retro's
mechanical half.

Its window is every work issue closed since the last closed retro issue (titled
`docs/retro-...` or labelled `retro`) closed, or the whole history where none has. Each issue comes
with the field report of the work pull request its landing pull request names
(`<!-- se:field-report-in <n> -->`). The draft holds:

- the sizes: closed, landed, duplicates, escalated, beside the previous retro's where its block is
  found;
- per landed issue the deliveries `integrate` refused (its `Integration stopped:` comments), its
  escalations (those, or the `escalated` label) and the suite time of its `Integrated in` comment;
- the field reports' Retro entries and "Not delivered" items, grouped;
- the rule checks, each broken one with what broke it: every landing pull request names a work
  issue open when it merged (`work-issue`), its `check` passed (`check`), no commit reached the
  integration branch outside a pull request (`outside-pr`), every closed work issue has a field
  report (`field-report`);
- the previous retro's findings, from its report's block, each with the work issues of the window
  that name it (`retro #<n> finding <k>`), its state (`closed` where one closed as completed) and
  whether the rule check it names broke again (recurred).

It ends in a JSON block (JSON is YAML too) under `<!-- se:retro-yaml -->`, which the next retro's
commands read. `--json` prints the block's data alone.

Without gh it prints the GitHub steps whose
answers are still missing, round by round, and reads the answers from the files the session saved
into `--answers <dir>` ([Without gh](src/skills/work-model/SKILL.md#without-gh)).

`uv run python scripts/retro.py file <retro issue> --draft FILE` files a judged retro. The judge
fills the draft's block:

- `findings`, each with `title` (five words or more), `body`, `class`, `home` (the file it
  changes), `controversial` with its `why`, and optionally `check` (a rule check);
- `classes`, each with `name` and `fix`;
- `went_well`, what went well.

It refuses, writing nothing, an incomplete judgment: a finding without one of those, a class
without a fix, a controversial finding without a why, a finding on the rule book, or on a check that
recurred, that is not controversial, nothing that went well.

It files no issue
([wrk-007](src/skills/work-model/references/rules.md#wrk-007-one-piece-of-work-one-issue-no-command-files-issues-on-its-own)):
it posts the report as the retro issue's closing comment and closes the issue. The report opens
with `<!-- se:retro-report -->`, then the facts and the block follow. It lists each finding,
numbered, with its class's fix, its home and its kind:

- `work`: SE bundles these into as few work issues as the work needs, each naming
  `retro #<n> finding <k>` for every finding it takes;
- `decision`: for the owner's decision list.

Without gh it prints the comment and the close as a plan.

`scripts/overhaul.py` holds the overhaul commands, which ask, rarely, whether the design is still
right. SE starts one and runs it as its issue says, `read`, the judgment, then `file`.

`uv run python scripts/overhaul.py new` files the overhaul issue, `docs/overhaul-<yyyymmdd>`
labelled `discovery` beside the work labels, with the body of
[the overhaul template](.github/ISSUE_TEMPLATE/overhaul.md), through `work_tickets.py file`'s
filing path (`file --label discovery`): once, so an open overhaul answers a second `new`.

`uv run python scripts/overhaul.py read <overhaul issue> [--out FILE] [--json]` writes the draft:

- every live rule of the rule book with what checks it, read from its implementations: a test (it
  names the tests or the suite), judgment ("by judgment"), a check (it links a script, or names
  neither);
- the retros closed since the last closed overhaul (titled `docs/overhaul-...`), or in the whole
  history where none has, each from its report's block: its sizes, its broken rule checks, its
  findings by kind and how many of the previous retro's findings closed or recurred, and the
  finding classes more than one of them named;
- the previous overhaul's findings, each with the issues that name it
  (`overhaul #<n> finding <k>`) and their state (`closed`, `open` or `none`);
- the pruning facts (`facts`, below), beside the previous overhaul's counts.

It ends in a JSON block under `<!-- se:overhaul-yaml -->`, which the next overhaul reads. Without
gh it prints its reads round by round and takes the answers from `--answers <dir>`, as `retro.py
collect` does.

`uv run python scripts/overhaul.py file <overhaul issue> --draft FILE` files a judged overhaul. The
judge fills the draft's block:

- `verdicts`, one per rule: `rule`, `strays` (`none`, `slightly`, `far`) and `how`;
- `looked_at`, every part answered (`outside`, `consistency`, `rules`, `retro`, `speed`,
  `mechanize`, `removal`; "nothing to change" is an answer);
- `findings`, each with `title` (five words or more), `body`, `rule` (a rule's id, or `new`),
  `place` (the file it changes), `controversial` with its `why`, and optionally `sources`;
- `went_well`.

It refuses, writing nothing, an incomplete judgment: a rule without a verdict, an empty
`looked_at` part, a finding without a rule of the book, a place or a body, a controversial finding
without a why, nothing that went well.

It files no issue
([wrk-007](src/skills/work-model/references/rules.md#wrk-007-one-piece-of-work-one-issue-no-command-files-issues-on-its-own)):
it posts the report, opening with `<!-- se:overhaul-report -->`, as the overhaul issue's closing
comment and closes the issue. Without gh it prints the comment and the close as a plan. Each
finding is

- `work`, for SE to bundle into work issues naming `overhaul #<n> finding <k>`, or
- `decision`, for the owner's decision list; a rule change (its place is the rule book, or its
  rule is `new`) is always a decision.

`uv run python scripts/overhaul.py facts [--json] [--repo PATH]` is an overhaul's pruning facts,
read from the checkout (default: the current directory). It only reads, uses the standard library
alone and judges nothing: each fact is a candidate the overhaul judges by the rule book's
[des-015](src/skills/work-model/references/rules.md#des-015-the-less-code-the-less-to-maintain)
and its neighbours. It lists:

- the functions, classes and methods in `scripts/` that nothing but tests reaches, each marked with
  whether the tests reach it: a name-based call graph (`ast`) from each script's import-time code,
  the handlers a decorator registers by name and the names authored text writes as code (a
  documented interface such as `preflight`); it errs towards missing dead code, never towards
  naming live code;
- duplicate blocks, six or more lines written alike in two places, and near-duplicate functions,
  75% or more of their shape (names and literals aside) alike;
- the lines of code and of tests per script, a test file counting for the script it imports or runs;
- the ten longest functions, files and parameter lists, and the ten files untouched longest (git);
- each script command (argparse's and `work_tickets.py`'s registry) that no line of the authored
  text (`se.toml` `authored_content`) names after its script.

`--json` prints the same facts as data.
