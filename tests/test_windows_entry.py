"""scripts/bash.ps1, the hand-off from PowerShell to the bash Git for Windows ships.

Its choice is one pure function, Select-SeBash, of git's location and the paths that exist; the
cases below list it. The real runs start the hand-off from PowerShell, as a PowerShell hook line
would, so they run only where PowerShell is: the Windows leg of kern-platforms runs this file from
a PowerShell step. That nothing but the build's setting se.toml [plugin] powershell_hooks names
the file runs everywhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

PROJECT = Path(__file__).resolve().parents[1]
HANDOFF = PROJECT / "scripts" / "bash.ps1"
INSTALL_LINE = ("SE needs the bash that Git for Windows ships: install Git for Windows "
                "(winget install --id Git.Git -e, or https://git-scm.com/download/win)")

POWERSHELLS = [shell for shell in ("powershell", "pwsh") if os.name == "nt" and shutil.which(shell)]
windows = pytest.mark.skipif(not POWERSHELLS, reason="the hand-off runs where PowerShell and Git's bash are: Windows")

GIT = PureWindowsPath("C:/Program Files/Git")
WSL = PureWindowsPath("C:/Windows/System32/bash.exe")


def quoted(text: str) -> str:
    """A PowerShell single-quoted literal of text."""
    return "'" + text.replace("'", "''") + "'"


def powershell(shell: str, command: str, env: dict[str, str] | None = None,
               stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run([shutil.which(shell) or shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", command], input=stdin, capture_output=True, text=True, check=False,
                          env=env, timeout=120)


def select(shell: str, git: str = "", places: tuple[PureWindowsPath, ...] = (), path_bash: str = "",
           exists: tuple[PureWindowsPath, ...] = ()) -> dict[str, str]:
    """Select-SeBash's answer, dot-sourcing the hand-off so it only defines its functions."""
    def array(items: tuple[PureWindowsPath, ...]) -> str:
        return "@(" + ", ".join(quoted(str(item)) for item in items) + ")"
    result = powershell(shell, f". {quoted(str(HANDOFF))}; Select-SeBash -Git {quoted(git)} -Places {array(places)} "
                               f"-PathBash {quoted(path_bash)} -Exists {array(exists)} | ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def chosen(answer: dict[str, str]) -> dict[str, str]:
    return {"case": answer["Case"], "bash": PureWindowsPath(answer["Bash"]).as_posix() if answer["Bash"] else ""}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("git", [GIT / "cmd" / "git.exe", GIT / "bin" / "git.exe", GIT / "mingw64" / "bin" / "git.exe"])
def test_it_chooses_gits_wrapper_bash_beside_git_over_wsls_launcher(shell: str, git: PureWindowsPath) -> None:
    answer = select(shell, git=str(git), path_bash=str(WSL),
                    exists=(GIT / "usr" / "bin" / "bash.exe", GIT / "bin" / "bash.exe"))
    assert chosen(answer) == {"case": "git", "bash": (GIT / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_without_the_wrapper_it_chooses_gits_plain_bash(shell: str) -> None:
    answer = select(shell, git=str(GIT / "cmd" / "git.exe"), exists=(GIT / "usr" / "bin" / "bash.exe",))
    assert chosen(answer) == {"case": "git", "bash": (GIT / "usr" / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_with_git_not_on_path_it_finds_git_in_a_usual_install_place(shell: str) -> None:
    user = PureWindowsPath("D:/Local/Programs/Git")
    answer = select(shell, places=(GIT, user), path_bash=str(WSL), exists=(user / "bin" / "bash.exe",))
    assert chosen(answer) == {"case": "install", "bash": (user / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("launcher", [WSL, PureWindowsPath("C:/Windows/SysWOW64/bash.exe"),
                                      PureWindowsPath("D:/Local/Microsoft/WindowsApps/bash.exe")])
def test_only_wsls_launcher_on_path_is_no_bash(shell: str, launcher: PureWindowsPath) -> None:
    assert chosen(select(shell, places=(GIT,), path_bash=str(launcher))) == {"case": "wsl", "bash": ""}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_a_bash_on_path_that_is_not_wsls_launcher_is_used_last(shell: str) -> None:
    other = PureWindowsPath("C:/msys64/usr/bin/bash.exe")
    assert chosen(select(shell, places=(GIT,), path_bash=str(other))) == {"case": "path", "bash": other.as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_nothing_found_is_no_bash(shell: str) -> None:
    assert chosen(select(shell, git=str(GIT / "cmd" / "git.exe"), places=(GIT,))) == {"case": "none", "bash": ""}


ARGUMENTS = ["plain", "two  spaces", "", 'a "quoted" word', "it's", "C:\\trailing\\", "back\\\\slashes",
             "--", "-c", "--hook", "$HOME *.sh", "semi;colon & pipe | <angle>", "%PATH%", "!bang"]


def handoff(shell: str, script: Path, arguments: list[str], env: dict[str, str] | None = None,
            stdin: str = "") -> subprocess.CompletedProcess[str]:
    line = " ".join(quoted(part) for part in [str(HANDOFF), str(script), *arguments])
    return powershell(shell, f"& {line}; exit $LASTEXITCODE", env=env, stdin=stdin)


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_from_powershell_every_argument_reaches_the_script_unchanged_with_its_exit_code(
        shell: str, tmp_path: Path) -> None:
    script = tmp_path / "echo.sh"
    script.write_text("printf '%s\\n' \"$#\"\nfor a in \"$@\"; do printf '<%s>\\n' \"$a\"; done\nexit 7\n",
                      encoding="utf-8", newline="\n")
    result = handoff(shell, script, ARGUMENTS)
    assert result.returncode == 7, result.stderr
    assert result.stdout.splitlines() == [str(len(ARGUMENTS))] + [f"<{argument}>" for argument in ARGUMENTS]


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_an_unquoted_switch_on_the_line_reaches_the_script_as_written(shell: str, tmp_path: Path) -> None:
    script = tmp_path / "echo.sh"
    script.write_text("for a in \"$@\"; do printf '<%s>\\n' \"$a\"; done\n", encoding="utf-8", newline="\n")
    result = powershell(shell, f"& {quoted(str(HANDOFF))} {quoted(str(script))} --hook; exit $LASTEXITCODE")
    assert (result.returncode, result.stdout.splitlines()) == (0, ["<--hook>"]), result.stderr


def bare_environment(tmp_path: Path, path: list[Path], places: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name in [name for name in env if name.upper() == "PATH"]:
        del env[name]
    env["PATH"] = os.pathsep.join(str(entry) for entry in path)
    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        env[name] = str(places)
    return env


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("wsl", [True, False], ids=["wsl-launcher-on-path", "nothing-on-path"])
def test_with_no_git_bash_it_prints_the_one_install_line(shell: str, wsl: bool, tmp_path: Path) -> None:
    launcher = tmp_path / "Windows" / "System32" / "bash.exe"
    launcher.parent.mkdir(parents=True)
    if wsl:
        launcher.write_bytes(b"")
    places = tmp_path / "Program Files"
    places.mkdir()
    script = tmp_path / "never.sh"
    script.write_text("echo ran\n", encoding="utf-8", newline="\n")
    result = handoff(shell, script, ["x"], env=bare_environment(tmp_path, [launcher.parent], places))
    assert (result.returncode, result.stdout, result.stderr.splitlines()) == (127, "", [INSTALL_LINE])


# The tools scripts/bootstrap.sh calls, Git's own bash builtins aside; uv and python are the
# runner's, not Git's, so they are not looked for here.
TOOLS = ["uname", "mktemp", "cut", "mkdir", "grep", "find", "tar", "unzip", "sha256sum", "dirname", "mv", "rm", "cat", "curl"]


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_from_a_powershell_whose_path_has_no_git_the_script_finds_bootstraps_tools(shell: str, tmp_path: Path) -> None:
    script = tmp_path / "tools.sh"
    script.write_text(
        f"for t in {' '.join(TOOLS)}; do command -v \"$t\" >/dev/null || {{ echo \"missing $t\"; exit 1; }}; done\n"
        "work=$(mktemp -d) && mkdir \"$work/a\" && printf 'x' > \"$work/a/f\" && mv \"$work/a/f\" \"$work/a/g\"\n"
        "find \"$work\" -name g -type f | grep -c /a/g\n"
        "tar -cf \"$work/t.tar\" -C \"$work\" a && tar -tf \"$work/t.tar\" | grep -c a/g\n"
        "sha256sum \"$work/a/g\" | cut -c1-8\n"
        "dirname /x/y\ncurl --version >/dev/null && echo curl\nuname -s | cut -c1-4\nrm -r \"$work\"\ncat\n",
        encoding="utf-8", newline="\n")
    system = Path(os.environ["SystemRoot"])
    env = bare_environment(tmp_path, [system / "System32", system], tmp_path / "nowhere")
    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if name in os.environ:
            env[name] = os.environ[name]
    result = handoff(shell, script, [], env=env, stdin="from stdin\n")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[:5] == ["1", "1", "2d711642", "/x", "curl"], lines
    assert lines[5] in ("MING", "MSYS"), lines
    assert lines[6:] == ["from stdin"], lines


_spec = importlib.util.spec_from_file_location("se_plugin", PROJECT / "scripts" / "se_plugin.py")
se_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se_plugin)

# What names a script: the plugin build, the layouts it generates (Copilot's and Claude Code's),
# the hooks, the start and setup scripts, the agents and the README. The build names the hand-off
# only behind powershell_hooks, unset in SE's se.toml, so the layouts it writes name it nowhere.
NAMERS = [".github/hooks", ".github/plugin", ".github/agents", ".github/skills", "agents", "skills",
          ".claude-plugin", ".githooks", "scripts", "src/agents", "src/skills", "README.md", "AGENTS.md"]
SETTING_OWNER = PROJECT / "scripts" / "se_plugin.py"


def test_nothing_but_the_unset_build_setting_names_the_handoff() -> None:
    assert "powershell_hooks" not in (PROJECT / "se.toml").read_text(encoding="utf-8")
    assert se_plugin.HANDOFF in SETTING_OWNER.read_text(encoding="utf-8")
    named = []
    for namer in NAMERS:
        root = PROJECT / namer
        files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        assert files, namer
        for path in files:
            if path in (HANDOFF, SETTING_OWNER) or "__pycache__" in path.parts:
                continue
            if "bash.ps1" in path.read_text(encoding="utf-8", errors="replace"):
                named.append(path.relative_to(PROJECT).as_posix())
    assert named == []
