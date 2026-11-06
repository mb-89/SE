---
name: decision
description: 'How every decision is made, the agent''s own and those it brings to the person: one Obsidian Markdown note per decision, a Pugh matrix in obs''s `pugh` fence with the eight-item checklist, asked about the general mechanism rather than the single instance; its output is the answered artifact. Load it whenever you decide something that is not mechanical, or present a decision, an escalation or an open point to the person.'
---

# Decision

Reader: every role, whenever it decides something that is not mechanical, and SE
when it brings a decision to the person.

Every decision is one note: a Pugh matrix with a checklist, which obs renders as a one-pager. The
agent decides its own questions with the same note it would show the person. How a decision that
the agent may not take travels up to the person is the work model's
[escalation ladder](../work-model/SKILL.md#escalation-ladder); when to ask and how a turn ends are
SE's hard rules in [catch-up](../catch-up/SKILL.md#hard-rules).

## The decision note

One Obsidian Markdown note per decision. Its reader must understand the problem before they see
any option, so every note answers, in this order: what is the situation today, what is wrong with
it, and which solutions there are.

- **Frontmatter:** `obs: {bless: pending}` when a person must bless the decision; no frontmatter
  when the note is only a record of a decision the agent took itself.
- **The heading:** `# <the decision>`, the question in a few words.
- **`## Current situation`:** what exists today and who uses it, in plain words. The first
  sentence names the class the case belongs to ([one level up](#one-level-up)).
- **`## The problem`:** what is wrong with it, and what shows it: a failure, a measurement, the
  person's words.
- **The `pugh` fence**, the matrix and its checklist. Its fields, marks and letters are obs's
  contract, owned by obs's capability note
  [pugh-decisions](https://github.com/mb-89/obs/blob/main/spec/capabilities/pugh-decisions.md) and
  its input model's
  [Pugh decision figures](https://github.com/mb-89/obs/blob/main/spec/design_input/input-model.md#pugh-decision-figures).
  SE asks of it:
  - The criteria are weighted before any option is marked.
  - The datum is the strongest rival; every other option is marked against it. "Keep what we have"
    is an option whenever something exists.
  - Every option says what it is and its own wins and losses.
  - Every option carries `short`, its short name: one word where possible, at most five. The
    field is obs's, owned by
    [pugh-decisions](https://github.com/mb-89/obs/blob/main/spec/capabilities/pugh-decisions.md).
  - `chosen` only where the decider prefers an option the matrix does not pick
    ([your own decisions](#your-own-decisions)).
  - The checklist is [the checklist](#the-checklist), one entry per item; an item about particular
    options names the letters of those it fails.

Nothing else goes before the fence: its options are the list of solutions the reader expands.
Any longer material goes in `##` sections after it, which obs shows as tabs. `<se>/scripts/deck.py
build` refuses a decision note without both sections before its fence.

The aim is no failed item: a failed item's answer says what would fix it. The worked example is
[the decision deck](references/decision-deck.md).

## The checklist

The decider answers every item before it decides or asks:

1. **Class or case:** is this one case of a general mechanism? If so, decide the mechanism.
2. **Is the problem real:** what shows it exists: a failure, a measurement, the person's words?
3. **Keep what we have:** is "keep what we have" an option, and is the datum the strongest rival?
4. **A named loser:** each losing option with the reason it lost.
5. **Fair criteria:** nothing counted twice, and weights set before the options were marked.
6. **What if:** for each other option, the weights under which it wins, with no bound. Is that a
   world that could happen, or nonsense? A world that could happen gets a sign to watch (a
   tripwire) and a fallback.
7. **Undo cost:** easy to reverse, or one-way? A one-way decision goes to the person.
8. **Consistency:** does it contradict a [principle](../work-model/references/principles.md) or an
   earlier decision? Which one does it replace?

Items 1, 2, 5 and 6 are about the decision as a whole and name no option; items 3, 4, 7 and 8 name
the letters of the options they fail.

## Your own decisions

An agent decides its own questions with the same note, without the bless request. Where it prefers an
option the matrix does not pick, it sets `chosen` and states, in that option's `losses` or the
"What if" answer, the world that choice needs: the weights under which it would win.

If that world is nonsense, the preference is wrong: it takes the matrix's winner, or, where it may
not decide, sends the note up the [escalation ladder](../work-model/SKILL.md#escalation-ladder). A
matrix that matches a decision only with weird or useless weights says the decision is not the
right one.

## One level up

Before writing the note, name the class the instance belongs to and decide the general mechanism;
the instance is the example. An answer about the mechanism settles every later case of the class,
an answer about the instance only this one. Write the class in the first sentence of
`## Current situation` ("This is one case of …") and phrase every option as a rule for the class.

Worked example (5 Nov): the instance "can queries select the manifest note?" became the mechanism
"a note can mark itself ignored, like a Python underscore name; the manifest is one such note".
The options then were rules for every note (may mark itself ignored, or may not), and the manifest
was the first case they settled.

If no class exists, because the case is truly one of a kind, say so in `## Current situation`
and decide the instance.

## Tasks for the person

An open point that is not a choice, something only the person can do (grant access, approve a
release, sign in), is a task, never an option in a decision. Tasks are listed separately, numbered
against their own total ("Task 1 of 2"), each with what to do, where, and what it unblocks.

## Bringing decisions to the person

The decisions the person must bless go to them as one deck, in one turn. `<se>/scripts/deck.py` builds,
serves and reads it; its `--help` owns what each subcommand does.

A deck may also carry record chapters, notes without a bless request and without a `pugh` fence, such as
what was decided without the person and their [tasks](#tasks-for-the-person), beside at least one decision.

1. Write the decision notes and their manifest into a scratch directory `<notes>`, then run
   `uv run python <se>/scripts/deck.py build <notes> --destination <deck>.html`.
2. Hand the deck to the person where they are, and wait for their answers:
   - **The Claude app** (cloud and mobile): publish `<deck>.html` with the Artifact tool and
     `capabilities: {artifact: {}}`, and send the person its link. Their Send publishes
     `answers.json` into the artifact, which wakes this session; read it with the Artifact
     tool's `read` and `path: "answers.json"`.
   - **Claude Code and Copilot** (local): run
     `uv run python <se>/scripts/deck.py serve <deck>.html --wait --timeout <seconds>` and send the
     person the URL it prints first; it ends with their answers.
3. Run `uv run python <se>/scripts/deck.py answers <answers.json>` and act on what it prints; add
   `--record <notes> --destination <record>.html` for [the record](#the-record).

## The record

The skill's output is the answered artifact (obs's `--answers` output): one decision with its
verdict, comments, overrides and vetoes. That artifact is the decision's record. A decision about
a class changes that class's rule.

Where it is kept is not this skill's concern: whatever uses the decision handles the artifact, an
issue may carry it as an attachment, and nothing is required to commit it.
