"""SE's relay read against the real core, beside se.toml `[tests.beside.se-relay]` (README
"Hand-offs through the relay"): where kern serves a checkout with the github component on the relay
backend, a PostToolUse hook lands a GitHub tool's answer in kern's snapshot, and `se_relay`'s read
writes it to a file the command reads, with no answer retyped. It builds kern's binary, so it runs
beside the suite after kern's tests have warmed Go's cache, not in it."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import fake_git

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
        tmp_path: Path, monkeypatch, shared_fake_git) -> None:
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


@pytest.mark.parametrize("copy", ["checkout", "plugin"])
def test_a_streamed_command_runs_as_one_call_its_steps_through_the_relay(
        tmp_path: Path, copy: str, shared_fake_git) -> None:
    """The acceptance's mechanism against the real core: a streamed command (fleet-check) runs as
    one call through kern's `call.`, from SE's own command line in the checkout kern serves or
    from the plugin's copy of SE, the path the skills name, run in that checkout; the integration
    component runs it with each GitHub read a `github.step` that kern tells the agent on its hook,
    the session's PostToolUse answers it, and each step's progress line reaches the caller while
    the call runs. With kern stopped the same command line hands its plan off again and says that
    it fell back: the fallback."""
    # SE's wiring names SE's Go components too, which the `se` binary carries (components/cmd/se).
    kern = tmp_path / ("se-binary.exe" if os.name == "nt" else "se-binary")
    built = run("go", "build", "-o", str(kern), "./cmd/se", cwd=ROOT / "components")
    assert built.returncode == 0, built.stderr
    checkout = fake_git.init(tmp_path / "se")  # a repository: SE's origin component reads its refs
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
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, worktree)
    se = checkout
    if copy == "plugin":  # a copy of SE's scripts of its own, as the plugin's clone holds them
        se = tmp_path / "plugin"
        shutil.copytree(ROOT / "scripts", se / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (se / "kern").symlink_to(ROOT / "kern", target_is_directory=True)
    command = [sys.executable, str(se / "scripts" / "work_tickets.py"), "fleet-check",
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
    assert "fell back to the file-based hand-off" in fallback.stderr, fallback.stderr


def door(root: Path, *arguments: str, env: dict | None = None) -> str:
    """`git -C <root> <arguments>` through the door, on the shared fake; its stdout."""
    import git_door

    result = git_door.run(*arguments, root=root, env=env)
    assert result.returncode == 0, (arguments, result.stderr)
    return result.stdout.strip()


# The tools' answers to one landing of PR #7 (work issue #5) through kern's relay: what a cloud
# session's GitHub tools answer, with the squash merge written on the bare origin as GitHub would.
class Landing:
    def __init__(self, origin: Path, head: str, report: str) -> None:
        self.origin, self.head, self.report, self.body = origin, head, report, ""

    def __call__(self, tool: str, input_: dict) -> object:
        method = input_.get("method")
        number = input_.get("pullNumber") or input_.get("issue_number")
        if tool == "pull_request_read" and method == "get" and number == 7:
            return {"number": 7, "body": self.report, "html_url": "https://localhost/owner/repo/pull/7",
                    "head": {"ref": "feature/worker", "sha": self.head}}
        if tool == "issue_read" and method == "get" and not self.body:
            return {"number": 5, "title": "feature/worker", "state": "open", "body": self.report,
                    "comments": 1, "html_url": "https://localhost/owner/tracker/issues/5"}
        if tool == "issue_read" and method == "get_comments":
            return [{"id": 1, "body": "Started: worker", "created_at": "2026-11-14T08:00:00Z",
                     "user": {"login": "owner"}}]
        if tool == "list_issues":  # the pause check: none paused
            return {"issues": [], "totalCount": 0, "pageInfo": {"hasNextPage": False}}
        if tool == "list_pull_requests":  # no landing pull request yet
            return []
        if tool == "create_pull_request":
            self.body = input_["body"]
            return {"id": "1", "url": "https://localhost/owner/repo/pull/20"}
        if tool == "pull_request_read" and method == "get_check_runs":
            sha = door(self.origin, "rev-parse", "refs/heads/land/feature/worker")
            return {"total_count": 1, "check_runs": [{
                "id": 2, "name": "check", "head_sha": sha, "status": "completed",
                "conclusion": "success", "html_url": "https://localhost/owner/repo/runs/2"}]}
        if tool == "merge_pull_request":
            main = door(self.origin, "rev-parse", "refs/heads/main")
            web = {"GIT_AUTHOR_NAME": "owner", "GIT_AUTHOR_EMAIL": "1+owner@users.noreply.github.com",
                   "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply" + "@github.com"}
            squash = door(self.origin, "commit-tree", "refs/heads/land/feature/worker^{tree}", "-p",
                          main, "-m", input_["commit_title"], env={**os.environ, **web})
            door(self.origin, "update-ref", "refs/heads/main", squash, main)
            return {"sha": squash, "merged": True, "message": "Pull Request successfully merged"}
        if tool == "pull_request_read" and method == "get":  # the landing pull request, merged
            return {"number": 20, "merged": True, "state": "closed", "body": self.body}
        if tool == "add_issue_comment":
            return {"id": "77", "url": f"https://localhost/owner/repo/issues/{number}#issuecomment-77"}
        if tool == "issue_read" and method == "get_labels":
            return [{"name": "work"}, {"name": "in-progress"}]
        if tool == "issue_read" and method == "get":
            return {"number": number, "state": "closed"}
        if tool in ("update_pull_request", "issue_write"):
            return {"id": "1", "url": "https://localhost/owner/repo"}
        raise AssertionError(f"integrate asked an unexpected step: {tool} {input_}")


def test_integrate_lands_a_pull_request_end_to_end_through_the_relay(
        tmp_path: Path, shared_fake_git) -> None:
    """The relay landing against the real core: `integrate 7` runs as one call through kern, and
    every GitHub step it asks, the reads before the push and each step of the landing plan after it
    (the pause check, the landing pull request, its check, the squash merge, the read-back and the
    close-out), reaches the outbox kern's hook tells the session; the session's answers land it."""
    from test_work_ticket_issues import reported_at

    kern = tmp_path / ("se-binary.exe" if os.name == "nt" else "se-binary")
    built = run("go", "build", "-o", str(kern), "./cmd/se", cwd=ROOT / "components")
    assert built.returncode == 0, built.stderr
    # origin at the path file://localhost/owner/repo.git names, so the checkout's origin reads as
    # a GitHub repository (work_tickets.remote_repo) and the fake pushes to it.
    url = "file://localhost/owner/repo.git"
    origin = Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path)).resolve()
    staged = fake_git.init(tmp_path / "origin.git", "--bare", "-b", "main")
    with shared_fake_git.edit() as fake:
        moved = fake.repositories.pop(staged.resolve())
        moved.path = origin
        fake.repositories[origin] = moved
    checkout = fake_git.clone(origin, tmp_path / "main")
    door(checkout, "remote", "set-url", "origin", url)
    for key, value in (("user.name", "mb"), ("user.email", "mb")):
        door(checkout, "config", key, value)
    (checkout / "se.toml").write_text(
        '[project]\nidentity = "mb <mb>"\nversion = "1.0.0"\npublic_check = false\n\n[tests]\n'
        f'command = [{json.dumps(sys.executable)}, "-c", "pass"]\ntarget_seconds = 60\n'
        'limit_seconds = 120\n', encoding="utf-8")
    (checkout / ".gitignore").write_text(
        "/components\n/scripts\n/kern\n/wiring.toml\n/.se/\n", encoding="utf-8")
    door(checkout, "add", "se.toml", ".gitignore")
    door(checkout, "commit", "-q", "-m", "base")
    door(checkout, "push", "-q", "origin", "HEAD:main")
    worker = tmp_path / "worker"
    door(checkout, "worktree", "add", "-q", "-b", "feature/worker", str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    door(worker, "add", "worker.txt")
    door(worker, "commit", "-q", "-m", "Add the worker file")
    door(worker, "push", "-q", "origin", "feature/worker")
    head = door(worker, "rev-parse", "HEAD")
    for part in ("components", "scripts", "kern"):
        try:
            (checkout / part).symlink_to(ROOT / part, target_is_directory=True)
        except OSError as error:  # Windows without the right to make links
            pytest.skip(f"no symlink: {error}")
    wiring = (ROOT / "wiring.toml").read_text(encoding="utf-8").replace(
        '[instances.github]\ncomponent = "github"\n',
        '[instances.github]\ncomponent = "github"\nconfig = { backend = "relay" }\n')
    (checkout / "wiring.toml").write_text(wiring, encoding="utf-8")
    nogh = tmp_path / "bin"  # a gh that is not signed in: the cloud's hand-off
    nogh.mkdir()
    (nogh / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (nogh / "gh").chmod(0o755)
    env = {**os.environ, "UV_SYSTEM_CERTS": "1", "PATH": f"{nogh}{os.pathsep}{os.environ['PATH']}"}
    env.pop("SE_KERN", None)
    answers = Landing(origin, head, reported_at(head))

    started = subprocess.run([str(kern), "start", "--root", str(checkout)], cwd=checkout, env=env,
                             capture_output=True, text=True, timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        assert run(str(kern), "status", "--root", str(checkout), "--wait", "10s",
                   cwd=checkout).returncode == 0
        call = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "work_tickets.py"), "integrate", "7",
             "--repo", "localhost/owner/tracker", "--worktree", str(checkout)],
            cwd=checkout, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines: list[str] = []
        threading.Thread(target=lambda: lines.extend(call.stderr), daemon=True).start()
        answered: list[str] = []
        end = time.monotonic() + 120
        while call.poll() is None and time.monotonic() < end:
            for tool, input_ in told(kern, checkout):
                payload = json.dumps({
                    "session_id": "s1", "hook_event_name": "PostToolUse",
                    "tool_name": f"mcp__github__{tool}", "tool_input": input_,
                    "tool_response": [{"type": "text", "text": json.dumps(answers(tool, input_))}]})
                posted = run(str(kern), "hook", "PostToolUse", "--root", str(checkout),
                             cwd=checkout, stdin=payload)
                assert posted.returncode == 0, posted.stderr
                answered.append(f"{tool} {input_.get('method') or ''}".strip())
            time.sleep(0.05)
        if call.poll() is None:
            call.kill()
        out, _ = call.communicate(timeout=30)
        assert call.returncode == 0, (out, "".join(lines), answered)
        assert answered == [
            "pull_request_read get", "issue_read get", "issue_read get_comments",  # the reads
            "list_issues", "list_pull_requests", "create_pull_request",  # after the push
            "pull_request_read get_check_runs", "merge_pull_request", "pull_request_read get",
            "pull_request_read get",  # the landing description, for its metrics line
            "add_issue_comment", "update_pull_request", "add_issue_comment",  # the close-out
            "issue_read get_labels", "issue_write update", "issue_write update", "issue_read get",
        ], answered
        assert "Integrated pull request #7" in out, out
        landed = door(origin, "rev-parse", "refs/heads/main")
        assert door(checkout, "rev-parse", "HEAD") == landed  # the checkout at the landed commit
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)
