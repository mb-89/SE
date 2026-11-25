# Learnings

- Parse a command-line value from a sibling script through a lazy resolver, not while registering commands; eager import can re-enter a partially initialized module, especially when tests load scripts with `importlib`.
- Keep each GitHub plan step's action key aligned with the adapter map (`comment_issue`, `close_issue`); a custom step name without a matching action fails after the plan is built.
- Run `python -m py_compile` before invoking a command that imports changed Python modules; a syntax error otherwise prevents both the command and its tests from starting.
- In collection tests, set prior-issue comments on the fake door before calling `collect`; updating the fixture after collection does not exercise outcome-marker parsing.
- On Windows with `core.autocrlf=true`, inspect byte-comparison failures for CRLF-only differences before changing generated outputs; path-bearing expectations should use native path syntax instead of hard-coded `/`.
- If an open-ended template field can be answered `None.`, declare `none_ok` in its schema; a placeholder is still checked as an answer.
- Move local tickets through their lifecycle: `work_tickets.py move` rejects a direct `todo` to `done` transition; move a worked ticket to `held` first.
