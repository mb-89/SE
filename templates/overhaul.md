---
# The overhaul's report comment: its judged block, checked by overhaul.py's own
# judgment_problems. scripts/templates.py's docstring owns this note's format.
name: overhaul
version: 1.0.0
kind: document
reader: fleet
says: "An overhaul's report: the verdicts, the findings and the judged block the next one reads."
tags: ["overhaul"]
checker: overhaul:judgment_problems
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:overhaul-report -->
  order: 30
adapter:
  json_after: <!-- se:overhaul-yaml -->
  # what judged adds
  drop:
    findings: ["finding", "kind", "rule_change"]
  result: problems
---
