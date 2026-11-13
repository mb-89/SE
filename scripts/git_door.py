#!/usr/bin/env python3
"""The one door to git: every git command SE runs goes through `run` (or `popen` for a stream).

The rule is the rule book's des-004, one door per outside thing, and tst-001, fakes that behave:
`tests/test_git_door.py` holds this door's contract and runs it against real git and against the
fake `tests/fake_git.py`; every other test that needs git uses the fake (`use`), and the suite
refuses real git behind this door to any test outside `tests/conftest.py`'s `REAL_GIT`. A git
subprocess outside this module fails `tests/test_repository.py`'s guard.

The door adds nothing to what git is asked: each caller keeps its own error type and message.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol


class Backend(Protocol):
    """What runs one git command: real git, or a fake held to the same contract."""

    def run(self, argv: list[str], *, cwd: Path | None, env: dict[str, str] | None,
            stdin: bytes | None, timeout: float | None) -> subprocess.CompletedProcess[bytes]: ...


class RealGit:
    """The git on PATH; `env` (variable -> value, None removes it) is laid over the process's
    environment, so a contract run can isolate git from the machine's configuration. What a call
    sets itself, differing from the process's environment, wins."""

    def __init__(self, env: dict[str, str | None] | None = None) -> None:
        self.env = env or {}

    def environment(self, env: dict[str, str] | None) -> dict[str, str] | None:
        if not self.env:
            return env
        merged = dict(os.environ if env is None else env)
        for name, value in self.env.items():
            if env is not None and name in env and env[name] != os.environ.get(name):
                continue
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        return merged

    def run(self, argv: list[str], *, cwd: Path | None, env: dict[str, str] | None,
            stdin: bytes | None, timeout: float | None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", *argv], cwd=cwd, env=self.environment(env), input=stdin,
                              capture_output=True, check=False, timeout=timeout)

    def popen(self, argv: list[str], *, env: dict[str, str] | None,
              **options) -> subprocess.Popen:
        return subprocess.Popen(["git", *argv], env=self.environment(env), **options)


BACKEND: Backend = RealGit()


@contextmanager
def use(backend: Backend) -> Iterator[Backend]:
    """Run every git command through `backend` for the block (a test's fake), then restore."""
    global BACKEND
    previous, BACKEND = BACKEND, backend
    try:
        yield backend
    finally:
        BACKEND = previous


def argv(arguments: tuple[str, ...], root: Path | str | None) -> list[str]:
    return (["-C", str(root)] if root is not None else []) + list(arguments)


def run(*arguments: str, root: Path | str | None = None, cwd: Path | None = None,
        env: dict[str, str] | None = None, stdin: bytes | None = None, binary: bool = False,
        no_prompt: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
    """`git [-C root] <arguments>`, its output captured, never raising on git's exit code.

    `binary` keeps stdout and stderr as bytes; otherwise both are UTF-8 text, undecodable bytes
    replaced. `no_prompt` stops git from asking for credentials (GIT_TERMINAL_PROMPT=0). A
    `timeout` raises subprocess.TimeoutExpired, as subprocess.run does."""
    if no_prompt:
        env = {**(os.environ if env is None else env), "GIT_TERMINAL_PROMPT": "0"}
    done = BACKEND.run(argv(arguments, root), cwd=cwd, env=env, stdin=stdin, timeout=timeout)
    if binary:
        return done
    return subprocess.CompletedProcess(done.args, done.returncode, text(done.stdout), text(done.stderr))


def text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data if isinstance(data, str) else data.decode("utf-8", "replace")


def popen(*arguments: str, root: Path | str | None = None, env: dict[str, str] | None = None,
          **options) -> subprocess.Popen:
    """`git [-C root] <arguments>` as a running process, for a stream (fast-export into
    fast-import); `options` go to subprocess.Popen. Only real git streams."""
    return BACKEND.popen(argv(arguments, root), env=env, **options)


def push(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """`git -C root push <arguments>`; the caller judges the refusal."""
    return run("push", *arguments, root=root)


# The identity git commits with


def identity_environment(identity: tuple[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment that makes a git commit carry `identity` as author and committer, whatever
    the clone's configuration or the environment's own GIT_AUTHOR_* and GIT_COMMITTER_* say."""
    name, email = identity
    return {**(os.environ if base is None else base), "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}


def set_identity(root: Path, identity: tuple[str, str]) -> subprocess.CompletedProcess[str] | None:
    """Set the checkout's user.name and user.email; the first failed `git config`, or None."""
    for key, value in zip(("user.name", "user.email"), identity):
        configured = run("config", key, value, root=root)
        if configured.returncode != 0:
            return configured
    return None

