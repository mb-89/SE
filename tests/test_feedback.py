"""Feedback within a second (scripts/feedback.py): the budgets declared once, the first line of a
silent run, the phases of the long commands, the announced GitHub and remote reads, and each
interactive command against a door that answers slowly."""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"


def load(name: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


work_tickets = load("work_tickets")
feedback = work_tickets.feedback
metrics = work_tickets.metrics


# Requirement 1: the budgets, declared once.


def test_the_budgets_are_declared_once_and_every_interactive_run_notes_its_own(tmp_path,
                                                                               monkeypatch):
    monkeypatch.setenv("SE_METRICS", str(tmp_path / "metrics.jsonl"))
    lines = {command: metrics.recorded(command, lambda: 0)[1]
             for command in ("work_tickets.py queue", "work_tickets.py intake",
                             "work_tickets.py status", "work_tickets.py metrics",
                             "se_start.py status", "work_tickets.py sync")}
    assert {command: line.get("budget_seconds") for command, line in lines.items()} == {
        "work_tickets.py queue": 5.0, "work_tickets.py intake": 5.0,
        "work_tickets.py status": 5.0, "work_tickets.py metrics": 5.0,
        "se_start.py status": 1.0, "work_tickets.py sync": None}
    assert feedback.FIRST_LINE_SECONDS == 1.0 and feedback.INTERACTIVE_SECONDS == 5.0
    over = {**lines["work_tickets.py queue"], "wall_seconds": 11.5}
    assert metrics.overruns(over) == ["wall time 11.5 s over its budget 5 s"]


def test_a_run_silent_past_half_its_first_line_budget_says_it_is_working(monkeypatch, capsys):
    monkeypatch.setattr(feedback, "FIRST_LINE_SECONDS", 0.2)
    with feedback.watched("work_tickets.py sync"):
        time.sleep(0.4)
    assert capsys.readouterr().err == "work_tickets.py sync: working, nothing to show yet\n"


def test_a_run_that_speaks_at_once_gets_no_extra_line(monkeypatch, capsys):
    monkeypatch.setattr(feedback, "FIRST_LINE_SECONDS", 0.2)
    with feedback.watched("work_tickets.py sync"):
        print("Synced")
        time.sleep(0.3)
    assert capsys.readouterr() == ("Synced\n", "")


def test_refresh_announces_each_phase_as_it_starts(tmp_path, monkeypatch, capsys):
    work_tickets.initialize(tmp_path)
    issue = {"repo": "owner/repo", "number": 5, "url": "https://github.com/owner/repo/issues/5",
             "title": "feat/x", "body": "## Requirements\n\n1. one\n", "updatedAt": "",
             "labels": [], "comments": []}

    def fetch(root, number, repo):
        assert capsys.readouterr().err == "Phase: read work issue #5\n"  # before the read
        return issue

    monkeypatch.setattr(work_tickets, "fetch_issue", fetch)
    work_tickets.refresh(tmp_path, 5, "owner/repo")
    assert capsys.readouterr().err == "Phase: compare it with the last read\n"


def test_every_long_command_announces_its_phases():
    source = (SCRIPTS / "work_tickets.py").read_text(encoding="utf-8")
    for function in ("def integrate(", "def run_suite(", "def compare_suites(", "def refresh(",
                     "def finish_integration(", "def read_back_integration("):
        body = source.split(function, 1)[1].split("\ndef ", 1)[0]
        assert "feedback.phase(" in body, function
    assert set(feedback.PHASED) == {"work_tickets.py integrate", "work_tickets.py suite",
                                    "work_tickets.py refresh"}


# Requirement 2: a read of GitHub or a remote is announced before it is made.


def test_a_github_call_is_announced_before_it_is_made(tmp_path, monkeypatch, capsys):
    seen: list[str] = []

    def run(arguments, **kwargs):
        seen.append(capsys.readouterr().err)
        return subprocess.CompletedProcess(arguments, 0, "[]", "")

    monkeypatch.setattr(work_tickets, "gh_executable", lambda: "gh")
    monkeypatch.setattr(work_tickets.subprocess, "run", run)
    work_tickets.run_gh(tmp_path, ["issue", "list", "--label", "escalated", "--json",
                                   "number,title", "--limit", "200", "--repo", "owner/repo"])
    assert seen == ["Reading GitHub: gh issue list --label escalated --repo owner/repo\n"]


def test_a_remote_read_by_git_is_announced_and_a_local_one_is_not(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets.subprocess, "run",
                        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0, "", ""))
    work_tickets.run_git(tmp_path, "status", "--short")
    work_tickets.run_git(tmp_path, "ls-remote", "--heads", "origin", "feat/x")
    assert capsys.readouterr().err == "Reading the remote: git ls-remote --heads origin feat/x\n"


# Requirements 3 and 4: the interactive commands against a door that answers slowly.

FAKE_GH = '''\
import json, os, sys, time
time.sleep(float(os.environ["FAKE_GH_DELAY"]))
a = sys.argv[1:]
if a[:2] == ["issue", "list"]:
    labels = [a[i + 1] for i, x in enumerate(a) if x == "--label"]
    print(json.dumps([{"number": n, "title": f"feat/candidate-{n}", "body": "",
                       "labels": [{"name": "work"}, {"name": "ready"}]} for n in range(1, 6)]
                     if "ready" in labels else []))
elif a[:2] == ["pr", "list"]:
    print("[]")
elif a[:1] == ["api"]:
    print(json.dumps({"issue_dependencies_summary": {"blocked_by": 0}}))
elif a[:2] == ["issue", "view"]:
    print(json.dumps({"number": 5, "title": "feat/x", "url": "https://github.com/owner/repo/issues/5",
                      "body": "## Requirements\\n\\n1. one\\n", "updatedAt": "", "labels": [],
                      "comments": []}))
'''


def git(*arguments: str) -> None:
    subprocess.run(["git", *arguments], check=True, capture_output=True)


@pytest.fixture(scope="module")
def slow_door(tmp_path_factory) -> dict:
    """A checkout with an origin, and a `gh` on PATH that answers like GitHub, slowly."""
    base = tmp_path_factory.mktemp("slow-door")
    bin_dir = base / "bin"
    bin_dir.mkdir()
    script = bin_dir / "fake_gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")
    if sys.platform == "win32":
        (bin_dir / "gh.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        gh = bin_dir / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        gh.chmod(0o755)
    origin, checkout = base / "origin.git", base / "checkout"
    git("init", "-q", "--bare", "-b", "main", str(origin))
    git("clone", "-q", str(origin), str(checkout))
    identity = ("-c", "user.name=alice", "-c", "user.email=alice@example.com")
    git("-C", str(checkout), *identity, "commit", "-q", "--allow-empty", "-m", "start")
    git("-C", str(checkout), "push", "-q", "origin", "HEAD:main")
    environment = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                   "SE_METRICS": str(base / "metrics.jsonl"), "HOME": str(base),
                   "USERPROFILE": str(base), "GITHUB_ACTIONS": ""}
    return {"checkout": checkout, "env": environment, "metrics": base / "metrics.jsonl"}


def interactive(checkout: Path) -> dict[str, list[str]]:
    work = [sys.executable, str(SCRIPTS / "work_tickets.py")]
    return {
        "work_tickets.py status": [*work, "status", "--worktree", str(checkout)],
        "work_tickets.py queue": [*work, "queue", "--worktree", str(checkout),
                                  "--repo", "github.com/owner/repo"],
        "work_tickets.py intake": [*work, "intake", "--worktree", str(checkout), "--issue", "5",
                                   "--repo", "github.com/owner/repo"],
        "work_tickets.py metrics": [*work, "metrics"],
        "work_tickets.py paused": [*work, "paused", "--worktree", str(checkout),
                                   "--repo", "github.com/owner/repo"],
        "se_start.py status": [sys.executable, str(SCRIPTS / "se_start.py"),
                               "--root", str(checkout), "status", "--offline"],
    }


def first_line_seconds(argv: list[str], environment: dict[str, str]) -> tuple[float, str]:
    """The seconds until `argv` shows its first line (stdout or stderr), and the line; the
    process is stopped then."""
    started = time.perf_counter()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=environment, text=True,
                               encoding="utf-8", errors="replace")
    found: list[tuple[float, str]] = []

    def read() -> None:
        line = process.stdout.readline()
        found.append((time.perf_counter() - started, line))

    reader = threading.Thread(target=read)
    reader.start()
    reader.join(timeout=10)
    process.kill()
    process.communicate()
    assert found, f"no line within 10 s from {argv}"
    return found[0]


def test_each_interactive_command_shows_its_first_line_within_a_second_of_a_slow_door(slow_door):
    environment = {**slow_door["env"], "FAKE_GH_DELAY": "3"}  # far past every budget
    commands = interactive(slow_door["checkout"])
    assert set(commands) == set(feedback.INTERACTIVE)
    for command, argv in commands.items():
        seconds, line = first_line_seconds(argv, environment)
        assert line.strip(), command
        assert seconds < feedback.FIRST_LINE_SECONDS, (command, seconds, line)


def test_queue_finishes_within_its_budget_against_a_door_of_half_a_second(slow_door):
    environment = {**slow_door["env"], "FAKE_GH_DELAY": "0.5"}
    slow_door["metrics"].unlink(missing_ok=True)
    result = subprocess.run(interactive(slow_door["checkout"])["work_tickets.py queue"],
                            capture_output=True, text=True, env=environment, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py queue" and line["gh_calls"] == 11
    assert line["wall_seconds"] < line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
    assert metrics.overruns(line) == []


def test_paused_finishes_within_its_budget_against_a_door_of_half_a_second(slow_door):
    environment = {**slow_door["env"], "FAKE_GH_DELAY": "0.5"}
    slow_door["metrics"].unlink(missing_ok=True)
    result = subprocess.run(interactive(slow_door["checkout"])["work_tickets.py paused"],
                            capture_output=True, text=True, env=environment, check=False)
    assert result.returncode == 0, result.stderr
    assert "Not paused" in result.stdout
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py paused" and line["gh_calls"] == 1
    assert line["wall_seconds"] < line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
    assert metrics.overruns(line) == []
