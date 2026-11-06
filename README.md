# se: systematic engineering

A process plugin for AI agents: roles (dispatcher, worker, integrator), skills, issue templates and the
scripts they call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Documentation

se's documentation is one HTML file, published at the `docs_url` of `se.toml` `[project]`
(<https://mb-89.github.io/SE/>), the one setting that names it. `docs.md` is its manifest: it lists
se's notes as chapters and restates none of them. The [obs](https://github.com/mb-89/obs) module
(`[modules.obs]` in `se.toml`) builds it:

```sh
uv run python scripts/build_docs.py --destination <file outside the repository>.html
```

Any obs warning fails the build, so a broken link or a missing note fails it; the long-paragraph
lint allows the 30 lines `scripts/build_docs.py` sets. The suite runs the build (`tests/test_docs.py`),
and the workflow `.github/workflows/docs.yml` builds and publishes it to GitHub Pages on each push
to `se`; a failed build publishes nothing, so the previous artifact stays.

## Modules

A repository pulls its dependencies (se itself, format tools, styles, other repositories) as modules
pinned to commits or to semantic version ranges, from any Git host. `scripts/se_modules.py` implements this section; its
invocation is in [Commands](#commands).

### `se.toml`

The consuming repository declares its modules in `se.toml` at its root:

```toml
[modules.obs]
url = "https://github.com/<owner>/obs.git"   # public form of the clone URL
ref = "<40-hex commit SHA>"                  # the pin
path = "skills"                              # optional: the part of the module that is used

[modules.style]
url = "https://github.com/<owner>/style.git"
version = "^1.4"                             # in place of ref: a semver range of the module's tags
```

- `url`: the clone URL in its public form. Machine-specific forms (mirrors, credentials) belong in
  the machine-local file below, never here.
- `ref`: the pin, a full commit SHA. Any commit on the module's `main` can be pinned, not only
  releases; `update` moves it.
- `version`: in place of `ref`, a semantic version range of the module's release tags
  `vMAJOR.MINOR.PATCH` ([Project settings](#project-settings) says how a module releases):
  `^1.4` (1.4.0 up to 2.0.0), `~1.4.2` (up to 1.5.0), `1.4` (any 1.4.x) or `1.4.2` (exactly). The
  highest matching tag is resolved and its version and commit are recorded in `se.lock` next to
  `se.toml`, which `sync` and `update` write and the repository commits. A module pins one of `ref`
  and `version`.
- `path`: optional relative directory inside the module; without it the whole module is used.
- Module names use letters, digits, `.`, `_` and `-`. Other keys are errors.
- The module named `se` is se itself; its pin (its `ref`, or the commit `se.lock` locks for its
  `version`) is the se version the [public check](AGENTS.md#public-safety) must run at.

A common repository declares only modules that are public. Work-only modules on private hosts are
declared the same way, in a work repository that consumes the common ones; a common repository never
names them.

### Project settings

`se.toml` also holds every project setting owned by se. Each se tool validates only the settings it
owns.

```toml
[project]
authored_content = ["README.md", "docs/**/*.md"]
identity = "mb <mb>"
integration_branch = "main"
public_check = true
version = "1.4.2"
```

`identity = "Name <email>"` is the project's commit identity. `work_tickets.py sync` writes it into
the checkout's git config (`user.name`, `user.email`), so every later commit and merge there
carries it, unless the machine sets `public_identity`, which wins. Unset, sync leaves the checkout's
identity as it is.

`integration_branch` is owned by the
[work model](.github/skills/work-model/SKILL.md#integration-branch).

`public_check` makes `work_tickets.py integrate` run se's
[public check](AGENTS.md#public-safety) on the merged tree and every merged commit before it pushes
the integration branch; on a failure it pushes nothing, restores the pre-merge branch and
escalates. `work_tickets.py push` runs its push gate first. Default `true`, so a project that never
set it is still checked; a project without a public check sets `public_check = false`, and `push`
then prints one line saying the check is off and where to turn it on.

`version = "MAJOR.MINOR.PATCH"` is the project's one semantic version, published as the git tag
`vMAJOR.MINOR.PATCH` on its integration branch; consumers pin ranges of it
([`se.toml`](#setoml)). Nobody types it after the first: `work_tickets.py push` of the integration
branch (which `integrate` runs) releases what was integrated since origin and the last tag. Each
integration is a first-parent merge whose message starts `Integrate <branch>`, as `integrate`
writes it; its kind comes from the branch prefix, `feature` (or `feat`) a minor bump, `fix`,
`perf`, `chore` or `docs` a patch bump, and a merge carrying the trailer `Breaking-change: yes`
(which `integrate` adds where the work issue's "Package kind" says "breaking") a major one. One push
bumps once, by its integrations' highest kind: it rewrites only `version`, commits `Release v<new>`,
tags it and pushes the tag with the branch. Another prefix is refused before anything is written; a
version without its tag yet is tagged as it is, which is how a project starts versioning. Without
`version` push releases nothing and says so; a malformed one is refused, naming the file.

### Test budget

```toml
[tests]
command = ["uv", "run", "pytest", "-q"]
target_seconds = 60
limit_seconds = 120
setup = ["uv", "sync"] # optional
```

`command` is the project's complete suite, an argument array run without a shell from the project
root; `work_tickets.py integrate` runs it at every integration, and `work_tickets.py suite` runs it
the same way for a worker's before-and-after times. `setup`, optional and of the same form, installs
the test dependencies (packages, browsers) and runs first; the gate prints its time and its last
lines apart, and that time does not count against the budget. A failing setup stops the run before
the suite, naming the command and its output. The gate measures the suite's wall time and prints it
with the last lines of the suite's own output and the ten slowest tests (`suite --slowest N`
lists N). A runner of any kind may write JUnit XML reports into the directory
named by the environment variable `SE_TEST_REPORTS`, one file per part; the gate then lists the
slowest tests across all reports, each with its part (the file's name), and prints one line per
part, so a speed issue names the right lever, one long test or the part's total work:
`<part>: 84.2 s wall; 309.6 s test time / 4 workers = 77.4 s; slowest 17.5 s`. The wall time is the
report's own `time`, the worker count its `workers` testsuite property (pytest's
`record_testsuite_property`), 1 without one. Without reports it reads
pytest's lines (it adds `--durations=<N>` to a pytest command), and where neither names a test it
says so and names that remedy. Above `target_seconds` (default
60) it warns; above `limit_seconds` (default 120) it refuses the integration, naming the test
result (passed, with its counts), the time, the limit, the slowest tests and the remedy: rerun once on
an idle host, as a loaded host can push a passing suite over the limit, and if it is still over, make
those tests faster. Failed tests exit with code 1, a passing suite over the limit with code 3. How
tests are written is owned by the [work model](.github/skills/work-model/SKILL.md#tests).

`work_tickets.py guard` checks deleted sentences in the configured project paths. Each configured
glob is relative to the project root. The field report must name every removed sentence in its
authored-prose section.

### Machine-local `~/.se/local.toml`

`public_identity = "Name <email>"` pins the author and committer identity allowed in every
commit pushed to a configured public mirror. If it is omitted, `integrate` uses the project's
`identity`, else the selected checkout's configured Git identity. When it is set, `sync` writes it into the checkout's git
config in place of the project's `identity` ([Project settings](#project-settings)).

Each machine may adapt modules without touching tracked files. se only reads this file; it never
writes it, and nothing from it is written into `se.toml`.

The file is shared with `work_tickets.py`. `se_modules.py` owns `[paths]` and `[urls]`;
`work_tickets.py` owns the top-level `integrator_session`, `public_identity` and `commit_trailer`
settings, and the `[trackers]`, `[worktree_roots]`, `[repos]`, and `[mirrors]` tables. Each tool ignores sections
owned by the other.

```toml
[paths]
obs = "~/src/obs"                     # use this checkout of module obs if the directory exists

[urls]
"https://github.com/" = "https://mirror.example.com/github/"   # prefix rewrite, longest wins
```

- `[paths]`: a local checkout per module name. If the directory exists, the module comes from it as
  it is (working tree, any commit, no git step) and is never updated; `sync` and `status` report the
  version its `se.toml` sets, and whether the module's `version` range admits it. A malformed
  version, or none where the module pins a range, is an error naming that file. If the directory is
  missing, the pin is used. Relative paths are
  relative to the file, `~` is expanded.
- `[urls]`: prefix rewrites applied to `url` before any git step, for example a private mirror of a
  public host. The longest matching prefix wins.

Work queue tracker, worktree and mirror settings are documented in the
[work model](.github/skills/work-model/SKILL.md#what-the-project-provides).

### Commands

One invocation on every platform; a project copies it as it is into its `AGENTS.md`, with `<se>`
the path where se lives in the project (`.` in se itself):

```sh
uv run python <se>/scripts/se_modules.py sync [<name>...]
uv run python <se>/scripts/se_modules.py status [<name>...]
uv run python <se>/scripts/se_modules.py update <name> [--to <ref>]
uv run python <se>/scripts/se_modules.py update --all
uv run python <se>/scripts/se_modules.py path <name>
```

- `sync`: a module with an existing local path is used from there; any other is cloned or fetched into
  `.se/modules/<name>` and checked out (detached) at its pin. A `version` range without a lock entry
  that admits it is resolved and locked first; a locked one stays where it is until `update`. A clone with local changes is never
  overwritten. Consuming repositories ignore `.se/`.
- `status`: one line per module with its source (`local` or `pinned`), the directory it is used from,
  the pin and the drift: for a local path the commits ahead of and behind the pin, uncommitted
  changes, or a pin the checkout does not have yet; for a pinned module whether the clone is at the pin
  and, for a `version` range, a newer matching tag the clone knows ("run update"). It never fetches.
- `update`: fetches the module (through `.se/modules/<name>`, also when a local path is used),
  resolves the newest commit on its `main` (or `--to` a branch, tag or commit), rewrites only that
  `ref` in `se.toml`, prints the commits added (and dropped, if the pin moves back) and syncs. A
  `version` range moves to its highest matching tag in `se.lock` instead (`--to` is refused there;
  change the range). It does not commit; commit the new pin with the commit list.
- `path`: prints the directory a module is used from (its `path` included), for tools that load it.
- `--root <dir>` names the repository (default: the nearest ancestor with `se.toml`); `--local <file>`
  reads another machine-local file than `~/.se/local.toml`.
- Git runs without prompts; credentials come from the machine's git setup.
