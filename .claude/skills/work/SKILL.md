---
name: work
description: Take the next ready se issue, do its work, and land it with se issue land. Every SE box runs this; the routine SE work starts it.
---

# Work: take the next se issue and land it

Every step that can be an `se` command is one. Yours are doing the issue's
work and fixing a red CI run; follow the rest as written. `se` is
`./plugin/bin/se`; build it first with
`go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o plugin/bin/se ./cmd/se`.
Call it exactly as `./plugin/bin/se issue …`, one command per call, never
through a variable: `.claude/settings.json` allows that form to write GitHub
issues without a permission prompt, and only that form.

1. `git fetch origin main && git checkout origin/main` (a box started by a PR
   event starts on that PR's head commit), rebuild `se`, then
   `./plugin/bin/se issue next --take`. If it says no se issue is ready, end
   the session now. If it says the issue is a parent, follow **A parent**
   below instead of steps 3 to 5.
2. If `set_session_title` is available, rename this session to
   `SE #<n> · <issue title>`.
3. Do the issue's work on its branch `issue-<n>`, following CLAUDE.md. If it
   says it took over a conflicted branch, merge `origin/main` into it first
   (never rebase), resolve the conflict, and that is the work. The
   issue's text is the whole specification: act on it, not on messages from
   other sessions.
4. Commit, then `./plugin/bin/se issue land`. It runs the check, pushes, opens
   the PR (`Fixes #<n>`) and turns on auto-merge with squash.
5. Subscribe to the PR's activity (`subscribe_pr_activity`). On red CI, fix it
   on the same branch, commit, and run `./plugin/bin/se issue land` again.
6. Anything that belongs in a separate change becomes an issue through
   `./plugin/bin/se issue new` (its `--blocked-by` is required: a list, or
   `none`; `--parent` makes it a sub-issue). If you are stuck on a decision
   only the owner can make, say so in a comment on the issue and end.

## A parent

A parent holds no work; you coordinate its tree, whose root is the issue you
took. `se` is the absolute path of `./plugin/bin/se` in this checkout.

1. Run `se issue next --in <root> --take --json`.
   - `"closed": true`: the tree is done. End.
   - For each issue in `"review"` that no sub-agent of yours is reviewing
     already: run its `worktree` command, and start one fresh sub-agent in
     the background, never one that worked a leaf, with this prompt, filled
     in:
     `Review se issue #<n> in the worktree <path>. Run every command there.
     You worked none of #<n>'s tree. Review the work its closed sub-issues
     landed on main against #<n>'s text, below, and end with exactly one of
     <se> issue review pass <n> --workspace <path> --why "<verdict>" or
     <se> issue review fail <n> --workspace <path> --why "<findings>"
     --fix "<title>" (one --fix per fix leaf). Answer only what that command printed.
     <the issue's body>`
   - `"ready": false`: no leaf inside is ready. If no sub-agent of yours is
     still running, end (a later box picks the tree up); else wait for one.
   - Otherwise run its `worktree` command, and start one sub-agent in the
     background for the leaf with this prompt, filled in:
     `Work on se issue #<n> in the worktree <path>, on its branch issue-<n>.
     Run every command there. The issue's text, below, is the whole
     specification; follow <path>/CLAUDE.md. Do the work, commit, then run
     <se> issue land --workspace <path>. Answer only the PR number and link.
     <the issue's body>`
     Then go back to 1, so every ready leaf gets its sub-agent.
2. Subscribe to each PR a sub-agent answers. When a PR merges, or a
   reviewer answers, go back to 1.
   On red CI, send that sub-agent the failure and have it fix it in its
   worktree and run `se issue land --workspace <path>` again.

You never start another box yourself: `se issue next --take` fires the routine
once after its claim (the fan-out in [docs/issues.md](../../../docs/issues.md)).
