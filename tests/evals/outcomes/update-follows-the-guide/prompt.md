---
schema_version: "1.0"
name: update-follows-the-guide
description: After the update command, SE follows the upgrade guide's sections it printed in their order and reports once what moved.
tags: [update]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: One reply that names what moved and the guide's sections in the order printed, SE 13 before obs 11, and no command it did not run.
---

/se:update

The update already ran in this session's checkout; this is what it printed:

```text
SE update of project
Checkout: main current with origin/main
SE: 12.0.1 -> v13.0.0
obs: pin ^10.3.2 -> ^11.0.0 (se.toml; commit it)
obs: 10.3.2 -> 11.0.0 (se.lock; commit it)
Upgrade guide: follow 2 sections in this order, every step and then its check, and commit after each:

## SE 13

### A breaking release needs its upgrade section

- **Steps:** none for a project.
- **Check:** none.

## obs 11

### Styles are components

- **Steps:** none for a project that names no style.
- **Check:** none.
```

This run has no shell and no GitHub tools; the output above is all there is. Report what moved
and which sections you followed, in their order.
