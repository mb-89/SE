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
   - **bare issue**: an open `se` issue at the top in no manifest, which no
     box takes: no parent, no sub-issues, not a manifest, retro, overhaul or
     issue for a person, nothing holds it and nothing claims it. An `se`
     built before manifests still files such issues.
   - **waiting on a person**: an `se-person` issue, with what it holds up.
     Reported, never fixed.

   Claimed work is moving while its branch was pushed, or the issue taken
   over, within the hour (the activity GitHub records for the branch, its
   creation included, or the last takeover marker: the lease reads it the
   same way), while its CI runs, or while a takeover of it is in flight: the
   last takeover marker names the same head and is less than an hour old.
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
   - a bare issue is filed into the open misc manifest (`se fleet fix`, the
     manifest `se issue new` files into, opening the next one where none is
     open, then GitHub's sub-issues link): it moves work there is already,
     and files no issue of its own;
   - an impossible block, any other leftover claim, or anything else with no
     remedy is reported by `se fleet check` (and the briefing), never filed:
     an issue is work, not a report ([principle 12](principles.md)).
4. **A takeover is recorded once.** A takeover is recorded with
   `<!-- se:takeover N -->` on its issue, part of the take's own write. It
   labels the issue `se-final`, and a stuck or conflicted `se-final` issue
   is taken over again, never handed to a person.
5. **`se fleet fix` writes no record.** Turning auto-merge on, deleting a
   spent branch and filing a bare issue into the misc manifest are their own
   record on GitHub; it writes no comment, and no issue but the next misc
   manifest, where a bare issue finds none open.

## The commands

<!-- se:manifest usage fleet -->
```
se fleet check [--json] [--repo OWNER/NAME]
se fleet fix [--json] [--repo OWNER/NAME]
se fleet plugins --into DIR
se fleet prune [--apply] [--json] [--repo OWNER/NAME]
se fleet rules [--json] [--repo OWNER/NAME]
se fleet trust [--rev REV] [--json]
```
<!-- /se:manifest -->

`se fleet check` lists the findings. Where GitHub's answers to its reads
say the hour's quota of requests has fallen below `github/config/quota-floor`
percent of its limit, a last line says how many are left and when the hour
resets (`quota` in its JSON): the boxes and every person's session share the
owner's one token ([io.md](io.md#living-within-githubs-rate-limits)). It is
no finding, so `se fleet fix` files nothing for it. `se fleet fix` runs the
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

## Merging into main

main's ruleset requires the check `check`, and no longer requires a PR to be
up to date with main before it merges (the owner switched the strict setting
off, 2026-10-14): **a PR merges once its own CI is green, and only a conflict
holds it back.** Waiting for up to date sent every open PR back for another
merge of main, battery and CI run each time one merged. The price is that two
PRs green apart can break main together, so **CI runs on every push to main
too, and a red main is the fleet's first job.** Every land and every keep
merges `origin/main` in and runs the battery, so a red main fails every box's
next check: the box whose check fails on what main brought fixes main first,
on its own branch, and lands that fix before its own work goes on. The rest
of the owner's rule (2026-10-14) stands: **a box stays with its PR until it
merges, it pushes only what is checked, and CI trusts the battery the box
already ran.** The merge queue is not offered for a repository a personal
account owns, and a push made with a workflow's own token starts no CI.

- **The battery records what it passed, in the checkout.** `tests/check.sh`
  writes the git tree it ran over into one file, `tests/passed`
  (`battery/config/passed`, the one place its path is set): HEAD's tree with
  that file left out, so recording a pass changes nothing it names, read
  from a clean worktree (the file aside) before the first step and again
  once it passed. A battery run is bound to the exact code.
- **`se issue land` pushes only what is current and checked.** It merges
  origin's copy of the branch and then `origin/main` into it before it runs
  the check, so the check runs on the main of the moment. It refuses to push
  a tree the battery did not record as passed, and a branch `origin/main`
  (fetched again after the check) has moved past. A merge that conflicts
  is undone, and the box resolves it by hand (never a rebase, never a
  force-push); one that conflicts in the record alone is settled, since the
  battery writes it anew. It commits the record with the work, so the pushed
  commit holds it.
- **CI trusts that record.** The `check` job, the one main's ruleset
  requires, first runs `se fleet trust --rev` on the commit it checked out
  (a PR's merge commit, or a push to main), with an `se` built outside the
  checkout: where that commit's record names its own tree, it passes in
  seconds. A missing record (a person's push without SE) or a stale one
  (main moved since) runs the battery. It asks GitHub nothing. It is trust in
  one's own boxes: faking the record is sabotage, not an accident.
- **The box keeps each PR it opened until it merges.** The worker that
  landed it runs `se issue keep` in its worktree: every minute it looks at
  the PR, and whenever main has moved past the branch on origin it merges
  `origin/main` in (never a rebase), runs the battery, commits its record
  and pushes as `se issue land` does; CI passes in seconds on the record.
  The PR does not wait for it to merge: auto-merge merges it once its CI is
  green. Keeping it up to date re-checks it against the main it merges into,
  and finds a conflict before GitHub does. It answers
  within `--for` (8 minutes), saying the PR merged, another box took the
  issue over (a takeover marker, or another box's claim, since it started),
  or that it is still open, and the worker runs it again. A merge that
  conflicts, a failing check and a PR closed unmerged are errors the worker
  fixes before it lands again. The Stop hook counts an open PR as unfinished
  ([spec/issues.md](issues.md#the-stop-hook)), so a box ends only once its
  PRs have merged or are taken over.

## A rule main takes

A PR that adds or tightens an se rule breaks the PRs opened before it, and
each of their boxes used to find out only from its own red CI or its next
merge. So `se fleet rules` merges the head of every open se PR (an
`issue-<n>` branch) with `origin/main` in a worktree under
`.se/.runtime/rules`, builds `se` there, runs `se rules` on the merge, and
the Go tests that read what the battery checks against beside the rules:
`./cmd/se`, `./internal/battery/...` and `./internal/io/proc/...`, which hold
the budget test, the step-budget test and the programs list. A PR opened
before main added a battery step, a budget or a program breaks those without
breaking a rule. It comments on each PR it breaks the findings (a merge that
does not build is one; go test's timings are left out) and what to do: merge
main in, fix them, land again. The comment carries
`<!-- se:rules KEY -->`, the findings' hash, so the same findings are told
once. A PR that conflicts with main is left to its takeover; one whose check
fails is reported, and the others are still checked. The workflow
`.github/workflows/rules.yml` runs it on every push to main that changes
`src/internal/rules`, `tests/check.sh`, `src/internal/battery`,
`spec/budgets.yaml` or `src/internal/io/proc`, and on demand.
