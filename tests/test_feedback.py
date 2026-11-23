"""Feedback within a second (scripts/feedback.py): the budgets declared once, the first line of a
silent run, the phases of the long commands, the announced GitHub and remote reads, and each
interactive command against a door that answers slowly."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import git_door
import fake_git
import waiting

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


class WatcherTurn:
    """`feedback.threading` for one test: its Event's timed wait, the watcher's check of whether a
    line came within half the budget, runs only once the body hands it its turn (`turn`), and the
    body goes on only once it ran (`taken`). The check itself then times out at once: which of
    the two came first is the body's order, not the clock's."""

    def __init__(self) -> None:
        self.turn, self.taken = threading.Event(), threading.Event()
        turn, taken = self.turn, self.taken

        class Event(threading.Event):
            def wait(self, timeout=None):
                if timeout is None:
                    return super().wait()
                assert turn.wait(waiting.DEADLINE_SECONDS), "the body never handed the watcher its turn"
                try:
                    return super().wait(0)
                finally:
                    taken.set()

        self.Event, self.Thread = Event, threading.Thread

    def hand_over(self) -> None:
        self.turn.set()
        assert self.taken.wait(waiting.DEADLINE_SECONDS), "the watcher never checked"


def test_a_run_silent_past_half_its_first_line_budget_says_it_is_working(monkeypatch, capsys):
    watcher = WatcherTurn()
    monkeypatch.setattr(feedback, "threading", watcher)
    with feedback.watched("work_tickets.py sync"):
        watcher.hand_over()  # half the budget passes with nothing shown
    assert capsys.readouterr().err == "work_tickets.py sync: working, nothing to show yet\n"


def test_a_run_that_speaks_at_once_gets_no_extra_line(monkeypatch, capsys):
    watcher = WatcherTurn()
    monkeypatch.setattr(feedback, "threading", watcher)
    with feedback.watched("work_tickets.py sync"):
        print("Synced")
        watcher.hand_over()  # half the budget passes after the line
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


def test_a_remote_read_by_git_is_announced_and_a_local_one_is_not(tmp_path, fake_git_door, capsys):
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
rounds = os.environ.get("FAKE_GH_ROUNDS")  # the calls of each round, e.g. "1,7,5"
if rounds:  # a call ends only once every call of its round has started
    def starts():
        lines = open(os.environ["FAKE_GH_LOG"], encoding="utf-8").read().splitlines()
        return [json.loads(line)["pid"] for line in lines if '"start"' in line]
    place = starts().index(os.getpid()) + 1
    bounds = [sum(int(n) for n in rounds.split(",")[:i + 1]) for i in range(len(rounds.split(",")))]
    bound = next((b for b in bounds if b >= place), 0)
    deadline = time.monotonic() + 30  # a failure bound: a call its round never joins
    while len(starts()) < bound and time.monotonic() < deadline:
        time.sleep(0.001)
log({"event": "end", "pid": os.getpid()})
a = sys.argv[1:]
if a[:2] == ["issue", "list"]:
    labels = [a[i + 1] for i, x in enumerate(a) if x == "--label"]
    blocked = os.environ.get("FAKE_GH_BLOCKERS")  # each candidate n names #1n and #20
    print(json.dumps([{"number": n, "title": f"feat/candidate-{n}",
                       "body": f"## Blocked by\\n\\n- #{10 + n}\\n- #20\\n" if blocked else "",
                       "labels": [{"name": "work"}, {"name": "ready"}]} for n in range(1, 6)]
                     if "ready" in labels else []))
elif a[:2] == ["pr", "list"]:
    print("[]")
elif a[:1] == ["api"]:
    number = a[1].rsplit("/", 1)[-1]
    print(json.dumps({"number": int(number) if number.isdigit() else 0, "state": "closed",
                      "state_reason": "completed", "issue_dependencies_summary": {"blocked_by": 0}}))
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


@pytest.fixture(scope="module")
def slow_door(tmp_path_factory) -> dict:
    """A checkout (a directory: the first-line runs read no git), and a `gh` on PATH that answers
    like GitHub, slowly."""
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
    checkout = base / "checkout"
    checkout.mkdir()
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


def first_line(argv: list[str], environment: dict[str, str], base: Path) -> tuple[str, list[dict]]:
    """The first line `argv` shows (stdout or stderr, into a file the door reads as each of its
    calls starts) and the door's log, once the command has ended."""
    base.mkdir()
    log, output = base / "door.jsonl", base / "output.txt"
    environment = {**environment, DOOR_LOG: str(log), DOOR_OUTPUT: str(output)}
    with output.open("w", encoding="utf-8") as sink:
        subprocess.run(argv, stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                       env=environment, timeout=waiting.DEADLINE_SECONDS, check=False)
    text = output.read_text(encoding="utf-8", errors="replace")
    assert "\n" in text, f"no line from {argv}: {text!r}"
    return text.split("\n", 1)[0], door_events(log)


def assert_first_line_before_the_door(command: str, argv: list[str], environment: dict[str, str],
                                      base: Path) -> None:
    """`command` shows a line before its first door call starts: the door, as it starts, already
    finds a line of the command's own (not the watcher's) in its output. The door answers at
    once, so the order of the log, not the clock, is what is checked."""
    line, events = first_line(argv, environment, base)
    assert line.strip(), command
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
import shutil, subprocess, sys
sys.path.insert(0, sys.argv[1])
import feedback
with feedback.watched("work_tickets.py silent"):
    subprocess.run([shutil.which("gh") or "gh", "issue", "list"], capture_output=True, check=False)
    print("listed")
'''


def test_a_command_whose_first_line_comes_after_its_door_call_fails_the_check(slow_door,
                                                                              tmp_path):
    script = tmp_path / "silent.py"
    script.write_text(SILENT_DOOR, encoding="utf-8")
    argv = [sys.executable, str(script), str(SCRIPTS)]
    with pytest.raises(AssertionError, match="its first line came after its first door call"):
        assert_first_line_before_the_door("work_tickets.py silent", argv, slow_door["env"],
                                          tmp_path / "silent")


# The queue's rounds of door calls, as FAKE_GH_ROUNDS holds them: the sign-in check, the listings,
# then the reads of the candidates (and, with FAKE_GH_BLOCKERS, of the blockers they name).
QUEUE_ROUNDS = "1,6,5"
BLOCKER_ROUNDS = "1,6,11"


def queue_checkout(tmp_path: Path) -> Path:
    """A checkout of the fake door whose origin holds main, as the queue's merge of main needs."""
    origin, checkout = tmp_path / "origin.git", tmp_path / "checkout"
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, checkout)
    identity = ("-c", "user.name=alice", "-c", "user.email=alice@example.com")
    for arguments in ((*identity, "commit", "-q", "--allow-empty", "-m", "start"), ("push", "-q", "origin", "HEAD:main")):
        assert git_door.run(*arguments, root=checkout).returncode == 0
    return checkout


def run_in_process(argv: list[str], environment: dict[str, str], monkeypatch) -> subprocess.CompletedProcess[str]:
    """`work_tickets.py <argv>` in this process, under `environment`, its git the door's fake; the
    door it measures, `gh`, stays a process of its own."""
    for name, value in environment.items():
        if os.environ.get(name) != value:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(work_tickets, "_signed_in_gh", set())  # the sign-in check is the door's first call
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = work_tickets.main(argv)
    return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())


def test_queue_reads_the_door_at_once_and_declares_its_budget(slow_door, tmp_path, fake_git_door, monkeypatch):
    """The queue's twelve door calls (the sign-in check, then six listings at once, then the
    blockers at once) wait for the door in three rounds, not twelve: proven by the door's own
    log, as a call ends only once its whole round has started. No wall time is checked."""
    log = tmp_path / "door.jsonl"
    environment = {**slow_door["env"], "FAKE_GH_ROUNDS": QUEUE_ROUNDS, DOOR_LOG: str(log)}
    slow_door["metrics"].unlink(missing_ok=True)
    checkout = queue_checkout(tmp_path)
    result = run_in_process(["queue", "--worktree", str(checkout), "--repo", "github.com/owner/repo"],
                            environment, monkeypatch)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py queue" and line["gh_calls"] == 11
    assert len([event for event in door_events(log) if event["event"] == "start"]) == 12
    assert door_depth(door_events(log)) == 3
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS


def test_queue_reads_the_blockers_its_candidates_name_with_their_own_reads(
        slow_door, tmp_path, fake_git_door, monkeypatch):
    """Candidates whose Blocked by names issues outside the listings: each blocker is read once,
    at once with the candidates' own reads, so the queue still waits for the door in three
    rounds."""
    log = tmp_path / "door.jsonl"
    environment = {**slow_door["env"], "FAKE_GH_ROUNDS": BLOCKER_ROUNDS, DOOR_LOG: str(log),
                   "FAKE_GH_BLOCKERS": "1"}
    checkout = queue_checkout(tmp_path)
    result = run_in_process(["queue", "--worktree", str(checkout), "--repo", "github.com/owner/repo"],
                            environment, monkeypatch)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    reads = [event["argv"][1] for event in door_events(log)
             if event["event"] == "start" and event["argv"][:1] == ["api"]]
    blockers = [path.rsplit("/", 1)[-1] for path in reads if path.rsplit("/", 1)[-1] in
                {"11", "12", "13", "14", "15", "20"}]
    assert sorted(blockers) == ["11", "12", "13", "14", "15", "20"]
    assert door_depth(door_events(log)) == 3


def test_paused_reads_the_door_once_and_declares_its_budget(slow_door, tmp_path):
    """The sign-in check, then one read: two door delays in sequence, proven by the door's own
    log. No wall time is checked: two calls in sequence are what any run waits."""
    log = tmp_path / "door.jsonl"
    environment = {**slow_door["env"], DOOR_LOG: str(log)}
    slow_door["metrics"].unlink(missing_ok=True)
    result = subprocess.run(interactive(slow_door["checkout"])["work_tickets.py paused"],
                            capture_output=True, text=True, env=environment, check=False)
    assert result.returncode == 0, result.stderr
    assert "Not paused" in result.stdout
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py paused" and line["gh_calls"] == 1
    assert door_depth(door_events(log)) == 2
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
