---
# One requirement: one checkable statement, then its Acceptance and Source lines. A list whose
# field names it (`items: requirement@1.0.0`) holds one per item, its first line the statement;
# a template node of a template manifest names it with `template: requirement@1.0.0`.
# scripts/templates.py's docstring owns this note's format.
name: requirement
version: 1.0.0
kind: entry
reader: fleet
says: "One requirement: one checkable statement, how it is checked and where it comes from."
tags: ["requirement"]
rules:
  required: refuse
  checkable: refuse
fields:
  - name: statement
    kind: line
    source: title
    required: true
    checkable: true
    says: "One statement a test or a look can check: what is true once it is met."
  - name: acceptance
    kind: line
    label: Acceptance
    required: true
    says: "How it is checked: the test, the command or what a reader sees."
  - name: source
    kind: line
    label: Source
    required: true
    says: "Where it comes from: the user's words, a design note or an issue."
example:
  title: "The fill refuses a nested requirement without acceptance."
  fields:
    statement: "The fill refuses a nested requirement without acceptance."
    acceptance: "A test fills one and reads the refusal."
    source: "The user requirement of the work issue."
---
