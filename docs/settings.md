# Settings

## Project settings

`se.toml` also holds every project setting owned by se. Each se tool validates only the settings it
owns.

```toml
[project]
authored_content = ["README.md", "docs/**/*.md"]
identity = "mb <mb>"
integration_branch = "main"
public_check = true
release = "workflow"
release_build = ["uv", "run", "python", "scripts/se_plugin.py", "build"]
version = "1.4.2"
```

`identity = "Name <email>"` is the project's commit identity. `work_tickets.py sync` writes it into
the checkout's git config (`user.name`, `user.email`), so every later commit and merge there
carries it, unless the machine sets `public_identity`, which wins. Unset, sync leaves the checkout's
identity as it is.

The plugin's session start (`scripts/bootstrap.sh --hook`) and the setup scripts write it the same
way (`work_tickets.py identity`), so a fresh clone's first commit never carries the host's default
identity.

`work_tickets.py push` refuses without one, and `work_tickets.py release` commits its release
with that identity explicitly, whatever the checkout's configuration or environment says. The
[public check](../AGENTS.md#public-safety) refuses a commit not yet pushed whose author or committer
differs from it.

`integration_branch` is owned by the
[work model](../src/skills/work-model/SKILL.md#integration-branch).

`public_check` makes `work_tickets.py integrate` run se's
[public check](../AGENTS.md#public-safety) on the merged tree and every merged commit before it pushes
its landing branch; on a failure it pushes nothing, leaves the integration branch as it was and
escalates. `work_tickets.py push` runs its push gate first.

Default `true`, so a project that never set it is still checked; a project without a public check
sets `public_check = false`, and `push` then prints one line saying the check is off and where to
turn it on.

Whatever `public_check` says, `push` (and every command that pushes through its gate) pushes only
a local branch, never a refspec, tag or commit, and refuses one that carries commits another remote
holds but origin does not: a project kept on two hosts shares trees, not histories. Only origin's
remote-tracking branches count as held by origin; a local tag proves nothing about it.

The check before every push knows its destination remote: it gates each commit that remote does
not hold yet, and a local-list line `remote:<remote name> <regex>` stops only the pushes to that
remote, so one checkout with two remotes keeps a term from one while the other may receive it.
The local list's line forms are [Public safety](../AGENTS.md#public-safety)'s.

`components` is the project's component listing command, an argument array run without a shell
in the checkout, such as obs's `["uv", "run", "obs-components"]`.

With no argument it lists, never installs: a table headed `component  kind  installed  newest  repository`, two spaces or more
between columns, as obs-components prints it. SE's start reports its offers
([Start and refresh](start.md#start-and-refresh)); unset, it runs nothing.

`version = "MAJOR.MINOR.PATCH"` is the project's one semantic version, published as the git tag
`vMAJOR.MINOR.PATCH` on its integration branch; consumers pin ranges of it
([`se.toml`](modules.md#setoml)). Nobody types it after the first, and a landing never moves it: each
landing only records its release kind, and the version moves when SE asks for a release.

Each integration is a first-parent commit whose message starts `Integrate <branch>` and states its
kind in the trailer `Release-kind: major|minor|patch`: the merge `integrate` builds, and on the
integration branch the one commit it lands as ([Landing on main](#landing-on-main)).
`integrate` writes it, and `work_tickets.py release-trailer` prints it:

- on a re-integration (an integration `Integrate <branch>` of the same branch is already on the
  integration branch) the field report's "Re-integration kind", `patch` unless it says otherwise;
- else the field report's "Release kind", which the
  [work model](../src/skills/work-model/SKILL.md#release-kind) owns; a missing or unknown kind is
  refused before anything is merged.
  - `field-report --draft` only proposes it; the worker keeps or replaces it by what changed.
  - It proposes the kind a breaking change takes at the project's `version` where the work
    issue's "Package kind" says "breaking"; else by the kind of work it names (or an old name's
    `<type>/` prefix): `feature` (or `feat`) `minor`; `fix`, `perf`, `chore` or `docs` `patch`.

`work_tickets.py release` is the release, which the integrator runs only when SE asks
([integrator](../src/agents/integrator.md#release)). One release raises the version once, by the
highest kind recorded since the last release, whose commit the tag of the current version names:

- On `land/release-v<new>` at origin's newest integration branch it rewrites only `version`, runs
  `release_build` where set and commits `Release v<new>` with what that regenerated, its message
  listing each integration it releases with its kind.
- The commit carries its parent's suite verdict (the complete suite runs where none is recorded),
  and the public check runs on it.
- It lands as integrate's landings do ([Landing on main](#landing-on-main)): a landing pull request,
  its `check`, then the squash merge or the fast-forward; without gh it prints the plan, and
  `release --read-back <tag>` finishes. That pull request names no work issue: `pr_issues.py`
  exempts the owner's `land/release-v<version>`.
- Then it tags the landed commit and pushes the tag, or leaves it to the
  [release workflow](#release-tags).

Two landings of kind patch, then one release, raise the version by one patch. With nothing
integrated since the last release, the release releases nothing and says so.

A landed integration without the trailer has no default kind: the release refuses it, naming
it, until `--kind <commit>=<kind> <reason>` states its kind, which the release commit records. A
kind that cannot be told otherwise (an unknown one, or two) is set by hand: the person sets
`version` in a pull request, which the next release tags as it is.

Below 1.0.0 a major bumps the minor part (0.3.1 to 0.4.0), so no kind reaches 1.0.0: the person
sets `version = "1.0.0"` by hand, as the statement that the interface is stable, and the release
tags it as it is.

A version without its tag yet is tagged as it is, which is how a project starts versioning.
Without `version` the release releases nothing and says so; a malformed one is refused, naming
the file.

`release_build` is the command that regenerates what copies the version (se's plugin manifests:
`["uv", "run", "python", "scripts/se_plugin.py", "build"]`), an argument array run without a shell
from the project root. Where it fails, the release restores `se.toml`, commits nothing and shows
its output.

`integrate` also runs it on its merge, before the suite, and commits what it rewrites into the
landing: a generated file that carries the version, added on a branch before `main` released,
never makes the branch stale, and the suite's verdict is recorded on the merge's tree.

### Workers

```toml
[workers]
local = 4
cloud = 8
claim_timeout_hours = 12
```

`[workers]` limits how many working agents run at once. `local` holds a local device's limit,
default 4; `cloud` holds the cloud's (a Claude Code cloud session, a CI runner), and unset leaves
the cloud open. Each is a whole number of at least 1. `claim_timeout_hours` is the claim timeout
below, a positive number of hours, default 12; other keys are refused.

- **What counts.** A worker runs while its work issue is open and labelled `in-progress`.
  `work_tickets.py capacity` prints how many more may start: the limit less those running, on a
  local device also its cores and memory.
- **Who holds it.** `start` refuses a start beyond it. Without gh it reads the workers running
  through kern's relay, or from `--running <file>`. An [integrator](../src/agents/integrator.md)
  starts no more, and after each landing starts the next startable issue, so a worker that
  finished frees its place. The [dispatcher](fleet.md#dispatcher) fires nothing while the limit is
  reached.
- **Not limited.** Integrators, reviewers and SE's own session.
- **The claim's beat.** A claim carries its heartbeat on the issue: the `in-progress` label, and
  one line in the body, `<!-- se:beat <UTC time to the minute> -->`. `start` writes the first
  with the claim, and the close-out removes it.
  - The worker's `intake` records its due time in `.se/work/beat.yaml`. On every tool call the
    plugin's hook (`scripts/se_hook.sh`) reads that file alone; once half the claim timeout has
    passed it starts `work_tickets.py beat` in the background, which sets the line to now.
  - A failed beat is due again 15 minutes later. Without gh, `beat` runs through kern's relay,
    so the session runs its read and write when the hook tells it. The write carries the issue's
    own labels, so the [template gate](templating.md#templates) judges it by the issue's own template.
  - The beat line is no change to the issue's text: refresh, the first hold, the body-read check
    and the template check ignore it.
- **Live or stale.** `work_tickets.py ready` names each claimed issue live (beat younger than the
  claim timeout) or stale (older, or no beat), with the beat's age; neither is startable. Its
  last line names the stale ones for SE to pass to the person; without gh, `ready --claimed
  <file>` judges the `list_issues` answer that `queue`'s plan reads.
  - Nothing frees a claim on its own. Releasing one is the person's step, which SE prepares:
    delete its branch, take off `in-progress` and remove the beat line.

### Commit checks

```toml
[commit_checks]
forbids = ["go", "run", "./cmd/kern", "forbids"]
```

`[commit_checks]` names a project's own commit checks, each a name and its command, an argument
array run without a shell. se's commit hook (`.githooks/pre-commit`, after the
[public check](../AGENTS.md#public-safety)) runs each in a copy of the staged tree, so code that
breaks one is refused before it is committed, not first at landing.

- **The staged tree.** The copy holds the index, the tree the commit records: an unstaged edit
  and an untracked file decide nothing. The table is read from the staged `se.toml`, and the
  check's git variables are removed, so its git never reaches the committing repository.
- **The refusal.** A check that exits non-zero refuses the commit, naming the check, its exit
  code and its command, with its output below; one that cannot start refuses it too. Each passing
  one prints `commit check <name>: passed`.
- **Every project.** A repository that runs se's hooks from se as a module runs its own table
  ([Public safety](../AGENTS.md#public-safety), "Hooks"); unset, the hook runs nothing more.
  `scripts/commit_checks.py` owns the table and the run.

### Landing on main

Every integration lands on the integration branch through a landing pull request and its check
`check`, as one commit on the tested base: se's `main` ruleset allows no force push and no
deletion, keeps the history linear and requires `check`
([AGENTS.md "Public safety"](../AGENTS.md#public-safety)). How that commit reaches `main` is the
setting `landing` below. `work_tickets.py integrate` does all of it:

1. It merges the work branch into origin's newest integration branch on `land/<branch>` (the
   `Integrate <branch>` merge with its `Release-kind` trailer, which records its kind and moves no
   version), runs the complete suite, the output regeneration, the project checks and the public
   check.
   - A fast-forward landing then writes the one landing commit: that tree on the base, as the
     project identity in both roles, with the merge's title and message less each line that
     holds an e-mail address (a `commit_trailer` co-author line, say).
2. It pushes `land/<branch>` and opens a pull request of it into the integration branch, or reuses
   the one still open from an earlier attempt.
   - Its title is the merge's title, `Integrate <branch>: <the first sentence of the work issue's
     Goal>`, never a commit's subject. Tracker references (pub-004's forms) are dropped from it,
     with an aside such as `(PR #<n>)` that holds one, and its punctuation tidied; without a
     usable Goal, or with fewer than two words left, it is `Integrate <branch>` alone.
   - A Goal that opens with a list's lead-in gives that lead-in. A sentence of up to 200
     characters stays whole, and a long branch name lowers the 200 so the title keeps within
     GitHub's 256. A longer one ends at its last clause end (a comma, semicolon, colon or dash)
     within them before "and", "but", "so" or "while", else at its last, never with "..."
     (`work_tickets.py` `at_boundary`).
   - A clause end inside brackets, quotes or code does not count, nor the one that closes a
     leading clause such as "Where ...", "If ..." or "With ..."; without one that counts, the
     sentence ends at its last word within them. The work template warns where a Goal's first
     sentence runs past 120 characters.
   - Its description is always a link, never the report, so it fits GitHub's body limit and any
     tool argument whatever the report's size: `Refs <work issue>`, the work pull request, and the
     marker `<!-- se:field-report-in <n> -->`.
   - The check's field-report step reads that marker and checks the description of work pull
     request `<n>`, the field report, against its work issue
     ([AGENTS.md "Public safety"](../AGENTS.md#public-safety)).
3. It waits for the check `check` on the landing head, polling every 30 s for up to an hour; a
   conclusion other than success merges nothing and escalates. A repository whose host has no
   runners accepts the integrator's status instead ([Landing without CI](tests.md#landing-without-ci)).
   - The run it waits for and names may be an edit's, which took its suite's result from an
     earlier run of exactly that tree and names it ([Edits reuse the suite](tests.md#edits-reuse-the-suite)).
4. It lands that head, once origin's integration branch is still the tested base; where it
   moved while it waited, it merges nothing: integrate again.
   - A squash landing squash-merges at exactly that head with the merge's message as the commit
     title and message: `Integrate <branch>: <goal>` and the `Release-kind` trailer, and no
     ` (#<number>)` or `Co-authored-by:` line GitHub's defaults would add.
   - A fast-forward landing pushes the integration branch to exactly that head, which `check`
     passed: GitHub writes no commit and marks the pull request merged. Where origin refuses the
     push, it stops with the rule change below and never falls back to the squash merge.
5. It reads the merge back: the pull request merged at that commit, which is origin's integration
   branch, on the base it tested and with the tree its checks passed.
   - Where origin's work branch holds commits the landing did not take, pushed after step 1 read
     it, it names each and closes nothing: the worker updates its report, and `integrate` lands
     them again, as a re-integration.
6. It closes the work pull request with a line naming the landing one, closes the work issue and
   cleans up.

Steps 2 to 4 and the GitHub half of step 6 are one plan: numbered GitHub steps, each a tool of the
host's GitHub tools (the GitHub MCP server's names) with its arguments, and later steps taking what
earlier ones give (`<pull number from step 1>`). Both paths run that one plan:

- **Where `gh` is signed in**, `integrate` runs it itself through one door, the class `GitHub` in
  `work_tickets.py` (`gh api`), which the tests replace with a fake.
- **Where it is not** (Claude's cloud, where `gh` has no account), `integrate` hands it off:
  - `integrate <pull request> --pr-description <file> --issue-body <file> --branch <head branch>`,
    from what the session's GitHub tools read, does step 1, pushes `land/<branch>`, keeps what the
    read-back needs in `.se/handoff/` and prints the plan.
  - The plan: `create_pull_request` (or `update_pull_request` on the one `list_pull_requests`
    finds open), `pull_request_read` `get_check_runs` until `check` passes, and for a squash
    landing `merge_pull_request` with `merge_method` squash, the exact title and message and
    `expectedHeadSha` at the landing head; where trust is on, the
    [record](tests.md#trusted-landings)'s two steps come first;
  - the session runs those steps with its GitHub tools;
  - `integrate --read-back <branch> --landing-pull <number> --check-run <url>
    --landing-description <file>` then, for a fast-forward landing, pushes step 4, and reads
    step 5 back through `git fetch` alone (origin's integration branch one commit on the tested
    base, with the tested tree).
  - It finishes everything local of step 6 and prints its close-out plan: the work pull request's
    comment and close, and the work issue's comment, label and close.
  - Before that it checks the landing pull request's description, saved once the plan's last
    step passed: it must end in the plan's [metrics](running.md#metrics) line, or the read-back fails and
    closes nothing.
  - An integration-fix commit, one the integrator pushes onto `land/<branch>` after the hand-off
    (a lock move), is recorded with `integrate --record-fix <branch>` before the read-back.
    - Each fix commit has one parent on the tested landing and is the project identity's, author
      and committer, with no e-mail address or tracker reference in its message, as every landing
      commit is; anything else is refused and nothing is recorded.
    - It runs the complete suite, the project checks and the public check on the new head, makes
      that head the tested landing in `.se/handoff/` and prints the plan again at it: a landing
      pull request already open is reused, and the merge expects the new head.
    - The read-back then compares against that head and names the fix commits. A head that
      changed without the command reads back with another tree and is refused, naming the
      command; a fast-forward landing takes no fix commit, its fix goes to the work branch.
- A failure on the way prints the escalation as a plan too: the comment and the `escalated`
  label.

The same split holds for `refs request` and `refs apply` (the work model's
[Steps only the person approves](../src/skills/work-model/SKILL.md#steps-only-the-person-approves)):
without a signed-in `gh` each prints its comment, dispatch and run steps, and `--read-back` checks
the refs through `git ls-remote` and prints the rest.

### Hand-offs through the relay

Where `gh` reaches GitHub over REST (Claude Code's cloud: `gh api` answers though `gh auth
status` fails), no command hands off and the relay is not used: each reads and writes GitHub itself
in one call (the work model's [Without gh](../src/skills/work-model/SKILL.md#without-gh) owns the
order of the paths). The relay is the path where REST does not answer either.

Where kern serves the checkout with its GitHub component on the relay backend (a cloud session,
no token), the hand-off needs neither a retyped file nor a second run
([docs/go-core.md "GitHub in the cloud"](go-core.md#github-in-the-cloud)):

- **Reads.** `intake`, `field-report --check`, `deliver` and `integrate` read the issue, its
  comments and the pull request from kern's snapshots, which every GitHub tool answer the session
  receives fills through the PostToolUse hook ([scripts/se_relay.py](../scripts/se_relay.py)).
- **One call.** `integrate`, `refs request`, `refs apply`, `file`, `route`, `fleet-check` and
  `start` (`work_tickets.py` `STREAMED_COMMANDS`) run as one call through kern's `call.`, from the same
  command line.
  - Their component runs the command in a thread of its own; each GitHub step of its plan is one
    `github.step` request on the component's `step` port, which `wiring.toml` binds to the GitHub
    component (`RelayDoor` in `work_tickets.py`, `Stepped` in
    [scripts/se_components.py](../scripts/se_components.py)).
  - kern tells the agent each step on its hook; the session runs it with its GitHub tools, and the
    answer comes back to the command through the PostToolUse hook. `integrate` so lands, reads its
    landing back and closes out in that one call, with no `--read-back`.
  - Each step's line, `GitHub step through kern's relay: <tool>`, and every phase reach the caller
    as they are said, and the call waits as long as kern beats: a check run of many minutes fits
    ([docs/go-core.md "Progress and long calls"](go-core.md#progress-and-long-calls)).
  - The step's line names `uv run python <se>/scripts/se_relay.py next --root <checkout>`, which
    prints the tool calls the relay waits for, as the hook tells them on a prompt: the agent asks
    for the pending step whichever tool's PostToolUse ran last.
  - Each told step's note opens with its sequence number in the call, `step <n>` (`se_relay.py`
    `numbered`), under the call in the hook and in `next`; `next --step <n>` refuses a step the
    relay no longer waits for with one line naming the current one. The two reads of a landing
    pull request in a row, its merge confirmation and its read-back, each name their purpose.
  - kern refuses an answer to an old step the same way, in one line on its hook
    (kern's GitHub component, its README "The verb `step`: a write tool through the relay").
  - A relay landing (`integrate`, `rehearse`) starts with one line: run each long wait in the
    background and call `next` after each, as a told step reaches the agent only when a tool call
    ends. It reads no CI suite time past the relay, and says once that it skipped it.
  - `integrate` reads the pull request first, then runs its local guards, the field-report guard
    against the branch's merge base and the merge, and only then reads the work issue: a branch
    that cannot land fails after that one read. A checkout detached at origin's integration branch
    (a cloud session's source checkout) is moved onto the branch first, fast-forwarded there.
  - The core fails a step of the command only after ten minutes without its answer, a line or a
    beat (`StepWait`, the work model's stall rule), not after one: the wait was raised, the hook's
    beat does not count, and the command's process beats every 5 s until its answer is out.
  - A step's answer reaches the core however long the step ran: kern's bus gives a placed
    process's answer no time limit, where NATS's default of two minutes refused the answer of any
    longer step, such as a landing's suite, release and push. An answer the bus refuses all the
    same fails the step at once, naming why, instead of waiting out `StepWait`.
- **The fallback.** Without kern, on a token backend or with `SE_KERN=off`, each command keeps its
  file-based hand-off above. A call kern refuses before it says anything runs directly; one that
  fails on the way is reported and never run twice, as it writes.
  - A command that falls back says so first, on stderr, and why: `se: <command> fell back to the
    file-based hand-off: <why>`.
- **Rehearsing a relay landing.** `work_tickets.py rehearse` runs a whole landing through the
  relay on the scratch branch `--base` names, without holding the integration branch: a relay
  read, a local phase `--gap` makes slow on purpose, the push of `rehearse/` and the base's name,
  the landing plan into the base (pause search, pull request, `check`, squash merge), the read-back.
  - It refuses the integration branch, `land/…` and `rehearse/…` as its base, resets the base to
    the integration branch's tip at each start, so no rehearsal builds on an earlier one, releases
    and tags nothing and touches no issue. A detached checkout is moved as for `integrate`.
  - It runs only as one call through kern's relay, and only when someone runs it.
- **Tested** against fake sessions in the suite (`tests/test_work_ticket_issues.py`,
  `tests/test_work_tickets.py`) and against the real core: `tests/beside_se_relay.py` runs
  `fleet-check` as one call whose reads a simulated session answers on the hook, from the
  checkout's script and from a plugin's copy, then the fallback once kern stops.
  - kern's `contract/longstep_test.go` asks a relay step after a local phase longer than two
    minutes (`se.toml` `[tests.beside.kern-long-step]`), nightly and where a change touches the
    files it guards ([Test budget](tests.md#test-budget)); its fast guards run in kern's own tests.

The docs workflow publishes every landed commit, as it runs on every push to `main`; a landing
moves no version, and the release workflow tags only the commit a release lands with its new
`se.toml` version ([Project settings](#project-settings)).

```toml
[integrate]
landing = "squash"
```

`landing` is `"squash"`, built in: GitHub squash-merges the landing pull request and commits it
for the merging account (web-flow committer, the account's `users.noreply.github.com` author),
which the identity gate and a public mirror's guard pass for the account that owns the
repository.

`"fast-forward"` lands the integrator's own commit, `mb <mb>` in se, with no address in its
message: `check` ran on exactly the commit that lands. The gate and the guard turn strict with
it and refuse GitHub's own commits like any foreign identity. It needs a ruleset that takes the
integrator's push, a person step for the owner:

- In the ruleset of the integration branch (Settings, Rules, Rulesets), remove the rule "Require
  a pull request before merging"; keep "Require status checks to pass" with `check`, "Require
  linear history", "Block force pushes" and "Restrict deletions".
- Then set `landing = "fast-forward"` in `se.toml`; obs and every project se lands for set it in
  their own.

One run can land the other way without a change to `se.toml`, to try a ruleset at the cost of
one landing: `integrate <pull request> --landing fast-forward` (or `--landing squash`).

- The choice holds for that run only and is kept in the hand-off's state, so `--read-back`
  finishes the landing the way it started, whatever `se.toml` says by then.
- A refused fast-forward push leaves the integration branch, the landing pull request and its
  branch as they were and falls back to nothing; integrating again without `--landing` lands as
  `se.toml` says. The integrate comment names the mode a flagged run used.
- The identity gate and a public mirror's guard keep reading `se.toml`: a flagged landing commit
  is `mb <mb>` either way, which both pass.

### Component versions

The binary `se.toml` `[binary] release` names (SE's `se`, `components/release.toml`) has a version
of its own, which `se-release` cuts as its tag. As with the project's version, a branch states the
kind and the landing assigns the number, so branches open in parallel never claim the same one.

Its folder is its inputs: for SE `components/`, whose `go.mod` `require kern` is the kern it is
built on ([Modules](modules.md#modules)), so a branch that moves that pin changes `se`. kern releases from
its own repository.

- **The branch states the kind:** a branch that changes a component adds the header line
  `**Component kinds:** se patch` to its field report, beside its Release kind, and leaves the
  version in the `release.toml` alone; `field-report --check` refuses an unknown kind.
- **The guard follows on a work branch:** kern's release guard (`se.toml`
  `[tests.beside.release-guard]`) passes a changed component whose kind is stated, read from
  `$SE_COMPONENT_KINDS`.
  - `work_tickets.py suite` sets it from `.se/work/field-report.md`, CI from the pull request's
    description (`field-report --check --component-kinds-to`).
  - A landing and `main` set none, so there the guard refuses as before.
- **The landing assigns the number:** `integrate` writes the next version of that kind after
  `main`'s into the landing's merge, before the suite runs, for each component whose folder the
  merge changes, and names it with the tag the push to `main` cuts. A kind stated for no component is refused before anything lands.
- **A branch that still claims a number lands:** its raised version gives the kind (the highest
  part it raised), and the number becomes the next free one of that kind, said in the output.
  Where the claim conflicts with `main`'s version, the landing takes `main`'s version on top of
  the branch first and then assigns the number.
- **The pins move with the number:** every other file that pins a component's tag as `@<tag>`
  (none today) is on one list,
  `scripts/component_versions.py` `PINS`, and the landing moves each pin to the assigned tag in
  the same merge, also where the branch moved it by hand.
  - `tests/test_component_versions.py` fails where a file pins a component's current tag and is
    not on the list.

### Release tags

`release = "workflow"` hands the tags to se's release workflow, for hosts that may push branches but
not tags (Claude's cloud sessions).

- `work_tickets.py release` still raises the version and lands its commit, pushes no tag and
  names the workflow; it reads the released versions from origin's tags (`git ls-remote --tags`),
  never from local ones, so a version without its tag on origin is left for the workflow, not
  raised.
- On each push to the integration branch the workflow walks its first-parent history and tags
  every version `se.toml` carried without a tag, `v<version>` on the first commit that carried it,
  so a missed release is backfilled; a second run changes nothing.
- An existing tag never moves: where it names another commit, the run warns and leaves it. The one
  exception is the major tag `v<major>` (`v2`) of the version `se.toml` carries: each run creates
  or force-updates it to the newest release of that major, so others follow se's reusable workflows
  by major version. An older major's tag is its own releases' to push; a run never creates or moves
  it.
- Each tag is pushed on its own: a refused one fails the run with one line naming the tag, origin's
  reason and the remedy, and the others still land. The remedy is the repository's tag rulesets
  where origin's reason names a rule; otherwise it is a rerun first, as a transient refusal
  (`missing necessary objects`) passes on one.
- Without `release`, `work_tickets.py release` pushes the tag itself once its commit landed;
  another value is refused, naming the file.

A repository turns it on with `release = "workflow"`, the copy of se's `release.yml` that
`se_workflows.py write .github/workflows/release.yml` writes ([Workflows](running.md#workflows)), and a copy
of se's own [`.github/workflows/release-tag.yml`](../.github/workflows/release-tag.yml), changed only
in `branches` to name its integration branch (se's names `main`), so that worker branches run
nothing.

Other repositories run se's workflows and actions at the se pin they choose, as copies se writes at
it ([Workflows](running.md#workflows)), so a breaking change reaches them only when they move the pin.
