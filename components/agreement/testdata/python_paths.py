"""The Python side of the agreement test (agreement_test.go): SE's Python fleet check, retro
countdown and overhaul countdown, scripts/work_tickets.py fleet_findings, scripts/retro.py
retro_countdown and scripts/overhaul.py overhaul_countdown, run on the GitHub snapshot names a
fixture holds, through doors that read them as the Python reads GitHub, with the fixture's
settings at its `now`.
Prints {"fleet": <fleet-check --json>, "retro": <countdown>, "overhaul": <countdown>}.

With --ages the fleet check runs with se.toml `[fleet] ages` on, as the Go side with its config
`ages` on.

Usage: python python_paths.py <se root> <fixture.json> [--ages]
"""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import overhaul  # noqa: E402
import retro  # noqa: E402
import work_tickets  # noqa: E402

fixture = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))


def data(family: str) -> list[dict]:
    """The family's answers, lowest number first."""
    return [s["data"] for s in sorted(fixture[family].values(), key=lambda s: s["number"])]


def state(item: dict) -> str:
    return str(item.get("state") or "").lower()


def conclusion(number: int) -> str:
    """The conclusion of the first check run named CHECK_NAME at the pull request's head."""
    snap = next((s for s in fixture["checks"].values() if s["number"] == number), None)
    runs = snap["data"] if snap else []
    runs = runs.get("check_runs", []) if isinstance(runs, dict) else runs
    return next((str(r.get("conclusion") or "") for r in runs
                 if r.get("name") == work_tickets.CHECK_NAME), "")


def base(item: dict) -> str:
    return str((item.get("base") or {}).get("ref") or item.get("baseRefName") or "")


class SnapshotFleet:
    """fleet_findings' door on the names: the issues by state, the open pull requests to the
    integration branch with their check, origin's branches; the names carry no comments."""

    def issues(self, wanted: str) -> list[dict]:
        return [item for item in data("issues") if state(item) == wanted]

    def issue(self, number: int) -> dict | None:
        return next((item for item in data("issues") if item["number"] == number), None)

    def comments(self, number: int) -> None:
        return None

    def pulls(self) -> list[dict]:
        return [{**item, "check": conclusion(item["number"])} for item in data("pulls")
                if state(item) == "open" and base(item) == fixture["base"]]

    def branches(self) -> dict[str, datetime]:
        return {name: datetime.fromisoformat(when.replace("Z", "+00:00"))
                for name, when in fixture["branches"].items()}


class SnapshotRetro:
    """The countdowns' door on the names."""

    missing: list = []

    def closed_issues(self) -> list[dict]:
        return [item for item in data("issues") if state(item) == "closed"]

    def open_issues(self) -> list[dict]:
        return [item for item in data("issues") if state(item) == "open"]

    def pulls(self) -> list[dict]:
        return data("pulls")

    def issue(self, number: int) -> dict:
        return next((item for item in data("issues") if item["number"] == number), {})


now = datetime.fromisoformat(fixture["now"].replace("Z", "+00:00"))
found = work_tickets.fleet_findings(SnapshotFleet(), now, timedelta(hours=fixture["lease_hours"]),
                                    fixture["repository"], ages="--ages" in sys.argv[3:])
door = SnapshotRetro()
closed = [retro.issue_of(item) for item in door.closed_issues()]
opened = [retro.issue_of(item) for item in door.open_issues()]
pulls = [retro.pull_of(item) for item in door.pulls()]
print(json.dumps({
    "fleet": json.loads(work_tickets.fleet_report(found, True)),
    "retro": asdict(retro.retro_countdown(
        closed, opened, pulls, fixture["tracker"], fixture["base"],
        {"due_after": fixture["due_after"], "failure_weight": fixture["failure_weight"],
         "days": fixture["days"]}, now)),
    "overhaul": asdict(overhaul.overhaul_countdown(
        closed, opened, {"due_after": fixture["overhaul_after"],
                         "days": fixture["overhaul_days"]}, now)),
}))
