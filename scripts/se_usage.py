"""The use log, `usage/adhoc` (docs/go-core.md "Scripts are ad hoc, components are long-term"): the
ad hoc components' calls and the ad hoc scripts' runs.

The kern core appends one record per call to an ad hoc component, by its path, and one per run of
an ad hoc script it saw in a shell tool's PostToolUse, by the script's path and content hash, into
`<root>/.se/usage/adhoc.jsonl`; `retro.py collect` reads it and lists a component used in
`PROMOTE_SESSIONS` or more sessions, and a script run `PROMOTE_RUNS` or more times, since the last
retro as promotion candidates. This module owns
the record's shape and the threshold for the Python side; docs/go-core.md owns the shape the Go core
writes, so Go and Python agree on one record (as they do on the declaration hash).

One record is one line of JSON:

    {"at": "2026-11-13T13:20:21Z", "session": "<id>", "component": "<name>", "path": ".se/components/<name>"}

- **at** is when the call was answered, RFC3339 UTC.
- **session** is the Claude session the call ran in, or "" where the core knew none; the candidate
  count is distinct non-empty sessions, so an empty session is one anonymous bucket.
- **component** is the ad hoc component's name; **path** is its folder under the checkout.

A script's run (kern/host/scripts.go owns which runs count) is one line of its own:

    {"at": "2026-11-13T15:02:11Z", "session": "<id>", "script": "probe.py", "hash": "<sha256>"}

- **script** is its path under the checkout, or under the scratch place it lives in
  (`<scratchpad>/…`, `<tmp>/…`); **hash** is the sha256 of its content; neither its arguments nor
  its output are ever recorded.

Standard library only; `.se/` is git-ignored, so the log is worktree-local and never merges.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

#: The use log, under the checkout the core serves; `.se/` is ignored (AGENTS.md).
STORE = Path(".se") / "usage" / "adhoc.jsonl"

#: Where the ad hoc components live, as `se component add` scaffolds them (docs/go-core.md).
COMPONENTS = Path(".se") / "components"

#: A component used in this many sessions or more since the last retro is a promotion candidate.
PROMOTE_SESSIONS = 3

#: A script run this many times or more since the last retro is a promotion candidate.
PROMOTE_RUNS = 3

#: The most-run scripts the retro lists, at most.
SCRIPTS_LISTED = 10


def path(root: Path) -> Path:
    """The use log under `root`."""
    return root / STORE


def record(root: Path, component: str, *, session: str = "", at: str | None = None,
           where: str | None = None) -> None:
    """Append one use of `component` to the log under `root`, the Python writer the tests use; the
    core writes the same record in Go."""
    entry = {"at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "session": session, "component": component,
             "path": where or (COMPONENTS / component).as_posix()}
    file = path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read(root: Path) -> list[dict]:
    """Every use record in the log under `root`, newest or oldest alike; a malformed line is
    skipped, so one bad write never hides the rest."""
    file = path(root)
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and (isinstance(entry.get("component"), str)
                                        or isinstance(entry.get("script"), str)):
            found.append(entry)
    return found


def candidates(records: Iterable[dict], in_window: Callable[[str], bool],
               threshold: int = PROMOTE_SESSIONS) -> list[dict]:
    """The promotion candidates among `records`: each ad hoc component whose uses in the window
    (those whose `at` passes `in_window`) span `threshold` or more distinct sessions, as
    `{component, path, sessions, uses}`, most used first then by name."""
    by_name: dict[str, dict] = {}
    for entry in records:
        at = entry.get("at")
        if not isinstance(at, str) or not in_window(at) or not isinstance(entry.get("component"), str):
            continue
        name = entry["component"]
        found = by_name.setdefault(name, {"component": name,
                                           "path": str(entry.get("path") or (COMPONENTS / name).as_posix()),
                                           "sessions": set(), "uses": 0})
        found["uses"] += 1
        session = entry.get("session")
        if isinstance(session, str) and session:
            found["sessions"].add(session)
    found = [{"component": c["component"], "path": c["path"], "sessions": len(c["sessions"]),
              "uses": c["uses"]}
             for c in by_name.values() if len(c["sessions"]) >= threshold]
    found.sort(key=lambda c: (-c["uses"], c["component"]))
    return found


def record_run(root: Path, script: str, digest: str, *, session: str = "", at: str | None = None) -> None:
    """Append one run of `script` (its content's sha256 `digest`) to the log under `root`, the
    Python writer the tests use; the core writes the same record in Go."""
    entry = {"at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "session": session, "script": script, "hash": digest}
    file = path(root)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def script_candidates(records: Iterable[dict], in_window: Callable[[str], bool],
                      threshold: int = PROMOTE_RUNS, listed: int = SCRIPTS_LISTED) -> list[dict]:
    """The most-run ad hoc scripts among `records`: each script, by its path and content hash, run
    `threshold` or more times in the window (those runs whose `at` passes `in_window`), as
    `{script, hash, runs, sessions}`, most run first then by path, at most `listed` of them."""
    by_key: dict[tuple[str, str], dict] = {}
    for entry in records:
        at, script = entry.get("at"), entry.get("script")
        if not isinstance(at, str) or not isinstance(script, str) or not in_window(at):
            continue
        digest = str(entry.get("hash") or "")
        found = by_key.setdefault((script, digest), {"script": script, "hash": digest,
                                                     "runs": 0, "sessions": set()})
        found["runs"] += 1
        session = entry.get("session")
        if isinstance(session, str) and session:
            found["sessions"].add(session)
    found = [{"script": s["script"], "hash": s["hash"], "runs": s["runs"],
              "sessions": len(s["sessions"])}
             for s in by_key.values() if s["runs"] >= threshold]
    found.sort(key=lambda s: (-s["runs"], s["script"], s["hash"]))
    return found[:listed]
