---
# An overhaul draft's judged block, the JSON under `<!-- se:overhaul-yaml -->`: overhaul.py's
# judgment_problems checks it, and `overhaul.py file` reads it through this note (`judged`), which
# keeps its overhaul-number check and question_problems. scripts/templates.py's docstring owns this
# note's format.
name: overhaul-judgment
version: 1.0.0
kind: block
reader: fleet
says: "An overhaul's judged block: a verdict on every rule, what it looked at, the findings and what went well, as JSON under its marker."
tags: ["overhaul"]
checker: overhaul:judgment_problems
adapter:
  json_after: <!-- se:overhaul-yaml -->
  when: retro:is_object
  result: problems
---
