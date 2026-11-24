---
# The comment the integrator writes on a work issue once it resumes a worker session that stopped on
# a usage limit, at most once per issue (docs/fleet.md "Fleet check"). Its schema is generated into
# scripts/interfaces/; limit_restart.py's remedy quotes the line written through it, and its
# RESTARTED finds it by its prefix. scripts/templates.py's docstring owns this note's format.
name: limit-restart
version: 1.0.0
kind: interface
reader: fleet
says: "A restart after a usage limit: the worker session the integrator resumed."
tags: ["message", "fleet"]
message: "Restarted after a usage limit: session {session}"
applies:
  actions: ["message.send"]
  marker_pattern: "Restarted after a usage limit: session .+"
rules:
  required: refuse
fields:
  - name: session
    kind: line
    required: true
    says: "The id of the resumed worker session."
example:
  fields:
    session: session_a
---
