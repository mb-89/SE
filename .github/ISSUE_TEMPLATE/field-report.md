---
name: Field report
about: What a worker delivered and did not deliver. One per work issue, created by the worker at the end.
title: "field-report: <branch>"
labels: field-report
---
<!-- se:fleet -->

**Work issue:** #<n>  **Pull request:** #<n>  **Branch:** `<branch>`  **Result:** complete | partial
**Tested against `<integration branch>`:** `<commit>` <!-- the integration-branch commit merged last before the pull request -->
**Branch tip:** `<tip>` <!-- the branch commit this report describes; field-report --check --worktree <worktree> fills it from the branch -->
**Re-integration kind:** patch <!-- what a later integration of this branch releases once its first merge is on the integration branch: patch, minor or major -->

## User requirement (quoted back)

>

## Delivered

<!-- Follow the [worker evidence rule](../agents/worker.agent.md#procedure).
     Add one row per work-issue requirement and acceptance item; numbered items under "Changes
     after filing" are requirements, by their number, as are those under "Routing". Evidence the host cannot carry
     is replaced by the command that reproduces it: where images cannot be attached, each
     screenshot's row names the command that takes it again. -->

| Work issue item | Result | Commits | Evidence |
|---|---|---|---|

**Commit groupings:** None <!-- or, per grouping the worker's commit rule allows: the commits, the
requirements they share, and why (one function changed together, or a test-only commit) -->

**Suite time:** None <!-- where the change adds tests, the [test rules](../skills/work-model/SKILL.md#tests):
     `work_tickets.py suite` before and after, and each new test over 2 s with its reason -->

## Not delivered

<!-- The delta: each unmet requirement or acceptance item, why, and exact next steps. "None" if complete. -->

## Removed behaviour, deleted or weakened tests, and authored prose

<!-- Follow the [capability-preservation rule](../skills/work-model/SKILL.md#rules-for-all-roles).
     "None" otherwise. -->

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

<!-- Short, with the retro template's headings; propose concrete changes to agents, templates or rules. -->

- **Went well:**
- **Cost time:**
- **Proposed improvement:** <!-- target file and the change -->
