---
name: systematic
description: 'Turns a request into requirements, systematically: first the open questions, each one looked up on the freshly fetched base branch, then one record per requirement with its concern, an EARS statement, its kind, its priority, how it is verified and what breaks without it. Use when a request, an idea or a design note is to become requirements a piece of work is built and checked against. A draft: nothing SE installs reads it yet.'
disable-model-invocation: true
---

# Systematic

A request becomes requirements in two steps, always in this order:

1. **Clarify against the tree.** Write the open questions as a list before any record, and answer
   each by looking at the freshly fetched base branch, showing the look.
   Read [references/clarify.md](references/clarify.md) before writing the first record of a
   request, and whenever a request names a command, file, flag or setting.
2. **One record per requirement.** Each requirement that survives the questions becomes one note
   with seven keys, in a fixed order.
   Read [references/requirements.md](references/requirements.md) when writing or extending a
   record, and when judging whether a demand is a requirement at all.

## Rules of thumb

- A question comes before a record. A record written before its questions are answered restates
  the request; it does not narrow it.
- Extend a standing record before writing a new one: a new demand often repeats one that already
  stands.
- A requirement names how it is verified before any result exists. If no method can be named, it
  is not a requirement yet.
- A record states what is needed, not how it is built. Design restated as a requirement is cut or
  moved to the design.
- Every number and unit names its source, or the record calls it a guess.

## To come

A later piece of work adds these references. None exists yet; each becomes a link when it lands.

- `references/process.md`: read when a request is large enough to need the whole path, from the
  first questions to the verified requirement.
- `references/cards/stakeholders.md`: read when it is unclear whose need a record serves.
- `references/cards/use-cases.md`: read when a functional requirement needs the steps around it.
- `references/cards/quality-scenarios.md`: read when writing a quality requirement.
- `references/cards/options.md`: read when a requirement leaves more than one way to meet it.
- `references/cards/spike.md`: read when a question can only be answered by trying.
- `references/cards/prior-art.md`: read before inventing what may already exist elsewhere.
- `references/cards/working-a-problem.md`: read when the request names a problem, not a need.
- `references/cards/design-brief.md`: read when the requirements are handed on to a design.
