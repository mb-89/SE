"""Read names from the core that runs in a checkout, live: SE's one reader of a kern name.

The core's standing file (`<checkout>/.se/.runtime/standing.json`, kern/README.md "The host")
names its bus and the client user's password; each name is one `get.<name>` on that bus, through
kern's Python SDK (`kern/python/kern`, standard library only). Where no core runs, or it does not
answer within the wait, the reader answers None, and every caller falls back to its own path:
the greeting to its cached work check, `fleet-check` to its own reads.

SE's components that write the names the greeting reads, `fleet/findings` and `retro/due`, are
SE's Go components (components/README.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SE_ROOT = Path(__file__).resolve().parents[1]
STANDING = Path(".se") / ".runtime" / "standing.json"
WAIT = 0.3  # seconds for the connection and for each name: the greeting keeps its 1 s budget
FLEET = "fleet/findings"
RETRO = "retro/due"


def read(root: Path | None, names: list[str], wait: float = WAIT) -> dict[str, object] | None:
    """Each of `names` as the core in the checkout at `root` holds it; None where no core runs
    there, it does not answer, or it provides none of them (a core that carries no such
    component answers an error, one that has not computed it the built-in value)."""
    if root is None:
        return None
    try:
        standing = json.loads((root / STANDING).read_text(encoding="utf-8"))
        url, password = standing["bus"], standing["users"]["client"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if str(SE_ROOT / "kern" / "python") not in sys.path:
        sys.path.insert(0, str(SE_ROOT / "kern" / "python"))
    try:
        from kern.nats import NatsError, Peer
        from kern.subjects import subject
    except ImportError:
        return None
    try:
        peer = Peer(url, "client", password, name="se", timeout=wait)
    except (OSError, NatsError):
        return None
    found: dict[str, object] = {}
    try:
        for name in names:
            answer = peer.request("get." + subject(name), {"name": name}, timeout=wait).json() or {}
            if answer.get("provided") and not answer.get("error"):
                found[name] = answer.get("value")
    except (OSError, NatsError, ValueError):
        return None
    finally:
        peer.close()
    return found or None


def live_work(root: Path | None) -> dict | None:
    """What is due in the work from the core, in the greeting's work-check shape: a retro part
    and a fleet part, each marked `"from": "kern"`, and only where the core has read GitHub
    issues for it (a core that has read none answers nothing, and the cache stays); None where
    no core carries SE's components."""
    names = read(root, [FLEET, RETRO])
    if not names:
        return None
    work: dict[str, dict] = {}
    fleet, retro = names.get(FLEET), names.get(RETRO)
    if isinstance(fleet, dict) and fleet.get("issues"):
        work["fleet"] = {"findings": [{"kind": f.get("kind"), "issue": f.get("issue")}
                                      for f in fleet.get("findings") or []],
                         "issues": fleet["issues"], "from": "kern"}
    if isinstance(retro, dict) and retro.get("issues"):
        work["retro"] = {"landed": retro.get("landed"), "due_after": retro.get("due_after"),
                         "issues": retro["issues"], "from": "kern"}
    return work or None
