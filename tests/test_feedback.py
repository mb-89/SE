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
from collections.abc import Callable
from pathlib import Path

import pytest
import git_door
import fake_git
import fake_processes as fake_programs
import process_door
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
se_start = load("se_start")
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
    monkeypatch.setattr(work_tickets.process_door, "run", run)
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

WATCHER_LINE = ": working, nothing to show yet"  # feedback.watched's line for a silent run
ROUND_BOUND_SECONDS = 30  # a failure bound: a call its round never joins ends after it


class SlowDoor:
    """`gh` behind the process door's fake: it answers like GitHub and logs each call's start and
    end, the log's order the sequence counter. A start notes what the command under test had shown
    by then (`shown`). With `rounds` (the calls of each round, e.g. "1,6,5") a call ends only once
    every call of its round has started, so calls made one after the other wait in sequence."""

    def __init__(self, rounds: str = "", blockers: bool = False,
                 shown: Callable[[], str] = lambda: "") -> None:
        self.rounds, self.blockers, self.shown = rounds, blockers, shown
        self.events: list[dict] = []
        self.changed = threading.Condition()

    def starts(self) -> int:
        return len([event for event in self.events if event["event"] == "start"])

    def __call__(self, invocation: fake_programs.Invocation) -> str:
        arguments = invocation.arguments
        with self.changed:
            call = self.starts() + 1
            self.events.append({"event": "start", "pid": call, "shown": self.shown(), "argv": arguments[:2]})
            self.changed.notify_all()
            if self.rounds:
                counts = [int(n) for n in self.rounds.split(",")]
                bounds = [sum(counts[:i + 1]) for i in range(len(counts))]
                bound = next((b for b in bounds if b >= call), 0)
                self.changed.wait_for(lambda: self.starts() >= bound, ROUND_BOUND_SECONDS)
            self.events.append({"event": "end", "pid": call})
        return self.answer(arguments)

    def answer(self, a: list[str]) -> str:
        if a[:2] == ["issue", "list"]:
            labels = [a[i + 1] for i, x in enumerate(a) if x == "--label"]
            return json.dumps([{"number": n, "title": f"feat/candidate-{n}",  # candidate n names #1n and #20
                                "body": f"## Blocked by\n\n- #{10 + n}\n- #20\n" if self.blockers else "",
                                "labels": [{"name": "work"}, {"name": "ready"}]} for n in range(1, 6)]
                              if "ready" in labels else [])
        if a[:2] == ["pr", "list"]:
            return "[]"
        if a[:1] == ["api"]:
            number = a[1].rsplit("/", 1)[-1]
            return json.dumps({"number": int(number) if number.isdigit() else 0, "state": "closed",
                               "state_reason": "completed", "issue_dependencies_summary": {"blocked_by": 0}})
        if a[:2] == ["issue", "view"]:
            return json.dumps({"number": 5, "title": "feat/x", "url": "https://github.com/owner/repo/issues/5",
                               "body": "## Requirements\n\n1. one\n", "updatedAt": "", "labels": [],
                               "comments": []})
        return ""


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
    """A checkout (a directory: the first-line runs read no git), the environment the commands run
    under, and a `gh` on PATH for them to find; the door's fake answers it (`SlowDoor`), so it
    never runs."""
    base = tmp_path_factory.mktemp("slow-door")
    bin_dir = base / "bin"
    bin_dir.mkdir()
    gh = bin_dir / ("gh.cmd" if sys.platform == "win32" else "gh")
    gh.write_text("exit 127\n", encoding="utf-8")
    gh.chmod(0o755)
    checkout = base / "checkout"
    checkout.mkdir()
    environment = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                   "SE_METRICS": str(base / "metrics.jsonl"), "HOME": str(base), "USERPROFILE": str(base)}
    return {"checkout": checkout, "env": environment, "metrics": base / "metrics.jsonl"}


Command = tuple[Callable[[list[str]], int], list[str]]


def interactive(checkout: Path) -> dict[str, Command]:
    """Each interactive command: the `main` that runs it and its arguments."""
    return {
        "work_tickets.py status": (work_tickets.main, ["status", "--worktree", str(checkout)]),
        "work_tickets.py queue": (work_tickets.main, ["queue", "--worktree", str(checkout),
                                                      "--repo", "github.com/owner/repo"]),
        "work_tickets.py intake": (work_tickets.main, ["intake", "--worktree", str(checkout), "--issue", "5",
                                                       "--repo", "github.com/owner/repo"]),
        "work_tickets.py metrics": (work_tickets.main, ["metrics"]),
        "work_tickets.py paused": (work_tickets.main, ["paused", "--worktree", str(checkout),
                                                       "--repo", "github.com/owner/repo"]),
        "se_start.py status": (se_start.main, ["--root", str(checkout), "status", "--offline"]),
    }


def run_in_process(command: Command, environment: dict[str, str], monkeypatch,
                   sink: io.StringIO | None = None) -> subprocess.CompletedProcess[str]:
    """`command` run in this process as a fresh run of its script would, under `environment`: its
    git the door's fake, `gh` the test's `SlowDoor`. Its stdout and stderr go to `sink` where
    given, into one stream as a terminal shows them."""
    main, argv = command
    for name, value in environment.items():
        if os.environ.get(name) != value:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(work_tickets, "_signed_in_gh", set())  # the sign-in check is the door's first call
    out, err = (sink, sink) if sink is not None else (io.StringIO(), io.StringIO())
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())


def first_line(command: Command, environment: dict[str, str], monkeypatch,
               fake_processes) -> tuple[str, list[dict]]:
    """The first line `command` shows (stdout or stderr, into one stream the door reads as each of
    its calls starts) and the door's log, once the command has ended."""
    sink = io.StringIO()
    door = SlowDoor(shown=sink.getvalue)
    fake_processes.on("gh", door)
    run_in_process(command, environment, monkeypatch, sink)
    text = sink.getvalue()
    assert "\n" in text, f"no line from {command[1]}: {text!r}"
    return text.split("\n", 1)[0], door.events


def assert_first_line_before_the_door(name: str, command: Command, environment: dict[str, str],
                                      monkeypatch, fake_processes) -> None:
    """`name` shows a line before its first door call starts: the door, as it starts, already
    finds a line of the command's own (not the watcher's) in its output. The door answers at
    once, so the order of the log, not the clock, is what is checked."""
    line, events = first_line(command, environment, monkeypatch, fake_processes)
    assert line.strip(), name
    starts = [event for event in events if event["event"] == "start"]
    if starts:  # the first call has started; what had the command shown by then?
        shown = [text for text in starts[0]["shown"].splitlines() if text.strip()]
        own = [text for text in shown if not text.endswith(WATCHER_LINE)]
        assert own, (name, "its first line came after its first door call", starts[0])


def test_each_interactive_command_shows_its_first_line_before_its_first_door_call(
        slow_door, fake_git_door, fake_processes, monkeypatch):
    commands = interactive(slow_door["checkout"])
    assert set(commands) == set(feedback.INTERACTIVE)
    for name, command in commands.items():
        assert_first_line_before_the_door(name, command, slow_door["env"], monkeypatch, fake_processes)


def silent(argv: list[str]) -> int:
    """A command whose first door call comes before its first line."""
    with feedback.watched("work_tickets.py silent"):
        process_door.run(["gh", "issue", "list"], capture_output=True, check=False)
        print("listed")
    return 0


def test_a_command_whose_first_line_comes_after_its_door_call_fails_the_check(
        slow_door, fake_processes, monkeypatch):
    with pytest.raises(AssertionError, match="its first line came after its first door call"):
        assert_first_line_before_the_door("work_tickets.py silent", (silent, []), slow_door["env"],
                                          monkeypatch, fake_processes)


# The queue's rounds of door calls: the sign-in check, the listings, then the reads of the
# candidates (and, with blockers, of the blockers they name).
QUEUE_ROUNDS = "1,6,5"
BLOCKER_ROUNDS = "1,6,11"


def queue_checkout(tmp_path: Path, monkeypatch) -> Path:
    """A checkout of the fake door whose origin holds main, as the queue's merge of main needs;
    its origin, a local path, stands for the remote that hosts the issues' repository."""
    monkeypatch.setattr(work_tickets, "issue_remote", lambda root, repo: "origin")
    origin, checkout = tmp_path / "origin.git", tmp_path / "checkout"
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, checkout)
    identity = ("-c", "user.name=alice", "-c", "user.email=alice@example.com")
    for arguments in ((*identity, "commit", "-q", "--allow-empty", "-m", "start"), ("push", "-q", "origin", "HEAD:main")):
        assert git_door.run(*arguments, root=checkout).returncode == 0
    return checkout


def queue(checkout: Path) -> Command:
    return work_tickets.main, ["queue", "--worktree", str(checkout), "--repo", "github.com/owner/repo"]


def test_queue_reads_the_door_at_once_and_declares_its_budget(slow_door, tmp_path, fake_git_door,
                                                              fake_processes, monkeypatch):
    """The queue's twelve door calls (the sign-in check, then six listings at once, then the
    blockers at once) wait for the door in three rounds, not twelve: proven by the door's own
    log, as a call ends only once its whole round has started. No wall time is checked."""
    door = SlowDoor(rounds=QUEUE_ROUNDS)
    fake_processes.on("gh", door)
    slow_door["metrics"].unlink(missing_ok=True)
    checkout = queue_checkout(tmp_path, monkeypatch)
    result = run_in_process(queue(checkout), slow_door["env"], monkeypatch)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py queue" and line["gh_calls"] == 11
    assert door.starts() == 12
    assert door_depth(door.events) == 3
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS


def test_queue_reads_the_blockers_its_candidates_name_with_their_own_reads(
        slow_door, tmp_path, fake_git_door, fake_processes, monkeypatch):
    """Candidates whose Blocked by names issues outside the listings: each blocker is read once,
    at once with the candidates' own reads, so the queue still waits for the door in three
    rounds."""
    door = SlowDoor(rounds=BLOCKER_ROUNDS, blockers=True)
    fake_processes.on("gh", door)
    checkout = queue_checkout(tmp_path, monkeypatch)
    result = run_in_process(queue(checkout), slow_door["env"], monkeypatch)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("ready #") == 5
    reads = [event["argv"][1] for event in door.events
             if event["event"] == "start" and event["argv"][:1] == ["api"]]
    blockers = [path.rsplit("/", 1)[-1] for path in reads if path.rsplit("/", 1)[-1] in
                {"11", "12", "13", "14", "15", "20"}]
    assert sorted(blockers) == ["11", "12", "13", "14", "15", "20"]
    assert door_depth(door.events) == 3


def test_paused_reads_the_door_once_and_declares_its_budget(slow_door, fake_git_door, fake_processes,
                                                            monkeypatch):
    """The sign-in check, then one read: two door delays in sequence, proven by the door's own
    log. No wall time is checked: two calls in sequence are what any run waits."""
    door = SlowDoor()
    fake_processes.on("gh", door)
    slow_door["metrics"].unlink(missing_ok=True)
    result = run_in_process(interactive(slow_door["checkout"])["work_tickets.py paused"], slow_door["env"],
                            monkeypatch)
    assert result.returncode == 0, result.stderr
    assert "Not paused" in result.stdout
    line = json.loads(slow_door["metrics"].read_text(encoding="utf-8").splitlines()[-1])
    assert line["command"] == "work_tickets.py paused" and line["gh_calls"] == 1
    assert door_depth(door.events) == 2
    assert line["budget_seconds"] == feedback.INTERACTIVE_SECONDS
