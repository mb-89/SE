---
# The overhaul report's judged block: its yaml fence, which the overhaul template's judgment node
# names, checked by overhaul.py's own judgment_problems, without the keys `file` adds to each
# finding. scripts/templates.py's docstring owns this note's format.
name: overhaul-judgment
version: 1.0.0
kind: block
reader: fleet
says: "An overhaul's judged block: the verdicts, what was looked at, the findings and what went well."
tags: ["overhaul"]
checker: overhaul:judgment_problems
adapter:
  extract: overhaul:fence_data
  # what judged adds
  drop:
    findings: ["finding", "kind", "rule_change"]
  result: problems
---
