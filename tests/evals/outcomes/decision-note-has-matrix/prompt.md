---
schema_version: "1.0"
name: decision-note-has-matrix
description: A decision brought to the person is written as one note with its situation, its problem and a pugh fence, in that order.
tags: [decision]
runs: 3
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Read]
expected_outcome: One Write of a Markdown note holding "## Current situation", "## The problem" and a pugh fence, in that order.
---

I have to decide this one myself, so prepare it for me as a decision note and write it to
`decisions/settings-source.md`.

The question: our command-line tool reads its settings from a TOML file in the project
(`app.toml`). Several users asked to set the same values through environment variables instead,
for their CI runners. Should the tool keep one source, the file, or read both, and if both, which
one wins?

What the tools returned when this session started:

- `app.toml` holds eleven settings; three of them (`timeout`, `retries`, `log_level`) are the ones
  users ask to override.
- Issue 18 ("set log level in CI without editing app.toml") has six thumbs-up; issue 21 asks the
  same for `timeout`.
- The tool has no other settings source today.

This run has no shell and no GitHub tools; the facts above are all there is.
