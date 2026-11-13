"""Nothing reaches the integration branch without a passing suite and public check recorded on
exactly the tree pushed: `work_tickets.py push` and the pre-push hook refuse alike."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import quiet_git


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
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            check=False)
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
    quiet_git.init(origin, "--bare", "-b", "main")
    quiet_git.clone(origin, root)
    git(root, "config", "user.name", "alice")
    git(root, "config", "user.email", "alice@example.com")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (root / "se.toml").write_text(f"{IDENTITY}[tests]\ncommand = {SUITE}\n", encoding="utf-8")
    commit(root, name="base.txt")
    git(root, "push", "-q", "origin", "main")


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch, repositories) -> Path:
    """A clone of a bare origin on main, the integration branch, without hooks; its suite passes
    where verdict.txt says pass."""
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: tmp_path / "no-local.toml")
    monkeypatch.setenv("PATH", f"{INTERPRETER.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    repositories(build_checkout, tmp_path)
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
    else:
        git(root, "config", "core.hooksPath", str(PROJECT / ".githooks"))
        code = subprocess.run(["git", "-C", str(root), "push", "-q", "origin", "main"],
                              check=False).returncode
    captured = capfd.readouterr()
    return code == 0, captured.out + captured.err


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
    assert subprocess.run(["git", "-C", str(checkout), "push", "-q", "origin", "topic"],
                          check=False).returncode == 0


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
