---
# One entry of a RAID register: its type, owner and status lines, then its text. The register
# template's entries node names it. scripts/templates.py's docstring owns this note's format.
name: raid-entry
version: 1.0.0
kind: entry
reader: owner
says: "One RAID entry: a risk, an assumption, an issue or a dependency, with its owner and status."
tags: ["register", "raid"]
rules:
  required: refuse
  choice: refuse
fields:
  - name: type
    kind: choice
    label: Type
    required: true
    says: "risk, assumption, issue or dependency."
    choices:
      - risk
      - assumption
      - issue
      - dependency
  - name: owner
    kind: line
    label: Owner
    required: true
    says: "Who answers for the entry."
  - name: status
    kind: choice
    label: Status
    required: true
    says: "open, watched or closed."
    choices:
      - open
      - watched
      - closed
  - name: text
    kind: text
    required: true
example:
  fields:
    type: risk
    owner: alice
    status: open
    text: "The release slips a week where the review queue stays full."
---

## Text

<!-- text: What the entry says: the risk and its effect, the assumption, the issue or what it depends on. -->
