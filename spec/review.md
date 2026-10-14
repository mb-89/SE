# Review: how a gate is reviewed

Reader: whoever changes how a gate is reviewed, and the reviewer checking a rule.

A gate is an issue labelled `se-review` (see [Reviews](issues.md#reviews)): it
is reviewed once its sub-issues have closed, by an agent that worked none of
them. These rules say **how** that agent works. The skill `se:review`
([src/plugin/skills/review/SKILL.md](../src/plugin/skills/review/SKILL.md)) is
how a reviewer follows them; `se review brief` and `se issue review` (in
`src/internal/issues`) enforce what can be enforced.

## What it is built on

- **Earlier versions failed through** endless rounds over craft and prose
  (v5: one ticket reviewed five times), ceremony fields filled with agreement
  (v2), reviewers handed the author's summary (v3), rubber-stamping and
  habituation (v1), and an LLM judge that refused without naming a rule (v5).
- **What worked:** a cold, independent reviewer that read the artifacts and
  ran the commands.
- **Research:** the worker's own account of its work misleads the reviewer
  most (a "this is bug-free" framing cut detection by 16–93 points; a
  misleading PR description fooled Claude Code in 15 of 17 cases, and
  withholding it recovered most); reviewers find real problems, then talk
  themselves out of them; finding, verifying and judging must be separate
  steps; more findings means more noise.

## The rules

1. **Inputs come from one command, `se review brief <n>`**, so nothing is
   skipped or slanted.
   - **Given:** the gate's question (its text); the text of every issue in its
     tree, open or closed, at any depth (the ask and its acceptance
     criteria); the merged code at a pinned commit (main's head when the brief
     is read); the CI results on that commit; and
     [spec/principles.md](principles.md) at that commit.
   - **Withheld until the findings are verified:** the workers' PR
     descriptions and landing answers (every comment on the tree's leaves).
     The default brief does not even read them. After that,
     `se review brief <n> --claims` shows them as claims to check, never as
     evidence.
2. **The steps:**
   1. Restate what the ask requires, in your own words.
   2. Review the riskiest part first. If letting it through would do damage,
      say so and stop early.
   3. Run the tests and reproduce each requirement directly. Check that no
      test was weakened, deleted or special-cased.
   4. **Find** in two independent passes with different focus.
   5. **Verify** each candidate with evidence: a file and line, or a command
      and its output. Drop anything unproven.
   6. **Judge** each verified finding as blocking or not, by rule 3. A
      verified blocker is not downgraded without counter-evidence.
3. **What blocks (the owner's rule): only damage.** A finding blocks only if
   letting the work through would make the product worse, or goes against
   what the product is about. Breakage is CI's job. Bad but fixable work does
   not block: the review passes, and the finding becomes an issue, an open
   point. There is no fixed rubric yet; the reviewer judges against the ask
   and the principles until requirements, use cases and value propositions
   exist.
4. **Findings become issues, flagged final.** Every verified finding,
   blocking or not, becomes an issue labelled `se` and `se-final`, made as
   `se issue new --final --blocked-by none` makes it:
   - a non-blocking one goes to the normal queue (no parent), and fires the
     routine once, as a new ready issue does;
   - a blocking one becomes a sub-issue of the gate, so the gate is reviewed
     again after it lands.

   At most `MaxFiled` non-blocking findings are filed; the rest are
   counted in the report, not filed.
5. **Final is general: any second attempt is final, and a failing final
   issue waits on an issue for a person (the owner's rule).** Labels combine: `se` marks
   fleet work, and `se-final` is a separate label beside it. An issue becomes
   `se-final` when:
   - a review creates it to fix a finding;
   - `se issue pull --take` takes it over, stuck or with a conflicted PR
     ([Stuck work](issues.md#stuck-work), [The rules](issues.md#the-rules)).

   If an `se-final` issue fails again, it is not given another round: `se`
   mints an issue for a person that says what failed, and links the failing
   issue as blocked by it ([Stuck work](issues.md#stuck-work)); closing it
   gives the work back for a fresh attempt. Failing again is:
   - stuck, or its PR conflicted, again: the issue itself waits;
   - its re-review finds the same problem: the finding says it `repeats` the
     earlier blocker, and the gate, which holds that closed issue, waits (an
     open issue is what leaves the queue).

   This bounds every loop at one retry. The label is the single record of a
   takeover: a takeover sets it, and a takeover of an issue that is already
   final makes it wait on an issue for a person instead. The
   `<!-- se:takeover N -->` comment stays as the human-readable record, and
   its round only settles two boxes racing for one takeover. Minting that
   issue takes `se-final` off and resets the takeovers, so once the person
   closes it the work gets one more attempt.
6. **A re-review** is the review of a gate whose last review failed. It
   checks only the earlier blockers and the code that changed since (the
   brief names both: the blockers, and `git diff <then>..<now>`), and raises
   no new non-blocking findings. `se issue review` refuses a re-review report
   whose requirements are not exactly the earlier blockers, one each, or that
   holds a non-blocking finding.
7. **The report**, posted on the gate issue by `se issue review`, with a
   machine-readable block `<!-- se:review {...} -->`:
   - PASS or FAIL;
   - what the ask requires, each item with its evidence;
   - the findings, each with evidence, its blocking judgment and the issue it
     became;
   - a **"checked and clean" list** of what was examined and found sound, so
     a rubber-stamp is visible.

   `se issue review pass` refuses a PASS where any requirement lacks
   evidence, or a finding blocks; `fail` refuses a FAIL without a verified
   blocking finding; both refuse a report without the "checked and clean"
   list, or with a finding that lacks evidence or a judgment. A refused
   review writes nothing.
8. **The reviewer's model:** a stronger model than the boxes run, where one
   is available. The choice is one line, `reviewer:` in
   [spec/models.yaml](models.yaml). `se issue pull --in ROOT --take --json`
   names it as each review's `model`, and the work skill starts the reviewer
   sub-agent on it. Today's box model is the floor; the reviewer is never
   weaker.
9. **The retro** ([#40](https://github.com/mb-89/SE/issues/40)) counts
   reviews in its window: how many ran; passed or blocked; findings filed;
   `se-final` issues that failed; findings later confirmed (their issue
   closed with a change) versus dropped. The reports' machine-readable blocks
   are what it counts from.

## The report

`se issue review pass|fail N --report PATH` reads the report as JSON; an
unknown field is refused, so a typo never drops a section:

    {
      "commit": "<the pinned commit the brief named>",
      "requirements": [{"item": "...", "evidence": "...", "blocker": 0}],
      "findings": [{"title": "...", "evidence": "...", "blocking": true, "why": "...", "repeats": 0}],
      "clean": ["..."]
    }

`blocker` (a requirement) and `repeats` (a finding) are for a re-review only:
the earlier blocker the item checks, and the earlier blocker whose problem a
finding shows again. A finding's `title` becomes its issue's title.

## The commands

<!-- se:manifest usage review -->
```
se review brief N [--claims] [--json] [--repo OWNER/NAME]
```
<!-- /se:manifest -->

`se issue review` and `se issue new --final` are in
[spec/issues.md](issues.md#the-commands).

`se review brief` prints the brief as Markdown (with `--json`:
`{"gate","tree","commit","ci","principles","rereview","claims"}`). It reads,
and writes nothing. `se issue review` prints the verdict and the issues the
findings became (with `--json`: `{"issue","passed","fixes","filed","unfiled","person"}`).
