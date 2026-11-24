"""Each command that hands off a plan or waits on kern's relay where gh has no account runs in one
call where gh's REST API answers (issue #1844's requirement 2): `paused`, `queue`, `intake
--outside`, `fleet-check`, `ready` with its claims, `file`, `route`, `start` and `integrate`.

gh here is Claude Code's cloud's: `gh auth status` fails, `gh api` answers, and the porcelain that
reaches GraphQL is refused (tests/fake_rest_github.py). Nothing patches `run_gh`, `gh_usable` or
`hand_off`: each command reaches GitHub through the real door, and each test checks it printed no
plan, wrote no hand-off and never reached GraphQL."""

import json
import shutil
from pathlib import Path

import pytest

from fake_rest_github import RestGitHub
from test_work_ticket_issues import (  # noqa: F401  (fixtures: the checkouts, the landing's GitHub)
    FakeGitHub, IDENTITY, OUTSIDE_CONFIG, git_ok, git_run, local_config, main_checkout,
    origin_main, reported_at, run, suite_passed, work_tickets, worktree,
)

pytestmark = pytest.mark.usefixtures("fake_git_door")
HOST = "git.example"
REPO = f"{HOST}/owner/repo"
SLUG = "owner/repo"


@pytest.fixture
def rest_gh(monkeypatch, fake_processes) -> RestGitHub:
    """gh as the cloud has it, for the checkout's origin `git.example/owner/repo`."""
    which = shutil.which
    github = RestGitHub(host=HOST)
    monkeypatch.setattr(work_tickets, "_gh_backend", {})
    monkeypatch.setattr(work_tickets.shutil, "which",
                        lambda name, *rest: "gh" if name == "gh" else which(name, *rest))
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: REPO)
    fake_processes.on("gh", github)
    return github


def in_one_call(github: RestGitHub, out: str, root: Path | None = None) -> bool:
    """The command ran its GitHub steps itself: no plan printed, no hand-off written, every gh
    call the sign-in check or a REST call."""
    handed = root is not None and (root / ".se" / "handoff").exists() and any(
        (root / ".se" / "handoff").iterdir())
    return ("GitHub plan" not in out and "GitHub step through kern's relay" not in out
            and not handed and all(call[:2] == ["auth", "status"] or
                                   (call[0] == "api" and "graphql" not in call)
                                   for call in github.calls))


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_paused_reads_the_pause_search_over_rest(worktree, rest_gh, capsys, paused):
    rest_gh.issue(SLUG, 1, "work", labels=["work"])
    if paused:
        rest_gh.issue(SLUG, 3, "Pause the fleet", labels=[work_tickets.PAUSE_LABEL])

    code = run(worktree, "paused")

    out = capsys.readouterr().out
    assert code == (1 if paused else 0) and in_one_call(rest_gh, out)
    assert (f"Paused by #3 Pause the fleet https://{HOST}/{SLUG}/issues/3" in out) == paused
    assert (f"Not paused: no open issue labelled pause in {REPO}" in out) == (not paused)


def test_file_route_and_ready_with_its_claims_run_over_rest(worktree, rest_gh, monkeypatch, capsys):
    rest_gh.issue(SLUG, 1, "Something from the other side", "Please fix it.")
    rest_gh.issue(SLUG, 5, "feature/running-20261106", labels=["work", "ready", "repo:repo", "in-progress"])
    monkeypatch.setattr(work_tickets, "branch_exists", lambda root, branch, repo: False)
    body = worktree / "work.md"
    body.write_text("## Goal\n\nA filed package.\n", encoding="utf-8")
    routing = worktree / "route.md"
    routing.write_text("## Package kind\n\nStandard, small.\n", encoding="utf-8")

    assert run(worktree, "file", "--title", "feature/filed-20261106", "--body-file", str(body)) == 0
    assert capsys.readouterr().out == f"Filed work issue https://{HOST}/{SLUG}/issues/6\n"
    assert rest_gh.label_names(SLUG, 6) == ["work", "ready", "repo:repo"]
    work = work_tickets.template_of("work")  # a body filed as given carries its template's marker
    assert rest_gh.issues[SLUG][6]["body"] == (f"{work_tickets.FLEET_MARKER}\n{work.marker_line}\n"
                                               "## Goal\n\nA filed package.\n")

    assert run(worktree, "route", "1", "--title", "fix/routed-20261106", "--routing-file", str(routing)) == 0
    routed = rest_gh.issues[SLUG][1]
    assert routed["title"] == "fix/routed-20261106"
    assert rest_gh.label_names(SLUG, 1) == ["work", "ready", "repo:repo"]
    assert routed["body"].startswith("Please fix it.\n\n" + work_tickets.HANDLED_MARKER)
    capsys.readouterr()

    assert run(worktree, "ready") == 0
    out = capsys.readouterr().out
    assert out == (
        "#6 feature/filed-20261106\n#1 fix/routed-20261106\n"
        "claimed #5 feature/running-20261106: stale, no beat, past the 12 h 00 min claim timeout\n"
        "Stale claims for the person: #5. Nothing frees a claim on its own: releasing one "
        "(deleting its branch, taking off in-progress and the beat line) is the person's step, "
        "which SE prepares (work model, Issues)\n")
    assert in_one_call(rest_gh, out, worktree)


def test_queue_lists_delivered_escalated_and_ready_work_over_rest(worktree, rest_gh, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "branch_exists", lambda root, branch, repo: False)
    rest_gh.issue(SLUG, 2, "feature/ready-20261106", labels=["work", "ready", "repo:repo"])
    rest_gh.issue(SLUG, 3, "feature/stuck-20261106", labels=["work", "escalated", "repo:repo"])
    rest_gh.pull(SLUG, 7, "feature/done-20261106", "feature/done-20261106", body=reported_at("abc1234"))
    rest_gh.pull(SLUG, 8, "feature/draft-20261106", "feature/draft-20261106", body="no report")

    assert run(worktree, "queue") == 0

    out = capsys.readouterr().out
    assert out.splitlines() == [
        f"delivered PR #7 feature/done-20261106 https://{HOST}/{SLUG}/pull/7",
        f"escalated #3 feature/stuck-20261106 https://{HOST}/{SLUG}/issues/3",
        out.splitlines()[2],  # the device's capacity
        "ready #2 feature/ready-20261106"]
    assert out.splitlines()[2].startswith("Capacity: ") and in_one_call(rest_gh, out, worktree)


def test_intake_outside_reads_each_repository_and_only_the_comments_it_judges_over_rest(
        worktree, rest_gh, capsys):
    (worktree / "se.toml").write_text(OUTSIDE_CONFIG, encoding="utf-8")
    rest_gh.issue(SLUG, 14, "issue 14", "From the other side.")
    rest_gh.issue(SLUG, 13, "issue 13", f"{work_tickets.FLEET_MARKER}\nA work issue.")
    rest_gh.issue(SLUG, 12, "issue 12", labels=["field-report"])
    rest_gh.issue(SLUG, 11, "issue 11", comments=["seen", f"{work_tickets.HANDLED_MARKER}\nRouted."])
    rest_gh.issue(SLUG, 9, "issue 9", comments=["below the cut-off"])
    rest_gh.issue("owner/other", 1, "issue 1")
    rest_gh.pull(SLUG, 15, "a pull request", "feature")

    assert run(worktree, "intake", "--outside") == 0

    out = capsys.readouterr().out
    assert out == ("Outside issues (2), not yet handled:\n"
                   f"  {REPO}#14 issue 14 https://{HOST}/{SLUG}/issues/14\n"
                   f"  {HOST}/owner/other#1 issue 1 https://{HOST}/owner/other/issues/1\n")
    paths = [call[3] for call in rest_gh.calls if call[0] == "api" and call[1] == "-X"]
    assert sorted(path for path in paths if "/comments" in path) == [
        f"repos/{SLUG}/issues/11/comments?per_page=100&page=1"]  # #9 sits below the cut-off
    assert in_one_call(rest_gh, out)


def test_fleet_check_reads_the_fleet_over_rest(worktree, rest_gh, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "fleet_branches", lambda root: {})
    rest_gh.issue(SLUG, 1, "feat/no-branch", labels=["work", "in-progress"],
                  comments=[{"body": "Started: worker session s1 on branch `feat/no-branch`",
                             "created_at": "2026-01-01T00:00:00Z"}])

    assert run(worktree, "fleet-check") == 1

    out = capsys.readouterr().out
    assert "#1" in out and "remedy:" in out and in_one_call(rest_gh, out)


def test_start_creates_the_worktree_and_marks_the_issue_over_rest(
        main_checkout, local_config, rest_gh, monkeypatch, capsys):
    branch = "feature/example-20261104"
    rest_gh.issue(SLUG, 5, branch, "## Goal\n\nStart it.\n", labels=["work", "ready", "repo:repo"])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, **_: 1)
    trees = main_checkout.parent / "trees"
    local_config.parent.mkdir(parents=True)
    local_config.write_text(f'[worktree_roots]\n"{main_checkout.name}" = "{trees.as_posix()}"\n',
                            encoding="utf-8")

    assert run(main_checkout, "start", "5") == 0

    out = capsys.readouterr().out
    assert f"Launch worker: agent=worker issue=https://{HOST}/{SLUG}/issues/5" in out
    assert git_run(trees / "feature-example-20261104", "branch", "--show-current").stdout.strip() == branch
    assert rest_gh.label_names(SLUG, 5) == ["work", "repo:repo", "in-progress"]
    assert in_one_call(rest_gh, out, main_checkout)


@pytest.mark.parametrize("cloud", [False, True], ids=["local", "cloud"])
def test_integrate_lands_and_closes_the_work_issue_over_rest(
        main_checkout, rest_gh, monkeypatch, capsys, cloud):
    """In the cloud the close-out claims none of three ready issues (SE#1881): no branch, no
    label changed, `Started: none here`."""
    branch = "feature/worker"
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", branch, str(worker))
    (worker / "worker.txt").write_text("worker\n", encoding="utf-8")
    git_ok("-C", str(worker), "add", "worker.txt")
    git_ok("-C", str(worker), "commit", "-q", "-m", "Add the worker file")
    git_ok("-C", str(worker), "push", "-q", "origin", branch)
    head = git_run(worker, "rev-parse", "HEAD", check=True).stdout.strip()
    report = reported_at(head)
    rest_gh.issue(SLUG, 5, branch, "## Goal\n\nLand it.\n", labels=["work", "in-progress", "repo:repo"])
    rest_gh.pull(SLUG, 7, branch, branch, body=report, sha=head)
    github = FakeGitHub()  # the landing's pull requests and check runs on the bare origin
    monkeypatch.setattr(work_tickets, "GitHub", github)
    monkeypatch.setattr(work_tickets, "wait", lambda seconds: None)
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    monkeypatch.setattr(work_tickets, "run_project_command", lambda root, command, label: "1 passed")
    monkeypatch.setattr(work_tickets, "run_suite", lambda root, **_: suite_passed(root, "1 passed"))
    monkeypatch.setattr(work_tickets, "guard", lambda root, branch, report: [])
    ready = (9, 10, 11)
    if cloud:  # what start_startable would claim, read over REST like everything else
        monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
        for number in ready:
            rest_gh.issue(SLUG, number, f"ready-{number}", "## Goal\n\nWait.\n",
                          labels=["work", "ready", "repo:repo"])
    else:
        monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo: [])
        monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, **_: 0)
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, number, repo: {"body": report})

    assert run(main_checkout, "integrate", "7") == 0

    out = capsys.readouterr().out
    assert ("Started: none here; start what is unblocked with the host's session tool\n" in out
            if cloud else "Started: 0" in out)
    if cloud:
        heads = git_run(main_checkout.parent / "origin.git", "for-each-ref", "--format=%(refname)",
                        "refs/heads/").stdout.split()
        assert not any(head.startswith("refs/heads/ready-") for head in heads)
        for number in ready:
            assert rest_gh.label_names(SLUG, number) == ["work", "ready", "repo:repo"]
            assert rest_gh.issues[SLUG][number]["body"] == "## Goal\n\nWait.\n"
    assert [call[0] for call in github.calls][:2] == ["open_pull", "create_pull"]
    landed = git_run(main_checkout.parent / "origin.git", "show", f"{origin_main(main_checkout)}:worker.txt")
    assert landed.stdout == "worker\n"  # squashed onto origin's main
    assert rest_gh.issues[SLUG][5]["state"] == "closed"
    assert in_one_call(rest_gh, out, main_checkout)


def test_unclaim_undoes_claims_no_worker_took_and_refuses_a_worker_s_branch_over_rest(
        main_checkout, rest_gh, capsys):
    """The claims a landing in the cloud made (SE#1881): #21 labelled ready again by hand, #22 still
    in progress, each with a beat line and a Started comment; #23's branch holds a worker's commit."""
    origin = main_checkout.parent / "origin.git"
    git_ok("-C", str(main_checkout), "fetch", "-q", "origin")
    older = git_run(main_checkout, "rev-parse", "origin/main~1", check=True).stdout.strip()
    beat = "<!-- se:fleet -->\n<!-- se:beat 2026-11-24T14:50Z -->\n\n## Goal\n\nWait.\n"
    started = "Started: worker session on branch `{}`\n"
    for number, labels in ((21, ["work", "ready"]), (22, ["work", "in-progress"]),
                           (23, ["work", "in-progress"])):
        rest_gh.issue(SLUG, number, f"claimed-{number}", beat, labels=[*labels, "repo:repo"],
                      comments=["Filed.", started.format(f"claimed-{number}")])
        git_ok("-C", str(main_checkout), "push", "-q", "origin", f"{older}:refs/heads/claimed-{number}")
    worker = main_checkout.parent / "worker"
    git_ok("-C", str(main_checkout), "worktree", "add", "-q", "-b", "work-23", str(worker), older)
    git_ok("-C", str(worker), "commit", "-q", "--allow-empty", "-m", "A worker's commit")
    git_ok("-C", str(worker), "push", "-q", "origin", "HEAD:refs/heads/claimed-23")

    assert run(main_checkout, "unclaim", "21", "22", "23") == 1

    captured = capsys.readouterr()
    assert "Unclaimed #21: beat line removed, Started comment answered\n" in captured.out
    assert "Unclaimed #22: beat line removed, ready again, Started comment answered\n" in captured.out
    assert ("unclaim: #23's branch claimed-23 on origin holds commits beyond main, a worker's; its "
            "claim is not undone and nothing was changed") in captured.err
    for number in (21, 22):
        assert rest_gh.issues[SLUG][number]["body"] == "<!-- se:fleet -->\n\n## Goal\n\nWait.\n"
        assert sorted(rest_gh.label_names(SLUG, number)) == ["ready", "repo:repo", "work"]
        answer = rest_gh.comments[(SLUG, number)][-1]["body"]
        assert answer.startswith("Claim undone: https://git.example/owner/repo/issues/"
                                 f"{number}#issuecomment-")
        assert answer.endswith(f" started no worker; `ready`, `claim` and `start` take its branch "
                               f"`claimed-{number}` again.\n") and answer.count("\n") == 1
    assert rest_gh.issues[SLUG][23]["body"] == beat
    assert rest_gh.label_names(SLUG, 23) == ["work", "in-progress", "repo:repo"]
    assert len(rest_gh.comments[(SLUG, 23)]) == 2
    assert git_run(origin, "rev-parse", "refs/heads/claimed-21", check=True).stdout.strip() == older

    assert run(main_checkout, "unclaim", "21", "22") == 0  # once undone, nothing is left to do
    assert capsys.readouterr().out == ("Unclaimed #21: nothing left to undo\n"
                                       "Unclaimed #22: nothing left to undo\n")
    assert [len(rest_gh.comments[(SLUG, number)]) for number in (21, 22)] == [3, 3]

    assert run(main_checkout, "ready") == 0  # their branches are unused claims start takes
    listed = capsys.readouterr().out
    assert "#21 claimed-21\n" in listed and "#22 claimed-22\n" in listed
    assert "#23 claimed-23\n" not in listed  # in progress: a claim, never startable


def test_turn_start_prints_every_part_of_the_turn_s_start_from_one_call(
        worktree, rest_gh, monkeypatch, capsys):
    (worktree / "se.toml").write_text(OUTSIDE_CONFIG, encoding="utf-8")
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "branch_exists", lambda root, branch, repo: False)
    monkeypatch.setattr(work_tickets, "fleet_branches", lambda root: {})
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos=False: None)
    rest_gh.issue(SLUG, 2, "feature/ready-20261106", labels=["work", "ready", "repo:repo"])
    rest_gh.issue(SLUG, 3, "feature/stuck-20261106", labels=["work", "escalated", "repo:repo"])
    rest_gh.issue(SLUG, 4, "feature/running-20261106", labels=["work", "in-progress", "repo:repo"])
    rest_gh.issue(SLUG, 14, "issue 14", "From the other side.")
    rest_gh.pull(SLUG, 7, "feature/done-20261106", "feature/done-20261106", body=reported_at("abc1234"))

    assert run(worktree, "turn-start") == 0

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[:8] == [
        f"Paused: no (no open issue labelled pause in {REPO})",
        "Escalations: 1", f"  escalated #3 feature/stuck-20261106 https://{HOST}/{SLUG}/issues/3",
        "Delivered pull requests: 1",
        f"  delivered PR #7 feature/done-20261106 https://{HOST}/{SLUG}/pull/7",
        "Capacity: unlimited (cloud)",
        "Startable work: 1", "  ready #2 feature/ready-20261106"]
    assert lines[8:10] == ["Claimed work: 2", lines[9]] and lines[9].startswith("  claimed #4 ")
    assert "Outside issues: 1" in lines  # #14, above its cut-off; owner/other has none
    assert f"  {REPO}#14 issue 14 https://{HOST}/{SLUG}/issues/14" in lines
    assert any(line.startswith("Fleet: ") for line in lines)
    assert in_one_call(rest_gh, out, worktree)


def test_turn_start_names_a_part_it_could_not_read_and_exits_one_while_paused(
        worktree, rest_gh, monkeypatch, capsys):
    (worktree / "se.toml").write_text(OUTSIDE_CONFIG, encoding="utf-8")
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "fleet_branches", lambda root: {})
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos=False: 2)
    rest_gh.issue(SLUG, 3, "Pause the fleet", labels=[work_tickets.PAUSE_LABEL])
    rest_gh.unreachable.add("owner/other")  # outside this session's reach

    assert run(worktree, "turn-start") == 1

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (f"Paused: yes, by #3 Pause the fleet https://{HOST}/{SLUG}/issues/3: "
                        "nothing starts, lands or is routed until the owner closes it")
    assert "Capacity: 2" in lines and "Delivered pull requests: none" in lines
    outside = next(line for line in lines if line.startswith("Outside issues: "))
    assert outside.startswith("Outside issues: not read: gh api GET repos/owner/other/issues "
                              "failed: gh: Not Found (HTTP 404)")


def test_turn_start_without_gh_prints_the_queue_s_and_the_fleet_check_s_plans(
        worktree, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: REPO)
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: pytest.fail(f"gh {args}"))

    assert run(worktree, "turn-start") == 2

    out = capsys.readouterr().out
    assert out.startswith(f"GitHub plan: queue of {REPO}\n1. list_issues ")
    assert "GitHub plan: fleet check\n" in out and out.rstrip().endswith(
        "Outside issues: read by hand, as the se checkout's src/skills/work-model/SKILL.md#without-gh says")
