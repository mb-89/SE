---
name: test-paths-on-windows
description: 'How a new test builds and compares paths so the Windows leg of CI passes. Load it before writing a test that builds a path.'
---

A new test that builds a path builds it with `filepath` (Go) or `pathlib` (Python), and compares
paths as `filepath.ToSlash` or `as_posix` writes them, never as text with `/`. Only the Windows leg
of CI (`kern-platforms`) sees a path come back as `\work\tmp\...`, so a run on Linux never
catches it, and the landing fails.
