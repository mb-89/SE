---
# A work issue's body file, .se/issues/<name>.md: the work template's sections, which its fill writes
# (templates.py fill work-file --path <file>), SE's hook holds every other write of it to, and
# `work_tickets.py file --body-file` files against the work template. scripts/templates.py's
# docstring owns this note's format.
name: work-file
version: 1.0.0
kind: document
reader: fleet
says: "A work issue's body file, `.se/issues/<name>.md`."
tags: ["issue", "work"]
extends: work
applies:
  actions: ["file.write"]
  paths: [".se/issues/*.md"]
example:
  fields:
    situation: "A body file can be written by hand."
    problem: "A hand-written body skips the template's fill."
    goal: "Only the fill writes a work issue's body file."
    approach: "The work-file template claims the file.\nNot picked: a review after filing, because it comes too late."
    package_kind: "standard"
    blocked_by: ["None"]
    user_requirement: "> The templater has its hands on a few things."
    requirements: ["The template claims the file.", "The hook refuses a direct edit."]
    acceptance: [{"done": false, "text": "A test edits the file and is refused."}]
    verification: "uv run pytest -q tests/test_se_templates.py"
---
