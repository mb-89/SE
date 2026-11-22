# se: systematic engineering

A process plugin for AI agents. Its main agent, **SE**, is the one a person talks to; its sub-agents
are the integrator, the worker and the reviewer. With them come their skills, issue templates and the scripts they
call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Getting it running

On a machine with only its package manager: install Git, clone SE, run RUNME once. RUNME installs
what is missing (Claude Code, uv, SE's binary) and starts the SE agent in the folder it runs from;
a second run installs nothing. `<owner>/<repository>` is explained under [Install](#install).

- Windows: `winget install --id Git.Git -e --source winget`, then in a new terminal `git clone
  https://github.com/<owner>/<repository>`, then right-click `RUNME.ps1` > Run with PowerShell, or
  `powershell -ExecutionPolicy Bypass -File RUNME.ps1` in the clone. PowerShell drops a bare `--`
  before the script sees it, so a PowerShell line writes it as '--'.
- Linux: `sudo apt-get install -y git` (Debian, Ubuntu) or `sudo dnf install -y git` (Fedora), the
  same clone, then `./RUNME.sh`.
- macOS: `brew install git`, the same clone, then `./RUNME.sh`.

`./RUNME.sh --help` prints SE's command line; afterwards `claude --agent se:se` starts the agent in
any folder. A failed run from Explorer closes its window: run the second Windows line in a terminal
to read why. Where Claude Code already has SE from GitHub, RUNME stops with the one command to run;
read it the same way.

- **The Claude app:** a cloud session started in an environment set up for SE starts as the SE
  agent. Its repositories are the ones the session works on (SE needs none); its network access
  the default, Limited with Allow package managers ticked, which reaches `github.com` and
  `release-assets.githubusercontent.com` (SE's clone and its binary's release).
  - Its setup script is the one under [Claude Code cloud](#claude-code-cloud), which clones SE into
    `~/.claude/skills/se`, and its variable `SE_DEFAULT_AGENT=se`.
  - Elsewhere, the first message picks the agent: `Act as the se agent defined in
    <se>/.github/agents/se.agent.md.`, which works in Copilot too.
- **Cowork, untested:** give the Cowork session the folder that holds SE's clone, and send the
  first message above with that folder as `<se>`. Nobody has tried it yet.

## Install

One step per place. What each agent does is in its own file in [src/agents/](src/agents/).
`<owner>/<repository>` is the owner and repository of the SE you install from, on GitHub (`uv run
python scripts/se_home.py tracker` prints it in a clone); no file of SE names it.

| Place | Install | Choose SE | Check that it loaded |
| --- | --- | --- | --- |
| Claude Code | from the clone: [RUNME](#getting-it-running), whose agent start runs `claude plugin install se --marketplace <clone>`; a copy from the GitHub marketplace (`<owner>/<repository>`) has no `.git`, so it gets no core release without `go`, no refresh at start and no documentation URL | `claude --agent se:se`, or `"agent": "se:se"` in a project's `.claude/settings.json` | `claude plugin list` shows `se@se`; `/agents` lists `se:se`, `se:integrator`, `se:reviewer` and `se:worker` |
| Claude Code cloud (claude.ai/code) | the environment's [setup script](#claude-code-cloud); an environment may cache its output, so a session can start with an older clone, which SE [refreshes at start](#start-and-refresh) | each session's first prompt, or SE_DEFAULT_AGENT=se on the environment ([below](#claude-code-cloud)) | `claude plugin list` shows `se@skills-dir`; ask the session which `se:` agents and skills it has: `se:se`, `se:integrator`, `se:reviewer`, `se:worker`, `se:catch-up`, `se:decision`, `se:work-model` |
| GitHub Copilot in VS Code, in se's own checkout | nothing: `git clone https://github.com/<owner>/<repository>` and open it; VS Code reads its `.github/agents/`, `.github/skills/`, `.github/hooks/se.json` and `.github/mcp.json` | in the Chat view pick the session target **Copilot** and the agent `se` (where `se` is missing, turn on `github.copilot.chat.cli.customAgents.enabled`) | the agent list holds `se`, `integrator`, `reviewer` and `worker`, and **Configure Skills** `catch-up`, `decision` and `work-model`; the first answer opens with the greeting, its first line `SE <version> started: <n> skills, <n> rules, <n> sub-agents.`; asked `status`, the tool `se/status` answers `se: running in <checkout>, pid <n>, ...` |
| GitHub Copilot in VS Code, another repository | **Chat: Install Plugin from Source** with `https://github.com/<owner>/<repository>` (agent plugins, `chat.plugins.enabled`), or copy `.github/agents/*.agent.md` to `~/.copilot/agents/` and `.github/skills/*` to `~/.copilot/skills/`; a repository that opts in also runs `scripts/setup.sh <repo> --copilot` ([docs/copilot.md](docs/copilot.md#another-repository)) | as above | as above, `se/status` naming that repository |
| GitHub Copilot CLI | `copilot plugin marketplace add <owner>/<repository>`, then `copilot plugin install se@se` (or `copilot plugin install <owner>/<repository>`, which the CLI calls deprecated) | `copilot --agent se` in a folder the CLI trusts (it asks once; `--trust-folder` for one run) | `copilot plugin list` shows `se@se`; `copilot skill list` shows `catch-up`, `decision` and `work-model` from the plugin's `.github/skills`; in the session, the greeting as above and `se-status` answering `se: running in <project>, ...` |
| GitHub Copilot cloud agent (github.com), in se's own checkout | nothing: it reads the repository's `.github/agents/`, `.github/skills/` and `.github/hooks/se.json`; untested ([docs/copilot.md](docs/copilot.md#cloud-agent-optional-and-untested)) | the repository's **Agents** tab: start a task and pick `se` | its `sessionStart` hook hands the session SE's greeting, as above |

Copilot's details are in [docs/copilot.md](docs/copilot.md): what a token-less Copilot CLI already
showed, the opt-in for another repository, the self-test and smoke test, and the owner's checklist
for the first run with Copilot.

SE's skills read files in the plugin's folder and run its scripts with `uv run python`, and that
folder is outside your project. Claude Code asks you to allow this the first time. A headless
`claude -p` session cannot ask, so it refuses them unless you allow them in advance, for example
`--allowedTools Read Glob Grep Write Edit "Bash(uv run python:*)"`.

Commits carry no co-author lines: in VS Code, set `git.addAICoAuthor` to `off`
([VS Code 1.110 release notes](https://code.visualstudio.com/updates/v1_110)), as the
[public check](AGENTS.md#public-safety) refuses a `Co-authored-by` line in every pushed commit.

**Everything else arrives by itself.** At the first start SE runs
[scripts/bootstrap.sh](scripts/bootstrap.sh): it installs `uv` into the user's home, Python 3.11 or
newer through `uv`, and the project's [components](#modules); in a session it fetches and starts
[kern](#kern). It is quiet when nothing is missing.

Claude Code runs it at every session start from the plugin's hooks, Copilot from
`.github/hooks/se.json`, a fail-open observer: SE works under Copilot with its hooks never firing.

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
git clone --depth 1 https://github.com/<owner>/<repository> ~/.claude/skills/se || echo "SE: clone failed, this session starts without SE" >&2
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

An environment made for SE can set `SE_DEFAULT_AGENT=se` beside its setup script, in its
environment variables; a session started there then needs no first line: SE's start hands it the
se agent. Sessions that SE or an integrator starts keep naming their role in their first message,
which wins. Any other value hands over nothing and the greeting names it.

A running fleet shows in the sidebar as one section, the tag `SE`: SE's own session `SE`, each
project's integrator `SE/<project>/integrator` with its workers `SE/<project>/worker/<ticket name>`
under it, and SE's reviewers `SE/<project>/reviewer/<pull request number>` beside it, each title
printed by `work_tickets.py session-title` ([Visible sessions](src/skills/work-model/SKILL.md#visible-sessions)).

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
    (kern's README, "The standing file").
- **A late checkout gets a core.** In a session without sources that clones a repository with an
  `se.toml` after its start, SessionStart ran before the clone existed. The first hook whose working
  directory is inside the clone starts its core in the background, as SessionStart would have, and
  the hooks there then post to it ([scripts/se_hook.sh](scripts/se_hook.sh)).
  - A session whose folder is inside no git checkout, as one started without sources is, starts no
    core and says nothing of one; a checkout with an se.toml cloned into it then gets its core from
    its first hook there.
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
Documentation: <docs_url>`, the documentation's URL ([Documentation](#documentation)). Under it, and only then, one line per module or SE itself with a newer
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
- Then, still before the core starts, the hook resolves the tree of the project's components,
  `se_start.py start-components`
  ([docs/components.md](docs/components.md#required-and-optional-at-start)).
  - What is placed comes first: a clone at the commit `se.lock` locks is used without asking any
    remote, so a start with every component placed works offline; the rest is found by name and
    placed at its pin ([Modules](#modules)).
  - A required component missing anywhere in the tree stops the start. The greeting shows one
    message, opening `SE cannot start:`, with its path from the root (`se -> obs`), the remotes
    read, each with why it offered nothing (Git's message where it could not be read), and the
    remedy, a remote of an owner that offers it.
  - Nothing after the stop runs: no commit identity, hooks or core. Any other failure to resolve
    the tree stops it the same way, such as a found release whose tag points elsewhere than
    `se.lock` records.
  - An optional component missing is one line naming its path, and the start goes on.
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
- The project's components: where the project's `se.toml` sets `[project] components`, its
  listing command ([Project settings](#project-settings)), `check` runs it in the checkout and
  caches its table; the greeting names, one line each, a component offered and not installed and
  an installed one with a newer release, with installed and newest version.
  - Each line names the command that takes it, the listing's `install <name>` or `update <name>`;
    SE never runs it.
  - A listing that fails, prints no table or runs past 60 seconds is one warning line, and the
    greeting still appears; without the setting nothing runs and nothing prints.
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
- An installed SE older than the project's se: where the project's `se.toml` uses a key or
  table the installed SE does not know, the start's modules step fails or places nothing, and the
  greeting's update check names the same cause.
  - Such a table is `[components]`, which replaced `[modules]` in se 6: an SE before 6 reads no
    component of it, and an SE 6 refuses a `[modules]` table, naming the rename.
  - The remedy is a newer installed SE: `uv run python <se>/scripts/se_start.py refresh`, or a
    new session, whose start moves it.

### Kern

Nobody starts the core by hand. SE builds its own binary, `se`: kern's core with SE's Go components,
released as `se-v<version>` that `components/release.toml` owns. `scripts/se_modules.py app-binary`
is bootstrap's one reader of the binary to run — SE's `se`, or the bare kern for an application with
no Go components. The plugin's hooks start the binary and post every session event to it:

- **kern at its pin:** the `se` binary is built on the kern `se.toml` `[components.kern]` pins
  ([Modules](#modules)), its clone in `.se/modules/kern`.
  - Before the core starts, the start syncs the installed SE's kern where that clone is missing
    or not at the commit `se.lock` locks, both read from the files alone, so an SE at its pin
    starts no process for it.
  - Where that fails, the session goes on without it and the greeting names the cause. A project
    that is SE's own checkout syncs it in the modules step.
- **SessionStart**, [scripts/bootstrap.sh](scripts/bootstrap.sh) `--hook`: for a project inside a
  git checkout, where `~/.se/bin/<name>-<version>` is on the machine, it runs `<name> start` for the
  project, which returns at once, and hands the core the session's start, which takes the session's
  lease. It names the binary in `<project>/.se/.runtime/kern.path` for the later hooks.
  - For a project inside no git checkout it runs none.
  - `~/.se/bin/<name>` links to the version in place (a copy where the file system makes no link),
    and Claude Code's env file puts `~/.se/bin` on the session's PATH, so `se status` works there.
- **The first start of a version** reads the release's `SHA256SUMS` (one small read). Where it names
  this platform's archive, the archive is fetched, checked against its line and unpacked in the
  background, and the core then starts.
  - Where no release matches, the binary is built from its folder (SE's `components/`, on kern's
    clone at its pin; the bare kern in that clone) with `go` in the background, and the greeting
    says so; without `go` it failed, and the greeting names both causes.
  - The background half runs in its own process (`setsid` where there is one), so the hook's end
    does not end it.
- **RUNME** places the binary once, with `bootstrap.sh --binary` (RUNME.conf's `get se` line): it
  fetches or builds `~/.se/bin/<name>-<version>` in the foreground, links it and starts nothing.
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
  pages `timeline.py` and `deck.py` build, `se.py`'s scaffold and `se_guidance.py`'s guidance.
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

### The MCP door

`se mcp --root <checkout>` is SE's MCP server over stdio, kern's door (kern's README "The MCP
door"), for every agent host that reads an `mcp.json` (Claude Code,
Copilot in VS Code and its CLI): a host whose `mcp.json` names it calls SE's read-only commands
through it as tools. The host spawns it as the session starts; nobody starts anything else.

- **What the host runs.** The launcher `scripts/se_mcp.sh --root <project>`, or its PowerShell
  twin `se_mcp.ps1`: standalone, it reads only the release pin (`components/release.toml`).
  - It runs `~/.se/bin/se-<version>` ([Kern](#kern)), or the binary `SE_MCP_BIN` names, as
    `se mcp --root <project> --home <this SE>`.
  - Standard output carries MCP alone; the rest goes to `<project>/.se/.runtime/mcp.log`, or,
    for a plugin install's session folder with no `.git` in it or above it, `~/.se/.runtime/mcp.log`.
- **Where the binary is missing** the launcher answers at once as a door of one tool, `status`,
  whose calls say `not-installed` and name the setup to run, SE's start (`scripts/bootstrap.sh`).
  That fetches the binary and checks it against the release's `SHA256SUMS` in `~/.se/bin`; then
  restart the server. The launcher fetches nothing itself, so no host waits on a download.
- **Declared per host, generated** by `scripts/se_plugin.py build`:
  - `.github/mcp.json` for Copilot in a checkout of SE;
  - the `mcpServers` entry of Copilot's plugin manifest `.github/plugin/plugin.json` for a plugin
    install, the plugin's root `${PLUGIN_ROOT}` in an argument only;
  - the `mcpServers` entry of the Claude Code manifest `.claude-plugin/plugin.json` only where
    `se.toml` `[plugin] claude_mcp` is on, the launcher run from `${CLAUDE_PLUGIN_ROOT}`; every
    Claude Code session with SE's plugin then starts the door, and Claude Code names its tools
    `mcp__plugin_se_se__<tool>` (`mcp__plugin_se_se__templates`);
  - a root `.mcp.json` only where `se.toml` `[plugin] root_mcp` is on; it is off, as Claude Code
    reads that file in every checkout.
- **A plugin install** runs the launcher in the plugin's folder with `--root .`; the launcher then
  serves the session's repository. It reads `SE_SESSION_CWD`, else the host's session folder,
  else, on Linux and macOS, its parent's working directory, and writes one line, `plugin <folder>:
  root <root> from <source>`, to that root's `.se/.runtime/mcp.log` ([scripts/se_mcp.sh](scripts/se_mcp.sh)).
  - Copilot's plugin root is `PLUGIN_ROOT`, its session folder `COPILOT_SESSION_CWD`; Claude
    Code's are `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PROJECT_DIR`, each read only under its own host.
  - Claude Code starts a plugin's server in the project itself, measured
    ([scripts/host-limits.toml](scripts/host-limits.toml), "plugin MCP door"), so there `--root .`
    is the project already.
  - A session folder that is no checkout gets no `.se`: that line goes to `~/.se/.runtime/mcp.log`.
- **A host that reads neither file**: `copilot mcp add se -- bash <se>/scripts/se_mcp.sh --root .`,
  or in VS Code `code --add-mcp
  '{"name":"se","command":"bash","args":["<se>/scripts/se_mcp.sh","--root","${workspaceFolder}"]}'`.
  - An installed plugin's `se` outranks `copilot mcp add`; then the door goes by hand, per
    session ([docs/copilot.md "The door by hand"](docs/copilot.md#the-door-by-hand)).
- **What the door does not cover.**
  - Where the `se` binary is not in place as the server starts (a fresh machine, or a cloud
    snapshot older than the pin), the door offers only `status` for that whole session; the way to
    a template there is the command line, `templates.py draft <template> --json`.
  - In a claude.ai cloud session the plugin is the clone in `~/.claude/skills/se` (`se@skills-dir`,
    [Claude Code cloud](#claude-code-cloud)); whether Claude Code starts that plugin's
    `mcpServers` is not measured.
- **In another repository**, one without a `wiring.toml` of its own, the door serves SE's tools
  from the SE the launcher lies in (the plugin's root, or the pinned module under
  `.se/modules/se`), and runs their commands against the project: kern's `--home` (its
  `cli.Source`), its processes placed in that SE with `KERN_ROOT` naming the project.
- **It answers at once.** Either handshake, `server/discover` of the MCP spec of 2026-07-28 or the
  legacy `initialize`, and `tools/list` come from the catalog the `se` binary reads without the
  core: its Go components, the checkout's `wiring.toml` and its components' declarations. Beside
  them it starts the core detached, or attaches to the one that runs.
- **It holds the session.** It takes a session lease once the core runs and renews it on every
  call. It returns the lease on EOF and on SIGTERM, so the core ends its grace after the last
  session; where the core ended idle or crashed, the door starts it again and takes the lease anew.
- **A call waits** up to 5 s for a core that is starting, then answers the error `starting` with
  its remedy (a tool result with `isError`): call again in a few seconds.

| tool | what | from |
|---|---|---|
| `status` | whether the core runs, and its health | kern |
| `greeting` | the live part of the [start greeting](#start-and-refresh): `retro-due/due` and `fleet/findings` | `components/cmd/se` `Greeting` |
| `integration` | `config`, `ready`, `capacity`, `fleet-check`, `settings-check`, `parity`, `metrics` | `components/integration` |
| `overhaul` | `overhaul.py facts` | `components/overhaul` |
| `tickets` | `work_tickets.py status` | `components/tickets` |
| `templates` | `list`, `draft`, `check`, `fill` | `components/templates` |

- **Read-only, command by command.** A script names the commands that change nothing in its
  `READ_ONLY_COMMANDS`, each with its MCP description, when an agent uses it; `work_tickets.py
  docs` writes `read-only = true` and that `mcp` line into its declaration. `work_tickets.py queue`
  syncs the checkout (git fetch and merge), so no tool offers it, and no command that writes.
- **Generated, never written per tool.** A command group with read-only commands is one tool,
  named in snake_case: `command` is one of them, `args` its arguments, `page` the page of a long
  answer.
- **Approvals stay the host's.** Every tool says `readOnlyHint` and not `destructiveHint`, which
  neither grants nor forces an approval. Allow a tool once per host: Copilot's CLI with
  `--allow-tool='se(<tool>)'`, Claude Code with the permission rule `mcp__se__<tool>`, VS Code
  through "Chat: Manage Tool Approval".
  - The door the Claude Code plugin declares takes the rule `mcp__plugin_se_se__<tool>`, such as
    `mcp__plugin_se_se__templates` for a session whose permission mode asks before a tool runs.
- **Checked.** The door's catalog check refuses a read-only command without an `mcp` line, and
  so does `work_tickets.py docs`, which writes it. `components/cmd/se/mcp_test.go` holds SE's
  catalog to the check, and the door to its contract with the Go SDK's client against the built
  `se mcp` and the real core, once per handshake.

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
  - The state of each Copilot guard in the project's `se.toml` `[copilot]`, a guard that is off a
    note ([docs/copilot.md "What a session costs"](docs/copilot.md#what-a-session-costs)).
  - Each hook and MCP server registration a host reads, and whether the scripts it names exist;
    `gh` signed in or not; the reach of the hosts SE fetches from.
  - The instruction files a host may read beside or instead of `AGENTS.md`: `CLAUDE.md`,
    `.claude/CLAUDE.md`, `CLAUDE.local.md` and `copilot-instructions.md` under `.github/`, looked
    for in the project and each folder above it up to home, each a note naming its folder and
    whether git tracks it, never its content; a note refuses nothing.
- **Read-only**: it writes nothing, starts nothing that stays, fetches nothing and calls no service
  beyond `gh auth status` and one HEAD request per host, each with a short timeout. Nothing runs it
  automatically.
- **Private**: it prints no token, bus user, environment value, e-mail address or path outside the
  checkout; home is `~`, the checkout `<checkout>`.
- Its checks are pure functions of the facts it gathers, which its docstring owns.

### Host sizes

`uv run python <se>/scripts/host_size.py report [--root DIR] [--tools FILE] [--json]` measures
the generated layouts (`AGENTS.md`, `.github/agents`, `.github/skills`, `agents/`, `skills/`) and,
with `--tools`, the JSON of a `tools/list` answer, against what each agent host caps.

It prints one row per host, file or tool and subject, "over", "under" or "not measured", the
largest overrun first, then the bytes a session is always handed apart from those it loads on
demand.

- **The host facts** are one dated data file, `scripts/host-limits.toml`, whose header owns its
  layout; a limit it lacks is "not measured", never "under".
- **A report only**: it writes nothing, always exits 0, and no hook, check, build or suite runs it.

## Documentation

se's documentation is one HTML file, published at the GitHub Pages site of SE's home,
`https://<owner>.github.io/<repository>/`, which `scripts/se_home.py` derives from the checkout's
origin; a project that publishes elsewhere sets `docs_url` in `se.toml` `[project]`.

`docs.md` is its manifest: it lists se's notes as chapters and restates none of them. The obs
component (`[components.obs]` in `se.toml`, found beside SE's repository) builds it:

```sh
uv run python scripts/build_docs.py --destination <file outside the repository>.html
```

obs builds it, and every decision deck, with the adapter component `html`, which it finds among
the machine's installed components, else in its own tree. `build_docs.py --install-html` runs
`obs-components install html` and fails, naming that command, where obs finds no `html`; the setup
scripts in se's checkout, the `check` job and the docs workflow run it before they build.

The build reads a copy of the repository in which no note asks for a verdict, so the worked
decision note shows as a page to read, with no Send; the note itself still asks, for the decks
built from it.

In the same copy the rule book shows as one table of its rules, grouped by section, each row
opening to its rule; `scripts/rule_book.py` makes the table and a note per rule from `rules.md`.
`--document <file>` also writes the obs Document the page was built from.

The README is the first chapter and the command line the second: `docs/command-line.md` holds one
`cmd` fence, `sh RUNME.sh --help`, so the chapter is SE's help as each build prints it. The build
passes obs `--execute-commands`, which lets obs run every `cmd` fence of the chapters and every
`cmd silent` fence of any Markdown file in the copy it reads; a failing one fails the build.

The build first runs RUNME once in that copy, so what RUNME installs lands in the home and in the
copy, never in the checkout. RUNME there takes the pinned `se` from `~/.se/bin`, as the copy holds
no `.git` to fetch it by and no modules to build it from: on a machine that lacks it,
`bash scripts/bootstrap.sh --binary` in the checkout places it first, as the docs workflow does.

Any obs warning fails the build, so a broken link, a missing note or a paragraph longer than obs's
default limit fails it. The suite runs the build (`tests/test_docs.py`),
and the workflow `.github/workflows/docs.yml` builds and publishes it to GitHub Pages on each push
to `main`; a failed build publishes nothing, so the previous artifact stays.

The Timeline, `timeline.html` beside the documentation, builds itself from the issues and
releases of the repositories in `se.toml` `[timeline]`: SE, obs and kern (a bare name lies beside
SE's home). The same workflow rebuilds it hourly and on each issue event.

It is one obs table, a row per issue or release: its repository, place, date, number, title and
status. It groups the rows by place (Today, Needs you, Next, Backlog, Done), puts the newest first
in each, and pages them; a backlog idea shows as waiting for your input. When the page opens, it
asks GitHub for what changed since the hourly snapshot and shows that where GitHub answers.

[scripts/timeline.py](scripts/timeline.py) owns what shows where, the live read, and how a
repository the workflow's token cannot read shows as a named gap instead of failing the build.

## Modules

A repository pulls the parts it builds with (se itself, kern, obs, styles, other repositories) as
**components**, each found by its name on the checkout's remotes and pinned to a commit or a
semantic version range ([docs/components.md](docs/components.md) owns the design).
`scripts/se_modules.py` implements this section; its invocation is in [Commands](#commands).

### `se.toml`

The host, the repository that uses them, lists its components in `se.toml` at its root, by name,
under `[components]` (se 6 renamed it from `[modules]`, which is refused naming the rename):

```toml
[components.obs]
ref = "<40-hex commit SHA>"                  # the pin
path = "skills"                              # optional: the part of the component that is used

[components.style]
version = "^1.4"                             # in place of ref: a semver range of its release tags
optional = true                              # the host works without it; absent: required

[components.kern]
go = "components/go.mod"                     # in place of ref: the version that go.mod requires
```

| Key | Meaning |
|---|---|
| `ref` | the pin, a full commit SHA. Any commit on the component's `main` can be pinned, not only releases; `update` moves it. |
| `version` | in place of `ref`, a semantic version range of the component's release tags `vMAJOR.MINOR.PATCH` ([Project settings](#project-settings) says how a component releases): `^1.4` (1.4.0 up to 2.0.0), `~1.4.2` (up to 1.5.0), `1.4` (any 1.4.x) or `1.4.2` (exactly). An entry pins one of `ref`, `version` and `go`. |
| `go` | in place of `ref` and `version`, for a Go module: `true` (the root's `go.mod`) or a relative path to a `go.mod`. The pin is the exact version that `go.mod` requires of the module path `<name>` (`require kern v0.14.1`), resolved to the tag `v<version>` and locked in `se.lock` as a range is; a `go.mod` without that require, or a version no owner tags, is refused. `update <name>` refuses and names the `go.mod` line to change instead (`update --all` leaves it as it is). A local checkout's version is its `release.toml` `version`. |
| `optional` | `true` marks a component the host works without: `sync` names one no owner offers in one line and goes on. An entry without it is required, and a required one missing fails, naming its path from the root, the remotes read and the remedy. |
| `path` | optional relative directory inside the component; without it the whole component is used. |
| `url` | refused: an entry names no address, since a component is found by its name. A machine that needs another place says so in the machine-local file below. |
| `se.lock` | next to `se.toml`, it records, as `[components.<name>]`, the release each `version` range and `go` pin of the tree chose, with its version and commit; `sync` and `update` write it and the repository commits it. |
| Component names | the name of the component's repository, compared without case: 1 to 32 letters, digits and `-`, starting with a letter or digit. Other keys are errors. |
| The component `se` | se itself; its pin is the se the [public check](AGENTS.md#public-safety) must run: exactly its `ref`, or any se whose `se.toml` version its `version` range admits. |

A common repository lists only components that are public. Work-only components on private hosts
are listed the same way, in a work repository that uses the common ones; a common repository never
names them.

#### Finding a component

`sync` and `update` find each name as [docs/components.md "Finding a component"](docs/components.md#finding-a-component)
says, reading only the checkout's own Git configuration:

- The remotes: `origin` first, then the others in the order Git lists them; each remote's host
  and owner come from its address (`scripts/se_home.py`); a local path offers nothing.
- The mark: on `github.com` the owner's repositories with the topic `component` are listed once
  per run, with the login of `GH_TOKEN` or `GITHUB_TOKEN` where one is set. The repository named
  like the component is reached as its remote is, with its name in place of the remote's.
- An owner the host cannot list is one line, and finding goes on with the next owner. On a host
  SE lists nothing of, or where the listing cannot be read, the repository beside the remote is
  read directly, its mark unchecked, in one line. `SE_COMPONENT_LISTING=off` does so everywhere.
- The releases: its `v` tags, read without fetching objects (`git ls-remote --tags`); the first
  owner that offers a release the pin admits wins, and its highest admitted release is taken.

A clone already at its locked commit is used without asking any remote. A found release whose tag
points to another commit than `se.lock` records is refused, naming both commits and
`se_modules.py update <name>`, so a stand-in never replaces a locked component silently.

Another owner's components join by adding any one of that owner's repositories as a remote; a fork
named like a component under such an owner stands in for it where the pin admits its release.

#### The tree

Resolving is recursive: each placed component's own `se.toml` `[components]`, read from its
release (a local checkout's working tree), is resolved the same way, and every component of the
tree is placed in the root's `.se/modules/<name>`. A release whose `se.toml` lists no
`[components]` lists none.

- One version per name: a name the tree reaches twice is one component, and each host's pin must
  admit its release; where they admit a common one the newest is taken, else `sync` fails naming
  both paths and both pins.
- A name already on the path is that component: an entry that names a host above it on the path,
  the root included, is that host itself, and its pin is checked against that host's version, not
  resolved again.

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

Whatever `public_check` says, `push` (and every command that pushes through its gate) pushes only
a local branch, never a refspec, tag or commit, and refuses one that carries commits another remote
holds but origin does not: a project kept on two hosts shares trees, not histories. Only origin's
remote-tracking branches count as held by origin; a local tag proves nothing about it.

The check before every push knows its destination remote: it gates each commit that remote does
not hold yet, and a local-list line `remote:<remote name> <regex>` stops only the pushes to that
remote, so one checkout with two remotes keeps a term from one while the other may receive it.
The local list's line forms are [Public safety](AGENTS.md#public-safety)'s.

`components` is the project's component listing command, an argument array run without a shell
in the checkout, such as obs's `["uv", "run", "obs-components"]`.

With no argument it lists, never installs: a table headed `component  kind  installed  newest  repository`, two spaces or more
between columns, as obs-components prints it. SE's start reports its offers
([Start and refresh](#start-and-refresh)); unset, it runs nothing.

`version = "MAJOR.MINOR.PATCH"` is the project's one semantic version, published as the git tag
`vMAJOR.MINOR.PATCH` on its integration branch; consumers pin ranges of it
([`se.toml`](#setoml)). Nobody types it after the first: `integrate` releases, on its landing
branch, what was integrated since origin and the last tag, as `work_tickets.py push` of the
integration branch does.

Each integration is a first-parent commit whose message starts `Integrate <branch>` and states its
kind in the trailer `Release-kind: major|minor|patch`: the merge `integrate` builds, and on the
integration branch the one commit it lands as ([Landing on main](#landing-on-main)).
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

`integrate` also runs it on its merge, before the suite, and commits what it rewrites into the
landing: a generated file that carries the version, added on a branch before `main` released,
never makes the branch stale, and the suite's verdict is recorded on the merge's tree.

#### Commit checks

```toml
[commit_checks]
forbids = ["go", "run", "./cmd/kern", "forbids"]
```

`[commit_checks]` names a project's own commit checks, each a name and its command, an argument
array run without a shell. se's commit hook (`.githooks/pre-commit`, after the
[public check](AGENTS.md#public-safety)) runs each in a copy of the staged tree, so code that
breaks one is refused before it is committed, not first at landing.

- **The staged tree.** The copy holds the index, the tree the commit records: an unstaged edit
  and an untracked file decide nothing. The table is read from the staged `se.toml`, and the
  check's git variables are removed, so its git never reaches the committing repository.
- **The refusal.** A check that exits non-zero refuses the commit, naming the check, its exit
  code and its command, with its output below; one that cannot start refuses it too. Each passing
  one prints `commit check <name>: passed`.
- **Every project.** A repository that runs se's hooks from se as a module runs its own table
  ([Public safety](AGENTS.md#public-safety), "Hooks"); unset, the hook runs nothing more.
  `scripts/commit_checks.py` owns the table and the run.

#### Landing on main

Every integration lands on the integration branch through a landing pull request and its check
`check`, as one commit on the tested base: se's `main` ruleset allows no force push and no
deletion, keeps the history linear and requires `check`
([AGENTS.md "Public safety"](AGENTS.md#public-safety)). How that commit reaches `main` is the
setting `landing` below. `work_tickets.py integrate` does all of it:

1. It merges the work branch into origin's newest integration branch on `land/<branch>` (the
   `Integrate <branch>` merge with its `Release-kind` trailer), runs the complete suite, the
   output regeneration, the project checks and the public check, and releases there.
   - A fast-forward landing then writes the one landing commit: that tree on the base, as the
     project identity in both roles, with the merge's title and message less each line that
     holds an e-mail address (a `commit_trailer` co-author line, say).
2. It pushes `land/<branch>` and opens a pull request of it into the integration branch, or reuses
   the one still open from an earlier attempt.
   - Its title is the merge's title, `Integrate <branch>: <the first sentence of the work issue's
     Goal>`, never a commit's subject. Tracker references (pub-004's forms) are dropped from it,
     with an aside such as `(PR #<n>)` that holds one, and its punctuation tidied; without a
     usable Goal, or with fewer than two words left, it is `Integrate <branch>` alone.
   - A Goal that opens with a list's lead-in gives that lead-in. A sentence of up to 200
     characters stays whole, and a long branch name lowers the 200 so the title keeps within
     GitHub's 256. A longer one ends at its last clause end (a comma, semicolon, colon or dash)
     within them before "and", "but", "so" or "while", else at its last, never with "..."
     (`work_tickets.py` `at_boundary`).
   - A clause end inside brackets, quotes or code does not count, nor the one that closes a
     leading clause such as "Where ...", "If ..." or "With ..."; without one that counts, the
     sentence ends at its last word within them. The work template warns where a Goal's first
     sentence runs past 120 characters.
   - Its description is always a link, never the report, so it fits GitHub's body limit and any
     tool argument whatever the report's size: `Refs <work issue>`, the work pull request, and the
     marker `<!-- se:field-report-in <n> -->`.
   - The check's field-report step reads that marker and checks the description of work pull
     request `<n>`, the field report, against its work issue
     ([AGENTS.md "Public safety"](AGENTS.md#public-safety)).
3. It waits for the check `check` on the landing head, polling every 30 s for up to an hour; a
   conclusion other than success merges nothing and escalates. A repository whose host has no
   runners accepts the integrator's status instead ([Landing without CI](#landing-without-ci)).
   - The run it waits for and names may be an edit's, which took its suite's result from an
     earlier run of exactly that tree and names it ([Edits reuse the suite](#edits-reuse-the-suite)).
4. It lands that head, once origin's integration branch is still the tested base; where it
   moved while it waited, it merges nothing: integrate again.
   - A squash landing squash-merges at exactly that head with the merge's message as the commit
     title and message: `Integrate <branch>: <goal>` and the `Release-kind` trailer, and no
     ` (#<number>)` or `Co-authored-by:` line GitHub's defaults would add.
   - A fast-forward landing pushes the integration branch to exactly that head, which `check`
     passed: GitHub writes no commit and marks the pull request merged. Where origin refuses the
     push, it stops with the rule change below and never falls back to the squash merge.
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
    finds open), `pull_request_read` `get_check_runs` until `check` passes, and for a squash
    landing `merge_pull_request` with `merge_method` squash, the exact title and message and
    `expectedHeadSha` at the landing head; where trust is on, the
    [record](#trusted-landings)'s two steps come first;
  - the session runs those steps with its GitHub tools;
  - `integrate --read-back <branch> --landing-pull <number> --check-run <url>
    --landing-description <file>` then, for a fast-forward landing, pushes step 4, and reads
    step 5 back through `git fetch` alone (origin's integration branch one commit on the tested
    base, with the tested tree).
  - It finishes everything local of step 6 and prints its close-out plan: the work pull request's
    comment and close, and the work issue's comment, label and close.
  - Before that it checks the landing pull request's description, saved after the merge: it must
    end in the plan's [metrics](#metrics) line, or the read-back fails and closes nothing.
  - An integration-fix commit, one the integrator pushes onto `land/<branch>` after the hand-off
    (a lock move), is recorded with `integrate --record-fix <branch>` before the read-back.
    - Each fix commit has one parent on the tested landing and is the project identity's, author
      and committer, with no e-mail address or tracker reference in its message, as every landing
      commit is; anything else is refused and nothing is recorded.
    - It runs the complete suite, the project checks and the public check on the new head, makes
      that head the tested landing in `.se/handoff/` and prints the plan again at it: a landing
      pull request already open is reused, and the merge expects the new head.
    - The read-back then compares against that head and names the fix commits. A head that
      changed without the command reads back with another tree and is refused, naming the
      command; a fast-forward landing takes no fix commit, its fix goes to the work branch.
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
- **One call.** `integrate`, `refs request`, `refs apply`, `file`, `route`, `fleet-check` and
  `start` (`work_tickets.py` `STREAMED_COMMANDS`) run as one call through kern's `call.`, from the same
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
  - Each told step's note opens with its sequence number in the call, `step <n>` (`se_relay.py`
    `numbered`), under the call in the hook and in `next`; `next --step <n>` refuses a step the
    relay no longer waits for with one line naming the current one. The two reads of a landing
    pull request in a row, its merge confirmation and its read-back, each name their purpose.
  - kern refuses an answer to an old step the same way, in one line on its hook
    (kern's GitHub component, its README "The verb `step`: a write tool through the relay").
  - A relay landing (`integrate`, `rehearse`) starts with one line: run each long wait in the
    background and call `next` after each, as a told step reaches the agent only when a tool call
    ends. It reads no CI suite time past the relay, and says once that it skipped it.
  - `integrate` reads the pull request first, then runs its local guards, the field-report guard
    against the branch's merge base and the merge, and only then reads the work issue: a branch
    that cannot land fails after that one read. A checkout detached at origin's integration branch
    (a cloud session's source checkout) is moved onto the branch first, fast-forwarded there.
  - The core fails a step of the command only after ten minutes without its answer, a line or a
    beat (`StepWait`, the work model's stall rule), not after one: the wait was raised, the hook's
    beat does not count, and the command's process beats every 5 s until its answer is out.
  - A step's answer reaches the core however long the step ran: kern's bus gives a placed
    process's answer no time limit, where NATS's default of two minutes refused the answer of any
    longer step, such as a landing's suite, release and push. An answer the bus refuses all the
    same fails the step at once, naming why, instead of waiting out `StepWait`.
- **The fallback.** Without kern, on a token backend or with `SE_KERN=off`, each command keeps its
  file-based hand-off above. A call kern refuses before it says anything runs directly; one that
  fails on the way is reported and never run twice, as it writes.
  - A command that falls back says so first, on stderr, and why: `se: <command> fell back to the
    file-based hand-off: <why>`.
- **Rehearsing a relay landing.** `work_tickets.py rehearse` runs a whole landing through the
  relay on the scratch branch `--base` names, without holding the integration branch: a relay
  read, a local phase `--gap` makes slow on purpose, the push of `rehearse/` and the base's name,
  the landing plan into the base (pause search, pull request, `check`, squash merge), the read-back.
  - It refuses the integration branch, `land/…` and `rehearse/…` as its base, resets the base to
    the integration branch's tip at each start, so no rehearsal builds on an earlier one, releases
    and tags nothing and touches no issue. A detached checkout is moved as for `integrate`.
  - It runs only as one call through kern's relay, and only when someone runs it.
- **Tested** against fake sessions in the suite (`tests/test_work_ticket_issues.py`,
  `tests/test_work_tickets.py`) and against the real core: `tests/beside_se_relay.py` runs
  `fleet-check` as one call whose reads a simulated session answers on the hook, from the
  checkout's script and from a plugin's copy, then the fallback once kern stops.
  - kern's `contract/longstep_test.go` asks a relay step after a local phase longer than two
    minutes (`se.toml` `[tests.beside.kern-long-step]`), nightly and where a change touches the
    files it guards ([Test budget](#test-budget)); its fast guards run in kern's own tests.

The landed commit carries the release's `se.toml` version, so the release workflow tags it and
the docs workflow publishes it, as both run on every push to `main`.

```toml
[integrate]
landing = "squash"
```

`landing` is `"squash"`, built in: GitHub squash-merges the landing pull request and commits it
for the merging account (web-flow committer, the account's `users.noreply.github.com` author),
which the identity gate and a public mirror's guard pass for the account that owns the
repository.

`"fast-forward"` lands the integrator's own commit, `mb <mb>` in se, with no address in its
message: `check` ran on exactly the commit that lands. The gate and the guard turn strict with
it and refuse GitHub's own commits like any foreign identity. It needs a ruleset that takes the
integrator's push, a person step for the owner:

- In the ruleset of the integration branch (Settings, Rules, Rulesets), remove the rule "Require
  a pull request before merging"; keep "Require status checks to pass" with `check`, "Require
  linear history", "Block force pushes" and "Restrict deletions".
- Then set `landing = "fast-forward"` in `se.toml`; obs and every project se lands for set it in
  their own.

One run can land the other way without a change to `se.toml`, to try a ruleset at the cost of
one landing: `integrate <pull request> --landing fast-forward` (or `--landing squash`).

- The choice holds for that run only and is kept in the hand-off's state, so `--read-back`
  finishes the landing the way it started, whatever `se.toml` says by then.
- A refused fast-forward push leaves the integration branch, the landing pull request and its
  branch as they were and falls back to nothing; integrating again without `--landing` lands as
  `se.toml` says. The integrate comment names the mode a flagged run used.
- The identity gate and a public mirror's guard keep reading `se.toml`: a flagged landing commit
  is `mb <mb>` either way, which both pass.

#### Component versions

The binary `se.toml` `[binary] release` names (SE's `se`, `components/release.toml`) has a version
of its own, which `se-release` cuts as its tag. As with the project's version, a branch states the
kind and the landing assigns the number, so branches open in parallel never claim the same one.

Its folder is its inputs: for SE `components/`, whose `go.mod` `require kern` is the kern it is
built on ([Modules](#modules)), so a branch that moves that pin changes `se`. kern releases from
its own repository.

- **The branch states the kind:** a branch that changes a component adds the header line
  `**Component kinds:** se patch` to its field report, beside its Release kind, and leaves the
  version in the `release.toml` alone; `field-report --check` refuses an unknown kind.
- **The guard follows on a work branch:** kern's release guard (`se.toml`
  `[tests.beside.release-guard]`) passes a changed component whose kind is stated, read from
  `$SE_COMPONENT_KINDS`.
  - `work_tickets.py suite` sets it from `.se/work/field-report.md`, CI from the pull request's
    description (`field-report --check --component-kinds-to`).
  - A landing and `main` set none, so there the guard refuses as before.
- **The landing assigns the number:** `integrate` writes the next version of that kind after
  `main`'s into the landing's merge, before the suite runs, for each component whose folder the
  merge changes, and names it with the tag the push to `main` cuts. A kind stated for no component is refused before anything lands.
- **A branch that still claims a number lands:** its raised version gives the kind (the highest
  part it raised), and the number becomes the next free one of that kind, said in the output.
  Where the claim conflicts with `main`'s version, the landing takes `main`'s version on top of
  the branch first and then assigns the number.
- **The pins move with the number:** every other file that pins a component's tag as `@<tag>`
  (none today) is on one list,
  `scripts/component_versions.py` `PINS`, and the landing moves each pin to the assigned tag in
  the same merge, also where the branch moved it by hand.
  - `tests/test_component_versions.py` fails where a file pins a component's current tag and is
    not on the list.

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

A repository turns it on with `release = "workflow"`, the copy of se's `release.yml` that
`se_workflows.py write .github/workflows/release.yml` writes ([Workflows](#workflows)), and a copy
of se's own [`.github/workflows/release-tag.yml`](.github/workflows/release-tag.yml), changed only
in `branches` to name its integration branch (se's names `main`), so that worker branches run
nothing.

Other repositories run se's workflows and actions at the se pin they choose, as copies se writes at
it ([Workflows](#workflows)), so a breaking change reaches them only when they move the pin.

### Fleet check

```toml
[fleet]
lease_hours = 3
restart_after_limit = false
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

With `--sessions <file>` it also reports each worker session stopped on a usage limit before it
delivered: the session tools' answers, the sessions `list_sessions` lists, each with the
`list_events` answer of its `result` and `rate_limit_event` events as `"events"`. The core holds no
sessions, so the check then reads the fleet itself.

`restart_after_limit` is off, built in: the report is all that happens. On, the remedy is to
resume the session once the limit lifts and comment `Restarted after a usage limit:` on its issue,
at most once per issue. [scripts/limit_restart.py](scripts/limit_restart.py) owns what counts.

### Dispatcher

`work_tickets.py dispatch` starts a fleet that stopped, with no model: an hour with nothing to start
costs no model tokens. It reads from GitHub alone:

- the startable work issues, as `ready` lists them: labelled `work` and `ready`, not waiting on a
  person (labelled `se-person` or `escalated`, or assigned to someone), with no open blocker;
- whether an integrator runs: an open landing pull request (`land/<branch>`), or in-progress work
  whose issue or branch moved within the [fleet lease](#fleet-check).

- Where startable work waits, no integrator runs and the fleet is not [paused](src/skills/work-model/SKILL.md#pause), `--fire`
  fires the scheduled task whose session is a fresh integrator, once, and names its session;
  `--dry-run` prints that fire and makes none. Anything else fires nothing and says why.
- The workflow [.github/workflows/dispatch.yml](.github/workflows/dispatch.yml) runs it every four
  hours. The integrator starts the next startable issue itself after each landing
  ([integrator](src/agents/integrator.md)); the dispatcher only restarts a fleet where none runs.
- Two repository secrets configure it, so no committed file names the task, its token or the
  service's host: `SE_DISPATCH_TRIGGER`, the fire URL of the scheduled task's API trigger as it
  shows it (an https URL ending in `/trig_<id>/fire`, which names the task's id), and
  `SE_DISPATCH_TOKEN`, that trigger's token. While either is unset, the workflow runs `--dry-run`.
- Setting them, and creating the scheduled task, are steps only the person takes
  ([Steps only the person approves](src/skills/work-model/SKILL.md#steps-only-the-person-approves)).
- Switch it off by disabling the workflow (the Actions tab, or `gh workflow disable dispatch.yml`)
  or by deleting either secret; an open `pause` issue holds it with the rest of the fleet.

### Settings check

`fleet/settings.toml` records settings the fleet runs on outside the repository: main's ruleset,
the scheduled tasks and the cloud environment. `scripts/fleet_settings.py` owns its format and
the doors.

`work_tickets.py settings-check` compares it with what the live doors read and prints each
difference in one line. It is advisory: it exits 0 unless `--strict` is given, and nothing runs it
on its own.

### Source parity

The same tree may be held by more than one remote or checkout
([More than one remote](src/skills/work-model/SKILL.md#more-than-one-remote)).
`work_tickets.py parity` compares two commits' trees, such as `origin/main` and
`mirror/main`, path by path, by mode and object id, and only reads (`git ls-tree`).

- **The lockfile rule:** a tracked file named `se.lock` or `uv.lock` is a dependency lockfile at any
  depth (`kern/template/uv.lock` too), since it records what resolved, which may differ where the
  source does not. Its content, presence and absence pass, and the command names it on one line,
  `lockfiles excluded:`. `work_tickets.py` `PARITY_LOCKFILES` owns the list; nothing else is excluded.
- **Every other path fails:** a path that differs is listed as `changed:`, or `only in <ref>:` for
  the side that holds it. Generated outputs (the layouts, `components/*/component.toml`) compare
  like source, and no text is normalized, whitespace included. Exit code 1 with any such path, 0
  without (`tests/test_parity.py`).

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
ends only with its work issue delivered; Copilot hands its `Stop` the same way
(`.github/hooks/se.json`), a check that fails open.

The hook scripts read both hosts' payloads alike: [scripts/hosts.sh](scripts/hosts.sh), the host
table, names the project variable, the host and cloud marks, the hook file's host selector and
Copilot's camelCase fields.

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
- Under Copilot it never refuses unless `[copilot] refuse_stop` is true: it names what is
  undelivered as Copilot's hook warning, as each refusal costs the person a model turn
  ([docs/copilot.md "What a session costs"](docs/copilot.md#what-a-session-costs)).
- A `SubagentStop` is judged only for a worker sub-agent (`worker`, `se:worker`), in the checkout
  it works in, one whose queue is for a work issue:
  - one its prompt names, else the one whose ticket queue its transcript (the event's
    `agent_transcript_path`) last touched, a path into `.se/work/` or a `--worktree`;
  - only where neither names one, the hook's `cwd`; where that holds none either, it lets the
    sub-agent end and says why.
- It also refuses in any checkout it judges, worker or not, while a changed file a template claims
  breaks it ([Templates](#templates)).
- Anywhere else (SE's own session, a person's session) it never refuses. Where it cannot judge it
  lets the turn end and says why: advice fails open.
- Without gh it judges by the answer file `.se/work/pull-request.json`, which
  `stop-check --pull <number> --pr-description <file>` writes from the pull request the session's
  GitHub tools opened; without either, it cannot judge.

### Work publication

A work branch is published only to the repository its work issue is for, never to whatever
origin happens to be. `work_tickets.py push`, and `deliver` through it, check origin before
anything is pushed or a pull request opened; the integration branch and landing branches keep
their own guards.

- The work issue is the one the checkout records (`intake`), titled like the branch.
- The repository it is for is its one `repo:<name>` label, which every work issue SE files
  carries. Without one, it is the repository holding the issue, or the checkout's own where that
  repository is the tracker the checkout routes its issues to.
- Origin passes where its repository name is that name, in any case: a name, not a host or an
  owner, so the rule holds wherever the project lives.
- Refused, naming the remedy, with nothing pushed: no recorded work issue, a recorded one titled
  like another branch, more than one `repo:` label, no origin, and an origin of another name.

### Late push

```toml
[deliver]
late_push = "warn"
```

A push of the work branch after its delivery makes the field report's Branch tip stale, and the
integrator refuses it at the landing. The pre-push hook names it at the push instead
([scripts/late_push.py](scripts/late_push.py)).

- `deliver` records the tip it delivers in the checkout, `.se/work/delivered-tip.json`; without
  gh, `stop-check --pull` records the Branch tip of the description it is given.
- The hook's guard, `work_tickets.py verified`, prints one line for a push of that branch at
  another commit: the delivery is now stale, the integrator will refuse it, and `deliver` must run
  again after the push. Before any delivery it says nothing.
- `late_push` is `"warn"`, built in: the push goes through. `"refuse"` refuses it; then the
  redelivery pushes through `deliver`, which records its tip first, or without gh through
  `work_tickets.py push --redeliver`.

### Review gate

```toml
[integrate]
review_gate = false
review_gate_risky = ["major", "rule-book", "role-file", "history"]
```

`review_gate` is off, built in: `integrate` reads no review. On, `integrate` refuses a risky change
whose work pull request has no reviewer's `pass` or `pass with open points` of the head that lands
(`review.py file`'s comment), before anything is pushed, naming the risks and this setting.

`review_gate_risky` lists the kinds that count as risky, all four built in: a major release, a
change to the rule book (AGENTS.md, the work model's rules.md), to an agent's role file
(`src/agents/`), or one that rewrites history. [scripts/review_gate.py](scripts/review_gate.py)
owns each kind and the decision.

Without gh the comments are read only for a risky change: the session saves them with its GitHub
tools (`issue_read get_comments`) and passes them as `--pr-comments <file>`.

### Test budget

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
    fails on another literal number, naming both files and both numbers ([Workflows](#workflows)).
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

The two budgets are apart, and neither spends the other's time:

- Each run prints and reports both times, `Suite: <result>; <time> (target, limit); go-components passed
  in <time> (target, limit)`, and the metrics line notes `beside_seconds` beside `suite_seconds`;
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

A sharded project records it with SE's two actions, as the copies SE writes into it at the se
pin ([Workflows](#workflows)), which the module command's `update se` moves with the pin:

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

A project's own `check` uses the action's copy at the se pin, as the sharded suite does
([Workflows](#workflows)); its copy of `se-pass-record.yml` calls the same copy,
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
`trust` runs the action from SE at the pin the copy names ([Workflows](#workflows)), and the vet
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

#### Landing without CI

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


### Platform legs and their queue

kern-platforms runs SE's start, hook and setup tests and its worktree removal tests on a Windows
runner, and `check` needs every leg; kern's own tests on Windows run in kern's repository's
`check`. The job keeps its name, which `work_tickets.py`, `ci_queue.py` and `check-rerun.yml` read.
The `se` binary is built for darwin; neither it nor the start and hook scripts are tested there.

A job's `timeout-minutes` counts only from when a runner takes it, so it
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

### Edits reuse the suite

A pull request's description and labels change many times without a new commit: the worker
corrects its field report, the integrator moves labels. Each change starts `check` again, on a tree
already checked, so such a run checks again only what it can change and takes the rest from an
earlier run ([scripts/ci_reuse.py](scripts/ci_reuse.py)).

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
  2026-11-10 work_tickets.py integrate #749: suite 130.5 s over its budget 120 s
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

Each machine may adapt components without touching tracked files. se only reads this file; it never
writes it, and nothing from it is written into `se.toml`.

The file is shared with `work_tickets.py`. `se_modules.py` owns `[paths]`, `[urls]` and `[hooks]`;
`work_tickets.py` owns the top-level `integrator_session`, `public_identity` and `commit_trailer`
settings, and the `[trackers]`, `[worktree_roots]`, `[repos]`, and `[mirrors]` tables. Each tool ignores sections
owned by the other.

```toml
[paths]
obs = "~/src/obs"                     # use this checkout of component obs if the directory exists

[urls]
"https://github.com/" = "https://mirror.example.com/github/"   # prefix rewrite, longest wins
```

| Setting | Meaning |
|---|---|
| `[paths]` | a local checkout per component name. If the directory exists, the component comes from it as it is (working tree, any commit, no git step), is never updated, and wins over finding; its own `se.toml` `[components]` is resolved from its working tree. If the directory is missing, the pin is used. Relative paths are relative to the file, `~` is expanded. |
| A local checkout's version | `sync` and `status` report the version its `se.toml` sets, and whether the component's `version` range admits it. A malformed version, or none where the entry pins a range, is an error naming that file. |
| `[urls]` | prefix rewrites applied to each address the finder reaches a component at, before any git step, for example a private mirror of a public host. The longest matching prefix wins. |
| `[hooks] core = "off"` | or `SE_HOOK_CORE=off` in the environment, which answers first: SE's session hooks then start no core and post to none, and nothing is uninstalled. The start still refreshes, syncs and greets, and the Stop check still answers. |
| `SE_TEMPLATES_GATE=off` | in the environment: SE's template gate judges no GitHub write on this machine, whatever se.toml `[templates] gate` says; unset, it follows se.toml ([Templates](#templates)). |
| `[paths] se = "<the installed SE's folder>"` | this machine's SE stays at its version, because the start's refresh leaves a local path alone ([Start and refresh](#start-and-refresh)). |

`[hooks] core = "off"`:

- Set in the file, it takes effect at the next session start.
- It does not reach the MCP server, which can start the core by itself: a host switches its own
  MCP server off. `SE_KERN=off` is another switch, which keeps commands direct.

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

| Command | What it does |
|---|---|
| `sync` | resolves the tree ([The tree](#the-tree)): a component with an existing local path is used from there; any other is found by name ([Finding a component](#finding-a-component)), cloned or fetched into `.se/modules/<name>` and checked out (detached) at its pin. A `version` range without a lock entry that admits it is resolved and locked first; a locked one stays where it is until `update`. A clone with local changes is never overwritten. Hosts ignore `.se/`. |
| `status` | one line per component of the root's list with its source (`local` or `pinned`), the directory it is used from, the pin and the drift (below). It never fetches. |
| `update` | finds the component again, its lock aside, and fetches it (through `.se/modules/<name>`, also when a local path is used), resolves the newest commit on its `main` (or `--to` a branch, tag or commit), rewrites only that `ref` in `se.toml`, prints the commits added (and dropped, if the pin moves back) and syncs. It does not commit; commit the new pin with the commit list. |
| `path` | prints the directory a component is used from (its `path` included), for tools that load it. |
| `--root` and `--local` | `--root <dir>` names the repository (default: the nearest ancestor with `se.toml`); `--local <file>` reads another machine-local file than `~/.se/local.toml`. |

- `status`'s drift is:
  - for a local path, the commits ahead of and behind the pin, uncommitted changes, or a pin the
    checkout does not have yet;
  - for a pinned component, whether the clone is at the pin and, for a `version` range, a newer
    matching tag the clone knows ("run update").
- `update`:
  - A `version` range moves to its highest matching tag in `se.lock` instead (`--to` is refused
    there; change the range).
  - `update se` also regenerates the project's copies of SE's workflows and actions at the new
    pin ([Workflows](#workflows)), so they run the version `se.toml` or `se.lock` pins.
- Git runs without prompts; credentials come from the machine's git setup.

### Workflows

A project calls SE's reusable workflows and actions as local copies, `uses: ./.github/...`, which
SE writes into it at its SE pin. A call of SE's own files would name SE's home, which differs on
each remote ([Neutral workflows](src/skills/work-model/SKILL.md#neutral-workflows)).

```sh
uv run python <se>/scripts/se_workflows.py write [<path>...]
uv run python <se>/scripts/se_workflows.py check
```

- What SE ships: `.github/workflows/` `branch-cleanup.yml`, `kern-battery.yml`, `kern-release.yml`
  and `release.yml`, and the actions `integrator-pass`, `suite-shard` and `suite-time` (`SHIPPED` in
  `scripts/se_workflows.py`). `write` writes the files it names, or regenerates those the project
  holds; each is a generated file whose first line names its source path, the pin and SE's place.
- SE's own workflows beside them are not shipped: `check.yml`, `docs.yml` and the templates backstop,
  `templates.yml`, run on SE's own events ([Templates](#templates)).
- The pin is `[components.se]`'s ([Modules](#modules)), else the one the copies carry, as in an
  application `se new app` made, or `--ref`.
- SE's place, how CI reaches it: where `sync` found SE, its clone's origin. One under the
  project's own owner on its host is `${{ github.repository_owner }}/<name>`, so the copies name no
  owner; any other names its own `<owner>/<name>`. SE is public, so the run's token reads it.
- Where SE's file reaches SE's own checkout, the copy checks out SE at the pin instead (in
  `.se/ci/se`, which the project ignores with `.se/`); a workflow keeps only its `workflow_call`.
- `update se` regenerates them, and `check` fails, naming the file and `write`, where a copy differs
  from what the pin generates: a project adds it to its integration checks, as SE runs
  `se_plugin.py check`.
  - `check` also fails where a workflow calls `suite-time` with a `shards:` number other than
    `se.toml` `[tests] shards` (default 1), naming both; an expression there is the run's, not
    compared.
- `branch-cleanup.yml` deletes a closed pull request's head branch, merged or not, and never a
  fork's, `main`, the default branch, `se`, `rehearsal`, a `ccr-` or `claude/` branch, another open
  pull request's head or a branch that moved since; its header owns the guards.
  - SE runs it on its own `pull_request` trigger; a project adds a trigger file of its own beside
    the copy, such as `branch-cleanup-on-close.yml`:

```yaml
name: branch-cleanup-on-close
on:
  pull_request:
    types: [closed]
permissions:
  contents: write
  pull-requests: read
jobs:
  cleanup:
    uses: ./.github/workflows/branch-cleanup.yml
    with:
      number: ${{ github.event.pull_request.number }}
      head_ref: ${{ github.event.pull_request.head.ref }}
      head_sha: ${{ github.event.pull_request.head.sha }}
      head_repository: ${{ github.event.pull_request.head.repo.full_name }}
```

- A project's own commit gate gates a pull request with the first call below, in the
  checked-out merge of its head into its base, the tree its landing lands, judged by that tree's
  allow list; its range is the commits its head holds and its base does not.
- It gates a push with the second call, by branch ([AGENTS.md "Public safety"](AGENTS.md#public-safety)).
  To the integration branch: the commits after its old tip, or where that tip is unknown those no
  other branch holds, gated whole.
- To a work branch, where the integration branch is the default branch and origin's ref for it
  exists: the commits after its old tip, or all its commits where that tip is unknown, without
  those the integration branch holds, which are not gated again; otherwise as to the integration
  branch.

```sh
python3 <se>/scripts/public_check.py --rev HEAD --range "refs/remotes/origin/$BASE_REF..$AFTER"
python3 <se>/scripts/public_check.py --rev "$AFTER" --push "$BEFORE" --branch "$BRANCH" --default-branch "$DEFAULT"
```

## New application

`se.py new app` ([its usage](#scaffold)) creates an application on kern, the core SE builds on
([docs/go-core.md "A bare application, and `se new app`"](docs/go-core.md#a-bare-application-and-se-new-app)),
in the new or empty folder its `--path` names: kern's template at SE's kern pin, the name filled in,
and git's first commit on `main` as the [project identity](#project-settings).

- **The pin:** the version SE's `[components.kern]` reads from `components/go.mod` and its tag
  `v<version>`, which the pinned clone's `release.toml` names, read by `se_modules.py`'s
  `kern_pin`. The template and kern's Go module come from that clone at the tag; a clone without
  the tag is refused, naming `se_modules.py sync kern`.
- **kern beside it:** kern's module path names no host, so it cannot be fetched: the application
  holds kern's Go module at the pin in `kern/` (every file of kern's repository but its template
  and its own project files: `.github/`, `se.toml`, `se.lock`, `AGENTS.md`, `pyproject.toml`,
  `uv.lock`, `.gitignore`), its `go.mod` requires `kern v<version>` and replaces the module by it.
- **What it holds:** the template's (kern's template README): its wiring,
  where `enabled = false` switches a component off, CI through kern's battery (its copy from the SE
  that made it, [Workflows](#workflows)), the `[tests]` budget and the `[components.kern]` pin.
- **Its own binary:** a bare application runs the bare kern. To build its own (the core plus its Go
  components), it adds a `release.toml` naming its `binary`, `package` and download, `[binary]
  release = "release.toml"` in `se.toml`, and a release workflow calling kern's reusable
  `kern-release.yml` with its folder — the way SE builds `se` (`components/release.toml`,
  `se-release.yml`).
  - It calls that workflow's copy, which `se_workflows.py write` adds ([Workflows](#workflows)).
- **GitHub stays the owner's:** the last line names the owner's step, creating the repository with
  its ruleset and the first push. The command does nothing on GitHub.

## Host validators

`uv run python scripts/host_validate.py` runs each host's own validator over the built layouts
(`claude plugin validate --strict` on both manifests, `skills-ref validate` on each skill folder) and
reports; SE's own lint in the build stays the first line. Exit codes: 0 passed, 1 a host refused a
layout, 2 a validator could not run; `--skips-pass` answers 0 where only a tool is absent.

It is off by default, and nothing runs it. Adding `[tests.beside.host-validators]` to `se.toml`,
running `tests/beside_host_validators.py`, puts the hosts' validators into every integration: that
step is the owner's.

## Decision rows

`uv run python scripts/decision_rows.py list --since DATE [--until DATE] [--json]` lists every row
of the Decisions table in the field reports of the pull requests merged into the integration branch
in the window, grouped by pull request, newest first, each with its work issue and the report's
Result. A landing without a Decisions section or without a field report is named as such.

It reads GitHub as `retro.py collect` does (without gh, from the answers saved into `--answers DIR`),
writes and files nothing, and nothing runs it.

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

A ticket's name is its title and, for a work ticket, its branch; the commands that file and route
tickets hold it to the work model's [name rule](src/skills/work-model/SKILL.md#issues).

<!-- generated by `work_tickets.py docs`: begin -->
#### Tickets

`components/tickets`: The worker's local ticket queue under .se/work: tickets, notes, discovery
evidence and the worktree's close.

| Command | Usage | What it does |
|---|---|---|
| `work_tickets.py close` | `work_tickets.py close --worktree WORKTREE [--integration-target INTEGRATION_TARGET] [--remove] [--json]` | check or close an integrated worktree |
| `work_tickets.py create` | `work_tickets.py create --worktree WORKTREE --id ID --title TITLE [--acceptance ACCEPTANCE]` | create a ticket in todo |
| `work_tickets.py init` | `work_tickets.py init --worktree WORKTREE` | initialize the ticket queue |
| `work_tickets.py move` | `work_tickets.py move --worktree WORKTREE --id ID --to {todo,held,done} [--issue-body FILE]` | move a ticket between states |
| `work_tickets.py probe` | `work_tickets.py probe --worktree WORKTREE --command PROBE_COMMAND --output OUTPUT` | append a command and output path to the discovery evidence index |
| `work_tickets.py review-note` | `work_tickets.py review-note --worktree WORKTREE --note NOTE --disposition DISPOSITION [--backlog-ref BACKLOG_REF]` | append a local note disposition |
| `work_tickets.py status` | `work_tickets.py status --worktree WORKTREE [--json] [--integration-target INTEGRATION_TARGET]` | report queue status |

#### Issues

`components/issues`: Work issues and their comments as a role reads and files them: intake, refresh,
escalation, filing, routing, the backlog, blockers and the fleet's pause.

| Command | Usage | What it does |
|---|---|---|
| `work_tickets.py backlog file` | `work_tickets.py backlog file --worktree WORKTREE --title TITLE (--body-file BODY_FILE \| --fields FILE) [--hold] [--repo REPO]` | file one backlog issue with both labels, creating backlogged where missing |
| `work_tickets.py backlog list` | `work_tickets.py backlog list --worktree WORKTREE [--search SEARCH] [--repo REPO]` | list the open backlog issues, or those whose title or body matches --search |
| `work_tickets.py block` | `work_tickets.py block --worktree WORKTREE --by BLOCKER [--repo REPO] issue` | link an issue to a native blocker |
| `work_tickets.py body-read` | `work_tickets.py body-read --worktree WORKTREE [--body-file FILE]` | record the work issue's body as read (intake records it; field-report --check and deliver refuse a body changed after it) |
| `work_tickets.py comments-read` | `work_tickets.py comments-read --worktree WORKTREE --count COUNT --newest NEWEST` | record the work issue's comments as read: their count and the newest one's id (intake records them; field-report --check and deliver refuse comments after it) |
| `work_tickets.py escalate` | `work_tickets.py escalate --worktree WORKTREE --issue ISSUE --file FILE [--repo REPO]` | comment a question on an issue and label it escalated |
| `work_tickets.py file` | `work_tickets.py file --worktree WORKTREE --title TITLE (--body-file BODY_FILE \| --fields FILE) [--hold] [--blocked-by N] [--label LABEL] [--repo REPO]` | for SE: file a work issue labelled work, ready and repo:<name>; with --blocked-by, ready only once its blockers are linked |
| `work_tickets.py intake` | `work_tickets.py intake --worktree WORKTREE (--issue ISSUE \| --issue-body FILE \| --outside) [--comments-file FILE] [--repo REPO] [--discovery] [--probe-root PROBE_ROOT]` | read the work issue with gh, or from the files your GitHub tools' answers were saved to, and write its tickets into todo; it lists the comments, each with its author, a line ending [not the repository owner] where the repository's owner account did not write it (scripts/comment_authors.py) |
| `work_tickets.py paused` | `work_tickets.py paused [--worktree WORKTREE] [--repo REPO]` | whether the fleet is paused: exit code 1 and the issue while an issue labelled pause is open in the repository (the owner's switch; closing it resumes), exit code 0 while none is. queue, start, integrate and route refuse while paused. Without gh it prints the search as a plan for the session's GitHub tools, exit code 2 |
| `work_tickets.py refresh` | `work_tickets.py refresh --worktree WORKTREE [--issue ISSUE] [--repo REPO] [--json]` | re-read the work issue and its comments and report changes; each new or edited comment with its author, marked as intake marks it (--json: byOwner) |
| `work_tickets.py route` | `work_tickets.py route --worktree WORKTREE [--title TITLE] [--type TYPE] (--routing-file ROUTING_FILE \| --fields FILE) [--hold] [--issue-title ISSUE_TITLE] [--issue-body ISSUE_BODY] [--issue-association ISSUE_ASSOCIATION] [--repo REPO] issue` | for SE: route a checked outside issue as a work issue in one edit: retitle it to its name, label it work, ready and repo:<name>, and append the routing section with the handled record to its body |
| `work_tickets.py unhold` | `work_tickets.py unhold --worktree WORKTREE [--issue-body FILE] [--repo REPO] issue` | for SE: check an issue filed with --hold against its template again and, where it passes, remove off-template and give a work issue ready back |

#### Delivery

`components/delivery`: A worker's delivery: the field report and its guard, sync and identity, the
gated push and the pull request, and the Stop hook's check.

| Command | Usage | What it does |
|---|---|---|
| `work_tickets.py deliver` | `work_tickets.py deliver --worktree WORKTREE [--integrator-session INTEGRATOR_SESSION]` | sync, check the field report, push, and create or update the pull request whose description carries it; files no issue |
| `work_tickets.py field-report` | `work_tickets.py field-report [--worktree WORKTREE] (--draft FILE \| --check FILE) [--issue-body FILE] [--comment-count N] [--newest-comment ID] [--check-runs FILE] [--component-kinds-to FILE]` | draft or check the field report a pull request description carries, laid out as .github/pull_request_template.md lays it out |
| `work_tickets.py guard` | `work_tickets.py guard --worktree WORKTREE --branch BRANCH --pr-description FILE` | require the field report to name removed protected content, against origin/<integration branch> as sync fetched it (the local branch without origin) |
| `work_tickets.py identity` | `work_tickets.py identity --worktree WORKTREE` | set the checkout's commit identity (machine-local public_identity, else se.toml project.identity) as sync does, without fetching or merging; scripts/setup.sh, setup.ps1 and the session's start (bootstrap.sh --hook) run it |
| `work_tickets.py pr-body` | `work_tickets.py pr-body [--worktree WORKTREE] --issue-body ISSUE_BODY --issue-url ISSUE_URL --field-report FILE` | print the pull request description deliver writes: Fixes <issue> where the report is complete and all its acceptance shows before the merge, else Refs <issue> (every partial, and acceptance seen only after the merge), then the field report between its markers |
| `work_tickets.py push` | `work_tickets.py push [--worktree WORKTREE] [--redeliver] [branch]` | se_templates.py check-files --changed origin/<integration branch> first; public check's push gate; a work branch only where origin is the repository its recorded work issue is for (README "Work publication"); then git push -u origin <branch>; retries a transient refusal once a minute, ten attempts; the integration branch needs a passing suite and public check recorded on the tree pushed |
| `work_tickets.py stop-check` | `work_tickets.py stop-check [--worktree WORKTREE] [--pull NUMBER] [--pr-description FILE] [--hook JSON]` | the plugin's Stop and SubagentStop hook: in a checkout whose ticket queue is for a work issue, refuse the turn's end while its branch has no open pull request whose description carries a field report that passes field-report --check at the branch tip, naming what is missing and the commands; at most [stop] refusals times in a row (se.toml, built in 5); under Copilot it only says what is undelivered unless [copilot] refuse_stop is true. It also refuses, in any checkout, while a changed file a template claims breaks it (se_templates.py check-files). Anywhere else, for a sub-agent that is no worker, and where it cannot judge (no gh and no recorded pull request) it lets the turn end. It reads the hook's JSON on stdin and answers the hook's JSON on stdout |
| `work_tickets.py sync` | `work_tickets.py sync --worktree WORKTREE` | merge the newest integration branch (se.toml project.integration_branch, default main) from origin, or locally without origin, then move the se clone (.se/modules/se) of a repository that pins se to the pin the merged se.lock names |
| `work_tickets.py verified` | `work_tickets.py verified [--worktree WORKTREE] remote_ref commit` | the pre-push hook's guard: refuse a push of <commit> to <remote ref> where the ref is the integration branch and no passing suite and public check are recorded on its tree; push runs the same check. A push of the delivered work branch at another commit than its delivered tip prints the late-push line, or with se.toml [deliver] late_push = "refuse" is refused (README "Late push") |

#### Integration

`components/integration`: The integrator's and SE's work: integrate and its release, ref
maintenance, the suite and its budget, metrics, settings, starting work, the queue, the fleet and
settings checks and the generated docs.

| Command | Usage | What it does |
|---|---|---|
| `work_tickets.py capacity` | `work_tickets.py capacity [--worktree WORKTREE] [--repo REPO] [--all-repos]` | show local worker capacity or cloud unlimited capacity |
| `work_tickets.py config` | `work_tickets.py config --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT] [--integrator-session INTEGRATOR_SESSION]` | show the repository and the machine-local settings in effect |
| `work_tickets.py dispatch` | `work_tickets.py dispatch [--worktree WORKTREE] [--repo REPO] [--fire \| --dry-run]` | the dispatcher (README "Dispatcher", scripts/dispatch.py): list the startable work issues (ready, not waiting on a person, no open blocker) and whether an integrator runs (an open landing pull request, or in-progress work that moved within the fleet lease), all read from GitHub with no model; with --fire it fires the scheduled task whose fire URL is in SE_DISPATCH_TRIGGER with the token in SE_DISPATCH_TOKEN once where startable work waits, none runs and the fleet is not paused; with --dry-run it prints that fire and makes none |
| `work_tickets.py docs` | `work_tickets.py docs [--check]` | write the command groups' component declarations (components/<group>/component.toml) from this registry and the README's command reference from them; with --check, only refuse a declaration or a README that differs |
| `work_tickets.py file-seconds` | `work_tickets.py file-seconds [--worktree WORKTREE] [--run ID] [--artifact FILE]` | write tests/file-seconds.json, the order the suite's workers take its test files in, from CI's seconds: the artifact file-seconds of a check run, by default the newest passing one of a push to the integration branch that kept it; prints each file that moved by 1 s or more |
| `work_tickets.py fleet-check` | `work_tickets.py fleet-check [--worktree WORKTREE] [--repo REPO] [--json] [--open-issues OPEN_ISSUES] [--closed-issues CLOSED_ISSUES] [--pulls PULLS] [--sessions FILE]` | list every stuck or stray piece of work, each with its issue, pull request and remedy: in-progress work without a branch once the lease has passed since its Started comment (listed as starting before) or without a push within the lease, a delivered pull request whose check failed or that conflicts, a branch of a closed issue, a block by an issue closed as not planned or by itself, an se-person issue and what it holds up, and with --sessions a worker session stopped on a usage limit without delivering; 'healthy' and exit code 0 when there is none, exit code 1 otherwise. It only reads. Without gh it prints its GitHub plan and takes the answers from files |
| `work_tickets.py format` | `work_tickets.py format [--root ROOT]` | apply the fix of every check the check job runs that a fix can satisfy: write the generated layouts (se_plugin.py build) and the command reference with its declarations (docs); a second run writes nothing |
| `work_tickets.py integrate` | `work_tickets.py integrate --worktree WORKTREE [--repo REPO] [--pr-description FILE] [--issue-body FILE] [--branch BRANCH] [--pr-comments FILE] [--read-back BRANCH] [--record-fix BRANCH] [--landing {squash,fast-forward}] [--landing-pull LANDING_PULL] [--check-run CHECK_RUN] [--landing-description FILE] [--build-command BUILD_COMMAND] [--include-late REASON] [--check-command JSON] [--check-command-temporary-directory] [pull_request]` | validate the field report a pull request's description carries, merge it on land/<branch>, test, land it through a squash pull request once check passes, and close the work issue. Where gh is not signed in it pushes land/<branch> and prints the GitHub steps as a plan for the session's GitHub tools; --read-back <branch> then checks the landing through git and finishes the close-out |
| `work_tickets.py metrics` | `work_tickets.py metrics [--since DATE] [--file FILE]` | print what the commands cost, from the line every run of a command appends (README Metrics): top spenders by total wall time and by GitHub calls, and each overrun of a declared budget (the suite's [tests] limit_seconds in se.toml) |
| `work_tickets.py parity` | `work_tickets.py parity [--worktree WORKTREE] left right` | compare two commits' trees, such as one branch on two remotes: every tracked path that differs, apart from dependency lockfiles (se.lock and uv.lock at any depth), is listed as changed, only left or only right, and fails with exit code 1; lockfile differences are named and pass. It only reads |
| `work_tickets.py queue` | `work_tickets.py queue [--worktree WORKTREE] [--repo REPO] [--all-repos]` | list delivered pull requests (open, to the integration branch, with a complete field report), escalations and startable work issues. Without gh it syncs the checkout and prints its reads as a plan for the session's GitHub tools |
| `work_tickets.py ready` | `work_tickets.py ready [--worktree WORKTREE] [--repo REPO] [--all-repos]` | list startable ready work issues |
| `work_tickets.py refs apply` | `work_tickets.py refs apply --worktree WORKTREE [--repo REPO] [--comments-file COMMENTS_FILE] [--read-back] [--run-url RUN_URL] [--conclusion CONCLUSION] issue` | for SE, on the person's yes: run ref-maintenance for real with the triples the issue's newest request posted, read the refs back and post the result; prints the line for the integrator. Where gh is not signed in it prints these GitHub steps as a plan for the session's GitHub tools; --read-back then checks the refs and finishes |
| `work_tickets.py refs request` | `work_tickets.py refs request --worktree WORKTREE --triples-file TRIPLES_FILE [--repo REPO] [--read-back] [--request-id REQUEST_ID] [--run-url RUN_URL] [--conclusion CONCLUSION] [--log-file LOG_FILE] issue` | for the integrator: post the triples on the issue, run ref-maintenance's dry run, post its output and label the issue escalated; prints the line for SE. Where gh is not signed in it prints these GitHub steps as a plan for the session's GitHub tools; --read-back then checks the refs and finishes |
| `work_tickets.py rehearse` | `work_tickets.py rehearse --worktree WORKTREE [--repo REPO] --base BASE [--gap SECONDS]` | rehearse a whole landing through kern's relay against a scratch branch, never the integration branch: a relay read, a local phase (--gap makes it slow on purpose), the push of rehearse/<base>, the landing pull request into <base>, its check, the squash merge and the read-back. It releases and tags nothing and touches no issue; it runs only as one call through kern's relay |
| `work_tickets.py release-trailer` | `work_tickets.py release-trailer [--worktree WORKTREE] --issue-body ISSUE_BODY [--pr-description FILE] [--include-late REASON] branch` | print the Release-kind trailer an integration merge of <branch> carries, from its field report's Release kind (a re-integration's from its Re-integration kind); push requires it |
| `work_tickets.py session-title` | `work_tickets.py session-title {se,integrator,worker,reviewer,researcher,spike} [project] [topic]` | print the title of a session a role starts: `SE`, `SE/<project>/integrator[/<area>]` or `SE/<project>/<role>/<topic>` (work model, Visible sessions) |
| `work_tickets.py settings-check` | `work_tickets.py settings-check [--worktree WORKTREE] [--repo REPO] [--ruleset FILE] [--scheduled-tasks FILE] [--environment FILE] [--strict]` | compare the fleet's settings the repository records (fleet/settings.toml) with the live ones, each difference in one line: main's ruleset through gh where it is signed in or from --ruleset, the scheduled tasks and the cloud environment from the answers of the session's list_triggers and get_environment tools; a part whose door is missing and a value recorded as unchecked are reported unchecked, never as a difference. Advisory: exit code 0 whatever it finds, 1 for a difference only with --strict. It only reads |
| `work_tickets.py start` | `work_tickets.py start --worktree WORKTREE [--repo REPO] [--worktree-root WORKTREE_ROOT] [--no-create] [--cloud-agent CLOUD_AGENT] [--issue-body FILE] [--blockers FILE] issue` | start a ready work issue: worktree from the newest main, label in-progress; without gh, the label change and the Started comment as GitHub steps, or through kern's relay where it serves the checkout |
| `work_tickets.py suite` | `work_tickets.py suite --worktree WORKTREE [--slowest N] [--compare REF] [--runs N] [--full] [--record-file-seconds PATH] [--keep-test-reports DIR]` | run se.toml's complete suite against its [tests] time budget, as integrate does; exit code 1 when tests fail, 3 when they pass over the limit and the budget refuses them (README "Test budget") |
| `work_tickets.py suite-shard` | `work_tickets.py suite-shard --worktree WORKTREE --name NAME --record DIR ...` | on CI, run one shard of a sharded suite, the COMMAND after --, show its output, time it and write its record DIR/NAME.json for suite-time; exit code the command's (README "Test budget") |
| `work_tickets.py suite-time` | `work_tickets.py suite-time --worktree WORKTREE --shards DIR [--expect N]` | in CI's check job, judge a sharded suite: its time is its slowest shard's, from the records suite-shard wrote; prints it as the notice CI's suite time is read from, and no time when a shard failed; refusals and warnings are workflow annotations; exit code 1 when a shard failed or is missing, 3 when the time is over the limit and the budget refuses it (README "Test budget") |
| `work_tickets.py test-seconds` | `work_tickets.py test-seconds [--worktree WORKTREE] [--runs N] [--run ID] [--report FILE] [--slowest N]` | print each test's seconds from CI's kept test reports: per run its wall, cpu and when each worker started and finished, then the slowest tests' median over the runs; by default the artifact test-reports of the newest passing check runs of a push to the integration branch that kept it; writes nothing |

#### Review

`components/review`: A cold review of a delivered pull request: the brief a reviewer starts from,
and the report it files as one comment.

| Command | Usage | What it does |
|---|---|---|
| `review.py brief` | `review.py brief [--claims] [--json] [--worktree WORKTREE] [--repo REPO] [--pull FILE] [--issue FILE] [--issue-comments FILE] [--checks FILE] [--pull-comments FILE] pull_request` | what a cold reviewer of a delivered pull request starts from |
| `review.py file` | `review.py file --report FILE [--pull FILE] [--issue FILE] [--worktree WORKTREE] [--repo REPO] pull_request` | check a review report and post it as one comment on the pull request |

#### Retro

`components/retro`: A retro: collect writes its draft from the work since the last one, file checks
the judged draft and closes the retro issue with its report.

| Command | Usage | What it does |
|---|---|---|
| `retro.py collect` | `retro.py collect [--since DATE \| --retro ISSUE] [--out FILE] [--json] [--signals FILE [FILE ...]] [--refusals] [--sessions FILE] [--answers DIR] [--worktree WORKTREE] [--repo REPO] retro` | read a retro's window from GitHub and write its draft |
| `retro.py file` | `retro.py file --draft FILE [--worktree WORKTREE] [--repo REPO] retro` | check a judged retro draft and close the retro issue with its report |

#### Overhaul

`components/overhaul`: An overhaul: new files its issue, read writes its draft, file checks the
judged draft and closes the issue with its report, and facts lists a checkout's pruning facts.

| Command | Usage | What it does |
|---|---|---|
| `overhaul.py facts` | `overhaul.py facts [--repo REPO] [--json]` | list the pruning facts of a checkout |
| `overhaul.py file` | `overhaul.py file --draft FILE [--worktree WORKTREE] [--repo REPO] overhaul` | check a judged overhaul draft and close the overhaul issue with its report |
| `overhaul.py new` | `overhaul.py new [--worktree WORKTREE] [--repo REPO]` | file the overhaul issue through work_tickets.py file |
| `overhaul.py read` | `overhaul.py read [--out FILE] [--json] [--answers DIR] [--worktree WORKTREE] [--repo REPO] overhaul` | write an overhaul's draft |

#### Render

`components/render`: The pages SE renders: timeline.py builds the Timeline from GitHub, deck.py
builds a deck of decisions, serves it and reads its answers.

| Command | Usage | What it does |
|---|---|---|
| `deck.py answers` | `deck.py answers [--record FOLDER] [--destination DESTINATION] answers` | print what the answers ask the agent to act on |
| `deck.py build` | `deck.py build --destination DESTINATION folder` | build a folder of decision notes into one deck |
| `deck.py serve` | `deck.py serve [--wait] [--timeout S] artifact` | serve a deck locally and print the answers it is sent |
| `timeline.py` | `timeline.py --destination DESTINATION [--snapshot SNAPSHOT] [--save-snapshot SAVE_SNAPSHOT] [--config CONFIG]` | Build the Timeline: one obs table of the repositories in se.toml `[timeline]`, newest first. |

#### Scaffold

`components/scaffold`: What SE scaffolds: a new application on kern, and an ad hoc component in a
checkout.

| Command | Usage | What it does |
|---|---|---|
| `se.py component add` | `se.py component add [--root ROOT] name` | scaffold an ad hoc component under the ignored .se/components/ |
| `se.py new app` | `se.py new app --path PATH name` | create an application on kern from kern's template at SE's kern pin |

#### Templates

`components/templates`: SE's templates: list names them, draft gives a template's fields, their
instructions and their shape, check finds everything SE's filing commands would refuse in a text, or
gives the Markdown to file, and fill checks an agent's fields against the raw input and gives the
document.

| Command | Usage | What it does |
|---|---|---|
| `se_templates.py backstop` | `se_templates.py backstop --event-name EVENT_NAME --event EVENT [--backstop {off,on}] [--worktree WORKTREE]` | plan the label or failure a GitHub event's off-template text gets |
| `se_templates.py check` | `se_templates.py check (--body-file BODY_FILE \| --fields FIELDS \| --body BODY \| --fields-json FIELDS_JSON) [--title TITLE] [--render] [--action ACTION] [--repo REPO] [--labels LABELS] [--base BASE] [--worktree WORKTREE] [--tree] [template]` | check a text against a template as SE's filing commands would |
| `se_templates.py check-files` | `se_templates.py check-files [--changed REF] [--root ROOT] [--templates TEMPLATES] [PATH ...]` | check the files a template claims, given or changed since a ref |
| `se_templates.py draft` | `se_templates.py draft [--markdown] [--tree] template` | print a template's fields, their instructions, their shape and its schema |
| `se_templates.py fill` | `se_templates.py fill [--prompt PROMPT] [--input INPUT \| --input-text INPUT_TEXT] [--fields FIELDS \| --fields-json FIELDS_JSON] [--title TITLE] [--worktree WORKTREE] [--templates TEMPLATES] [--tree] template` | fill a template from the raw input: the instructions, or the checked document |
| `se_templates.py gate` | `se_templates.py gate [--gate {off,warn,refuse}] [--templates TEMPLATES] [--root ROOT] [--runtime ROOT]` | SE's hook: judge one GitHub write's body, or a claimed file's write, against its template |
| `se_templates.py list` | `se_templates.py list [--tree]` | name every template with its actions |

#### Guidance

`components/guidance`: SE's guidance: collect resolves the guidance trees of the project and its
modules for a template or a set of tags, general before specific; project writes the tool files the
notes implement; and check finds what docs/guidance.md refuses in them.

| Command | Usage | What it does |
|---|---|---|
| `se_guidance.py check` | `se_guidance.py check [--root ROOT]` | find what docs/guidance.md refuses in the guidance trees |
| `se_guidance.py collect` | `se_guidance.py collect (--template TEMPLATE \| --tags TAGS) [--json] [--root ROOT]` | print the guidance a template or a set of tags gets, general first |
| `se_guidance.py project` | `se_guidance.py project [--root ROOT]` | write each tool file the notes implement, its generated part from them |
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

| Field | Meaning |
|---|---|
| `verdict` | `pass`, `pass with open points` or `decline` |
| `head` | the commit reviewed, the head the brief named |
| `acceptance` | each acceptance item of the work issue, `{"item", "evidence"}` |
| `findings` | each verified finding, `{"title", "evidence", "place", "blocking", "why"}`, empty where none was found; only damage blocks: the product made worse, or against what it is about |
| `clean` | the "checked and clean" list, what was examined and found sound |

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

`--sessions <file>` adds the cloud sessions' costs: the file holds each session `list_sessions`
lists, with its `list_events` result events (kinds `["result"]`) as `"events"`. Each session is
found by its title, `SE/<repo>/<role>/<topic>` ([Visible sessions](src/skills/work-model/SKILL.md#visible-sessions)),
and the draft sums its tokens and cost per issue, role and repository; another title is counted
as other, never guessed.

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

`scripts/transcript_signals.py <transcripts or directories>` counts what sessions did, read from
their transcripts (Claude Code's JSONL): corrections, retries, repeated command shapes, scripts
written twice, denials by tool and long waits, per session and in total (`--json`).

It prints counts, locations and masked command shapes, never message text; it judges nothing,
files nothing, and nothing runs it. Its docstring owns the signals and the adapter a new format
adds.

`scripts/overhaul.py` holds the overhaul commands, which ask, rarely, whether the design is still
right. SE starts one and runs it as its issue says, `read`, the judgment, then `file`.

`overhaul.py new` files the overhaul issue, `overhaul-<yyyymmdd>`
labelled `discovery` beside the work labels, with the body of
[the overhaul template](.github/ISSUE_TEMPLATE/overhaul.md), through `work_tickets.py file`'s
filing path (`file --label discovery`): once, so an open overhaul answers a second `new`.

`overhaul.py read` writes the draft:

- every live rule of the rule book with what checks it, read from its implementations: a test (it
  names the tests or the suite), judgment ("by judgment"), a check (it links a script, or names
  neither);
- the retros closed since the last closed overhaul (titled `overhaul-<yyyymmdd>`, or `docs/overhaul-<yyyymmdd>` before the name rule), or in the whole
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

### Templates

[docs/templates.md](docs/templates.md) owns the template system: its names, the template, the
document and the packages that build it. This section holds the commands of the engine as it runs
today.

One Markdown note per template under `templates/`, its front matter the fields and its body the
skeleton with an instruction per section, is read by one engine, `scripts/templates.py`, whose
docstring owns the note's format, the field kinds, the selection order, the two severities and the
marker a rendered document carries, `<!-- se:template <repository>/<name> <version> <digest> -->`.

The templates own the shape of issues; the GitHub issue templates in `.github/ISSUE_TEMPLATE/`
are advice beside them.

The texts `overhaul.py` and `retro.py` file pass the work template as they stand, and the GitHub
issue template `work.md` has a section for every part the work template requires; the tests check
both.

| Template | What it shapes |
|---|---|
| `templates/decision.md` | A decision note: the situation and the problem before the options' pugh fence. |
| `templates/field-report.md` | A work pull request's description: the field report between its markers. |
| `templates/housekeeping.md` | The owner's housekeeping pull request: no field report, no field required. |
| `templates/landing.md` | A landing pull request: it names the work issue, the work pull request and its report. |
| `templates/merge-message.md` | An integration's squash commit: `Integrate <branch>` and one Release-kind trailer. |
| `templates/overhaul.md` | An overhaul's report: the verdicts, the findings and the judged block the next one reads. |
| `templates/retro.md` | A retro's report or draft: its judged block, under its marker. |
| `templates/review.md` | A cold review's one comment: what a person reads, then the JSON block the retro reads. |
| `templates/routed.md` | The routing block SE appends to an outside issue: where it came from and what it lacks. |
| `templates/terms.toml`, the term list and no template | Inside terms and the plain words to use instead. They only warn. |
| `templates/ticket.md` | An issue the owner reads: what is, what is wrong, what should be, how, and how we know. |
| `templates/work.md` | One package for one worker: the ticket's why, then numbered requirements and acceptance. |

`check` refuses a missing, empty or placeholder field, a choice outside its set, an Approach
without its alternative, the same text in two fields and an SE command that does not exist; the
writing rules (word counts, actors, one sentence per step, bare issue numbers, board lines, inside
terms, unnamed blockers, the title's shape) only warn.

`templates.py check <template> --body-file <file>` (or `--fields <file>`, the JSON `draft --json` prints)
prints at most ten findings and exits 1 where one refuses; `templates.py draft <template>` prints the empty
template and `templates.py list` names every template with its actions. They read `templates/` at `origin/main`
where it holds them, else the working tree (`--tree` always).

`draft --json` also gives each field's shape (its kind, heading, whether it is required, its
choices) and the template's JSON Schema, which a model's strict tool use takes as it stands;
`templates.py schema <template>` prints that schema alone, generated from the template.

A `file.write` template claims files by its `applies.paths` globs, such as a milestone's steps.
`templates.py check --path <file>` checks one against the template its front matter's `template:`
line names or the conditions pick, refuses one none picks and leaves unclaimed files free.

The front matter and `#` title stay as they are, but for the `template`, `version` and `overlay`
lines the front matter records its template by.

A document is checked against the template version its marker or front matter records: another
minor or patch version warns, another major version refuses, naming both versions and the fill
that writes it again ([docs/templates.md "The document"](docs/templates.md#the-document)).

`--templates <folder>` reads the templates from another folder.

A claimed file is written only by its fill
([docs/templates.md "Fill"](docs/templates.md#fill)), and one that breaks its template cannot end a
turn, be pushed or pass CI; each refusal names the file, the template and each finding.

- `scripts/se_templates.py check-files` with `--changed` and a ref checks every claimed file changed
  since that ref's merge base, committed or not, untracked ones too; its docstring owns the answer.
- `work_tickets.py stop-check` and `push` run it against `origin/<integration branch>`, CI's
  `check` job against the pull request's base. Where no template claims a path, it checks nothing.
- Under Copilot the Stop hook only advises. No template of SE's claims a path yet.
- SE's template gate denies every Write, Edit or MultiEdit of a claimed file before it runs, and
  each path of `push_files` and `create_or_update_file`, whatever it would leave. It names the
  template and the fill, `templates.py fill <template> --path <file>`, which writes the file itself.
  - SE's start writes `.se/.runtime/templates-files` where a template claims a path, so
    `scripts/se_hook.sh` picks the file tools with builtins only there; a template added during a
    session is guarded from the next session's start. `scripts/se_templates.py`'s docstring (The
    file tools) owns the rest.

An agent asks for a template through the MCP door's tool `templates`, `scripts/se_templates.py`: `list`
names the templates, `draft <template>` gives `draft --json`'s answer, and `check` finds all the filing
commands below would refuse (private terms, the name rule, SE's commands too) or gives the
Markdown to file. It only reads; its first line is `passes` or `refused: <n> findings`.

`fill` is one step from raw input to document ([docs/templates.md "Fill"](docs/templates.md#fill)):
it takes the template, the prompt, the raw input and the agent's fields.

- Without fields it answers the template's instructions, its guidance and the empty draft.
- With them it checks the document against the template and the raw input. Every field takes
  `Not in input` where the input does not say, and a field with `quote: true` refuses a quote the
  raw input does not hold word for word.
- `templates.py fill` writes a claimed file to its `--path`, or the document to `--out` or stdout;
  a refusal names every finding and writes nothing. The tool's `fill` answers as `check --render`
  and writes nothing; filing stays the filing commands' and the GitHub tools'.

The commands that file issues check with them where se.toml `[templates] enforce` says so: `file`
against `work`, `backlog file` against `ticket` and `route` against `routed`. Each takes
`--body-file` (for `route`, `--routing-file`) or `--fields <file>`, the JSON `draft --json` prints,
always rendered through the template.

- `enforce` is `off` (the default: a `--body-file` body is filed byte for byte as before), `warn`
  (the findings go to stderr and the issue is filed) or `refuse` (nothing is printed, asked or
  written; the refusal lists every finding in at most ten lines). With `warn` or `refuse` a
  `--body-file` body is parsed and rendered again, its unknown sections kept.
- They read `[templates]` from `se.toml` at `origin/<integration branch>`, the working tree's only
  where that ref does not exist, so a branch cannot switch its own check off.
- `refusals` (default 2) caps the retries: refusals are counted per session, template and issue in
  `~/.se/templates/`. From that count on each refusal names `--hold`, which files the text as given,
  labelled `off-template` and not `ready`; `ready` and `start` take no such issue. Before that count
  `--hold` is refused.
  - The way back: fix the title or body on the issue itself, since filing it again only comments
    on it, then run `work_tickets.py unhold` with its number, which checks it against its template
    and lifts the hold where it passes.
- The check also runs the two layers of `scripts/public_check.py` over the title and the body
  ([Public safety](AGENTS.md#public-safety)): the committed public list, and the checkout's
  private `.public-check.local`, which nothing committed refers to, where it holds one.
  - A hit names the field and the list, never the term: stop and ask the owner. `--hold` never
    files such a text.

SE's template gate holds the writes an agent sends through the GitHub MCP tools (`issue_write`,
`add_issue_comment`, `create_pull_request` and the other five of `scripts/se_templates.py`'s table)
to the same checks, where se.toml `[templates] gate` says so.

The gate is `off` (the default), `warn` (the agent gets the findings) or `refuse` (the call is
denied, naming the template, every finding and the templates tool).

- `scripts/se_hook.sh` picks the guarded calls with bash builtins and runs `se_templates.py gate` for
  them alone, whose docstring owns the table, the answers and the failure rule.
- A shell call that names `gh` is guarded too: the gate reads each `gh issue`, `gh pr` and `gh api`
  write in it as the same write through the GitHub tools; its docstring owns the commands it reads.
  - A body it cannot read, such as one from `$(...)` or `--fill`, is refused where a template applies,
    naming `--body-file`.
  - It does not see `gh api graphql`, `curl` or another program that calls GitHub's API.
- It reads `[templates] gate` as `enforce` is read, from the se.toml of the project whose home holds
  the target, else of SE itself; a write elsewhere, without a body or that no template covers runs as
  before. `SE_TEMPLATES_GATE=off` turns it off for a machine.
- From `refusals` on, a refused issue write may be sent again labelled `off-template` and without
  `ready`, the hold `--hold` files; a private term is never held.
- It fails open when it is slow: past 10 s, or where the host cancels it, the call runs.
  It fails open where it cannot judge (no Python 3.11, a payload it cannot read), and logs it in
  `.se/.runtime/templates-gate.log`; it fails closed only on a crash once it knows a template applies.

SE's templates backstop marks what reaches GitHub past every hook, where se.toml `[templates] backstop` is
`on` (default `off`): a person's write on github.com, a session without SE's hooks, a label change.

The workflow `.github/workflows/templates.yml` runs on each issue and comment event and hands the event
to `scripts/se_templates.py backstop`, whose docstring owns what it checks and its plan.

- A fleet issue (the fleet marker, or labelled `work`) whose text breaks its template gets the label
  `off-template`, and the run's summary lists the findings and the `unhold` line; a marked comment that
  breaks its template gets a failed run, as `unhold` reads the issue's body alone.
- Outside reporters' issues, unmarked comments and passing text are left alone. The workflow never
  comments and never removes a label; `work_tickets.py unhold` stays the way back.
- SE's own se.toml leaves it `off`: open issues SE's commands filed from an older template would be
  labelled.
