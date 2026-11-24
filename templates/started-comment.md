---
# The comment `work_tickets.py start` posts on a work issue once its worker starts, which
# fleet-check's lease counts from (src/skills/work-model/SKILL.md "Worktrees"). Its schema is
# generated into scripts/interfaces/, which start writes it through; the readers find it by its
# prefix, `Started:`. scripts/templates.py's docstring owns this note's format.
name: started-comment
version: 1.0.0
kind: interface
reader: fleet
says: "A work issue's Started comment: the branch its worker works on."
tags: ["message", "start"]
message: "Started: worker session on branch `{branch}`"
applies:
  actions: ["message.send"]
  marker_pattern: "Started: worker session on branch `.+`"
rules:
  required: refuse
fields:
  - name: branch
    kind: line
    required: true
    says: "The work branch, named like the work issue's title."
example:
  fields:
    branch: templates-interfaces
---
