"""se_hook.sh posts one session event to the kern SE pins, and fails open (README "Kern")."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "se_hook.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="se_hook.sh runs in bash")
# A fake kern: logs its arguments and its stdin, and answers as told by $HOME/answer and $HOME/code.
FAKE_KERN = """#!/bin/sh
echo "$* <<$(cat)" >> "$HOME/calls"
[ -f "$HOME/answer" ] && cat "$HOME/answer"
[ -f "$HOME/noise" ] && echo "kern hook: no core runs" >&2
exit 0
"""
EVENT = '{"session_id":"s1","hook_event_name":"PreToolUse","tool_name":"Bash"}'


def hook(home: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, input=EVENT, capture_output=True, text=True,
                          timeout=30)


@pytest.fixture
def machine(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    (home / ".se" / "bin").mkdir(parents=True)
    return home, project


def install(home: Path, project: Path) -> Path:
    """The binary bootstrap.sh named for the project at the session's start."""
    binary = home / ".se" / "bin" / "kern-0.0.0"
    binary.write_text(FAKE_KERN, encoding="utf-8")
    binary.chmod(0o755)
    named = project / ".se" / ".runtime" / "kern.path"
    named.parent.mkdir(parents=True)
    named.write_text(f"{binary}\n", encoding="utf-8")
    return binary


def test_an_event_goes_to_the_pinned_kern_for_the_project_with_the_hosts_json(machine):
    home, project = machine
    install(home, project)
    result = hook(home, project, "PreToolUse")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {project} <<{EVENT}\n"


def test_kerns_answer_is_the_hooks_output_and_its_errors_stay_quiet(machine):
    home, project = machine
    install(home, project)
    (home / "answer").write_text('{"decision": "block"}\n', encoding="utf-8")
    (home / "noise").touch()
    result = hook(home, project, "Stop")
    assert result.returncode == 0 and result.stdout == '{"decision": "block"}\n' and result.stderr == ""


def test_without_kern_on_this_machine_the_hook_passes_silently(machine):
    home, project = machine
    result = hook(home, project, "PostToolUse")  # no session start named a binary
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    binary = install(home, project)
    binary.unlink()  # named, still being fetched
    result = hook(home, project, "PostToolUse")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    binary.write_text("not executable", encoding="utf-8")
    assert hook(home, project, "PostToolUse").returncode == 0
    assert not (home / "calls").exists()
