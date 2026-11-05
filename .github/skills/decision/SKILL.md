---
name: decision
description: 'How the dispatcher brings the person a decision or a task: one per message, numbered against the open total, a short context, one option table with the recommendation marked, asked about the general mechanism rather than the single instance, and the answer recorded where it takes effect. Load it whenever you present a decision, an escalation or an open point to the person.'
---

# Decision

This skill owns how a decision reaches the person and how its answer is kept. When to ask and
how a turn ends are the dispatcher's hard rules in [catch-up](../catch-up/SKILL.md#hard-rules);
the shared rules of all roles are the [work model](../work-model/SKILL.md).

## One decision per message

- **One per message.** Each message carries exactly one decision, numbered against the open total:
  "Decision 2 of 3". A decision that comes up meanwhile joins the queue and raises the total.
- **Context in one to three sentences**: what exists, who uses it, what was found in code or
  history. Name the decision so the person can tell it from every other open point.
- **One table**, the recommendation marked:

  | Option | What it means | What we gain | What we lose |
  |---|---|---|---|
  | **A (recommended)** | … | … | … |
  | B | … | … | … |

- **The answer format** closes the message: "Reply A, B or C". With `ask_user`, the options are its
  choices and the recommended one is the default.

## One level up

Before writing the question, name the class the instance belongs to and ask about the general
mechanism; the instance is the example. An answer about the mechanism settles every later case of
the class, an answer about the instance only this one. Write the class in the context sentence
("This is one case of …") and phrase every option as a rule for the class.

Worked example (5 Nov): the instance "can queries select the manifest note?" became the mechanism
"a note can mark itself ignored, like a Python underscore name; the manifest is one such note".
The options then were rules for every note (may mark itself ignored, or may not), and the manifest
was the first case they settled.

If no class exists, because the case is truly one of a kind, say so in the context and ask about
the instance.

## Tasks for the person

An open point that is not a choice, something only the person can do (grant access, approve a
release, sign in), is a task, never an option in a decision. Tasks are listed separately, one per
message as well, numbered against their own total ("Task 1 of 2"), each with what to do, where, and
what it unblocks.
