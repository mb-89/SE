"""The application's Go tests, run as one test of the battery, so se.toml [tests] holds them and the
Python tests to one budget."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_go_tests_pass():
    run = subprocess.run(["go", "test", "./..."], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
