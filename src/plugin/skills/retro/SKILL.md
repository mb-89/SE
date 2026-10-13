---
name: retro
description: Start an SE retro, or, as the box that took one, collect its window, judge it, and file its report. The work skill hands an issue labelled se-retro to it.
---

# Retro: do SE's rules hold across what landed?

The rules are [spec/retro.md](../../../../spec/retro.md). `se` is
`./src/plugin/bin/se`, called exactly as `./src/plugin/bin/se retro …`, one
command per call.

## Starting one, with a person

Ask the person for their field feedback: what they saw go wrong or well since
the last retro. Then run
`./src/plugin/bin/se retro new --field "<their words>"`, or
`./src/plugin/bin/se retro new --no-field` if they have none or say skip.
Tell them the issue it created. A box takes it from there.

## The box that took retro N

1. `./src/plugin/bin/se retro collect <n>`. It writes the draft to
   `../retro-<n>.md`. If it says it wrote the report already posted on the
   issue, the owner has decided: read their comments on the issue, apply what
   they moved between controversial and not to `findings` in the draft's
   block, and go to 4.
2. Read the draft: the issue's field feedback, the rule checks, the counts,
   the metrics against the previous retros, the previous retro's score, the
   scripts and the matrix of landing answers.
3. Judge, and write it into the draft's block (the YAML under
   `<!-- se:retro-yaml -->`); leave the facts as they are.
   - `findings`: what went wrong, blamelessly: the rule, tool or prompt that
     produced it, not who. Each with a `title` (the fix, as an issue title), a
     `class`, a `body` (what happened, with issue and PR numbers, and the fix),
     a `home` (`check`, `refusal`, `gate`, `field`, `command`, `guidance` or `removal`:
     the cheapest durable one, guidance last), and `controversial` with its
     `why` when it changes a principle, trades one metric against another,
     you are not sure, or it recurred after an earlier fix. Name the rule
     `check` or the `metric` it should move, so the next retro can score it.
     A finding about the retro itself (its questions, checks, metrics or this
     skill) gets `retro: true`.
   - `classes`: group the findings; three of a kind is a property of the
     machinery. Each a `name` and its cheapest durable `fix`.
   - `went_well`: what worked and should stay.
4. `./src/plugin/bin/se retro report <n>`. If it refuses, fix what it names
   and run it again. It either posts the report and gives the retro to the
   owner, or creates the issues and closes the retro. Either way, end: there
   is no PR to land.
