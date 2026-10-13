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
  - Started by a person (the default): the retro skill first asks the person
    for **field feedback**, which `--field TEXT` puts into the issue.
    `--no-field` skips the question. `se retro new` refuses to guess: it takes
    exactly one of `--field`, `--no-field` and `--unattended`.
  - `--unattended` never asks. The automatic cadence (#41) starts retros this
    way.
  - The issue's body records which it is, `<!-- se:retro attended -->` or
    `<!-- se:retro unattended -->`.
- **The box** takes a retro like any issue (`se issue next --take` says it is
  a retro) and follows the retro skill,
  [src/plugin/skills/retro/SKILL.md](../src/plugin/skills/retro/SKILL.md),
  instead of landing a branch.
- **The mechanical half,** `se retro collect N`, reads the window from GitHub
  and writes a report draft beside the checkout (`../retro-N.md`). It holds:
  - the matrix: every closed issue × every landing question, from the
    answers' machine-readable blocks; it stays in the draft and is not posted;
  - **rule checks:**
    - `fixes`: every merged PR said `Fixes #n`;
    - `ci`: every merged PR had green CI (the last run of each check on its
      head);
    - `outside-pr`: no commit reached main outside a PR (every commit on main
      is some merged PR's merge commit);
    - `mark`: every `se` issue carries `se issue new`'s mark,
      `<!-- se:new -->`, which it writes at the end of every body;
    - `answers`: every landed issue (a leaf closed as completed, not a retro)
      has landing answers;
  - **counts:** conflicts (conflict takeovers), takeovers, `se-person` flags,
    CI reruns, `by-hand` answers that are not "none", and the median time from
    claim to merge;
  - **scripts:** every file added under `src/scripts/` in the window, grouped
    by the word its name starts with, each with the comment line that says why;
  - **the previous retro's findings:** did their issues close, and did their
    classes recur?
- **The judgment half (the box):**
  - read the draft;
  - look for what became inconsistent in the window, a hand-written element
    that now restates what another owns, and prose that serves no reader its
    file names (principles 17 to 19); each is a finding like any other;
  - group findings into classes, where three of a kind is a property of the
    machinery;
  - pick each class's cheapest durable fix;
  - record what went well.

  It writes its judgment into the draft's block: `findings` (each a `title`,
  `class`, `body`, `home`, and `controversial` with its `why`; optionally the
  rule `check` or the `metric` it should move, which the next retro scores it
  by, and `retro: true` for a finding about the retro itself), `classes`
  (`name`, `fix`) and `went_well`. A finding's `home` is one of `check`,
  `refusal`, `gate`, `field` (a prefilled one), `command` (an `se` command
  for a step done by hand), `guidance` or `removal`.
- **Who decides (the owner's rule for retros and overhauls alike):** every
  finding becomes an issue through the same code as `se issue new`.
  - A **non-controversial** finding goes into the normal queue.
  - A **controversial** one is created with the label `se-person` and
    assigned to the owner, so it waits for a person.

  Controversial means any of:
  - it changes a design principle ([principles.md](principles.md));
  - it trades one metric against another;
  - the box is not sure;
  - it already failed or recurred after an earlier fix (repeated failure goes
    to a person).

  Not controversial, so normal work: removing something, and changing a
  command's interface or a landing question.

  `se retro report N` files the judged draft. It refuses, writing nothing, a
  judgment that is not complete: a finding without a title, a body, a class
  the classes name, a known home, or a `why` where it is controversial; a
  class without a fix; an unknown check or metric; nothing that went well.
  When the issues are created depends on who is there:
  - **A person is present (the default):** `se retro report` posts the report
    on the retro issue and stops: the issue is labelled `se-person` and
    assigned to the owner. The person may move findings between the two kinds
    in a comment, then runs `se issue resume`. The next box takes the retro
    again, `se retro collect` hands it the posted report, it applies what the
    person decided to the block, and `se retro report` creates the issues as
    decided and closes the retro.
  - **Unattended:** `se retro report` creates the issues at once, by the rule
    above, and closes the retro.

  Either way it deletes the retro's claim, `issue-N`: a retro lands no
  branch. Where the box's token may not delete branches, it says so and goes
  on: `se fleet prune` removes the branch once the retro is closed, and a
  resumed retro's stale claim is taken over like any stuck claim.
- **The retro reviews itself**, every time, as a fixed part of the report:
  - **Metrics against the previous retros:** conflicts, takeovers, CI reruns,
    `se-person` flags, `by-hand` mentions and time from claim to merge, each
    per closed issue. `se retro collect` computes them and stores them in the
    report's machine-readable block, so the trend is a number, not an
    impression; the draft tabulates them against every earlier retro.
  - **Did the last retro's fixes help?** For each of its findings: did its
    issue close, did the rule check it named break again, did its metric
    drop.
  - **Is the retro itself effective?** How many findings became issues, how
    many of those closed, and which findings recurred anyway.
  - **Should the retro change itself?** Proposals for the landing questions
    ([landing.yaml](landing.yaml)), the rule checks, the metrics or the retro
    skill are findings like any other, with the same homes (`retro: true`).
- **The report stays on the retro issue** as its closing comment, opening
  with `<!-- se:retro-report -->`, with a machine-readable block under
  `<!-- se:retro-yaml -->`: the window, metrics, rule checks, the previous
  retro's score, findings with the issues they became, classes and what went
  well. The next retro reads it first.

## The commands

<!-- se:manifest usage retro -->
```
se retro collect N [--out FILE] [--json] [--repo OWNER/NAME]
se retro new (--field TEXT | --no-field | --unattended) [--json] [--repo OWNER/NAME]
se retro report N [--draft FILE] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

`new` is offered in a session as `/se retro new`; all three are, as
`/se retro <word>`. They read and write GitHub through `gh api`, as the issue
commands do ([issues.md](issues.md)), in `src/internal/issues`.
