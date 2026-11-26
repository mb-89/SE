<!-- se:field-report -->
<!-- The worker's field report, the description of its pull request: one per work issue, written by
     the worker at delivery between the se:field-report markers, which the integration reads. -->

**Work issue:** #<n>  **Branch:** `<branch>`  **Result:** complete | partial
**Tested against `<integration branch>`:** `<commit>` <!-- the integration-branch commit merged last before the pull request -->
**Branch tip:** `<tip>` <!-- the branch commit this report describes; field-report --check --worktree <worktree> fills it from the branch -->
**Release kind:** <kind> — <reason> <!-- patch, minor or major and a one-line reason: what changed decides it, as the [work model's Release kind](../skills/work-model/SKILL.md#release-kind) says, never the branch name; field-report --draft only proposes one -->
<!-- A branch that changes the se binary (components/, its require kern among them) adds the line "**Component kinds:** se patch" here, one kind per component, and leaves the version in its release.toml alone: the landing assigns it (docs/settings.md "Component versions"). -->
**Re-integration kind:** patch <!-- what a later integration of this branch releases once its first merge is on the integration branch: patch, minor or major -->

## User requirement (quoted back)

>

## Delivered

<!-- Follow the [worker evidence rule](../agents/worker.md#procedure).
     Add one row per work-issue requirement and acceptance item; numbered items under "Changes
     after filing" are requirements, by their number, as are those under "Routing". Evidence
     the host cannot carry is replaced by the command that reproduces it: where images cannot
     be attached, each screenshot's row names the command that takes it again. A new test over
     2 s in the focused run gets its own row, with its reason. -->

| Work issue item | Result | Commits | Evidence |
|---|---|---|---|

**Commit groupings:** None <!-- or, per grouping the worker's commit rule allows: the commits, the
requirements they share, and why (one function changed together, or a test-only commit) -->

## Not delivered

<!-- The delta: each unmet requirement or acceptance item, why, and exact next steps. "None" if complete.
     Any partial keeps the work issue open at this landing: a planned split, which names each piece
     left as a bullet "- **Piece <n>, <what>:** ...", until its last piece; any other until SE
     re-scopes it. -->

## Removed behaviour, deleted or weakened tests, and authored prose

<!-- Follow the [capability-preservation rule](../skills/work-model/SKILL.md#rules-for-all-roles).
     Each removed or renamed public item and each newly required field gets its own line
     "**Breaking:** <item>", which makes the Release kind major (minor below 1.0.0)
     ([work model](../skills/work-model/SKILL.md#release-kind)). "None" otherwise.
     Name each deleted or renamed test; a folder moved with its tests to another repository is one
     line "Moved: <folder> to <repository> at <commit>" (with "as <path>" below its root there),
     checked at that commit ([work model](../skills/work-model/SKILL.md#tests)). -->

## Review responses

<!-- On a re-delivered pull request, the field report answers every review point: done with
     evidence, or not done with a reason. "None" for the initial delivery. -->

| Review point | Result | Evidence or reason |
|---|---|---|

## Decisions

<!-- Every decision taken without the user (disagree and commit). "None" otherwise. -->

| Decision | Alternatives | Rationale | Confidence |
|---|---|---|---|

## Spec gaps

<!-- Where the design notes were silent or contradictory, and what was recorded where. -->

## Tickets for other repositories

<!-- One block per ticket, ready for SE to file as a work issue there:
     ### <repo>: <title> / Goal / Requirements / Acceptance. Generic findings from an
     application become framework tickets and must not name the application. See the
     [work model](../skills/work-model/SKILL.md#roles-and-flow) for the entry granularity and
     source-file requirement. "None" otherwise. -->

## Retro

<!-- The standing questions, asked of the agent that did the work: one "### <question>" each, as
     templates/standing-questions.md asks them (the retro and the overhaul ask the same); answer
     each for this piece of work, "None" where it does not apply, and name target files and changes.
     Under "What goes badly, each with its moment in the log?", record all friction, including
     resolved friction, with evidence, impact and outcome; follow the shared work model's
     "Friction and observation". "None" means there truly was none.
     The last three, the tooling questions, every role answers in every report, in any project, and
     "None" does not answer them: what took the longest and why; what tool you wished was present
     (in SE, kern, the project, or outside our tooling); and the tooling starfish, removals included.
     field-report --draft writes them in; the check refuses a report that leaves one out or empty,
     naming it. -->

<!-- se:standing-questions -->

<!-- se:field-report:end -->
