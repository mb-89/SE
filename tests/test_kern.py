"""kern, the Go core incubated under kern/ (kern/README.md "Tests"): the check main requires runs it."""

import re
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".github" / "workflows" / "check.yml"
# The first major of actions/setup-go that runs on Node 24.
SETUP_GO_NODE_24 = 6


def test_the_required_check_runs_kerns_vet_and_tests_on_the_go_its_go_mod_pins() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["check", "kern-windows"], (
        "kern runs in the required job check, and on Windows in kern-windows, which check needs"
    )
    setups = re.findall(r"uses: actions/setup-go@v(\d+)\n        with:\n((?:          .*\n)+)", workflow)
    assert len(setups) == 2, "kern's steps set up Go on Windows and on Linux"
    for major, inputs in setups:
        assert int(major) >= SETUP_GO_NODE_24, "setup-go below v6 runs on Node 20"
        assert "go-version-file: kern/go.mod" in inputs and "cache-dependency-path: kern/go.sum" in inputs
    assert re.search(r"(?m)^go \d+\.\d+\.\d+$", (PROJECT / "kern" / "go.mod").read_text(encoding="utf-8"))
    # Go is set up before the suite step, which runs kern's tests as se.toml declares them.
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    steps = ["actions/setup-go", "time go vet ./...", "scripts/work_tickets.py suite --worktree .",
             "needs.kern-windows.result"]
    assert [check.index(step) for step in steps] == sorted(check.index(step) for step in steps)
    assert "        working-directory: kern\n        run: time go vet ./...\n" in check
    assert "go test" not in check, "kern's tests have one declaration, se.toml [tests.beside.kern]"


def test_the_required_check_fails_unless_kern_passed_on_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    windows = jobs[jobs.index("\n  kern-windows:\n"):]
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    assert "    runs-on: windows-" in windows
    for command in ("go vet ./...", "go test ./..."):
        assert f"        working-directory: kern\n        run: {command}\n" in windows
    assert "work_tickets.py suite" not in windows, "the Python suite and its budget stay on Linux"
    assert "    needs: kern-windows\n" in check
    # A required check that is skipped counts as passed: check runs whatever kern-windows answered.
    assert "    if: ${{ !cancelled() }}\n" in check
    assert re.search(r'if \[ "\$WINDOWS" != success \]; then\n.*\n\s+exit 1', check), "check fails unless kern-windows passed"


RELEASE = PROJECT / ".github" / "workflows" / "kern-release.yml"
BATTERY = PROJECT / ".github" / "workflows" / "kern-battery.yml"
TEMPLATE = PROJECT / "kern" / "template"
# The first major of each action kern's workflows use that runs on Node 24.
NODE_24 = {"actions/checkout": 5, "actions/setup-go": SETUP_GO_NODE_24, "actions/upload-artifact": 6,
           "actions/download-artifact": 7, "astral-sh/setup-uv": 7}

def test_the_battery_holds_the_applications_tests_to_se_toml_tests() -> None:
    text = BATTERY.read_text(encoding="utf-8")
    assert "on:\n  workflow_call:\n" in text
    assert "go-version-file: ${{ inputs.directory }}/go.mod" in text
    assert "run: go vet ./..." in text
    assert 'tests.get("command"), tests.get("target_seconds"), tests.get("limit_seconds")' in text
    assert "if seconds > limit:" in text and "if seconds > target:" in text
