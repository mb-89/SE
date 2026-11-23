---
# The standing questions, asked alike by the retro, the overhaul and the field report: each one
# a section, its heading the question. The three templates nest this block; scripts/templates.py's
# docstring owns this note's format.
name: standing-questions
version: 1.0.0
kind: block
reader: fleet
says: "The standing questions every retro, overhaul and field report answers, one section each."
tags: ["retro", "field-report"]
rules:
  required: refuse
  duplicate: "off"
fields:
  - name: real_use
    kind: text
    required: true
    none_ok: true
  - name: machine_scripts
    kind: text
    required: true
    none_ok: true
  - name: port_or_remove
    kind: text
    required: true
    none_ok: true
  - name: stale_process
    kind: text
    required: true
    none_ok: true
  - name: not_produced
    kind: text
    required: true
    none_ok: true
  - name: shell_command
    kind: text
    required: true
    none_ok: true
  - name: promote_upstream
    kind: text
    required: true
    none_ok: true
  - name: failed_checks
    kind: text
    required: true
    none_ok: true
  - name: goes_well
    kind: text
    required: true
    none_ok: true
  - name: goes_badly
    kind: text
    required: true
    none_ok: true
  - name: thoughts_actions
    kind: text
    required: true
    none_ok: true
  - name: start_stop
    kind: text
    required: true
    none_ok: true
  - name: bad_output_cause
    kind: text
    required: true
    none_ok: true
example:
  fields:
    real_use: "None."
    machine_scripts: "None."
    port_or_remove: "None."
    stale_process: "None."
    not_produced: "None."
    shell_command: "None."
    promote_upstream: "None."
    failed_checks: "None."
    goes_well: "None."
    goes_badly: "None."
    thoughts_actions: "None."
    start_stop: "None."
    bad_output_cause: "None."
---

## What came back from real use since the last retro?

<!-- real_use: What the person or a real run sent back: a refusal, a failure, a request. In a field report: what came back from running the work for real. "None" where nothing applies. -->

## Which scripts did the AI write that a machine could own?

<!-- machine_scripts: Each ad hoc script or command line written more than once, and the component that could own it. "None" where nothing applies. -->

## Anything worth porting to other projects, or so bad we remove it?

<!-- port_or_remove: What other projects should take over, and what should go. "None" where nothing applies. -->

## Has the process gone stale?

<!-- stale_process: A step that no longer earns its cost, or a rule nobody follows. "None" where nothing applies. -->

## What would have stopped this from being produced at all?

<!-- not_produced: The check, gate or rule that would have prevented the waste before it was made. "None" where nothing applies. -->

## What did the shell do that a command could have done? Name it.

<!-- shell_command: Each shell sequence an SE command could run, by its name. "None" where nothing applies. -->

## Did anything local earn promotion upstream?

<!-- promote_upstream: A local helper, rule or note that belongs in SE or in kern. "None" where nothing applies. -->

## For each failed check, what rule would have caught it?

<!-- failed_checks: Each failed check or test, and the rule that would have caught it earlier. "None" where nothing applies. -->

## What goes well, and what makes it go well?

<!-- goes_well: What worked, and the cause that made it work. "None" where nothing applies. -->

## What goes badly, each with its moment in the log?

<!-- goes_badly: What went wrong, each with the log line, commit or comment where it shows. "None" where nothing applies. -->

## What do the thoughts say that the actions do not?

<!-- thoughts_actions: Where the reasoning and what was done part ways. "None" where nothing applies. -->

## Start, stop, keep, more, less.

<!-- start_stop: One line each: what to start, stop, keep, do more and do less. "None" where nothing applies. -->

## Which rule, prompt or tool made each bad output, and what change stops it?

<!-- bad_output_cause: Each bad output, the rule, prompt or tool behind it, and the change, with its target file. "None" where nothing applies. -->
