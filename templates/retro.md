---
# The retro's judged block, checked by retro.py's own judgment_problems. Its report comment links
# the committed retro doc that holds the block, so a comment without one has nothing to judge here
# and warns. scripts/templates.py's docstring owns this note's format.
name: retro
version: 1.0.0
kind: document
reader: fleet
says: "A retro's report or draft: its judged block, under its marker."
tags: ["retro"]
checker: retro:judgment_problems
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:retro-report -->
  order: 20
adapter:
  json_after: <!-- se:retro-yaml -->
  # what judged adds to each finding
  drop:
    findings: ["finding", "kind"]
  missing: warn
  result: problems
---
