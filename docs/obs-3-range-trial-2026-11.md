# Moving SE to obs 3: trial of 16 Nov 2026

SE runs on obs 2.1.8. This trial ran SE once on obs 3.9.0, the newest obs 3 release, and once on
2.1.8, on the same copy of main, one run after the other. SE itself stays on 2.1.8; whether it
moves is your decision.

## The two runs

| check | obs 2.1.8 | obs 3.9.0 |
|---|---|---|
| complete suite | 2373 passed, 0 failed, 40 skipped | 2372 passed, 1 failed, 40 skipped |
| suite time (target 60 s, limit 120 s) | 53.3 s | 58.0 s |
| documentation page build | builds | refused with one warning |
| deck, story, docs and recorded-output tests | 94 passed | 93 passed, 1 failed |
| decision deck against its recording | matches | matches |

Both suites stay under the 60 s target. The 40 skipped tests are the same on both versions.

## What breaks on obs 3

One break, seen twice: the documentation page. Nothing else differs between the two runs.

- **Test:** `tests/test_docs.py::test_documentation_builds_without_warnings`, and the same build
  run by hand (`scripts/build_docs.py`).
- **First error line:** `html: Warning: obs-html artifact: artifact-data notes[1].html: carries
  provenance (timestamp).`
- **Cause:** obs 3.3.0 added a check that warns when a page carries what looks like the time it
  was built: a date followed by a time of day. SE's page refuses any warning.
- **Where:** README.md, the example output of `work_tickets.py metrics`, whose last line starts
  `2026-11-10T09:00:00Z`. It is an example, not a build time, but it has that shape.
- **Smallest change:** in that README example, write the date alone (`2026-11-10 work_tickets.py
  integrate ...`). With that one line changed, the page builds on obs 3.9.0 without a warning.

No break shows on both versions, so nothing here predates the move.

## New obs options that change SE's pages

None. obs 3 adds four page options, and each is off unless a build turns it on; SE's builds turn
none on, so the docs page, the decision decks and the story pages look as they do today.

- The decision figure's own verdict (`decisionVerdict`): off. The decision deck still matches its
  recording.
- A banner for hosts that cannot run the page, a note for agents reading the page, and refusing a
  page instead of warning about it: all off.

## obs's release history, confirmed

- From 2.1.8 to 3.0.0 is one commit, d38d05d, marked as a major release. It changes only three
  workflows, AGENTS.md, se.toml and se.lock: obs's own way of working, not what it builds.
- After 3.0.0 no release is major: 29 releases up to 3.9.0, 9 minor and 20 patch.
- What SE gains: the computed verdict of a decision (e9cf15b, first in 3.2.0), the verdict printed
  as text (c3447fe, 3.4.0) and the skill that teaches an agent obs's notes (f8a6c8c, 3.5.0). The
  commits name no obs issue numbers, so those three numbers are not confirmed from obs's history.

Mechanical move: yes, 1 break (one README example line).
