"""bootstrap.sh brings uv, Python and the modules into an empty home, and says what it cannot do."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile

import pytest
from shell_paths import BASH, WINDOWS, drop_tool, link_tools, sh, tool_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap.sh"
# The SE the core is handed as its home (`--home`), as bash names it.
SE_ROOT = sh(ROOT)
# SE's own binary, as se_modules.py app-binary answers it (components/release.toml): kern's core plus
# SE's Go components, the binary `se`. bootstrap fetches, builds and starts it, not the bare kern.
APP = tomllib.loads((ROOT / "components" / "release.toml").read_text(encoding="utf-8"))
NAME, APP_VERSION = APP["binary"], APP["version"]
# The download base app-binary answers: release.toml's path under the home origin names (se_home.py).
APP_BASE = "https://example.com/alice/project/" + APP["download"].replace("{version}", APP_VERSION)
BUILD_DIR, PACKAGE = "components", APP["package"]
TOOLS = ("bash", "sh", "dirname", "grep", "cat", "env", "chmod", "mkdir", "touch", "uname", "tail", "tar",
         "gzip", "sha256sum", "shasum", "setsid", "unzip", "mv", "rm", "ln", "cp", "find")
pytestmark = pytest.mark.skipif(BASH is None, reason="bootstrap.sh runs in bash")

# A fake uv: `python find` fails until `python install` ran; the core switch's read
# (se_modules.py hooks-core) runs the real script with this interpreter; SE's start prints a greeting unless
# `status-fails` exists; its refresh at start (tests/test_start_refresh.py) moves SE where
# `refresh-moves` exists, else has nothing to move, and is logged apart; its hooks at start say
# nothing, as where they are in place; every other call is logged.
FAKE_UV = """#!/bin/sh
case "$*" in *"se_start.py "*" start-refresh"*)
  echo refresh >> "$HOME/refreshes"
  [ -f "$HOME/refresh-moves" ] || exit 1
  echo "SE: 1.0.0 -> 1.0.1, refreshed at this start"; exit 0 ;;
esac
echo "uv $*" >> "$HOME/calls"
case "$*" in *"se_modules.py --local "*" hooks-core"*) shift 5; exec "@PYTHON@" "$@" ;; esac
case "$*" in *"se_start.py "*" start-hooks"*) exit 0 ;; esac
case "$*" in *se_start.py*) [ -f "$HOME/status-fails" ] && exit 1; echo '{"greeting": 1}'; exit 0 ;; esac
case "$*" in *"se_modules.py --root "*" app-binary"*) cat "$HOME/app-binary" 2>/dev/null; exit 0 ;; esac
case "$*" in *"se_modules.py --root "*" sync kern"*)
  [ -f "$HOME/kern-sync-fails" ] && { echo "error: module kern: git clone failed"; exit 1; }; exit 0 ;;
esac
case "$1 $2" in
  "python find") [ -f "$HOME/python" ] ;;
  "python install") touch "$HOME/python" ;;
esac
""".replace("@PYTHON@", sh(Path(sys.executable)))
INSTALLER = f"""mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/uv" <<'UV'
{FAKE_UV}UV
chmod +x "$HOME/.local/bin/uv"
"""
# A fake uv installer, as astral.sh's: puts uv into ~/.local/bin, or fails while "offline".
# The binary's release (README "Kern"): served from $HOME/se-release where it exists, else a 404 (22).
FAKE_CURL = f"""#!/bin/sh
echo "curl $*" >> "$HOME/calls"
[ -f "$HOME/offline" ] && exit 6
case "$*" in */releases/download/*)
  while [ "$1" != -o ]; do shift; done
  out="$2"; url="$3"
  [ -f "$HOME/se-release/${{url##*/}}" ] || exit 22
  cat "$HOME/se-release/${{url##*/}}" > "$out"; exit 0 ;;
esac
cat <<'INSTALLER'
{INSTALLER}INSTALLER
"""
# On Windows bootstrap.sh installs uv through PowerShell (astral.sh's install.ps1): the same fake.
FAKE_POWERSHELL = f"""#!/bin/sh
echo "powershell $*" >> "$HOME/calls"
[ -f "$HOME/offline" ] && exit 6
sh <<'INSTALLER'
{INSTALLER}INSTALLER
"""
UV_INSTALL = ("powershell -NoProfile -ExecutionPolicy ByPass -c irm https://astral.sh/uv/install.ps1 | iex"
              if WINDOWS else "curl -LsSf https://astral.sh/uv/install.sh")


def fake_bin(base: Path, *, git: bool = True) -> Path:
    """A PATH holding only the shell tools the script uses, a fake curl and, optionally, git."""
    # setsid, shasum and unzip are not everywhere; bootstrap.sh does without them
    folder = link_tools(base / "bin", TOOLS)
    for name, script in (("curl", FAKE_CURL), ("powershell", FAKE_POWERSHELL)):
        (folder / name).write_text(script, encoding="utf-8", newline="\n")
        (folder / name).chmod(0o755)
    if git:
        (folder / "git").write_text("#!/bin/sh\n", encoding="utf-8", newline="\n")
        (folder / "git").chmod(0o755)
    return folder


def run(home: Path, path: Path, project: Path, *args: str, stdin: str = "",
        **variables: str) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": tool_path(path), "CLAUDE_PROJECT_DIR": sh(project), **variables}
    return subprocess.run([BASH, sh(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60,
                          input=stdin)


def calls(home: Path) -> list[str]:
    log = home / "calls"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (project / ".git").mkdir()  # a checkout: the start's core step runs only inside one
    # se_modules.py app-binary: name, version, download base, build folder, package.
    (home / "app-binary").write_text(f"{NAME} {APP_VERSION} {APP_BASE} {BUILD_DIR} {PACKAGE}\n", encoding="utf-8",
                                     newline="\n")
    (project / "se.toml").write_text('[modules.obs]\nurl = "https://example.com/obs.git"\nref = "%s"\n' % ("0" * 40),
                                     encoding="utf-8", newline="\n")
    return home, project, tmp_path


# A wrapper of the kind a harness puts first on PATH (an rm guard): it records its call, then hands
# over to the next file of its name on PATH past its own entry.
WRAPPER = """#!/bin/sh
echo "wrapper $*" >> "@LOG@"
past=
IFS=:
for entry in $PATH; do
  if [ -n "$past" ] && [ -x "$entry/cat" ]; then exec "$entry/cat" "$@"; fi
  [ "$entry/cat" -ef "$0" ] && past=1
done
echo "cat: command not found" >&2
exit 127
"""


@pytest.mark.skipif(WINDOWS, reason="a shim runs its file by its path there: a wrapper finds no entry of its own")
def test_a_wrapper_first_on_path_still_reaches_the_tool_after_it_on_the_fake_path(tmp_path, monkeypatch):
    wrapper, log, text = tmp_path / "wrapper", tmp_path / "log", tmp_path / "text"
    wrapper.mkdir()
    (wrapper / "cat").write_text(WRAPPER.replace("@LOG@", str(log)), encoding="utf-8", newline="\n")
    (wrapper / "cat").chmod(0o755)
    text.write_text("through the wrapper\n", encoding="utf-8", newline="\n")
    monkeypatch.setenv("PATH", f"{wrapper}{os.pathsep}{os.environ['PATH']}")
    path = fake_bin(tmp_path)
    assert (path / "cat").resolve() == (wrapper / "cat").resolve(), "the wrapper stays first"
    env = {"PATH": tool_path(path)}
    result = subprocess.run([BASH, "-c", 'cat "$0"', str(text)], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout == "through the wrapper\n", result.stderr
    assert log.read_text(encoding="utf-8") == f"wrapper {text}\n"
    drop_tool(path, "cat")
    gone = subprocess.run([BASH, "-c", "command -v cat"], env=env, capture_output=True, text=True, timeout=60)
    assert gone.returncode != 0 and gone.stdout == ""


def test_an_empty_home_gets_uv_python_and_the_modules_and_a_second_start_is_quiet(machine):
    home, project, base = machine
    path = fake_bin(base)
    first = run(home, path, project)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "installing uv into" in first.stdout and "installing Python 3.11" in first.stdout
    log = calls(home)
    assert log[0] == UV_INSTALL
    assert "uv python install 3.11" in log
    sync = [line for line in log if line.startswith("uv run")]
    assert sync == [f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_modules.py --root {sh(project)} sync"]
    (home / "calls").unlink()
    second = run(home, path, project)
    assert second.returncode == 0 and second.stdout == ""
    assert not any(line.startswith(("curl", "powershell", "uv python install")) for line in calls(home))


def test_an_interrupted_first_start_finishes_when_run_again(machine):
    home, project, base = machine
    path = fake_bin(base)
    (home / "offline").touch()
    offline = run(home, path, project)
    assert offline.returncode == 1
    assert "installing uv failed (offline?). Run this again when online" in offline.stdout
    (home / "offline").unlink()
    again = run(home, path, project)
    assert again.returncode == 0, again.stdout + again.stderr
    assert (home / ".local" / "bin" / "uv").is_file() and (home / "python").is_file()


def test_missing_git_names_the_one_line_to_run(machine):
    home, project, base = machine
    result = run(home, fake_bin(base, git=False), project)
    assert result.returncode == 1
    assert result.stdout.startswith("se bootstrap: git is missing; se's tools run git. Run: ")
    assert calls(home) == []


def test_a_project_without_modules_syncs_nothing(machine):
    home, project, base = machine
    (project / "se.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
    assert run(home, fake_bin(base), project).returncode == 0
    assert not any(line.startswith("uv run") for line in calls(home))


def test_the_session_finds_uv_through_claudes_env_file(machine):
    home, project, base = machine
    env_file = base / "env"
    env = {"HOME": sh(home), "PATH": tool_path(fake_bin(base)), "CLAUDE_PROJECT_DIR": sh(project),
           "CLAUDE_ENV_FILE": str(env_file)}
    subprocess.run([BASH, sh(SCRIPT)], env=env, check=True, capture_output=True, timeout=60)
    assert env_file.read_text(encoding="utf-8") == f'export PATH="{sh(home)}/.local/bin:$PATH"\n'
    assert os.access(home / ".local" / "bin" / "uv", os.X_OK)


def test_the_hook_ends_with_ses_greeting_carrying_what_bootstrap_said(machine):
    home, project, base = machine
    result = run(home, fake_bin(base), project, "--hook")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == '{"greeting": 1}\n'  # the JSON alone: Claude Code parses the hook's stdout
    start = [line for line in calls(home) if "se_start.py" in line and " status " in line]
    assert len(start) == 1
    assert start[0].startswith(f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_start.py "
                               f"--root {sh(project)} status --hook --note se bootstrap: installing uv into ")
    assert "--note se bootstrap: installing Python 3.11" in start[0]


def test_the_hook_sets_the_projects_commit_identity_at_start(machine):
    """A fresh clone carries the host's default identity until something sets the project's: the
    session's start does, as setup.sh does, through work_tickets.py identity."""
    home, project, base = machine
    path = fake_bin(base)
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    identity = [line for line in calls(home) if "work_tickets.py" in line]
    assert identity == [f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/work_tickets.py "
                        f"identity --worktree {sh(project)}"]
    assert calls(home).index(identity[0]) < next(
        index for index, line in enumerate(calls(home)) if "se_start.py" in line and " status " in line)
    (home / "calls").unlink()
    assert run(home, path, project).returncode == 0  # outside a session's start: setup.sh's
    assert not any("work_tickets.py" in line for line in calls(home))


@pytest.mark.parametrize("host", ["claude", "copilot camelCase", "copilot PascalCase"])
def test_the_hook_points_the_projects_hooks_at_se_at_start_under_each_hosts_payload(machine, host):
    """A fresh clone has no core.hooksPath until setup.sh runs: the session's start sets it, under
    Claude's payload (its project variable) and Copilot's two shapes (the payload's cwd), through
    se_start.py start-hooks, which leaves a set one alone (tests/test_se_start.py)."""
    home, project, base = machine
    path = fake_bin(base)
    if host == "claude":
        result = run(home, path, project, "--hook", stdin=START)
    elif host == "copilot camelCase":
        result = subprocess.run([BASH, sh(SCRIPT), "--hook"], env={"HOME": sh(home), "PATH": tool_path(path)},
                                capture_output=True, text=True, timeout=60, input=COPILOT_START % sh(project),
                                cwd=base)
    else:
        result = copilot_start(home, path, base, PASCAL_START % sh(project))
    assert result.returncode == 0, result.stdout + result.stderr
    hooks = [line for line in calls(home) if " start-hooks" in line]
    assert hooks == [f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_start.py "
                     f"--root {sh(project)} start-hooks"]
    assert calls(home).index(hooks[0]) < next(
        index for index, line in enumerate(calls(home)) if "se_start.py" in line and " status " in line)
    (home / "calls").unlink()
    assert run(home, path, project).returncode == 0  # outside a session's start: setup.sh's
    assert not any("start-hooks" in line for line in calls(home))


def test_a_start_that_moved_se_runs_once_more_carrying_what_it_said(machine):
    home, project, base = machine
    (home / "refresh-moves").touch()
    result = run(home, fake_bin(base), project, "--hook", stdin=START)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert (home / "refreshes").read_text(encoding="utf-8").splitlines() == ["refresh"]  # once: no loop
    notes = greeting_call(home).split(" status --hook ")[1]
    assert notes.startswith("--note se bootstrap: installing uv into ")
    assert "--note se bootstrap: installing Python 3.11" in notes
    assert notes.index("installing Python") < notes.index("--note SE: 1.0.0 -> 1.0.1, refreshed at this start")


def test_the_hook_falls_back_to_plain_lines_when_the_greeting_cannot_run(machine):
    home, project, base = machine
    path = fake_bin(base)
    (home / "offline").touch()
    offline = run(home, path, project, "--hook")  # no uv: no greeting, the line that says why
    assert offline.returncode == 1
    assert "installing uv failed (offline?). Run this again when online" in offline.stdout
    (home / "offline").unlink()
    (home / "status-fails").touch()
    failing = run(home, path, project, "--hook")
    assert failing.returncode == 0
    assert failing.stdout.startswith("se bootstrap: installing uv into ")


PLATFORM = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(platform.system(), "") + "-" + {
    "x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower(), "")
# The release's archive for this platform: Windows' is a zip of se.exe (kern/tools/release).
ASSET = f"{NAME}-{APP_VERSION}-{PLATFORM}.{'zip' if WINDOWS else 'tar.gz'}"
# A fake kern: logs each call with its stdin; `start` fails while $HOME/kern-fails exists.
FAKE_KERN = """#!/bin/sh
input=""
[ "$1" = hook ] && input=" <<$(cat)"
echo "kern $*$input" >> "$HOME/calls"
if [ "$1" = start ] && [ -f "$HOME/kern-fails" ]; then echo "kern start: boom" >&2; exit 2; fi
exit 0
"""
START = '{"session_id":"s1","hook_event_name":"SessionStart"}'


def kern_bin(home: Path) -> Path:
    return home / ".se" / "bin" / f"{NAME}-{APP_VERSION}{'.exe' if WINDOWS else ''}"


def greeting_call(home: Path) -> str:
    [start] = [line for line in calls(home) if "se_start.py" in line and " status " in line]
    return start


def until(home: Path, text: str) -> list[str]:
    """The calls once one holds text: the background half of kern's first start runs on its own."""
    end = time.monotonic() + 20
    while not any(text in line for line in calls(home)):
        assert time.monotonic() < end, f"no call holds {text!r}: {calls(home)}"
        time.sleep(0.02)
    return calls(home)


def release(home: Path, *, corrupt: bool = False) -> None:
    """The se binary's release for this platform, as tools/release builds it: the archive and SHA256SUMS."""
    folder = home / "se-release"
    folder.mkdir()
    staged = home / "staged"
    staged.mkdir()
    exe = f"{NAME}.exe" if WINDOWS else NAME
    (staged / exe).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    (staged / exe).chmod(0o755)
    asset = ASSET
    if WINDOWS:  # Windows' release is a zip of se.exe (kern/tools/release)
        with zipfile.ZipFile(folder / asset, "w") as archive:
            archive.write(staged / exe, arcname=exe)
    else:
        with tarfile.open(folder / asset, "w:gz") as archive:
            archive.add(staged / exe, arcname=exe)
    digest = hashlib.sha256((folder / asset).read_bytes()).hexdigest()
    (folder / "SHA256SUMS").write_text(f"{'0' * 64 if corrupt else digest}  {asset}\n", encoding="utf-8", newline="\n")


needs_platform = pytest.mark.skipif(PLATFORM.startswith("-") or PLATFORM.endswith("-"),
                                    reason="kern releases linux, darwin and windows on amd64 and arm64")


def test_a_session_start_starts_the_kern_on_this_machine_and_hands_it_the_start(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)  # uv and Python in place
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    result = run(home, path, project, "--hook", stdin=START)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    log = [line for line in calls(home) if line.startswith("kern ")]
    assert log == [f"kern start --root {sh(project)} --home {SE_ROOT}", f"kern hook SessionStart --root {sh(project)} <<{START}"]
    assert greeting_call(home).endswith(f"--kern-bin {sh(kern_bin(home))}")
    assert not any(line.startswith("curl") for line in calls(home)), "a binary already here needs no network"
    assert f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_modules.py --root {sh(ROOT)} app-binary --project {sh(project)}" in calls(home)
    # Every later hook finds the binary where the start named it (scripts/se_hook.sh).
    assert (project / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8") == f"{sh(kern_bin(home))}\n"


# Copilot's camelCase sessionStart payload (an event registered in camelCase): no project variable,
# so the project is the payload's cwd (scripts/hosts.sh).
COPILOT_START = '{"sessionId":"s1","timestamp":1,"cwd":"%s","source":"startup"}'


def test_a_copilot_start_finds_the_project_by_its_cwd_greets_as_copilot_and_hands_kern_snake_case(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)  # uv and Python in place
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    env = {"HOME": sh(home), "PATH": tool_path(path)}
    result = subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, capture_output=True, text=True, timeout=60,
                            input=COPILOT_START % sh(project), cwd=base)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert f"--root {sh(project)} status --hook --host copilot " in greeting_call(home)
    handed = '{"session_id":"s1","timestamp":1,"cwd":"%s","source":"startup"}' % sh(project)
    log = [line for line in calls(home) if line.startswith("kern ")]
    assert log == [f"kern start --root {sh(project)} --home {SE_ROOT}", f"kern hook SessionStart --root {sh(project)} <<{handed}"]


# Copilot's start as .github/hooks/se.json registers it: PascalCase `SessionStart`, so a Claude-shaped
# payload, and the hook's environment naming its host.
PASCAL_START = '{"hook_event_name":"SessionStart","session_id":"s1","cwd":"%s","source":"startup"}'


def copilot_start(home: Path, path: Path, cwd: Path, payload: str) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": tool_path(path), "SE_HOOK_HOST": "copilot"}
    return subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, capture_output=True, text=True, timeout=60,
                          input=payload, cwd=cwd)


def test_a_copilot_start_with_a_claude_shaped_payload_greets_as_copilot(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    result = copilot_start(home, path, base, PASCAL_START % sh(project))
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert f"--root {sh(project)} status --hook --host copilot " in greeting_call(home)


def test_copilot_starts_a_session_once_however_many_sources_fire(machine):
    """Copilot runs every hook source it finds together; the second start of the same session ends
    quietly, and kern is started once."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    first = copilot_start(home, path, base, PASCAL_START % sh(project))
    second = copilot_start(home, path, base, PASCAL_START % sh(project))
    assert first.stdout == '{"greeting": 1}\n' and (second.returncode, second.stdout) == (0, "")
    assert [line for line in calls(home) if line.startswith("kern start")] == [f"kern start --root {sh(project)} --home {SE_ROOT}"]
    other = copilot_start(home, path, base, (PASCAL_START % sh(project)).replace('"s1"', '"s2"'))
    assert other.stdout == '{"greeting": 1}\n', "another session starts"


def test_claude_code_starts_are_not_guarded(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    for _ in range(2):
        assert run(home, path, project, "--hook", stdin=START).stdout == '{"greeting": 1}\n'
    assert not list((project / ".se" / ".runtime").glob("start-*.claim"))


def start_steps(home: Path) -> dict[str, bool]:
    """Which of the steps a compaction skips this start ran, read from the fake uv's logs."""
    log = calls(home)
    return {"refresh": (home / "refreshes").exists(),
            "modules": any("se_modules.py" in line and " sync" in line for line in log),
            "identity": any("work_tickets.py" in line and " identity " in line for line in log),
            "hooks": any(" start-hooks" in line for line in log),
            "file gate": any("se_forms.py gate --runtime " in line for line in log)}


def test_a_start_after_a_compaction_skips_the_refresh_modules_identity_and_hooks_and_still_greets(machine):
    """Claude Code fires SessionStart with source "compact" after every compaction: the steps that
    ran at the session's own start do not run again, and the greeting context still comes, so the
    session keeps <se>."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    result = run(home, path, project, "--hook", stdin=START.replace("}", ',"source":"compact"}'))
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert start_steps(home) == dict.fromkeys(("refresh", "modules", "identity", "hooks", "file gate"), False)
    assert greeting_call(home)


@pytest.mark.parametrize("source", ['"source":"startup"', '"source":"resume"', '"source":"clear"', None])
def test_every_other_start_runs_every_step(machine, source):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    payload = START if source is None else START.replace("}", f",{source}}}")
    result = run(home, path, project, "--hook", stdin=payload)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert start_steps(home) == dict.fromkeys(("refresh", "modules", "identity", "hooks", "file gate"), True)


def test_the_start_writes_the_file_gates_line_through_se_forms_and_removes_it_without_se_toml(machine):
    """se_hook.sh guards the file tools only where the start left forms-files (README "Forms"):
    `se_forms.py gate --runtime` writes or removes it from se.toml (tests/test_se_forms.py); a
    project without se.toml loses a line an earlier start left."""
    home, project, base = machine
    path = fake_bin(base)
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert [line for line in calls(home) if "se_forms.py" in line] == [
        f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_forms.py gate --runtime "
        f"{sh(project)}"]
    line = project / ".se" / ".runtime" / "forms-files"
    line.parent.mkdir(parents=True, exist_ok=True)
    line.write_text("write\n", encoding="utf-8")
    (project / "se.toml").unlink()
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert not line.exists() and not any("se_forms.py" in line for line in calls(home))


def test_the_session_finds_se_on_its_path_by_a_stable_name(machine):
    """`se status` works in the session's shells: the start links ~/.se/bin/<name> to the version
    it runs and puts ~/.se/bin on the session's PATH through Claude Code's env file."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    env_file = base / "env"
    env = {"HOME": sh(home), "PATH": tool_path(path), "CLAUDE_PROJECT_DIR": sh(project),
           "CLAUDE_ENV_FILE": str(env_file)}
    subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, input=START, check=True, capture_output=True,
                   text=True, timeout=60)
    assert f'export PATH="{sh(home)}/.se/bin:$PATH"\n' in env_file.read_text(encoding="utf-8")
    stable = kern_bin(home).with_name(NAME + (".exe" if WINDOWS else ""))
    (home / "calls").unlink()
    shell = subprocess.run([BASH, "-c", f'. "{sh(env_file)}" && {NAME} status'], env=env,
                           capture_output=True, text=True, timeout=60)
    assert shell.returncode == 0 and calls(home) == ["kern status"], (shell.stderr, calls(home))
    assert os.access(stable, os.X_OK)


def test_the_core_starts_without_uvs_deprecated_tls_variable(machine):
    """core.log holds no deprecation notice of uv's: the core, and every component it places with
    `uv run`, starts with UV_NATIVE_TLS turned into UV_SYSTEM_CERTS."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN.replace(
        'echo "kern $*$input" >> "$HOME/calls"',
        'echo "kern $*$input native=${UV_NATIVE_TLS-unset} system=${UV_SYSTEM_CERTS-unset}" >> "$HOME/calls"'),
        encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    env = {"HOME": sh(home), "PATH": tool_path(path), "CLAUDE_PROJECT_DIR": sh(project), "UV_NATIVE_TLS": "1"}
    subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, input=START, check=True, capture_output=True,
                   text=True, timeout=60)
    assert f"kern start --root {sh(project)} --home {SE_ROOT} native=unset system=1" in calls(home), calls(home)


def test_a_failed_start_of_kern_is_named_with_its_cause(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "kern-fails").touch()
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert f"--kern-failed {NAME} start: kern start: boom --kern-bin" in greeting_call(home)
    assert not any("kern hook" in line for line in calls(home)), "no core to hand the start to"


@needs_platform
@pytest.mark.parametrize("missing", [
    (),
    pytest.param(("sha256sum", "setsid"), marks=pytest.mark.skipif(
        WINDOWS, reason="macOS's tools; on Windows, without setsid, the background fetch did not finish")),
], ids=["every-tool", "shasum-no-setsid"])  # as on macOS: the checksum from shasum, no setsid
def test_the_first_start_of_a_version_fetches_its_release_in_the_background_then_starts_it(machine, missing):
    home, project, base = machine
    path = fake_bin(base)
    for tool in missing:
        drop_tool(path, tool)
    if not (path / "sha256sum").exists() and not (path / "shasum").exists():
        pytest.skip("neither sha256sum nor shasum is on this machine")
    run(home, path, project)
    release(home)
    (home / "calls").unlink()
    result = run(home, path, project, "--hook", stdin=START)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert greeting_call(home).endswith(f"--kern-starting fetching the {NAME} {APP_VERSION} release for {PLATFORM} "
                                        "in the background")
    log = until(home, "kern hook SessionStart")
    assert f"curl -fsSL --max-time 2 -o {sh(home)}/.se/bin/{NAME}-{APP_VERSION}.SHA256SUMS {APP_BASE}/SHA256SUMS" in log
    assert f"kern start --root {sh(project)} --home {SE_ROOT}" in log
    assert f"kern hook SessionStart --root {sh(project)} <<{START}" in log
    assert os.access(kern_bin(home), os.X_OK)
    assert sorted(p.name for p in kern_bin(home).parent.iterdir()) == sorted([
        kern_bin(home).name, f"{NAME}-{APP_VERSION}.SHA256SUMS",
        NAME + (".exe" if WINDOWS else "")]), "nothing half-done is left; the stable name is there"


@needs_platform
def test_an_archive_that_fails_its_checksum_is_never_run(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    release(home, corrupt=True)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    until(home, ASSET)
    time.sleep(0.5)
    assert not kern_bin(home).exists()
    assert not any(line.startswith("kern ") for line in calls(home))


def test_with_no_release_kern_is_built_from_ses_kern_in_the_background_and_the_greeting_says_so(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    # A fake go: `go build -o <out> ./cmd/se` in SE's components/ writes the fake binary.
    (path / "go").write_text(f"""#!/bin/sh
echo "go $* in $PWD" >> "$HOME/calls"
cat > "$3" <<'KERN'
{FAKE_KERN}KERN
chmod +x "$3"
""", encoding="utf-8", newline="\n")
    (path / "go").chmod(0o755)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-starting no {NAME} {APP_VERSION} release at {APP_BASE}; "
                                        f"building it from {sh(ROOT)}/{BUILD_DIR} in the background")
    log = until(home, "kern hook SessionStart")
    assert any(line.startswith("go build -o ") and line.endswith(f"{PACKAGE} in {sh(ROOT)}/{BUILD_DIR}") for line in log)
    assert f"kern start --root {sh(project)} --home {SE_ROOT}" in log and os.access(kern_bin(home), os.X_OK)


def test_with_no_release_and_no_go_kern_failed_names_both(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-failed no {NAME} {APP_VERSION} release at {APP_BASE}, and no go "
                                        f"to build it from {sh(ROOT)}/{BUILD_DIR}")


def test_where_origin_names_no_home_the_start_fetches_nothing_and_builds_from_its_folder(machine):
    """app-binary answers `-` for the download base where the checkout's origin names no home: no
    release is asked for, and the start builds the binary from its folder as where none matches."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "app-binary").write_text(f"{NAME} {APP_VERSION} - {BUILD_DIR} {PACKAGE}\n", encoding="utf-8",
                                     newline="\n")
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-failed no {NAME} {APP_VERSION} release to fetch: the origin of "
                                        f"{sh(ROOT)} names no home, and no go to build it from {sh(ROOT)}/{BUILD_DIR}")
    assert not any(line.startswith("curl") for line in calls(home))


def test_a_start_outside_a_git_checkout_starts_no_core(machine):
    """A session started without sources (README "Cloud sessions"): no core, no read of the binary,
    no fetch and nothing said of the core; the session's shells still find `se` for a late checkout."""
    (machine[1] / ".git").rmdir()
    home, project, path = kern_in_place(machine)
    env_file = machine[2] / "claude-env"
    result = run(home, path, project, "--hook", stdin=START, CLAUDE_ENV_FILE=sh(env_file))
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert not any(line.startswith(("kern ", "curl")) or " app-binary " in line for line in calls(home))
    runtime = project / ".se" / ".runtime"
    assert not (runtime / "kern.path").exists() and not (runtime / "kern-session-start.json").exists()
    greeting = greeting_call(home)
    assert "--kern-starting" not in greeting and "--kern-failed" not in greeting and "--kern-bin" not in greeting
    assert greeting.endswith("--kern-none")
    assert f'export PATH="{sh(home)}/.se/bin:$PATH"' in env_file.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("worktree", (False, True), ids=("subfolder", "linked-worktree"))
def test_a_start_in_a_subfolder_of_a_checkout_or_a_linked_worktree_starts_the_core(machine, worktree):
    home, project, path = kern_in_place(machine)
    if worktree:  # a linked worktree's .git is a file naming its git directory
        (project / ".git").rmdir()
        (project / ".git").write_text("gitdir: /elsewhere/.git/worktrees/project\n", encoding="utf-8")
    else:
        project = project / "docs"
        project.mkdir()
    result = run(home, path, project, "--hook", stdin=START)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [line for line in calls(home) if line.startswith("kern ")][0] == f"kern start --root {sh(project)} --home {SE_ROOT}"
    assert "--kern-none" not in greeting_call(home)


def test_bootstrap_outside_a_session_leaves_kern_alone(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    assert run(home, path, project).returncode == 0
    assert not any("kern" in line for line in calls(home))


def test_without_a_pin_kern_is_left_alone(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "app-binary").unlink()  # se_modules.py app-binary answers nothing
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert "--kern" not in greeting_call(home)
    assert not any(line.startswith(("curl", "kern ")) for line in calls(home))


# The core switch (README "Machine-local `~/.se/local.toml`", scripts/switches/hooks.toml):
# SE_HOOK_CORE in the environment, else [hooks] core in ~/.se/local.toml.
OFF_VALUES = ("off", "OFF", "Off")
ON_VALUES = ("", " off", "off ", "0", "false", "on")
ENV_NOTE = "SE: no core at this start: SE_HOOK_CORE is off in the environment; the hooks answer without one"
LOCAL_NOTE = "SE: no core at this start: [hooks] core is off in ~/.se/local.toml; the hooks answer without one"


def kern_in_place(machine) -> tuple[Path, Path, Path]:
    """uv, Python and the binary in place, the logs empty: the start the switch decides."""
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    return home, project, path


def local_file(home: Path, text: str) -> None:
    (home / ".se" / "local.toml").write_text(text, encoding="utf-8", newline="\n")


def files(*folders: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for folder in folders for p in folder.rglob("*"))


def core_started(home: Path) -> bool:
    return any(line.startswith("kern ") for line in calls(home))


def test_the_switch_rows_default_is_the_starts_behaviour(machine):
    sys.path.insert(0, str(ROOT / "scripts"))
    import se_switches

    [row] = [switch for switch in se_switches.load().switches if switch.name == "SE_HOOK_CORE"]
    assert (row.default, row.reader) == ("on", "scripts/bootstrap.sh")
    home, project, path = kern_in_place(machine)
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert core_started(home) and (project / ".se" / ".runtime" / "kern.path").exists()


def test_an_empty_hook_core_variable_starts_as_unset(machine):
    home, project, path = kern_in_place(machine)
    seen = []
    for variables in ({}, {"SE_HOOK_CORE": ""}):
        env_file = home.parent / "env"
        result = run(home, path, project, "--hook", stdin=START, CLAUDE_ENV_FILE=sh(env_file), **variables)
        seen.append((result.returncode, result.stdout, calls(home), files(project, home),
                     env_file.read_text(encoding="utf-8")))
        (home / "calls").unlink()
        env_file.unlink()
    assert seen[0] == seen[1]
    assert not any("hooks-core" in line for line in seen[0][2])


@pytest.mark.parametrize("text", (None, '[paths]\nobs = "~/src/obs"\n'))
def test_without_hooks_in_the_local_file_the_start_reads_no_setting(machine, text):
    home, project, path = kern_in_place(machine)
    if text is not None:
        local_file(home, text)
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert not any("hooks-core" in line for line in calls(home))
    assert core_started(home)


@pytest.mark.parametrize(("variables", "text", "note"), [
    *(({"SE_HOOK_CORE": value}, None, ENV_NOTE) for value in OFF_VALUES),
    ({"SE_HOOK_CORE": "off"}, '[hooks]\ncore = "on"\n', ENV_NOTE),
    ({}, '[hooks]\ncore = "off"\n', LOCAL_NOTE),
    ({}, '[hooks]\ncore = "OFF"\n', LOCAL_NOTE),
    ({}, "[hooks]\ncore = false\n", LOCAL_NOTE),
], ids=["off", "OFF", "Off", "environment first", "local", "local OFF", "local false"])
def test_hook_core_off_starts_no_core_and_says_so(machine, variables, text, note):
    home, project, path = kern_in_place(machine)
    if text is not None:
        local_file(home, text)
    runtime = project / ".se" / ".runtime"
    runtime.mkdir(parents=True)
    (runtime / "kern.path").write_text(f"{sh(kern_bin(home))}\n", encoding="utf-8")  # an earlier session's
    env_file = home / "env"
    result = run(home, path, project, "--hook", stdin=START, CLAUDE_ENV_FILE=sh(env_file), **variables)
    assert (result.returncode, result.stdout) == (0, '{"greeting": 1}\n'), result.stderr
    assert not core_started(home)
    assert not any("app-binary" in line or line.startswith("curl") for line in calls(home))
    assert not (runtime / "kern.path").exists() and not (runtime / "kern-session-start.json").exists()
    assert f"{sh(home)}/.se/bin" not in env_file.read_text(encoding="utf-8")
    greeting = greeting_call(home)
    assert greeting.endswith(f"--note {note}") and "--kern" not in greeting
    assert any("hooks-core" in line for line in calls(home)) == (not variables)


@pytest.mark.parametrize("value", ON_VALUES)
def test_any_other_hook_core_value_starts_the_core_as_today(machine, value):
    home, project, path = kern_in_place(machine)
    assert run(home, path, project, "--hook", stdin=START, SE_HOOK_CORE=value).returncode == 0
    assert core_started(home) and "no core at this start" not in greeting_call(home)


@pytest.mark.parametrize("text", ('[hooks]\ncore = "on"\n', "[hooks]\ncore = true\n",
                                  "[hooks]\ncore = 1\n", '[hooks]\ncor = "off"\n'))
def test_a_local_file_that_does_not_say_off_leaves_the_hooks_on(machine, text):
    home, project, path = kern_in_place(machine)
    local_file(home, text)
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert any("hooks-core" in line for line in calls(home))
    assert core_started(home) and "no core at this start" not in greeting_call(home)


# --binary (RUNME.conf's `get se` line): the binary placed and linked, nothing started. It writes
# into the SE it runs from (.se/.runtime/runme-se), so these run a copy of the script in a folder
# of their own, never in this checkout.
def binary_root(base: Path) -> Path:
    root = base / "se"
    (root / "scripts").mkdir(parents=True)
    for name in ("bootstrap.sh", "hosts.sh"):
        shutil.copy2(SCRIPT.parent / name, root / "scripts" / name)
    return root


def run_binary(home: Path, path: Path, root: Path) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": tool_path(path)}
    return subprocess.run([BASH, sh(root / "scripts" / "bootstrap.sh"), "--binary"], env=env,
                          capture_output=True, text=True, timeout=60, cwd=root)


def placed(home: Path, root: Path) -> None:
    """The binary in place and linked as its stable name, RUNME's record written, nothing started."""
    assert os.access(kern_bin(home), os.X_OK)
    stable = home / ".se" / "bin" / (NAME + (".exe" if WINDOWS else ""))
    assert stable.exists()
    assert (root / ".se" / ".runtime" / "runme-se").read_text(encoding="utf-8") == f"{APP_VERSION}\n"
    assert not (root / ".se" / ".runtime" / "kern.path").exists()
    assert not any(line.startswith("kern ") for line in calls(home)), "--binary starts nothing"
    assert not any(" sync" in line or " identity " in line or "start-hooks" in line for line in calls(home))


@needs_platform
def test_binary_fetches_the_release_in_the_foreground_links_it_and_starts_nothing(machine):
    home, _, base = machine
    root = binary_root(base)
    release(home)
    result = run_binary(home, fake_bin(base), root)
    assert result.returncode == 0, result.stdout + result.stderr
    placed(home, root)
    assert any(ASSET in line for line in calls(home))


def test_binary_builds_with_go_where_no_release_matches(machine):
    home, _, base = machine
    root = binary_root(base)
    path = fake_bin(base)
    (path / "go").write_text(f"""#!/bin/sh
echo "go $* in $PWD" >> "$HOME/calls"
cat > "$3" <<'KERN'
{FAKE_KERN}KERN
chmod +x "$3"
""", encoding="utf-8", newline="\n")
    (path / "go").chmod(0o755)
    (root / BUILD_DIR).mkdir()
    (root / BUILD_DIR / "go.mod").write_text("module se/components\n", encoding="utf-8")
    result = run_binary(home, path, root)
    assert result.returncode == 0, result.stdout + result.stderr
    placed(home, root)
    assert any(line.startswith("go build -o ") and line.endswith(f"{PACKAGE} in {sh(root)}/{BUILD_DIR}")
               for line in calls(home))


def test_binary_without_a_release_or_go_names_both_in_one_line_and_exits_1(machine):
    home, _, base = machine
    root = binary_root(base)
    result = run_binary(home, fake_bin(base), root)
    assert result.returncode == 1
    lines = [line for line in result.stdout.splitlines() if " release at " in line]
    assert lines == [f"se bootstrap: no {NAME} {APP_VERSION} release at {APP_BASE}, and no go to build it "
                     f"from {sh(root)}/{BUILD_DIR}"], result.stdout
    assert not (root / ".se" / ".runtime" / "runme-se").exists()


# kern for the installed SE (scripts/bootstrap.sh kern_place, README "Modules"): an SE that pins kern
# by [modules.kern] gets its clone synced before the core starts where it is missing or off the
# commit se.lock locks; at that commit, no process starts.
LOCKED = "b" * 40


def pinning_se(base: Path, head: str | None) -> Path:
    """A copy of SE's start scripts in a folder of its own that pins kern, its clone at `head`."""
    root = binary_root(base)
    (root / "se.toml").write_text('[modules.kern]\nurl = "../kern.git"\ngo = "components/go.mod"\n',
                                  encoding="utf-8", newline="\n")
    (root / "se.lock").write_text(f'[modules.obs]\nversion = "4.0.1"\nref = "{"a" * 40}"\n\n'
                                  f'[modules.kern]\nversion = "0.14.1"\nref = "{LOCKED}"\n',
                                  encoding="utf-8", newline="\n")
    if head is not None:
        (root / ".se" / "modules" / "kern" / ".git").mkdir(parents=True)
        (root / ".se" / "modules" / "kern" / ".git" / "HEAD").write_text(f"{head}\n", encoding="utf-8")
    return root


def run_hook(home: Path, path: Path, project: Path, root: Path) -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": tool_path(path), "CLAUDE_PROJECT_DIR": sh(project)}
    return subprocess.run([BASH, sh(root / "scripts" / "bootstrap.sh"), "--hook"], env=env, input=START,
                          capture_output=True, text=True, timeout=60)


def kern_syncs(home: Path, root: Path) -> list[str]:
    return [line for line in calls(home) if f"se_modules.py --root {sh(root)} sync kern" in line]


@pytest.mark.parametrize("head", [None, "c" * 40], ids=["missing", "off-the-lock"])
def test_a_start_places_the_installed_ses_kern_before_the_core_where_it_is_missing(machine, head):
    home, project, base = machine
    root = pinning_se(base, head)
    path = fake_bin(base)
    run(home, path, project)  # uv and Python in place
    (home / "calls").unlink()
    assert run_hook(home, path, project, root).returncode == 0
    log = calls(home)
    assert len(kern_syncs(home, root)) == 1
    locate = next(i for i, line in enumerate(log) if " app-binary " in line)
    assert log.index(kern_syncs(home, root)[0]) < locate, "placed before the core's binary is located"
    assert "placing kern" not in greeting_call(home)


def test_an_ses_kern_at_its_lock_starts_no_process(machine):
    home, project, base = machine
    root = pinning_se(base, LOCKED)
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    assert run_hook(home, path, project, root).returncode == 0
    assert kern_syncs(home, root) == [] and any(" app-binary " in line for line in calls(home))


def test_a_failed_placement_is_named_in_the_greeting_and_the_start_goes_on(machine):
    home, project, base = machine
    root = pinning_se(base, None)
    path = fake_bin(base)
    run(home, path, project)
    (home / "kern-sync-fails").touch()
    (home / "calls").unlink()
    assert run_hook(home, path, project, root).returncode == 0
    assert (f"--note SE: placing kern for {sh(root)} failed, so this start goes on without it: error: "
            "module kern: git clone failed") in greeting_call(home)
    assert any(" app-binary " in line for line in calls(home)), "the core step goes on"


def test_binary_places_kern_before_it_builds_the_binary_on_it(machine):
    """The build fallback builds $pins/$builddir, whose go.mod replaces kern by the placed clone:
    --binary syncs it first; the build names its folder and package, no default of kern/."""
    home, _, base = machine
    root = pinning_se(base, None)
    path = fake_bin(base)
    (path / "go").write_text(f"""#!/bin/sh
echo "go $* in $PWD" >> "$HOME/calls"
cat > "$3" <<'KERN'
{FAKE_KERN}KERN
chmod +x "$3"
""", encoding="utf-8", newline="\n")
    (path / "go").chmod(0o755)
    (root / BUILD_DIR).mkdir()
    (root / BUILD_DIR / "go.mod").write_text("module se/components\n\nreplace kern => ../.se/modules/kern\n",
                                             encoding="utf-8")
    result = run_binary(home, path, root)
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(home)
    build = next(i for i, line in enumerate(log) if line.startswith("go build -o "))
    assert log[build].endswith(f"{PACKAGE} in {sh(root)}/{BUILD_DIR}")
    assert log.index(kern_syncs(home, root)[0]) < build
    assert "$se_root/kern" not in SCRIPT.read_text(encoding="utf-8"), "--kern-build names its folder"
