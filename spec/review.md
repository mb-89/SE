# Review: how a gate is reviewed

Reader: whoever changes how a gate is reviewed, and the reviewer checking a rule.

A gate is an issue labelled `se-review` (see [Reviews](issues.md#reviews)): it
is reviewed once its sub-issues have closed, by an agent that worked none of
them. These rules say **how** that agent works. The agent `se:reviewer`
(see the agents in [spec/issues.md](issues.md#the-box)) is how a reviewer
follows them; `se review brief` and `se issue review` (in
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
2. **The steps are the reviewer agent's:** finding, verifying and judging are
   separate steps, and the riskiest part comes first, so a reviewer that
   finds damage can stop early. A verified blocker is judged by rule 3.
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
   - a non-blocking one goes into the review's one manifest of findings,
     `Findings of the review of #N`, labelled `se-manifest` and `se-final`,
     which the first of them creates, and fires the routine once, as a new
     ready issue does;
   - a blocking one becomes a sub-issue of the gate, so the gate is reviewed
     again after it lands.

   At most `issues/config/max-filed` non-blocking findings are filed; the rest are
   counted in the report, not filed.
5. **Final is general: any second attempt is final, and agents decide
   (the owner's rule).** Labels combine: `se` marks fleet work, and
   `se-final` is a separate label beside it. An issue becomes `se-final`
   when:
   - a review creates it to fix a finding;
   - `se issue pull --take` takes it over stuck, with no push for too long
     or a red PR ([Stuck work](issues.md#stuck-work)).

   A conflict is no failure: main moves on under a PR through no fault of
   its box, so a conflict takeover never makes an issue final, and a final
   issue in conflict is taken over like any other
   ([The rules](issues.md#the-rules)).

   A final issue is never superseded again: its box lands a PR. Nothing
   mints an issue for a person on a box's behalf. If an `se-final` issue
   fails again:
   - stuck again: it is taken over again, like any other (a conflict is no
     failure, [The rules](issues.md#the-rules));
   - its re-review finds the same problem: the finding says it `repeats` the
     earlier blocker. The repeat is accepted, the reviewer's decision, named
     in the report: it files nothing and blocks no more, and where nothing
     else blocks, the gate closes.

   This bounds the review loop at one retry. The label is the single record
   of a takeover of stuck work: such a takeover sets it. The
   `<!-- se:takeover N -->` comment stays as the human-readable record, and
   its round only settles two boxes racing for one takeover.
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
     became, or that it is an accepted repeat;
   - a **"checked and clean" list** of what was examined and found sound, so
     a rubber-stamp is visible.

   `se issue review pass` refuses a PASS where any requirement lacks
   evidence, or a finding blocks; `fail` refuses a FAIL without a verified
   blocking finding; both refuse a report without the "checked and clean"
   list, or with a finding that lacks evidence or a judgment. A refused
   review writes nothing.
8. **The reviewer's model:** a stronger model than the boxes run, where one
   is available. The choice is one line, `reviewer:` in
   [spec/models.yaml](models.yaml), which the agent's front matter names
   too (the rule `agents` holds them equal). `se issue pull --in ROOT --take
   --json` names each review's `agent`, and the box starts it. Today's box
   model is the floor; the reviewer is never weaker.
9. **The retro** ([#40](https://github.com/mb-89/SE/issues/40)) counts
   reviews in its window: how many ran; passed or blocked; findings filed;
   `se-final` issues that failed; findings later confirmed (their issue
   closed with a change) versus dropped. The reports' machine-readable blocks
   are what it counts from.

10. **What others built runs on the delta:** the brief ends with the
   reviewer's list from the reuse config of
   [src/index/wiring.yaml](../src/index/wiring.yaml)
   (the simplifier, `/security-review` and the pr-review-toolkit agents),
   each resolved against the plugins the box loaded. What they report are
   candidates, verified like any other. The report's `ran` names each entry
   once, with what it found or why it did not run, and `se issue review`
   refuses a report that leaves one out; the verdict shows them under "Ran
   on the delta". The worker runs its light list before it commits, the
   overhaul its heavy one over everything, each handed over by the take;
   an agent's front matter preloads (`skills`) only what its tier's list
   names (the rule `agents`).

## The report

`se issue review pass|fail N --report PATH` reads the report as JSON, in the
shape the reviewer agent's step 9 gives; an unknown field is refused, so a typo
never drops a section.

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
findings became (with `--json`: `{"issue","passed","fixes","filed","unfiled","accepted","closed"}`).
