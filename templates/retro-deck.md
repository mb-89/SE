---
# A retro's and an overhaul's one output, a deck: its title page, every step as one chapter, then
# one decision chapter per finding. A retro cover is exactly `<name>: Retro #<n>` and `Retro report`,
# the document type, rendered once: a retro has no subtitle. Every decision chapter, "Anything else?"
# included, is a note of templates/decision.md, built by retro_deck.decision_note and refused otherwise;
# "Anything else?" has "Nothing else" as its single selectable default. Learning (a project's retro deck, 26 Nov): the deck's shape comes from the templates, never from the agent's judgment; the cover
# showed "Retro report" twice and the decisions were free text. scripts/retro_deck.py
# renders the deck from a judged draft, checks it and builds it with obs; retro.py deck and
# overhaul.py deck run it. The person's decisions of 24 and 25 Nov (SE#1826). scripts/templates.py
# owns this note's format.
name: retro-deck
version: 3.0.0
kind: document
reader: owner
says: "Every decision chapter is a decision note; a retro's deck ends with Anything else? and Nothing else as its single selectable default."
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
    required: false
    says: "An overhaul's subtitle names its rule and finding counts; a retro has none, as its cover's second line is its document type, `Retro report`."
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
    steps: "### Table of what happened\n\n| chapter | from | to | steps |\n|---|---|---|---|\n| 1 | 2 Nov 10:00 | 2 Nov 16:00 | #11 |\n\n### The standing questions\n\n| question | 1 |\n|---|---|\n| What came back from real use since the last retro? | #11 |\n\n#### What came back from real use since the last retro?\n\nNone."
    decisions: "### 1. Refuse a landing without a field report\n\n#### Current situation\n\n###14 closed without a field report, and its landing went through.\n\n#### The problem\n\nClass: Lost reports. Nothing at the landing asks for the report. Home: `scripts/work_tickets.py`.\n\n#### What others do\n\nGerrit refuses a submit until its required labels are set; GitHub refuses a merge until its required checks pass.\n\n```pugh\ncriteria:\n  - {\"key\": \"cause\", \"label\": \"Removes the class's cause\", \"weight\": 1, \"better\": \"higher\", \"kind\": \"judged\"}\ncandidates:\n  - {\"key\": \"a\", \"label\": \"Refuse a landing without a field report\", \"what\": \"integrate refuses a landing whose pull request has no field report.\", \"wins\": \"No report is lost.\", \"losses\": \"One more check per landing.\", \"success\": \"The next retro finds no landing without a report.\", \"marks\": {\"cause\": {\"mark\": 1, \"because\": \"it removes the class's cause\"}}}\n  - {\"key\": \"b\", \"label\": \"Keep what we have\", \"what\": \"Nothing changes.\", \"wins\": \"No work.\", \"losses\": \"Reports stay lost.\", \"success\": \"Nothing to check.\", \"marks\": {\"cause\": 0}}\ndatum: {\"prefer\": [\"b\"]}\n```\n\n### Anything else?\n\n#### Current situation\n\nThe findings on the pages before this one come from the collected record, the field reports and the top-level SE session's input.\n\n#### The problem\n\nSomething the person saw may be in none of them, and a retro that does not ask leaves it out.\n\n#### What others do\n\nA Start, Stop, Continue retrospective ends with an open round for what nobody has said yet; a GitHub pull request review ends with a general comment beside its line comments.\n\n```pugh\ncriteria:\n  - {\"key\": \"said\", \"label\": \"Everything the person saw is in the retro\", \"weight\": 1, \"better\": \"higher\", \"kind\": \"judged\"}\ncandidates:\n  - {\"key\": \"a\", \"label\": \"Nothing else\", \"what\": \"The retro holds everything the person saw.\", \"wins\": \"The retro closes as it stands.\", \"losses\": \"None.\", \"success\": \"No later report names something this retro missed.\", \"marks\": {\"said\": 0}}\n  - {\"key\": \"b\", \"label\": \"Something else\", \"what\": \"The person names it in this chapter's comment.\", \"fits\": false, \"whyNot\": \"Write it in the comment: the comment is the answer.\", \"wins\": \"It reaches SE.\", \"losses\": \"None.\", \"success\": \"SE answers the comment.\", \"marks\": {\"said\": {\"mark\": 1, \"because\": \"the comment adds what was missing\"}}}\ndatum: {\"prefer\": [\"a\"]}\n```"
---

## Steps

<!-- steps: Every step the run ran, in its order, one `### <step>` chapter each: a retro's collected facts, the table of what happened, the standing questions with their full matrix and answers, and the classes with their causes, fixes and homes, each naming its findings; an overhaul's verdicts, what it looked at, both question blocks, its findings by name, what went well and its facts. Each thing once: one table of what happened, its chapters, and one matrix, the standing questions against the chapters. A time of day reads `22 Nov 20:16`, in UTC, never an ISO timestamp. -->

## Decisions

<!-- decisions: One `### <n>. <finding>` chapter per finding the person decides, on the last pages, each a note of the decision template (templates/decision.md) as retro_deck.decision_note writes it: `Current situation` in plain technical English, never a stock phrase, `The problem` with its class and home, `What others do`, then the `pugh` fence with the change and keeping what we have; a retro ends with `Anything else?`, whose single selectable default is `Nothing else` and whose comment takes anything else. A free-form chapter is refused. -->
