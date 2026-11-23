---
name: parse-dont-validate
description: 'Parse, do not validate: a value is checked once, when its type is made, and relied on afterwards. Read it before you add a type, a check of a value, or a target that takes one.'
tags: [work]
---
<!-- Generated from guidance/parse-dont-validate.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

The person's principle of 22 Nov, for every type, not only templates:

> So pass, don't validate is something we should always do. We have these types that get created
> once, and then we can rely on the type to be correct.

- **One constructor checks.** A value that must hold a rule gets a type of its own, and the one
  function that makes that type checks the rule. A value it refuses is never made.
- **Nothing else constructs it.** The type's fields are private to its package, so code elsewhere
  holds only a value the constructor made, or the zero value, which every target refuses. Where the
  value crosses a process, it carries proof of its maker that decoding verifies.
- **Targets take the type, never the raw value.** A function, verb or tool that needs a checked
  value takes that type, so the compiler or the bus refuses anything else; it never re-checks the
  value, and never accepts a text and checks it after the fact.
- **A refusal names the constructor.** Where a target refuses a value of another type, it says which
  constructor makes the one it takes.

The filled template is the first such type: SE's design of its templates, `docs/templates.md`,
its section "The filled template is a type".

Not picked: checking a value where it is used, as SE's filing commands and its gate still check a
text after it is written, since every path the check does not see bypasses it.
