---
name: python-ad-hoc-go-system
description: 'Python for ad hoc work, Go for what is part of the system: where new code goes, and when to port. Read it before you write a script, a component or a port.'
---

The person's principle of 22 Nov:

> Python is always the ad hoc stuff when we just write scripts, and then when we want it in our
> system, we should have a tendency to port it to Go just because it's faster, right?

- **Ad hoc is Python.** A script an agent writes while working, or an ad hoc component under
  `.se/components/`, is Python and stays untracked
  ([gen-001](../src/skills/work-model/references/rules.md#gen-001-mechanize-first)).
- **The system tends to Go.** What the system keeps, a component under `components/` or in kern,
  is written in Go, and a Python part that becomes part of the system is ported, also where a
  larger change touches it anyway. Go starts in milliseconds and its types carry the checks
  (the guidance note `parse-dont-validate`).
- **Held to one set of cases.** A port keeps the Python answers: one set of cases, which the
  Python code writes and the Go code passes word for word, until the Python path is retired.
  SE's template engine is the first so held: SE's `components/README.md`, its section "The
  template engine in Go".
- **Python stays where it wraps Python.** pytest, the overhaul's facts from Python's syntax tree,
  and what renders a page or a deck stay Python; SE's `docs/go-core.md` "Scripts are ad hoc,
  components are long-term" owns that table.

Not picked: porting only where measured budgets demand it, since every component then stays in the
language it happened to start in.
