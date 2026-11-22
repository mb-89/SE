---
# The one message an integrator at the top level sends SE once `work_tickets.py escalate` has
# labelled the work issue and commented its question (src/agents/integrator.md "Escalate and
# improve"). Its schema is generated into scripts/interfaces/, which work_tickets.py escalate writes
# it through. scripts/templates.py's docstring owns this note's format.
name: escalation
version: 1.0.0
kind: interface
reader: fleet
says: "An escalation to SE: the escalated issue and its question in one line."
tags: ["message", "escalation"]
message: "escalated #{issue}: {question}"
applies:
  actions: ["message.send"]
  marker_pattern: "escalated #.+: .+"
rules:
  required: refuse
fields:
  - name: issue
    kind: line
    required: true
    says: "The number of the escalated issue, digits alone."
  - name: question
    kind: line
    required: true
    says: "The question SE decides, in one line: the first line of the escalation's comment."
example:
  fields:
    issue: "12"
    question: "Land the change that removes the old export, or keep both?"
---
