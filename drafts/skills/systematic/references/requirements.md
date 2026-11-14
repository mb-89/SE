# One record per requirement

## The record

A requirement is one Markdown note. Its file name is its id: `req-<nnn>.md`, three digits,
`req-001.md` first, in the order the records are written. An id is never reused.

Its front matter holds seven keys, in this order:

1. `concern`: exactly one concern; a record with two is two records.
2. `statement`: one sentence in one of the five EARS patterns below.
3. `kind`: `functional`, `quality`, `constraint` or `interface`.
4. `priority`: `must` or `wish`. A must is one the work does not ship while it fails; anything
   shipped around is a wish.
5. `verify`: `test`, `analysis`, `inspection` or `demonstration`, with its pass rule, named when
   the record is written and before any result exists. If none can be named, it is not a
   requirement yet.
6. `breaks-if-removed`: one line on what fails without it. If none can be written, the record is
   a deletion candidate.
7. `serves`: the need it serves, and whose need it is.

```markdown
---
concern: <one concern>
statement: When <trigger>, the <system> shall <response>.
kind: functional
priority: must
verify: test; <pass rule>
breaks-if-removed: <what fails without it>
serves: <the need>, for <whom>
---
```

## EARS

EARS (the Easy Approach to Requirements Syntax, Mavin et al., IEEE RE 2009;
[alistairmavin.com/ears](https://alistairmavin.com/ears/)) has five patterns:

- Ubiquitous: `The <system> shall <response>.`
- Event-driven: `When <trigger>, the <system> shall <response>.`
- State-driven: `While <precondition>, the <system> shall <response>.`
- Unwanted behaviour: `If <trigger>, then the <system> shall <response>.`
- Optional feature: `Where <feature is included>, the <system> shall <response>.`

Quality scenarios and stakeholders are left to their cards (the To come list of
[SKILL.md](../SKILL.md#to-come)).

## What quackitect learned

The source is quackitect v3, the third generation of the system before SE.

- **Extend before writing (measured).** In its one measured round, 11 of 36 new records repeated
  a demand that already stood. So a standing record is extended before a new one is written:
  search the records for the concern first.
- **Fluent records no method can verify (read).** A model writes a requirement that reads well and
  that no test, analysis, inspection or demonstration can check. The `verify` key, named before
  any result, catches it.
- **Tolerances with no source (read).** A model writes a number, a limit or a unit that nobody
  measured or documented. Every number and unit names its source, or the record calls it a guess.
- **Design restated as requirement (read).** A model writes how something is built as what is
  needed. Such a record is cut, or its need is written instead.

The first lesson is measured, in quackitect's own round; the other three are read, from the
literature on writing requirements with a model.
