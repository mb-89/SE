"""The MCP door's launcher, scripts/se_mcp.sh and its PowerShell twin se_mcp.ps1 (README "MCP door"):
MCP alone on standard output, the rest in a log, and an answer at once where the binary is missing."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from shell_paths import BASH, WINDOWS, sh

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "se_mcp.sh"
TWIN = ROOT / "scripts" / "se_mcp.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
# What a host sends first: initialize, its notification, the tool list, a call, a method no door has.
SESSION = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "host", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": "c", "method": "tools/call", "params": {"name": "status", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
]
needs_bash = pytest.mark.skipif(BASH is None, reason="se_mcp.sh runs in bash")


# The host variables a plugin install reads or must ignore; launch() passes none of the runner's on.
PLUGIN_VARIABLES = ("CLAUDE_PROJECT_DIR", "COPILOT_PROJECT_DIR", "COPILOT_SESSION_CWD", "SE_SESSION_CWD",
                    "PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "SE_MCP_PLUGIN_PROJECT", "SE_MCP_PLUGIN_FOLDER")


def launch(kind: str, home: Path | None, project: Path, stdin: str, se: Path = ROOT, parent: Path | None = None,
           **env: str) -> subprocess.CompletedProcess:
    """Run the launcher of the SE folder `se`; with `parent`, from a shell whose working directory it is."""
    dropped = {"SE_MCP_BIN", *PLUGIN_VARIABLES} | ({"HOME", "USERPROFILE"} if home is None else set())
    environment = {key: value for key, value in os.environ.items() if key not in dropped}
    if home is not None:
        environment.update(HOME=str(home), USERPROFILE=str(home))
    environment.update(env)
    if kind == "bash":
        command = [BASH, sh(se / "scripts" / "se_mcp.sh"), "--root", sh(project)]
        if parent is not None:  # `; :` keeps the shell alive, the launcher's parent
            command = [BASH, "-c", '"$BASH" "$@"; :', "parent", *command[1:]]
    else:
        command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(se / "scripts" / "se_mcp.ps1"), "--root", str(project)]
    return subprocess.run(command, input=stdin, capture_output=True, text=True, encoding="utf-8", env=environment,
                          cwd=parent, timeout=60, check=False)


def answers(result: subprocess.CompletedProcess) -> dict:
    """Each answer on standard output by its id; every line must be one JSON-RPC message."""
    found = {}
    for line in result.stdout.splitlines():
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0", line
        found[message["id"]] = message
    return found


LAUNCHERS = [pytest.param("bash", marks=needs_bash),
             pytest.param("powershell", marks=pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell here"))]


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 answer MCP themselves where the binary is missing; that "
                    "door is shell, run only as a process")
def test_without_the_binary_the_launcher_answers_at_once_naming_the_setup(tmp_path, kind):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    result = launch(kind, home, project, "".join(json.dumps(m) + "\n" for m in SESSION))
    assert result.returncode == 0, result.stderr
    got = answers(result)
    assert sorted(got, key=str) == sorted([1, 2, "c", 4], key=str), "the notification has no answer"
    assert got[1]["result"]["serverInfo"]["name"] == "se"
    assert got[1]["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in got[2]["result"]["tools"]] == ["status"]
    call = got["c"]["result"]
    assert call["isError"] is True and call["structuredContent"]["error"] == "not-installed"
    assert "is not in place at" in call["structuredContent"]["message"]
    assert "scripts/bootstrap.sh" in call["structuredContent"]["remedy"]
    assert call["content"][0]["text"].startswith("not-installed: ")
    assert got[4]["error"]["code"] == -32601
    log = (project / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert "not installed: se " in log


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 read ~/.se/bin for a release being fetched; shell, run "
                    "only as a process")
def test_a_release_being_fetched_says_so(tmp_path, kind):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    version = next(line.split('"')[1] for line in (ROOT / "components" / "release.toml").read_text(
        encoding="utf-8").splitlines() if line.startswith("version"))
    (home / ".se" / "bin").mkdir(parents=True)
    (home / ".se" / "bin" / f"se-{version}.SHA256SUMS").write_text("0  se.tar.gz\n", encoding="utf-8")
    call = SESSION[3]
    got = answers(launch(kind, home, project, json.dumps(call) + "\n"))
    assert "SE's start found its release and fetches it" in got["c"]["result"]["structuredContent"]["message"]


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 answer an SE_MCP_BIN that names no binary; shell, run "
                    "only as a process")
def test_an_override_naming_no_binary_is_answered_not_run(tmp_path, kind):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    got = answers(launch(kind, home, project, json.dumps(SESSION[3]) + "\n", SE_MCP_BIN=str(tmp_path / "none")))
    assert "SE_MCP_BIN names" in got["c"]["result"]["structuredContent"]["message"]


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's exec of the binary, stdout the host's and stderr the log's, is shell, "
                    "run only as a process")
def test_the_binary_gets_the_project_and_this_se_and_only_its_protocol_reaches_stdout(tmp_path):
    """The override names a local binary; its standard output is the host's, its stderr the log's."""
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    fake = tmp_path / "se"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\necho "said beside the protocol" >&2\ncat\n',
                    encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    line = json.dumps(SESSION[2]) + "\n"
    result = launch("bash", home, project, line, SE_MCP_BIN=sh(fake), ARGS_FILE=sh(tmp_path / "args"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == line and result.stderr == ""
    assert (tmp_path / "args").read_text(encoding="utf-8").splitlines() == [
        "mcp", "--root", sh(project), "--home", sh(ROOT)]
    log = (project / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert "said beside the protocol" in log and "starting " in log


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's log fallback to TMPDIR is shell, run only as a process")
def test_a_project_it_cannot_write_logs_to_the_temporary_folder(tmp_path):
    if WINDOWS or os.geteuid() == 0:
        pytest.skip("a read-only folder needs POSIX permissions and no root")
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    project.chmod(0o500)
    try:
        result = launch("bash", home, project, json.dumps(SESSION[2]) + "\n", TMPDIR=str(tmp_path))
    finally:
        project.chmod(0o700)
    assert answers(result)[2]["result"]["tools"][0]["name"] == "status"
    assert "not installed" in (tmp_path / "se-mcp.log").read_text(encoding="utf-8")


def test_the_launcher_reads_nothing_of_se_but_the_release_pin():
    """Standalone (README "MCP door"): no other script of SE is sourced or run, in either twin."""
    for path in (SCRIPT, TWIN):
        text = path.read_text(encoding="utf-8")
        named = {word for word in text.replace("'", " ").replace('"', " ").split()
                 if word.endswith((".py", ".sh", ".ps1", ".toml")) and "/" in word}
        assert named <= {"$se_root/components/release.toml", "$se_root/scripts/bootstrap.sh",
                         "$seRoot/scripts/bootstrap.sh",
                         "$chosen/scripts/se_mcp.sh", "$chosen/components/release.toml",
                         "$chosen/scripts/se_mcp.ps1"}, (path.name, named)
        assert "release.toml" in text


# A plugin install (README "MCP door"): Copilot runs the launcher in the plugin folder with --root .,
# PLUGIN_ROOT the plugin folder; the launcher serves the session's repository instead.


def se_copy(folder: Path, checkout: bool = False) -> Path:
    """An SE folder of the two launchers and the release pin; with `checkout`, a .git beside them."""
    (folder / "scripts").mkdir(parents=True)
    (folder / "components").mkdir()
    for script in (SCRIPT, TWIN):
        shutil.copy(script, folder / "scripts" / script.name)
    shutil.copy(ROOT / "components" / "release.toml", folder / "components" / "release.toml")
    if checkout:
        (folder / ".git").mkdir()
    return folder


def repository(folder: Path) -> Path:
    """A checkout of no SE, with a subfolder."""
    (folder / ".git").mkdir(parents=True)
    (folder / "sub").mkdir()
    return folder


def stub(tmp_path: Path) -> Path:
    """A binary that prints its arguments and SE_MCP_PLUGIN_FOLDER, one per line."""
    fake = tmp_path / "se"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" "folder=${SE_MCP_PLUGIN_FOLDER-unset}"\n',
                    encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    return fake


def door_root(kind: str, result: subprocess.CompletedProcess) -> str:
    """The root the not-installed door names in its remedy's `cd '<root>'`."""
    remedy = answers(result)["c"]["result"]["structuredContent"]["remedy"]
    return remedy.split("cd '", 1)[1].split("'", 1)[0]


def named(kind: str, path: Path) -> str:
    return sh(path) if kind == "bash" else str(path)


def plugin_run(kind: str, tmp_path: Path, plugin: Path, **env: str) -> subprocess.CompletedProcess:
    """The plugin case through the not-installed door: PLUGIN_ROOT as the host writes it (a backslash
    path on Windows), --root the plugin folder, the parent shell in the plugin folder."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.setdefault("PLUGIN_ROOT", str(plugin))
    return launch(kind, home, plugin, json.dumps(SESSION[3]) + "\n", se=plugin, parent=plugin, **env)


def stub_run(tmp_path: Path, plugin: Path, parent: Path | None = None, project: Path | None = None,
             **env: str | None) -> list[str]:
    """The bash launcher of `plugin` with the stub binary: its arguments and SE_MCP_PLUGIN_FOLDER.
    PLUGIN_ROOT is the plugin folder unless `env` names it, None for none."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.setdefault("PLUGIN_ROOT", str(plugin))
    result = launch("bash", home, project or plugin, "", se=plugin, parent=parent or plugin,
                    SE_MCP_BIN=sh(stub(tmp_path)), **{key: value for key, value in env.items() if value is not None})
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def today(tmp_path: Path, plugin: Path, project: Path | None = None) -> list[str]:
    project = project or plugin
    return ["mcp", "--root", sh(project), "--home", sh(plugin), "folder=unset"]


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1 from "
                    "COPILOT_SESSION_CWD is shell, run only as a process")
def test_a_plugin_install_serves_the_checkout_of_the_session_folder(tmp_path, kind):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, COPILOT_SESSION_CWD=named(kind, repo / "sub"))
    assert door_root(kind, result) == named(kind, repo)
    log = (repo / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    decision = next(line for line in log.splitlines() if ": root " in line)
    assert f"COPILOT_SESSION_CWD={named(kind, repo / 'sub')}" in decision
    assert f"plugin {named(kind, plugin)}" in decision


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1, SE_SESSION_CWD first, "
                    "is shell, run only as a process")
def test_the_se_session_folder_wins_over_copilots(tmp_path, kind):
    plugin = se_copy(tmp_path / "plugin")
    first, second = repository(tmp_path / "first"), repository(tmp_path / "second")
    result = plugin_run(kind, tmp_path, plugin, SE_SESSION_CWD=named(kind, first),
                        COPILOT_SESSION_CWD=named(kind, second))
    assert door_root(kind, result) == named(kind, first)


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.parametrize("value", ["", "${COPILOT_SESSION_CWD}"])
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1 skips an unusable "
                    "SE_SESSION_CWD; shell, run only as a process")
def test_an_empty_or_unexpanded_se_session_folder_is_ignored(tmp_path, kind, value):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, SE_SESSION_CWD=value, COPILOT_SESSION_CWD=named(kind, repo / "sub"))
    assert door_root(kind, result) == named(kind, repo)


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1 ignores the hook "
                    "variables; shell, run only as a process")
def test_hook_variables_are_no_source(tmp_path, kind):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, CLAUDE_PROJECT_DIR=named(kind, repo),
                        COPILOT_PROJECT_DIR=named(kind, repo))
    assert door_root(kind, result) == named(kind, plugin)
    log = (plugin / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert "from no variable set" in log


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh hands the binary SE_MCP_PLUGIN_FOLDER where no source counts; shell, "
                    "run only as a process")
def test_with_no_source_the_binary_is_told_the_plugin_folder(tmp_path):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    got = stub_run(tmp_path, plugin, CLAUDE_PROJECT_DIR=sh(repo), COPILOT_PROJECT_DIR=sh(repo))
    assert got == today(tmp_path, plugin)[:-1] + [f"folder={sh(plugin)}"]


def parent_cwd_readable() -> bool:
    if sys.platform.startswith("linux"):
        return True
    return sys.platform == "darwin" and shutil.which("lsof") is not None


needs_parent_cwd = pytest.mark.skipif(BASH is None or not parent_cwd_readable(),
                                      reason="the parent-cwd backstop is Linux's /proc and macOS's lsof")


@needs_parent_cwd
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's parent-cwd backstop reads its parent shell's folder (/proc, lsof); "
                    "run only as a process")
def test_with_no_variable_the_parent_process_folder_decides(tmp_path):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    got = stub_run(tmp_path, plugin, parent=repo / "sub")
    assert got == ["mcp", "--root", sh(repo), "--home", sh(plugin), "folder=unset"]
    assert "from parent cwd" in (repo / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert stub_run(tmp_path, plugin, parent=repo / "sub", SE_MCP_PLUGIN_PROJECT="off") == today(tmp_path, plugin)


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's plugin-install root choice keeps a plugin checkout as its root; "
                    "shell, run only as a process")
def test_a_plugin_folder_that_is_the_session_checkout_stays_the_root_with_no_signal(tmp_path):
    plugin = se_copy(tmp_path / "plugin", checkout=True)
    assert stub_run(tmp_path, plugin, COPILOT_SESSION_CWD=sh(plugin)) == today(tmp_path, plugin)


@needs_parent_cwd
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's parent-cwd backstop reads its parent shell's folder (/proc, lsof); "
                    "run only as a process")
def test_a_plugin_checkout_run_from_itself_stays_the_root_with_no_signal(tmp_path):
    plugin = se_copy(tmp_path / "plugin", checkout=True)
    assert stub_run(tmp_path, plugin, parent=plugin) == today(tmp_path, plugin)


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's plugin-install root choice for a session folder in the plugin is "
                    "shell, run only as a process")
def test_a_session_folder_inside_a_plain_plugin_folder_gets_no_signal(tmp_path):
    plugin = se_copy(tmp_path / "plugin")
    assert stub_run(tmp_path, plugin, COPILOT_SESSION_CWD=sh(plugin)) == today(tmp_path, plugin)


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 hand over to another SE checkout's own launcher; shell, "
                    "run only as a process")
def test_another_se_checkout_is_served_by_its_own_launcher(tmp_path, kind):
    plugin, other = se_copy(tmp_path / "plugin"), se_copy(tmp_path / "other", checkout=True)
    (other / "sub").mkdir()
    result = plugin_run(kind, tmp_path, plugin, COPILOT_SESSION_CWD=named(kind, other / "sub"))
    assert door_root(kind, result) == named(kind, other)
    remedy = answers(result)["c"]["result"]["structuredContent"]["remedy"]
    assert f"'{named(kind, other).rstrip(os.sep)}" in remedy.split("&&" if kind == "bash" else ";", 1)[1]
    assert "starting" not in (other / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert "not installed" in (other / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's gate of the plugin case, shut in each of five ways, is shell, run "
                    "only as a process")
def test_outside_the_gate_the_binary_gets_todays_arguments(tmp_path):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    session = {"COPILOT_SESSION_CWD": sh(repo / "sub")}
    assert stub_run(tmp_path, plugin, PLUGIN_ROOT=None, **session) == today(tmp_path, plugin)
    other = tmp_path / "other"
    other.mkdir()
    assert stub_run(tmp_path, plugin, project=other, **session) == today(tmp_path, plugin, other)
    assert stub_run(tmp_path, plugin, PLUGIN_ROOT=str(other), **session) == today(tmp_path, plugin)
    assert stub_run(tmp_path, plugin, SE_MCP_PLUGIN_PROJECT="off", **session) == today(tmp_path, plugin)
    assert stub_run(tmp_path, plugin, PLUGIN_ROOT=None) == today(tmp_path, plugin)


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the SE_MCP_PLUGIN_PROJECT=off switch of scripts/se_mcp.sh and se_mcp.ps1 is shell, run "
                    "only as a process")
def test_the_escape_switch_keeps_the_plugin_folder(tmp_path, kind):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, COPILOT_SESSION_CWD=named(kind, repo / "sub"),
                        SE_MCP_PLUGIN_PROJECT="off")
    assert door_root(kind, result) == named(kind, plugin)
    assert not (repo / ".se").exists()


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh takes an unset HOME from the account; shell, run only as a process")
def test_an_unset_home_is_taken_from_the_account(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = launch("bash", None, project, "", SE_MCP_BIN=sh(stub(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:3] == ["mcp", "--root", sh(project)]


def declared_server(path: Path) -> dict:
    """The se server as a generated MCP config declares it."""
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["se"]


def expand(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace("${" + name + "}", value)
    return text


@needs_bash
@pytest.mark.parametrize("expanded", [True, False], ids=["expanded", "unexpanded"])
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh run as the generated Copilot plugin config runs it, args, env and cwd; "
                    "shell, run only as a process")
def test_the_plugin_config_serves_the_session_checkout(tmp_path, expanded):
    """The launcher as the generated Copilot plugin runs it: its args, its env, cwd the plugin folder.
    A host that leaves ${COPILOT_SESSION_CWD} unexpanded still sets the variable itself."""
    server = declared_server(ROOT / ".github" / "plugin" / "plugin.json")
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    host = {"PLUGIN_ROOT": sh(plugin), "COPILOT_SESSION_CWD": sh(repo / "sub")}
    env = {name: expand(value, host) if expanded else value for name, value in server["env"].items()}
    assert server["command"] == "bash" and server["args"][1:] == ["--root", "."]
    assert expand(server["args"][0], host) == sh(plugin / "scripts" / "se_mcp.sh")
    home = tmp_path / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items() if key not in {"SE_MCP_BIN", *PLUGIN_VARIABLES}}
    environment.update(HOME=str(home), USERPROFILE=str(home), SE_MCP_BIN=sh(stub(tmp_path)),
                       PLUGIN_ROOT=str(plugin), COPILOT_SESSION_CWD=sh(repo / "sub"), **env)
    result = subprocess.run([BASH, "-c", '"$BASH" "$@"; :', "host", expand(server["args"][0], host), "--root", "."],
                            capture_output=True, text=True, encoding="utf-8", env=environment, cwd=plugin,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["mcp", "--root", sh(repo), "--home", sh(plugin), "folder=unset"]


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh run as .github/mcp.json runs it keeps its root; shell, run only as a "
                    "process")
def test_the_checkouts_own_config_keeps_its_root_whatever_the_session_folder(tmp_path):
    """.github/mcp.json runs the launcher of the checkout itself, no PLUGIN_ROOT: the gate stays shut,
    so its SE_SESSION_CWD changes nothing."""
    server = declared_server(ROOT / ".github" / "mcp.json")
    checkout, repo = se_copy(tmp_path / "checkout", checkout=True), repository(tmp_path / "repo")
    env = {name: expand(value, {"COPILOT_SESSION_CWD": sh(repo)}) for name, value in server["env"].items()}
    assert "SE_SESSION_CWD" in env
    assert stub_run(tmp_path, checkout, PLUGIN_ROOT=None, COPILOT_SESSION_CWD=sh(repo), **env) == today(
        tmp_path, checkout)


# A session folder that is no checkout (README "MCP door"): the plugin case keeps it as the root, and
# the launcher logs at home, so that folder gets no .se.


def session_folder(tmp_path: Path) -> Path:
    """A folder with no .git in it or above it; skipped where the temporary folder lies in a checkout."""
    folder = tmp_path / "session"
    folder.mkdir()
    if any((parent / ".git").exists() for parent in (folder, *folder.parents)):
        pytest.skip("the temporary folder lies in a checkout")
    return folder


def home_log(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".se" / ".runtime" / "mcp.log"


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 log at home for a session folder with no .git; shell, "
                    "run only as a process")
def test_a_session_folder_that_is_no_checkout_gets_no_se_and_the_log_is_at_home(tmp_path, kind):
    plugin, session = se_copy(tmp_path / "plugin"), session_folder(tmp_path)
    result = plugin_run(kind, tmp_path, plugin, SE_SESSION_CWD=named(kind, session))
    assert door_root(kind, result) == named(kind, session)
    assert not (session / ".se").exists()
    log = home_log(tmp_path).read_text(encoding="utf-8")
    decision = next(line for line in log.splitlines() if ": root " in line)
    assert f"from SE_SESSION_CWD={named(kind, session)}" in decision
    assert "not installed: " in log


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh and se_mcp.ps1 log in a session folder that is a repository's root; "
                    "shell, run only as a process")
def test_a_session_folder_that_is_a_repositorys_root_logs_there(tmp_path, kind):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, SE_SESSION_CWD=named(kind, repo))
    assert door_root(kind, result) == named(kind, repo)
    assert ": root " in (repo / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert not (tmp_path / "home" / ".se" / ".runtime").exists()


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's exec of the binary for a session folder, its stderr in the home log, "
                    "is shell, run only as a process")
def test_the_binary_gets_the_session_folder_and_its_stderr_lands_in_the_home_log(tmp_path):
    plugin, session = se_copy(tmp_path / "plugin"), session_folder(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    fake = tmp_path / "se"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\necho "said beside the protocol" >&2\n',
                    encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    result = launch("bash", home, plugin, "", se=plugin, parent=plugin, PLUGIN_ROOT=str(plugin),
                    SE_SESSION_CWD=sh(session), SE_MCP_BIN=sh(fake), ARGS_FILE=sh(tmp_path / "args"))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "args").read_text(encoding="utf-8").splitlines() == [
        "mcp", "--root", sh(session), "--home", sh(plugin)]
    assert "said beside the protocol" in home_log(tmp_path).read_text(encoding="utf-8")
    assert not (session / ".se").exists()


@needs_parent_cwd
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh's parent-cwd backstop reads its parent shell's folder (/proc, lsof); "
                    "run only as a process")
def test_a_parent_folder_that_is_no_checkout_gets_no_se(tmp_path):
    plugin, session = se_copy(tmp_path / "plugin"), session_folder(tmp_path)
    got = stub_run(tmp_path, plugin, parent=session)
    assert got == ["mcp", "--root", sh(session), "--home", sh(plugin), "folder=unset"]
    assert not (session / ".se").exists()
    assert "from parent cwd" in home_log(tmp_path).read_text(encoding="utf-8")


# Claude Code's plugin install (README "The MCP door"): .claude-plugin/plugin.json runs the launcher
# from ${CLAUDE_PLUGIN_ROOT} with --root .; Claude Code sets CLAUDE_PLUGIN_ROOT and CLAUDE_PROJECT_DIR
# in the server's environment and starts it in the project (scripts/host-limits.toml).


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1 from "
                    "CLAUDE_PROJECT_DIR is shell, run only as a process")
def test_a_claude_plugin_run_from_its_folder_serves_the_project_dir(tmp_path, kind):
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    result = plugin_run(kind, tmp_path, plugin, PLUGIN_ROOT="", CLAUDE_PLUGIN_ROOT=str(plugin),
                        CLAUDE_PROJECT_DIR=named(kind, repo / "sub"), COPILOT_SESSION_CWD=named(kind, tmp_path))
    assert door_root(kind, result) == named(kind, repo)
    log = (repo / ".se" / ".runtime" / "mcp.log").read_text(encoding="utf-8")
    assert f"from CLAUDE_PROJECT_DIR={named(kind, repo / 'sub')}" in log


@pytest.mark.parametrize("kind", LAUNCHERS)
@pytest.mark.spawns("contract: shell, the plugin-install root choice of scripts/se_mcp.sh and se_mcp.ps1 under Claude Code is "
                    "shell, run only as a process")
def test_under_claude_code_the_se_session_folder_still_wins_and_copilots_is_no_source(tmp_path, kind):
    plugin = se_copy(tmp_path / "plugin")
    first, second = repository(tmp_path / "first"), repository(tmp_path / "second")
    result = plugin_run(kind, tmp_path, plugin, PLUGIN_ROOT="", CLAUDE_PLUGIN_ROOT=str(plugin),
                        SE_SESSION_CWD=named(kind, first), CLAUDE_PROJECT_DIR=named(kind, second))
    assert door_root(kind, result) == named(kind, first)
    alone = plugin_run(kind, tmp_path, se_copy(tmp_path / "plain"), PLUGIN_ROOT="",
                       CLAUDE_PLUGIN_ROOT=str(tmp_path / "plain"), COPILOT_SESSION_CWD=named(kind, second))
    assert door_root(kind, alone) == named(kind, tmp_path / "plain")


@needs_bash
@pytest.mark.spawns("contract: shell, scripts/se_mcp.sh run as Claude Code starts the manifest's server, from two folders; "
                    "shell, run only as a process")
def test_the_claude_manifests_door_as_claude_code_starts_it_serves_the_project(tmp_path):
    """The server as a build with [plugin] claude_mcp on declares it, started as Claude Code 2.1.330
    starts it: cwd the project, CLAUDE_PLUGIN_ROOT and CLAUDE_PROJECT_DIR set; the gate stays shut."""
    server = se_plugin_server(tmp_path)
    plugin, repo = se_copy(tmp_path / "plugin"), repository(tmp_path / "repo")
    host = {"CLAUDE_PLUGIN_ROOT": sh(plugin)}
    assert server == {"type": "stdio", "command": "bash", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/se_mcp.sh", "--root", "."]}
    home = tmp_path / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items() if key not in {"SE_MCP_BIN", *PLUGIN_VARIABLES}}
    environment.update(HOME=str(home), USERPROFILE=str(home), SE_MCP_BIN=sh(stub(tmp_path)),
                       CLAUDE_PLUGIN_ROOT=str(plugin), CLAUDE_PROJECT_DIR=str(repo))
    for cwd in (repo, plugin):  # where Claude Code starts it, and a host that starts it in the plugin
        result = subprocess.run([BASH, "-c", '"$BASH" "$@"; :', "host", expand(server["args"][0], host),
                                 *server["args"][1:]], capture_output=True, text=True, encoding="utf-8",
                                env=environment, cwd=cwd, timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["mcp", "--root", sh(repo), "--home", sh(plugin), "folder=unset"]


def se_plugin_server(tmp_path: Path) -> dict:
    """The se server of .claude-plugin/plugin.json, built from SE's sources with claude_mcp on."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("se_plugin_for_mcp", ROOT / "scripts" / "se_plugin.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    root = tmp_path / "built"
    shutil.copytree(ROOT / "src", root / "src")
    (root / "se.toml").write_text('[project]\nversion = "1.0.0"\n[plugin]\nclaude_mcp = true\n', encoding="utf-8")
    return declared_server_of(module.expected(root))


def declared_server_of(files: dict) -> dict:
    return json.loads(files[next(path for path in files if str(path) == ".claude-plugin/plugin.json")])["mcpServers"]["se"]
