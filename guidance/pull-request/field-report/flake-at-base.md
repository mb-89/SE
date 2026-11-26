---
name: flake-at-base
description: 'How to diagnose a failing test without excusing it: repeat the test at the integration branch, then fix the red check before delivery.'
---

Every failed test, including one reproduced at the integration branch, is a failure to fix; deliver
only when checks report zero failures, zero errors and zero warnings. Right: repeat the test at base
to diagnose it (`go test -count=500 -run <test>` for Go, or a loop for Python), then fix it. Wrong:
"fails at base too, so the branch is fine"—no base failure is an acceptable state.
