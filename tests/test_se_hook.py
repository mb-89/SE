"""se_hook.sh posts one session event to the kern SE pins, and fails open (README "Kern")."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
from shell_paths import BASH, sh
import waiting

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
if [ -f "$HOME/fallback-answer" ]; then cat "$HOME/fallback-answer"; exit 0; fi
echo '{"decision": "block", "reason": "from the fallback"}'
"""
STOP = '{"session_id":"s1","hook_event_name":"Stop","cwd":"/w"}'
EVENT = '{"session_id":"s1","hook_event_name":"PreToolUse","tool_name":"Bash"}'


# What runs as a process here, and why: se_hook.sh is bash, and every test below proves its own
# logic, so each runs it (as the host does) against the fake programs it execs; one is its entry.
def shell(logic: str) -> pytest.MarkDecorator:
    return pytest.mark.spawns(f"shell: scripts/se_hook.sh's {logic} is bash, run only as a process")


KERN = shell("call of the kern bootstrap.sh named, and its fail-open, against a fake kern it execs")
STOPS = shell("Stop answer, kern's else stop-check's through uv, against a fake kern and uv it runs")
COPILOT = shell("handling of Copilot's payloads (hosts.sh: snake_case, project, host field)")
WARNING = shell("answer of a stop's advice, under Copilot a warning on stderr with exit code 2")
LATE = shell("late-checkout start, claimed and detached, against a fake bootstrap.sh")
CORE = shell("SE_HOOK_CORE switch")
GATE = shell("file-gate filter (templates-files, file tools in the project), against a fake uv")
BEAT = shell("claim beat (its due line and claim, a detached work_tickets.py beat), against a fake uv")
PLUGIN = pytest.mark.spawns("shell: .github/plugin/hooks.json's bash and PowerShell commands, which pick "
                            "PLUGIN_ROOT's script, run only as a process in the host's shell")


def hook(home: Path, project: Path, *args: str, event: str = EVENT, **variables: str) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": sh(project), **variables}
    return subprocess.run([BASH, sh(SCRIPT), *args], env=env, input=event, capture_output=True, text=True,
                          timeout=30)


@pytest.fixture
def machine(tmp_path):
    bell = BELLS[tmp_path / "home"] = waiting.Bell()
    (tmp_path / "bell").write_text(str(bell.port), encoding="utf-8")
    yield machine_in(tmp_path)
    BELLS.pop(tmp_path / "home").close()


# The bell of each test's machine, by its home: the fake bootstrap.sh rings it as it starts.
BELLS: dict[Path, waiting.Bell] = {}


def machine_in(tmp_path: Path) -> tuple[Path, Path]:
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


@pytest.mark.spawns("entry: scripts/se_hook.sh")
def test_an_event_goes_to_the_pinned_kern_for_the_project_with_the_hosts_json(machine):
    home, project = machine
    install(home, project)
    result = hook(home, project, "PreToolUse")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {sh(project)} <<{EVENT}\n"


@KERN
def test_kerns_answer_is_the_hooks_output_and_its_errors_stay_quiet(machine):
    home, project = machine
    install(home, project)
    (home / "answer").write_text('{"decision": "block"}\n', encoding="utf-8", newline="\n")
    (home / "noise").touch()
    result = hook(home, project, "PostToolUse")
    assert result.returncode == 0 and result.stdout == '{"decision": "block"}\n' and result.stderr == ""


@KERN
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


@STOPS
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


@STOPS
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


@COPILOT
def test_a_copilot_event_without_a_project_variable_goes_to_the_cwds_kern_in_snake_case(machine):
    home, project = machine
    install(home, project)
    result = copilot_hook(home, "PreToolUse", COPILOT_TOOL % sh(project))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    handed = '{"session_id":"s1","timestamp":1,"cwd":"%s","tool_name":"bash","toolArgs":"{}"}' % sh(project)
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {sh(project)} <<{handed}\n"


@COPILOT
def test_without_a_project_variable_or_a_cwd_the_project_is_the_working_directory(machine, tmp_path):
    home, project = machine
    install(home, project)
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "SE_HOOK_HOST": "copilot"}
    result = subprocess.run([BASH, sh(SCRIPT), "PostToolUse"], env=env, input='{"session_id":"s1"}',
                            capture_output=True, text=True, timeout=30, cwd=project)
    assert result.returncode == 0, result.stderr
    assert (home / "calls").read_text(encoding="utf-8").startswith("hook PostToolUse --root ")


@COPILOT
def test_copilots_pascal_case_stop_reaches_stop_check_as_claudes_does(machine):
    """.github/hooks/se.json registers `Stop`: Copilot then sends a Claude-shaped payload."""
    home, project = machine
    stop = '{"hook_event_name":"Stop","session_id":"s1","cwd":"%s","stop_hook_active":false}' % sh(project)
    result = copilot_hook(home, "Stop", stop, SE_HOOK_HOST="copilot")
    assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    [line] = (home / "fallback").read_text(encoding="utf-8").splitlines()
    assert line.endswith(f'work_tickets.py stop-check <<{{"se_host":"copilot",{stop[1:]}')


@COPILOT
def test_a_copilot_agent_stop_falls_back_to_stop_check_with_the_payload_in_snake_case(machine):
    home, project = machine
    result = copilot_hook(home, "Stop", COPILOT_STOP % sh(project))
    assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    handed = ('{"se_host":"copilot","session_id":"s1","timestamp":1,"cwd":"%s","transcript_path":"/t",'
              '"stop_reason":"end_turn"}' % sh(project))
    [line] = (home / "fallback").read_text(encoding="utf-8").splitlines()
    assert line.endswith(f"work_tickets.py stop-check <<{handed}")


# The Stop hook's advice under Copilot (docs/copilot.md "What a session costs"): stop-check's
# systemMessage, as json.dumps writes it, becomes Copilot's hook warning, stderr with exit code 2;
# `\"`, `\\` and `\n` are unescaped, a `\uXXXX` stays as it is.
ADVICE = '{"systemMessage": "se Stop hook, advice only: \\"x\\" undelivered\\nrun deliver now"}'
SAID = 'se Stop hook, advice only: "x" undelivered\nrun deliver now\n'


@pytest.mark.parametrize("through", ("kern", "fallback"))
@WARNING
def test_under_copilot_a_stops_advice_is_a_hook_warning_never_output(machine, through):
    home, project = machine
    stop = '{"hook_event_name":"Stop","session_id":"s1","cwd":"%s"}' % sh(project)
    if through == "kern":
        install(home, project)
        (home / "answer").write_text(ADVICE + "\n", encoding="utf-8", newline="\n")
    else:
        (home / "fallback-answer").write_text(ADVICE + "\n", encoding="utf-8", newline="\n")
    result = copilot_hook(home, "Stop", stop, SE_HOOK_HOST="copilot")
    assert (result.returncode, result.stdout, result.stderr) == (2, "", SAID)
    handed = (home / ("calls" if through == "kern" else "fallback")).read_text(encoding="utf-8")
    assert f'<<{{"se_host":"copilot",{stop[1:]}' in handed


@WARNING
def test_under_claude_code_a_stops_advice_stays_its_output(machine):
    home, project = machine
    install(home, project)
    (home / "answer").write_text(ADVICE + "\n", encoding="utf-8", newline="\n")
    result = hook(home, project, "Stop", event=STOP)
    assert (result.returncode, result.stdout, result.stderr) == (0, ADVICE + "\n", "")
    assert "se_host" not in (home / "calls").read_text(encoding="utf-8")


@COPILOT
def test_an_empty_copilot_stop_payload_gets_the_host_field_alone(machine):
    home, project = machine
    install(home, project)
    result = copilot_hook(home, "Stop", "{ }", SE_HOOK_HOST="copilot", CLAUDE_PROJECT_DIR=sh(project))
    assert result.returncode == 0, result.stderr
    assert (home / "calls").read_text(encoding="utf-8").endswith('<<{"se_host":"copilot" }\n')


# A late checkout (README "Cloud sessions"): a fake bootstrap.sh beside a copy of the hook logs each
# start it is asked for, with the checkout it was asked for and the hook's JSON.
# The detached start of bootstrap.sh: logs its arguments and stdin, then rings the test's bell
# (tests/waiting.py), found beside the home.
FAKE_BOOTSTRAP = """#!/bin/sh
echo "$CLAUDE_PROJECT_DIR $* <<$(cat)" >> "$HOME/starts"
"@PYTHON@" -c "@RING@" "$(cat "$HOME/../bell")" started
""".replace("@PYTHON@", sh(Path(sys.executable))).replace("@RING@", waiting.RING)


def late_hook(home: Path, project: Path, cwd: Path, event: str = "PostToolUse", settle: bool = False,
              **variables: str) -> subprocess.CompletedProcess:
    """Run the hook in a late checkout's setting. With `settle`, off Windows, return only once the
    hook and every process it started have exited: each inherits the write end of a pipe, the
    detached start of bootstrap.sh among them, so the read end's end of file means all are gone.
    Windows cannot pass that descriptor; there `settle` changes nothing (`waiting.settled_run`)."""
    scripts = home / "plugin" / "scripts"
    if not scripts.is_dir():
        scripts.mkdir(parents=True)
        (scripts / "se_hook.sh").write_bytes(SCRIPT.read_bytes())
        (scripts / "hosts.sh").write_bytes((SCRIPT.parent / "hosts.sh").read_bytes())
        (scripts / "bootstrap.sh").write_text(FAKE_BOOTSTRAP, encoding="utf-8", newline="\n")
    payload = f'{{"session_id":"s1","hook_event_name":"{event}","cwd":"{sh(cwd)}"}}'
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": sh(project), **variables}
    command = [BASH, sh(scripts / "se_hook.sh"), event]
    run = waiting.settled_run if settle else subprocess.run
    return run(command, env=env, input=payload, capture_output=True, text=True, timeout=30)


def starts(home: Path, count: int) -> list[str]:
    """The starts the fake bootstrap.sh logged, once `count` of them rang the test's bell (it runs
    detached)."""
    BELLS[home].wait(lambda heard: len(heard) >= count)
    log = home / "starts"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def clone(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    (path / "se.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (path / "src").mkdir()
    return path


@LATE
def test_the_first_hook_in_a_late_checkout_starts_its_core_once_and_then_posts_to_it(machine):
    home, project = machine
    install(home, project)
    late = clone(home.parent / "SE")
    result = late_hook(home, project, late / "src", settle=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    payload = f'{{"session_id":"s1","hook_event_name":"PostToolUse","cwd":"{sh(late / "src")}"}}'
    # The positive control of the settle: once settled, the detached start is in the log, read once.
    logged = (home / "starts").read_text(encoding="utf-8").splitlines() if os.name != "nt" else starts(home, 1)
    assert logged == [f"{sh(late)} --hook <<{payload}"]
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


@LATE
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


@LATE
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


# SE_HOOK_CORE (README "Machine-local `~/.se/local.toml`"): exactly `off`, in any case, keeps the
# hooks from the core; every other value, the empty string among them, leaves them as unset.
OFF_VALUES = ("off", "OFF", "Off")
ON_VALUES = ("", " off", "off ", "0", "false", "on")


def outcome(home: Path, result: subprocess.CompletedProcess) -> tuple:
    """What a hook did: its answer and what the fakes were handed."""
    read = lambda name: (home / name).read_text(encoding="utf-8") if (home / name).exists() else None
    return result.returncode, result.stdout, result.stderr, read("calls"), read("fallback")


@pytest.mark.parametrize(("name", "event"), (("PostToolUse", EVENT), ("Stop", STOP)))
@CORE
def test_an_empty_hook_core_variable_acts_as_unset(machine, name, event):
    home, project = machine
    install(home, project)
    (home / "code").write_text("3", encoding="utf-8")  # a Stop falls back to stop-check too
    seen = []
    for variables in ({}, {"SE_HOOK_CORE": ""}):
        for log in ("calls", "fallback"):
            (home / log).unlink(missing_ok=True)
        seen.append(outcome(home, hook(home, project, name, event=event, **variables)))
    assert seen[0] == seen[1]
    assert seen[0][3] is not None, "the core was posted to"


@pytest.mark.parametrize("value", OFF_VALUES)
@CORE
def test_hook_core_off_posts_to_no_core_and_passes_every_event_but_stop(machine, value):
    home, project = machine
    install(home, project)
    for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionEnd"):
        result = hook(home, project, event, SE_HOOK_CORE=value)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert not (home / "calls").exists() and not (home / "fallback").exists()


@pytest.mark.parametrize("value", OFF_VALUES)
@CORE
def test_hook_core_off_still_answers_a_stop_with_stop_check(machine, value):
    home, project = machine
    install(home, project)
    fallback = f"run --no-project --python >=3.11 python {sh(ROOT)}/scripts/work_tickets.py stop-check <<{STOP}"
    for event in ("Stop", "SubagentStop"):
        result = hook(home, project, event, event=STOP, SE_HOOK_CORE=value)
        assert (result.returncode, result.stdout) == (0, '{"decision": "block", "reason": "from the fallback"}\n')
    assert (home / "fallback").read_text(encoding="utf-8").splitlines() == [fallback, fallback]
    assert not (home / "calls").exists()


@CORE
def test_hook_core_off_under_copilot_a_stops_advice_is_still_a_hook_warning(machine):
    home, project = machine
    install(home, project)
    stop = '{"hook_event_name":"Stop","session_id":"s1","cwd":"%s"}' % sh(project)
    (home / "fallback-answer").write_text(ADVICE + "\n", encoding="utf-8", newline="\n")
    result = copilot_hook(home, "Stop", stop, SE_HOOK_HOST="copilot", SE_HOOK_CORE="off")
    assert (result.returncode, result.stdout, result.stderr) == (2, "", SAID)
    assert not (home / "calls").exists()


@pytest.mark.parametrize("value", ON_VALUES)
@CORE
def test_any_other_hook_core_value_posts_to_the_core_as_today(machine, value):
    home, project = machine
    install(home, project)
    result = hook(home, project, "PreToolUse", SE_HOOK_CORE=value)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert (home / "calls").read_text(encoding="utf-8") == f"hook PreToolUse --root {sh(project)} <<{EVENT}\n"


@CORE
def test_hook_core_off_starts_no_late_checkout_and_claims_none(machine):
    home, project = machine
    install(home, project)
    late = clone(home.parent / "SE")
    install(home, late)  # even a late checkout that named its binary is not posted to
    (late / ".se" / ".runtime" / "kern.path").unlink()
    result = late_hook(home, project, late / "src", settle=True, SE_HOOK_CORE="off")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert not (late / ".se" / ".runtime" / "late-start.claim").exists()
    # Settled, every process the hook started has exited, so a start would be in the log by now;
    # Windows cannot settle, and there the missing claim, which a start takes before it runs, is
    # the proof.
    assert not (home / "starts").exists() and not (home / "calls").exists()


# A Copilot plugin install's hooks (.github/plugin/hooks.json, scripts/se_plugin.py
# PLUGIN_HOOKS_FILE), run as the host runs them, in a folder holding its own `scripts/`: a stub of
# each script under PLUGIN_ROOT and another in the folder say which one ran.
PLUGIN_HOOKS = ROOT / ".github" / "plugin" / "hooks.json"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
PLUGIN_FORMS = ["bash", pytest.param("powershell", marks=pytest.mark.skipif(POWERSHELL is None,
                                                                           reason="no PowerShell here"))]


def plugin_hook(kind: str, event: str, folder: Path, plugin_root: str | None) -> subprocess.CompletedProcess:
    [entry] = json.loads(PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"][event]
    if kind == "bash":
        env = {"PATH": "/usr/bin:/bin", "HOME": sh(folder)}
        command = [BASH, "-c", entry["bash"]]
    else:  # the bash it runs is the one the scripts run in, first on PATH
        env = {**os.environ, "PATH": os.path.dirname(BASH) + os.pathsep + os.environ.get("PATH", "")}
        env.pop("PLUGIN_ROOT", None)
        command = [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", entry["powershell"]]
    if plugin_root is not None:
        env["PLUGIN_ROOT"] = plugin_root
    return subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True, timeout=60)


@pytest.fixture
def plugin_and_repository(tmp_path):
    plugin, repository = tmp_path / "plugin", tmp_path / "repository"
    for root, said in ((plugin, "plugin-ran"), (repository, "local-ran")):
        (root / "scripts").mkdir(parents=True)
        for script in ("bootstrap.sh", "se_hook.sh"):
            (root / "scripts" / script).write_text(f'echo "{said} {script} $*"\n', encoding="utf-8", newline="\n")
    return plugin, repository


def plugin_root(kind: str, plugin: Path) -> str:
    """PLUGIN_ROOT as each form's host sets it: bash's own path, PowerShell's with backslashes on Windows."""
    return sh(plugin) if kind == "bash" else str(plugin)


@pytest.mark.parametrize("kind", PLUGIN_FORMS)
@pytest.mark.parametrize("event, said", (("SessionStart", "bootstrap.sh --hook"), ("Stop", "se_hook.sh Stop")))
@PLUGIN
def test_a_plugin_hook_runs_only_the_plugins_own_script(plugin_and_repository, kind, event, said):
    plugin, repository = plugin_and_repository
    result = plugin_hook(kind, event, repository, plugin_root(kind, plugin))
    assert (result.returncode, result.stdout.strip()) == (0, f"plugin-ran {said}"), result.stderr


@pytest.mark.parametrize("kind", PLUGIN_FORMS)
@pytest.mark.parametrize("case", ("unset", "empty", "se checkout"))
@PLUGIN
def test_a_plugin_hook_runs_nothing_without_plugin_root_or_in_ses_checkout(plugin_and_repository, kind, case):
    """No fallback to the folder's own scripts; in SE's checkout its repository hooks run its copy."""
    plugin, repository = plugin_and_repository
    root = {"unset": None, "empty": ""}.get(case, plugin_root(kind, plugin))
    if case == "se checkout":
        (repository / ".github" / "hooks").mkdir(parents=True)
        (repository / ".github" / "hooks" / "se.json").write_text("{}\n", encoding="utf-8")
    for event in ("SessionStart", "Stop"):
        result = plugin_hook(kind, event, repository, root)
        assert (result.returncode, result.stdout.strip()) == (0, ""), (event, result.stderr)


@pytest.mark.parametrize("kind", PLUGIN_FORMS)
@pytest.mark.parametrize(("code", "passed"), ((2, 2), (1, 0), (0, 0)))
@PLUGIN
def test_copilots_stop_hook_passes_the_warning_through_and_fails_open_else(
        plugin_and_repository, kind, code, passed):
    """Copilot shows a hook's stderr on exit code 2 and goes on; every other exit fails open."""
    plugin, repository = plugin_and_repository
    (plugin / "scripts" / "se_hook.sh").write_text(f"echo advice >&2; exit {code}\n", encoding="utf-8",
                                                    newline="\n")
    result = plugin_hook(kind, "Stop", repository, plugin_root(kind, plugin))
    assert result.returncode == passed and "advice" in result.stderr
    start = plugin_hook(kind, "SessionStart", repository, plugin_root(kind, plugin))
    assert start.returncode == 0


# The file gate's filter (README "Templates"): the file tools reach se_templates.py gate only where SE's
# start left `claimed` in templates-files, and only for a file in the project; the fake uv logs each run.

def file_event(tool: str, **given) -> str:
    return json.dumps({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": tool,
                       "tool_input": given})


def gate_runs(home: Path) -> int:
    log = home / "fallback"
    return log.read_text(encoding="utf-8").count("se_templates.py gate") if log.exists() else 0


@GATE
def test_file_tools_run_no_gate_without_the_starts_line_and_only_in_the_project_with_it(machine):
    home, project = machine
    install(home, project)
    inside, outside = sh(project / "book" / "s.md"), sh(project.parent / "else" / "s.md")
    calls = [file_event("Write", file_path=inside, content="x"),
             file_event("Edit", file_path=inside, old_string="a", new_string="b"),
             file_event("MultiEdit", file_path=inside, edits=[]),
             file_event("mcp__github__push_files", owner="o", repo="r", files=[]),
             file_event("mcp__github__create_or_update_file", owner="o", repo="r", path="s.md")]
    for event in calls:  # no template claims a path: no line, every call costs what it did
        result = hook(home, project, "PreToolUse", event=event)
        assert result.returncode == 0 and result.stdout == ""
    assert gate_runs(home) == 0 and (home / "calls").read_text(encoding="utf-8").count("hook ") == 5
    line = project / ".se" / ".runtime" / "templates-files"
    line.write_text("claimed\n", encoding="utf-8", newline="\n")
    for event in calls:
        assert hook(home, project, "PreToolUse", event=event).returncode == 0
    assert gate_runs(home) == 5
    for event in (file_event("Write", file_path=outside, content="x"),
                  file_event("Read", file_path=inside), file_event("Write", content="x"),
                  file_event("mcp__github__get_file_contents", owner="o", repo="r", path="s.md")):
        assert hook(home, project, "PreToolUse", event=event).returncode == 0
    assert gate_runs(home) == 5
    line.write_text("write\n", encoding="utf-8", newline="\n")  # the retired switch's line
    assert hook(home, project, "PreToolUse", event=calls[0]).returncode == 0
    assert gate_runs(home) == 5


# The claim's heartbeat (README "Workers"): a fake uv logs each beat the hook starts, detached, and
# rings the test's bell (tests/waiting.py), found beside the home.
FAKE_BEAT_UV = """#!/bin/sh
echo "$*" >> "$HOME/beats"
"@PYTHON@" -c "@RING@" "$(cat "$HOME/../bell")" beat
""".replace("@PYTHON@", sh(Path(sys.executable))).replace("@RING@", waiting.RING)


def beat_due(project: Path, due: float) -> Path:
    """The beat record intake writes, due at the Unix time `due`."""
    record = project / ".se" / "work" / "beat.yaml"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(f"# The claim's heartbeat\nissue: 5\nrepo: \"git.example/owner/repo\"\n"
                      f"beat: 2026-11-23T08:30Z\ndue: {int(due)}\n", encoding="utf-8", newline="\n")
    return record


def settled_hook(home: Path, project: Path, event: str = "PreToolUse") -> subprocess.CompletedProcess:
    """The hook, returned once it and every process it started have exited (off Windows)."""
    env = {"HOME": sh(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": sh(project)}
    payload = '{"session_id":"s1","hook_event_name":"%s","tool_name":"Bash"}' % event
    return waiting.settled_run([BASH, sh(SCRIPT), event], env=env, input=payload,
                               capture_output=True, text=True, timeout=30)


@BEAT
def test_a_tool_call_starts_the_claims_beat_once_it_is_due_and_before_reads_the_record_alone(machine):
    home, project = machine
    uv = home / ".local" / "bin" / "uv"
    uv.write_text(FAKE_BEAT_UV, encoding="utf-8", newline="\n")
    install(home, project)
    beats, claim = home / "beats", project / ".se" / "work" / "beat.claim"

    beat_due(project, time.time() + 3 * 3600)  # younger than half the timeout: nothing started
    for event in ("PreToolUse", "PostToolUse"):
        result = settled_hook(home, project, event)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert not beats.exists() and not claim.exists()
    assert (home / "calls").read_text(encoding="utf-8").count("hook PreToolUse") == 1  # kern still told

    beat_due(project, time.time() - 60)  # due: one beat, detached, its output in beat.log
    assert settled_hook(home, project).returncode == 0
    BELLS[home].wait(lambda heard: len(heard) >= 1)
    assert beats.read_text(encoding="utf-8").splitlines() == [
        f"run --no-project --python >=3.11 python {sh(ROOT)}/scripts/work_tickets.py beat "
        f"--worktree {sh(project)}"]
    assert claim.is_file() and (project / ".se" / "work" / "beat.log").is_file()

    # While its claim stands, the next tool calls start no second beat; `beat` removes the claim.
    assert settled_hook(home, project).returncode == 0
    assert len(beats.read_text(encoding="utf-8").splitlines()) == 1
    claim.unlink()
    assert settled_hook(home, project).returncode == 0
    BELLS[home].wait(lambda heard: len(heard) >= 2)
    assert len(beats.read_text(encoding="utf-8").splitlines()) == 2
