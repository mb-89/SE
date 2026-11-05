# se: systematic engineering

A process plugin for AI agents: roles (dispatcher, worker, integrator), skills, issue templates and the
scripts they call. It is project-neutral; a project describes its own commands in its `AGENTS.md` and
pulls se in as a module.

Status: being bootstrapped. Everything in this repository must be publishable; see `AGENTS.md`.

License: MIT, see [LICENSE](LICENSE).

## Modules

A repository pulls its dependencies (se itself, format tools, styles, other repositories) as modules
pinned to commits, from any Git host. `scripts/se_modules.py` implements this section.

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

A common repository declares only modules that are public. Work-only modules on private hosts are
declared the same way, in a work repository that consumes the common ones; a common repository never
names them.

### Machine-local `~/.se/local.toml`

Each machine may adapt modules without touching tracked files. se only reads this file; it never
writes it, and nothing from it is written into `se.toml`.

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

```sh
uv run python scripts/se_modules.py sync [<name>...]
uv run python scripts/se_modules.py status [<name>...]
uv run python scripts/se_modules.py update <name> [--to <ref>]
uv run python scripts/se_modules.py update --all
uv run python scripts/se_modules.py path <name>
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
