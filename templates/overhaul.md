---
# An overhaul's report, its closing comment: the verdicts, what was looked at, the standing
# questions and the overhaul's own (two nested blocks), the findings and what follows, what went
# well, the facts, then the judged block the next overhaul reads, which stays overhaul.py's own
# (judgment_problems). overhaul.py lays the draft's questions out from this note and checks the
# report before it files it. The person's decision of 22 Nov (SE#1678). scripts/templates.py's docstring owns
# this note's format.
name: overhaul
version: 2.0.0
kind: document
reader: fleet
says: "An overhaul's report: verdicts, both question blocks, the findings and the judged block the next one reads."
tags: ["overhaul"]
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:overhaul-report -->
  order: 30
rules:
  required: refuse
  duplicate: "off"
fields:
  - name: verdicts
    kind: text
    required: true
  - name: looked_at
    kind: text
    required: true
  - name: questions
    kind: node
    required: true
    node: standing-questions@1.0.0
  - name: overhaul_questions
    kind: node
    required: true
    node: overhaul-questions@1.0.0
  - name: findings
    kind: text
    required: true
    none_ok: true
  - name: went_well
    kind: text
    required: true
  - name: facts
    kind: text
    required: true
example:
  fields:
    verdicts: "| rule | strays | how |\n|---|---|---|\n| gen-001 | none | Held. |"
    looked_at: "- **outside**: nothing to change."
    questions: "### What came back from real use since the last retro?\n\nNone.\n\n### Which scripts did the AI write that a machine could own?\n\nNone.\n\n### Anything worth porting to other projects, or so bad we remove it?\n\nNone.\n\n### Has the process gone stale?\n\nNone.\n\n### What would have stopped this from being produced at all?\n\nNone.\n\n### What did the shell do that a command could have done? Name it.\n\nNone.\n\n### Did anything local earn promotion upstream?\n\nNone.\n\n### For each failed check, what rule would have caught it?\n\nNone.\n\n### What goes well, and what makes it go well?\n\nNone.\n\n### What goes badly, each with its moment in the log?\n\nNone.\n\n### What do the thoughts say that the actions do not?\n\nNone.\n\n### Start, stop, keep, more, less.\n\nNone.\n\n### Which rule, prompt or tool made each bad output, and what change stops it?\n\nNone."
    overhaul_questions: "### Are the prose and the code still in the voice and style we hold?\n\nNone.\n\n### Is the method still the best we know?\n\nNone.\n\n### Has the guidance drifted from what the machines do?\n\nNone.\n\n### Does every file earn its place?\n\nNone.\n\n### Would a named design pattern improve us?\n\nNone.\n\n### What does the outside world do, and what can we learn from it?\n\nNone."
    findings: "None."
    went_well: "- The retros held."
    facts: "One rule."
---

## Verdicts

<!-- verdicts: One row per rule of the book: how far se strays from it, and how. -->

## What was looked at

<!-- looked_at: Every part the overhaul looked at, each with its answer; "nothing to change" is an answer. -->

## The standing questions

<!-- questions: The standing questions, the retro's and the field report's too, answered over everything since the last overhaul: one `### <question>` each; "None" where nothing applies. -->

## The overhaul's own questions

<!-- overhaul_questions: The overhaul's own questions: one `### <question>` each; "None" where nothing applies. -->

## Findings

<!-- findings: Each finding, numbered, with its kind, its rule and the place it changes, then what follows: the work findings bundled into work issues, the decisions on the person's list. -->

## What went well

<!-- went_well: What went well since the last overhaul. -->

## The facts

<!-- facts: The draft's facts, then the judged block under its marker, the data the next overhaul reads. -->
