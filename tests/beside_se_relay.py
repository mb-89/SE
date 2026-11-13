"""SE's relay read against the real core, beside se.toml `[tests.beside.se-relay]` (README
"Hand-offs through the relay"): where kern serves a checkout with the github component on the relay
backend, a PostToolUse hook lands a GitHub tool's answer in kern's snapshot, and `se_relay`'s read
writes it to a file the command reads, with no answer retyped. It builds kern's binary, so it runs
beside the suite after kern's tests have warmed Go's cache, not in it."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import quiet_git

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


def told(kern: Path, checkout: Path) -> list[tuple[str, dict]]:
    """The tool calls kern's relay tells the agent on a prompt's hook, as the session reads them."""
    said = run(str(kern), "hook", "UserPromptSubmit", "--root", str(checkout), cwd=checkout,
               stdin='{"session_id": "s1"}').stdout.strip()
    if not said:
        return []
    context = json.loads(said)["hookSpecificOutput"]["additionalContext"]
    calls = []
    for line in context.splitlines():
        found = re.match(r"\d+\. (\S+) (\{.*\})$", line)
        if found:
            calls.append((found[1], json.loads(found[2])))
    return calls


def answer(tool: str, input_: dict) -> object:
    """What the GitHub tools answer the fleet check's reads, for a fleet of one stuck issue."""
    method = input_.get("method")
    if tool == "list_issues" and input_["state"] == "OPEN":
        return {"issues": [{"number": 5, "title": "feat/x", "state": "OPEN", "body": "",
                            "labels": ["work", "in-progress"]}], "pageInfo": {"hasNextPage": False}}
    if tool == "list_issues":
        return {"issues": []}
    if tool == "issue_read" and method == "get_comments":
        return [{"body": "Started: worker", "created_at": "2026-11-01T09:00:00Z"}]
    if tool == "list_pull_requests":
        return []
    raise AssertionError(f"an unexpected tool call: {tool} {input_}")


def test_a_streamed_command_runs_as_one_call_its_steps_through_the_relay(tmp_path: Path) -> None:
    """The acceptance's mechanism against the real core: a streamed command (fleet-check) runs as
    one call through kern's `call.` from SE's own command line; the integration component runs it
    with each GitHub read a `github.step` that kern tells the agent on its hook, the session's
    PostToolUse answers it, and each step's progress line reaches the caller while the call runs.
    With kern stopped the same command line hands its plan off again: the fallback."""
    kern = tmp_path / ("kern.exe" if os.name == "nt" else "kern")
    assert run("go", "build", "-o", str(kern), "./cmd/kern", cwd=ROOT / "kern").returncode == 0
    checkout = tmp_path / "se"
    (checkout / ".git").mkdir(parents=True)
    for part in ("components", "scripts", "kern"):
        try:
            (checkout / part).symlink_to(ROOT / part, target_is_directory=True)
        except OSError as error:  # Windows without the right to make links
            pytest.skip(f"no symlink: {error}")
    wiring = (ROOT / "wiring.toml").read_text(encoding="utf-8").replace(
        '[instances.github]\ncomponent = "github"\n',
        '[instances.github]\ncomponent = "github"\nconfig = { backend = "relay" }\n')
    assert 'backend = "relay"' in wiring
    (checkout / "wiring.toml").write_text(wiring, encoding="utf-8")
    nogh = tmp_path / "bin"  # a gh that is not signed in: the cloud's hand-off
    nogh.mkdir()
    (nogh / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (nogh / "gh").chmod(0o755)
    env = {**os.environ, "UV_SYSTEM_CERTS": "1", "PATH": f"{nogh}{os.pathsep}{os.environ['PATH']}"}
    env.pop("SE_KERN", None)
    origin, worktree = tmp_path / "origin.git", tmp_path / "wt"  # the branches it reads
    quiet_git.init(origin, "--bare", "-b", "main")
    quiet_git.clone(origin, worktree)
    command = [sys.executable, str(checkout / "scripts" / "work_tickets.py"), "fleet-check",
               "--repo", "alice/demo", "--worktree", str(worktree)]

    started = subprocess.run([str(kern), "start", "--root", str(checkout)], cwd=checkout, env=env,
                             capture_output=True, text=True, timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        assert run(str(kern), "status", "--root", str(checkout), "--wait", "10s",
                   cwd=checkout).returncode == 0
        call = subprocess.Popen(command, cwd=checkout, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        answered: list[str] = []
        lines: list[str] = []
        threading.Thread(target=lambda: lines.extend(call.stderr), daemon=True).start()
        end = time.monotonic() + 90
        while call.poll() is None and time.monotonic() < end:
            for tool, input_ in told(kern, checkout):
                # Each step's line reached the caller before the session ran it: progress streams.
                assert any(f"GitHub step through kern's relay: {tool}" in line for line in lines), lines
                payload = json.dumps({
                    "session_id": "s1", "hook_event_name": "PostToolUse",
                    "tool_name": f"mcp__github__{tool}", "tool_input": input_,
                    "tool_response": [{"type": "text", "text": json.dumps(answer(tool, input_))}]})
                posted = run(str(kern), "hook", "PostToolUse", "--root", str(checkout),
                             cwd=checkout, stdin=payload)
                assert posted.returncode == 0, posted.stderr
                answered.append(tool + " " + str(input_.get("method") or ""))
            time.sleep(0.05)
        out, _ = call.communicate(timeout=30)
        assert call.returncode == 1 and answered, (out, "".join(lines))  # stuck work found, through kern
        assert answered == ["list_issues ", "list_issues ", "list_pull_requests ",
                            "issue_read get_comments"], answered
        assert "#5" in out and "no branch" in out and "GitHub plan:" not in out, out
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)
    # Kern stopped: the same command line hands its plan to the session, the file-based fallback.
    fallback = subprocess.run(command, cwd=checkout, env=env, capture_output=True, text=True,
                              timeout=60)
    assert fallback.returncode == 0 and "GitHub plan: fleet check" in fallback.stdout, fallback
