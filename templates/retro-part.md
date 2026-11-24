---
# The label each part of a retro report too long for one comment ends in (retro.py `parts`). Its
# schema is generated into scripts/interfaces/, which retro.py writes it through.
# scripts/templates.py's docstring owns this note's format.
name: retro-part
version: 1.0.0
kind: interface
reader: owner
says: "The label a part of a split retro report ends in: which part of how many, of which retro's report."
tags: ["message", "retro"]
message: "_Part {index} of {total} of the report of retro #{number}._"
applies:
  actions: ["message.send"]
  marker_pattern: "_Part .+ of .+ of the report of retro #.+\\._"
rules:
  required: refuse
fields:
  - name: index
    kind: line
    required: true
    says: "The part's number, from 1, digits alone."
  - name: total
    kind: line
    required: true
    says: "How many parts the report is posted in, digits alone."
  - name: number
    kind: line
    required: true
    says: "The retro issue's number, digits alone."
example:
  fields:
    index: "2"
    total: "3"
    number: "30"
---
