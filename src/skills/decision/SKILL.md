---
name: decision
description: 'How every decision is made, the agent''s own and those it brings to the person: one Obsidian Markdown note per decision that says how others solve its problem, a Pugh matrix in obs''s `pugh` fence with the nine-item checklist, asked about the general mechanism rather than the single instance; its output is the answered artifact. Load it whenever you decide something that is not mechanical, or present a decision, an escalation or an open point to the person.'
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
it, how others solve it, and which solutions there are.

- **Frontmatter:** `obs: {bless: pending}` when a person must bless the decision; no frontmatter
  when the note is only a record of a decision the agent took itself.
- **The heading:** `# <the decision>`, the question in a few words.
- **`## Current situation`:** what exists today and who uses it, in plain words. The first
  sentence names the class the case belongs to ([one level up](#one-level-up)).
- **`## The problem`:** what is wrong with it, and what shows it: a failure, a measurement, the
  person's words.
- **`## What others do`:** how the rest of the world solves the same problem: at least two outside
  tools, products or conventions, each with what it does and a concrete example the person can
  follow. The person asks for it in every design decision: "Again, check the outside world. Is
  there something similar like this already present? Can we reuse something?"
  - The section is factual. It names a tool only as an example, never as something the project
    uses; where the project does not use it, nothing implies that it does.
  - No option refers to the outside tools or says which of them it borrows from, the recommended
    one least of all: each option says what it is in its own words.
- **The `pugh` fence**, the matrix and its checklist. Its fields, marks and letters are obs's
  contract, owned by obs's capability note `spec/capabilities/pugh-decisions.md` and its input
  model's section "Pugh decision figures" in `spec/design_input/input-model.md`, both in obs, the
  repository beside SE's (`.se/modules/obs/` in a checkout that pins it). SE asks of it:
  - `context` and `concern`: the situation and the concern the decision answers, for its
    one-sentence summary, the verdict.
    - The verdict names only the chosen option: "In the context of …, facing …, we decided for
      A · Deck, to achieve …, accepting …", never the options left out, since deciding for one
      already decides against the rest.
    - obs's Pugh figure writes it; until obs follows, it still adds "and against" the others.
  - The criteria are weighted before any option is marked.
  - Effort to build or move is a criterion only where it is exceptional; ordinary work to build
    the better system is no criterion
    ([dec-006](../work-model/references/rules.md#dec-006-right-before-cheap)).
  - "Keep what we have" is an option whenever something exists. The datum is what exists today
    wherever something exists, never an option not yet built; every other option is marked
    against it. Only where nothing exists is the datum the strongest rival
    ([dec-003](../work-model/references/rules.md#dec-003-keep-what-we-have)).
  - Every option says what it is and its own wins and losses.
  - No option's text names another option, by its key, short name or letter: each says only what
    it is, and the matrix alone compares them. The person: "Don't mention the ones that we didn't
    decide for. We only mention the ones we decide for."
  - Every option carries `success`, its success criterion
    ([dec-010](../work-model/references/rules.md#dec-010-a-success-criterion)).
  - Every mark carries its reason, `{mark, because}`; the datum's marks, against itself, need none.
  - Every option carries `short`, its short name: one word where possible, at most five. The
    field is obs's, owned by obs's `spec/capabilities/pugh-decisions.md`.
  - `chosen` only where the decider prefers an option the matrix does not pick
    ([your own decisions](#your-own-decisions)).
  - The checklist is [the checklist](#the-checklist), one entry per item; an item about particular
    options names the letters of those it fails.

Nothing else goes before the fence: its options are the list of solutions the reader expands.
Any longer material goes in `##` sections after it, which obs shows as tabs.

`<se>/scripts/deck.py build` refuses a decision note without the three sections, in order, before
its fence, so the deck shows them above the options. It warns of an option without `success`, a
mark without `because`, or an option whose text names another's key or short name.

The aim is no failed item: a failed item's answer says what would fix it. The worked example is
[the decision deck](references/decision-deck.md).

## Diagrams

Wherever something can be shown with a diagram (how parts fit together, what flows where, what is
generated from what), show it as one, never as text art (boxes and arrows drawn with characters).
The person: "If you can do something with a diagram, do it with a diagram."

- In a decision note, as obs's diagram figure, a `mermaid` fence (obs's capability note
  `spec/capabilities/mermaid.md`), so the deck draws it. The worked example's current situation
  carries one.
- In a chat answer, as a rendered image the host shows, such as that diagram drawn as SVG or PNG.

## The checklist

The decider answers every item before it decides or asks; each is a rule of the
[rule book](../work-model/references/rules.md#dec-decisions):

1. **Class or case:** [dec-001](../work-model/references/rules.md#dec-001-class-or-case)
2. **Is the problem real:** [dec-002](../work-model/references/rules.md#dec-002-is-the-problem-real);
   its answer also names the outside solutions of `## What others do`.
3. **Keep what we have:** [dec-003](../work-model/references/rules.md#dec-003-keep-what-we-have)
4. **A named loser:** [dec-004](../work-model/references/rules.md#dec-004-a-named-loser)
5. **Fair criteria:** [dec-005](../work-model/references/rules.md#dec-005-fair-criteria)
6. **Right before cheap:** [dec-006](../work-model/references/rules.md#dec-006-right-before-cheap)
7. **What if:** [dec-007](../work-model/references/rules.md#dec-007-what-if)
8. **Undo cost:** [dec-008](../work-model/references/rules.md#dec-008-undo-cost)
9. **Consistency:** [dec-009](../work-model/references/rules.md#dec-009-consistency)

Items 1, 2, 5 and 7 are about the decision as a whole and name no option; items 3, 4, 6, 8 and 9
name the letters of the options they fail.

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

An open point that is not a choice, something only the person can do (grant access, change a
setting, sign in), is a task, never an option in a decision. Tasks are listed separately, numbered
against their own total ("Task 1 of 2"), each with what to do, where, and what it unblocks.

## Bringing decisions to the person

The decisions the person must bless go to them as one deck, in one turn. `<se>/scripts/deck.py` builds,
serves and reads it; its `--help` owns what each subcommand does.

A deck may also carry record chapters, notes without a bless request and without a `pugh` fence, such as
what was decided without the person and their [tasks](#tasks-for-the-person), beside at least one decision.

1. Write the decision notes and their manifest into a scratch directory `<notes>`, then run
   `uv run python <se>/scripts/deck.py build <notes> --destination <deck>.html --host <host>`.
   - `<host>` is the host the answers go back to: `claude-app`, `claude-code` or `copilot`
     (`local` for any other).
   - Its chapters and their versions are in `<deck>.document.json` beside it, the obs Document it
     was built from; never decode the built page for them.
2. Hand the deck to the person where they are, and end your turn; their answers arrive later, and
   nothing waits on them:
   - **The Claude app** (cloud and mobile), `--host claude-app`: publish `<deck>.html` with the
     Artifact tool and the capabilities `deck.py --help` names, `artifact` and full-form
     `comments`, and send the person its link.
     - The publish's result says whether this session watches the artifact; where it does not,
       watch it with the `ArtifactComments` tool before sending the link, or no session can take
       the person's message (the deck tells them "No Claude session is listening").
     - Their Send sends the answers to Claude as a comment first, then saves `answers.json` into
       the artifact; either wakes this session.
     - Read `answers.json` with the Artifact tool's `read` and `path: "answers.json"`. Where it is
       missing or older than the comment, take the payload from the comment's `answers.json:` part,
       or from its lines where the payload did not fit.
   - **Claude Code and Copilot** (local), `--host claude-code` or `--host copilot`: run
     `uv run python <se>/scripts/deck.py serve <deck>.html` in the background (under Copilot, a
     background terminal) and send the person the URL it prints first.
     - Their Send posts the answers to that server, which writes `answers.json` beside
       `<deck>.html`; the deck tells them it was sent to Claude Code or to Copilot.
     - Read that file on your next turn, when the person says they sent; stop the server once it
       is read.
3. Run `uv run python <se>/scripts/deck.py answers <answers.json>` and act on what it prints; add
   `--record <notes> --destination <record>.html` for [the record](#the-record).
   - Any verdict may carry a comment, Bless included: act on the comment too.
   - A decision that reads `comment` has the person's comment and no verdict: it is still open, so
     answer the comment and ask again.
4. A verdict the person gives in the chat for a decision of an open deck is that decision's answer,
   as if they had sent it from the deck; they need not send it there as well.
   - SE records it as it records a deck answer: that decision's entry in the answers payload,
     with the verdict and the person's chat words as its comment, then step 3.
   - A chat message that names no verdict, or no decision it answers, is a comment: answer it.

## The record

The skill's output is the answered artifact (obs's `--answers` output): one decision with its
verdict, comments, overrides and vetoes. That artifact is the decision's record. A decision about
a class changes that class's rule.

Where it is kept is not this skill's concern: whatever uses the decision handles the artifact, an
issue may carry it as an attachment, and nothing is required to commit it.
