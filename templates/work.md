---
# A work issue: one package for one worker, its title a name under the name rule and its branch
# that name. It extends the ticket template; scripts/templates.py's docstring owns this note's format.
name: work
version: 1.1.0
kind: document
reader: fleet
says: "One package for one worker: the ticket's why, then numbered requirements and acceptance."
tags: ["issue", "work"]
extends: ticket
remove: ["steps", "check", "depends_on"]
order:
  - title
  - situation
  - problem
  - goal
  - approach
  - base_branch
  - reproduction
  - package_kind
  - blocked_by
  - user_requirement
  - design_owner
  - requirements
  - changes_after_filing
  - file_ownership
  - acceptance
  - owner_step
  - verification
applies:
  actions: ["issue.create", "issue.edit"]
  order: 20
  labels: ["work"]
rules:
  terms: "off"
  bare-number: "off"
  first-sentence: warn
fields:
  - name: title
    kind: line
    source: title
    required: true
    shape: work_tickets:name_refusal
    says: "The name, its branch too: 1 to 5 lowercase words joined by dashes, such as `branch-cleanup-on-pr-close`."
  - name: goal
    kind: text
    required: true
    max_words: 120
    first_sentence_chars: 120
  - name: base_branch
    kind: line
  - name: reproduction
    kind: text
  - name: package_kind
    kind: choice
    choices:
      - standard
      - discovery
      - breaking
      - patch
      - minor
      - major
      - work_tickets:RELEASE_KINDS
  - name: blocked_by
    kind: issue
    exact_heading: true
    required: true
    none_ok: true
  - name: user_requirement
    kind: text
    verbatim: true
  - name: design_owner
    kind: text
  - name: requirements
    items: requirement@1.0.0
    carried: ["acceptance", "source"]
    since: 1.1.0
    exact_heading: true
    numbered: true
    required: true
  - name: changes_after_filing
    kind: list
    numbered: true
    continue_numbers: true
    markers: true
  - name: file_ownership
    kind: text
  - name: acceptance
    kind: checklist
    required: true
  - name: owner_step
    kind: list
  - name: verification
    kind: code
    required: true
example:
  title: plain-titles
  fields:
    title: plain-titles
    situation: Issues are titled by their branch name.
    problem: The owner cannot tell from the list what an issue changes.
    goal: Every issue title says in plain words what changes.
    approach: "SE writes the title from the Goal.\nNot picked: a separate summary field, because the title is what the list shows."
    package_kind: standard
    blocked_by: ["None"]
    user_requirement: "> Titles I can read."
    requirements: ["`file` writes the plain title.", "`route` keeps it."]
    acceptance:
      - done: false
        text: A test files an issue and reads its title.
    verification: uv run pytest -q tests/test_issue_creation.py
---

## Goal

<!-- goal: What is true once this is done, the outcome a person sees. It should take two to four sentences and shall stay within 120 words. Its first sentence, one complete statement of at most 120 characters, becomes the landing title. -->

## Base branch

<!-- base_branch: The branch the work starts from, where it is not the integration branch. -->

## Reproduction

<!-- reproduction: For a finding from a field report: the report linked, the command and its output verbatim. -->

## Package kind

<!-- package_kind: standard, discovery (read-only research), breaking (a major release, minor below 1.0.0), or a kind of work, as `route --type` takes it. -->

## Blocked by

<!-- blocked_by: The issues that must be closed first, one `#n` or link per line, or None. -->

## User requirement (verbatim)

<!-- user_requirement: The user's words, quoted exactly. -->

## Design owner

<!-- design_owner: The files and sections that own the decided behaviour. -->

## Requirements

<!-- requirements: Numbered requirements in the order to do them, each one checkable statement (the requirement template); the Acceptance section carries how each is checked. -->

## Changes after filing

<!-- changes_after_filing: Requirements added after filing, numbered after the last; review open points keep their markers. -->

## File ownership

<!-- file_ownership: Where parallel packages share files: who owns each shared file. -->

## Acceptance

<!-- acceptance: Checkable items with the evidence expected. -->

## Owner step

<!-- owner_step: Steps only the owner takes, one item each. -->

## Verification

<!-- verification: The focused tests and real commands to run. -->
