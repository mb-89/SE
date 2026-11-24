---
# Every merge into the integration branch: its title and its one Release-kind trailer, the rule
# work_tickets.py's merge_release_kind applies. scripts/se_templates.py's gate judges each merge call
# by it, one without a message as the pull request's description GitHub takes.
# scripts/templates.py's docstring owns this note's format.
name: merge-message
version: 1.0.0
kind: interface
reader: fleet
says: "A merge into the integration branch: `Integrate <branch>` (a release's `Release v<version>`) and one Release-kind trailer."
tags: ["commit"]
checker: work_tickets:merge_release_kind
applies:
  actions: ["pr.merge"]
  base: integration
  fallback: true
adapter:
  title_rule: work_tickets:MERGE_SUBJECT_PATTERN
  text_as: message
  title_as: subject
  with:
    commit: ""
  result: raises
---
