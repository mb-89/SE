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
  answered `304` and costs no quota. A list read is paged, 100 items a page, and each page keeps
  its own ETag, so an unchanged page costs no quota either. Every `refresh` (2 minutes) it reads
  each snapshot and list it holds again, each page with its ETag.
- **Its pacing.** A `429`, or a `403` with `Retry-After` or `X-RateLimit-Remaining: 0`, is a rate
  limit. The backend waits what `Retry-After` asks, else until the quota's reset, else a minute,
  and every read waits with it, a later page of a list among them. It sends a page four times at
  most, and fails one whose wait is over `pace-max`. A `403` that is no rate limit fails at once.
- **The relay** answers a snapshot or list younger than `refresh` at once. Otherwise the read goes
  out as an entry of the family `outbox`: the tool's bare name and its input, and when it was
  asked. It waits up to `relay-wait` (`0s`) for the answer, else fails naming the tool call to
  run. A paged read's entry names the next page the session is to run, with the cursor or page the
  last answer gave; the entry stands until a PostToolUse answers it.
- **Every GitHub tool answer lands.** The component hears each PostToolUse the core is handed.
  - A single read: `<server>__issue_read` (method `get`) or `<server>__pull_request_read` (methods
    `get` and `get_check_runs`), with an owner, a repository and a number, lands in its snapshot.
  - A comment read: either tool's method `get_comments`, with an owner, a repository and a number,
    lands in `comments`, page by page.
  - A list read: `<server>__list_issues` (with a `state` and `labels`) or
    `<server>__list_pull_requests` (with a `state`), with an owner and a repository and nothing
    that narrows or reshapes the list further (`fields`, `since`, a sort, `head`, `base`), lands
    in `issue-lists` or `pull-lists`, page by page. One that names such a narrowing is another
    list than a name holds, so it passes unread.
  - Each lands asked or not, and drops its outbox entry; a paged answer lands its name once its
    last page is heard, and a first page nobody asked with more behind it lands nothing, since it
    is no whole list. Other tools and methods pass unread; an error answer is logged.

## The verb `step`: a write tool through the relay

The reads above are the tools the component knows; the verb `step` runs any GitHub tool through
the relay, so a command's write steps (open a pull request, merge, comment, close) reach GitHub
through the session the same way. It asks `github.step`, `{"tool", "input", "note"?, "match"?,
"wait"?}`: the tool's bare name (such as `merge_pull_request`), its input, the note the agent
watches for, the input keys an answer must carry equal, and how long to wait, up to `step-wait`
(`60m`).

- Without `match`, every input key whose value is no text over 200 bytes must match, so a long
  body the session re-wraps is read back from the answer; owner and repo match regardless of case.
- The step stands in `outbox` until a PostToolUse of that tool with that input answers it. The
  verb answers `github.step-answer`, `{"tool", "input", "read", "data"}`: the input the session
  sent and the tool's answer, as JSON where it is JSON, else its text.
- A step whose call is given up leaves `outbox` at once, so the agent is never told a step that
  no one waits for ([docs/go-core.md "A call given up"](../../../docs/go-core.md#a-call-given-up)).
- Only the relay runs steps; with a token a command runs its GitHub steps itself.

## Telling the agent, on the hook

On each `PostToolUse`, `UserPromptSubmit` and `SessionStart` the component tells the agent the
tool calls `outbox` waits for, reads and steps, oldest first, each with its note, as the host's
hook `additionalContext`. A PostToolUse that answered a step first waits up to `tell-wait`
(`300ms`) for the next step, so the agent is told it in the same hook.

## Verbs and names

| verb | asks | answers |
|---|---|---|
| `issue` | `{"owner", "repo", "number"}` | the issue's snapshot |
| `pull` | the same | the pull request's snapshot |
| `check-runs` | the same | the snapshot of the check runs at the pull request's head |
| `comment-list` | the same | the snapshot of every comment of the issue or pull request, every page |
| `issue-list` | `{"owner", "repo", "state", "labels"}` | the list of the repository's issues in that state carrying every label |
| `pull-list` | `{"owner", "repo", "state"}` | the list of the repository's pull requests in that state |
| `step` | `github.step` | `github.step-answer`, the tool's answer |

`state` is `open` (the default), `closed` or `all`; `labels` lists issues alone, since GitHub
lists pull requests by none. A list read keeps the issues, not the pull requests GitHub's issues
list also holds.

A **snapshot** is `{"repo", "number", "read", "via", "data"}` and a **list** is
`{"repo", "state", "labels", "read", "via", "data"}`: `read` is the time it was read, `via` the
backend, `data` the answer as that backend read it (GitHub's REST JSON through the token, the
tool's JSON through the relay — a list's `data` is every page's items in GitHub's order). A
snapshot stands at the key `<owner>.<repo>.<number>` and a list at `<owner>.<repo>.<state>`, then
each label in order, all in lower case, in its family:

```toml
[instances.github]
component = "github"
# config = { backend = "auto", refresh = "2m", relay-wait = "0s", pace-max = "60s", step-wait = "60m", tell-wait = "300ms" }

[wires]
"github.issues" = "github/issues/<key>"
"github.pulls" = "github/pulls/<key>"
"github.checks" = "github/checks/<key>"
"github.comments" = "github/comments/<key>"
"github.issue-lists" = "github/issue-lists/<key>"
"github.pull-lists" = "github/pull-lists/<key>"
"github.outbox" = "github/outbox/<key>"
"<component>.<request port>" = "github.issue"
"<component>.<request port>" = "github.step"
```

An outbox entry stands at `<verb>.<key>`, a step's at `step.<tool>.<hash of its input>`. The component runs one instance per core. It is switched
off with `enabled = false`: it then looks for no token and hears nothing, and its names read their
built-in values.

## Tests

`github_test.go` and `lists_test.go` hold both backends to fakes: the token backend to a fake REST
server (per-page ETags, the refresh, a check-runs read at the head, each kind of rate limit on a
single read and on a later page, paged issue, pull-request and comment reads), the relay to
PostToolUse payloads shaped as a cloud session's hook hands them (list_issues' cursor pages,
list_pull_requests' and get_comments' numbered pages, a list heard whole without being asked), and
both through the real core, from the
hook's post to a client's read of the snapshot name. `step_test.go` holds the verb `step` and the
telling: a step waits for the tool use that matches it and answers that tool's answer, and the hook
of an answer tells the next step as the host's hook JSON.
