# Process

Reader: a person, or an agent the person asked, taking a large request the whole way from the
first questions to verified requirements and a handed-over result.

This page is a menu a person calls by name. No work has to follow it today, and a step may be
skipped where it adds nothing. Whether major work must follow it is an open question for the
owner.

## The steps

Each step names the evidence that shows it is done.

1. **Frame.** Write the request in one line, its open questions and its stakeholders
   ([clarify](clarify.md), [stakeholders](cards/stakeholders.md)).
   Done when: every question has one of the three results of the look, shown.
2. **Requirements.** One record per requirement ([requirements](requirements.md),
   [use cases](cards/use-cases.md), [quality scenarios](cards/quality-scenarios.md)).
   Done when: every record has its seven keys and a `verify` named before any result.
3. **Candidates.** Write the ways to meet them ([options](cards/options.md),
   [prior art](cards/prior-art.md)).
   Done when: at least three options stand, doing nothing among them, each with its cost.
4. **Decide.** The decision skill makes and records the choice.
   Done when: the decision skill's note exists and names the picked option.
5. **Prove the riskiest unknown.** Try the one thing most likely to sink the choice
   ([spike](cards/spike.md)).
   Done when: its answer and the command output behind it are written down.
6. **Build test-first.** Each must record gets its test before its code.
   Done when: each such test was seen failing before the change and passing after it.
7. **Validate against every need.** Walk the records' `serves` keys, not only the tests.
   Done when: each need is met, or named as unmet with its reason.
8. **Hand over.** Write what was built, what was deferred and why
   ([design brief](cards/design-brief.md)).
   Done when: the work issue's Acceptance items are each ticked or answered.

## Three more items

- **Probe the real channel early.** Before step 6, run the real host, command or service once;
  a model of it hides what the real one refuses.
- **The architecture view is a boundary.** Once a design names its parts and their links, the
  build stays inside them; a step that needs a new part goes back to step 4.
- **Sweep for consistency before validating.** Before step 7, read the records, the issue and the
  code side by side for names, numbers and paths that disagree.

When the request names a problem rather than a need, start with
[working a problem](cards/working-a-problem.md) and enter at step 1 once the cause is known.
