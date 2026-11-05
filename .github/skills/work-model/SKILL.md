---
name: work-model
description: 'The shared rules of how we work, for every role (dispatcher, worker, integrator): one work issue in, a pull request plus a field-report issue out; the box; escalation; freshness, dependencies and scheduling; worktrees; local tickets and notes; what a project provides. Load it whenever you act as dispatcher, worker or integrator, write or read work, field-report or retro issues, or use scripts/work_tickets.py.'
---

# Work model

This skill owns the rules that are the same for every role. Each role's own rules live in its
agent definition: [dispatcher](../../agents/dispatcher.agent.md),
[worker](../../agents/worker.agent.md), [integrator](../../agents/integrator.agent.md). The
dispatcher's procedure is the [catch-up](../catch-up/SKILL.md) skill. Issue formats are the
templates in [`.github/ISSUE_TEMPLATE/`](../../ISSUE_TEMPLATE/). Everything specific to one project
(its commands, design notes, quality rules, hot files) is owned by the project's `AGENTS.md`; see
[What the project provides](#what-the-project-provides).

## Roles and flow

One issue in, one issue out; the same for local sessions and cloud agents.

- **Work issue (in)**: one GitHub issue per package from `work.md`, carrying only the task. Title
  = branch name (`<type>/<topic>-<yyyymmdd>`), label `work`. Everything that is the same for every
  package lives in the agent definitions and this skill, never in issues. A session prompt names
  only the agent, the issue and the worktree.
- **The box**: a worker changes only its own worktree. Any other checkout it reads (for example a
  related repository its tests use) is read-only. Everything comes in through its work issue
  (re-read with its comments before each ticket, so it can change in flight) and goes out through
  its pull request and its field-report issue. What it needs outside the box goes into the field
  report.
- **Out**: a pushed branch, a pull request to the integration branch, a field-report issue from `field-report.md`
  (title `field-report: <branch>`, label `field-report`) and one notification to the integrator.
  The field report holds what was not done, decisions with confidence, spec gaps, a short retro
  and tickets for other repositories. Each "Tickets for other repositories" entry is one reusable
  capability and lists every source file it replaces.
- **Integrator**: a subtype of worker and the only writer of the integration branch.
- **Dispatcher**: the only session the human talks to. The dispatcher never writes any repository.
  It may file work issues for and dispatch into any repository by starting or messaging that
  repository's integrator. Each repository has exactly one integrator, the only writer of its
  integration branch. The integrator starts that repository's workers. Workers stay in their box; a worker
  records cross-repository needs in its field report.
- **Only the dispatcher talks to the human.** Workers and integrators never ask the human anything
  and never wait for an answer, an approval or a decision: they decide what they may decide,
  escalate the rest, and continue with other work or end their turn.
- **Escalation**: label `escalated`, the question in a comment, to the integrator one level up or
  to the dispatcher at the top level, which presents it to the human. The answer arrives as an
  issue comment or a new request, never as a reply anyone waits for.
- **Messages travel only up and down the tree**: a session messages only the session that started
  it and the sessions it started. A sideways message (one integrator to another) stops at a
  permission prompt in Claude's cloud, so news for another repository goes up to the dispatcher,
  which passes it down to that repository's integrator.
- **Comments carry the host's footer**: where the host requires a footer on every GitHub comment
  (Claude's cloud does), each fixed comment text a role or command gives (`Started: …`,
  `Integrated in …`, an escalation) is followed by that footer, unchanged. Nothing else repeats
  this rule.
- Issues are read and written with `gh`, bodies through `--body-file`; where the host offers no
  `gh`, see [Without gh](#without-gh). Branches and the integration branch are pushed; a release
  needs the human's approval, obtained by the dispatcher.
- Retros use `retro.md`; each improvement names the agent definition, template, skill or script
  it changes, and becomes an ordinary work issue.

## Integration branch

The integration branch is the one branch the integrator writes and every worker branches from,
merges and opens its pull request against. It is `main` unless the project names another in
`se.toml`, for example while an older process still lives on `main`:

```toml
[project]
integration_branch = "se"
```

`work_tickets.py` reads it from there for `sync`, `start`, `deliver`, `guard` and `integrate`;
`integrate` refuses a main checkout that is not on it. Below, `main` means the integration branch.

## Rules for all roles

Framework repositories (the process plugin and document format/converter) carry every capability that is generically useful. Application repositories carry only their content and application-specific code. When an application reveals a generic capability, create a framework work issue and delete the application's copy after the framework provides it. A framework never names, special-cases or depends on an application; for public repositories, the public check's deny list enforces this boundary.

- Packages are worker-sized: one separately reviewable change. Larger work is split into issues
  linked by "Blocked by", each owning its part of shared files.
- Packages that touch the same hot file get one owner or run one after the other; the next one
  merges `main` before touching that file.
- Work issues quote the user's requirement word for word; the field report quotes it back.
- Every error message names where it comes from (the command, file or input) and, where
  possible, the remedy.
- Work follows the user's priority order; no new investigation starts while a top-priority bug is
  open.
- Workers run focused tests and what their issue's acceptance names, the complete suite only
  where it names the suite; the integrator runs the complete suite, one integration at a time,
  while the dispatcher talks with the human.
- No hard time boxes: workers deliver whole items. A worker never ends its turn without
  delivering; when it stops, its field report names the blocker.
- **Disagree and commit**: ambiguity is a decision. Investigate the repository, contracts and
  tests, make the best defensible, reversible decision within scope, record it with its
  confidence for the field report, and continue. This never grants authority to bypass policy,
  disclose private data, act destructively or publish without approval.
- **Preserve capabilities**: removing or narrowing an existing user-visible capability, or
  deleting or weakening its protecting test, is a product decision for the human. Deleting or
  condensing authored content is recorded in the field report with what was dropped and where it
  moved, unless the work issue names the change. "Disagree and commit" never covers it: the worker
  escalates instead. The dispatcher never writes a work issue that leaves "keep or remove" to the
  worker.
- **Mechanical first**: a procedure that repeats becomes a command in `work_tickets.py`
  (`intake`, `refresh`, `sync`, `guard`, `deliver`, `escalate`, `block`, `ready`, `capacity`, `queue`,
  `start`, `close`, `config`); prose steps remain only for judgment. Escalations and product decisions stay
  manual.

## Freshness, dependencies and scheduling

Pull requests built on an old `main` cause most integration trouble.

- **No "require branches up to date" protection**: it causes contention. The integrator is the
  merge queue: it merges each pull request into the newest `main`, resolves mechanical conflicts
  and runs the complete suite on the merged result. A semantic conflict, or a branch whose work no
  longer fits, is escalated back.
- Branches take `main` by merging it. A pushed branch is never rebased.
- A worktree and its branch are created when work starts, from the newest `main`. The worker
  syncs first, before each ticket and before the pull request; the field report names the `main`
  commit it was tested against.
- Dependencies are native GitHub "blocked by" links, set by the dispatcher. Blocked state is
  computed (`issue_dependencies_summary.blocked_by`), never a label. `ready` is only the
  dispatcher's approval; startable = `ready` and zero open blockers.
- No label is edited by hand: `start` changes `ready` to `in-progress`; the integrator removes
  `in-progress` when it closes the issue.
- After each integration the integrator starts every startable work issue that has no branch yet
  and whose file ownership does not clash with running workers, and starts its session itself.
- Nobody watches for field reports. Triggers: the worker's delivery notification (its only message
  to another agent, never a question); `work_tickets.py queue` at the start of every integrator and
  dispatcher turn, so a missed notification is handled as soon as either session is talked to;
  in the cloud only, scheduled triggers and Actions workflows on the `field-report` label.
- Capacity limits apply only to local workers (CPU cores and memory minus running workers). Cloud
  workers have none. File clashes and the serial merge queue apply everywhere.
- An integrated worker session is deleted once its branch is on `main` and its worktree is
  removed; a session is kept only while it holds an unresolved discussion with a handover issue.

## Worktrees

- One worktree per local worker, created when its work starts, from the newest `main`:
  `work_tickets.py start <issue> --worktree <main checkout>` refuses an issue that is not
  startable (including open blockers, an existing branch, a file-ownership clash or exhausted
  local capacity), fetches, runs
  `git worktree add -b <branch> <worktree-root>/<branch-with-slashes-replaced> origin/main` and
  changes the issue's `ready` label to `in-progress`. It prints the worker launch line with the
  exact created path. In a cloud runner, pass `--cloud-agent <login>` (or set
  `SE_CLOUD_AGENT`) to assign the worker and change the labels without creating a local worktree.
- Copilot CLI offers a platform-enforced alternative, not the local-worker launch path:
  `copilot --agent worker --no-ask-user --allow-all-tools --prompt "<worker prompt>"`.
  A live `worker`-profile run declared its `execute`, `read`, `edit`, `search`, and
  `send_message` allowlist and exposed no `ask_user`; however, the unprofiled CLI prompt-mode
  control also exposed no `ask_user`, so this does not prove that absence is profile-specific
  (and `set_workspace` is not a CLI tool). This alternative creates no UI session, so there is no
  user visibility, steering or review return by message, or delivery notification; additionally,
  `--allow-all-tools` approves every tool in the profile without prompts. Keep agent-host
  `create_session` workers as the default until a separate decision changes that path.
- A project whose packages need more than one plain worktree (paired checkouts, a test environment
  file, linked dependency folders) provides its own creation and removal scripts and names them in
  its `AGENTS.md`; it creates the worktree from the newest `main` with its script, then
  `start --no-create` verifies the linked worktree for the issue's branch, merges `main` into it,
  then changes `ready` to `in-progress` and prints the launch line; without a worktree it refuses.
  Cloud start (`--cloud-agent`) is unchanged.
- Removal happens only after integration, with `work_tickets.py close --remove
  --integration-target main --worktree <worktree>` or the project's removal script, never
  `git worktree remove --force` (it follows links into other checkouts). Removal refuses while
  tickets remain in `todo/` or `held/` or notes are unresolved.

## Local tickets and notes

A worker splits its work issue into local tickets in its worktree:

```text
.se/work/{todo,held,done,notes}/
```

- `.se/` is ignored, worktree-local state and never merges. `work_tickets.py` moves the same
  ticket file between `todo/`, `held/` (in progress) and `done/`; there is no second task list.
- A work issue labelled `discovery` is a read-only research package: its acceptance is evidence
  (findings, proposed tickets or probe results), not test-command wording. Its intake creates the
  ignored `.se/work/probe/evidence.md` index. `intake --discovery` also creates that index for an
  existing standard issue. A project that needs another ignored root declares it in its worker
  command with `--probe-root <relative-path>`; `work_tickets.py probe --command <command> --output
  <path>` appends the command and its output to the index. `field-report --draft` links that index
  in Delivered.
- Test-driven: regression first, then the change, then focused checks and the affected real
  command. Check an acceptance item only with evidence; move a ticket to `done/` only when every
  item is satisfied. A ticket that cannot be finished stays in `held/` with the attempts and
  failure evidence, and the field report states it as not delivered with exact next steps.
- A partial-delivery blocker is only work outside the worker's box: another package's file, a
  user decision, or missing access. Tests of the package's own code are never blockers, including
  failure paths exercised with temporary repositories or fakes. Workers may create, use and close
  throw-away tracker issues for live acceptance runs.
- Notes are private scratch: never committed, never copied into tracked files or reports. A note
  is resolved by a local `Disposition:` line stating the decision; future work becomes a tracked
  backlog item or work issue, not a copy of the note. Only unresolved notes block worktree removal.
- Rebuilds use the latest integrated state through the project's build command; every integrated
  package that changes output includes a fresh build and a check of the affected output.

## What the project provides

se is project-neutral. A project that uses it states in its `AGENTS.md`:

- where se lives in the project (`<se>` below; `.` in se itself) and that `.se/` is git-ignored;
- the setup command that installs the tools the roles need (`git`, `gh`, Python 3.11 or newer and
  whatever the project's tests need);
- the focused and the complete test commands, including gated test tiers if there are any;
- the commit identity its commits carry where the machine sets no `public_identity`, and its
  public check, if it has one, with the hooks that run it and `public_check = true` in its
  `se.toml` ([Project settings](../../../README.md#project-settings)), which gates every push to
  the integration branch on it;
- its integration project checks as JSON argument arrays passed to `integrate --check-command`, for
  example `--check-command '[["uv", "run", "pytest", "-q"], ["uv", "run", "python", "check.py"]]'`.
  The commands run without a shell. Add `--check-command-temporary-directory` when every command
  needs an isolated temporary working directory;
- the build command that regenerates the project's outputs and how to check them;
- the design notes that own product qualities, ownership and testing rules;
- its worktree scripts, when a plain worktree is not enough (see [Worktrees](#worktrees)), and the
  environment file a testing shell must load, if any;
- its hot files (files that parallel packages touch and that need one owner) and its backlog.

The repository and its host come from the checkout's git remote `origin` (or `--repo`). Machine-local
facts never go into a repository; they live in `~/.se/local.toml`. The
[Modules guide](../../../README.md#modules) owns the module-specific settings; command-line arguments
override the settings below, and `work_tickets.py config` shows what is in effect:

```toml
integrator_session = "<integrator session to notify at delivery>"
public_identity = "mb <mb>"
commit_trailer = "<trailer line>" # optional; none by default

[trackers] # repository name to tracker host/owner/repo; never commit this table
"<repository name>" = "<host>/<owner>/<repo>"

[worktree_roots] # optional overrides by checkout folder or remote name
"<checkout folder or remote name>" = "<directory>"

[repos."<host>/<owner>/<repo>"]   # optional overrides for one repository
integrator_session = "<session>"
```

**Commit identity and public check**: every role commits as `public_identity` where the machine
sets it (the [Modules guide](../../../README.md#machine-local-selocaltoml) owns what it pins), else
as the identity the project's `AGENTS.md` names. Claude's cloud has no `~/.se/local.toml`, so there
`public_identity` is unset and the project's identity applies. The identity goes into the
checkout's git config at the start, so merges carry it as well as commits: where `public_identity`
is set, `work_tickets.py sync` writes it (`user.name`, `user.email`); where it is unset, the role
runs `git config user.name` and `git config user.email` with the project's identity before its
first commit. A fresh clone, such as a cloud
session's, runs the project's setup command before its first commit, so the project's hooks run its
public check on every commit and push. Commit messages carry no tracker numbers (`#<n>`): a commit
outlives its tracker. No session prompt repeats any of this.

`commit_trailer` is the one place that names a commit trailer: an environment that requires one
(an agent host's co-author line) sets it on its machine, every role adds it as the last line of
each commit it makes, and `integrate` adds it to its merge commits. Unset, commits carry no trailer,
as a project's public rule may require.

The `--repo` resolution order is argument, `[trackers]`, then `origin`. A tracker is selected by
the repository name and is where that repository's work issues and field reports live. Work issues
and field reports carry `repo:<name>` for their repository; `ready`, `capacity`, and `queue` filter
to that label by default. Pass `--all-repos` to those commands to include tracker issues for every
repository instead. New worktrees default to the sibling `<checkout>.worktrees` folder unless
`--worktree-root` or `[worktree_roots]` overrides it.

### Mirrors

A machine may mirror a checkout to further Git remotes without declaring that relationship in the
repository. Configure each checkout key as an array of tables under `[mirrors]`; each table names
the locally configured remote, its target branch, whether `sync` fetches and merges that branch,
and whether it is public. `integrate` pushes `main` to every mirror after `origin`; before each
public mirror push it runs the project check command and refuses that push if the check fails.

```toml
[mirrors]
"<checkout>" = [
  { remote = "mirror", branch = "main", fetch = true, public = true },
]
```

## Commands and shell

- `work_tickets.py` means `python <se>/scripts/work_tickets.py <command> ... --worktree <checkout>`
  (standard library only). `--help` lists every command.
- A session may start in another checkout than the one it works in: `cd` to its worktree in every
  command, use absolute paths for every read and edit and for .NET file APIs (`[IO.File]::...`
  resolves relative paths against the process directory), and run git as `git -C <worktree>`.
- Windows PowerShell 5.1: judge native commands by exit code only; pass every issue, comment and
  pull-request body with `--body-file` (quotes or spaces inside native arguments break the call);
  no inline jq expressions with spaces (use `--json` and `ConvertFrom-Json`).

### Without gh

Where the host offers no `gh` (Claude's cloud), a role still follows its procedure; this section
owns what changes.

- **GitHub through the host's tools**: issues, comments, pull requests and field reports are read
  and written with the host's GitHub tools (in Claude's cloud, its GitHub MCP tools), with the same
  titles, labels, bodies and footers the commands would write.
- **Commands that still run** (they need no GitHub): `init`, `create`, `move`, `status`,
  `review-note`, `probe`, `sync`, `guard`, `config`, `close`. Every other command fails, naming
  itself, the missing `gh` and this section.
- **Every other step by hand**, as that command's `--help` and its role's procedure document it,
  for example:
  - `intake` and `refresh`: read the issue and its comments; `create` one ticket per numbered
    requirement plus `delivery`.
  - `deliver`: `sync`; `git push -u origin <branch>`; open the pull request to the integration
    branch, titled like the work issue; file the field report from `field-report.md`, filled in by
    hand (`field-report --draft` needs `intake`'s snapshot), titled `field-report: <branch>`, label
    `field-report`; send the notification.
  - `start`: start the worker session with the host's session tool, on an outcome branch named
    like the work issue and based on the integration branch.
  - `integrate`: merge the pull request's branch into the newest integration branch locally, run
    the complete suite and, where `se.toml` sets `public_check`, the public check
    (`public_check.py --rev HEAD --range <pre-merge>..HEAD`), refusing on a failure, push the
    integration branch, then close the issues with the
    `Integrated in …` comment.
- **Never `add_repo`**: the host's tool that attaches a repository stops the session at an
  approval prompt no one answers; a role works with the repositories its session started with.
- **Commit trailers**: the project's [`commit_trailer`](#what-the-project-provides) wins over a
  host's attribution reminder; with none set, commits carry no trailer.
- **Other process files**: where a host loads other instructions (an old plugin, another
  branch's `CLAUDE.md`), the role files and the project's `AGENTS.md` on the integration branch
  are the rules.
- **Retries after a server error**: after a 5xx from GitHub, read before retrying any write, not
  only a create (the object may exist); where closing with a state reason fails, close without
  one (GitHub's default reason is completed).
- **Delivery fallback**: an output whose write keeps failing after those retries goes in full into
  the next output that can be written, and a short placeholder points to it: where the field-report
  issue cannot be created with the report, the full report goes into the pull request body, a short
  field-report issue links it, and the delivery notice names the pull request.
- **The session prompt carries only** the agent, the work issue, the branch (the session's outcome
  branch, which replaces the worktree) and the integrator session to notify; everything else is in
  the role files, this skill and the project's `AGENTS.md`:

  ```text
  Act as the worker agent defined in <se>/.github/agents/worker.agent.md (read it first, plus the project's AGENTS.md).
  Work issue: <issue URL>
  Branch: <branch>
  Integrator session to notify at delivery: <integrator session>
  ```
