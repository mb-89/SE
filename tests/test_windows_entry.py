"""scripts/bash.ps1, the hand-off from PowerShell to the bash Git for Windows ships.

Its choice is one pure function, Select-SeBash, of git's location and the paths that exist; the
cases below list it. The real runs start the hand-off from PowerShell, as a PowerShell hook line
would, so they run only where PowerShell is: the Windows leg of kern-platforms runs this file from
a PowerShell step, with the hooks' PowerShell lines the build writes where se.toml [plugin]
powershell_hooks is "handoff". That nothing but that setting names the file runs everywhere.
The session start's detached spawn (scripts/se_start.py) is tested here too, beside the hand-off,
so the Windows leg runs its flags and a real detached child.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
import waiting

PROJECT = Path(__file__).resolve().parents[1]
HANDOFF = PROJECT / "scripts" / "bash.ps1"
INSTALL_LINE = ("SE needs the bash that Git for Windows ships: install Git for Windows "
                "(winget install --id Git.Git -e, or https://git-scm.com/download/win)")

POWERSHELLS = [shell for shell in ("powershell", "pwsh") if os.name == "nt" and shutil.which(shell)]
windows = pytest.mark.skipif(not POWERSHELLS, reason="the hand-off runs where PowerShell and Git's bash are: Windows")
# What the Windows cases prove is PowerShell's and Git's bash's own work, which runs only as a
# process: the spawn guard (scripts/spawn_guard.py) passes them on the Windows leg by these marks.
SELECTS = pytest.mark.spawns("shell: Select-SeBash is PowerShell (scripts/bash.ps1), run only by a "
                             "PowerShell process")
HANDS_OFF = pytest.mark.spawns("shell: scripts/bash.ps1 hands off from a PowerShell process to Git's bash, "
                               "both run only as processes")
HOOK_LINE = pytest.mark.spawns("shell: a generated PowerShell hook line runs scripts/bash.ps1 and Git's bash, "
                               "run only as processes")

GIT = PureWindowsPath("C:/Program Files/Git")
WSL = PureWindowsPath("C:/Windows/System32/bash.exe")


def quoted(text: str) -> str:
    """A PowerShell single-quoted literal of text."""
    return "'" + text.replace("'", "''") + "'"


def powershell(shell: str, command: str, env: dict[str, str] | None = None,
               stdin: str = "", cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([shutil.which(shell) or shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", command], input=stdin, capture_output=True, text=True, check=False,
                          env=env, timeout=120, cwd=cwd)


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
@SELECTS
def test_it_chooses_gits_wrapper_bash_beside_git_over_wsls_launcher(shell: str, git: PureWindowsPath) -> None:
    answer = select(shell, git=str(git), path_bash=str(WSL),
                    exists=(GIT / "usr" / "bin" / "bash.exe", GIT / "bin" / "bash.exe"))
    assert chosen(answer) == {"case": "git", "bash": (GIT / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@SELECTS
def test_without_the_wrapper_it_chooses_gits_plain_bash(shell: str) -> None:
    answer = select(shell, git=str(GIT / "cmd" / "git.exe"), exists=(GIT / "usr" / "bin" / "bash.exe",))
    assert chosen(answer) == {"case": "git", "bash": (GIT / "usr" / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@SELECTS
def test_with_git_not_on_path_it_finds_git_in_a_usual_install_place(shell: str) -> None:
    user = PureWindowsPath("D:/Local/Programs/Git")
    answer = select(shell, places=(GIT, user), path_bash=str(WSL), exists=(user / "bin" / "bash.exe",))
    assert chosen(answer) == {"case": "install", "bash": (user / "bin" / "bash.exe").as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("launcher", [WSL, PureWindowsPath("C:/Windows/SysWOW64/bash.exe"),
                                      PureWindowsPath("D:/Local/Microsoft/WindowsApps/bash.exe")])
@SELECTS
def test_only_wsls_launcher_on_path_is_no_bash(shell: str, launcher: PureWindowsPath) -> None:
    assert chosen(select(shell, places=(GIT,), path_bash=str(launcher))) == {"case": "wsl", "bash": ""}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@SELECTS
def test_a_bash_on_path_that_is_not_wsls_launcher_is_used_last(shell: str) -> None:
    other = PureWindowsPath("C:/msys64/usr/bin/bash.exe")
    assert chosen(select(shell, places=(GIT,), path_bash=str(other))) == {"case": "path", "bash": other.as_posix()}


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@SELECTS
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
@HANDS_OFF
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
@HANDS_OFF
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
@HANDS_OFF
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
@HANDS_OFF
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

# The payload a host sends a hook on stdin, which the hook script must still read.
PAYLOAD = '{"session_id": "s-1", "hook_event_name": "Stop"}'


def handoff_lines(plugin: bool) -> list[tuple[str, str]]:
    """Each (script, PowerShell line) of the hooks file the build writes with powershell_hooks set to
    "handoff": the repository's (.github/hooks/se.json) or a plugin install's (.github/plugin/hooks.json)."""
    hooks = json.loads(se_plugin._copilot_hooks(plugin=plugin, setting="handoff"))["hooks"]
    return [(se_plugin.COPILOT_HOOKS[event][0], entry["powershell"])
            for event, entries in hooks.items() for entry in entries]


def hook_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A folder holding the hand-off and, in place of each hook script, one that prints its
    arguments and its input and fails; and an empty project folder a plugin's hooks run in."""
    folder, project = tmp_path / "se", tmp_path / "project"
    (folder / "scripts").mkdir(parents=True)
    project.mkdir()
    shutil.copy(HANDOFF, folder / "scripts" / "bash.ps1")
    for command, _ in se_plugin.COPILOT_HOOKS.values():
        (folder / command.split(" ")[0]).write_text(
            "for a in \"$@\"; do printf '<%s>\\n' \"$a\"; done\ncat\nexit 3\n", encoding="utf-8", newline="\n")
    return folder, project


def run_hook_line(shell: str, line: str, plugin: bool, folder: Path, project: Path,
                  env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ if env is None else env)
    if plugin:
        env["PLUGIN_ROOT"] = str(folder)
    return powershell(shell, line, env=env, stdin=PAYLOAD, cwd=project if plugin else folder)


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("plugin", [False, True], ids=["repository-hooks", "plugin-hooks"])
@HOOK_LINE
def test_a_generated_handoff_hook_line_reaches_its_script_with_its_input_and_exits_0(
        shell: str, plugin: bool, tmp_path: Path) -> None:
    folder, project = hook_tree(tmp_path)
    for command, line in handoff_lines(plugin):
        result = run_hook_line(shell, line, plugin, folder, project)
        arguments = [f"<{argument}>" for argument in command.split(" ")[1:]]
        assert (result.returncode, result.stdout.splitlines()) == (0, [*arguments, PAYLOAD]), \
            (line, result.stderr)


@windows
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("plugin", [False, True], ids=["repository-hooks", "plugin-hooks"])
@HOOK_LINE
def test_with_no_git_bash_a_generated_handoff_hook_line_prints_the_install_line_and_exits_0(
        shell: str, plugin: bool, tmp_path: Path) -> None:
    folder, project = hook_tree(tmp_path)
    places = tmp_path / "Program Files"
    places.mkdir()
    # Only Windows PowerShell's own folder: the line starts it by name, and it holds no bash.
    starter = Path(shutil.which("powershell") or "").parent
    for command, line in handoff_lines(plugin):
        result = run_hook_line(shell, line, plugin, folder, project,
                               env=bare_environment(tmp_path, [starter], places))
        assert (result.returncode, result.stdout) == (0, ""), (line, result.stderr)
        assert INSTALL_LINE in result.stderr.splitlines(), (line, result.stderr)


# What names a script: the plugin build, the layout it generates (for both hosts),
# the hooks, the start and setup scripts, the agents and the README. The build names the hand-off
# only behind powershell_hooks, unset in SE's se.toml, so the layout it writes names it nowhere.
NAMERS = [".github/hooks", ".github/plugin", "agents", "skills",
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


# The session start's background check: a detached child with a hidden console on Windows.
CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, DETACHED_PROCESS = 0x00000200, 0x08000000, 0x00000008
SE_START = PROJECT / "scripts" / "se_start.py"


def load_se_start():
    spec = importlib.util.spec_from_file_location("se_start_spawn", SE_START)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_windows_detached_start_hides_its_console_instead_of_having_none() -> None:
    flags = load_se_start().detached_options("nt")["creationflags"]
    assert flags & CREATE_NO_WINDOW and flags & CREATE_NEW_PROCESS_GROUP
    assert not flags & DETACHED_PROCESS


CHILD = """
import socket, sys
from pathlib import Path
port, marker = int(sys.argv[1]), Path(sys.argv[2])
with socket.create_connection(("127.0.0.1", port)) as test:  # rings the test's bell, then waits for go
    if test.recv(2) == b"go":
        marker.write_text("done", encoding="utf-8")
"""

PARENT = """
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("se_start", sys.argv[1])
se_start = importlib.util.module_from_spec(spec)
sys.modules["se_start"] = se_start
spec.loader.exec_module(se_start)
se_start._spawn_detached([sys.executable, *sys.argv[2:]])
"""


DETACHED = pytest.mark.spawns("detached: se_start.py's _spawn_detached; only a real parent process that "
                              "exits shows the child it started outlives it")


@DETACHED
def test_a_detached_child_outlives_the_parent_that_started_it(tmp_path: Path) -> None:
    """The child rings the test's bell and waits there for the go, which the test sends only once
    the parent has exited; the child's marker, written after the go, shows it outlived it."""
    child, marker = tmp_path / "child.py", tmp_path / "marker"
    child.write_text(CHILD, encoding="utf-8")
    bell = waiting.Bell()
    try:
        parent = subprocess.run([sys.executable, "-c", PARENT, str(SE_START), str(child), str(bell.port),
                                 str(marker)], capture_output=True, text=True, timeout=120, check=False)
        assert parent.returncode == 0, parent.stderr
        with bell.answer() as connection:
            assert not marker.exists()
            connection.sendall(b"go")
            assert connection.recv(1) == b""  # the child closes once the marker is written
    finally:
        bell.close()
    assert marker.read_text(encoding="utf-8") == "done"
