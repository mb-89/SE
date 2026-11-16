"""The order the suite's workers take its test files in (tests/conftest.py, "The order the
workers take the test files in"): the heaviest file first, by the seconds the checkout's last
parallel run recorded in pytest's cache, else by its tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
