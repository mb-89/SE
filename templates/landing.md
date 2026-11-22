---
# The landing pull request `integrate` opens: the lines work_tickets.py's landing_description
# writes. scripts/templates.py's docstring owns this note's format.
name: landing
version: 1.0.0
kind: document
reader: fleet
says: "A landing pull request: it names the work issue, the work pull request and its report."
tags: ["pull-request", "landing"]
applies:
  actions: ["pr.create", "pr.edit"]
  base: integration
  marker_pattern: <!-- se:field-report-in \d+ -->
  order: 10
adapter:
  lines:
    - first: true
      pattern: Refs https?://\S+/issues/\d+
      says: the first line is `Refs <work issue url>`, as landing_description writes it
    - pattern: Lands https?://\S+/pull/\d+, whose description is the field report\.
      says: a line `Lands <work pull request url>, whose description is the field report.`
    - pattern: <!-- se:field-report-in \d+ -->
      says: the line `<!-- se:field-report-in <work pull request number> -->`, CI's field-report step reads it
---
