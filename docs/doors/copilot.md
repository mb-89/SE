# The Copilot manifest and hooks: outside facts

Reader: whoever changes SE's Copilot manifest, its hooks or its Copilot checks
([scripts/se_plugin.py](../../scripts/se_plugin.py), [scripts/agent_lint.py](../../scripts/agent_lint.py)),
or checks a Copilot fact they rest on. This note owns the outside facts that manifest and those hooks
rely on that no script reads: each with its source, the day it was read and how sure SE is of it.
Last read: 2026-11-14.

Main declares no Copilot door: [scripts/doors/](../../scripts/doors/) holds git's, GitHub's and the
MCP door's declarations only, and the MCP door's facts are [mcp.md](mcp.md).
[scripts/host-limits.toml](../../scripts/host-limits.toml) is the one home for host facts a script
reads: each limit, surface and registration with its source and date. An item here is prose
evidence that no script reads; once a row holds its fact, the item links the row and drops its own
wording.

The install, the self-test and the owner's checklist are [docs/copilot.md](../copilot.md), and what
a token-less Copilot CLI showed is its section
[What a token-less Copilot CLI showed](../copilot.md#what-a-token-less-copilot-cli-showed), linked
and not restated. The record of the owner's first run, [docs/copilot-cold-run.toml](../copilot-cold-run.toml),
is not filled on main yet, so no item below comes from it.

Each item carries one mark, the one a host-limits row would take. `documented`: a host's page says
it. `seen`: a run showed it, what host-limits calls `measured`. `silent`: no page says it, and the
item names the pages read. `assumed`: SE's code relies on it and no page or run shows it, and the
item links the file that assumes it.

## Manifests

- **CLI manifest order.** The Copilot CLI looks for a legacy plugin's manifest in a fixed order,
  Copilot's places before the Claude one, and an Agent Plugins manifest, a root manifest that
  declares that spec, takes precedence over them; the order is the `plugin manifest` row of
  `registrations.copilot-cli` in [scripts/host-limits.toml](../../scripts/host-limits.toml).
  Source: https://docs.github.com/en/copilot/reference/cli-plugin-reference, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py), its
  `MANIFEST_LOOKUPS`.
- **VS Code manifest order.** VS Code detects a plugin's format from its root manifest first, an
  Agent Plugins one where it declares that schema and Copilot's otherwise, then the format-specific
  places, Claude's `.claude-plugin/plugin.json` among them; `.github/plugin/plugin.json` is not one
  of its places. Source: https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference,
  read 2026-11-14. `documented`. SE acts on it in [docs/copilot.md "VS Code"](../copilot.md#vs-code).
- **The install took the Copilot manifest.** A Copilot CLI plugin install of SE read the Copilot
  manifest, not the Claude one, as recorded in
  [docs/copilot.md](../copilot.md#what-a-token-less-copilot-cli-showed): Copilot CLI 1.0.112, in a
  Linux cloud container, on 2026-11-14, without signing in. `seen`. SE acts on it in
  [scripts/se_plugin.py](../../scripts/se_plugin.py), which writes that manifest.
- **Copilot's agents and Claude Code's skills.** The Copilot CLI loads Claude Code's skills folder
  where the manifest's `skills` names it. It also loads agents written as Claude Code's
  `agents/<name>.md`, warning `unknown field ignored: disallowedTools`, and reads Claude's tool
  names as aliases; SE gives it exactly those files, with no Copilot copy and no `tools` list
  ([docs/copilot.md](../copilot.md#the-door-by-hand)). A `model: inherit` it does
  not inherit: it warns `Custom agent "probe" specifies model "inherit" which is not available;
  using "auto" instead` and runs the agent. A `target` it ignores with `unknown field ignored:
  target` and lists the agent. A relative link in an agent's body it resolves from the session's
  folder, not the file's. Copilot CLI 1.0.112 on Windows, 2026-11-23. `seen`. SE acts on it in
  [scripts/se_plugin.py](../../scripts/se_plugin.py), whose Copilot manifest names
  `agents/` and `skills/`, and [scripts/agent_lint.py](../../scripts/agent_lint.py),
  `CLAUDE_AGENT_FIELDS`.
- **A `vscode` agent is not in VS Code's Copilot pickers.** The Chat view's mode picker, with the
  session target Copilot, and the Agents window's list an agent only if its `target` is
  `github-copilot` or unset; the local harness lists all. `target` otherwise sets which schema the
  editor checks the file against, and `user-invocable: false` hides an agent from every picker.
  VS Code reads a plugin with `.claude-plugin/plugin.json` as Claude-format, its agents from
  `agents/`, while its Copilot runtime reads the plugin's Copilot manifest. Sources:
  microsoft/vscode `src/vs/workbench/contrib/chat/browser/widget/input/modePickerActionItem.ts`
  (`getActionsForCustomAgentTarget`), `.../sessions/providers/copilotChatSessions/browser/modePicker.ts`
  (`getAvailableModes`), `.../chat/common/promptSyntax/languageProviders/promptFileAttributes.ts`
  (`getTarget`) and `src/vs/platform/agentPlugins/common/pluginParsers.ts`
  (`detectManifestPluginFormat`), main, read 2026-11-23; the custom agent file reference. `documented`.
  SE sets no `target`: its one file per agent must show in every picker
  ([docs/copilot.md "VS Code"](../copilot.md#vs-code)).

## Front matter

- **Agent fields.** GitHub's custom agent reference names `name`, `description` (required),
  `target`, `tools`, `model`, `disable-model-invocation`, `user-invocable`, the retired `infer`,
  and `mcp-servers` and `metadata`, which IDEs do not use; VS Code's reference adds
  `argument-hint`, `agents`, `model-policy`, `reasoning-effort`, `skills`, `deferred-tool-loading`,
  `strict-tools-list`, `include-custom-instructions`, `github`, `handoffs`, `hooks` and the
  Local-only `advancedOptions`. Sources: https://docs.github.com/en/copilot/reference/custom-agents-configuration
  and https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference, each read 2026-11-14. `documented`. SE acts on it in [scripts/agent_lint.py](../../scripts/agent_lint.py),
  `COPILOT_AGENT_FIELDS`, whose comment cites the fact check of 14 Nov: this item is its source.
- **Fields the cloud agent ignores.** Copilot on github.com ignores `argument-hint` and `handoffs`,
  and VS Code describes `handoffs` as suggestions of its Local harness, which is deprecated. Sources:
  https://docs.github.com/en/copilot/reference/custom-agents-configuration and
  https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference, each read 2026-11-14. `documented`. SE acts on it in [scripts/agent_lint.py](../../scripts/agent_lint.py),
  which offers neither `handoffs` nor `agents`.
- **Unknown tool names.** Copilot ignores a tool name it does not know, so an agent can list a
  tool of another host. Source: https://docs.github.com/en/copilot/reference/custom-agents-configuration,
  read 2026-11-14. `documented`. SE acts on it in [scripts/agent_lint.py](../../scripts/agent_lint.py),
  where an unknown tool name is no finding.
- **Skill fields.** VS Code reads a skill's `name`, `description`, `argument-hint`,
  `user-invocable` and `disable-model-invocation`, and does not load a skill whose name does not
  match its folder; the name and description caps are the `skill-name` and `skill-description` rows of
  `limits` in [scripts/host-limits.toml](../../scripts/host-limits.toml). Source:
  https://code.visualstudio.com/docs/copilot/customization/agent-skills, read 2026-11-14.
  `documented`. SE acts on it in [scripts/agent_lint.py](../../scripts/agent_lint.py).
- **Project names win over a plugin's.** The CLI loads agents and skills first-found-wins, so a
  project's agent or skill hides a plugin's of the same name, silently. Source:
  https://docs.github.com/en/copilot/reference/cli-plugin-reference, read 2026-11-14.
  `documented`. SE acts on it in [docs/copilot.md "SE's own checkout"](../copilot.md#ses-own-checkout).

## Hooks

- **Every hook source runs.** The Copilot CLI loads hooks from policy, user, project and plugin
  sources and runs every entry of an event from all of them; it deduplicates none. Source:
  https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py), whose plugin
  hooks skip SE's checkout, and [docs/copilot.md "Hooks"](../copilot.md#hooks).
- **The event name sets the payload.** An event registered in camelCase gets camelCase fields; one
  in PascalCase gets snake_case fields, VS Code's Copilot format, and a PascalCase `PreToolUse`
  uses Claude's matchers and tool names. Source:
  https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py),
  `COPILOT_HOOKS`, which registers PascalCase events.
- **The stop payload names no agent.** The `agentStop` (`Stop`) payload carries the session,
  working directory, transcript and stop reason, but no agent name; sub-agents fire `subagentStop`.
  Source: https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [docs/copilot.md "Remedies"](../copilot.md#remedies), a refused
  stop.
- **What reaches the session at start.** Of a `sessionStart` hook's answer only a top-level
  `additionalContext` is consumed, and output that does not parse as one JSON object counts as
  none. Source: https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_start.py](../../scripts/se_start.py), which answers
  Copilot in that shape.
- **A stop blocks only by its answer.** A stop hook blocks with `decision` `"block"` and a
  non-empty `reason` on standard output, which forces another turn; after a run of consecutive
  blocks the CLI ends the turn anyway. Source:
  https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [README.md "Stop hook"](../../README.md#stop-hook).
- **A non-zero exit, per event.** In the CLI a hook's exit code 2 is a warning, except that it
  denies for `preToolUse` and `permissionRequest` and becomes context for `postToolUseFailure`;
  any other non-zero exit is logged and the run goes on, except for `preToolUse`, which fails
  closed. Source: https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14. `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py),
  whose hook lines always exit 0.
- **A time-out fails open.** A hook past its time limit is logged and skipped on every event,
  `preToolUse` included; the default limit is the `hook-timeout` rows of `limits` in
  [scripts/host-limits.toml](../../scripts/host-limits.toml). Source:
  https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py), which sets
  each hook's `timeoutSec`.
- **VS Code's exit codes.** VS Code's hook reference reads exit code 2 as a blocking error whose
  standard error goes to the model, and any other non-zero exit as a warning. Source:
  https://code.visualstudio.com/docs/agents/reference/hooks-reference, read 2026-11-14.
  `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py), whose hook
  lines always exit 0.
- **Repository hooks in prompt mode.** In prompt mode (`-p`) the CLI loads a repository's hooks
  only in a trusted folder, with `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS` set, or with
  `COPILOT_ALLOW_ALL`. Source: https://docs.github.com/en/copilot/reference/cli-command-reference,
  read 2026-11-14. `documented`. SE acts on it in [docs/copilot.md "Remedies"](../copilot.md#remedies),
  folder trust.

## The cloud agent

- **Cloud hooks.** A cloud agent job runs only the cloned repository's hook files, fires a subset
  of the events and honours only the `bash` entries; the files are the `hooks` row of
  `registrations.copilot-cli` in [scripts/host-limits.toml](../../scripts/host-limits.toml).
  Source: https://docs.github.com/en/copilot/reference/hooks-configuration, read 2026-11-14.
  `documented`. SE acts on it in
  [docs/copilot.md "Cloud agent, optional and untested"](../copilot.md#cloud-agent-optional-and-untested).
- **No plugins in the cloud.** The cloud agent's sandbox ships no installed plugins, user hook
  files or user settings. Source: https://docs.github.com/en/copilot/reference/hooks-configuration,
  read 2026-11-14. `documented`. SE acts on it in
  [docs/copilot.md "Cloud agent, optional and untested"](../copilot.md#cloud-agent-optional-and-untested).
- **Cloud MCP servers.** The cloud agent takes MCP servers from the repository's MCP settings or
  an agent's `mcp-servers`, and passes them only secrets and variables named `COPILOT_MCP_...`.
  Sources: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/extend-cloud-agent-with-mcp
  and https://docs.github.com/en/copilot/reference/custom-agents-configuration, each read 2026-11-14. `documented`. SE acts on it in
  [docs/copilot.md "Cloud agent, optional and untested"](../copilot.md#cloud-agent-optional-and-untested).
- **Cloud setup steps.** What a server needs beyond the runner's tools, such as `uv`, goes in the
  repository's copilot-setup-steps workflow. Source:
  https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/extend-cloud-agent-with-mcp,
  read 2026-11-14. `documented`. SE acts on it in
  [docs/copilot.md "Cloud agent, optional and untested"](../copilot.md#cloud-agent-optional-and-untested).

## Servers

- **Server precedence.** The CLI's MCP servers are last-wins by name: the user's config ranks below
  plugins, and `--additional-mcp-config` above both; the `user MCP config` row of
  `registrations.copilot-cli` in [scripts/host-limits.toml](../../scripts/host-limits.toml) holds
  the first half. Source: https://docs.github.com/en/copilot/reference/cli-plugin-reference, read 2026-11-14. `documented`. SE acts on it in
  [docs/copilot.md "The door by hand"](../copilot.md#the-door-by-hand).

## Environment variables

- **`PLUGIN_ROOT` in a plugin's server.** The CLI sets `PLUGIN_ROOT` in a plugin's stdio server's
  environment and expands `${PLUGIN_ROOT}` in its arguments, environment values and working
  directory. Source: https://docs.github.com/en/copilot/reference/cli-plugin-reference, read 2026-11-14. `documented`. SE acts on it in [scripts/se_plugin.py](../../scripts/se_plugin.py) and
  [scripts/se_mcp.sh](../../scripts/se_mcp.sh).
- **`PLUGIN_ROOT` in a plugin's hooks.** SE's plugin hook lines run only where `$PLUGIN_ROOT` is
  set in the hook's environment, which no hook page read says the CLI does. Assumed in
  [scripts/se_plugin.py](../../scripts/se_plugin.py). `assumed`.
- **`COPILOT_SESSION_CWD`.** SE's plugin server entry expands it into `SE_SESSION_CWD`, and the
  launcher reads either to find the session's repository; no page read names it, and no run has
  shown its value. Assumed in [scripts/se_mcp.sh](../../scripts/se_mcp.sh) and
  [scripts/se_plugin.py](../../scripts/se_plugin.py). `assumed`.
- **`COPILOT_HOME`.** It overrides the CLI's configuration and state folder, `~/.copilot` where
  unset, its installed plugins among them. Source:
  https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in [scripts/host_registrations.py](../../scripts/host_registrations.py).
- **`COPILOT_GITHUB_TOKEN`.** The CLI's authentication token, ahead of `GH_TOKEN` and
  `GITHUB_TOKEN`. Source: https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14. `documented`. SE acts on it in [docs/copilot.md "Smoke test"](../copilot.md#smoke-test).
- **`COPILOT_AUTO_UPDATE`.** Set to `false`, it stops the CLI updating itself and its first-party
  plugins, and running a newer cached CLI. Source:
  https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in [docs/copilot.md "Smoke test"](../copilot.md#smoke-test).
- **`COPILOT_CLI`.** No page read names it as a mark of the CLI. Pages read, each read 2026-11-14:
  https://docs.github.com/en/copilot/reference/cli-command-reference and
  https://docs.github.com/en/copilot/reference/hooks-configuration. `silent`. SE does nothing about
  it.
- **`COPILOT_AGENT_SESSION_ID`.** No page read names it as a mark of a Copilot session. Pages
  read, each read 2026-11-14: https://docs.github.com/en/copilot/reference/cli-command-reference
  and https://docs.github.com/en/copilot/reference/hooks-configuration. `silent`. SE does nothing
  about it.
- **`COPILOT_PROJECT_DIR`.** No page read names it; a hook finds the project from its payload's
  working directory. Pages read, each read 2026-11-14:
  https://docs.github.com/en/copilot/reference/cli-command-reference and
  https://docs.github.com/en/copilot/reference/hooks-configuration. `silent`. SE does nothing
  about it.
