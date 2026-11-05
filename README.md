# se: systematic engineering

A process plugin for AI agents: roles (dispatcher, worker, integrator), skills, issue templates and the
scripts they call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Modules

A repository pulls its dependencies (se itself, format tools, styles, other repositories) as modules
pinned to commits, from any Git host. `scripts/se_modules.py` implements this section; its
invocation is in [Commands](#commands).

### `se.toml`

The consuming repository declares its modules in `se.toml` at its root:

```toml
[modules.obs]
url = "https://github.com/<owner>/obs.git"   # public form of the clone URL
ref = "<40-hex commit SHA>"                  # the pin
path = "skills"                              # optional: the part of the module that is used
```

- `url`: the clone URL in its public form. Machine-specific forms (mirrors, credentials) belong in
  the machine-local file below, never here.
- `ref`: the pin, a full commit SHA. Any commit on the module's `main` can be pinned, not only
  releases; `update` moves it.
- `path`: optional relative directory inside the module; without it the whole module is used.
- Module names use letters, digits, `.`, `_` and `-`. Other keys are errors.
- The module named `se` is se itself; its pin is the se version the
  [public check](AGENTS.md#public-safety) must run at.

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
```

`identity = "Name <email>"` is the project's commit identity. `work_tickets.py sync` writes it into
the checkout's git config (`user.name`, `user.email`), so every later commit and merge there
carries it, unless the machine sets `public_identity`, which wins. Unset, sync leaves the checkout's
identity as it is.

`integration_branch` is owned by the
[work model](.github/skills/work-model/SKILL.md#integration-branch).

`public_check = true` makes `work_tickets.py integrate` run se's
[public check](AGENTS.md#public-safety) on the merged tree and every merged commit before it pushes
the integration branch; on a failure it pushes nothing, restores the pre-merge branch and
escalates. Default `false`, for projects without a public check.

### Test budget

```toml
[tests]
command = ["uv", "run", "pytest", "-q"]
target_seconds = 60
limit_seconds = 120
```

`command` is the project's complete suite, an argument array run without a shell from the project
root; `work_tickets.py integrate` runs it at every integration, and `work_tickets.py suite` runs it
the same way for a worker's before-and-after times. The gate measures the wall time and prints it
with the ten slowest tests (it adds `--durations=10` to a pytest command; other runners' lines of
the form `<seconds>s <phase> <test>` are read from their output). Above `target_seconds` (default
60) it warns; above `limit_seconds` (default 120) it refuses the integration, naming the time, the
limit, the slowest tests and the remedy: make those tests faster, or file a perf package first. How
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
  it is (working tree, any commit, no git step); if it is missing, the pin is used. Relative paths are
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
  `.se/modules/<name>` and checked out (detached) at its pin. A clone with local changes is never
  overwritten. Consuming repositories ignore `.se/`.
- `status`: one line per module with its source (`local` or `pinned`), the directory it is used from,
  the pin and the drift: for a local path the commits ahead of and behind the pin, uncommitted
  changes, or a pin the checkout does not have yet; for a pinned module whether the clone is at the pin.
- `update`: fetches the module (through `.se/modules/<name>`, also when a local path is used),
  resolves the newest commit on its `main` (or `--to` a branch, tag or commit), rewrites only that
  `ref` in `se.toml`, prints the commits added (and dropped, if the pin moves back) and syncs. It does
  not commit; commit the new pin with the commit list.
- `path`: prints the directory a module is used from (its `path` included), for tools that load it.
- `--root <dir>` names the repository (default: the nearest ancestor with `se.toml`); `--local <file>`
  reads another machine-local file than `~/.se/local.toml`.
- Git runs without prompts; credentials come from the machine's git setup.
