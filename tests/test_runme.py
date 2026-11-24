"""RUNME.sh and RUNME.ps1, the generic pair every tool has (des-016), and the RUNME.conf each
project declares.

The real RUNME.sh runs from a copy in a temporary folder, beside a RUNME.conf of the test's own,
with fakes of `uname`, `id`, `sudo`, the package managers and the installers on a PATH that holds
nothing else, each recording its call: every route runs on every leg, the Windows one in Git's
bash. RUNME.ps1 runs only where PowerShell is (`-k powershell`, the Windows leg's own step).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import generated
import pytest
import se_modules
import se_workflows
from shell_paths import BASH, WINDOWS, link_tools, sh, tool_path

ROOT = Path(__file__).resolve().parents[1]
PAIR = ("RUNME.sh", "RUNME.ps1")
# kern's application template, in the clone of kern se.toml pins (tests/conftest.py places it).
TEMPLATE = se_modules.kern_dir(ROOT) / "template"
CEILINGS = {"RUNME.sh": 60, "RUNME.ps1": 40}
# The tools RUNME.sh runs besides the fakes; nothing else is on the test's PATH.
TOOLS = ("sh", "awk", "sed", "dirname", "cat", "chmod", "mkdir", "touch", "tr", "printf")
pytestmark = pytest.mark.skipif(BASH is None, reason="RUNME.sh runs in sh")

# Records its call; `<name>-fails` in the home makes it fail; else, where it installs, it puts the
# command `<installs>` into the installed folder.
FAKE = """#!/bin/sh
echo "@NAME@ $*" >> "$HOME/calls"
echo "@NAME@ says hi"
[ -f "$HOME/@NAME@-fails" ] && exit 3
for pkg in "$@"; do
  case "$pkg" in -*|install|update|-q|-y|-n) continue ;; esac
  printf '#!/bin/sh\\necho "%s ran"\\n' "$pkg" > "$HOME/installed/$pkg"; chmod +x "$HOME/installed/$pkg"
done
exit 0
"""
FAKE_UNAME = '#!/bin/sh\necho "${FAKE_UNAME:-Linux}"\n'
FAKE_ID = '#!/bin/sh\necho "${FAKE_UID:-1000}"\n'
FAKE_SUDO = '#!/bin/sh\necho "sudo $*" >> "$HOME/calls"\n[ "$1" = -n ] && shift\nexec "$@"\n'
# The tool: its arguments one a line between brackets, its folder, and the exit code TOOL_EXIT names.
# On Windows its folder by drive (`pwd -W`): MSYS names the temporary folder /tmp or by its drive,
# as the mount table its running processes share has it.
TOOL = """#!/bin/sh
echo "pwd=$(pwd)"
for arg in "$@"; do echo "[$arg]"; done
exit "${TOOL_EXIT:-0}"
""".replace("$(pwd)", "$(pwd -W)" if WINDOWS else "$(pwd)")


def shown(path: Path) -> str:
    """`path` as the tool shows its folder."""
    return path.as_posix() if WINDOWS else str(path)


def script(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def box(tmp_path):
    """A project holding RUNME.sh and a tool, an empty home and a PATH of fakes."""
    project, home, fakes, installed = (tmp_path / name for name in ("project", "home", "bin", "home/installed"))
    for folder in (project, fakes, installed):
        folder.mkdir(parents=True)
    shutil.copy2(ROOT / "RUNME.sh", project / "RUNME.sh")
    script(project / "tool", TOOL)
    link_tools(fakes, TOOLS)
    script(fakes / "uname", FAKE_UNAME)
    script(fakes / "id", FAKE_ID)
    script(fakes / "sudo", FAKE_SUDO)
    return project, home, fakes


def conf(project: Path, *lines: str) -> None:
    (project / "RUNME.conf").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def fake(fakes: Path, *names: str) -> None:
    for name in names:
        script(fakes / name, FAKE.replace("@NAME@", name))


# The arguments cross into bash in variables, never on a Windows command line, which quotes them
# differently from the MSYS runtime (as RUNME.ps1 hands them over): this rebuilds them and runs RUNME.sh.
REBUILD = ('i=0; set --; while [ "$i" -lt "$ARGC" ]; do eval "set -- \\"\\$@\\" \\"\\${ARG_$i}\\""; '
           'i=$((i + 1)); done; exec "$RUNME" "$@"')


def runme(box, *args: str, cwd: Path | None = None, **variables: str) -> subprocess.CompletedProcess:
    project, home, fakes = box
    env = {"HOME": sh(home), "PATH": tool_path(fakes, home / "installed"), **variables,
           "RUNME": sh(project / "RUNME.sh"), "REBUILD": REBUILD, "ARGC": str(len(args)),
           **{f"ARG_{i}": arg for i, arg in enumerate(args)}}
    return subprocess.run([BASH, "-c", "eval $REBUILD"], env=env, capture_output=True, text=True,
                          timeout=60, cwd=cwd or project, stdin=subprocess.DEVNULL)


def calls(home: Path) -> list[str]:
    log = home / "calls"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.spawns("shell: RUNME.sh's need check and run line are sh, run only as a process against fakes on PATH")
def test_with_nothing_missing_runme_installs_nothing_prints_nothing_and_runs_the_tool(box):
    project, home, fakes = box
    fake(fakes, "apt-get")
    conf(project, "need sh command sh", "get sh apt sh", 'run "$RUNME_ROOT/tool"')
    result = runme(box, "a")
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == f"pwd={shown(project)}\n[a]\n"
    assert calls(home) == []


@pytest.mark.spawns("shell: RUNME.sh's choice of the first way that fits, its installer on stderr, is sh, run only as "
                    "a process")
def test_a_missing_need_runs_its_first_fitting_way_on_stderr_then_the_tool(box):
    project, home, fakes = box
    fake(fakes, "apt-get", "dnf")
    conf(project, "need hello command hello", "get hello brew hello", "get hello apt hello", "get hello dnf hello",
         'run "$RUNME_ROOT/tool"')
    result = runme(box, FAKE_UID="0")
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"pwd={shown(project)}\n", "the installer's output goes to stderr"
    assert result.stderr.splitlines()[0] == ("RUNME: installing hello: apt-get update -q && "
                                             "apt-get install -y -q hello")
    assert "apt-get says hi" in result.stderr
    assert calls(home) == ["apt-get update -q", "apt-get install -y -q hello"], "as root, no sudo; dnf not tried"


@pytest.mark.parametrize("arguments", [
    ("plain",), ("with space", 'a "quote"', "it's", ""), ("--help",), ("--", "-x", "$HOME", "*")],
    ids=["one", "spaces-quotes-empty", "help", "dashes-and-expansions"])
@pytest.mark.spawns("shell: RUNME.sh's hand-off of every argument to the tool in the caller's folder is sh, run only "
                    "as a process")
def test_every_argument_reaches_the_tool_unchanged_in_the_callers_folder(box, arguments, tmp_path):
    project, _, _ = box
    conf(project, 'run "$RUNME_ROOT/tool"')
    caller = tmp_path / "elsewhere"
    caller.mkdir()
    result = runme(box, *arguments, cwd=caller)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.splitlines() == [f"pwd={shown(caller)}", *(f"[{arg}]" for arg in arguments)]


@pytest.mark.spawns("shell: RUNME.sh's exec of the tool, its exit code, is sh, run only as a process")
def test_the_tools_exit_code_is_runmes(box):
    project, _, _ = box
    conf(project, 'run "$RUNME_ROOT/tool"')
    assert runme(box, TOOL_EXIT="7").returncode == 7


@pytest.mark.spawns("shell: RUNME.sh's sudo -n without a terminal and its remedy line are sh, run only as a process")
def test_apt_get_runs_with_sudo_n_without_a_terminal_and_a_failed_install_names_sudo(box):
    project, home, fakes = box
    fake(fakes, "apt-get")
    (home / "apt-get-fails").touch()
    conf(project, "need hello command hello", "get hello apt hello", 'run "$RUNME_ROOT/tool"')
    result = runme(box)
    assert result.returncode == 1 and result.stdout == "", "the tool does not run"
    assert calls(home)[0] == "sudo -n apt-get update -q"
    assert result.stderr.splitlines()[-1] == ("RUNME: hello is missing; run: sudo apt-get update -q && "
                                              "sudo apt-get install -y -q hello")
    assert "sudo -n" not in result.stderr.splitlines()[-1]


@pytest.mark.skipif(WINDOWS or not hasattr(os, "openpty"), reason="a terminal for stdin: a pty")
@pytest.mark.spawns("shell: RUNME.sh's plain sudo where stdin is a terminal (a pty) is sh, run only as a process")
def test_with_a_terminal_apt_get_runs_with_plain_sudo(box):
    project, home, fakes = box
    fake(fakes, "apt-get")
    conf(project, "need hello command hello", "get hello apt hello", 'run "$RUNME_ROOT/tool"')
    leader, follower = os.openpty()
    try:
        env = {"HOME": sh(home), "PATH": tool_path(fakes, home / "installed")}
        result = subprocess.run([BASH, sh(project / "RUNME.sh")], env=env, capture_output=True, text=True,
                                timeout=60, cwd=project, stdin=follower)
    finally:
        os.close(leader)
        os.close(follower)
    assert result.returncode == 0, result.stderr
    assert calls(home)[:2] == ["sudo apt-get update -q", "apt-get update -q"]


@pytest.mark.spawns("shell: RUNME.sh's package manager probe is sh, run only as a process against fakes on PATH")
def test_dnf_where_apt_get_is_not(box):
    project, home, fakes = box
    fake(fakes, "dnf")
    conf(project, "need hello command hello", "get hello apt hello", "get hello dnf hello", 'run "$RUNME_ROOT/tool"')
    result = runme(box, FAKE_UID="0")
    assert result.returncode == 0, result.stderr
    assert calls(home) == ["dnf install -y hello"]


@pytest.mark.spawns("shell: RUNME.sh's fallback through the other ways and its remedy line are sh, run only as a "
                    "process")
def test_on_linux_without_apt_get_and_dnf_the_line_names_the_first_other_way_that_fits(box):
    project, home, fakes = box
    conf(project, "need hello command hello", "get hello apt hello", "get hello unix false first",
         "get hello any false second", 'run "$RUNME_ROOT/tool"')
    result = runme(box)
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.splitlines() == ["RUNME: installing hello: false first", "RUNME: installing hello: false second",
                                          "RUNME: hello is missing; run: false first"]


@pytest.mark.spawns("shell: RUNME.sh's refusal where no way fits is sh, run only as a process")
def test_a_need_no_way_fits_says_so_and_never_runs_the_tool(box):
    project, _, _ = box
    conf(project, "need hello command hello", "get hello windows nothing-here", 'run "$RUNME_ROOT/tool"')
    result = runme(box)
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == "RUNME: hello is missing; run: what installs it here (RUNME.conf names no way)\n"


@pytest.mark.spawns("shell: RUNME.sh's command way, run in the project's folder, is sh, run only as a process")
def test_a_command_way_runs_in_the_projects_folder(box, tmp_path):
    project, _, _ = box
    conf(project, "need made file made", "get made unix touch made", 'run "$RUNME_ROOT/tool"')
    caller = tmp_path / "caller"
    caller.mkdir()
    result = runme(box, cwd=caller)
    assert result.returncode == 0, result.stderr
    assert (project / "made").exists() and not (caller / "made").exists()


@pytest.mark.spawns("shell: RUNME.sh's file need check, its .exe twin, is sh, run only as a process")
def test_a_file_need_counts_its_exe_twin(box):
    project, home, _ = box
    (project / "tool.exe").touch()
    conf(project, "need built file tool2", "get built any false", 'run "$RUNME_ROOT/tool"')
    (project / "tool2.exe").touch()
    result = runme(box)
    assert result.returncode == 0 and result.stderr == "" and calls(home) == []


@pytest.mark.spawns("shell: RUNME.sh's path lines and their tilde are sh, run only as a process")
def test_path_lines_come_after_the_callers_path_and_a_tilde_is_the_home(box):
    project, home, fakes = box
    (home / "tools").mkdir()
    script(home / "tools" / "hello", '#!/bin/sh\necho "home hello"\n')
    script(fakes / "hello", '#!/bin/sh\necho "caller hello"\n')
    conf(project, "path ~/tools", "path inside", "need hello command hello", """run sh -c 'hello; echo "$PATH"'""")
    result = runme(box)
    assert result.returncode == 0, result.stderr
    first, path = result.stdout.splitlines()
    assert first == "caller hello", "the caller's PATH comes first"
    assert path.endswith(f":{sh(home)}/tools:{sh(project)}/inside")


@pytest.mark.spawns("shell: RUNME.sh's refusals without a RUNME.conf or a run line are sh, run only as a process")
def test_without_a_conf_or_a_run_line_runme_says_so_and_exits_2(box):
    project, _, _ = box
    result = runme(box)
    assert result.returncode == 2 and result.stderr == f"RUNME: no RUNME.conf in {sh(project)}\n"
    conf(project, "need sh command sh")
    result = runme(box)
    assert result.returncode == 2 and result.stderr == "RUNME: RUNME.conf has no run line\n"


@pytest.mark.spawns("shell: RUNME.sh's winget way and its PATH reread through PowerShell are sh, run only as a "
                    "process against fakes")
def test_on_windows_winget_installs_and_path_is_read_again_from_the_registry(box):
    project, home, fakes = box
    fake(fakes, "winget")
    # The registry's PATH, as PowerShell answers it, names the folder the installer filled.
    script(fakes / "powershell", f'#!/bin/sh\necho "powershell" >> "$HOME/calls"\nprintf "C:\\\\later\\r\\n"\n')
    script(fakes / "cygpath", f'#!/bin/sh\necho "{sh(home)}/later"\n')
    (home / "later").mkdir()
    script(fakes / "winget", FAKE.replace("@NAME@", "winget").replace('"$HOME/installed/$pkg"', '"$HOME/later/$pkg"'))
    conf(project, "need Hello.Id command Hello.Id", "get Hello.Id apt hello", "get Hello.Id winget Hello.Id",
         'run "$RUNME_ROOT/tool"')
    result = runme(box, FAKE_UNAME="MINGW64_NT-10.0")
    assert result.returncode == 0, result.stderr
    assert result.stderr.splitlines()[0] == ("RUNME: installing Hello.Id: winget install --id Hello.Id -e --source winget "
                                             "--accept-package-agreements --accept-source-agreements")
    assert calls(home)[1] == "powershell", "PATH read again after the install"
    assert not any(line.startswith("sudo") for line in calls(home)), "no sudo on Windows"


# SE's own declaration.
def needs(text: str) -> list[str]:
    seen: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if parts[:1] == ["need"] and parts[1] not in seen:
            seen.append(parts[1])
    return seen


def test_ses_conf_declares_what_se_needs_in_order_and_runs_se():
    text = (ROOT / "RUNME.conf").read_text(encoding="utf-8")
    assert needs(text) == "git curl bash claude uv se".split()
    assert [line for line in text.splitlines() if line.startswith("run ")] == ["run se"]
    assert "need se file .se/.runtime/runme-se" in text.splitlines()
    assert "get se any bash scripts/bootstrap.sh --binary" in text.splitlines()


@pytest.mark.spawns("shell: RUNME.sh with SE's own RUNME.conf, its file need placed once by the bootstrap way, is sh, "
                    "run only as a process")
def test_with_an_older_se_in_the_home_runme_places_the_pinned_one_once_then_runs_it(box):
    project, home, fakes = box
    shutil.copy2(ROOT / "RUNME.conf", project / "RUNME.conf")
    for name in "git curl claude uv".split():
        script(fakes / name, "#!/bin/sh\n")
    script(fakes / "bash", f'#!/bin/sh\nexec "{sh(Path(BASH))}" "$@"\n')
    (home / ".se" / "bin").mkdir(parents=True)
    script(home / ".se" / "bin" / "se", '#!/bin/sh\necho "old se $*"\n')
    (project / "scripts").mkdir()
    script(project / "scripts" / "bootstrap.sh", """#!/bin/sh
echo "bootstrap $*" >> "$HOME/calls"
printf '#!/bin/sh\\necho "pinned se $*"\\n' > "$HOME/.se/bin/se"
mkdir -p .se/.runtime && echo 1.0.0 > .se/.runtime/runme-se
""")
    first = runme(box, "--help")
    assert first.returncode == 0, first.stderr
    assert first.stdout == "pinned se --help\n"
    assert first.stderr.splitlines()[0] == "RUNME: installing se: bash scripts/bootstrap.sh --binary"
    second = runme(box, "--help")
    assert second.stdout == "pinned se --help\n" and second.stderr == ""
    assert calls(home) == ["bootstrap --binary"], "placed once"


# The pair itself, the same in every project.
def confs() -> list[Path]:
    """Every RUNME.conf of SE's checkout and of kern's template (in .se/, which the walk skips)."""
    found = []
    for folder, dirs, files in [*os.walk(ROOT), *os.walk(TEMPLATE)]:
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        found += [Path(folder) / name for name in files if name == "RUNME.conf"]
    return found


def test_every_runme_conf_names_gits_winget_id():
    found = confs()
    assert {ROOT / "RUNME.conf", TEMPLATE / "RUNME.conf"} <= set(found)
    for path in found:
        assert re.search(r"(?m)^get git winget \S+$", path.read_text(encoding="utf-8")), path


def unmarked(text: str) -> str:
    """kern's copy of a file of the pair without the marker se_workflows.py write gives it (kern
    2.1.0 marks every generated file); a copy without that marker fails."""
    text = text.replace("\r\n", "\n")
    marker = generated.marker_at(text, "hash")
    assert marker is not None and marker.generator == se_workflows.GENERATOR, (
        "kern's copy names no se_workflows.py write as its generator")
    lines = text.split("\n")
    del lines[generated.place(text, "hash")]
    return "\n".join(lines)


def test_the_templates_pair_is_ses_byte_for_byte_and_names_no_project():
    named: set[str] = set()
    for path in confs():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 3)
            if parts[:1] == ["get"] and len(parts) == 4 and parts[2] == "winget":
                named.add(parts[3])
            named.update(re.findall(r"https?://\S+", line))
    for name in PAIR:
        data = (ROOT / name).read_bytes()
        # Line endings are the checkout's (git's autocrlf on Windows), not the file's; kern's copy is
        # SE's file with the marker of its generator.
        assert unmarked((TEMPLATE / name).read_text(encoding="utf-8")) == data.decode("ascii").replace("\r\n", "\n"), (
            f"kern's template/{name}, without its marker, differs from {name}")
        text = data.decode("ascii")  # ASCII, for Windows PowerShell 5.1
        assert len(text.splitlines()) <= CEILINGS[name]
        if name == "RUNME.sh":  # sh reads LF only (.gitattributes); PowerShell reads either
            assert b"\r" not in data
        for word in (r"\bse\b", r"\bSE\b", r"\bapp\b"):
            assert not re.search(word, text), f"{name} holds {word}"
        for term in named:
            assert term not in text, f"{name} names {term}, which a RUNME.conf owns"
    if not WINDOWS:
        assert os.access(ROOT / "RUNME.sh", os.X_OK) and os.access(TEMPLATE / "RUNME.sh", os.X_OK)


def test_the_template_readme_opens_with_its_description_then_getting_it_running():
    """kern's application template; SE's own README is one page, its command first
    (tests/test_readme.py)."""
    text = (TEMPLATE / "README.md").read_text(encoding="utf-8")
    first = re.search(r"(?m)^## .*$", text)
    assert first[0] == "## Getting it running"
    above = [line for line in text[:first.start()].splitlines() if line.strip() and not line.startswith("#")]
    assert above, "a description above the first section"


# RUNME.ps1, from PowerShell itself: Windows only (the Windows leg's step `RUNME from PowerShell`).
POWERSHELL = shutil.which("powershell") if WINDOWS else None
powershell_only = pytest.mark.skipif(POWERSHELL is None, reason="RUNME.ps1 runs where Windows PowerShell is")


def quoted(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def ps_box(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    for name in PAIR:
        shutil.copy2(ROOT / name, project / name)
    script(project / "tool", TOOL)
    conf(project, "get git winget Git.Git", 'run "$RUNME_ROOT/tool"')
    return project


def ps(project: Path, line: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                           f"& {quoted(str(project / 'RUNME.ps1'))} {line}; exit $LASTEXITCODE"],
                          capture_output=True, text=True, timeout=120, cwd=project, env=env)


@powershell_only
@pytest.mark.spawns("shell: RUNME.ps1's hand-off of every argument to RUNME.sh through Git's bash is PowerShell, run "
                    "only as a process (the Windows leg)")
def test_powershell_hands_every_argument_to_runme_sh_with_its_exit_code(tmp_path):
    project = ps_box(tmp_path)
    arguments = ["plain", "with space", 'a "quote"', "it's", "", "--help", "$HOME"]
    env = {**os.environ, "TOOL_EXIT": "5"}
    result = ps(project, " ".join(quoted(arg) for arg in arguments), env)
    assert result.returncode == 5, result.stderr
    assert result.stdout.splitlines()[1:] == [f"[{arg}]" for arg in arguments]


@powershell_only
@pytest.mark.spawns("shell: RUNME.ps1's reading of a double dash is PowerShell's own, run only as a process (the "
                    "Windows leg)")
def test_powershell_drops_an_unquoted_double_dash_and_keeps_a_quoted_one(tmp_path):
    project = ps_box(tmp_path)
    result = ps(project, "a -- b '--'")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1:] == ["[a]", "[b]", "[--]"]


@powershell_only
@pytest.mark.spawns("shell: RUNME.ps1's refusal without Git's bash or winget is PowerShell, run only as a process "
                    "(the Windows leg)")
def test_powershell_without_gits_bash_or_winget_prints_one_line_and_exits_1(tmp_path):
    project = ps_box(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    env = {**os.environ, "PATH": f"{system};{system / 'WindowsPowerShell' / 'v1.0'}", "ProgramW6432": str(empty),
           "ProgramFiles": str(empty), "ProgramFiles(x86)": str(empty), "LOCALAPPDATA": str(empty)}
    result = ps(project, "a", env)
    assert result.returncode == 1
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert lines == ["RUNME: install Git for Windows, then run RUNME again: RUNME runs in the bash Git ships"]
