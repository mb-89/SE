---
# A retro's report, its closing comment, and the draft it is filed from: the six steps, the
# standing questions nested in step 4. retro.py lays the draft out from this note and checks it
# before it files the report; its judged block is the adapter templates/retro-judgment.md. The
# person's decision of 22 Nov (SE#1678). scripts/templates.py's docstring owns this note's format.
name: retro
version: 2.0.0
kind: document
reader: fleet
says: "A retro's report and its draft: the six steps, the standing questions nested in step 4."
tags: ["retro"]
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:retro-report -->
  order: 20
rules:
  required: refuse
  duplicate: "off"
fields:
  - name: field_feedback
    kind: text
    required: true
    none_ok: true
  - name: collect
    kind: text
    required: true
  - name: timeline
    kind: text
    required: true
  - name: matrix
    kind: text
    required: true
  - name: answers
    kind: node
    required: true
    node: standing-questions@1.0.0
  - name: classes
    kind: text
    required: true
  - name: decisions
    kind: text
    required: true
example:
  fields:
    field_feedback: "None."
    collect: "Two issues landed; one delivery was refused."
    timeline: "| chapter | steps |\n|---|---|\n| 1 | #11 |"
    matrix: "| question | 1 |\n|---|---|\n| Has the process gone stale? | #11 |"
    answers: "### What came back from real use since the last retro?\n\nNone.\n\n### Which scripts did the AI write that a machine could own?\n\nNone.\n\n### Anything worth porting to other projects, or so bad we remove it?\n\nNone.\n\n### Has the process gone stale?\n\nNone.\n\n### What would have stopped this from being produced at all?\n\nNone.\n\n### What did the shell do that a command could have done? Name it.\n\nNone.\n\n### Did anything local earn promotion upstream?\n\nNone.\n\n### For each failed check, what rule would have caught it?\n\nNone.\n\n### What goes well, and what makes it go well?\n\nNone.\n\n### What goes badly, each with its moment in the log?\n\nNone.\n\n### What do the thoughts say that the actions do not?\n\nNone.\n\n### Start, stop, keep, more, less.\n\nNone.\n\n### Which rule, prompt or tool made each bad output, and what change stops it?\n\nNone."
    classes: "#### Lost reports\n\nCause: a landing without a field report. Fix: `integrate` refuses it. Home: check, `scripts/work_tickets.py`. Tree: open."
    decisions: "Open: Lost reports, for the person's decision."
---

## 1. Field feedback

<!-- field_feedback: Relevant field feedback already available in the record; do not ask for or wait on more. Write "None." when no separate input is available. -->

## 2. Collect

<!-- collect: Per project, what retro.py collect read: what came back, refusals, escalations, suite times, session costs, scripts run three or more times, planning misses, the field reports' answers to the standing questions, and the last retro's classes measured again, rate before against rate now. -->

## 3. Table of what happened

<!-- timeline: The timeline in chapters of about six hours, then per step what went well, what it cost and whether a machine could do it; collect fills what the record says, the judge the rest. -->

## 4. The standing questions

<!-- matrix: The matrix: each standing question against each chapter, a cell naming what answers it there; collect fills the field reports' answers, the judge the rest. -->

## Answers to the standing questions

<!-- answers: The retro's answer to each standing question over the whole window, one `### <question>` each; "None" where nothing applies. -->

## 5. Classes and homes

<!-- classes: One cause and one fix per class, its home the first that holds in the order check, refusal, gate, prefill, checklist line, command, setting, sentence, and each class checked against the tree: fixed, past or open. -->

## 6. The person decides

<!-- decisions: Every open class, decided by the person in an SE session; SE files what is accepted. -->
