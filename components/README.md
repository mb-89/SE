# SE's components

SE's own components on kern (kern's README), the application's, not kern's:
the rules they compute are SE's work model. Two kinds live here, one folder each:

- **Python, declared** by their `component.toml` and placed by the checkout's `wiring.toml`:
  tickets, issues, delivery, integration, review, retro, overhaul, render and scaffold, SE's
  script commands (README ["Commands as components"](../README.md#commands-as-components)).
- **Go, compiled into the `se` binary**: fleet, retro-due, origin and template, SE's Go module
  `se/components` (`go.mod` here: it requires kern at the version `se.toml` `[components.kern]` pins
  and replaces it by the clone `se_modules.py sync kern` places in `../.se/modules/kern`).
  Beside them the binary carries kern's GitHub component and kern's clock, whose `clock/second`
  the GitHub refresh counts (`wiring.toml` binds `"github.second" = "clock/second"`).

## The Go components

| component | reads | writes | port of |
|---|---|---|---|
| `fleet` | `github/issues`, `github/pulls`, `github/checks`, `github/issue-lists`, `github/pull-lists` whole; `origin/branches`; config `lease-hours`, `repository`, `base` | `fleet/findings`: each stuck or stray piece of work with its remedy, as `fleet-check --json` lists it, with when it was computed, how many issues, pull requests and branches it read, whether that was a complete read of the open issue and pull-request lists (`complete`) and since when (`since`); only a complete read is `healthy` | `work_tickets.py` `fleet_findings` |
| `retro-due` | `github/issues`, `github/pulls` whole; `origin/tracker`; config `due-after` (20), `failure-weight` (5), `days` (7), `overhaul-after` (3), `overhaul-days` (30), `base` | `retro-due/due`: what came back since the newest retro started (landed, failed, their weighted `count`), whether a retro is due and why, the retros open, where the window starts; the retros closed since the newest overhaul started, whether an overhaul is due and why, the overhauls open | `retro.py` `retro_countdown`, `overhaul.py` `overhaul_countdown` |
| `origin` | the checkout's git: `refs/remotes/origin` and origin's URL, at start and after SessionStart, UserPromptSubmit, Stop, SubagentStop and each Bash PostToolUse | `origin/branches`: each branch with the committer time of its tip; `origin/tracker`: `<owner>/<repository>` of the home origin names (kern's `kern/home`), `""` where it names none | `work_tickets.py` `fleet_branches`, without its fetch |
| `template` | at each call, the templates a name resolves to for the checkout its config `root` names, as `catalog` reads them ([The template engine in Go](#the-template-engine-in-go)); SE's scripts and templates in the checkout its config `se` names | nothing: its verbs answer. `fill` makes a filled template ([The template engine in Go](#the-template-engine-in-go)); `accept` is a templated target's gate across the bus; `check` gives a text's findings | `scripts/templates.py` |

- **Whole families.** fleet and retro-due count across issues, so each reads a GitHub family whole: an
  input of type `map[string]T` bound to a family of `T` reads every key standing, and the
  derivation runs once per change at any key (kern's index, kern's README "Types").
- **What the names hold.** They hold only what was read: every GitHub tool answer a session receives
  lands, and the token backend refreshes what it holds, but nothing lists a repository's issues. So
  each output names how many issues it read, and a reader takes it only where that is above 0.
- **No comments.** The names carry no issue comments, so the lease of in-progress work without a
  branch is never counted from its `Started:` comment: it is `no branch` at once, as the Python check
  answers where it read no comments ([README "Fleet check"](../README.md#fleet-check)).
- **The binary.** `cmd/se` is the `se` binary: kern's command line carrying kern's GitHub
  component and these three, and SE's start, `se agent`: it starts the SE agent in the caller's
  folder with SE loaded from its clone, Claude Code's directory marketplace `se` (`--host copilot`:
  Copilot CLI with `--plugin-dir`, for that run only). A bare `se` is `se agent` at a terminal and
  prints the help with no terminal, inside Claude Code or on a cloud box; `se help` lists every
  verb. `bootstrap.sh` builds or fetches
  it for SE's checkout (SE's [docs/go-core.md](../docs/go-core.md) "How the binary arrives"), so the
  checkout's root `wiring.toml` names these components beside SE's four Python command groups, and
  the core starts them. [`release.toml`](release.toml) owns the binary's version and its release,
  `se-v<version>`.

## The template engine in Go

`template/` is SE's template engine ported to Go (SE#1683): the same template notes and template
manifests (`manifest.go`), checks and answers as [scripts/templates.py](../scripts/templates.py),
whose docstring owns the format.
`Load` reads the notes, `Parse`, `Render`, `Check`, `Select`, `Draft`, `Schema` and `FillDocument`
answer as the Python functions of their names do.

- **One set of cases.** [tests/template_cases.py](../tests/template_cases.py) writes
  `template/testdata/cases/`: every SE template and five fixture sets, filled, read, checked,
  selected and broken, each with the Python engine's answer. `cases_test.go` holds Go to every
  answer, word for word; `tests/test_template_cases.py` fails where the committed cases lag the
  Python engine, so a change to either engine or to `templates/` refreshes them with
  `uv run python tests/template_cases.py`.
- **Code a template names.** A template names Python as `<module>:<NAME>`; Go holds its port of
  each name SE's templates use in `References` (`references.go`), `Checkers` and `Extractors`
  (`checkers.go`), and the cases hold each port to the Python one. A name Go holds no port of does
  not load; an adapter whose checker or reading Go does not hold fails its check, naming it.
- **Where a name resolves.** `CatalogAt` (`repositories.go`) is `catalog`'s resolution: the
  checkout's own `templates/` at origin's integration branch (se.toml `[project]
  integration_branch`, through kern's git door), else in its working tree; then each template
  repository se.toml `[templates] repositories` lists, a component pinned by `ref`, `version`
  (with `se.lock`) or `go` and placed at its pin, or the machine's `~/.se/local.toml` `[paths]`
  checkout; then SE's own. A repository that does not resolve refuses the catalog with
  `se_modules.py`'s words; `overlays.go` applies each `<name>.overlay.md` and refuses one that
  loosens its template. The cases hold checkouts with every kind of pin and refusal, their git
  answered by a fake (`repositories.json`), and overlays that load and do not. A TOML file that
  does not parse names go-toml's error, where Python names tomllib's.
- **The rule `dangling`.** An SE command or script a text names that does not exist
  (`dangling.go`, the port of `scripts/references.py` `dangling`): Go reads each script's
  subcommands from its source (`commands.go`: the parser `main` parses, its `add_parser` calls, a
  positional's `choices`, work_tickets.py's registry), where Python runs its argparse parser.
  The config `se` names SE's checkout whose scripts it reads. `agreement/` holds the Go reading
  to Python's tree for every script of SE's checkout, and the cases hold texts naming what exists,
  what does not and what a Requirement creates.
- **The adapters' checkers.** `checkers.go` ports each of SE's: the field report's structure
  (`work_tickets:field_report_problems`, against SE's `.github/pull_request_template.md` with the
  standing questions nested in its Retro section, without the work issue), the squash commit's
  trailer (`work_tickets:merge_release_kind`), the review report (`review:checked_report`) and
  the Pugh fence (`deck:pugh_problems`), called as `adapter_findings` calls them: `extract`,
  `json_after` (read as Python's `json.loads` reads it, its error text included, `pyjson.go`),
  `drop`, `missing`, `with`, `none`, `text_as`, `title_as` and `result`. An adapter written wrong
  for its checker fails the check with the Python engine's error. The cases hold each adapter's
  texts: what its writer writes and every refusal.
- **Where Go answers otherwise.** Python keeps a lone surrogate of a JSON string, Go reads it as
  U+FFFD.

## Who reads them

[scripts/kern_names.py](../scripts/kern_names.py) reads `fleet/findings` and `retro-due/due` (the retro and the overhaul part) from the core
running in a checkout, over its bus as the client user, within 0.3 s each; where no core carries
them it answers nothing and every reader keeps its own path.

- **The greeting** takes each part over the cached work check and says so: `live from kern`; the
  fleet part only from a complete read.
- **`fleet-check`**, which the integrator runs, answers from `fleet/findings` where its read is
  complete, naming how much the core has read and since when; otherwise it says how much the core
  has seen and the Python check reads GitHub as before.

## Tests

```sh
cd components && go vet ./... && go test ./...
```

Each component is tested against kern's Go fake core. `agreement/` feeds the Go components and SE's
Python paths one snapshot (`agreement/testdata/snapshot.json`, in the REST and the tool shape) and
compares every finding word for word, so the two paths cannot drift. `cmd/se` starts the real core
with the checkout's root `wiring.toml` (its Go instances), lands GitHub tool answers through
PostToolUse and reads both names as a client. `se.toml` `[tests.beside.go-components]` runs them
after the suite; `[tests.beside.se-components]` (`tests/beside_se_components.py`) builds the `se`
binary and serves SE's checkout, where `se status` lists these components beside the Python groups.
