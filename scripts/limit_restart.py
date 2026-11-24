# se:template se/python-module 1.0.0
"""Worker sessions that stopped on a usage limit without delivering, as the fleet check reports them.

`work_tickets.py fleet-check --sessions <file>` takes the session tools' answers (claude-code-remote):
a JSON list of the sessions `list_sessions` lists, each with the `list_events` answer of its
`result` and `rate_limit_event` events as `"events"`. A session stopped on a usage limit where it is
not working and its newest signal is a limit: a rate-limit event whose status is `rejected`, or a
result whose text names a usage limit; a result after it that names none ends it.

The fleet check always reports such a session for an in-progress issue whose branch the session
names (its title, tags or summary) and that has no delivered pull request; reporting is read-only.
se.toml `[fleet] restart_after_limit` says what the finding's remedy is: off, the built-in, the
report is all that happens; on, the integrator resumes the session once the limit lifts and
comments RESTARTED on the issue, at most once per issue (README "Fleet check").

Everything here is pure: `findings` takes the sessions, the issues, the delivered branches, each
issue's comments, the time and the setting, and answers the findings' facts; `work_tickets.py
fleet_findings` is the thin wiring that wraps them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

#: The finding's kind, listed after the fleet check's own kinds.
KIND = "stopped on a limit"
#: The comment the integrator writes on the issue when it resumes the session; one per issue.
RESTARTED = "Restarted after a usage limit:"
SETTING = "[fleet] restart_after_limit"
#: What a result's text says when the session stopped on a usage limit.
LIMIT_TEXT = re.compile(r"\b(?:usage|rate|session|weekly)\s+limit\b|\blimit\s+(?:reached|hit)\b|"
                        r"\bout of (?:extra )?usage\b", re.IGNORECASE)
#: The session states of a session that is still at work, as `list_sessions` names them.
WORKING = frozenset({"working", "running"})


class SettingError(ValueError):
    """The `[fleet]` table holds a restart value that cannot be read."""


@dataclass(frozen=True)
class Stop:
    """A session stopped on a usage limit: its id, when it last changed and when the limit lifts
    (None where its events do not say)."""

    session: str
    at: datetime | None
    lifts: datetime | None


@dataclass(frozen=True)
class Found:
    """One finding's facts: the issue, its branch, what is wrong and the remedy."""

    issue: int
    branch: str
    what: str
    remedy: str


def restart(table: Mapping[str, object]) -> bool:
    """`restart_after_limit` of se.toml's `[fleet]` table: false, built in, or true."""
    value = table.get("restart_after_limit", False)
    if not isinstance(value, bool):
        raise SettingError(f"fleet.restart_after_limit must be true or false (built in false); "
                           f"got {value!r}")
    return value


def when(value: object) -> datetime | None:
    """A time as the session tools write it: an ISO text, or seconds (or milliseconds) since the
    epoch; None where it is neither."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    if isinstance(value, str) and value:
        try:
            found = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return found if found.tzinfo else found.replace(tzinfo=timezone.utc)
    return None


def signals(node: object) -> list[tuple[str, datetime | None]]:
    """The signals in one event, in order: `("limit", lifts)` for a rejected rate limit or a result
    naming a usage limit, `("result", None)` for any other result."""
    found: list[tuple[str, datetime | None]] = []
    if isinstance(node, list):
        for item in node:
            found += signals(item)
        return found
    if not isinstance(node, dict):
        return found
    info = node.get("rate_limit_info")
    if isinstance(info, dict) and str(info.get("status") or "").lower() == "rejected":
        found.append(("limit", when(info.get("resetsAt") or info.get("resets_at"))))
    if node.get("type") == "result" and isinstance(node.get("result"), str):
        found.append(("limit" if LIMIT_TEXT.search(node["result"]) else "result", None))
    for key, value in node.items():
        if key == "rate_limit_info":
            continue
        if key == "result" and isinstance(value, dict):
            text = str(value.get("result") or value.get("text") or "")
            found.append(("limit" if LIMIT_TEXT.search(text) else "result", None))
            found += signals({k: v for k, v in value.items() if k != "result"})
        elif isinstance(value, (dict, list)):
            found += signals(value)
    return found


def events_of(session: Mapping[str, object]) -> list[object]:
    """A session's events: its `"events"` list, or the `data` list of a list_events answer."""
    events = session.get("events")
    if isinstance(events, dict):
        events = events.get("data")
    return events if isinstance(events, list) else []


def stopped(session: Mapping[str, object]) -> Stop | None:
    """Where `session` stopped on a usage limit, when and until when; None otherwise."""
    state = {str(session.get(key) or "").lower() for key in ("status_bucket", "status")}
    if state & WORKING:
        return None
    limited, lifts = False, None
    for event in events_of(session):
        for kind, until in signals(event):
            limited, lifts = kind == "limit", (until or lifts if kind == "limit" else None)
    if not limited:
        return None
    return Stop(str(session.get("id") or session.get("session_id") or "?"),
                when(session.get("updated_at")), lifts)


def text_of(session: Mapping[str, object]) -> str:
    """What a session says of itself, its events left out: where its branch is named."""
    return json.dumps({key: value for key, value in session.items() if key != "events"},
                      ensure_ascii=False)


def restarted(comments: list[object] | None) -> bool:
    """Whether an issue's comments hold the integrator's RESTARTED comment."""
    return any(isinstance(comment, dict) and
               str(comment.get("body") or "").lstrip().startswith(RESTARTED)
               for comment in comments or [])


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def findings(sessions: list[object], in_progress: Mapping[int, str], delivered: set[str],
             comments_of: Callable[[int], list[object] | None], now: datetime, on: bool
             ) -> list[Found]:
    """One finding per in-progress issue (its number to its branch) without a delivered pull
    request whose branch a session stopped on a usage limit names, the newest such session."""
    newest: dict[int, Stop] = {}
    for session in sessions:
        if not isinstance(session, dict) or (stop := stopped(session)) is None:
            continue
        text = text_of(session)
        for number, branch in in_progress.items():
            if branch and branch in text and branch not in delivered:
                earlier = newest.get(number)
                floor = datetime.min.replace(tzinfo=timezone.utc)
                if earlier is None or (stop.at or floor) >= (earlier.at or floor):
                    newest[number] = stop
    found = []
    for number, stop in sorted(newest.items()):
        branch = in_progress[number]
        lifts = (f"; the limit lifts at {stamp(stop.lifts)}" if stop.lifts else
                 "; its events do not say when the limit lifts")
        at = f" at {stamp(stop.at)}" if stop.at else ""
        what = (f"worker session {stop.session} stopped on a usage limit{at} without delivering "
                f"{branch}{lifts}")
        resume = (f"resume session {stop.session} with one message to continue #{number} and "
                  f"deliver, then comment `{RESTARTED} session {stop.session}` on #{number}; once "
                  "per issue")
        if not on:
            remedy = (f"none: reported only, as se.toml {SETTING} is off; SE decides whether "
                      "to restart it")
        elif restarted(comments_of(number)):
            remedy = (f"none: #{number} was restarted after a usage limit once already (its "
                      f"`{RESTARTED}` comment); SE decides what follows")
        elif stop.lifts is not None and stop.lifts > now:
            remedy = f"once the limit lifts at {stamp(stop.lifts)}, {resume}"
        elif stop.lifts is not None:
            remedy = f"the limit has lifted: {resume}"
        else:
            remedy = f"once the limit lifts, {resume}"
        found.append(Found(number, branch, what, remedy))
    return found
