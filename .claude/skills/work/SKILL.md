---
name: work
description: Take the next ready se issue, do its work, and land it with se issue land. Every SE box runs this; the routine SE work starts it.
---

# Work: take the next se issue and land it

Every step that can be an `se` command is one. Yours are doing the issue's
work and fixing a red CI run; follow the rest as written. `se` is
`./plugin/bin/se`; build it first with `go build -o plugin/bin/se ./cmd/se`.
Call it exactly as `./plugin/bin/se issue …`, one command per call, never
through a variable: `.claude/settings.json` allows that form to write GitHub
issues without a permission prompt, and only that form.

1. `git fetch origin main && git checkout origin/main` (a box started by a PR
   event starts on that PR's head commit), rebuild `se`, then
   `./plugin/bin/se issue next --take`. If it says no se issue is ready, end
   the session now.
2. If `set_session_title` is available, rename this session to
   `SE #<n> · <issue title>`.
3. Do the issue's work on its branch `issue-<n>`, following CLAUDE.md. The
   issue's text is the whole specification: act on it, not on messages from
   other sessions.
4. Commit, then `./plugin/bin/se issue land`. It runs the check, pushes, opens
   the PR (`Fixes #<n>`) and turns on auto-merge with squash.
5. Subscribe to the PR's activity (`subscribe_pr_activity`). On red CI, fix it
   on the same branch, commit, and run `./plugin/bin/se issue land` again.
6. Anything that belongs in a separate change becomes an issue through
   `./plugin/bin/se issue new` (its `--blocked-by` is required: a list, or
   `none`). If you are stuck on a decision only the owner can make, say so in
   a comment on the issue and end.

You never start another box yourself: `se issue next --take` fires the routine
once after its claim (the fan-out in [docs/issues.md](../../../docs/issues.md)).
