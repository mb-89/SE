"""CI's trust in the integrator's run (scripts/ci_trust.py, README "Trusted landings"): who may write
the record, which record is trusted, when the full suite runs anyway, and the safety net's
bookkeeping. GitHub is a fake door, or for the end-to-end lookup a local HTTP server; the workflows
that call it are read as text."""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import git_door
import pytest
import quiet_git

import ci_trust  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TRUSTED = '[tests]\ncommand = ["uv", "run", "pytest", "-q"]\ntrust_integrator = true\nfull_every = 5\n'
OWNER = "alice"


IDENTITY = ("-c", "user.name=mb", "-c", "user.email=mb")  # a runner has no git identity
pytestmark = pytest.mark.usefixtures("fake_git_door")  # git is the fake behind the door (tests/fake_git.py)


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, f"git {' '.join(arguments)}: {result.stderr.strip()}"
    return result.stdout.strip()


def commit(root: Path, files: dict[str, str], message: str = "change") -> str:
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, *IDENTITY, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A project with trust on and one landing on main."""
    root = quiet_git.init(tmp_path / "project", "-b", "main")
    commit(root, {"se.toml": TRUSTED, "a.txt": "a\n"}, "first landing")
    return root


class FakeApi:
    """GitHub as ci_trust's door sees it: check runs per commit, workflow runs, the pull requests
    that landed a commit; what it was asked to create."""

    def __init__(self) -> None:
        self.checks: dict[str, list[dict]] = {}
        self.runs: dict[str, dict] = {}
        self.pulls: dict[str, list[str]] = {}
        self.created: list[dict] = []

    def check_runs(self, sha: str, name: str) -> list[dict]:
        return [check for check in reversed(self.checks.get(sha, [])) if check["name"] == name]

    def run(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def pull_heads(self, sha: str) -> list[str]:
        return self.pulls.get(sha, [])

    def create_check_run(self, data: dict) -> dict:
        self.created.append(data)
        return {"html_url": f"https://github.com/alice/project/runs/{len(self.created)}"}


def record(api: FakeApi, root: Path, sha: str, *, run_id: str = "900", actor: str = OWNER,
           app: str = "github-actions", tree: str | None = None, suite: str | None = None,
           result: str = "passed", path: str = ".github/workflows/se-pass-record.yml",
           event: str = "workflow_dispatch", title_sha: str | None = None) -> dict:
    """The record se-pass-record.yml writes on `sha`, and its run, as GitHub answers them; each
    keyword makes one part of it another than the honest one."""
    recorded_tree = tree or ci_trust.tree(root, sha)
    data = {"format": ci_trust.RECORD_FORMAT, "sha": sha, "tree": recorded_tree,
            "tested": recorded_tree, "suite": suite or ci_trust.suite_hash(root, sha),
            "command": "uv run pytest -q", "seconds": "41.0", "result": result,
            "time": "2026-11-13T18:00:00Z", "session": "session_integrator",
            "run": f"https://github.com/alice/project/actions/runs/{run_id}"}
    check = {"id": int(run_id), "name": ci_trust.RECORD_CHECK, "head_sha": sha,
             "app": {"slug": app}, "conclusion": "success" if result == "passed" else "failure",
             "external_id": run_id, "html_url": f"https://github.com/alice/project/runs/{run_id}",
             "output": {"text": json.dumps(data)}}
    api.checks.setdefault(sha, []).append(check)
    api.runs[run_id] = {"id": int(run_id), "path": path, "event": event, "head_sha": sha,
                        "display_title": ci_trust.run_title(title_sha or sha, recorded_tree),
                        "triggering_actor": {"login": actor}, "conclusion": "success",
                        "html_url": data["run"]}
    return check


def pull_request(root: Path, head: str) -> ci_trust.Run:
    """A landing pull request's check run: its merge commit checked out (here the head itself, on
    an unmoved main), its head and base."""
    return ci_trust.Run("pull_request", git(root, "rev-parse", "HEAD"), head, "main", OWNER)


def landing(root: Path, name: str = "b.txt") -> str:
    """A landing branch off main, its head; origin/main is main, as a pull request's checkout
    fetches it."""
    git(root, "update-ref", "refs/remotes/origin/main", "main")
    git(root, "switch", "-q", "-c", f"land/{name}")
    return commit(root, {name: f"{name}\n"}, f"land {name}")


# The trust boundary: what is trusted and what is not.


def test_a_record_of_exactly_the_tree_by_the_integrators_dispatch_is_trusted(repo: Path) -> None:
    head, api = landing(repo), FakeApi()
    record(api, repo, head)

    decision = ci_trust.decide(repo, pull_request(repo, head), api)

    assert decision.trusted, decision.why
    assert decision.record == "https://github.com/alice/project/runs/900"
    assert decision.why == (
        f"the integrator's record https://github.com/alice/project/runs/900: tree "
        f"{ci_trust.tree(repo)[:12]} passed `uv run pytest -q` in 41.0 s at 2026-11-13T18:00:00Z, "
        "session session_integrator")


@pytest.mark.parametrize("forged, why", [
    ({"tree": "1" * 40}, r"is of tree 111111111111, the landing's tree is [0-9a-f]{12}"),
    ({"suite": "2" * 64}, r"names suite 222222222222, this tree's suite is [0-9a-f]{12}: stale"),
    ({"actor": "mallory"}, r"was dispatched by mallory, not by the integrator alice"),
    ({"app": "some-app"}, r"was written by some-app, not by a run of se-pass-record.yml"),
    ({"path": ".github/workflows/other.yml"}, r"was written by .github/workflows/other.yml on "
                                              r"workflow_dispatch, not by a dispatch"),
    ({"event": "push"}, r"on push, not by a dispatch of se-pass-record.yml"),
    ({"result": "failed"}, r"records failed, not a pass"),
    ({"title_sha": "3" * 40}, r"and its run .* name other commits"),
])
def test_a_record_for_another_tree_suite_writer_or_result_is_not_trusted(
        repo: Path, forged: dict, why: str) -> None:
    head, api = landing(repo), FakeApi()
    record(api, repo, head, **forged)

    decision = ci_trust.decide(repo, pull_request(repo, head), api)

    assert not decision.trusted
    assert re.search(why, decision.why), decision.why
    assert decision.why.endswith(": the full suite runs")


def test_a_record_of_the_head_is_not_trusted_for_a_merge_onto_a_moved_main(repo: Path) -> None:
    head, api = landing(repo), FakeApi()
    record(api, repo, head)
    git(repo, "switch", "-q", "main")
    moved = commit(repo, {"c.txt": "c\n"}, "main moved")
    git(repo, "update-ref", "refs/remotes/origin/main", moved)
    git(repo, *IDENTITY, "merge", "-q", "--no-ff", "-m", "merge", head)  # the merge commit check checks out

    decision = ci_trust.decide(repo, pull_request(repo, head), api)

    assert not decision.trusted and "is of tree" in decision.why


def test_a_record_of_a_stale_format_is_not_trusted(repo: Path) -> None:
    head, api = landing(repo), FakeApi()
    check = record(api, repo, head)
    text = json.loads(check["output"]["text"])
    check["output"]["text"] = json.dumps({**text, "format": 0})

    decision = ci_trust.decide(repo, pull_request(repo, head), api)

    assert not decision.trusted and "is of format 0, this se reads 1: stale" in decision.why


def test_the_suite_hash_follows_the_tests_table_and_the_se_pin(repo: Path) -> None:
    before = ci_trust.suite_hash(repo, "HEAD")
    commit(repo, {"a.txt": "other\n"})
    assert ci_trust.suite_hash(repo, "HEAD") == before  # code changes the tree, not the suite
    commit(repo, {"se.toml": TRUSTED.replace('"-q"', '"-x"')})
    changed = ci_trust.suite_hash(repo, "HEAD")
    commit(repo, {"se.toml": TRUSTED + '\n[modules.se]\nref = "' + "4" * 40 + '"\n'})
    assert len({before, changed, ci_trust.suite_hash(repo, "HEAD")}) == 3


def test_the_integrator_is_the_owner_unless_se_toml_names_one(repo: Path) -> None:
    head, api = landing(repo), FakeApi()
    record(api, repo, head, actor="integrator-bot")
    assert not ci_trust.decide(repo, pull_request(repo, head), api).trusted

    commit(repo, {"se.toml": TRUSTED + 'integrator = "integrator-bot"\n'})
    record(api, repo, git(repo, "rev-parse", "HEAD"), run_id="901", actor="integrator-bot")
    assert ci_trust.decide(repo, pull_request(repo, git(repo, "rev-parse", "HEAD")), api).trusted


# When the full suite runs anyway.


def test_ses_own_check_keeps_trust_off_and_runs_the_full_suite() -> None:
    assert ci_trust.trust_settings(ROOT) == ci_trust.Trust(False, ci_trust.DEFAULT_FULL_EVERY, None)
    api = FakeApi()  # a record would not even be read
    decision = ci_trust.decide(ROOT, ci_trust.Run("pull_request", "x", "y", "main", OWNER), api)
    assert decision == ci_trust.Decision(
        False, "se.toml [tests] trust_integrator is off: the full suite runs")


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_the_safety_nets_runs_never_trust_a_record(repo: Path, event: str) -> None:
    api = FakeApi()
    sha = git(repo, "rev-parse", "HEAD")
    record(api, repo, sha)
    decision = ci_trust.decide(repo, ci_trust.Run(event, sha, owner=OWNER), api)
    assert decision == ci_trust.Decision(
        False, f"the safety net: a {event} run runs the full suite")


def test_every_nth_landing_runs_the_full_suite(repo: Path) -> None:
    for name in ("b", "c", "d"):
        commit(repo, {f"{name}.txt": name}, f"landing {name}")  # main holds four landings
    head, api = landing(repo, "e.txt"), FakeApi()  # the fifth, full_every = 5
    record(api, repo, head)

    decision = ci_trust.decide(repo, pull_request(repo, head), api)
    assert not decision.trusted
    assert decision.why == ("landing 5 is a multiple of se.toml [tests] full_every 5: the safety "
                            "net runs the full suite")

    git(repo, "switch", "-q", "main")
    commit(repo, {"e.txt": "e"}, "landing e")
    head = landing(repo, "f.txt")  # the sixth is trusted again
    record(api, repo, head, run_id="902")
    assert ci_trust.decide(repo, pull_request(repo, head), api).trusted


def test_a_push_to_main_finds_the_record_on_the_pull_request_that_landed_it(repo: Path) -> None:
    head, api = landing(repo), FakeApi()
    record(api, repo, head)
    git(repo, "switch", "-q", "main")
    squash = commit(repo, {"b.txt": "b.txt\n"}, "squash")  # the same tree as the landing head
    api.pulls[squash] = [head]

    decision = ci_trust.decide(repo, ci_trust.Run("push", squash, owner=OWNER), api)
    assert decision.trusted, decision.why

    other = commit(repo, {"c.txt": "c\n"}, "pushed by hand")
    decision = ci_trust.decide(repo, ci_trust.Run("push", other, owner=OWNER), api)
    assert decision == ci_trust.Decision(False, f"no merged pull request landed {other[:12]}, so "
                                                "no record names it: the full suite runs")


def test_a_landing_without_a_record_runs_the_full_suite(repo: Path) -> None:
    head = landing(repo)
    decision = ci_trust.decide(repo, pull_request(repo, head), FakeApi())
    assert decision == ci_trust.Decision(
        False, f"no record se integrator pass on {head[:12]}: the full suite runs")


@pytest.mark.parametrize("setting, why", [
    ("trust_integrator = 1", "trust_integrator must be true or false"),
    ("full_every = 0", "full_every must be a whole number of landings, 1 or more"),
    ('integrator = ""', "integrator must name the integrator's GitHub account"),
])
def test_a_malformed_trust_setting_is_refused(tmp_path: Path, setting: str, why: str) -> None:
    (tmp_path / "se.toml").write_text(f"[tests]\n{setting}\n", encoding="utf-8")
    with pytest.raises(ci_trust.TrustError, match=why):
        ci_trust.trust_settings(tmp_path)


# The record's writer, se-pass-record.yml's step.


def dispatch(root: Path, head: str, actor: str = OWNER, **inputs: str) -> ci_trust.Run:
    tree = ci_trust.tree(root, head)
    given = {"sha": head, "tree": tree, "tested": tree, "suite": ci_trust.suite_hash(root, head),
             "command": "uv run pytest -q", "seconds": "41.0", "result": "passed",
             "time": "2026-11-13T18:00:00Z", "session": "session_integrator", **inputs}
    return ci_trust.Run("workflow_dispatch", head, owner=OWNER, triggering_actor=actor,
                        run_url="https://github.com/alice/project/actions/runs/900", inputs=given)


def test_the_record_step_writes_the_check_run_lookup_trusts(repo: Path) -> None:
    head, api = landing(repo), FakeApi()

    assert ci_trust.run_record(repo, dispatch(repo, head), api) == 0

    [created] = api.created
    text = json.loads(created["output"]["text"])
    assert {key: created[key] for key in ("name", "head_sha", "status", "conclusion",
                                          "external_id")} == {
        "name": "se integrator pass", "head_sha": head, "status": "completed",
        "conclusion": "success", "external_id": "900"}
    assert {key: text[key] for key in ("tree", "suite", "command", "result", "time", "session")} == {
        "tree": ci_trust.tree(repo), "suite": ci_trust.suite_hash(repo, "HEAD"),
        "command": "uv run pytest -q", "result": "passed", "time": "2026-11-13T18:00:00Z",
        "session": "session_integrator"}
    # What it wrote, as GitHub serves it back with its run, is what lookup trusts.
    api.checks[head] = [{**created, "app": {"slug": "github-actions"}, "html_url": "u", "id": 1}]
    api.runs["900"] = {"path": ".github/workflows/se-pass-record.yml", "event": "workflow_dispatch",
                       "head_sha": head, "display_title": ci_trust.run_title(head, text["tree"]),
                       "triggering_actor": {"login": OWNER}}
    assert ci_trust.decide(repo, pull_request(repo, head), api).trusted


@pytest.mark.parametrize("run, why", [
    ({"actor": "mallory"}, "mallory dispatched this record; only the integrator alice may"),
    ({"tree": "5" * 40}, "tree 555555555555 is not the checkout's"),
    ({"suite": "6" * 64}, "suite 666666666666 is not the checkout's"),
    ({"sha": "7" * 40}, "sha 777777777777 is not the checkout's"),
])
def test_the_record_step_refuses_a_record_the_commit_does_not_bear_out(
        repo: Path, run: dict, why: str) -> None:
    head, api = landing(repo), FakeApi()
    with pytest.raises(ci_trust.TrustError, match=re.escape(why)):
        ci_trust.run_record(repo, dispatch(repo, head, **run), api)
    assert api.created == []


# The safety net's bookkeeping.


def test_a_full_pass_marks_its_commit_only_where_trust_is_on(repo: Path, capsys) -> None:
    api, sha = FakeApi(), git(repo, "rev-parse", "HEAD")
    ci_trust.run_full_pass(repo, ci_trust.Run("schedule", sha), api)
    assert [(check["name"], check["head_sha"]) for check in api.created] == [("se full pass", sha)]

    commit(repo, {"se.toml": "[tests]\n"})
    ci_trust.run_full_pass(repo, ci_trust.Run("schedule", git(repo, "rev-parse", "HEAD")), api)
    assert len(api.created) == 1
    assert "Full pass not marked: se.toml [tests] trust_integrator is off" in capsys.readouterr().out


def test_a_failed_full_run_names_the_trusted_records_since_the_last_full_pass(
        repo: Path, capsys) -> None:
    api = FakeApi()
    passed = git(repo, "rev-parse", "HEAD")
    api.checks[passed] = [{"name": "se full pass", "conclusion": "success"}]
    trusted = []
    for name in ("b", "c"):
        head = landing(repo, f"{name}.txt")
        record(api, repo, head, run_id=str(910 + len(trusted)))
        git(repo, "switch", "-q", "main")
        squash = commit(repo, {f"{name}.txt": f"{name}.txt\n"}, f"squash {name}")
        api.pulls[squash] = [head]
        trusted.append(squash)
    older = record(api, repo, passed, run_id="905")  # before the full pass: not named

    ci_trust.run_finding(repo, ci_trust.Run("schedule", trusted[-1]), api, {})

    out = capsys.readouterr().out
    assert out.startswith(f"::error title=se trusted landing::safety net: the full suite failed on "
                          f"{trusted[-1][:12]}; the trusted records that let changes through since "
                          "the last full pass: ")
    assert f"{trusted[1][:12]} landed on the record https://github.com/alice/project/runs/911" in out
    assert f"{trusted[0][:12]} landed on the record https://github.com/alice/project/runs/910" in out
    assert "session session_integrator" in out and older["html_url"] not in out


# The trust job end to end: ci_trust.py lookup through its real door, against a local GitHub.


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


@pytest.mark.parametrize("matching", [True, False])
def test_the_lookup_step_answers_through_the_rest_api(repo: Path, tmp_path: Path,
                                                      matching: bool) -> None:
    head, api = landing(repo), FakeApi()
    check = record(api, repo, head, tree=None if matching else "8" * 40)
    LocalGitHub.answers = {
        f"/repos/alice/project/commits/{head}/check-runs": {"total_count": 1, "check_runs": [check]},
        "/repos/alice/project/actions/runs/900": api.runs["900"]}
    LocalGitHub.asked = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LocalGitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    event, outputs = tmp_path / "event.json", tmp_path / "outputs"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": head}, "base": {"ref": "main"}}}),
                     encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event),
           "GITHUB_SHA": head, "GITHUB_REPOSITORY": "alice/project",
           "GITHUB_REPOSITORY_OWNER": OWNER, "GITHUB_TOKEN": "token", "GITHUB_OUTPUT": str(outputs),
           "GITHUB_API_URL": f"http://127.0.0.1:{server.server_address[1]}"}
    try:
        code = ci_trust.main(["lookup", "--worktree", str(repo)], env)
    finally:
        server.shutdown()
    assert code == 0
    assert outputs.read_text(encoding="utf-8").splitlines() == (
        ["trusted=true", "record=https://github.com/alice/project/runs/900"] if matching
        else ["trusted=false", "record="])
    assert LocalGitHub.asked[0] == (f"/repos/alice/project/commits/{head}/check-runs?check_name="
                                    "se%20integrator%20pass&per_page=100")


def test_the_lookup_step_runs_in_full_where_github_cannot_be_read(repo: Path, tmp_path: Path,
                                                                 capsys) -> None:
    head = landing(repo)
    outputs = tmp_path / "outputs"
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_SHA": head, "GITHUB_REPOSITORY": "alice/project",
           "GITHUB_TOKEN": "token", "GITHUB_OUTPUT": str(outputs),
           "GITHUB_API_URL": "http://127.0.0.1:9"}  # nothing listens there

    assert ci_trust.main(["lookup", "--worktree", str(repo)], env) == 0

    assert outputs.read_text(encoding="utf-8").splitlines()[0] == "trusted=false"
    assert "::warning title=se trusted landing::the record could not be read" in capsys.readouterr().out


# The workflows that call it.


def test_the_record_workflow_names_its_run_by_the_commit_and_tree_it_records() -> None:
    workflow = (WORKFLOWS / ci_trust.RECORD_WORKFLOW).read_text(encoding="utf-8")
    assert "run-name: se pass record ${{ inputs.sha }} tree ${{ inputs.tree }}" in workflow
    assert ci_trust.run_title("S", "T") == "se pass record S tree T"
    inputs = re.search(r"(?ms)^    inputs:\n(.*?)^\S", workflow)[1]
    assert re.findall(r"(?m)^      (\w+):$", inputs) == list(ci_trust.RECORD_INPUTS)
    assert re.search(r"(?m)^on:\n  workflow_dispatch:$", workflow)  # nothing else starts it
    assert "checks: write" in workflow and "mode: record" in workflow


def test_ses_check_gates_the_suite_and_kern_platforms_on_the_trust_job() -> None:
    workflow = (WORKFLOWS / "check.yml").read_text(encoding="utf-8")
    jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow.split("\njobs:\n")[1]))
    assert list(jobs) == ["check", "kern-platforms", "kern-platforms-queue", "trust"]
    assert "mode: lookup" in jobs["trust"] and "fetch-depth: 0" in jobs["trust"]
    for gated in ("kern-platforms", "kern-platforms-queue"):
        assert "needs: trust\n    if: needs.trust.outputs.trusted != 'true'" in jobs[gated], gated
    assert "needs: [trust, kern-platforms]" in jobs["check"]
    suite = re.search(r"(?ms)- name: The complete suite.*?\n(?=      - )", jobs["check"])[0]
    assert "if: needs.trust.outputs.trusted != 'true'" in suite
    # The cheap gates always run: the commits, the issue rule, the layouts, the reference, the report.
    for step in ("Gate the commits", "names an open work issue", "layouts match",
                 "command reference", "field report follows"):
        block = re.search(rf"(?ms)- name: [^\n]*{step}.*?\n(?=      - )", jobs["check"])[0]
        assert "needs.trust" not in block, step
    assert re.search(r'(?m)^  schedule:\n    - cron: "[^"]+"$', workflow)  # the nightly safety net
    assert "mode: full-pass" in jobs["check"] and "mode: finding" in jobs["check"]


def test_the_action_runs_ses_script_from_its_own_checkout() -> None:
    action = (ROOT / ".github" / "actions" / "integrator-pass" / "action.yml").read_text(
        encoding="utf-8")
    assert 'python3 "$GITHUB_ACTION_PATH/../../../scripts/ci_trust.py" "$MODE"' in action
    assert "description: lookup, record, full-pass or finding." in action
    assert set(ci_trust.COMMANDS) == {"lookup", "record", "full-pass", "finding"}
