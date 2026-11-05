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

## Tasks for the person

An open point that is not a choice, something only the person can do (grant access, approve a
release, sign in), is a task, never an option in a decision. Tasks are listed separately, one per
message as well, numbered against their own total ("Task 1 of 2"), each with what to do, where, and
what it unblocks.
