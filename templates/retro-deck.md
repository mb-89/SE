---
# A retro's and an overhaul's one output, a deck: its title page, every step as one chapter, then
# one decision chapter per finding. A retro cover is exactly `<name>: Retro #<n>` and `Retro report`;
# its last decision is "Anything else?" with "Nothing else" as the answer. scripts/retro_deck.py
# renders the deck from a judged draft, checks it and builds it with obs; retro.py deck and
# overhaul.py deck run it. The person's decisions of 24 and 25 Nov (SE#1826). scripts/templates.py
# owns this note's format.
name: retro-deck
version: 2.0.0
kind: document
reader: owner
says: "A retro's deck ends with Anything else? and Nothing else as its single selectable default."
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
    says: "The retro title page's title: `<name>: Retro #<n>`; an overhaul's is `Overhaul #<n>`."
  - name: subtitle
    kind: line
    label: Subtitle
    required: true
    says: "A retro's subtitle is exactly `Retro report`; an overhaul's names its rule and finding counts."
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
    title: "example: Retro #12"
    subtitle: "Retro report"
    steps: "### Table of what happened\n\n| chapter | from | to | steps |\n|---|---|---|---|\n| 1 | 2 Nov 10:00 | 2 Nov 16:00 | #11 |\n\n### The standing questions\n\n| question | 1 |\n|---|---|\n| What came back from real use since the last retro? | #11 |\n\n#### What came back from real use since the last retro?\n\nNone."
    decisions: "### 1. Refuse a landing without a field report\n\n#14 closed without a field report, and its landing went through.\n\nClass: Lost reports. Home: `scripts/work_tickets.py`.\n\n**Work, for your go**: Bless sends it to SE.\n\n### Anything else?\n\nNothing else"
---

## Steps

<!-- steps: Every step the run ran, in its order, one `### <step>` chapter each: a retro's collected facts, the table of what happened, the standing questions with their full matrix and answers, and the classes with their causes, fixes and homes, each naming its findings; an overhaul's verdicts, what it looked at, both question blocks, its findings by name, what went well and its facts. Each thing once: one table of what happened, its chapters, and one matrix, the standing questions against the chapters. A time of day reads `22 Nov 20:16`, in UTC, never an ISO timestamp. -->

## Decisions

<!-- decisions: One `### <n>. <finding>` chapter per finding the person decides, on the last pages: it opens with its current situation in plain technical English, never a stock phrase, then its class and home, and last whether it is work for their go or a decision for theirs; a retro ends with `Anything else?` and the single answer `Nothing else`. -->
