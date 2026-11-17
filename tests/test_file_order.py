"""The order the suite's workers take its test files in (tests/conftest.py, "The order the
workers take the test files in"): the heaviest file first, by the seconds the checkout's last
parallel run recorded in pytest's cache, else by the tracked table tests/file-seconds.json, which
seeds the order where the cache records nothing (CI, a fresh clone, a new worktree), else by its
tests. The cache wins file by file; `uv run pytest -q --record-file-seconds` refreshes the table."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import conftest

ROOT = Path(__file__).resolve().parents[1]


def test_recorded_seconds_order_the_files_heaviest_first():
    counts = {"a.py": 300, "b.py": 3, "c.py": 40}
    assert conftest.file_order(counts, {"a.py": 10.0, "b.py": 14.0, "c.py": 2.0}) == ["b.py", "a.py", "c.py"]


def test_without_seconds_the_files_go_by_their_tests_and_ties_keep_the_collection_order():
    assert conftest.file_order({"a.py": 2, "b.py": 9, "c.py": 2}, {}) == ["b.py", "a.py", "c.py"]


def test_a_file_the_cache_does_not_know_counts_its_tests_at_the_known_mean():
    # Known: 10 s over 101 tests, about 0.1 s a test: the new file's 50 tests weigh about 5 s.
    counts = {"old.py": 100, "new.py": 50, "small.py": 1}
    assert conftest.file_order(counts, {"old.py": 4.0, "small.py": 6.0}) == ["small.py", "new.py", "old.py"]


def test_a_parallel_run_records_each_files_seconds_and_the_next_run_collects_by_them(tmp_path):
    """Two quick files of the suite, run on two workers with the cache in tmp_path: the cache then
    holds each file's seconds, and a run collecting with a recorded heavier second file takes it first."""
    files = ["tests/test_se_home.py", "tests/test_outside_text.py"]
    cache = ["-o", f"cache_dir={tmp_path / 'cache'}", "--rootdir", str(ROOT)]
    # The outer run's JUnit report (work_tickets.py suite) stays the outer run's.
    env = {name: value for name, value in os.environ.items() if name != conftest.REPORTS_VARIABLE}
    ran = subprocess.run([sys.executable, "-m", "pytest", "-q", "-n", "2", *cache, *files],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    recorded = tmp_path / "cache" / "v" / "se" / "file-seconds"
    seconds = json.loads(recorded.read_text(encoding="utf-8"))
    assert set(seconds) == set(files) and all(value >= 0 for value in seconds.values())

    recorded.write_text(json.dumps({files[0]: 0.1, files[1]: 99.0}), encoding="utf-8")
    listed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-n", "0", "--collect-only", *cache, *files],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert listed.returncode == 0, listed.stdout + listed.stderr
    order = [line.split("::")[0] for line in listed.stdout.splitlines() if "::" in line]
    assert order and order[0] == files[1] and set(order) == set(files)


QUICK = ["tests/test_se_home.py", "tests/test_outside_text.py"]


def run_pytest(*args: str) -> subprocess.CompletedProcess:
    """A pytest run of the suite's conftest at ROOT; the outer run's JUnit report stays the outer run's."""
    env = {name: value for name, value in os.environ.items() if name != conftest.REPORTS_VARIABLE}
    return subprocess.run([sys.executable, "-m", "pytest", "--rootdir", str(ROOT), *args],
                          cwd=ROOT, env=env, capture_output=True, text=True, check=False)


def table_problems(path: Path, root: Path) -> list[str]:
    """What keeps the table at `path` from requirement 3's form: each problem names the entry."""
    remedy = f"write it with `{conftest.RECORD_COMMAND}`"
    if not path.exists():
        return [f"{path}: missing; {remedy}"]
    text = path.read_text(encoding="utf-8")
    try:
        table = conftest.read_table(path)
    except pytest.UsageError as error:
        return [str(error)]
    problems = []
    if list(table) != sorted(table):
        problems.append(f"{path}: its files are not sorted; {remedy}")
    for name, raw in re.findall(r'^\s*"([^"]+)": (\S+?),?$', text, flags=re.MULTILINE):
        if not re.fullmatch(r"\d+(\.\d)?", raw):
            problems.append(f"{path}: {name}: {raw} is not seconds rounded to 0.1; {remedy}")
    for name in table:
        if not (root / name).exists():
            problems.append(f"{path}: {name}: no such file; {remedy}")
    return problems


def test_the_cache_wins_the_table_fills_the_rest_and_a_file_in_neither_goes_by_the_mean():
    merged = conftest.merged_seconds({"a.py": 1.0}, {"a.py": 50.0, "b.py": 6.0})
    assert merged == {"a.py": 1.0, "b.py": 6.0}
    # Known: 7 s over 7 tests, 1 s a test: c.py's 3 tests weigh 3 s, between b.py and a.py.
    assert conftest.file_order({"a.py": 2, "b.py": 5, "c.py": 3}, merged) == ["b.py", "c.py", "a.py"]


def test_with_nothing_recorded_the_table_orders_the_files(tmp_path):
    table = tmp_path / "file-seconds.json"
    table.write_text(json.dumps({QUICK[0]: 0.1, QUICK[1]: 99.0}), encoding="utf-8")
    seeded = ["-p", "no:cacheprovider", "-o", f"file_seconds={table}"]
    listed = run_pytest("-q", "-n", "0", "--collect-only", *seeded, *QUICK)
    assert listed.returncode == 0, listed.stdout + listed.stderr
    order = [line.split("::")[0] for line in listed.stdout.splitlines() if "::" in line]
    assert order and order[0] == QUICK[1] and set(order) == set(QUICK)

    ran = run_pytest("-n", "1", "-v", *seeded, *QUICK)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    tests = [word.split("::")[0] for line in ran.stdout.splitlines() if "PASSED" in line
             for word in line.split() if "::" in word]
    assert tests and tests[0] == QUICK[1] and set(tests) == set(QUICK)


def test_record_file_seconds_writes_the_files_of_a_passing_parallel_run(tmp_path):
    table = tmp_path / "file-seconds.json"
    ran = run_pytest("-q", "-n", "2", "-p", "no:cacheprovider", f"--record-file-seconds={table}", *QUICK)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "file seconds: wrote" in ran.stdout
    seconds = json.loads(table.read_text(encoding="utf-8"))
    assert list(seconds) == sorted(QUICK) and all(value == round(value, 1) >= 0 for value in seconds.values())
    assert table_problems(table, ROOT) == []

    table.write_text(json.dumps({"tests/test_gone.py": 3.0, "tests/test_docs.py": 7.5, QUICK[0]: 40.0}),
                     encoding="utf-8")
    ran = run_pytest("-q", "-n", "2", "-p", "no:cacheprovider", f"--record-file-seconds={table}", *QUICK)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    seconds = json.loads(table.read_text(encoding="utf-8"))
    assert list(seconds) == sorted([*QUICK, "tests/test_docs.py"]) and seconds["tests/test_docs.py"] == 7.5
    assert seconds[QUICK[0]] != 40.0  # this run's seconds, not the earlier table's


def test_record_file_seconds_writes_nothing_after_a_run_of_part_of_the_files_and_says_why(tmp_path):
    table = tmp_path / "file-seconds.json"
    ran = run_pytest("-q", "-n", "2", "-p", "no:cacheprovider", "-k", "home",
                     f"--record-file-seconds={table}", *QUICK)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert not table.exists()
    assert "file seconds: wrote nothing" in ran.stdout and "whole files" in ran.stdout


def test_a_table_that_is_not_files_to_non_negative_seconds_is_refused_naming_it(tmp_path):
    for number, text in enumerate(['["tests/a.py"]', '{"tests/a.py": -1}', '{"tests/a.py": "5"}', "{"]):
        table = tmp_path / f"bad-{number}.json"
        table.write_text(text, encoding="utf-8")
        with pytest.raises(pytest.UsageError, match=re.escape(str(table))):
            conftest.read_table(table)
        assert table_problems(table, ROOT) and str(table) in table_problems(table, ROOT)[0]
    listed = run_pytest("-q", "-n", "0", "--collect-only", "-p", "no:cacheprovider",
                        "-o", f"file_seconds={tmp_path / 'bad-1.json'}", *QUICK)
    assert listed.returncode != 0 and str(tmp_path / "bad-1.json") in listed.stdout + listed.stderr
    assert conftest.read_table(tmp_path / "missing.json") == {}  # a missing table is today's order


def test_a_table_out_of_form_is_refused_naming_the_entry(tmp_path):
    cases = {
        "unsorted": ('{\n  "tests/test_se_home.py": 1.0,\n  "tests/test_docs.py": 2.0\n}\n', "not sorted"),
        "decimals": ('{\n  "tests/test_docs.py": 2.25\n}\n', "tests/test_docs.py: 2.25"),
        "gone": ('{\n  "tests/test_gone.py": 2.0\n}\n', "tests/test_gone.py: no such file"),
    }
    for name, (text, problem) in cases.items():
        table = tmp_path / f"{name}.json"
        table.write_text(text, encoding="utf-8")
        problems = table_problems(table, ROOT)
        assert any(problem in line and str(table) in line for line in problems), (name, problems)
    assert "missing" in table_problems(tmp_path / "none.json", ROOT)[0]


def test_the_committed_table_is_sorted_rounded_and_names_existing_files():
    assert table_problems(conftest.FILE_SECONDS_TABLE, ROOT) == []
