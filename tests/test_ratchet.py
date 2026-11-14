"""scripts/ratchet.py: found counts per path against a baseline that may only shrink."""

from __future__ import annotations

import pytest

from ratchet import compare

FOUND = {"b.py": 3, "a.py": 1, "same.py": 2, "fewer.py": 1}
BASELINE = {"b.py": 2, "same.py": 2, "fewer.py": 2, "vanished.py": 1}


def test_report_mode_names_new_and_gone_as_sorted_paths_and_leaves_the_unchanged_out():
    new, gone = compare(FOUND, BASELINE, "report")
    assert new == ["a.py", "b.py"]
    assert gone == ["fewer.py", "vanished.py"]


def test_report_mode_on_equal_counts_finds_nothing():
    assert compare({"a.py": 2}, {"a.py": 2}, "report") == ([], [])


@pytest.mark.parametrize("mode", [(), ("off",)])
def test_off_and_no_mode_given_give_two_empty_lists_for_the_same_input(mode):
    assert compare(FOUND, BASELINE, *mode) == ([], [])


@pytest.mark.parametrize("mode", ["refuse", "Report", ""])
def test_any_other_mode_raises_and_says_refusing_is_the_owners_step(mode):
    with pytest.raises(ValueError, match="owner's step"):
        compare(FOUND, BASELINE, mode)
