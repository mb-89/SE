# Coordination: a box that finds nothing to take

On 13 October the fleet stopped twice while open issues remained. Every box
found "No se issue is ready" and left, and nobody looked at why nothing was
ready. Both times the cause was visible on GitHub in a minute: one claimed
issue's PR in conflict, everything else blocked behind it. So: **a box that
finds nothing to take checks whether something is broken, fixes what it can,
and only then leaves.**

## The rules

1. **The work skill hands over.** When `se issue next --take` takes nothing,
   the box runs the coordination skill,
   [src/plugin/skills/coordination/SKILL.md](../src/plugin/skills/coordination/SKILL.md),
   before it ends.
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
3. **The coordination skill fixes what has a known remedy,** in the order
   the command lists, each with the mechanism that already exists:
   - a conflicted, red or stalled claim, or a claim with no PR, is taken
     over: `se issue next --take <n>` checks its branch out as it stands, the
     box merges `origin/main` into it, makes it green and lands it again with
     `se issue land`;
   - a green PR with auto-merge off gets auto-merge turned on (`se fleet fix`);
   - a leftover claim whose issue is closed and whose branch has no open PR
     is left to the prune workflow, which deletes the branch (see **Pruning**
     below); `se fleet fix` reports it as an issue only if the branch is
     still there a day after the issue closed (the workflow failed);
   - any other leftover claim whose issue is no open `se` issue and whose
     branch main holds whole (no commit main lacks) has its branch deleted
     (`se fleet fix`): nothing is lost, and nothing else could clear it;
   - an impossible block, any other leftover claim, or anything else with no remedy is
     reported as an issue (`se fleet fix`, through the same code as
     `se issue new`), labelled `se-person` and assigned to the repository's
     owner where it is a judgment: a cycle, a blocker outside the fleet, a
     green PR auto-merge does not merge.
4. **It never fixes the same thing twice.** A takeover is recorded with
   `<!-- se:takeover N -->`, every other fix with `<!-- se:fleet KEY M -->` on
   the finding's issue (`M` is the issue it made, or 0). A finding that comes
   back after its fix goes to a person: a takeover labels the issue
   `se-final`, and a takeover of an `se-final` issue labels it `se-person`
   instead, and any other finding becomes an `se-person` issue. A finding
   already reported as an issue that is still open is left as it is.
5. **The record.** The box lands nothing of its own, so each fix is a comment
   on the issue it acted on, saying what was found and what was done (the
   takeover's comment, or the `se fleet fix` record). When it found nothing, it
   says nothing.

## The commands

`se fleet check [--json]` lists the findings. `se fleet fix [--json]` runs the
same check and applies every remedy that needs no checkout, in order, and
names the takeovers it leaves to the box; an issue it made that a box may
take fires the routine once. `se issue next --take <n>` on a claimed leaf
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
