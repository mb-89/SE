---
# The trailer every integration merge carries, the one source of its release kind
# (src/skills/work-model/SKILL.md "Release kind", templates/merge-message.md). Its schema is
# generated into scripts/interfaces/, which work_tickets.py release_trailer writes it through;
# RELEASE_TRAILER_PATTERN reads it. scripts/templates.py's docstring owns this note's format.
name: release-trailer
version: 1.0.0
kind: interface
reader: fleet
says: "An integration merge's release kind, its one trailer."
tags: ["message", "release"]
message: "Release-kind: {kind}"
applies:
  actions: ["message.send"]
  marker_pattern: "Release-kind: (patch|minor|major)"
rules:
  required: refuse
  choice: refuse
fields:
  - name: kind
    kind: choice
    required: true
    says: "patch, minor or major: the release the merge asks for."
    choices:
      - work_tickets:RELEASE_ORDER
example:
  fields:
    kind: minor
---
