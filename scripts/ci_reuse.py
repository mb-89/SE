#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Whether a run of `check` takes the suite's result from an earlier run of the same tree instead
of running it again (docs/tests.md "One suite run per tree").

A tree is checked once per landing: the work pull request's run, the landing pull request's and
the push to the integration branch check the same tree when nothing moved between them, and a pull
request's description and labels change many times without a new commit. Each such run checks the
field report and the issue rule again, as the description can change them, and takes the result of
the suite, the Go checks, kern-platforms and showcase from the newest completed run of `check` that
carries one for the same reuse key: the tree checked out (on a pull request the merge of the head
into its base, so a moved base is another tree) and the Component kinds the description gives the
suite's release guard.

The runs read are those of this landing's own pull requests, on any event but the nightly safety
net: on a pull request its head and the work pull request its landing description names
(`<!-- se:field-report-in <n> -->`); on a push the merged pull requests that landed the commit and
the work pull requests they name. A run of the same reuse key checked out the same tree, so it ran
the same workflow and the same tests: its result is the tree's.

`key` writes the run's reuse key; the `trust` job names its decision step after it, so a later run
reads each earlier run's key from that step's name in the jobs API. `decide` answers `suite`: `run`
(this run runs them), `trusted` (the integrator's record, scripts/ci_trust.py) or `reused`, with
the earlier run it took the result from and that result, `success` or `failure`. A scheduled run,
a re-run attempt, a newest completed run of the head that was cancelled and a tree without such a
run run everything; a failed earlier result is taken as failed. Standard library only: it runs
with the runner's `python3` and the Actions token; exit code 0 done, 2 a setup error."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ci_trust
import component_versions
import se_script

REUSE_EVENTS = ("pull_request", "push")  # every event but the nightly safety net (schedule)
DECIDE_STEP = "Reuse an earlier result of this tree"  # the trust job's step, named with the key
KEY_NAMED = re.compile(r"\(reuse key ([0-9a-f]{16})\)\s*$")
CHECK_JOB, TRUST_JOB, PLATFORM_JOB, SHOWCASE_JOB = "check", "trust", "kern-platforms", "showcase"
SUITE_STEP = "The complete suite and the suites beside it"
VET_STEP = "SE's Go components vet"
REPORT_IN = re.compile(r"(?m)^<!-- se:field-report-in ([0-9]+) -->[ \t\r]*$")
REPORT_MARK = "<!-- se:field-report -->"
RUNS_READ = 100  # earlier runs of the head read at most, newest first


class ReuseError(Exception):
    """A setup error: the event, git or GitHub's API; exit code 2."""


def stated_kinds(body: str | None) -> str | None:
    """The release guard's $SE_COMPONENT_KINDS as `check`'s field-report step sets it from the
    description `body`: None where it sets none (a landing pull request's link, or no field
    report), else the report's Component kinds; refused where they cannot be read."""
    text = body or ""
    if REPORT_IN.search(text) or REPORT_MARK not in text:
        return None
    try:
        return component_versions.environment_value(component_versions.stated_kinds(text))
    except component_versions.VersionError as error:
        raise ReuseError(f"the description's Component kinds: {error}") from error


def reuse_key(tree: str, kinds: str | None) -> str:
    """What decides the suite's result besides the workflow: the tree and the kinds, hashed. No
    kinds stated and none set are one key: the release guard reads an empty value as unset (kern's
    tools/release Kinds), so a work pull request that states none and its landing share it."""
    text = json.dumps({"tree": tree, "kinds": kinds or None}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Event:
    """The run asking: its event and action, its id and attempt, and the pull request's head (on a
    push the commit pushed) and description."""

    name: str
    action: str = ""
    run_id: str = ""
    attempt: int = 1
    head: str = ""
    body: str = ""

    @classmethod
    def of(cls, environ: dict[str, str]) -> "Event":
        payload: dict = {}
        if environ.get("GITHUB_EVENT_PATH"):
            try:
                payload = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ReuseError(f"the event payload {environ['GITHUB_EVENT_PATH']}: {error}")
        pull = payload.get("pull_request") or {}
        attempt = environ.get("GITHUB_RUN_ATTEMPT", "1")
        head = (pull.get("head") or {}).get("sha") or environ.get("GITHUB_SHA", "")
        return cls(environ.get("GITHUB_EVENT_NAME", ""), str(payload.get("action") or ""),
                   environ.get("GITHUB_RUN_ID", ""), int(attempt) if attempt.isdigit() else 1,
                   str(head), str(pull.get("body") or ""))


@dataclass(frozen=True)
class Decision:
    suite: str  # run, trusted or reused
    why: str
    source: str = ""  # the earlier run's URL, where reused
    result: str = ""  # its result, success or failure, where reused


def run_everything(why: str) -> Decision:
    return Decision("run", why + ": the suite, the Go checks, kern-platforms and showcase run")


def work_pull(body: str | None) -> int | None:
    """The work pull request a landing pull request's description links, or None."""
    linked = REPORT_IN.search(body or "")
    return int(linked[1]) if linked else None


def job(jobs: list[dict], name: str) -> dict | None:
    return next((found for found in jobs if found.get("name") == name), None)


def step(found: dict | None, prefix: str) -> dict | None:
    return next((named for named in (found or {}).get("steps") or []
                 if str(named.get("name") or "").startswith(prefix)), None)


def key_of(jobs: list[dict]) -> str | None:
    """The reuse key an earlier run's trust job named its decision step with; None before it."""
    named = KEY_NAMED.search(str((step(job(jobs, TRUST_JOB), DECIDE_STEP) or {}).get("name") or ""))
    return named[1] if named else None


def results(jobs: list[dict]) -> dict[str, str]:
    """What an earlier run concluded for each part this run would take: the Go checks, the suite,
    each kern-platforms leg and showcase; `missing` where it has none."""
    check = job(jobs, CHECK_JOB)
    found = {part: str((step(check, prefix) or {}).get("conclusion") or "missing")
             for part, prefix in (("the Go checks", VET_STEP), ("the suite", SUITE_STEP))}
    legs = [leg for leg in jobs if str(leg.get("name") or "") == PLATFORM_JOB
            or str(leg.get("name") or "").startswith(f"{PLATFORM_JOB} (")]
    for leg in legs:
        found[str(leg["name"])] = str(leg.get("conclusion") or "missing")
    if not legs:
        found[PLATFORM_JOB] = "missing"
    found[SHOWCASE_JOB] = str((job(jobs, SHOWCASE_JOB) or {}).get("conclusion") or "missing")
    return found


def decide(event: Event, key: str, runs: list[dict], jobs_of: Callable[[dict], list[dict]],
           trusted: bool = False, heads: tuple[str, ...] = ()) -> Decision:
    """Whether this run takes the suite's result from one of `runs`, the runs of `check` for the
    heads of this landing's pull requests (`heads`, the event's head first), as the API lists
    them; `jobs_of` reads a run's jobs."""
    if trusted:
        return Decision("trusted", "the integrator's record of this tree is trusted "
                                   "(scripts/ci_trust.py)")
    if event.name not in REUSE_EVENTS:
        return run_everything(f"a {event.name} {event.action}".rstrip() + " run checks its tree")
    if event.attempt > 1:
        return run_everything(f"attempt {event.attempt} is a re-run")
    return earlier_result(key, runs, jobs_of, heads or (event.head,), event.run_id)


def earlier_result(key: str, runs: list[dict], jobs_of: Callable[[dict], list[dict]],
                   heads: tuple[str, ...], own_run: str = "") -> Decision:
    """The newest result of the reuse key `key` among the completed `runs` of `heads` but
    `own_run`: reused, passed or failed, naming its run; else run, naming why. A cancelled newest
    run of the first head runs everything (a re-run of it runs everything anyway)."""
    named = ", ".join(head[:12] for head in heads)
    earlier = sorted((run for run in runs if str(run.get("id")) != own_run
                      and run.get("status") == "completed" and run.get("head_sha") in heads),
                     key=lambda run: int(run.get("id") or 0), reverse=True)
    if not earlier:
        return run_everything(f"no completed run of check for the head{'s' * (len(heads) > 1)} "
                              f"{named}")
    skipped, own_seen = [], False
    for run in earlier:
        url = str(run.get("html_url") or run.get("id"))
        own = run.get("head_sha") == heads[0]
        if run.get("conclusion") == "cancelled":
            if own and not own_seen:
                return run_everything(f"the previous run {url} was cancelled")
            skipped.append(f"{url} was cancelled")
            continue
        own_seen = own_seen or own
        jobs = jobs_of(run)
        if key_of(jobs) != key:
            skipped.append(f"{url} checked another tree or other Component kinds")
            continue
        found = results(jobs)
        failed = [part for part, conclusion in found.items() if conclusion == "failure"]
        if failed:
            return Decision("reused", f"the run {url} of this tree failed {', '.join(failed)}",
                            url, "failure")
        if all(conclusion == "success" for conclusion in found.values()):
            return Decision("reused", f"the run {url} of this tree passed "
                                      f"{', '.join(found)}", url, "success")
        skipped.append(f"{url} ran " + ", ".join(
            f"{part} {conclusion}" for part, conclusion in found.items() if conclusion != "success"))
    return run_everything(f"no earlier run of this tree for the head{'s' * (len(heads) > 1)} "
                          f"{named} carries the result ({'; '.join(skipped)})")


class Api(ci_trust.Api):
    """GitHub's REST API as ci_trust's door, with the reads the decision makes; tests replace it."""

    def workflow_runs(self, run_id: str, head: str) -> list[dict]:
        """The pull_request runs for `head` of the workflow `run_id` belongs to, of any status: with
        `head_sha`, GitHub's `status=completed` filter lists only some of the completed runs, so
        `decide` filters by status itself."""
        own = self.request("GET", f"actions/runs/{run_id}") or {}
        if not own.get("workflow_id"):
            raise ReuseError(f"the run {run_id} names no workflow")
        listed = self.request("GET", f"actions/workflows/{own['workflow_id']}/runs?head_sha="
                                     f"{urllib.parse.quote(head)}&event=pull_request&per_page={RUNS_READ}") or {}
        return list(listed.get("workflow_runs") or [])

    def pull_head(self, number: int) -> str:
        """The head commit of pull request `number`."""
        pull = self.request("GET", f"pulls/{number}") or {}
        return str((pull.get("head") or {}).get("sha") or "")

    def landed_pulls(self, sha: str) -> list[dict]:
        """The merged pull requests that landed `sha`: each one's head commit and description."""
        pulls = self.request("GET", f"commits/{sha}/pulls") or []
        return [{"head": str(pull["head"]["sha"]), "body": str(pull.get("body") or "")}
                for pull in pulls if isinstance(pull, dict) and pull.get("merged_at")
                and isinstance(pull.get("head"), dict) and pull["head"].get("sha")]

    def jobs(self, run: dict) -> list[dict]:
        listed = self.request("GET", f"actions/runs/{run['id']}/jobs?per_page=100") or {}
        return list(listed.get("jobs") or [])


def checked_key(root: Path, event: Event) -> tuple[str, str]:
    """This run's reuse key, and what it is of."""
    tree, kinds = ci_trust.tree(root), stated_kinds(event.body)
    of = f"tree {tree[:12]}, Component kinds " + ("unset" if kinds is None else repr(kinds))
    return reuse_key(tree, kinds), of


def reads_earlier_runs(event: Event) -> bool:
    return event.name in REUSE_EVENTS and event.attempt == 1


def landing_heads(event: Event, door: Api) -> tuple[str, ...]:
    """The heads whose runs may hold this tree's result: on a pull request its head and the head
    of the work pull request its landing description links; on a push the heads of the merged
    pull requests that landed the commit and of the work pull requests they link."""
    if event.name == "pull_request":
        pulls = [{"head": event.head, "body": event.body}]
    else:
        pulls = door.landed_pulls(event.head)
    heads = [pull["head"] for pull in pulls]
    for pull in pulls:
        number = work_pull(pull["body"])
        if number is not None:
            heads.append(door.pull_head(number))
    return tuple(dict.fromkeys(head for head in heads if head))


def runs_of(door: Api, run_id: str, heads: tuple[str, ...]) -> list[dict]:
    listed = {}
    for head in heads:
        for run in door.workflow_runs(run_id, head):
            listed.setdefault(run.get("id"), run)
    return list(listed.values())


def api_of(env: dict[str, str]) -> Api:
    missing = [name for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY") if not env.get(name)]
    if missing:
        raise ReuseError(f"decide runs in GitHub Actions: {', '.join(missing)} unset")
    return Api(env.get("GITHUB_API_URL") or "https://api.github.com", env["GITHUB_TOKEN"],
               env["GITHUB_REPOSITORY"])


def run_decide(root: Path, event: Event, trusted: bool, api: Api | None,
               env: dict[str, str]) -> Decision:
    """The decision step: trusted first, then the earlier runs, read only where they may count;
    a key or a read that fails runs everything, with a warning."""
    if trusted or not reads_earlier_runs(event):
        return decide(event, "", [], lambda _: [], trusted)
    try:
        key, of = checked_key(root, event)
        door = api or api_of(env)
        heads = landing_heads(event, door)
        if not heads:
            return run_everything(f"no merged pull request landed {event.head[:12]}")
        result = decide(event, key, runs_of(door, event.run_id, heads), door.jobs, heads=heads)
    except (ReuseError, ci_trust.TrustError) as error:
        result = run_everything(f"the earlier runs could not be read ({error})")
        print(f"::warning title=se reused check::{result.why}")
        return result
    if result.suite == "reused":
        print(f"::notice title=se reused check::{of}: {result.why}")
        ci_trust.summary(env, f"Reused: {of}: {result.why}")
    return result


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None,
         api: Api | None = None) -> int:
    parser = se_script.parser(prog="ci_reuse.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    key = commands.add_parser("key", help="write this run's reuse key (output key)")
    decision = commands.add_parser("decide", help="decide whether this run takes an earlier "
                                   "result (outputs suite, source, result, why)")
    for command in (key, decision):
        command.add_argument("--worktree", type=Path, default=Path("."),
                             help="the checkout (default .)")
    decision.add_argument("--trusted", choices=("true", "false", ""), default="false",
                          help="the trust job's lookup answer")
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    root = args.worktree.resolve()
    try:
        event = Event.of(env)
        if args.command == "key":
            try:
                value, of = checked_key(root, event)
            except (ReuseError, ci_trust.TrustError) as error:
                value, of = "none", f"no reuse key ({error})"
            ci_trust.output(env, key=value)
            print(f"Reuse key {value}: {of}")
            return 0
        result = run_decide(root, event, args.trusted == "true", api, env)
    except ReuseError as error:
        print(f"::error title=se reused check::{args.command}: {error}")
        return 2
    ci_trust.output(env, suite=result.suite, source=result.source, result=result.result,
                    why=result.why)
    if result.suite != "reused":
        print(f"{result.suite}: {result.why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
