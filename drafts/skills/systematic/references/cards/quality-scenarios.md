# Quality scenarios

Reader: an agent writing a quality requirement: speed, reliability, safety, ease of use or change.

## When

- A demand uses an adjective: fast, robust, simple, safe.
- A record has `kind: quality` and no number in its `verify` key.
- Two quality demands compete, such as a strict check and a fast start.

## Steps

1. Name the quality in one word, using ISO/IEC 25010's terms where one fits: performance
   efficiency, reliability, security, maintainability, usability, portability.
2. Write the six parts: the source of the stimulus, the stimulus, the environment it arrives in,
   the part of the system that receives it, the response, and the response measure.
3. Give the measure a number and a unit, and name where the number comes from; without a source,
   call it a guess.
4. Say how the measure is taken: which command, on which tree, how many runs.
5. Measure today's value on the base branch before writing the target, so the record states the
   change it asks for.
6. Write the scenario as one EARS statement; the measure becomes the pass rule of `verify`.

## Where it goes in SE

The scenario becomes one record in the requirements reference with `kind: quality`; the measure
is the pass rule in its `verify` key. Today's measured value goes in the work issue's Situation
section. A conflict between two qualities goes to the decision skill.

## Source

Len Bass, Paul Clements and Rick Kazman, "Software Architecture in Practice", 2nd edition,
Addison-Wesley, 2003: the six-part quality attribute scenario. ISO/IEC 25010:2011 for the names
of the qualities.
