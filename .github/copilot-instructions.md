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
- Check the field-report draft gate before starting issue-free work: without an intake snapshot it
  refuses. Report that refusal rather than inventing a snapshot or bypassing the gate.
- Run focused tests with `-n 0` when another session is running the complete suite, unless testing
  xdist itself; the default worker count can start many processes and contend with its setup.
- Match a Windows executable's case-insensitive extension before looking up a fake process handler;
  a full path to `sh.EXE`, `python.exe` or `gh.CMD` must reach the same handler as its bare name.
- Run obs and its adapter through their in-process entry points in tests, with their git door faked;
  starting their real commands defeats the spawn guard even when their output is correctly asserted.
- When a test's fixture parameter changes, the removal guard can flag its unchanged name as
  deleted; list the name and say its assertions remain in the field report, then run the guard again.
- On Windows, create the isolated profile's `AppData\Local` before running PowerShell: a missing
  special folder makes its module cache relative to the working directory even when `LOCALAPPDATA`
  is set. Keep the matching roaming and local environment paths in the child's own profile.
- A byte-stable recording and any note hashed by bytes need LF in `.gitattributes`; Windows checkout
  conversion otherwise changes every recorded line or the note's bless version.
- Before a focused `uv run --no-sync` in a fresh worktree, check that its environment contains the
  test dependencies; an empty environment cannot run pytest without a normal sync first.
- PowerShell's `$HOME` is read-only: use a different local variable for a test profile path.
- Leave tracked files unchanged while a focused test snapshots the checkout, just as for the
  complete suite; even a documentation edit during its build makes the snapshot assertion fail.
- Batch authored-content reads when a field-report guard checks a whole tree; one `git show` per
  tracked path exceeded the delivery timebox. Wrong: start one Git process per file; right: list
  the matching blobs once and read them with `git cat-file --batch`.
- A default argument binds a module constant when the function is defined, so a test that
  monkeypatches the constant does not reach it; write `limit=None` and `limit or CONSTANT`
  in the body.
- A refusal names its cause and the one command that removes it (`retro.py file <n>`,
  `retro.py collect <n>`, the sync of a lagging mirror); a refusal that only says "no" costs
  a round trip to SE and was read as a gate to respect.
- Origin may be a mirror that lags another remote: an "is SE current" check that reads only
  origin's tags reports current while a newer release exists; read the other remotes too.
- When inserting a test above another with the edit tool, end `new_str` with the following
  test's `def` line intact; dropping it silently merges two tests.
- A fixing-command hint is not an end-to-end fix: test the person's next action through the gate,
  closure and read-back in one call. Keep approval separate from later finding outcomes.
- Freeze effective template fields, nested templates and rule settings, not just a version label.
  Reopening or an explicit version bump starts a new input phase; a routine check never does.
- Store a file's frozen-input metadata in front matter, not a long comment in its body: downstream
  document builders lint body paragraphs and must not render template guidance.
- A legacy document without saved inputs must not be stamped with today's schema under its older
  version: resolve that version first, or preserve the legacy record and its explicit diagnostic.
- Find existing test filenames before selecting a runner command; names inferred from the feature
  can miss the real suite. Run slow obs-backed files separately to respect a command's timebox.
- A rule book entry states its rule in one sentence; put its mechanism and examples under
  Implementations rather than adding sentences to the rule itself.
- Separate pytest invocations that use the same obs setup lock are not independent; run them
  serially instead of turning setup contention into repeated three-minute timeouts.
- Compare a frozen template's effective fields and version in round-trip tests, not its source
  path or worked examples: those are deliberately not portable acceptance inputs.
- Privacy regression fixtures construct generic forbidden paths from components; a literal full
  profile path in tracked test source is itself rejected by the public check.
- Read a maintenance generator's entry point before passing `--help`: a script without an argument
  parser may regenerate unconditionally rather than display usage.
- Upward delivery notices obey the same recipient-status rule as orders: steer a running chat,
  queue otherwise, retry `cannotSteer` with the identical queued message, and verify once.
- When a requested guidance change replaces a protected sentence, update its existing assertion
  to enforce the new rule and retained safeguards, rather than leaving the old rule in the test.
- Deliver local decks as standalone HTML through an absolute-path Markdown link, never a
  background server; accept chat verdicts and do not assume a local Send saves answers.
- Use roles, never personal names, in decision notes and tracked or public output; private
  names belong only in the ignored local scan list, never a committed example or term list.
- A timeboxed full-tree report guard is incomplete, not passed; targeted introspection can
  inventory replaced text but cannot stand in for the acceptance check.
