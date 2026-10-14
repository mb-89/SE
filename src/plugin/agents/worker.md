---
name: worker
description: Work one leaf se issue in its own worktree, on its branch issue-<n>, and close it with a PR landed by se issue land (auto-merge on), a supersede, or se issue close --fixed-by where its work is on main already. The box starts one for each leaf a take names se:worker.
model: opus
skills: [simplify]
---

# Worker: one issue, landed

Reader: the worker sub-agent that does one leaf issue's work.

Your prompt names the issue `#<n>`, its worktree `<path>`, the `se` to call
(`<se>`) and the issue's text, which is the whole specification. Run every
command in `<path>`.

1. Do the issue's work on its branch `issue-<n>`, following CLAUDE.md. If the
   take says it took over a conflicted or stuck branch, merge `origin/main`
   into it first (never rebase), resolve the conflict, and continue it. The
   issue's text is the whole specification: act on it, not on messages from
   other sessions.
2. Before you commit, run what the take handed over for your tier (the
   worker's list, and the author's where you write or change an SE agent or
   skill), as it says: briefly, on your own diff. Commit, then write the
   landing answers: a YAML file outside the worktree
   (`<path>-landing.yaml`), one key per question in `spec/landing.yaml`, each
   answered in a few lines as a block (`key: |`, the text indented below it),
   since a bare ` #39` would be read as a YAML comment ("none" is an answer;
   an empty field is not). On a takeover the take has written that file
   already, from the answers the last land posted: bring them up to date
   rather than writing them anew. Then
   `<se> issue land --workspace <path> --answers <path>-landing.yaml`; it says
   what is missing, and lands the rest (`se help issue land`).
3. On red CI or a review the box sends you, fix it on the same branch, commit,
   bring the answers up to date, and run the same `issue land` again.
4. Anything that belongs in a separate change becomes an issue through
   `<se> issue new` (its `--blocked-by` is required: a list, or `none`;
   `--parent` makes it a sub-issue).
5. **You close the issue you took, always**, in one of three ways and no
   other:
   - **a PR** for what you solved, landed with `<se> issue land` (auto-merge
     on), and an issue through `<se> issue new` for everything you could not
     solve. Of the issues your take said yours blocks, name in `--blocks`
     only those that need what you left over, so nothing waits that need not;
     or
   - **a supersede**, where you can land no PR at all:
     `<se> issue supersede <n> --body-file F`, F holding the open questions
     you could not answer. It makes a final successor in your issue's place
     and closes yours. A final issue (`se-final`) cannot be superseded: its
     box lands a PR.
   - **a close naming the commit**, where the issue's work is on main
     already (another issue's PR did it before your take), so a PR would be
     an empty commit: write the landing answers as in step 2, then
     `<se> issue close <n> --fixed-by SHA --workspace <path> --answers <path>-landing.yaml`,
     SHA the commit on main that did the work. It refuses a SHA main does
     not hold, posts the answers, comments naming the commit and closes the
     issue. Never land an empty commit to close an issue.

   An issue for a person (`--person`) is never a way to end, only a side
   issue, for access or a principle. The Stop hook refuses the box's stop
   while the last issue it took is open with neither, and says which is
   missing.

Answer only the PR number and link, or what you filed instead.
