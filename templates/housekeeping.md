---
# The owner's housekeeping pull request: it carries the label `housekeeping` and no field report
# (scripts/pr_issues.py's issue rule exempts it), and states its release kind as every pull request
# into the integration branch does. scripts/templates.py's docstring owns this note's format.
name: housekeeping
version: 1.0.0
kind: document
reader: owner
says: "The owner's housekeeping pull request: no field report, only its release kind."
tags: ["pull-request"]
applies:
  actions: ["pr.create", "pr.edit"]
  base: integration
  labels: ["housekeeping"]
  order: 20
adapter:
  lines:
    - pattern: "Release-kind: (?:patch|minor|major)"
      says: "the line `Release-kind: <patch|minor|major>`, which CI's release-kind gate reads"
---
