"""A one-off probe of the PreToolUse payload Copilot sends, run by .github/hooks/copilot-probe.json.

    copilot_probe.py <registration>     the hook event name the hooks file registered

It reads one hook payload on stdin and appends one line to `.se/.runtime/copilot-probe.log` under
the working directory (a project hook runs in the repository's root): the time, the registration,
the payload's top-level keys, the tool's name and its input's keys, never a value but the name. A
tool input given as a JSON string is parsed for its keys. It prints nothing and always exits 0, so
it never changes or blocks a tool call. Standard library only.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

LOG = Path(".se") / ".runtime" / "copilot-probe.log"


def row(registration: str, text: str) -> str:
    """The log line for one payload `text`: keys and the tool's name, never a value."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        payload = json.loads(text)
    except ValueError:
        return f"{stamp}\t{registration}\tunreadable payload ({len(text)} characters)"
    if not isinstance(payload, dict):
        return f"{stamp}\t{registration}\tpayload is {type(payload).__name__}"
    name = payload.get("tool_name", payload.get("toolName"))
    given, shape = None, "none"
    for key in ("tool_input", "toolArgs", "toolInput"):
        if key in payload:
            given, shape = payload[key], f"{key}:{type(payload[key]).__name__}"
            break
    if isinstance(given, str):
        try:
            given = json.loads(given)
        except ValueError:
            given = None
    keys = ",".join(sorted(given)) if isinstance(given, dict) else "-"
    return "\t".join((stamp, registration, "payload=" + ",".join(sorted(payload)),
                      f"tool={name}", f"input={shape}", f"input_keys={keys}"))


def main(argv: list[str]) -> int:
    registration = argv[0] if argv else "?"
    try:
        line = row(registration, sys.stdin.read())
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as log:
            log.write(line + "\n")
    except Exception:  # a probe never blocks a tool call
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
