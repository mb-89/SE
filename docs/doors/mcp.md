# The MCP door: outside facts

Reader: whoever changes SE's MCP door, kern's `mcp` package or its launcher, or checks a host fact
it rests on. This note owns the outside facts the door relies on that no script reads: each with
its source, the day it was read and how sure SE is of it. Last read: 2026-11-14.

[scripts/host-limits.toml](../../scripts/host-limits.toml) is the one home for host facts a script
reads: each limit, surface and registration with its source and date. An item here is prose
evidence that no script reads; once a row holds its fact, the item links the row and drops its own
wording. The door's own files are declared in [scripts/doors/mcp.toml](../../scripts/doors/mcp.toml);
this note lists none. What a token-less Copilot CLI showed is
[docs/copilot.md](../copilot.md#what-a-token-less-copilot-cli-showed), linked and not restated.

Each item carries one mark, the one a host-limits row would take. `documented`: a host's page or
the MCP spec says it. `seen`: a run showed it, what host-limits calls `measured`. `silent`: no page
says it, and the item names the pages read. `assumed`: SE's code relies on it and no page or run
shows it, and the item links the file that assumes it.

## The protocol

- **Spec revision.** The MCP spec of 2026-07-28 is the first "modern" revision: every request
  carries its protocol version, identity and capabilities as metadata, and every server must
  implement `server/discover`. Source: https://modelcontextprotocol.io/specification/2026-07-28/basic/lifecycle,
  read 2026-11-14. `documented`. SE acts on it in
  kern's README "The MCP door".
- **Legacy handshake.** Revisions up to 2025-11-25 open a session with `initialize`; a dual-era
  server may serve both, and an `initialize` request selects legacy semantics for that stdio
  process. Source: https://modelcontextprotocol.io/specification/2026-07-28/basic/lifecycle,
  read 2026-11-14. `documented`. SE acts on it in
  kern's README "The MCP door".
- **Stdio fallback.** A client that knows both eras should probe with `server/discover` first; any
  error that is not a recognized modern error, or no answer within a reasonable time, marks the
  server legacy, and the client falls back to `initialize`, never keyed to one error code. Source:
  https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio, read 2026-11-14.
  `documented`. SE acts on it in kern's README "The MCP door".
- **Which handshake a host sends first.** No host's page says whether it sends `server/discover`
  or `initialize` first, so either may open the door. Pages read, each read 2026-11-14:
  https://docs.github.com/en/copilot/reference/cli-command-reference,
  https://docs.github.com/en/copilot/reference/cli-plugin-reference,
  https://code.visualstudio.com/docs/agents/reference/mcp-configuration and
  https://code.claude.com/docs/en/mcp. `silent`. SE acts on it in
  kern's README "The MCP door": the door speaks both.
- **Standard output is protocol only.** A stdio server must not write anything to its standard
  output that is not a valid MCP message; it may log to standard error, which the client should not
  read as an error. Source: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio,
  read 2026-11-14. `documented`. SE acts on it in
  [README.md "The MCP door"](../../README.md#the-mcp-door): the launcher sends everything else to
  its log.

## When a host loads a project's MCP config

- **Copilot CLI: folder trust.** The CLI loads workspace servers, its project MCP files from the
  working directory up to the git root, only in a trusted folder; the files are the `MCP door`
  row of `registrations.copilot-cli` in [scripts/host-limits.toml](../../scripts/host-limits.toml).
  Source: https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in [docs/copilot.md "Remedies"](../copilot.md#remedies).
- **Copilot CLI: prompt mode.** In prompt mode (`-p`) workspace MCP sources stay off unless
  `GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP` is set, and `--trust-folder` trusts the working
  directory's hooks and workspace servers for one new non-interactive session without saving it.
  Source: https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in [docs/copilot.md "Smoke test"](../copilot.md#smoke-test), whose
  run passes `--trust-folder`.
- **Copilot CLI: tool list snapshot.** The CLI keeps a snapshot of each local server's tool list,
  so its tools are there at start while live discovery runs and then replaces it. Source:
  https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE does nothing about it.
- **VS Code: native destinations.** VS Code's Copilot harness reads the user's Copilot MCP config
  and a workspace-root project MCP file directly; `.vscode/mcp.json`, a profile's `mcp.json` and
  `code --add-mcp` write the editor-managed config of the deprecated Local harness, which reaches a
  Copilot session only where VS Code forwards an eligible entry. Its places are the `workspace MCP
  config` and `user MCP config` rows of `registrations.copilot-vscode` in
  [scripts/host-limits.toml](../../scripts/host-limits.toml). Source:
  https://code.visualstudio.com/docs/agents/reference/mcp-configuration, read 2026-11-14.
  `documented`. SE acts on it in [README.md "The MCP door"](../../README.md#the-mcp-door).
- **VS Code: Copilot's project file.** No VS Code page says that its Copilot harness reads
  `.github/mcp.json`. Pages read, each read 2026-11-14:
  https://code.visualstudio.com/docs/agents/reference/mcp-configuration and
  https://code.visualstudio.com/docs/copilot/customization/mcp-servers. `silent`. SE acts on it in
  [docs/copilot.md "Monday checklist"](../copilot.md#monday-checklist), whose second step checks
  it.
- **VS Code: the editor's autostart.** The experimental editor setting `chat.mcp.autostart` starts
  servers when a chat message is submitted, and does not stop a Copilot harness session from
  starting the servers it manages itself. Source:
  https://code.visualstudio.com/docs/agents/reference/mcp-configuration, read 2026-11-14.
  `documented`. SE does nothing about it.
- **When a Copilot harness starts a server.** No page says whether the CLI or VS Code's Copilot
  harness starts a configured stdio server as the session starts or at its first tool call. Pages
  read, each read 2026-11-14: https://docs.github.com/en/copilot/reference/cli-command-reference and
  https://code.visualstudio.com/docs/agents/reference/mcp-configuration. `silent`. SE acts on it
  in [README.md "The MCP door"](../../README.md#the-mcp-door), which starts the core whenever the
  door is spawned.
- **Claude Code: project servers need approval.** A server of a project's committed MCP file stays
  pending until the person approves it in a trusted workspace; a cloned repository cannot approve
  its own servers. Source: https://code.claude.com/docs/en/mcp, read 2026-11-14. `documented`. SE
  acts on it in [README.md "The MCP door"](../../README.md#the-mcp-door): no root file is
  committed while its build setting is off.

## Time

- **A slow server is dropped.** Each host gives a server a start budget and drops one that does
  not answer within it; the budgets are the `mcp-start-timeout` rows of `limits` in
  [scripts/host-limits.toml](../../scripts/host-limits.toml), with their sources. Source:
  https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in kern's README "The MCP door":
  the handshake and the tool list never wait on the core.
- **A tool call's time limit.** The Copilot CLI's per-server `timeout` also bounds tool discovery
  and every tool call; [scripts/host-limits.toml](../../scripts/host-limits.toml) has no row for a
  tool call's limit, on any host. Source:
  https://docs.github.com/en/copilot/reference/cli-command-reference, read 2026-11-14.
  `documented`. SE acts on it in kern's README "The MCP door":
  a call made while the core starts waits briefly, then answers `starting`.

## The launcher's stand-in door

- **A host falls back from the stand-in.** While the `se` binary is missing, the launcher answers
  as a door of its own that knows `initialize` and not `server/discover`, which it refuses as an
  unknown method; so it assumes that a host sending `server/discover` first falls back to
  `initialize`, as the spec's stdio binding asks of a client that knows both eras. Assumed in
  [scripts/se_mcp.sh](../../scripts/se_mcp.sh) and its twin
  [scripts/se_mcp.ps1](../../scripts/se_mcp.ps1). `assumed`.
