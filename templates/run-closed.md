---
# The one message a retro or an overhaul sends SE's session once its report is posted and its issue
# closed (src/agents/retro.md step 6). Its schema is generated into scripts/interfaces/; no code
# sends it, as kern's door offers no command that does. scripts/templates.py's docstring owns this
# note's format.
name: run-closed
version: 1.0.0
kind: interface
reader: fleet
says: "A retro's or an overhaul's hand-back: the run's kind and issue number and its report's link."
tags: ["message", "retro", "overhaul"]
message: "{kind} #{number} closed: {link}"
applies:
  actions: ["message.send"]
  marker_pattern: "(retro|overhaul) #.+ closed: .+"
rules:
  required: refuse
  choice: refuse
fields:
  - name: kind
    kind: choice
    required: true
    says: "retro or overhaul: the run that closed."
    choices:
      - retro
      - overhaul
  - name: number
    kind: line
    required: true
    says: "The run's issue number, digits alone."
  - name: link
    kind: line
    required: true
    says: "The link of the report the run posted."
example:
  fields:
    kind: retro
    number: "30"
    link: "https://example.com/issues/30#issuecomment-1"
---
