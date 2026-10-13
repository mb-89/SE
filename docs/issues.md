# Issues: how the fleet picks its work

SE's work items are GitHub issues. These rules say which issue a box may work
on next and how it claims it. They live here and nowhere else; `se issue next`
and `se issue take` (in `internal/issues`) are their one implementation, so the
choice is deterministic and no prompt restates it.

## The rules

- **Fleet work**: an open issue carrying the label `se`. Other issues are not
  the fleet's.
- **Blockers**: an issue waits while any of its blockers is open. Blockers are
  GitHub's native "blocked by" links, and nothing else; a "Blocked by: #12"
  line in an issue's body does not block it. An `se` command that writes those
  links comes in a separate issue; agents never write dependencies any other
  way.
- **Claimed**: an issue whose branch `issue-<n>` exists on origin is claimed. A
  box claims an issue by pushing that branch from the current `origin/main`. A
  push is atomic, so if two boxes race, the second push is refused and that box
  moves to the next issue.
- **Order**: the lowest issue number among the ready ones.
- **Done**: the PR's body says `Fixes #n`, so GitHub closes the issue when the
  PR merges, and the issues it blocked become ready.

## The command

    se issue next [--take [N]] [--json] [--repo OWNER/NAME]

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

It reads GitHub through `gh api`, which owns the authentication, and works on
the repository of the workspace's `origin` unless `--repo` names another.
