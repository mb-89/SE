"""se_hook.sh posts one session event to the kern SE pins, and fails open (README "Kern")."""
from pathlib import Path
import os
import subprocess
import time

import pytest
from shell_paths import BASH, sh

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "se_hook.sh"
pytestmark = pytest.mark.skipif(BASH is None, reason="se_hook.sh runs in bash")
# A fake kern: logs its arguments and its stdin, and answers as told by $HOME/answer and $HOME/code.
FAKE_KERN = """#!/bin/sh
echo "$* <<$(cat)" >> "$HOME/calls"
[ -f "$HOME/answer" ] && cat "$HOME/answer"
[ -f "$HOME/noise" ] && echo "kern hook: no core runs" >&2
[ -f "$HOME/code" ] && exit "$(cat "$HOME/code")"
exit 0
"""
# A fake uv where bootstrap.sh installs it: logs its arguments and stdin, and answers as stop-check.
FAKE_UV = """#!/bin/sh
echo "$* <<$(cat)" >> "$HOME/fallback"
echo '{"decision": "block", "reason": "from the fallback"}'
"""
STOP = '{"session_id":"s1","hook_event_name":"Stop","cwd":"/w"}'
EVENT = '{"session_id":"s1","hook_event_name":"PreToolUse","tool_name":"Bash"}'


def hook(home: Path, project: Path, *args: str, event: str = EVENT) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": sh(project)}
    return subprocess.run([BASH, sh(SCRIPT), *args], env=env, input=event, capture_output=True, text=True,
                          timeout=30)


@pytest.fixture
def machine(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    (home / ".se" / "bin").mkdir(parents=True)
    uv = home / ".local" / "bin" / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text(FAKE_UV, encoding="utf-8", newline="\n")
    uv.chmod(0o755)
    return home, project


def install(home: Path, project: Path) -> Path:
    """The binary bootstrap.sh named for the project at the session's start."""
    binary = home / ".se" / "bin" / "kern-0.0.0"
    binary.write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    binary.chmod(0o755)
    named = project / ".se" / ".runtime" / "kern.path"
    named.parent.mkdir(parents=True, exist_ok=True)
    named.write_text(f"{sh(binary)}\n", encoding="utf-8", newline="\n")
    return binary


def test_an_event_goes_to_the_pinned_kern_for_the_project_with_the_hosts_json(machine):
    home, project = machine
    install(home, project)
    result = hook(home, project, "PreToolUse")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {sh(project)} <<{EVENT}\n"


def test_kerns_answer_is_the_hooks_output_and_its_errors_stay_quiet(machine):
    home, project = machine
    install(home, project)
    (home / "answer").write_text('{"decision": "block"}\n', encoding="utf-8", newline="\n")
    (home / "noise").touch()
    result = hook(home, project, "PostToolUse")
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


def test_a_stop_kern_answers_is_its_output_and_runs_no_fallback(machine):
    home, project = machine
    install(home, project)
    (home / "answer").write_text('{"decision": "block", "reason": "from kern"}\n', encoding="utf-8", newline="\n")
    for event in ("Stop", "SubagentStop"):
        result = hook(home, project, event, event=STOP)
        assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from kern"}\n')
    calls = (home / "calls").read_text(encoding="utf-8").splitlines()
    assert calls[0] == f"hook Stop --root {sh(project)} --wait 10s --unanswered 3 <<{STOP}"
    assert not (home / "fallback").exists()
    (home / "answer").unlink()  # kern answered that the stop passes: nothing to say
    assert (hook(home, project, "Stop", event=STOP).stdout, (home / "fallback").exists()) == ("", False)


def test_a_stop_no_command_of_kerns_answers_falls_back_to_stop_check_with_the_hooks_json(machine):
    home, project = machine
    fallback = f"run --no-project --python >=3.11 python {sh(ROOT)}/scripts/work_tickets.py stop-check <<{STOP}"
    result = hook(home, project, "Stop", event=STOP)  # no session start named a binary
    assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    assert (home / "fallback").read_text(encoding="utf-8").splitlines() == [fallback]
    install(home, project)
    (home / "code").write_text("3", encoding="utf-8")  # kern: no command answered
    (home / "noise").touch()
    result = hook(home, project, "SubagentStop", event=STOP)
    assert (result.returncode, result.stdout, result.stderr) == (
        0, '{"decision": "block", "reason": "from the fallback"}\n', "")
    assert (home / "fallback").read_text(encoding="utf-8").splitlines() == [fallback, fallback]


# Copilot's payloads (scripts/hosts.sh): camelCase, and its CLI hooks may set no project variable.
COPILOT_TOOL = '{"sessionId":"s1","timestamp":1,"cwd":"%s","toolName":"bash","toolArgs":"{}"}'
COPILOT_STOP = '{"sessionId":"s1","timestamp":1,"cwd":"%s","transcriptPath":"/t","stopReason":"end_turn"}'


def copilot_hook(home: Path, event: str, payload: str, **variables: str) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", **variables}
    return subprocess.run([BASH, sh(SCRIPT), event], env=env, input=payload, capture_output=True, text=True,
                          timeout=30)


def test_a_copilot_event_without_a_project_variable_goes_to_the_cwds_kern_in_snake_case(machine):
    home, project = machine
    install(home, project)
    result = copilot_hook(home, "PreToolUse", COPILOT_TOOL % sh(project))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    handed = '{"session_id":"s1","timestamp":1,"cwd":"%s","tool_name":"bash","toolArgs":"{}"}' % sh(project)
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {sh(project)} <<{handed}\n"


def test_without_a_project_variable_or_a_cwd_the_project_is_the_working_directory(machine, tmp_path):
    home, project = machine
    install(home, project)
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "SE_HOOK_HOST": "copilot"}
    result = subprocess.run([BASH, sh(SCRIPT), "PostToolUse"], env=env, input='{"session_id":"s1"}',
                            capture_output=True, text=True, timeout=30, cwd=project)
    assert result.returncode == 0, result.stderr
    assert (home / "calls").read_text(encoding="utf-8").startswith("hook PostToolUse --root ")


def test_copilots_pascal_case_stop_reaches_stop_check_as_claudes_does(machine):
    """.github/hooks/se.json registers `Stop`: Copilot then sends a Claude-shaped payload."""
    home, project = machine
    stop = '{"hook_event_name":"Stop","session_id":"s1","cwd":"%s","stop_hook_active":false}' % sh(project)
    result = copilot_hook(home, "Stop", stop, SE_HOOK_HOST="copilot")
    assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    [line] = (home / "fallback").read_text(encoding="utf-8").splitlines()
    assert line.endswith(f"work_tickets.py stop-check <<{stop}")


def test_a_copilot_agent_stop_falls_back_to_stop_check_with_the_payload_in_snake_case(machine):
    home, project = machine
    result = copilot_hook(home, "Stop", COPILOT_STOP % sh(project))
    assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    handed = ('{"session_id":"s1","timestamp":1,"cwd":"%s","transcript_path":"/t","stop_reason":"end_turn"}'
              % sh(project))
    [line] = (home / "fallback").read_text(encoding="utf-8").splitlines()
    assert line.endswith(f"work_tickets.py stop-check <<{handed}")


# A late checkout (README "Cloud sessions"): a fake bootstrap.sh beside a copy of the hook logs each
# start it is asked for, with the checkout it was asked for and the hook's JSON.
FAKE_BOOTSTRAP = """#!/bin/sh
echo "$CLAUDE_PROJECT_DIR $* <<$(cat)" >> "$HOME/starts"
"""


def late_hook(home: Path, project: Path, cwd: Path, event: str = "PostToolUse") -> subprocess.CompletedProcess:
    scripts = home / "plugin" / "scripts"
    if not scripts.is_dir():
        scripts.mkdir(parents=True)
        (scripts / "se_hook.sh").write_bytes(SCRIPT.read_bytes())
        (scripts / "hosts.sh").write_bytes((SCRIPT.parent / "hosts.sh").read_bytes())
        (scripts / "bootstrap.sh").write_text(FAKE_BOOTSTRAP, encoding="utf-8", newline="\n")
    payload = f'{{"session_id":"s1","hook_event_name":"{event}","cwd":"{sh(cwd)}"}}'
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": sh(project)}
    return subprocess.run([BASH, sh(scripts / "se_hook.sh"), event], env=env, input=payload,
                          capture_output=True, text=True, timeout=30)


def starts(home: Path, count: int) -> list[str]:
    """The starts the fake bootstrap.sh logged, once `count` of them are in (it runs detached)."""
    log = home / "starts"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        if len(lines) >= count:
            return lines
        time.sleep(0.05)
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def clone(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    (path / "se.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (path / "src").mkdir()
    return path


def test_the_first_hook_in_a_late_checkout_starts_its_core_once_and_then_posts_to_it(machine):
    home, project = machine
    install(home, project)
    late = clone(home.parent / "SE")
    result = late_hook(home, project, late / "src")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    payload = f'{{"session_id":"s1","hook_event_name":"PostToolUse","cwd":"{sh(late / "src")}"}}'
    assert starts(home, 1) == [f"{sh(late)} --hook <<{payload}"]
    # The session's own core still takes the hook while the late one comes up; the claim, taken
    # anew only once ten minutes have passed, holds: a start would have written it again.
    claim = late / ".se" / ".runtime" / "late-start.claim"
    five_minutes_ago = time.time() - 300
    os.utime(claim, (five_minutes_ago, five_minutes_ago))
    assert late_hook(home, project, late).returncode == 0
    assert claim.stat().st_mtime == pytest.approx(five_minutes_ago)
    assert (home / "calls").read_text(encoding="utf-8").splitlines()[0].startswith(
        f"hook PostToolUse --root {sh(project)} <<")
    # Once the late start named its binary, the hooks there post to the late checkout's core.
    install(home, late)
    late_hook(home, project, late / "src")
    assert (home / "calls").read_text(encoding="utf-8").splitlines()[-1].startswith(
        f"hook PostToolUse --root {sh(late)} <<")
    assert claim.stat().st_mtime == pytest.approx(five_minutes_ago)
    assert starts(home, 1) == [f"{sh(late)} --hook <<{payload}"]


def test_no_late_start_in_the_project_or_a_checkout_without_se(machine):
    home, project = machine
    (project / ".git").mkdir()
    (project / "se.toml").write_text("", encoding="utf-8")
    other = home.parent / "other"
    (other / ".git").mkdir(parents=True)
    for cwd in (project, other, home.parent):
        assert late_hook(home, project, cwd).returncode == 0
    # A start claims before it runs, so no claim is no start.
    assert not (project / ".se").exists() and not (other / ".se").exists()
    assert not (home / "starts").exists()


def test_a_late_claim_older_than_ten_minutes_is_taken_anew(machine):
    home, project = machine
    late = clone(home.parent / "SE")
    late_hook(home, project, late)
    assert len(starts(home, 1)) == 1
    claim = late / ".se" / ".runtime" / "late-start.claim"
    stale = time.time() - 660
    os.utime(claim, (stale, stale))
    late_hook(home, project, late)
    assert len(starts(home, 2)) == 2 and claim.stat().st_mtime > stale + 300
