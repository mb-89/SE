---
# The squash commit `integrate` lands: its title and its one Release-kind trailer, the rule
# work_tickets.py's merge_release_kind applies. scripts/templates.py's docstring owns this note's format.
name: merge-message
version: 1.0.0
kind: interface
reader: fleet
says: "An integration's squash commit: `Integrate <branch>` and one Release-kind trailer."
tags: ["commit"]
checker: work_tickets:merge_release_kind
applies:
  actions: ["pr.merge"]
  base: integration
  fallback: true
adapter:
  title_rule: work_tickets:INTEGRATION_SUBJECT_PATTERN
  text_as: message
  title_as: subject
  with:
    commit: ""
  result: raises
---
