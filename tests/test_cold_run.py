"""The cold run's record (`docs/copilot-cold-run.toml`) and its pure reader
(`scripts/cold_run.py`): the shipped record is blank and follows the Monday checklist of
`docs/copilot.md`, the reader reports what a record says and never a pass, names a malformed
record's line, and stays pure and off by default. Every record but the shipped one is made up."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

import cold_run
from cold_run import NOT_RUN, main, report

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "copilot-cold-run.toml"
CHECKLIST = ROOT / "docs" / "copilot.md"


def checklist_steps() -> list[tuple[int, str]]:
    """The numbered steps of the Monday checklist: number and bold short name."""
    text = CHECKLIST.read_text(encoding="utf-8")
    section = text.split("## Monday checklist", 1)[1].split("\n## ", 1)[0]
    section = section.split("\n### ", 1)[0]
    return [(int(number), name.rstrip("."))
            for number, name in re.findall(r"^(\d+)\. \*\*(.+?)\*\*", section, re.MULTILINE)]


def step_block(number: int, result: str, minutes: int, beyond: str) -> tuple[str, str]:
    """The shipped lines of one step's result, minutes and beyond, and their filled form."""
    text = RECORD.read_text(encoding="utf-8")
    start = text.index(f"number = {number}\n")
    old = text[start:text.index('beyond = "nothing"\n', start) + len('beyond = "nothing"\n')]
    new = (old.replace(f'result = "{NOT_RUN}"', f'result = "{result}"')
              .replace("minutes = 0", f"minutes = {minutes}")
              .replace('beyond = "nothing"', f'beyond = "{beyond}"'))
    return old, new


def fill(text: str, number: int, result: str, minutes: int, beyond: str = "nothing") -> str:
    old, new = step_block(number, result, minutes, beyond)
    start = text.index(f"number = {number}\n")
    assert text[start:start + len(old)] == old
    return text[:start] + new + text[start + len(old):]


# The shipped record


def test_the_shipped_record_has_every_step_not_run_and_the_asked_fields_empty():
    data = tomllib.loads(RECORD.read_text(encoding="utf-8"))
    assert [step["result"] for step in data["step"]] == [NOT_RUN] * len(data["step"])
    assert {step["minutes"] for step in data["step"]} == {0}
    assert {step["beyond"] for step in data["step"]} == {"nothing"}
    assert {key: value.strip() for key, value in data["asked"].items()} == {
        "dispatch": "", "tools": "", "manifest": ""}
    assert data["run"] == {"host": "", "platform": "", "date": ""}
    assert data["proof"] == {"doctor": ""}


def test_the_shipped_records_steps_are_the_numbered_steps_of_the_monday_checklist():
    data = tomllib.loads(RECORD.read_text(encoding="utf-8"))
    steps = checklist_steps()
    assert len(steps) >= 2
    assert [(step["number"], step["name"]) for step in data["step"]] == steps


def test_the_checklist_reader_finds_a_numbered_step():
    assert checklist_steps()[0] == (1, "Copilot CLI, SE's checkout")


def test_docs_copilot_md_points_the_notes_at_the_record():
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "[`copilot-cold-run.toml`](copilot-cold-run.toml)" in text


# The reader


def test_a_record_with_every_step_not_run_reports_nothing_run_and_never_a_pass():
    out = report(RECORD.read_text(encoding="utf-8"))
    assert out.splitlines()[-1] == "verdict: nothing run"
    assert "steps: 0 of 9 run, 0 as expected, 0 differ, 9 not run" in out
    assert "differs: none" in out
    assert "beyond the written step: none" in out
    assert "minutes: 0" in out
    assert "dispatch: not recorded" in out
    assert "tools: not recorded" in out
    assert "manifest: not recorded" in out
    assert "malformed" not in out
    assert "pass" not in out.lower()


def test_a_made_up_record_shows_a_difference_a_step_beyond_the_dispatch_tools_and_manifest():
    text = RECORD.read_text(encoding="utf-8")
    text = fill(text, 1, "as expected", 12)
    text = fill(text, 2, "differs", 20, "trusted the folder twice")
    text = fill(text, 3, "as expected", 5, "named the label by hand")
    text = text.replace('host = ""', 'host = "Copilot CLI 1.0.112"', 1)
    text = text.replace('platform = ""', 'platform = "Linux"', 1)
    text = text.replace('date = ""', 'date = "2026-11-16"', 1)
    text = text.replace('dispatch = ""', 'dispatch = "yes"', 1)
    text = text.replace('tools = """\n"""', 'tools = """\nse-status, se-tickets\n"""', 1)
    text = text.replace('manifest = ""', 'manifest = ".github/plugin/plugin.json"', 1)
    text = text.replace('doctor = ""', 'doctor = "copilot-cold-run.doctor.txt"', 1)
    out = report(text)
    assert out.splitlines() == [
        "cold run: Copilot CLI 1.0.112, Linux, 2026-11-16",
        "steps: 3 of 9 run, 2 as expected, 1 differ, 6 not run",
        "differs:",
        "  step 2 (VS Code, SE's checkout)",
        "beyond the written step:",
        "  step 2 (VS Code, SE's checkout): trusted the folder twice",
        "  step 3 (A real request, on a safe target): named the label by hand",
        "minutes: 37",
        "dispatch: yes",
        "tools: recorded",
        "manifest: .github/plugin/plugin.json",
        "doctor's report: copilot-cold-run.doctor.txt",
        "verdict: 3 of 9 steps run, 1 differ",
    ]
    assert "pass" not in out.lower()


@pytest.mark.parametrize("dispatch", ["no", "not run"])
def test_the_dispatch_result_is_reported_as_recorded(dispatch):
    text = RECORD.read_text(encoding="utf-8").replace('dispatch = ""', f'dispatch = "{dispatch}"')
    assert f"dispatch: {dispatch}\n" in report(text)


def test_a_record_that_is_not_toml_is_named_with_its_line():
    text = RECORD.read_text(encoding="utf-8").replace('minutes = 0', 'minutes = = 3', 1)
    line = next(index for index, row in enumerate(text.splitlines(), 1) if "= = 3" in row)
    out = report(text)
    assert out.startswith("cold run: the record is malformed\n")
    assert f"malformed: line {line}: " in out
    assert out.splitlines()[-1] == "verdict: nothing read"


def test_a_step_with_an_unknown_result_and_bad_minutes_is_named_with_their_lines():
    text = RECORD.read_text(encoding="utf-8")
    text = fill(text, 4, "fine", 3)
    text = text.replace("minutes = 3", 'minutes = "a few"', 1)
    rows = text.splitlines()
    result_line = rows.index('result = "fine"') + 1
    minutes_line = rows.index('minutes = "a few"') + 1
    out = report(text)
    assert f"malformed: line {result_line}: step 4: result 'fine' is not one of" in out
    assert f"malformed: line {minutes_line}: step 4: minutes 'a few'" in out
    assert out.splitlines()[-1] == "verdict: nothing run"


def test_an_unknown_dispatch_is_named_with_its_line():
    text = RECORD.read_text(encoding="utf-8").replace('dispatch = ""', 'dispatch = "maybe"')
    line = text.splitlines().index('dispatch = "maybe"') + 1
    out = report(text)
    assert f"malformed: line {line}: dispatch 'maybe' is not one of" in out
    assert "dispatch: not recorded" in out


def test_a_record_without_steps_is_named():
    out = report('[run]\nhost = ""\n')
    assert "malformed: the record: no [[step]] entries" in out
    assert out.splitlines()[-1] == "verdict: nothing run"


def test_the_command_exits_0_on_a_malformed_record(tmp_path, capsys):
    record = tmp_path / "record.toml"
    record.write_text("[[step]\nnumber = \n", encoding="utf-8")
    assert main(["report", str(record)]) == 0
    assert "malformed: line 1: " in capsys.readouterr().out


def test_the_command_reports_the_shipped_record(capsys):
    assert main(["report", str(RECORD)]) == 0
    assert capsys.readouterr().out.endswith("verdict: nothing run\n")


def test_a_record_it_cannot_read_exits_2(tmp_path, capsys):
    assert main(["report", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read" in capsys.readouterr().err


# Pure and off by default


def imported(source: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_reader_imports_nothing_from_se_and_nothing_that_reaches_outside():
    names = imported(Path(cold_run.__file__).read_text(encoding="utf-8"))
    assert names <= {"__future__", "argparse", "dataclasses", "re", "sys", "tomllib"}


def test_the_report_function_opens_no_file():
    tree = ast.parse(Path(cold_run.__file__).read_text(encoding="utf-8"))
    report_node = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "report")
    calls = {node.func.id for node in ast.walk(report_node)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "open" not in calls


def tracked_text(paths) -> list[str]:
    found = []
    for base in paths:
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "cold_run" in text or "copilot-cold-run" in text:
                found.append(path.relative_to(ROOT).as_posix())
    return found


def test_nothing_that_starts_or_loads_se_names_the_reader_or_the_record():
    places = [ROOT / "src", ROOT / "agents", ROOT / "skills", ROOT / ".github" / "agents",
              ROOT / ".github" / "skills", ROOT / ".github" / "hooks", ROOT / ".githooks",
              ROOT / ".claude-plugin", ROOT / "hooks", ROOT / "README.md", ROOT / "se.toml"]
    assert tracked_text([place for place in places if place.exists()]) == []


def test_no_other_script_names_the_reader():
    scripts = [path for path in (ROOT / "scripts").glob("*.py") if path.stem != "cold_run"]
    assert tracked_text(scripts) == []
