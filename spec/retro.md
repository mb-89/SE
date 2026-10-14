# Retro: do SE's rules hold across what landed?

Reader: whoever changes how a retro runs, and the box judging one.

A retro is not a review of single issues. It checks whether SE's rules held
across everything that landed since the last retro, scores whether the last
retro's fixes worked, and turns what it finds into fixes for the machinery. In
order of preference those fixes are: a check, a refusal, a gate, a prefilled
field, and only last a sentence of guidance. It is blameless: it fixes what
produced a bad outcome, not the outcome. The principles it measures against
are [principles.md](principles.md).

What earlier versions taught, and how this design answers it:

- the window broke when it was computed from private files or logs, so here
  it comes from GitHub only;
- findings piled up undelivered, so here they become `se` issues;
- box transcripts died with their containers, so here the record is the
  landing answers ([issues.md](issues.md#landing-answers));
- retros ran too heavy, so here the mechanical half is one command.

## The rules

- **A retro is an issue** labelled `se` and `se-retro`. Its window is
  everything closed since the last closed `se-retro` issue closed, read from
  GitHub. The first retro covers the repository's whole history.
- **Starting one:** `se retro new` creates the issue (through the same code as
  `se issue new`) and fires the routine, as fan-out does, so a box takes it at
  once.
  - Started by a person (the default): the agent `se:retro` first takes the
    person's **field feedback**, which `--field TEXT` puts into the issue.
    `--no-field` skips the question. `se retro new` refuses to guess: it takes
    exactly one of `--field`, `--no-field` and `--unattended`.
  - `--unattended` never asks. The automatic cadence (below) starts retros this
    way.
  - The issue's body records which it is, `<!-- se:retro attended -->` or
    `<!-- se:retro unattended -->`.
- **The cadence:** retros happen without anyone remembering them. When
  `se issue pull --take` runs, before offering anything else, it counts the
  `se` issues closed since the last closed `se-retro` issue closed, retros,
  overhauls and final issues (`se-final`) not counted, so what retros,
  reviews and overhauls file does not start the next retro (with none closed
  yet, the whole history). At `issues/config/retro-cadence` (the
  issues instance's config value, built-in in `src/internal/issues/cadence.go`) or more, with no `se-retro` issue open,
  it starts an unattended retro, as `se retro new --unattended` does, and
  takes it ahead of all other work but a due overhaul
  ([overhaul.md](overhaul.md)). An open `se-retro` issue, attended or not,
  means no second one is started, under a race too: after starting one,
  `--take` reads the open `se-retro` issues again, and where a lower one is
  open, closes its own as a duplicate of it, with a comment naming it, takes
  nothing from the cadence and goes on to the normal take. A retro closed as
  a duplicate never ran: it opens no window and the overhaul does not count
  it. `--take N` names its issue and skips the
  cadence. The plain `se issue pull` only reports the count, and that a retro
  is due.
- **The box** takes a retro like any issue (`se issue pull --take` says it is
  a retro and names its agent, `se:retro`) and starts that agent, which files
  the report instead of landing a branch.
- **The mechanical half,** `se retro collect N`, reads the window from GitHub
  and writes a report draft beside the checkout (`../retro-N.md`). It holds:
  - the matrix: every closed issue × every landing question, from the
    answers' machine-readable blocks; it stays in the draft and is not posted;
  - the [rule checks](#the-rule-checks), each broken one with what broke
    it;
  - **sizes:** the closed issues, the landed ones (those the `answers` check
    counts: a leaf closed as completed, not a retro, an overhaul or a
    person's decision), the closed issues for a person and the duplicates,
    each its own count, so a sweep closing issues for a person reads as one;
  - **counts:** conflicts (conflict takeovers), takeovers, `se-person` flags,
    CI reruns, `by-hand` answers that are not "none", the GitHub requests the
    landing facts counted, their rate-limit refusals and the minutes waited
    for the reset, and the median time from claim to merge;
  - **issues for a person** per closed issue, against a soft budget of 0.1
    (`PersonBudget`), which the draft says it is within or over: an issue for
    a person is the last resort ([principle 15](principles.md));
  - **open points** and **decisions:** every closed issue's `open` and
    `decisions` answers that are not "none"; the decisions are listed for the
    owner to look at;
  - **scripts:** every file added under `src/scripts/` in the window, grouped
    by the word its name starts with, each with the comment line that says why;
  - **the previous retro's findings:** did their issues close, and did their
    classes recur?
- **The judgment half (the box):** it reads the draft, looks for what the
  window made inconsistent, restated or written for no reader (principles 17
  to 19), groups the findings into classes, picks each class's cheapest
  durable fix and records what went well. How, and the fields it writes into
  the draft's block, are the agent's (its steps 2 and 3).
- **Who decides (the owner's rule for retros and overhauls alike):** every
  finding becomes an issue through the same code as `se issue new`,
  labelled `se-final`: what a run files is its output, never superseded and
  never counted toward the cadence.
  - The **non-controversial** findings go into the run's one manifest,
    `Findings of the retro #N`, labelled `se-manifest` and `se-final`, which
    the first of them creates; its leaves land as one PR
    ([issues.md](issues.md#manifests-all-work-moves-in-them)).
  - A **controversial** one is an issue for a person: labelled `se-person`
    and assigned to the owner, it waits for them. The retro does not.
  - The **open points** the window's landing answers name (`open`) are
    listed in the draft (`## Open points`): a box opens no issue, so the
    retro is the one that turns them into findings.

  Controversial means only what only a person can do
  ([principle 15](principles.md)), its `kind` one of:
  - `access`: a setting, an account, a secret, a permission or a payment only
    the owner has;
  - `principle`: it changes a design principle.

  Its `why` says in a sentence what only the person can do. Everything else
  is normal work, the box's decision named in the finding's `decision`, which
  its issue carries for the owner to review afterwards: a trade-off of one
  metric against another, a finding the box is not sure about, one that
  recurred after an earlier fix, one too big for one leaf, removing
  something, and changing a command's interface or a landing question.

  `se retro report N` files the judged draft. It refuses, writing nothing, a
  judgment that is not complete: a finding without a title, a body, a class
  the classes name, a known home, or a `kind` (access or principle) and a `why`
  where it is controversial; a
  class without a fix; an unknown check or metric; nothing that went well.
  **A retro never waits**, whoever started it: `se retro report` creates the
  issues at once, by the rule above, posts the report as the retro's closing
  comment, and closes it. What needs the person is in the issues for them;
  they decide there. (A report posted for the owner before retros stopped
  waiting is handed back by `se retro collect`, and filed as it stands, with
  whatever the owner said in its comments applied.)

  It deletes the retro's claim, `issue-N`: a retro lands no branch. Where the box's token may not delete branches, it says so and goes
  on: `se fleet prune` removes the branch once the retro is closed, and a
  resumed retro's stale claim is taken over like any stuck claim.
- **The retro reviews itself**, every time, as a fixed part of the report:
  - **Metrics against the previous retros:** conflicts, takeovers, CI reruns,
    `se-person` flags, `by-hand` mentions, duplicates (issues closed as
    duplicate, and issues for a person made in the window beyond the first
    for each issue they hold back), GitHub requests, rate-limit refusals and minutes waited for
    the reset, and time from claim to merge, each per landed issue (never per closed issue: closing issues
    for a person or duplicates must not make a metric read better), beside
    the sizes. `se retro collect` computes them and stores them in the
    report's machine-readable block, so the trend is a number, not an
    impression; the draft tabulates them against every earlier retro.
  - **Did the last retro's fixes help?** For each of its findings: did its
    issue close, did the rule check it named break again, did its metric
    drop. A metric's move counts for a finding only once its issue closed
    as completed: before its fix is on main, a drop is not the fix's.
  - **Is the retro itself effective?** How many findings became issues, how
    many of those closed, and which findings recurred anyway.
  - **Should the retro change itself?** Proposals for the landing questions
    ([landing.yaml](landing.yaml)), the rule checks, the metrics or the retro
    agent are findings like any other, with the same homes (`retro: true`).
- **The report stays on the retro issue** as its closing comment, opening
  with `<!-- se:retro-report -->`, with a machine-readable block under
  `<!-- se:retro-yaml -->`: the window, metrics, rule checks, the previous
  retro's score, findings with the issues they became, classes and what went
  well. The next retro reads it first.

## The rule checks

Each rule is checked only on what closed after the PR that brought it merged,
so a rule does not count the history it predates; a rule on what is written at
creation, as the mark is, only on what was created after it. What broke it before, in the
window, the draft gives once as a count beside it, outside the broken checks
the next retro scores. `RuleChecks` in `src/internal/issues/retro.go` owns the
list:

<!-- se:manifest checks -->
- `fixes`: every merged PR said `Fixes #n`; checked on what closed after PR #14 brought it.
- `ci`: every merged PR had green CI (the last run of each check on its head); checked from the first commit.
- `outside-pr`: no commit reached main outside a PR (every commit on main is some merged PR's merge commit); checked from the first commit.
- `mark`: every `se` issue carries `se issue new`'s mark, `<!-- se:new -->`, which it writes at the end of every body; checked on what was created after PR #91 brought it.
- `answers`: every landed issue (a leaf closed as completed, not a retro, an overhaul or a person's decision) has landing answers; checked on what closed after PR #74 brought it.
<!-- /se:manifest -->

## The commands

<!-- se:manifest usage retro -->
```
se retro collect N [--out FILE] [--json] [--repo OWNER/NAME]
se retro new (--field TEXT | --no-field | --unattended) [--json] [--repo OWNER/NAME]
se retro report N [--draft FILE] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

All three are offered in a session, as `/se retro <word>`. They read and write GitHub through `gh api`, as the issue
commands do ([issues.md](issues.md)), in `src/internal/issues`.
