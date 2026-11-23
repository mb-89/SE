#!/usr/bin/env python3
"""The shell door: every shell SE's Python starts, `sh`, `bash`, PowerShell or a command line, starts through `run`.

The shell is a door, like git, gh and the network (the rule book's des-004, one door per outside
thing): product code reaches a shell only through this door, and a test never starts one. Only
the door's contract starts a real shell: `tests/test_shell_door.py`, which holds this door to its
fake. Every other test gets the fake behind this door (the `fake_shell`
fixture of tests/conftest.py, a tests/fake_processes.py `FakeProcesses` answering by the test's
handlers), and the spawn guard (scripts/spawn_guard.py) refuses a shell start in any test but
the door's contract (`contract: shell`) and a shell script's one entry-point test, naming the call.

What counts as a shell (`is_shell`): a command line (`shell=True`, a string command, `os.system`),
a program whose name is one of SHELLS (with or without `.exe`), or a shell script run as the
program itself (SCRIPT_SUFFIXES). The process door (scripts/process_door.py) hands each of them to
this door, so a command a project configures as a shell script passes through it too.

The door adds nothing to what the shell is asked: `run` takes `subprocess.run`'s arguments and
answers its `CompletedProcess`, each caller keeping its own error type and message.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import PurePath
from typing import Any, Protocol

#: The programs that are shells, by their name in lower case without `.exe`.
SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "fish", "pwsh", "powershell", "cmd"})
#: A script run as the program itself is a shell's: its interpreter line or Windows starts one.
SCRIPT_SUFFIXES = (".sh", ".bash", ".ps1")


def shell_program(program: object) -> bool:
    """Whether `program`, a command's first word, is a shell or a shell script."""
    text = os.fsdecode(program) if isinstance(program, (bytes, os.PathLike)) else str(program)
    name = PurePath(text.replace("\\", "/")).name.lower()
    return name.removesuffix(".exe") in SHELLS or name.endswith(SCRIPT_SUFFIXES)


def is_shell(argv: object, shell: bool = False) -> bool:
    """Whether running `argv` starts a shell: a command line (`shell`, or a string or bytes
    command), or a program `shell_program` names."""
    if shell or isinstance(argv, (str, bytes)):
        return True
    if isinstance(argv, os.PathLike):
        return shell_program(argv)
    words = list(argv)
    return bool(words) and shell_program(words[0])


class Backend(Protocol):
    """What runs one shell: the real one, or a fake held to the same contract."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess: ...


class RealShell:
    """The shell itself, as a child process (`subprocess.run`)."""

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, **options)


BACKEND: Backend = RealShell()


@contextmanager
def use(backend: Backend) -> Iterator[Backend]:
    """Run every shell through `backend` for the block (a test's fake), then restore."""
    global BACKEND
    previous, BACKEND = BACKEND, backend
    try:
        yield backend
    finally:
        BACKEND = previous


def run(argv: Sequence[str] | str, **options: Any) -> subprocess.CompletedProcess:
    """Run the shell `argv` as `subprocess.run(argv, **options)` would, through the door's backend;
    a command that starts no shell belongs to the process door and is refused."""
    if not is_shell(argv, bool(options.get("shell"))):
        raise ValueError(f"shell_door: {argv!r} starts no shell; run it through scripts/process_door.py")
    return BACKEND.run(argv if isinstance(argv, str) else [str(word) for word in argv], options)
