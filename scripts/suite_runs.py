"""Whether a suite beside ran a test, read from its output alone (docs/tests.md "Test budget").

`ran(output)` takes a suite's stdout and stderr, stripped, and answers `Ran(verdict, reason)`:
`some` where tests ran, `none` (with a short reason) where none did, `unknown` where the output
says neither. It does no IO and reads no command, so it works whatever command printed it.

This docstring owns which output counts as which:

- A Go package line is one `go test` prints without `-v`: `ok` or `?`, spaces, a tab, the package
  path, a tab, then the rest (`ok  \\tkern/x\\t0.01s [no tests to run]`, `?   \\tkern/cmd\\t[no test
  files]`, `ok  \\tx\\t(cached)`). Go reads `none` where the output holds at least one package line
  and every one ends in `[no test files]` or `[no tests to run]`; `some` where an `ok` line ends in
  neither. Other lines (`PASS`, `=== RUN`, `testing: warning: no tests to run`, `ok in kern`) are
  no package lines.
- A pytest summary line is a comma list of counts followed by ` in <n>s`, with ` (<h:mm:ss>)`
  after it for a run over a minute, with or without `=` banners (`3 skipped in 0.2s`,
  `== 1 passed, 2 skipped in 0.3s ==`). The last such line is read: `none` where it counts only
  skipped, deselected or warning(s); `some` where it counts anything else (passed, failed,
  xfailed, xpassed, error(s)).
- Any other output is `unknown`, never `none`: empty output, a release guard's lines, a count
  without ` in <n>s` (the copilot self-test's). Where the output holds both shapes, `some` from
  either wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SOME, NONE, UNKNOWN = "some", "none", "unknown"

GO_PACKAGE = re.compile(r"(ok|\?) +\t[^\t]+\t(?P<rest>.*)")
GO_EMPTY = ("[no test files]", "[no tests to run]")
PYTEST_SUMMARY = re.compile(
    r"=* *(?P<counts>\d+ [a-z]+(?:, \d+ [a-z]+)*) in \d+(?:\.\d+)?s(?: \(\d+:\d\d:\d\d\))? *=*")
PYTEST_EMPTY = {"skipped", "deselected", "warning", "warnings"}


@dataclass(frozen=True)
class Ran:
    verdict: str  # SOME, NONE or UNKNOWN
    reason: str = ""  # for NONE: why no test ran


def go_reading(lines: list[str]) -> Ran:
    rests = [match["rest"].rstrip() for match in map(GO_PACKAGE.fullmatch, lines) if match]
    if not rests:
        return Ran(UNKNOWN)
    if all(rest.endswith(GO_EMPTY) for rest in rests):
        return Ran(NONE, "every package reads " + " or ".join(
            marker for marker in GO_EMPTY if any(rest.endswith(marker) for rest in rests)))
    return Ran(SOME)


def pytest_reading(lines: list[str]) -> Ran:
    summaries = [match for match in map(PYTEST_SUMMARY.fullmatch, lines) if match]
    if not summaries:
        return Ran(UNKNOWN)
    counts = [count.split(" ", 1) for count in summaries[-1]["counts"].split(", ")]
    if all(kind in PYTEST_EMPTY for _, kind in counts):
        return Ran(NONE, "pytest counted " + ", ".join(f"{n} {kind}" for n, kind in counts)
                   + " and none passed")
    return Ran(SOME)


def ran(output: str) -> Ran:
    """Whether the suite whose `output` this is ran a test (see the module's docstring)."""
    lines = [line.strip("\r") for line in output.splitlines()]
    readings = [go_reading(lines), pytest_reading([line.strip() for line in lines])]
    for verdict in (SOME, NONE):
        for reading in readings:
            if reading.verdict == verdict:
                return reading
    return Ran(UNKNOWN)
