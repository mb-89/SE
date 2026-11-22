---
# The owner's housekeeping pull request: it carries the label `housekeeping` and no field report
# (scripts/pr_issues.py exempts it). scripts/templates.py's docstring owns this note's format.
name: housekeeping
version: 1.0.0
kind: document
reader: owner
says: "The owner's housekeeping pull request: no field report, no field required."
tags: ["pull-request"]
applies:
  actions: ["pr.create", "pr.edit"]
  base: integration
  labels: ["housekeeping"]
  order: 20
---
