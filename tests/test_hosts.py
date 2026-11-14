"""The host table (scripts/hosts.sh): one place names how SE tells host, cloud, project and payload;
scripts/hosts.py reads it as a pure module."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hosts  # noqa: E402


def test_the_table_names_claudes_rows_only_and_the_project_variable():
    """No Copilot variable could be checked against a Copilot run: its hook file names its host."""
    assert hosts.table()["SE_PROJECT_VARIABLES"] == ("CLAUDE_PROJECT_DIR",)
    assert hosts.variables() == ["CLAUDECODE", "CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS"]


def test_the_host_is_claude_where_the_environment_marks_it():
    assert hosts.host({}) is None
    assert hosts.host({"CLAUDECODE": "1"}) == "claude"
    assert hosts.host({"CLAUDE_CODE_REMOTE": "true"}) == "claude"
    assert hosts.host({"GITHUB_ACTIONS": "true"}) is None, "any CI run, not a host"


def test_a_hook_answers_the_host_its_hook_file_names_else_the_payloads_else_claude():
    assert hosts.hook_host({}) == "claude"
    assert hosts.hook_host({"SE_HOOK_HOST": "copilot"}, {"session_id": "s"}) == "copilot"
    assert hosts.hook_host({"SE_HOOK_HOST": "other"}, {"session_id": "s"}) == "claude"
    assert hosts.hook_host({}, {"sessionId": "s"}) == "copilot"


def test_a_cloud_is_marked_by_its_value_in_any_case():
    assert hosts.clouds({}) == []
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "TRUE"}) == ["claude"]
    assert hosts.clouds({"CLAUDE_CODE_REMOTE": "false"}) == []
    assert hosts.clouds({"GITHUB_ACTIONS": "true", "SE_CLOUD_AGENT": "a"}) == ["ci"]


def test_the_project_is_claudes_variable_where_set():
    assert hosts.project_dir({}) is None
    assert hosts.project_dir({"CLAUDE_PROJECT_DIR": "/a"}) == "/a"
    assert hosts.project_dir({"CLAUDE_PROJECT_DIR": "", "COPILOT_PROJECT_DIR": "/b"}) is None


def test_a_copilot_payload_reads_as_claudes_and_a_claude_payload_is_kept():
    copilot = {"sessionId": "s", "cwd": "/w", "transcriptPath": "/t", "stopReason": "end_turn",
               "stop_hook_active": False}
    assert hosts.payload(copilot) == {"session_id": "s", "cwd": "/w", "transcript_path": "/t",
                                      "stop_reason": "end_turn", "stop_hook_active": False}
    claude = {"session_id": "s", "hook_event_name": "Stop", "cwd": "/w"}
    assert hosts.payload(claude) == claude
    assert (hosts.payload_host(copilot), hosts.payload_host(claude)) == ("copilot", "claude")
    assert hosts.payload({"session_id": "snake", "sessionId": "camel"}) == {"session_id": "snake"}



def test_no_table_line_shadows_a_variable_the_table_names():
    """The hook scripts source the table, so a line named like a variable it reads would replace it."""
    named = {*hosts.variables(), *hosts.table()["SE_PROJECT_VARIABLES"], hosts.table()["SE_HOOK_HOSTS"][0]}
    assert not set(hosts.table()) & named
