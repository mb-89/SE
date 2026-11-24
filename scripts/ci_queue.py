#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""The queue bound of CI's platform legs (docs/tests.md "Platform legs and their queue").

A job's `timeout-minutes` counts from the moment a runner takes it: the time a leg waits in the
queue for a runner counts against nothing but GitHub's own limit (a job without a runner for 24
hours fails), and `check` needs every leg, so one leg that never gets a runner holds the required
check that long. This script bounds that wait:

- `watch`, a job of the same run beside the legs: it reads the run's jobs every `--poll-seconds`;
  once every leg named `--jobs <prefix> (...)` has started on a runner it passes. A leg still
  queued after `--queue-minutes`, or one that ended without a runner (GitHub cancels or fails a leg
  it never placed), is reported as never run, as an error and in the job's summary, never as a
  test failure, and the run is cancelled, so it ends now instead of in 24 hours and `rerun` hears
  a cancelled run.
- `rerun`, from the workflow `check-rerun.yml` once a run of `check` completed: a first attempt
  cancelled while one of its legs never got a runner is re-run once; a second attempt, a run in
  which a leg ran and failed, or a run that ended any other way, is left as it ended.

Standard library only: it runs with the runner's `python3` (3.11 or later) and the Actions token,
through `ci_trust.Api`; exit code 0 passed or nothing to do, 1 a leg never got a runner, 2 a setup
error (the environment, the API)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
import se_script

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_trust import Api, TrustError  # noqa: E402

#: The statuses of a job that no runner has taken yet.
WAITING = frozenset({"queued", "waiting", "pending", "requested"})


def legs(jobs: list[dict], prefix: str) -> list[dict]:
    """The jobs of one matrix job, named `<prefix> (<leg>)`, or `<prefix>` alone."""
    return [j for j in jobs if j.get("name") == prefix or str(j.get("name", "")).startswith(prefix + " (")]


def waiting(jobs: list[dict], prefix: str) -> list[str]:
    """The names of the legs no runner has taken yet."""
    return [str(j["name"]) for j in legs(jobs, prefix) if j.get("status") in WAITING]


def unplaced(job: dict) -> bool:
    """No runner named and no step run: no runner ever took the job."""
    return not job.get("runner_name") and not job.get("steps")


def ended_unrun(jobs: list[dict], prefix: str) -> list[str]:
    """The names of the legs that ended without a runner ever taking them: never run, never
    passed."""
    return [str(j["name"]) for j in legs(jobs, prefix)
            if j.get("status") == "completed" and unplaced(j)]


def failed(jobs: list[dict], prefix: str) -> list[str]:
    """The names of the legs that ran on a runner and failed: a test failure."""
    return [str(j["name"]) for j in legs(jobs, prefix)
            if j.get("conclusion") == "failure" and not unplaced(j)]


def never_ran(jobs: list[dict], prefix: str) -> list[str]:
    """The names of the legs of a completed run that never had a runner: no runner named, no
    step run."""
    return [str(j["name"]) for j in legs(jobs, prefix) if unplaced(j)]


def jobs_of(api: Api, run: int, attempt: int | None = None) -> list[dict]:
    path = f"actions/runs/{run}" + (f"/attempts/{attempt}" if attempt else "") + "/jobs?per_page=100"
    answer = api.request("GET", path) or {}
    return list(answer.get("jobs") or []) if isinstance(answer, dict) else []


def watch(api: Api, run: int, attempt: int, prefix: str, queue_minutes: float, poll_seconds: float,
          now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
          summary: Path | None = None) -> int:
    """Pass once every leg has started on a runner; a leg that ended without one, or one still
    waiting past the queue bound, is reported as never run and the run cancelled (`rerun` re-runs
    a first attempt once)."""
    deadline = now() + queue_minutes * 60
    while True:
        jobs = jobs_of(api, run, attempt)
        found, left, ended = legs(jobs, prefix), waiting(jobs, prefix), ended_unrun(jobs, prefix)
        if ended:
            why = "(it ended without one)"
            break
        if found and not left:
            print(f"ci-queue: every {prefix} leg got a runner: " + ", ".join(j["name"] for j in found))
            return 0
        if now() >= deadline:
            why = f"within {queue_minutes:g} minutes"
            break
        sleep(poll_seconds)
    named = ", ".join(ended + left) or f"{prefix} (none listed)"
    line = (f"{named} never got a runner {why}: it was not tested, which is no test failure; the "
            "run is cancelled"
            + (" and re-runs once (check-rerun.yml)" if attempt == 1 else ", and this second attempt "
               "is not re-run"))
    print(f"::error title=no runner for {prefix}::{line}")
    if summary is not None:
        with summary.open("a", encoding="utf-8") as out:
            out.write(f"### {prefix}: no runner\n\n{line}\n")
    api.request("POST", f"actions/runs/{run}/cancel")
    return 1


def rerun(api: Api, run: int, prefix: str) -> int:
    """Re-run a first attempt that was cancelled while one of its legs never got a runner."""
    found = api.request("GET", f"actions/runs/{run}") or {}
    attempt = int(found.get("run_attempt") or 0)
    if found.get("conclusion") != "cancelled" or attempt != 1:
        print(f"ci-queue: run {run} attempt {attempt} ended {found.get('conclusion')}: nothing to re-run")
        return 0
    jobs = jobs_of(api, run, attempt)
    broken = failed(jobs, prefix)
    if broken:
        print(f"ci-queue: run {run}: {', '.join(broken)} failed: a test failure stays as it ended")
        return 0
    idle = never_ran(jobs, prefix)
    if not idle:
        print(f"ci-queue: run {run} was cancelled with every {prefix} leg run: not re-run")
        return 0
    print(f"ci-queue: run {run} was cancelled as {', '.join(idle)} never got a runner: re-running it once")
    api.request("POST", f"actions/runs/{run}/rerun")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = se_script.parser(prog="ci_queue.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("watch", help="bound the queue wait of this run's platform legs")
    w.add_argument("--jobs", required=True, help="the matrix job's name, e.g. kern-platforms")
    w.add_argument("--queue-minutes", type=float, required=True)
    w.add_argument("--poll-seconds", type=float, default=30.0)
    r = sub.add_parser("rerun", help="re-run once a first attempt cancelled for a leg without a runner")
    r.add_argument("--jobs", required=True)
    r.add_argument("--run", type=int, required=True, help="the completed run of check")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    env = os.environ
    try:
        api = Api(env.get("GITHUB_API_URL") or "https://api.github.com", env["GITHUB_TOKEN"],
                  env["GITHUB_REPOSITORY"])
        if args.command == "watch":
            summary = env.get("GITHUB_STEP_SUMMARY")
            return watch(api, int(env["GITHUB_RUN_ID"]), int(env.get("GITHUB_RUN_ATTEMPT") or 1),
                         args.jobs, args.queue_minutes, args.poll_seconds,
                         summary=Path(summary) if summary else None)
        return rerun(api, args.run, args.jobs)
    except KeyError as error:
        print(f"::error title=ci-queue::{args.command}: the environment names no {error}")
        return 2
    except TrustError as error:
        print(f"::error title=ci-queue::{args.command}: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
