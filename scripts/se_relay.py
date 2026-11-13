#!/usr/bin/env python3
"""SE's GitHub reads through kern's GitHub relay (README "Hand-offs through the relay").

Without gh (Claude's cloud) SE's commands hand their GitHub steps to the session. Where kern serves
the checkout with its GitHub component on the relay backend, a command reads GitHub through kern
instead of from a file the session retypes: every GitHub tool answer the session receives lands in
kern's snapshot names (`github/issues/<key>`, `github/pulls/<key>`, `github/comments/<key>`,
`github/checks/<key>`) with the time it was read. `Relay.answer_file` writes a snapshot's data, the
tool's answer unchanged, to `.se/.runtime/relay/`, so a command reads it as it reads a file the
session saved, and names the exact tool call to run where no snapshot stands or the one standing is
older than `MAX_AGE_SECONDS`. The session runs that tool, its answer reaches kern through the
PostToolUse hook, and the command runs again.

Where kern does not serve the checkout, or runs its GitHub component on a token, or `SE_KERN=off`,
`relay` answers None and every command keeps its file-based hand-off. Standard library only; kern's
Python SDK and `se_components` are imported where they are needed.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import se_components

#: The GitHub component's instance in the wiring.
GITHUB = "github"
#: The relay backend's name, as the instance's output `backend` reads it.
RELAY = "relay"
#: The oldest snapshot a command reads; an older one is read again with the tool first.
MAX_AGE_SECONDS = 600
#: Where answer_file writes the snapshots a command reads, under the checkout kern serves.
ANSWERS = Path(".se") / ".runtime" / "relay"
#: How long a read of a snapshot name waits for kern.
GET_WAIT = 2.0

#: Each snapshot family and the GitHub tool call that reads it: its tool, method and number key.
FAMILIES = {
    "issues": ("issue_read", "get", "issue_number"),
    "pulls": ("pull_request_read", "get", "pullNumber"),
    "comments": ("issue_read", "get_comments", "issue_number"),
    "checks": ("pull_request_read", "get_check_runs", "pullNumber"),
}


#: The GitHub step of the call this thread runs as one call through kern, where se_components'
#: Stepped set it: step(tool, input, note, wait) asks kern's `github.step` and answers the tool's
#: answer. None outside such a call: the command hands its plan to the session instead. It is the
#: thread's, as calls run side by side in one process, each in its own thread.
_calls = threading.local()


def steps() -> Callable[[str, dict[str, Any], str, str], Any] | None:
    """The GitHub step of the call this thread runs through kern, or None."""
    return getattr(_calls, "step", None)


@contextlib.contextmanager
def stepping(step: Callable[[str, dict[str, Any], str, str], Any]) -> Iterator[None]:
    """Run a command in this thread with `step` as its GitHub step (se_components' Stepped sets
    it); a call beside it in another thread keeps its own."""
    before, _calls.step = steps(), step
    try:
        yield
    finally:
        _calls.step = before


class RelayError(Exception):
    """kern's relay cannot answer what a command asks; its message names the tool call to run."""


def key(owner: str, repo: str, number: int) -> str:
    """A snapshot's key: <owner>.<repo>.<number> in lower case (kern's github.Key)."""
    return f"{owner.lower()}.{repo.lower()}.{number}"


def tool_call(family: str, owner: str, repo: str, number: int) -> str:
    """The GitHub tool call that reads a family's snapshot, as the session runs it."""
    tool, method, number_arg = FAMILIES[family]
    return tool + " " + json.dumps({"method": method, "owner": owner, "repo": repo,
                                    number_arg: number}, sort_keys=True)


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class Relay:
    """kern's GitHub relay for one checkout: `answer_file` writes the file a command reads."""

    def __init__(self, root: Path, get: Callable[[str], Any],
                 now: Callable[[], datetime] | None = None):
        self.root = root
        self.get = get
        self.now = now or (lambda: datetime.now(timezone.utc))

    def snapshot(self, family: str, owner: str, repo: str, number: int) -> dict[str, Any] | None:
        """The snapshot standing for one read, or None."""
        value = self.get(f"{GITHUB}/{family}/{key(owner, repo, number)}")
        return value if isinstance(value, dict) and "data" in value else None

    def answer_file(self, family: str, owner: str, repo: str, number: int, what: str) -> Path:
        """The snapshot's data, the GitHub tool's answer unchanged, written to a file under the
        checkout's .se/.runtime/relay/; raises, naming the tool call, where no snapshot stands or
        it is older than MAX_AGE_SECONDS, so the session runs the tool and the command runs
        again."""
        found = self.snapshot(family, owner, repo, number)
        call = tool_call(family, owner, repo, number)
        if found is None:
            raise RelayError(
                f"kern's relay holds no {what} of {owner}/{repo}#{number}: read it with the GitHub "
                f"tool {call}, then run this command again (its answer reaches kern through the "
                "PostToolUse hook)")
        read = parse_time(found.get("read"))
        age = (self.now() - read).total_seconds() if read else None
        if age is None or age > MAX_AGE_SECONDS:
            raise RelayError(
                f"kern's relay holds the {what} of {owner}/{repo}#{number} as read "
                f"{found.get('read')}, over {MAX_AGE_SECONDS // 60} minutes ago: read it again "
                f"with the GitHub tool {call}, then run this command again")
        path = self.root / ANSWERS / f"{family}-{key(owner, repo, number)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(found["data"], ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
        return path


def relay(root: Path, now: Callable[[], datetime] | None = None) -> Relay | None:
    """kern's relay where kern serves `root` with the GitHub component on the relay backend and
    SE_KERN is not off; else None, and the command keeps its file-based hand-off."""
    if os.environ.get(se_components.SWITCH, "").lower() == "off":
        return None
    served = se_components.kern_root(root.resolve())
    found = se_components.standing(served) if served else None
    if served is None or found is None:
        return None
    se_components.sdk()
    from kern.nats import NatsError, Peer

    def get(name: str) -> Any:
        try:
            peer = Peer(found["bus"], "client", found["users"]["client"], name="se-relay",
                        timeout=se_components.CONNECT_WAIT)
        except (OSError, KeyError, TypeError, ValueError):
            raise RelayError("kern's relay is not reachable")
        try:
            answer = peer.request("get." + GITHUB, {"name": name}, GET_WAIT).json() or {}
        finally:
            peer.close()
        return answer.get("value") if answer.get("provided") else None

    try:
        if get(f"{GITHUB}/{'backend'}") != RELAY:
            return None
    except (NatsError, OSError, RelayError, KeyError, TypeError, ValueError):
        return None
    return Relay(root, get, now)
