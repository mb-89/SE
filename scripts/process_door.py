#!/usr/bin/env python3
"""The one door to other programs: every program SE runs as a child process, git aside, starts through `run`.

The rule is the rule book's des-004, one door per outside thing, and tst-001, fakes that behave:
`tests/test_process_door.py` holds this door's contract and runs it against a real process and
against the fake `tests/fake_processes.py`; every other test hands the door that fake (`use`, the
`fake_processes` fixture of tests/conftest.py), which answers each program in-process: a script
of SE through its `main(argv)`, `gh` from the test's answers, a project's suite or build command
from a function the test gives. So the spawn guard (scripts/spawn_guard.py) counts no process
for them. git has its own door, scripts/git_door.py, and a shell its own, scripts/shell_door.py:
`run` hands a command that starts a shell (`shell_door.is_shell`), such as a project's suite or
commit check written as a shell script, to that door, so every shell passes through it.

The door adds nothing to what the program is asked: `run` takes `subprocess.run`'s arguments and
answers its `CompletedProcess`, each caller keeping its own error type and message.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol

import shell_door


class Backend(Protocol):
    """What runs one program: the real one, or a fake held to the same contract."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess: ...


class RealProcesses:
    """The program itself, as a child process (`subprocess.run`)."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, **options)


BACKEND: Backend = RealProcesses()


@contextmanager
def use(backend: Backend) -> Iterator[Backend]:
    """Run every program through `backend` for the block (a test's fake), then restore."""
    global BACKEND
    previous, BACKEND = BACKEND, backend
    try:
        yield backend
    finally:
        BACKEND = previous


def run(argv: Sequence[str] | str, **options: Any) -> subprocess.CompletedProcess:
    """Run `argv` as `subprocess.run(argv, **options)` would, through the door's backend; a shell
    runs through the shell door instead."""
    if shell_door.is_shell(argv, bool(options.get("shell"))):
        return shell_door.run(argv, **options)
    return BACKEND.run(argv if isinstance(argv, str) else [str(word) for word in argv], options)
