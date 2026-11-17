# app

A bare application on kern: the core with no components, its wiring, its CI and its test budget in
SE's shape (kern's design, SE's `docs/go-core.md` "A bare application, and `se new app`").
SE's `se new app <name> --path <dir>` (SE's README "New application") copies this folder at kern's
pin, fills in the name and makes the first commit.

## Getting it running

Install Git, clone this repository and run RUNME once in the clone: it installs what `RUNME.conf`
declares and this machine lacks (Go), builds `app` and runs it with every argument.

- Windows: `winget install --id Git.Git -e --source winget`, then in a new terminal `git clone
  <repository URL>`, then `powershell -ExecutionPolicy Bypass -File RUNME.ps1` in the clone.
- Linux: `sudo apt-get install -y git` or `sudo dnf install -y git`, the same clone, then
  `./RUNME.sh`; macOS: `brew install git`, the same clone, then `./RUNME.sh`.

The apt or dnf Go must be 1.21 or newer, which fetches go.mod's toolchain itself. After a pull,
delete `app` (or `app.exe`) and run RUNME again.

| path | what |
|---|---|
| `go.mod` | the module, its Go version, and kern as a requirement |
| `cmd/app/main.go` | the binary: the core with the application's Go components, none yet |
| `components/` | the application's Go components, one package each |
| `types/` | the JSON types its components share on the bus |
| `wiring.toml` | the instances and wires the core starts on, none yet; `enabled = false` switches one off |
| `se.toml` | `[project]`, the `[tests]` budget and the `[modules.kern]` pin |
| `tests/` | the battery: the Go tests, and a test that starts the bare core, asks it and stops it |
| `.github/workflows/check.yml` | CI: kern's battery, through the copy beside it |
| `.github/workflows/kern-battery.yml` | the battery's copy `se new app` writes at kern's pin (SE's README "Workflows") |
| `AGENTS.md` | the agent guide |
| `RUNME.sh`, `RUNME.ps1` | the generic installer every tool has, the same as SE's: installs what `RUNME.conf` declares, then runs the tool |
| `RUNME.conf` | this application's declaration: what it needs, how each is installed, and its run command |

## The pin

kern is pinned twice with one owner: `go.mod` requires its version, and `se.toml [modules.kern]`
says `go = true`, so the version is read from `go.mod`. While kern is incubated in SE, kern's
module (the path `go.mod` requires) cannot be fetched, so `go.mod`'s `replace` builds against kern's
source: the kern beside the template here, and kern's source at the pin in `kern/` in an application
that `se new app` made. kern's move to its own repository drops the `replace` and that folder.

## Building your own binary

This bare application has no Go components, so it runs the bare `kern` release that `bootstrap.sh`
fetches: it needs no binary of its own (SE's `docs/go-core.md` "How the binary arrives"). When it
gains Go components, it builds its own binary the same way SE builds `se`:

- add a `release.toml` beside `cmd/app/` naming its `version`, its `download` base, its `binary` and
  its `package` (`./cmd/app`), as `kern/release.toml` does for the bare core;
- point `se.toml` at it with `[binary]\nrelease = "release.toml"`, so `bootstrap.sh` fetches, builds
  and starts that binary instead of the bare kern;
- write the copy of kern's reusable release workflow beside the battery's, at the same pin, with
  `uv run python <se>/scripts/se_workflows.py write --root . .github/workflows/kern-battery.yml
  .github/workflows/kern-release.yml` (SE's README "Workflows"), and add a release workflow that
  calls it with its folder (`.`):

```yaml
  jobs:
    release:
      uses: ./.github/workflows/kern-release.yml
      with:
        directory: .
```

## Tests

```sh
uv run pytest -q
```

It runs the Go tests (`tests/test_go.py`) and the Python tests under the one budget of `se.toml`
`[tests]`; CI runs the same command through kern's battery, which vets the Go code first.
