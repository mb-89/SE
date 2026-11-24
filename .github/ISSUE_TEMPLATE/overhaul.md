---
name: Overhaul
about: Ask, rarely, whether the design is still right; SE starts it with overhaul.py new.
title: "overhaul-<yyyymmdd>"
labels: discovery
---
<!-- se:fleet -->

## Situation

The rule book, the code and the retros change with every landing, and each retro judges only its
own window.

## Problem

So nobody asks whether the design as a whole still holds.

## Goal

Is the design still right? This overhaul judges se against every rule of its rule book, the
retros' trend since the last overhaul and the code's pruning facts, and posts one report here.

## Approach

Two commands of se (its README "Work commands") run it, and a judge fills the block between them.
Not picked: an issue per finding, because only SE files issues, once it has read the report.

## Package kind

Discovery: the overhaul writes a report, not code, and files no issue.

## Blocked by

None.

## Requirements

1. `uv run python <se>/scripts/overhaul.py read <this issue> --out <draft>` writes the draft:
   every rule with what checks it, the retros since the last overhaul, the previous overhaul's
   findings with the state of the issues that took them, and the pruning facts.
2. The judge reads the draft, then se itself, answers every standing question
   (`templates/standing-questions.md`, the retro's and the field report's too) and every question
   of the overhaul's own (`templates/overhaul-questions.md`), what the outside world does and what
   we can learn from it among them, and fills its block: a verdict per rule, every `looked_at`
   part, the `findings` (each naming its rule, its place and its body) and `went_well`.
3. `uv run python <se>/scripts/overhaul.py file <this issue> --draft <draft>` checks the
   judgment and the answers, posts the report as this issue's closing comment and closes it, filing no issue:
   SE reads the report, bundles the `work` findings into work issues (each naming
   `overhaul #<n> finding <k>`) and puts the `decision` findings, every rule change among them,
   on the owner's decision list.

## Acceptance

- [ ] The report is posted here and this issue is closed.

## Verification

```sh
uv run python <se>/scripts/overhaul.py read <this issue> --out <draft>
uv run python <se>/scripts/overhaul.py file <this issue> --draft <draft>
```
