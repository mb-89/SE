"""A project's own commit checks (README "Commit checks"): `se.toml` `[commit_checks]` names them as
commands, and se's commit hook runs them on the staged tree, refusing the commit where one fails.

git is the door's fake: in memory where the test calls the module, behind a state file
(`shared_fake_git`) where the commit runs se's hooks as git runs them. A check's command runs
through the process door, its fake answering it in-process (`fake_processes`), but in the hook's
one entry-point test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import commit_checks
import fake_git
import fake_processes as fake_processes_module
import git_door

PROJECT = Path(__file__).resolve().parents[1]
# The interpreter by its bare name, found on the PATH the test sets: the hook's public check scans
# the staged se.toml, which carries no machine path.
INTERPRETER = Path(sys.executable)


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def check(expected: str) -> str:
    """A check that passes where the checked tree's work.txt reads `expected`."""
    code = f"import sys; sys.exit(open('work.txt').read() != '{expected}' and 'work.txt is not {expected}')"
    return f'["{INTERPRETER.name}", "-c", "{code}"]'


def check_work(expected: str):
    """The fake of `check(expected)`'s command, as the process door's fake answers it: it reads
    work.txt where the check runs."""
    def answer(call: fake_processes_module.Invocation) -> fake_processes_module.Answer:
        if (call.cwd / "work.txt").read_text(encoding="utf-8") != expected:
            return fake_processes_module.Answer(1, "", f"work.txt is not {expected}\n")
        return fake_processes_module.Answer(0)
    return answer


def repository(tmp_path: Path, settings: str) -> Path:
    root = fake_git.init(tmp_path / "project")
    git(root, "config", "user.name", "alice")
    git(root, "config", "user.email", "alice@example.com")
    (root / "se.toml").write_text(settings, encoding="utf-8")
    return root


def test_the_table_names_each_check_and_its_command_in_order():
    settings = '[commit_checks]\nforbids = ["kern", "forbids"]\nlint = ["uv", "run", "lint"]\n'
    assert commit_checks.checks(settings) == {"forbids": ["kern", "forbids"],
                                              "lint": ["uv", "run", "lint"]}
    assert commit_checks.checks('[project]\nversion = "1.0.0"\n') == {}


@pytest.mark.parametrize("entry", ['forbids = "kern forbids"', "forbids = []", 'forbids = ["kern", 1]'])
def test_an_entry_that_is_no_command_is_refused_naming_it(entry):
    with pytest.raises(commit_checks.SetupError, match=r"\[commit_checks\] forbids must be a command"):
        commit_checks.checks(f"[commit_checks]\n{entry}\n")


def test_a_check_runs_on_the_staged_tree_not_the_working_tree(tmp_path, fake_git_door, fake_processes, capsys):
    fake_processes.on(INTERPRETER.name, check_work("staged"))
    root = repository(tmp_path, f"[commit_checks]\nstaged = {check('staged')}\n")
    (root / "work.txt").write_text("staged", encoding="utf-8")
    git(root, "add", "-A")
    (root / "work.txt").write_text("unstaged", encoding="utf-8")
    (root / "untracked.txt").write_text("not in the commit", encoding="utf-8")
    assert commit_checks.run(root) == 0
    assert "commit check staged: passed" in capsys.readouterr().out
    git(root, "add", "-A")
    assert commit_checks.run(root) == 1
    assert "work.txt is not staged" in capsys.readouterr().err
    assert [call.words[:2] for call in fake_processes.calls] == [[INTERPRETER.name, "-c"]] * 2
    assert all(call.cwd != root for call in fake_processes.calls)


def test_a_command_that_cannot_start_refuses_naming_the_check(tmp_path, fake_git_door, fake_processes, capsys):
    def cannot_start(call):
        raise FileNotFoundError(2, "No such file or directory", call.words[0])

    fake_processes.on("se-no-such-command", cannot_start)
    root = repository(tmp_path, '[commit_checks]\nmissing = ["se-no-such-command"]\n')
    git(root, "add", "-A")
    assert commit_checks.run(root) == 2
    assert "commit check missing: error: `se-no-such-command` cannot start" in capsys.readouterr().err


@pytest.mark.spawns("entry: .githooks/pre-commit, the shell that runs scripts/commit_checks.py on a commit")
@pytest.mark.usefixtures("shared_fake_git")  # the commit's hooks run as child processes
def test_the_commit_hook_refuses_a_failing_check_by_name_and_lets_a_passing_one_through(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{INTERPRETER.parent}{os.pathsep}{os.environ['PATH']}")
    root = repository(tmp_path, f"[commit_checks]\nwork-is-good = {check('good')}\n")
    git(root, "config", "core.hooksPath", str(PROJECT / ".githooks"))
    (root / "work.txt").write_text("bad", encoding="utf-8")
    git(root, "add", "-A")

    refused = git_door.run("commit", "-q", "-m", "Add bad work", root=root)
    assert refused.returncode != 0
    said = refused.stdout + refused.stderr
    assert "commit check work-is-good: failed with exit code 1" in said, said
    assert "work.txt is not good" in said, said
    assert git_door.run("rev-parse", "--verify", "HEAD", root=root).returncode != 0

    (root / "work.txt").write_text("good", encoding="utf-8")
    git(root, "add", "-A")
    passed = git_door.run("commit", "-q", "-m", "Add good work", root=root)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert git(root, "log", "-1", "--format=%s") == "Add good work"
