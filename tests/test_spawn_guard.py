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
    assert "spawns: 1 processes started by 1 of 1 tests; 0 in contract and entry-point tests, 1 refused" in output
    assert no_starts == [spawn_guard.POPEN]


def test_a_marked_test_may_start_processes_and_is_counted(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted="import pytest\n" + GIT_TEST.replace(
        "def test_runs_git", "@pytest.mark.spawns('contract: git')\ndef test_runs_git"))
    result = run(pytester)
    result.assert_outcomes(passed=1)
    assert "spawns: 1 processes started by 1 of 1 tests; 1 in contract and entry-point tests" in result.stdout.str()


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


SHELL_TEST = """\
import os
import subprocess

import pytest

@pytest.mark.spawns("{reason}")
def test_runs_a_shell(tmp_path):
    for start in (lambda: subprocess.run(["bash", "-c", "true"]), lambda: os.system("make docs")):
        try:
            start()
        except FileNotFoundError:
            pass
"""


def test_a_shell_is_refused_in_a_test_marked_for_another_reason_naming_each_call(pytester: pytest.Pytester,
                                                                               no_starts) -> None:
    pytester.makepyfile(test_planted=SHELL_TEST.format(reason="entry: scripts/x.py"))
    result = run(pytester)
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "test_planted.py::test_runs_a_shell started 2 shell(s) in its call, and only the shell door's contract" \
        in output, output
    assert "bash -c true (test_planted.py:8" in output and "shell: make docs (test_planted.py:8" in output, output
    assert "scripts/shell_door.py" in output and "contract: shell, <what it proves>" in output, output
    assert "2 refused in 1 tests (failed); 2 shells" in output, output


def test_a_shell_scripts_entry_point_test_may_start_a_shell(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=SHELL_TEST.format(reason="entry: scripts/x.sh"))
    run(pytester).assert_outcomes(passed=1)


def test_the_shell_doors_contract_starts_a_shell_and_the_total_counts_it(pytester: pytest.Pytester,
                                                                        no_starts) -> None:
    pytester.makepyfile(test_planted=SHELL_TEST.format(reason="contract: shell, x.sh's logic"))
    result = run(pytester)
    result.assert_outcomes(passed=1)
    assert "spawns: 2 processes started by 1 of 1 tests; 2 in contract and entry-point tests, 0 refused in 0 " \
           "tests (failed); 2 shells" in result.stdout.str()


@pytest.mark.parametrize("reason, kept, shell", [
    ("contract: shell", True, True), ("contract: shell, x.sh", True, True), ("contract: shell; x", True, True),
    ("contract: shells", True, False), ("contract: git", True, False), ("entry: scripts/se_hook.sh", True, True),
    ("entry: scripts/se_hook.sh, its wiring", True, True), ("entry: scripts/work_tickets.py", True, False),
    ("shell: scripts/bootstrap.sh's steps", False, False), ("tool: obs's build", False, False),
    ("contract: ", False, False), ("entry:", False, False), ("", False, False), (None, False, False)])
def test_only_a_contract_or_an_entry_point_may_start_processes_and_few_a_shell(reason, kept: bool,
                                                                               shell: bool) -> None:
    assert spawn_guard.kept(reason) is kept
    assert spawn_guard.shell_kept(reason) is shell


def test_a_test_marked_for_another_reason_is_refused_naming_the_reason(pytester: pytest.Pytester,
                                                                        no_starts) -> None:
    pytester.makepyfile(test_planted="import pytest\n" + GIT_TEST.replace(
        "def test_runs_git", "@pytest.mark.spawns('tool: git is the tool')\ndef test_runs_git"))
    result = run(pytester)
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "its mark's reason, 'tool: git is the tool', is no door's contract" in output, output
    assert "git status --short (test_planted.py:7)" in output, output


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


TWO_TESTS = GIT_TEST + "\n\ndef test_quiet():\n    pass\n"


def test_under_warn_a_refused_start_passes_and_is_named_by_file(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=TWO_TESTS)
    result = run(pytester, "--spawn-guard=warn")
    result.assert_outcomes(passed=2)
    output = result.stdout.str()
    assert "spawns: 1 processes started by 1 of 2 tests; 0 in contract and entry-point tests, 1 refused in 1 " \
           "tests (warned); 0 shells (scripts/spawn_guard.py warn)" in output, output
    assert "spawns: warn: the refused tests by file, each to convert (--spawn-guard=error names each call): " \
           "test_planted.py 1" in output, output


def test_the_ini_value_sets_the_level_and_the_option_wins(pytester: pytest.Pytester, no_starts) -> None:
    pytester.makepyfile(test_planted=GIT_TEST)
    pytester.makeini("[pytest]\nspawn_guard = warn\n")
    run(pytester).assert_outcomes(passed=1)
    run(pytester, "--spawn-guard=error").assert_outcomes(failed=1)
    pytester.makeini("[pytest]\nspawn_guard = loud\n")
    refused = run(pytester)
    assert refused.ret == pytest.ExitCode.USAGE_ERROR and "error or warn" in refused.stderr.str()


def test_the_controller_adds_up_its_workers_counts() -> None:
    guard = spawn_guard.SpawnGuard()
    for nodeid, value in [("a::t1", "2:kept:2"), ("a::t2", "3:kept:0"), ("a::t3", "1:refused:1"),
                          ("a::t4", "0:kept:0")]:
        report = pytest.TestReport(nodeid, ("a", 0, nodeid), {}, "passed", None, "teardown",
                                   user_properties=[(spawn_guard.PROPERTY, value)])
        guard.pytest_runtest_logreport(report)
    assert (sum(guard.ran.values()), guard.kept, guard.refused, guard.shells) == (6, 5, ["a::t3"], 3)


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
    assert not (ROOT / "tests" / "spawn-baseline.yaml").exists(), "there is no baseline"
    assert pytestconfig.getini(spawn_guard.INI) in spawn_guard.LEVELS


def test_the_suite_gate_prints_the_guards_total() -> None:
    """`work_tickets.py suite` prints the spawn guard's line of the suite's output, as the run read it."""
    import work_tickets

    output = ("....\nspawns: 3 processes started by 2 of 9 tests; 3 in contract and entry-point tests, 0 refused "
              "in 0 tests (failed); 0 shells (scripts/spawn_guard.py error)\n9 passed in 1.00s\n")
    assert work_tickets.spawns_line(output).startswith("spawns: 3 processes started by 2 of 9 tests")
    assert work_tickets.spawns_line("9 passed in 1.00s\n") == ""
