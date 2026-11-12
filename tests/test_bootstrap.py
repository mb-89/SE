"""bootstrap.sh brings uv, Python and the modules into an empty home, and says what it cannot do."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap.sh"
TOOLS = ("bash", "sh", "dirname", "grep", "cat", "env", "chmod", "mkdir", "touch", "uname")
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bootstrap.sh runs in bash")

# A fake uv: `python find` fails until `python install` ran; SE's start prints a greeting unless
# `status-fails` exists; every call is logged.
FAKE_UV = """#!/bin/sh
echo "uv $*" >> "$HOME/calls"
case "$*" in *se_start.py*) [ -f "$HOME/status-fails" ] && exit 1; echo '{"greeting": 1}'; exit 0 ;; esac
case "$1 $2" in
  "python find") [ -f "$HOME/python" ] ;;
  "python install") touch "$HOME/python" ;;
esac
"""
# A fake uv installer, as astral.sh's: puts uv into ~/.local/bin, or fails while "offline".
FAKE_CURL = f"""#!/bin/sh
echo "curl $*" >> "$HOME/calls"
[ -f "$HOME/offline" ] && exit 6
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
        (folder / tool).symlink_to(shutil.which(tool))
    (folder / "curl").write_text(FAKE_CURL, encoding="utf-8")
    (folder / "curl").chmod(0o755)
    if git:
        (folder / "git").write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / "git").chmod(0o755)
    return folder


def run(home: Path, path: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": str(path), "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def calls(home: Path) -> list[str]:
    log = home / "calls"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
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
