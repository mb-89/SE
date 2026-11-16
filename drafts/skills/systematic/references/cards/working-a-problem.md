# Working a problem

Reader: an agent whose request names a problem, a failure or a symptom, not a need.

## When

- The request reports something broken: a failing check, a wrong output, a slow step.
- The need behind it is only clear once the cause is known.
- Several fixes are proposed and none has been tried.

## Steps

1. Reproduce before fixing: make it fail on demand, with the command and its output written down.
   A problem that cannot be reproduced is asked of the person.
2. Bisect: halve the space between a good state and a bad one (commits, inputs, settings) until
   one change is left.
3. Write each assumption next to its cheapest experiment, and run the cheapest first.
4. Stop comparing after two rounds: when two rounds of comparing causes or fixes add nothing,
   pick the one the evidence favours and say why.
5. Mark an estimate as an estimate: a number nobody measured says so where it is written.

## Where it goes in SE

The reproduction and the cause go to the work issue's Situation and Problem sections. The fix's
need becomes a record in the requirements reference, and the reproduction becomes its `verify`
key, as a test that failed before and passes after.

## Source

David Agans, "Debugging", AMACOM, 2002: make it fail before fixing it. Andreas Zeller, "Why
Programs Fail", Morgan Kaufmann, 2005: bisection and delta debugging, and a hypothesis tested
by the experiment that decides it.
