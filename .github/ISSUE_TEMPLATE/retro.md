---
name: Retro
about: Look back over several packages or a session to improve the agents, templates and rules systematically.
title: "retro-<scope>-<yyyymmdd>"
labels: retro
---
<!-- se:fleet -->

**Scope:** <!-- the window: work issues closed since the last closed retro issue closed -->

## Situation

Each package ends in its own field report, so what went wrong in one is seen only there.

## Problem

What went wrong in one package comes back in the next.

## Goal

The agents, templates and rules improve from what the window's packages show.

## Approach

The retro takes five steps from the retro template (`templates/retro.md`): collect, the table of
what happened, the standing questions with their matrix and answers, classes and homes, and the
person's decisions. The retro agent collects and judges the record, then builds a deck ending with
`Anything else?` and the sole default answer `Nothing else`. Two commands of se (its README "Work
commands") run it, and a judge fills the steps and the block between them.
Not picked: free-form findings only, and an issue per finding, because only SE files issues, once
it has read the report.

## Blocked by

None.

## Requirements

1. **Collect**: `uv run python <se>/scripts/retro.py collect <this issue> --out <draft>` writes the
   window's counts, rule checks, metrics, repeated scripts, field-report answers, previous findings
   and classes, and breaking releases beyond the project's component pins.
2. **Table of what happened**: the draft groups the timeline into chapters of about six hours and
   records what went well, what it cost and whether a machine could do each step.
3. **The standing questions**: the judge fills the matrix of questions against chapters and answers
   every standing question.
4. **Classes and homes**: the judge fills `findings`, `classes` and `went_well`, giving each class
   one cause, one fix and its first applicable home, and each finding its class, changed file and
   controversy reason where applicable.
5. **Anything else**: the retro deck ends with a bless chapter titled `Anything else?`, offering
   only the selectable default `Nothing else`, which the person may reject with a comment.
6. **Report**: the judge commits the draft on the integration branch as `docs/retro-...` and runs
   `uv run python <se>/scripts/retro.py file <this issue> --draft <draft>` to post the report with
   a link to the document.
7. **Outcomes**: SE records each accepted `work` finding with
   `work_tickets.py file --finding <retro>:<finding>` and each declined or merged finding with
   `retro.py outcome`.
8. **Close**: the retro closes only after every finding has an outcome.

## Acceptance

- [ ] The report, the five steps, is posted here, linking the retro doc; the issue stays open until
      each finding has an outcome, then closes.

## Verification

```sh
uv run python <se>/scripts/retro.py collect <this issue> --out <draft>
uv run python <se>/scripts/retro.py file <this issue> --draft <draft>
```
