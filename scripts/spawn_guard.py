# se:template se/python-module 1.0.0
"""The spawn guard: a pytest plugin that counts the processes each test starts and refuses a start outside a contract or entry test.

Reader: whoever writes a test, loads the plugin into a Python project's suite, or converts a test
that still starts processes. The rule it enforces is the guidance note `tests-spawn-no-processes`
(guidance/pull-request/field-report/tests-spawn-no-processes.md): a test calls product code in-process; only a door's
contract test or a script's or hook's one entry-point test starts a real process.

What counts as a start, in the test's setup, call and teardown, from any thread of the test
process: `subprocess.Popen` (and so `subprocess.run`, `check_output`, `os.popen` and asyncio's
subprocesses, which all start through it), `os.system`, `os.spawn*`, `os.posix_spawn`,
`os.posix_spawnp` and `os.exec*`. A start inside another (`Popen` through `os.posix_spawn`) counts
once. The setup of a fixture wider than one test (`session`, `package`, `module`, `class` scope)
does not count: one shared repository or one build per run is the remedy, not the defect.

A test may start processes only where it is marked `@pytest.mark.spawns("<reason>")` (or a
module's `pytestmark`) with one of two reasons: `contract: <door>` for a door's contract test,
which proves the real program behaves as the door's fake assumes, or `entry: <script or hook>`
for its one wiring test. Any other test that starts a process is refused, and so is one marked
for another reason; its report names each call: the command and the place that started it, as
`git status (scripts/git_door.py:65, from tests/test_x.py:12)`. A mark without a reason fails.

The shell is a door (scripts/shell_door.py): a start that runs a shell, a command line
(`shell=True`, `os.system`), a shell program (`sh`, `bash`, PowerShell, `cmd`) or a shell script
(`shell_door.is_shell`), is refused in every test but the shell door's contract (`contract: shell,
<what it proves>`) and a shell script's one entry-point test (`entry: scripts/<name>.sh`).

The level (`--spawn-guard`, else the `spawn_guard` ini value, else `error`): under `error` a
refused start fails its test; under `warn`, for a suite whose tests are still being converted, it
is named in the test's report and the summary, and the test passes. There is no baseline: a
suite converts every test and then sets `error`, so no new start comes back.

The run's terminal summary prints one line: the processes started, those in contract and
entry-point tests, those refused and in how many tests, and the shells among them (`spawns: ...`),
under `warn` a second line naming the refused tests by file; under pytest-xdist the controller
adds up its workers' counts, which each test's report carries in its `user_properties` ("spawns").

Loading it: SE's own suite registers it from `tests/conftest.py` (`pytest_addoption`); a Python
project whose se module lies at `.se/modules/se` does the same from its own top-level conftest,
as the guidance note shows. It needs nothing but pytest.
"""

from __future__ import annotations

import importlib.util
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
INI = "spawn_guard"
ERROR, WARN = "error", "warn"
LEVELS = (ERROR, WARN)
CONTRACT = "contract: "
ENTRY = "entry: "
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


def shell_contract(text: str | None) -> bool:
    """Whether a spawns reason marks the shell door's contract (`contract: shell, ...`)."""
    return bool(text) and (text == SHELL_CONTRACT or text.startswith((SHELL_CONTRACT + ",", SHELL_CONTRACT + ";",
                                                                     SHELL_CONTRACT + ":", SHELL_CONTRACT + " ")))


def entry_script(text: str | None) -> str:
    """The script or hook an `entry: <script> ...` reason names, else ""."""
    if not text or not text.startswith(ENTRY):
        return ""
    words = text[len(ENTRY):].split()
    return words[0].rstrip(",;:") if words else ""


def kept(text: str | None) -> bool:
    """Whether a spawns reason is one the guard lets start processes: a door's contract
    (`contract: <door>`) or an entry point's wiring test (`entry: <script or hook>`)."""
    return bool(text) and (text.startswith(CONTRACT) and bool(text[len(CONTRACT):].strip())
                           or bool(entry_script(text)))


def shell_kept(text: str | None) -> bool:
    """Whether a spawns reason lets its test start a shell: the shell door's contract, or the
    one entry-point test of a shell script (`entry: scripts/<name>.sh`)."""
    script = entry_script(text)
    return shell_contract(text) or bool(script) and shell_door.shell_program(script)


def shell_allowed(item: pytest.Item) -> bool:
    """Whether `item` may start a shell (`shell_kept`), for a suite that gives it the real shell."""
    return shell_kept(reason(item))


def reason(item: pytest.Item) -> str | None:
    """`item`'s spawns mark reason, "" for a mark without one, None where it carries none."""
    marker = item.get_closest_marker(MARK)
    if marker is None:
        return None
    text = marker.args[0] if marker.args else marker.kwargs.get("reason", "")
    return str(text).strip()


def refusals(text: str | None, calls: list[str], shells: list[str]) -> list[str]:
    """Why a test phase with these starts, under a mark of reason `text` (None: unmarked), is
    refused: each rule it breaks, its calls listed; none where the guard keeps it."""
    found = []
    if calls and not kept(text):
        why = "no test starts one unmarked" if text is None else \
            f"its mark's reason, {text!r}, is no door's contract (`{CONTRACT}<door>`) or entry point (`{ENTRY}<script>`)"
        found.append((f"started {len(calls)} process(es)", why, calls, REMEDY))
    if shells and not shell_kept(text):
        found.append((f"started {len(shells)} shell(s)", "only the shell door's contract starts one", shells,
                      SHELL_REMEDY))
    return [f"{what}, and {why}:\n" + "\n".join(f"  {call}" for call in listed) + f"\nRemedy: {remedy}."
            for what, why, listed, remedy in found]


class SpawnGuard:
    """The plugin: on each worker it counts and judges the tests; on the controller it adds up."""

    def __init__(self) -> None:
        self.level = ERROR
        self.ran: dict[str, int] = {}  # node id: its starts, for every test that ran (the controller)
        self.counter = Counter()
        self.kept = self.shells = 0
        self.refused: list[str] = []

    def pytest_addoption(self, parser: pytest.Parser) -> None:
        parser.addoption("--spawn-guard", choices=LEVELS, default=None,
                         help=f"what the spawn guard does with a refused start: fail its test (error) or name it "
                              f"in the summary (warn); default the `{INI}` ini value, else error")
        parser.addini(INI, "the spawn guard's level: error (a refused start fails its test) or warn",
                      default=ERROR)

    def pytest_configure(self, config: pytest.Config) -> None:
        config.addinivalue_line("markers", f"{MARK}(reason): this test may start processes, for the reason "
                                           "given: `contract: <door>` or `entry: <script>`")
        self.level = config.getoption("spawn_guard") or str(config.getini(INI)).strip() or ERROR
        if self.level not in LEVELS:
            raise pytest.UsageError(f"{INI} = {self.level!r}: the spawn guard's level is error or warn")
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
        item.stash[REFUSED] = False
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
        text = reason(item)
        if text == "" and call.when == "call":
            self.fail(report, f"{item.nodeid} carries @pytest.mark.{MARK} without a reason; give one "
                              f"(`{CONTRACT}<door>` or `{ENTRY}<script>`)")
        for message in refusals(text, calls, shells):
            item.stash[REFUSED] = True
            message = f"{item.nodeid} {message.replace(', and', f' in its {call.when}, and', 1)}"
            if self.level == ERROR:
                self.fail(report, message)
            else:
                report.sections.append((f"spawn guard ({WARN})", message))
        if call.when == "teardown":
            kind = "refused" if item.stash[REFUSED] else "kept"
            report.user_properties.append((PROPERTY, f"{item.stash[STARTS]}:{kind}:{item.stash[SHELLS]}"))

    @staticmethod
    def fail(report: pytest.TestReport, message: str) -> None:
        if report.failed:
            report.longrepr = f"{report.longrepr}\n\n{message}"
        else:
            report.outcome = "failed"
            report.longrepr = message

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        for name, value in report.user_properties:
            if name != PROPERTY:
                continue
            count, _, rest = str(value).partition(":")
            kind, _, shells = rest.partition(":")
            self.ran[report.nodeid] = int(count)
            self.shells += int(shells or 0)
            if kind == "refused":
                self.refused.append(report.nodeid)
            else:
                self.kept += int(count)

    def pytest_terminal_summary(self, terminalreporter) -> None:
        total = sum(self.ran.values())
        if not self.ran:
            return
        verdict = "failed" if self.level == ERROR else "warned"
        terminalreporter.write_line(
            f"spawns: {total} processes started by {sum(1 for count in self.ran.values() if count)} of "
            f"{len(self.ran)} tests; {self.kept} in contract and entry-point tests, {total - self.kept} refused in "
            f"{len(self.refused)} tests ({verdict}); {self.shells} shells ({OWNER} {self.level})")
        if self.level == WARN and self.refused:
            files: dict[str, int] = {}
            for nodeid in self.refused:
                files[nodeid.split("::", 1)[0]] = files.get(nodeid.split("::", 1)[0], 0) + 1
            terminalreporter.write_line(f"spawns: {WARN}: the refused tests by file, each to convert "
                                        f"(--spawn-guard=error names each call): "
                                        + ", ".join(f"{name} {count}" for name, count in sorted(files.items())))


STARTS = pytest.StashKey[int]()
SHELLS = pytest.StashKey[int]()
REFUSED = pytest.StashKey[bool]()


def started(item: pytest.Item) -> int:
    """The processes `item` started so far, its setup, call and teardown, the running phase included."""
    plugin = guard(item.config)
    running = len(plugin.counter.calls) if plugin is not None and plugin.counter.active else 0
    return item.stash.get(STARTS, 0) + running


def allowed(item: pytest.Item) -> bool:
    """Whether `item` may start processes, for a suite that gives such tests the real programs and
    the others their fakes: a spawns mark with its reason. Under `warn` a mark the guard refuses
    still gets the real programs, so the test runs as it did until it is converted."""
    return bool(reason(item))


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
