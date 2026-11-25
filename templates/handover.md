---
# The handover, the untracked file .se/handover.md in the main checkout of a local device, that SE
# writes when it closes a catch-up and its next start on that machine reads
# (src/skills/catch-up/SKILL.md, scripts/se_start.py). It is never committed and never filed; a cloud
# session writes none. scripts/templates.py's docstring owns this note's format.
name: handover
version: 2.0.0
kind: document
reader: fleet
says: "Where the work stands for the next session on this machine: state, open work, branches, parked decisions, how to resume."
tags: ["handover"]
applies:
  actions: ["file.write"]
  paths: [".se/handover.md"]
rules:
  required: refuse
  duplicate: refuse
fields:
  - name: state
    kind: text
    required: true
  - name: open_issues
    kind: issue
    required: true
    none_ok: true
  - name: branches
    kind: list
    required: true
    none_ok: true
  - name: decisions
    kind: list
    required: true
    none_ok: true
  - name: resume
    kind: text
    required: true
example:
  fields:
    state: "Everything delivered is integrated; the last release is tagged."
    open_issues:
      - "#12 the templates engine"
    branches:
      - "templates-interfaces: delivered, waiting for its landing"
    decisions:
      - None
    resume: "Start the integrator on the delivered pull request, then catch up."
---
## State

<!-- state: What is integrated and released, and what runs now, with the day it was written. -->

## Open issues

<!-- open_issues: The open work and escalated issues, one a line with its name, or None. -->

## Running and unintegrated branches

<!-- branches: Each branch with a running session or not yet integrated, and its state, or None. -->

## Parked decisions

<!-- decisions: Each decision waiting on the person, with its decision note, or None. -->

## How to resume

<!-- resume: The first steps the next session takes, in order. -->
