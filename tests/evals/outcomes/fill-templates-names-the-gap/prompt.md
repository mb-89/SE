---
schema_version: "1.0"
name: fill-templates-names-the-gap
description: Asked to fill a template from raw notes that lack one mandatory section, the agent fills what the notes hold and names the section they cannot fill instead of inventing it.
tags: [fill-templates]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: One reply with the label spec's sections, Product and Warnings from the notes, and Languages named as not in the material, no language invented.
---

Write me a label spec. The template is label-spec, below; my raw data is the two notes below.

```text
templates/label-spec.md
---
name: label-spec
version: 1.0.0
kind: document
tags: ["label"]
reader: owner
says: "A product label's specification: what the label shows and the warnings it carries."
applies:
  actions: ["file.write"]
  paths: ["documents/label-*.md"]
fields:
  - name: product
    kind: text
    required: true
  - name: warnings
    kind: text
    required: true
  - name: languages
    kind: text
    required: true
---

## Product

<!-- product: What the product is and who uses it. -->

## Warnings

<!-- warnings: Each warning the label carries, with the reason it is there. -->

## Languages

<!-- languages: The languages the label is printed in. -->
```

```text
material/pump-brief.md
# Pump X

Pump X is a 230 V garden pump for home owners. It runs on mains power only.
```

```text
material/safety-review.md
# Safety review

- The housing gets hot after an hour of running: warn against touching it.
- Water and mains power: warn to unplug the pump before cleaning it.
```

This run has no shell and no file tools beyond Read; the text above is all there is. Reply with
the document you would write, section by section, and name every section the notes cannot fill.
