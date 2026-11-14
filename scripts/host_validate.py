#!/usr/bin/env python3
"""The hosts' own validators over the layouts SE generates: a report, run by hand, called by nothing.

SE's own lint (scripts/agent_lint.py, run by the build) stays the first line; this holds the built
layouts to the real hosts, so a manifest key a host strips or a skill a host would skip shows before
a session meets it (README "Host validators").

The validators are one table of data, `VALIDATORS`: name, host, tool, argument list, the layout
paths it reads (each a glob relative to the root, one run per match) and the tool version its
expectations were written against. `report` turns the tools' answers into the report; every
process starts through the one `runner` handed in, so tests pass a fake.

    host_validate.py [--root <dir>] [--skips-pass] [--timeout <seconds>]

Exit codes, as public_check.py uses them: 0 every validator that ran passed, 1 a host refused a
layout (the file and the host's own message are printed), 2 a validator could not run (tool absent,
older than its pinned version, timed out). `--skips-pass` answers 0 where the only shortfall is an
absent tool. A host without a validator is listed and never counted as passed.

Off by default: no se.toml beside suite, workflow, hook, role or skill runs it. Putting the hosts'
validators into every integration is the owner's step: a `[tests.beside.host-validators]` entry in
se.toml running `uv run pytest -q -n 0 tests/beside_host_validators.py`.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

EXIT_PASSED, EXIT_REFUSED, EXIT_NOT_RUN = 0, 1, 2
TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class Validator:
    """One host's validator, as data. `tool` None is a host without one: `note` says how it is
    checked instead. `args` come before each target; `refuses` are the exit codes that mean the host
    refused the target (any other nonzero code is a validator that could not run)."""

    name: str
    host: str
    tool: str | None
    args: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)
    pinned: str = ""
    refuses: tuple[int, ...] = (1,)
    note: str = ""


# Run on the repository root, `claude plugin validate` checks only the marketplace manifest (its own
# output says so), so each manifest is its own target. skills-ref is the Agent Skills project's
# reference validator (agentskills.io), one skill folder per run. The Copilot CLI has no validate
# command.
VALIDATORS: tuple[Validator, ...] = (
    Validator(name="claude plugin validate", host="Claude Code", tool="claude",
              args=("plugin", "validate", "--strict"),
              reads=(".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"), pinned="2.1.325"),
    Validator(name="skills-ref validate", host="Agent Skills", tool="skills-ref", args=("validate",),
              reads=("skills/*/", ".github/skills/*/"), pinned="0.1.0"),
    Validator(name="Copilot CLI", host="GitHub Copilot", tool=None,
              note="no validator; checked by hand on the Monday checklist"),
)


@dataclass(frozen=True)
class Answer:
    """What a process gave back: its exit code and output, or that it could not start or ran out of
    time."""

    code: int | None = None
    output: str = ""
    absent: bool = False
    timed_out: bool = False


Runner = Callable[[Sequence[str], Path, float], Answer]


@dataclass(frozen=True)
class Result:
    """One validator's answers: its version check (None where it has no tool) and one answer per
    target, empty where it did not get that far."""

    validator: Validator
    targets: tuple[str, ...] = ()
    version: Answer | None = None
    answers: tuple[Answer, ...] = ()


VERSION = re.compile(r"\d+(?:\.\d+)+")


def version_of(text: str) -> tuple[int, ...] | None:
    """The first dotted version a tool prints, as numbers."""
    found = VERSION.search(text)
    return tuple(int(part) for part in found.group().split(".")) if found else None


def shortfall(validator: Validator, version: Answer) -> str | None:
    """Why a validator cannot run, from its version check; None where it can."""
    if version.absent:
        return "not installed"
    if version.timed_out:
        return "timed out reading its version"
    found = version_of(version.output) if version.code == 0 else None
    if found is None:
        return "version unreadable"
    pinned = version_of(validator.pinned)
    if pinned is not None and found < pinned:
        return f"version {'.'.join(map(str, found))} is older than the pinned {validator.pinned}"
    return None


def report(results: Sequence[Result], skips_pass: bool = False) -> tuple[list[str], int]:
    """The report's lines and exit code from the validators' answers."""
    lines: list[str] = []
    passed = refused = skipped = unchecked = 0
    absent_only = True
    for result in results:
        validator = result.validator
        label = f"{validator.host}: {validator.name}"
        if validator.tool is None:
            unchecked += 1
            lines.append(f"unchecked {label}: {validator.note}")
            continue
        reason = shortfall(validator, result.version) if result.version else "not run"
        if reason is None and not result.targets:
            reason = "no layout to read (" + ", ".join(validator.reads) + "); run the build first"
        if reason is not None:
            skipped += max(len(result.targets), 1)
            absent_only = absent_only and reason == "not installed"
            lines.append(f"skipped {label}: {validator.tool} {reason}")
            continue
        for target, answer in zip(result.targets, result.answers):
            if answer.code == 0:
                passed += 1
                lines.append(f"passed {label} {target}")
            elif answer.code in validator.refuses:
                refused += 1
                lines.append(f"refused {label} {target}:")
                lines.extend(f"    {line}" for line in answer.output.strip().splitlines())
            else:
                skipped += 1
                absent_only = False
                why = "timed out" if answer.timed_out else ("not installed" if answer.absent
                                                            else f"exited {answer.code}")
                lines.append(f"skipped {label} {target}: {validator.tool} {why}")
    lines.append(f"host validators: {passed} passed, {refused} refused, {skipped} skipped, "
                 f"{unchecked} without a validator")
    if refused:
        return lines, EXIT_REFUSED
    if skipped and not (skips_pass and absent_only):
        return lines, EXIT_NOT_RUN
    return lines, EXIT_PASSED


def targets(root: Path, validator: Validator) -> tuple[str, ...]:
    """The layout paths a validator reads that exist under root, relative and with `/`."""
    found: list[str] = []
    for pattern in validator.reads:
        folder = pattern.endswith("/")
        for path in sorted(root.glob(pattern.rstrip("/"))):
            if path.is_dir() == folder:
                found.append(path.relative_to(root).as_posix())
    return tuple(found)


def collect(root: Path, runner: Runner, validators: Sequence[Validator] = VALIDATORS,
            timeout: float = TIMEOUT_SECONDS) -> list[Result]:
    """Every validator's answers over the layouts under root, each process through runner."""
    results: list[Result] = []
    for validator in validators:
        if validator.tool is None:
            results.append(Result(validator))
            continue
        paths = targets(root, validator)
        version = runner([validator.tool, *validator.version_args], root, timeout)
        answers: tuple[Answer, ...] = ()
        if shortfall(validator, version) is None:
            answers = tuple(runner([validator.tool, *validator.args, path], root, timeout) for path in paths)
        results.append(Result(validator, paths, version, answers))
    return results


def run_process(argv: Sequence[str], cwd: Path, timeout: float) -> Answer:
    """The real runner: a process without a shell, its output and errors together."""
    tool = shutil.which(argv[0])
    if tool is None:
        return Answer(absent=True)
    try:
        done = subprocess.run([tool, *argv[1:]], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return Answer(timed_out=True)
    except OSError:
        return Answer(absent=True)
    return Answer(done.returncode, (done.stdout or "") + (done.stderr or ""))


def main(argv: Sequence[str] | None = None, runner: Runner = run_process,
         validators: Sequence[Validator] = VALIDATORS) -> int:
    parser = argparse.ArgumentParser(
        description="Run the hosts' own validators over SE's generated layouts and report.",
        epilog="Off by default: nothing runs it. To put it into every integration, the owner adds "
               "[tests.beside.host-validators] to se.toml with command "
               '["uv", "run", "pytest", "-q", "-n", "0", "tests/beside_host_validators.py"]. '
               "Exit codes: 0 passed, 1 a host refused a layout, 2 a validator could not run.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="the repository whose built layouts are checked (default: this se)")
    parser.add_argument("--skips-pass", action="store_true",
                        help="answer 0 where the only shortfall is an absent tool")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS,
                        help=f"seconds per validator run (default {TIMEOUT_SECONDS:g})")
    options = parser.parse_args(argv)
    lines, code = report(collect(options.root.resolve(), runner, validators, options.timeout),
                         options.skips_pass)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
