"""SE's relay read against the real core, beside se.toml `[tests.beside.se-relay]` (README
"Hand-offs through the relay"): where kern serves a checkout with the github component on the relay
backend, a PostToolUse hook lands a GitHub tool's answer in kern's snapshot, and `se_relay`'s read
writes it to a file the command reads, with no answer retyped. It builds kern's binary, so it runs
beside the suite after kern's tests have warmed Go's cache, not in it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "kern" / "python"))

import se_relay  # noqa: E402

WIRING = """
[instances.github]
component = "github"
config = { backend = "relay" }

[wires]
"github.issues" = "github/issues/<key>"
"github.pulls" = "github/pulls/<key>"
"github.comments" = "github/comments/<key>"
"github.checks" = "github/checks/<key>"
"github.outbox" = "github/outbox/<key>"
"""

# A PostToolUse payload shaped as a Claude Code cloud session's hook hands it (docs/go-core.md
# "What the hooks carry"): the tool's answer as MCP content.
PAYLOAD = json.dumps({
    "session_id": "s1", "hook_event_name": "PostToolUse",
    "tool_name": "mcp__github__issue_read",
    "tool_input": {"method": "get", "owner": "alice", "repo": "demo", "issue_number": 7},
    "tool_response": [{"type": "text", "text": json.dumps(
        {"number": 7, "title": "One issue", "body": "## Requirements\n\n1. One.\n"})}],
})


def run(*args: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, input=stdin, capture_output=True, text=True,
                          timeout=120, env={**os.environ, "UV_SYSTEM_CERTS": "1"})


def test_a_posttooluse_hook_lands_a_snapshot_the_relay_read_writes_to_a_file(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(se_relay.se_components.SWITCH, raising=False)  # the suite sets SE_KERN=off
    kern = tmp_path / ("kern.exe" if os.name == "nt" else "kern")
    built = run("go", "build", "-o", str(kern), "./cmd/kern", cwd=ROOT / "kern")
    assert built.returncode == 0, built.stderr
    checkout = tmp_path / "se"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "wiring.toml").write_text(WIRING, encoding="utf-8")

    assert run(str(kern), "start", "--root", str(checkout), cwd=checkout).returncode == 0
    try:
        assert run(str(kern), "status", "--root", str(checkout), "--wait", "5s",
                   cwd=checkout).returncode == 0
        relay = se_relay.relay(checkout)
        assert relay is not None, "kern serves the checkout on the relay backend"
        # No snapshot yet: the read names the tool call to run.
        with pytest.raises(se_relay.RelayError, match="issue_read"):
            relay.answer_file("issues", "alice", "demo", 7, "work issue")
        # The session runs that tool; its PostToolUse hook hands kern the answer.
        posted = run(str(kern), "hook", "PostToolUse", "--root", str(checkout), cwd=checkout,
                     stdin=PAYLOAD)
        assert posted.returncode == 0, posted.stderr
        path = relay.answer_file("issues", "alice", "demo", 7, "work issue")
        assert json.loads(path.read_text(encoding="utf-8"))["title"] == "One issue"
        # The comments, a one-page get_comments answer, land in the comments family as one list.
        comments = json.dumps({**json.loads(PAYLOAD), "tool_input": {
            "method": "get_comments", "owner": "alice", "repo": "demo", "issue_number": 7},
            "tool_response": [{"type": "text", "text": json.dumps([{"id": 5, "body": "Started"}])}]})
        assert run(str(kern), "hook", "PostToolUse", "--root", str(checkout), cwd=checkout,
                   stdin=comments).returncode == 0
        listed = relay.answer_file("comments", "alice", "demo", 7, "work issue comments")
        assert [c["id"] for c in json.loads(listed.read_text(encoding="utf-8"))] == [5]
        # And the hook of a prompt now hands the agent nothing to run: the outbox is empty.
        prompt = run(str(kern), "hook", "UserPromptSubmit", "--root", str(checkout), cwd=checkout,
                     stdin='{"session_id": "s1"}')
        assert prompt.stdout.strip() == "", prompt.stdout
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)
