# Starting SE

## Start and refresh

SE's first message is its start report ([docs/boot.md](boot.md#the-start-report)).
[scripts/se_start.py](../scripts/se_start.py) implements this section:

```sh
uv run python <se>/scripts/se_start.py status [--greeting]
uv run python <se>/scripts/se_start.py check
uv run python <se>/scripts/se_start.py refresh
uv run python <se>/scripts/se_start.py boot [--upgrade]
uv run python <se>/scripts/se_start.py update
```

- Where it runs: in Claude Code, the plugin's start hook (`bootstrap.sh --hook`) shows the greeting
  to the person and hands it to the session, together with SE's root (`SE root: <path>`), where the
  skills find SE's scripts; elsewhere SE's [instructions](../src/agents/se.md) run `status --greeting`
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
  ([docs/components.md](components.md#required-and-optional-at-start)).
  - What is placed comes first: a clone at the commit `se.lock` locks is used without asking any
    remote, so a start with every component placed works offline; the rest is found by name and
    placed at its pin ([Modules](modules.md#modules)).
  - A required component missing anywhere in the tree stops the start. The greeting shows one
    message, opening `SE cannot start:`, with its path from the root (`se -> obs`), the remotes
    read, each with why it offered nothing (Git's message where it could not be read), and the
    remedy, a remote of an owner that offers it.
  - Nothing after the stop runs: no commit identity, hooks or core. Any other failure to resolve
    the tree stops it the same way, such as a found release whose tag points elsewhere than
    `se.lock` records.
  - An optional component missing is one line naming its path, and the start goes on.
  - A runtime the tree needs and the machine lacks after `RUNME.conf`'s ways stops it the same way,
    naming the runtime, the components that need it and the remedy
    ([docs/components.md "Runtimes"](components.md#runtimes)).
- `status` reads only the disk and the last update check, cached in `~/.se/start-check.json`
  (`--cache`, or `SE_START_CACHE`), so it answers within a second. A check older than an hour, or
  none, starts `check` in the background; the next start shows its result.
- `check` reads the version tags of SE's own remote and of every module's remote, once each and in
  parallel. A failed read is named in the greeting with its remote, its cause and the command to see
  it; the greeting still appears.
- What is due in the work: where gh reaches GitHub, signed in or over REST, `check` also counts what came back since the
  newest retro started ([Retro due](fleet.md#retro-due)), the retros closed since the newest overhaul
  started where that countdown is on, runs the [fleet check](fleet.md#fleet-check), and caches them.
  - The greeting then names a retro that is [due or open](fleet.md#retro-due), an overhaul that is
    [due or open](fleet.md#overhaul-due) and the fleet's findings by kind and issue, one line each with the
    command to run, and a part whose read failed with its cause.
  - `status` reads them from the cache, and each part from kern live where the core in the checkout
    carries SE's fleet and retro-due components and has read issues: its line then says `live from kern`
    ([components/README.md](../components/README.md#who-reads-them)).
  - Without gh (neither signed in nor answered over REST) the greeting names neither; the
    [se agent](../src/agents/se.md) runs the fleet check's plan at its first turn instead.
  - `refresh` reads no work: its checks keep the cached lines.
- The project's components: where the project's `se.toml` sets `[project] components`, its
  listing command ([Project settings](settings.md#project-settings)), `check` runs it in the checkout and
  caches its table; the greeting names, one line each, a component offered and not installed and
  an installed one with a newer release, with installed and newest version.
  - Each line names the command that takes it, the listing's `install <name>` or `update <name>`;
    SE never runs it.
  - A listing that fails, prints no table or runs past 60 seconds is one warning line, and the
    greeting still appears; without the setting nothing runs and nothing prints.
- The outside skills SE's agents rely on (`[roles]` of SE's `se.toml`,
  [AGENTS.md "Agents and skills"](../AGENTS.md#agents-and-skills)): the greeting names, in one line,
  each one whose plugin the session lacks, with the roles that rely on it.
  - A plugin counts as present where Claude Code's record of the installed plugins names it with
    its marketplace, or where it is cloned into `~/.claude/skills/` (as the cloud's SE is).
  - Locally the line ends with the command that installs each plugin, `claude plugin install
    <plugin>@<marketplace>`; in Claude's cloud it says that the session lacks them and that the
    cloud environment provides plugins ([Claude Code cloud](install.md#claude-code-cloud)).
  - A list SE cannot read is named instead, and the greeting still appears.
- What is due: the highest version a module's `version` range admits above its locked one, and for
  SE the highest version of its major. A newer version outside the range is shown apart and never
  applied, with the remedy: for a module the range to set in its `se.toml` and the `update` that
  takes it, for SE an install again.
- A local path (`[paths]` of `~/.se/local.toml`, SE's own under the name `se`) is reported as local
  and never touched. A module pinned by commit is reported, and only the module command's
  [`update`](running.md#commands) moves it.
- `refresh` takes no choices. It checks now, then moves each due item: it checks the new version
  out into a temporary worktree first, checks that it starts (its `se.toml` names that version; for
  SE, `status` runs there) and only then switches. A module's lock moves in `se.lock`; commit it.
- SE itself moves the way it was [installed](install.md#install):
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
  - Such a table is `[components]`, which replaced `[modules]` in se 8: an SE before 8 reads no
    component of it, and an SE 8 refuses a `[modules]` table, naming the rename.
  - The remedy is a newer installed SE: `uv run python <se>/scripts/se_start.py refresh`, or a
    new session, whose start moves it.

### Boot

SE's start report, the boot and the one update command the report names are [docs/boot.md](boot.md).

### Kern

Nobody starts the core by hand. SE builds its own binary, `se`: kern's core with SE's Go components,
released as `se-v<version>` that `components/release.toml` owns. `scripts/se_modules.py app-binary`
is bootstrap's one reader of the binary to run — SE's `se`, or the bare kern for an application with
no Go components. The plugin's hooks start the binary and post every session event to it:

- **kern at its pin:** the `se` binary is built on the kern `se.toml` `[components.kern]` pins
  ([Modules](modules.md#modules)), its clone in `.se/modules/kern`.
  - Before the core starts, the start syncs the installed SE's kern where that clone is missing
    or not at the commit `se.lock` locks, both read from the files alone, so an SE at its pin
    starts no process for it.
  - Where that fails, the start goes on to the binary and the greeting names the cause. A project
    that is SE's own checkout syncs it in the modules step.
- **SessionStart**, [scripts/bootstrap.sh](../scripts/bootstrap.sh) `--hook`: for a project inside a
  git checkout, where `~/.se/bin/<name>-<version>` is on the machine, it runs `<name> start` for the
  project, which returns at once, and hands the core the session's start, which takes the session's
  lease. It names the binary in `<project>/.se/.runtime/kern.path` for the later hooks.
  - For a project inside no git checkout it runs one for SE's root, named in SE's own
    `.se/.runtime/kern.path` ([required components](boot.md#required-components)).
  - `~/.se/bin/<name>` links to the version in place (a copy where the file system makes no link),
    and Claude Code's env file puts `~/.se/bin` on the session's PATH, so `se status` works there.
- **The first start of a version** reads the release's `SHA256SUMS` (one small read). Where it names
  this platform's archive, the archive is fetched, checked against its line and unpacked in the
  background, and the core then starts.
  - Where no release matches, the binary is built from its folder (SE's `components/`, on kern's
    clone at its pin; the bare kern in that clone) with `go` in the background; without `go` it
    failed, and the start stops naming both causes.
  - The start waits for that background up to `SE_KERN_WAIT` seconds (45 by default); one that runs
    longer goes on, and the start stops naming kern and the remedy, a new start once it is in place
    ([required components](boot.md#required-components)).
  - The background half runs in its own process (`setsid` where there is one), so the hook's end
    does not end it.
- **RUNME** places the binary once, with `bootstrap.sh --binary` (RUNME.conf's `get se` line): it
  fetches or builds `~/.se/bin/<name>-<version>` in the foreground, links it and starts nothing.
- **Every other event** (SessionEnd, SubagentStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop
  and SubagentStop) runs [scripts/se_hook.sh](../scripts/se_hook.sh) `<event>`, which hands the host's
  JSON to the named binary's `kern hook <event>`.
  - SessionEnd returns the session's lease. The Stop hooks are answered by the delivery
    component's `stop-check`, and else by `stop-check` directly ([Stop hook](fleet.md#stop-hook)).
  - It fails open: without kern's binary, or with no core answering within 500 ms, it prints
    nothing and exits 0.
- **The greeting** hands the session the binary's state, never the person: `<name> <version>:
  running` (`se <version>` for SE), `starting: <why>`, or `failed: <cause>`.

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
"Migration"](go-core.md#migration)); the command line does not change.
[scripts/se_components.py](../scripts/se_components.py) owns how.

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
  - The [command reference](work-commands.md#work-commands) renders from these declarations as kern's reader reads
    them.
- **Placed:** `wiring.toml` places each in a process of its own, beside SE's Go components in the
  `se` binary, so the core the hooks start in SE's checkout lists them all: `se status --json` names
  the instances, those attached (a placed one once its process attached, a Go one with the core)
  and, under `backends`, the backend each chose (`github`: `relay` or `token`).
- **Discovered:** `se_components.py commands [--json]` lists every command the checkout's
  components declare, with its usage, summary and class, from the declarations alone. It holds
  the discovery budget, the guidance note
  [discover-cheap-load-late](../guidance/discover-cheap-load-late.md) (`tests/test_discovery_budget.py`).
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
    waits ([docs/go-core.md "A call given up"](go-core.md#a-call-given-up)).
  - `SE_KERN=off` keeps every command direct (the suite and each component's own process set it);
    `SE_KERN=on` refuses to fall back.
- **Tested** against kern's Python fake core (`tests/test_se_components.py`), and once against the
  real core with the components placed (`tests/beside_se_components.py`, `se.toml`
  `[tests.beside.se-components]`).

### The MCP door

`se mcp --root <checkout>` is SE's MCP server over stdio, kern's door (kern's README "The MCP
door"), for every agent host that reads an `mcp.json` (Claude Code,
Copilot in VS Code and its CLI): a host whose `mcp.json` names it calls SE's commands through it
as tools. The host spawns it as the session starts; nobody starts anything else.

- **What it offers.** SE's read-only commands, and the commands that write only through kern's
  GitHub component (Writing, through requests only, below).

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
  root <root> from <source>`, to that root's `.se/.runtime/mcp.log` ([scripts/se_mcp.sh](../scripts/se_mcp.sh)).
  - Copilot's plugin root is `PLUGIN_ROOT`, its session folder `COPILOT_SESSION_CWD`; Claude
    Code's are `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PROJECT_DIR`, each read only under its own host.
  - Claude Code starts a plugin's server in the project itself, measured
    ([scripts/host-limits.toml](../scripts/host-limits.toml), "plugin MCP door"), so there `--root .`
    is the project already.
  - A session folder that is no checkout gets no `.se`: that line goes to `~/.se/.runtime/mcp.log`.
- **A host that reads neither file**: `copilot mcp add se -- bash <se>/scripts/se_mcp.sh --root .`,
  or in VS Code `code --add-mcp
  '{"name":"se","command":"bash","args":["<se>/scripts/se_mcp.sh","--root","${workspaceFolder}"]}'`.
  - An installed plugin's `se` outranks `copilot mcp add`; then the door goes by hand, per
    session ([docs/copilot.md "The door by hand"](copilot.md#the-door-by-hand)).
- **What the door does not cover.**
  - Where the `se` binary is not in place as the server starts (a fresh machine, or a cloud
    snapshot older than the pin), the door offers only `status` for that whole session; the way to
    a template there is the command line, `templates.py draft <template> --json`.
  - In a claude.ai cloud session the plugin is the clone in `~/.claude/skills/se` (`se@skills-dir`,
    [Claude Code cloud](install.md#claude-code-cloud)); whether Claude Code starts that plugin's
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
| `templates` | `list`, `draft`, `check` | `components/templates` |
| `templates_write` | `fill`, which with `--repo` files the document it checked ([docs/templates.md "Fill"](templates.md#fill)) | `components/templates` |
| `github_write` | `github issue-create`, `github issue-comment`, from a filled template the template component made | kern's GitHub component |

- **Read-only, command by command.** A script names the commands that change nothing in its
  `READ_ONLY_COMMANDS`, each with its MCP description, when an agent uses it; `work_tickets.py
  docs` writes `read-only = true` and that `mcp` line into its declaration. `work_tickets.py queue`
  syncs the checkout (git fetch and merge), so no tool offers it.
- **Writing, through requests only.** A command its script names in `WRITING_COMMANDS`, with its
  MCP description, writes only through the request ports its `REQUESTS` declares, which
  `wiring.toml` binds to an I/O verb; `work_tickets.py docs` writes `writes = true` and the ports,
  and kern's door offers it in the tool `<instance>_write` (`templates_write`).
- **Generated, never written per tool.** A command group with read-only commands is one tool,
  named in snake_case: `command` is one of them, `args` its arguments, `page` the page of a long
  answer.
- **Approvals stay the host's.** Every read-only tool says `readOnlyHint` and not
  `destructiveHint`, which neither grants nor forces an approval; a writing tool says it writes. Allow a tool once per host: Copilot's CLI with
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
    note ([docs/copilot.md "What a session costs"](copilot.md#what-a-session-costs)).
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
the generated layout (`AGENTS.md`, `agents/`, `skills/`) and,
with `--tools`, the JSON of a `tools/list` answer, against what each agent host caps.

It prints one row per host, file or tool and subject, "over", "under" or "not measured", the
largest overrun first, then the bytes a session is always handed apart from those it loads on
demand.

- **The host facts** are one dated data file, `scripts/host-limits.toml`, whose header owns its
  layout; a limit it lacks is "not measured", never "under".
- **A report only**: it writes nothing, always exits 0, and no hook, check, build or suite runs it.
