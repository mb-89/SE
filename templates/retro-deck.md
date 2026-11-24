---
# A retro's and an overhaul's one output, a deck: its title page (the title and subtitle lines, which
# become obs's cover), every step the run ran as one chapter each, then one decision chapter per
# finding the person decides, last. scripts/retro_deck.py renders it from a judged draft, checks it
# and builds it with obs; retro.py deck and overhaul.py deck run it. The person's decision of 24 Nov
# (SE#1826). scripts/templates.py's docstring owns this note's format.
name: retro-deck
version: 1.0.0
kind: document
reader: owner
says: "A retro's or an overhaul's deck: a title page, every step it ran as a chapter, then the decisions."
tags: ["retro", "overhaul", "deck"]
applies:
  actions: ["deck.build"]
  marker: <!-- se:retro-deck -->
  order: 25
rules:
  required: refuse
  duplicate: "off"
fields:
  - name: title
    kind: line
    label: Title
    required: true
    says: "The title page's title: `Retro #<n>` or `Overhaul #<n>`."
  - name: subtitle
    kind: line
    label: Subtitle
    required: true
    says: "The title page's subtitle: the window the run covers and how many findings it brings."
  - name: steps
    kind: text
    required: true
    exact_heading: true
  - name: decisions
    kind: text
    required: true
    none_ok: true
    exact_heading: true
example:
  fields:
    title: "Retro #12"
    subtitle: "13 to 24 November: 1 finding"
    steps: "### Table of what happened\n\n| chapter | from | to | steps |\n|---|---|---|---|\n| 1 | 2 Nov 10:00 | 2 Nov 16:00 | #11 |\n\n### The standing questions\n\n| question | 1 |\n|---|---|\n| What came back from real use since the last retro? | #11 |\n\n#### What came back from real use since the last retro?\n\nThe person's field feedback:\n\n> The integrator stalled twice on a red suite."
    decisions: "### 1. Refuse a landing without a field report\n\n#14 closed without a field report, and its landing went through.\n\nClass: Lost reports. Home: `scripts/work_tickets.py`.\n\n**Work, for your go**: Bless sends it to SE."
---

## Steps

<!-- steps: Every step the run ran, in its order, one `### <step>` chapter each: a retro's collected facts, the table of what happened, the standing questions with their full matrix and the field feedback answered in it, and the classes with their causes, fixes and homes, each naming its findings; an overhaul's verdicts, what it looked at, both question blocks, its findings by name, what went well and its facts. Each thing once: one table of what happened, its chapters, and one matrix, the standing questions against the chapters. A time of day reads `22 Nov 20:16`, in UTC, never an ISO timestamp. -->

## Decisions

<!-- decisions: One `### <n>. <finding>` chapter per finding the person decides, on the last pages: it opens with its current situation in plain technical English, never a stock phrase, then its class and home, and last whether it is work for their go or a decision for theirs; "None" where the run brings none. -->
