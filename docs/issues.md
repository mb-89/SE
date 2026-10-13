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

## Nesting: leaves are work, parents coordinate

Issues nest through GitHub's sub-issues, to any depth: an iteration is a
parent of milestones, a milestone a parent of work items. What an issue is
follows from its structure alone:

- **A leaf** (no sub-issues) is **work**: one worker does it on its branch
  `issue-<n>` and lands one PR with `se issue land`.
- **A parent** (has sub-issues) **holds no work of its own**. It is
  coordinated, never landed: `se issue land` refuses it, and it never gets a
  `Fixes` line.
- **Parents close by themselves.** Every `se issue` command first closes,
  deepest first, each open parent whose sub-issues are all closed, with a
  comment saying so; closing a parent can complete its own parent, which then
  closes in the same run.
- **Except for reviews.** A parent labelled `se-review` never closes by
  itself. Once its sub-issues are all closed it is *ready for review*, which
  is not work: it is never taken as a leaf, and it keeps blocking its
  dependents until it is closed (reviews are #15).
- **Order** comes from native "blocked by" links and nothing else. A leaf is
  ready when it is open, not claimed, and neither it nor any of its ancestors
  has an open blocker: with milestone M2 blocked by M1, no leaf of M2 starts
  before M1 has closed.
- **The top**: `se issue next` offers only issues without a parent. A parent
  there is ready while some leaf inside it is; a sub-issue is never offered at
  the top.
- **The tree's claim**: taking a parent at the top pushes `issue-<root>`,
  which claims the whole tree. That claim does not hold the tree from other
  boxes: a later box that finds a leaf ready inside it takes the parent again
  and picks the tree up from the claim. The leaves' own claims keep two
  coordinators from taking one leaf twice.
- **Leaves inside a tree** are claimed by `se issue next --in <root> --take`,
  each with its own branch `issue-<n>` from `origin/main`, and worked on in
  their own git worktrees, so several are in flight at once and land as
  separate PRs. `--in` reaches leaves at any depth, so the coordinator of the
  root hands out every leaf of the tree, and a sub-agent is only ever given a
  leaf.
- **The coordinator** is the box that took the parent. It starts one sub-agent
  per ready leaf inside its own box (no separate cloud sessions), each in the
  leaf's worktree, and repeats until the root has closed. When nothing inside
  is ready while the root is open, it ends; a later box picks the tree up.

## The commands

    se issue next [--in ROOT] [--take [N]] [--json] [--repo OWNER/NAME]
    se issue land [--json] [--repo OWNER/NAME]
    se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N] [--json] [--repo OWNER/NAME]

Every one of them first closes the parents whose sub-issues are all closed.

`se issue next` prints the next ready issue at the top (number, title, link
and body), or says that none is ready; it exits 0 either way. A parent is
marked as one (with `--json`: `"parent": true`), with the command that
coordinates it. A session has it as
`/se issue next`.

`se issue next --take` claims the next ready issue, and `--take N` (or
`--take=N`) issue `N`: it pushes `origin/main` as `issue-<n>` (a push that may
only create the branch, never move it), then checks the branch out. Where the
push is refused because another box claimed the issue first, it moves to the
next ready issue. It prints what it took, or that nothing is ready. `--take N`
refuses an issue that is not ready and says why. There is no separate `take`
command.

`se issue land` runs on the checked-out `issue-<n>` branch. It refuses an
issue with open sub-issues ("a parent holds no work") and a tree with
uncommitted changes, runs `tests/check.sh` and goes on only if it passes,
pushes the branch, opens one PR against main titled after the issue with the
body `Fixes #<n>`, and turns on auto-merge with squash; a PR with nothing left
to wait for is squash-merged at once. It prints the PR's number and link (with
`--json`: `{"issue","number","url","created","merged"}`). Where the branch's PR
is open already, it pushes and reports that PR, so running it again after a
fix for red CI is safe. A session has it as `/se issue land`.

`se issue new` creates an issue labelled `se` on the repository, makes it a
sub-issue of `--parent` where that is given, and links it as blocked by each
issue `--blocked-by` names, then prints its number and link
(with `--json`: `{"number","url","blocked_by","parent"}`). `--blocked-by` is required: a
comma-separated list of issue numbers (`--blocked-by 5,8`) or the word `none`.
Every issue in the list is looked up before anything is written, so a list
naming an issue that does not exist, or a pull request, creates nothing; so
does a `--parent` that does not exist. The
body comes from `--body` or from `--body-file`, one of them. A session has it
as `/se issue new`.

They read and write GitHub through `gh api` (the links through
`/repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by`, the tree through
`/repos/{owner}/{repo}/issues/{n}/sub_issues`), which owns the
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

No agent ever starts another box. A box whose `se issue next --take` finds
nothing ready leaves at once.
