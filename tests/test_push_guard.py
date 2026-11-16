"""Nothing reaches the integration branch without a passing suite and public check recorded on
exactly the tree pushed: `work_tickets.py push` and the pre-push hook refuse alike.

git is the door's fake behind a state file (`shared_fake_git`, tests/conftest.py), which runs se's
pre-push hook as git does and which the hook's scripts reach as child processes."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
import fake_git
import git_door


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)
verdicts = work_tickets.sibling("verdicts")
# The interpreter by its bare name, found on the PATH the checkout fixture sets: se.toml is
# committed and public-checked, so it carries no machine path (a runner's /home/<name>/...).
INTERPRETER = Path(sys.executable)
SUITE = f'["{INTERPRETER.name}", "-c", "import sys; sys.exit(open(\'verdict.txt\').read().strip() != \'pass\')"]'


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(root: Path, verdict: str = "pass", name: str = "work.txt", text: str = "work") -> str:
    (root / "verdict.txt").write_text(verdict, encoding="utf-8")
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"Change {name}")
    return git(root, "rev-parse", "HEAD")


IDENTITY = '[project]\nidentity = "alice <alice@example.com>"\n'


def build_checkout(tmp_path: Path) -> None:
    origin, root = tmp_path / "origin.git", tmp_path / "main"
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, root)
    git(root, "config", "user.name", "alice")
    git(root, "config", "user.email", "alice@example.com")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (root / "se.toml").write_text(f"{IDENTITY}[tests]\ncommand = {SUITE}\n", encoding="utf-8")
    commit(root, name="base.txt")
    git(root, "push", "-q", "origin", "main")


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch, shared_fake_git) -> Path:
    """A clone of a bare origin on main, the integration branch, without hooks; its suite passes
    where verdict.txt says pass."""
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: tmp_path / "no-local.toml")
    monkeypatch.setenv("PATH", f"{INTERPRETER.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    build_checkout(tmp_path)
    return tmp_path / "main"


def test_the_fixture_commits_no_machine_path(checkout):
    """A checkout under /home/<name> (a CI runner's) would fail the fixture's own public check."""
    text = (checkout / "se.toml").read_text(encoding="utf-8")
    assert INTERPRETER.parent.as_posix() not in text and str(INTERPRETER.parent) not in text


def run_suite(root: Path) -> None:
    try:
        work_tickets.run_suite(root)
    except work_tickets.QueueError:
        pass


def origin_main(root: Path) -> str:
    return git(root.parent / "origin.git", "rev-parse", "main")


def push_with(pusher: str, root: Path, capfd) -> tuple[bool, str]:
    """Push main with work_tickets.py push, or with a plain git push through se's hooks."""
    if pusher == "push":
        code = work_tickets.main(["push", "main", "--worktree", str(root)])
        said = ""
    else:
        git(root, "config", "core.hooksPath", str(PROJECT / ".githooks"))
        pushed = git_door.run("push", "-q", "origin", "main", root=root)
        code, said = pushed.returncode, pushed.stdout + pushed.stderr
    captured = capfd.readouterr()
    return code == 0, captured.out + captured.err + said


CASES = {
    "no verdict": (lambda root: commit(root), False, "suite: no verdict is recorded"),
    "a failing verdict": (
        lambda root: (commit(root, "fail"), run_suite(root)), False,
        "suite: its recorded verdict is a failure"),
    "a passing verdict for another tree": (
        lambda root: (commit(root), run_suite(root), commit(root, name="later.txt")), False,
        "suite: no verdict is recorded"),
    "a passing verdict for this tree": (lambda root: (commit(root), run_suite(root)), True, ""),
}


@pytest.mark.parametrize("pusher", ["push", "hook"])
@pytest.mark.parametrize("case", CASES)
def test_push_and_the_hook_agree_on_the_suite_verdict(checkout, capfd, pusher, case):
    prepare, passes, refusal = CASES[case]
    prepare(checkout)
    before = origin_main(checkout)
    pushed, output = push_with(pusher, checkout, capfd)
    assert pushed is passes, output
    if passes:
        assert origin_main(checkout) == git(checkout, "rev-parse", "HEAD")
        return
    assert origin_main(checkout) == before
    head = git(checkout, "rev-parse", "HEAD")
    assert f"{refusal} for commit {head[:12]}" in output
    assert "Remedy: check out" in output and "work_tickets.py suite" in output


def test_a_branch_other_than_the_integration_branch_needs_no_verdict(checkout, capfd):
    git(checkout, "switch", "-q", "-c", "topic")
    commit(checkout)
    assert work_tickets.main(["push", "topic", "--worktree", str(checkout)]) == 0
    git(checkout, "config", "core.hooksPath", str(PROJECT / ".githooks"))
    commit(checkout, name="later.txt")
    assert git_door.run("push", "-q", "origin", "topic", root=checkout).returncode == 0


@pytest.mark.parametrize("landing", ["squash", "fast-forward"])
def test_a_published_commit_github_made_merged_in_passes_the_push_gates_a_new_one_does_not(
        checkout, tmp_path, capfd, landing):
    """A squash landing's commit on origin's main is GitHub's (web-flow committer, the account's
    noreply author): the strict identity gate (fast-forward landings) refuses it, but a branch
    that merges main pushes only its own commits, so `push` and the hook gate those no remote
    holds yet."""
    if landing == "fast-forward":
        with (checkout / "se.toml").open("a", encoding="utf-8") as config:
            config.write('\n[integrate]\nlanding = "fast-forward"\n')
        git(checkout, "commit", "-qam", "Land by fast-forward")
        git(checkout, "push", "-q", "origin", "main")
    git(checkout, "switch", "-q", "-c", "topic")
    commit(checkout, name="topic.txt")
    assert work_tickets.main(["push", "topic", "--worktree", str(checkout)]) == 0
    origin = tmp_path / "origin.git"
    main = git(origin, "rev-parse", "refs/heads/main")
    squash = git_door.run("commit-tree", f"{main}^{{tree}}", "-p", main, "-m", "Integrate x",
                          root=origin, env={**os.environ, "GIT_AUTHOR_NAME": "owner",
                                            "GIT_AUTHOR_EMAIL": "1+owner@users.noreply.github.com",
                                            "GIT_COMMITTER_NAME": "GitHub",
                                            "GIT_COMMITTER_EMAIL": "noreply" + "@github.com"})
    assert squash.returncode == 0, squash.stderr
    git(origin, "update-ref", "refs/heads/main", squash.stdout.strip(), main)
    git(checkout, "fetch", "-q", "origin")
    git(checkout, "merge", "-q", "--no-edit", "origin/main")
    git(checkout, "config", "core.hooksPath", str(PROJECT / ".githooks"))
    capfd.readouterr()

    assert work_tickets.main(["push", "topic", "--worktree", str(checkout)]) == 0

    assert "foreign-identity" not in capfd.readouterr().out
    (checkout / "foreign.txt").write_text("foreign", encoding="utf-8")
    git(checkout, "add", "foreign.txt")
    foreign = git_door.run("commit", "-q", "-m", "Add foreign.txt", root=checkout,
                           env={**os.environ, "GIT_AUTHOR_NAME": "bob", "GIT_AUTHOR_EMAIL": "bob"})
    assert foreign.returncode == 0, foreign.stderr
    assert work_tickets.main(["push", "topic", "--worktree", str(checkout)]) == 1
    assert git_door.run("push", "-q", "origin", "topic", root=checkout).returncode != 0
    out = capfd.readouterr()
    assert "author: foreign-identity 'bob <bob>'" in out.out + out.err


def verified(root: Path, ref: str = "refs/heads/main") -> int:
    return work_tickets.main(["verified", ref, "HEAD", "--worktree", str(root)])


@pytest.mark.parametrize(("public_check", "passes"), [
    (None, False), (False, False), ("other tree", False), (True, True),
])
def test_the_guard_needs_a_passing_public_check_on_the_tree(checkout, capsys, public_check, passes):
    """The hook's guard (`verified`), which push runs too, on each public-check verdict."""
    head = commit(checkout)
    verdicts.record(checkout, "suite", head, True)
    if public_check == "other tree":
        verdicts.record(checkout, "public-check", "HEAD~1", True)
    elif public_check is not None:
        verdicts.record(checkout, "public-check", head, public_check)
    assert verified(checkout) == (0 if passes else 1)
    error = capsys.readouterr().err
    if not passes:
        assert "public-check: " in error and f"commit {head[:12]}" in error
        assert "public_check.py --repo <checkout> --rev" in error


def test_without_a_public_check_the_guard_needs_the_suite_only(checkout):
    (checkout / "se.toml").write_text(f"{IDENTITY}public_check = false\n[tests]\ncommand = {SUITE}\n",
                                      encoding="utf-8")
    verdicts.record(checkout, "suite", commit(checkout), True)
    assert verified(checkout) == 0
    assert verified(checkout, "refs/heads/topic") == 0


def test_the_suite_records_pass_and_fail_on_the_tree_of_its_commit(checkout, capsys):
    head = commit(checkout)
    run_suite(checkout)
    tree = git(checkout, "rev-parse", "HEAD^{tree}")
    recorded = verdicts.verdict(checkout, "suite", tree)
    assert recorded["passed"] is True and recorded["commit"] == head
    assert recorded["seconds"] is not None
    commit(checkout, "fail")
    run_suite(checkout)
    assert verdicts.verdict(checkout, "suite", git(checkout, "rev-parse", "HEAD^{tree}"))["passed"] is False
    assert "Suite verdict recorded: failed" in capsys.readouterr().out


def test_the_suite_on_a_changed_checkout_records_nothing(checkout, capsys):
    commit(checkout)
    (checkout / "untracked.txt").write_text("x", encoding="utf-8")
    run_suite(checkout)
    assert verdicts.verdict(checkout, "suite", git(checkout, "rev-parse", "HEAD^{tree}")) is None
    assert "Suite verdict not recorded" in capsys.readouterr().out


def test_a_suite_over_its_limit_records_a_failure(checkout, monkeypatch):
    commit(checkout)
    ticks = iter([0.0, 500.0])
    monkeypatch.setattr(work_tickets, "clock", lambda: next(ticks))
    run_suite(checkout)
    assert verdicts.verdict(checkout, "suite", git(checkout, "rev-parse", "HEAD^{tree}"))["passed"] is False


def test_a_worktree_shares_the_verdicts_of_its_repository(checkout, tmp_path):
    head = commit(checkout)
    verdicts.record(checkout, "suite", head, True)
    git(checkout, "worktree", "add", "-q", str(tmp_path / "other"), head)
    assert verdicts.refusal(tmp_path / "other", "suite", head, "x") is None


@pytest.mark.parametrize(("content", "passed"), [("clean\n", True), ("/" + "home/alice\n", False)])
def test_the_public_check_of_a_rev_records_its_verdict(checkout, content, passed):
    public_check = work_tickets.sibling("public_check")
    commit(checkout, name="file.txt", text=content)
    public_check.main(["--repo", str(checkout), "--rev", "HEAD", "--range", "HEAD~1..HEAD"])
    recorded = verdicts.verdict(checkout, "public-check", git(checkout, "rev-parse", "HEAD^{tree}"))
    assert recorded["passed"] is passed


def test_a_release_commit_carries_its_parents_suite_verdict(checkout, capfd):
    (checkout / "se.toml").write_text(
        f'{IDENTITY}version = "1.0.0"\n[tests]\ncommand = {SUITE}\n', encoding="utf-8")
    commit(checkout)
    git(checkout, "tag", "v1.0.0")
    git(checkout, "switch", "-q", "-c", "fix/topic-20261106")
    commit(checkout, name="fix.txt")
    git(checkout, "switch", "-q", "main")
    git(checkout, "merge", "-q", "--no-ff", "-m", "Integrate fix/topic-20261106: fix",
        "-m", "Release-kind: patch", "fix/topic-20261106")
    run_suite(checkout)
    merge_tree = git(checkout, "rev-parse", "HEAD^{tree}")
    pushed, output = push_with("push", checkout, capfd)
    assert pushed, output
    release_tree = git(checkout, "rev-parse", "HEAD^{tree}")
    assert git(checkout, "log", "-1", "--format=%s") == "Release v1.0.1"
    recorded = verdicts.verdict(checkout, "suite", release_tree)
    assert recorded["passed"] is True and recorded["carried_from"] == merge_tree


def test_the_suite_notes_its_time_and_limit_in_the_metrics_line(checkout, tmp_path, monkeypatch,
                                                                 capsys):
    """README "Metrics": the suite's wall time and its [tests] limit, which the report flags."""
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("SE_METRICS", str(path))

    assert work_tickets.main(["suite", "--worktree", str(checkout)]) == 0

    line = json.loads(path.read_text(encoding="utf-8"))
    assert line["command"] == "work_tickets.py suite" and line["suite_limit_seconds"] == 120
    assert 0 < line["suite_seconds"] <= line["wall_seconds"]


# A push of the work branch after its delivery (README "Late push", scripts/late_push.py).
late_push = work_tickets.sibling("late_push")
WORK_BRANCH = "fix/topic-20261114"


def hook_push(root: Path, branch: str = WORK_BRANCH) -> tuple[int, str]:
    """Push `branch` with a plain git push through se's hooks: its exit code and what it said."""
    git(root, "config", "core.hooksPath", str(PROJECT / ".githooks"))
    pushed = git_door.run("push", "-q", "origin", branch, root=root)
    return pushed.returncode, pushed.stdout + pushed.stderr


def delivered_work_branch(root: Path) -> str:
    """The work branch, pushed and delivered at its tip (as deliver records it); its tip."""
    git(root, "switch", "-q", "-c", WORK_BRANCH)
    tip = commit(root, name="fix.txt")
    assert work_tickets.main(["push", "--worktree", str(root)]) == 0
    work_tickets.record_delivered_tip(root, WORK_BRANCH, tip)
    return tip


def test_a_push_before_any_delivery_names_no_late_push(checkout, capfd):
    git(checkout, "switch", "-q", "-c", WORK_BRANCH)
    commit(checkout, name="fix.txt")
    code, said = hook_push(checkout)
    output = said + "".join(capfd.readouterr())
    assert code == 0, output
    assert "late push" not in output


def test_a_push_after_the_delivery_names_the_stale_delivery_and_goes_through(checkout, capfd):
    tip = delivered_work_branch(checkout)
    later = commit(checkout, name="late.txt")
    code, said = hook_push(checkout)
    output = said + "".join(capfd.readouterr())
    assert code == 0, output
    assert git(checkout.parent / "origin.git", "rev-parse", WORK_BRANCH) == later
    lines = [line for line in output.splitlines() if "late push" in line]
    assert lines == [f"warning: late push: {WORK_BRANCH} was delivered at {tip[:12]} and this "
                     f"push moves it to {later[:12]}: the delivery is now stale and the "
                     "integrator will refuse it; run work_tickets.py deliver again after this "
                     "push"]


def test_a_push_of_the_delivered_tip_or_of_another_branch_names_no_late_push(checkout, capsys):
    delivered_work_branch(checkout)
    assert verified(checkout, f"refs/heads/{WORK_BRANCH}") == 0
    commit(checkout, name="late.txt")
    assert verified(checkout, "refs/heads/other") == 0
    assert "late push" not in "".join(capsys.readouterr())


def test_with_the_setting_on_a_push_after_the_delivery_is_refused(checkout, capfd):
    (checkout / "se.toml").write_text(
        f'{IDENTITY}[deliver]\nlate_push = "refuse"\n[tests]\ncommand = {SUITE}\n', encoding="utf-8")
    tip = delivered_work_branch(checkout)
    commit(checkout, name="late.txt")
    code, said = hook_push(checkout)
    output = said + "".join(capfd.readouterr())
    assert code != 0, output
    assert git(checkout.parent / "origin.git", "rev-parse", WORK_BRANCH) == tip
    assert f"error: late push: {WORK_BRANCH} was delivered at {tip[:12]}" in output
    assert "work_tickets.py push --redeliver" in output


def test_push_redeliver_records_its_tip_first_so_even_the_refusing_setting_lets_it_through(
        checkout, capfd):
    (checkout / "se.toml").write_text(
        f'{IDENTITY}[deliver]\nlate_push = "refuse"\n[tests]\ncommand = {SUITE}\n', encoding="utf-8")
    delivered_work_branch(checkout)
    later = commit(checkout, name="late.txt")
    git(checkout, "config", "core.hooksPath", str(PROJECT / ".githooks"))
    assert work_tickets.main(["push", "--redeliver", "--worktree", str(checkout)]) == 0
    assert "late push" not in "".join(capfd.readouterr())
    assert late_push.load(checkout / ".se" / "work") == {"branch": WORK_BRANCH, "tip": later}


def test_a_failed_redelivery_push_puts_the_record_back(checkout, monkeypatch):
    tip = delivered_work_branch(checkout)
    commit(checkout, name="late.txt")

    def refused(root, branch=None):
        raise work_tickets.QueueError("push refused")

    monkeypatch.setattr(work_tickets, "push", refused)
    assert work_tickets.main(["push", "--redeliver", "--worktree", str(checkout)]) == 1
    assert late_push.load(checkout / ".se" / "work") == {"branch": WORK_BRANCH, "tip": tip}


@pytest.mark.parametrize("value", ['"loud"', "true"])
def test_an_unknown_late_push_setting_is_refused_naming_the_values(checkout, capsys, value):
    (checkout / "se.toml").write_text(
        f'{IDENTITY}[deliver]\nlate_push = {value}\n[tests]\ncommand = {SUITE}\n', encoding="utf-8")
    assert verified(checkout, f"refs/heads/{WORK_BRANCH}") == 1
    assert "deliver.late_push must be one of warn, refuse" in capsys.readouterr().err


# Landing without CI (README "Landing without CI"): where se.toml on the pushed commit's parent sets
# [tests] ci = false, the integrator's commit status stands in for missing local verdicts.

NO_CI = f"{IDENTITY}[tests]\ncommand = {SUITE}\nci = false\n"
CONTEXT = work_tickets.trust.STATUS_CONTEXT


class StatusHost:
    """The host's commit statuses as work_tickets' door reads them, the integrator alice (the
    owner of origin, git.example/alice/project); no network."""

    def __init__(self) -> None:
        self.listed: dict[str, list[dict]] = {}
        self.landed_by: dict[str, list[str]] = {}
        self.reads: list[str] = []

    def __call__(self, root: Path, repo: str) -> "StatusHost":
        return self

    def statuses(self, sha: str) -> list[dict]:
        self.reads.append(sha)
        return list(reversed(self.listed.get(sha, [])))

    def merged_heads(self, sha: str) -> list[str]:
        return self.landed_by.get(sha, [])

    def write(self, root: Path, sha: str, *, tree: str | None = None, suite: str | None = None,
              creator: str = "alice", state: str = "success", context: str = CONTEXT) -> None:
        """A status on `sha`, by default the integrator's pass for exactly `sha`'s tree and suite."""
        tree = tree or git(root, "rev-parse", f"{sha}^{{tree}}")
        suite = suite or work_tickets.trust.suite_hash(root, sha)
        listed = self.listed.setdefault(sha, [])
        listed.append({"id": len(listed) + 1, "state": state, "context": context,
                       "creator": {"login": creator},
                       "description": work_tickets.trust.status_description(tree, suite)})


@pytest.fixture
def host(monkeypatch) -> StatusHost:
    fake = StatusHost()
    monkeypatch.setattr(work_tickets, "GitHub", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/alice/project")
    return fake


def without_ci(root: Path) -> str:
    """main's se.toml with ci = false, then a commit on it whose tree has no local verdict."""
    (root / "se.toml").write_text(NO_CI, encoding="utf-8")
    commit(root, name="setting.txt")
    return commit(root, name="later.txt")


def test_without_ci_the_guard_accepts_the_integrators_status_on_the_pushed_commit(
        checkout, host, capsys):
    head = without_ci(checkout)
    host.write(checkout, head)
    assert verified(checkout) == 0
    tree = git(checkout, "rev-parse", "HEAD^{tree}")
    assert (f"Verified: HEAD carries the integrator alice's status {CONTEXT}: tree "
            f"{tree[:12]} passed") in capsys.readouterr().out


def test_without_ci_the_guard_accepts_the_status_on_the_landing_head_that_landed_it(
        checkout, host, capsys):
    head = without_ci(checkout)
    landing = git(checkout, "commit-tree", "HEAD^{tree}", "-p", "HEAD~1", "-m", "Integrate it")
    host.write(checkout, landing)  # the squash commit carries none; its landing head does
    host.landed_by[head] = [landing]
    assert verified(checkout) == 0
    assert f"(on {landing[:12]})" in capsys.readouterr().out


def test_without_ci_push_accepts_the_status_as_the_hook_does(checkout, host, capfd):
    head = without_ci(checkout)
    host.write(checkout, head)
    pushed, output = push_with("push", checkout, capfd)
    assert pushed, output
    assert origin_main(checkout) == git(checkout, "rev-parse", "HEAD")
    assert f"carries the integrator alice's status {CONTEXT}" in output


@pytest.mark.parametrize(("status", "named"), [
    ({}, "no status se integrator verdict"),
    ({"tree": "d" * 40}, "is of tree dddddddddddd"),
    ({"suite": "e" * 64}, "names suite eeeeeeeeeeee"),
    ({"creator": "mallory"}, "written by mallory, not by the integrator alice"),
    ({"state": "failure"}, "is failure, not success"),
    ({"context": "ci/other"}, "no status se integrator verdict"),
])
def test_without_ci_the_guard_refuses_any_other_status(checkout, host, capsys, status, named):
    head = without_ci(checkout)
    if status:
        host.write(checkout, head, **status)
    assert verified(checkout) == 1
    error = capsys.readouterr().err
    assert "Refusing to push HEAD" in error and "suite: no verdict is recorded" in error
    assert named in error


def test_with_ci_the_guard_reads_no_status_and_refuses_as_before(checkout, host, capsys):
    head = commit(checkout, name="later.txt")
    host.write(checkout, head)  # a status that would pass where ci were off
    assert verified(checkout) == 1
    assert host.reads == []
    error = capsys.readouterr().err
    assert "Refusing to push HEAD to the integration branch main" in error
    assert CONTEXT not in error


def test_a_pushed_commit_cannot_turn_ci_off_for_itself(checkout, host, capsys):
    (checkout / "se.toml").write_text(NO_CI, encoding="utf-8")
    head = commit(checkout, name="later.txt")  # the setting arrives with the commit pushed
    host.write(checkout, head)
    assert verified(checkout) == 1
    assert host.reads == []  # its parent keeps CI on: no status is read
