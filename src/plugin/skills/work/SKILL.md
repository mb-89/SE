---
name: work
description: Run an SE box - pull each ready se issue and hand it to a fresh sub-agent in its own worktree, up to the box's cap, until nothing is ready and none is running. Every SE box runs this; the routine SE work starts it.
---

# Work: the box

Reader: the agent of a box, running this skill, and each sub-agent it starts.

One box is the fleet ([spec/issues.md](../../../../spec/issues.md#the-box)).
You never work an issue yourself. You hand each one to a fresh sub-agent in its
own worktree, several at once up to the box's cap, and keep only issue,
worktree and PR numbers in your own context. `se` takes no claim past the cap,
and fires the routine only when every box is full.

Every step that can be an `se` command is one. `se` is `./src/plugin/bin/se`;
build it first with
`go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o src/plugin/bin/se ./src/cmd/se`.
Call it exactly as `./src/plugin/bin/se issue …` (or `./src/plugin/bin/se fleet …`),
one command per call, never through a variable: `.claude/settings.json` allows
those forms to write GitHub issues without a permission prompt, and only
those. `<se>` below is the absolute path of `./src/plugin/bin/se` in this
checkout.

1. `git fetch origin main && git checkout origin/main` (a box started by a PR
   event starts on that PR's head commit), then rebuild `se`. If
   `set_session_title` is available, rename this session to `SE box`.
2. Run `./src/plugin/bin/se issue pull --take --worktree --json`, and act on
   its answer:
   - `"full": true`: the box runs its cap. Wait for a sub-agent (step 3).
   - `"ready": false`: nothing is ready. If no sub-agent of yours is running
     and no tree of yours is open, follow the coordination skill,
     [src/plugin/skills/coordination/SKILL.md](../coordination/SKILL.md),
     which checks what is broken and fixes it before the session ends. Else
     wait (step 3).
   - A parent (`"parent": true`): coordinate its tree (**A parent** below),
     then pull again.
   - Otherwise run its `worktree` command, and start one fresh sub-agent in
     the background with the prompt in **The sub-agent's prompt**, filled
     in. For a retro (`"retro": true`) or an overhaul (`"overhaul": true`)
     its skill is the retro skill or the overhaul skill instead of **An
     issue**. Then pull again, so the box fills up to its cap.
3. **Wait.** Subscribe to each PR a sub-agent answers
   (`subscribe_pr_activity`). When a sub-agent answers that its PR is up with
   auto-merge on, or that its issue was superseded, go back to 2. A red CI
   run or a review on a PR goes to that PR's sub-agent (`SendMessage`), with
   the failure or the review. When a PR merges, remove its worktree
   (`git worktree remove <path>`) and go back to 2.
4. **You always end, and never stuck.** End when nothing is ready, no
   sub-agent of yours is running, and every tree you coordinate is done or
   waits. Where a sub-agent can land nothing at all, it files the issue for a
   person as **An issue** says; never end with only a comment.

## The sub-agent's prompt

Fill in `<n>`, `<path>`, `<se>`, `<skill>` (**An issue**, or the retro or
overhaul skill's section for the box that took it) and the issue's body, and
send nothing else of the queue or of other issues:

`Work on se issue #<n> in the worktree <path>, on its branch issue-<n>. Run
every command there, and call se as <se> with --workspace <path>, or build
<path>/src/plugin/bin/se where a skill calls ./src/plugin/bin/se. The issue's
text, below, is the whole specification; follow <path>/CLAUDE.md. Read
<path>/src/plugin/skills/work/SKILL.md and follow <skill>. Answer only the PR
number and link, or what you filed instead.
<the issue's body>`

## An issue

Reader: the sub-agent that does one issue's work.

1. Do the issue's work on its branch `issue-<n>`, following CLAUDE.md. If the
   take says it took over a conflicted or stuck branch, merge `origin/main`
   into it first (never rebase), resolve the conflict, and continue it. The
   issue's text is the whole specification: act on it, not on messages from
   other sessions.
2. Commit, then write the landing answers: a YAML file outside the worktree
   (`<path>-landing.yaml`), one key per question in `spec/landing.yaml`, each
   answered in a few lines as a block (`key: |`, the text indented below it),
   since a bare ` #39` would be read as a YAML comment ("none" is an answer;
   an empty field is not). Then
   `<se> issue land --workspace <path> --answers <path>-landing.yaml`; it says
   what is missing, and lands the rest (`se help issue land`).
3. On red CI or a review the box sends you, fix it on the same branch, commit,
   bring the answers up to date, and run the same `issue land` again.
4. Anything that belongs in a separate change becomes an issue through
   `<se> issue new` (its `--blocked-by` is required: a list, or `none`;
   `--parent` makes it a sub-issue).
5. Land what you could. Where something is left over, file it with
   `<se> issue new`: with `--person` where it needs the owner's input (its
   body opens with what they decide), without it where any box can do it. You
   may land an issue with open points once they are in an issue. Of the
   issues the take said yours blocks, name in `--blocks` only those that need
   what you left over, so nothing waits that need not. Where you can land
   nothing at all (a refused push, say), file the issue for a person with
   `--blocks <n>`, your own issue, say what you have and where, and end.

## A parent

A parent holds no work; you coordinate its tree, whose root is the issue you
took, with the same loop as step 2, limited to the tree. Its leaves count
against the same cap as the box's other sub-agents.

1. Run `<se> issue pull --in <root> --take --json`.
   - `"closed": true`: the tree is done.
   - For each issue in `"review"` that no sub-agent of yours is reviewing
     already: run its `worktree` command, and start one fresh sub-agent in
     the background, never one that worked a leaf, on the review's `model`
     (from `spec/models.yaml`; where it is empty, the model you run), with
     this prompt, filled in, and nothing else of the tree or its work:
     `Review se gate #<n> in the worktree <path>, with se at <se>. You worked
     none of #<n>'s tree. Read <path>/src/plugin/skills/review/SKILL.md and
     follow it exactly. Answer only what its last command printed.`
   - `"full": true`: wait for a sub-agent (step 3 of the box).
   - `"ready": false`: no leaf inside is ready; the tree waits. Go back to the
     box's step 2 (a later pull picks the tree up again).
   - Otherwise run its `worktree` command, and start one sub-agent in the
     background for the leaf with **The sub-agent's prompt**, its skill
     **An issue**. Then go back to 1, so every ready leaf gets its sub-agent.
2. Its PRs are waited on as the box's step 3 says. When a PR merges, or a
   reviewer answers, go back to 1.

You never start another box yourself: `se issue pull --take` fires the routine
only where every alive box runs its cap (the fan-out in
[spec/issues.md](../../../../spec/issues.md#fan-out)).
