# Prior art

Reader: an agent about to invent something that may already exist elsewhere.

## When

- A requirement asks for a mechanism that is common outside SE: a format, a protocol, a tool.
- The design names a standard or another project and nobody has read it.
- A claim about what a host or service does rests on memory, not on a source.

## Steps

1. Write the question as a search: what is needed, in the words others would use for it.
2. Search in rounds. A round is a few searches and the sources they find, read far enough to
   judge them.
3. Stop after two rounds in a row that add nothing new.
4. Sort each claim into one of four classes: vendor claim (what a maker says of its product),
   protocol guarantee (what a published specification requires), local measurement (what was run
   here, with its output), inference (what follows from the others but was not seen).
5. Weigh them in that order, upward: a local measurement beats a protocol guarantee, which beats
   a vendor claim; an inference is never evidence by itself.
6. Name each source with its date: a found idea is adopted, adapted or set aside, with a reason.

## Where it goes in SE

Adopted ideas and their classes go to the work issue's Situation or Approach section. In a
discovery package, record each local measurement with `<se>/scripts/work_tickets.py probe`, which
appends it to the discovery evidence index. `<se>/scripts/transcript_signals.py --research` lists
the searches and fetches a session made, as the trail behind the claims.

## Source

Barbara Kitchenham, "Procedures for Performing Systematic Reviews", Keele University, 2004: a
review with a stated question, a stated search and a record of what each source contributed.
