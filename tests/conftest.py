"""Shared fixtures of se's suite."""

from __future__ import annotations

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
import network_guard  # noqa: E402

# The test process reaches nothing beyond this machine, its collection included (tests/network_guard.py).
network_guard.install()

# The suite's runs of work_tickets.py and se_start.py measure themselves (scripts/metrics.py); their
# lines go nowhere, never into the machine's ~/.se/metrics.jsonl. A test of the lines sets its own.
os.environ["SE_METRICS"] = os.devnull

# The suite's commands run directly, never through a kern that serves this checkout (README "Commands
# as components"): a test's fakes live in its own process. A test of the routing sets its own.
os.environ["SE_KERN"] = "off"

# What a CI runner sets and a local machine does not: GitHub Actions' variables and SE's cloud agent,
# which switch commands to their runner behaviour (`start` a cloud start, `capacity` none), and the
# public check's cloud list, which adds terms to every check.
RUNNER_VARIABLES = ("CI", "SE_CLOUD_AGENT", "SE_PUBLIC_CHECK_TERMS")
RUNNER_PREFIX = "GITHUB_"


def runner_variables(environment: Mapping[str, str]) -> list[str]:
    """The names in `environment` that a runner sets (RUNNER_VARIABLES, every GITHUB_*)."""
    return [name for name in environment if name in RUNNER_VARIABLES or name.startswith(RUNNER_PREFIX)]


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
    path = Path(item.path).resolve()
    name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    return git_door.RealGit() if name in REAL_GIT else RefusedGit(item.nodeid)


def door_variable(item: pytest.Item) -> str:
    """What the door's variable tells the child processes `item` starts (scripts/git_door.py
    `from_environment`): real git for a file in REAL_GIT, otherwise refused, so a child reaches
    git only through the fake its test hands it (`shared_fake_git`)."""
    return "real" if isinstance(door_backend(item), git_door.RealGit) else "refused"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem):
    with git_door.use(door_backend(item)), network_guard.running(item.nodeid), \
            pytest.MonkeyPatch.context() as patch:
        patch.setenv(git_door.VARIABLE, door_variable(item))
        yield


class GuardReports:
    """Fails each test phase that tried to reach beyond this machine (tests/network_guard.py
    `fail`). A plugin
    `pytest_configure` registers, not a hook of this conftest's own: pytest calls a conftest's
    `pytest_runtest_makereport` only for the tests under its folder, and the complete run also
    collects kern/python/tests."""

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call):
        outcome = yield
        report = outcome.get_result()
        network_guard.fail(report)


@pytest.fixture
def fake_git_door() -> Iterator[fake_git.FakeGit]:
    """git behind the door is the fake for this test (tests/fake_git.py, held to real git by
    tests/test_git_door.py); what the test and the code under test run reaches no real git."""
    with git_door.use(fake_git.FakeGit()) as fake:
        yield fake


@pytest.fixture
def shared_fake_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[fake_git.StateFile]:
    """The fake for this test and every child process it starts: its state in a file that the
    door's variable names (`SE_GIT_DOOR=fake:<file>`, read by scripts/git_door.py and kern's
    kern/git alike), so a script run as a process or a kern binary reaches the same fake."""
    state = fake_git.StateFile(tmp_path / "git-door.json")
    monkeypatch.setenv(git_door.VARIABLE, f"fake:{state.path}")
    with git_door.use(state):
        yield state


@pytest.fixture(scope="session")
def obs() -> Path:
    """The obs module at its pin with its environment built, once per checkout at a time.

    The suite's workers run test files in parallel (pyproject.toml), and every obs build syncs the module
    and runs it through uv: a fresh checkout must clone and build it once, never twice at once. A
    directory made atomically is the lock, which every platform has.
    """
    lock = ROOT / ".se" / "obs-setup.lock"
    lock.parent.mkdir(exist_ok=True)
    deadline = time.monotonic() + 600
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                pytest.fail(f"{lock} is still held after 600 s; remove it if no suite runs")
            time.sleep(0.2)
    try:
        with pytest.MonkeyPatch.context() as patch:
            # Bringing SE's own checkout's obs module to its pin is the suite's setup, not a test:
            # it fetches the real module, through real git.
            patch.setenv(git_door.VARIABLE, "real")
            directory = build_docs.obs_dir()
        subprocess.run(["uv", "sync", "--quiet", "--project", str(directory)], cwd=ROOT, check=True,
                       env=build_docs.child_environment())
        os.environ[build_docs.OBS_VARIABLE] = str(directory)  # the builds of the tests that take it
        return directory
    finally:
        os.rmdir(lock)


# The suite's JUnit report for `work_tickets.py suite` (README "Test budget"): where the gate names a
# report directory, the controller writes se.xml there with its worker count and each test's setup
# time and worker, so the gate prints se's Parts line and its slow setups.
REPORTS_VARIABLE = "SE_TEST_REPORTS"
setup_seconds: dict[tuple[str, str], float] = {}  # (test, worker): the controller's setup times


# The suite builds the plugin layouts from src/ before its tests (AGENTS.md "Agents and skills"), so
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
    config.pluginmanager.register(GuardReports(), "se-guard-reports")
    order_by_file_seconds(config)
    reports = os.environ.get(REPORTS_VARIABLE)
    if reports and not config.option.xmlpath and not hasattr(config, "workerinput"):
        config.option.xmlpath = str(Path(reports) / "se.xml")


def pytest_sessionstart(session: pytest.Session) -> None:
    from _pytest.junitxml import xml_key

    report = session.config.stash.get(xml_key, None)
    if report is not None:  # junitxml opens it on the controller only
        session.config.pluginmanager.register(SetupTimes(), "se-setup-times")
        report.add_global_property("workers", getattr(session.config.option, "numprocesses", 0) or 1)


class SetupTimes:
    """Adds each test's setup time and worker to its JUnit test case, on the controller."""

    @pytest.hookimpl(tryfirst=True)  # before junitxml writes the test case's properties
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        node = getattr(report, "node", None)  # pytest-xdist: the worker that ran the test
        worker = node.gateway.id if node is not None else "main"
        if report.when == "setup":
            setup_seconds[(report.nodeid, worker)] = report.duration
        elif report.when == "teardown" and (report.nodeid, worker) in setup_seconds:
            seconds = setup_seconds.pop((report.nodeid, worker))
            report.user_properties.extend([("setup_time", f"{seconds:.3f}"), ("worker", worker)])


# The order the workers take the test files in (pyproject.toml runs `--dist loadfile`): the
# heaviest file first, by its seconds in the checkout's last parallel run, so no long file starts
# last and runs alone while the other workers idle. pytest-xdist's own order is by test count,
# which sends a file of three slow tests out among the last. The controller records each file's
# setup, call and teardown seconds in pytest's cache at the end of a parallel run and hands what it
# read at the start to every worker, so all of them collect one order; a file the cache does not
# know (all of them in a fresh checkout) counts its tests at the known files' mean seconds per test.
FILE_SECONDS_KEY = "se/file-seconds"
FILE_SECONDS_INPUT = "se_file_seconds"
file_seconds_read = pytest.StashKey[dict[str, float]]()


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


def parallel(config: pytest.Config) -> bool:
    """Whether this run's tests are spread over pytest-xdist's workers."""
    return bool(getattr(config.option, "numprocesses", None)) and getattr(config.option, "dist", "no") != "no"


class FileSeconds:
    """On the controller: reads the recorded seconds at the start, hands them to every worker,
    adds up this run's seconds per file and records them at the end of a parallel run that passed
    and took whole files, dropping a file that is gone."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.run: dict[str, float] = {}

    @property
    def read(self) -> dict[str, float]:
        """The recorded seconds, read once: after pytest_configure, as the cache is set up there."""
        if file_seconds_read not in self.config.stash:
            cache = getattr(self.config, "cache", None)
            recorded = cache.get(FILE_SECONDS_KEY, {}) if cache is not None else {}
            self.config.stash[file_seconds_read] = recorded if isinstance(recorded, dict) else {}
        return self.config.stash[file_seconds_read]

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node) -> None:
        node.workerinput[FILE_SECONDS_INPUT] = self.read

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        order_items(items, self.read)  # a run without workers collects here

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        name = file_of(report.nodeid)
        self.run[name] = self.run.get(name, 0.0) + report.duration  # setup, call and teardown

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        cache = getattr(self.config, "cache", None)
        if self.run and cache is not None and parallel(self.config) and whole_files(self.config) \
                and session.testsfailed == 0:
            kept = {name: seconds for name, seconds in self.read.items() if (self.config.rootpath / name).exists()}
            cache.set(FILE_SECONDS_KEY, {**kept, **{name: round(seconds, 3) for name, seconds in self.run.items()}})


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
