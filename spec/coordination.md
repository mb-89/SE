# Coordination: a box that finds nothing to take

Reader: whoever changes what a box does when it finds nothing to take.

On 13 October the fleet stopped twice while open issues remained. Every box
found "No se issue is ready" and left, and nobody looked at why nothing was
ready. Both times the cause was visible on GitHub in a minute: one claimed
issue's PR in conflict, everything else blocked behind it. So: **a box that
finds nothing to take checks whether something is broken, fixes what it can,
and only then leaves.**

## The rules

1. **The box checks before it ends.** When `se issue pull --take` takes
   nothing, the box, the agent `se:coordinator`, checks the fleet and fixes
   it before it ends; its agent file says how (see the agents in
   [spec/issues.md](issues.md#the-box)).
2. **The diagnosis is a command, not judgment.** `se fleet check` reads
   GitHub and lists every finding, each with its kind, its issue, its PR where
   there is one, and the remedy it names. It exits 0 and says `healthy` when it
   finds nothing; `--json` answers `{"healthy","findings"}`. It lists the kinds
   in this order, lowest issue first within a kind:
   - **stalled root**: open `se` issues exist but none is ready, and blocked
     ones wait, directly or through links and trees, on a claimed issue whose
     work is not moving (one of the claim findings below). The finding names
     that root, what it holds up, and its own finding as its cause; the root's
     own finding is not listed again.
   - **conflicted PR**: a claimed leaf's open PR is not mergeable
     (`mergeable_state` `dirty`).
   - **red PR**: a claimed leaf's PR fails a check run on its latest commit,
     with no push to its branch for an hour.
   - **green but unmerged**: CI is green and the PR merges, but auto-merge is
     off; or it is on and the PR has sat unmerged for an hour since the last
     push.
   - **no PR**: a claimed leaf whose branch has no PR, open or closed, and no
     push for an hour.
   - **leftover claim**: an `issue-<n>` branch whose issue is closed (or no
     open `se` issue), or whose PR was closed unmerged.
   - **impossible block**: an issue blocked by an issue closed as not planned,
     by an open issue no box works (not labelled `se`, or in another
     repository), or by itself through a cycle.
   - **waiting on a person**: an `se-person` issue, with what it holds up.
     Reported, never fixed.

   Claimed work is moving while its branch was pushed within the hour (the
   activity GitHub records for the branch, its creation included), while its
   CI runs, or while a takeover of it is in flight: the last takeover marker
   names the same head and is less than an hour old.
3. **The box fixes what has a known remedy,** in the order
   the command lists, each with the mechanism that already exists:
   - a conflicted, red or stalled claim, or a claim with no PR, is taken
     over: `se issue pull --take <n> --worktree` fetches its branch as it
     stands, and the box hands it to the agent the take names, which lands it;
   - a green PR with auto-merge off gets auto-merge turned on (`se fleet fix`);
   - a leftover claim whose issue is closed and whose branch has no open PR
     is left to the prune workflow, which deletes the branch (see **Pruning**
     below); `se fleet fix` reports it as an issue only if the branch is
     still there a day after the issue closed (the workflow failed);
   - any other leftover claim whose issue is no open `se` issue and whose
     branch main holds whole (no commit main lacks) has its branch deleted
     (`se fleet fix`, by `git push origin --delete` from the workspace, the
     transport `se issue land` pushes through): nothing is lost, and nothing
     else could clear it;
   - an impossible block, any other leftover claim, or anything else with no remedy is
     reported as an issue (`se fleet fix`, through the same code as
     `se issue new`), labelled `se-person` and assigned to the repository's
     owner where it is a judgment: a cycle, a blocker outside the fleet, a
     green PR auto-merge does not merge.
4. **It never fixes the same thing twice.** A takeover is recorded with
   `<!-- se:takeover N -->`, every other fix with `<!-- se:fleet KEY M -->` on
   the finding's issue (`M` is the issue it made, or 0). A finding that comes
   back after its fix goes to a person: a takeover labels the issue
   `se-final`, and a takeover of an `se-final` issue makes it wait on an
   issue for a person instead, and any other finding becomes an `se-person`
   issue. A finding
   already reported as an issue that is still open is left as it is.
5. **The record.** The box lands nothing of its own, so each fix is a comment
   on the issue it acted on, saying what was found and what was done (the
   takeover's comment, or the `se fleet fix` record). When it found nothing, it
   says nothing.

## The commands

<!-- se:manifest usage fleet -->
```
se fleet check [--json] [--repo OWNER/NAME]
se fleet fix [--json] [--repo OWNER/NAME]
se fleet plugins --into DIR
se fleet prune [--apply] [--json] [--repo OWNER/NAME]
se fleet refresh [--json] [--repo OWNER/NAME]
se fleet rules [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

`se fleet check` lists the findings. `se fleet fix` runs the
same check and applies every remedy that needs no checkout, in order, and
names the takeovers it leaves to the box; a remedy that fails is reported and
the remedies after it are still applied; an issue it made that a box may
take fires the routine once. `se issue pull --take <n>` on a claimed leaf
takes it over where the check finds it stuck, and refuses a claim whose work
is moving.

## Pruning

Cloud sessions cannot delete branches, so GitHub does it, with the
repository's own token. `se fleet prune` lists every `issue-<n>` branch whose
issue is closed and every `claude/*` branch whose last commit is more than an
hour old (so a session that has just pushed can still open its PR), each with
no open PR; `--apply` deletes them. It never touches `main` or any other
branch. The workflow `.github/workflows/prune.yml` runs
`se fleet prune --apply` when an issue or a PR closes, and every hour, and
its output names what it deleted.

## Up to date with main

CI must run on what lands, so main's ruleset merges a PR only when its
branch is up to date with main (its required check `check` is strict): a PR
whose CI ran before main moved waits. Two things keep it moving, with no
box in the loop:

- `se issue land` merges origin's copy of the branch and then `origin/main`
  into it before it runs the check, so the check runs on what lands and the
  push is a fast-forward. A merge that conflicts is undone, and the box
  resolves it by hand (never a rebase, never a force-push).
- `se fleet refresh` brings every open PR with auto-merge on that main has
  moved past up to date through GitHub's update-branch, and approves the
  `pull_request` run of `ci` that the update starts on its new head: a
  `git push` made with the repository's token starts no workflow, but
  update-branch starts that run, which waits in `action_required`, and the
  required check `check` waits on it. A PR that conflicts with main is
  left to its takeover; an update that fails is reported, and the workflow
  run goes red. The workflow `.github/workflows/refresh.yml` runs it on every
  push to main, and every hour.

## A rule main takes

A PR that adds or tightens an se rule breaks the PRs opened before it, and
each of their boxes used to find out only from its own red CI or its next
merge. So `se fleet rules` merges the head of every open se PR (an
`issue-<n>` branch) with `origin/main` in a worktree under
`.se/.runtime/rules`, builds `se` there, runs `se rules` on the merge, and
comments on each PR it breaks the findings (a merge that does not build is
one) and what to do: merge main in, fix them, land again. The comment carries
`<!-- se:rules KEY -->`, the findings' hash, so the same findings are told
once. A PR that conflicts with main is left to its takeover; one whose check
fails is reported, and the others are still checked. The workflow
`.github/workflows/rules.yml` runs it on every push to main that changes
`src/internal/rules`, and on demand.
