---
# A decision note of a deck: its sections, then its options node, the pugh block, as deck.py's
# build and the decision skill's note shape read it. deck.py reads its sections before the fence
# from here. scripts/templates.py's docstring owns this note's format.
name: decision
version: 2.0.0
kind: document
reader: owner
says: "A decision note: the situation, the problem and what others do, then the options' pugh fence."
tags: ["decision"]
applies:
  actions: ["deck.build"]
  marker_pattern: "(`{3,}|~{3,})[ \\t]*pugh[ \\t]*"
rules:
  required: refuse
fields:
  - name: situation
    kind: text
    required: true
    exact_heading: true
  - name: problem
    kind: text
    required: true
    exact_heading: true
  - name: others
    kind: text
    required: true
    exact_heading: true
  - name: options
    node: pugh@1.0.0
    fence: pugh
    required: true
    says: "The options as obs's `pugh` fence, after the sections: the criteria, then every option with its marks."
example:
  fields:
    situation: "Today each decision is a table in a chat message, answered in the chat."
    problem: "A chat table dies with the session that showed it."
    others: "Decision records keep one file per decision."
    options: "```pugh\ncriteria:\n  - {key: record, label: The record survives, weight: 1, better: higher, kind: judged}\ndatum: {prefer: [chat]}\ncandidates:\n  - {key: deck, label: A deck, what: One note per decision., marks: {record: 1}, wins: Kept., losses: Built.}\n  - {key: chat, label: The chat, what: A table per message., marks: {record: 0}, wins: Known., losses: Lost.}\n```"
---

## Current situation

<!-- situation: What exists today and who uses it; the first sentence names the class the case belongs to. -->

## The problem

<!-- problem: What is wrong with it, and what shows it: a failure, a measurement, the person's words. -->

## What others do

<!-- others: How at least two outside tools, products or conventions solve the same problem, each with a concrete example. -->
