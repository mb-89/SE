"""The Python SDK's half of streaming (docs/go-core.md "Progress and long calls"): a step's lines go
out at once on ``say.<i>``, and while a step runs the runner beats there and on ``lease.<i>``, so the
core waits for a long step as long as the process lives. ``contract/stream_test.go`` runs the same
runner against the real core."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

KERN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KERN / "python"))

from kern import runner  # noqa: E402

DECLARATION = """name = "drip"
contract = 1
help = "Drips progress lines."

[commands."drip talk"]
usage = "drip talk"
summary = "Say two lines, slowly."
group = "Fixtures"
help = "Says each line as it goes."
class = "batch"
"""

INIT = """import time
from kern import component

drip = component("drip")


@drip.command("drip talk")
def talk(args, inputs, say):
    say("one")
    time.sleep(0.6)
    say("two")
    return "done"
"""


class Peer:
    """What the runner publishes, in order, from any thread."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def publish(self, subject: str, data=b"", reply: str = "") -> None:
        with self.lock:
            self.sent.append((subject, data if isinstance(data, dict) else json.loads(data or b"{}")))


def test_a_step_says_its_lines_at_once_and_beats_while_it_runs(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "component.toml").write_text(DECLARATION, encoding="utf-8")
    (tmp_path / "__init__.py").write_text(INIT, encoding="utf-8")
    comp = runner.load(tmp_path)
    monkeypatch.setattr(runner, "BEAT", 0.1)
    peer = Peer()
    run = runner.Runner(comp, peer, "drip")  # type: ignore[arg-type]

    answer = run._step("drip talk", {"call": "7", "step": 1, "args": []})

    assert answer["text"] == "done" and "lines" not in answer, answer
    said = [body for subject, body in peer.sent if subject == "say.drip"]
    assert [b["line"] for b in said if "line" in b] == ["one", "two"]
    assert all(b["call"] == "7" for b in said)
    beats = [b for b in said if "line" not in b]
    assert beats, "the runner beats on say.drip while the step runs"
    leases = [subject for subject, _ in peer.sent if subject == "lease.drip"]
    assert len(leases) == len(beats), "each beat also renews the lease"
    two = next(i for i, (s, b) in enumerate(peer.sent) if b.get("line") == "two")
    assert any(s == "say.drip" and "line" not in b for s, b in peer.sent[:two]), \
        "a beat comes between the lines, while the step sleeps"
    before = len(peer.sent)
    time.sleep(0.3)
    assert len(peer.sent) == before, "no beat after the step answered"
