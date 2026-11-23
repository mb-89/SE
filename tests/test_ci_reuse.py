"""A pull request's edit or label change reuses the suite's result of an earlier run of the same tree
(scripts/ci_reuse.py, README "Edits reuse the suite"): which earlier run counts, that a failed one
keeps `check` failed, when everything runs, and the workflow steps that act on the decision.
GitHub is a fake door, or for the end-to-end decision a local HTTP server; the workflow is read as
text and its decision steps run as its runner runs them."""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import git_door
import pytest
import fake_git

import ci_reuse  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / ".github" / "workflows" / "check.yml"
KEY = "0123456789abcdef"
HEAD = "a" * 40
REPORT = ("Fixes https://github.com/alice/project/issues/7\n\n**Component kinds:** {kinds}\n\n"
          "<!-- se:field-report -->\n## Summary\n\nreport\n")

pytestmark = pytest.mark.usefixtures("fake_git_door")  # git is the fake behind the door (tests/fake_git.py)


def edit(action: str = "edited", attempt: int = 1, event: str = "pull_request") -> ci_reuse.Event:
    """This run: the pull request's event, run 9000, on HEAD."""
    return ci_reuse.Event(event, action, "9000", attempt, HEAD, "")


def earlier(run_id: int, *, key: str = KEY, suite: str = "success", vet: str = "success",
            legs: str = "success", conclusion: str | None = None, head: str = HEAD,
            status: str = "completed") -> tuple[dict, list[dict]]:
    """An earlier run of check, as the runs API lists it, and its jobs as the jobs API answers:
    the trust job's decision step named with its reuse key, the check job's Go and suite steps and
    the kern-platforms leg; `skipped` everywhere is a run that reused or stopped before them."""
    failed = "failure" in (suite, vet, legs)
    run = {"id": run_id, "status": status, "head_sha": head, "event": "pull_request",
           "conclusion": conclusion or ("failure" if failed else "success"),
           "html_url": f"https://github.com/alice/project/actions/runs/{run_id}"}
    jobs = [{"name": "trust", "conclusion": "success", "steps": [
                {"name": "Set up job", "conclusion": "success"},
                {"name": f"{ci_reuse.DECIDE_STEP} (reuse key {key})", "conclusion": "success"}]},
            {"name": "kern-platforms (windows-2025)", "conclusion": legs},
            {"name": "check", "conclusion": "failure" if failed else "success", "steps": [
                {"name": "The pull request's field report follows the template",
                 "conclusion": "success"},
                {"name": "SE's Go components vet", "conclusion": vet},
                {"name": "The complete suite and the suites beside it, within their budgets",
                 "conclusion": suite}]}]
    return run, jobs


def decide(*runs: tuple[dict, list[dict]], event: ci_reuse.Event | None = None,
           trusted: bool = False) -> ci_reuse.Decision:
    jobs = {run["id"]: listed for run, listed in runs}
    return ci_reuse.decide(event or edit(), KEY, [run for run, _ in runs],
                           lambda run: jobs[run["id"]], trusted)


# Acceptance: an edit without a new commit takes the earlier result and names its run.


@pytest.mark.parametrize("action", ci_reuse.REUSE_ACTIONS)
def test_an_edit_or_label_change_takes_the_passed_result_of_the_tree_and_names_its_run(
        action: str) -> None:
    decision = decide(earlier(100), event=edit(action))
    assert (decision.suite, decision.result) == ("reused", "success")
    assert decision.source == "https://github.com/alice/project/actions/runs/100"
    assert decision.why == ("the run https://github.com/alice/project/actions/runs/100 of this "
                            "tree passed the Go checks, the suite, kern-platforms (windows-2025)")


def test_an_edit_after_a_reusing_run_takes_the_result_that_run_took() -> None:
    reused = earlier(101, suite="skipped", vet="skipped", legs="skipped", conclusion="success")
    decision = decide(earlier(100), reused)
    assert (decision.suite, decision.source) == (
        "reused", "https://github.com/alice/project/actions/runs/100")


# Acceptance: after a failed suite, an edit leaves check failed.


@pytest.mark.parametrize(("part", "failed"), [
    ({"suite": "failure"}, "the suite"),
    ({"vet": "failure", "suite": "skipped"}, "the Go checks"),
    ({"legs": "failure"}, "kern-platforms (windows-2025)"),
    # kern-platforms runs beside check: a leg that failed in a run whose report failed counts too.
    ({"legs": "failure", "vet": "skipped", "suite": "skipped"}, "kern-platforms (windows-2025)"),
])
def test_a_failed_earlier_result_keeps_check_failed_naming_its_run(part: dict, failed: str) -> None:
    decision = decide(earlier(100, **part))
    assert (decision.suite, decision.result) == ("reused", "failure")
    assert decision.why == (f"the run https://github.com/alice/project/actions/runs/100 of this "
                            f"tree failed {failed}")


def test_a_later_reuse_does_not_hide_an_earlier_failure() -> None:
    reused = earlier(101, suite="skipped", vet="skipped", legs="skipped", conclusion="failure")
    assert decide(earlier(100, suite="failure"), reused).result == "failure"


# Where nothing may be reused, everything runs, as today.


@pytest.mark.parametrize(("runs", "named"), [
    ((), f"no completed run of check for the head {HEAD[:12]}"),
    ((earlier(100, status="in_progress"),), "no completed run of check"),
    ((earlier(100, head="b" * 40),), "no completed run of check"),
    ((earlier(100), earlier(101, conclusion="cancelled", suite="cancelled")),
     "the previous run https://github.com/alice/project/actions/runs/101 was cancelled"),
    ((earlier(100, key="fedcba9876543210"),), "checked another tree or other Component kinds"),
    ((earlier(100, suite="skipped", vet="skipped", legs="success", conclusion="failure"),),
     "runs/100 ran the Go checks skipped, the suite skipped"),
])
def test_without_an_earlier_result_of_the_tree_everything_runs(runs, named) -> None:
    decision = decide(*runs)
    assert decision.suite == "run" and decision.source == ""
    assert named in decision.why
    assert decision.why.endswith(": the suite, the Go checks and kern-platforms run")


def test_the_run_itself_is_never_its_own_earlier_run() -> None:
    own, jobs = earlier(9000)
    assert decide((own, jobs)).suite == "run"


@pytest.mark.parametrize(("event", "named"), [
    (edit("opened"), "a pull_request opened run checks its tree"),
    (edit("synchronize"), "a pull_request synchronize run checks its tree"),
    (edit("reopened"), "a pull_request reopened run checks its tree"),
    (edit("", event="push"), "a push run checks its tree"),
    (edit("", event="schedule"), "a schedule run checks its tree"),
    (edit("edited", attempt=2), "attempt 2 is a re-run"),
])
def test_every_other_event_and_a_re_run_run_everything(event, named) -> None:
    decision = decide(earlier(100), event=event)
    assert decision.suite == "run" and named in decision.why


def test_a_trusted_record_answers_before_any_earlier_run() -> None:
    assert decide(earlier(100, suite="failure"), trusted=True).suite == "trusted"


# The reuse key: the tree checked out and the Component kinds the suite's release guard reads.


@pytest.mark.parametrize(("body", "kinds"), [
    (REPORT.format(kinds="se patch, app minor"), "app=minor,se=patch"),
    (REPORT.format(kinds=""), ""),
    ("Refs https://github.com/alice/project/issues/7\n\n<!-- se:field-report-in 12 -->\n", None),
    ("Switch the default agent\n", None),  # no field report: the step sets no kinds
])
def test_the_kinds_are_the_ones_checks_field_report_step_gives_the_suite(body, kinds) -> None:
    assert ci_reuse.stated_kinds(body) == kinds


def test_another_tree_or_other_kinds_is_another_key() -> None:
    keys = {ci_reuse.reuse_key(tree, kinds) for tree in ("1" * 40, "2" * 40)
            for kinds in (None, "", "se=patch")}
    assert len(keys) == 6 and all(re.fullmatch(r"[0-9a-f]{16}", key) for key in keys)


def test_unreadable_kinds_are_no_key() -> None:
    with pytest.raises(ci_reuse.ReuseError, match="Component kinds"):
        ci_reuse.stated_kinds(REPORT.format(kinds="se huge"))


# The decision end to end: ci_reuse.py key and decide through the real door, against a local GitHub.


class LocalGitHub(http.server.BaseHTTPRequestHandler):
    answers: dict[str, object] = {}
    asked: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        self.asked.append(self.path)
        path = self.path.split("?")[0]
        if path not in self.answers:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.answers[path]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = fake_git.init(tmp_path / "project", "-b", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    assert git_door.run("add", "-A", root=root).returncode == 0
    assert git_door.run("-c", "user.name=mb", "-c", "user.email=mb", "commit", "-q", "-m", "a",
                        root=root).returncode == 0
    return root


def step_env(tmp_path: Path, action: str, port: int, name: str) -> dict[str, str]:
    """The environment of the trust job's step `name` as the runner gives it."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"action": action, "pull_request": {
        "head": {"sha": HEAD}, "body": REPORT.format(kinds="se patch")}}), encoding="utf-8")
    return {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event),
            "GITHUB_RUN_ID": "9000", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "alice/project",
            "GITHUB_TOKEN": "token", "GITHUB_OUTPUT": str(tmp_path / f"{name}.out"),
            "GITHUB_API_URL": f"http://127.0.0.1:{port}"}


def outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


@pytest.mark.parametrize("suite", ["success", "failure"])
def test_the_trust_jobs_steps_decide_through_the_rest_api(checkout: Path, tmp_path: Path, capsys,
                                                         suite: str) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LocalGitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        env = step_env(tmp_path, "edited", port, "key")
        assert ci_reuse.main(["key", "--worktree", str(checkout)], env) == 0
        key = outputs(env)["key"]
        assert re.fullmatch(r"[0-9a-f]{16}", key)
        run, jobs = earlier(100, key=key, suite=suite)
        LocalGitHub.answers = {
            "/repos/alice/project/actions/runs/9000": {"id": 9000, "workflow_id": 77},
            "/repos/alice/project/actions/workflows/77/runs": {"workflow_runs": [run]},
            "/repos/alice/project/actions/runs/100/jobs": {"jobs": jobs}}
        LocalGitHub.asked = []
        env = step_env(tmp_path, "edited", port, "decide")
        assert ci_reuse.main(["decide", "--worktree", str(checkout), "--trusted", "false"], env) == 0
    finally:
        server.shutdown()
    answered = outputs(env)
    assert (answered["suite"], answered["result"]) == ("reused", suite)
    assert answered["source"] == "https://github.com/alice/project/actions/runs/100"
    # No status filter: on 22 Nov GitHub's `status=completed` with `head_sha` listed one of the
    # head's two completed runs, and the edit ran everything; the decision filters by status itself.
    assert LocalGitHub.asked[1] == (f"/repos/alice/project/actions/workflows/77/runs?head_sha={HEAD}"
                                    "&event=pull_request&per_page=100")
    assert "::notice title=se reused check::tree " in capsys.readouterr().out


def test_the_decision_runs_everything_where_github_cannot_be_read(checkout: Path, tmp_path: Path,
                                                                 capsys) -> None:
    env = step_env(tmp_path, "labeled", 9, "decide")  # nothing listens on port 9
    assert ci_reuse.main(["decide", "--worktree", str(checkout)], env) == 0
    assert outputs(env)["suite"] == "run"
    assert "::warning title=se reused check::the earlier runs could not be read" in \
        capsys.readouterr().out


def test_a_synchronize_run_reads_no_earlier_run(checkout: Path, tmp_path: Path) -> None:
    env = step_env(tmp_path, "synchronize", 9, "decide")  # a read would fail: nothing listens
    assert ci_reuse.main(["decide", "--worktree", str(checkout)], env) == 0
    assert outputs(env)["suite"] == "run"


# The workflow: the trust job decides, every gate reads its answer, check acts on a reused one.


def jobs_of_workflow() -> dict[str, str]:
    workflow = CHECK.read_text(encoding="utf-8")
    return dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow.split("\njobs:\n")[1]))


def test_the_trust_job_names_its_decision_step_with_the_key_a_later_run_reads() -> None:
    trust = jobs_of_workflow()["trust"]
    assert "run: python3 scripts/ci_reuse.py key" in trust
    assert (f"name: {ci_reuse.DECIDE_STEP} (reuse key ${{{{ steps.key.outputs.key }}}})"
            in trust)
    assert 'run: python3 scripts/ci_reuse.py decide --trusted "$TRUSTED"' in trust
    assert "TRUSTED: ${{ steps.lookup.outputs.trusted }}" in trust
    for name in ("suite", "source", "result", "why"):
        assert f"{name}: ${{{{ steps.reuse.outputs.{name} }}}}" in trust
    check = jobs_of_workflow()["check"]
    # The names the decision reads in an earlier run's jobs.
    assert f"- name: {ci_reuse.SUITE_STEP}" in check and f"- name: {ci_reuse.VET_STEP}" in check
    assert "\n  kern-platforms:\n" in CHECK.read_text(encoding="utf-8")


def test_the_suite_the_go_checks_and_the_legs_run_only_where_the_decision_says_run() -> None:
    jobs = jobs_of_workflow()
    for gated in ("kern-platforms", "kern-platforms-queue"):
        assert "needs: trust\n    if: needs.trust.outputs.suite == 'run'" in jobs[gated], gated
    for step in ("SE's Go components vet", "Install obs's adapter component obs-html",
                 "The complete suite and the suites beside it", "Keep the suite's file seconds",
                 "Keep the suite's test reports", "Mark the full pass", "Name the trusted records"):
        block = re.search(rf"(?ms)- name: {re.escape(step)}.*?\n(?=      - |\Z)", jobs["check"])[0]
        assert "needs.trust.outputs.suite == 'run'" in block, step
    assert "needs.trust.outputs.trusted" not in CHECK.read_text(encoding="utf-8")


def step_script(name: str) -> str:
    """The shell of the check job's step `name`, its `run: |` block."""
    lines = CHECK.read_text(encoding="utf-8").splitlines()
    named = lines.index(f"      - name: {name}")
    start = next(index for index in range(named, len(lines)) if lines[index].strip() == "run: |")
    block = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block)


def run_step(name: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-e", "-c", step_script(name)], env={**os.environ, **env},
                          capture_output=True, text=True, check=False)


REUSED_STEP = "The suite, the Go checks and kern-platforms of an earlier run of this tree"
PLATFORM_STEP = "SE's start, hook and setup scripts passed on Windows"
SOURCE = "https://github.com/alice/project/actions/runs/100"


def test_a_reused_pass_passes_naming_the_run_it_took() -> None:
    result = run_step(REUSED_STEP, SOURCE=SOURCE, RESULT="success", WHY="the run passed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("::notice title=se reused check::")
    assert SOURCE in result.stdout
    block = re.search(rf"(?ms)- name: {re.escape(REUSED_STEP)}.*?\n(?=      - )",
                      jobs_of_workflow()["check"])[0]
    assert "if: needs.trust.outputs.suite == 'reused'" in block
    platforms = run_step(PLATFORM_STEP, SUITE="reused", PLATFORMS="skipped")
    assert platforms.returncode == 0 and "the earlier run's" in platforms.stdout


def test_a_reused_failure_fails_check_naming_the_run_and_the_remedy() -> None:
    result = run_step(REUSED_STEP, SOURCE=SOURCE, RESULT="failure", WHY="the run failed the suite")
    assert result.returncode == 1
    assert result.stdout.startswith("::error title=se reused check::the run failed the suite "
                                    f"({SOURCE})")
    assert "re-run all jobs of this run, which runs everything" in result.stdout


@pytest.mark.parametrize(("suite", "platforms", "passes"), [
    ("run", "success", True), ("run", "failure", False), ("run", "skipped", False),
    ("trusted", "skipped", True), ("reused", "skipped", True), ("", "skipped", False),
])
def test_the_platform_step_passes_only_on_run_legs_or_an_earlier_answer(suite, platforms,
                                                                        passes) -> None:
    assert (run_step(PLATFORM_STEP, SUITE=suite, PLATFORMS=platforms).returncode == 0) is passes
