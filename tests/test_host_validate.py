"""The hosts' validators over the generated layouts (scripts/host_validate.py), on a fake runner:
each outcome gives its exit code and lines, and nothing in SE runs the command by default."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_validate  # noqa: E402
from host_validate import Answer  # noqa: E402

PLUGIN, MARKETPLACE = ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"
SKILLS = ("skills/decision", "skills/work-model", ".github/skills/decision")
# The beside suites se.toml declares on main when this command arrived; the command adds none.
BESIDE_ON_MAIN = ["kern", "go-components", "kern-long-step", "release-guard", "new-app",
                  "se-components", "se-relay", "script-runs"]


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    """A built layout: both manifests and three skill folders."""
    for name in (PLUGIN, MARKETPLACE):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    for folder in SKILLS:
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return tmp_path


class FakeRunner:
    """Answers by the tool and the last argument; a version check without an entry answers the
    pinned version, a target without one passes. Records every call."""

    def __init__(self, answers: dict[tuple[str, str], Answer] | None = None):
        self.answers = answers or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, cwd, timeout):
        self.calls.append(list(argv))
        answer = self.answers.get((argv[0], argv[-1]))
        if answer is not None:
            return answer
        if argv[-1] == "--version":
            pinned = next(v.pinned for v in host_validate.VALIDATORS if v.tool == argv[0])
            return Answer(0, f"{pinned} ({argv[0]})\n")
        return Answer(0, "ok\n")


def run(layout: Path, runner: FakeRunner, skips_pass: bool = False) -> tuple[list[str], int]:
    return host_validate.report(host_validate.collect(layout, runner), skips_pass)


def test_every_validator_that_ran_passed(layout):
    lines, code = run(layout, FakeRunner())
    assert code == 0
    assert f"passed Claude Code: claude plugin validate {PLUGIN}" in lines
    assert f"passed Claude Code: claude plugin validate {MARKETPLACE}" in lines
    assert "passed Agent Skills: skills-ref validate .github/skills/decision" in lines
    assert "unchecked GitHub Copilot: Copilot CLI: no validator; checked by hand on the Monday checklist" in lines
    assert lines[-1] == "host validators: 5 passed, 0 refused, 0 skipped, 1 without a validator"


def test_the_runner_gets_each_layout_path_after_the_arguments(layout):
    runner = FakeRunner()
    run(layout, runner)
    assert ["claude", "plugin", "validate", "--strict", PLUGIN] in runner.calls
    assert ["claude", "plugin", "validate", "--strict", MARKETPLACE] in runner.calls
    assert ["skills-ref", "validate", "skills/work-model"] in runner.calls
    assert not any(call[0] == "Copilot CLI" for call in runner.calls)


def test_a_refused_layout_prints_the_file_and_the_hosts_message(layout):
    message = "x Found 1 error:\n  > name: Plugin name cannot contain spaces.\n"
    lines, code = run(layout, FakeRunner({("claude", PLUGIN): Answer(1, message)}))
    assert code == 1
    at = lines.index(f"refused Claude Code: claude plugin validate {PLUGIN}:")
    assert lines[at + 2] == "      > name: Plugin name cannot contain spaces."
    assert lines[-1] == "host validators: 4 passed, 1 refused, 0 skipped, 1 without a validator"
    # A refusal is never answered away as a skip.
    assert run(layout, FakeRunner({("claude", PLUGIN): Answer(1, message)}), skips_pass=True)[1] == 1


def test_an_absent_tool_is_a_skip_unless_skips_pass(layout):
    runner = FakeRunner({("skills-ref", "--version"): Answer(absent=True)})
    lines, code = run(layout, runner)
    assert code == 2
    assert "skipped Agent Skills: skills-ref validate: skills-ref not installed" in lines
    assert lines[-1] == "host validators: 2 passed, 0 refused, 3 skipped, 1 without a validator"
    assert not any(call[:2] == ["skills-ref", "validate"] for call in runner.calls)
    assert run(layout, runner, skips_pass=True)[1] == 0


def test_an_older_version_than_the_pinned_one_is_a_skip_even_with_skips_pass(layout):
    runner = FakeRunner({("claude", "--version"): Answer(0, "2.0.9 (Claude Code)\n")})
    lines, code = run(layout, runner, skips_pass=True)
    assert code == 2
    assert "skipped Claude Code: claude plugin validate: claude version 2.0.9 is older than the pinned 2.1.325" in lines
    assert lines[-1] == "host validators: 3 passed, 0 refused, 2 skipped, 1 without a validator"


def test_a_newer_version_runs(layout):
    lines, code = run(layout, FakeRunner({("claude", "--version"): Answer(0, "2.10.0 (Claude Code)\n")}))
    assert code == 0, lines


def test_a_time_out_is_a_skip_even_with_skips_pass(layout):
    runner = FakeRunner({("skills-ref", "skills/decision"): Answer(timed_out=True)})
    lines, code = run(layout, runner, skips_pass=True)
    assert code == 2
    assert "skipped Agent Skills: skills-ref validate skills/decision: skills-ref timed out" in lines
    assert lines[-1] == "host validators: 4 passed, 0 refused, 1 skipped, 1 without a validator"
    lines, code = run(layout, FakeRunner({("claude", "--version"): Answer(timed_out=True)}))
    assert code == 2
    assert "skipped Claude Code: claude plugin validate: claude timed out reading its version" in lines


def test_an_unexpected_exit_code_is_not_a_refusal(layout):
    lines, code = run(layout, FakeRunner({("claude", MARKETPLACE): Answer(3, "crash")}))
    assert code == 2
    assert f"skipped Claude Code: claude plugin validate {MARKETPLACE}: claude exited 3" in lines


def test_a_tree_without_built_layouts_is_a_skip(tmp_path):
    lines, code = run(tmp_path, FakeRunner())
    assert code == 2
    assert lines[-1] == "host validators: 0 passed, 0 refused, 2 skipped, 1 without a validator"
    assert any("no layout to read" in line for line in lines)


def test_the_real_runner_reports_an_absent_tool(tmp_path):
    answer = host_validate.run_process(["se-no-such-validator-tool", "--version"], tmp_path, 5)
    assert answer.absent


def test_main_prints_the_report_and_answers_its_code(layout, capsys):
    code = host_validate.main(["--root", str(layout)],
                              runner=FakeRunner({("claude", PLUGIN): Answer(1, "bad")}))
    assert code == 1
    assert capsys.readouterr().out.splitlines()[-1].startswith("host validators: 4 passed, 1 refused")


def test_help_gives_the_switch(capsys):
    with pytest.raises(SystemExit):
        host_validate.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "[tests.beside.host-validators]" in help_text
    assert "tests/beside_host_validators.py" in help_text


def test_se_toml_declares_no_beside_suite_for_it():
    beside = tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["tests"]["beside"]
    assert list(beside) == BESIDE_ON_MAIN
    for suite in beside.values():
        assert not any("host_valid" in part for part in suite["command"])


def test_no_workflow_hook_role_or_skill_names_it():
    places = [ROOT / "src", ROOT / ".github", ROOT / ".githooks", ROOT / "agents", ROOT / "skills",
              ROOT / "hooks"]
    named = [path.relative_to(ROOT).as_posix() for place in places if place.exists()
             for path in place.rglob("*") if path.is_file()
             and ("host_validate" in (text := path.read_text(encoding="utf-8", errors="replace"))
                  or "beside_host_validators" in text)]
    assert named == []
