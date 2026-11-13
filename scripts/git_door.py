#!/usr/bin/env python3
"""The one door to git: every git command SE runs goes through `run` (or `popen` for a stream).

The rule is the rule book's des-004, one door per outside thing, and tst-001, fakes that behave:
`tests/test_git_door.py` holds this door's contract and runs it against real git and against the
fake `tests/fake_git.py`; every other test that needs git uses the fake (`use`), and the suite
refuses real git behind this door to any test outside `tests/conftest.py`'s `REAL_GIT`. A git
subprocess outside this module fails `tests/test_repository.py`'s guard.

The door adds nothing to what git is asked: each caller keeps its own error type and message.

`SE_GIT_DOOR` picks the backend of a process the door starts in (`from_environment`), so a test
reaches the child processes it starts too: unset or `real`, the git on PATH; `fake:<state file>`,
the fake behind that file (tests/fake_git.py `StateFile`, whose format kern's Go door reads as
well); `refused`, which stops the process at its first git command, naming it.

As a command, `git_door.py <git arguments>` runs one git command through the door, its output and
exit code git's: the door for a shell that needs git (se's hooks, setup.sh, setup.ps1, the check
workflow's gate), so a test that hands them the fake reaches no real git.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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


VARIABLE = "SE_GIT_DOOR"


class RefusedGit:
    """A child process's backend under `SE_GIT_DOOR=refused`: its first git command ends it,
    naming the command and the remedy (a test that starts it gives it the fake)."""

    def refuse(self, argv: list[str]):
        raise SystemExit(f"git door: {VARIABLE}=refused, so this process may not run git "
                         f"(git {' '.join(argv)}); the test that started it sets {VARIABLE}=fake:<state file> "
                         "(the shared_fake_git fixture, tests/conftest.py)")

    def run(self, argv: list[str], **_) -> subprocess.CompletedProcess[bytes]:
        self.refuse(argv)

    def popen(self, argv: list[str], **_) -> subprocess.Popen:
        self.refuse(argv)


def from_environment(environment: dict[str, str] | os._Environ = os.environ) -> Backend:
    """The backend `SE_GIT_DOOR` names (the module docstring); any other value is refused."""
    value = environment.get(VARIABLE, "")
    kind, _, where = value.partition(":")
    if value in ("", "real"):
        return RealGit()
    if value == "refused":
        return RefusedGit()
    if kind == "fake" and where:
        return fake_backend(Path(where))
    raise SystemExit(f"git door: {VARIABLE}={value!r} is none of real, refused or fake:<state file>")


def fake_backend(state: Path) -> Backend:
    """The fake behind `state`, from the tests/fake_git.py that wrote it (only a test sets the
    variable; the door that reads it may be a copy of SE without tests, as the plugin's is)."""
    fake_git = sys.modules.get("fake_git")
    if fake_git is None:
        if not state.is_file():
            raise SystemExit(f"git door: {VARIABLE} names the state file {state}, which does not exist")
        module = Path(json.loads(state.read_text(encoding="utf-8"))["fake"])
        spec = importlib.util.spec_from_file_location("fake_git", module)
        fake_git = importlib.util.module_from_spec(spec)
        sys.modules["fake_git"] = fake_git
        spec.loader.exec_module(fake_git)
    return fake_git.StateFile(state)


if __name__ == "__main__":  # run as a command: the fake a state file loads imports this module
    sys.modules.setdefault("git_door", sys.modules[__name__])
BACKEND: Backend = from_environment()


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


def main(arguments: list[str] | None = None) -> int:
    """Run `git <arguments>` through the door; git's output and exit code are the command's."""
    done = run(*(sys.argv[1:] if arguments is None else arguments), binary=True)
    sys.stdout.buffer.write(done.stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(done.stderr)
    sys.stderr.buffer.flush()
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
