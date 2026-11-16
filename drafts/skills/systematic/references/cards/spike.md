# Spike

Reader: an agent facing a question that only trying can answer.

## When

- The clarify reference's look cannot answer a question: the docs are silent or disagree.
- A requirement's `verify` key depends on whether something is possible at all.
- An estimate would be a guess without a first attempt.

## Steps

1. Write the one question the spike answers, and the answer that would change the plan.
2. Set a limit before starting: a time box, or a number of attempts.
3. Try it in a scratch copy, never in the checkout the work is built in.
4. Use the real channel: the real host, command or service, not a model of it.
5. Record what was run and what it printed, as it printed it.
6. Stop at the limit, answered or not. An unanswered question is itself the result.
7. Throw the spike's code away; only the answer and its evidence are kept.

## Where it goes in SE

The answer and its evidence go to the work issue's Situation section, or to the `verify` key of
the record that depended on it. In a discovery package, record each run with
`<se>/scripts/work_tickets.py probe`, which appends it to the discovery evidence index.

## Source

Kent Beck, "Extreme Programming Explained", Addison-Wesley, 2000: the spike solution, a small
program that explores a question and is then thrown away.
