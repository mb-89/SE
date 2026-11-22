"""No SE test waits on the wall clock (tst-002): no test module or fixture calls `time.sleep`.

A test waits on an event instead (tests/waiting.py), with one deadline that fires only where the
event never comes. The text of a script a test runs as a child process is a string, not this
module's code, so a child that sleeps to prove a time bound kills it (tests/test_time_bound.py)
keeps its sleep.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def sleeps(source: str) -> list[int]:
    """The lines of `source` that call `time.sleep`, under any name an import gives it."""
    tree = ast.parse(source)
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == "time"}
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            functions |= {alias.asname or alias.name for alias in node.names if alias.name == "sleep"}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if (isinstance(called, ast.Attribute) and called.attr == "sleep"
                and isinstance(called.value, ast.Name) and called.value.id in modules):
            lines.append(node.lineno)
        elif isinstance(called, ast.Name) and called.id in functions:
            lines.append(node.lineno)
    return sorted(lines)


def sleeping(folder: Path) -> list[str]:
    """`<file>:<line>` of every `time.sleep` call in the Python files under `folder`."""
    return [f"{path.relative_to(folder).as_posix()}:{line}"
            for path in sorted(folder.rglob("*.py")) if "__pycache__" not in path.parts
            for line in sleeps(path.read_text(encoding="utf-8"))]


def test_a_sleep_in_a_test_module_is_refused_naming_its_line(tmp_path):
    (tmp_path / "test_waits.py").write_text(
        "import time\n\n\ndef test_waits():\n    time.sleep(0.1)\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text(
        "from time import sleep as nap\nimport time as clock\nnap(1)\nclock.sleep(2)\n", encoding="utf-8")
    assert sleeping(tmp_path) == ["helper.py:3", "helper.py:4", "test_waits.py:5"]


def test_a_sleep_in_the_text_of_a_child_script_passes(tmp_path):
    (tmp_path / "test_child.py").write_text(
        'import time\nCHILD = "import time\\ntime.sleep(60)\\n"\n\n\ndef test_child():\n'
        '    assert time.monotonic()\n', encoding="utf-8")
    assert sleeping(tmp_path) == []


def test_no_se_test_module_or_fixture_sleeps():
    assert sleeping(TESTS) == [], "wait on an event, not the clock (tests/waiting.py, tst-002)"
