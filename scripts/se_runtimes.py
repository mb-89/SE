# se:template se/python-module 1.0.0
"""The runtimes a component tree needs on the machine, collected and checked before any component runs.

docs/components.md "Runtimes" owns the rule: each component's `se.toml` lists the runtimes it needs
under `[runtimes]`, with a version range each; the needs of an application are the union over its
whole tree; the tree is placed only where the machine holds every one of them. A runtime the machine
lacks is got through the root's `RUNME.conf`, by RUNME itself; one still missing, or present at a
version its range refuses, stops the sync and the start, naming it, who needs it and the remedy.

The machine is one door: `Machine` probes a runtime's version and runs RUNME; `SE_RUNTIMES=fake:<file>`
puts a fake in its place (the tests').
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import shell_door
from se_modules import ModuleError, version_bounds

#: The se.toml table of the runtimes a component needs (docs/components.md "Runtimes").
TABLE = "runtimes"
#: The machine the check reads: unset, this one; `fake:<file>`, a JSON object of what the machine
#: has and what RUNME gets it: `{"have": {"<runtime>": "<version>"}, "get": {"<runtime>": "<version>"}}`.
VARIABLE = "SE_RUNTIMES"
#: The runtimes a declaration names, each with the commands that answer its version (the first on
#: PATH asked) and the pattern that reads the version from the answer. One line adds a runtime.
PROBES: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "go": (("go",), ("version",), r"\bgo(\d+\.\d+(?:\.\d+)?)"),
    "node": (("node",), ("--version",), r"\bv(\d+\.\d+\.\d+)"),
    "python": (("python3", "python"), ("--version",), r"\bPython (\d+\.\d+\.\d+)"),
    "uv": (("uv",), ("--version",), r"\buv (\d+\.\d+\.\d+)"),
}
RUNME_CONF = "RUNME.conf"
RUNME_SH = "RUNME.sh"
#: Where the check writes the RUNME that gets one runtime: RUNME.sh beside a RUNME.conf of that runtime.
GET_DIR = Path(".se") / ".runtime" / "runtimes"
PROBE_TIMEOUT = 20
Version = tuple[int, int, int]


@dataclass(frozen=True)
class Need:
    """One component's need of one runtime: the range it admits and the component's path from the root."""

    runtime: str
    range: str
    path: tuple[str, ...]


def _arrow(path: tuple[str, ...]) -> str:
    return " -> ".join(path)


def parse(data: Mapping, where: str, path: tuple[str, ...]) -> list[Need]:
    """The `[runtimes]` of a component's se.toml `data` (its file named `where`), the component at
    `path`: each a known runtime with a version range in the form of a component pin (README
    "Modules": `^1.22`, `~3.12.1`, `3.12` or `0.5.4`)."""
    table = data.get(TABLE, {})
    if not isinstance(table, dict):
        raise ModuleError(f"{where}: [{TABLE}] must be a table of <runtime> = \"<version range>\"")
    needs = []
    for runtime, text in table.items():
        if runtime not in PROBES:
            raise ModuleError(f"{where}: runtime {runtime!r} is none SE knows; known: {', '.join(sorted(PROBES))} "
                                f"(se_runtimes.py PROBES adds one)")
        if not isinstance(text, str):
            raise ModuleError(f"{where}: runtime {runtime}: its version must be a range string such as \"^1.22\"")
        try:
            version_bounds(runtime, text)
        except ModuleError as error:
            raise ModuleError(f"{where}: runtime {runtime}: {error}") from error
        needs.append(Need(runtime, text, path))
    return needs


def _bounds(need: Need) -> tuple[Version, Version]:
    return version_bounds(need.runtime, need.range)


def _version(text: str) -> Version:
    """A probed version, `1.22` read as `1.22.0`."""
    major, minor, patch = ([int(part) for part in text.split(".")] + [0, 0])[:3]
    return major, minor, patch


def union(needs: list[Need]) -> dict[str, list[Need]]:
    """The tree's needs by runtime, in the order the tree first names each; a runtime whose ranges
    admit no common version refuses, naming both components and both ranges."""
    by_runtime: dict[str, list[Need]] = {}
    for need in needs:
        by_runtime.setdefault(need.runtime, []).append(need)
    for runtime, group in by_runtime.items():
        low = max(_bounds(need)[0] for need in group)
        for need in group:
            if not low < _bounds(need)[1]:
                first = next(other for other in group if _bounds(other)[0] == low)
                raise ModuleError(
                    f"runtime {runtime}: {_arrow(first.path)} needs {first.range} and {_arrow(need.path)} "
                    f"needs {need.range}, and no version of {runtime} admits both; align the two ranges")
    return by_runtime


def admitted(group: list[Need], version: Version) -> bool:
    return all(bounds[0] <= version < bounds[1] for bounds in map(_bounds, group))


class Machine:
    """The machine's runtimes: `version` asks the runtime's own command, `runme` runs RUNME."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path

    def version(self, runtime: str) -> str | None:
        commands, arguments, pattern = PROBES[runtime]
        for command in commands:
            found = shutil.which(command, path=self.path)
            if found is None:
                continue
            try:
                answer = subprocess.run([found, *arguments], capture_output=True, text=True,
                                        timeout=PROBE_TIMEOUT, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            match = re.search(pattern, answer.stdout + answer.stderr)
            if match:
                return match[1]
        return None

    def runme(self, root: Path, folder: Path) -> tuple[int, str]:
        """Run the root's RUNME.sh beside the RUNME.conf in `folder`: its exit code and the last line it wrote."""
        if not (root / RUNME_SH).is_file():
            return 2, f"no {RUNME_SH} in {root} gets it"
        shutil.copy2(root / RUNME_SH, folder / RUNME_SH)
        try:
            done = shell_door.run(["sh", str(folder / RUNME_SH)], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, check=False)
        except OSError as error:
            return 127, f"RUNME could not run: {error}"
        lines = (done.stderr + done.stdout).strip().splitlines()
        return done.returncode, lines[-1] if lines else ""


class FakeMachine:
    """The tests' machine, read from a file: what it has, and what its RUNME gets."""

    def __init__(self, file: Path) -> None:
        data = json.loads(file.read_text(encoding="utf-8"))
        self.have: dict[str, str] = dict(data.get("have", {}))
        self.get: dict[str, str] = dict(data.get("get", {}))
        self.ran: list[str] = []

    def version(self, runtime: str) -> str | None:
        return self.have.get(runtime)

    def runme(self, root: Path, folder: Path) -> tuple[int, str]:
        lines = (folder / RUNME_CONF).read_text(encoding="utf-8").splitlines()
        runtime = next(line.split()[1] for line in lines if line.startswith("need "))
        self.ran.append(runtime)
        if runtime in self.get:
            self.have[runtime] = self.get[runtime]
            return 0, ""
        first = next((line.split(None, 3)[3] for line in lines if line.startswith(f"get {runtime} ")), "")
        return 1, f"RUNME: {runtime} is missing; run: {first}"


def machine(environment: Mapping[str, str] | None = None, root: Path | None = None) -> Machine | FakeMachine:
    """The machine `SE_RUNTIMES` names: a fake where it is `fake:<file>`, else this one, with the
    root's RUNME.conf `path` lines after PATH, as RUNME puts them."""
    value = (os.environ if environment is None else environment).get(VARIABLE, "")
    if value.startswith("fake:"):
        return FakeMachine(Path(value[len("fake:"):]))
    path = os.environ.get("PATH", "")
    if root is not None:
        extra = [str(_at(root, line.split()[1])) for line in _conf_lines(root) if line.split()[:1] == ["path"]
                 and len(line.split()) > 1]
        path = os.pathsep.join([path, *extra])
    return Machine(path)


def _conf_lines(root: Path) -> list[str]:
    conf = root / RUNME_CONF
    return conf.read_text(encoding="utf-8").splitlines() if conf.is_file() else []


def _at(root: Path, place: str) -> Path:
    """A RUNME.conf path as RUNME reads it: `~/` in the home, another relative one in the root."""
    if place.startswith("~/"):
        return Path.home() / place[2:]
    return Path(place) if Path(place).is_absolute() else root / place


def get_conf(root: Path, runtime: str) -> str | None:
    """The RUNME.conf that gets `runtime` alone: the root's `path` lines, made absolute; a `need` per
    command that answers its version; the root's `get` lines of it, a command way run in the root as
    RUNME runs it there; and `run true`. None where the root's RUNME.conf names no way to get it."""
    lines = _conf_lines(root)
    gets = [line.split(None, 3) for line in lines if line.split()[:2] == ["get", runtime]]
    gets = [parts for parts in gets if len(parts) == 4]
    if not gets:
        return None
    out = [f"path {_at(root, line.split()[1]).as_posix()}" for line in lines
           if line.split()[:1] == ["path"] and len(line.split()) > 1]
    out += [f"need {runtime} command {command}" for command in PROBES[runtime][0]]
    for _, name, way, what in gets:
        if way in ("unix", "windows", "any"):
            what = f"cd {shlex.quote(root.as_posix())} && {what}"
        out.append(f"get {name} {way} {what}")
    out.append("run true")
    return "\n".join(out) + "\n"


def check(root: Path, needs: list[Need], door: Machine | FakeMachine | None = None) -> list[str]:
    """Hold the machine to the tree's needs before any component runs: each runtime it lacks is got
    through the root's RUNME.conf by RUNME; the lines say what was got. A runtime still missing, or
    present at a version a range refuses, raises `ModuleError` naming each, its range, the
    components that need it and the remedy."""
    if not needs:
        return []
    door = door or machine(root=root)
    said, refused = [], []
    for runtime, group in union(needs).items():
        ranges = " and ".join(dict.fromkeys(need.range for need in group))
        who = ", ".join(_arrow(need.path) for need in group)
        found = door.version(runtime)
        if found is None:
            conf = get_conf(root, runtime)
            if conf is None:
                refused.append(f"  {runtime} {ranges} (for {who}): missing; {RUNME_CONF} names no way to get it: "
                               f"add a line get {runtime} <way> <what> (RUNME.sh's header), or install {runtime} "
                               "yourself")
                continue
            folder = root / GET_DIR
            folder.mkdir(parents=True, exist_ok=True)
            (folder / RUNME_CONF).write_text(conf, encoding="utf-8", newline="\n")
            code, last = door.runme(root, folder)
            found = door.version(runtime)
            if found is None:
                remedy = last.removeprefix("RUNME: ") if last else f"RUNME exited {code}"
                refused.append(f"  {runtime} {ranges} (for {who}): missing; RUNME could not get it: {remedy}")
                continue
            said.append(f"runtime {runtime} {found}: got through {RUNME_CONF} (for {who})")
        if not admitted(group, _version(found)):
            refused.append(f"  {runtime} {ranges} (for {who}): found {found}, outside the range; install a "
                           f"{runtime} it admits")
    if refused:
        count = f"{len(refused)} runtime{'s' if len(refused) > 1 else ''}"
        raise ModuleError("\n".join([f"the component tree needs {count} this machine lacks; "
                                       "no component runs until each is present:", *refused]))
    return said
