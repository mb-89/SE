# Coordination: finding and repairing what is broken

Reader: whoever changes how the fleet finds and repairs what is broken.

On 13 October the fleet stopped twice while open issues remained. Every box
found "No se issue is ready" and left, and nobody looked at why nothing was
ready. Both times the cause was visible on GitHub in a minute: one claimed
issue's PR in conflict, everything else blocked behind it. So **the take
repairs what is stuck, and `se fleet check` says what else is broken.** A box
does not sweep the fleet when it finds nothing to take: every idle box
sweeping at once wrote the same issues and comments many times over
(14 October). It ends, and the next take takes over what is stuck.

## The rules

1. **The take repairs, the box does not sweep.** `se issue pull --take`
   offers a stuck claim as a takeover, so the next box takes it over at its
   take, its input. A box that takes nothing ends
   ([spec/issues.md](issues.md#the-box)); it runs neither `se fleet check`
   nor `se fleet fix`.
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
3. **What has a known remedy is fixed,** in the order
   the command lists, each with the mechanism that already exists:
   - a conflicted, red or stalled claim, or a claim with no PR, is taken
     over at a take: `se issue pull --take` fetches its branch as it
     stands, and the box hands it to the agent the take names, which lands it;
   - a green PR with auto-merge off gets auto-merge turned on (`se fleet fix`);
   - a leftover claim whose issue is closed and whose branch has no open PR
     is left to the prune workflow, which deletes the branch (see **Pruning**
     below); `se fleet check` reports it if the branch is still there a day
     after the issue closed (the workflow failed);
   - any other leftover claim whose issue is no open `se` issue and whose
     branch main holds whole (no commit main lacks) has its branch deleted
     (`se fleet fix`, by `git push origin --delete` from the workspace, the
     transport `se issue land` pushes through): nothing is lost, and nothing
     else could clear it;
   - an impossible block, any other leftover claim, or anything else with no
     remedy is reported by `se fleet check` (and the briefing), never filed:
     an issue is work, not a report ([principle 12](principles.md)).
4. **A takeover is recorded once.** A takeover is recorded with
   `<!-- se:takeover N -->` on its issue, part of the take's own write. It
   labels the issue `se-final`, and a stuck or conflicted `se-final` issue
   is taken over again, never handed to a person.
5. **`se fleet fix` writes no record.** Turning auto-merge on and deleting a
   spent branch are their own record on GitHub; it writes no comment and no
   issue.

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
names the takeovers it leaves to the next take; a remedy that fails is
reported and the remedies after it are still applied; everything else is
reported, never filed. `se issue pull --take <n>` on a claimed leaf
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
  moved past up to date through GitHub's update-branch, and starts the
  `ci` workflow on its new head itself, since a push made with the
  repository's token starts no workflow. A PR that conflicts with main is
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
