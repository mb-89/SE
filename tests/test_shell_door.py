"""The shell door's contract (scripts/shell_door.py): what SE's code relies on a shell to answer, held once against a
real shell and against the fake every other test gets (tests/fake_processes.py behind the `fake_shell` fixture).

The real side is one test, `test_the_real_shell_answers_as_its_fake`, the door's own contract:
it starts one `sh` per case. Every other case here runs in-process: what a shell is, the process
door handing a shell over and the shell door refusing a program that is none, the fake answering by the test's handlers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import fake_processes as fakes
import process_door
import shell_door

# Each case: the command line, the options the caller passes the door, and the exit code and
# output a shell answers it with.
CASES = {
    "text": ("printf 'out\\n'; printf 'err\\n' >&2; exit 3", {"capture_output": True, "text": True}, (3, "out\n", "err\n")),
    "bytes": ("printf 'out\\n'", {"capture_output": True}, (0, b"out\n", b"")),
    "input": ("cat; printf '!'", {"capture_output": True, "text": True, "input": "given"}, (0, "given!", "")),
    "merged": ("printf 'out\\n'; printf 'err\\n' >&2", {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                                                       "text": True}, (0, "out\nerr\n", None)),
}


@pytest.mark.spawns("contract: shell, the shell door's own contract: a real sh answers each case as the fake does")
@pytest.mark.skipif(shutil.which("sh") is None, reason="no sh on this machine's PATH")
@pytest.mark.parametrize("case", sorted(CASES))
def test_the_real_shell_answers_as_its_fake(case: str) -> None:
    line, options, (code, out, err) = CASES[case]
    real = shell_door.RealShell().run(["sh", "-c", line], {**options, "stdin": subprocess.DEVNULL}
                                       if "input" not in options else dict(options))
    fake = fakes.FakeProcesses(scripts=False, hooks=False).on("sh", lambda _invocation: fakes.Answer(
        code, out, err if err is not None else ""))
    with shell_door.use(fake):
        answered = shell_door.run(["sh", "-c", line], **options)
    assert (real.returncode, real.stdout, real.stderr) == (code, out, err)
    assert (answered.returncode, answered.stdout, answered.stderr) == (code, out, err)


@pytest.mark.parametrize("argv, shell", [
    ("echo hi", False),
    (["make", "docs"], True),
    (["sh", "RUNME.sh"], False),
    (["/bin/bash", "-c", "true"], False),
    ([r"C:\Program Files\Git\bin\bash.exe", "-lc", "true"], False),
    (["pwsh", "-NoProfile"], False),
    (["powershell.exe", "-File", "x.ps1"], False),
    (["cmd", "/c", "dir"], False),
    ([str(Path("scripts") / "bootstrap.sh"), "--hook"], False),
    ([Path("RUNME.ps1")], False),
])
def test_a_shell_is_a_command_line_a_shell_program_or_a_shell_script(argv, shell: bool) -> None:
    assert shell_door.is_shell(argv, shell)


@pytest.mark.parametrize("argv", [["make", "docs"], [sys.executable, "x.sh"], ["uv", "run", "python", "a.py"],
                                  ["gh", "api", "repos"], ["shellcheck", "x.sh"], []])
def test_no_other_program_is_a_shell(argv) -> None:
    assert not shell_door.is_shell(argv)


def test_the_process_door_hands_a_shell_to_the_shell_door(fake_shell: fakes.FakeProcesses,
                                                          fake_processes: fakes.FakeProcesses) -> None:
    fake_shell.on(lambda _invocation: True, lambda invocation: 5)
    for argv, options in ((["bash", "-c", "true"], {}), ("true", {"shell": True}), (["make", "docs"], {"shell": True}),
                          (["scripts/check.sh"], {})):
        assert process_door.run(argv, **options).returncode == 5
    assert [call.argv for call in fake_shell.calls] == [["bash", "-c", "true"], "true", ["make", "docs"],
                                                        ["scripts/check.sh"]]
    assert fake_processes.calls == []


def test_the_shell_door_refuses_a_program_that_is_no_shell_naming_the_process_door() -> None:
    with pytest.raises(ValueError, match="scripts/process_door.py"):
        shell_door.run(["make", "docs"])


def test_a_test_gets_the_fake_shell_which_answers_by_its_handlers(fake_shell: fakes.FakeProcesses,
                                                                 tmp_path: Path) -> None:
    fake_shell.on("sh", lambda invocation: f"ran {' '.join(invocation.arguments)} in {invocation.cwd.name}\n")
    result = shell_door.run(["sh", "RUNME.sh", "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.stdout == f"ran RUNME.sh --help in {tmp_path.name}\n"
    assert [call.words for call in fake_shell.calls] == [["sh", "RUNME.sh", "--help"]]
    fake_shell.on(lambda invocation: isinstance(invocation.argv, str), lambda invocation: 4)
    assert shell_door.run("make docs", shell=True).returncode == 4


def test_a_shell_no_handler_answers_fails_the_test_naming_it(fake_shell: fakes.FakeProcesses) -> None:
    with pytest.raises(pytest.fail.Exception, match=r"no fake answers `bash -c exit 9`"):
        shell_door.run(["bash", "-c", "exit 9"])


def test_the_guard_and_the_door_read_one_list_of_shells() -> None:
    import spawn_guard

    assert spawn_guard.shell_door.SHELLS == shell_door.SHELLS
    assert spawn_guard.shell_door.SCRIPT_SUFFIXES == shell_door.SCRIPT_SUFFIXES
    assert os.path.samefile(spawn_guard.shell_door.__file__, shell_door.__file__)
