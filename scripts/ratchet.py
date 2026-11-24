# se:template se/python-module 1.0.0
"""A count that may only shrink: found counts per path against a baseline, in a mode.

`compare(found, baseline, mode)` returns `(new, gone)`, two sorted lists of paths:

- `"off"`, the default: two empty lists, whatever it is given;
- `"report"`: `new` holds each path whose found count is over its baseline (0 where it has none),
  `gone` each baseline path whose found count is under its entry, as hygiene's git-door check
  counts today (scripts/hygiene.py, `git_door_findings`).

Any other mode, `"refuse"` among them, raises a ValueError: refusing is the owner's step to take.
It reads no file and calls nothing; a caller passes the counts in.
"""

from __future__ import annotations

from collections.abc import Mapping

MODES = ("off", "report")


def compare(found: Mapping[str, int], baseline: Mapping[str, int], mode: str = "off") -> tuple[list[str], list[str]]:
    """The paths over their baseline (`new`) and the baseline paths under it (`gone`), in `mode`."""
    if mode not in MODES:
        raise ValueError(f"ratchet mode {mode!r} is not one of {', '.join(MODES)}: "
                         "refusing is the owner's step, not this helper's")
    if mode == "off":
        return [], []
    new = sorted(path for path, count in found.items() if count > baseline.get(path, 0))
    gone = sorted(path for path, count in baseline.items() if found.get(path, 0) < count)
    return new, gone
