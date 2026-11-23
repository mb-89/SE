---
# The overhaul's own questions, after the standing questions: each one a section, its heading the
# question. The overhaul template nests this block; scripts/templates.py's docstring owns this
# note's format.
name: overhaul-questions
version: 1.0.0
kind: block
reader: fleet
says: "The questions an overhaul asks beside the standing questions, one section each."
tags: ["overhaul"]
rules:
  required: refuse
  duplicate: "off"
fields:
  - name: voice_style
    kind: text
    required: true
    none_ok: true
  - name: best_method
    kind: text
    required: true
    none_ok: true
  - name: guidance_drift
    kind: text
    required: true
    none_ok: true
  - name: file_earns_place
    kind: text
    required: true
    none_ok: true
  - name: design_pattern
    kind: text
    required: true
    none_ok: true
  - name: outside_world
    kind: text
    required: true
    none_ok: true
example:
  fields:
    voice_style: "None."
    best_method: "None."
    guidance_drift: "None."
    file_earns_place: "None."
    design_pattern: "None."
    outside_world: "None."
---

## Are the prose and the code still in the voice and style we hold?

<!-- voice_style: Where the prose or the code strays from the house voice and style, by file. "None" where nothing applies. -->

## Is the method still the best we know?

<!-- best_method: The method against the best known alternative, and which wins. "None" where nothing applies. -->

## Has the guidance drifted from what the machines do?

<!-- guidance_drift: Each place the guidance says one thing and the code does another. "None" where nothing applies. -->

## Does every file earn its place?

<!-- file_earns_place: Each file that does not, and what to do with it. "None" where nothing applies. -->

## Would a named design pattern improve us?

<!-- design_pattern: The pattern, where it applies and what it would replace. "None" where nothing applies. -->

## What does the outside world do, and what can we learn from it?

<!-- outside_world: What comparable projects and tools do, and what of it we should take. "None" where nothing applies. -->
