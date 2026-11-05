# Agent guide (se)

- This repository is common and open source; it must stay publishable. The rule and its check are owned
  by [Public safety](#public-safety).
- SPOT everywhere: one owner per fact; everything else links to it.
- No backwards compatibility unless asked.

## Public safety

Everything here must be publishable at any time. Nothing may identify an employer, a work project, a
person, a machine, an account or an internal host: no work company, product or project names, no user
names or user profile paths, no personal e-mail addresses, no device or server names, no internal or
enterprise hosts. Use generic names (`<name>`, `alice`, `example.com`). Work-specific content belongs in
separate repositories that use se as a module. Commit with a generic identity: a name without an e-mail
domain (`mb <mb>`) or a `users.noreply.github.com` address; never a real e-mail address.

`scripts/public_check.py` enforces the rule on tracked file names and contents (binary files as bytes),
commit messages and author and committer identities. It prints locations and pattern labels, never the
matched text; exit code 0 passed, 1 hits, 2 setup error.

- Generic patterns, committed in the script: user profile paths (`X:\Users\<name>`, `/home/<name>`,
  `/Users/<name>`), e-mail addresses other than `*@users.noreply.github.com` and `example.*`,
  enterprise GitHub hosts (GitHub Enterprise Cloud subdomains), machine names in UNC paths.
  The fixed addresses services write into commits themselves, `noreply` at `github.com` and at
  `anthropic.com`, name no person and pass.
- Private deny list for terms that must never be written down here: `~/.se/private-terms.txt`, or the
  file named by `SE_PRIVATE_TERMS`; one case-insensitive regex per line, `#` comments. It is never
  committed, and hits name only its line number. Without it the check warns and runs the generic
  patterns only, as on a public CI host.
- False positives: reasoned entries in `.public-check-allow`, whose header owns their format and rules.
- Hooks: run `scripts/setup.ps1` or `scripts/setup.sh` once per clone. They set `core.hooksPath` to
  `.githooks`: pre-commit checks the staged content, commit-msg the message and identity, pre-push
  every pushed commit. A repository that uses se as a module runs `scripts/setup.ps1 -Repo <path>`
  (or `scripts/setup.sh <path>`) and so runs se's check without copying it.
- By hand: `uv run python scripts/public_check.py --repo <path>` (`--help` for the options).

Never bypass the hooks with `--no-verify`: remove the content or add a reasoned allow entry.
