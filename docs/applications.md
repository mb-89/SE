# Applications

## New application

`se.py new app` ([its usage](work-commands.md#scaffold)) creates an application on kern, the core SE builds on
([docs/go-core.md "A bare application, and `se new app`"](go-core.md#a-bare-application-and-se-new-app)),
in the new or empty folder its `--path` names: kern's template at SE's kern pin, the name filled in,
and git's first commit on `main` as the [project identity](settings.md#project-settings).

- **The pin:** the version SE's `[components.kern]` reads from `components/go.mod` and its tag
  `v<version>`, which the pinned clone's `release.toml` names, read by `se_modules.py`'s
  `kern_pin`, and the commit SE's `se.lock` locks for it. The template comes from that clone at the
  tag.
  - A clone without the tag, or a lock that is missing, names another version or another commit
    than the tag's, is refused, naming `se_modules.py sync kern`.
- **kern beside it:** kern's module path names no host, so it cannot be fetched; the application
  pins it as SE does and carries no copy of it, only the template.
  - Its `go.mod` requires `kern v<version>` and replaces the module by `./.se/modules/kern`; its
    `se.lock` locks the commit SE's does; its `.gitignore` ignores `.se/modules/`.
  - Its `se.toml` pins kern as `[components.kern]` with `go = true`; a template that still writes
    `[modules.kern]` with its `url` gets that table in its place.
  - `se new app` copies SE's clone there at that commit, so the application vets and tests before
    it has an origin, and nothing under `.se/` is in its first commit. `se_modules.py sync kern`
    there keeps that clone while it holds the locked commit; once the pin moves, it finds kern by
    its name under the owners of the application's remotes ([Modules](modules.md#modules)).
  - Its CI places kern at that commit with the action `kern-at-pin` before the battery vets and
    tests it, and before its release builds ([Workflows](running.md#workflows)).
- **What it holds:** the template's (kern's template README): its wiring,
  where `enabled = false` switches a component off, CI through kern's battery (its copy from the SE
  that made it, [Workflows](running.md#workflows)), the `[tests]` budget and the `[components.kern]` pin.
- **Its own binary:** a bare application runs the bare kern. To build its own (the core plus its Go
  components), it adds a `release.toml` naming its `binary`, `package` and download, `[binary]
  release = "release.toml"` in `se.toml`, and a release workflow calling kern's reusable
  `kern-release.yml` with its folder — the way SE builds `se` (`components/release.toml`,
  `se-release.yml`).
  - It calls that workflow's copy, which `se_workflows.py write` adds ([Workflows](running.md#workflows)).
- **GitHub stays the owner's:** the last line names the owner's step, creating the repository with
  its ruleset and the first push. The command does nothing on GitHub.

## Host validators

`uv run python scripts/host_validate.py` runs each host's own validator over the built layout
(`claude plugin validate --strict` on both manifests, `skills-ref validate` on each skill folder) and
reports; SE's own lint in the build stays the first line. Exit codes: 0 passed, 1 a host refused a
layout, 2 a validator could not run; `--skips-pass` answers 0 where only a tool is absent.

It is off by default, and nothing runs it. Adding `[tests.beside.host-validators]` to `se.toml`,
running `tests/beside_host_validators.py`, puts the hosts' validators into every integration: that
step is the owner's.

## Decision rows

`uv run python scripts/decision_rows.py list --since DATE [--until DATE] [--json]` lists every row
of the Decisions table in the field reports of the pull requests merged into the integration branch
in the window, grouped by pull request, newest first, each with its work issue and the report's
Result. A landing without a Decisions section or without a field report is named as such.

It reads GitHub as `retro.py collect` does (without gh, from the answers saved into `--answers DIR`),
writes and files nothing, and nothing runs it.

## Ad hoc components

`se.py component add` ([its usage](work-commands.md#scaffold)) scaffolds an ad hoc component in the checkout: a Python component over NATS under the ignored
`.se/components/<name>/` (its `component.toml` and `__init__.py`), placed in the ad hoc wiring
overlay `.se/wiring.toml` that the core reads after `wiring.toml`. Restart the core to run it, about
30 ms; it is never tracked.

An ad hoc solution stays untracked until it earns its place
([gen-001](../src/skills/work-model/references/rules.md#gen-001-mechanize-first)).

The core counts each call of an ad hoc component and each run of an untracked script into
`.se/usage/adhoc.jsonl`, and `work_tickets.py`'s retro ([Retro due](fleet.md#retro-due)) lists a component
used in three or more sessions and a script run three or more times since the last retro as
candidates to promote to a tracked `components/<name>/` ([docs/go-core.md](go-core.md#scripts-are-ad-hoc-components-are-long-term)).
