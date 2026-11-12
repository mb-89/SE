"""The overhaul's pruning facts (scripts/overhaul.py facts) on a fixture checkout and on se itself."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

import overhaul

ROOT = Path(__file__).resolve().parents[1]

# A block written twice, in two scripts: the duplicate the facts must find.
COPIED = """\
    total = 0
    for value in values:
        if value is None:
            continue
        total = total + value * weight
    average = total / max(len(values), 1)
    return round(average, places)
"""

APP = f'''\
"""The fixture's application."""

import argparse

import lib


def used(values, weight, places):
{COPIED}

def tested_only():
    return helper_of_tested()


def helper_of_tested():
    return 1


def nothing_reaches():
    return 2


def documented():
    return 3


def run_ship(args):
    return lib.shared() + used([1], 2, 3)


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ship").set_defaults(handler=run_ship)
    commands.add_parser("forgotten")
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    main()
'''

LIB = f'''\
"""The fixture's library."""


def shared():
    return used_again([1, 2], 3, 4)


def used_again(values, weight, places):
{COPIED}
'''

TEST = '''\
import app


def test_tested_only():
    assert app.tested_only() == 1
'''

README = """\
# Fixture

Run `uv run python scripts/app.py ship` to ship; `documented` is the library's interface, and
`scripts/lib.py` holds the rest.
"""


def git(root: Path, *arguments: str, when: str = "2026-01-01T00:00:00Z") -> None:
    environment = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=alice", "-c", "user.email=alice@example.com",
                    *arguments], check=True, capture_output=True, env=environment)


@pytest.fixture(scope="module")
def checkout(tmp_path_factory) -> Path:
    """The fixture checkout, built once: facts only reads it."""
    root = tmp_path_factory.mktemp("checkout")
    git(root, "init", "-q")
    (root / "se.toml").write_text('[project]\nauthored_content = ["README.md"]\n', encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    (root / "scripts" / "lib.py").write_text(LIB, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "The library", when="2026-01-01T00:00:00Z")
    (root / "scripts" / "app.py").write_text(APP, encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(TEST, encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "The application", when="2026-03-01T00:00:00Z")
    return root


def facts(root: Path, capsys) -> dict:
    assert overhaul.main(["facts", "--json", "--repo", str(root)]) == 0
    return json.loads(capsys.readouterr().out)


def test_facts_find_unreached_code_duplicates_and_unnamed_commands(checkout, capsys):
    found = facts(checkout, capsys)
    unreached = {item["what"]: item["tests"] for item in found["unreached"]}
    assert unreached == {"function tested_only": True, "function helper_of_tested": True,
                         "function nothing_reaches": False}
    assert [(block["a"].split(":")[0], block["b"].split(":")[0], block["lines"])
            for block in found["duplicates"]] == [("scripts/app.py", "scripts/lib.py", 7)]
    assert [(pair["a"].split()[1], pair["b"].split()[1]) for pair in found["near"]] == [("used", "used_again")]
    assert found["near"][0]["alike"] >= overhaul.NEAR_ALIKE
    assert found["unnamed"] == ["app.py forgotten"]
    assert overhaul.main(["facts", "--repo", str(checkout)]) == 0
    report = capsys.readouterr().out
    assert "- scripts/app.py:26 function nothing_reaches (not even tests)" in report
    assert "- app.py forgotten" in report


def test_facts_measure_sizes_lengths_and_the_untouched_and_change_nothing(checkout, capsys):
    found = facts(checkout, capsys)
    sizes = {row["script"]: (row["lines"], row["test_lines"]) for row in found["sizes"]}
    assert sizes["scripts/app.py"][1] == 3 and sizes["scripts/lib.py"][1] == 0
    assert [(item["what"], item["lines"]) for item in found["long_functions"][:3]] == [
        ("used", 8), ("used_again", 8), ("main", 7)]
    assert found["long_files"][0]["at"] == "scripts/app.py"
    assert [(item["what"], item["parameters"]) for item in found["long_parameters"][:2]] == [
        ("used", 3), ("used_again", 3)]
    assert found["untouched"][0] == {"at": "scripts/lib.py", "last": "2026-01-01"}
    status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True,
                            text=True, check=True).stdout
    assert status == ""


def test_facts_on_se_answer_within_the_budget(capsys):
    started = time.perf_counter()
    found = facts(ROOT, capsys)
    assert time.perf_counter() - started < 10
    assert {row["script"] for row in found["sizes"]} >= {"scripts/work_tickets.py"}
