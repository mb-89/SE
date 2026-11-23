"""The spawn guard: a pytest plugin that counts the processes each test starts and fails a test that starts one unmarked.

Reader: whoever writes a test, loads the plugin into a Python project's suite, or converts a test
that still starts processes. The rule it enforces is the guidance note `tests-spawn-no-processes`
(guidance/pull-request/field-report/tests-spawn-no-processes.md): a test calls product code in-process; only a door's
contract test, a script's or hook's one entry-point test, or a test marked with its reason starts
a real process.

What counts as a start, in the test's setup, call and teardown, from any thread of the test
process: `subprocess.Popen` (and so `subprocess.run`, `check_output`, `os.popen` and asyncio's
subprocesses, which all start through it), `os.system`, `os.spawn*`, `os.posix_spawn`,
`os.posix_spawnp` and `os.exec*`. A start inside another (`Popen` through `os.posix_spawn`) counts
once. The setup of a fixture wider than one test (`session`, `package`, `module`, `class` scope)
does not count: one shared repository or one build per run is the remedy, not the defect.

A test may start processes where it is
- marked `@pytest.mark.spawns("<reason>")` (or a module's `pytestmark`), the reason non-empty:
  `contract: <door>` for a door's contract test, `entry: <script or hook>` for its one entry-point
  test, anything else a justification read at review;
- named in the baseline (`spawn_baseline` ini, default `tests/spawn-baseline.yaml`), the tests not
  converted yet. The baseline may only shrink: `--spawn-baseline=write` rewrites it from this run,
  dropping each entry that ran, passed and started nothing, and each one of a file that ran whole
  (no `-k`, no `-m`) that names no test of it any more, and never adds a test (it runs each
  listed test as converted, `allowed`, so a suite hands it its fakes); `--spawn-baseline=init`
  writes it from scratch, once, where none exists. A baseline entry that ran and started nothing
  fails, naming the remedy, so a converted test leaves the baseline in its own change.

Any other test that starts a process fails, its report naming each call: the command and the
place that started it, as `git status (scripts/git_door.py:65, from tests/test_x.py:12)`.

The shell is a door (scripts/shell_door.py): a start that runs a shell, a command line
(`shell=True`, `os.system`), a shell program (`sh`, `bash`, PowerShell, `cmd`) or a shell script
(`shell_door.is_shell`), is refused in every test but the shell door's contract, a test marked
`contract: shell, <what it proves>`; neither another mark nor the baseline lets a test start one.

The run's terminal summary prints one line: the processes started, in marked and in baseline
tests, the shells among them, and the tests that failed for one (`spawns: ...`); under pytest-xdist the controller adds
up its workers' counts, which each test's report carries in its `user_properties` ("spawns").

Loading it: SE's own suite registers it from `tests/conftest.py` (`pytest_addoption`); a Python
project whose se module lies at `.se/modules/se` does the same from its own top-level conftest,
as the guidance note shows. It needs nothing but pytest.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sysconfig
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pytest

MARK = "spawns"
NAME = "spawn-guard"
INI = "spawn_baseline"
DEFAULT_BASELINE = "tests/spawn-baseline.yaml"
PROPERTY = "spawns"
OWNER = "scripts/spawn_guard.py"
NOTE = "the guidance note tests-spawn-no-processes"
SHELL_CONTRACT = "contract: shell"
SHELL_REMEDY = (f"the shell is a door (scripts/shell_door.py) and a test never starts one: run the code "
                f"under test with the door's fake (the fake_shell fixture), or, for the shell door's "
                f"contract, mark the test @pytest.mark.{MARK}(\"{SHELL_CONTRACT}, <what it proves>\"); {NOTE} "
                f"says how")
REMEDY = (f"call the code in-process (a script through its `main(argv)`, git through its fake), or, "
          f"for a door's contract or a script's one entry-point test, mark it "
          f"@pytest.mark.{MARK}(\"contract: <door>\" or \"entry: <script>\"); {NOTE} says how")

# The os functions that start a process, beside subprocess.Popen, where this platform has them.
OS_STARTS = ("system", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp",
             "spawnvpe", "posix_spawn", "posix_spawnp", "execl", "execle", "execlp", "execlpe", "execv",
             "execve", "execvp", "execvpe")
SKIPPED_PATHS = tuple(str(Path(path)) for path in {sysconfig.get_paths()["stdlib"],
                                                   sysconfig.get_paths()["purelib"],
                                                   sysconfig.get_paths()["platlib"]})


def _load_shell_door():
    """scripts/shell_door.py beside this file, which owns what a shell is, loaded by its path so a
    project that loads this plugin from its se module needs nothing on its path."""
    spec = importlib.util.spec_from_file_location("_spawn_guard_shell_door", Path(__file__).with_name("shell_door.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell_door = _load_shell_door()


@dataclass
class Counter:
    """The starts of one session's running test; `paused` while a wider fixture sets up."""

    calls: list[str] = field(default_factory=list)
    shells: list[str] = field(default_factory=list)  # the calls among them that started a shell
    active: bool = False
    paused: int = 0

    def record(self, command: str, shell: bool = False) -> None:
        if self.active and not self.paused:
            self.calls.append(f"{command} ({where()})")
            if shell:
                self.shells.append(self.calls[-1])

    def take(self) -> tuple[list[str], list[str]]:
        """The calls since the last take, and the shells among them."""
        calls, shells, self.calls, self.shells = self.calls, self.shells, [], []
        return calls, shells


# The counters of the sessions running in this process, innermost last: a test that runs pytest
# in-process (pytester) opens a session of its own, whose tests count their own starts.
COUNTERS: list[Counter] = []
_original: dict[str, object] = {}  # the starts `install` replaced, by name
POPEN = "Popen._execute_child"
_depth = threading.local()


def where() -> str:
    """The place that started the process: the innermost frame outside the standard library,
    installed packages, pytest and this file, and the innermost frame of a test file (`test_*`,
    `conftest*`) where that differs."""
    frames = [frame for frame in traceback.extract_stack()[:-3]
              if not frame.filename.startswith(SKIPPED_PATHS) and Path(frame.filename).name != Path(__file__).name
              and "_pytest" not in frame.filename and "pluggy" not in frame.filename]
    if not frames:
        return "unknown place"
    inner = frames[-1]
    tests = [frame for frame in frames if Path(frame.filename).name.startswith(("test_", "conftest"))]
    text = f"{relative(inner.filename)}:{inner.lineno}"
    if tests and tests[-1] is not inner:
        text += f", from {relative(tests[-1].filename)}:{tests[-1].lineno}"
    return text


def relative(filename: str) -> str:
    path = Path(filename)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def command_text(argv) -> str:
    """A start's command: its program's name and up to three arguments, a script by its file
    name; a shell command line (`shell=True`, `os.system`) as `shell: <its first line>`."""
    if isinstance(argv, bytes):
        argv = os.fsdecode(argv)
    if isinstance(argv, str):
        line = argv.strip().splitlines()[0] if argv.strip() else ""
        return f"shell: {line[:60]}" + (" ..." if len(line) > 60 or "\n" in argv.strip() else "")
    if isinstance(argv, os.PathLike):
        argv = [argv]
    words = [os.fsdecode(word) if isinstance(word, (bytes, os.PathLike)) else str(word) for word in argv]
    if not words:
        return "(empty command)"
    words = [Path(word).name if index == 0 or word.endswith((".py", ".sh", ".ps1", ".js")) else word
             for index, word in enumerate(words)]
    return " ".join(words[:4]) + (" ..." if len(words) > 4 else "")


def counted(name: str, command, shell=lambda arguments, options: False):
    """The start `_original[name]`, each call recorded on the innermost counter once, by
    `command(arguments)` and whether `shell(arguments, options)` says it starts a shell, however
    many starts it makes inside (`subprocess.Popen` through `os.posix_spawn`). It looks the start
    up at each call, so a test of this plugin can stand a fake in for it."""

    def wrapper(*arguments, **options):
        depth = getattr(_depth, "value", 0)
        if not depth and COUNTERS:
            COUNTERS[-1].record(command(arguments), bool(shell(arguments, options)))
        _depth.value = depth + 1
        try:
            return _original[name](*arguments, **options)
        finally:
            _depth.value = depth

    wrapper.__wrapped__ = _original[name]
    return wrapper


def argument_list(arguments: tuple, at: int) -> list:
    """The program and its arguments of an `os.spawn*` or `os.exec*` call whose path is at
    `at - 1`: a list (`spawnv`, `execv`) or the rest of the call (`spawnl`, `execl`)."""
    rest = arguments[at:]
    if rest and not isinstance(rest[0], (str, bytes, os.PathLike)):
        return list(rest[0])
    return [arguments[at - 1], *rest[1:]] if rest else [arguments[at - 1]]


def popen_shell(arguments: tuple, options: dict) -> bool:
    """Whether a `Popen._execute_child(self, args, executable, ..., shell, ...)` call starts a
    shell: its command, its `shell` flag (the eleventh argument) or its `executable`."""
    shell = arguments[10] if len(arguments) > 10 else options.get("shell", False)
    executable = arguments[2] if len(arguments) > 2 else options.get("executable")
    return shell_door.is_shell(arguments[1], bool(shell)) or bool(executable) and shell_door.shell_program(executable)


def install() -> None:
    """Count the process starts of this process from now on; installing twice changes nothing."""
    if _original:
        return
    _original[POPEN] = subprocess.Popen._execute_child
    subprocess.Popen._execute_child = counted(POPEN, lambda arguments: command_text(arguments[1]), popen_shell)
    for name in OS_STARTS:
        start = getattr(os, name, None)
        if start is None:
            continue
        _original[name] = start
        if name == "system":
            command = lambda arguments: command_text(arguments[0])  # noqa: E731
            shell = lambda arguments, options: True  # noqa: E731
        elif name.startswith("spawn"):
            command = lambda arguments: command_text(argument_list(arguments, 2))  # noqa: E731
            shell = lambda arguments, options: shell_door.is_shell(argument_list(arguments, 2))  # noqa: E731
        elif name.startswith("posix_spawn"):
            command = lambda arguments: command_text(arguments[1])  # noqa: E731
            shell = lambda arguments, options: (shell_door.shell_program(arguments[0])  # noqa: E731
                                                or shell_door.is_shell(arguments[1]))
        else:
            command = lambda arguments: command_text(argument_list(arguments, 1))  # noqa: E731
            shell = lambda arguments, options: shell_door.is_shell(argument_list(arguments, 1))  # noqa: E731
        setattr(os, name, counted(name, command, shell))


def uninstall() -> None:
    """Undo `install`."""
    for name, start in _original.items():
        if name == POPEN:
            subprocess.Popen._execute_child = start
        else:
            setattr(os, name, start)
    _original.clear()


# The baseline: a YAML mapping of node ids, quoted as JSON strings (valid YAML), to the processes
# each started when it was written; read without a YAML library, so any project can load it.
HEADER = (f"# Tests still allowed to start processes, not converted yet ({OWNER}).\n"
          f"# Generated: `pytest --spawn-baseline=write` drops each entry that ran and started none; it\n"
          f"# never adds one. Convert a test and its entry goes; {NOTE} says how.\n")


def read_baseline(path: Path) -> dict[str, int]:
    """The baseline at `path`, node id to its starts; none where the file is missing."""
    if not path.exists():
        return {}
    entries: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#") or text in ("tests:", "tests: {}"):
            continue
        key, separator, value = text.rpartition(": ")
        try:
            entries[json.loads(key)] = int(value)
        except (ValueError, TypeError):
            raise pytest.UsageError(f"{path}:{number}: not a baseline entry `\"<node id>\": <starts>`; "
                                    f"write the file with `pytest --spawn-baseline=write`") from None
        if not separator:
            raise pytest.UsageError(f"{path}:{number}: not a baseline entry")
    return entries


def write_baseline(path: Path, entries: dict[str, int]) -> None:
    lines = [HEADER, "tests:\n" if entries else "tests: {}\n"]
    lines += [f"  {json.dumps(name)}: {count}\n" for name, count in sorted(entries.items())]
    path.write_text("".join(lines), encoding="utf-8")


def shell_contract(text: str | None) -> bool:
    """Whether a spawns reason marks the shell door's contract (`contract: shell, ...`)."""
    return bool(text) and (text == SHELL_CONTRACT or text.startswith((SHELL_CONTRACT + ",", SHELL_CONTRACT + ";",
                                                                     SHELL_CONTRACT + ":", SHELL_CONTRACT + " ")))


def shell_allowed(item: pytest.Item) -> bool:
    """Whether `item` may start a shell: it is part of the shell door's contract."""
    return shell_contract(reason(item))


def reason(item: pytest.Item) -> str | None:
    """`item`'s spawns mark reason, "" for a mark without one, None where it carries none."""
    marker = item.get_closest_marker(MARK)
    if marker is None:
        return None
    text = marker.args[0] if marker.args else marker.kwargs.get("reason", "")
    return str(text).strip()


class SpawnGuard:
    """The plugin: on each worker it counts and judges the tests; on the controller it adds up."""

    def __init__(self) -> None:
        self.baseline_path: Path | None = None
        self.baseline: dict[str, int] = {}
        self.mode = ""
        self.ran: dict[str, int] = {}  # node id: its starts, for every test that ran (the controller)
        self.kinds: dict[str, str] = {}  # node id: "marked", "listed" or ""
        self.failed: set[str] = set()  # the tests that failed a phase (the controller)
        self.written: tuple[int, int] | None = None
        self.counter = Counter()
        self.marked = self.listed = self.shells = 0
        self.refused: list[str] = []

    def pytest_addoption(self, parser: pytest.Parser) -> None:
        parser.addoption("--spawn-baseline", choices=("check", "write", "init"), default="check",
                         help="the spawn guard's baseline: check it (default); write it from this run, "
                              "only shrinking; or init it where none exists")
        parser.addini(INI, "the spawn guard's baseline of tests still allowed to start processes",
                      default=DEFAULT_BASELINE)

    def pytest_configure(self, config: pytest.Config) -> None:
        config.addinivalue_line("markers", f"{MARK}(reason): this test may start processes, for the reason "
                                           "given: `contract: <door>`, `entry: <script>` or a justification")
        self.mode = config.getoption("spawn_baseline")
        self.baseline_path = config.rootpath / config.getini(INI)
        if self.mode == "init" and self.baseline_path.exists():
            raise pytest.UsageError(f"--spawn-baseline=init: {self.baseline_path} exists, and the baseline may only "
                                    "shrink; write it with --spawn-baseline=write")
        self.baseline = {} if self.mode == "init" else read_baseline(self.baseline_path)
        install()
        COUNTERS.append(self.counter)

    def pytest_unconfigure(self) -> None:
        if self.counter in COUNTERS:
            COUNTERS.remove(self.counter)
        if not COUNTERS:
            uninstall()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        wide = fixturedef.scope != "function"
        self.counter.paused += wide
        try:
            yield
        finally:
            self.counter.paused -= wide

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem):
        item.stash[STARTS] = 0
        item.stash[SHELLS] = 0
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_setup(self, item):
        self.counter.take()
        self.counter.active = True
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call):
        outcome = yield
        report = outcome.get_result()
        calls, shells = self.counter.take()
        if call.when == "teardown":
            self.counter.active = False
        item.stash[STARTS] = item.stash.get(STARTS, 0) + len(calls)
        item.stash[SHELLS] = item.stash.get(SHELLS, 0) + len(shells)
        allowed = reason(item)
        if allowed == "" and call.when == "call":
            self.fail(report, f"{item.nodeid} carries @pytest.mark.{MARK} without a reason; give one "
                              "(`contract: <door>`, `entry: <script>` or a justification)")
        elif calls and allowed is None and item.nodeid not in self.baseline and self.mode != "init":
            listing = "\n".join(f"  {text}" for text in calls)
            self.fail(report, f"{item.nodeid} started {len(calls)} process(es) in its {call.when}, and no test "
                              f"starts one unmarked:\n{listing}\nRemedy: {REMEDY}.")
        if shells and not shell_contract(allowed) and self.mode != "init":
            listing = "\n".join(f"  {text}" for text in shells)
            self.fail(report, f"{item.nodeid} started {len(shells)} shell(s) in its {call.when}, and only the shell "
                              f"door's contract starts one:\n{listing}\nRemedy: {SHELL_REMEDY}.")
        if call.when == "teardown":
            starts = item.stash[STARTS]
            listed = item.nodeid in self.baseline or self.mode == "init"
            refused_shell = item.stash[SHELLS] and not shell_contract(allowed) and self.mode != "init"
            kind = "" if refused_shell else "marked" if allowed else "listed" if listed else ""
            report.user_properties.append((PROPERTY, f"{starts}:{kind}:{item.stash[SHELLS]}"))
            if not starts and item.nodeid in self.baseline and allowed is None and self.mode == "check" \
                    and not report.failed:
                self.fail(report, f"{item.nodeid} is in the spawn baseline {self.baseline_path} and started no "
                                  "process: remove its entry (`pytest --spawn-baseline=write` drops it)")

    @staticmethod
    def fail(report: pytest.TestReport, message: str) -> None:
        if report.failed:
            report.longrepr = f"{report.longrepr}\n\n{message}"
        else:
            report.outcome = "failed"
            report.longrepr = message

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.failed:
            self.failed.add(report.nodeid)
        for name, value in report.user_properties:
            if name != PROPERTY:
                continue
            count, _, rest = str(value).partition(":")
            kind, _, shells = rest.partition(":")
            self.ran[report.nodeid] = int(count)
            self.kinds[report.nodeid] = kind
            self.shells += int(shells or 0)
            if int(count):
                self.marked += int(count) if kind == "marked" else 0
                self.listed += int(count) if kind == "listed" else 0
                if not kind:
                    self.refused.append(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if hasattr(session.config, "workerinput") or self.mode == "check" or self.baseline_path is None:
            return
        unmarked = {name: count for name, count in self.ran.items() if count and self.kinds.get(name) != "marked"}
        if self.mode == "init":
            kept = unmarked
        else:
            # An entry that did not run stays, unless its file ran whole: then its test is gone.
            whole = not (session.config.option.keyword or session.config.option.markexpr)
            files = {name.split("::", 1)[0] for name in self.ran} if whole else set()
            kept = {name: unmarked.get(name, count) for name, count in self.baseline.items()
                    if name in unmarked or name in self.failed
                    or name not in self.ran and name.split("::", 1)[0] not in files}
        write_baseline(self.baseline_path, kept)
        self.written = (len(kept), len(self.baseline))

    def pytest_terminal_summary(self, terminalreporter) -> None:
        total = sum(self.ran.values())
        if not self.ran:
            return
        terminalreporter.write_line(
            f"spawns: {total} processes started by {sum(1 for count in self.ran.values() if count)} of "
            f"{len(self.ran)} tests; {self.marked} in marked tests, {self.listed} in baseline tests, "
            f"{total - self.marked - self.listed} refused in {len(self.refused)} tests; {self.shells} shells "
            f"({OWNER})")
        if self.written is not None:
            terminalreporter.write_line(f"spawns: wrote {self.baseline_path} with {self.written[0]} entries "
                                        f"(it held {self.written[1]})")


STARTS = pytest.StashKey[int]()
SHELLS = pytest.StashKey[int]()


def started(item: pytest.Item) -> int:
    """The processes `item` started so far, its setup, call and teardown, the running phase included."""
    plugin = guard(item.config)
    running = len(plugin.counter.calls) if plugin is not None and plugin.counter.active else 0
    return item.stash.get(STARTS, 0) + running


def allowed(item: pytest.Item) -> bool:
    """Whether `item` may start processes, for a suite that gives such tests the real programs and
    the others their fakes: a spawns mark with its reason, or a baseline entry outside
    `--spawn-baseline=write`, which tries each listed test as converted."""
    plugin = guard(item.config)
    listed = plugin is not None and (item.nodeid in plugin.baseline and plugin.mode != "write"
                                     or plugin.mode == "init")
    return bool(reason(item)) or listed


def guard(config: pytest.Config) -> SpawnGuard | None:
    """The guard registered with `config`, by `register` or handed to pytest as a plugin object."""
    return next((plugin for plugin in config.pluginmanager.get_plugins() if isinstance(plugin, SpawnGuard)), None)


def register(pluginmanager: pytest.PytestPluginManager) -> SpawnGuard:
    """Register the plugin once, from a conftest's `pytest_addoption(parser, pluginmanager)`."""
    plugin = pluginmanager.get_plugin(NAME)
    if plugin is None:
        plugin = SpawnGuard()
        pluginmanager.register(plugin, NAME)
    return plugin
