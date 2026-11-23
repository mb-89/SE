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

The retro takes six steps, the retro template's (`templates/retro.md`): field feedback, collect,
the table of what happened, the standing questions with their matrix, classes and homes, and the
person's decisions. Two commands of se (its README "Work commands") run it, and a judge fills the
steps and the block between them.
Not picked: free-form findings only, and an issue per finding, because only SE files issues, once
it has read the report.

## Blocked by

None.

## Requirements

1. **Field feedback**: before anything is read, the person says what came back from real use
   since the last retro; the judge quotes it in step 1 of the draft.
2. **Collect**: `uv run python <se>/scripts/retro.py collect <this issue> --out <draft>` writes the
   draft, the retro template's six steps: in step 2 the window's sizes, refusals, escalations,
   suite times, the rule checks, the metrics, the scripts run three or more times, the field
   reports' answers to the standing questions and what they did not deliver, the previous retro's
   findings, scored, and its classes measured again, and the breaking releases beyond the pins of
   the project's component tree (`se_modules.py breaking`).
3. **Table of what happened**: step 3 holds the timeline in chapters of about six hours and, per
   step, what went well, what it cost and whether a machine could do it; the judge fills what the
   record leaves open, reading `uv run python <se>/scripts/work_tickets.py metrics --since <window
   start>` on the machine the integrations ran on (README "Metrics"): its top spenders and overruns
   are findings where a command should be made cheaper.
4. **The standing questions**: the judge fills the matrix of the questions against the chapters
   and answers every standing question.
5. **Classes and homes**: the judge fills the block's `findings`, `classes` and `went_well`. Each
   class has one cause and one fix, its home the first that holds in the order check, refusal,
   gate, prefill, checklist line, command, setting, sentence; each finding names its class, its
   home (the file it changes) and, where it changes a rule, trades one metric for another, the
   judge is unsure or it recurred, `controversial` with its why.
6. **The person decides** every open class in the session; the judge records the decisions in step
   6. The judged draft lands on the integration branch as the retro doc (`docs/retro-...`), then
   `uv run python <se>/scripts/retro.py file <this issue> --draft <draft>` checks the judgment,
   posts the report as this issue's closing comment, linking the doc for the facts and the block,
   and closes it. It files no issue: SE reads the report, bundles the `work` findings into work
   issues (each naming `retro #<n> finding <k>`) and puts the `decision` findings on the owner's
   decision list.

## Acceptance

- [ ] The report, the six steps, is posted here, linking the retro doc, and this issue is closed.

## Verification

```sh
uv run python <se>/scripts/retro.py collect <this issue> --out <draft>
uv run python <se>/scripts/retro.py file <this issue> --draft <draft>
```
