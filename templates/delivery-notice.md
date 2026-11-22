---
# The one message a worker sends its integrator once its pull request carries its field report
# (src/agents/worker.md step 7). Its schema is generated into scripts/interfaces/, which
# work_tickets.py deliver writes it through. scripts/templates.py's docstring owns this note's format.
name: delivery-notice
version: 1.0.0
kind: interface
reader: fleet
says: "A worker's delivery: the pull request whose description is its field report, and its branch."
tags: ["message", "delivery"]
message: "field report in PR #{pr} for {branch}"
applies:
  actions: ["message.send"]
  marker_pattern: "field report in PR #.+ for .+"
rules:
  required: refuse
fields:
  - name: pr
    kind: line
    required: true
    says: "The number of the work pull request, digits alone."
  - name: branch
    kind: line
    required: true
    says: "The work branch, named like the work issue's title."
example:
  fields:
    pr: "7"
    branch: templates-interfaces
---
