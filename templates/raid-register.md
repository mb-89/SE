---
# A RAID register, an issue of its own that carries <!-- se:raid --> or this template's marker:
# what it covers, then its entries, each one a raid-entry document. It claims no path, as none of
# SE's own templates does. scripts/templates.py's docstring owns this note's format.
name: raid-register
version: 1.0.0
kind: document
reader: owner
says: "A RAID register: its risks, assumptions, issues and dependencies, one raid-entry each."
tags: ["register", "raid"]
applies:
  actions: ["issue.create", "issue.edit"]
  order: 40
  marker: <!-- se:raid -->
rules:
  required: refuse
fields:
  - name: scope
    kind: text
    required: true
  - name: entries
    entries: raid-entry@1.0.0
    required: true
example:
  fields:
    scope: "The risks, assumptions, issues and dependencies of the next release."
    entries: "### The release slips\n\nType: risk\nOwner: alice\nStatus: open\n\n#### Text\n\nThe release slips a week where the review queue stays full.\n\n### The mirror stays up\n\nType: assumption\nOwner: bob\nStatus: watched\n\n#### Text\n\nThe package mirror answers during the release."
---

## Scope

<!-- scope: What the register covers: the project, the release or the piece of work. -->

## Entries

<!-- entries: One heading per entry, `### <name>`, then its Type, Owner and Status lines and its `#### Text`. -->
