# app

A bare application on kern: the core with no components, its wiring, its CI and its test budget in
SE's shape (kern's design, SE's `docs/go-core.md` "A bare application, and `se new app`").
`se new app <name> --path <dir>` copies this folder at kern's pin and fills in the name; until that
command exists, copy it and replace `app` by hand.

| path | what |
|---|---|
| `go.mod` | the module, its Go version, and kern as a requirement |
| `cmd/app/main.go` | the binary: the core with the application's Go components, none yet |
| `components/` | the application's Go components, one package each |
| `types/` | the JSON types its components share on the bus |
| `wiring.toml` | the instances and wires the core starts on, none yet |
| `se.toml` | `[project]`, the `[tests]` budget and the `[modules.kern]` pin |
| `tests/` | the battery: the Go tests, and a test that starts the bare core, asks it and stops it |
| `.github/workflows/check.yml` | CI: kern's reusable battery at kern's release tag |
| `AGENTS.md` | the agent guide |

## The pin

kern is pinned twice with one owner: `go.mod` requires its version, and `se.toml [modules.kern]`
says `go = true`, so the version is read from `go.mod`. While kern is incubated in SE, `go.mod`'s
`replace` builds the template against the kern beside it; a copy drops that line and requires a
released kern.

## Tests

```sh
uv run pytest -q
```

It runs the Go tests (`tests/test_go.py`) and the Python tests under the one budget of `se.toml`
`[tests]`; CI runs the same command through kern's battery, which vets the Go code first.
