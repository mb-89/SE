"""The fake behind the process door (scripts/process_door.py): every program a test's code runs, answered in-process.

Reader: whoever writes a test whose code under test runs a program (`gh`, a project's suite or build
command, one of SE's scripts or hooks), or changes the door.

A test takes the `fake_processes` fixture (tests/conftest.py), which installs a `FakeProcesses`
behind the door for the test. Each program the code under test runs is answered by the first
handler that matches it, and none starts a process:

- a script of SE (`python <se>/scripts/<name>.py ...`, also through `uv run ... python`) by its
  `main(argv)`, imported and called in this process with the call's working directory,
  environment, standard input and output (`run_main`), on by default;
- se's git hooks (`.githooks/pre-commit`, `commit-msg`, `pre-push`), which the fake git runs on a
  commit or push, by their logic in-process (`HOOKS`): the shell around se's scripts, written out;
- anything else by what the test hands `on(<program>, <handler>)`: `gh` by its answers, a suite
  command by a function. A handler takes the `Invocation` and answers an `Answer`, a
  `CompletedProcess`, an exit code or the standard output.

The shell door (scripts/shell_door.py) has a fake of this class of its own, without SE's scripts
and hooks (the `fake_shell` fixture), which answers each shell by the test's handlers only.

A program no handler answers fails the test, naming the command and the remedy; a test failure,
so no `except OSError` of the code under test swallows it. `calls` records every invocation.

`tests/test_process_door.py` holds this fake to the real door: the same `CompletedProcess` for
text and bytes, input, exit codes and `check`.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OWNER = "tests/fake_processes.py"


@dataclass(frozen=True)
class Invocation:
    """One program the code under test ran, as it asked the door."""

    argv: list[str] | str
    options: dict[str, Any]

    @property
    def words(self) -> list[str]:
        return self.argv.split() if isinstance(self.argv, str) else list(self.argv)

    @property
    def cwd(self) -> Path | None:
        cwd = self.options.get("cwd")
        return Path(cwd) if cwd is not None else None

    @property
    def env(self) -> dict[str, str] | None:
        return self.options.get("env")

    @property
    def stdin(self) -> bytes:
        given = self.options.get("input")
        if given is None:
            return b""
        return given.encode("utf-8") if isinstance(given, str) else bytes(given)

    @property
    def script(self) -> Path | None:
        """The Python script this runs (`python <script>.py ...`, `uv run ... python <script>.py`), if any."""
        words = self.words
        if not words or not (python(words[0]) or Path(words[0]).name in ("uv", "uv.exe")):
            return None
        script = next((Path(word) for word in words[1:] if word.endswith(".py")), None)
        if script is not None and not script.is_absolute() and self.cwd is not None:
            return self.cwd / script  # as the child resolves it, from its own working directory
        return script

    @property
    def arguments(self) -> list[str]:
        """The arguments after the script, or after the program where it runs none."""
        words = self.words
        script = self.script
        if script is None:
            return words[1:]
        return words[next(index for index, word in enumerate(words) if word.endswith(".py")) + 1:]

    def text(self) -> str:
        return " ".join(self.words)


@dataclass
class Answer:
    """What a fake program answers: its exit code and output, text or bytes."""

    returncode: int = 0
    stdout: str | bytes = ""
    stderr: str | bytes = ""


Handler = Callable[[Invocation], "Answer | subprocess.CompletedProcess | int | str | None"]


def python(program: str) -> bool:
    name = Path(program).name.lower().removesuffix(".exe")
    return name.startswith("python") or program == sys.executable


def program_name(invocation: Invocation) -> str:
    """The name a handler matches: the script's file name where the call runs a script, else the
    program's name without `.exe`, `.cmd` or `.bat`."""
    if invocation.script is not None:
        return invocation.script.name
    words = invocation.words
    name = Path(words[0]).name if words else ""
    for suffix in (".exe", ".cmd", ".bat"):
        name = name.removesuffix(suffix)
    return name


_lock = threading.RLock()


@contextlib.contextmanager
def child_context(invocation: Invocation) -> Iterator[tuple[io.TextIOWrapper, io.TextIOWrapper]]:
    """This process set up as the child would be: its working directory, environment, standard
    input and output, restored after. One at a time, as they are the process's."""
    with _lock:
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace", write_through=True)
        err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace", write_through=True)
        given = io.TextIOWrapper(io.BytesIO(invocation.stdin), encoding="utf-8", errors="replace")
        saved = (os.getcwd(), dict(os.environ), sys.stdin, sys.stdout, sys.stderr, list(sys.argv))
        try:
            if invocation.cwd is not None:
                os.chdir(invocation.cwd)
            if invocation.env is not None:
                os.environ.clear()
                os.environ.update(invocation.env)
            sys.stdin, sys.stdout, sys.stderr = given, out, err
            yield out, err
        finally:
            out.flush()
            err.flush()
            cwd, environment, sys.stdin, sys.stdout, sys.stderr, sys.argv[:] = saved
            os.chdir(cwd)
            if dict(os.environ) != environment:
                os.environ.clear()
                os.environ.update(environment)


def exit_code(code: object) -> int:
    """The exit code a `main` return value or `SystemExit` code makes, as the interpreter does."""
    if code is None:
        return 0
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def run_main(main: Callable[..., object], invocation: Invocation, name: str = "") -> Answer:
    """`main(arguments)` called in this process as the child would run it (`child_context`), its
    exit code and output answered."""
    with child_context(invocation) as (out, err):
        sys.argv[:] = [name or program_name(invocation), *invocation.arguments]
        try:
            code = exit_code(main(invocation.arguments))
        except SystemExit as stop:
            code = exit_code(stop.code)
        return Answer(code, out.buffer.getvalue(), err.buffer.getvalue())


def script_main(path: Path) -> Callable[..., object]:
    """The `main` of SE's script at `path`, imported as the module of its name."""
    if path.resolve().parent != SCRIPTS.resolve():
        pytest.fail(f"{OWNER}: the script {path} is not one of SE's scripts ({SCRIPTS}); answer it with "
                    "fake_processes.on(<name>, <handler>)", pytrace=False)
    module = importlib.import_module(path.stem)
    main = getattr(module, "main", None)
    if main is None:
        pytest.fail(f"{OWNER}: scripts/{path.name} has no main(argv) to run in-process; give it one", pytrace=False)
    return main


def run_script(invocation: Invocation) -> Answer:
    """A Python script that is none of SE's, such as one a test planted as a project's command, run
    as `python <script>` would run it, in this process (`run_main`): for `on(<its name>, run_script)`."""
    import runpy

    path = invocation.script
    if path is None:
        pytest.fail(f"{OWNER}: run_script answers `python <script>.py` only, not `{invocation.text()}`", pytrace=False)
    def main(_arguments: list[str]) -> None:  # one that runs to its end exits 0, as under the interpreter
        runpy.run_path(str(path), run_name="__main__")
    return run_main(main, invocation, path.name)


def se_script(invocation: Invocation) -> Answer:
    return run_main(script_main(invocation.script), invocation)


# se's git hooks (.githooks), their shell written out in-process: each runs se's scripts by their main.
def hook_script(name: str, arguments: list[str], invocation: Invocation, stdin: bytes = b"") -> Answer:
    call = Invocation([sys.executable, str(SCRIPTS / name), *arguments],
                      {**invocation.options, "input": stdin})
    return se_script(call)


def joined(*answers: Answer) -> Answer:
    def text(value: str | bytes) -> bytes:
        return value.encode("utf-8") if isinstance(value, str) else value
    return Answer(answers[-1].returncode, b"".join(text(answer.stdout) for answer in answers),
                  b"".join(text(answer.stderr) for answer in answers))


def pre_commit(invocation: Invocation) -> Answer:
    check = hook_script("public_check.py", ["--staged"], invocation)
    if check.returncode:
        return check
    return joined(check, hook_script("commit_checks.py", [], invocation))


def commit_msg(invocation: Invocation) -> Answer:
    return hook_script("public_check.py", ["--message-file", invocation.arguments[0]], invocation)


def pre_push(invocation: Invocation) -> Answer:
    import git_door

    remote = invocation.arguments[0]
    held = [] if any(space in remote for space in " \t\n") else ["--not", f"--remotes={remote}"]
    answers, status = [Answer()], 0
    for line in invocation.stdin.decode("utf-8").splitlines():
        words = line.split()
        if len(words) != 4:
            continue
        _local_ref, local_sha, remote_ref, remote_sha = words
        if not local_sha.strip("0"):
            continue  # branch deletion
        known = remote_sha.strip("0") and git_door.run(
            "cat-file", "-e", f"{remote_sha}^{{commit}}", cwd=invocation.cwd).returncode == 0
        commits = f"{remote_sha}..{local_sha}" if known else local_sha
        range_text = " ".join([commits, *held])
        for answer in (hook_script("public_check.py", ["--rev", local_sha, "--remote", remote, "--range", range_text],
                                   invocation),
                       hook_script("work_tickets.py", ["verified", remote_ref, local_sha], invocation)):
            answers.append(answer)
            status = status or (1 if answer.returncode else 0)
    result = joined(*answers)
    result.returncode = status
    return result


HOOKS: dict[str, Handler] = {"pre-commit": pre_commit, "commit-msg": commit_msg, "pre-push": pre_push}


def se_hook(invocation: Invocation) -> Path | None:
    """The se hook this runs (a file of a `.githooks` folder beside `se-script`), if any; through
    the shell git ships on Windows too."""
    for word in invocation.words[:2]:
        path = Path(word)
        if path.name in HOOKS and (path.parent / "se-script").is_file():
            return path
    return None


@dataclass
class FakeProcesses:
    """The door's fake for one test: handlers by program name, SE's scripts and hooks in-process."""

    scripts: bool = True
    hooks: bool = True
    handlers: list[tuple[str | Callable[[Invocation], bool], Handler]] = field(default_factory=list)
    calls: list[Invocation] = field(default_factory=list)

    def on(self, program: str | Callable[[Invocation], bool], handler: Handler) -> FakeProcesses:
        """Answer `program` (its name as `program_name` reads it, or a test of the invocation) with
        `handler`; a later handler for the same program wins."""
        self.handlers.insert(0, (program, handler))
        return self

    def handler(self, invocation: Invocation) -> Handler | None:
        name = program_name(invocation)
        for program, handler in self.handlers:
            if (program == name) if isinstance(program, str) else program(invocation):
                return handler
        hook = se_hook(invocation) if self.hooks else None
        if hook is not None:
            return HOOKS[hook.name]
        if self.scripts and invocation.script is not None and invocation.script.resolve().parent == SCRIPTS.resolve():
            return se_script
        return None

    def run(self, argv: list[str] | str, options: dict[str, Any]) -> subprocess.CompletedProcess:
        invocation = Invocation(argv, dict(options))
        self.calls.append(invocation)
        handler = self.handler(invocation)
        if handler is None:
            pytest.fail(f"{OWNER}: no fake answers `{invocation.text()}`; give the test's fake_processes a handler "
                        f"(fake_processes.on({program_name(invocation)!r}, <handler>)), as {OWNER} says", pytrace=False)
        return completed(invocation, answer_of(handler(invocation)))


def answer_of(value) -> Answer:
    if isinstance(value, Answer):
        return value
    if isinstance(value, subprocess.CompletedProcess):
        return Answer(value.returncode, value.stdout or "", value.stderr or "")
    if isinstance(value, bool) or value is None:
        return Answer(0 if value in (None, True) else 1)
    if isinstance(value, int):
        return Answer(value)
    return Answer(0, value)


def completed(invocation: Invocation, answer: Answer) -> subprocess.CompletedProcess:
    """`answer` as `subprocess.run` returns it for the call's options: text or bytes, captured or
    written to this process's standard output, and `check` raising."""
    options = invocation.options
    text = bool(options.get("text") or options.get("universal_newlines") or options.get("encoding")
                or options.get("errors"))
    encoding = options.get("encoding") or "utf-8"

    def shaped(value: str | bytes) -> str | bytes:
        data = value.encode("utf-8") if isinstance(value, str) else value
        return data.decode(encoding, options.get("errors") or "strict").replace("\r\n", "\n") if text else data

    captured = options.get("capture_output")
    stdout = shaped(answer.stdout) if captured or options.get("stdout") == subprocess.PIPE else None
    stderr = shaped(answer.stderr) if captured or options.get("stderr") == subprocess.PIPE else None
    if options.get("stderr") == subprocess.STDOUT and stdout is not None:
        stdout = stdout + shaped(answer.stderr)
    for value, captured_value, stream in ((answer.stdout, stdout, sys.stdout), (answer.stderr, stderr, sys.stderr)):
        if captured_value is None and value and options.get("stdout" if stream is sys.stdout else "stderr") \
                not in (subprocess.DEVNULL, subprocess.STDOUT):
            stream.write(value.decode("utf-8", "replace") if isinstance(value, bytes) else value)
    result = subprocess.CompletedProcess(invocation.argv, answer.returncode, stdout, stderr)
    if options.get("check") and answer.returncode:
        raise subprocess.CalledProcessError(answer.returncode, invocation.argv, stdout, stderr)
    return result
