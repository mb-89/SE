---
name: discover-cheap-load-late
description: 'Progressive disclosure and lazy loading: what a command or module is comes from its declaration alone, and its code loads on first use. Read it before you add, list or rewrite a command, a component or a module.'
---
<!-- Generated from guidance/discover-cheap-load-late.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

The person's principle of 22 Nov, for every module and every rewrite: a utility with 200 commands
does not block at its start for the 199 it does not run.

- **Discover cheaply.** What a command or a module is (its name, summary, usage and kind) is
  written in its declaration: a component's `component.toml`, a skill's or a guidance note's front
  matter. Whatever lists, helps or offers reads the declarations alone and never imports, runs or
  starts what it lists.
- **Load late.** The code, the process or the body loads when it is first used, once: a command's
  module when that command runs, a component's process at its first call or first changed input.
- **Generating is not discovering.** A command that writes a declaration from code
  (`work_tickets.py docs`) may load that code; nothing that reads the declaration may.
- **The cost is flat.** A listing pays one read per declaration, never one load per entry, so its
  budget holds however many commands there are.

Not picked: loading everything at start and making it faster, since the cost then still grows with
every command.

## Its checks

Each module holds its listings to one budget, with a test over many fixture entries whose code
trips when it is loaded: each fixture's module records that it ran. The test fails on any record,
naming the entry, and on a listing slower than the budget. A discovery that loads what it lists
thus fails, however fast its machine.

- **SE:** `tests/test_discovery_budget.py` holds `se_components.py commands`, SE's command list
  from the declarations, to the numbers below. A person waits on a listing, so it answers within
  the interactive class's second, the interpreter's start included.
- **kern and obs** hold their own listings to the same numbers in their suites: kern's `help`,
  `mcp --tools` and `components list`, obs's `components list`.

```implements tests/discovery-budget.toml
# The discovery budget (guidance note discover-cheap-load-late): fixture components, the commands
# each declares, and the seconds a listing of all of them may take, the interpreter's start included.
components = 200
commands_per_component = 5
budget_seconds = 1.0
```

The places that load eagerly today, each with the package that changes it, are the inventory of
[docs/go-core.md "Discover cheaply, load late"](../../../docs/go-core.md#discover-cheaply-load-late).
