"""The order the suite's workers take its test files in (tests/conftest.py, "The order the
workers take the test files in"): the heaviest file first, by the seconds the checkout's last
parallel run recorded in pytest's cache, else by the tracked table tests/file-seconds.json, which
seeds the order where the cache records nothing (CI, a fresh clone, a new worktree), else by its
tests. The cache wins file by file. The table holds CI's seconds, as CI's runner runs the
PowerShell cases and skips the Playwright ones: CI's suite step records them into its artifact
file-seconds, and `uv run python scripts/work_tickets.py file-seconds` writes the table from it."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
import work_tickets

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



# CI records its seconds and the table is written from them (work_tickets.py `suite
# --record-file-seconds`, `file-seconds`).


def test_the_suites_pytest_command_carries_the_record_and_another_runner_runs_as_declared():
    record = Path("/tmp/run/file-seconds.json")
    command = work_tickets.with_file_seconds(work_tickets.with_durations(["uv", "run", "pytest", "-q"], 10), record)
    assert command == ["uv", "run", "pytest", "-q", "--durations=10", f"--record-file-seconds={record}"]
    assert work_tickets.with_file_seconds(["go", "test", "./..."], record) == ["go", "test", "./..."]
    assert work_tickets.with_file_seconds(["uv", "run", "pytest"], None) == ["uv", "run", "pytest"]


class FakeCi:
    """CI's runs as gh answers them: `runs` the passing pushes newest first, `artifacts` the runs
    that kept file-seconds with the seconds it holds."""

    def __init__(self, runs: list[int], artifacts: dict[str, dict[str, float]]) -> None:
        self.runs, self.artifacts, self.calls = runs, artifacts, []

    def __call__(self, root: Path, arguments: list[str]) -> str:
        self.calls.append(arguments)
        if arguments[:2] == ["run", "list"]:
            return json.dumps([{"databaseId": run} for run in self.runs])
        if arguments[0] == "api":
            run = arguments[1].split("/")[-2]
            kept = [{"name": "file-seconds", "expired": False}] if run in self.artifacts else []
            return json.dumps({"artifacts": [{"name": "other", "expired": False}, *kept]})
        if arguments[:2] == ["run", "download"]:
            directory = Path(arguments[arguments.index("--dir") + 1])
            (directory / "file-seconds.json").write_text(json.dumps(self.artifacts[arguments[2]]), encoding="utf-8")
            return ""
        raise AssertionError(f"unexpected gh {arguments}")


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A checkout of three test files and a table that also names a gone one."""
    for name in ("test_a.py", "test_b.py", "test_kept.py"):
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")
    table = {"tests/test_a.py": 1.0, "tests/test_kept.py": 4.0, "tests/test_gone.py": 3.0}
    conftest.write_table(tmp_path / "tests" / "file-seconds.json", table)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/alice/example")
    return tmp_path


def test_file_seconds_writes_the_table_from_ci_keeping_a_file_the_run_lacks_and_dropping_a_gone_one(
        checkout, monkeypatch, capsys):
    ci = FakeCi([9, 7], {"7": {"tests/test_a.py": 6.04, "tests/test_b.py": 0.5}})
    monkeypatch.setattr(work_tickets, "run_gh", ci)
    assert work_tickets.main(["file-seconds", "--worktree", str(checkout)]) == 0
    table = checkout / "tests" / "file-seconds.json"
    expected = {"tests/test_a.py": 6.0, "tests/test_b.py": 0.5, "tests/test_kept.py": 4.0}
    assert json.loads(table.read_text(encoding="utf-8")) == expected
    conftest.write_table(checkout / "form.json", expected)
    assert table.read_text(encoding="utf-8") == (checkout / "form.json").read_text(encoding="utf-8")
    assert table_problems(table, checkout) == []
    out = capsys.readouterr().out
    assert "from run 7 (2 files of the run, 1 kept from the table); 2 moved by 1 s or more" in out
    assert "  tests/test_a.py: 1.0 s -> 6.0 s" in out and "  tests/test_gone.py: 3.0 s -> none" in out
    assert "test_b.py" not in out and "test_kept.py" not in out  # moved by less than 1 s, or not at all
    listed = ci.calls[0]
    assert listed[:2] == ["run", "list"] and listed[listed.index("--event") + 1] == "push"
    assert listed[listed.index("--branch") + 1] == "main" and listed[listed.index("--status") + 1] == "success"


def test_file_seconds_refuses_a_run_without_the_artifact_in_one_line_naming_it(checkout, monkeypatch, capsys):
    before = (checkout / "tests" / "file-seconds.json").read_text(encoding="utf-8")
    monkeypatch.setattr(work_tickets, "run_gh", FakeCi([], {}))
    assert work_tickets.main(["file-seconds", "--worktree", str(checkout), "--run", "8"]) == 1
    error = capsys.readouterr().err.strip()
    assert len(error.splitlines()) == 1 and "run 8 has no artifact file-seconds" in error
    assert (checkout / "tests" / "file-seconds.json").read_text(encoding="utf-8") == before


def test_file_seconds_reads_an_artifact_the_host_downloaded(checkout, capsys):
    artifact = checkout / "artifact.json"
    artifact.write_text(json.dumps({"tests/test_b.py": 9.0}), encoding="utf-8")
    assert work_tickets.main(["file-seconds", "--worktree", str(checkout), "--artifact", str(artifact),
                              "--run", "12"]) == 0
    assert json.loads((checkout / "tests" / "file-seconds.json").read_text(encoding="utf-8")) == {
        "tests/test_a.py": 1.0, "tests/test_b.py": 9.0, "tests/test_kept.py": 4.0}
    assert "from run 12" in capsys.readouterr().out


def test_record_file_seconds_without_a_path_is_refused_naming_the_refresh_from_ci():
    before = conftest.FILE_SECONDS_TABLE.read_bytes()
    ran = run_pytest("-q", "-n", "2", "-p", "no:cacheprovider", *QUICK, "--record-file-seconds")
    assert ran.returncode == pytest.ExitCode.USAGE_ERROR, ran.stdout + ran.stderr
    assert conftest.RECORD_COMMAND in ran.stdout + ran.stderr and "PowerShell" in ran.stdout + ran.stderr
    assert conftest.RECORD_COMMAND == "uv run python scripts/work_tickets.py file-seconds"
    assert conftest.FILE_SECONDS_TABLE.read_bytes() == before


def test_drift_names_a_file_more_than_5_s_and_more_than_half_over_the_table_and_no_other():
    table = {"far.py": 4.0, "slow.py": 20.0, "near.py": 4.0, "new.py": 0.0, "gone.py": 9.0}
    run = {"far.py": 9.5, "slow.py": 29.0, "near.py": 8.9, "unknown.py": 50.0, "new.py": 5.1}
    # far: 5.5 s over and 138 % over; slow: 9 s over but 45 %; near: 4.9 s over; unknown: no entry.
    assert conftest.drift_lines(run, table) == [
        "file seconds: far.py took 9.5 s here, the table says 4.0 s; refresh it with " + conftest.RECORD_COMMAND,
        "file seconds: new.py took 5.1 s here, the table says 0.0 s; refresh it with " + conftest.RECORD_COMMAND,
    ]
    assert conftest.drift_lines({"a.py": 1.0}, {"a.py": 1.0}) == []


SLOWER = """\
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report):
    if report.nodeid.startswith("tests/test_se_home.py"):
        report.duration += 1.0  # the file takes over 5 s more than its table entry, slept nowhere
"""


def test_a_run_that_writes_a_table_names_a_file_that_drifted_and_one_that_writes_none_names_none(tmp_path):
    (tmp_path / "slower.py").write_text(SLOWER, encoding="utf-8")
    table = tmp_path / "table.json"
    table.write_text(json.dumps({QUICK[0]: 0.5, QUICK[1]: 60.0}), encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if name != conftest.REPORTS_VARIABLE}
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), env.get("PYTHONPATH", "")])
    base = [sys.executable, "-m", "pytest", "--rootdir", str(ROOT), "-q", "-n", "2", "-p", "no:cacheprovider",
            "-p", "slower", "-o", f"file_seconds={table}", *QUICK]
    for record, named in ((["--record-file-seconds", str(tmp_path / "out.json")], True), ([], False)):
        ran = subprocess.run([*base, *record], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        assert ran.returncode == 0, ran.stdout + ran.stderr
        lines = [line for line in ran.stdout.splitlines() if " took " in line]
        assert len(lines) == int(named), ran.stdout
        if named:
            assert lines[0].startswith(f"file seconds: {QUICK[0]} took ")
            assert lines[0].endswith(f"s here, the table says 0.5 s; refresh it with {conftest.RECORD_COMMAND}")
