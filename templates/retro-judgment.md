---
# A retro draft's judged block, the JSON under `<!-- se:retro-yaml -->`: retro.py's
# judgment_problems checks it, and `retro.py file` reads it through this note (`judged`), which
# keeps its retro-number check. scripts/templates.py's docstring owns this note's format.
name: retro-judgment
version: 1.0.0
kind: block
reader: fleet
says: "A retro's judged block: the findings, the classes and what went well, as JSON under its marker."
tags: ["retro"]
checker: retro:judgment_problems
adapter:
  json_after: <!-- se:retro-yaml -->
  when: retro:is_object
  result: problems
---
