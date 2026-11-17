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

Two commands of se (its README "Work commands") run it, and a judge fills the block between them.
Not picked: an issue per finding, because only SE files issues, once it has read the report.

## Blocked by

None.

## Requirements

1. `uv run python <se>/scripts/retro.py collect <this issue> --out <draft>` writes the draft: the
   window's sizes, the rule checks, the field reports' Retro and "Not delivered" sections, and the
   previous retro's findings, scored.
2. The judge reads the draft, and `uv run python <se>/scripts/work_tickets.py metrics --since
   <window start>` on the machine the integrations ran on (README "Metrics"): its top spenders
   and overruns are findings where a command should be made cheaper. The judge fills its block's
   `findings`, `classes` and `went_well`. Each finding names its class, its home (the file it
   changes) and, where it changes a rule, trades one metric for another, the judge is unsure or it
   recurred, `controversial` with its why.
3. The judged draft lands on the integration branch as the retro doc (`docs/retro-...`), then
   `uv run python <se>/scripts/retro.py file <this issue> --draft <draft>` checks the judgment,
   posts the report as this issue's closing comment, linking the doc for the facts and the block,
   and closes it. It files no issue: SE reads the report, bundles the `work` findings into work
   issues (each naming `retro #<n> finding <k>`) and puts the `decision` findings on the owner's
   decision list.

## Acceptance

- [ ] The report is posted here, linking the retro doc, and this issue is closed.

## Verification

```sh
uv run python <se>/scripts/retro.py collect <this issue> --out <draft>
uv run python <se>/scripts/retro.py file <this issue> --draft <draft>
```
