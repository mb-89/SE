"""The refresh at the session's start (README "Start and refresh"): an installed SE one release behind
moves to the latest release in the same start, and the core starts from the moved tree's pins; a
remote that cannot be read starts the session with the SE it has, in one line.

Real git, the real bootstrap.sh and se_start.py; only the core is a fake binary that logs its calls.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import quiet_git
from shell_paths import BASH, WINDOWS, sh

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("uv") is None,
                                reason="bootstrap.sh runs in bash and runs se_start.py through uv")
# What an installed SE's start reads: its scripts, its manifest and release pins, its layout.
TREE = ("scripts", "se.toml", ".claude-plugin", "agents", "skills", "components/release.toml", ".gitignore")
FAKE_SE = """#!/bin/sh
input=""
[ "$1" = hook ] && input=" <<$(cat)"
echo "${0##*/} $*$input" >> "$HOME/calls"
exit 0
"""
START = '{"session_id":"s1","hook_event_name":"SessionStart"}'


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def release(origin: Path, version: str, binary: str) -> None:
    """Commit SE at `version` with its se binary pinned at `binary`, and tag it v<version>."""
    manifest = origin / "se.toml"
    text = manifest.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("version = "))
    manifest.write_text(text.replace(old, f'version = "{version}"', 1), encoding="utf-8", newline="\n")
    pins = origin / "components" / "release.toml"
    text = pins.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("version = "))
    pins.write_text(text.replace(old, f'version = "{binary}"', 1), encoding="utf-8", newline="\n")
    git(origin, "add", "-A")
    git(origin, "-c", "user.name=alice", "-c", "user.email=alice@example.com", "commit", "-q", "-m", f"v{version}")
    git(origin, "tag", f"v{version}")


@pytest.fixture
def behind(tmp_path):
    """SE's origin at 5.0.1 (binary se 0.2.0) and a plugin install cloned from it at 5.0.0 (se 0.1.0),
    as a cloud environment's cached setup script left it: one release behind."""
    origin = quiet_git.init(tmp_path / "origin", "-b", "main")
    for name in TREE:
        source, target = ROOT / name, origin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target)
    release(origin, "5.0.0", "0.1.0")
    home = tmp_path / "home"
    plugin = quiet_git.clone(origin.as_uri(), home / ".claude" / "skills" / "se", "--depth", "1")
    release(origin, "5.0.1", "0.2.0")
    project = tmp_path / "project"
    project.mkdir()
    (project / "se.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8", newline="\n")
    for binary in ("0.1.0", "0.2.0"):
        fake = home / ".se" / "bin" / f"se-{binary}{'.exe' if WINDOWS else ''}"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text(FAKE_SE, encoding="utf-8", newline="\n")
        fake.chmod(0o755)
    return home, plugin, project, tmp_path


def start(home: Path, plugin: Path, project: Path, base: Path) -> dict:
    """The plugin's SessionStart hook, as Claude Code runs it: its greeting's JSON."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CLAUDE_PROJECT_DIR": sh(project),
           "SE_START_CACHE": str(base / "start-check.json"), "SE_METRICS": str(base / "metrics.jsonl")}
    env.pop("SE_START_REFRESHED", None)
    env.pop("CLAUDE_ENV_FILE", None)
    result = subprocess.run([BASH, sh(plugin / "scripts" / "bootstrap.sh"), "--hook"], env=env, input=START,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def calls(home: Path) -> list[str]:
    """The core's start and the session's start handed to it, by binary (the greeting also asks
    its status)."""
    log = home / "calls"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [line.split(" --root ")[0] for line in lines if " status " not in line]


def test_a_plugin_one_release_behind_moves_at_start_and_starts_the_core_from_the_new_pins(behind):
    home, plugin, project, base = behind
    greeting = start(home, plugin, project, base)["systemMessage"].splitlines()
    assert git(plugin, "describe", "--tags", "--exact-match") == "v5.0.1"
    assert greeting[0] == f"SE: 5.0.0 -> 5.0.1, refreshed at this start ({plugin.resolve().as_posix()})"
    assert greeting[1].startswith("SE 5.0.1 started: ")
    assert calls(home) == ["se-0.2.0 start", "se-0.2.0 hook SessionStart"]
    named = (project / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8").strip()
    assert Path(named).name.startswith("se-0.2.0")
    # The next start has nothing to move and says nothing of it.
    (home / "calls").unlink()
    again = start(home, plugin, project, base)["systemMessage"].splitlines()
    assert again[0].startswith("SE 5.0.1 started: ")
    assert calls(home) == ["se-0.2.0 start", "se-0.2.0 hook SessionStart"]


def test_a_remote_that_cannot_be_read_starts_with_the_plugin_it_has_in_one_line(behind):
    home, plugin, project, base = behind
    git(plugin, "remote", "set-url", "origin", (base / "gone").as_uri())
    greeting = start(home, plugin, project, base)["systemMessage"].splitlines()
    assert git(plugin, "describe", "--tags", "--exact-match") == "v5.0.0"
    assert greeting[0].startswith("SE: no refresh at start, this session starts with SE 5.0.0: cannot reach ")
    assert greeting[1].startswith("SE 5.0.0 started: ")
    assert calls(home) == ["se-0.1.0 start", "se-0.1.0 hook SessionStart"]
