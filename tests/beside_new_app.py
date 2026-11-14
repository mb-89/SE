"""`se new app`'s acceptance, the suite beside se.toml `[tests.beside.new-app]`: an application
created from this SE, at its kern pin, passes its own test run, and its core refuses a wiring that
needs a switched-off component, naming both.

The SE it is created from is this working tree's, in the git door's fake: its scripts, se.toml and
kern, kern committed and tagged at its pin, so the template checked is the one this tree would
release; how the pin's ref is found is tests/test_se_new.py's.

It builds the application's Go, so it runs beside the suite, after kern's tests have warmed Go's
build cache, not in it (its file name keeps the suite from collecting it): README "Test budget".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import fake_git
import git_door
import pytest
import se_modules

ROOT = Path(__file__).resolve().parents[1]
NAME = "ledger"

# An application's own component: it reads a total, as a report would. kern's fixture component
# tally, imported beside it, stands in for a shared component until kern has one (its components/).
REPORT = """package report

import (
	"fmt"

	"github.com/mb-89/kern/index"
)

type in struct {
	Total int `index:"total"`
}

func init() {
	index.Register(index.Declare("report", "Reports a total.",
		index.Derived("line", "", "The total, said.", func(i in) (string, error) {
			return fmt.Sprint("total ", i.Total), nil
		})))
}
"""

WIRING = """[instances.tally]
component = "tally"
enabled = false

[instances.report]
component = "report"

[wires]
"tally.numbers" = "built-in"
"report.total" = {to}
"""


# The fake's state, shared with every child process through the door's variable (SE_GIT_DOOR).
DOOR: list[fake_git.StateFile] = []


def run(*args: str, cwd: Path, timeout: float = 300) -> subprocess.CompletedProcess:
    """`args` in `cwd`, its git the fake; Go stamps no VCS status, which it reads with real git from
    the `.git` folder the fake leaves on disk."""
    goflags = " ".join(filter(None, [os.environ.get("GOFLAGS", ""), "-buildvcs=false"]))
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "UV_SYSTEM_CERTS": "1", "GOFLAGS": goflags,
                               git_door.VARIABLE: f"fake:{DOOR[0].path}"})


def fake_se(root: Path) -> Path:
    """This working tree's SE in the fake: its scripts, se.toml and kern, kern committed and tagged
    kern-v<version> at its pin, origin on github.com."""
    se = root / "se"
    ignore = shutil.ignore_patterns("__pycache__", ".venv")
    shutil.copytree(ROOT / "scripts", se / "scripts", ignore=ignore)
    shutil.copytree(ROOT / "kern", se / "kern", ignore=ignore)
    shutil.copy2(ROOT / "se.toml", se / "se.toml")
    _, tag = se_modules.kern_pin(se)
    with git_door.use(DOOR[0]):
        fake_git.init(se, "-b", "main")
        for args in (("add", "se.toml", "kern"), ("-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q",
                     "-m", "SE"), ("tag", tag), ("remote", "add", "origin", "https://github.com/alice/se.git")):
            done = git_door.run(*args, root=se)
            assert done.returncode == 0, done.stderr
    return se


@pytest.fixture(scope="module")
def app(tmp_path_factory) -> Path:
    DOOR[:] = [fake_git.StateFile(tmp_path_factory.mktemp("git") / "git-door.json")]
    se = fake_se(tmp_path_factory.mktemp("se"))
    path = tmp_path_factory.mktemp("apps") / NAME
    done = run(sys.executable, str(se / "scripts" / "se.py"), "new", "app", NAME, "--path", str(path), cwd=se)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1].startswith("Owner's step: create the GitHub repository alice/"), done.stdout
    assert "is not released yet" not in done.stdout, "the template comes from the pin's tag"
    return path


def test_the_new_applications_own_test_run_passes(app: Path) -> None:
    done = run("uv", "run", "pytest", "-q", cwd=app)
    assert done.returncode == 0, done.stdout + done.stderr


def test_its_core_refuses_a_wiring_that_needs_a_switched_off_component_naming_both(app: Path, tmp_path: Path) -> None:
    (app / "components" / "report").mkdir()
    (app / "components" / "report" / "report.go").write_text(REPORT, encoding="utf-8")
    main = app / "cmd" / NAME / "main.go"
    main.write_text(main.read_text(encoding="utf-8").replace(
        '"github.com/mb-89/kern/cli"\n',
        f'"github.com/mb-89/kern/cli"\n\t_ "github.com/mb-89/kern/index/fixture"\n\t_ "example.com/{NAME}/components/report"\n'),
        encoding="utf-8")
    binary = tmp_path / (NAME + (".exe" if sys.platform == "win32" else ""))
    built = run("go", "build", "-o", str(binary), f"./cmd/{NAME}", cwd=app)
    assert built.returncode == 0, built.stderr

    refused = tmp_path / "refused"
    refused.mkdir()
    (refused / "wiring.toml").write_text(WIRING.replace("{to}", '"tally.total"'), encoding="utf-8")
    done = run(str(binary), "serve", "--root", str(refused), cwd=refused, timeout=30)
    assert done.returncode != 0
    assert ("wiring line 10: input report.total is bound to tally/total, and its writer tally is switched "
            "off on line 3") in done.stderr, done.stderr

    # The same wire marked builtin = true goes without its writer: the core starts with both instances.
    started = tmp_path / "started"
    started.mkdir()
    (started / "wiring.toml").write_text(
        WIRING.replace("{to}", '{ to = "tally.total", builtin = true }'), encoding="utf-8")
    assert run(str(binary), "start", "--root", str(started), cwd=started, timeout=30).returncode == 0
    try:
        status = run(str(binary), "status", "--root", str(started), "--wait", "10s", cwd=started, timeout=30)
        assert status.returncode == 0 and "2 instance(s)" in status.stdout, status.stdout + status.stderr
    finally:
        run(str(binary), "stop", "--root", str(started), cwd=started, timeout=30)
