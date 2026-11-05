---
name: Field report
about: What a worker delivered and did not deliver. One per work issue, created by the worker at the end.
title: "field-report: <branch>"
labels: field-report
---

**Work issue:** #<n>  **Pull request:** #<n>  **Branch:** `<branch>`  **Result:** complete | partial
**Tested against `<integration branch>`:** `<commit>` <!-- the integration-branch commit merged last before the pull request -->

## User requirement (quoted back)

>

## Delivered

<!-- Follow the [worker evidence rule](../agents/worker.agent.md#procedure).
     Add one row per work-issue requirement and acceptance item. Evidence the host cannot carry
     is replaced by the command that reproduces it: where images cannot be attached, each
     screenshot's row names the command that takes it again. -->

| Work issue item | Result | Commits | Evidence |
|---|---|---|---|

**Commit groupings:** None <!-- or, per grouping the worker's commit rule allows: the commits, the
requirements they share, and why (one function changed together, or a test-only commit) -->

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

<!-- Every decision taken without the user (disagree and commit). -->

| Decision | Alternatives | Rationale | Confidence |
|---|---|---|---|

## Spec gaps

<!-- Where the design notes were silent or contradictory, and what was recorded where. -->

## Tickets for other repositories

<!-- One block per ticket, ready for the dispatcher to file as a work issue there:
     ### <repo>: <title> / Goal / Requirements / Acceptance. Generic findings from an
     application become framework tickets and must not name the application. See the
     [work model](../skills/work-model/SKILL.md#roles-and-flow) for the entry granularity and
     source-file requirement. "None" otherwise. -->

## Retro

<!-- Short, with the retro template's headings; propose concrete changes to agents, templates or rules. -->

- **Went well:**
- **Cost time:**
- **Proposed improvement:** <!-- target file and the change -->
