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
se fleet trust [--json]
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

## Up to date with main

CI must run on what lands, so main's ruleset merges a PR only when its
branch is up to date with main (its required check `check` is strict): a PR
whose CI ran before main moved waits. The merge queue is not offered for a
repository a personal account owns, and a push made with a workflow's own
token starts no CI, so no workflow can bring a PR up to date either. The
owner's rule (2026-10-14): **a box stays with its PR until it merges, it
pushes only what is up to date with main and checked, and CI trusts the
battery the box already ran.**

- **The battery stamps what it passed.** `tests/check.sh` writes one file
  in the checkout, the stamp (`tests/battery.stamp`; the issues instance's
  `config/stamp` in `src/index/wiring.yaml` names its path, and
  `src/internal/battery`, `Stamp`, is its built-in value). It holds the hash
  of the tree the battery ran over with the stamp itself left out: SHA-256
  over every entry `git ls-tree -r` lists of `HEAD` but the stamp's, of a
  clean worktree (a changed stamp counts as clean), read before the first
  step and again once it passed. A battery run is bound to the exact code,
  and committing a new stamp leaves the hash as it was. `.gitattributes`
  merges the stamp as a union, so two branches that both changed it merge
  without a conflict, into a stamp that names no hash until the battery runs
  again.
- **`se issue land` pushes only what is current and checked, its stamp
  committed with it.** It merges origin's copy of the branch and then
  `origin/main` into it before it runs the check, so the check runs on what
  lands. It then commits the stamp, alone, where it changed (the landing
  facts count no such commit), and refuses to push a tree the stamp does not
  name, and a branch `origin/main` (fetched again after the check) has moved
  past: only a fast-forward onto main is pushed, and main's ruleset enforces
  the merge side. A merge that conflicts is undone, and the box resolves it
  by hand (never a rebase, never a force-push). A leaf landing into its
  manifest's branch commits the stamp too. Nothing is posted to GitHub for
  it: the commit status `se/battery` it posted before is gone, since the
  cloud boxes' proxy refuses it (#449, #468).
- **CI trusts the stamp.** The `check` job, the one main's ruleset
  requires, runs on every pull request and on every push to main. It first
  runs `se fleet trust` (built from the tree checked out, outside the
  checkout), which computes the same hash of the tree checked out, `HEAD`
  with the stamp left out, and reads the stamp `HEAD` holds. Where they
  match, it passes in seconds. Where they differ, it runs the battery as
  before: on a pull request CI checks out the PR's merge with main, which
  is the tree the box stamped only while main has not moved past the
  branch; on a push to main the squash commit holds the PR's tree, and so
  its stamp. A missing or stale stamp (a person's push without SE, or a
  union of two) runs the battery too. It reads no GitHub. It is trust in
  one's own boxes, not a proof: whoever can push can commit a stamp, as they
  could post the status before, and the owner changes no setting.
- **The box keeps each PR it opened until it merges.** The worker that
  landed it runs `se issue keep` in its worktree: every minute it looks at
  the PR, and whenever main has moved past the branch on origin it merges
  `origin/main` in (never a rebase), runs the battery, commits its stamp
  and pushes as `se issue land` does. The push starts CI like any person's
  push, CI passes in seconds on the stamp, and auto-merge merges it. It answers
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
