"""The time bound (tests/time_bound.py): which tests get it, and what a test past it reports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import se_modules
import time_bound

TESTS = Path(__file__).resolve().parent


class Item:
    """The parts of a collected test `time_bound.mark` reads and writes."""

    def __init__(self, path: Path, fixturenames=(), own: float | None = None) -> None:
        self.path = path
        self.fixturenames = list(fixturenames)
        self.markers = [pytest.mark.timeout(own).mark] if own is not None else []

    def get_closest_marker(self, name: str):
        return next((marker for marker in reversed(self.markers) if marker.name == name), None)

    def add_marker(self, marker) -> None:
        self.markers.append(marker.mark)

    @property
    def bound(self):
        marker = self.get_closest_marker("timeout")
        return marker.args[0] if marker is not None else None


def test_each_test_gets_the_bound_and_one_that_takes_obs_the_wait_on_top():
    plain = Item(TESTS / "test_example.py", ["tmp_path"])
    deck = Item(TESTS / "test_deck.py", ["decks", "obs", "tmp_path"])
    kern = Item(se_modules.kern_dir(TESTS.parent) / "python" / "tests" / "test_example.py")
    time_bound.mark([plain, deck, kern], obs_wait=600)
    assert plain.bound == time_bound.BOUND == 30
    assert deck.bound == time_bound.BOUND + 600
    assert kern.bound == time_bound.BOUND


def test_a_test_with_its_own_mark_keeps_it_and_one_beside_the_suite_gets_none():
    own = Item(TESTS / "test_example.py", own=5)
    beside = Item(TESTS / "beside_se_relay.py", ["obs"])
    time_bound.mark([own, beside], obs_wait=600)
    assert own.bound == 5 and len(own.markers) == 1
    assert beside.bound is None


def test_the_bound_is_three_times_the_slowest_test_in_whole_tens():
    assert time_bound.BOUND == -(-3 * time_bound.SLOWEST_SECONDS // 10) * 10


PLANTED = """\
import time

import pytest


@pytest.mark.timeout(1)
def test_sleeps_past_its_bound():
    time.sleep(60)


def test_has_the_bound(request):
    assert request.node.get_closest_marker("timeout").args[0] == {bound}
"""


@pytest.mark.skipif(sys.platform == "win32", reason="on Windows pytest-timeout ends the worker "
                    "instead (its timer thread), and the section is not added")
def test_a_test_past_its_bound_fails_naming_itself_its_bound_and_the_remedy(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_planted.py").write_text(PLANTED.format(bound=time_bound.BOUND), encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest",
                             "test_planted.py"], cwd=tmp_path, env=environment, capture_output=True,
                            text=True, check=False, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "1 failed, 1 passed" in output
    assert "Timeout (>1.0s) from pytest-timeout." in output
    assert ("tests/time_bound.py: test_planted.py::test_sleeps_past_its_bound ran past its time bound "
            "of 1 s") in output
    assert "Remedy: run the test alone to find what it waits for" in output


class Scheduling:
    """pytest-xdist's `--dist loadfile` scheduling as `time_bound.crashed` sees it: the requeued work
    of each file, test to whether it is done."""

    def __init__(self, workqueue: dict[str, dict[str, bool]]) -> None:
        self.workqueue = workqueue


def test_a_test_that_ends_its_worker_fails_once_by_name_and_its_file_goes_on():
    """tests/conftest.py `pytest_handlecrashitem`: pytest-xdist requeues the file of a test whose
    worker ended, the test with it, so it would end worker after worker until the run stops; the
    crashed test is marked done, and its report names it, the likely cause and where the bound is."""
    crashed = "tests/test_x.py::test_hangs"
    sched = Scheduling({"tests/test_x.py": {"tests/test_x.py::test_before": True, crashed: False,
                                            "tests/test_x.py::test_after": False}})
    report = pytest.TestReport(crashed, ("tests/test_x.py", None, "tests/test_x.py"), {}, "failed",
                               f"worker 'gw0' crashed while running '{crashed}'", "???")
    time_bound.crashed(crashed, report, sched)
    assert sched.workqueue["tests/test_x.py"] == {"tests/test_x.py::test_before": True, crashed: True,
                                                  "tests/test_x.py::test_after": False}
    text = str(report.longrepr)
    assert text.startswith(f"worker 'gw0' crashed while running '{crashed}'")
    assert f"{crashed} ended its worker and failed; it is not run again" in text
    assert "thread method, the only one on Windows" in text and time_bound.OWNER in text
