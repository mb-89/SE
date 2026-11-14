"""A positive control for a sweep: a sweep that finds nothing on a tree it should find something in
fails here, naming itself, before any test trusts its silence on the real tree."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pytest


def positive_control(name: str, sweep: Callable[[Path], Iterable[object]], tree: Path, path: str, text: str,
                     member: object) -> list[object]:
    """Plant `text` at `path` under `tree`, run `sweep` on `tree`, and fail, naming the sweep and the
    member, when `member` is missing from what it found; returns what it found."""
    planted = tree / Path(path)
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(text, encoding="utf-8")
    found = list(sweep(tree))
    if member not in found:
        pytest.fail(f"positive control: the sweep {name} did not find its planted member {member!r} "
                    f"({len(found)} found)")
    return found
