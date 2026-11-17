"""suite_runs.py: whether a suite beside ran a test, read from its output alone."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import suite_runs
from suite_runs import NONE, SOME, UNKNOWN, ran

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize("output, reason", [
    ("ok  \tkern/contract\t0.01s [no tests to run]", "every package reads [no tests to run]"),
    ("?   \tkern/cmd\t[no test files]", "every package reads [no test files]"),
    ("ok  \tx\t(cached) [no tests to run]\n?   \tkern/cmd\t[no test files]",
     "every package reads [no test files] or [no tests to run]"),
    ("testing: warning: no tests to run\nPASS\nok  \tx\t0.01s [no tests to run]",
     "every package reads [no tests to run]"),
])
def test_go_output_whose_every_package_ran_no_test_reads_none(output, reason):
    assert ran(output) == suite_runs.Ran(NONE, reason)


@pytest.mark.parametrize("output", [
    "ok  \tx\t0.2s",
    "ok  \tx\t(cached)",
    "ok  \tx\t0.2s\nok  \ty\t0.01s [no tests to run]\n?   \tz\t[no test files]",
])
def test_go_output_where_a_package_ran_tests_reads_some(output):
    assert ran(output).verdict == SOME


@pytest.mark.parametrize("output, reason", [
    ("3 skipped in 0.2s", "pytest counted 3 skipped and none passed"),
    ("== 2 skipped, 1 deselected in 0.1s ==", "pytest counted 2 skipped, 1 deselected and none passed"),
    ("3 skipped in 75.12s (0:01:15)", "pytest counted 3 skipped and none passed"),
    ("1 passed in 0.1s\n3 skipped, 1 warning in 0.2s", "pytest counted 3 skipped, 1 warning and none passed"),
])
def test_a_pytest_summary_of_skips_alone_reads_none(output, reason):
    assert ran(output) == suite_runs.Ran(NONE, reason)


@pytest.mark.parametrize("output", [
    "2 passed, 1 skipped in 0.3s",
    "1 xfailed in 0.1s",
    "=== 1 passed in 75.12s (0:01:15) ===",
    "3 skipped in 0.1s\n1 error in 0.2s",
])
def test_a_pytest_summary_that_counts_a_test_reads_some(output):
    assert ran(output).verdict == SOME


@pytest.mark.parametrize("output", [
    "",
    "ok in kern",
    "release guard: v0.9.1 matches kern/release.toml\nrelease guard: passed",
    "copilot self-test: 0 passed, 0 failed, 3 skipped, 0 noted; cleaned up",
    "PASS\n=== RUN   TestTally",
])
def test_other_output_reads_unknown(output):
    assert ran(output) == suite_runs.Ran(UNKNOWN)


def test_some_from_either_shape_wins():
    assert ran("ok  \tx\t0.2s\n3 skipped in 0.1s").verdict == SOME
    assert ran("ok  \tx\t0.01s [no tests to run]\n1 passed in 0.1s").verdict == SOME


def imported(source):
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_module_imports_no_script_and_only_the_standard_library():
    names = imported(Path(suite_runs.__file__).read_text(encoding="utf-8"))
    assert names & {path.stem for path in SCRIPTS.glob("*.py")} == set()
    assert names <= {"__future__", "dataclasses", "re"}
