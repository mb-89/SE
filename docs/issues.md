# Issues: how the fleet picks its work

SE's work items are GitHub issues. These rules say which issue a box may work
on next, how it claims it, and how issues and their dependencies are created.
They live here and nowhere else; `se issue next` and `se issue new` (in
`internal/issues`) are their one implementation, so the choice is deterministic
and no prompt restates it.

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
