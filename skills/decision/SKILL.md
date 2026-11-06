---
name: decision
description: 'How every decision is made, the agent''s own and those it brings to the person: one Obsidian Markdown note per decision, a Pugh matrix in a `pugh` fence with the eight-item checklist as its second tab, asked about the general mechanism rather than the single instance; its output is the answered artifact. Load it whenever you decide something that is not mechanical, or present a decision, an escalation or an open point to the person.'
---
<!-- Generated from src/skills/decision/SKILL.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

# Decision

Reader: every role, whenever it decides something that is not mechanical, and SE
when it brings a decision to the person.

Every decision is one note: a Pugh matrix with a checklist, which obs renders as a one-pager. The
agent decides its own questions with the same note it would show the person. How a decision that
the agent may not take travels up to the person is the work model's
[escalation ladder](../work-model/SKILL.md#escalation-ladder); when to ask and how a turn ends are
SE's hard rules in [catch-up](../catch-up/SKILL.md#hard-rules).

## The decision note

One Obsidian Markdown note per decision, in this order:

- **Frontmatter:** `obs.bless: pending` when a person must bless the decision; no frontmatter when
  the note is only a record of a decision the agent took itself.
- **Context:** one to three sentences: what exists, who uses it, what shows the problem. The first
  sentence names the class the case belongs to ([one level up](#one-level-up)).
- **The `pugh` fence**, the matrix and its checklist, in the input form obs defines:
  - `criteria`: each with its `name` and `weight`, weighted before any option is marked.
  - `datum`: the letter of the strongest rival; every other option is marked against it.
  - `options`: one per letter (`A`, `B`, …), each with its `name`, a `what` sentence, its `marks`
    against the datum per criterion (`1` better, `0` the same, `-1` worse), and `wins` and
    `losses`: its unique gains and losses, as text. "Keep what we have" is an option whenever
    something exists.
  - `chosen`: only where the decider prefers an option the matrix does not pick
    ([your own decisions](#your-own-decisions)).
  - `checklist`: [the checklist](#the-checklist), one entry per item, each with its `item`, a
    one-line `answer` and `pass` (`true` or `false`); an item about particular options adds
    `options`, the letters it fails.

obs shows the matrix on the first tab and the checklist on the second. A failed item that names
options becomes a weighted "Checklist" row in the matrix; a failed item about the decision as a
whole names no option, and obs raises it on the matrix tab. The aim is no failures: a failed item's
answer says what would fix it. The worked example is
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
8. **Consistency:** does it contradict a principle or an earlier decision? Which one does it
   replace?

Items 1, 2, 5 and 6 are about the decision as a whole and name no option; items 3, 4, 7 and 8 name
the letters of the options they fail.

## Your own decisions

An agent decides its own questions with the same note, without `obs.bless`. Where it prefers an
option the matrix does not pick, it sets `chosen` and states, in that option's `losses` or the
"What if" answer, the world that choice needs: the weights under which it would win. If that
world is nonsense, the preference is wrong: it takes the matrix's winner, or, where it may not
decide, sends the note up the [escalation ladder](../work-model/SKILL.md#escalation-ladder). A
matrix that matches a decision only with weird or useless weights says the decision is not the
right one.

## One level up

Before writing the note, name the class the instance belongs to and decide the general mechanism;
the instance is the example. An answer about the mechanism settles every later case of the class,
an answer about the instance only this one. Write the class in the context sentence ("This is one
case of …") and phrase every option as a rule for the class.

Worked example (5 Nov): the instance "can queries select the manifest note?" became the mechanism
"a note can mark itself ignored, like a Python underscore name; the manifest is one such note".
The options then were rules for every note (may mark itself ignored, or may not), and the manifest
was the first case they settled.

If no class exists, because the case is truly one of a kind, say so in the context and decide the
instance.

## Tasks for the person

An open point that is not a choice, something only the person can do (grant access, approve a
release, sign in), is a task, never an option in a decision. Tasks are listed separately, numbered
against their own total ("Task 1 of 2"), each with what to do, where, and what it unblocks.

## The record

The skill's output is the answered artifact (obs's `--answers` output): one decision with its
verdict, comments, overrides and vetoes. That artifact is the decision's record. Where it is kept
is not this skill's concern: whatever uses the decision handles the artifact, an issue may carry
it as an attachment, and nothing is required to commit it. A decision about a class changes that
class's rule.
