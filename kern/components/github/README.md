# github

kern's GitHub component: the one I/O component that reaches GitHub. Every other component reads
GitHub through its verbs, so no other component holds a token or a client. It names no
application. Its design is SE's [docs/go-core.md](../../../docs/go-core.md), "GitHub in the
cloud".

## The backends

The config key `backend` chooses at start, and the output `backend` names the choice:

| backend | where | how a read is answered |
|---|---|---|
| `token` | a token is found: `GH_TOKEN`, else `GITHUB_TOKEN`, else `gh auth token` | GitHub's REST API, in process |
| `relay` | none is found, or in a cloud session | the session's own GitHub tool, its answer handed back by the PostToolUse hook |

`auto`, the default, takes the relay in a Claude Code cloud session (`CLAUDE_CODE_REMOTE=true`),
whose `GH_TOKEN` is the proxy's stand-in that code cannot use; elsewhere the token where one is
found, else the relay. `token` without one refuses the start.

- **The token backend** keeps each path's ETag and answer, so a read of an unchanged one is
  answered `304` and costs no quota. Every `refresh` (2 minutes) it reads each snapshot it holds
  again, with its ETag.
- **Its pacing.** A `429`, or a `403` with `Retry-After` or `X-RateLimit-Remaining: 0`, is a rate
  limit. The backend waits what `Retry-After` asks, else until the quota's reset, else a minute,
  and every read waits with it. It sends a read four times at most, and fails one whose wait is
  over `pace-max`. A `403` that is no rate limit fails at once.
- **The relay** answers a snapshot younger than `refresh` at once. Otherwise the read goes out as
  an entry of the family `outbox`: the tool's bare name and its input, and when it was asked. It
  waits up to `relay-wait` (`0s`) for the answer, else fails naming the tool call to run. The
  entry stands until a PostToolUse answers it.
- **Every GitHub tool answer lands.** The component hears each PostToolUse the core is handed. An
  MCP tool `<server>__issue_read` (method `get` or `get_comments`) or `<server>__pull_request_read`
  (methods `get` and `get_check_runs`), with an owner, a repository and a number, lands in its
  snapshot, asked or not, and drops its outbox entry. Other tools and methods pass unread; an error
  answer is logged.

## The verb `step`: a write tool through the relay

A read is one of four tools the component knows; the verb `step` runs any GitHub tool through the
relay, so a command's write steps (open a pull request, wait for a check, merge, comment, close)
reach GitHub through the session the same way. It asks `github.step`, `{"tool", "input", "note"?,
"match"?, "wait"?}`: the tool's bare name (such as `merge_pull_request`), its input, the note the
agent watches for, the input keys an answer must carry equal (empty, every key whose value is no
text over 200 bytes, so a long body the session re-wraps is read back from the answer; owner and
repo match regardless of case) and how long to wait, up to `step-wait` (`60m`). The step stands in
`outbox` until a PostToolUse of that tool with that input answers it, and the verb answers
`github.step-answer`, `{"tool", "input", "read", "data"}`: the input the session sent and the
tool's answer, as JSON where it is JSON, else its text. Only the relay runs steps; with a token a
command runs its GitHub steps itself.

## Telling the agent, on the hook

The component tells the agent, on each `PostToolUse`, `UserPromptSubmit` and `SessionStart`, the
tool calls `outbox` waits for, oldest first, each with its note, as the host's hook
`additionalContext`. A PostToolUse that answered a step waits up to `tell-wait` (`300ms`) for the
next step, so the agent is told it in the same hook. The agent runs each call with its GitHub
tools; the PostToolUse hook hands the answer back, and the waiting read or step is answered.

## Verbs and names

| verb | asks | answers |
|---|---|---|
| `issue` | `{"owner", "repo", "number"}` | the issue's snapshot |
| `pull` | the same | the pull request's snapshot |
| `check-runs` | the same | the snapshot of the check runs at the pull request's head |
| `comments` | the same | the snapshot of the issue's comments |
| `step` | `github.step` | `github.step-answer`, the tool's answer |

A snapshot is `{"repo", "number", "read", "via", "data"}`: `read` is the time it was read,
`via` the backend, `data` the answer as that backend read it (GitHub's REST JSON through the
token, the tool's JSON through the relay). Each stands at the key `<owner>.<repo>.<number>`, in
lower case, in its family:

```toml
[instances.github]
component = "github"
# config = { backend = "auto", refresh = "2m", relay-wait = "0s", pace-max = "60s", step-wait = "60m", tell-wait = "300ms" }

[wires]
"github.issues" = "github/issues/<key>"
"github.pulls" = "github/pulls/<key>"
"github.checks" = "github/checks/<key>"
"github.comments" = "github/comments/<key>"
"github.outbox" = "github/outbox/<key>"
"<component>.<request port>" = "github.issue"
"<component>.<request port>" = "github.step"
```

A read's outbox entry stands at `<verb>.<owner>.<repo>.<number>`, a step's at `step.<tool>.<hash
of its input>`. The component runs one instance per
core. It is switched off with `enabled = false`: it then looks for no token and hears nothing,
and its names read their built-in values.

## Tests

`github_test.go` holds both backends to fakes: the token backend to a fake REST server (ETags,
the refresh, a check-runs read at the head, each kind of rate limit), the relay to PostToolUse
payloads shaped as a cloud session's hook hands them, and both through the real core, from the
hook's post to a client's read of the snapshot name. `step_test.go` holds the verb `step` and the
telling: a step waits for the tool use that matches it, answers the tool's answer, and the hook of
an answer tells the next step as the host's hook JSON.
