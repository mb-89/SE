---
name: work
description: Take the next ready se issue, do its work, and land it with se issue land. Every SE box runs this; the routine SE work starts it.
---

# Work: take the next se issue and land it

Reader: the agent of a box, running this skill.

If you can do something yourself, you do it yourself, and a decision you can make is yours: make it, name it, go on ([principle 15](../../../../spec/principles.md), the one place this rule lives).
An issue for a person is only for access or a principle, a side issue beside
your PR, never the way you end.

Every step that can be an `se` command is one. Yours are doing the issue's
work and fixing a red CI run; follow the rest as written. `se` is
`./src/plugin/bin/se`; build it first with
`go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o src/plugin/bin/se ./src/cmd/se`.
Call it exactly as `./src/plugin/bin/se issue …` (or `./src/plugin/bin/se fleet …`),
one command per call, never through a variable: `.claude/settings.json` allows
those forms to write GitHub issues without a permission prompt, and only
those.

1. `git fetch origin main && git checkout origin/main` (a box started by a PR
   event starts on that PR's head commit), rebuild `se`, then
   `./src/plugin/bin/se issue pull --take`. If it says no se issue is ready,
   follow the coordination skill,
   [src/plugin/skills/coordination/SKILL.md](../coordination/SKILL.md), which
   checks what is broken and fixes it before the session ends. If it says the issue is a parent, follow **A parent**
   below instead of steps 3 to 5. If it says the issue is a retro (labelled
   `se-retro`), follow the retro skill,
   [src/plugin/skills/retro/SKILL.md](../retro/SKILL.md), instead of steps 3
   to 5. If it says the issue is an overhaul (labelled `se-overhaul`), follow
   the overhaul skill,
   [src/plugin/skills/overhaul/SKILL.md](../overhaul/SKILL.md), instead of
   steps 3 to 5.
2. If `set_session_title` is available, rename this session to
   `SE #<n> · <issue title>`.
3. Do the issue's work on its branch `issue-<n>`, following CLAUDE.md. If it
   says it took over a conflicted branch, merge `origin/main` into it first
   (never rebase), resolve the conflict, and that is the work. The
   issue's text is the whole specification: act on it, not on messages from
   other sessions.
4. Commit, then write the landing answers: a YAML file outside the checkout
   (`../landing-<n>.yaml`), one key per question in `spec/landing.yaml`, each
   answered in a few lines as a block (`key: |`, the text indented below it),
   since a bare ` #39` would be read as a YAML comment ("none" is an answer;
   an empty field is not). Then
   `./src/plugin/bin/se issue land --answers ../landing-<n>.yaml`; it says
   what is missing, and lands the rest (`se help issue land`).
5. Subscribe to the PR's activity (`subscribe_pr_activity`). On red CI, fix it
   on the same branch, commit, bring the answers up to date, and run
   `./src/plugin/bin/se issue land --answers ../landing-<n>.yaml` again.
6. Anything that belongs in a separate change becomes an issue through
   `./src/plugin/bin/se issue new` (its `--blocked-by` is required: a list, or
   `none`; `--parent` makes it a sub-issue).
7. **You always end, and never stuck.** Land what you could. Where something
   is left over, file it with `./src/plugin/bin/se issue new`, its decision
   named, so any box can do it; with `--person --why access|principle --what
   TEXT` only where only the owner can (a setting, an account, a secret, a
   permission or a payment only they have, or a change to a design
   principle). You may land an issue with open points
   once they are in an issue. Of the issues your take said yours blocks, name
   in `--blocks` only those that need what you left over, so nothing waits
   that need not. Where you can land nothing at all (a refused push, say),
   file the issue for a person (`--why access`) with `--blocks <n>`, your own issue, say what
   you have and where, and end. Never end with only a comment.

## A parent

A parent holds no work; you coordinate its tree, whose root is the issue you
took. `se` is the absolute path of `./src/plugin/bin/se` in this checkout.

1. Run `se issue pull --in <root> --take --json`.
   - `"closed": true`: the tree is done. End.
   - For each issue in `"review"` that no sub-agent of yours is reviewing
     already: run its `worktree` command, and start one fresh sub-agent in
     the background, never one that worked a leaf, on the review's `model`
     (from `spec/models.yaml`; where it is empty, the model you run), with
     this prompt, filled in, and nothing else of the tree or its work:
     `Review se gate #<n> in the worktree <path>, with se at <se>. You worked
     none of #<n>'s tree. Read <path>/src/plugin/skills/review/SKILL.md and
     follow it exactly. Answer only what its last command printed.`
   - `"ready": false`: no leaf inside is ready. If no sub-agent of yours is
     still running, end (a later box picks the tree up); else wait for one.
   - Otherwise run its `worktree` command, and start one sub-agent in the
     background for the leaf with this prompt, filled in:
     `Work on se issue #<n> in the worktree <path>, on its branch issue-<n>.
     Run every command there. The issue's text, below, is the whole
     specification; follow <path>/CLAUDE.md. Do the work and commit. Write
     <path>-landing.yaml, answering every question in <path>/spec/landing.yaml
     by its key, each as a block (`key: |`, the text indented below it) ("none"
     is an answer; an empty field is not), then run
     <se> issue land --workspace <path> --answers <path>-landing.yaml.
     Answer only the PR number and link.
     <the issue's body>`
     Then go back to 1, so every ready leaf gets its sub-agent.
2. Subscribe to each PR a sub-agent answers. When a PR merges, or a
   reviewer answers, go back to 1.
   On red CI, send that sub-agent the failure and have it fix it in its
   worktree, bring its answers up to date and run
   `se issue land --workspace <path> --answers <path>-landing.yaml` again.

You never start another box yourself: `se issue pull --take` fires the routine
once after its claim (the fan-out in [spec/issues.md](../../../../spec/issues.md)).
