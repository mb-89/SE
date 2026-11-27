"""No SE test refuses work for its time (tst-003): no test asserts on a reading of the real clock.

A test that measures a time records it against its budget instead, through the `measure` fixture
(tests/conftest.py), which `work_tickets.py suite` names and the overhaul's facts collect. An
assert is refused where it holds a duration: a difference of two readings of the clock
(`time.perf_counter`, `monotonic`, `time`, `process_time`, `thread_time`, their `_ns` forms,
`os.times`, or a function of the file that returns one), or a value its scope assigned from such a
difference. A deadline (a hang guard) and a timestamp (`time.time() - 300`) are no durations and
pass, as does a fake clock, a test's own object. The rule
holds from its first day as an error: the cases it found are converted in the change that adds it,
so it needs no warning phase and no baseline.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
CLOCKS = {"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "time", "time_ns",
          "process_time", "process_time_ns", "thread_time", "thread_time_ns"}


def clock_calls(tree: ast.Module) -> set[ast.Call]:
    """The calls in `tree` that read the real clock, under any name an import gives it."""
    modules: dict[str, set[str]] = {"time": set(), "os": set()}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    modules[alias.name].add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            functions |= {alias.asname or alias.name for alias in node.names if alias.name in CLOCKS}
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
            if (called.value.id in modules["time"] and called.attr in CLOCKS) or (
                    called.value.id in modules["os"] and called.attr == "times"):
                found.add(node)
        elif isinstance(called, ast.Name) and called.id in functions:
            found.add(node)
    return found


def scopes(tree: ast.Module) -> list[ast.AST]:
    """The module and each function in it: a value's name counts within its own scope only."""
    return [tree, *(node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))]


def own_nodes(scope: ast.AST):
    """The nodes of `scope`, not of the functions nested in it."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def reads_clock(node: ast.AST, calls: set[ast.Call], readings: set[str], clocks: set[str]) -> bool:
    """Whether `node` reads the clock: a clock call, a reading's name in its scope, or a call of
    a function of the file that returns a reading."""
    return any(child in calls or (isinstance(child, ast.Name) and child.id in readings)
               or (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                   and child.func.id in clocks)
               for child in ast.walk(node))


def measures(node: ast.AST, calls: set[ast.Call], readings: set[str], clocks: set[str],
             durations: set[str]) -> bool:
    """Whether `node` holds a duration: a difference of two clock readings, or the name of a
    value assigned from one."""
    return any((isinstance(child, ast.BinOp) and isinstance(child.op, ast.Sub)
                and reads_clock(child.left, calls, readings, clocks)
                and reads_clock(child.right, calls, readings, clocks))
               or (isinstance(child, ast.Name) and child.id in durations)
               for child in ast.walk(node))


def assigned(scope: ast.AST, holds) -> set[str]:
    """The names `scope` assigns, one by one, from a value for which `holds` is true, a value from
    such a name too; an unpacked tuple's names are not told apart, so they are none."""
    found: set[str] = set()
    while True:
        fresh = set()
        for node in own_nodes(scope):
            if (isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    and node.value is not None and holds(node.value, found)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                fresh |= {target.id for target in targets if isinstance(target, ast.Name)}
        if fresh <= found:
            return found
        found |= fresh


def clock_assertions(source: str) -> list[int]:
    """The lines of `source` whose `assert` holds a duration measured on the real clock."""
    tree = ast.parse(source)
    calls = clock_calls(tree)
    clocks: set[str] = set()
    while True:  # a function that returns a single reading, or a reading of such a function
        fresh = set()
        for scope in scopes(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            readings = assigned(scope, lambda value, found: reads_clock(value, calls, found, clocks))
            if any(isinstance(node, ast.Return) and node.value is not None
                   and not isinstance(node.value, ast.Tuple)
                   and reads_clock(node.value, calls, readings, clocks)
                   for node in own_nodes(scope)):
                fresh.add(scope.name)
        if fresh <= clocks:
            break
        clocks |= fresh
    lines = []
    for scope in scopes(tree):
        readings = assigned(scope, lambda value, found: reads_clock(value, calls, found, clocks))
        durations = assigned(scope, lambda value, found: measures(value, calls, readings, clocks,
                                                                  found))
        lines += [node.lineno for node in own_nodes(scope) if isinstance(node, ast.Assert)
                  and measures(node.test, calls, readings, clocks, durations)]
    return sorted(lines)


def asserting(folder: Path) -> list[str]:
    """`<file>:<line>` of every assert on the real clock in the Python files under `folder`."""
    return [f"{path.relative_to(folder).as_posix()}:{line}"
            for path in sorted(folder.rglob("*.py")) if "__pycache__" not in path.parts
            for line in clock_assertions(path.read_text(encoding="utf-8"))]


def test_an_assert_on_the_clock_is_refused_naming_its_line(tmp_path):
    (tmp_path / "test_budget.py").write_text(
        "import time\n\n\ndef test_fast():\n    started = time.perf_counter()\n"
        "    took = time.perf_counter() - started\n    assert took < 1\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text(
        "from time import monotonic as now\nimport os\n\n\ndef cpu():\n    return sum(os.times()[:2])\n\n\n"
        "start = cpu()\nassert cpu() - start < 10\nbegan = now()\nassert now() - began < 5\n",
        encoding="utf-8")
    assert asserting(tmp_path) == ["helper.py:10", "helper.py:12", "test_budget.py:7"]


def test_a_recorded_measurement_a_hang_guard_and_a_fake_clock_pass(tmp_path):
    (tmp_path / "test_ok.py").write_text(
        "import time\nimport pytest\n\n\ndef test_records(measure, clock):\n"
        "    started = time.perf_counter()\n    measure(time.perf_counter() - started, 1)\n"
        "    deadline = time.monotonic() + 60\n    if time.monotonic() > deadline:\n"
        "        pytest.fail('no answer within 60 s')\n    assert time.monotonic() < deadline\n"
        "    stale = time.time() - 300\n    assert stale + 300 > 0\n    assert clock.now - 0 < 10\n",
        encoding="utf-8")
    assert asserting(tmp_path) == []


def test_no_se_test_asserts_on_the_real_clock():
    assert asserting(TESTS) == [], ("record the time with the measure fixture (tests/conftest.py), "
                                    "or fail a hang guard with pytest.fail (tst-003)")
