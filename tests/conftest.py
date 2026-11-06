"""Shared fixtures of se's suite."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402


@pytest.fixture(scope="session")
def obs() -> Path:
    """The obs module at its pin with its environment built, once per checkout at a time.

    The suite's workers run test files in parallel (pyproject.toml), and every obs build syncs the module
    and runs it through uv: a fresh checkout must clone and build it once, never twice at once. A
    directory made atomically is the lock, which every platform has.
    """
    lock = ROOT / ".se" / "obs-setup.lock"
    lock.parent.mkdir(exist_ok=True)
    deadline = time.monotonic() + 600
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                pytest.fail(f"{lock} is still held after 600 s; remove it if no suite runs")
            time.sleep(0.2)
    try:
        directory = build_docs.obs_dir()
        subprocess.run(["uv", "sync", "--quiet", "--project", str(directory)], cwd=ROOT, check=True,
                       env=build_docs.child_environment())
        return directory
    finally:
        os.rmdir(lock)


@pytest.fixture(scope="session")
def repositories(tmp_path_factory) -> Callable[[Callable[[Path], None], Path], None]:
    """`repositories(build, tmp_path)` lays out in tmp_path the git repositories `build` makes in an
    empty directory: built once per session (per worker) and copied for each test, which costs a
    fraction of the git commands. The copies' remotes point into tmp_path, as a fresh build's do."""
    built: dict[Callable[[Path], None], Path] = {}

    def lay_out(build: Callable[[Path], None], tmp_path: Path) -> None:
        if build not in built:
            built[build] = tmp_path_factory.mktemp(build.__name__)
            build(built[build])
        template = built[build]
        shutil.copytree(template, tmp_path, symlinks=True, dirs_exist_ok=True)
        # Git writes a local remote's path into config as given, a backslash doubled.
        forms = {str(template): str(tmp_path), template.as_posix(): tmp_path.as_posix(),
                 str(template).replace("\\", "\\\\"): str(tmp_path).replace("\\", "\\\\")}
        for config in [*tmp_path.glob("*/.git/config"), *tmp_path.glob("*.git/config")]:
            text = original = config.read_text(encoding="utf-8")
            for old, new in forms.items():
                text = text.replace(old, new)
            if text != original:
                config.write_text(text, encoding="utf-8")

    return lay_out
