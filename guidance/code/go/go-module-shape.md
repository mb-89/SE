---
name: go-module-shape
description: 'The one shape of a new Go module: scaffolded from the go-module template, its go.mod marked, one package with its entry Run and its test. Read it before you create or reshape a Go module.'
---

The person's requirement of 24 Nov: a Go module always starts from its template, and the author
fills in only its own content.

- **Scaffold the module.** `uv run python <se>/scripts/templates.py scaffold go-module --path
  <folder> --says "<what it does>"` writes `go.mod`, the package `<name>.go` with its entry `Run(In) (Out, error)` and
  `<name>_test.go`, each marked with the template and version; it builds and tests green as it
  stands. SE's gate refuses a `go.mod` written any other way and names the scaffold call.
- **go.mod keeps its marker.** Its first line is `// se:template se/go-module <version>`, then the
  `module` line, a path that names no host (AGENTS.md "Neutral home"), and the `go` line.
- **Fill the slots.** `In` and `Out` take the module's own fields, `Run` its logic, the test its
  cases; a package of SE's components module is a component under `components/`, which follows
  kern's component contract instead (`components/README.md`).
- **Tests reach no process.** A Go test reaches git and other outside things through kern's doors
  and their fakes, as SE's components do.

Not picked: a module skeleton that already imports kern, since a module that is no kern component
would then carry a dependency it does not use.
