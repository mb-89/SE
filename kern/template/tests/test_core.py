"""The battery starts the bare core: the application's binary, built from cmd/app, starts in the
background on the application's wiring, says it runs, and stops."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAME = "app"


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    path = tmp_path_factory.mktemp("bin") / (NAME + (".exe" if sys.platform == "win32" else ""))
    subprocess.run(["go", "build", "-o", str(path), "./cmd/" + NAME], cwd=ROOT, check=True)
    return path


def run(binary, *args):
    done = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=30)
    return done.returncode, done.stdout + done.stderr


def test_the_core_starts_runs_and_stops(binary, tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    shutil.copy(ROOT / "wiring.toml", root / "wiring.toml")
    assert run(binary, "status", "--root", str(root)) == (1, f"{NAME}: not running in {root}\n")
    code, out = run(binary, "start", "--root", str(root))
    assert code == 0 and out.startswith(f"{NAME}: started in "), out
    try:
        code, out = run(binary, "status", "--root", str(root), "--wait", "10s")
        assert code == 0 and f"{NAME}: running in {root}" in out and "0 instance(s)" in out, out
    finally:
        code, out = run(binary, "stop", "--root", str(root))
    assert code == 0 and f"{NAME}: stopped pid " in out, out
    assert run(binary, "status", "--root", str(root))[0] == 1
