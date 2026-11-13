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
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["check"], "kern runs in the one required job"
    setup = re.search(r"uses: actions/setup-go@v(\d+)\n        with:\n((?:          .*\n)+)", workflow)
    assert setup, "kern's steps set up Go"
    assert int(setup[1]) >= SETUP_GO_NODE_24, "setup-go below v6 runs on Node 20"
    assert "go-version-file: kern/go.mod" in setup[2] and "cache-dependency-path: kern/go.sum" in setup[2]
    assert re.search(r"(?m)^go \d+\.\d+\.\d+$", (PROJECT / "kern" / "go.mod").read_text(encoding="utf-8"))
    # Go is set up before the suite step, which runs kern's tests as se.toml declares them.
    steps = ["actions/setup-go", "time go vet ./...", "scripts/work_tickets.py suite --worktree ."]
    assert [workflow.index(step) for step in steps] == sorted(workflow.index(step) for step in steps)
    assert "        working-directory: kern\n        run: time go vet ./...\n" in workflow
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    assert "go test" not in check, "kern's tests have one declaration, se.toml [tests.beside.kern]"
