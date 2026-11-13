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


@pytest.fixture
def fake_git_door() -> Iterator[fake_git.FakeGit]:
    """git behind the door is the fake for this test (tests/fake_git.py, held to real git by
    tests/test_git_door.py); what the test and the code under test run reaches no real git."""
    with git_door.use(fake_git.FakeGit()) as fake:
        yield fake


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
        directory = build_docs.obs_dir()
        subprocess.run(["uv", "sync", "--quiet", "--project", str(directory)], cwd=ROOT, check=True,
                       env=build_docs.child_environment())
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
