"""No command files issues on its own (rule book wrk-007): every path to the issue-create door in
`scripts/` belongs to `work_tickets.py file`, `backlog file` or `route`, the deliberate filing paths
SE uses. Read from the source, so a new script that files an issue fails here, not in the queue."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# The door: the functions that create an issue, through gh or as a plan step for the host's tools.
DOOR = {"filed_once", "filing_plan", "work_issue_filing"}
# The deliberate filing paths: `file`, `backlog file` and `route`, in work_tickets.py.
FILING = {("work_tickets.py", "file_work_issue"), ("work_tickets.py", "backlog_file"),
          ("work_tickets.py", "route_outside_issue")}
CREATES_BY_API = re.compile(r"/issues['\"]?\Z")


def constants(node: ast.AST) -> list[str]:
    return [item.value for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def creates(node: ast.AST) -> str | None:
    """What makes `node` an issue create on its own, or None."""
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [item.value if isinstance(item, ast.Constant) else None for item in node.elts]
        if any(pair == ("issue", "create") for pair in zip(values, values[1:])):
            return "gh issue create"
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and "issue create" in node.value:
        return "gh issue create"
    if isinstance(node, ast.Call):
        strings = constants(node)
        methods = [item for item in ast.walk(node) if isinstance(item, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "method"
            and isinstance(value, ast.Constant) and value.value == "create"
            for key, value in zip(item.keys, item.values))]
        if "issue_write" in strings and methods:
            return "issue_write create"
        if "POST" in strings and any(CREATES_BY_API.search(ast.unparse(argument))
                                     for argument in ast.walk(node)
                                     if isinstance(argument, (ast.Constant, ast.JoinedStr))):
            return "POST issues"
        called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
            node.func, "id", None)
        if called in DOOR:
            return f"calls {called}"
    return None


def door_paths(name: str, source: str) -> list[str]:
    """Every place in script `name` that reaches the issue-create door outside the door itself and
    the deliberate filing paths, as `<script>:<line> <function>: <what>`."""
    found = []
    for top in ast.parse(source).body:
        owner = top.name if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef)) else "<module>"
        if owner in DOOR or (name, owner) in FILING:
            continue
        for node in ast.walk(top):
            what = creates(node)
            if what is not None:
                found.append(f"{name}:{node.lineno} {owner}: {what}")
    return found


def test_only_file_backlog_file_and_route_reach_the_issue_create_door():
    found = [path for script in sorted(SCRIPTS.glob("*.py"))
             for path in door_paths(script.name, script.read_text(encoding="utf-8"))]
    assert found == []


def test_the_door_and_its_filing_paths_are_where_the_check_looks():
    source = (SCRIPTS / "work_tickets.py").read_text(encoding="utf-8")
    defined = {node.name for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    assert DOOR | {owner for _, owner in FILING} <= defined
    assert any(creates(node) for node in ast.walk(ast.parse(source)))


def test_a_script_that_creates_an_issue_is_found():
    fixture = '''
import work_tickets

def report(root, title):
    work_tickets.run_gh(root, ["issue", "create", "--title", title])

def plan(repo, title):
    return Step("create", "issue_write", {"method": "create", "title": title})

def by_api(root, repo):
    run_gh(root, ["api", "-X", "POST", f"repos/{repo}/issues", "-f", "title=x"])

def deduped(root, repo, title, body, filing):
    return work_tickets.filed_once(root, repo, "file", title, body, filing)

def comment(root):
    work_tickets.run_gh(root, ["issue", "comment", "5"])
'''
    assert [path.split(":", 1)[1] for path in door_paths("review.py", fixture)] == [
        "5 report: gh issue create", "8 plan: issue_write create", "11 by_api: POST issues",
        "14 deduped: calls filed_once"]
