"""The host table (scripts/hosts.sh): one place names how SE tells host, cloud, project and payload;
scripts/hosts.py reads it as a pure module."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hosts  # noqa: E402


def test_the_table_names_each_cloud_and_project_variable_in_order():
    assert hosts.table()["SE_PROJECT_VARIABLES"] == ("CLAUDE_PROJECT_DIR", "COPILOT_PROJECT_DIR")
    assert hosts.variables() == ["CLAUDECODE", "CLAUDE_CODE_REMOTE", "COPILOT_PROJECT_DIR", "COPILOT_AGENT_PROMPT",
                                 "GITHUB_ACTIONS", "SE_CLOUD"]


def test_the_host_is_the_first_the_environment_marks():
    assert hosts.host({}) is None
    assert hosts.host({"CLAUDECODE": "1"}) == "claude"
    assert hosts.host({"COPILOT_AGENT_PROMPT": "fix it"}) == "copilot"
    assert hosts.host({"CLAUDE_CODE_REMOTE": "true", "COPILOT_PROJECT_DIR": "/p"}) == "claude"


def test_a_cloud_is_marked_by_its_value_in_any_case_or_by_being_set():
    assert hosts.clouds({}) == []
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "TRUE"}) == ["claude"]
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "false"}) == []
    assert hosts.clouds({"COPILOT_AGENT_PROMPT": "fix it", "GITHUB_ACTIONS": "true"}) == ["copilot", "ci"]
    assert hosts.clouds({"SE_CLOUD": "true"}) == ["se"]


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

