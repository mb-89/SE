---
# The comment `work_tickets.py unclaim` answers a work issue's last Started comment with, once it
# has undone a claim no worker took (src/skills/work-model/SKILL.md "Worktrees"). Its schema is
# generated into scripts/interfaces/, which unclaim writes it through; unclaim finds it by its
# prefix, `Claim undone:`. scripts/templates.py's docstring owns this note's format.
name: claim-undone
version: 1.0.0
kind: interface
reader: fleet
says: "The answer to a Started comment whose claim was undone: that comment and the branch the next start takes."
tags: ["message", "start"]
message: "Claim undone: {started} started no worker; `ready`, `claim` and `start` take its branch `{branch}` again."
applies:
  actions: ["message.send"]
  marker_pattern: "Claim undone: .+ started no worker; .+"
rules:
  required: refuse
fields:
  - name: started
    kind: line
    required: true
    says: "The Started comment answered: its URL, or `its Started comment` where it has none."
  - name: branch
    kind: line
    required: true
    says: "The work branch, named like the work issue's title."
example:
  fields:
    started: "https://example.com/issues/12#issuecomment-1"
    branch: templates-interfaces
---
