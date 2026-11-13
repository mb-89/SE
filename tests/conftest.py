"""Shared fixtures of se's suite."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402
import se_plugin  # noqa: E402
import quiet_git  # noqa: E402
import fake_git  # noqa: E402
import git_door  # noqa: E402

# The suite's runs of work_tickets.py and se_start.py measure themselves (scripts/metrics.py); their
# lines go nowhere, never into the machine's ~/.se/metrics.jsonl. A test of the lines sets its own.
os.environ["SE_METRICS"] = os.devnull

# The suite's commands run directly, never through a kern that serves this checkout (README "Commands
# as components"): a test's fakes live in its own process. A test of the routing sets its own.
os.environ["SE_KERN"] = "off"

# What a CI runner sets and a local machine does not: GitHub Actions' variables and SE's cloud agent,
# which switch commands to their runner behaviour (`start` a cloud start, `capacity` none).
RUNNER_VARIABLES = ("CI", "SE_CLOUD_AGENT")
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
# not pass the door is tests/test_repository.py's guard's to find. The list may only shrink.
STILL_ON_REAL_GIT = "runs real git until its piece of the move to the fake lands"
REAL_GIT: dict[str, str] = {
    "tests/test_git_door.py": "the door's contract, held against real git",
    # Found by the refusal of child processes: `se new app` reads SE's own checkout, kern's template
    # at its real pin tag, as test_references.py and test_repository.py read it (piece 6's kind).
    "tests/beside_new_app.py": "reads SE's own checkout: kern's template at its real pin",
    "tests/test_quiet_git.py": STILL_ON_REAL_GIT,
    "tests/test_references.py": STILL_ON_REAL_GIT,
    "tests/test_releases.py": STILL_ON_REAL_GIT,
    "tests/test_repository.py": STILL_ON_REAL_GIT,
    "tests/test_rewrite_history.py": STILL_ON_REAL_GIT,
    "tests/test_start_refresh.py": STILL_ON_REAL_GIT,
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
    with git_door.use(door_backend(item)), pytest.MonkeyPatch.context() as patch:
        patch.setenv(git_door.VARIABLE, door_variable(item))
        yield


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


@pytest.fixture(scope="session")
def repositories(tmp_path_factory) -> Callable[[Callable[[Path], None], Path], None]:
    """`repositories(build, tmp_path)` lays out in tmp_path the git repositories `build` makes in an
    empty directory: built once per session (per worker) and copied for each test, which costs a
    fraction of the git commands. The copies' remotes point into tmp_path, as a fresh build's do;
    git's lock files stay behind (tests/quiet_git.py)."""
    built: dict[Callable[[Path], None], Path] = {}

    def lay_out(build: Callable[[Path], None], tmp_path: Path) -> None:
        if build not in built:
            built[build] = tmp_path_factory.mktemp(build.__name__)
            build(built[build])
        template = built[build]
        quiet_git.copy(template, tmp_path)
        # Git writes a local remote's path into config as given, a backslash doubled.
        forms = {str(template): str(tmp_path), template.as_posix(): tmp_path.as_posix(),
                 str(template).replace("\\", "\\\\"): str(tmp_path).replace("\\", "\\\\")}
        for config in [*tmp_path.glob("*/.git/config"), *tmp_path.glob("*.git/config")]:
            text = original = config.read_text(encoding="utf-8")
            for old, new in forms.items():
                text = text.replace(old, new)
            if text != original:
                config.write_text(text, encoding="utf-8")

    return lay_out



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
