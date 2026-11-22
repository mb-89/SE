---
# The review comment `review.py file` posts: its JSON block, checked by review.py's own
# checked_report. scripts/templates.py's docstring owns this note's format.
name: review
version: 1.0.0
kind: document
reader: fleet
says: "A cold review's one comment: what a person reads, then the JSON block the retro reads."
tags: ["review"]
checker: review:checked_report
applies:
  actions: ["comment.create", "comment.edit"]
  marker: <!-- se:review -->
  order: 10
adapter:
  json_after: <!-- se:review -->
  # what verdict_data adds beside the report
  drop:
    ".": ["pull", "landed"]
  result: raises
---
