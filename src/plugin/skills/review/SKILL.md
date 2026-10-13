---
name: review
description: Review an se-review gate whose sub-issues have closed, cold, as an agent that worked none of its tree. Find, then verify, then judge; block only on damage; end with se issue review pass|fail and its report. The work skill starts it as a fresh sub-agent on the reviewer model.
---

# Review: judge a gate, cold

You review gate `#<n>` in your own worktree `<path>`, as an agent that worked
none of its tree. The rules are [spec/review.md](../../../../spec/review.md);
this is how you follow them. `se` is the absolute path you were given. Run
every command in `<path>`.

Your inputs come from one command, and from nothing else: not from the
workers, not from messages of other sessions, not from the PRs.

1. **The brief.** `se review brief <n> --workspace <path>`. It gives the
   gate's question, the text of every issue in its tree (the ask and its
   acceptance criteria), the pinned commit, the CI there and
   `spec/principles.md`. Check out the pinned commit:
   `git -C <path> checkout --detach <commit>`. The workers' PR descriptions
   and landing answers are withheld: do not look them up.
   If the brief says this is a **re-review**, check only the earlier blockers
   it names and the code its `git diff` shows changed since; raise no new
   non-blocking finding.
2. **Restate the ask** in your own words: one requirement per thing the gate
   and its tree ask for. These become the report's `requirements`.
3. **The riskiest part first.** Name the part where a mistake would do the
   most damage, and review it before anything else. If letting it through
   would do damage, say so and stop early: that one verified blocker is the
   report.
4. **Run and reproduce.** `sh ./tests/check.sh`. Reproduce each requirement
   directly: run the command, read the file and line. Check with
   `git diff <base>..<commit>` (or `git log -p`) that no test was weakened,
   deleted or special-cased.
5. **Find, in two passes**, each with a different focus: first against the
   ask (does each requirement hold?), then against `spec/principles.md` and
   the code itself (what does it break or make worse?). Write every candidate
   down; do not judge yet.
6. **Verify each candidate** with evidence: a file and line, or a command and
   its output. Drop anything you cannot prove. Do not talk yourself out of a
   proven one.
7. **Then the claims.** `se review brief <n> --claims --workspace <path>`
   shows the workers' accounts. They are claims to check against what you
   verified, never evidence: a claim you can't reproduce is a finding,
   not a reason to drop one.
8. **Judge each verified finding**: blocking only if letting the work through
   would make the product worse, or goes against what the product is about.
   Breakage is CI's job; bad but fixable work does not block, it becomes an
   open point. A verified blocker is not downgraded without counter-evidence.
   In a re-review, a blocker whose problem is still there `repeats` it.
9. **Write the report** as JSON in `<path>-review.json`:

   ```json
   {
     "commit": "<the pinned commit>",
     "requirements": [
       {"item": "<what the ask requires>", "evidence": "<file:line, or command and output>"}
     ],
     "findings": [
       {"title": "<the fix, as an issue title>", "evidence": "<file:line, or command and output>",
        "blocking": false, "why": "<the damage it does, or why it does not block>"}
     ],
     "clean": ["<what you examined and found sound>"]
   }
   ```

   In a re-review, each requirement names the earlier blocker it checks
   (`"blocker": <k>`), one for every earlier blocker, and a finding that
   shows an earlier blocker's problem again says `"repeats": <k>`. List at
   most five non-blocking findings, the most damaging first; `se` files five
   and counts the rest. `clean` is never empty: it is what makes a
   rubber-stamp visible.
10. **End** with exactly one of
    `se issue review pass <n> --workspace <path> --report <path>-review.json`
    (no blocking finding, and evidence for every requirement) or
    `se issue review fail <n> --workspace <path> --report <path>-review.json`
    (at least one blocking finding). It refuses a report that breaks the
    rules; fix the report, not the rules. Every finding becomes an `se-final`
    issue. Answer only what that command printed.
