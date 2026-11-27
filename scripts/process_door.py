# se:template se/python-module 1.0.0
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

A program that runs beside SE while SE talks to it or leaves it running (a server spoken to over
its standard streams, a detached session) starts through `start`, which takes `subprocess.Popen`'s
arguments and answers its `Popen`; the fake starts none, so a test that needs one is a contract or
entry-point test. A shell never starts this way: it runs through the shell door.

The door adds nothing to what the program is asked: `run` takes `subprocess.run`'s arguments and
answers its `CompletedProcess`, each caller keeping its own error type and message. Its
declaration, `scripts/doors/process.toml`, makes every other start a reach `door_report.py` refuses.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Any, Protocol

import se_script
import shell_door


class Backend(Protocol):
    """What runs one program: the real one, or a fake held to the same contract."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess: ...

    def start(self, argv: list[str], options: dict[str, Any]) -> subprocess.Popen: ...


class RealProcesses:
    """The program itself, as a child process (`subprocess.run`)."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, **options)

    def start(self, argv: list[str], options: dict[str, Any]) -> subprocess.Popen:
        return subprocess.Popen(argv, **options)


BACKEND: Backend = RealProcesses()


def use(backend: Backend) -> AbstractContextManager[Backend]:
    """Run every program through `backend` for the block (a test's fake), then restore."""
    return se_script.swapped(sys.modules[__name__], "BACKEND", backend)


def run(argv: Sequence[str] | str, **options: Any) -> subprocess.CompletedProcess:
    """Run `argv` as `subprocess.run(argv, **options)` would, through the door's backend; a shell
    runs through the shell door instead."""
    if shell_door.is_shell(argv, bool(options.get("shell"))):
        return shell_door.run(argv, **options)
    return BACKEND.run(argv if isinstance(argv, str) else [str(word) for word in argv], options)


def start(argv: Sequence[str], **options: Any) -> subprocess.Popen:
    """Start `argv` as `subprocess.Popen(argv, **options)` would, through the door's backend, and
    answer the running process; a shell is refused, as it runs through the shell door's `run`."""
    if shell_door.is_shell(argv, bool(options.get("shell"))):
        raise ValueError(f"process_door.start: {' '.join(map(str, argv))!r} starts a shell; "
                         "run it through shell_door.run")
    return BACKEND.start([str(word) for word in argv], options)
