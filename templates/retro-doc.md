---
# The line a retro report ends in that links its committed retro doc at a commit (retro.py
# `report`); the next collect and overhaul read it back by retro.py's DOC_PATTERN, which takes a
# full commit only. Its schema is generated into scripts/interfaces/, which retro.py writes it
# through. scripts/templates.py's docstring owns this note's format.
name: retro-doc
version: 1.0.0
kind: interface
reader: fleet
says: "A retro report's link to its committed retro doc: the commit and the doc's path in the checkout."
tags: ["message", "retro"]
message: "<!-- se:retro-doc {sha} {path} -->"
applies:
  actions: ["message.send"]
  marker_pattern: "<!-- se:retro-doc .+ .+ -->"
rules:
  required: refuse
fields:
  - name: sha
    kind: line
    required: true
    says: "The integration branch's commit that holds the retro doc, its full 40 hex digits."
  - name: path
    kind: line
    required: true
    says: "The retro doc's path in the checkout, with forward slashes and no space."
example:
  fields:
    sha: "0123456789abcdef0123456789abcdef01234567"
    path: docs/retro-30.md
---
