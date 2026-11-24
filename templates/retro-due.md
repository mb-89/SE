---
# What `retro.py due` prints: one countdown line per kind, the retro's and the overhaul's. A
# snippet, which retro.py's countdown_lines fills and scripts/interfaces.py writes through the
# schema generated into scripts/interfaces/. scripts/templates.py's docstring owns this note's format.
name: retro-due
version: 1.0.0
kind: interface
reader: owner
says: "The retro and overhaul countdowns: per kind what it counted since where it starts, the days, and whether it is due or open."
tags: ["message", "retro"]
message: "retro: {retro_count} ({retro_landed} landed, {retro_failed} failed) {retro_start}, {retro_days} days; {retro_state}\noverhaul: {overhaul_count} retros closed {overhaul_start}, {overhaul_days} days; {overhaul_state}"
applies:
  actions: ["message.send"]
  marker_pattern: "retro: .+ days; .+"
rules:
  required: refuse
fields:
  - name: retro_count
    kind: line
    required: true
    says: "The retro's weighted count of what came back, digits alone."
  - name: retro_landed
    kind: line
    required: true
    says: "How many of those landed, digits alone."
  - name: retro_failed
    kind: line
    required: true
    says: "How many of those failed, digits alone."
  - name: retro_start
    kind: line
    required: true
    says: "Where it starts: since which retro started, and when, or in the whole history."
  - name: retro_days
    kind: line
    required: true
    says: "The days since its start, digits alone."
  - name: retro_state
    kind: line
    required: true
    says: "open with its open retros, due with its reason, or not due."
  - name: overhaul_count
    kind: line
    required: true
    says: "How many retros closed since its start, digits alone."
  - name: overhaul_start
    kind: line
    required: true
    says: "Where it starts: since which overhaul started, and when, or in the whole history."
  - name: overhaul_days
    kind: line
    required: true
    says: "The days since its start, digits alone."
  - name: overhaul_state
    kind: line
    required: true
    says: "open with its open overhauls, due with its reason, or not due."
example:
  fields:
    retro_count: "12"
    retro_landed: "10"
    retro_failed: "2"
    retro_start: "since #30 started 2026-11-01"
    retro_days: "23"
    retro_state: "due: 12 came back (due after 10)"
    overhaul_count: "2"
    overhaul_start: "in the whole history"
    overhaul_days: "40"
    overhaul_state: "not due"
---
