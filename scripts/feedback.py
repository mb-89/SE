"""Feedback within a second: the time budgets of the `work_tickets.py` and `se_start.py` commands,
declared once here, and what keeps a slow command from reading as hung (README "Feedback budgets").

- Every subcommand prints its first line within `FIRST_LINE_SECONDS`: `watched` prints one for a
  run that has shown nothing by half of it.
- The interactive commands (`INTERACTIVE`) finish within their budget; `metrics.recorded` notes it
  as the run's `budget_seconds`, so `work_tickets.py metrics` flags each overrun.
- The long commands (`PHASED`) announce each phase as it starts (`phase`).
- A call to GitHub or to a remote prints what it reads before it is made (`reading`), so a slow
  reply is never silent.

Progress goes to stderr, flushed, so what a command prints on stdout (JSON, a description) stays
as it was.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager

FIRST_LINE_SECONDS = 1.0  # every subcommand prints its first line within it
INTERACTIVE_SECONDS = 5.0  # an interactive command finishes within it
INTERACTIVE = {  # command -> the seconds it may take
    "work_tickets.py status": INTERACTIVE_SECONDS,
    "work_tickets.py queue": INTERACTIVE_SECONDS,
    "work_tickets.py intake": INTERACTIVE_SECONDS,
    "work_tickets.py metrics": INTERACTIVE_SECONDS,
    "work_tickets.py paused": INTERACTIVE_SECONDS,
    "se_start.py status": 1.0,  # the session's greeting: answers from disk and its cache
}
PHASED = ("work_tickets.py integrate", "work_tickets.py suite", "work_tickets.py refresh")
SHOWN_ARGUMENTS = 10  # a door line names at most this many words of the call
VALUE_OPTIONS = {"--json", "--jq", "--body-file", "--limit", "--template", "-q"}  # not shown


def budget(command: str) -> float | None:
    """The seconds `command` (`<script>.py <subcommand>`) may take, where it is interactive."""
    return INTERACTIVE.get(command)


def progress(text: str) -> None:
    """Print one progress line on stderr, at once."""
    print(text, file=sys.stderr, flush=True)


def phase(text: str) -> None:
    """Announce a phase of a long command as it starts."""
    progress(f"Phase: {text}")


def reading(what: str, arguments: list[str] | tuple[str, ...]) -> None:
    """Announce a call to `what` (`GitHub`, a remote) before it is made: the call's words, without
    the options that only shape its output or carry a body."""
    shown: list[str] = []
    hide = False
    for argument in arguments:
        if hide or argument in VALUE_OPTIONS:
            hide = not hide
            continue
        shown.append(argument)
    more = " ..." if len(shown) > SHOWN_ARGUMENTS else ""
    progress(f"Reading {what}: {' '.join(shown[:SHOWN_ARGUMENTS])}{more}")


class _Seen:
    """A stream that records that something was written to it."""

    def __init__(self, stream, seen: threading.Event) -> None:
        self._stream, self._seen = stream, seen

    def write(self, text: str) -> int:
        if text:
            self._seen.set()
        return self._stream.write(text)

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


@contextmanager
def watched(command: str) -> Iterator[None]:
    """Run the body with its first line due within `FIRST_LINE_SECONDS`: where it has written
    nothing to stdout or stderr by half of it, print that `command` is working."""
    seen = threading.Event()
    out, err = sys.stdout, sys.stderr
    for stream in (out, err):  # a line printed is a line shown, also through a pipe
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    sys.stdout, sys.stderr = _Seen(out, seen), _Seen(err, seen)

    def first_line() -> None:
        if not seen.wait(FIRST_LINE_SECONDS / 2):
            print(f"{command}: working, nothing to show yet", file=err, flush=True)

    watcher = threading.Thread(target=first_line, daemon=True)
    watcher.start()
    try:
        yield
    finally:
        seen.set()
        watcher.join()
        sys.stdout, sys.stderr = out, err
