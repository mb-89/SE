"""Recorded outputs: a test holds a whole output to its text in `tests/recorded/<name>.txt`.

    recorded(name, text)

compares `text`, after SUBSTITUTIONS, with the recorded file and fails with a unified diff and the
one command that rewrites it. The text is kept, not a hash, so the diff shows what changed. Only
with `SE_RECORD=1` set is the file written instead, a change the pull request shows.

What changes from run to run (the clock, the version, a session id, a path of this machine) is
replaced by the named substitutions below, the one place that lists them, so a recording passes
the public check and is byte-stable. Pure: nothing but this module and the test that names a
recording reads it; no command, hook or check calls it. A later issue registers its off-state
output with one line in `tests/test_recorded_outputs.py`.
"""

from __future__ import annotations

import difflib
import os
import re
import tempfile
import tomllib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = Path(__file__).resolve().parent / "recorded"
VARIABLE = "SE_RECORD"


def _version() -> str | None:
    version = tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8")).get("project", {}).get("version")
    return version if isinstance(version, str) else None


def _literal(value: str | None, placeholder: str) -> Callable[[str], str]:
    """Replace one exact string, where it is known and not empty."""
    return (lambda text: text.replace(value, placeholder)) if value else (lambda text: text)


def _pattern(pattern: str, placeholder: str) -> Callable[[str], str]:
    compiled = re.compile(pattern)
    return lambda text: compiled.sub(placeholder, text)


def _paths(path: Path, placeholder: str) -> Callable[[str], str]:
    """Replace a directory as the OS writes it and as posix, longest spelling first; a root or a
    one-part directory (a home of `/`) is left alone, as replacing it would cut every path."""
    if len(path.parts) < 3:
        return lambda text: text
    spellings = sorted({str(path), path.as_posix()}, key=len, reverse=True)
    def substitute(text: str) -> str:
        for spelling in spellings:
            text = text.replace(spelling, placeholder)
        return text
    return substitute


# Every substitution, by name, in the order applied: paths before the patterns that could cut into them.
SUBSTITUTIONS: dict[str, Callable[[str], str]] = {
    "checkout": _paths(ROOT, "<checkout>"),
    "temp": _paths(Path(tempfile.gettempdir()).resolve(), "<tmp>"),
    "home": _paths(Path.home(), "~"),
    "clock": _pattern(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2}| UTC)?",
                      "<time>"),
    "se version": _literal(_version(), "<se-version>"),
    "session id": _pattern(r"\bsession_[0-9A-Za-z]{16,}\b", "<session>"),
}


def normalise(text: str) -> str:
    """`text` with every substitution applied and its line ends as `\\n`."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for substitute in SUBSTITUTIONS.values():
        text = substitute(text)
    return text


def rewrite_command(name: str) -> str:
    """The one command that rewrites the recording `name` from the code as it is."""
    return f"SE_RECORD=1 uv run pytest -q tests/test_recorded_outputs.py -k {name}"


class Differs(AssertionError):
    """A text that differs from its recording, or has none."""


def recorded(name: str, text: str, directory: Path = RECORDINGS) -> None:
    """Hold `text` to `<directory>/<name>.txt`; with SE_RECORD=1, write it there instead."""
    path = directory / f"{name}.txt"
    actual = normalise(text)
    if os.environ.get(VARIABLE) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(actual.encode("utf-8"))
        return
    if not path.exists():
        raise Differs(f"no recording {path.name} for {name}; record it with: {rewrite_command(name)}")
    expected = normalise(path.read_bytes().decode("utf-8"))
    if expected == actual:
        return
    diff = "".join(difflib.unified_diff(expected.splitlines(keepends=True), actual.splitlines(keepends=True),
                                        f"recorded/{path.name}", f"{name} now"))
    raise Differs(f"{name} differs from its recording:\n{diff}\nwhere the change is meant, rewrite it with: "
                  f"{rewrite_command(name)}")
