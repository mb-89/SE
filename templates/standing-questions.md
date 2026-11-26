---
# The standing questions, asked alike by the retro, the overhaul and the field report: each one
# a section, its heading the question. The three templates nest this block; scripts/templates.py's
# docstring owns this note's format. The last three, the tooling questions, are the owner's of 26 Nov:
# "all agents that provide a field report, no matter what they use, need to answer that"; every role
# answers them in every report, in any project, and "None" does not answer them.
name: standing-questions
version: 2.0.0
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
  - name: longest
    kind: text
    required: true
  - name: wished_tool
    kind: text
    required: true
  - name: tooling_starfish
    kind: text
    required: true
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
    longest: "Waiting 40 minutes for the full suite, as no command ran only the tests of the change."
    wished_tool: "In SE: a command that runs the tests a diff touches."
    tooling_starfish: "Start: run the touched tests first. Stop: nothing. Keep: the commit hooks. More: refusals that name their fix. Less: hand-written shell sequences."
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

<!-- goes_badly: All friction, including waiting, polling, limited tooling, workarounds and retries, even when resolved: each with its log line, commit or comment, impact and outcome. Explain any polling fallback: no event interface, its narrow scope and bounds. "None" only when there truly was none. -->

## What do the thoughts say that the actions do not?

<!-- thoughts_actions: Where the reasoning and what was done part ways. "None" where nothing applies. -->

## Start, stop, keep, more, less.

<!-- start_stop: One line each: what to start, stop, keep, do more and do less. "None" where nothing applies. -->

## Which rule, prompt or tool made each bad output, and what change stops it?

<!-- bad_output_cause: Each bad output, the rule, prompt or tool behind it, and the change, with its target file. "None" where nothing applies. -->

## What took the longest, and why?

<!-- longest: The step that took the most time in this run, how long it took, and its cause. Always answered: there is always a longest step. -->

## What tool did you wish was present: in SE, kern, the project, or anything outside our tooling?

<!-- wished_tool: Each tool, command, helper, data field or template whose presence would have made this run short, and where it belongs: SE, kern, the project, or something outside our tooling to add to it. Name each other place where the same gap probably costs time. Always answered: say where nothing was missing and why. -->

## Tooling starfish: what should our tooling start, stop, keep, do more of and do less of? Removals count too.

<!-- tooling_starfish: One line each for our tooling (SE, kern, the project's own and anything we use beside them): start, stop, keep, more and less, a removal among them where something should go. Always answered. -->
