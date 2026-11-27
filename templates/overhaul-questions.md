---
# The overhaul's own questions, after the standing questions: each one a section, its heading the
# question. The overhaul template nests this block; scripts/templates.py's docstring owns this
# note's format. Each question names the facts `overhaul.py facts` computes for it, or why
# judgment alone answers it (scripts/overhaul.py QUESTION_FACTS); `facts` fails where one names neither.
name: overhaul-questions
version: 1.1.0
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
  - name: doors
    kind: text
    required: true
    none_ok: true
  - name: door_tests
    kind: text
    required: true
    none_ok: true
  - name: superfluous_tests
    kind: text
    required: true
    none_ok: true
  - name: slowest_tests
    kind: text
    required: true
    none_ok: true
  - name: long_files
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
    doors: "None."
    door_tests: "None."
    superfluous_tests: "None."
    slowest_tests: "None."
    long_files: "None."
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

## Are there enough doors, and does any code reach around one?

<!-- doors: Each outside thing without a door, and each reach around a declared one, with where it belongs. "None" where nothing applies. -->

## Is each door tested once, in its contract, and faked everywhere else?

<!-- door_tests: Each door tested against the real thing outside its contract, or with no contract, and each test that starts a process it could fake. "None" where nothing applies. -->

## Which tests are superfluous, duplicated or over-broad?

<!-- superfluous_tests: Each test that repeats another's lines or runs far more than it asserts, and what to prune, especially in the big battery. "None" where nothing applies. -->

## Which test files are slowest, and what makes them slow?

<!-- slowest_tests: Each of the slowest files, what its time goes to, and how to cut it. "None" where nothing applies. -->

## Does every file over 1,000 lines do one job on one abstraction level?

<!-- long_files: Each file over 1,000 lines, the jobs it does, whether its stated reason still holds, and which part is fundamental and belongs in Go or in a module of its own. "None" where nothing applies. -->
