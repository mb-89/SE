---
# The single open handover issue, labelled handover, that SE writes when it closes a catch-up and
# reads when one starts (src/skills/catch-up/SKILL.md). Its schema is generated into
# scripts/interfaces/; the template gate checks every write of it. scripts/templates.py's docstring
# owns this note's format.
name: handover
version: 1.0.0
kind: interface
reader: fleet
says: "Where the work stands for the next session: state, open work, branches, parked decisions, how to resume."
tags: ["issue", "handover"]
applies:
  actions: ["issue.create", "issue.edit"]
  order: 15
  labels: ["handover"]
rules:
  required: refuse
  duplicate: refuse
fields:
  - name: title
    kind: line
    source: title
    required: true
    says: "Handover, then the day it was written: `Handover 2026-11-22`."
  - name: state
    kind: text
    heading: State
    required: true
    says: "What is integrated and released, and what runs now."
  - name: open_issues
    kind: issue
    heading: Open issues
    required: true
    none_ok: true
    says: "The open work and escalated issues, one a line with its name, or None."
  - name: branches
    kind: list
    heading: Running and unintegrated branches
    required: true
    none_ok: true
    says: "Each branch with a running session or not yet integrated, and its state, or None."
  - name: decisions
    kind: list
    heading: Parked decisions
    required: true
    none_ok: true
    says: "Each decision waiting on the person, with its decision note, or None."
  - name: resume
    kind: text
    heading: How to resume
    required: true
    says: "The first steps the next session takes, in order."
example:
  fields:
    title: Handover 2026-11-22
    state: "Everything delivered is integrated; the last release is tagged."
    open_issues:
      - "#12 the templates engine"
    branches:
      - "templates-interfaces: delivered, waiting for its landing"
    decisions:
      - None
    resume: "Start the integrator on the delivered pull request, then catch up."
---
