# SE's components

SE's own components on kern ([kern/README.md](../kern/README.md)), the application's, not kern's:
the rules they compute are SE's work model. Two kinds live here, one folder each:

- **Python, declared** by their `component.toml` and placed by the checkout's `wiring.toml`:
  tickets, issues, delivery and integration, SE's script commands (README
  ["Commands as components"](../README.md#commands-as-components)).
- **Go, compiled into the `se` binary**: fleet, retro and origin, SE's Go module
  `github.com/mb-89/se/components` (`go.mod` here, kern replaced by `../kern` while it is incubated).

## The Go components

| component | reads | writes | port of |
|---|---|---|---|
| `fleet` | `github/issues`, `github/pulls`, `github/checks` whole; `origin/branches`; config `lease-hours`, `repository`, `base` | `fleet/findings`: each stuck or stray piece of work with its remedy, as `fleet-check --json` lists it, with when it was computed and how many issues, pull requests and branches it read | `work_tickets.py` `fleet_findings` |
| `retro` | `github/issues`, `github/pulls` whole; config `due-after`, `tracker`, `base` | `retro/due`: the work issues landed since the last retro, `due_after`, whether a retro is due, where the window starts | `retro.py` `landed_since_retro` |
| `origin` | the checkout's git: `refs/remotes/origin`, at start and after SessionStart, UserPromptSubmit, Stop, SubagentStop and each Bash PostToolUse | `origin/branches`: each branch with the committer time of its tip | `work_tickets.py` `fleet_branches`, without its fetch |

- **Whole families.** fleet and retro count across issues, so each reads a GitHub family whole: an
  input of type `map[string]T` bound to a family of `T` reads every key standing, and the
  derivation runs once per change at any key (kern's index, kern/README.md "Types").
- **What the names hold.** They hold only what was read: every GitHub tool answer a session receives
  lands, and the token backend refreshes what it holds, but nothing lists a repository's issues. So
  each output names how many issues it read, and a reader takes it only where that is above 0.
- **No comments.** The names carry no issue comments, so the lease of in-progress work without a
  branch is never counted from its `Started:` comment: it is `no branch` at once, as the Python check
  answers where it read no comments ([README "Fleet check"](../README.md#fleet-check)).
- **The binary.** `cmd/se` is kern's command line (`se start`, `status`, `stop`, `serve`, `hook`)
  carrying kern's GitHub component and these three. `wiring.toml` here is their wiring, with SE's own
  checkout's config. The bare `kern` binary SE's start runs today carries none of them, so the
  checkout's own `wiring.toml` cannot name them yet.

## Who reads them

[scripts/kern_names.py](../scripts/kern_names.py) reads `fleet/findings` and `retro/due` from the core
running in a checkout, over its bus as the client user, within 0.3 s each; where no core carries
them it answers nothing and every reader keeps its own path.

- **The greeting** takes each part over the cached work check and says so: `live from kern`.
- **`fleet-check`**, which the integrator runs, answers from `fleet/findings`, naming how much the core
  has read; otherwise the Python check reads GitHub as before.

## Tests

```sh
cd components && go vet ./... && go test ./...
```

Each component is tested against kern's Go fake core. `agreement/` feeds the Go components and SE's
Python paths one snapshot (`agreement/testdata/snapshot.json`, in the REST and the tool shape) and
compares every finding word for word, so the two paths cannot drift. `cmd/se` starts the real core
with this wiring, lands GitHub tool answers through PostToolUse and reads both names as a client.
`se.toml` `[tests.beside.go-components]` runs them after the suite.
