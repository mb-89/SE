# Metrics, local settings and workflows

## Metrics

Every run of a `work_tickets.py` or `se_start.py` subcommand appends one JSON line to
`~/.se/metrics.jsonl` (`SE_METRICS` names another file), so the command that spends time or
GitHub's limits can be named instead of guessed. `scripts/metrics.py` owns the line and the report.

- `command` (`work_tickets.py backlog file`), `start` (UTC), `wall_seconds` and `exit_code`.
- GitHub through the door: `gh_calls` (every `gh` call and every push attempt), `gh_refusals` (a
  call GitHub refused for its rate limit, a push it refused transiently) and `gh_wait_seconds`
  (the waits on GitHub: a push retry, a poll of `check` or of a workflow run).
- CI's suite time on the integration branch, `ci_suite_seconds`, the median of its last runs,
  where it was read ([Test budget](tests.md#test-budget)); `integrate` always reads it, so its line holds
  both times.
- What a command notes itself: the suite's `suite_seconds` and its `suite_limit_seconds` (`[tests]`
  `limit_seconds`) from `suite` and `integrate`, the `issue` `integrate` landed, and
  `budget_seconds` from an interactive command, its budget from
  [Feedback budgets](#feedback-budgets).

A line that cannot be written is dropped; the command never fails for it. `integrate` prints its own
line last, `Metrics: {...}`, for the integrator's report.

The landing pull request's description ends in that line too, as it stands when the landing plan is
written, so a cloud integrator's costs outlive its container: [`retro.py collect`](work-commands.md#work-commands)
reads it back. A hand-off's `integrate --read-back` refuses a description that lacks it
([Landing on main](settings.md#landing-on-main)).

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
([retro.md](../.github/ISSUE_TEMPLATE/retro.md)).

## Feedback budgets

A person never waits on a silent command. The budgets are declared once, in
[scripts/feedback.py](../scripts/feedback.py), which owns them and the lines below; they hold every
`work_tickets.py` and `se_start.py` subcommand:

- First line within 1 s: a run that has shown nothing after half a second prints
  `<command>: working, nothing to show yet`.
- Interactive commands finish within 5 s: `work_tickets.py status`, `queue`, `intake` and
  `metrics`; `se_start.py status`, the greeting, within 10 s. Each run notes its budget in its
  [metrics](#metrics) line, so `work_tickets.py metrics` flags an overrun.
- Long commands announce each phase as it starts, `Phase: <what>`: `integrate` (the pull request
  read, the guard, sync, the merge, the suite, the checks, the push, the landing plan,
  the read-back and the close-out), `release` (sync, the release commit, the checks, the push and
  the landing plan), `suite` (its setup and the suite; with `--compare`, each run)
  and `refresh`.
- A call that reads GitHub or a remote prints what it reads before it is made:
  `Reading GitHub: gh issue list --state open --label escalated` (without the options that only
  shape the output), `Reading the remote: git fetch origin`.

Progress lines go to stderr, so what a command prints on stdout, JSON or a description, stays as it
is. `queue` reads its listings, and each candidate's blockers and branch, at once while the checkout
syncs, so it waits on GitHub about three times per run rather than once per call.

## Machine-local `~/.se/local.toml`

`public_identity = "Name <email>"` pins the author and committer identity allowed in every
commit pushed to a configured public mirror. If it is omitted, `integrate` uses the project's
`identity`, else the selected checkout's configured Git identity. When it is set, `sync` writes it into the checkout's git
config in place of the project's `identity` ([Project settings](settings.md#project-settings)).

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
| `SE_TEMPLATES_GATE=off` | in the environment: SE's template gate judges no GitHub write on this machine, whatever se.toml `[templates] gate` says; unset, it follows se.toml ([Templates](templating.md#templates)). |
| `[paths] se = "<the installed SE's folder>"` | this machine's SE stays at its version, because the start's refresh leaves a local path alone ([Start and refresh](start.md#start-and-refresh)). |

`[hooks] core = "off"`:

- Set in the file, it takes effect at the next session start.
- It does not reach the MCP server, which can start the core by itself: a host switches its own
  MCP server off. `SE_KERN=off` is another switch, which keeps commands direct.

Work queue tracker, worktree and mirror settings are documented in the
[work model](../src/skills/work-model/SKILL.md#what-the-project-provides), the `[outside]` table in its
[Outside issues](../src/skills/work-model/SKILL.md#outside-issues).

## Commands

One invocation on every platform; a project copies it as it is into its `AGENTS.md`, with `<se>`
the path where se lives in the project (`.` in se itself):

```sh
uv run python <se>/scripts/se_modules.py sync [<name>...]
uv run python <se>/scripts/se_modules.py status [<name>...]
uv run python <se>/scripts/se_modules.py breaking [--all]
uv run python <se>/scripts/se_modules.py update <name> [--to <ref>]
uv run python <se>/scripts/se_modules.py update --all
uv run python <se>/scripts/se_modules.py path <name>
```

| Command | What it does |
|---|---|
| `sync` | resolves the tree ([The tree](modules.md#the-tree)): a component with an existing local path is used from there; any other is found by name ([Finding a component](modules.md#finding-a-component)), cloned or fetched into `.se/modules/<name>` and checked out (detached) at its pin. A `version` range without a lock entry that admits it is resolved and locked first; a locked one stays where it is until `update`. A clone with local changes is never overwritten. Hosts ignore `.se/`. |
| `status` | one line per component of the root's list with its source (`local` or `pinned`), the directory it is used from, the pin and the drift (below). It never fetches. |
| `breaking` | one line per pin of the tree, nested ones included, whose component's newest release is a breaking one beyond it, or one line where none is; `--all` lists every pin. It changes nothing ([docs/components.md "Breaking releases beyond a pin"](components.md#breaking-releases-beyond-a-pin)). |
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

## Workflows

A project calls SE's reusable workflows and actions as local copies, `uses: ./.github/...`, which
SE writes into it at its SE pin. A call of SE's own files would name SE's home, which differs on
each remote ([Neutral workflows](../src/skills/work-model/SKILL.md#neutral-workflows)).

```sh
uv run python <se>/scripts/se_workflows.py write [<path>...]
uv run python <se>/scripts/se_workflows.py check
```

- What SE ships: `.github/workflows/` `branch-cleanup.yml`, `kern-battery.yml`, `kern-release.yml`
  and `release.yml`, and the actions `integrator-pass`, `kern-at-pin`, `release-kind`,
  `suite-shard` and `suite-time` (`SHIPPED` in `scripts/se_workflows.py`).
  - Every project holds `release-kind`, whichever others it calls (`EVERY_PROJECT`): its required
    check `check` calls it on each pull request (`uses: ./.github/actions/release-kind`), the gate
    that refuses a pull request into the integration branch whose description states no release
    kind ([Release kind](../src/skills/work-model/SKILL.md#release-kind)). `write` adds it where the
    pin ships it, and `check` names it missing.
  - Beside them, the files a project holds as SE has them: `RUNME.sh` and `RUNME.ps1`, the
    installer beside the project's own `RUNME.conf`, and `ref-maintenance.yml`, which its owner
    triggers by hand; each keeps its triggers (`WHOLE`).
- `write` writes the files it names, or regenerates those the project holds. Each is a generated
  file whose marker (the guidance note
  [generated-files-are-marked](../guidance/generated-files-are-marked.md)) names `se_workflows.py
  write` and, as its source, SE's file, the pin and SE's place: its first line, or the line after
  `RUNME.sh`'s `#!`.
- `kern-at-pin` checks kern out at the commit a folder's `se.lock` locks into its
  `.se/modules/kern`, refusing a lock whose version is not the `require kern` of the `go.mod` that
  the folder's `se.toml` `[components.kern]` `go` names, naming both lines. A folder whose `se.lock`
  locks no kern and that carries `kern/go.mod` is left as it is; one with neither is refused,
  naming `se_modules.py sync kern`.
  - `kern-battery.yml` calls it before its vet and `kern-release.yml` before its build, so kern is
    placed one way. `write` adds its copy wherever it writes either workflow, and `check` names it
    where a project holds either without it.
- SE's own workflows beside them are not shipped: `check.yml`, `docs.yml` and the templates backstop,
  `templates.yml`, run on SE's own events ([Templates](templating.md#templates)).
- The pin is `[components.se]`'s ([Modules](modules.md#modules)), else the one the copies carry, as in an
  application `se new app` made, or `--ref`.
- SE's place, how CI reaches it: where `sync` found SE, its clone's origin. One under the
  project's own owner on its host is `${{ github.repository_owner }}/<name>`, so the copies name no
  owner; any other names its own `<owner>/<name>`. SE is public, so the run's token reads it.
- Where SE's file reaches SE's own checkout, the copy checks out SE at the pin instead (in
  `.se/ci/se`, which the project ignores with `.se/`); a workflow keeps only its `workflow_call`,
  unless it is held whole.
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
- It gates a push with the second call, by branch ([AGENTS.md "Public safety"](../AGENTS.md#public-safety)).
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
