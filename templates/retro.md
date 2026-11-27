---
# A retro's report, its closing comment, and the draft it is filed from: the five steps, the
# standing questions nested in step 3. retro.py lays the draft out from this note and checks it
# before it files the report; its judged block is the adapter templates/retro-judgment.md. The
# person's decision of 22 Nov (SE#1678). SE's input is evidence in step 1, and the report goes up
# before the deck because, in the owner's words, "the last [retro] took forever to finish, and
# that's really not acceptable, so it needs to be quicker this time." Learning (a project's retro deck, 26 Nov): the deck's shape comes from the templates (retro-deck.md, decision.md), never from
# the agent's judgment: retro.py deck renders the cover once and every decision as a decision note.
# scripts/templates.py's docstring owns this note's format.
name: retro
version: 4.0.0
kind: document
reader: fleet
says: "A retro's report and its draft: the five steps, the standing questions nested in step 3."
tags: ["retro"]
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:retro-report -->
  order: 20
rules:
  required: refuse
  duplicate: "off"
fields:
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
    node: standing-questions@2.0.0
  - name: classes
    kind: text
    required: true
  - name: decisions
    kind: text
    required: true
example:
  fields:
    collect: "Two issues landed; one delivery was refused."
    timeline: "| chapter | steps |\n|---|---|\n| 1 | #11 |"
    matrix: "| question | 1 |\n|---|---|\n| Has the process gone stale? | #11 |"
    answers: "### What came back from real use since the last retro?\n\nNone.\n\n### Which scripts did the AI write that a machine could own?\n\nNone.\n\n### Anything worth porting to other projects, or so bad we remove it?\n\nNone.\n\n### Has the process gone stale?\n\nNone.\n\n### What would have stopped this from being produced at all?\n\nNone.\n\n### What did the shell do that a command could have done? Name it.\n\nNone.\n\n### Did anything local earn promotion upstream?\n\nNone.\n\n### For each failed check, what rule would have caught it?\n\nNone.\n\n### What goes well, and what makes it go well?\n\nNone.\n\n### What goes badly, each with its moment in the log?\n\nNone.\n\n### What do the thoughts say that the actions do not?\n\nNone.\n\n### Start, stop, keep, more, less.\n\nNone.\n\n### Which rule, prompt or tool made each bad output, and what change stops it?\n\nNone.\n\n### What took the longest, and why?\n\nJudging the classes, as the record named no cause.\n\n### What tool did you wish was present: in SE, kern, the project, or anything outside our tooling?\n\nIn SE: a list of the window's causes by class.\n\n### Tooling starfish: what should our tooling start, stop, keep, do more of and do less of? Removals count too.\n\nStart: classes by cause. Stop: nothing. Keep: the record. More: refusals that name their fix. Less: hand steps."
    classes: "#### Lost reports\n\nCause: a landing without a field report. Fix: `integrate` refuses it. Home: check, `scripts/work_tickets.py`. Tree: open."
    decisions: "Open: Lost reports, for the person's decision."
---

## 1. Collect

<!-- collect: Per project, what retro.py collect read: what came back, refusals, escalations, suite times, session costs, scripts run three or more times, planning misses, the field reports' answers to the standing questions (by question, so a gap the tooling questions name in two reports stands together and is a finding), and the last retro's classes measured again, rate before against rate now. SE's input: the retro asks the top-level SE session named in its prompt once, in one message, for a file of what SE saw go wrong, the local notes register with it; it does not wait for the answer. Read SE's file with the field reports and judge it by the same standard as every other piece of evidence; where SE did not answer, say so here. -->

## 2. Table of what happened

<!-- timeline: The timeline in chapters of about six hours, then per step what went well, what it cost and whether a machine could do it; collect fills what the record says, the judge the rest. -->

## 3. The standing questions

<!-- matrix: The matrix: each standing question against each chapter, a cell naming what answers it there; collect fills the field reports' answers, the judge the rest. -->

## Answers to the standing questions

<!-- answers: The retro's answer to each standing question over the whole window, one `### <question>` each; "None" where nothing applies. -->

## 4. Classes and homes

<!-- classes: One cause and one fix per class, its home the first that holds in the order check, refusal, gate, prefill, checklist line, command, setting, sentence, and each class checked against the tree: fixed, past or open. -->

## 5. The person decides

<!-- decisions: The report goes up first, moving the issue to report state as soon as the findings table stands; only then is a lean deck built. The report records each finding as open; the standalone deck carries the person's answer, so preparing the report does not wait on it. -->
