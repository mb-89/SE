"""The spawn guard (scripts/spawn_guard.py): each test's process starts counted, an unmarked one refused.

Every case runs a planted suite in-process (pytester), its process starts handed to a fake, so
these tests start no process themselves.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import spawn_guard  # noqa: E402


class Started(Exception):
    """What the fake start raises in place of starting a process."""


@pytest.fixture
def no_starts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every start the guard wraps reaches this fake, which records its name and raises `Started`
    (a FileNotFoundError, as for a missing program), so no process starts."""
    calls: list[str] = []

    def fake(name: str):
        def start(*_arguments, **_options):
            calls.append(name)
            raise FileNotFoundError(f"fake start {name}")
        return start

    spawn_guard.install()
    for name in list(spawn_guard._original):
        monkeypatch.setitem(spawn_guard._original, name, fake(name))
    return calls


def run(pytester: pytest.Pytester, *arguments: str) -> pytest.RunResult:
    return pytester.runpytest_inprocess("-p", "no:cacheprovider", *arguments, plugins=[spawn_guard.SpawnGuard()])


GIT_TEST = """\
import subprocess

def test_runs_git(tmp_path):
    try:
        subprocess.run([str(tmp_path / "git"), "status", "--short"])
    except FileNotFoundError:
        pass
"""


def test_a_new_test_that_runs_git_is_refused_naming_the_call(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=GIT_TEST)
    result = run(pytester)
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "test_planted.py::test_runs_git started 1 process(es) in its call" in output, output
    assert "git status --short (test_planted.py:5)" in output, output
    assert "@pytest.mark.spawns" in output and "tests-spawn-no-processes" in output, output
    assert "spawns: 1 processes started by 1 of 1 tests; 0 in marked tests, 0 in baseline tests, 1 refused" in output
    assert no_starts == [spawn_guard.POPEN]


def test_a_marked_test_may_start_processes_and_is_counted(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="import pytest\n" + GIT_TEST.replace(
        "def test_runs_git", "@pytest.mark.spawns('contract: git')\ndef test_runs_git"))
    result = run(pytester)
    result.assert_outcomes(passed=1)
    assert "spawns: 1 processes started by 1 of 1 tests; 1 in marked tests" in result.stdout.str()


def test_a_mark_without_a_reason_fails(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="""\
        import pytest

        @pytest.mark.spawns()
        def test_quiet():
            pass
        """)
    result = run(pytester)
    result.assert_outcomes(failed=1)
    assert "carries @pytest.mark.spawns without a reason" in result.stdout.str()


@pytest.mark.parametrize("call, shown", [
    ("os.system('git status')", "shell: git status"),
    ("subprocess.run('git log -1', shell=True)", "shell: git log -1"),
    ("os.spawnv(os.P_WAIT, '/usr/bin/git', ['git', 'fetch'])", "git fetch"),
    ("os.execv('/usr/bin/git', ['git', 'push'])", "git push"),
])
def test_each_kind_of_start_is_counted_and_named(pytester: pytest.Pytester, no_starts, call: str, shown: str) -> None:
    if call.startswith(("os.spawnv", "os.execv")) and not hasattr(os, call[3:call.index("(")]):
        pytest.skip(f"{call} is not on this platform")
    pytester.makepyfile(test_planted=f"import os\nimport subprocess\n\ndef test_starts():\n    try:\n"
                                     f"        {call}\n    except FileNotFoundError:\n        pass\n")
    result = run(pytester)
    result.assert_outcomes(failed=1)
    assert f"{shown} (test_planted.py:6)" in result.stdout.str(), result.stdout.str()


def test_asyncio_subprocesses_are_counted(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="import asyncio\n\ndef test_starts(tmp_path):\n    async def start():\n"
                                     "        try:\n            await asyncio.create_subprocess_exec(str(tmp_path / 'git'), 'gc')\n"
                                     "        except FileNotFoundError:\n            pass\n    asyncio.run(start())\n")
    result = run(pytester)
    result.assert_outcomes(failed=1)
    assert "git gc (" in result.stdout.str(), result.stdout.str()


def test_a_start_inside_another_counts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = spawn_guard.Counter(active=True)
    monkeypatch.setattr(spawn_guard, "COUNTERS", [counter])
    monkeypatch.setattr(spawn_guard, "_original", {"outer": lambda: inner(), "inner": lambda: None})
    inner = spawn_guard.counted("inner", lambda arguments: "inner")
    spawn_guard.counted("outer", lambda arguments: "outer")()
    assert [call.split(" ")[0] for call in counter.calls] == ["outer"]


def test_a_fixture_wider_than_one_test_starts_processes_freely(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="""\
        import subprocess
        import pytest

        @pytest.fixture(scope="session")
        def repository(tmp_path_factory):
            try:
                subprocess.run([str(tmp_path_factory.getbasetemp() / "git"), "init"])
            except FileNotFoundError:
                pass

        def test_uses_it(repository):
            pass
        """)
    result = run(pytester)
    result.assert_outcomes(passed=1)
    assert no_starts == [spawn_guard.POPEN]


def baseline(pytester: pytest.Pytester) -> dict[str, int]:
    return spawn_guard.read_baseline(pytester.path / spawn_guard.DEFAULT_BASELINE)


TWO_TESTS = GIT_TEST + "\n\ndef test_quiet():\n    pass\n"


def test_init_writes_the_baseline_and_a_listed_test_then_passes(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=TWO_TESTS)
    (pytester.path / "tests").mkdir()
    run(pytester, "--spawn-baseline=init").assert_outcomes(passed=2)
    assert baseline(pytester) == {"test_planted.py::test_runs_git": 1}
    result = run(pytester)
    result.assert_outcomes(passed=2)
    assert "1 in baseline tests" in result.stdout.str()
    refused = run(pytester, "--spawn-baseline=init")
    assert refused.ret == pytest.ExitCode.USAGE_ERROR
    assert "may only shrink" in refused.stderr.str()


def test_the_baseline_only_shrinks(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=TWO_TESTS, test_new=GIT_TEST.replace("test_runs_git", "test_runs_git_too"))
    path = pytester.path / spawn_guard.DEFAULT_BASELINE
    path.parent.mkdir()
    spawn_guard.write_baseline(path, {"test_planted.py::test_runs_git": 1, "test_planted.py::test_quiet": 2,
                                      "test_gone.py::test_elsewhere": 3})
    result = run(pytester, "--spawn-baseline=write", "test_planted.py", "test_new.py")
    result.assert_outcomes(passed=2, failed=1)  # the new spawning test is refused, never added
    assert baseline(pytester) == {"test_planted.py::test_runs_git": 1, "test_gone.py::test_elsewhere": 3}
    assert "spawns: wrote" in result.stdout.str()


def test_a_listed_test_that_starts_nothing_fails_naming_the_remedy(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="def test_quiet():\n    pass\n")
    path = pytester.path / spawn_guard.DEFAULT_BASELINE
    path.parent.mkdir()
    spawn_guard.write_baseline(path, {"test_planted.py::test_quiet": 1})
    result = run(pytester)
    result.assert_outcomes(passed=1, errors=1)
    assert "is in the spawn baseline" in result.stdout.str() and "--spawn-baseline=write" in result.stdout.str()


def test_the_baseline_is_yaml_with_json_quoted_ids(tmp_path: Path) -> None:
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "baseline.yaml"
    entries = {"tests/test_x.py::test_y[a: b]": 2, 'tests/test_x.py::test_z["q"]': 1}
    spawn_guard.write_baseline(path, entries)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["tests"] == entries
    assert spawn_guard.read_baseline(path) == entries
    spawn_guard.write_baseline(path, {})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["tests"] == {}
    assert spawn_guard.read_baseline(path) == {}


def test_a_malformed_baseline_line_is_refused_by_its_line(tmp_path: Path) -> None:
    path = tmp_path / "baseline.yaml"
    path.write_text("tests:\n  not an entry\n", encoding="utf-8")
    with pytest.raises(pytest.UsageError, match=r"baseline.yaml:2"):
        spawn_guard.read_baseline(path)


def test_the_controller_adds_up_its_workers_counts() -> None:
    guard = spawn_guard.SpawnGuard()
    for nodeid, value in [("a::t1", "2:marked"), ("a::t2", "3:listed"), ("a::t3", "1:"), ("a::t4", "0:")]:
        report = pytest.TestReport(nodeid, ("a", 0, nodeid), {}, "passed", None, "teardown",
                                   user_properties=[(spawn_guard.PROPERTY, value)])
        guard.pytest_runtest_logreport(report)
    assert (sum(guard.ran.values()), guard.marked, guard.listed, guard.refused) == (6, 2, 3, ["a::t3"])


@pytest.mark.parametrize("argv, shown", [
    (["/usr/bin/git", "status"], "git status"),
    ([sys.executable, str(ROOT / "scripts" / "work_tickets.py"), "sync", "--worktree", "x", "y"],
     f"{Path(sys.executable).name} work_tickets.py sync --worktree ..."),
    ("git status\nmore", "shell: git status ..."),
    ([], "(empty command)"),
])
def test_a_command_is_named_short(argv, shown: str) -> None:
    assert spawn_guard.command_text(argv) == shown


def test_the_suites_conftest_registers_the_guard(pytestconfig: pytest.Config) -> None:
    assert isinstance(pytestconfig.pluginmanager.get_plugin(spawn_guard.NAME), spawn_guard.SpawnGuard)
    assert subprocess.Popen._execute_child.__name__ == "wrapper"
    assert json.loads(json.dumps(spawn_guard.DEFAULT_BASELINE)) == "tests/spawn-baseline.yaml"


def test_the_suite_gate_prints_the_guards_total() -> None:
    """`work_tickets.py suite` prints the spawn guard's line of the suite's output, as the run read it."""
    import work_tickets

    output = ("....\nspawns: 3 processes started by 2 of 9 tests; 3 in marked tests, 0 in baseline tests, "
              "0 refused in 0 tests (scripts/spawn_guard.py)\n9 passed in 1.00s\n")
    assert work_tickets.spawns_line(output).startswith("spawns: 3 processes started by 2 of 9 tests")
    assert work_tickets.spawns_line("9 passed in 1.00s\n") == ""
