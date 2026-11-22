---
# The owner's ticket schema: a title that is a name under the name rule, then Situation, Problem,
# Goal, Approach, Steps, Check and an optional Depends on. scripts/templates.py's docstring owns this
# file's format.
name: ticket
version: 1.0.0
kind: document
reader: owner
says: "An issue the owner reads: what is, what is wrong, what should be, how, and how we know."
tags: ["issue"]
applies:
  actions: ["issue.create", "issue.edit"]
  order: 30
rules:
  required: refuse
  choice: refuse
  not-picked: refuse
  duplicate: refuse
  dangling: refuse
  words: warn
  actor: warn
  one-sentence: warn
  bare-number: warn
  board: warn
  terms: warn
  unnamed-entry: warn
  title-shape: warn
actors: ["owner", "SE", "integrator", "worker", "reviewer", "CI", "the person", "everyone"]
fields:
  - name: title
    kind: line
    source: title
    required: true
    shape: work_tickets:name_refusal
    says: "The name: 1 to 5 lowercase words joined by dashes, such as `branch-cleanup-on-pr-close`; never repeated in the body."
  - name: situation
    kind: text
    required: true
    max_words: 120
  - name: problem
    kind: text
    required: true
    max_words: 120
  - name: goal
    kind: text
    required: true
    max_words: 120
  - name: approach
    kind: text
    required: true
    max_words: 160
    not_picked: true
  - name: steps
    kind: list
    numbered: true
    required: true
    actor: true
    one_sentence: true
  - name: check
    kind: list
    required: true
    actor: true
  - name: depends_on
    kind: issue
    none_ok: true
example:
  title: plain-issue-titles
  fields:
    title: plain-issue-titles
    situation: Issues are titled by their branch name.
    problem: The owner cannot tell from the list what an issue changes.
    goal: Every issue title says in plain words what changes.
    approach: "SE writes the title from the Goal.\nNot picked: a separate summary field, because the title is what the list shows."
    steps: ["SE writes the plain title when it files an issue.", "The worker keeps it."]
    check: ["The owner reads the issue list and understands each title."]
    depends_on: ["None"]
---

## Situation

<!-- situation: What is true today, as someone who has not followed the work would see it. -->

## Problem

<!-- problem: What goes wrong because of it, and for whom. -->

## Goal

<!-- goal: What is true once this is done, the outcome a person sees. -->

## Approach

<!-- approach: How it is done, then a line `Not picked:` naming the alternative and why not. -->

## Steps

<!-- steps: The steps in order, one sentence each, each naming who takes it. -->

## Check

<!-- check: How someone sees that it works, one item per check, each naming who checks. -->

## Depends on

<!-- depends_on: The issues that must be done first, each linked and named, or None. -->
