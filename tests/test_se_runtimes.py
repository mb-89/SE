"""The machine door of the runtime check (scripts/se_runtimes.py), held to the fake the start's tests
use (tests/test_se_start.py, `SE_RUNTIMES=fake:`): the real probe reads a runtime's version from its
own command, and the real RUNME.sh gets a missing one from the RUNME.conf the check writes.
"""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import pytest
import se_runtimes
from shell_paths import link_tools

ROOT = Path(__file__).resolve().parents[1]
# The tools RUNME.sh runs; nothing else is on the test's PATH, so no runtime of the machine answers.
TOOLS = ("sh", "awk", "sed", "dirname", "cat", "chmod", "mkdir", "printf", "uname", "id")
pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="RUNME.sh runs in sh")


@pytest.mark.spawns("contract: se_runtimes.Machine.version, the machine door's probe, runs the runtime's own "
                    "command (python --version) that the start's fake machine stands in for")
def test_the_probe_reads_a_runtimes_version_from_its_own_command():
    machine = se_runtimes.Machine(path=str(Path(sys.executable).parent))

    assert machine.version("python") == platform.python_version()
    assert se_runtimes.Machine(path="").version("python") is None, "none on PATH: missing"


@pytest.mark.spawns("shell: se_runtimes.Machine.runme runs RUNME.sh's get line through the shell door, "
                    "and the probe then runs the node it wrote")
@pytest.mark.skipif(sys.platform == "win32", reason="the sealed PATH holds shell shims and the "
                    "runtime got is a shell script, neither of which Windows starts as a command")
def test_runme_gets_a_missing_runtime_from_the_conf_the_check_writes(tmp_path, monkeypatch):
    root, tools = tmp_path / "app", tmp_path / "bin"
    root.mkdir()
    link_tools(tools, TOOLS)
    monkeypatch.setenv("PATH", str(tools))
    shutil.copy2(ROOT / "RUNME.sh", root / "RUNME.sh")
    (root / "RUNME.conf").write_text(
        "path runtimes\n"
        "get node unix mkdir -p runtimes && printf '#!/bin/sh\\necho v20.11.1\\n' > runtimes/node"
        " && chmod +x runtimes/node\n"
        "run true\n", encoding="utf-8", newline="\n")
    needs = [se_runtimes.Need("node", "^20", ("app", "lib"))]

    said = se_runtimes.check(root, needs, se_runtimes.machine({}, root))

    assert said == ["runtime node 20.11.1: got through RUNME.conf (for app -> lib)"]
    assert (root / "runtimes" / "node").is_file(), "the get line ran in the root, as RUNME runs it there"


@pytest.mark.spawns("shell: RUNME.sh's own remedy for a get line that fails is shell, run only as a process")
@pytest.mark.skipif(sys.platform == "win32", reason="the sealed PATH holds shell shims and the "
                    "runtime got is a shell script, neither of which Windows starts as a command")
def test_runmes_own_remedy_names_a_runtime_it_could_not_get(tmp_path, monkeypatch):
    root, tools = tmp_path / "app", tmp_path / "bin"
    root.mkdir()
    link_tools(tools, TOOLS)
    monkeypatch.setenv("PATH", str(tools))
    shutil.copy2(ROOT / "RUNME.sh", root / "RUNME.sh")
    (root / "RUNME.conf").write_text("get node unix exit 3\nrun true\n", encoding="utf-8", newline="\n")

    with pytest.raises(se_runtimes.ModuleError) as refused:
        se_runtimes.check(root, [se_runtimes.Need("node", "^20", ("app",))], se_runtimes.machine({}, root))

    assert str(refused.value).splitlines()[1] == "  node ^20 (for app): missing; RUNME could not get it: node is " \
                                                 f"missing; run: cd {root.as_posix()} && exit 3"
