---
name: flake-at-base
description: 'How to tell a flake from your own failure: rerun the one test at the integration branch with a high repeat count. Load it before treating a red test as yours.'
---
<!-- Generated from guidance/pull-request/field-report/flake-at-base.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

A failing test is yours only once it passes at base. Before treating it as your own, rerun that
one test at the integration branch with a high repeat count: `go test -count=500 -run <test>` for
Go, the test in a loop of as many runs for Python. One that fails there too is a flake already at
base; name it, with both counts, in the field report.
