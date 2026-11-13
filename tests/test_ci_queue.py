"""CI's queue bound of the platform legs (scripts/ci_queue.py, README "Platform legs and their
queue"), against a fake of GitHub's jobs API and a fake clock: a leg that never gets a runner is
reported as such and its run cancelled, and a first attempt cancelled so is re-run once."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_queue  # noqa: E402

PREFIX = "kern-platforms"


def job(leg: str, status: str, runner: str = "", steps: int = 0) -> dict:
    return {"name": f"{PREFIX} ({leg})", "status": status, "runner_name": runner or None,
            "steps": [{"name": "Set up job"}] * steps}


class FakeApi:
    """GitHub's REST API as ci_queue asks it: the jobs of each poll in turn, and the run."""

    def __init__(self, polls: list[list[dict]], run: dict | None = None) -> None:
        self.polls, self.run, self.asked = polls, run or {}, []

    def request(self, method: str, path: str, data: dict | None = None) -> object:
        self.asked.append((method, path))
        if method == "GET" and path.endswith("/jobs?per_page=100"):
            return {"jobs": self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]}
        if method == "GET":
            return self.run
        return {}


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_every_leg_with_a_runner_passes_without_cancelling(capsys) -> None:
    api, clock = FakeApi([[job("windows-2025", "queued"), job("macos-15", "queued"),
                           {"name": "check", "status": "queued"}],
                          [job("windows-2025", "in_progress", "w1", 2), job("macos-15", "completed", "m1", 9)]]), Clock()
    assert ci_queue.watch(api, 7, 1, PREFIX, 20, 30, clock.now, clock.sleep) == 0
    assert "every kern-platforms leg got a runner" in capsys.readouterr().out
    assert ("POST", "actions/runs/7/cancel") not in api.asked
    assert api.asked[0] == ("GET", "actions/runs/7/attempts/1/jobs?per_page=100")


def test_a_leg_without_a_runner_past_the_bound_is_reported_and_its_run_cancelled(tmp_path, capsys) -> None:
    api, clock = FakeApi([[job("windows-2025", "completed", "w1", 9), job("macos-15", "queued")]]), Clock()
    summary = tmp_path / "summary.md"
    assert ci_queue.watch(api, 7, 1, PREFIX, 20, 30, clock.now, clock.sleep, summary) == 1
    out = capsys.readouterr().out
    assert ("::error title=no runner for kern-platforms::kern-platforms (macos-15) never got a runner "
            "within 20 minutes: it was not tested, which is no test failure; the run is cancelled and "
            "re-runs once (check-rerun.yml)") in out
    assert "kern-platforms (windows-2025)" not in out
    assert "never got a runner" in summary.read_text(encoding="utf-8")
    assert api.asked[-1] == ("POST", "actions/runs/7/cancel")
    assert clock.t == 20 * 60, "it waited the bound, polling, and no longer"


def test_a_second_attempt_says_it_is_not_re_run(capsys) -> None:
    api, clock = FakeApi([[job("macos-15", "queued")]]), Clock()
    assert ci_queue.watch(api, 7, 2, PREFIX, 1, 30, clock.now, clock.sleep) == 1
    assert "this second attempt is not re-run" in capsys.readouterr().out


def test_a_first_attempt_cancelled_for_a_leg_without_a_runner_is_re_run_once(capsys) -> None:
    jobs = [job("windows-2025", "completed", "w1", 9), job("macos-15", "completed")]
    api = FakeApi([jobs], {"conclusion": "cancelled", "run_attempt": 1})
    assert ci_queue.rerun(api, 7, PREFIX) == 0
    assert api.asked[-1] == ("POST", "actions/runs/7/rerun")
    assert "kern-platforms (macos-15) never got a runner: re-running it once" in capsys.readouterr().out


def test_no_re_run_of_a_second_attempt_a_failure_or_a_cancel_after_every_leg_ran() -> None:
    ran = [job("windows-2025", "completed", "w1", 9), job("macos-15", "completed", "m1", 3)]
    idle = [job("macos-15", "completed")]
    for run, jobs in (({"conclusion": "cancelled", "run_attempt": 2}, idle),
                      ({"conclusion": "failure", "run_attempt": 1}, idle),
                      ({"conclusion": "cancelled", "run_attempt": 1}, ran)):
        api = FakeApi([jobs], run)
        assert ci_queue.rerun(api, 7, PREFIX) == 0
        assert not any(method == "POST" for method, _ in api.asked), run


def test_the_workflow_bounds_the_legs_queue_and_re_runs_from_its_own_workflow() -> None:
    check = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
    watcher = check[check.index("\n  kern-platforms-queue:\n"):]
    watcher = watcher[:watcher.find("\n  # ", 1)]
    assert "python3 scripts/ci_queue.py watch --jobs kern-platforms --queue-minutes" in watcher
    assert "actions: write" in watcher and "needs: trust" in watcher
    legs = check[check.index("\n  kern-platforms:\n"):]
    assert "\n    timeout-minutes: " in legs[:legs.index("steps:")], "a leg that runs is bounded too"
    rerun = (ROOT / ".github" / "workflows" / "check-rerun.yml").read_text(encoding="utf-8")
    assert "workflows: [check]" in rerun and "types: [completed]" in rerun
    assert "github.event.workflow_run.conclusion == 'cancelled'" in rerun
    assert "python3 scripts/ci_queue.py rerun --jobs kern-platforms --run" in rerun
