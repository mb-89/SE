# app

A bare application on kern: the core with no components, its wiring, its CI and its test budget in
SE's shape (kern's design, SE's `docs/go-core.md` "A bare application, and `se new app`").
SE's `se new app <name> --path <dir>` (SE's README "New application") copies this folder at kern's
pin, fills in the name and makes the first commit.

| path | what |
|---|---|
| `go.mod` | the module, its Go version, and kern as a requirement |
| `cmd/app/main.go` | the binary: the core with the application's Go components, none yet |
| `components/` | the application's Go components, one package each |
| `types/` | the JSON types its components share on the bus |
| `wiring.toml` | the instances and wires the core starts on, none yet; `enabled = false` switches one off |
| `se.toml` | `[project]`, the `[tests]` budget and the `[modules.kern]` pin |
| `tests/` | the battery: the Go tests, and a test that starts the bare core, asks it and stops it |
| `.github/workflows/check.yml` | CI: kern's reusable battery at kern's release tag |
| `AGENTS.md` | the agent guide |

## The pin

kern is pinned twice with one owner: `go.mod` requires its version, and `se.toml [modules.kern]`
says `go = true`, so the version is read from `go.mod`. While kern is incubated in SE, no module
`github.com/mb-89/kern` can be fetched, so `go.mod`'s `replace` builds against kern's source: the
kern beside the template here, and kern's source at the pin in `kern/` in an application that
`se new app` made. The move to `mb-89/kern` drops the `replace` and that folder.

## Building your own binary

This bare application has no Go components, so it runs the bare `kern` release that `bootstrap.sh`
fetches: it needs no binary of its own (SE's `docs/go-core.md` "How the binary arrives"). When it
gains Go components, it builds its own binary the same way SE builds `se`:

- add a `release.toml` beside `cmd/app/` naming its `version`, its `download` base, its `binary` and
  its `package` (`./cmd/app`), as `kern/release.toml` does for the bare core;
- point `se.toml` at it with `[binary]\nrelease = "release.toml"`, so `bootstrap.sh` fetches, builds
  and starts that binary instead of the bare kern;
- add a release workflow that calls kern's reusable one with its folder (`.`):

```yaml
  jobs:
    release:
      uses: mb-89/SE/.github/workflows/kern-release.yml@kern-v<version>
      with:
        directory: .
```

## Tests

```sh
uv run pytest -q
```

It runs the Go tests (`tests/test_go.py`) and the Python tests under the one budget of `se.toml`
`[tests]`; CI runs the same command through kern's battery, which vets the Go code first.
