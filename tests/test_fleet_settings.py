"""The fleet's settings in the repository against the live ones (scripts/fleet_settings.py):
`work_tickets.py settings-check`, advisory, over fakes of its three doors.

Each door's contract is the answer the real door gave on 14 Nov 2026, kept under
tests/fixtures/fleet-settings/ with its private values replaced: the REST rules of main, and the
claude-code-remote tools list_triggers and get_environment, which only a session can call. The
contract tests read it and the fake alike; every other test uses the fake."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)
fleet_settings = work_tickets.sibling("fleet_settings")
RECORDED = PROJECT / "tests" / "fixtures" / "fleet-settings"

pytestmark = pytest.mark.usefixtures("fake_git_door")

SCRIPT = "#!/bin/bash\nexit 0\n#nov14"
SETTINGS = f"""
[ruleset]
branch = "main"
required_checks = ["check"]
strict = false
merge_methods = ["squash"]
linear_history = true
block_force_push = true
block_deletion = true

[[scheduled_tasks]]
name = "Issue intake check"
schedule = "15 * * * *"
model = ""
target = "persistent session"
enabled = true
prompt = "unchecked: not publishable"

[environment]
name = "general"
network = "unrestricted"
setup_script = '''
{SCRIPT}'''
"""


def fake_rules(checks=("check",), strict=False, methods=("squash",), linear=True,
               force_push_blocked=True, deletion_blocked=True) -> list[dict]:
    """The rules GitHub applies to a branch, as GET repos/<o>/<r>/rules/branches/<b> answers."""
    rules = [{"type": "deletion"}] if deletion_blocked else []
    rules += [{"type": "non_fast_forward"}] if force_push_blocked else []
    rules += [{"type": "required_linear_history"}] if linear else []
    rules += [{"type": "pull_request", "parameters": {"allowed_merge_methods": list(methods)}},
              {"type": "required_status_checks", "parameters": {
                  "strict_required_status_checks_policy": strict,
                  "required_status_checks": [{"context": check} for check in checks]}}]
    return rules


def fake_task(name="Issue intake check", cron="15 * * * *", model="", persist=True,
              enabled=True, prompt="any") -> dict:
    """One scheduled task as list_triggers lists it."""
    return {"name": name, "cron_expression": cron, "enabled": enabled, "persist_session": persist,
            "derived_state": {"prompt": prompt, "model": model}}


def fake_triggers(*tasks: dict, more=False) -> dict:
    return {"data": list(tasks) or [fake_task()], "has_more": more}


def fake_environment(name="general", network="unrestricted", script=SCRIPT) -> dict:
    """The environment as get_environment answers; script None as where it is withheld."""
    answer = {"name": name, "network": {"type": network}, "has_setup_script": True}
    return {**answer, "setup_script": script} if script is not None else answer


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / "fleet").mkdir(parents=True)
    (root / "fleet" / "settings.toml").write_text(SETTINGS, encoding="utf-8")
    return root


@pytest.fixture
def no_gh(monkeypatch):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)


def answers(tmp_path: Path, rules=None, triggers=None, environment=None) -> list[str]:
    """The settings-check options for each answer given, each saved as a JSON file."""
    options = []
    for flag, data in (("--ruleset", rules), ("--scheduled-tasks", triggers),
                       ("--environment", environment)):
        if data is not None:
            path = tmp_path / f"{flag.strip('-')}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            options += [flag, str(path)]
    return options


def run(worktree: Path, *arguments: str) -> int:
    return work_tickets.main(["settings-check", "--worktree", str(worktree),
                              "--repo", "git.example/owner/repo", *arguments])


def recorded(name: str) -> object:
    return json.loads((RECORDED / name).read_text(encoding="utf-8"))


# The contract of each door: the real answer and the fake read alike.

def test_the_rules_door_reads_the_real_answer_as_it_reads_the_fake():
    assert fleet_settings.live_ruleset(recorded("rules-branches-main.json")) == \
        fleet_settings.live_ruleset(fake_rules())


def test_the_list_triggers_door_reads_the_real_answer_as_it_reads_the_fake():
    real, more = fleet_settings.live_tasks(recorded("list-triggers.json"))
    fake, _ = fleet_settings.live_tasks(fake_triggers(fake_task(prompt=real[0]["prompt"])))
    assert (real, more) == (fake, False)


def test_the_get_environment_door_reads_the_real_answer_as_it_reads_the_fake():
    real = recorded("get-environment.json")
    assert fleet_settings.live_environment(real) == \
        fleet_settings.live_environment(fake_environment(script=real["setup_script"]))


# The check.

def test_the_check_reports_no_difference_where_every_door_reads_the_recorded_values(
        worktree, tmp_path, no_gh, capsys):
    code = run(worktree, *answers(tmp_path, fake_rules(), fake_triggers(), fake_environment()))
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == [
        'unchecked: scheduled_tasks."Issue intake check".prompt: not publishable',
        "no difference in 13 checked settings, 1 unchecked"]


def test_each_difference_is_one_line_and_fails_the_check_only_with_strict(
        worktree, tmp_path, no_gh, capsys):
    drifted = answers(
        tmp_path, fake_rules(strict=True, methods=("squash", "merge")),
        fake_triggers(fake_task(cron="0 * * * *", model="claude-example")),
        fake_environment(network="limited", script="#!/bin/bash\nexit 1\n#nov14"))
    assert run(worktree, *drifted) == 0
    advisory = capsys.readouterr().out
    assert run(worktree, *drifted, "--strict") == 1
    lines = capsys.readouterr().out.splitlines()
    assert advisory.splitlines() == lines
    assert [line for line in lines if line.startswith("difference")] == [
        "difference: ruleset.strict: recorded false, live true",
        'difference: ruleset.merge_methods: recorded ["squash"], live ["merge", "squash"]',
        'difference: scheduled_tasks."Issue intake check".schedule: recorded "15 * * * *", '
        'live "0 * * * *"',
        'difference: scheduled_tasks."Issue intake check".model: recorded "", '
        'live "claude-example"',
        'difference: environment.network: recorded "unrestricted", live "limited"',
        "difference: environment.setup_script: line 2 differs"]
    assert lines[-1] == "6 difference(s) in 13 checked settings, 1 unchecked"


def test_a_recorded_task_not_live_is_a_difference_unless_the_list_was_cut_short(
        worktree, tmp_path, no_gh, capsys):
    other = fake_task(name="Another task")
    assert run(worktree, *answers(tmp_path, triggers=fake_triggers(other)), "--strict") == 1
    assert 'difference: scheduled_tasks."Issue intake check": recorded, not live' in \
        capsys.readouterr().out
    assert run(worktree, *answers(tmp_path, triggers=fake_triggers(other, more=True)),
               "--strict") == 0
    assert 'unchecked: scheduled_tasks."Issue intake check": not in the first page' in \
        capsys.readouterr().out


def test_a_missing_door_is_unchecked_and_never_fails_the_check(worktree, no_gh, capsys):
    assert run(worktree, "--strict") == 0
    assert capsys.readouterr().out.splitlines() == [
        "unchecked: ruleset: no door: gh is not signed in; save the answer of GET "
        "repos/owner/repo/rules/branches/main and pass --ruleset <file>",
        "unchecked: scheduled_tasks: no door: pass the session's list_triggers answer as "
        "--scheduled-tasks <file>",
        "unchecked: environment: no door: pass the session's get_environment answer as "
        "--environment <file>",
        "no difference in 0 checked settings, 3 unchecked"]


def test_a_withheld_setup_script_is_unchecked(worktree, tmp_path, no_gh, capsys):
    assert run(worktree, *answers(tmp_path, environment=fake_environment(script=None))) == 0
    assert "unchecked: environment.setup_script: get_environment withheld it" in \
        capsys.readouterr().out


def test_with_gh_the_check_reads_the_ruleset_through_gh_and_a_refusal_is_unchecked(
        worktree, monkeypatch, capsys):
    paths = []

    class FakeGitHub:
        def __init__(self, root, repo):
            self.repo = repo

        def api(self, path):
            paths.append((self.repo, path))
            if refused:
                raise work_tickets.QueueError("gh: HTTP 403")
            return fake_rules(linear=False)

    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "GitHub", FakeGitHub)
    refused = False
    assert run(worktree, "--strict") == 1
    assert paths == [("git.example/owner/repo", "rules/branches/main")]
    assert "difference: ruleset.linear_history: recorded true, live false" in \
        capsys.readouterr().out
    refused = True
    assert run(worktree, "--strict") == 0
    assert "unchecked: ruleset: gh could not read it: gh: HTTP 403" in capsys.readouterr().out


def test_the_repository_records_the_fleet_settings_it_checks():
    """SE's own file loads, and every part the check compares is recorded."""
    settings = fleet_settings.load(PROJECT)
    assert set(fleet_settings.RULESET_KEYS) <= set(settings["ruleset"])
    assert [task["name"] for task in settings["scheduled_tasks"]] == ["Issue intake check"]
    assert settings["environment"]["setup_script"].rstrip().endswith("#nov14")
