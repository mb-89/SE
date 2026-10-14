# Issues: how the fleet picks its work

Reader: whoever changes how the fleet picks, claims, nests, lands or reviews its work.

SE's work items are GitHub issues. These rules say which issue a box may work
on next, how it claims it, and how issues and their dependencies are created.
They live here and nowhere else; `se issue pull`, `se issue new`,
`se issue land`, `se issue review`, `se issue resume` and `se issue tree` (in
`src/internal/issues`) are their one implementation, so the
choice is deterministic and no prompt restates it.

## The rules

- **Fleet work**: an open issue carrying the label `se`. Other issues are not
  the fleet's.
- **Created**: fleet issues are created with `se issue new` and no other way.
  It labels the issue `se` and requires `--blocked-by`, so every issue declares
  its dependencies when it is made, even if that is `none`. Every body it
  writes ends in the mark `<!-- se:new -->`, which the retro checks
  ([retro.md](retro.md)).
- **Agents**: what works an issue follows from its kind alone, in one place,
  the registry of kinds (`src/internal/issues/kinds.go`): a leaf gets
  `se:worker`, a parent `se:coordinator` (the box itself), a gate ready for
  review `se:reviewer`, a retro `se:retro` and an overhaul `se:overhaul`. The
  take names it (with `--json`: `agent`), and the box starts it. Each agent is
  one file of the plugin, holding its role's whole procedure
  ([The box](#the-box)).
- **Skills**: an issue names the skills its work needs in one place, the
  marked line `se issue new --skills` writes into its body. The take hands
  each over in full in its answer, and the session's log records it; no label
  picks a skill ([principle 22](principles.md)).
- **Blockers**: an issue waits while any of its blockers is open. Blockers are
  GitHub's native "blocked by" links, and nothing else; a "Blocked by: #12"
  line in an issue's body does not block it. `se issue new --blocked-by` is
  how those links are written; agents never write dependencies any other way,
  and there is no command to add or remove them later.
- **Claimed**: an issue whose branch `issue-<n>` exists on origin is claimed. A
  box claims an issue by pushing that branch from the current `origin/main`. A
  push is atomic, so if two boxes race, the second push is refused and that box
  moves to the next issue.
- **Order**: any conflicted claim first (below), then stuck work (see
  [Stuck work](#stuck-work)), then the lowest issue number among the ready
  ones.
- **Conflicted claims are taken over at once.** GitHub runs no CI on a PR
  that conflicts with main and sends nothing that wakes its box, so a
  conflicted claim would sit forever. Before offering anything else,
  `se issue pull --take` looks at every claimed leaf's open PR; one GitHub
  reports as not mergeable (`mergeable` false, `mergeable_state` `dirty`) is
  taken next, whatever its age. A `null` `mergeable` means GitHub has not
  computed it yet: `se` asks again shortly, and while it stays `null` it is no
  conflict. The box taking it checks out `issue-<n>` as it stands, merges
  `origin/main` into it (never a rebase, never a force-push), resolves the
  conflict and lands it again with `se issue land`.
- **A takeover makes the issue final**: it labels it `se-final`, the single
  record that it was taken over (see [spec/review.md](review.md), rule 5),
  and records it as a comment carrying the marker `<!-- se:takeover N -->`
  (stuck work writes the same marker), the human-readable record; a conflict
  takeover also records the PR head it found, `<!-- se:takeover-head SHA -->`.
  A PR still conflicted at that same head is a takeover in flight and is left
  to its box. Of two boxes writing the same `N` at once, the earlier comment
  wins and the other box deletes its own. A conflict on an issue that is
  already `se-final` (taken over before, for a conflict or stuck, or filed by
  a review) instead waits on an issue for a person, as a final stuck claim
  does (below).
- **Waits on a person**: an issue labelled `se-person` is never ready. Only
  issues minted for a person carry it (`se issue new --person`, and the issues
  se mints below and in [retro.md](retro.md)); every other issue that needs a
  person waits on one of those through a native "blocked by" link. No run
  waits on a person: a box, a retro and an overhaul always end.
- **Done**: the PR's body says `Fixes #n`, so GitHub closes the issue when the
  PR merges, and the issues it blocked become ready.
  A PR merges only when it is up to date with main, so CI ran on what lands
  ([coordination.md](coordination.md#up-to-date-with-main)).

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
  dependents until it is closed by its review (see [Reviews](#reviews)). It
  still makes its tree ready at the top, so a box takes the tree and its
  coordinator starts the reviewer.
- **Order** comes from native "blocked by" links and nothing else. A leaf is
  ready when it is open, not claimed, and neither it nor any of its ancestors
  has an open blocker: with milestone M2 blocked by M1, no leaf of M2 starts
  before M1 has closed.
- **The top**: `se issue pull` offers only issues without a parent. A parent
  there is ready while some leaf inside it is, or some parent in its tree
  (itself included) is ready for review; a sub-issue is never offered at the
  top. So a review never waits on the coordinator that was running when its
  last leaf merged: any later box takes the tree and starts the reviewer.
- **The tree's claim**: taking a parent at the top pushes `issue-<root>`,
  which claims the whole tree. That claim does not hold the tree from other
  boxes: a later box that finds a leaf or a review ready inside it takes the
  parent again and picks the tree up from the claim. The leaves' own claims keep two
  coordinators from taking one leaf twice.
- **Leaves inside a tree** are claimed by `se issue pull --in <root> --take`,
  each with its own branch `issue-<n>` from `origin/main`, and worked on in
  their own git worktrees, so several are in flight at once and land as
  separate PRs. `--in` reaches leaves at any depth, so the coordinator of the
  root hands out every leaf of the tree, and a sub-agent is only ever given a
  leaf.
- **The coordinator** is the box that took the parent. A tree is coordinated
  by the box's one loop ([The box](#the-box)), limited to the tree: its leaves
  go to sub-agents under the same cap as the box's other issues, and each
  parent ready for review gets one reviewer. When nothing inside is ready
  while the root is open, the box leaves the tree; a later take picks it up.

## Stuck work

A box can stall: its session dies, or it waits forever. Its issue then stays
claimed, and the queue behind it stops. Releasing and escalating stuck work is
mechanical, done inside `se issue pull` by every box, never left to an
agent's memory. Work that needs a decision waits on an **issue for a
person**, and leaves the agents' queue until the person has closed it.

- **Stuck** is decided by a timer, not judgment. A claimed leaf (claimed at
  the top or with `--in`) is stuck when nothing has been pushed to its branch
  `issue-<n>` (or its PR), nor a takeover recorded, for longer than the lease,
  `issues/config/lease` (the issues instance's config value, built-in in
  `src/internal/issues/stuck.go`). It is under the routine's
  4-hour schedule, so a scheduled box always catches it. The last push is
  GitHub's activity on the branch (`/repos/{owner}/{repo}/activity`), its
  creation included; a branch GitHub keeps no push record of is stuck. A
  parent's claim is never stuck: it does not hold its tree anyway.
- **First stuck: taken over.** A stuck leaf goes before new work: at the top,
  `se issue pull --take` takes it over before any ready issue, and a parent
  with a stuck leaf inside before any other parent or leaf; inside a tree,
  `--in ROOT --take` takes it over before any ready leaf. The new box
  continues the existing branch and PR: at the top it checks `issue-<n>` out
  as it stands, inside a tree its worktree command checks it out. `se`
  records the takeover on the issue as a comment carrying the marker
  `<!-- se:takeover <round> -->`, and labels it `se-final`, as a conflict
  takeover does. Of two boxes taking over one issue, the first comment of the
  round wins; the other deletes its own and moves on. A takeover renews the
  lease.
- **Final and stuck: an issue for a person.** A leaf labelled `se-final`
  (taken over once already, or filed by a review) that is stuck is never
  labelled `se-person` itself. `se` mints an issue for a person, "Decide how
  #n goes on", labelled `se-person` and assigned to the repository owner (so
  GitHub notifies them), and links #n as blocked by it: the one link `se`
  writes on an issue that already exists, since no box is left to write it.
  #n gets a comment saying why, with the markers `<!-- se:person -->` and
  `<!-- se:resume -->`, and loses `se-final`: once the person closes their
  issue, #n is back in the queue for a fresh attempt. This sweep runs inside
  every `se issue pull`. A claim waiting on its blockers is not stuck; once
  they close, its old push makes it stuck at once, and the next box takes it
  over. `se issue pull` never offers an `se-person` issue, or a tree
  containing one (at the top, nor with `--in`). #n's dependents stay blocked
  through their native links.
- **A box that takes an issue closes it, always** (the owner's rule,
  2026-10-14). It ends in one of three ways and no other: a PR for what it
  solved, auto-merge on (`se issue land`), with an issue (`se issue new`) for
  everything it could not solve; a supersede (`se issue supersede <n>`),
  where it cannot land a PR at all; or, where the issue's work reached main
  before the take, a close naming that commit
  (`se issue close <n> --fixed-by SHA`), so a moot issue ends without an
  empty PR. `se issue pull --take` names the open
  issues the taken one blocks; the box names in `--blocks` those of them that
  need what it left over, and only those, so nothing waits that need not. An
  issue for a person (`se issue new --person`) is never a way for a box to
  end: it is only a side issue, for access or a principle. The plugin's Stop
  hook holds a box to the rule (see [The Stop hook](#the-stop-hook)).
- **The person's side:**
  - `se issue pull --person` lists every issue waiting on a person, with its
    reason and how many open issues it holds up, directly or through a tree.
  - The person decides, says so on the issue, and closes it; what it blocked
    goes on.
  - `se issue resume <n>` is for an issue labelled `se-person` by hand, or
    before issues for a person existed: it removes the label, and `se-final`
    with it, and puts the issue back in the queue, its takeover count reset
    (a comment with the marker `<!-- se:resume -->`). A claim still stale is
    then taken over by the next box, as a first takeover.

## The commands

<!-- se:manifest usage issue review -->
```
se issue close N --fixed-by SHA --answers FILE [--json] [--repo OWNER/NAME]
se issue edit N [--title T] [--body B | --body-file PATH] [--json] [--repo OWNER/NAME]
se issue land --answers FILE [--json] [--repo OWNER/NAME]
se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N] [--blocks N,M] [--review] [--final] [--person] [--allow-duplicate] [--skills NAME,NAME] [--json] [--repo OWNER/NAME]
se issue pull [--in ROOT] [--take [N]] [--worktree] [--person] [--full] [--json] [--repo OWNER/NAME]
se issue resume N [--json] [--repo OWNER/NAME]
se issue review pass|fail N --report PATH [--json] [--repo OWNER/NAME]
se issue supersede N (--body B | --body-file PATH) [--json] [--repo OWNER/NAME]
se issue tree [ROOT] [--json] [--repo OWNER/NAME]
se review brief N [--claims] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

Every one of them first closes the parents whose sub-issues are all closed.

`se issue pull` prints the next issue at the top a take would have (number,
title, link, and one line on why it is at the top): stuck work first, then
the lowest ready one; or it says that none is ready; then where each cadence
stands, a line each; it exits 0 either way. `--full` adds the issue's body.
A press of its button in `/se ui` shows its short form: the same lines, the
cadences in one. Every issue text `se` prints, a take's body and `--json`'s
among them, leaves out `se`'s machine marks (`<!-- … -->`) and the
attribution footer (`issues.Shown`). Without `--take` it takes
nothing, so a person can pull the next issue to read it: it pushes no branch,
fires no routine, and writes only what every `se issue` command and the sweep
write. A stuck leaf is marked as one
(with `--json`: `"takeover": true`). Each issue its sweep gave to a person is
named in a line before the answer (with `--json`: the field `flagged`). A parent is
marked as one (with `--json`: `"parent": true`), with the command that
coordinates it. A session has it as
`/se issue pull`.

`se issue pull --take` claims the next ready issue, and `--take N` (or
`--take=N`) issue `N`: it pushes `origin/main` as `issue-<n>` (a push that may
only create the branch, never move it), then checks the branch out; a stuck
leaf it takes over instead, checking its branch out as it stands. Where the
push is refused because another box claimed the issue first, it moves to the
next ready issue. It prints what it took, or that nothing is ready. `--take N`
refuses an issue that is not ready, or a sub-issue that is no stuck leaf,
and says why. There is no
separate `take` command. Taking a parent whose branch exists already checks
that branch out: the tree is picked up from its claim. Plain `--take` first
takes over a conflicted claim (see [The rules](#the-rules)): it prints
`Took over #<n> …` with the PR, and the instruction to merge `origin/main`
into the branch and land it again (with `--json`: the issue's `takeover`,
`{"pr","url","count","why","answers"}`). `--take N` takes over claimed leaf `N`, at
any depth, where `se fleet check` finds it stuck (a conflicted or red PR, or
no PR and no push for an hour; see [spec/coordination.md](../spec/coordination.md)),
or where it is stuck past the lease, so every takeover remedy the check names
runs; labelled `se-final`, it waits on an issue for a person instead. A claim whose work is moving
is refused.
Every takeover, at the top or with `--in`, writes the landing answers the
issue's last land posted on it (see [Landing answers](#landing-answers)) back
to the answers file beside the branch's checkout, `<path>-landing.yaml` where
`<path>` is its worktree (or, without `--worktree`, the workspace), so the
box that takes over brings them up to date rather than writing them anew; a
file there already is kept. It names the file (with `--json`: the
takeover's `answers`).
Every claim records the claiming box's session on the issue, a comment
carrying `<!-- se:box <session> -->` (a takeover's comment carries it too).
Once it has claimed an issue, `--take` runs the fan-out (below), which fires
the routine only where the fleet needs another box, and adds a line saying
what it did; with `--json` that line is the field `fanout`.
`--take --worktree` is a box's take: it claims as `--take` does but checks
nothing out (a takeover's branch is only fetched) and names the command that
checks the issue's branch out in its own worktree beside the checkout, for
its sub-agent (with `--json`: the field `worktree`; a parent gets none, as the
box coordinates its tree itself), and every take names the agent of the
issue's kind (with `--json`: the field `agent`). Where the box (its session) already runs
its cap of sub-agents, `--worktree` and `--in ROOT --take` take nothing and
say so (with `--json`: `{"ready":false,"full":true,"why"}`). It also names the open issues the taken one blocks (with
`--json`: the issue's `blocks`), for `se issue new --blocks`.

`se issue pull --in ROOT` names what is ready inside ROOT's tree: its stuck
leaves to take over, then its ready leaves, at any depth, lowest number first,
and apart from them the `se-review` parents ready for review; or says that
nothing is ready (with why, where the tree holds an issue waiting on a
person), or that ROOT has closed (with `--json`:
`{"root","closed","ready","review","why"}`). With `--take`
(or `--take N`) it claims the first of those leaves (or leaf `N`), moving on where
another box claimed it first: it pushes `origin/main` as `issue-<n>` and
fetches it, checking nothing out (a stuck leaf it takes over and fetches as
it stands), and prints the leaf with the command that
checks it out in its own worktree beside the checkout (with `--json`:
`{"ready","closed","issue","branch","worktree","agent","review"}`). It also names the
parents ready for review, each with the command that makes its reviewer's
fresh worktree and its agent, `se:reviewer` (`review`: a list of issues, each
with its `worktree` and `agent`). That claim fires nothing:
the leaf is worked on by a sub-agent inside the coordinator's box, under its cap.

`se issue land` runs on the checked-out `issue-<n>` branch. It refuses
without an answer to each landing question (see [Landing
answers](#landing-answers)), refuses an
issue with open sub-issues ("a parent holds no work") and a tree with
uncommitted changes, runs `tests/check.sh` and goes on only if it passes,
pushes the branch, records on the leaf who worked it (see
[Reviews](#reviews)), posts the landing answers on the issue, opens one PR against main titled after the issue with the
body `Fixes #<n>`, and turns on auto-merge with squash; a PR with nothing left
to wait for is squash-merged at once. It prints the PR's number and link (with
`--json`: `{"issue","number","url","created","merged"}`). Where the branch's PR
is open already, it pushes and reports that PR, so running it again after a
fix for red CI is safe, and updates the answers it posted before. A session
has it as `/se issue land`.

### Landing answers

Each landed issue is a chapter of the record: transcripts are kept nowhere,
so the answers are the record, and the retro reads the same questions across
every issue closed in its window. The questions are one list,
[spec/landing.yaml](landing.yaml) (key, question and a one-line hint each),
the only place they are written; `se issue land` and the retro both read it.

- `--answers FILE` is YAML keyed by the same keys, each answer text (a
  relative FILE is read from the workspace). `land` refuses, before it checks
  or pushes anything, while a key is missing or its answer empty, and refuses
  a key the list does not know, naming each key at fault. "none" is an
  answer; an empty field is not. The file stands outside the checkout, so
  the tree stays clean.
- After the push and before it opens or finds the PR, `land` posts the
  answers on the issue as one comment opening with `<!-- se:landing -->`:
  each answer under its question, then the facts it knows without asking,
  and the same again in a fenced YAML block (`issue`, `answers` in the
  list's order, `facts`) right under the marker `<!-- se:landing-yaml -->`,
  which the retro parses.
- The facts: when the branch was created (the claim, from GitHub's activity
  record) and the minutes from it to landing; the branch's commits, merges
  excluded; its takeovers, from their markers; and its merges of main, all
  counted against `origin/main`; and the GitHub requests the `se` commands
  run in the checkout made, from its ledger, this land's so far included
  ([io.md](io.md#living-within-githubs-rate-limits)).
- Landing again (after a CI fix, say) updates that comment rather than
  adding a second.
- The comment is where the answers outlive the box that wrote them: its
  answers file stands outside its checkout, where no other box sees it, so a
  takeover (`se issue pull --take`) writes the answers back from the
  comment's block.

`se issue new` creates an issue labelled `se` on the repository, makes it a
sub-issue of `--parent` where that is given, and links it as blocked by each
issue `--blocked-by` names, then prints its number and link
(with `--json`: `{"number","url","blocked_by","parent","blocks","person"}`). `--blocked-by` is required: a
comma-separated list of issue numbers (`--blocked-by 5,8`) or the word `none`.
Every issue in the list is looked up before anything is written, so a list
naming an issue that does not exist, or a pull request, creates nothing; so
does a `--parent` that does not exist. So does a title that an open `se`
issue under the same `--parent` (or at the top, without one) has already,
spaces trimmed: the error names that issue, so a tree is not created twice;
`--allow-duplicate` creates it anyway. The
body comes from `--body` or from `--body-file`, one of them. `--review` labels
it `se-review` as well (see [Reviews](#reviews)), and `--final` labels it
`se-final`, its last attempt before a person (see
[spec/review.md](review.md), rule 5). `--person` makes it an issue for a
person: labelled `se-person` and assigned to the owner (it takes neither
`--review` nor `--final`); its body opens with what they decide. `--blocks
N,M` links each issue it names as blocked by the new one, checked before
anything is written. Where nothing blocks the
issue it created (every issue in `--blocked-by` is closed, or it is `none`),
it runs the fan-out (below) and adds a line saying what it did (with
`--json`: the field `fanout`); otherwise a new ready issue could wait for the
next merge or the schedule. A blocked issue fires nothing.
A session has it as `/se issue new`.

`se issue edit N` is how an `se` issue changes after it is made, never by
hand (`gh issue edit` drops the mark the retro checks). It writes through the
same code as `se issue new`: `--title` replaces the title, refused empty or
where an open `se` issue under N's parent has it already; `--body` or
`--body-file` replaces the body, which still ends in the mark
`<!-- se:new -->` and keeps each se block of the old body (a line holding
`<!-- se:KIND -->`, such as the skills line or a retro's mark) whose kind the
new body does not carry itself. With neither, it writes the body again as it
stands, its mark put back. A pull request, or an issue not labelled `se`, is
refused (with `--json`: `{"issue","kept"}`).

`se issue supersede N` is the second way a box closes the issue it took,
where it cannot land a PR. It creates N's successor through the same code as
`se issue new`: N's title and text, then the open questions the box could not
answer (`--body` or `--body-file`), labelled `se-final`, a sub-issue of N's
parent and blocked by N's open blockers; it links N's open dependents as
blocked by the successor (GitHub's native links), then closes N, its comment
naming the successor. A final issue is refused: its box lands a PR. A ready
successor fires the routine once (with `--json`:
`{"issue","successor","parent","blocked_by","blocks","ready","fanout"}`).

`se issue close N --fixed-by SHA --answers FILE` is the third way, for an
issue whose work reached main before its box took it (another issue's PR did
it): landing would take an empty commit. It fetches `origin/main` and refuses
unless SHA names a commit that `origin/main` holds, refuses a pull request, a
closed issue and a parent ("a parent holds no work"), and reads FILE as
`se issue land` does, refusing a missing, empty or unknown answer, all before
it writes anything. Then it records the worker, posts the landing answers on N
as `land` does (see [Landing answers](#landing-answers)), comments naming the
commit and its link under the marker `<!-- se:fixed-by SHA -->`, and closes N
as completed (with `--json`: `{"issue","commit","subject","url"}`). N's
dependents become ready as when a PR closes it.

### The Stop hook

In a box (a cloud session no person attends, as the routine starts it), the
plugin hands every Stop and SubagentStop to `se hook stop`, which refuses the
stop while any issue the box took is open with neither an open PR from its
branch, auto-merge on, nor a supersede, naming each and what it misses (a
close by `se issue close --fixed-by` closes the issue, so it counts as
closed). The box's issues are every one `se issue pull --take` took (a
parent's box coordinates and closes nothing itself); a leaf's sub-agent is
held to the leaf its prompt names. It
is enforcement, so it fails closed: only what GitHub shows, or what
`se issue land` recorded, lets the box end. `se issue land` records the PR it
landed, auto-merge on, in `.se/.runtime/box.json` of its workspace
(`{"landed":{"N":{"pr":P,"auto_merge":true}}}`), and the hook trusts that
record, in its own workspace or in the issue's worktree beside it, before it
asks GitHub, whose `auto_merge` field a proxy's auto-merge route may leave
unset.
Its escape hatches: a box waiting on background work passes; it refuses at
most `refusals` times in a row ([spec/stop.yaml](stop.yaml)); a prompt from a
person resets the count (`se hook prompt`); and a check that cannot judge
lets the turn end and logs why in `.se/.runtime/logs/stop.log`. An
interactive session is never refused.

`se issue review` passes or fails a parent ready for review, and
`se review brief` is what its reviewer starts from; see [Reviews](#reviews)
and [spec/review.md](review.md). A session has them as `/se issue review` and
`/se review brief`.

`se issue pull --person` lists every open issue labelled `se-person`, each
with its reason and how many open issues it blocks, directly or through a tree
(with `--json`: a list of `{"number","title","url","reason","blocks"}`), or
says that none waits on a person. `se issue resume N` is the person's, for an
issue labelled `se-person` by hand or before issues for a person existed: it
refuses an issue not labelled `se-person`; see [Stuck work](#stuck-work).

`se issue tree` lists every open se issue, each indented under its parent,
one line each: number, state, where it stands (ready, claimed, blocked and by
what), how many of its sub-issues are closed, its labels and its title. `se
issue tree ROOT` lists ROOT and every issue below it, open or closed. Then it
estimates when the last open issue (of ROOT's tree, with ROOT) closes,
mechanically, from what the fleet measured over the pace window
(`PaceWindow`, 7 days, in `src/internal/issues/queue.go`), read by the same
code the retro reads it with (the se issues closed in the window, the PR that
fixed each, and the claim time in its landing answers):

- **the work left**: every open leaf, and every open review gate, which is
  reviewed once its tree is done;
- **the pace**: the se issues merged an hour, and their claim-to-merge times,
  p50 and p90;
- **the parallelism**: how many run at once, the leaves in flight now that
  are not stuck past the lease, or the merges an hour times the p50,
  whichever is more, and at least one;
- **the critical path**: the longest chain of work that must run in a row:
  an issue waits for its blockers' and its ancestors' blockers' work (a
  parent's being all of its tree), and a review gate for its tree.

The estimate is the larger of the critical path run end to end and the work
left spread over the parallelism, once at the p50 time and once at the p90
time: the spread between them is its uncertainty. It names the critical path,
and says beside it how long the work left takes at the window's merges an
hour, idle hours and all. With `--json` it answers
`{"issues":[...],"queue":{...}}`: each issue as
`{"number","title","state","url","labels","depth","closed","total","why"}`,
and the queue's numbers (`open`, `in_flight`, `stuck`, `pace`, `parallel`,
`critical_path`, `p50_hours`, `p90_hours`, `p50_at`, `p90_at`, `pace_hours`,
or `why` there is no estimate). The briefing gives its one line under Next. It changes
nothing but what every `se issue` command and the sweep write. A session has
it as `/se issue tree`.

They read and write GitHub through `gh api` (the links through
`/repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by`, the tree through
`/repos/{owner}/{repo}/issues/{n}/sub_issues`), which owns the
authentication, and work on the repository of the workspace's `origin` unless
`--repo` names another.

## Reviews

Some issues, typically milestones, need a review before they count as done,
and a review is never done by an agent that did the reviewed work. GitHub
issues have no review of their own, so a review is plain issue mechanics, all
through `se`, with every verdict on the reviewed issue's thread.

- **The marker** is the label `se-review` on the reviewed issue itself, set by
  `se issue new --review`. Its sub-issues are the work; the issue is its own
  review.
- **Ready for review**: once its sub-issues have all closed and nothing blocks
  it, it does not close by itself (see [Nesting](#nesting-leaves-are-work-parents-coordinate)).
  `se issue pull --in` names it apart from the work, and at the top its tree
  is ready, so any box takes the tree and starts its reviewer.
- **How it is reviewed** is [spec/review.md](review.md): the reviewer starts
  from `se review brief N` and ends with its report.
- **Pass**: `se issue review pass N --report PATH` posts the report on N and
  closes it as completed; the parents it completes then close by themselves.
- **Fail**: `se issue review fail N --report PATH` posts the report on N. Each
  blocking finding becomes an `se-final` sub-issue of N, made as
  `se issue new --parent N --blocked-by none --final` would, its body the
  finding. N stays open: the fixes are work inside it, and once they have
  landed it is ready for review again, as a re-review.
- **Either way**, the non-blocking findings (at most `issues/config/max-filed`) become `se-final`
  issues in the normal queue.
- **Who worked a leaf** is recorded by `se issue land`: a comment on the leaf,
  `Worked by session S in W.`, with the marker
  `<!-- se-worker {"session":S,"workspace":W} -->`, once per worker. S is the
  Claude Code session (`CLAUDE_CODE_SESSION_ID`), W the workspace it landed
  from. Sub-agents of one box share a session and each works in its own
  worktree, so the two together tell them apart. Without a session, nothing is
  recorded.
- **Separation, mechanically**: `se issue review` reads every leaf in N's tree,
  open or closed, at any depth, and refuses where the agent running it (its
  session and workspace) worked one of them. It also refuses, rather than
  guess, where it cannot tell: when `CLAUDE_CODE_SESSION_ID` is unset, or a
  leaf records no worker. A leaf closed as not planned or as a duplicate
  landed no work and is not asked. A refused review writes nothing.
- **The reviewer** is a fresh sub-agent of the coordinator that worked none of
  the tree, in a fresh worktree of `origin/main` beside the checkout,
  `review-<n>-<k>` (k counts N's sub-issues, so every round after a fail gets
  its own). `se issue pull --in ROOT --take` names the command that makes it.
  It ends with `se issue review pass|fail`.

## The routine

Boxes are cloud sessions that work unattended. Every box is started by the
routine `SE work`, whose whole prompt is

    work as se:coordinator

A box is the agent `se:coordinator`: the plugin's session start hands a box
(a cloud session no person attends) that agent's whole procedure, and the box
runs it in its own session, since an agent cannot start agents of its own.
The routine has two triggers:

- a GitHub trigger on `pull_request.closed` with is-merged = true and base
  branch = main, so every merge into main starts a box, which may find the
  issues that merge unblocked;
- a schedule, every 4 hours.

It also has an API trigger, which `se` fires for the fan-out.

### The box

The plugin's agents, one file each, holding each role's whole procedure:

<!-- se:manifest agents -->
- [`se:worker`](../src/plugin/agents/worker.md), for the kind leaf: an issue with no sub-issues: work, landed as one PR.
- [`se:coordinator`](../src/plugin/agents/coordinator.md), for the kind parent: an issue with sub-issues: the box coordinates its tree, as it runs the queue and checks the fleet when nothing is ready.
- [`se:reviewer`](../src/plugin/agents/reviewer.md), for the kind gate: an se-review parent ready for review: reviewed cold.
- [`se:retro`](../src/plugin/agents/retro.md), for the kind retro: an issue labelled se-retro.
- [`se:overhaul`](../src/plugin/agents/overhaul.md), for the kind overhaul: an issue labelled se-overhaul.
<!-- /se:manifest -->

One box is the fleet. A box never works an issue itself: it coordinates
sub-agents, so one box can hold the whole queue, and each claim does not
cost a fire of the routine (whose limit the fan-out ran into on 2026-10-14).

- **The loop:** the box pulls each ready issue with
  `se issue pull --take --worktree`, makes its worktree, and hands it to a
  fresh sub-agent of the agent the take names, with a clean context, several
  at once up to its cap. A parent it takes it coordinates the same way with
  `--in ROOT --take`.
- **The cap** is `fleet.box/config/parallel`, 4 (`Parallel` in
  `src/internal/issues/box.go` until the fleet's rules move onto the index):
  the box's disk allowance and CPU limit it, and the battery takes about
  25s. `se` refuses a take that would pass it.
- **When it pulls again:** when a sub-agent's PR is up with auto-merge on, or
  its issue is superseded. A red CI or a review on a PR goes back to that PR's
  sub-agent.
- **Its context** keeps only issue, worktree and PR numbers, so it can run
  for days. It ends when nothing is ready and no sub-agent is running.
- **Alive:** a box is alive while one of its claims is: a claimed leaf whose
  branch saw a push within the lease, the box named by its last
  `<!-- se:box -->` comment. Its sub-agent counts against the cap until the
  claim's PR has auto-merge on. A claim with no box comment counts as a box of
  its own at its cap. A box that dies is left to the stuck sweep: its claims
  are taken over once their lease runs out.

### Fan-out

The fan-out adds a box only when the boxes are full, mechanically, never by an
agent's choice:

- **When it fires:** `se issue pull --take` after its claim, and `se issue new`
  for an issue nothing blocks, count the alive boxes from the open claims and
  fire the routine `SE work` once in two cases: issues are ready and no box is
  alive (a restart), or every alive box runs its cap and another issue is
  ready. While a box has room under its cap, it takes the issue itself and
  nothing fires; the taking box counts as alive. The line says which.
- **The end:** a box that finds nothing ready claims nothing and fires
  nothing. It leaves once no sub-agent of its own is running.
- **No cap** on boxes in flight; the owner decided against one. The routine's
  own limit stands: 30 fires an hour. A fire refused for that is reported
  and the box goes on.
- **A refused fire is kept:** where the routine refuses the fire after a take
  with 429, `se` keeps it on the claim, in the fleet state it already keeps
  there: a comment `<!-- se:fanout-retry T -->`, T the time its
  `Retry-After` names (an hour where it names none). Until T nothing fires: a
  take says the fan-out waits, and keeps the same mark on its own claim, so
  the refusal outlives the claim that first kept it. Once T has passed, the
  next take or `se fleet check` that finds the fleet needs another box (the
  two cases above) fires it, once, and leaves `<!-- se:fanout-fired -->` on
  every claim that kept it. A refusal kept only on claims that have since
  closed is gone; the merge that closed them starts a box anyway.
- **How it fires:** an HTTP POST of the body `{}` to the URL in
  `SE_ROUTINE_FIRE_URL`, with the headers
  `Authorization: Bearer $SE_ROUTINE_FIRE_TOKEN`,
  `anthropic-beta: experimental-cc-routine-2026-04-01`,
  `anthropic-version: 2023-06-01` and `Content-Type: application/json`; the
  route is documented at <https://code.claude.com/docs/en/routines>. `se`
  prints the started session's link from the answer.
- **Never fails a claim:** where either variable is unset (on a desk, say),
  `se` says in one line that fan-out is off, and counts nothing; a failed or
  refused fire is reported the same way, and a count that fails fires. The
  claim stands either way. The token is never printed.

The owner's one-time setup: add an API trigger to the routine `SE work`, and
put its fire URL in `SE_ROUTINE_FIRE_URL` and its token in
`SE_ROUTINE_FIRE_TOKEN` in the cloud environment the routine's boxes run in.

No agent starts another box; only this fan-out and the triggers above do.
