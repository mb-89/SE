# SE under GitHub Copilot

Reader: the owner, installing SE into GitHub Copilot and calling it for the first time. This note
owns the opt-in install into another repository, the self-test and smoke test, the checklist for
the first run with Copilot, and the cloud agent's notes. The install line of each host is README
[Install](../README.md#install); the MCP door is README [The MCP door](../README.md#the-mcp-door).

`<owner>/<repository>` below is the owner and repository of the SE you install from: the
repository its checkout's origin names (`uv run python scripts/se_home.py tracker` prints it).

No session that built this had a Copilot token, so nothing here ran against a signed-in Copilot.
What a token-less Copilot CLI could show was run (below); everything else is on the
[checklist](#monday-checklist), each with what you should see.

## What a session costs

Read on 16 Nov 2026: GitHub's [usage-based billing for individuals][ubb], [models and
pricing][pricing], [requests in Copilot (legacy)][legacy], [AI credit session limits][limits] and
[hooks configuration][hooks], and Copilot CLI 1.0.112's own `copilot help billing` and
`copilot help limits`, which it prints without signing in.

- **Since 1 June 2026 a monthly plan pays in AI credits**, 1 credit = $0.01: each model call costs
  its tokens at the model's price, input, cache reads and writes, and output. Every call sends the
  conversation so far again, mostly from the cache at about a tenth of the input price; sub-agents
  and compaction count too. Copilot Pro includes 1,500 credits a month, Pro+ 7,000.
- **An annual Pro or Pro+ plan stays on premium requests**: one per prompt the person sends, times
  the model's multiplier; tool calls cost none, an autopilot continuation costs one. Pro includes
  300 a month, Pro+ 1,500.

So under AI credits nothing is free: one person prompt costs every model call the agent makes for
it. What SE adds on top are the paths below, each a model turn or a session the person did not ask
for. Each guard is on by default under Copilot only; its se.toml setting turns it off, and under
Claude Code nothing reads it.

| Path | What one person prompt can cost | Guard, and the setting that turns it off |
|---|---|---|
| The Stop hook refusing a stop, up to `[stop] refusals` (5) in a row | Each refusal is one more agent turn, its reason the prompt ([hooks][hooks]): credits for that turn's model calls, the whole conversation sent again each call. Premium requests on a legacy plan: not sourced; the docs count only the person's prompts and autopilot continuations. | The hook never refuses; it names what is undelivered as Copilot's hook warning, stderr with exit code 2. `[copilot] refuse_stop = true` |
| A session SE starts: a worker, the integrator, a reviewer (`create_session`, or the detached `copilot -p` line) | A whole agent run the person did not prompt: every model call of it in credits; one premium request per session on a legacy plan, more with its own Stop refusals. Not measured: no session here had a token. | SE starts none: it prints the line, and the person runs it. `[copilot] start_sessions = true` |
| In-chat sub-agents (`task`) | Their model calls count ([CLI billing help](#what-a-session-costs)). | None needed: SE never starts one, on either host ([Visible sessions](../src/skills/work-model/SKILL.md#visible-sessions)). |
| SE's start context: the agent, the greeting, the skills it loads | No extra request: it rides on the calls the person's prompt makes. 28,611 bytes always handed to `se` (`host_size.py report`, 16 Nov), about 7,000 tokens at 4 bytes a token (estimate), up to 129,999 bytes with every skill loaded. | None: a constant per call, mostly cached; a guard would remove SE's procedure. |

[ubb]: https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals
[pricing]: https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
[legacy]: https://docs.github.com/en/copilot/concepts/billing/copilot-requests
[limits]: https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/set-session-limit
[hooks]: https://docs.github.com/en/copilot/reference/hooks-configuration

With the defaults, a session costs only the model calls of the person's own prompts.
`[copilot] refuse_stop = true` adds up to five turns per undelivered stop, and
`[copilot] start_sessions = true` adds every session SE starts.

```toml
[copilot]
refuse_stop = false     # built in: the Stop hook never refuses under Copilot
start_sessions = false  # built in: SE prints the line that starts a session, never starts one
```

- **Where they show**: the greeting under Copilot ends with a `Copilot guards:` line naming each
  setting; `uv run python <se>/scripts/se_doctor.py` has a `copilot` row for each.
- **To cap a session yourself**: `--max-ai-credits <n>` (at least 30) on a `copilot -p` line, or
  `/limits set max-ai-credits <n>` in a session; sub-agents share it ([limits][limits]).
- **To measure one**: `--usage-output-file <file>` writes a session's credits, premium requests and
  tokens per model and per agent when it ends; `/usage` shows the running session.

## What a token-less Copilot CLI showed

Copilot CLI 1.0.112 (npm `@github/copilot`), in a cloud container on 14 Nov, with an empty home.
It reads plugins, skills and MCP servers without signing in; a session (`-p`, `--acp`) stops at
sign-in before it starts any MCP server.

- `copilot plugin marketplace add <owner>/<repository>` registered the marketplace `se`, and
  `copilot plugin install se@se` installed `se@se` 5.59.0 from the generated
  `.claude-plugin/marketplace.json`. `copilot plugin install <owner>/<repository>` installed it
  too, with a warning that direct installs are deprecated.
- The install takes the Copilot layout: `copilot skill list --json` gives `catch-up`, `decision`
  and `work-model` from the plugin's `.github/skills/`. With `.github/plugin/plugin.json` and
  `.github/mcp.json` removed, the CLI read `.claude-plugin/plugin.json` and gave no `se` server.
- `copilot mcp get se --json` in another repository: the plugin's `.github/mcp.json`, not the
  manifest's `mcpServers`, with `"cwd": "${PLUGIN_ROOT}"` and `PLUGIN_ROOT` set in its `env`.
  Removing that file gave the manifest's entry, with the same `cwd`.
- In SE's own checkout, `.github/mcp.json` loads only once the folder is trusted, as a workspace
  server without a `cwd`; the project's skills load without trust. With the plugin installed, the
  plugin's `se` hides it, trusted or not; `copilot plugin disable se` brings it back.
- `--additional-mcp-config` with a server `se` replaces the plugin's `se` in `copilot mcp list` and
  `copilot mcp get se`. A user-level `se` from `copilot mcp add` stays in
  `~/.copilot/mcp-config.json`, but `copilot mcp list` shows only the plugin's.
- The flags the smoke test and the worker launch line use exist in 1.0.112: `-C`, `--agent`,
  `--plugin-dir`, `-p`, `-n`, `--output-format`, `--allow-tool`, `--no-ask-user`,
  `--trust-folder`. A refused run still writes its JSON result line, `{"type": "result", ...,
  "exitCode": 1}`.

**Open point, for a Copilot run to decide:** a plugin's server starts in the plugin's folder, so
its `--root .` names that folder. The launcher then picks the session's repository: from
`SE_SESSION_CWD` or `COPILOT_SESSION_CWD`, else, on Linux and macOS, its parent's working
directory (README [The MCP door](../README.md#the-mcp-door)). No signed-in session has shown which
it gets. If `se-status` answers about the plugin's folder (or `no-checkout`), that is this.

## The door by hand

The remedy for the open point is one line per session, run inside the repository. It names the
repository itself, `git rev-parse --show-toplevel`, so it serves the repository the session runs
in, whichever that is. Where to see what the door chose is [Where to look](#where-to-look).

```sh
copilot --agent se --additional-mcp-config "{\"mcpServers\":{\"se\":{\"type\":\"local\",\"command\":\"bash\",\"args\":[\"<se>/scripts/se_mcp.sh\",\"--root\",\"$(git rev-parse --show-toplevel)\"],\"tools\":[\"*\"]}}}"
```

- **Why this source.** An `--additional-mcp-config` server outranks a plugin's, as GitHub documents
  and as Copilot CLI 1.0.112 showed on 14 Nov: its `se` replaced the plugin's in `copilot mcp list`
  and `copilot mcp get se`. A signed-in session has not shown it yet.
- **Why the name `se`.** The worker and the reviewer are strict on `se/*`: their tools list admits
  the server `se` and no other. The se agent itself has no tools list.
- **No user-level `se`.** A server added with `copilot mcp add` does not help while the plugin is
  installed: user config ranks below plugins, and it pins every session to one repository. In
  1.0.112 a user-level `se` stayed in `~/.copilot/mcp-config.json`, but `copilot mcp list` showed
  only the plugin's.

### Windows

In PowerShell, write the entry to a file and name it with `@`. First check which `bash` the door
would get: `(Get-Command bash).Source` must be Git Bash (`...\Git\bin\bash.exe` or
`...\Git\usr\bin\bash.exe`), not the WSL launcher under `C:\Windows\System32`. Write `<se>` with
`/`.

```powershell
$repo = git rev-parse --show-toplevel
$json = '{"mcpServers":{"se":{"type":"local","command":"bash","args":["<se>/scripts/se_mcp.sh","--root","REPO"],"tools":["*"]}}}'
[IO.File]::WriteAllText("$env:TEMP\se-mcp.json", $json.Replace('REPO', $repo))
copilot --agent se --additional-mcp-config "@$env:TEMP\se-mcp.json"
```

Where `bash` is not Git Bash, the same file names PowerShell's launcher instead:

```powershell
$json = '{"mcpServers":{"se":{"type":"local","command":"powershell","args":["-NoProfile","-ExecutionPolicy","Bypass","-File","<se>/scripts/se_mcp.ps1","--root","REPO"],"tools":["*"]}}}'
```

### SE's own checkout

An installed plugin's `se` hides the checkout's `.github/mcp.json` server, trusted or not (seen on
14 Nov in 1.0.112). The plugin's launcher then finds the checkout, an SE checkout, and hands over
to the checkout's own `scripts/se_mcp.sh`, so the door still serves it. Where it does not:

- `copilot plugin disable se` brings the workspace server back (seen the same day);
- or the `--additional-mcp-config` line above, run in the checkout, so with the checkout as root.

`copilot --plugin-dir=.` works as today.

### Hooks

The plugin's hooks run the plugin's own scripts, `$PLUGIN_ROOT/scripts/bootstrap.sh` and
`se_hook.sh`, and skip SE's checkout, where `.github/hooks/se.json` runs the checkout's. Where
another repository shows no greeting, start SE by hand inside it:
`env -u CLAUDE_PROJECT_DIR bash <se>/scripts/bootstrap.sh --hook </dev/null`.

First check the repository for a `scripts/bootstrap.sh` or `scripts/se_hook.sh` of its own: a
relative `bash scripts/...` there runs that one, not SE's, so always name SE's by its full path.

### VS Code

VS Code's own parser takes SE as a Claude-format plugin: it checks `.claude-plugin/plugin.json`
before `.github/plugin/plugin.json`. So the plugin brings no `se` server there, and its hooks use
`${CLAUDE_PLUGIN_ROOT}`. Always add the user-level door, README's `code --add-mcp` line with
`${workspaceFolder}` ([The MCP door](../README.md#the-mcp-door)).

- That expansion in a user profile is unverified. The fallback is `<repo>/.vscode/mcp.json` with
  the same entry: `{"servers": {"se": {"type": "stdio", "command": "bash", "args":
  ["<se>/scripts/se_mcp.sh", "--root", "${workspaceFolder}"]}}}`.
- The check is **MCP: List Servers**: it lists `se` and its state; **Show Output** shows its start.

### Where to look

The first check is the launcher's decision line, `plugin <folder>: root <root> from <source>`, in
`.se/.runtime/mcp.log`: in the repository it chose, or in the plugin's folder (`PLUGIN_ROOT` in
`copilot mcp get se --json`) where it kept that. For a session folder with no `.git` in it or
above it, the line is in `~/.se/.runtime/mcp.log`. Where none has a line, the launcher never ran:
`/mcp` shows the server's start error.

## Another repository

`scripts/setup.sh <repo> --copilot` (or `scripts/setup.ps1 -Repo <repo> -Copilot`) installs the
hooks as without the flag, then `scripts/copilot.py install`:

- merges into `<repo>/.github/copilot/settings.json`, keeping every other key,
  `{"extraKnownMarketplaces":{"se":{"source":{"source":"github","repo":"<owner>/<repository>"}}},"enabledPlugins":{"se@se":true}}`
  (on a host other than GitHub, `{"source":"git","url":"<home>.git"}`);
- pins `[modules.se]` in `<repo>/se.toml` at `^MAJOR.MINOR` of the SE that ran it, keeping an
  existing pin, ignores `.se/` in git, and runs `se_modules.py --root <repo> sync se`.

Without `--copilot` nothing of this happens. `copilot.py install --repo <repo> --no-sync` pins
without cloning. The marketplace `se@se` names is the generated `.claude-plugin/marketplace.json`.

## Self-test

`uv run python scripts/copilot.py self-test` needs neither Copilot nor a person. It copies SE, as
a plugin install does, beside an empty git project that is not SE, and checks there:

- the layout the Copilot manifest names, and `se_plugin.py check` of the copy;
- the hook registrations of `.github/hooks/se.json`;
- the launcher the manifest runs, with `${PLUGIN_ROOT}` the copy;
- the door started as Copilot starts a plugin's server: in the copy with `--root .` and
  `PLUGIN_ROOT` set, its parent process in the project. It runs once with `COPILOT_SESSION_CWD`
  naming the project and once without, from an environment without `CLAUDE_PROJECT_DIR`,
  `SE_SESSION_CWD`, `PLUGIN_ROOT` and every `COPILOT_*` variable;
- in each run the MCP handshake, `tools/list` and one `status` call. It passes only where
  `status` names the project, and is `noted`, naming the root it got, otherwise (the open point).
  Without the variable, Windows has no parent's working directory to read, so it is noted there;
- with a Copilot CLI on `PATH` (or `--cli <path>`), what it reads of the copy without signing in;
  otherwise that line is `skipped`.

It stops the core and removes the folder (`--keep` keeps it). It ends `copilot self-test: <n>
passed, <n> failed, <n> skipped, <n> noted`, exit code 0 without a failure. The door runs SE's
start's release in `~/.se/bin`; `--build` builds it from the checkout. The suite runs it beside
itself with `--build` (`se.toml` `[tests.beside.copilot-self-test]`).

## Smoke test

`bash scripts/copilot_smoke.sh` runs the pinned Copilot CLI once from SE's checkout:
`copilot --plugin-dir=. --agent se -p status --output-format json --allow-tool='se'
--no-ask-user --trust-folder`, through `npx` on Node 22 or later.

- `scripts/copilot.py smoke-verdict` reads its JSON lines and passes where they hold the greeting
  `SE <version> started:` and one call of an `se` tool that did not fail.
- It prints one line, `copilot smoke: passed|failed|skipped: <why>`; exit code 0, 1 or 2.
  Without `COPILOT_GITHUB_TOKEN` it is `skipped`, never `failed`.
- `--record` also writes the run to `tests/fixtures/copilot/smoke.jsonl`. Until then the helper's
  test reads `smoke.synthetic.jsonl`, written by hand and marked `"synthetic": true`.

## Monday checklist

Each step names the points of the Copilot work it settles (#1121, #1122, #1123); "Expect" is what
you should see, and a known difference links its [remedy](#remedies). Steps 1 to 5 are in SE's
own checkout. Steps 6 and 7, a plugin install in VS Code and another repository, are **expected
to differ (documented)**: a difference there is a finding, not a failure.

After each step, note: as expected, differs, or not run; the minutes it took; and what you needed
beyond the written step. The notes go into [`copilot-cold-run.toml`](copilot-cold-run.toml), and
the filled file is pasted as the comment on #1172, "Monday: the owner's first Copilot run".

1. **Copilot CLI, SE's checkout.** In a checkout of SE, with the CLI installed
   (`npm install -g @github/copilot@1.0.112`), run `uv run python scripts/copilot.py self-test`;
   then `copilot --agent se`, trusting the folder ([trust](#remedies)), and say `status`.
   - Expect `copilot self-test: 10 passed, 0 failed, 0 skipped, 1 noted`, the noted line being the
     [open point](#what-a-token-less-copilot-cli-showed), `mcp-root`.
   - Expect the greeting `SE <version> started: ...` once (#1121: the agents, skills and
     `SessionStart` load with `SE_HOOK_HOST`; #1123: the greeting reaches the session, and where
     kern fails, the line `SE runs without kern: ...` too).
   - Expect `se-status` to answer `se: running in <checkout>, ...` and `copilot mcp get se` to list
     the server (#1122: the door spawns and lists `greeting`, `integration`, `overhaul`, `status`,
     `tickets`; #1123: `se/*` admits them). Tools [not shown](#remedies), or
     [`not-installed`](#remedies), have a remedy.
   - Ask for `tickets` and `integration` `fleet-check`. Expect answers, a long one in pages; a first
     call right after the start may answer `starting`, the next one the result (#1122: paging,
     `starting`, the tool timeout).
   - End the turn. Expect the `Stop` hook to run the delivery check, silent here (#1121); an
     [advising stop](#remedies) is safe.
   - A silent `Stop` leaves no trace on main: kern logs no hook event. Step 4's worker run is where
     it shows, as the hook warning `se Stop hook, advice only under Copilot ...` while that worker
     is undelivered. If it never shows there, the `Stop` hook never ran: note it in the cold-run
     record.
   - A draft skill by name: in a scratch copy, set `se.toml` `[plugin] draft_skills = ["<draft>"]`,
     build (`scripts/se_plugin.py`), run `copilot --agent se` there. Expect `/<draft>` to load it
     and no turn to load it unasked; note the result in step 1's record.
2. **VS Code, SE's checkout.** Open the checkout with no install, trust it ([trust](#remedies)),
   add the door with the user-level line of README [The MCP door](../README.md#the-mcp-door)
   (`code --add-mcp ...`), pick the session target Copilot and the agent `se`, say `status`.
   - Expect the agent list to hold `se`, `integrator`, `reviewer`, `worker`, the greeting once, and
     `se/status` answering without an approval asked, as it says `readOnlyHint` (#1122). Then
     remove the user-level line and reload: expect the same from `.github/mcp.json`, read with its
     `mcpServers` key (#1123).
3. **A real request, on a safe target.** In the session of step 1, ask `se` to file one small work
   issue as a person step (label `se-person`), so no worker takes it into the live fleet; or close
   it as not planned right after. Expect `se` to say what it files, file it, and name it.
4. **Plugin install, resume and the worker launch line, CLI.** `copilot plugin marketplace add
   <owner>/<repository>`, `copilot plugin install se@se`, then `copilot --agent se` in the checkout.
   - Expect the greeting once, though the checkout and the plugin both register hooks (#1121: the
     plugin's hooks skip SE's checkout, [Hooks](#hooks); the guard keeps a second start quiet; the
     plugin's Claude hooks fail open). The plugin's `se` hides the checkout's server here
     ([SE's own checkout](#ses-own-checkout)).
   - In a new run, `--allow-tool='se(status)'`: expect no prompt for `se-status` (#1122). Then
     `copilot --continue`: expect `se-status` to answer, the core kept or started again (#1121).
   - Expect `se` to print that line rather than run it ([What a session costs](#what-a-session-costs)).
     Run the worker launch line of the work model's "Host procedure under Copilot" once on step 3's
     issue: expect `copilot` to take `-C`, `--trust-folder`, `--no-ask-user`, `--allow-tool`, `-n`
     and `-p`, and to go on detached (#1123). Close the issue as not planned.
   - Quit every session. Expect `se status --root <checkout>` to show no session once the core's
     grace ends (#1122: the lease returns on EOF and SIGTERM).
5. **Windows**, with Git for Windows. Repeat step 1 there. Expect the greeting and `se-status`
   (#1121: the PowerShell hook commands run with `bash` on the `PATH`; #1123: `bash` reaches the MCP
   command, `se_mcp.ps1` passes standard input and output through, see [no bash](#remedies)). Rename
   `~/.se/bin/se-<version>.exe` for one session: expect `se-status` to answer `not-installed`
   naming SE's start, Copilot accepting the stand-in door (#1123); rename it back.
6. **VS Code, another repository** (expected to differ, documented). **Chat: Install Plugin from
   Source** with `https://github.com/<owner>/<repository>`; no trust prompt, which shows only for marketplace
   and deep-link installs. Add the user-level door ([VS Code](#vs-code)), pick Copilot and `se`,
   say `status`. Expect the greeting and the user-level door's `se/status` naming that repository
   (#1123: VS Code reads the install as a Claude-format plugin, so the door is the user-level
   one, `${workspaceFolder}` expands, the server's working directory). An answer about another
   folder is the open point.
7. **Copilot CLI, another repository** (expected to differ, documented). `bash
   <se>/scripts/setup.sh <repo> --copilot`, then `copilot --agent se` in `<repo>`. Expect
   `copilot install: ...` lines and `se: pinned` from the sync, the greeting, and `se-status`
   naming `<repo>`; the open point otherwise, with its remedy [The door by hand](#the-door-by-hand).
8. **On anything else**, at any step: `uv run python <se>/scripts/se_doctor.py`, and paste its whole
   report with the step's number into SE's session.
9. **Record the smoke test.** In SE's checkout, `COPILOT_GITHUB_TOKEN=<token> bash
   scripts/copilot_smoke.sh --record`. Expect `copilot smoke: passed: greeting ... and se tool status
   answered`; commit `tests/fixtures/copilot/smoke.jsonl` once `uv run python
   scripts/public_check.py --repo .` passes over it.

Claude Code's spawn of the door through a root `.mcp.json` (#1122) is no Copilot point and not on
this list: no such file is committed. The cloud agent's point (#1121) is in its own section below,
with its own "Expect", as trying it is optional.

### Remedies

Each is an expected result with its one-line remedy.

- **Folder trust.** Project MCP servers and hooks load only in a trusted folder. CLI: answer the
  trust prompt with "Yes, and remember this folder", or `--trust-folder` for one run (it lands in
  `trustedFolders` of `~/.copilot/config.json`). VS Code: **Workspaces: Manage Workspace Trust**,
  then **Trust**.
- **The `se` tools do not show.** Tool search may defer them: `/mcp get se` shows the server and
  its tools. CLI: set `"toolSearch": false` in `~/.copilot/settings.json` for a new session, so
  every tool loads at turn start. VS Code: turn the `se` tools on in the chat's tool picker.
- **`not-installed`.** The host spawned the door before SE's start fetched the binary: restart the
  `se` server once (CLI `/mcp reload`; VS Code **MCP: List Servers**, `se`, **Restart**).
- **No `bash` on Windows.** CLI: the `@file` whose command is `powershell` with `se_mcp.ps1`
  ([Windows](#windows)); VS Code: `code --add-mcp` with the same `command` and `args`.
- **An advising stop.** Copilot's stop event carries no agent name, so the delivery check can judge
  SE's own session as a worker's in a checkout whose ticket queue is for a work issue, off the
  integration branch. You see the hook warning `se Stop hook, advice only under Copilot ...`,
  naming what is undelivered; the turn ends. With `[copilot] refuse_stop = true` it refuses
  instead, `se Stop hook (1 of 5 in a row): ...`, and lets the turn end after five.

## The default agent

Where the environment sets `SE_DEFAULT_AGENT=se`, Copilot's session start hands over the same
sentence as Claude Code's, in `additionalContext`: the session acts as the se agent
([README "Claude Code cloud"](../README.md#claude-code-cloud)). A session that picks its agent
with `--agent` or its agent list keeps that agent, as does one whose first message names another.

## Cloud agent, optional and untested

The docs disagree on whether Copilot's cloud agent loads plugins; they agree on where it takes its
MCP servers from and that its runner needs `se` and `uv`. Nothing is generated for it.

- **Try it**: on github.com, assign an issue of SE's repository to Copilot, or start a task in its
  **Agents** tab, and pick `se`. Expect the session to open with SE's greeting, its agents and
  skills loaded from `.github/` (#1121).
- **The door**: in the repository's **Settings**, Copilot, cloud agent, MCP configuration, paste
  `{"mcpServers": {"se": {"type": "local", "command": "bash", "args": ["scripts/se_mcp.sh",
  "--root", "."], "tools": ["*"]}}}`; an agent file's `mcp-servers` takes the same entry.
- **The runner**: `.github/workflows/copilot-setup-steps.yml`, a job `copilot-setup-steps` whose
  steps check out the repository, install `uv` (`astral-sh/setup-uv`) and run
  `bash scripts/bootstrap.sh --hook`, which fetches the `se` binary into `~/.se/bin`.
