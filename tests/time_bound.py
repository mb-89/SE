"""The time bound: a test that runs far longer than the slowest test fails, naming itself, its bound and the remedy.

Reader: whoever writes a slow test, measures the bound again, or changes the wiring in tests/conftest.py.

`mark` gives each collected test pytest-timeout's mark with BOUND seconds, which pytest-timeout
counts over setup, call and teardown, so a hanging fixture is caught too. A test whose fixtures
include `obs` (the tests of tests/test_deck.py count through `decks`) gets the obs fixture's wait for
its lock on top: on a fresh checkout its setup clones and builds obs over the network, which no
measurement on one host bounds. A test that carries its own `timeout` mark keeps it. A test in
`tests/beside_*.py` gets none: those files run under their own `se.toml` `[tests.beside.*]` limit,
or only where the owner adds them (README "Host validators").

`explain` adds one section to the report of a test pytest-timeout stopped: the test, its bound,
this file as where the bound is set and measured, and the remedy.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

OWNER = "tests/time_bound.py"

# BOUND is 3 times the slowest test of the complete suite (setup, call and teardown, as pytest's
# JUnit report times a test), rounded up to whole tens of seconds. Measured with
# `work_tickets.py suite --slowest 10`, twice, on 17 Nov 2026 at main c99b701, on a 4-CPU Linux
# container (Intel Xeon at 2.30 GHz): the slower of the two runs' slowest was
# tests/test_start_refresh.py::test_a_plugin_one_release_behind_moves_at_start_and_starts_the_core_from_the_new_pins,
# 7.59 s, which gives 30 s (3 x 7.59 = 22.77). Measure again the same way where a test rightly
# takes longer.
SLOWEST_SECONDS = 7.59
BOUND = 30


def beside(item: pytest.Item) -> bool:
    """Whether `item` is a test of a `tests/beside_*.py` file, which runs under its own limit."""
    path = Path(item.path)
    return path.parent.name == "tests" and path.name.startswith("beside_") and path.suffix == ".py"


def mark(items: Iterable[pytest.Item], obs_wait: float, bound: float = BOUND) -> None:
    """Give each of `items` its timeout mark: `bound`, plus `obs_wait` for a test that takes `obs`;
    none for a test that has its own or lives in a `tests/beside_*.py` file."""
    for item in items:
        if item.get_closest_marker("timeout") is not None or beside(item):
            continue
        seconds = bound + (obs_wait if "obs" in getattr(item, "fixturenames", ()) else 0)
        item.add_marker(pytest.mark.timeout(seconds))


def timed_out(report: pytest.TestReport) -> bool:
    """Whether `report` is of a test phase pytest-timeout stopped."""
    text = str(report.longrepr) if report.failed else ""
    return "Timeout" in text and "pytest-timeout" in text


def explain(item: pytest.Item, report: pytest.TestReport) -> None:
    """Add the bound's section to the report of a test past its bound."""
    if not timed_out(report):
        return
    marker = item.get_closest_marker("timeout")
    if marker is None:  # a bound given on the command line (`--timeout`), not by `mark`
        seconds = item.config.getoption("timeout", None)
    else:
        seconds = marker.args[0] if marker.args else marker.kwargs.get("timeout")
    report.sections.append((OWNER, (
        f"{OWNER}: {item.nodeid} ran past its time bound of {seconds} s and failed; the bound is set "
        f"and measured in {OWNER}. Remedy: run the test alone to find what it waits for; where it "
        f"rightly takes longer, measure the bound again as the comment beside BOUND in {OWNER} says.")))
