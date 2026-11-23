"""The discovery budget (guidance note discover-cheap-load-late): SE's command list,
`se_components.py commands`, reads the components' declarations alone and loads none of their code,
within the budget the note states in its `toml` block, read from the note itself, however many
commands there are.

Each fixture component's `__init__.py` is a tripwire: loading it records the component's name, and
the budget fails on any record, naming the component, and on a listing slower than the budget. The
time is the fastest of three runs, as the suite runs beside other tests; a tripwire fails at once.
The note's seconds are the Linux host's the suite's time bound was measured on; on a platform that
runs the suite slower, the budget scales as the time bound does (tests/time_bound.py SCALE)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
import time_bound

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "se_components.py"
NOTE = ROOT / "guidance" / "discover-cheap-load-late.md"
BUDGET = tomllib.loads(re.search(r"^```toml\n(.*?)^```$",  # a CRLF checkout reads as LF
                                 NOTE.read_text(encoding="utf-8").replace("\r\n", "\n"),
                                 re.MULTILINE | re.DOTALL).group(1))
RUNS = 3
SECONDS = BUDGET["budget_seconds"] * time_bound.SCALE

Listing = Callable[[Path], list[str]]


def declaration(name: str, commands: int) -> str:
    """A fixture component.toml of `commands` interactive commands, as kern reads one."""
    lines = [f'name = "{name}"', "contract = 1", f'help = "Fixture component {name}."', ""]
    for n in range(commands):
        lines += [f'[commands."{name} run-{n}"]', f'usage = "{name} run-{n} [--json]"',
                  f'summary = "run fixture command {n} of {name}"', 'group = "Fixtures"',
                  f'help = "Runs fixture command {n} of {name}."', 'class = "interactive"', ""]
    return "\n".join(lines)


def catalog(root: Path, tripwires: Path, components: int, commands: int,
            folder: str = "components") -> list[str]:
    """`components` fixture components under root/<folder>, each with a tripwire `__init__.py`; the
    names of every command they declare."""
    tripwires.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(components):
        name = f"fixture-{i:03d}"
        home = root / folder / name
        home.mkdir(parents=True)
        (home / "component.toml").write_text(declaration(name, commands), encoding="utf-8")
        (home / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(tripwires / name)!r}).touch()\n", encoding="utf-8")
        names += [f"{name} run-{n}" for n in range(commands)]
    return names


def command_list(root: Path) -> list[str]:
    """The command list as a person runs it, the interpreter's start included."""
    done = subprocess.run([sys.executable, str(SCRIPT), "commands", "--json", "--root", str(root)],
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return [entry["command"] for entry in json.loads(done.stdout)]


def command_list_in_process(root: Path) -> list[str]:
    """The command list through `se_components.main`, in this process."""
    import se_components

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert se_components.main(["commands", "--json", "--root", str(root)]) == 0
    return [entry["command"] for entry in json.loads(out.getvalue())]


def loading_list(root: Path) -> list[str]:
    """A listing that loads each component's code before it reads the declarations: what the
    budget exists to refuse."""
    for init in sorted((root / "components").glob("*/__init__.py")):
        spec = importlib.util.spec_from_file_location(f"loaded_{init.parent.name}", init)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    return command_list_in_process(root)


def budget_findings(listing: Listing, root: Path, tripwires: Path, expected: list[str]) -> list[str]:
    """What breaks the budget: each component loaded at discovery, each command not listed, and
    a listing slower than the budget in each of its runs."""
    fastest = float("inf")
    for _ in range(RUNS):
        started = time.perf_counter()
        listed = listing(root)
        fastest = min(fastest, time.perf_counter() - started)
        loaded = sorted(p.name for p in tripwires.iterdir())
        if loaded:
            return [f"{name}: loaded at discovery" for name in loaded]
        if fastest <= SECONDS:
            break
    findings = [f"{name}: not listed" for name in sorted(set(expected) - set(listed))]
    if fastest > SECONDS:
        findings.append(f"the fastest of {RUNS} listings took {fastest:.2f} s, over the budget of "
                        f"{SECONDS:.2f} s")
    return findings


@pytest.fixture
def fixtures(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    root, tripwires = tmp_path / "checkout", tmp_path / "tripwires"
    expected = catalog(root, tripwires, BUDGET["components"], BUDGET["commands_per_component"])
    return root, tripwires, expected


@pytest.mark.spawns("entry: scripts/se_components.py; its budget counts the interpreter's start "
                    "(guidance note discover-cheap-load-late), so the listing runs as a person runs it")
def test_the_command_list_reads_every_declaration_within_the_budget_and_loads_none(fixtures):
    root, tripwires, expected = fixtures
    assert len(expected) == BUDGET["components"] * BUDGET["commands_per_component"]
    assert budget_findings(command_list, root, tripwires, expected) == []


def test_a_listing_that_loads_what_it_lists_fails_the_budget_naming_each_component(fixtures):
    root, tripwires, expected = fixtures
    findings = budget_findings(loading_list, root, tripwires, expected)
    assert len(findings) == BUDGET["components"]
    assert findings[0] == "fixture-000: loaded at discovery"


def test_the_list_names_each_command_with_its_usage_summary_and_kind(capsys):
    import se_components

    assert se_components.main(["commands", "--json", "--root", str(ROOT)]) == 0
    entries = {e["command"]: e for e in json.loads(capsys.readouterr().out)}
    assert entries["se_guidance.py collect"] == {
        "command": "se_guidance.py collect", "component": "guidance", "group": "Guidance",
        "usage": "se_guidance.py collect (--template TEMPLATE | --tags TAGS) [--json] [--session SESSION]\n"
                 "                       [--page PAGE] [--root ROOT]",
        "summary": "print the guidance a template or a set of tags gets, general first",
        "class": "interactive"}
    assert se_components.main(["commands", "--root", str(ROOT)]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("se_guidance.py collect "))
    assert line.endswith("  (guidance, interactive)")
    assert "print the guidance a template or a set of tags gets, general first" in line


def test_the_list_reads_the_ad_hoc_components_after_the_tracked_ones(tmp_path, capsys):
    import se_components

    tripwires = tmp_path / "tripwires"
    tracked = catalog(tmp_path, tripwires, 1, 1)
    ad_hoc = catalog(tmp_path / ".se", tripwires / "ad-hoc", 1, 2)
    assert se_components.main(["commands", "--json", "--root", str(tmp_path)]) == 0
    assert [e["command"] for e in json.loads(capsys.readouterr().out)] == tracked + ad_hoc
    assert not any(tripwires.rglob("fixture-*"))


def test_a_declaration_kern_refuses_is_named_and_the_rest_listed(tmp_path, capsys):
    import se_components

    catalog(tmp_path, tmp_path / "tripwires", 2, 1)
    broken = tmp_path / "components" / "fixture-000" / "component.toml"
    broken.write_text(broken.read_text(encoding="utf-8").replace('class = "interactive"\n', ""),
                      encoding="utf-8")
    assert se_components.main(["commands", "--json", "--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert [e["command"] for e in json.loads(captured.out)] == ["fixture-001 run-0"]
    assert "fixture-000" in captured.err and "component.toml" in captured.err
