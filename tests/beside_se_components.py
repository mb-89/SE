"""SE's commands as components against the real core, the suite beside se.toml
`[tests.beside.se-components]` (README "Commands as components"): where kern serves a checkout with
SE's wiring, `kern status` lists SE's components attached, an interactive command answers through
kern as it answers directly, and once kern has stopped it runs directly again.

It builds kern's binary, so it runs beside the suite, after kern's tests have warmed Go's build
cache, not in it (its file name keeps the suite from collecting it): README "Test budget".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ["delivery", "integration", "issues", "tickets"]


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "UV_SYSTEM_CERTS": "1", **(env or {})})


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout of its own for the core, SE's components, scripts and SDK linked into it, so the
    core's files and its lease never touch this checkout's own kern."""
    root = tmp_path / "se"
    (root / ".git").mkdir(parents=True)
    for part in ("components", "scripts", "kern"):
        try:
            (root / part).symlink_to(ROOT / part, target_is_directory=True)
        except OSError as error:  # Windows without the right to make links
            pytest.skip(f"no symlink: {error}")
    (root / "wiring.toml").write_bytes((ROOT / "wiring.toml").read_bytes())
    return root


def test_kern_lists_ses_components_and_a_command_answers_through_it_and_without_it(
        checkout: Path, tmp_path: Path) -> None:
    kern = tmp_path / ("kern.exe" if os.name == "nt" else "kern")
    built = run("go", "build", "-o", str(kern), "./cmd/kern", cwd=ROOT / "kern")
    assert built.returncode == 0, built.stderr
    queue = tmp_path / "queue"
    (queue / ".git").mkdir(parents=True)
    script = str(checkout / "scripts" / "work_tickets.py")
    command = [sys.executable, script, "status", "--worktree", str(queue)]
    assert run(sys.executable, script, "init", "--worktree", str(queue), cwd=checkout,
               env={"SE_KERN": "off"}).returncode == 0
    direct = run(*command, cwd=checkout, env={"SE_KERN": "off"})
    refused = run(*command[:-1], str(tmp_path / "none"), cwd=checkout, env={"SE_KERN": "off"})
    assert (direct.returncode, refused.returncode) == (0, 1) and "Initialized: yes" in direct.stdout

    started = run(str(kern), "start", "--root", str(checkout), cwd=checkout)
    assert started.returncode == 0, started.stderr
    try:
        assert run(str(kern), "status", "--root", str(checkout), "--wait", "5s",
                   cwd=checkout).returncode == 0
        # SE_KERN=on refuses the direct path: these answers came through kern.
        through = run(*command, cwd=checkout, env={"SE_KERN": "on"})
        assert (through.returncode, through.stdout) == (0, direct.stdout), through.stderr
        through_refused = run(*command[:-1], str(tmp_path / "none"), cwd=checkout,
                              env={"SE_KERN": "on"})
        assert (through_refused.returncode, through_refused.stdout, through_refused.stderr) == (
            1, refused.stdout, refused.stderr)
        status = run(str(kern), "status", "--root", str(checkout), "--json", cwd=checkout)
        health = json.loads(status.stdout)["health"]
        assert sorted(health["instances"]) == GROUPS
        # The calls above waited for their component's attach; the other two attached alone.
        assert {"tickets"} <= set(health["attached"]) <= set(GROUPS)
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)

    after = run(*command, cwd=checkout, env={"SE_KERN": ""})
    assert (after.returncode, after.stdout) == (0, direct.stdout)
