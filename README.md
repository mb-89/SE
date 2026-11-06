# se: systematic engineering

A process plugin for AI agents. Its main agent, **SE**, is the one a person talks to; its sub-agents
are the integrator and the worker. With them come their skills, issue templates and the scripts they
call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Install

One step per place. The `se` branch is where SE lives until it replaces `main`, so the commands name
it (`#se`, `-b se`); once it is `main`, they drop it. What each agent does is in its own file in
[src/agents/](src/agents/).

| Place | Install | Choose SE | Check that it loaded |
| --- | --- | --- | --- |
| Claude Code | `claude plugin install se --marketplace mb-89/SE#se` | `claude --agent se:se`, or `"agent": "se:se"` in a project's `.claude/settings.json` | `claude plugin list` shows `se@se`; `/agents` lists `se:se`, `se:integrator` and `se:worker` |
| Claude Code cloud (claude.ai/code) | the environment's setup script: `rm -rf ~/.claude/skills/se; git clone --depth 1 -b se https://github.com/mb-89/SE ~/.claude/skills/se` | `"agent": "se:se"` in the repository's `.claude/settings.json` | ask the session which agent it runs as and which `se:` agents and skills it has |
| GitHub Copilot in VS Code, in se's own checkout | `git clone -b se https://github.com/mb-89/SE` and open it: VS Code reads its `.github/agents/` and `.github/skills/` | pick `se` in the Agent dropdown of the Chat view | the dropdown lists `se`, `integrator` and `worker`; **Configure Skills** lists `catch-up`, `decision` and `work-model` |
| GitHub Copilot in VS Code, every repository | **Chat: Install Plugin from Source** with `https://github.com/mb-89/SE` (agent plugins, `chat.plugins.enabled`); or copy `.github/agents/*.agent.md` to `~/.copilot/agents/` and `.github/skills/*` to `~/.copilot/skills/` | as above | as above |

Marketplace plugins do not load in a cloud session; a plugin cloned into `~/.claude/skills/` does
(it shows as `se@skills-dir`). Remove the environment's own SE plugin, if it has one (a
`CLAUDE_CODE_PLUGIN_DIRS` naming another plugin `se`), so the two do not collide: while it is set,
the other plugin wins and `claude --agent se:se` stops with `--agent 'se:se' not found`.

SE's skills read files in the plugin's folder and run its scripts with `uv run python`, and that
folder is outside your project. Claude Code asks you to allow this the first time. A headless
`claude -p` session cannot ask, so it refuses them unless you allow them in advance, for example
`--allowedTools Read Glob Grep Write Edit "Bash(uv run python:*)"`.

**Everything else arrives by itself.** At the first start SE runs
[scripts/bootstrap.sh](scripts/bootstrap.sh) (Claude Code runs it at every session start; it is quiet
when nothing is missing): it installs `uv` into the user's home, Python 3.11 or newer through `uv`,
and the project's [modules](#modules).

The one tool it cannot install without admin rights is `git`; it then names the one line to run. An
interrupted first start finishes when run again.

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
  to the person and hands it to the session; elsewhere SE's [instructions](src/agents/se.md) run
  `status --greeting` first.
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
to `se`; a failed build publishes nothing, so the previous artifact stays.

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
the integration branch; on a failure it pushes nothing, restores the pre-merge branch and
escalates. `work_tickets.py push` runs its push gate first.

Default `true`, so a project that never set it is still checked; a project without a public check
sets `public_check = false`, and `push` then prints one line saying the check is off and where to
turn it on.

`version = "MAJOR.MINOR.PATCH"` is the project's one semantic version, published as the git tag
`vMAJOR.MINOR.PATCH` on its integration branch; consumers pin ranges of it
([`se.toml`](#setoml)). Nobody types it after the first: `work_tickets.py push` of the integration
branch (which `integrate` runs) releases what was integrated since origin and the last tag.

Each integration is a first-parent merge whose message starts `Integrate <branch>`, as `integrate`
writes it, and states its kind in the trailer `Release-kind: major|minor|patch`. `integrate` writes
it, and `work_tickets.py release-trailer` prints it for a merge by hand:

- on a re-integration (a merge `Integrate <branch>` of the same branch is already on the
  integration branch) the field report's "Re-integration kind", `patch` unless it says otherwise;
- else `major` where the work issue's "Package kind" says "breaking";
- else by the branch prefix: `feature` (or `feat`) `minor`; `fix`, `perf`, `chore` or `docs`
  `patch`; another prefix is refused before anything is merged.

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

#### Release tags

`release = "workflow"` hands the tags to se's release workflow, for hosts that may push branches but
not tags (Claude's cloud sessions).

- `push` still bumps and commits the version, pushes the branch only and names the workflow; it
  reads the released versions from origin's tags (`git ls-remote --tags`), never from local ones,
  so a version without its tag on origin is left for the workflow, not bumped.
- On each push to the integration branch the workflow walks its first-parent history and tags
  every version `se.toml` carried without a tag, `v<version>` on the first commit that carried it,
  so a missed release is backfilled; a second run changes nothing.
- An existing tag never moves: where it names another commit, the run warns and leaves it.
- Without `release`, `push` pushes the tags itself; another value is refused, naming the file.

A repository turns it on with `release = "workflow"` and a copy of se's own
[`.github/workflows/release-tag.yml`](.github/workflows/release-tag.yml), changed only in
`branches` to name its integration branch (se's names `se`), so that worker branches run nothing.

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
