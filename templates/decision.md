---
# A decision note of a deck: deck.py's section rule, checked where deck.py checks it, at its
# build. scripts/templates.py's docstring owns this note's format.
name: decision
version: 1.0.0
kind: document
reader: owner
says: "A decision note: the situation and the problem before the options' pugh fence."
tags: ["decision"]
checker: deck:_explains
applies:
  actions: ["deck.build"]
  fallback: true
adapter:
  sections: true
  when: deck:_holds_pugh
  result: truth
  refusal: write `## Current situation` and `## The problem`, in that order, before the `pugh` fence, as deck.py's SECTIONS and the decision skill's note shape say
---
