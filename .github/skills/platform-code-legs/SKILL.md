---
name: platform-code-legs
description: 'How a branch that changes platform code is delivered: after its own kern-platforms legs pass, linked in the field report. Load it before delivering a branch that touches code Windows or macOS runs differently.'
---
<!-- Generated from guidance/pull-request/field-report/platform-code-legs.md by scripts/se_plugin.py; edit the source and run `python scripts/se_plugin.py build`. -->

Code that Windows or macOS runs differently is tested only by the CI job `kern-platforms`, on
Windows, and a worker cannot run it; darwin is built, not tested. Such code is `*_windows.go`,
`*_darwin.go`, `//go:build` tags, `runtime.GOOS`, `sys.platform` or `os.name` branches, `.ps1`
files, and the start and hook scripts `kern-platforms` runs.

- Push the branch and open its work pull request first (`deliver`, or without gh its steps), but
  do not notify the integrator yet.
- Wait until that pull request's own `kern-platforms` legs are green. Fix a red leg on the branch
  and push again, so a landing never debugs it.
- Link each green leg's job page in the evidence table. Then check and deliver again, and notify.
- The check and `deliver` warn, without refusing, where such a branch's report links no green job
  of each leg, and they name the legs and job links they read.
