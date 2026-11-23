"""The process door's contract (scripts/process_door.py): what SE's code relies on a child process to answer, held once
against a real process and against the fake tests/fake_processes.py, which every other test uses.

The real side of each case is the door's one contract test: it starts one Python child for all
its cases (`real_answers`, a module fixture), so the contract costs one process however many
cases it holds.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import fake_processes as fakes
import process_door

# Each case: the child's exit code, its standard output and error (it echoes its input to its
# output after its text), and the options the caller passes the door.
CASES = {
    "text": (0, "out\n", "", {"capture_output": True, "text": True}),
    "bytes": (0, "out\n", "err\n", {"capture_output": True}),
    "encoding": (3, "ö\n", "", {"capture_output": True, "encoding": "utf-8", "errors": "replace"}),
    "input": (0, "out\n", "", {"capture_output": True, "text": True, "input": "given"}),
    "stdout only": (0, "out\n", "err\n", {"stdout": subprocess.PIPE, "text": True}),
    "merged": (0, "out\n", "err\n", {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True}),
}

CHILD = """\
import json, sys
cases = json.loads(sys.argv[1])
results = {}
import subprocess
for name, (code, out, err, options) in cases.items():
    program = ("import sys\\n"
               f"sys.stdout.write({out!r} + sys.stdin.read()); sys.stdout.flush()\\n"
               f"sys.stderr.write({err!r}); sys.exit({code})")
    options = {key: (subprocess.PIPE if value == "PIPE" else subprocess.STDOUT if value == "STDOUT" else value)
               for key, value in options.items()}
    if "input" not in options:
        options["stdin"] = subprocess.DEVNULL
    result = subprocess.run([sys.executable, "-c", program], **options)
    shown = lambda value: value if value is None or isinstance(value, str) else ["bytes", value.decode()]
    results[name] = [result.returncode, shown(result.stdout), shown(result.stderr)]
print(json.dumps(results))
"""


def portable(options: dict) -> dict:
    return {key: ("PIPE" if value == subprocess.PIPE else "STDOUT" if value == subprocess.STDOUT else value)
            for key, value in options.items()}


def shown(value):
    return value if value is None or isinstance(value, str) else ["bytes", value.decode()]


@pytest.fixture(scope="module")
def real_answers() -> dict[str, list]:
    """Each case as the real door answers it: one child process runs them all, each through
    `subprocess.run` as `RealProcesses` does (its children start inside that one process)."""
    cases = {name: [code, out, err, portable(options)] for name, (code, out, err, options) in CASES.items()}
    with process_door.use(process_door.RealProcesses()):
        result = process_door.run([sys.executable, "-c", CHILD, json.dumps(cases)], capture_output=True,
                                  text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


@pytest.mark.spawns("contract: processes, the door's one real child")
@pytest.mark.parametrize("name", list(CASES))
def test_the_fake_answers_as_the_real_door(name: str, real_answers, capfd) -> None:
    code, out, err, options = CASES[name]
    fake = fakes.FakeProcesses().on(
        "child", lambda call: fakes.Answer(code, out + call.stdin.decode(), err))
    result = fake.run(["child"], dict(options))
    assert [result.returncode, shown(result.stdout), shown(result.stderr)] == real_answers[name]


def test_check_raises_as_subprocess_does() -> None:
    fake = fakes.FakeProcesses().on("child", lambda call: 2)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        fake.run(["child"], {"check": True, "capture_output": True})
    assert raised.value.returncode == 2


def test_a_script_of_se_runs_in_process_by_its_main(tmp_path: Path, monkeypatch, fake_processes) -> None:
    import se_home

    seen: list[tuple[list[str], str, str]] = []

    def main(argv):
        import os
        seen.append((argv, os.getcwd(), os.environ.get("PROBE", "")))
        print("printed")
        raise SystemExit(4)

    monkeypatch.setattr(se_home, "main", main, raising=False)
    script = fakes.SCRIPTS / "se_home.py"
    result = process_door.run([sys.executable, str(script), "a", "b"], cwd=tmp_path, env={"PROBE": "x"},
                              capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (4, "printed\n")
    assert seen == [(["a", "b"], str(tmp_path), "x")]
    assert fake_processes.calls[-1].arguments == ["a", "b"]


def test_a_program_no_handler_answers_fails_the_test_naming_it(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_planted=f"""\
        import sys
        sys.path[:0] = [{str(Path(__file__).parent)!r}, {str(Path(__file__).parents[1] / 'scripts')!r}]
        import fake_processes, process_door

        def test_runs_gh():
            with process_door.use(fake_processes.FakeProcesses()):
                try:
                    process_door.run(["gh", "pr", "list"], capture_output=True)
                except OSError:
                    pass
        """)
    result = pytester.runpytest_inprocess("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1)
    assert "no fake answers `gh pr list`" in result.stdout.str()
    assert "fake_processes.on('gh', <handler>)" in result.stdout.str()

