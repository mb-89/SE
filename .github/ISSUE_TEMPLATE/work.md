---
name: Work issue (design input)
about: One package for one worker. Title = branch name. Carries only the task; generic rules live in .github/agents/worker.agent.md.
title: "<type>/<topic>-<yyyymmdd>"
labels: work
---

## Goal

<!-- The user-visible outcome and why it matters, in two to four sentences. -->

## Reproduction

<!-- For an issue that comes from a field report's finding: link the report and quote the
     reproduction command it ran and that command's output, verbatim. Delete this section
     otherwise. -->

## Package kind

<!-- Standard packages change code and verify it with focused tests. For read-only research that
produces findings, proposed tickets or probe results, apply the `discovery` label. Discovery
packages record evidence instead of test-command wording. -->

## Blocked by

<!-- Issues that must be closed first, linked as native "blocked by" dependencies by the dispatcher
     (scripts/work_tickets.py block <this> --by <n>). Blocked state is computed from those links,
     never a label; nobody edits labels by hand. Label `ready` = approved; startable = ready and no
     open blockers. The worktree and branch are created when work starts, from the newest main.
     "None" otherwise. -->

None

## User requirement (verbatim)

<!-- Quote the user's words exactly; the field report quotes them back. -->

>

## Design owner

<!-- The design notes that own the decided behaviour: file and section, as the project's AGENTS.md
     names them. The worker reads them; the issue does not copy them. -->

## Requirements

<!-- Numbered, checkable, in the order to do them; commits follow the
     [worker's procedure](../agents/worker.agent.md#procedure). Keep a package worker-sized:
     one reviewable change, roughly one to five requirements. Split larger work
     (e.g. a scheduler with several commands) into separate issues linked by "Blocked by",
     each owning its part of shared files. Capabilities to remove must be named explicitly with
     the user's decision; otherwise all existing capabilities are preserved. A requirement found
     through an error message names the outcome ("the rebuild validates"), not the first symptom
     ("add key X"). A requirement that says what "adapters" or "consumers" must do names which
     ones are in scope, for example whether an interim implementation counts. -->

1.

## File ownership

<!-- Only when parallel packages share files: name the owner of each shared root file
     (pyproject.toml, lock files and CI config), what this package owns, what it must not edit,
     and which shared file it edits last after merging main. Delete this section otherwise. -->

## Acceptance

<!-- Checkable items with the evidence expected (test name, command, measurement). -->

- [ ]

## Verification

<!-- Focused tests and real commands to run; the integrator runs the complete suite. -->

```powershell
```
