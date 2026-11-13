#!/usr/bin/env python3
"""CI's trust in the integrator's run of the complete suite (README "Trusted landings").

`work_tickets.py integrate` runs the complete suite on the tree it lands. Where se.toml `[tests]`
sets `trust_integrator = true`, its landing plan dispatches the workflow `se-pass-record.yml`, whose
`record` step writes that pass on the landing head as the check run `se integrator pass`: the tree,
the test command, the suite's hash, the result, the time and the integrator session. CI's `lookup`
then passes at once where that record names exactly the tree it checked out, and otherwise lets the
full suite run. The safety net runs everything on a schedule and on every `full_every`-th landing;
after a full pass `full-pass` marks the commit, and after a failed full run `finding` names the
trusted records since the last full pass.

Who may write the record: a dispatch of `se-pass-record.yml` by the integrator's account
(`[tests] integrator`, default the repository's owner), whose run writes it as github-actions. Every
other record is not trusted. Standard library only: it runs with the runner's `python3` (3.11 or
later) and the Actions token; exit code 0 done, 2 a setup error (se.toml, git, the API)."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


RECORD_CHECK = "se integrator pass"  # the check run the record is
FULL_CHECK = "se full pass"  # the check run a full pass of CI leaves where trust is on
RECORD_WORKFLOW = "se-pass-record.yml"  # the one workflow whose runs may write the record
RECORD_FORMAT = 1  # a record of another format is stale
DEFAULT_FULL_EVERY = 10
FINDING_DEPTH = 50  # first-parent commits a finding walks back at most
RECORD_INPUTS = ("sha", "tree", "tested", "suite", "command", "seconds", "result", "time", "session")
SESSION_VARIABLES = ("SE_SESSION", "CLAUDE_CODE_SESSION_ID")
RECORD_APP = "github-actions"
RETRY_SECONDS = 5
SAFETY_NET_EVENTS = ("schedule", "workflow_dispatch")


class TrustError(Exception):
    """A setup error: se.toml, git or GitHub's API refused; exit code 2."""


@dataclass(frozen=True)
class Trust:
    """se.toml `[tests]`'s trust settings (README "Trusted landings")."""

    on: bool  # trust_integrator, default false
    full_every: int  # full_every: every N-th landing runs the full suite anyway
    integrator: str | None  # the account whose dispatch may write the record; None: the owner


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise TrustError(f"git {' '.join(arguments)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def project(root: Path, rev: str | None = None) -> dict:
    """se.toml of `root`'s working tree, or of commit `rev`; {} where it has none."""
    try:
        text = (git(root, "show", f"{rev}:se.toml") if rev
                else (root / "se.toml").read_text(encoding="utf-8"))
    except (OSError, TrustError):
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise TrustError(f"se.toml{' at ' + rev if rev else ''} in {root} is not TOML: {error}")


def trust_settings(root: Path, rev: str | None = None) -> Trust:
    """Read and check the trust settings of `[tests]`; refuse a malformed one, naming it."""
    tests = project(root, rev).get("tests") or {}
    where = f"[tests] in {root / 'se.toml'}"
    on = tests.get("trust_integrator", False)
    if not isinstance(on, bool):
        raise TrustError(f"{where}: trust_integrator must be true or false (default false)")
    every = tests.get("full_every", DEFAULT_FULL_EVERY)
    if isinstance(every, bool) or not isinstance(every, int) or every < 1:
        raise TrustError(f"{where}: full_every must be a whole number of landings, 1 or more "
                         f"(default {DEFAULT_FULL_EVERY}); 1 runs every landing in full")
    integrator = tests.get("integrator")
    if integrator is not None and not (isinstance(integrator, str) and integrator.strip()):
        raise TrustError(f"{where}: integrator must name the integrator's GitHub account")
    return Trust(on, every, integrator.strip() if integrator else None)


def suite_hash(root: Path, rev: str | None = None) -> str:
    """The hash of what decides the suite: se.toml `[tests]` and the se module it pins, with the
    record's format; a record naming another is stale."""
    data = project(root, rev)
    suite = {"format": RECORD_FORMAT, "tests": data.get("tests") or {},
             "se": (data.get("modules") or {}).get("se")}
    text = json.dumps(suite, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree(root: Path, rev: str = "HEAD") -> str:
    return git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}")


def test_command(root: Path, rev: str | None = None) -> str:
    """The suite's command and each suite beside it, as one line."""
    tests = project(root, rev).get("tests") or {}
    parts = [shlex.join(tests.get("command") or [])]
    for name, beside in sorted((tests.get("beside") or {}).items()):
        if isinstance(beside, dict):
            parts.append(f"{name}: {shlex.join(beside.get('command') or [])} "
                         f"in {beside.get('directory', '.')}")
    return "; ".join(parts)


def session(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return next((env[name] for name in SESSION_VARIABLES if env.get(name)), "unknown")


def record_inputs(root: Path, sha: str, tested: str, seconds: float | None,
                  now: datetime.datetime | None = None,
                  environ: dict[str, str] | None = None) -> dict[str, str]:
    """The inputs of the record's dispatch for the landing head `sha`, whose suite ran on commit
    `tested` (its parent, where the landing's release commit changed only version files)."""
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sha": sha, "tree": tree(root, sha), "tested": tree(root, tested),
            "suite": suite_hash(root, sha), "command": test_command(root, sha),
            "seconds": "" if seconds is None else f"{seconds:.1f}", "result": "passed",
            "time": stamp, "session": session(environ)}


def run_title(sha: str, tree_hash: str) -> str:
    """The run name `se-pass-record.yml` gives its run (its `run-name`), which ties the run to the
    commit and tree it recorded."""
    return f"se pass record {sha} tree {tree_hash}"


def record_of(check_run: dict) -> dict | None:
    try:
        record = json.loads(str((check_run.get("output") or {}).get("text") or ""))
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def judge(check_run: dict, run: dict | None, *, tree_hash: str, suite: str,
          integrator: str) -> tuple[bool, str]:
    """Whether CI may trust `check_run`, a record `se integrator pass`, for the checked-out tree
    `tree_hash` whose suite hashes to `suite`; `run` is the workflow run the record names. Why."""
    url = str(check_run.get("html_url") or check_run.get("id"))
    app = str((check_run.get("app") or {}).get("slug") or "")
    if app != RECORD_APP:
        return False, (f"the record {url} was written by {app or 'an unknown writer'}, not by a "
                       f"run of {RECORD_WORKFLOW} ({RECORD_APP})")
    record = record_of(check_run)
    if record is None:
        return False, f"the record {url} holds no record"
    if record.get("format") != RECORD_FORMAT:
        return False, (f"the record {url} is of format {record.get('format')}, this se reads "
                       f"{RECORD_FORMAT}: stale")
    if record.get("result") != "passed" or check_run.get("conclusion") != "success":
        return False, f"the record {url} records {record.get('result')}, not a pass"
    if run is None:
        return False, f"the record {url} names no workflow run of {RECORD_WORKFLOW}"
    path = str(run.get("path") or "").split("@")[0]
    if Path(path).as_posix() != f".github/workflows/{RECORD_WORKFLOW}" or \
            run.get("event") != "workflow_dispatch":
        return False, (f"the record {url} was written by {path or 'a run'} on "
                       f"{run.get('event')}, not by a dispatch of {RECORD_WORKFLOW}")
    actor = str((run.get("triggering_actor") or run.get("actor") or {}).get("login") or "")
    if actor.lower() != integrator.lower():
        return False, (f"the record {url} was dispatched by {actor or 'nobody known'}, not by the "
                       f"integrator {integrator}")
    sha, recorded = str(record.get("sha") or ""), str(record.get("tree") or "")
    if (run.get("display_title") != run_title(sha, recorded) or run.get("head_sha") != sha
            or check_run.get("head_sha") != sha):
        return False, f"the record {url} and its run {run.get('html_url')} name other commits"
    if recorded != tree_hash:
        return False, (f"the record {url} is of tree {recorded[:12]}, the landing's tree is "
                       f"{tree_hash[:12]}")
    if record.get("suite") != suite:
        return False, (f"the record {url} names suite {str(record.get('suite'))[:12]}, this tree's "
                       f"suite is {suite[:12]}: stale")
    return True, (f"the integrator's record {url}: tree {tree_hash[:12]} passed `{record.get('command')}`"
                  f" in {record.get('seconds') or '?'} s at {record.get('time')}, session "
                  f"{record.get('session')}")


class Api:
    """The one door to GitHub's REST API, with the Actions token; tests replace it."""

    def __init__(self, base: str, token: str, repository: str) -> None:
        self.base, self.token, self.repository = base.rstrip("/"), token, repository

    def request(self, method: str, path: str, data: dict | None = None) -> object:
        body = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/repos/{self.repository}/{path}", data=body, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     **({"Content-Type": "application/json"} if body else {})})
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    text = response.read().decode("utf-8")
                    return json.loads(text) if text.strip() else {}
            except urllib.error.HTTPError as error:
                if error.code == 404 and method == "GET":
                    return None
                if error.code >= 500 and attempt == 1:
                    time.sleep(RETRY_SECONDS)
                    continue
                raise TrustError(f"{method} {path}: HTTP {error.code}") from error
            except urllib.error.URLError as error:
                raise TrustError(f"{method} {path}: {error.reason}") from error
        raise AssertionError("unreachable: the second attempt returns or raises")

    def check_runs(self, sha: str, name: str) -> list[dict]:
        """The check runs `name` on commit `sha`, newest first."""
        found = self.request("GET", f"commits/{sha}/check-runs?check_name="
                                    f"{urllib.parse.quote(name)}&per_page=100") or {}
        runs = [run for run in found.get("check_runs") or [] if run.get("name") == name]
        return sorted(runs, key=lambda run: int(run.get("id") or 0), reverse=True)

    def run(self, run_id: str) -> dict | None:
        return self.request("GET", f"actions/runs/{run_id}") if str(run_id).isdigit() else None

    def pull_heads(self, sha: str) -> list[str]:
        """The head commits of the merged pull requests that landed `sha`."""
        pulls = self.request("GET", f"commits/{sha}/pulls") or []
        return [str(pull["head"]["sha"]) for pull in pulls
                if isinstance(pull, dict) and pull.get("merged_at") and pull.get("head")]

    def create_check_run(self, data: dict) -> dict:
        return self.request("POST", "check-runs", data) or {}


@dataclass(frozen=True)
class Run:
    """The CI run asking: its event, the commit checked out and, on a pull request, its head
    commit and base branch."""

    event: str
    sha: str
    head: str | None = None
    base: str | None = None
    owner: str = ""
    triggering_actor: str = ""
    run_url: str = ""
    inputs: dict | None = None

    @classmethod
    def of(cls, environ: dict[str, str]) -> "Run":
        event: dict = {}
        if environ.get("GITHUB_EVENT_PATH"):
            try:
                event = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise TrustError(f"the event payload {environ['GITHUB_EVENT_PATH']}: {error}")
        pull = event.get("pull_request") or {}
        server, repo, run_id = (environ.get("GITHUB_SERVER_URL", "https://github.com"),
                                environ.get("GITHUB_REPOSITORY", ""), environ.get("GITHUB_RUN_ID", ""))
        return cls(environ.get("GITHUB_EVENT_NAME", ""), environ.get("GITHUB_SHA", ""),
                   (pull.get("head") or {}).get("sha"), (pull.get("base") or {}).get("ref"),
                   environ.get("GITHUB_REPOSITORY_OWNER", repo.split("/")[0]),
                   environ.get("GITHUB_TRIGGERING_ACTOR", environ.get("GITHUB_ACTOR", "")),
                   f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
                   event.get("inputs") if isinstance(event.get("inputs"), dict) else None)

    @property
    def main_ref(self) -> str:
        """The first-parent line the landing joins: the base branch's, or the commit's own."""
        return f"refs/remotes/origin/{self.base}" if self.base else "HEAD"


def integrator_of(trust: Trust, run: Run) -> str:
    return trust.integrator or run.owner


def landing_number(root: Path, run: Run) -> int:
    """Which landing on the main line this run checks: the first-parent count of the commit, or
    of the base branch plus one for a pull request."""
    count = int(git(root, "rev-list", "--count", "--first-parent", run.main_ref))
    return count + 1 if run.base else count


@dataclass(frozen=True)
class Decision:
    trusted: bool
    why: str
    record: str = ""


def decide(root: Path, run: Run, api: Api) -> Decision:
    """Whether this CI run may pass on the integrator's record instead of the full suite."""
    trust = trust_settings(root, "HEAD")
    if not trust.on:
        return Decision(False, "se.toml [tests] trust_integrator is off: the full suite runs")
    if run.event in SAFETY_NET_EVENTS:
        return Decision(False, f"the safety net: a {run.event} run runs the full suite")
    number = landing_number(root, run)
    if number % trust.full_every == 0:
        return Decision(False, f"landing {number} is a multiple of se.toml [tests] full_every "
                               f"{trust.full_every}: the safety net runs the full suite")
    heads = [run.head] if run.head else api.pull_heads(run.sha)
    if not heads:
        return Decision(False, f"no merged pull request landed {run.sha[:12]}, so no record "
                               "names it: the full suite runs")
    checked, suite, integrator = tree(root), suite_hash(root, "HEAD"), integrator_of(trust, run)
    reasons = []
    for head in heads:
        records = api.check_runs(head, RECORD_CHECK)
        if not records:
            reasons.append(f"no record {RECORD_CHECK} on {head[:12]}")
        for check_run in records:
            trusted, why = judge(check_run, api.run(str(check_run.get("external_id") or "")),
                                 tree_hash=checked, suite=suite, integrator=integrator)
            if trusted:
                return Decision(True, why, str(check_run.get("html_url") or ""))
            reasons.append(why)
    return Decision(False, "; ".join(reasons) + ": the full suite runs")


def output(environ: dict[str, str], **values: str) -> None:
    target = environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in values.items())


def summary(environ: dict[str, str], text: str) -> None:
    target = environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def run_lookup(root: Path, run: Run, api: Api, environ: dict[str, str]) -> int:
    trust_settings(root, "HEAD")  # a malformed setting fails the step; a read below runs in full
    try:
        decision = decide(root, run, api)
    except TrustError as error:
        decision = Decision(False, f"the record could not be read ({error}): the full suite runs")
        print(f"::warning title=se trusted landing::{decision.why}")
    output(environ, trusted="true" if decision.trusted else "false", record=decision.record)
    if decision.trusted:
        print(f"::notice title=se trusted landing::trusted, so the full suite does not run: "
              f"{decision.why}")
        summary(environ, f"Trusted landing: {decision.why}")
    else:
        print(f"Full suite: {decision.why}")
    return 0


def run_record(root: Path, run: Run, api: Api) -> int:
    """`se-pass-record.yml`'s step: write the record its dispatch names, refusing one the
    checked-out commit does not bear out or a dispatch by another than the integrator."""
    inputs = run.inputs or {}
    missing = [name for name in RECORD_INPUTS if name not in inputs]
    if run.event != "workflow_dispatch" or missing:
        raise TrustError(f"record runs in a dispatch of {RECORD_WORKFLOW} with the inputs "
                         f"{', '.join(RECORD_INPUTS)}; missing {', '.join(missing) or 'the dispatch'}")
    trust = trust_settings(root, "HEAD")
    integrator = integrator_of(trust, run)
    if run.triggering_actor.lower() != integrator.lower():
        raise TrustError(f"{run.triggering_actor or 'nobody known'} dispatched this record; only "
                         f"the integrator {integrator} may (se.toml [tests] integrator)")
    head = git(root, "rev-parse", "HEAD")
    checks = {"sha": head, "tree": tree(root), "suite": suite_hash(root, "HEAD")}
    wrong = [f"{name} {str(inputs[name])[:12]} is not the checkout's {value[:12]}"
             for name, value in checks.items() if inputs[name] != value]
    if wrong:
        raise TrustError("the record does not match the commit it is for: " + "; ".join(wrong))
    passed = inputs["result"] == "passed"
    record = {"format": RECORD_FORMAT, **{name: inputs[name] for name in RECORD_INPUTS},
              "run": run.run_url}
    created = api.create_check_run({
        "name": RECORD_CHECK, "head_sha": head, "status": "completed",
        "conclusion": "success" if passed else "failure",
        "external_id": run.run_url.rsplit("/", 1)[-1], "details_url": run.run_url,
        "output": {"title": f"Integrator {inputs['result']} on tree {checks['tree'][:12]}",
                   "summary": (f"The integrator's suite {inputs['result']} on tree "
                               f"{inputs['tested']} at {inputs['time']} in {inputs['seconds']} s, "
                               f"session {inputs['session']}: `{inputs['command']}`; recorded for "
                               f"tree {checks['tree']} (README \"Trusted landings\")."),
                   "text": json.dumps(record, indent=1, sort_keys=True)}})
    print(f"::notice title=se trusted landing::recorded {inputs['result']} for tree "
          f"{checks['tree'][:12]} on {head[:12]}: {created.get('html_url', '')}")
    return 0


def run_full_pass(root: Path, run: Run, api: Api) -> int:
    """After CI's full suite passed: mark the commit, where trust is on, so a later finding knows
    where the last full pass was."""
    if not trust_settings(root, "HEAD").on:
        print("Full pass not marked: se.toml [tests] trust_integrator is off")
        return 0
    sha = run.head or run.sha
    created = api.create_check_run({
        "name": FULL_CHECK, "head_sha": sha, "status": "completed", "conclusion": "success",
        "details_url": run.run_url,
        "output": {"title": f"Full suite passed on tree {tree(root)[:12]}",
                   "summary": f"CI ran the full suite on tree {tree(root)} and it passed: {run.run_url}"}})
    print(f"Full pass marked on {sha[:12]}: {created.get('html_url', '')}")
    return 0


def passed_in_full(api: Api, shas: list[str]) -> bool:
    return any(check.get("conclusion") == "success" for sha in shas
               for check in api.check_runs(sha, FULL_CHECK))


def run_finding(root: Path, run: Run, api: Api, environ: dict[str, str]) -> int:
    """After CI's full suite failed: the finding, naming each trusted record that let a change
    through since the last full pass."""
    trust = trust_settings(root, "HEAD")
    if not trust.on:
        return 0
    lines = []
    if run.head:  # this pull request's own record, which the full run did not take
        lines += [f"this landing ({run.head[:12]}): {check.get('html_url')}"
                  for check in api.check_runs(run.head, RECORD_CHECK)[:1]]
    commits = git(root, "rev-list", "--first-parent", f"--max-count={FINDING_DEPTH}",
                  run.main_ref).split()
    for commit in commits:
        shas = [commit, *api.pull_heads(commit)]
        if passed_in_full(api, shas):
            break
        for sha in shas:
            for check in api.check_runs(sha, RECORD_CHECK)[:1]:
                record = record_of(check) or {}
                lines.append(f"{commit[:12]} landed on the record {check.get('html_url')} (tree "
                             f"{str(record.get('tree'))[:12]}, {record.get('time')}, session "
                             f"{record.get('session')})")
    named = "; ".join(lines) if lines else "no trusted record since the last full pass"
    text = (f"safety net: the full suite failed on {run.sha[:12]}; the trusted records that let "
            f"changes through since the last full pass: {named}")
    print(f"::error title=se trusted landing::{text}")
    summary(environ, text)
    return 0


COMMANDS = {"lookup": "decide whether this CI run passes on the integrator's record (outputs "
                      "trusted and record)",
            "record": "in se-pass-record.yml: write the record its dispatch names",
            "full-pass": "after a passing full suite: mark the commit as fully passed",
            "finding": "after a failing full suite: name the trusted records since the last full pass"}


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None,
         api: Api | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in COMMANDS.items():
        commands.add_parser(name, help=text).add_argument(
            "--worktree", type=Path, default=Path("."), help="the project's checkout (default .)")
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    root = args.worktree.resolve()
    try:
        run = Run.of(env)
        if api is None:
            missing = [name for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY") if not env.get(name)]
            if missing:
                raise TrustError(f"{args.command} runs in GitHub Actions: {', '.join(missing)} unset")
            api = Api(env.get("GITHUB_API_URL") or "https://api.github.com", env["GITHUB_TOKEN"],
                      env["GITHUB_REPOSITORY"])
        if args.command == "lookup":
            return run_lookup(root, run, api, env)
        if args.command == "record":
            return run_record(root, run, api)
        if args.command == "full-pass":
            return run_full_pass(root, run, api)
        return run_finding(root, run, api, env)
    except TrustError as error:
        print(f"::error title=se trusted landing::{args.command}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
