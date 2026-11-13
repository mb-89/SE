"""SE's components against the real core, the suite beside se.toml `[tests.beside.se-components]`
(README "Commands as components"): where the `se` binary serves a checkout with SE's wiring,
`se status` lists SE's four Python command groups placed and attached beside its four Go components
(fleet, github, origin, retro) in process, an interactive command answers through the core as it
answers directly, and once the core has stopped it runs directly again; the Stop hook (README "Stop
hook") answers through the delivery component as stop-check answers directly.

It builds the `se` binary (kern's core plus SE's Go components, components/cmd/se), so it runs beside
the suite, after kern's tests have warmed Go's build cache, not in it (its file name keeps the suite
from collecting it): README "Test budget".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import quiet_git

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ["delivery", "integration", "issues", "overhaul", "render", "retrospective", "review",
          "scaffold", "tickets"]  # SE's Python command groups, each placed
GO = ["fleet", "github", "origin", "retro"]  # SE's Go components, in the se binary (components/README.md)


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "UV_SYSTEM_CERTS": "1", **(env or {})})


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout of its own for the core, SE's components, scripts and SDK linked into it, so the
    core's files and its lease never touch this checkout's own kern. It is a real git repository so
    the origin component reads its refs (the bare core refuses a wiring with a component it lacks;
    the se binary carries fleet, github, origin and retro)."""
    root = tmp_path / "se"
    quiet_git.init(root, "-b", "main")
    for part in ("components", "scripts", "kern"):
        try:
            (root / part).symlink_to(ROOT / part, target_is_directory=True)
        except OSError as error:  # Windows without the right to make links
            pytest.skip(f"no symlink: {error}")
    (root / "wiring.toml").write_bytes((ROOT / "wiring.toml").read_bytes())
    return root


@pytest.fixture(scope="module")
def se_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    binary = tmp_path_factory.mktemp("se") / ("se.exe" if os.name == "nt" else "se")
    built = run("go", "build", "-o", str(binary), "./cmd/se", cwd=ROOT / "components")
    assert built.returncode == 0, built.stderr
    return binary


def test_kern_lists_ses_components_and_a_command_answers_through_it_and_without_it(
        checkout: Path, tmp_path: Path, se_binary: Path) -> None:
    kern = se_binary
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
        # The four Python groups placed beside SE's four Go components in the se binary.
        assert sorted(health["instances"]) == sorted(GROUPS + GO)
        # The Go components run in process (not "attached"); the calls above waited for their
        # command's component to attach, and the other placed ones attached alone.
        assert {"tickets"} <= set(health["attached"]) <= set(GROUPS)
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)

    after = run(*command, cwd=checkout, env={"SE_KERN": ""})
    assert (after.returncode, after.stdout) == (0, direct.stdout)


def worker_checkout(root: Path) -> Path:
    """A worker's checkout on its branch, its ticket queue for a work issue."""
    root.mkdir(parents=True)
    quiet_git.init(root, "-b", "main")
    for args in (("config", "user.name", "Worker test"),
                 ("config", "user.email", "worker-test@example.invalid"), ("commit", "-q",
                 "--allow-empty", "-m", "baseline"), ("checkout", "-q", "-b", "feat/example-20261113")):
        assert run("git", *args, cwd=root).returncode == 0
    (root / ".se" / "work").mkdir(parents=True)
    (root / ".se" / "work" / "body-read.json").write_text('{"sha256": "0"}\n', encoding="utf-8")
    return root


@pytest.mark.skipif(shutil.which("bash") is None, reason="se_hook.sh runs in bash")
def test_a_stop_answers_through_the_delivery_component_as_stop_check_answers_directly(
        checkout: Path, tmp_path: Path, se_binary: Path) -> None:
    kern = se_binary
    worker = worker_checkout(tmp_path / "worker")
    no_gh = tmp_path / "no-gh"  # gh refuses to sign in on both paths: they judge by the answer file
    no_gh.mkdir()
    (no_gh / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (no_gh / "gh").chmod(0o755)
    env = {"PATH": f"{no_gh}{os.pathsep}{os.environ['PATH']}"}
    bare = tmp_path / "bare"  # a project whose session start named no kern
    (bare / ".git").mkdir(parents=True)
    hook = ["bash", str(checkout / "scripts" / "se_hook.sh"), "Stop"]
    event = json.dumps({"session_id": "s1", "hook_event_name": "Stop", "cwd": str(worker),
                        "stop_hook_active": False})

    def stop(project: Path) -> tuple[str, float]:
        (worker / ".se" / "work" / "stop-refusals.json").unlink(missing_ok=True)
        began = time.perf_counter()
        said = subprocess.run(hook, input=event, capture_output=True, text=True, timeout=60,
                              env={**os.environ, **env, "CLAUDE_PROJECT_DIR": str(project)})
        took = time.perf_counter() - began
        assert said.returncode == 0, said.stderr
        return said.stdout, took

    started = run(str(kern), "start", "--root", str(checkout), cwd=checkout, env=env)
    assert started.returncode == 0, started.stderr
    (checkout / ".se" / ".runtime" / "kern.path").write_text(f"{kern}\n", encoding="utf-8")
    try:
        for _ in range(600):  # the delivery component's process attaches within seconds
            status = run(str(kern), "status", "--root", str(checkout), "--json", cwd=checkout)
            if status.returncode == 0 and "delivery" in (json.loads(status.stdout)["health"]["attached"] or []):
                break
            time.sleep(0.1)
        else:
            pytest.fail("the delivery component never attached")
        description = tmp_path / "description.md"
        description.write_text("Fixes it, no report\n", encoding="utf-8")
        states = {"no pull request recorded": None, "a description without a report": description}
        for state, recorded in states.items():
            if recorded is not None:
                run(sys.executable, str(checkout / "scripts" / "work_tickets.py"), "stop-check",
                    "--pull", "7", "--pr-description", str(recorded), "--worktree", str(worker),
                    cwd=worker, env={**env, "SE_KERN": "off"})
            direct, direct_took = stop(bare)
            through, through_took = stop(checkout)
            (worker / ".se" / "work" / "stop-refusals.json").unlink(missing_ok=True)
            asked = subprocess.run([str(kern), "hook", "Stop", "--root", str(checkout),
                                    "--wait", "10s", "--unanswered", "3"], input=event,
                                   capture_output=True, text=True, timeout=60)
            assert asked.returncode == 0, f"{state}: no command of kern's answered: {asked.stderr}"
            assert through == direct == asked.stdout and direct, state
            print(f"{state}: through kern {through_took * 1000:.1f} ms, "
                  f"directly {direct_took * 1000:.1f} ms")
        assert json.loads(direct)["decision"] == "block"
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)
