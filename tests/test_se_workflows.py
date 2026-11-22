"""SE's workflows and actions in a project as generated local copies (scripts/se_workflows.py, README
"Workflows"): no tracked workflow names SE's home, and the copies follow the project's SE pin."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import fake_git
import git_door
import se_workflows

ROOT = Path(__file__).resolve().parents[1]
PIN = "a" * 40
PLACE = "${{ github.repository_owner }}/SE"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def loaded(text: str) -> dict:
    data = yaml.safe_load(text)
    if True in data:
        data["on"] = data.pop(True)
    return data


# The copy, pure.


def test_a_module_url_names_how_ci_reaches_se_without_an_owner_where_it_is_relative() -> None:
    assert se_workflows.repository_expression("../SE.git") == PLACE
    assert se_workflows.repository_expression("../se") == "${{ github.repository_owner }}/se"
    assert se_workflows.repository_expression("https://example.com/alice/SE.git") == "alice/SE"
    assert se_workflows.repository_expression("git@example.com:alice/SE.git") == "alice/SE"
    for url in ("../../team/SE.git", "./SE.git", "/srv/se", ""):
        with pytest.raises(se_workflows.WorkflowError):
            se_workflows.repository_expression(url)


def test_every_file_se_ships_generates_a_copy_that_names_no_home_and_reaches_se_at_the_pin() -> None:
    for path in se_workflows.SHIPPED:
        copy = se_workflows.generate((ROOT / path).read_text(encoding="utf-8"), path, PIN, PLACE)
        assert se_workflows.read_header(copy) == (path, PIN, PLACE), path
        data = loaded(copy)
        # Nothing in the copy reaches the checkout the file runs from: SE comes from the pin.
        for own in ("${{ job.workflow_repository }}", "${{ job.workflow_sha }}",
                    "GITHUB_ACTION_PATH/../../../scripts"):
            assert own not in copy, (path, own)
        if path.startswith(".github/workflows/"):
            assert set(data["on"]) == {"workflow_call"}, f"{path}: a project calls it, never runs it on its own"
            assert list(data["jobs"]) == list(loaded((ROOT / path).read_text(encoding="utf-8"))["jobs"]), path
        elif "scripts/" in copy:
            first = data["runs"]["steps"][0]
            assert first["uses"].startswith("actions/checkout@")
            assert first["with"] == {"repository": PLACE, "ref": PIN, "path": se_workflows.CHECKOUT}, path
            assert f'"$GITHUB_WORKSPACE/{se_workflows.CHECKOUT}/scripts/' in copy


def test_the_battery_copy_checks_out_se_at_the_pin_where_se_s_own_reaches_its_workflow_commit() -> None:
    path = ".github/workflows/kern-battery.yml"
    copy = se_workflows.generate((ROOT / path).read_text(encoding="utf-8"), path, PIN, PLACE)
    data = loaded(copy)
    checkouts = [step for job in data["jobs"].values() for step in job["steps"]
                 if step.get("with", {}).get("path") == ".kern-battery"]
    assert len(checkouts) == 2 and all(step["with"]["repository"] == PLACE and step["with"]["ref"] == PIN
                                       for step in checkouts)


def test_a_reusable_workflow_keeps_only_workflow_call() -> None:
    text = ("name: x\n\non:\n  workflow_call:\n    inputs:\n      a:\n        type: string\n\n"
            "  # a rerun\n  pull_request:\n    paths: [x]\n  workflow_dispatch:\n\njobs:\n  a:\n    runs-on: x\n")
    copy = se_workflows.generate(text, ".github/workflows/release.yml", PIN, PLACE)
    assert copy.endswith("on:\n  workflow_call:\n    inputs:\n      a:\n        type: string\n\n"
                         "jobs:\n  a:\n    runs-on: x\n")
    with pytest.raises(se_workflows.WorkflowError, match="no workflow_call"):
        se_workflows.generate("on:\n  push:\njobs: {}\n", ".github/workflows/release.yml", PIN, PLACE)


def test_generate_refuses_a_file_se_does_not_ship_and_a_pin_that_is_no_commit() -> None:
    with pytest.raises(se_workflows.WorkflowError, match="ships no such file"):
        se_workflows.generate("on:\n  workflow_call:\n", ".github/workflows/check.yml", PIN, PLACE)
    with pytest.raises(se_workflows.WorkflowError, match="full commit SHA"):
        se_workflows.generate("on:\n  workflow_call:\n", ".github/workflows/release.yml", "v5", PLACE)


def test_only_a_generated_copy_has_a_header() -> None:
    assert se_workflows.read_header("name: check\n") is None
    assert se_workflows.read_header(se_workflows.header("x", PIN, PLACE) + "name: x\n") == ("x", PIN, PLACE)


# The wiring: a project with SE pinned as its module, on the git door's fake.

RELEASE = ".github/workflows/release.yml"
SHARD = ".github/actions/suite-shard/action.yml"


@pytest.fixture
def world(tmp_path: Path, fake_git_door):
    se = fake_git.init(tmp_path / "SE", "-b", "main")
    files = {RELEASE: (ROOT / RELEASE).read_text(encoding="utf-8"),
             SHARD: (ROOT / SHARD).read_text(encoding="utf-8")}
    for name, text in files.items():
        write(se / name, text)
    git_door.run("add", "-A", root=se)
    git_door.run("-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-m", "one", root=se)
    first = git_door.run("rev-parse", "HEAD", root=se).stdout.strip()
    write(se / RELEASE, files[RELEASE] + "# two\n")
    git_door.run("-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-am", "two", root=se)
    second = git_door.run("rev-parse", "HEAD", root=se).stdout.strip()
    project = fake_git.init(tmp_path / "project", "-b", "main")
    git_door.run("remote", "add", "origin", "https://example.com/alice/project.git", root=project)
    write(project / "se.toml", f'[modules.se]\nurl = "../SE.git"\nref = "{first}"\n')
    return se, project, first, second


def test_write_puts_the_copies_a_project_names_at_its_pin_and_check_passes(world) -> None:
    se, project, first, _ = world
    plan = se_workflows.plan(project, [RELEASE, SHARD], source=se)
    assert (plan.ref, plan.repository) == (first, PLACE)
    assert se_workflows.write(project, plan) == [f"{RELEASE}: generated from SE at {first[:12]}",
                                                 f"{SHARD}: generated from SE at {first[:12]}"]
    assert se_workflows.write(project, plan) == [], "a current copy is not written again"
    assert se_workflows.held(project) == {RELEASE: (RELEASE, first, PLACE), SHARD: (SHARD, first, PLACE)}
    assert se_workflows.check(project, se_workflows.plan(project, [], source=se)) == []
    assert "alice" not in (project / RELEASE).read_text() + (project / SHARD).read_text()


def test_check_names_a_hand_edited_copy_and_one_behind_the_pin(world, capsys) -> None:
    se, project, first, second = world
    se_workflows.write(project, se_workflows.plan(project, [RELEASE, SHARD], source=se))
    write(project / SHARD, (project / SHARD).read_text() + "# edited\n")
    write(project / "se.toml", f'[modules.se]\nurl = "../SE.git"\nref = "{second}"\n')
    assert se_workflows.check(project, se_workflows.plan(project, [], source=se)) == [
        f"{RELEASE}: differs from SE's file at the pin {second[:12]}; run se_workflows.py write",
        f"{SHARD}: differs from SE's file at the pin {second[:12]}; run se_workflows.py write",
    ]
    assert se_workflows.main(["--root", str(project), "--source", str(se), "check"]) == 1
    assert se_workflows.main(["--root", str(project), "--source", str(se), "write"]) == 0
    assert se_workflows.main(["--root", str(project), "--source", str(se), "check"]) == 0
    assert (project / RELEASE).read_text().endswith("# two\n")


def test_without_a_pin_or_a_copy_the_plan_names_its_remedy(world, capsys) -> None:
    se, project, *_ = world
    with pytest.raises(se_workflows.WorkflowError, match="holds no copy of SE's files; name the ones it calls"):
        se_workflows.plan(project, [], source=se)
    (project / "se.toml").write_text("[project]\n")
    with pytest.raises(se_workflows.WorkflowError, match=r"no pin for SE's files .*\[modules.se\]"):
        se_workflows.plan(project, [RELEASE], source=se)
    with pytest.raises(se_workflows.WorkflowError, match="SE ships no .github/workflows/check.yml"):
        se_workflows.plan(project, [".github/workflows/check.yml"], ref="HEAD", repository=PLACE, source=se)
    assert se_workflows.main(["--root", str(project), "--source", str(se), "check"]) == 2
    assert "se_workflows: " in capsys.readouterr().err


def test_an_application_without_se_pinned_keeps_the_pin_and_place_its_copies_carry(world) -> None:
    se, project, first, _ = world
    (project / "se.toml").write_text("[project]\n")
    se_workflows.write(project, se_workflows.plan(project, [RELEASE], ref=first, repository=PLACE, source=se))
    plan = se_workflows.plan(project, [SHARD, RELEASE], source=se)
    assert (plan.ref, plan.repository) == (first, PLACE)


# The shards CI runs against se.toml's `[tests] shards` (README "Test budget").

CHECK = ".github/workflows/check.yml"


def calling(shards: str, first: bool = True) -> str:
    step = ("      - uses: ./.github/actions/suite-time\n        with:\n" if first else
            "      - name: The suite's time\n        with:\n")
    step += f"          shards: {shards}\n"
    if not first:
        step += "        uses: ./.github/actions/suite-time/\n"
    return ("name: check\non: [push]\njobs:\n  check:\n    runs-on: x\n    steps:\n"
            "      - uses: actions/checkout@v7\n" + step +
            "      - name: after\n        run: echo shards: 9\n")


def test_suite_time_s_literal_shards_are_read_from_its_step_alone() -> None:
    assert se_workflows.suite_time_shards(calling("2")) == [(10, 2)]
    assert se_workflows.suite_time_shards(calling('"3"', first=False)) == [(10, 3)]
    assert se_workflows.suite_time_shards(calling("${{ strategy.job-total }}")) == []
    assert se_workflows.suite_time_shards(calling("2").replace("suite-time", "suite-shard")) == []


def test_check_fails_where_suite_time_s_shards_differ_from_se_toml_s(world) -> None:
    se, project, first, _ = world
    se_workflows.write(project, se_workflows.plan(project, [SHARD], source=se))
    manifest = f'[modules.se]\nurl = "../SE.git"\nref = "{first}"\n'
    write(project / CHECK, calling("2"))
    write(project / "se.toml", manifest + "\n[tests]\nshards = 2\n")
    assert se_workflows.check(project, se_workflows.plan(project, [], source=se)) == []
    assert se_workflows.main(["--root", str(project), "--source", str(se), "check"]) == 0
    write(project / "se.toml", manifest + "\n[tests]\nshards = 3\n")
    assert se_workflows.check(project, se_workflows.plan(project, [], source=se)) == [
        f"{CHECK}:10: suite-time runs shards: 2, but se.toml [tests] shards = 3; make them agree, "
        "as the budget is each shard's"]
    assert se_workflows.main(["--root", str(project), "--source", str(se), "check"]) == 1
    write(project / "se.toml", manifest)
    assert se_workflows.shard_mismatches(project) == [
        f"{CHECK}:10: suite-time runs shards: 2, but se.toml [tests] shards is unset (1); make them "
        "agree, as the budget is each shard's"]
    write(project / CHECK, calling("1"))
    assert se_workflows.shard_mismatches(project) == [], "one shard is the default"


def test_a_project_without_suite_time_or_shards_passes_as_before(world, tmp_path) -> None:
    se, project, first, _ = world
    se_workflows.write(project, se_workflows.plan(project, [SHARD], source=se))
    write(project / CHECK, calling("2").replace("suite-time", "suite-shard"))
    write(project / "se.toml", f'[modules.se]\nurl = "../SE.git"\nref = "{first}"\n\n[tests]\nshards = 4\n')
    assert se_workflows.check(project, se_workflows.plan(project, [], source=se)) == []
    bare = tmp_path / "bare"
    bare.mkdir()
    assert se_workflows.shard_mismatches(bare) == [], "neither se.toml nor workflows"
    write(bare / "se.toml", "[tests]\nshards = 0\n")
    write(bare / CHECK, calling("2"))
    assert se_workflows.shard_mismatches(bare) == [], "an invalid setting is the budget's to refuse"


def test_ses_own_forms_backstop_is_not_shipped_and_lets_no_event_text_into_a_run_line() -> None:
    """forms.yml (README "Forms"): SE's own workflow on issue and comment events, with only the
    permissions it needs, and no `${{ github.event` expression in any `run:` line, as anyone can
    open an issue."""
    path = ".github/workflows/forms.yml"
    assert path not in se_workflows.SHIPPED
    text = (ROOT / path).read_text(encoding="utf-8")
    data = loaded(text)
    assert data["on"] == {"issues": {"types": ["opened", "edited", "reopened", "labeled"]},
                          "issue_comment": {"types": ["created", "edited"]}}
    assert data["permissions"] == {"contents": "read", "issues": "write"}
    steps = [step for job in data["jobs"].values() for step in job["steps"]]
    runs = [step["run"] for step in steps if "run" in step]
    assert any("se_forms.py backstop" in run and '"$GITHUB_EVENT_PATH"' in run for run in runs)
    assert any("gh issue edit" in run and "--add-label" in run for run in runs)
    assert not any("${{" in run for run in runs)
    assert not any("remove-label" in run or "gh issue comment" in run for run in runs)
