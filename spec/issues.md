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
- **Skills**: an issue names the skills its work needs in one place, the
  marked line `se issue new --skills` writes into its body (a retro and an
  overhaul name theirs). The take hands each over in full in its answer, and
  the session's log records it; no label picks a skill
  ([principle 21](principles.md)).
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
- **The coordinator** is the box that took the parent. It starts one sub-agent
  per ready leaf inside its own box (no separate cloud sessions), each in the
  leaf's worktree, and one reviewer per parent ready for review, and repeats
  until the root has closed. When nothing inside is ready while the root is
  open, it ends; a later box picks the tree up.

## Stuck work

A box can stall: its session dies, or it waits forever. Its issue then stays
claimed, and the queue behind it stops. Releasing and escalating stuck work is
mechanical, done inside `se issue pull` by every box, never left to an
agent's memory. Work that needs a decision waits on an **issue for a
person**, and leaves the agents' queue until the person has closed it.

- **Stuck** is decided by a timer, not judgment. A claimed leaf (claimed at
  the top or with `--in`) is stuck when nothing has been pushed to its branch
  `issue-<n>` (or its PR), nor a takeover recorded, for longer than the lease:
  3 hours, `Lease` in `src/internal/issues/stuck.go`. That is under the routine's
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
  2026-10-14). It ends in one of two ways and no other: a PR for what it
  solved, auto-merge on (`se issue land`), with an issue (`se issue new`) for
  everything it could not solve; or a supersede (`se issue supersede <n>`),
  where it cannot land a PR at all. `se issue pull --take` names the open
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
se issue land --answers FILE [--json] [--repo OWNER/NAME]
se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N] [--blocks N,M] [--review] [--final] [--person] [--allow-duplicate] [--skills NAME,NAME] [--json] [--repo OWNER/NAME]
se issue pull [--in ROOT] [--take [N]] [--person] [--json] [--repo OWNER/NAME]
se issue resume N [--json] [--repo OWNER/NAME]
se issue review pass|fail N --report PATH [--json] [--repo OWNER/NAME]
se issue supersede N (--body B | --body-file PATH) [--json] [--repo OWNER/NAME]
se issue tree [ROOT] [--json] [--repo OWNER/NAME]
se review brief N [--claims] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

Every one of them first closes the parents whose sub-issues are all closed.

`se issue pull` prints the next issue at the top a take would have (number,
title, link and body): stuck work first, then the lowest ready one; or it
says that none is ready; it exits 0 either way. Without `--take` it takes
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
`{"pr","url","count","why"}`). `--take N` takes over claimed leaf `N`, at
any depth, where `se fleet check` finds it stuck (a conflicted or red PR, or
no PR and no push for an hour; see [spec/coordination.md](../spec/coordination.md)),
or where it is stuck past the lease, so every takeover remedy the check names
runs; labelled `se-final`, it waits on an issue for a person instead. A claim whose work is moving
is refused.
Once it has claimed an issue, `--take` fires the routine once (the fan-out,
below) and adds a line saying what the fire did; with `--json` that line is
the field `fanout`. It also names the open issues the taken one blocks (with
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
`{"ready","closed","issue","branch","worktree","review"}`). It also names the
parents ready for review, each with the command that makes its reviewer's
fresh worktree (`review`: a list of issues, each with its `worktree`). That claim fires nothing:
the leaf is worked on by a sub-agent inside the coordinator's box.

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
  counted against `origin/main`.
- Landing again (after a CI fix, say) updates that comment rather than
  adding a second.

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
it fires the routine once, as the fan-out does, and adds a line saying what
the fire did (with `--json`: the field `fanout`); otherwise a new ready issue
would wait for the next merge or the schedule. A blocked issue fires nothing.
A session has it as `/se issue new`.

`se issue supersede N` is the second way a box closes the issue it took,
where it cannot land a PR. It creates N's successor through the same code as
`se issue new`: N's title and text, then the open questions the box could not
answer (`--body` or `--body-file`), labelled `se-final`, a sub-issue of N's
parent and blocked by N's open blockers; it links N's open dependents as
blocked by the successor (GitHub's native links), then closes N, its comment
naming the successor. A final issue is refused: its box lands a PR. A ready
successor fires the routine once (with `--json`:
`{"issue","successor","parent","blocked_by","blocks","ready","fanout"}`).

### The Stop hook

In a box (a cloud session no person attends, as the routine starts it), the
plugin hands every Stop and SubagentStop to `se hook stop`, which refuses the
stop while the box's issue is open with neither an open PR from its branch,
auto-merge on, nor a supersede, and says which is missing. The box's issue is
the one `se issue pull --take` took (a parent's box coordinates and closes
nothing itself); a leaf's sub-agent is held to the leaf its prompt names. It
is enforcement, so it fails closed: only what GitHub shows lets the box end.
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

`se issue tree` lists every se issue with sub-issues, open or closed, open
first, one line each: number, state, how many of its sub-issues are closed,
its labels and its title. `se issue tree ROOT` lists ROOT and every issue
below it, open or closed, each indented under its parent (with `--json`: a
list of `{"number","title","state","url","labels","depth","closed","total"}`).
It changes nothing but the parents every command closes. A session has it as
`/se issue tree`.

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
- **Either way**, the non-blocking findings (five at most) become `se-final`
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

    run the work skill

and the work skill is [src/plugin/skills/work/SKILL.md](../src/plugin/skills/work/SKILL.md), `se:work` in a session.
The routine has two triggers:

- a GitHub trigger on `pull_request.closed` with is-merged = true and base
  branch = main, so every merge into main starts a box, which may find the
  issues that merge unblocked;
- a schedule, every 4 hours.

It also has an API trigger, which `se` fires for the fan-out.

### Fan-out

One merge starts one box, but there should be as many boxes as there is ready
work. So boxes start boxes, mechanically, never by an agent's choice:

- **Fan-out:** whenever `se issue pull --take` has claimed an issue, it fires
  the routine `SE work` once, so another box starts and takes the next ready
  issue. That box fires again after its own claim, and so on.
- **A new ready issue** fires it too: `se issue new` fires once when nothing
  blocks the issue it created.
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
