# Issues: how the fleet picks its work

SE's work items are GitHub issues. These rules say which issue a box may work
on next, how it claims it, and how issues and their dependencies are created.
They live here and nowhere else; `se issue next`, `se issue new` and
`se issue land` (in `internal/issues`) are their one implementation, so the
choice is deterministic and no prompt restates it.

## The rules

- **Fleet work**: an open issue carrying the label `se`. Other issues are not
  the fleet's.
- **Created**: fleet issues are created with `se issue new` and no other way.
  It labels the issue `se` and requires `--blocked-by`, so every issue declares
  its dependencies when it is made, even if that is `none`.
- **Blockers**: an issue waits while any of its blockers is open. Blockers are
  GitHub's native "blocked by" links, and nothing else; a "Blocked by: #12"
  line in an issue's body does not block it. `se issue new --blocked-by` is
  how those links are written; agents never write dependencies any other way,
  and there is no command to add or remove them later.
- **Claimed**: an issue whose branch `issue-<n>` exists on origin is claimed. A
  box claims an issue by pushing that branch from the current `origin/main`. A
  push is atomic, so if two boxes race, the second push is refused and that box
  moves to the next issue.
- **Order**: the lowest issue number among the ready ones.
- **Done**: the PR's body says `Fixes #n`, so GitHub closes the issue when the
  PR merges, and the issues it blocked become ready.

## The commands

    se issue next [--take [N]] [--json] [--repo OWNER/NAME]
    se issue land [--json] [--repo OWNER/NAME]
    se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--json] [--repo OWNER/NAME]

`se issue next` prints the next ready issue (number, title, link and body), or
says that none is ready; it exits 0 either way. A session has it as
`/se issue next`.

`se issue next --take` claims the next ready issue, and `--take N` (or
`--take=N`) issue `N`: it pushes `origin/main` as `issue-<n>` (a push that may
only create the branch, never move it), then checks the branch out. Where the
push is refused because another box claimed the issue first, it moves to the
next ready issue. It prints what it took, or that nothing is ready. `--take N`
refuses an issue that is not ready and says why. There is no separate `take`
command.
Once it has claimed an issue, `--take` fires the routine once (the fan-out,
below) and adds a line saying what the fire did; with `--json` that line is
the field `fanout`.

`se issue land` runs on the checked-out `issue-<n>` branch. It refuses a tree
with uncommitted changes, runs `tests/check.sh` and goes on only if it passes,
pushes the branch, opens one PR against main titled after the issue with the
body `Fixes #<n>`, and turns on auto-merge with squash; a PR with nothing left
to wait for is squash-merged at once. It prints the PR's number and link (with
`--json`: `{"issue","number","url","created","merged"}`). Where the branch's PR
is open already, it pushes and reports that PR, so running it again after a
fix for red CI is safe. A session has it as `/se issue land`.

`se issue new` creates an issue labelled `se` on the repository and links it as
blocked by each issue `--blocked-by` names, then prints its number and link
(with `--json`: `{"number","url","blocked_by"}`). `--blocked-by` is required: a
comma-separated list of issue numbers (`--blocked-by 5,8`) or the word `none`.
Every issue in the list is looked up before anything is written, so a list
naming an issue that does not exist, or a pull request, creates nothing. The
body comes from `--body` or from `--body-file`, one of them. A session has it
as `/se issue new`.

Both read and write GitHub through `gh api` (the links through
`/repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by`), which owns the
authentication, and work on the repository of the workspace's `origin` unless
`--repo` names another.

## The routine

Boxes are cloud sessions that work unattended. Every box is started by the
routine `SE work`, whose whole prompt is

    run the work skill

and the work skill is [.claude/skills/work/SKILL.md](../.claude/skills/work/SKILL.md).
The routine has two triggers:

- a GitHub trigger on `pull_request.closed` with is-merged = true and base
  branch = main, so every merge into main starts a box, which may find the
  issues that merge unblocked;
- a schedule, every 4 hours.

It also has an API trigger, which `se` fires for the fan-out.

### Fan-out

One merge starts one box, but there should be as many boxes as there is ready
work. So boxes start boxes, mechanically, never by an agent's choice:

- **Fan-out:** whenever `se issue next --take` has claimed an issue, it fires
  the routine `SE work` once, so another box starts and takes the next ready
  issue. That box fires again after its own claim, and so on.
- **The end:** a box that finds nothing ready claims nothing and fires
  nothing, so the fan-out ends by itself. Such a box leaves at once.
- **No cap** on boxes in flight; the owner decided against one. The only limit
  is the routine's own: 30 fires an hour. A fire refused for that is reported
  and the box goes on.
- **How it fires:** an HTTP POST of the body `{}` to the URL in
  `SE_ROUTINE_FIRE_URL`, with the headers
  `Authorization: Bearer $SE_ROUTINE_FIRE_TOKEN`,
  `anthropic-beta: experimental-cc-routine-2026-04-01`,
  `anthropic-version: 2023-06-01` and `Content-Type: application/json`; the
  route is documented at <https://code.claude.com/docs/en/routines>. `se`
  prints the started session's link from the answer.
- **Never fails a claim:** where either variable is unset (on a desk, say),
  `se` says in one line that fan-out is off; a failed or refused fire is
  reported the same way. The claim stands either way. The token is never
  printed.

The owner's one-time setup: add an API trigger to the routine `SE work`, and
put its fire URL in `SE_ROUTINE_FIRE_URL` and its token in
`SE_ROUTINE_FIRE_TOKEN` in the cloud environment the routine's boxes run in.

No agent starts another box; only this fan-out and the triggers above do.
