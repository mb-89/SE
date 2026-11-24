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
