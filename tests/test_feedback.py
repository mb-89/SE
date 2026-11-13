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
import quiet_git

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


# Requirements 3 and 4: the interactive commands against a door that answers slowly. The door
# records each call's start and end in one log, so a test proves order (a first line before the
# first call, calls made at once) instead of timing the machine it runs on.

DOOR_LOG = "FAKE_GH_LOG"  # the door's log: one line per event, its position the sequence counter
DOOR_OUTPUT = "FAKE_GH_OUTPUT"  # the file the command under test writes its output to, if any
WATCHER_LINE = ": working, nothing to show yet"  # feedback.watched's line for a silent run

FAKE_GH = '''\
import json, os, sys, time
def log(event):
    if os.environ.get("FAKE_GH_LOG"):
        with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\\n")
output = os.environ.get("FAKE_GH_OUTPUT")
shown = open(output, encoding="utf-8", errors="replace").read() if output else ""
log({"event": "start", "pid": os.getpid(), "shown": shown, "argv": sys.argv[1:3]})
time.sleep(float(os.environ["FAKE_GH_DELAY"]))
log({"event": "end", "pid": os.getpid()})
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


def door_events(log: Path) -> list[dict]:
    """The door's log in the order its events happened."""
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def door_depth(events: list[dict]) -> int:
    """The most door calls in a chain where each starts only after the one before has ended: the
    number of door delays a run waits in sequence."""
    depth: dict[int, int] = {}
    ended: list[int] = []
    for event in events:
        if event["event"] == "start":
            depth[event["pid"]] = 1 + max((depth[pid] for pid in ended), default=0)
        else:
            ended.append(event["pid"])
    return max(depth.values(), default=0)


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
    quiet_git.init(origin, "--bare", "-b", "main")
    quiet_git.clone(origin, checkout)
    identity = ("-c", "user.name=alice", "-c", "user.email=alice@example.com")
    git("-C", str(checkout), *identity, "commit", "-q", "--allow-empty", "-m", "start")
    git("-C", str(checkout), "push", "-q", "origin", "HEAD:main")
    environment = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                   "SE_METRICS": str(base / "metrics.jsonl"), "HOME": str(base),
                   "USERPROFILE": str(base)}
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


def first_line(argv: list[str], environment: dict[str, str], base: Path,
               deadline: float) -> tuple[float, str, list[dict]]:
    """The seconds until `argv` shows its first line (stdout or stderr, into a file the door
    reads as each of its calls starts), the line, and the door's log once its first call has
    started or the command has ended; the process is stopped then."""
    base.mkdir()
    log, output = base / "door.jsonl", base / "output.txt"  # its own: a stopped run's call
    environment = {**environment, DOOR_LOG: str(log), DOOR_OUTPUT: str(output)}  # may start late
    started = time.perf_counter()
    found: tuple[float, str] | None = None
    with output.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=environment)
        try:
            while time.perf_counter() - started < deadline:
                ended = process.poll() is not None
                text = output.read_text(encoding="utf-8", errors="replace")
                if found is None and "\n" in text:
                    found = time.perf_counter() - started, text.split("\n", 1)[0]
                called = any(event["event"] == "start" for event in door_events(log))
                if ended or (found is not None and called):
                    break
                time.sleep(0.01)
        finally:
            process.kill()
            process.wait()
    assert found is not None, f"no line within {deadline} s from {argv}"
    return (*found, door_events(log))


DOOR_DELAY = 10.0  # the door's answer; far past every budget, so no answer can be what is shown


def assert_first_line_before_the_door(command: str, argv: list[str], environment: dict[str, str],
                                      base: Path) -> None:
    """`command` shows a line before its first door call starts: the door, as it starts, already
    finds a line of the command's own (not the watcher's) in its output. A command that calls no
    door shows its first line before the door's delay has passed: the margin over the first-line
    budget is the delay less that budget, so a slow machine's start-up cannot fail it."""
    environment = {**environment, "FAKE_GH_DELAY": str(DOOR_DELAY)}
    seconds, line, events = first_line(argv, environment, base, DOOR_DELAY)
    assert line.strip(), command
    assert seconds < DOOR_DELAY, (command, seconds, line)
    starts = [event for event in events if event["event"] == "start"]
    if starts:  # the first call has started; what had the command shown by then?
        shown = [text for text in starts[0]["shown"].splitlines() if text.strip()]
        own = [text for text in shown if not text.endswith(WATCHER_LINE)]
        assert own, (command, "its first line came after its first door call", starts[0])


def test_each_interactive_command_shows_its_first_line_before_its_first_door_call(slow_door,
                                                                                  tmp_path):
    commands = interactive(slow_door["checkout"])
    assert set(commands) == set(feedback.INTERACTIVE)
    for command, argv in commands.items():
        assert_first_line_before_the_door(command, argv, slow_door["env"],
                                          tmp_path / command.replace(" ", "-"))


SILENT_DOOR = '''\
import subprocess, sys
sys.path.insert(0, sys.argv[1])
import feedback
with feedback.watched("work_tickets.py silent"):
    subprocess.run(["gh", "issue", "list"], capture_output=True, check=False)
'''


def test_a_command_whose_first_line_comes_after_its_door_call_fails_the_check(slow_door,
                                                                              tmp_path):
    script = tmp_path / "silent.py"
    script.write_text(SILENT_DOOR, encoding="utf-8")
    argv = [sys.executable, str(script), str(SCRIPTS)]
    with pytest.raises(AssertionError, match="its first line came after its first door call"):
        assert_first_line_before_the_door("work_tickets.py silent", argv, slow_door["env"],
                                          tmp_path / "silent")


BUDGET_DOOR_DELAY = 1.0  # the door's answer for the budget tests


def test_queue_reads_the_door_at_once_and_declares_its_budget(slow_door, tmp_path):
    """The queue's twelve door calls (the sign-in check, then seven listings at once, then five
    blockers at once) wait for the door in three rounds, not twelve: proven by the door's own
    log. Its wall time is checked against the door's delay only: under eleven delays, a margin of
    eight over the three it waits, never against the budget itself."""
    log = tmp_path / "door.jsonl"
    environment = {**slow_door["env"], "FAKE_GH_DELAY": str(BUDGET_DOOR_DELAY),
                   DOOR_LOG: str(log)}
    slow_door["metrics"].unlink(missing_ok=True)
    result = subprocess.run(interactive(slow_door["checkout"])["work_tickets.py queue"],
                            capture_output=True, text=True, env=environment, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py queue" and line["gh_calls"] == 11
    assert len([event for event in door_events(log) if event["event"] == "start"]) == 12
    assert door_depth(door_events(log)) == 3
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
    assert line["wall_seconds"] < line["gh_calls"] * BUDGET_DOOR_DELAY


def test_paused_reads_the_door_once_and_declares_its_budget(slow_door, tmp_path):
    """The sign-in check, then one read: two door delays in sequence, proven by the door's own
    log. No wall time is checked: two calls in sequence are what any run waits."""
    log = tmp_path / "door.jsonl"
    environment = {**slow_door["env"], "FAKE_GH_DELAY": str(BUDGET_DOOR_DELAY),
                   DOOR_LOG: str(log)}
    slow_door["metrics"].unlink(missing_ok=True)
    result = subprocess.run(interactive(slow_door["checkout"])["work_tickets.py paused"],
                            capture_output=True, text=True, env=environment, check=False)
    assert result.returncode == 0, result.stderr
    assert "Not paused" in result.stdout
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py paused" and line["gh_calls"] == 1
    assert door_depth(door_events(log)) == 2
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
