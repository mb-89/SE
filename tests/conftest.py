"""Shared fixtures of se's suite."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402
import se_plugin  # noqa: E402
import fake_git  # noqa: E402
import git_door  # noqa: E402
import fake_processes as fake_programs  # noqa: E402
import process_door  # noqa: E402
import network_guard  # noqa: E402
import se_modules  # noqa: E402
import shell_door  # noqa: E402
import spawn_guard  # noqa: E402
import time_bound  # noqa: E402
import waiting  # noqa: E402

# The test process reaches nothing beyond this machine, its collection included (tests/network_guard.py).
network_guard.install()

# The suite's runs of work_tickets.py and se_start.py measure themselves (scripts/metrics.py); their
# lines go nowhere, never into the machine's ~/.se/metrics.jsonl. A test of the lines sets its own.
os.environ["SE_METRICS"] = os.devnull

# The suite's commands run directly, never through a kern that serves this checkout (docs/start.md "Commands
# as components"): a test's fakes live in its own process. A test of the routing sets its own.
os.environ["SE_KERN"] = "off"

# The suite lists no host's repositories (scripts/se_modules.py `host_listing`): a component is read
# directly beside its remote, and a test of the finder sets its fake listing.
os.environ[se_modules.LISTING_VARIABLE] = "off"

# What a CI runner or a cloud session sets and a local machine does not: GitHub Actions' variables,
# Claude Code's cloud mark and SE's cloud agent, which switch commands to their runner behaviour
# (`start` a cloud start, `capacity` the cloud's worker limit), and the environment's default
# agent, which adds a sentence to the start's hand-over.
RUNNER_VARIABLES = ("CI", "CLAUDE_CODE_REMOTE", "SE_CLOUD_AGENT", "SE_DEFAULT_AGENT")
RUNNER_PREFIX = "GITHUB_"


def runner_variables(environment: Mapping[str, str]) -> list[str]:
    """The names in `environment` that a runner sets (RUNNER_VARIABLES, every GITHUB_*)."""
    return [name for name in environment if name in RUNNER_VARIABLES or name.startswith(RUNNER_PREFIX)]


# Every test runs in a home of its own (`own_home`), its session and module fixtures in one of the
# suite's (`suite_home`), so none reads the developer's home, config or credentials (~/.gitconfig,
# gh's login, uv's or npm's config, ~/.se) and what one writes under ~ is its own. What the
# machine's tools keep only to run faster, and which holds no config or credential, stays where
# the machine keeps it: uv's cache and the Pythons uv installed, Go's build and module caches (the
# toolchain go.mod asks for among them), npm's cache and Playwright's browsers. Their places are
# read here, once, before any home moves, into the variables that name them, so an obs build or a
# `go run` in a test neither downloads nor builds everything again; one already set keeps its value.
HOME_VARIABLES = ("HOME", "USERPROFILE")
XDG_VARIABLES = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")
GIT_CONFIG_VARIABLES = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")


def machine_caches(environ: Mapping[str, str], platform: str = sys.platform) -> dict[str, str]:
    """Where the machine's tools keep their caches, by the variable that names each, as each tool
    finds it where the variable is unset: under the home `environ` names (USERPROFILE on Windows),
    its XDG folders on Linux, Library/Caches on macOS and LOCALAPPDATA and APPDATA on Windows."""
    windows, mac = platform == "win32", platform == "darwin"
    home = Path(environ.get("USERPROFILE" if windows else "HOME") or Path.home())
    local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
    cache = Path(environ.get("XDG_CACHE_HOME") or home / ".cache")
    data = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    user_cache = local if windows else home / "Library" / "Caches" if mac else cache  # Go's os.UserCacheDir
    gopath = environ.get("GOPATH") or str(home / "go")
    return {
        "UV_CACHE_DIR": str(local / "uv" / "cache" if windows else cache / "uv"),
        "UV_PYTHON_INSTALL_DIR": str(roaming / "uv" / "data" / "python" if windows else data / "uv" / "python"),
        "GOCACHE": str(user_cache / "go-build"),
        "GOPATH": gopath,
        "GOMODCACHE": str(Path(gopath.split(os.pathsep)[0]) / "pkg" / "mod"),
        "npm_config_cache": str(local / "npm-cache" if windows else home / ".npm"),
        "PLAYWRIGHT_BROWSERS_PATH": str(user_cache / "ms-playwright"),
    }


for _name, _place in machine_caches(os.environ).items():
    if not any(name.casefold() == _name.casefold() for name in os.environ):  # npm reads NPM_CONFIG_CACHE too
        os.environ[_name] = _place

# The machine's home as the session found it, for the suite's setup that fetches and builds its
# modules through the machine's git, uv and gh (the obs fixture), and for nothing else.
MACHINE_HOME = {name: os.environ.get(name) for name in (*HOME_VARIABLES, *XDG_VARIABLES, *GIT_CONFIG_VARIABLES)}

# obs's machine folder, where its components are installed (obs's `local_folder`, which reads this
# variable): the suite's own, in the checkout beside its obs module, never the developer's
# ~/.config/obs, so every build of the suite runs the adapter obs-html the obs fixture installed
# there, whatever the developer installed. A test of obs's lookup sets its own.
os.environ["OBS_LOCAL_FOLDER"] = str(ROOT / ".se" / "obs-local")


def use_home(patch: pytest.MonkeyPatch, home: Path) -> None:
    """Point `patch`'s environment at `home`, an empty folder: HOME and USERPROFILE name it, the XDG
    folders are unset, so each tool finds its own under it, and git reads no global configuration
    beyond `home`'s nor the system's."""
    for name in HOME_VARIABLES:
        patch.setenv(name, str(home))
    for name in XDG_VARIABLES:
        patch.delenv(name, raising=False)
    patch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    patch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def use_machine_home(patch: pytest.MonkeyPatch) -> None:
    """Point `patch`'s environment back at the machine's home as the session found it (MACHINE_HOME)."""
    for name, value in MACHINE_HOME.items():
        if value is None:
            patch.delenv(name, raising=False)
        else:
            patch.setenv(name, value)


@pytest.fixture(scope="session", autouse=True)
def suite_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """The home of the session's and the modules' fixtures, which run before any test's own."""
    with pytest.MonkeyPatch.context() as patch:
        home = tmp_path_factory.mktemp("suite-home")
        use_home(patch, home)
        yield home


@pytest.fixture(autouse=True)
def own_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """This test's home, a fresh empty folder beside its tmp_path (not in it, as many a test reads
    all of tmp_path): what it writes under ~ is its own. A test that sets HOME itself wins."""
    with pytest.MonkeyPatch.context() as patch:
        home = tmp_path_factory.mktemp("home")
        use_home(patch, home)
        yield home


@pytest.fixture(scope="session", autouse=True)
def local_machine() -> Iterator[None]:
    """Every test runs as on a local machine, whatever runs the suite: the runner's variables are
    cleared for the session, before any fixture, so the suite behaves on GitHub's runner as it does
    locally. A test that needs one sets it itself (`monkeypatch.setenv`)."""
    with pytest.MonkeyPatch.context() as patch:
        for name in runner_variables(os.environ):
            patch.delenv(name)
        yield


# Real git behind the door (scripts/git_door.py) only for the test files named here, with their
# reason; every other test's git is refused unless it installs the fake (`fake_git_door`), so "only
# the door's contract suite touches real git" is enforced, not counted. A git subprocess that does
# not pass the door is scripts/hygiene.py's git-door check's to find. The list may only shrink.
REAL_GIT: dict[str, str] = {
    "tests/test_git_door.py": "the door's contract, held against real git",
}


class RefusedGit:
    """The door's backend outside REAL_GIT: every git command fails the test that ran it, naming
    the command and the remedy; a pytest failure, so no `except Exception` of the code under test
    swallows it."""

    def __init__(self, test: str) -> None:
        self.test = test

    def refuse(self, argv: list[str]):
        pytest.fail(f"{self.test} ran real git (git {' '.join(argv)}); take the fake_git_door fixture "
                    "(tests/fake_git.py), or name the file in tests/conftest.py REAL_GIT", pytrace=False)

    def run(self, argv: list[str], **_) -> subprocess.CompletedProcess[bytes]:
        self.refuse(argv)

    def popen(self, argv: list[str], **_) -> subprocess.Popen:
        self.refuse(argv)


def door_backend(item: pytest.Item) -> git_door.Backend:
    """What the door runs for `item`, its setup and teardown included: real git for a file in
    REAL_GIT, otherwise RefusedGit."""
    return git_door.RealGit() if item_file(item) in REAL_GIT else RefusedGit(item.nodeid)


def door_variable(item: pytest.Item) -> str:
    """What the door's variable tells the child processes `item` starts (scripts/git_door.py
    `from_environment`): real git for a file in REAL_GIT, otherwise refused, so a child reaches
    git only through the fake its test hands it (`shared_fake_git`)."""
    return "real" if isinstance(door_backend(item), git_door.RealGit) else "refused"


def process_backend(item: pytest.Item) -> process_door.Backend:
    """What the process door (scripts/process_door.py) runs for `item`: the real programs for a test
    the spawn guard lets start them (a `spawns` mark, or the baseline), else the fake
    (tests/fake_processes.py), which answers SE's scripts and hooks in-process and the test's
    handlers (the `fake_processes` fixture) for the rest."""
    return process_door.RealProcesses() if spawn_guard.allowed(item) else fake_programs.FakeProcesses()


def shell_backend(item: pytest.Item) -> shell_door.Backend:
    """What the shell door (scripts/shell_door.py) runs for `item`: the real shell for a test the
    spawn guard lets start processes (a `spawns` mark; the guard judges whether a shell may be among
    them), else the fake (tests/fake_processes.py), which answers by the test's handlers (the
    `fake_shell` fixture)."""
    if spawn_guard.allowed(item):
        return shell_door.RealShell()
    return fake_programs.FakeProcesses(scripts=False, hooks=False)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem):
    with git_door.use(door_backend(item)), process_door.use(process_backend(item)), \
            shell_door.use(shell_backend(item)), \
            network_guard.running(item.nodeid), pytest.MonkeyPatch.context() as patch:
        patch.setenv(git_door.VARIABLE, door_variable(item))
        yield


# The fake behind a state file (`shared_fake_git`) is for a test whose child processes run git, or
# whose git runs hooks, which only the state file runs (in this process through the process door's
# fake, tests/fake_processes.py): it costs about 3 ms a git call, the fake in memory
# (`fake_git_door`) about 0.15 ms. So a test that ran git through the state file, ran no hook and
# started no child process (as the spawn guard counts them, scripts/spawn_guard.py `started`)
# fails at its teardown, naming the remedy, unless its file is named here with its reason. The
# list may only shrink.
IN_PROCESS_STATE_FILE: dict[str, str] = {
}
def item_file(item: pytest.Item) -> str:
    """`item`'s file, relative to se's root where it lies inside it."""
    path = Path(item.path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


class WatchedStateFile(fake_git.StateFile):
    """The state file of `shared_fake_git`, counting the git commands this process runs through it."""

    runs = 0

    def run(self, argv: list[str], **options) -> subprocess.CompletedProcess[bytes]:
        self.runs += 1
        return super().run(argv, **options)


def state_file_refusal(item: pytest.Item, state: WatchedStateFile) -> str:
    """Why `item` may not have taken the state file, or "" where it may: it ran git through it, ran
    no hook and started no child process, and its file is not in IN_PROCESS_STATE_FILE."""
    started = spawn_guard.started(item)
    if not state.runs or started or state.hooks_run or item_file(item) in IN_PROCESS_STATE_FILE:
        return ""
    return (f"{item.nodeid} ran git through the state file ({state.runs} commands, shared_fake_git), ran no "
            "hook and started no child process; take the fake_git_door fixture, the fake in memory, or name the "
            "file in tests/conftest.py IN_PROCESS_STATE_FILE with its reason")


class GuardReports:
    """Fails each test phase that tried to reach beyond this machine (tests/network_guard.py
    `fail`) and explains a test past its time bound (tests/time_bound.py `explain`). A plugin
    `pytest_configure` registers, not a hook of this conftest's own: pytest calls a conftest's
    `pytest_runtest_makereport` only for the tests under its folder, and a run may name a test
    file outside it."""

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call):
        outcome = yield
        report = outcome.get_result()
        network_guard.fail(report)
        time_bound.explain(item, report)


@pytest.hookimpl(optionalhook=True)
def pytest_handlecrashitem(crashitem: str, report: pytest.TestReport, sched) -> None:
    """A test that ended its pytest-xdist worker fails once, by name (tests/time_bound.py `crashed`)."""
    time_bound.crashed(crashitem, report, sched)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every collected test gets its time bound (tests/time_bound.py), one outside tests/ too."""
    time_bound.mark(items, OBS_LOCK_WAIT_SECONDS)


@pytest.fixture
def fake_git_door() -> Iterator[fake_git.FakeGit]:
    """git behind the door is the fake for this test (tests/fake_git.py, held to real git by
    tests/test_git_door.py); what the test and the code under test run reaches no real git."""
    with git_door.use(fake_git.FakeGit()) as fake:
        yield fake


@pytest.fixture
def fake_processes() -> fake_programs.FakeProcesses:
    """The process door's fake of this test (tests/fake_processes.py), for its handlers: `gh`'s
    answers, a suite command; SE's scripts and hooks it answers in-process by itself. A test the
    spawn guard lets start processes runs the real programs and cannot take it."""
    backend = process_door.BACKEND
    if not isinstance(backend, fake_programs.FakeProcesses):
        pytest.fail("fake_processes: this test runs the real programs (a spawns mark); drop the mark to take the "
                    "fake", pytrace=False)
    return backend


@pytest.fixture
def fake_shell() -> fake_programs.FakeProcesses:
    """The shell door's fake of this test (tests/fake_processes.py), for its handlers: each shell
    the code under test starts (`sh RUNME.sh`, a command line) answered by `fake_shell.on(...)`; a
    shell no handler answers fails the test, naming it. The shell door's contract (`contract:
    shell`) runs the real shell and cannot take it."""
    backend = shell_door.BACKEND
    if not isinstance(backend, fake_programs.FakeProcesses):
        pytest.fail("fake_shell: this test runs the real shell (a spawns mark); drop the mark to take the fake",
                    pytrace=False)
    return backend


@pytest.fixture
def shared_fake_git(request: pytest.FixtureRequest, tmp_path: Path,
                    monkeypatch: pytest.MonkeyPatch) -> Iterator[fake_git.StateFile]:
    """The fake for this test and every child process it starts: its state in a file that the
    door's variable names (`SE_GIT_DOOR=fake:<file>`, read by scripts/git_door.py and kern's
    kern/git alike), so a script run as a process or a kern binary reaches the same fake. A test
    that starts no child process takes `fake_git_door` instead (IN_PROCESS_STATE_FILE)."""
    state = WatchedStateFile(tmp_path / "git-door.json")
    monkeypatch.setenv(git_door.VARIABLE, f"fake:{state.path}")
    with git_door.use(state):
        yield state
    refusal = state_file_refusal(request.node, state)
    if refusal:
        pytest.fail(refusal, pytrace=False)


@pytest.fixture
def door_fake(request: pytest.FixtureRequest) -> fake_git.FakeGit | fake_git.StateFile:
    """The fake a fixture builds a test's repositories on: the state file where the test or one of
    its fixtures takes `shared_fake_git`, as its child processes run git, else the fake in memory
    (`fake_git_door`)."""
    shared = "shared_fake_git" in request.fixturenames
    return request.getfixturevalue("shared_fake_git" if shared else "fake_git_door")


# How long the obs fixture waits for another worker's clone and build of obs (its lock); a test that
# takes it gets this on top of its time bound (tests/time_bound.py).
OBS_LOCK_WAIT_SECONDS = 600


@pytest.fixture(scope="session")
def obs() -> Path:
    """The obs module at its pin with its environment built and its adapter component obs-html
    installed, once per checkout at a time.

    The suite's workers run test files in parallel (pyproject.toml), and every obs build syncs the module
    and runs it through uv: a fresh checkout must clone and build it once, never twice at once. The
    lock is the operating system's on a file (`waiting.exclusive`), which wakes the next worker as
    the build ends and lets go where its holder dies.
    """
    with contextlib.ExitStack() as held:
        try:
            held.enter_context(waiting.exclusive(ROOT / ".se" / "obs-setup.flock", OBS_LOCK_WAIT_SECONDS))
        except TimeoutError as error:
            pytest.fail(str(error))
        # Bringing SE's own checkout's obs module to its pin and building it is the suite's setup,
        # not a test: it fetches the real module through real git and runs the real programs, in the
        # machine's home, whose git configuration and gh login reach the module's and the adapter's
        # remotes; it installs the adapter into the suite's obs folder (OBS_LOCAL_FOLDER above).
        with pytest.MonkeyPatch.context() as patch, process_door.use(process_door.RealProcesses()):
            use_machine_home(patch)
            patch.setenv(git_door.VARIABLE, "real")
            directory = build_docs.obs_dir()
            subprocess.run(["uv", "sync", "--quiet", "--project", str(directory)], cwd=ROOT, check=True,
                           env=build_docs.child_environment())
            # The adapter component every build runs through, installed where it is missing, as a
            # build installs it: once here, so no test's build waits for it.
            adapter, refusal = build_docs.ready_adapter(directory)
        if adapter is None:
            pytest.fail(refusal)
        os.environ[build_docs.OBS_VARIABLE] = str(directory)  # the builds of the tests that take it
        return directory


# kern, the Go core, at the pin se.toml [components.kern] reads from components/go.mod (docs/modules.md
# "Modules"): placed before collection, as tests read its files while they are collected
# (tests/test_se_home.py TABLE, tests/test_se_components.py's import of kern's SDK).
KERN = se_modules.kern_dir(ROOT)


def kern_at_pin() -> bool:
    """Whether kern's clone is at the commit se.lock locks for the version components/go.mod
    requires, read from the files alone: no git, so an unchanged pin costs nothing."""
    try:
        version = se_modules.go_require(ROOT, se_modules.KERN, "components/go.mod")[1]
        locked = se_modules.read_lock(ROOT).get(se_modules.KERN)
        head = (KERN / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, se_modules.ModuleError):
        return False
    return locked is not None and locked == (version, head)


def place_kern() -> None:
    """Bring kern to its pin once per checkout at a time, under a lock as the obs fixture does:
    the suite's setup, through real git (`se_modules.py sync kern`)."""
    if kern_at_pin():
        return
    with contextlib.ExitStack() as held:
        try:
            held.enter_context(waiting.exclusive(ROOT / ".se" / "kern-setup.flock", OBS_LOCK_WAIT_SECONDS))
        except TimeoutError as error:
            raise pytest.UsageError(str(error)) from None
        if kern_at_pin():
            return
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "se_modules.py"), "sync", se_modules.KERN],
                                cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, git_door.VARIABLE: "real"})
        if result.returncode:  # fails open: a test that reads kern then fails, naming the file
            print(f"warning: se_modules.py sync kern failed, so the tests that read kern fail:\n"
                  f"{result.stderr}{result.stdout}", file=sys.stderr)


@pytest.fixture(scope="session")
def kern() -> Path:
    """kern's folder, its clone at the pin (`se_modules.kern_dir`), which pytest_configure placed."""
    return KERN


# The suite's JUnit report for `work_tickets.py suite` (docs/tests.md "Test budget"): where the gate names a
# report directory, the controller writes se.xml there with its worker count and each test's setup
# time and worker, so the gate prints se's Parts line and its slow setups. It also names the host's
# CPU and when each test's setup started, in seconds from the controller's session start, which
# `work_tickets.py test-seconds` reads from CI's artifact test-reports.
REPORTS_VARIABLE = "SE_TEST_REPORTS"
setup_seconds: dict[tuple[str, str], tuple[float, float]] = {}  # (test, worker): setup time, start


# The suite builds the plugin layout from src/ before its tests (AGENTS.md "Agents and skills"), so
# no run tests stale generated files and nobody has to remember `se_plugin.py build`; on the
# controller only, before pytest-xdist starts its workers.
built_layouts = pytest.StashKey[list[str]]()


def build_plugin_layouts(config: pytest.Config) -> None:
    try:
        config.stash[built_layouts] = [str(path) for path in se_plugin.build(ROOT)]
    except se_plugin.SourceError as error:
        raise pytest.UsageError(f"se_plugin.py build: {error}; fix the source in src/") from error


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    for path in config.stash.get(built_layouts, []):
        terminalreporter.write_line(f"se_plugin.py build: wrote {path}")


@pytest.hookimpl(tryfirst=True)  # before junitxml opens its report
def pytest_configure(config: pytest.Config) -> None:
    if not hasattr(config, "workerinput"):
        build_plugin_layouts(config)
        place_kern()  # on the controller, before pytest-xdist starts the workers that collect
    config.pluginmanager.register(GuardReports(), "se-guard-reports")
    order_by_file_seconds(config)
    reports = os.environ.get(REPORTS_VARIABLE)
    if reports and not config.option.xmlpath and not hasattr(config, "workerinput"):
        config.option.xmlpath = str(Path(reports) / "se.xml")


def pytest_sessionstart(session: pytest.Session) -> None:
    from _pytest.junitxml import xml_key

    report = session.config.stash.get(xml_key, None)
    if report is not None:  # junitxml opens it on the controller only
        session.config.pluginmanager.register(SetupTimes(time.time()), "se-setup-times")
        report.add_global_property("workers", getattr(session.config.option, "numprocesses", 0) or 1)
        report.add_global_property("cpu", host_cpu())


def host_cpu() -> str:
    """The host's CPU model and its count, `<model> x<count>`: the model from the first `model name`
    line of /proc/cpuinfo, else platform.processor(), else `unknown`."""
    import platform

    model = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as cpuinfo:
            model = next((line.split(":", 1)[1].strip() for line in cpuinfo
                          if line.startswith("model name") and ":" in line), "")
    except OSError:
        pass
    return f"{model or platform.processor() or 'unknown'} x{os.cpu_count()}"


class SetupTimes:
    """Adds each test's setup time, worker and start to its JUnit test case, on the controller;
    `started` is the seconds from the session's start to the start of the test's setup."""

    def __init__(self, session_start: float) -> None:
        self.session_start = session_start

    @pytest.hookimpl(tryfirst=True)  # before junitxml writes the test case's properties
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        node = getattr(report, "node", None)  # pytest-xdist: the worker that ran the test
        worker = node.gateway.id if node is not None else "main"
        if report.when == "setup":
            setup_seconds[(report.nodeid, worker)] = (report.duration, report.start)
        elif report.when == "teardown" and (report.nodeid, worker) in setup_seconds:
            seconds, start = setup_seconds.pop((report.nodeid, worker))
            started = max(0.0, start - self.session_start)
            report.user_properties.extend([("setup_time", f"{seconds:.3f}"), ("worker", worker),
                                           ("started", f"{started:.3f}")])


# The order the workers take the test files in (pyproject.toml runs `--dist loadfile`): the
# heaviest file first, by its seconds in the checkout's last parallel run, so no long file starts
# last and runs alone while the other workers idle. pytest-xdist's own order is by test count,
# which sends a file of three slow tests out among the last. The controller records each file's
# setup, call and teardown seconds in pytest's cache at the end of a parallel run and hands what it
# read at the start to every worker, so all of them collect one order. Where the cache records no
# seconds for a file (all of them in CI, a fresh clone or a new worktree), the tracked table
# tests/file-seconds.json seeds them; the cache wins file by file, and the cache's record holds
# only the checkout's own runs. A file in neither counts its tests at the known files' mean seconds
# per test. `-o file_seconds=<path>` reads another table.
# The table holds CI's seconds: CI's runner runs the PowerShell cases and skips the Playwright ones,
# so a fleet host weighs files otherwise, and CI's order is the one the budget judges. CI's suite
# step records them (`--record-file-seconds=PATH`, a passing parallel run of whole files) into its
# artifact file-seconds, and RECORD_COMMAND writes the table from it; that run also names each file
# that took more than DRIFT_SECONDS and more than DRIFT_SHARE over the table it read (drift_lines).
FILE_SECONDS_KEY = "se/file-seconds"
FILE_SECONDS_INPUT = "se_file_seconds"
FILE_SECONDS_TABLE = ROOT / "tests" / "file-seconds.json"
RECORD_COMMAND = "uv run python scripts/work_tickets.py file-seconds"
DRIFT_SECONDS, DRIFT_SHARE = 5.0, 0.5
file_seconds_read = pytest.StashKey[dict[str, float]]()


def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    spawn_guard.register(pluginmanager)  # the spawn guard (scripts/spawn_guard.py) judges every test
    parser.addoption("--record-file-seconds", nargs="?", const="", default=None, metavar="PATH",
                     help="write this run's seconds per file to PATH at the end of a passing parallel "
                          "run of whole files, as CI's suite step does; the tracked table is CI's, "
                          f"written with `{RECORD_COMMAND}`")
    parser.addini("file_seconds", "the file-seconds table the order reads where the cache records none",
                  default="")


def file_of(nodeid: str) -> str:
    """The file a test's node id names."""
    return nodeid.split("::", 1)[0]


def file_order(counts: Mapping[str, int], seconds: Mapping[str, float]) -> list[str]:
    """The files of `counts` (file: its number of tests), heaviest first: by its recorded `seconds`,
    else by its tests at the known files' mean seconds per test; ties keep the collection order."""
    known = [name for name in counts if name in seconds]
    tests = sum(counts[name] for name in known)
    per_test = sum(seconds[name] for name in known) / tests if tests else 1.0
    weight = {name: seconds[name] if name in seconds else counts[name] * per_test for name in counts}
    return sorted(counts, key=lambda name: -weight[name])


def record_target(config: pytest.Config) -> Path | None:
    """Where --record-file-seconds writes, or None without it; the option without a PATH is refused,
    as the tracked table holds CI's seconds, not this host's."""
    target = config.getoption("record_file_seconds")
    if target is None:
        return None
    if not target:
        raise pytest.UsageError(
            "--record-file-seconds needs a PATH: the tracked table tests/file-seconds.json holds CI's "
            "seconds, whose runner runs the PowerShell cases and skips the Playwright ones; write it "
            f"from CI's run with `{RECORD_COMMAND}`")
    return Path(target).resolve()


def drift_lines(run: Mapping[str, float], table: Mapping[str, float]) -> list[str]:
    """One line per file whose seconds in `run` exceed `table`'s by more than DRIFT_SECONDS and by
    more than DRIFT_SHARE of them: the share keeps a runner slower all over from naming its heavy
    files. A file the table lacks is none."""
    return [f"file seconds: {name} took {seconds:.1f} s here, the table says {table[name]:.1f} s; "
            f"refresh it with {RECORD_COMMAND}"
            for name, seconds in sorted(run.items())
            if name in table and seconds > table[name] + DRIFT_SECONDS
            and seconds > table[name] * (1 + DRIFT_SHARE)]


def merged_seconds(recorded: Mapping[str, float], table: Mapping[str, float]) -> dict[str, float]:
    """The seconds the order weighs by: the cache's `recorded` seconds, else the table's."""
    return {**table, **recorded}


def table_path(config: pytest.Config) -> Path:
    """The file-seconds table the order reads: `-o file_seconds=<path>`, else the one beside this file."""
    named = config.getini("file_seconds")
    return config.rootpath / named if named else FILE_SECONDS_TABLE


def read_table(path: Path) -> dict[str, float]:
    """The table at `path`, a JSON object of file paths to non-negative seconds; none where it is missing."""
    if not path.exists():
        return {}
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise pytest.UsageError(f"{path}: not a JSON object of file paths to seconds ({error}); "
                                f"write it with `{RECORD_COMMAND}`") from error
    if not isinstance(table, dict) or not all(
            isinstance(name, str) and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
            for name, value in table.items()):
        raise pytest.UsageError(f"{path}: not a JSON object of file paths to non-negative seconds; "
                                f"write it with `{RECORD_COMMAND}`")
    return {name: float(value) for name, value in table.items()}


def write_table(path: Path, table: Mapping[str, float]) -> None:
    """`table` at `path`: keys sorted, one per line, seconds rounded to 0.1 s."""
    rounded = {name: round(seconds, 1) for name, seconds in sorted(table.items())}
    path.write_text(json.dumps(rounded, indent=2) + "\n", encoding="utf-8")


def parallel(config: pytest.Config) -> bool:
    """Whether this run's tests are spread over pytest-xdist's workers."""
    return bool(getattr(config.option, "numprocesses", None)) and getattr(config.option, "dist", "no") != "no"


class FileSeconds:
    """On the controller: reads the recorded seconds at the start, hands them, the table filling
    what the cache lacks, to every worker, adds up this run's seconds per file and records them at
    the end of a parallel run that passed and took whole files, dropping a file that is gone; with
    --record-file-seconds, it also writes the table then."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.table = read_table(table_path(config))
        self.run: dict[str, float] = {}
        self.summary = ""

    @property
    def read(self) -> dict[str, float]:
        """The recorded seconds, read once: after pytest_configure, as the cache is set up there."""
        if file_seconds_read not in self.config.stash:
            cache = getattr(self.config, "cache", None)
            recorded = cache.get(FILE_SECONDS_KEY, {}) if cache is not None else {}
            self.config.stash[file_seconds_read] = recorded if isinstance(recorded, dict) else {}
        return self.config.stash[file_seconds_read]

    @property
    def seconds(self) -> dict[str, float]:
        """The seconds the order weighs by, the cache's and the table's."""
        return merged_seconds(self.read, self.table)

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node) -> None:
        node.workerinput[FILE_SECONDS_INPUT] = self.seconds

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        order_items(items, self.seconds)  # a run without workers collects here

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        name = file_of(report.nodeid)
        self.run[name] = self.run.get(name, 0.0) + report.duration  # setup, call and teardown

    def unrecordable(self, session: pytest.Session) -> str:
        """Why this run's seconds are not all of its files' seconds, or "" where they are."""
        if not self.run:
            return "no test ran"
        if session.testsfailed:
            return "a test failed"
        if not parallel(self.config):
            return "the run was not parallel"
        if not whole_files(self.config):
            return "the run did not take whole files (-k, -m or a test id)"
        return ""

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        reason = self.unrecordable(session)
        cache = getattr(self.config, "cache", None)
        if not reason and cache is not None:
            kept = {name: seconds for name, seconds in self.read.items() if (self.config.rootpath / name).exists()}
            cache.set(FILE_SECONDS_KEY, {**kept, **{name: round(seconds, 3) for name, seconds in self.run.items()}})
        path = record_target(self.config)
        if path is None:
            return
        if not reason and exitstatus != 0:
            reason = f"the run ended with exit status {int(exitstatus)}"
        if reason:
            self.summary = f"file seconds: wrote nothing to {path}: {reason}"
            return
        try:
            earlier = read_table(path)
        except pytest.UsageError as error:
            self.summary = f"file seconds: wrote nothing: {error}"
            return
        kept = {name: seconds for name, seconds in earlier.items() if (self.config.rootpath / name).exists()}
        write_table(path, {**kept, **self.run})
        self.summary = "\n".join([
            f"file seconds: wrote {path} ({len(self.run)} files of this run, {len(kept.keys() - self.run.keys())} kept)",
            *drift_lines(self.run, self.table)])

    def pytest_terminal_summary(self, terminalreporter) -> None:
        for line in self.summary.splitlines():
            terminalreporter.write_line(line)


def whole_files(config: pytest.Config) -> bool:
    """Whether this run's selection takes whole files, so each file's seconds are all of it."""
    return not (config.option.keyword or config.option.markexpr or any("::" in arg for arg in config.args))


def order_by_file_seconds(config: pytest.Config) -> None:
    """pytest_configure's part of the file order: a worker orders by the seconds the controller
    hands it; the controller reads and records them and, where workers run, keeps pytest-xdist
    from sorting the files again by their test counts."""
    if hasattr(config, "workerinput"):
        seconds = dict(config.workerinput.get(FILE_SECONDS_INPUT, {}))
        config.pluginmanager.register(WorkerFileOrder(seconds), "se-file-order")
        return
    record_target(config)  # refuses the option without a PATH before any test runs
    config.pluginmanager.register(FileSeconds(config), "se-file-seconds")
    if parallel(config):
        config.option.loadscopereorder = False  # the workers' collection order is the order


def order_items(items: list[pytest.Item], seconds: Mapping[str, float]) -> None:
    """`items` sorted by file_order; a file keeps its own order (the sort is stable)."""
    counts: dict[str, int] = {}
    for item in items:
        counts[file_of(item.nodeid)] = counts.get(file_of(item.nodeid), 0) + 1
    rank = {name: place for place, name in enumerate(file_order(counts, seconds))}
    items.sort(key=lambda item: rank[file_of(item.nodeid)])


class WorkerFileOrder:
    """On a worker: collects in the order of the seconds the controller handed over."""

    def __init__(self, seconds: Mapping[str, float]) -> None:
        self.seconds = seconds

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        order_items(items, self.seconds)
