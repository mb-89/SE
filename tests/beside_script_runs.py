"""The ad hoc scripts' runs counted against the real core, beside se.toml
`[tests.beside.script-runs]` (docs/go-core.md "Scripts are ad hoc, components are long-term"): a
shell tool's PostToolUse, posted through `kern hook PostToolUse` as SE's hook posts it, counts each
run of a script git does not track into the use log, and `retro.py collect` lists the script with
its count; a tracked script and an ordinary command are not counted. It builds kern's binary, so it
runs beside the suite after kern's tests have warmed Go's cache, not in it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import quiet_git  # noqa: E402
import retro  # noqa: E402

# The window starts before every run the test posts.
SINCE = "2026-01-01T00:00:00Z"


class EmptyDoor:
    """A window with no issues and no pull requests: the collect reads only the use log."""

    missing: list[str] = []

    def closed_issues(self):
        return []

    def open_issues(self):
        return []

    def pulls(self):
        return []

    def issue(self, number):
        return {}

    def comments(self, number):
        return []

    def checks(self, found):
        return []


def run(*args: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, input=stdin, capture_output=True, text=True,
                          timeout=120, env={**os.environ, "UV_SYSTEM_CERTS": "1"})


def test_an_untracked_script_run_three_times_is_listed_by_the_retro_with_count_three(
        tmp_path: Path) -> None:
    kern = tmp_path / ("kern.exe" if os.name == "nt" else "kern")
    built = run("go", "build", "-o", str(kern), "./cmd/kern", cwd=ROOT / "kern")
    assert built.returncode == 0, built.stderr
    checkout = quiet_git.init(tmp_path / "app")
    (checkout / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
    quiet_git.git("-C", str(checkout), "add", "tracked.py")
    quiet_git.git("-C", str(checkout), "-c", "user.name=alice", "-c", "user.email=alice@example.com",
                  "commit", "-q", "-m", "tracked")
    (checkout / "probe.py").write_text("print('ad hoc')\n", encoding="utf-8")

    def post(command: str) -> None:
        payload = json.dumps({"session_id": "s1", "hook_event_name": "PostToolUse", "cwd": str(checkout),
                              "tool_name": "Bash", "tool_input": {"command": command},
                              "tool_response": {"stdout": "ad hoc", "stderr": ""}})
        posted = run(str(kern), "hook", "PostToolUse", "--root", str(checkout), cwd=checkout,
                     stdin=payload)
        assert posted.returncode == 0, posted.stderr

    assert run(str(kern), "start", "--root", str(checkout), cwd=checkout).returncode == 0
    try:
        assert run(str(kern), "status", "--root", str(checkout), "--wait", "5s",
                   cwd=checkout).returncode == 0
        post("python tracked.py")
        post("git status && uv run pytest -q")
        for arg in ("one", "two", "three"):
            post(f"python probe.py {arg}")
        # The next event is handled once the last run's count is written (kern/host/core.go hook).
        post("git log --oneline -1")
    finally:
        run(str(kern), "stop", "--root", str(checkout), cwd=checkout)

    found = retro.collect(checkout, 1, EmptyDoor(), "alice/app", "main", "HEAD",
                          datetime.now(timezone.utc), since=SINCE)
    assert found is not None
    assert [(s["script"], s["runs"]) for s in found.scripts] == [("probe.py", 3)]
    text = retro.draft(found)
    assert "| `probe.py` | 3 | 1 |" in text and "tracked.py" not in text
