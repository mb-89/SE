"""bootstrap.sh brings uv, Python and the modules into an empty home, and says what it cannot do."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import time
import tomllib
import zipfile

import pytest
from shell_paths import BASH, WINDOWS, sh

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap.sh"
# SE's own binary, as se_modules.py app-binary answers it (components/release.toml): kern's core plus
# SE's Go components, the binary `se`. bootstrap fetches, builds and starts it, not the bare kern.
APP = tomllib.loads((ROOT / "components" / "release.toml").read_text(encoding="utf-8"))
NAME, APP_VERSION = APP["binary"], APP["version"]
APP_BASE = APP["download"].replace("{version}", APP_VERSION)
BUILD_DIR, PACKAGE = "components", APP["package"]
TOOLS = ("bash", "sh", "dirname", "grep", "cat", "env", "chmod", "mkdir", "touch", "uname", "tail", "tar",
         "gzip", "sha256sum", "shasum", "setsid", "unzip", "mv", "rm", "ln", "cp")
pytestmark = pytest.mark.skipif(BASH is None, reason="bootstrap.sh runs in bash")

# A fake uv: `python find` fails until `python install` ran; SE's start prints a greeting unless
# `status-fails` exists; its refresh at start (tests/test_start_refresh.py) moves SE where
# `refresh-moves` exists, else has nothing to move, and is logged apart; every other call is logged.
FAKE_UV = """#!/bin/sh
case "$*" in *"se_start.py "*" start-refresh"*)
  echo refresh >> "$HOME/refreshes"
  [ -f "$HOME/refresh-moves" ] || exit 1
  echo "SE: 1.0.0 -> 1.0.1, refreshed at this start"; exit 0 ;;
esac
echo "uv $*" >> "$HOME/calls"
case "$*" in *se_start.py*) [ -f "$HOME/status-fails" ] && exit 1; echo '{"greeting": 1}'; exit 0 ;; esac
case "$*" in *"se_modules.py --root "*" app-binary"*) cat "$HOME/app-binary" 2>/dev/null; exit 0 ;; esac
case "$1 $2" in
  "python find") [ -f "$HOME/python" ] ;;
  "python install") touch "$HOME/python" ;;
esac
"""
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
    folder = base / "bin"
    folder.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        if not found:  # setsid, shasum and unzip are not everywhere; bootstrap.sh does without them
            continue
        if WINDOWS:  # a linked Git tool would not find the DLLs beside it: a shim runs it there
            (folder / tool).write_text(f'#!/bin/sh\nexec "{sh(Path(found))}" "$@"\n', encoding="utf-8",
                                       newline="\n")
        else:
            (folder / tool).symlink_to(found)
    for name, script in (("curl", FAKE_CURL), ("powershell", FAKE_POWERSHELL)):
        (folder / name).write_text(script, encoding="utf-8", newline="\n")
        (folder / name).chmod(0o755)
    if git:
        (folder / "git").write_text("#!/bin/sh\n", encoding="utf-8", newline="\n")
        (folder / "git").chmod(0o755)
    return folder


def run(home: Path, path: Path, project: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {"HOME": sh(home), "PATH": sh(path), "CLAUDE_PROJECT_DIR": sh(project)}
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
    # se_modules.py app-binary: name, version, download base, build folder, package.
    (home / "app-binary").write_text(f"{NAME} {APP_VERSION} {APP_BASE} {BUILD_DIR} {PACKAGE}\n", encoding="utf-8",
                                     newline="\n")
    (project / "se.toml").write_text('[modules.obs]\nurl = "https://example.com/obs.git"\nref = "%s"\n' % ("0" * 40),
                                     encoding="utf-8", newline="\n")
    return home, project, tmp_path


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
    env = {"HOME": sh(home), "PATH": sh(fake_bin(base)), "CLAUDE_PROJECT_DIR": sh(project),
           "CLAUDE_ENV_FILE": str(env_file)}
    subprocess.run([BASH, sh(SCRIPT)], env=env, check=True, capture_output=True, timeout=60)
    assert env_file.read_text(encoding="utf-8") == f'export PATH="{sh(home)}/.local/bin:$PATH"\n'
    assert os.access(home / ".local" / "bin" / "uv", os.X_OK)


def test_the_hook_ends_with_ses_greeting_carrying_what_bootstrap_said(machine):
    home, project, base = machine
    result = run(home, fake_bin(base), project, "--hook")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == '{"greeting": 1}\n'  # the JSON alone: Claude Code parses the hook's stdout
    start = [line for line in calls(home) if "se_start.py" in line]
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
    [start] = [line for line in calls(home) if "se_start.py" in line]
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
    assert log == [f"kern start --root {sh(project)}", f"kern hook SessionStart --root {sh(project)} <<{START}"]
    assert greeting_call(home).endswith(f"--kern-bin {sh(kern_bin(home))}")
    assert not any(line.startswith("curl") for line in calls(home)), "a binary already here needs no network"
    assert f"uv run --no-project --python >=3.11 python {sh(SCRIPT.parent)}/se_modules.py --root {sh(ROOT)} app-binary --project {sh(project)}" in calls(home)
    # Every later hook finds the binary where the start named it (scripts/se_hook.sh).
    assert (project / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8") == f"{sh(kern_bin(home))}\n"


# Copilot's sessionStart payload (.github/hooks/se.json): camelCase, and its CLI hooks may lack any
# project variable, so the project is the payload's cwd (scripts/hosts.sh).
COPILOT_START = '{"sessionId":"s1","timestamp":1,"cwd":"%s","source":"startup"}'


def test_a_copilot_start_finds_the_project_by_its_cwd_greets_as_copilot_and_hands_kern_snake_case(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)  # uv and Python in place
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8", newline="\n")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    env = {"HOME": sh(home), "PATH": sh(path)}
    result = subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, capture_output=True, text=True, timeout=60,
                            input=COPILOT_START % sh(project), cwd=base)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert f"--root {sh(project)} status --hook --host copilot " in greeting_call(home)
    handed = '{"session_id":"s1","timestamp":1,"cwd":"%s","source":"startup"}' % sh(project)
    log = [line for line in calls(home) if line.startswith("kern ")]
    assert log == [f"kern start --root {sh(project)}", f"kern hook SessionStart --root {sh(project)} <<{handed}"]


def test_copilots_project_variable_names_the_project_where_claudes_is_unset(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    env = {"HOME": sh(home), "PATH": sh(path), "COPILOT_PROJECT_DIR": sh(project)}
    result = subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, capture_output=True, text=True, timeout=60,
                            input=COPILOT_START % sh(base), cwd=base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"--root {sh(project)} status --hook --host copilot " in greeting_call(home)


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
    env = {"HOME": sh(home), "PATH": sh(path), "CLAUDE_PROJECT_DIR": sh(project),
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
    env = {"HOME": sh(home), "PATH": sh(path), "CLAUDE_PROJECT_DIR": sh(project), "UV_NATIVE_TLS": "1"}
    subprocess.run([BASH, sh(SCRIPT), "--hook"], env=env, input=START, check=True, capture_output=True,
                   text=True, timeout=60)
    assert f"kern start --root {sh(project)} native=unset system=1" in calls(home), calls(home)


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
        (path / tool).unlink(missing_ok=True)
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
    assert f"kern start --root {sh(project)}" in log
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
    assert f"kern start --root {sh(project)}" in log and os.access(kern_bin(home), os.X_OK)


def test_with_no_release_and_no_go_kern_failed_names_both(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-failed no {NAME} {APP_VERSION} release at {APP_BASE}, and no go "
                                        f"to build it from {sh(ROOT)}/{BUILD_DIR}")


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
