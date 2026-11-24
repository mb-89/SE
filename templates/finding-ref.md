---
# How a work issue names a retro's or an overhaul's finding it takes, so the next run scores it
# (src/agents/se.md, src/agents/retro.md). The reports write it through the schema generated into
# scripts/interfaces/; retro.py's and overhaul.py's FINDING_REFERENCE find it in free text.
# scripts/templates.py's docstring owns this note's format.
name: finding-ref
version: 1.0.0
kind: interface
reader: fleet
says: "A finding's reference in a work issue: the run's kind and number and the finding's number in its report."
tags: ["message", "retro", "overhaul"]
message: "{kind} #{number} finding {finding}"
applies:
  actions: ["message.send"]
  marker_pattern: "(retro|overhaul) #.+ finding .+"
rules:
  required: refuse
  choice: refuse
fields:
  - name: kind
    kind: choice
    required: true
    says: "retro or overhaul: the run whose report holds the finding."
    choices:
      - retro
      - overhaul
  - name: number
    kind: line
    required: true
    says: "The run's issue number, digits alone."
  - name: finding
    kind: line
    required: true
    says: "The finding's number in the run's report, digits alone."
example:
  fields:
    kind: retro
    number: "30"
    finding: "2"
---
