"""The host table (scripts/hosts.sh): one place names how SE tells host, cloud, project and payload."""
from pathlib import Path
import re

import hosts

ROOT = Path(__file__).resolve().parents[1]


def test_the_table_names_each_cloud_and_project_variable_in_order():
    assert hosts.table()["SE_PROJECT_VARIABLES"] == ("CLAUDE_PROJECT_DIR", "COPILOT_PROJECT_DIR")
    assert hosts.variables() == ["CLAUDE_CODE_REMOTE", "COPILOT_AGENT_PROMPT", "GITHUB_ACTIONS", "SE_CLOUD"]


def test_a_cloud_is_marked_by_its_value_in_any_case_or_by_being_set():
    assert hosts.clouds({}) == []
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "TRUE"}) == ["claude"]
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "false"}) == []
    assert hosts.clouds({"COPILOT_AGENT_PROMPT": "fix it", "GITHUB_ACTIONS": "true"}) == ["copilot", "ci"]
    assert hosts.in_cloud(environment={"SE_CLOUD": "true"})
    assert not hosts.in_cloud("ci", {"CLAUDE_CODE_REMOTE": "true"})


def test_the_project_is_the_first_project_variable_set():
    assert hosts.project_dir({}) is None
    assert hosts.project_dir({"COPILOT_PROJECT_DIR": "/b"}) == "/b"
    assert hosts.project_dir({"CLAUDE_PROJECT_DIR": "/a", "COPILOT_PROJECT_DIR": "/b"}) == "/a"
    assert hosts.project_dir({"CLAUDE_PROJECT_DIR": "", "COPILOT_PROJECT_DIR": "/b"}) == "/b"


def test_a_copilot_payload_reads_as_claudes_and_a_claude_payload_is_kept():
    copilot = {"sessionId": "s", "cwd": "/w", "transcriptPath": "/t", "stopReason": "end_turn",
               "stop_hook_active": False}
    assert hosts.payload(copilot) == {"session_id": "s", "cwd": "/w", "transcript_path": "/t",
                                      "stop_reason": "end_turn", "stop_hook_active": False}
    claude = {"session_id": "s", "hook_event_name": "Stop", "cwd": "/w"}
    assert hosts.payload(claude) == claude
    assert (hosts.payload_host(copilot), hosts.payload_host(claude)) == ("copilot", "claude")
    assert hosts.payload({"session_id": "snake", "sessionId": "camel"}) == {"session_id": "snake"}


def test_no_script_checks_a_host_variable_on_its_own():
    """Every script reads the host table; only a variable a script sets for a child may appear."""
    names = [*hosts.variables(), *hosts.table()["SE_PROJECT_VARIABLES"]]
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b")
    found = []
    for path in sorted((ROOT / "scripts").iterdir()):
        if path.suffix not in (".py", ".sh", ".ps1") or path.stem == "hosts":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not re.search(r'CLAUDE_PROJECT_DIR="\$\w+"\s', line):
                found.append(f"{path.name}:{number}: {line.strip()}")
    assert found == []
