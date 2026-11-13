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

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap.sh"
KERN_VERSION = tomllib.loads((ROOT / "kern" / "release.toml").read_text(encoding="utf-8"))["version"]
KERN_BASE = f"https://github.com/mb-89/SE/releases/download/kern-v{KERN_VERSION}"
TOOLS = ("bash", "sh", "dirname", "grep", "cat", "env", "chmod", "mkdir", "touch", "uname", "tail", "tar",
         "gzip", "sha256sum", "setsid", "mv", "rm")
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bootstrap.sh runs in bash")

# A fake uv: `python find` fails until `python install` ran; SE's start prints a greeting unless
# `status-fails` exists; every call is logged.
FAKE_UV = """#!/bin/sh
echo "uv $*" >> "$HOME/calls"
case "$*" in *se_start.py*) [ -f "$HOME/status-fails" ] && exit 1; echo '{"greeting": 1}'; exit 0 ;; esac
case "$*" in *"se_modules.py --root "*" kern-pin"*) cat "$HOME/kern-pin" 2>/dev/null; exit 0 ;; esac
case "$1 $2" in
  "python find") [ -f "$HOME/python" ] ;;
  "python install") touch "$HOME/python" ;;
esac
"""
# A fake uv installer, as astral.sh's: puts uv into ~/.local/bin, or fails while "offline".
# kern's release (README "Kern"): served from $HOME/kern-release where it exists, else a 404 (22).
FAKE_CURL = f"""#!/bin/sh
echo "curl $*" >> "$HOME/calls"
[ -f "$HOME/offline" ] && exit 6
case "$*" in *kern-v*)
  while [ "$1" != -o ]; do shift; done
  out="$2"; url="$3"
  [ -f "$HOME/kern-release/${{url##*/}}" ] || exit 22
  cat "$HOME/kern-release/${{url##*/}}" > "$out"; exit 0 ;;
esac
cat <<'INSTALLER'
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/uv" <<'UV'
{FAKE_UV}UV
chmod +x "$HOME/.local/bin/uv"
INSTALLER
"""


def fake_bin(base: Path, *, git: bool = True) -> Path:
    """A PATH holding only the shell tools the script uses, a fake curl and, optionally, git."""
    folder = base / "bin"
    folder.mkdir()
    for tool in TOOLS:
        if shutil.which(tool):  # setsid is not everywhere; bootstrap.sh does without it
            (folder / tool).symlink_to(shutil.which(tool))
    (folder / "curl").write_text(FAKE_CURL, encoding="utf-8")
    (folder / "curl").chmod(0o755)
    if git:
        (folder / "git").write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / "git").chmod(0o755)
    return folder


def run(home: Path, path: Path, project: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": str(path), "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60,
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
    (home / "kern-pin").write_text(f"{KERN_VERSION} {KERN_BASE}\n", encoding="utf-8")  # se_modules.py kern-pin
    (project / "se.toml").write_text('[modules.obs]\nurl = "https://example.com/obs.git"\nref = "%s"\n' % ("0" * 40),
                                     encoding="utf-8")
    return home, project, tmp_path


def test_an_empty_home_gets_uv_python_and_the_modules_and_a_second_start_is_quiet(machine):
    home, project, base = machine
    path = fake_bin(base)
    first = run(home, path, project)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "installing uv into" in first.stdout and "installing Python 3.11" in first.stdout
    log = calls(home)
    assert log[0] == "curl -LsSf https://astral.sh/uv/install.sh"
    assert "uv python install 3.11" in log
    sync = [line for line in log if line.startswith("uv run")]
    assert sync == [f"uv run --no-project --python >=3.11 python {SCRIPT.parent}/se_modules.py --root {project} sync"]
    (home / "calls").unlink()
    second = run(home, path, project)
    assert second.returncode == 0 and second.stdout == ""
    assert not any(line.startswith(("curl", "uv python install")) for line in calls(home))


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
    (project / "se.toml").write_text("[project]\n", encoding="utf-8")
    assert run(home, fake_bin(base), project).returncode == 0
    assert not any(line.startswith("uv run") for line in calls(home))


def test_the_session_finds_uv_through_claudes_env_file(machine):
    home, project, base = machine
    env_file = base / "env"
    env = {"HOME": str(home), "PATH": str(fake_bin(base)), "CLAUDE_PROJECT_DIR": str(project),
           "CLAUDE_ENV_FILE": str(env_file)}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True, timeout=60)
    assert env_file.read_text(encoding="utf-8") == f'export PATH="{home}/.local/bin:$PATH"\n'
    assert os.access(home / ".local" / "bin" / "uv", os.X_OK)


def test_the_hook_ends_with_ses_greeting_carrying_what_bootstrap_said(machine):
    home, project, base = machine
    result = run(home, fake_bin(base), project, "--hook")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == '{"greeting": 1}\n'  # the JSON alone: Claude Code parses the hook's stdout
    start = [line for line in calls(home) if "se_start.py" in line]
    assert len(start) == 1
    assert start[0].startswith(f"uv run --no-project --python >=3.11 python {SCRIPT.parent}/se_start.py "
                               f"--root {project} status --hook --note se bootstrap: installing uv into ")
    assert "--note se bootstrap: installing Python 3.11" in start[0]


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


PLATFORM = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system(), "") + "-" + {
    "x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower(), "")
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
    return home / ".se" / "bin" / f"kern-{KERN_VERSION}"


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
    """kern's release for this platform, as tools/release builds it: the archive and SHA256SUMS."""
    folder = home / "kern-release"
    folder.mkdir()
    staged = home / "staged"
    staged.mkdir()
    (staged / "kern").write_text(FAKE_KERN, encoding="utf-8")
    (staged / "kern").chmod(0o755)
    asset = f"kern-{KERN_VERSION}-{PLATFORM}.tar.gz"
    with tarfile.open(folder / asset, "w:gz") as archive:
        archive.add(staged / "kern", arcname="kern")
    digest = hashlib.sha256((folder / asset).read_bytes()).hexdigest()
    (folder / "SHA256SUMS").write_text(f"{'0' * 64 if corrupt else digest}  {asset}\n", encoding="utf-8")


needs_platform = pytest.mark.skipif(PLATFORM.startswith("-") or PLATFORM.endswith("-"),
                                    reason="kern releases linux and darwin on amd64 and arm64")


def test_a_session_start_starts_the_kern_on_this_machine_and_hands_it_the_start(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)  # uv and Python in place
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8")
    kern_bin(home).chmod(0o755)
    (home / "calls").unlink()
    result = run(home, path, project, "--hook", stdin=START)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    log = [line for line in calls(home) if line.startswith("kern ")]
    assert log == [f"kern start --root {project}", f"kern hook SessionStart --root {project} <<{START}"]
    assert greeting_call(home).endswith(f"--kern-bin {kern_bin(home)}")
    assert not any(line.startswith("curl") for line in calls(home)), "a kern already here needs no network"
    assert f"uv run --no-project --python >=3.11 python {SCRIPT.parent}/se_modules.py --root {ROOT} kern-pin" in calls(home)
    # Every later hook finds the binary where the start named it (scripts/se_hook.sh).
    assert (project / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8") == f"{kern_bin(home)}\n"


def test_a_failed_start_of_kern_is_named_with_its_cause(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    kern_bin(home).parent.mkdir(parents=True)
    kern_bin(home).write_text(FAKE_KERN, encoding="utf-8")
    kern_bin(home).chmod(0o755)
    (home / "kern-fails").touch()
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert "--kern-failed kern start: kern start: boom --kern-bin" in greeting_call(home)
    assert not any("kern hook" in line for line in calls(home)), "no core to hand the start to"


@needs_platform
def test_the_first_start_of_a_version_fetches_its_release_in_the_background_then_starts_it(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    release(home)
    (home / "calls").unlink()
    result = run(home, path, project, "--hook", stdin=START)
    assert result.returncode == 0 and result.stdout == '{"greeting": 1}\n', result.stdout + result.stderr
    assert greeting_call(home).endswith(f"--kern-starting fetching release kern-v{KERN_VERSION} for {PLATFORM} "
                                        "in the background")
    log = until(home, "kern hook SessionStart")
    assert f"curl -fsSL --max-time 2 -o {home}/.se/bin/kern-{KERN_VERSION}.SHA256SUMS {KERN_BASE}/SHA256SUMS" in log
    assert f"kern start --root {project}" in log
    assert f"kern hook SessionStart --root {project} <<{START}" in log
    assert os.access(kern_bin(home), os.X_OK)
    assert sorted(p.name for p in kern_bin(home).parent.iterdir()) == [
        kern_bin(home).name, f"{kern_bin(home).name}.SHA256SUMS"], "nothing half-done is left"


@needs_platform
def test_an_archive_that_fails_its_checksum_is_never_run(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    release(home, corrupt=True)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    until(home, f"kern-{KERN_VERSION}-{PLATFORM}.tar.gz")
    time.sleep(0.5)
    assert not kern_bin(home).exists()
    assert not any(line.startswith("kern ") for line in calls(home))


def test_with_no_release_kern_is_built_from_ses_kern_in_the_background_and_the_greeting_says_so(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    # A fake go: `go build -o <out> ./cmd/kern` in SE's kern/ writes the fake kern.
    (path / "go").write_text(f"""#!/bin/sh
echo "go $* in $PWD" >> "$HOME/calls"
cat > "$3" <<'KERN'
{FAKE_KERN}KERN
chmod +x "$3"
""", encoding="utf-8")
    (path / "go").chmod(0o755)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-starting no release kern-v{KERN_VERSION} at {KERN_BASE}; "
                                        f"building it from {ROOT}/kern in the background")
    log = until(home, "kern hook SessionStart")
    assert any(line.startswith("go build -o ") and line.endswith(f"./cmd/kern in {ROOT}/kern") for line in log)
    assert f"kern start --root {project}" in log and os.access(kern_bin(home), os.X_OK)


def test_with_no_release_and_no_go_kern_failed_names_both(machine):
    home, project, base = machine
    path = fake_bin(base)
    run(home, path, project)
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert greeting_call(home).endswith(f"--kern-failed no release kern-v{KERN_VERSION} at {KERN_BASE}, and no go "
                                        f"to build it from {ROOT}/kern")


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
    (home / "kern-pin").unlink()  # se_modules.py kern-pin answers nothing
    (home / "calls").unlink()
    assert run(home, path, project, "--hook", stdin=START).returncode == 0
    assert "--kern" not in greeting_call(home)
    assert not any(line.startswith(("curl", "kern ")) for line in calls(home))
