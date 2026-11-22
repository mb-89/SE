---
# A routed outside issue: only the routing block `route` appends after the handled marker is
# checked; everything above it is the outside author's data. scripts/templates.py's docstring owns
# this note's format.
name: routed
version: 1.0.0
kind: block
reader: fleet
says: "The routing block SE appends to an outside issue: where it came from and what it lacks."
tags: ["issue", "outside"]
keep_unknown: true
applies:
  actions: ["issue.create", "issue.edit"]
  order: 10
  marker: <!-- se:handled -->
scope:
  after: <!-- se:handled -->
  section: Routing
  level: 3
rules:
  required: refuse
  choice: refuse
  duplicate: refuse
  dangling: refuse
  words: warn
  board: warn
  unnamed-entry: warn
fields:
  - name: routed_from
    kind: line
    label: Routed from
    required: true
    says: The outside issue's original title.
  - name: goal
    kind: text
  - name: package_kind
    kind: choice
    choices:
      - standard
      - discovery
      - breaking
      - patch
      - minor
      - major
      - work_tickets:RELEASE_KINDS
  - name: blocked_by
    kind: issue
    none_ok: true
  - name: user_requirement
    kind: text
    verbatim: true
  - name: design_owner
    kind: text
  - name: requirements
    kind: list
    numbered: true
  - name: acceptance
    kind: checklist
  - name: verification
    kind: code
example:
  title: feat/outside-idea-20261116
  fields:
    routed_from: "Proposal: make the example work"
    package_kind: standard
    requirements: ["The example works."]
    acceptance:
      - done: false
        text: A test runs the example.
---

### Goal

<!-- goal: The outcome, where the outside issue does not say it. -->

### Package kind

<!-- package_kind: standard, discovery (read-only research), breaking (a major release), or a kind of work, as `route --type` takes it. -->

### Blocked by

<!-- blocked_by: The issues that must be closed first, one per line, or None. -->

### User requirement (verbatim)

<!-- user_requirement: The user's words, quoted exactly. -->

### Design owner

<!-- design_owner: The files and sections that own the decided behaviour. -->

### Requirements

<!-- requirements: Numbered, checkable requirements the outside issue lacks. -->

### Acceptance

<!-- acceptance: Checkable items with the evidence expected. -->

### Verification

<!-- verification: The focused tests and real commands to run. -->
