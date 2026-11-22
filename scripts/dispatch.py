#!/usr/bin/env python3
"""The dispatcher (README "Dispatcher"): a check with no model that fires the scheduled task whose
session is a fresh integrator, where startable work waits and no integrator runs.

`work_tickets.py dispatch` registers the command and passes itself as `wt`: this module reads
GitHub through its doors (`run_gh`, `issue_api`) and its one owner of startable work
(`ready_issues`), and owns only what the dispatcher adds: whether an integrator runs, and the fire.

The task's fire URL (its API trigger's, which names the task's id) and its token come from the
variables below, set from repository secrets: no committed file names the task, its token or the
service's host.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

TRIGGER_VARIABLE = "SE_DISPATCH_TRIGGER"
TOKEN_VARIABLE = "SE_DISPATCH_TOKEN"
HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "experimental-cc-routine-2026-04-01",
    "Content-Type": "application/json",
}
TRIGGER_PATH = re.compile(r"/\S*/trig_[A-Za-z0-9]+/fire\Z")
MODES = ("report", "dry-run", "fire")


def github_time(value: object) -> datetime | None:
    """A GitHub timestamp (`2026-11-22T09:49:51Z`) as an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def branch_pushed_at(wt: ModuleType, root: Path, repo: str, branch: str) -> datetime | None:
    """When `branch`'s tip on GitHub was committed, or None where GitHub has no such branch."""
    try:
        found = wt.issue_api(root, repo, "branches/" + urllib.parse.quote(branch, safe=""))
    except wt.QueueError as error:
        if "404" in str(error) or "Not Found" in str(error):
            return None
        raise
    commit = (found.get("commit") or {}).get("commit") or {}
    return github_time((commit.get("committer") or {}).get("date"))


def integrator_activity(wt: ModuleType, root: Path, repo: str,
                        now: datetime | None = None) -> list[str]:
    """What shows that an integrator runs for `repo`, one line each, read from GitHub alone, as the
    scheduled task's token reads nothing: an open landing pull request (`land/<branch>`) updated
    within the fleet's lease, or in-progress work whose issue or branch moved within it (a worker
    of a running integrator, which its delivery wakes). None: no integrator runs."""
    now = now or datetime.now(timezone.utc)
    lease = wt.fleet_lease(root)
    code = wt.remote_repo(root) or repo
    pulls, active = (json.loads(listing or "[]") for listing in wt.concurrently(
        lambda: wt.run_gh(root, [
            "pr", "list", "--state", "open", "--json", "number,headRefName,updatedAt",
            "--limit", "200", *wt.repo_arguments(code),
        ]),
        lambda: wt.run_gh(root, [
            "issue", "list", "--state", "open", "--label", "work", "--label", wt.IN_PROGRESS_LABEL,
            "--json", "number,title,updatedAt", "--limit", "200",
            *wt.repository_label_arguments(root, False), *wt.repo_arguments(repo),
        ]),
    ))

    def recent(moment: datetime | None) -> bool:
        return moment is not None and now - moment <= lease

    found = [f"landing pull request #{pull['number']} ({pull['headRefName']}) is open"
             for pull in pulls
             if str(pull.get("headRefName", "")).startswith(wt.LANDING_PREFIX)
             and recent(github_time(pull.get("updatedAt")))]
    pushed = wt.concurrently(*(lambda issue=issue: branch_pushed_at(wt, root, code, str(issue["title"]))
                               for issue in active))
    for issue, tip in zip(active, pushed):
        if recent(github_time(issue.get("updatedAt"))) or recent(tip):
            found.append(f"#{issue['number']} {issue['title']} is in progress")
    return found


class FireError(Exception):
    """The fire was refused or could not be made; nothing was fired."""


def fire(trigger: str, token: str, text: str) -> dict[str, object]:
    """Fire the scheduled task once through its API trigger's fire URL `trigger`; its answer."""
    request = urllib.request.Request(
        trigger, method="POST", data=json.dumps({"text": text}).encode("utf-8"),
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise FireError(f"dispatch: firing the scheduled task failed: HTTP {error.code} "
                        f"{error.reason}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise FireError(f"dispatch: firing the scheduled task failed: {error}") from None


def secrets(environ: dict[str, str] | os._Environ = os.environ) -> tuple[str, str]:
    """The scheduled task's fire URL and token from the environment, refused where one is
    missing or the URL is not an API trigger's."""
    trigger = environ.get(TRIGGER_VARIABLE, "").strip()
    token = environ.get(TOKEN_VARIABLE, "").strip()
    missing = [name for name, value in ((TRIGGER_VARIABLE, trigger), (TOKEN_VARIABLE, token))
               if not value]
    if missing:
        raise FireError(f"dispatch --fire: {' and '.join(missing)} not set; set the repository "
                        "secrets README \"Dispatcher\" names, or run --dry-run")
    url = urllib.parse.urlsplit(trigger)
    if url.scheme != "https" or not url.netloc or not TRIGGER_PATH.match(url.path):
        raise FireError(f"dispatch --fire: {TRIGGER_VARIABLE} is not a scheduled task's fire URL "
                        "(an https URL ending in /trig_<id>/fire, as its API trigger shows it)")
    return trigger, token


def dispatch(wt: ModuleType, root: Path, repo: str, mode: str, pause: list[dict[str, object]],
             startable: list[dict[str, object]], now: datetime | None = None) -> list[str]:
    """The dispatcher's run: the startable issues, whether an integrator runs, and the verdict.
    `pause` and `startable` are what work_tickets.py read (`pause_issues`, `ready_issues`).
    `mode` is "report" (no verdict acted on), "dry-run" (prints the fire it would make) or "fire"
    (fires the scheduled task once where startable work waits, no integrator runs and the fleet
    is not paused). It reads GitHub only, so a run that fires nothing makes no model call."""
    if mode not in MODES:
        raise ValueError(f"dispatch: mode {mode!r} is none of {', '.join(MODES)}")
    running = integrator_activity(wt, root, repo, now)
    lines = [f"Startable: #{issue['number']} {issue['title']}" for issue in startable]
    lines += [] if startable else ["Startable: none"]
    lines += [f"Integrator runs: {line}" for line in running]
    lines += [] if running else ["Integrator runs: none seen"]
    if pause:
        return [*lines, f"Fires nothing: the fleet is paused by {wt.pause_names(pause)}"]
    if not startable:
        return [*lines, "Fires nothing: no startable work"]
    if running:
        return [*lines, "Fires nothing: an integrator runs"]
    text = ("Startable work waits and no integrator runs: "
            + ", ".join(f"#{issue['number']}" for issue in startable))
    if mode == "dry-run":
        return [*lines, f"Would fire the scheduled task once: {text}"]
    if mode == "report":
        return [*lines, "Would fire the scheduled task once; pass --fire to fire it"]
    trigger, token = secrets()  # before anything is fired, so a missing one fires nothing
    answer = fire(trigger, token, text)
    session = answer.get("claude_code_session_url") or "no session named"
    return [*lines, f"Fired the scheduled task once: {session}"]
