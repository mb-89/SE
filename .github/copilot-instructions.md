# Learnings

- Parse a command-line value from a sibling script through a lazy resolver, not while registering commands; eager import can re-enter a partially initialized module, especially when tests load scripts with `importlib`.
- Keep each GitHub plan step's action key aligned with the adapter map (`comment_issue`, `close_issue`); a custom step name without a matching action fails after the plan is built.
- Run `python -m py_compile` before invoking a command that imports changed Python modules; a syntax error otherwise prevents both the command and its tests from starting.
- In collection tests, set prior-issue comments on the fake door before calling `collect`; updating the fixture after collection does not exercise outcome-marker parsing.
- On Windows with `core.autocrlf=true`, inspect byte-comparison failures for CRLF-only differences before changing generated outputs; path-bearing expectations should use native path syntax instead of hard-coded `/`.
- If `gofmt` is unavailable on Windows, use `go fmt`; restore the checkout's CRLF line endings afterward so unrelated package files do not appear changed.
- If an open-ended template field can be answered `None.`, declare `none_ok` in its schema; a placeholder is still checked as an answer.
- Move local tickets through their lifecycle: `work_tickets.py move` rejects a direct `todo` to `done` transition; move a worked ticket to `held` first.
- When changing session titles, follow every consumer, including retro cost attribution, not just
  fleet discovery. New sessions use the new scheme; historical evidence still needs to attribute
  sessions recorded under earlier titles.
- On a Windows checkout, the plugin build tolerates CRLF, but its byte-for-byte tests require
  canonical generator output. Regenerate those bytes from `se_plugin.expected()` before those
  checks rather than changing the generator or weakening the tests to hide checkout conversion.
- Check the publication path before working without a work issue: `work_tickets.py push` requires
  an intake snapshot even when the person authorized issue-free work. For such an authorized fix,
  push with `git push` and the hooks active (the pre-push public check still runs) and open the
  pull request with `gh pr create`; never invent an issue snapshot or push with `--no-verify`.
- Prefer `work_tickets.py guard` when checking a report's removed tests and prose, rather than
  composing long inline probes. If introspection is necessary, read the helper's actual name
  first: the test-removal helper is `deleted_test_places`, not `deleted_tests`.
