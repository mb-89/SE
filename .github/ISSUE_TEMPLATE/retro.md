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

The retro takes six steps, the retro template's (`templates/retro.md`): collected field feedback,
collect, the table of what happened, the standing questions with their matrix, classes and homes,
and the person's decisions. The judge does not ask for or wait on field feedback; it uses the
record available and writes `None.` when no separate input exists. Two commands of se (its README
"Work commands") run it, and a judge fills the steps and the block between them.
Not picked: free-form findings only, and an issue per finding, because only SE files issues, once
it has read the report.

## Blocked by

None.

## Requirements

1. **Field feedback**: the judge uses field feedback already available in the record and does not
   ask for or wait on more; step 1 says `None.` when no separate input exists.
2. **Collect**: `uv run python <se>/scripts/retro.py collect <this issue> --out <draft>` writes the
   draft, the retro template's six steps: in step 2 the window's sizes, refusals, escalations,
   suite times, the rule checks, the metrics, the scripts run three or more times, the field
   reports' answers to the standing questions and what they did not deliver, the previous retro's
   findings, scored, and its classes measured again, and the breaking releases beyond the pins of
   the project's component tree (`se_modules.py breaking`).
3. **Table of what happened**: step 3 holds the timeline in chapters of about six hours and, per
   step, what went well, what it cost and whether a machine could do it; the judge fills what the
   record leaves open, reading `uv run python <se>/scripts/work_tickets.py metrics --since <window
   start>` on the machine the integrations ran on (docs/running.md "Metrics"): its top spenders and overruns
   are findings where a command should be made cheaper.
4. **The standing questions**: the judge fills the matrix of the questions against the chapters
   and answers every standing question.
5. **Classes and homes**: the judge fills the block's `findings`, `classes` and `went_well`: each
   class has one cause and one fix, its home the first that holds in the order check, refusal,
   gate, prefill, checklist line, command, setting, sentence, and each finding names its class, its
   home (the file it changes) and, where it changes a rule, trades one metric for another, the
   judge is unsure or it recurred, `controversial` with its why.
6. **The person decides** every open class in the session; the judge records the decisions in step
   6, the judged draft lands on the integration branch as the retro doc (`docs/retro-...`), and
   `uv run python <se>/scripts/retro.py file <this issue> --draft <draft>` checks the judgment
   and posts the report, linking the doc for the facts and the block. The retro stays open in
   report state: SE files each accepted `work` finding with
   `work_tickets.py file --finding <retro>:<finding>` (the work issue names
   `retro #<n> finding <k>`) and records declined or merged findings with `retro.py outcome`.
   Once every finding has an outcome, the retro becomes done and closes.

## Acceptance

- [ ] The report, the six steps, is posted here, linking the retro doc; the issue stays open until
      each finding has an outcome, then closes.

## Verification

```sh
uv run python <se>/scripts/retro.py collect <this issue> --out <draft>
uv run python <se>/scripts/retro.py file <this issue> --draft <draft>
```
