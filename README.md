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
| Claude Code cloud (claude.ai/code) | the environment's [setup script](#claude-code-cloud); an environment may cache its output, so a session can start with an older clone, which SE [refreshes at start](#start-and-refresh) | each session's first prompt ([below](#claude-code-cloud)) | `claude plugin list` shows `se@skills-dir`; ask the session which `se:` agents and skills it has: `se:se`, `se:integrator`, `se:reviewer`, `se:worker`, `se:catch-up`, `se:decision`, `se:work-model` |
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
and the project's [modules](#modules); in a session it fetches and starts [kern](#kern).

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

It replaces any older SE line (a clone into `/opt/se` that runs `/opt/se/src/build.sh`). A failed
clone starts the session without SE instead of stopping it.

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

### Cloud sessions

What a cloud session meets, whatever state its container comes up in.

- **One cached snapshot per set of sources.** The cloud keeps a container snapshot for each set
  of sources a session starts with, and rebuilds it only when the environment's setup script is
  edited. A session with SE's repository among its sources can so come up with an older SE plugin,
  an older `se` binary and the standing file of a core that ended with the snapshot.
  - The greeting names an SE older than the checkout the session works on, in one line under its
    first: `SE <plugin> runs, older than this checkout's SE <checkout>: ...`; editing the
    environment's setup script rebuilds the snapshots.
  - A plugin from before SE [refreshes at start](#start-and-refresh) (5.47.4 was one) cannot move
    itself, and one from before that line cannot say so.
  - A standing file that names no running core stops no start: kern takes it over
    ([kern/README.md](kern/README.md), "The standing file").
- **A late checkout gets a core.** In a session without sources that clones a repository with an
  `se.toml` after its start, SessionStart ran before the clone existed. The first hook whose working
  directory is inside the clone starts its core in the background, as SessionStart would have, and
  the hooks there then post to it ([scripts/se_hook.sh](scripts/se_hook.sh)).
- **`setup.sh` in a spawned session.** Claude Code's auto-mode permission check judges `bash
  scripts/setup.sh` as one command, before any of its steps runs.
  - In a session another session started without sources, which then cloned SE by hand, it refused
    the command twice: with the clone in one command ("Undermining Oversight"), then alone
    ("Unauthorized Access"). Reading the script, the clone and `git log` passed.
  - The same command ran in a session started with SE's repository as its source.
  - So a spawned session that commits to a repository is started with it as its source
    (`create_session` with `source_url`); one that clones by hand can read and test, and stops at
    `setup.sh` with its report. Nothing is worded to get around the check.

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
- At the session's start, before the core starts, the hook moves an installed SE that is a git
  checkout (the cloud's setup-script clone) to the latest release of its major, `se_start.py
  start-refresh`: one read of the remote's tags and, where it is behind, one fetch of that tag.
  - The move is `refresh`'s, trial start included; the start then runs again from the moved tree,
    so the core starts from its pins, and the greeting names both versions.
  - It fails open: a remote that cannot be read, or a move that fails, starts the session with the
    SE it has, saying so in one line. A development checkout (local changes, a branch other than
    `main`, or commits no remote branch or tag holds), the session's own working tree and a plugin
    Claude Code installed are left to `refresh`.
  - Where the session's working tree is SE's own checkout, the core runs that checkout's release
    pins, not the installed SE's, so a session on `main` runs `main`'s.
- The counts are what loaded: the skills and agents of the plugin's layout (every agent but SE is a
  sub-agent) and the rules the [public check](AGENTS.md#public-safety) enforces.
- `status` reads only the disk and the last update check, cached in `~/.se/start-check.json`
  (`--cache`, or `SE_START_CACHE`), so it answers within a second. A check older than an hour, or
  none, starts `check` in the background; the next start shows its result.
- `check` reads the version tags of SE's own remote and of every module's remote, once each and in
  parallel. A failed read is named in the greeting with its remote, its cause and the command to see
  it; the greeting still appears.
- What is due in the work: where gh is signed in, `check` also counts the work issues landed since
  the last retro (the window of [`retro.py collect`](#work-commands)), the retros closed since
  the last overhaul where that countdown is on, runs the [fleet check](#fleet-check), and caches
  them.
  - The greeting then names a retro that is [due](#retro-due), an overhaul that is
    [due](#overhaul-due) and the fleet's findings by kind and issue, one line each with the command
    to run, and a part whose read failed with its cause.
  - `status` reads them from the cache, and each part from kern live where the core in the checkout
    carries SE's fleet and retro-due components and has read issues: its line then says `live from kern`
    ([components/README.md](components/README.md#who-reads-them)).
  - Without gh (Claude's cloud, where no token reaches SE's code) the greeting names neither; the
    [se agent](src/agents/se.md) runs the fleet check's plan at its first turn instead.
  - `refresh` reads no work: its checks keep the cached lines.
- The outside skills SE's agents rely on (`[roles]` of SE's `se.toml`,
  [AGENTS.md "Agents and skills"](AGENTS.md#agents-and-skills)): the greeting names, in one line,
  each one whose plugin the session lacks, with the roles that rely on it.
  - A plugin counts as present where Claude Code's record of the installed plugins names it with
    its marketplace, or where it is cloned into `~/.claude/skills/` (as the cloud's SE is).
  - Locally the line ends with the command that installs each plugin, `claude plugin install
    <plugin>@<marketplace>`; in Claude's cloud it says that the session lacks them and that the
    cloud environment provides plugins ([Claude Code cloud](#claude-code-cloud)).
  - A list SE cannot read is named instead, and the greeting still appears.
- What is due: the highest version a module's `version` range admits above its locked one, and for
  SE the highest version of its major. A newer version outside the range is shown apart and never
  applied, with the remedy: for a module the range to set in its `se.toml` and the `update` that
  takes it, for SE an install again.
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

### Kern

Nobody starts the core by hand. SE builds its own binary, `se`: kern's core with SE's Go components,
released as `se-v<version>` that `components/release.toml` owns. `scripts/se_modules.py app-binary`
is bootstrap's one reader of the binary to run — SE's `se`, or the bare kern for an application with
no Go components. The plugin's hooks start the binary and post every session event to it:

- **SessionStart**, [scripts/bootstrap.sh](scripts/bootstrap.sh) `--hook`: where
  `~/.se/bin/<name>-<version>` is on the machine, it runs `<name> start` for the project, which
  returns at once, and hands the core the session's start, which takes the session's lease. It names
  the binary in `<project>/.se/.runtime/kern.path` for the later hooks.
  - `~/.se/bin/<name>` links to the version in place (a copy where the file system makes no link),
    and Claude Code's env file puts `~/.se/bin` on the session's PATH, so `se status` works there.
- **The first start of a version** reads the release's `SHA256SUMS` (one small read). Where it names
  this platform's archive, the archive is fetched, checked against its line and unpacked in the
  background, and the core then starts.
  - Where no release matches, the binary is built from its folder (SE's `components/`, kern's own
    `kern/`) with `go` in the background, and the greeting says so; without `go` it failed, and the
    greeting names both causes.
  - The background half runs in its own process (`setsid` where there is one), so the hook's end
    does not end it.
- **Every other event** (SessionEnd, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop
  and SubagentStop) runs [scripts/se_hook.sh](scripts/se_hook.sh) `<event>`, which hands the host's
  JSON to the named binary's `kern hook <event>`.
  - SessionEnd returns the session's lease. The Stop hooks are answered by the delivery
    component's `stop-check`, and else by `stop-check` directly ([Stop hook](#stop-hook)).
  - It fails open: without kern's binary, or with no core answering within 500 ms, it prints
    nothing and exits 0.
- **The greeting** names the binary's state under its first line: `<name> <version>: running, pid
  <n>` (`se <version>` for SE), `starting: <why>`, or `failed: <cause>`.

| measured on 13 Nov in a Claude Code cloud container, Linux amd64, 5 runs | wall time |
|---|---|
| SessionStart, `bootstrap.sh --hook` to the greeting, kern on the machine, 10 runs (before kern: 180 to 234 ms); the pin's read through `uv` is about 150 ms of it | 336 to 410 ms |
| the same with the [refresh at start](#start-and-refresh), SE up to date: one read of SE's tags from GitHub, the core running, 6 runs (without the read: 393 to 463 ms) | 0.98 to 1.44 s |
| the refresh at start moving a shallow clone one release behind (5.47.3 to 5.47.4, from GitHub), trial start included, `start_refresh` alone | 1.84 s |
| the first start of a version, its release fetched (kern-v0.1.0): the hook; the core running, 3 runs | 657 to 715 ms; 1.21 to 1.38 s |
| the first start of a version with no release: the hook; the core running, Go's build cache warm, 3 runs | 524 to 667 ms; 1.40 to 1.52 s |
| a hook through `se_hook.sh`, the core running, by event (PostToolUse with a GitHub tool's answer) | 10.0 to 15.5 ms |
| a hook through `se_hook.sh`, no core running | 8.8 to 11.3 ms |
| a hook through `se_hook.sh`, no binary named | 4.2 to 5.5 ms |
| `kern hook` alone, no core running; the core running | 6.0 to 6.6 ms; 7.0 to 7.8 ms |
| for comparison, a Python start that does nothing: `python3 -c pass`; `uv run --no-project python -c pass` | 13 to 19 ms; 39 to 72 ms |

### Commands as components

SE's script commands attach to kern as Python components ([docs/go-core.md
"Migration"](docs/go-core.md#migration)); the command line does not change.
[scripts/se_components.py](scripts/se_components.py) owns how.

- **Declared:** each command group of a script is one component, `components/<group>/`:
  `work_tickets.py`'s tickets, issues, delivery and integration, `review.py`'s review, `retro.py`'s
  retro, `overhaul.py`'s overhaul, render, the
  pages `timeline.py` and `deck.py` build, and `se.py`'s scaffold.
  - Its `component.toml` is what `work_tickets.py docs` writes from the script's argparse parser
    (for `work_tickets.py`, built from its command registry), and its `__init__.py` answers each
    declared command with the script's own code.
  - A script joins by naming its groups (`COMPONENTS`), its read-only commands
    (`INTERACTIVE_COMMANDS`) and its `make_parser`, and by its name in `se_components.py`
    `SCRIPTS`. A script without subcommands (`timeline.py`) is one command, and two scripts share
    a component where the second names the first one's group (deck.py, timeline.py's render).
  - The [command reference](#work-commands) renders from these declarations as kern's reader reads
    them.
- **Placed:** `wiring.toml` places each in a process of its own, beside SE's Go components in the
  `se` binary, so the core the hooks start in SE's checkout lists them all: `se status --json` names
  the instances, those attached (a placed one once its process attached, a Go one with the core)
  and, under `backends`, the backend each chose (`github`: `relay` or `token`).
- **Routed:** a command a person waits on that only reads (its class `interactive`: `status`,
  `config`, `ready`, `capacity`, `queue`, `fleet-check`, `metrics` and `overhaul.py facts`) goes
  through kern's `call.<command>` where kern serves the checkout the command runs in and that
  checkout holds the script.
  - Any copy of the script routes there, the plugin's (the path SE's skills name) as much as the
    checkout's own, and kern answers with the checkout's code.
  - Everywhere else, and for every command that writes, the command runs directly, as it did
    before components. A call that fails on the way runs directly too: the command only reads.
  - A call kern has not answered within 60 s (`CALL_WAIT`), as one waiting behind calls in
    another directory, is given up and runs directly. The component's process serves the calls
    waiting for its one working directory in arrival order, and drops a call given up while it
    waits ([docs/go-core.md "A call given up"](docs/go-core.md#a-call-given-up)).
  - `SE_KERN=off` keeps every command direct (the suite and each component's own process set it);
    `SE_KERN=on` refuses to fall back.
- **Tested** against kern's Python fake core (`tests/test_se_components.py`), and once against the
  real core with the components placed (`tests/beside_se_components.py`, `se.toml`
  `[tests.beside.se-components]`).

### Doctor

When something half-works, `uv run python <se>/scripts/se_doctor.py` prints one report to paste
whole, the most important finding first, each line "seen", "silent" (asked, no answer) or "not
measured". `--json` prints the same as data, `--offline` skips `gh` and the network, `--strict`
exits 1 on a problem; otherwise it exits 0.

- **What it measures**: the host and whether it is a cloud session; the SE checkout against its
  upstream as last fetched; each installed SE plugin against the checkout and the latest release
  the start's update check cached.
  - The `se` binary on `PATH`, in `~/.se/bin` and where the core started it, against its pin; the
    core's standing file, pid, boot id and last log lines.
  - Each hook and MCP server registration a host reads, and whether the scripts it names exist;
    `gh` signed in or not; the reach of the hosts SE fetches from.
- **Read-only**: it writes nothing, starts nothing that stays, fetches nothing and calls no service
  beyond `gh auth status` and one HEAD request per host, each with a short timeout. Nothing runs it
  automatically.
- **Private**: it prints no token, bus user, environment value, e-mail address or path outside the
  checkout; home is `~`, the checkout `<checkout>`.
- Its checks are pure functions of the facts it gathers, which its docstring owns.

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

The plugin's session start (`scripts/bootstrap.sh --hook`) and the setup scripts write it the same
way (`work_tickets.py identity`), so a fresh clone's first commit never carries the host's default
identity.

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
([AGENTS.md "Public safety"](AGENTS.md#public-safety)). `work_tickets.py integrate`
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
   - A Goal that opens with a list's lead-in gives that lead-in. A sentence over 120 characters
     ends at its last clause boundary (a comma, semicolon, colon or dash) within them, never with
     "...", or at its first within 200 (`work_tickets.py` `at_boundary`).
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
   - Where origin's work branch holds commits the landing did not take, pushed after step 1 read
     it, it names each and closes nothing: the worker updates its report, and `integrate` lands
     them again, as a re-integration.
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
    `expectedHeadSha` at the landing head; where trust is on, the
    [record](#trusted-landings)'s two steps come first;
  - the session runs those steps with its GitHub tools;
  - `integrate --read-back <branch> --landing-pull <number> --check-run <url>
    --landing-description <file>` then reads step 5 back through `git fetch` alone (origin's
    integration branch one commit on the tested base, with the tested tree).
  - It finishes everything local of step 6 and prints its close-out plan: the work pull request's
    comment and close, and the work issue's comment, label and close.
  - Before that it checks the landing pull request's description, saved after the merge: it must
    end in the plan's [metrics](#metrics) line, or the read-back fails and closes nothing.
- A failure on the way prints the escalation as a plan too: the comment and the `escalated`
  label.

The same split holds for `refs request` and `refs apply` (the work model's
[Steps only the person approves](src/skills/work-model/SKILL.md#steps-only-the-person-approves)):
without a signed-in `gh` each prints its comment, dispatch and run steps, and `--read-back` checks
the refs through `git ls-remote` and prints the rest.

#### Hand-offs through the relay

Where kern serves the checkout with its GitHub component on the relay backend (a cloud session,
no token), the hand-off needs neither a retyped file nor a second run
([docs/go-core.md "GitHub in the cloud"](docs/go-core.md#github-in-the-cloud)):

- **Reads.** `intake`, `field-report --check`, `deliver` and `integrate` read the issue, its
  comments and the pull request from kern's snapshots, which every GitHub tool answer the session
  receives fills through the PostToolUse hook ([scripts/se_relay.py](scripts/se_relay.py)).
- **One call.** `integrate`, `refs request`, `refs apply`, `file`, `route` and `fleet-check`
  (`work_tickets.py` `STREAMED_COMMANDS`) run as one call through kern's `call.`, from the same
  command line.
  - Their component runs the command in a thread of its own; each GitHub step of its plan is one
    `github.step` request on the component's `step` port, which `wiring.toml` binds to the GitHub
    component (`RelayDoor` in `work_tickets.py`, `Stepped` in
    [scripts/se_components.py](scripts/se_components.py)).
  - kern tells the agent each step on its hook; the session runs it with its GitHub tools, and the
    answer comes back to the command through the PostToolUse hook. `integrate` so lands, reads its
    landing back and closes out in that one call, with no `--read-back`.
  - Each step's line, `GitHub step through kern's relay: <tool>`, and every phase reach the caller
    as they are said, and the call waits as long as kern beats: a check run of many minutes fits
    ([docs/go-core.md "Progress and long calls"](docs/go-core.md#progress-and-long-calls)).
  - The step's line names `uv run python <se>/scripts/se_relay.py next --root <checkout>`, which
    prints the tool calls the relay waits for, as the hook tells them on a prompt: the agent asks
    for the pending step whichever tool's PostToolUse ran last.
  - `integrate` reads the pull request first, then runs its local guards, the field-report guard
    against the branch's merge base and the merge, and only then reads the work issue: a branch
    that cannot land fails after that one read. A checkout detached at origin's integration branch
    (a cloud session's source checkout) is moved onto the branch first, fast-forwarded there.
  - The core fails a step of the command only after ten minutes without its answer, a line or a
    beat (`StepWait`, the work model's stall rule), not after one: the wait was raised, the hook's
    beat does not count, and the command's process beats every 5 s until its answer is out.
- **The fallback.** Without kern, on a token backend or with `SE_KERN=off`, each command keeps its
  file-based hand-off above. A call kern refuses before it says anything runs directly; one that
  fails on the way is reported and never run twice, as it writes.
  - A command that falls back says so first, on stderr, and why: `se: <command> fell back to the
    file-based hand-off: <why>`.
- **Tested** against fake sessions in the suite (`tests/test_work_ticket_issues.py`,
  `tests/test_work_tickets.py`) and against the real core: `tests/beside_se_relay.py` runs
  `fleet-check` as one call whose reads a simulated session answers on the hook, from the
  checkout's script and from a plugin's copy, then the fallback once kern stops.

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
  reason and the remedy, and the others still land. The remedy is the repository's tag rulesets
  where origin's reason names a rule; otherwise it is a rerun first, as a transient refusal
  (`missing necessary objects`) passes on one.
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

An in-progress issue whose branch origin does not have yet is listed as `starting`, which is
healthy, until the lease has passed since its newest `Started:` comment; then it is `no branch`.
Where the issue has no such comment, or its comments were not read, the lease cannot be counted:
it is `no branch` at once, saying why.

Blocks are the `## Blocked by` section of each open issue's body, where `work_tickets.py block`
writes them.

Where the core running in the checkout carries SE's fleet component and has read the open issues
and the open pull requests each as a whole list, it answers from the core's `fleet/findings`
instead, live, naming how many issues and pull requests the core has read and since when
([components/README.md](components/README.md#who-reads-them)); the Python check stays the path
everywhere else.

A partial view is no verdict: where the core holds only some issues or pull requests, the check
says how many it has seen and since when, and reads the fleet itself.

Without gh it prints its GitHub plan; the session runs it with its GitHub tools, saves the three
lists as JSON (each in-progress issue with its comments) and passes them as `--open-issues`,
`--closed-issues` and `--pulls`.

### Settings check

`fleet/settings.toml` records settings the fleet runs on outside the repository: main's ruleset,
the scheduled tasks and the cloud environment. `scripts/fleet_settings.py` owns its format and
the doors.

`work_tickets.py settings-check` compares it with what the live doors read and prints each
difference in one line. It is advisory: it exits 0 unless `--strict` is given, and nothing runs it
on its own.

### Retro due

```toml
[retro]
due_after = 10
```

A retro is due once `due_after` work issues landed since the last closed retro issue, built in 10;
the [start greeting](#start-and-refresh) names it. `scripts/retro.py` owns the count and the
setting; SE's retro-due component counts the same from kern's GitHub names, for the greeting to read
live ([components/README.md](components/README.md)).

### Overhaul due

```toml
[overhaul]
due_after = 3  # absent or 0: off
```

An overhaul is due once `due_after` retros closed since the last closed overhaul issue; a retro
closed as a duplicate or as not planned does not count, as for the landings a retro counts. The
[start greeting](#start-and-refresh) names it beside the retro.

- **Off unless set.** Absent or 0 switches the countdown off, SE's own `se.toml` among them: the
  greeting names no overhaul, and the retro and the overhaul score earlier findings as they did
  before it.
- **Too early to score.** With it on, an earlier finding that an issue still open takes is listed
  as `too early to score`, by `retro.py collect` and `overhaul.py read`, not scored as a failure.
- **One store.** `scripts/overhaul.py` owns the count (`retros_since`, a pure function of the runs
  it is given) and the setting; the retro-due component counts the same into its name,
  `retro-due/due`, by its config `overhaul-after` (0, off, unless the wiring sets it).

### Stop hook

```toml
[stop]
refusals = 5
```

The plugin hands every `Stop` and `SubagentStop` to `work_tickets.py stop-check`, so a worker's turn
ends only with its work issue delivered.

- kern answers it within the hook: `wiring.toml` binds both events to the delivery component's
  `stop-check`, which judges in its own warm process ([Kern](#kern)).
- Where no command of kern's answers (no binary, no core, the component's process not attached
  yet, or it failed), [scripts/se_hook.sh](scripts/se_hook.sh) runs `stop-check` as a process of
  its own, with the same verdict.
- The warm process asks `gh auth status` once: a gh found unusable is held 60 s, a usable one for
  the process.

| measured on 13 Nov in a Claude Code cloud container, Linux amd64, gh not signed in, 6 runs | wall time |
|---|---|
| a Stop through `se_hook.sh`, answered by kern's delivery component: the first; the later ones | 319 ms; 24 to 57 ms |
| a Stop through `se_hook.sh`, answered by `stop-check` directly through `uv` | 434 to 586 ms |

What it judges:

- Where it refuses: a checkout whose ticket queue (`.se/work/`) is for a work issue (intake's
  snapshot, or what was recorded as read of it), on a branch other than the integration branch.
- What it refuses: the stop, while the branch has no open pull request whose description carries a
  field report that passes `field-report --check` at the branch tip. The refusal names what is
  missing and the commands that deliver.
- `refusals` is how often in a row it refuses, built in 5; then it lets the turn end and says so,
  and counts afresh. A passing stop resets the count.
- A `SubagentStop` is judged only for a worker sub-agent (`worker`, `se:worker`), in the checkout
  it works in, one whose queue is for a work issue:
  - one its prompt names, else the one whose ticket queue its transcript (the event's
    `agent_transcript_path`) last touched, a path into `.se/work/` or a `--worktree`;
  - only where neither names one, the hook's `cwd`; where that holds none either, it lets the
    sub-agent end and says why.
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
over_limit = "fail" # optional, or "warn"

[tests.beside.kern] # optional, one table per suite in another toolchain
setup = ["go", "test", "-run", "^$", "./..."] # optional
command = ["go", "test", "./..."]
directory = "kern"
target_seconds = 30
limit_seconds = 60
```

- `command`: the project's complete suite, an argument array run without a shell from the project
  root. `work_tickets.py integrate` runs it at every integration, and `work_tickets.py suite` runs
  it the same way for a worker's before-and-after times.
- `setup`: optional and of the same form; it installs the test dependencies (packages, browsers)
  and runs first. The gate prints its time and its last lines apart, and that time does not count
  against the budget. A failing setup stops the run before the suite, naming the command and its
  output.
- `target_seconds` (default 60): above it the gate warns.
- `limit_seconds` (default 120): the budget, judged on one reference run, CI's (below).
- `over_limit` (default `"fail"`): what a run over the limit does. One rule holds for every
  project: an overrun fails, as below. A project that declares `"warn"` takes the other side of
  the trade-off: no run is refused for its time, so a slow runner never blocks a landing, but
  nothing stops the suite from creeping past its budget; each overrun only warns, naming the
  setting.
- `beside.<name>`: optional, a suite in another toolchain, such as SE's kern Go tests
  ([kern/README.md](kern/README.md#tests)). Its `command` runs in `directory` (relative to the
  root, default `.`) after the complete suite, wherever the suite runs: `integrate`,
  `work_tickets.py suite` and CI's `check`.
  - Its `setup`, optional, runs first in the same folder, outside its budget, as the suite's
    does: for a Go suite, `go test -run '^$' ./...` builds every test binary, so a cold build
    (kern's took 35.1 s once on CI) never counts as test time. A failing setup refuses the run, and the suite beside does not run.
  - A key the running scripts do not know is refused on the reference run (CI's `check`, which
    runs the merged tree's scripts) and elsewhere warns and is ignored. `integrate` runs the
    integration branch's scripts, so a branch can add a key and use it in one landing.

The two budgets are apart, and neither spends the other's time:

- Each run prints and reports both times, `Suite: <result>; <time> (target, limit); kern passed in
  <time> (target, limit)`, and the metrics line notes `beside_seconds` beside `suite_seconds`;
  `work_tickets.py metrics` flags a suite beside over its limit as it does the suite
  ([Metrics](#metrics)).
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

A sharded project records it with SE's two actions, at the se ref it pins (the module command's
`update se` moves the ref with the pin, [Modules](#modules)), and copies nothing:

```yaml
jobs:
  shard:
    strategy:
      matrix:
        shard: [one, two]
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@v7
      - uses: mb-89/SE/.github/actions/suite-shard@<se ref>
        with:
          name: ${{ matrix.shard }}
          command: uv run pytest -q tests/${{ matrix.shard }}
  check:
    needs: shard
    if: always()
    runs-on: ubuntu-26.04
    steps:
      - uses: actions/checkout@v7
      - uses: mb-89/SE/.github/actions/suite-time@<se ref>
        with:
          shards: 2
```

- [`suite-shard`](.github/actions/suite-shard/action.yml) runs in each shard:
  `work_tickets.py suite-shard` runs the shard's command, times it and writes its record, which
  the action uploads, also when the shard fails.
- [`suite-time`](.github/actions/suite-time/action.yml) runs in `check`: `work_tickets.py
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

Generated text is not authored, and the guard leaves it out by the mark its generator writes with
it. That is a block from a `<!-- generated by <generator>: begin -->` line to a
`<!-- generated by <generator>: end -->` line (the command reference below), and the whole of a
file that holds the notice `se_plugin.py build` opens each generated Markdown file with.

### Trusted landings

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
  [`integrator-pass`](.github/actions/integrator-pass/action.yml)) and the suite runs only where it
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

A project's own `check` uses the action at the se ref it pins, as the sharded suite does; its
copy of `se-pass-record.yml` calls the same action, `mb-89/SE/.github/actions/integrator-pass@<se
ref>`, with `mode: record`:

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
        uses: mb-89/SE/.github/actions/integrator-pass@<se ref>
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

A kern application gets the same shortcut from its battery: `kern-battery.yml`'s job `trust`
runs the action from the kern commit the battery runs at (`job.workflow_sha`), the tag the
application pins, and the vet and tests run only where it answers false.

To turn it on, the application also grants those two permissions, adds the `schedule` and copies
`se-pass-record.yml` with the action at `@kern-v<version>`. kern's template keeps it off
([kern's battery](kern/README.md#the-battery)).

Free minutes for a private repository, which the owner sets up:

- Linux runners only (`ubuntu-*`): a Windows minute counts double, a macOS minute ten times.
- `check` on pull requests only, so a landing is not run again on its push to main; the nightly
  `schedule` keeps main covered.
- Never on data-only pushes: `paths-ignore` for the files no test reads.
- An Actions budget of $0 in the account's billing settings, so a month past the free minutes
  stops the runs instead of billing them.
- Each run's job is billed by the started minute: a trusted `check` and the record's run cost a
  minute each, against the full suite's own minutes.


### Platform legs and their queue

kern-platforms runs kern's tests and SE's start and hook tests on a Windows and a macOS runner, and
`check` needs every leg. A job's `timeout-minutes` counts only from when a runner takes it, so it
bounds a leg that runs (45 minutes) and not one that waits: a leg that never gets a runner waits
until GitHub fails it after 24 hours, and `check` with it.

- **The queue bound.** The job kern-platforms-queue
  ([scripts/ci_queue.py](scripts/ci_queue.py) `watch`) reads the run's jobs every 30 s. Once every
  leg has a runner it passes; a leg still queued after 20 minutes is reported as never run, an
  error naming the leg and in the job's summary, not as a test failure, and the run is cancelled.
- **Re-run once.** `.github/workflows/check-rerun.yml` hears each completed run of `check`
  (`ci_queue.py rerun`): a first attempt that was cancelled while a leg never had a runner is
  re-run; a second attempt, or a run that ended any other way, stays as it ended.
- **Tested** against a fake of the jobs API and a fake clock (`tests/test_ci_queue.py`); GitHub's
  own queue, cancel and re-run are not reproducible there.
### Metrics

Every run of a `work_tickets.py` or `se_start.py` subcommand appends one JSON line to
`~/.se/metrics.jsonl` (`SE_METRICS` names another file), so the command that spends time or
GitHub's limits can be named instead of guessed. `scripts/metrics.py` owns the line and the report.

- `command` (`work_tickets.py backlog file`), `start` (UTC), `wall_seconds` and `exit_code`.
- GitHub through the door: `gh_calls` (every `gh` call and every push attempt), `gh_refusals` (a
  call GitHub refused for its rate limit, a push it refused transiently) and `gh_wait_seconds`
  (the waits on GitHub: a push retry, a poll of `check` or of a workflow run).
- CI's suite time on the integration branch, `ci_suite_seconds`, the median of its last runs,
  where it was read ([Test budget](#test-budget)); `integrate` always reads it, so its line holds
  both times.
- What a command notes itself: the suite's `suite_seconds` and its `suite_limit_seconds` (`[tests]`
  `limit_seconds`) from `suite` and `integrate`, the `issue` `integrate` landed, and
  `budget_seconds` from an interactive command, its budget from
  [Feedback budgets](#feedback-budgets).

A line that cannot be written is dropped; the command never fails for it. `integrate` prints its own
line last, `Metrics: {...}`, for the integrator's report.

The landing pull request's description ends in that line too, as it stands when the landing plan is
written, so a cloud integrator's costs outlive its container: [`retro.py collect`](#work-commands)
reads it back. A hand-off's `integrate --read-back` refuses a description that lacks it
([Landing on main](#landing-on-main)).

`work_tickets.py metrics` prints the top spenders by total wall time and by GitHub calls since a day
(`--since`), and every overrun of a budget a line declares:

```text
Metrics: 4 runs since 2026-11-10 in ~/.se/metrics.jsonl
Top spenders by wall time:
  work_tickets.py integrate: 1 runs, 300.0 s wall, 40 GitHub calls, 2 refused, 120 s waiting
Top spenders by GitHub calls:
  work_tickets.py integrate: 1 runs, 300.0 s wall, 40 GitHub calls, 2 refused, 120 s waiting
Overruns: 1
  2026-11-10T09:00:00Z work_tickets.py integrate #749: suite 130.5 s over its budget 120 s
```

The lines are per machine; the retro reads the report of the machine its integrations ran on
([retro.md](.github/ISSUE_TEMPLATE/retro.md)).

### Feedback budgets

A person never waits on a silent command. The budgets are declared once, in
[scripts/feedback.py](scripts/feedback.py), which owns them and the lines below; they hold every
`work_tickets.py` and `se_start.py` subcommand:

- First line within 1 s: a run that has shown nothing after half a second prints
  `<command>: working, nothing to show yet`.
- Interactive commands finish within 5 s: `work_tickets.py status`, `queue`, `intake` and
  `metrics`; `se_start.py status`, the greeting, within 1 s. Each run notes its budget in its
  [metrics](#metrics) line, so `work_tickets.py metrics` flags an overrun.
- Long commands announce each phase as it starts, `Phase: <what>`: `integrate` (the pull request
  read, the guard, sync, the merge, the suite, the checks, the release, the push, the landing plan,
  the read-back and the close-out), `suite` (its setup and the suite; with `--compare`, each run)
  and `refresh`.
- A call that reads GitHub or a remote prints what it reads before it is made:
  `Reading GitHub: gh issue list --state open --label escalated` (without the options that only
  shape the output), `Reading the remote: git fetch origin`.

Progress lines go to stderr, so what a command prints on stdout, JSON or a description, stays as it
is. `queue` reads its listings, and each candidate's blockers and branch, at once while the checkout
syncs, so it waits on GitHub about three times per run rather than once per call.

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
  - It also moves each call of the module's actions in `.github/workflows/`, `uses:
    <owner>/<repo>/.github/actions/<name>@<ref>` with `<owner>/<repo>` its url's last two path
    segments, to the new pin: its highest `v<x.y.z>` tag, else its commit. So the actions (SE's
    [shard actions](#test-budget)) run the version `se.lock` pins; a reusable workflow stays at
    its major tag.
- `path`: prints the directory a module is used from (its `path` included), for tools that load it.
- `--root <dir>` names the repository (default: the nearest ancestor with `se.toml`); `--local <file>`
  reads another machine-local file than `~/.se/local.toml`.
- Git runs without prompts; credentials come from the machine's git setup.

## New application

`se.py new app` ([its usage](#scaffold)) creates an application on kern, the core SE builds on
([docs/go-core.md "A bare application, and `se new app`"](docs/go-core.md#a-bare-application-and-se-new-app)),
in the new or empty folder its `--path` names: kern's template at SE's kern pin, the name filled in,
and git's first commit on `main` as the [project identity](#project-settings).

- **The pin:** while kern is incubated, `kern/release.toml`'s version and its tag `kern-v<version>`,
  read by `se_modules.py`'s `kern_pin`. A version not tagged yet comes from SE's `HEAD`, which the
  command says.
- **kern beside it:** no module `github.com/mb-89/kern` can be fetched yet, so the application holds
  kern's source at the pin in `kern/`, and its `go.mod` replaces the module by it.
- **What it holds:** the template's ([kern/template/README.md](kern/template/README.md)): its wiring,
  where `enabled = false` switches a component off, CI through kern's battery, the `[tests]` budget
  and the `[modules.kern]` pin.
- **Its own binary:** a bare application runs the bare kern. To build its own (the core plus its Go
  components), it adds a `release.toml` naming its `binary`, `package` and download, `[binary]
  release = "release.toml"` in `se.toml`, and a release workflow calling kern's reusable
  `kern-release.yml` with its folder — the way SE builds `se` (`components/release.toml`,
  `se-release.yml`).
- **GitHub stays the owner's:** the last line names the owner's step, creating the repository with
  its ruleset and the first push. The command does nothing on GitHub.

## Ad hoc components

`se.py component add` ([its usage](#scaffold)) scaffolds an ad hoc component in the checkout: a Python component over NATS under the ignored
`.se/components/<name>/` (its `component.toml` and `__init__.py`), placed in the ad hoc wiring
overlay `.se/wiring.toml` that the core reads after `wiring.toml`. Restart the core to run it, about
30 ms; it is never tracked.

An ad hoc solution stays untracked until it earns its place
([gen-001](src/skills/work-model/references/rules.md#gen-001-mechanize-first)).

The core counts each call of an ad hoc component and each run of an untracked script into
`.se/usage/adhoc.jsonl`, and `work_tickets.py`'s retro ([Retro due](#retro-due)) lists a component
used in three or more sessions and a script run three or more times since the last retro as
candidates to promote to a tracked `components/<name>/` ([docs/go-core.md](docs/go-core.md#scripts-are-ad-hoc-components-are-long-term)).

## Work commands

`scripts/work_tickets.py` runs the [work model](src/skills/work-model/SKILL.md): its tickets, issues,
deliveries and integrations. Each command's `--help` names its arguments in full.

The reference below renders from kern's catalog of SE's commands, the declarations of its
components ([Commands as components](#commands-as-components)), which `uv run python
scripts/work_tickets.py docs` writes from each script's parser (`work_tickets.py`'s command
registry, the argparse parser of `review.py`, `retro.py`, `overhaul.py`, `timeline.py`, `deck.py`
and `se.py`); change a command there.

Every SE command is listed there alone: the sections after it name a command and say what it does,
its usage being the reference's.

<!-- generated by `work_tickets.py docs`: begin -->
#### Tickets

`components/tickets`: The worker's local ticket queue under .se/work: tickets, notes, discovery
evidence and the worktree's close.

```text
work_tickets.py close --worktree WORKTREE [--integration-target INTEGRATION_TARGET]
                      [--remove] [--json]
    check or close an integrated worktree

work_tickets.py create --worktree WORKTREE --id ID --title TITLE [--acceptance ACCEPTANCE]
    create a ticket in todo

work_tickets.py init --worktree WORKTREE
    initialize the ticket queue

work_tickets.py move --worktree WORKTREE --id ID --to {todo,held,done} [--issue-body FILE]
    move a ticket between states

work_tickets.py probe --worktree WORKTREE --command PROBE_COMMAND --output OUTPUT
    append a command and output path to the discovery evidence index

work_tickets.py review-note --worktree WORKTREE --note NOTE --disposition DISPOSITION
                            [--backlog-ref BACKLOG_REF]
    append a local note disposition

work_tickets.py status --worktree WORKTREE [--json] [--integration-target INTEGRATION_TARGET]
    report queue status
```

#### Issues

`components/issues`: Work issues and their comments as a role reads and files them: intake, refresh,
escalation, filing, routing, the backlog, blockers and the fleet's pause.

```text
work_tickets.py backlog file --worktree WORKTREE --title TITLE --body-file BODY_FILE
                             [--repo REPO]
    file one backlog issue with both labels, creating backlogged where missing

work_tickets.py backlog list --worktree WORKTREE [--search SEARCH] [--repo REPO]
    list the open backlog issues, or those whose title or body matches --search

work_tickets.py block --worktree WORKTREE --by BLOCKER [--repo REPO] issue
    link an issue to a native blocker

work_tickets.py body-read --worktree WORKTREE [--body-file FILE]
    record the work issue's body as read (intake records it; field-report --check and deliver refuse
    a body changed after it)

work_tickets.py comments-read --worktree WORKTREE --count COUNT --newest NEWEST
    record the work issue's comments as read: their count and the newest one's id (intake records
    them; field-report --check and deliver refuse comments after it)

work_tickets.py escalate --worktree WORKTREE --issue ISSUE --file FILE [--repo REPO]
    comment a question on an issue and label it escalated

work_tickets.py file --worktree WORKTREE --title TITLE --body-file BODY_FILE [--blocked-by N]
                     [--label LABEL] [--repo REPO]
    for SE: file a work issue labelled work, ready and repo:<name>; with --blocked-by, ready only
    once its blockers are linked

work_tickets.py intake --worktree WORKTREE (--issue ISSUE | --issue-body FILE | --outside)
                       [--comments-file FILE] [--repo REPO] [--discovery]
                       [--probe-root PROBE_ROOT]
    read the work issue with gh, or from the files your GitHub tools' answers were saved to, and
    write its tickets into todo

work_tickets.py paused [--worktree WORKTREE] [--repo REPO]
    whether the fleet is paused: exit code 1 and the issue while an issue labelled pause is open in
    the repository (the owner's switch; closing it resumes), exit code 0 while none is. queue,
    start, integrate and route refuse while paused. Without gh it prints the search as a plan for
    the session's GitHub tools, exit code 2

work_tickets.py refresh --worktree WORKTREE [--issue ISSUE] [--repo REPO] [--json]
    re-read the work issue and its comments and report changes

work_tickets.py route --worktree WORKTREE [--title TITLE] [--type TYPE]
                      --routing-file ROUTING_FILE [--issue-title ISSUE_TITLE]
                      [--issue-body ISSUE_BODY] [--repo REPO]
                      issue
    for SE: route a checked outside issue as a work issue in one edit: retitle it to its branch
    name, label it work, ready and repo:<name>, and append the routing section with the handled
    record to its body
```

#### Delivery

`components/delivery`: A worker's delivery: the field report and its guard, sync and identity, the
gated push and the pull request, and the Stop hook's check.

```text
work_tickets.py deliver --worktree WORKTREE [--integrator-session INTEGRATOR_SESSION]
    sync, check the field report, push, and create or update the pull request whose description
    carries it; files no issue

work_tickets.py field-report [--worktree WORKTREE] (--draft FILE | --check FILE)
                             [--issue-body FILE] [--comment-count N] [--newest-comment ID]
                             [--check-runs FILE]
    draft or check the field report a pull request description carries, in the form of
    .github/pull_request_template.md

work_tickets.py guard --worktree WORKTREE --branch BRANCH --pr-description FILE
    require the field report to name removed protected content, against origin/<integration branch>
    as sync fetched it (the local branch without origin)

work_tickets.py identity --worktree WORKTREE
    set the checkout's commit identity (machine-local public_identity, else se.toml
    project.identity) as sync does, without fetching or merging; scripts/setup.sh, setup.ps1 and the
    session's start (bootstrap.sh --hook) run it

work_tickets.py pr-body [--worktree WORKTREE] --issue-body ISSUE_BODY --issue-url ISSUE_URL
                        --field-report FILE
    print the pull request description deliver writes: Fixes <issue> where all its acceptance shows
    before the merge, else Refs <issue>, then the field report between its markers

work_tickets.py push [--worktree WORKTREE] [branch]
    public check's push gate, then git push -u origin <branch>; retries a transient refusal once a
    minute, ten attempts; the integration branch needs a passing suite and public check recorded on
    the tree pushed

work_tickets.py stop-check [--worktree WORKTREE] [--pull NUMBER] [--pr-description FILE]
                           [--hook JSON]
    the plugin's Stop and SubagentStop hook: in a checkout whose ticket queue is for a work issue,
    refuse the turn's end while its branch has no open pull request whose description carries a
    field report that passes field-report --check at the branch tip, naming what is missing and the
    commands; at most [stop] refusals times in a row (se.toml, built in 5). Anywhere else, for a
    sub-agent that is no worker, and where it cannot judge (no gh and no recorded pull request) it
    lets the turn end. It reads the hook's JSON on stdin and answers the hook's JSON on stdout

work_tickets.py sync --worktree WORKTREE
    merge the newest integration branch (se.toml project.integration_branch, default main) from
    origin, or locally without origin

work_tickets.py verified [--worktree WORKTREE] remote_ref commit
    the pre-push hook's guard: refuse a push of <commit> to <remote ref> where the ref is the
    integration branch and no passing suite and public check are recorded on its tree; push runs the
    same check
```

#### Integration

`components/integration`: The integrator's and SE's work: integrate and its release, ref
maintenance, the suite and its budget, metrics, settings, starting work, the queue, the fleet and
settings checks and the generated docs.

```text
work_tickets.py capacity [--worktree WORKTREE] [--repo REPO] [--all-repos]
    show local worker capacity or cloud unlimited capacity

work_tickets.py config --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT]
                       [--integrator-session INTEGRATOR_SESSION]
    show the repository and the machine-local settings in effect

work_tickets.py docs [--check]
    write the command groups' component declarations (components/<group>/component.toml) from this
    registry and the README's command reference from them; with --check, only refuse a declaration
    or a README that differs

work_tickets.py fleet-check [--worktree WORKTREE] [--repo REPO] [--json]
                            [--open-issues OPEN_ISSUES] [--closed-issues CLOSED_ISSUES]
                            [--pulls PULLS]
    list every stuck or stray piece of work, each with its issue, pull request and remedy: in-
    progress work without a branch once the lease has passed since its Started comment (listed as
    starting before) or without a push within the lease, a delivered pull request whose check failed
    or that conflicts, a branch of a closed issue, a block by an issue closed as not planned or by
    itself, an se-person issue and what it holds up; 'healthy' and exit code 0 when there is none,
    exit code 1 otherwise. It only reads. Without gh it prints its GitHub plan and takes the answers
    from files

work_tickets.py format [--root ROOT]
    apply the fix of every check the check job runs that a fix can satisfy: write the generated
    layouts (se_plugin.py build) and the command reference with its declarations (docs); a second
    run writes nothing

work_tickets.py integrate --worktree WORKTREE [--repo REPO] [--pr-description FILE]
                          [--issue-body FILE] [--branch BRANCH] [--read-back BRANCH]
                          [--landing-pull LANDING_PULL] [--check-run CHECK_RUN]
                          [--landing-description FILE] [--build-command BUILD_COMMAND]
                          [--include-late REASON] [--check-command JSON]
                          [--check-command-temporary-directory]
                          [pull_request]
    validate the field report a pull request's description carries, merge it on land/<branch>, test,
    land it through a squash pull request once check passes, and close the work issue. Where gh is
    not signed in it pushes land/<branch> and prints the GitHub steps as a plan for the session's
    GitHub tools; --read-back <branch> then checks the landing through git and finishes the close-
    out

work_tickets.py metrics [--since DATE] [--file FILE]
    print what the commands cost, from the line every run of a command appends (README Metrics): top
    spenders by total wall time and by GitHub calls, and each overrun of a declared budget (the
    suite's [tests] limit_seconds in se.toml)

work_tickets.py queue [--worktree WORKTREE] [--repo REPO] [--all-repos]
    list delivered pull requests (open, to the integration branch, with a complete field report),
    escalations and startable work issues

work_tickets.py ready [--worktree WORKTREE] [--repo REPO] [--all-repos]
    list startable ready work issues

work_tickets.py refs apply --worktree WORKTREE [--repo REPO] [--comments-file COMMENTS_FILE]
                           [--read-back] [--run-url RUN_URL] [--conclusion CONCLUSION]
                           issue
    for SE, on the person's yes: run ref-maintenance for real with the triples the issue's newest
    request posted, read the refs back and post the result; prints the line for the integrator.
    Where gh is not signed in it prints these GitHub steps as a plan for the session's GitHub tools;
    --read-back then checks the refs and finishes

work_tickets.py refs request --worktree WORKTREE --triples-file TRIPLES_FILE [--repo REPO]
                             [--read-back] [--request-id REQUEST_ID] [--run-url RUN_URL]
                             [--conclusion CONCLUSION] [--log-file LOG_FILE]
                             issue
    for the integrator: post the triples on the issue, run ref-maintenance's dry run, post its
    output and label the issue escalated; prints the line for SE. Where gh is not signed in it
    prints these GitHub steps as a plan for the session's GitHub tools; --read-back then checks the
    refs and finishes

work_tickets.py release-trailer [--worktree WORKTREE] --issue-body ISSUE_BODY
                                [--pr-description FILE] [--include-late REASON]
                                branch
    print the Release-kind trailer an integration merge of <branch> carries, from its field report's
    Release kind (a re-integration's from its Re-integration kind); push requires it

work_tickets.py settings-check [--worktree WORKTREE] [--repo REPO] [--ruleset FILE]
                               [--scheduled-tasks FILE] [--environment FILE] [--strict]
    compare the fleet's settings the repository records (fleet/settings.toml) with the live ones,
    each difference in one line: main's ruleset through gh where it is signed in or from --ruleset,
    the scheduled tasks and the cloud environment from the answers of the session's list_triggers
    and get_environment tools; a part whose door is missing and a value recorded as unchecked are
    reported unchecked, never as a difference. Advisory: exit code 0 whatever it finds, 1 for a
    difference only with --strict. It only reads

work_tickets.py start --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT]
                      [--no-create] [--cloud-agent CLOUD_AGENT]
                      issue
    start a ready work issue: worktree from the newest main, label in-progress

work_tickets.py suite --worktree WORKTREE [--slowest N] [--compare REF] [--runs N]
    run se.toml's complete suite against its [tests] time budget, as integrate does; exit code 1
    when tests fail, 3 when they pass over the limit and the budget refuses them (README "Test
    budget")

work_tickets.py suite-shard --worktree WORKTREE --name NAME --record DIR ...
    on CI, run one shard of a sharded suite, the COMMAND after --, show its output, time it and
    write its record DIR/NAME.json for suite-time; exit code the command's (README "Test budget")

work_tickets.py suite-time --worktree WORKTREE --shards DIR [--expect N]
    in CI's check job, judge a sharded suite: its time is its slowest shard's, from the records
    suite-shard wrote; prints it as the notice CI's suite time is read from, and no time when a
    shard failed; refusals and warnings are workflow annotations; exit code 1 when a shard failed or
    is missing, 3 when the time is over the limit and the budget refuses it (README "Test budget")
```

#### Review

`components/review`: A cold review of a delivered pull request: the brief a reviewer starts from,
and the report it files as one comment.

```text
review.py brief [--claims] [--json] [--worktree WORKTREE] [--repo REPO] [--pull FILE]
                [--issue FILE] [--issue-comments FILE] [--checks FILE] [--pull-comments FILE]
                pull_request
    what a cold reviewer of a delivered pull request starts from

review.py file --report FILE [--pull FILE] [--issue FILE] [--worktree WORKTREE] [--repo REPO]
               pull_request
    check a review report and post it as one comment on the pull request
```

#### Retro

`components/retro`: A retro: collect writes its draft from the work since the last one, file checks
the judged draft and closes the retro issue with its report.

```text
retro.py collect [--since DATE | --retro ISSUE] [--out FILE] [--json] [--answers DIR]
                 [--worktree WORKTREE] [--repo REPO]
                 retro
    read a retro's window from GitHub and write its draft

retro.py file --draft FILE [--worktree WORKTREE] [--repo REPO] retro
    check a judged retro draft and close the retro issue with its report
```

#### Overhaul

`components/overhaul`: An overhaul: new files its issue, read writes its draft, file checks the
judged draft and closes the issue with its report, and facts lists a checkout's pruning facts.

```text
overhaul.py facts [--repo REPO] [--json]
    list the pruning facts of a checkout

overhaul.py file --draft FILE [--worktree WORKTREE] [--repo REPO] overhaul
    check a judged overhaul draft and close the overhaul issue with its report

overhaul.py new [--worktree WORKTREE] [--repo REPO]
    file the overhaul issue through work_tickets.py file

overhaul.py read [--out FILE] [--json] [--answers DIR] [--worktree WORKTREE] [--repo REPO]
                 overhaul
    write an overhaul's draft
```

#### Render

`components/render`: The pages SE renders: timeline.py builds the Timeline from GitHub, deck.py
builds a deck of decisions, serves it and reads its answers.

```text
deck.py answers [--record FOLDER] [--destination DESTINATION] answers
    print what the answers ask the agent to act on

deck.py build --destination DESTINATION folder
    build a folder of decision notes into one deck

deck.py serve [--wait] [--timeout S] artifact
    serve a deck locally and print the answers it is sent

timeline.py --destination DESTINATION [--snapshot SNAPSHOT] [--save-snapshot SAVE_SNAPSHOT]
            [--config CONFIG]
    Build the Timeline: one static HTML page of the repositories in se.toml `[timeline]`.
```

#### Scaffold

`components/scaffold`: What SE scaffolds: a new application on kern, and an ad hoc component in a
checkout.

```text
se.py component add [--root ROOT] name
    scaffold an ad hoc component under the ignored .se/components/

se.py new app --path PATH name
    create an application on kern from kern's template at SE's kern pin
```
<!-- generated by `work_tickets.py docs`: end -->

`scripts/review.py` holds the review commands, which load `work_tickets.py` for its GitHub door.
`review.py brief` prints what a cold reviewer of a pull request starts from:

- the work issue the pull request names, with its comments;
- the diff against its base at the pull request's head commit, which it names;
- the check runs on that commit;
- the rule book at that commit.

It withholds the pull request's description (the field report) and its comments, because a
worker's own account misleads a reviewer most. `--claims` adds them under a heading that calls
them claims to check, never evidence. Without gh it prints its GitHub steps as a plan and reads
the answers from files ([Without gh](src/skills/work-model/SKILL.md#without-gh)).

`review.py file` keeps a reviewer's findings out of the chat and out of the queue: it posts the
review as one comment on the reviewed pull request and files no issue
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
`retro.py collect` is a retro's mechanical half.

Its window is every work issue closed since the last closed retro issue (titled
`docs/retro-...` or labelled `retro`) closed. Where none has, it starts when the oldest open retro
issue was created; only where no retro issue exists is it the whole history.

`--since` starts the window at a date (`YYYY-MM-DD`) or time, `--retro` where that closed retro
issue closed, whose findings it then scores; the rule checks judge only the window.

Each issue comes with the field report of the work pull request its landing pull request names
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
- the window's [metrics](#metrics) report: the line each landing pull request's description ends
  in, merged with the lines of the local metrics file that started in the window, a run in both
  counted once (by its command and start, the local line winning);
- the previous retro's findings, from the block of the retro doc its report links, each with the work issues of the window
  that name it (`retro #<n> finding <k>`), its state (`closed` where one closed as completed) and
  whether the rule check it names broke again (recurred).
  - Where the [overhaul countdown](#overhaul-due) is on, a finding an issue still open takes is
    `too early to score`: filed after the previous retro's cut-off, it had no time to land, so it
    is listed and scored neither as failed nor as recurred.

It ends in a JSON block (JSON is YAML too) under `<!-- se:retro-yaml -->`, which the next retro's
commands read from the committed draft. `--json` prints the block's data alone.

Without gh it prints the GitHub steps whose
answers are still missing, round by round, and reads the answers from the files the session saved
into `--answers <dir>` ([Without gh](src/skills/work-model/SKILL.md#without-gh)).

`retro.py file` files a judged retro, the draft committed as the retro doc on the integration
branch. The judge fills the draft's block:

- `findings`, each with `title` (five words or more), `body`, `class`, `home` (the file it
  changes), `controversial` with its `why`, and optionally `check` (a rule check);
- `classes`, each with `name` and `fix`;
- `went_well`, what went well.

It refuses, writing nothing, an incomplete judgment: a finding without one of those, a class
without a fix, a controversial finding without a why, a finding on the rule book, or on a check that
recurred, that is not controversial, nothing that went well. It refuses, too, a draft the
integration branch does not hold as it stands: land it there first.

It files no issue
([wrk-007](src/skills/work-model/references/rules.md#wrk-007-one-piece-of-work-one-issue-no-command-files-issues-on-its-own)):
it posts the report proper as the retro issue's closing comment and closes the issue. The report
opens with `<!-- se:retro-report -->` and lists each finding, numbered, with its class's fix, its
home and its kind:

- `work`: SE bundles these into as few work issues as the work needs, each naming
  `retro #<n> finding <k>` for every finding it takes;
- `decision`: for the owner's decision list.

Then what went well and what follows. The facts and the block stay in the retro doc, which the
report links at the integration branch's commit (`<!-- se:retro-doc <sha> <path> -->`), where the
next collect and overhaul read them. A report over GitHub's 65,536 characters is posted as
numbered parts in order, never cut. Without gh it prints the comments and the close as a plan.

`scripts/overhaul.py` holds the overhaul commands, which ask, rarely, whether the design is still
right. SE starts one and runs it as its issue says, `read`, the judgment, then `file`.

`overhaul.py new` files the overhaul issue, `docs/overhaul-<yyyymmdd>`
labelled `discovery` beside the work labels, with the body of
[the overhaul template](.github/ISSUE_TEMPLATE/overhaul.md), through `work_tickets.py file`'s
filing path (`file --label discovery`): once, so an open overhaul answers a second `new`.

`overhaul.py read` writes the draft:

- every live rule of the rule book with what checks it, read from its implementations: a test (it
  names the tests or the suite), judgment ("by judgment"), a check (it links a script, or names
  neither);
- the retros closed since the last closed overhaul (titled `docs/overhaul-...`), or in the whole
  history where none has, each from the block of the retro doc its report links: its sizes, its
  broken rule checks, its findings by kind and the previous retro's findings it scored, and the
  finding classes more than one of them named;
  - of those findings, how many closed or recurred, and, where the
    [overhaul countdown](#overhaul-due) is on, how many were too early to score apart;
- the previous overhaul's findings, each with the issues that name it
  (`overhaul #<n> finding <k>`) and their state (`closed`, `open` where one is still open, or
  `none`; `too early to score` instead of `open` where the [countdown](#overhaul-due) is on);
- the pruning facts (`facts`, below), beside the previous overhaul's counts.

It ends in a JSON block under `<!-- se:overhaul-yaml -->`, which the next overhaul reads. Without
gh it prints its reads round by round and takes the answers from `--answers <dir>`, as `retro.py
collect` does.

`overhaul.py file` files a judged overhaul. The judge fills the draft's block:

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

`overhaul.py facts` is an overhaul's pruning facts, read from the checkout (default: the current
directory). It only reads, uses the standard library alone and judges nothing: each fact is a candidate the overhaul judges by the rule book's
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
