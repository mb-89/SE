---
# A decision's Pugh matrix, obs's `pugh` fence: the block the decision template's options node
# names. deck.py's pugh_problems checks what SE asks of it; obs checks the rest at its build (obs's
# spec/capabilities/pugh-decisions.md). scripts/templates.py's docstring owns this note's format.
name: pugh
version: 1.0.0
kind: block
reader: owner
says: "A Pugh matrix in obs's `pugh` fence: weighted criteria and at least two options."
tags: ["decision"]
checker: deck:pugh_problems
adapter:
  result: problems
---
