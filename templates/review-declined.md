---
# The comment review.py writes on the work issue of a pull request its cold review declines
# (src/agents/reviewer.md). Its schema is generated into scripts/interfaces/, which review.py
# writes it through; retro.py's DECLINED finds it by its start. scripts/templates.py's docstring
# owns this note's format.
name: review-declined
version: 1.0.0
kind: interface
reader: fleet
says: "A declined review's comment on the work issue: the pull request the review declined and its link."
tags: ["message", "review"]
message: "Declined by the review of pull request #{number} ({url}): the change is fundamentally wrong and does not land. The review comment there holds the findings; SE re-scopes this issue or takes it to the owner."
applies:
  actions: ["message.send"]
  marker_pattern: "Declined by the review of pull request #.+ \\(.+\\): .+"
rules:
  required: refuse
fields:
  - name: number
    kind: line
    required: true
    says: "The number of the declined pull request, digits alone."
  - name: url
    kind: line
    required: true
    says: "The declined pull request's link."
example:
  fields:
    number: "5"
    url: "https://example.com/pull/5"
---
