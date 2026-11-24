# se:template se/python-module 1.0.0
"""A push of a work branch after its delivery, named at the push instead of at the landing.

`work_tickets.py deliver` (and, without gh, `stop-check --pull`) records the tip it delivered in
the checkout, `.se/work/delivered-tip.json`: the branch and its commit. The pre-push hook's guard,
`work_tickets.py verified`, asks `verdict` about every push: a push of that branch with another
commit makes the delivery stale, as the integrator's read-back of the field report's Branch tip
would refuse it, so it prints one line saying so and that `deliver` must run again after the push.

se.toml `[deliver] late_push` says what that line does: `"warn"` (built in) lets the push through,
`"refuse"` refuses it. `work_tickets.py push --redeliver` records the tip it pushes first, the
redelivery's own push without gh. Everything here is pure but `load` and `record`, which read and
write the record (docs/fleet.md "Late push").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

RECORD = "delivered-tip.json"
MODES = ("warn", "refuse")
DEFAULT_MODE = "warn"


@dataclass(frozen=True)
class Verdict:
    """What the guard says about one push: the line to print, and whether it refuses the push."""

    line: str
    refuse: bool


def record_path(work: Path) -> Path:
    """The record in the checkout's ticket folder `work` (`.se/work`)."""
    return work / RECORD


def load(work: Path) -> dict[str, str] | None:
    """The delivered branch and tip recorded in `work`; None without a readable record."""
    try:
        data = json.loads(record_path(work).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("branch") or not data.get("tip"):
        return None
    return {"branch": str(data["branch"]), "tip": str(data["tip"])}


def record(work: Path, branch: str, tip: str) -> dict[str, str] | None:
    """Record `tip` as the delivered commit of `branch` in `work`; the record it replaced."""
    before = load(work)
    work.mkdir(parents=True, exist_ok=True)
    record_path(work).write_text(json.dumps({"branch": branch, "tip": tip}, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
    return before


def restore(work: Path, before: dict[str, str] | None) -> None:
    """Put back the record `record` replaced: none, or the one it returned."""
    if before is None:
        record_path(work).unlink(missing_ok=True)
    else:
        record(work, before["branch"], before["tip"])


def mode(table: dict[str, object]) -> str:
    """`late_push` of se.toml's `[deliver]` table, `table`: warn (built in) or refuse."""
    value = table.get("late_push", DEFAULT_MODE)
    if value not in MODES:
        raise ValueError(f"deliver.late_push must be one of {', '.join(MODES)} (built in "
                         f"{DEFAULT_MODE}); got {value!r}")
    return str(value)


def same(one: str, other: str) -> bool:
    """Whether two commit names, either abbreviated, name the same commit."""
    return bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))


def verdict(delivered: dict[str, str] | None, remote_ref: str, commit: str,
            setting: str = DEFAULT_MODE) -> Verdict | None:
    """The guard's word on a push of `commit` to `remote_ref`: None where nothing was delivered,
    the ref is not the delivered branch, or the commit is the delivered tip."""
    if delivered is None or remote_ref != f"refs/heads/{delivered['branch']}":
        return None
    if same(commit, delivered["tip"]):
        return None
    where = f"late push: {delivered['branch']} was delivered at {delivered['tip'][:12]} and "
    if setting == "refuse":
        return Verdict(
            f"error: {where}this push would move it to {commit[:12]}, making the delivery stale; "
            'se.toml [deliver] late_push = "refuse" refuses it: push it through '
            "work_tickets.py deliver, or without gh work_tickets.py push --redeliver", True)
    return Verdict(
        f"warning: {where}this push moves it to {commit[:12]}: the delivery is now stale and the "
        "integrator will refuse it; run work_tickets.py deliver again after this push", False)
