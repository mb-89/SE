---
schema_version: "1.0"
name: catch-up-ends-the-turn
description: Catching up on a repository with nothing waiting for the person ends the turn with the sentence that says so.
tags: [catch-up]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: The reply summarizes the open work and says "No input needed from you right now".
---

Catch me up on this repository, then tell me whether you need anything from me.

This run has no shell and no GitHub tools. The repository's state is below, as the GitHub tools
and git returned it when this session started; treat it as current.

Handover (`HANDOVER.md` on `main`):

```markdown
# Handover

- Release 1.4.0 is out; nothing is pending for it.
- The integrator is running and lands delivered pull requests on its own.
- No decision is open with the person.
```

Open issues, as the GitHub tools returned them:

```json
[
  {"number": 31, "title": "feat/csv-export-20261114", "state": "open",
   "labels": ["work", "in-progress"], "assignees": [],
   "body": "Add a CSV export to the report command. Worker started; no comment since."},
  {"number": 32, "title": "docs/install-notes-20261114", "state": "open",
   "labels": ["work", "ready"], "assignees": [],
   "body": "Shorten the install notes in README.md."}
]
```

Open pull requests, as the GitHub tools returned them:

```json
[
  {"number": 33, "title": "feat/csv-export-20261114", "state": "open", "draft": false,
   "head": {"ref": "feat/csv-export-20261114"}, "base": {"ref": "main"},
   "body": "Fixes https://github.com/example/app/issues/31\n\n(field report, delivered)"}
]
```

No issue carries the label `escalated` or `se-person`, and no decision note is open.
