# Learnings

- Parse a command-line value from a sibling script through a lazy resolver, not while registering commands; eager import can re-enter a partially initialized module, especially when tests load scripts with `importlib`.
- Keep each GitHub plan step's action key aligned with the adapter map (`comment_issue`, `close_issue`); a custom step name without a matching action fails after the plan is built.
- Run `python -m py_compile` before invoking a command that imports changed Python modules; a syntax error otherwise prevents both the command and its tests from starting.
- In collection tests, set prior-issue comments on the fake door before calling `collect`; updating the fixture after collection does not exercise outcome-marker parsing.
- On Windows with `core.autocrlf=true`, inspect byte-comparison failures for CRLF-only differences before changing generated outputs; path-bearing expectations should use native path syntax instead of hard-coded `/`.
- If an open-ended template field can be answered `None.`, declare `none_ok` in its schema; a placeholder is still checked as an answer.
- Move local tickets through their lifecycle: `work_tickets.py move` rejects a direct `todo` to `done` transition; move a worked ticket to `held` first.
- When changing session titles, follow every consumer, including retro cost attribution, not just
  fleet discovery. New sessions use the new scheme; historical evidence still needs to attribute
  sessions recorded under earlier titles.
- On a Windows checkout, the plugin build tolerates CRLF, but its byte-for-byte tests require
  canonical generator output. Regenerate those bytes from `se_plugin.expected()` before those
  checks rather than changing the generator or weakening the tests to hide checkout conversion.
- Check the active checkout's root and branch before editing after a handoff; paths in summarized
  history can name a sibling checkout.
- For a worktree-scoped command, pass its required `--worktree` explicitly even when running from
  that checkout; check its help, and create its destination's parent directory when needed
  (`field-report --draft` does not create it).
- Keep validation bounded: run focused tests first and stop any command that exceeds its timebox,
  reporting the limited validation rather than waiting on a broader suite.
- For an authorized issue-free fix, use `field-report --draft --authorized-fix`, then the checked
  `work_tickets.py push` or `deliver` path; never invent an issue snapshot or bypass the hooks.
- Prefer `work_tickets.py guard` when checking a report's removed tests and prose, rather than
  composing long inline probes. If introspection is necessary, read the helper's actual name
  first: the test-removal helper is `deleted_test_places`, not `deleted_tests`.
- Batch authored-content reads when a field-report guard checks a whole tree; one `git show` per
  tracked path exceeded the delivery timebox. Wrong: start one Git process per file; right: list
  the matching blobs once and read them with `git cat-file --batch`.
