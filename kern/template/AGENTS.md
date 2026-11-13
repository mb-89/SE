# Agent guide (app)

- An application on kern: the core, its bus and its host come from kern; this repository holds the
  application's components, its wiring and its tests ([README](README.md)).
- A component is one package under `components/`, registered with `index.Register` and imported in
  `cmd/app/main.go`; it runs where `wiring.toml` names an instance of it.
- Tests: `uv run pytest -q`, the Go and Python tests within `se.toml` `[tests]`'s budget; CI runs
  them through kern's battery.
