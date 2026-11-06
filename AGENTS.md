# Agent guide (se)

- This repository is common and open source; it must stay publishable. The rule and its check are owned
  by [Public safety](#public-safety).
- SPOT everywhere: one owner per fact; everything else links to it.
- No backwards compatibility unless asked.

## Agents and skills

- Each agent and skill is written once, in `src/agents/<name>.md` and `src/skills/<name>/`. Front
  matter keys prefixed `copilot.` or `claude.` go only into that host's layout.
- `uv run python scripts/se_plugin.py build` generates everything else from it: the Copilot layout
  (`.github/agents/`, `.github/skills/`) and the Claude Code plugin (`agents/`, `skills/`,
  `.claude-plugin/`). Never edit those by hand; `tests/test_se_plugin.py` fails until they match.
- Installing SE is the README's [Install](README.md#install).

## Tests

- Focused: `uv run pytest -q tests/<file>.py` (add `-k <name>` for one test), the tests of what changed.
- Complete: `uv run pytest -q`, declared with its time budget in `se.toml` `[tests]`; `integrate` runs
  it against that budget, and `work_tickets.py suite --worktree <checkout>` runs it the same way.
- Test environment: none to load. Where uv warns that it cannot verify TLS behind a proxy, set
  `UV_SYSTEM_CERTS=1` in that shell.

## Public safety

Everything here must be publishable at any time. Nothing may identify an employer, a work project, a
person, a machine, an account or an internal host: no work company, product or project names, no user
names or user profile paths, no personal e-mail addresses, no device or server names, no internal or
enterprise hosts.

Use generic names (`<name>`, `alice`, `example.com`). Work-specific content belongs in separate
repositories that use se as a module.

Commit with a generic identity: a name without an e-mail domain or a `users.noreply.github.com`
address; never a real e-mail address. Where the machine sets no `public_identity`, se's commits carry
`mb <mb>`, the `identity` in `se.toml`.

`scripts/public_check.py` enforces the rule on tracked file names and contents (binary files as bytes),
commit messages and author and committer identities. It prints locations and pattern labels, never the
matched text; exit code 0 passed, 1 hits, 2 setup error.

- Tracker references in commit messages, the
  [work model's rule](src/skills/work-model/SKILL.md#what-the-project-provides): the commit
  gates (`--message-file`, and the commits of a `--range`, as the hooks and `integrate` pass it)
  refuse them and, as they name nothing private, print the reference with its remedy. A full check
  leaves history already pushed alone; a commit already published passes by its reasoned message
  entry in `.public-check-allow`.
- A `--range` on a shallow clone that reaches beyond the fetched history is refused with exit code
  2, naming `git fetch --unshallow`, so a gate never passes over commits it cannot see.
- The project identity in the commit gates of a `--range`: where the project sets an `identity`
  (or the machine a `public_identity`, which wins), a commit whose author or committer differs is
  refused, naming the commit, the identity found (redacted) and the remedy. A full check leaves
  history already pushed alone.
  - GitHub's web-flow identity (`GitHub`, `noreply` at `github.com`), the committer of a commit
    made on GitHub, passes as committer, never as author.
  - A commit already published passes by its reasoned commit entry in `.public-check-allow`.
- Generic patterns, committed in the script: user profile paths (`X:\Users\<name>`, `/home/<name>`,
  `/Users/<name>`), e-mail addresses other than `*@users.noreply.github.com` and `example.*`,
  enterprise GitHub hosts (GitHub Enterprise Cloud subdomains), machine names in UNC paths.
  - The fixed addresses services write into commits themselves, `noreply` at `github.com` and at
    `anthropic.com`, name no person and pass.
- Private deny list for terms that must never be written down here: `~/.se/private-terms.txt`, or the
  file named by `SE_PRIVATE_TERMS`; one case-insensitive regex per line, `#` comments. It is never
  committed, and hits name only its line number. Without it the check warns and runs the generic
  patterns only, as on a public CI host.
- One se version per check: every verdict names the se commit that ran it, and a repository that
  pins se (`[modules.se]` in its `se.toml`, [README "Modules"](README.md#modules)) is refused with
  exit code 2 when the running se is not at that pin: another commit than its `ref`, or a version
  outside its `version` range or none readable, naming both; `scripts/se_modules.py sync` brings
  the clone there.
- False positives: reasoned entries in `.public-check-allow`, whose header owns their format and rules.
- Hooks: run `scripts/setup.ps1` or `scripts/setup.sh` once per clone. They set `core.hooksPath` to
  `.githooks`: pre-commit checks the staged content, commit-msg the message and identity, pre-push
  every pushed commit. A repository that uses se as a module runs `scripts/setup.ps1 -Repo <path>`
  (or `scripts/setup.sh <path>`) and so runs se's check without copying it.
- Pushes of the integration branch: pre-push and `work_tickets.py push` also need the verdicts the
  [work model](src/skills/work-model/SKILL.md#integration-branch) names.
- By hand: `uv run python scripts/public_check.py --repo <path>` (`--help` for the options).

Never bypass the hooks with `--no-verify`: remove the content or add a reasoned allow entry.
