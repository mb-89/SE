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
   judgment and the answers and posts the report here, filing no issue; the report is its
   blessing, so this issue holds no filing from then on.
4. SE gives each finding an outcome, a `decision` finding after the owner decides: a work issue
   with `work_tickets.py file --finding <this issue>:<k>`, naming `overhaul #<n> finding <k>`, or
   declined or merged with `retro.py outcome`; the last outcome closes this issue.

## Acceptance

- [ ] The report is posted here, and every finding has an outcome, which closes this issue.

## Verification

```sh
uv run python <se>/scripts/overhaul.py read <this issue> --out <draft>
uv run python <se>/scripts/overhaul.py file <this issue> --draft <draft>
```
