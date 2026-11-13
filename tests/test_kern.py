"""kern, the Go core incubated under kern/ (kern/README.md "Tests"): the check main requires runs it."""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".github" / "workflows" / "check.yml"
# The first major of actions/setup-go that runs on Node 24.
SETUP_GO_NODE_24 = 6


def test_the_required_check_runs_kerns_vet_and_tests_on_the_go_its_go_mod_pins() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["kern-windows", "check"], (
        "kern runs in the required job check, and on Windows in kern-windows, which check needs"
    )
    setups = re.findall(r"uses: actions/setup-go@v(\d+)\n        with:\n((?:          .*\n)+)", workflow)
    assert len(setups) == 2, "kern's steps set up Go on Windows and on Linux"
    for major, inputs in setups:
        assert int(major) >= SETUP_GO_NODE_24, "setup-go below v6 runs on Node 20"
        assert "go-version-file: kern/go.mod" in inputs and "cache-dependency-path: kern/go.sum" in inputs
    assert re.search(r"(?m)^go \d+\.\d+\.\d+$", (PROJECT / "kern" / "go.mod").read_text(encoding="utf-8"))
    check = jobs[jobs.index("\n  check:\n"):]
    steps = ["scripts/work_tickets.py suite --worktree .", "actions/setup-go", "time go vet ./...",
             "time go test ./...", "needs.kern-windows.result"]
    assert [check.index(step) for step in steps] == sorted(check.index(step) for step in steps)
    for command in ("time go vet ./...", "time go test ./..."):
        assert f"        working-directory: kern\n        run: {command}\n" in check


def test_the_required_check_fails_unless_kern_passed_on_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    windows = jobs[jobs.index("\n  kern-windows:\n"):jobs.index("\n  check:\n") + 1]
    check = jobs[jobs.index("\n  check:\n"):]
    assert "    runs-on: windows-" in windows
    for command in ("go vet ./...", "go test ./..."):
        assert f"        working-directory: kern\n        run: {command}\n" in windows
    assert "work_tickets.py suite" not in windows, "the Python suite and its budget stay on Linux"
    assert "    needs: kern-windows\n" in check
    # A required check that is skipped counts as passed: check runs whatever kern-windows answered.
    assert "    if: ${{ !cancelled() }}\n" in check
    assert re.search(r'if \[ "\$WINDOWS" != success \]; then\n.*\n\s+exit 1', check), "check fails unless kern-windows passed"
