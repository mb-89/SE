---
name: work-model
description: 'The shared rules of how we work, for every role (SE, worker, integrator): one work issue in, a pull request out whose description is the field report; the box; escalation; freshness, dependencies and scheduling; worktrees; local tickets and notes; what a project provides. Load it whenever you act as SE, worker or integrator, write or read work or retro issues or field reports, or use <se>/scripts/work_tickets.py.'
---

# Work model

This skill owns the rules that are the same for every role. Each role's own rules live in its
agent definition: [SE](../../agents/se.md),
[worker](../../agents/worker.md), [integrator](../../agents/integrator.md). The
SE's procedure is the [catch-up](../catch-up/SKILL.md) skill.

Issue formats are the templates in [`.github/ISSUE_TEMPLATE/`](../../../.github/ISSUE_TEMPLATE/).
Everything specific to one project (its commands, design notes, quality rules, hot files) is owned
by the project's `AGENTS.md`; see [What the project provides](#what-the-project-provides).

## Roles and flow

One issue in, one issue out; the same for local sessions and cloud agents.

- **Work issue (in)**: one GitHub issue per package from `work.md`, carrying only the task. Title
  = branch name (`<type>/<topic>-<yyyymmdd>`), labelled as [Issues](#issues) says. Everything that
  is the same for every package lives in the agent definitions and this skill, never in issues. A
  session prompt names only the agent, the issue and the worktree.
- **The box**: a worker changes only its own worktree. Any other checkout it reads (for example a
  related repository its tests use) is read-only. Everything comes in through its work issue
  (re-read with its comments before each ticket, so it can change in flight) and goes out through
  its pull request, whose description is its field report. What it needs outside the box goes into the field
  report.
- **Out**: a pushed branch, a pull request to the integration branch whose description is the
  field report, and one notification to the integrator. No field-report issue is filed: one piece
  of work is one issue, the work issue, which the integrator closes once the work is integrated.
  - The report's one form is the pull request template,
    [`.github/pull_request_template.md`](../../../.github/pull_request_template.md). The report
    sits between its `<!-- se:field-report -->` and `<!-- se:field-report:end -->` lines.
  - `field-report --draft` writes it there, and every reader (`field-report --check`, `guard`,
    `release-trailer`, `integrate`, `queue`) finds it there. A description without them holds no
    report and is refused.
  - Field-report issues filed before this are history: they keep their `field-report` label and
    are not migrated; nothing new gets that label.
  - The field report holds what was not done, decisions with confidence, spec gaps, a short retro
    and tickets for other repositories.
  - Each "Tickets for other repositories" entry is one reusable capability and lists every source
    file it replaces.
- **Integrator**: a subtype of worker and the only writer of the integration branch.
- **SE**, the main agent (formerly the dispatcher): the only session the human talks to. SE never
  writes any repository. It may file work issues for and dispatch into any repository by starting or
  messaging that repository's integrator.
  - Each repository has exactly one integrator, the only writer of its integration branch. The
    integrator starts that repository's workers.
  - Workers stay in their box; a worker records cross-repository needs in its field report.
- **Only SE talks to the human.** Workers and integrators never ask the human anything
  and never wait for an answer, an approval or a decision: they decide what they may decide,
  escalate the rest, and continue with other work or end their turn. A step only the person may
  approve is prepared below and run by SE ([Steps only the person approves](#steps-only-the-person-approves)).
- **Escalation**: what a role may not decide climbs the [escalation ladder](#escalation-ladder).
- **Asking a working agent**: a person who wants to ask a running worker or integrator something
  asks SE, which sends it a message down the tree. There is no other channel into a running
  session.
- **Messages travel only up and down the tree**: a session messages only the session that started
  it and the sessions it started. A sideways message (one integrator to another) stops at a
  permission prompt in Claude's cloud, so news for another repository goes up to SE,
  which passes it down to that repository's integrator.
- **Comments carry the host's footer**: where the host requires a footer on every GitHub comment
  (Claude's cloud does), each fixed comment text a role or command gives (`Started: …`,
  `Integrated in …`, an escalation) is followed by that footer, unchanged. Nothing else repeats
  this rule.
- Issues are read and written with `gh`, bodies through `--body-file`; where the host offers no
  `gh`, see [Without gh](#without-gh). Branches and the integration branch are pushed; a release
  needs the human's approval, obtained by SE.
- Retros use `retro.md` and read the field reports in the pull request descriptions of the
  window's closed work issues; each improvement names the agent definition, template, skill or
  script it changes, and becomes an ordinary work issue.

## Issues

An issue is one package of work: its title is its branch name, and it ends as one merge whose
pull request carries its field report.

- **Sizes**: tiny, small or medium. A topic bigger than medium becomes several issues, worked in
  order.
- **Kinds**: a work issue ([Roles and flow](#roles-and-flow)), work from outside
  ([Outside issues](#outside-issues)) and a backlog issue (below). A field report is no issue: it
  is the description of the work's pull request.
- **Decisions are never issues**: they go to the person as a deck, as the
  [escalation ladder](#escalation-ladder) says.
- **Labels**: SE labels work itself; the person never labels anything. SE files a work issue with
  `work_tickets.py file`, and routes a checked outside issue with `work_tickets.py route`; both
  apply `work`, `ready` and `repo:<name>` in the same step, creating the labels a repository lacks.
  - `ready` is the GitHub record that SE checked the issue and it may be worked; `ready` and
    `start` take only `work` + `ready`, never a `backlogged`, `field-report` or `in-progress`
    issue.
  - `file --blocked-by <n>` links the blockers before it adds `ready`.
- **Planned**: optional. An open issue whose body has a line of its own `Planned: yyyy-mm-dd` is
  planned for that day; the Timeline (`<se>/scripts/timeline.py`) shows it on that day, or on Today
  marked late once the day has passed.
- **Backlog**: a far-out idea that is not ready work is an issue labelled `backlogged` and
  `se-person`, filed and found by SE with `work_tickets.py backlog file` and `backlog list
  --search <text>` (title and body).
  - It is not work: no integrator or worker takes it (`ready` and `start` skip it), and the
    outside-issue intake skips it, as neither new work nor an outside issue.
  - It becomes work only when SE re-files it as a work issue, or removes the `backlogged` label
    once the owner has blessed it.

## Escalation ladder

Issues carry work between boxes. A decision a box may not take climbs a ladder: worker, then
integrator (integrators may nest, each escalating to the one that started it), then SE,
then person. Every level decides, and writes what it sends up, as the
[decision skill](../decision/SKILL.md) says.

- **One level per loop**: a loop climbs one level each time it would repeat. A point that has gone
  around once at one level (a merge refused and sent back, the same open point raised again) goes
  to the next level up instead of around again.
- **How each level sends it up**: a worker in its field report's "Not delivered"; an integrator
  with `work_tickets.py escalate` (label `escalated`, the decision note linked in the comment)
  and, at the top level, one message to SE. The answer comes back as an issue comment
  or a new request, never as a reply anyone waits for.
- **Straight to the person**: a level that is sure a person must decide (a one-way decision, a
  removed capability) may mark it "for the person", and the levels above pass it on without
  deciding it. That is allowed, not preferred.
- **The person gets decisions as a deck, not as issues**: SE brings the person the open
  decision notes together as one deck. Not everything that reaches the person is an escalated
  issue: a decision from SE's own discussion with the person joins the deck directly.
  Until the deck command exists, SE shows the notes one after the other.

### Steps only the person approves

The person talks only to SE ([dec-012](references/rules.md#dec-012-only-se-asks-the-person)). A host
counts a person's approval only in the session it was given, so a step that needs one is run in
SE's session, never in a worker's or an integrator's: those roles prepare it and escalate it, and
no procedure but SE's sends the person to a session.

- **One-way ref changes** (force-updating or deleting a branch, moving or deleting a tag) go
  through the repository's `ref-maintenance` workflow, as triples `<old-sha> <new-sha> <ref>`.
  1. The integrator pushes the commits the new refs point to, writes the triples to a file and
     runs `work_tickets.py refs request <issue> --triples-file <file>`: it posts the triples on
     the issue, runs the workflow's dry run, posts its output and labels the issue `escalated`.
     It prints the one line the integrator sends SE as its escalation message.
  2. SE presents that line to the person. On the person's yes, SE runs `work_tickets.py refs
     apply <issue>`, which runs the workflow for real with the posted triples, reads the refs back
     from origin and posts the result; SE sends the integrator the line it prints.
  3. The integrator verifies the refs (`git ls-remote origin`) and closes out.

  Without a signed-in `gh` both commands hand their GitHub steps to the session as a plan and
  read the refs back with `--read-back` ([Without gh](#without-gh)).
- **Every other step only the person may approve** (a setting, an environment, a permission, a
  push to a protected branch) is escalated the same way: the escalation names the step and its
  exact command or setting. SE runs it on the person's yes, or names the one setting the person
  changes.

## Outside issues

An outside issue reaches a repository from outside the fleet: from the person's other side or any
other source. It arrives unlabelled and nothing is asked of whoever files it; the fleet tells its
own issues apart instead, and SE labels it once it routes it ([Issues](#issues)):

- Every issue the fleet files carries the hidden marker `<!-- se:fleet -->` in its body: the issue
  templates hold it, and `file` and `backlog file` add it. An issue labelled `field-report` (one of
  the old field-report issues) counts as marked.
- `se.toml` `[outside]` names each repository SE watches with its cut-off, the last issue number
  that existed before the marker (`"<host>/<owner>/<repo>" = <number>`); issues up to it are known,
  never outside issues.
- An outside issue is handled once its body or one of its comments carries `<!-- se:handled -->`,
  so the record lives on the issue itself.
- Routing one (`work_tickets.py route`) is one edit: its title becomes its branch name, given or
  derived from its title, and it gets the work labels.
  - Its body, unchanged above, gets the handled marker and one section headed Routing: a
    `Routed from:` line with the original title, then the
    [work.md](../../../.github/ISSUE_TEMPLATE/work.md) sections it lacks, one heading level down.
  - Every reader of the issue's sections reads these as its own; `field-report --check` enforces
    the numbered requirements there, named "Routing".
- `work_tickets.py intake --outside` lists the open, unmarked, unhandled issues above each
  cut-off, read in one query. What SE does with each is its
  [outside-issue routine](../../agents/se.md#outside-issues).

## Integration branch

The integration branch is the one branch the integrator writes and every worker branches from,
merges and opens its pull request against. It is `main` unless the project names another in
`se.toml`, for example while an older process still lives on `main`:

```toml
[project]
integration_branch = "next"
```

`work_tickets.py` reads it from there for `sync`, `start`, `deliver`, `guard` and `integrate`;
`integrate` refuses a main checkout that is not on it. Below, `main` means the integration branch.
Nothing is pushed to it directly: `integrate` lands each integration as a squash pull request that
waits for the required check `check`, as the README's
[Landing on main](../../../README.md#landing-on-main) says.

Every pull request into the integration branch names the work it does, so no work is done outside
the issues dispatch reads:

- Its description names at least one issue of the repository that is open and labelled `work`,
  with `Refs`, `Closes` or `Fixes` and `#<n>` or the issue's URL; it may name several.
- A landing pull request passes by its `Lands <work pull request>` line, where that work pull
  request's description names one.
- The repository owner's own pull request labelled `housekeeping` is exempt.
- The job `check` enforces it with `<se>/scripts/pr_issues.py`, through the Actions token.

Nothing reaches the integration branch without a passing complete suite and, unless `se.toml` sets
`public_check = false`, a passing public check on exactly the tree pushed:

- `work_tickets.py suite` (which `integrate` runs) records its verdict on the tree of the commit
  it ran on, where the checkout holds exactly that commit; `public_check.py --rev <commit>` records
  its verdict on that commit's tree. A failure, or a suite over its limit, records a failure.
- `integrate` refuses to push a landing branch without both passing verdicts on its tree, and
  reads the squash commit back only with that tree; `work_tickets.py push` and se's pre-push hook
  (`work_tickets.py verified`) refuse a push of the integration branch itself the same way, naming
  the commit and the remedy.
- The release commit (only the version and what `release_build` regenerates) carries its parent's
  suite verdict.
- There is no bypass: an emergency push runs `suite` like any other.
- The verdicts live in the repository's git directory (`se-verdicts/`, `<se>/scripts/verdicts.py`),
  shared by its worktrees.

## Release kind

A release's kind follows what changed, never the branch name: the worker declares it in the field
report's "Release kind" (patch, minor or major, with a one-line reason), and
[releases](../../../README.md#project-settings) bump by it. The branch prefix only proposes a
default (`field-report --draft`).

- **Breaking means major**, as Semantic Versioning 2.0.0 (item 8) defines it: removing or
  renaming a public command, option, field or format, or making an optional field required,
  breaks what depends on it.
- **The check**: such a report lists each as a `**Breaking:**` line under "Removed behaviour", and
  `field-report --check` refuses it, or a work issue whose "Package kind" says "breaking", as
  patch or minor.
- **Public** is what a user of the project relies on: its command-line interfaces, its file formats
  and schemas, and its documented module APIs.
- Otherwise new behaviour is minor and a fix that changes no public interface is patch.
- **A change to these rules declares its own kind**: a package that changes how release kinds are
  derived states its kind in its work issue's "Package kind", because its integration runs under
  the rules it replaces (SE#792 was major by its own new rule, but the old `release-trailer` would
  have released it as a patch).

## Rules for all roles

Framework repositories (the process plugin and document format/converter) carry every capability
that is generically useful. Application repositories carry only their content and
application-specific code.

When an application reveals a generic capability, create a framework work issue and delete the
application's copy after the framework provides it. A framework never names, special-cases or
depends on an application; for public repositories, the public check's local list enforces this
boundary.

- Packages are worker-sized: one separately reviewable change. Larger work is split into issues
  linked by "Blocked by", each owning its part of shared files.
- Packages that touch the same hot file get one owner or run one after the other; the next one
  merges `main` before touching that file.
- Work issues quote the user's requirement word for word; the field report quotes it back.
- **Writing work issues**:
  - an issue that renames an identifier says whether the code emits it or only documents it;
  - a docs issue that asks to point instead of restating quotes the text to replace and names each
    note by its repository path;
  - a docs requirement names the test file its regression test belongs in;
  - content a worker needs from another repository (a list, a decision, a spec passage) is quoted
    inline with its source named, because a cloud worker reads only its own repository: a
    cross-repository link is never the only copy (`intake` warns on one with no quoted block next
    to it).
- Every error message names where it comes from (the command, file or input) and, where
  possible, the remedy.
- Work follows the user's priority order; no new investigation starts while a top-priority bug is
  open.
- Workers run focused tests and what their issue's acceptance names, the complete suite only
  where it names the suite; the integrator runs the complete suite, one integration at a time,
  while SE talks with the human.
- No hard time boxes: workers deliver whole items. A worker never ends its turn without
  delivering; when it stops, its field report names the blocker.
- **Disagree and commit**: ambiguity is a decision. Investigate the repository, contracts and
  tests, make the best defensible, reversible decision within scope, record it with its
  confidence for the field report, and continue. This never grants authority to bypass policy,
  disclose private data, act destructively or publish without approval.
- **Preserve capabilities**: removing or narrowing an existing user-visible capability, or
  deleting or weakening its protecting test, is a product decision for the human. "Disagree and
  commit" never covers it: the worker escalates instead. SE never writes a work issue that leaves
  "keep or remove" to the worker.
  - Deleting or condensing authored content is recorded in the field report with what was dropped
    and where it moved, unless the work issue names the change.
- **Mechanical first**: a procedure that repeats becomes a command in `work_tickets.py`
  (`intake`, `refresh`, `sync`, `guard`, `deliver`, `escalate`, `block`, `file`, `route`, `ready`,
  `capacity`, `queue`, `start`, `close`, `config`); prose steps remain only for judgment. Escalations and product decisions stay
  manual.

### Suite at a moved pin

When the acceptance names the complete suite and a dependency pin moves, the suite runs at the new
pin before the change, so failures that exist already are told apart from the change's own.

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
- Dependencies are native GitHub "blocked by" links, set by SE. Blocked state is
  computed (`issue_dependencies_summary.blocked_by`), never a label. `ready` is only
  [SE's approval](#issues); startable = `ready` and zero open blockers.
- Labels change only in these steps: SE's `file` and `route` ([Issues](#issues)); `start` changes
  `ready` to `in-progress`, and so does the integrator in the step where it starts a worker with
  `create_session` instead of `start`; the integrator removes `in-progress` when it closes the
  issue.
- After each integration the integrator starts every startable work issue that has no branch yet
  and whose file ownership does not clash with running workers, and starts its session itself.
- Nobody watches for deliveries. Triggers: the worker's delivery notification (its only message
  to another agent, never a question); `work_tickets.py queue` at the start of every integrator and
  SE turn, so a missed notification is handled as soon as either session is talked to; in the
  cloud only, scheduled triggers.
- **Delivered, waiting for integration** is an open pull request to the integration branch whose
  description carries a complete field report (one that follows its form); `queue` lists them.
- **Closing**: `integrate` closes the work issue with a comment that links the pull request and
  the release, and names the landing pull request with its `check` run. Where acceptance can only be seen after the merge, the issue stays open and the
  comment names what it waits for.
- Capacity limits apply only to local workers (CPU cores and memory minus running workers). Cloud
  workers have none. File clashes and the serial merge queue apply everywhere.
- An integrated worker session is deleted once its branch is on `main` and its worktree is
  removed; a session is kept only while it holds an unresolved discussion with a handover issue.

## Worktrees

- One worktree per local worker, created when its work starts, from the newest `main`, by
  `work_tickets.py start <issue> --worktree <main checkout>`:
  - it refuses an issue that is not startable (including open blockers, an existing branch, a
    file-ownership clash or exhausted local capacity);
  - it fetches, runs
    `git worktree add -b <branch> <worktree-root>/<branch-with-slashes-replaced> origin/main` and
    changes the issue's `ready` label to `in-progress`;
  - it prints the worker launch line with the exact created path.
  - In a cloud runner, pass `--cloud-agent <login>` (or set `SE_CLOUD_AGENT`) to assign the worker
    and change the labels without creating a local worktree.
- Copilot CLI offers a platform-enforced alternative, not the local-worker launch path:
  `copilot --agent worker --no-ask-user --allow-all-tools --prompt "<worker prompt>"`. Keep
  agent-host `create_session` workers as the default until a separate decision changes that path.
  - A live `worker`-profile run declared its `execute`, `read`, `edit`, `search`, and
    `send_message` allowlist and exposed no `ask_user`; however, the unprofiled CLI prompt-mode
    control also exposed no `ask_user`, so this does not prove that absence is profile-specific
    (and `set_workspace` is not a CLI tool).
  - This alternative creates no UI session, so there is no user visibility, steering or review
    return by message, or delivery notification; additionally, `--allow-all-tools` approves every
    tool in the profile without prompts.
- A project whose packages need more than one plain worktree (paired checkouts, a test environment
  file, linked dependency folders) provides its own creation and removal scripts and names them in
  its `AGENTS.md`; it creates the worktree from the newest `main` with its script.
  - Then `start --no-create` verifies the linked worktree for the issue's branch, merges `main`
    into it, then changes `ready` to `in-progress` and prints the launch line; without a worktree
    it refuses. Cloud start (`--cloud-agent`) is unchanged.
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
  existing standard issue.
  - A project that needs another ignored root declares it in its worker command with
    `--probe-root <relative-path>`.
  - `work_tickets.py probe --command <command> --output <path>` appends the command and its output
    to the index. `field-report --draft` links that index in Delivered.
- Test-driven: regression first, then the change, then focused checks and the affected real
  command. Check an acceptance item only with evidence; move a ticket to `done/` only when every
  item is satisfied. A ticket that cannot be finished stays in `held/` with the attempts and
  failure evidence, and the field report states it as not delivered with exact next steps.
- A partial-delivery blocker is only work outside the worker's box: another package's file, a
  user decision, or missing access. Tests of the package's own code are never blockers, including
  failure paths exercised with temporary repositories or fakes. Workers may create, use and close
  throw-away tracker issues for live acceptance runs.
- Notes are private scratch: never committed, never copied into tracked files or reports. A note
  is resolved by a local `Disposition:` line stating the decision; future work becomes a
  [backlog issue](#issues) or work issue, not a copy of the note. Only unresolved notes block worktree removal.
- Rebuilds use the latest integrated state through the project's build command; every integrated
  package that changes output includes a fresh build and a check of the affected output.

## Tests

This section is the one statement of how tests are written
([tst-002](references/rules.md#tst-002-fast-tests), fast tests); work
issues point here and never restate it. The project's suite and its time budget are `[tests]` in
`se.toml` ([Test budget](../../../README.md#test-budget)), which the integration gate enforces.

- Test a behaviour once, at the outermost interface (the command a person or role runs), on fakes;
  real outside services appear only in their own contract tests.
- No sleeping and no wall clock: time comes from an injected clock, waiting from an event.
- Tests run in parallel and share no state; fixtures are built once and reused.
- Browser checks are batched: one browser session serves every check of a run.
- A worker whose change adds tests runs `work_tickets.py suite` before and after the change and
  reports both times in its field report (`**Suite time:**`); each new test that takes over 2 s is
  named there with its reason.

## What the project provides

se is project-neutral. A project that uses it states in its `AGENTS.md`:

- where se lives in the project, `<se>` in every skill and agent (`.` in se itself), and that `.se/`
  is git-ignored;
  - in Claude Code, the start hook names it in the session context as `SE root: <path>` (a plugin
    install, a `~/.claude/skills/se` clone and se's own checkout alike), and that path wins;
  - scripts are always `<se>/scripts/<name>.py`, never relative to the working directory;
    `<se>/scripts/se_plugin.py` refuses a skill or agent that names one otherwise;
- the setup command that installs the tools the roles need (`git`, `gh`, Python 3.11 or newer and
  whatever the project's tests need);
- the focused and the complete test commands, including gated test tiers if there are any;
- its public check with the hooks that run it; `public_check` in its `se.toml`
  ([Project settings](../../../README.md#project-settings)) gates every push to the integration
  branch on it, on unless the project sets it to `false`;
- its integration project checks as JSON argument arrays passed to `integrate --check-command`, for
  example `--check-command '[["uv", "run", "pytest", "-q"], ["uv", "run", "python", "check.py"]]'`.
  The commands run without a shell. Add `--check-command-temporary-directory` when every command
  needs an isolated temporary working directory;
- the build command that regenerates the project's outputs and how to check them;
- the design notes that own product qualities, ownership and testing rules;
- its worktree scripts, when a plain worktree is not enough (see [Worktrees](#worktrees)), and the
  environment file a testing shell must load, if any;
- its hot files (files that parallel packages touch and that need one owner).

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

**Commit identity and public check**
([pub-002](references/rules.md#pub-002-a-generic-commit-identity)): every role commits as `public_identity` where the machine
sets it (the [Modules guide](../../../README.md#machine-local-selocaltoml) owns what it pins), else
as the project's `identity` in its `se.toml` ([Project settings](../../../README.md#project-settings)).
Claude's cloud has no `~/.se/local.toml`, so there the project's identity applies. No session prompt
repeats any of this section's rules:

- `work_tickets.py sync`, which every role runs at the start, writes whichever applies into the
  checkout's git config (`user.name`, `user.email`), so merges carry it as well as commits.
- A fresh clone, such as a cloud session's, runs the project's setup command before its first
  commit, so the project's hooks run its public check on every commit and push.
- Commit messages carry no tracker numbers
  ([pub-004](references/rules.md#pub-004-no-tracker-references-in-commit-messages)). se's public check refuses them in its commit gates
  ([Public safety](../../../AGENTS.md#public-safety)), and `integrate` writes its merge messages
  without them where the project's public check is on.

`commit_trailer` is the one place that names a commit trailer: an environment that requires one
sets it on its machine, every role adds it as the last line of
each commit it makes, and `integrate` adds it to its merge and squash commits. Unset, commits carry no trailer,
as a project's public rule may require; se's public check refuses attribution trailers
([pub-003](references/rules.md#pub-003-no-attribution-trailers),
[Public safety](../../../AGENTS.md#public-safety)).

The `--repo` resolution order is argument, `[trackers]`, then `origin`. A tracker is selected by
the repository name and is where that repository's work issues live; its pull requests, and the
field reports their descriptions carry, live on `origin`.

Work issues carry `repo:<name>` for their repository; `ready`, `capacity`, and `queue` filter to
that label by default. Pass `--all-repos` to those commands to include tracker issues for every
repository instead. New worktrees default to the sibling `<checkout>.worktrees`
folder unless `--worktree-root` or `[worktree_roots]` overrides it.

### Mirrors

A machine may mirror a checkout to further Git remotes without declaring that relationship in the
repository. Configure each checkout key as an array of tables under `[mirrors]`; each table names
the locally configured remote, its target branch, whether `sync` fetches and merges that branch,
and whether it is public.

`integrate` pushes `main` to every mirror after `origin`; before each public mirror push it runs
the project check command and refuses that push if the check fails.

```toml
[mirrors]
"<checkout>" = [
  { remote = "mirror", branch = "main", fetch = true, public = true },
]
```

## Adapter sync contract

An adapter is a command that writes to an external system (a tracker, a wiki, a service's API).
Every adapter follows this contract; [`<se>/scripts/adapter_sync.py`](../../../scripts/adapter_sync.py)
is its reusable part, imported from the project's se module.

- **One command, dry run by default**: it reads the external state, computes the plan and the
  merge, prints a complete change and conflict report, and writes nothing.
- **An explicit `--apply`** performs the writes (`add_apply_argument`).
- **Preflight on apply**: the apply repeats the reads; an object whose external revision changed
  since the plan was computed is not written, and the report names it (`preflight`).
- **One logged write path**: every external request goes through one transport (`Transport`),
  whose verb guard refuses any non-read request outside apply mode, naming its method and path,
  and whose log (method, path, status, time; never headers or bodies) is the audit. No side
  scripts, no second client.
- **Secrets**: read from the environment at run time (`secret_from_env`); never printed, logged,
  committed or stored, and scrubbed from every recorded response (`Transport.recorded`).
- **Artifacts**: the dry run's plan and the apply's result are written as machine-readable files
  (sorted JSON, `write_artifact`), so reviews and tests compare them.

## Commands and shell

- `work_tickets.py` means `python <se>/scripts/work_tickets.py <command> ... --worktree <checkout>`
  (standard library only). `--help` lists every command.
- A session may start in another checkout than the one it works in: `cd` to its worktree in every
  command, use absolute paths for every read and edit and for .NET file APIs (`[IO.File]::...`
  resolves relative paths against the process directory), and run git as `git -C <worktree>`.
- Wait on a background process by its process id (`kill -0 <pid>` in a loop; PowerShell
  `Get-Process -Id <pid>`), never by `pgrep -f <pattern>`: the pattern matches the waiting shell's
  own command line, so the wait never ends.
- Windows PowerShell 5.1: judge native commands by exit code only; pass every issue, comment and
  pull-request body with `--body-file` (quotes or spaces inside native arguments break the call);
  no inline jq expressions with spaces (use `--json` and `ConvertFrom-Json`).

### Without gh

Where the host offers no `gh` (Claude's cloud), a role still follows its procedure; this section
owns what changes. A `gh` that is installed but fails `gh auth status` counts as no `gh`.

- **GitHub through the host's tools**: issues, comments and pull requests (their descriptions
  carrying the field reports) are read and written with the host's GitHub tools (in Claude's cloud, its GitHub MCP tools), with the same
  titles, labels, bodies and footers the commands would write.
- **Commands that still run** (they need no GitHub): `init`, `create`, `move`, `status`,
  `review-note`, `probe`, `sync`, `suite`, `guard`, `config`, `close`, `push`, `verified`,
  `comments-read`, `body-read --body-file`, `release-trailer`, `pr-body`, `docs` and
  `field-report --check`.
- **Commands that hand off** their GitHub steps: `integrate`, `refs request` and `refs apply`
  do everything local, print their GitHub steps as a plan of tool names and arguments, and
  check the result through git with `--read-back` (README
  [Landing on main](../../../README.md#landing-on-main)).
  - The session runs each plan's steps in order with its GitHub tools, then the plan's `Then:`
    line.
- **Every other command** fails, naming itself, the missing `gh` and this section.
- **Every other step by hand**, as that command's `--help` and its role's procedure document it,
  for example:
  - `intake` and `refresh`: read the issue and its comments; `create` one ticket per numbered
    requirement plus `delivery`; record the comments read with `comments-read --count <n>
    --newest <id>` and the body read with `body-read --body-file <file>`, from what the GitHub
    tools read.
  - `intake --outside`: read each `[outside]` repository's open issues and their comments, and
    keep those [Outside issues](#outside-issues) leaves.
  - `deliver`: `sync`; `push`; open the pull request to the integration branch, titled like the
    work issue, with the description `pr-body --issue-body <file> --issue-url <url>
    --field-report .se/work/field-report.md` prints (the closing line, then the report between
    its markers); send the notification. No issue is filed.
    - The field report comes from `field-report.md`, the template copied with its markers and
      filled in by hand (`field-report --draft` needs `intake`'s snapshot).
    - It passes `field-report --check .se/work/field-report.md --worktree <worktree> --issue-body
      <file> --comment-count <n> --newest-comment <id>` (the work issue's body saved to `<file>`,
      its comments as the GitHub tools read them now).
    - That check runs after `sync` and before `push`: it fills the report's Branch tip from the
      branch.
    - A commit after delivery changes the tip: run the check again and update the pull request's
      description in place.
    - A refused report is fixed and checked again, never delivered.
  - `start`: start the worker session with the host's session tool, on an outcome branch named
    like the work issue and based on the integration branch.
  - `integrate`: the hand-off, the cloud path of [Landing on main](../../../README.md#landing-on-main).
    - Save the pull request's description and its work issue's body to files, then run
      `integrate <pull request> --pr-description <file> --issue-body <file> --branch <its head
      branch>`.
    - It checks the report, merges on `land/<branch>`, runs the complete suite, the checks and
      the public check, releases, pushes `land/<branch>` and prints the landing plan.
    - Its refusals (late commits, a failed check) are those with `gh`; `--include-late <reason>`
      states why late commits are included.
    - Run the plan's steps; anything but a passed `check` merges nothing.
    - Then `integrate --read-back <branch> --landing-pull <number> --check-run <url>`: it reads
      the landing back through git, fast-forwards the checkout, cleans up and prints the
      close-out plan; run its steps. It starts no session: start what is unblocked as `start`
      above says.
  - `refs request` and `refs apply`: the same hand-off. `refs apply` takes the issue's comments
    as the GitHub tools read them, saved as a JSON list, with `--comments-file <file>`.
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
- **Delivery fallback**: where the pull request cannot be opened with the report as its
  description after those retries, open it with the closing line alone, then write the full
  description (`pr-body`'s output) by editing the pull request; the delivery notice names the pull
  request.
- **The session prompt carries only** the agent, the work issue, the branch (the session's outcome
  branch, which replaces the worktree) and the integrator session to notify; everything else is in
  the role files, this skill and the project's `AGENTS.md`:

  ```text
  Act as the worker agent defined in <se>/.github/agents/worker.agent.md (read it first, plus the project's AGENTS.md).
  Work issue: <issue URL>
  Branch: <branch>
  Integrator session to notify at delivery: <integrator session>
  ```
