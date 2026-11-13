---
name: Retro
about: Look back over several packages or a session to improve the agents, templates and rules systematically.
title: "retro: <scope> <yyyymmdd>"
labels: retro
---
<!-- se:fleet -->

**Scope:** <!-- the window: work issues closed since the last closed retro issue closed -->

## How this retro runs

Two commands of se (its README "Work commands"):

1. `uv run python <se>/scripts/retro.py collect <this issue> --out <draft>` writes the draft: the
   window's sizes, the rule checks, the field reports' Retro and "Not delivered" sections, and the
   previous retro's findings, scored.
2. The judge reads the draft, and `uv run python <se>/scripts/work_tickets.py metrics --since
   <window start>` on the machine the integrations ran on (README "Metrics"): its top spenders
   and overruns are findings where a command should be made cheaper. The judge fills its block's
   `findings`, `classes` and `went_well`. Each finding names its class, its home (the file it
   changes) and, where it changes a rule, trades one metric for another, the judge is unsure or it
   recurred, `controversial` with its why.
3. `uv run python <se>/scripts/retro.py file <this issue> --draft <draft>` checks the judgment,
   posts the report as this issue's closing comment and closes it. It files no issue: SE reads the
   report, bundles the `work` findings into work issues (each naming `retro #<n> finding <k>`)
   and puts the `decision` findings on the owner's decision list.
