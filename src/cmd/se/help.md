# Help: every command's help, as se gives it

Reader: whoever reviews a change to se's commands, and sees here what it did to their help.

This file is made from the command registry by `se manifest --write`, and the
`manifest` rule fails the battery where it differs, so a change to a command's
declaration shows its help's diff in the PR. Write nothing here by hand.

<!-- se:manifest help -->
## se help

```text
se <command> [flags]

Checks:
  manifest         print a manifest, or rewrite every manifest section
  rules            check this checkout against every SE rule

Daemon:
  serve            run this workspace's daemon in the foreground
  start            start the daemon in the background, or find it running
  stop             end this workspace's daemon

Fleet:
  briefing         where SE stands: what waits on you, in flight, happened, next
  fleet check      list what is broken in the fleet, each with its remedy
  fleet fix        fix what fleet check finds that needs no checkout
  fleet plugins    fetch the outside plugins and skills SE runs, pinned
  fleet prune      list the stray branches; --apply deletes them
  fleet rules      tell each open se PR the se checks it breaks merged with main
  fleet trust      say whether CI may skip the battery on the commit checked out

Hooks:
  hook prompt      a person prompted: reset the Stop hook's refusals
  hook stop        hold a box to a merged PR or supersede for each issue it took

Issues:
  issue close      close issue N, its work on main already, naming the commit
  issue edit       rewrite se issue N's title and body, keeping its mark
  issue keep       keep an issue-N branch's PR up to date until it merges
  issue land       check and land issue-N: a leaf into its manifest, else one PR
  issue new        create an se issue in a manifest, with its blockers
  issue pull       show the next se issue, stuck work first; --take claims it
  issue review     pass or fail a gate whose sub-issues closed, by its report
  issue supersede  close issue N by a final successor with its open questions
  issue tree       list the open queue and estimate when its last issue closes

Overhaul:
  overhaul file    file a judged report: create its issues and close it
  overhaul new     start an overhaul: is the design still right?
  overhaul read    read an overhaul's facts and write its report draft

Retro:
  retro collect    read a retro's window from GitHub and write its report draft
  retro new        start a retro over everything closed since the last one
  retro report     file a judged report: create its issues and close it

Reviews:
  review brief     everything a reviewer of gate N starts from

Session:
  guidance         answer the principles and the skills a session holds
  help             list the commands, or show one: help <command>
  off              switch SE off for this session; the daemon runs on
  on               switch SE on: start the daemon, forward this session's events
  restart          restart the daemon; in an SE checkout, rebuild se first
  status           say whether a daemon answers, and which commits SE came from
  ui               open SE's control panel: the on/off toggle and the commands
  update           pull main into the installed SE, rebuild se and reload

se help <command> shows its usage and flags.
The agents, each reached as @agent-<name> or by asking for its role:
se:worker, se:coordinator, se:reviewer, se:retro, se:overhaul.
Every command takes --workspace DIR (default: here).
```

## /se help

```text
/se <command> [flags]

Fleet:
  briefing         where SE stands: what waits on you, in flight, happened, next
  fleet check      list what is broken in the fleet, each with its remedy
  fleet fix        fix what fleet check finds that needs no checkout
  fleet prune      list the stray branches; --apply deletes them
  fleet rules      tell each open se PR the se checks it breaks merged with main

Issues:
  issue close      close issue N, its work on main already, naming the commit
  issue edit       rewrite se issue N's title and body, keeping its mark
  issue keep       keep an issue-N branch's PR up to date until it merges
  issue land       check and land issue-N: a leaf into its manifest, else one PR
  issue new        create an se issue in a manifest, with its blockers
  issue pull       show the next se issue, stuck work first; --take claims it
  issue review     pass or fail a gate whose sub-issues closed, by its report
  issue supersede  close issue N by a final successor with its open questions
  issue tree       list the open queue and estimate when its last issue closes

Overhaul:
  overhaul file    file a judged report: create its issues and close it
  overhaul new     start an overhaul: is the design still right?
  overhaul read    read an overhaul's facts and write its report draft

Retro:
  retro collect    read a retro's window from GitHub and write its report draft
  retro new        start a retro over everything closed since the last one
  retro report     file a judged report: create its issues and close it

Reviews:
  review brief     everything a reviewer of gate N starts from

Session:
  guidance         answer the principles and the skills a session holds
  help             list the commands, or show one: help <command>
  off              switch SE off for this session; the daemon runs on
  on               switch SE on: start the daemon, forward this session's events
  restart          restart the daemon; in an SE checkout, rebuild se first
  status           say whether a daemon answers, and which commits SE came from
  ui               open SE's control panel: the on/off toggle and the commands
  update           pull main into the installed SE, rebuild se and reload

/se help <command> shows its usage and flags.
The agents, each reached as @agent-<name> or by asking for its role:
se:worker, se:coordinator, se:reviewer, se:retro, se:overhaul.
```

## se help briefing

```text
se briefing [--since TIME | --last N] [--json] [--repo OWNER/NAME]

Read GitHub and the checkout and tell, pending first: every se-person issue with
its reason and what it holds up, and every report waiting for the owner, from
every registered pending source; the claimed issues and their PRs, and what
fleet check reports; the issues closed in the window, each with its PR and
landing answer done, and the last retro; what issue pull would take, how many
issues are ready, claimed, blocked, in trees or in no manifest, and the queue's
size with when its last issue is estimated to close (issue tree tells the
detail); and what SE is. The window is the last day or the last 10 closed
issues, whichever are more; --since takes a time (RFC 3339, a date, or an age
such as 36h or 3d), --last a count. The skill se:briefing presents it.

Flags:
  --json             answer JSON
  --last N           tell of the last N closed issues
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --since TIME       tell of the issues closed since TIME: RFC 3339, a date, or
                     an age such as 36h or 3d
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help fleet check

```text
se fleet check [--json] [--repo OWNER/NAME]

Read GitHub and list every finding: a stalled root, a conflicted, red or green
but unmerged PR, a claim with no PR, a leftover claim, an impossible block, a
bare issue (in no manifest), an issue waiting on a person. Each names its issue,
its PR and its remedy, in the order the box, se:coordinator, fixes them. Nothing
found, it says healthy. Where GitHub's answers say the hour's quota of requests
has fallen below the github instance's quota-floor share
(github/config/quota-floor), a last line says how many are left and when it
resets. With fan-out on, a fan-out the routine refused with 429, which se issue
pull --take keeps on the alive claims with its retry time, fires once that time
has passed and the fleet still needs the box, and a last line says so.
spec/coordination.md has the rules.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help fleet fix

```text
se fleet fix [--json] [--repo OWNER/NAME]

Run fleet check and apply, in its order, every remedy that needs no checkout:
auto-merge goes on, a leftover claim of a closed issue is left to the prune
workflow for a day after the close, any other leftover claim's branch main holds
whole is deleted by a git push from the workspace, and a bare issue is filed
into the open misc manifest (opening the next where none is open) by a sub-issue
link. Every other finding is reported, never filed: it writes no issue and no
comment (an issue is work, not a report). A takeover is named for the next take.
A remedy that fails is reported, and the ones after it are still applied.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help fleet plugins

```text
se fleet plugins --into DIR

Fetch every source of the reuse config (src/index/wiring.yaml) at its pinned
commit into DIR, as a folder of plugins that one entry of
CLAUDE_CODE_PLUGIN_DIRS loads: each plugin as DIR/<name>, each lone skill inside
DIR/adopted. A folder there that no source names any more is removed. A cloud
environment's setup script runs it (spec/cloud.md).

Flags:
  --into DIR       the DIR to fetch them into
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help fleet prune

```text
se fleet prune [--apply] [--json] [--repo OWNER/NAME]

List every issue-<n> branch whose issue is closed and every claude/* branch
whose last commit is more than an hour old, each with no open PR. --apply
deletes them; without it nothing is deleted. It never touches main or any other
branch. The prune workflow runs it with the repository's token.

Flags:
  --apply            delete the branches it lists
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help fleet rules

```text
se fleet rules [--json] [--repo OWNER/NAME]

For every open se PR against main: merge its head with origin's main in a
worktree under .se/.runtime/rules, build se there and run se rules and the tests
of the battery, the budgets and the programs list on the merge, and comment on
each PR it breaks the findings and what to do, once for the same findings, so
the box that owns it acts before its CI goes red. A PR that conflicts with main
is left to its takeover; one whose check fails is reported, and the others are
still checked. The rules workflow runs it when main takes a change to se's
rules, tests/check.sh, the battery, spec/budgets.yaml or proc.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help fleet trust

```text
se fleet trust [--json]

CI's check job asks it first, on a pull request and on a push to main: exit 0
and say why where the battery's stamp (issues/config/stamp), as the workspace's
HEAD holds it, names the hash of HEAD's tree with the stamp left out, as
tests/check.sh wrote it and se issue land and se issue keep committed it with
the work; else exit 1 and say why (main moved, or the stamp is missing or
stale), and CI runs the battery itself (with --json, a trusted commit answers
{"trusted","why"}). It reads no GitHub: the stamp is a file in the commit. It is
trust in one's own boxes, not a proof.

Flags:
  --json           answer JSON
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help guidance

```text
se guidance [--session-id ID]

Answer the guidance a session's context carries: spec/principles.md where the
guidance instance's principles switch is on, in a box the whole procedure of its
agent, se:coordinator, and each skill a take handed to session ID, as its log
records them, in full where the inline switch is on, else by name. Each is read
from the SE checkout the plugin was loaded from (SE_PLUGIN_CHECKOUT, else the
workspace), so a project holds no SE file. The plugin's SessionStart hook puts
it into the context on startup, resume, clear and compact; the hand-again is a
row of the session's log.

Flags:
  --session-id ID  the session ID whose log names the skills handed to it
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help help

```text
se help [<command>]

Without a word, help lists every command under its group. With a command's name,
it shows that command's usage and every flag it takes; se <command> --help shows
the same.
```

## se help hook prompt

```text
se hook prompt

A prompt from a person: reset how often in a row se hook stop has refused, so
the cap counts afresh.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help hook stop

```text
se hook stop [--agent-transcript PATH] [--waiting] [--repo OWNER/NAME]

Answer the plugin's Stop (or, with --agent-transcript, SubagentStop) as JSON:
block, naming each, while any issue this box took is open: with no PR from its
branch, with one whose auto-merge is off, or with one not merged yet (a box
keeps its PR until it merges: se issue keep), unless another box took the issue
over; else pass, with why. A merged PR or a supersede closes the issue. A PR se
issue land recorded with auto-merge on in .se/.runtime/box.json, of this
workspace or of the issue's worktree beside it, counts as auto-merge on whatever
GitHub's auto_merge field shows. The issues are every one se issue pull --take
recorded, or for a sub-agent the leaf its prompt names. An interactive session,
and a box waiting on background work (--waiting), always pass. It refuses at
most refusals times in a row (spec/stop.yaml); a prompt from a person resets the
count (se hook prompt). A check that cannot judge lets the turn end and logs why
in .se/.runtime/logs/stop.log.

Flags:
  --agent-transcript PATH  the sub-agent's transcript PATH: the stop is a
                           SubagentStop
  --json                   answer JSON
  --repo OWNER/NAME        the repository as OWNER/NAME (default: the
                           workspace's origin)
  --waiting                the session has background work or a wake-up that
                           brings it back
  --workspace DIR          the workspace DIR the daemon serves (default: here)
```

## se help issue close

```text
se issue close N --fixed-by SHA --answers FILE [--json] [--repo OWNER/NAME]

The third way a box closes the issue it took, beside a PR and a supersede, where
its work is on main already and landing would take an empty commit: refuse
unless SHA names a commit that origin/main holds and FILE answers every question
in spec/landing.yaml (as se issue land reads it), and refuse a closed issue and
a parent; then post the answers on N, close N's open PR and delete its issue-N
claim by a git push from the workspace, comment naming the commit, and close N
as completed.

Flags:
  --answers FILE     the landing answers, a YAML FILE keyed as spec/landing.yaml
  --fixed-by SHA     the SHA of the commit on main that did N's work
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue edit

```text
se issue edit N [--title T] [--body B | --body-file PATH] [--json] [--repo
    OWNER/NAME]

Rewrite se issue N through the same code as se issue new, never by hand: --title
T replaces its title (an empty one, or one an open se issue under N's parent has
already, is refused); --body B or --body-file PATH replaces its body, which
still ends in se issue new's mark, <!-- se:new -->, and keeps each se block of
the old body (a line holding <!-- se:KIND -->, such as the skills line or a
retro's mark) whose kind the new body does not carry itself. With neither, it
writes the body again as it stands, its mark put back. A pull request, or an
issue not labelled se, is refused.

Flags:
  --body B           the issue's new body B
  --body-file PATH   a file PATH holding the issue's new body
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --title T          the issue's new title T
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue keep

```text
se issue keep [--for D] [--json] [--repo OWNER/NAME]

On an issue-N branch whose PR se issue land opened: a box keeps its PR until it
merges. Every minute, for D at most (default 8m, so one call fits a tool's
timeout), it looks at the PR; whenever main has moved past the branch on origin,
it merges origin/main in (never a rebase), passes tests/check.sh, commits the
battery's stamp with the work and pushes, as se issue land does, so CI trusts
the stamp and auto-merge merges. It says when the PR merged, or another box took
the issue over, or that it is still open: run it again. A merge that conflicts,
a failing check and a PR closed unmerged are errors to fix, then land again
(with --json: {"issue","pr","url","merged","taken_over","updated"}).

Flags:
  --for D            keep the PR this long (D) at most before answering
                     (default: 8m0s)
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue land

```text
se issue land --answers FILE [--json] [--repo OWNER/NAME]

On an issue-N branch: refuse unless FILE answers every question in
spec/landing.yaml (YAML keyed by their keys, none empty, none unknown; a
relative FILE is read from the workspace), and refuse an issue with open
sub-issues. A leaf inside a manifest (an issue with a parent) lands into the
manifest's branch: merge origin's issue-N and the manifest's issue-M into it
(never a rebase), pass tests/check.sh, commit the battery's stamp with the work,
push it to both, post the answers on the leaf with its facts (its time from
claim to land among them) and close it; a leaf gets no PR of its own, so an
earlier box's open PR of the leaf to main is closed (its auto-merge off) with a
comment naming the manifest. An issue at the top (a manifest whose leaves are
all closed, a retro, an overhaul) lands to main: merge origin's branch and
origin/main in, pass tests/check.sh, commit the battery's stamp
(issues/config/stamp) with the work, refuse a tree the stamp does not name and a
branch main moved past meanwhile, post the answers on the issue (or update the
ones posted before), open its PR against main (Fixes #N, and the battery's
profile), or find it open with its profile brought up to date, and turn on
auto-merge (squash), recording the PR, auto-merge on, in .se/.runtime/box.json,
which se hook stop trusts before it asks GitHub; a manifest whose branch holds
nothing main does not closes with no PR.

Flags:
  --answers FILE     the landing answers, a YAML FILE keyed as spec/landing.yaml
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue new

```text
se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none
    [--parent N | --manifest] [--blocks N,M] [--review] [--final] [--person]
    [--allow-duplicate] [--not-blocked N,M] [--skills NAME,NAME] [--json]
    [--repo OWNER/NAME]

Create an se issue, linked as blocked by each issue --blocked-by names (GitHub's
native links), and name it. All work moves in manifests: a manifest is an issue
at the top on one topic whose sub-issues are its work, landing as one PR, its
leaves together about 1h (issues.manifest/config/target), and boxes take only
manifests. --parent N files it into a manifest (a sub-issue of N); --manifest
makes it a new manifest itself, labelled se-manifest, whose leaves follow with
--parent; without either it goes into the open misc manifest (labelled se-misc),
which takes new issues for that time from its creation, after which the next one
opens. --blocks links each issue it names as blocked by the new one: those
dependents of a box's issue that need what is left of it. --review labels it
se-review; --final labels it se-final, its last attempt: never superseded again.
--person makes it an issue for a person: labelled se-person and assigned to the
owner, it waits for them, and its body opens with what they decide. --skills
names the skills its work needs, each a folder of src/plugin/skills in the
workspace, in one marked line of its body: the take hands each over (se help
issue pull). A name that is an agent's role (work, coordination, review, retro,
overhaul, or the agent's own name) is left out of that line, since the take
names the agent that holds it. It refuses a title an open se issue under the
same --parent (or at the top) has already, naming it, unless --allow-duplicate
is given. It refuses a body that names (#N) an open se issue, one whose work is
not on main yet, unless --blocked-by names it, so the take holds the new issue
until it merges, or --not-blocked does, saying the mention is only a reference;
--parent and --blocks name issues it may mention freely. An issue for a person
stands at the top, in no manifest. A ready issue, one nothing open blocks, fires
the routine once. In a box it refuses, writing nothing: a box opens no issue,
its work ends in a PR (se issue land) or a supersede (se issue supersede);
retros, reviews and overhauls file theirs through their own commands.

Flags:
  --allow-duplicate   create it although an open se issue under the same parent
                      has its title
  --blocked-by N,M    the issues that block it, as N,M, or none
  --blocks N,M        the issues it blocks, as N,M: those that need it
  --body B            the issue's body B
  --body-file PATH    a file PATH holding the issue's body
  --final             label it se-final: its last attempt, never superseded
                      again
  --json              answer JSON
  --manifest          make it a new manifest, labelled se-manifest: its leaves
                      follow with --parent
  --not-blocked N,M   the open se issues its body names only as a reference, as
                      N,M: it need not wait for them
  --parent N          the issue N it is a sub-issue of
  --person            make it an issue for a person: label it se-person and
                      assign it to the owner
  --repo OWNER/NAME   the repository as OWNER/NAME (default: the workspace's
                      origin)
  --review            label it se-review: it is reviewed once its sub-issues
                      have closed
  --skills NAME,NAME  the skills its work needs, as NAME,NAME: a take hands each
                      over
  --title T           the issue's title T
  --workspace DIR     the workspace DIR the daemon serves (default: here)
```

## se help issue pull

```text
se issue pull [--in ROOT] [--take [N]] [--worktree] [--person] [--full]
    [--json] [--repo OWNER/NAME]

Pull the next ready se issue at the top, stuck work before new work; boxes take
only manifests, so at the top it offers a manifest (a parent), a retro or an
overhaul, never a leaf in no manifest, and a manifest whose leaves are all
closed is offered to be landed as one PR. After stuck and conflicted work, it
offers the priority manifests first, lowest number first: those labelled
se-priority or holding an open leaf so labelled, and an open retro or overhaul;
inside a manifest, its se-priority leaves come before the rest. Every --take
first reads fleet.box/config/paused (issues/config/paused) in the wiring file on
origin/main, and while it is set takes nothing and says the fleet is paused, so
the box ends. Without --take it only shows it (number, title, link, why it is at
the top, and where the cadences stand; --full adds the body), or says that none
is ready, and takes nothing; a press of its /se ui button shows the short form,
the cadences in one line. --take claims it (or issue N): its branch issue-N,
pushed from origin/main and checked out. Plain --take first starts and takes an
unattended overhaul where 5 retros (issues/config/overhaul-cadence) have closed
since the last overhaul closed and none is open, else an unattended retro where
10 se issues (issues/config/retro-cadence) have closed since the last retro
closed and none is open (the plain form reports both counts); then it takes over
a claimed issue whose PR conflicts with main: its branch is checked out as it
stands, to merge main into. A claimed leaf nothing was pushed to for longer than
the 3h0m0s lease (issues/config/lease) is stuck: it is taken over before new
work, its branch checked out as it stands. A takeover writes the landing answers
the issue's last land posted on it back to <checkout>-landing.yaml beside its
checkout (its worktree with --worktree or --in), keeping a file there already,
and names it. A takeover also says, from the REST API, when its branch was last
pushed and its open PR's mergeable state and the last run of each of its checks,
so no box reaches for gh. A claim stuck a second time, or conflicting after a
takeover, is taken over again; nothing mints an issue for a person on a box's
behalf. A claim records the box's session on the issue, and fires the routine
once only where the fleet needs another box: every alive box runs its cap of
sub-agents (fleet.box/config/parallel, 4, Parallel) and another issue is ready
(fan-out); a fire the routine refuses with 429 is kept on the claim with the
retry time it names, nothing fires before that time, and the next take or se
fleet check after it fires it. --worktree is the box's take: it checks nothing
out, names the command that makes the issue's worktree for its sub-agent, and is
refused while the box runs its cap. A take hands over every skill the issue's
marked skills line names (se issue new --skills): their full text follows the
issue, or, where the guidance instance's inline switch is off, their names and
files; the session's log records each by name and hash. A name there that is an
agent's role, as retro or overhaul, is no skill: the take's agent holds it, so
it is neither handed over nor reported missing. A take names the agent that
works the issue, by its kind (the registry in src/internal/issues/kinds.go):
se:worker for a leaf, se:coordinator for a parent, which is the box itself,
se:retro and se:overhaul; each review names se:reviewer. --in ROOT names the
ready leaves inside ROOT's tree, and --take claims one for a worktree. Every
--take also refuses where main has moved past the commit se was built from,
naming se update: the agents and guidance it hands over come from main. --person
lists the issues waiting on a person.

Flags:
  --full             without --take: show the issue's body too
  --in ROOT          look inside the tree of issue ROOT for its ready leaves
  --json             answer JSON
  --person           list the issues waiting on a person
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --take             claim the next ready issue, or issue N as --take N
  --workspace DIR    the workspace DIR the daemon serves (default: here)
  --worktree         with --take: claim for a sub-agent's worktree, checking
                     nothing out
```

## se help issue review

```text
se issue review pass|fail N --report PATH [--json] [--repo OWNER/NAME]

Review N, an se-review parent whose sub-issues have closed, as an agent that
worked none of its tree, with the report in the JSON file PATH (spec/review.md).
It refuses a pass where a requirement lacks evidence, and a report without its
checked-and-clean list. Every finding becomes an se-final issue: a blocking one
a sub-issue of N, a non-blocking one in the queue (at most 5,
issues/config/max-filed). pass posts the report and closes N; fail posts it, and
N waits for its fixes. A re-review finding that repeats an earlier blocker is an
accepted repeat: it files nothing, the report names it, and a fail whose
blocking findings are all repeats closes N.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --report PATH      the review's report, a JSON file at PATH
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue supersede

```text
se issue supersede N (--body B | --body-file PATH | --duplicate-of M)
    [--json] [--repo OWNER/NAME]

The second way a box closes the issue it took, beside a PR (and se issue close
--fixed-by, where its work is on main already): create N's successor through the
same code as se issue new, with N's title and text and the open questions the
box could not answer (B), labelled se-final, a sub-issue of N's parent and
blocked by N's open blockers; link N's open dependents as blocked by it; close
N's open PR, its comment naming the successor, and delete N's issue-N claim by a
git push from the workspace; then close N, its comment naming the successor. A
final issue is refused: its box lands a PR. A ready successor fires the routine
once. With --duplicate-of M, for an issue that the open issue M (its PR) already
covers, it mints nothing: it links N's open dependents as blocked by M, then
closes N as a duplicate (state_reason duplicate), its comment naming M; a final
issue closes so too. Before N closes, N's open PR closes, its comment naming M,
and N's issue-N claim is deleted by a git push from the workspace, so se fleet
fix finds no leftover claim. M is an open issue or a merged PR, never an open
PR, which may never merge: an open or unmerged PR is refused, and a merged PR's
commit on main is named, as se issue close --fixed-by does.

Flags:
  --body B           the open questions B the box could not answer
  --body-file PATH   a file PATH holding the open questions
  --duplicate-of M   the open issue or merged PR M that already covers N: close
                     N as its duplicate, minting nothing
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help issue tree

```text
se issue tree [ROOT] [--json] [--repo OWNER/NAME]

List every open se issue, each indented under its parent: its number, where it
stands (ready, claimed, blocked and by what), how many of its sub-issues are
closed, its labels and its title. With ROOT, list ROOT and every issue below it,
open or closed. Then estimate when the last open one closes, from what the fleet
measured over the last 7d (PaceWindow), read as the retro reads it: the se
issues merged an hour, and their claim-to-merge times (p50, p90) from the
landing answers; how many run at once (the leaves in flight now that are not
stuck, or the merges an hour times the p50, whichever is more); and the critical
path, the longest chain of open work that must run in a row (blocked-by links,
an ancestor's counting for its whole tree, and a review gate after its tree).
The estimate is the larger of the critical path end to end and the open work
spread over those running at once, at the p50 and at the p90 time; it names the
critical path, and how long the work takes at the window's pace, idle hours and
all. --json answers {"issues":[...],"queue":{...}} with the numbers.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help manifest

```text
se manifest [--write] [<name>]

A manifest section stands between <!-- se:manifest <name> --> and <!--
/se:manifest --> in a Markdown file, and is made from its owners: agents (the
registry of kinds and the plugin's agents), checks (the retro's rule checks),
help (every command's help, as se help and /se help give it), skills (the skills
folder), spec (spec/), usage <word>... (the usage lines of the commands under
each word). With a name, manifest prints that manifest; with --write, it
rewrites every section of every Markdown file git tracks and names the files it
changed, and refuses while git's index holds unmerged paths. The rule manifest
fails where a committed section differs.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
  --write          rewrite every manifest section in the checkout
```

## se help off

```text
se off

Switch SE off for this session. The daemon runs on for other sessions.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help on

```text
se on

Switch SE on: start this workspace's daemon and forward every event of the
session to it.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help overhaul file

```text
se overhaul file N [--draft FILE] [--json] [--repo OWNER/NAME]

File overhaul N's report from its judged draft FILE (default: ../overhaul-N.md
beside the workspace). It refuses a judgment that is not complete: a principle
without a verdict, nothing said on the outside world, the system's consistency,
the principles themselves, the retro, speed, mechanizing or removal, a finding
without its principle, place or how far it strays, an outside finding without a
source. A change to a principle is always controversial. It gets one se issue
per finding, one for a person (se-person) where it is controversial, then the
report as its closing comment, and closes: it never waits for the owner. Its
claim issue-N goes.

Flags:
  --draft FILE       the judged draft, a FILE (default: ../overhaul-N.md beside
                     the workspace)
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help overhaul new

```text
se overhaul new [--unattended] [--json] [--repo OWNER/NAME]

Create an overhaul: an se issue labelled se-overhaul that checks SE as it stands
against every design principle, the outside world, the consistency of the whole
system, the principles themselves and the retro's last 5 runs
(issues/config/overhaul-cadence), and fire the routine so a box takes it at
once. Its box creates the findings' issues, those for a person where
controversial, and closes it: an overhaul never waits. --unattended records that
no person started it; se issue pull --take starts one so every 5 closed retros.
spec/overhaul.md has the rules.

Flags:
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --unattended       no person started it: the cadence did
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help overhaul read

```text
se overhaul read N [--out FILE] [--json] [--repo OWNER/NAME]

Read overhaul N's facts and write its report draft to FILE (default:
../overhaul-N.md beside the workspace): every design principle from
spec/principles.md, mechanical or judged; the last 5 retros' metrics
(issues/config/overhaul-cadence), broken rule checks and findings, how many
became issues and closed, and which recurred; the previous overhaul's findings
with their issues' state; and the pruning and code-shape facts of the
workspace's code (production-unreachable, duplicates and near-duplicates, sizes,
one-user abstractions, unused se surfaces, legacy states, scripts, the files
untouched longest, the longest functions, files and parameter lists, switches on
a kind, and files touched per change). Where a report is already posted on N (an
overhaul from before overhauls stopped waiting for the owner), it writes that
one instead, to be filed as it stands.

Flags:
  --json             answer JSON
  --out FILE         where to write the draft, a FILE (default: ../overhaul-N.md
                     beside the workspace)
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help restart

```text
se restart

Stop this workspace's daemon and start it again. In an SE checkout, se is
rebuilt from its source first.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help retro collect

```text
se retro collect N [--out FILE] [--json] [--repo OWNER/NAME]

Read retro N's window from GitHub (everything closed since the last retro
closed) and write the report draft to FILE (default: ../retro-N.md beside the
workspace): the rule checks, the counts, the metrics against the previous
retros, how the previous retro's findings fared, the scripts added under
src/scripts/, and the matrix of every closed issue × every landing question.
Where a report is already posted on N (a retro from before retros stopped
waiting for the owner), it writes that one instead, to be filed as it stands.

Flags:
  --json             answer JSON
  --out FILE         where to write the draft, a FILE (default: ../retro-N.md
                     beside the workspace)
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help retro new

```text
se retro new (--field TEXT | --no-field | --unattended) [--json] [--repo
    OWNER/NAME]

Create a retro: an se issue labelled se-retro, whose window is everything closed
since the last retro closed, and fire the routine so a box takes it at once. A
person starts it with --field TEXT, their field feedback, which goes into the
issue (the agent se:retro passes it on), or --no-field. --unattended never asks.
Either way its box creates the findings' issues, those for a person where
controversial, and closes it: a retro never waits. spec/retro.md has the rules.

Flags:
  --field TEXT       the person's field feedback, as TEXT
  --json             answer JSON
  --no-field         a person starts it without field feedback
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --unattended       no person started it: never ask for field feedback
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help retro report

```text
se retro report N [--draft FILE] [--json] [--repo OWNER/NAME]

File retro N's report from its judged draft FILE (default: ../retro-N.md beside
the workspace). It refuses a judgment that is not complete. It gets one se issue
per finding, one for a person (se-person) where it is controversial, then the
report as its closing comment, and closes: it never waits for the owner. Its
claim issue-N goes.

Flags:
  --draft FILE       the judged draft, a FILE (default: ../retro-N.md beside the
                     workspace)
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help review brief

```text
se review brief N [--claims] [--json] [--repo OWNER/NAME]

Print the brief of gate N's review: its question, the text of every issue in its
tree, main's head as the pinned commit, the CI there and spec/principles.md; for
a re-review, the earlier blockers and the diff since. The workers' PR
descriptions and comments are withheld; --claims adds them, once the findings
are verified, as claims to check.

Flags:
  --claims           add the workers' accounts, as claims to check, once the
                     findings are verified
  --json             answer JSON
  --repo OWNER/NAME  the repository as OWNER/NAME (default: the workspace's
                     origin)
  --workspace DIR    the workspace DIR the daemon serves (default: here)
```

## se help rules

```text
se rules [--fix]

Check every file git tracks or would track against each rule in
src/internal/rules, naming each finding by file, line and rule, and how long
each rule took. The rules that read prose know se's commands and its manifests.
It fails on a finding; tests/check.sh runs it. --fix first applies the
mechanical part of each finding where the rule can, such as the fast-test rule's
t.Parallel() as a test's first statement, names each file it changed, and then
checks.

Flags:
  --fix            apply the mechanical part of each finding where the rule can,
                   then check
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help serve

```text
se serve [--idle D] [--takeover]

Run this workspace's daemon in the foreground: the debugger's way in.

Flags:
  --idle D         end after this long (D) without an event; 0 never (default:
                   30m0s)
  --takeover       ask a daemon already running for this workspace to step down,
                   and take its place
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help start

```text
se start

Answer the running daemon, or start one in the background. Prints its address
and token as JSON.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help status

```text
se status

Say whether a daemon answers for this workspace, and which commits the session's
SE came from: one line where the hooks, the plugin's checkout and se agree;
where they disagree, a short line per commit and the remedy, a new session,
once.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help stop

```text
se stop

End this workspace's daemon

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help ui

```text
se ui

Open SE's control panel, a grid of buttons every surface draws, the phone
included: the on/off toggle top left, then a button for each command registered
as one (a command that takes no typed words), each labelled with its name. A row
holds at most the cli instance's columns config value (cli/config/columns) and
the next button starts the next row; every cell is as wide as every other, so
the columns align from row to row and a short last row stays to the left. A
press runs what typing /se <name> runs.

Flags:
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```

## se help update

```text
se update [--repo DIR] [--session-start]

Pull main into the installed SE checkout, rebuild se, restart a running daemon
and reload the plugin.

Flags:
  --repo DIR       the installed SE checkout DIR (default: the one this binary
                   was built into)
  --session-start  as the plugin runs it at session start: never fail, say
                   nothing when nothing changed
  --workspace DIR  the workspace DIR the daemon serves (default: here)
```
<!-- /se:manifest -->
