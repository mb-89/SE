"""The MCP door's launcher, scripts/se_mcp.sh and its PowerShell twin se_mcp.ps1 (README "MCP door"):
MCP alone on standard output, the rest in a log, and an answer at once where the binary is missing."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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


def launch(kind: str, home: Path, project: Path, stdin: str, **env: str) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items() if key != "SE_MCP_BIN"}
    environment.update(HOME=str(home), USERPROFILE=str(home), **env)
    if kind == "bash":
        command = [BASH, sh(SCRIPT), "--root", sh(project)]
    else:
        command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TWIN), "--root", str(project)]
    return subprocess.run(command, input=stdin, capture_output=True, text=True, encoding="utf-8", env=environment,
                          timeout=60, check=False)


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
def test_an_override_naming_no_binary_is_answered_not_run(tmp_path, kind):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    got = answers(launch(kind, home, project, json.dumps(SESSION[3]) + "\n", SE_MCP_BIN=str(tmp_path / "none")))
    assert "SE_MCP_BIN names" in got["c"]["result"]["structuredContent"]["message"]


@needs_bash
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
                         "$seRoot/scripts/bootstrap.sh"}, (path.name, named)
        assert "release.toml" in text
