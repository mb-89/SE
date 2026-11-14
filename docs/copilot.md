# SE under GitHub Copilot

Reader: the owner, installing SE into GitHub Copilot and calling it for the first time. This note
owns the opt-in install into another repository, the self-test and smoke test, the checklist for
the first run with Copilot, and the cloud agent's notes. The install line of each host is README
[Install](../README.md#install); the MCP door is README [The MCP door](../README.md#the-mcp-door).

No session that built this had a Copilot token, so nothing here ran against a signed-in Copilot.
What a token-less Copilot CLI could show was run (below); everything else is on the
[checklist](#monday-checklist), each with what you should see.

## What a token-less Copilot CLI showed

Copilot CLI 1.0.112 (npm `@github/copilot`), in a cloud container on 14 Nov, with an empty home.
It reads plugins, skills and MCP servers without signing in; a session (`-p`, `--acp`) stops at
sign-in before it starts any MCP server.

- `copilot plugin marketplace add mb-89/SE` registered the marketplace `se`, and `copilot plugin
  install se@se` installed `se@se` 5.59.0 from the generated `.claude-plugin/marketplace.json`.
  `copilot plugin install mb-89/SE` installed it too, with a warning that direct installs are
  deprecated.
- The install takes the Copilot layout: `copilot skill list --json` gives `catch-up`, `decision`
  and `work-model` from the plugin's `.github/skills/`. With `.github/plugin/plugin.json` and
  `.github/mcp.json` removed, the CLI read `.claude-plugin/plugin.json` and gave no `se` server.
- `copilot mcp get se --json` in another repository: the plugin's `.github/mcp.json`, not the
  manifest's `mcpServers`, with `"cwd": "${PLUGIN_ROOT}"` and `PLUGIN_ROOT` set in its `env`.
  Removing that file gave the manifest's entry, with the same `cwd`.
- In SE's own checkout, `.github/mcp.json` loads only once the folder is trusted, as a workspace
  server without a `cwd`; the project's skills load without trust.
- The flags the smoke test and the worker launch line use exist in 1.0.112: `-C`, `--agent`,
  `--plugin-dir`, `-p`, `-n`, `--output-format`, `--allow-tool`, `--no-ask-user`,
  `--trust-folder`. A refused run still writes its JSON result line, `{"type": "result", ...,
  "exitCode": 1}`.

**Open point, for a Copilot run to decide:** a plugin's server starts in the plugin's folder, so
its `--root .` names that folder, not the project. If `se-status` in another repository answers
about the plugin's folder (or `no-checkout`), that is this. Until it is fixed, add the door for
that repository by hand, `copilot mcp add se -- bash <se>/scripts/se_mcp.sh --root <repo>`.
The same may hold for the hooks' `bash scripts/...` commands in another repository.

## Another repository

`scripts/setup.sh <repo> --copilot` (or `scripts/setup.ps1 -Repo <repo> -Copilot`) installs the
hooks as without the flag, then `scripts/copilot.py install`:

- merges into `<repo>/.github/copilot/settings.json`, keeping every other key,
  `{"extraKnownMarketplaces":{"se":{"source":{"source":"github","repo":"mb-89/SE"}}},"enabledPlugins":{"se@se":true}}`;
- pins `[modules.se]` in `<repo>/se.toml` at `^MAJOR.MINOR` of the SE that ran it, keeping an
  existing pin, ignores `.se/` in git, and runs `se_modules.py --root <repo> sync se`.

Without `--copilot` nothing of this happens. `copilot.py install --repo <repo> --no-sync` pins
without cloning. The marketplace `se@se` names is the generated `.claude-plugin/marketplace.json`.

## Self-test

`uv run python scripts/copilot.py self-test` needs neither Copilot nor a person. It copies SE, as
a plugin install does, beside an empty git project that is not SE, and checks there:

- the layout the Copilot manifest names, and `se_plugin.py check` of the copy;
- the hook registrations of `.github/hooks/se.json`;
- the launcher the manifest runs, with `${PLUGIN_ROOT}` the copy, in the project;
- the MCP handshake, `tools/list` and one `status` call, which starts a core in the project;
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

Each step names the points of the Copilot work it settles (#1121, #1122, #1123). "Expect" is what
you should see.

1. **Self-test.** In a checkout of SE, with the Copilot CLI installed
   (`npm install -g @github/copilot@1.0.112`): `uv run python scripts/copilot.py self-test`.
   Expect `copilot self-test: 9 passed, 0 failed, 0 skipped, 1 noted`, the noted line being the
   [open point](#what-a-token-less-copilot-cli-showed).
2. **VS Code, SE's checkout.** Open the checkout, trust it, pick the session target Copilot and
   the agent `se`, and say `status`.
   - Expect the agent list to hold `se`, `integrator`, `reviewer`, `worker`; the first answer to
     open with `SE <version> started: ...`, once per session (#1121: the agents and skills load,
     `SessionStart` fires with `SE_HOOK_HOST`; #1123: the greeting reaches the session, and where
     kern fails, the line `SE runs without kern: ...` too).
   - Expect a call of `se/status` answering `se: running in <checkout>, ...` with no approval asked,
     as it says `readOnlyHint` (#1123: VS Code reads `.github/mcp.json` with its `mcpServers` key,
     `se/*` admits the tools; #1122: the door spawns and lists `greeting`, `integration`,
     `overhaul`, `status`, `tickets`).
   - Ask for `tickets` and for `integration` `fleet-check`. Expect each to answer; a long one in
     pages, read page by page; a first call right after the start may answer `starting`, and the
     next one, a few seconds on, the result (#1122: paging, `starting`, the tool timeout).
   - End the session. Expect `se status --root <checkout>` to show one session fewer once the core's
     grace ends (#1122: the lease returns on EOF).
3. **VS Code, another repository.** **Chat: Install Plugin from Source** with
   `https://github.com/mb-89/SE`; no trust prompt (it shows only for marketplace and deep-link
   installs). Pick Copilot and `se`, say `status`.
   - Expect the greeting and `se/status` naming that repository (#1123: the install picks
     `.github/plugin/plugin.json` and its four fields, `${PLUGIN_ROOT}` expands, the server's
     working directory). An answer naming the plugin's folder is the open point.
4. **Copilot CLI, SE's checkout.** `copilot plugin marketplace add mb-89/SE`, `copilot plugin
   install se@se`, then in the checkout `copilot --agent se`, trusting the folder; say `status`.
   - Expect `copilot mcp get se` to list the server (#1123), the greeting once, though hooks fire
     from the checkout and the plugin (#1121: the guard keeps the second start quiet; the plugin's
     Claude hooks fail open), and `se-status` answering.
   - Allow one tool with `--allow-tool='se(status)'` in a new run: expect no prompt for it (#1122).
   - End the turn. Expect the `Stop` hook to run the delivery check, silent outside a worker
     (#1121).
5. **Copilot CLI, another repository.** `bash <se>/scripts/setup.sh <repo> --copilot`, then
   `copilot --agent se` in `<repo>`. Expect `copilot install: ...` lines and `se: local` or
   `se: pinned` from the sync; then the greeting, and `se-status` naming `<repo>` (the open point
   otherwise).
6. **Resume and the worker launch line.** `copilot --continue` in SE's checkout: expect `se-status`
   to answer, the core kept or started again (#1121). Run the worker launch line of the work model's
   "Host procedure under Copilot" once on a scratch issue: expect `copilot` to take `-C`,
   `--trust-folder`, `--no-ask-user`, `--allow-tool`, `-n` and `-p`, and to go on detached (#1123).
7. **Windows**, with Git for Windows. Repeat step 4 there. Expect the greeting and `se-status`
   (#1121: the PowerShell hook commands run with `bash` on the `PATH`; #1123: `bash` reaches the MCP
   command, and `se_mcp.ps1` passes standard input and output through). Then rename
   `~/.se/bin/se-<version>.exe` for one session: expect `se-status` to answer `not-installed`
   naming SE's start, Copilot accepting the stand-in door (#1123); rename it back.
8. **On anything else**, at any step: `uv run python <se>/scripts/se_doctor.py`, and paste its whole
   report with the step's number into SE's session.
9. **Record the smoke test.** In SE's checkout, `COPILOT_GITHUB_TOKEN=<token> bash
   scripts/copilot_smoke.sh --record`. Expect `copilot smoke: passed: greeting ... and se tool status
   answered`; commit `tests/fixtures/copilot/smoke.jsonl` once `uv run python
   scripts/public_check.py --repo .` passes over it.

Claude Code's spawn of the door through a root `.mcp.json` (#1122) is no Copilot point and not on
this list: no such file is committed. The cloud agent's point (#1121) is in the next section, with
its own "Expect", as trying it is optional.

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
