## Learnings

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
