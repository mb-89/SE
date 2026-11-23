"""`decision_rows.py`: the Decisions rows of made-up field reports through the pure core, and of a
window's landings through `list` from saved answers (the session's GitHub tools, without gh)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import decision_rows
import work_tickets

ROOT = Path(__file__).resolve().parents[1]
REPO = "github.com/owner/repo"
HEADER = "| Decision | Alternatives | Rationale | Confidence |\n|---|---|---|---|\n"


def body(decisions: str | None, result: str = "complete") -> str:
    """A pull request description carrying a field report whose Decisions section is
    `decisions` (None: no such section)."""
    section = "" if decisions is None else (
        "## Decisions\n\n<!-- Every decision taken without the user. -->\n\n" + decisions + "\n")
    return (f"Fixes https://github.com/owner/repo/issues/1\n\n{work_tickets.REPORT_BEGIN}\n"
            f"**Work issue:** #1  **Branch:** `feat/a`  **Result:** {result}\n\n"
            f"## Not delivered\n\nNone\n\n{section}## Spec gaps\n\nNone\n\n"
            f"{work_tickets.REPORT_END}\n")


def test_two_rows_come_out_in_order_with_the_result():
    report = decision_rows.parse(body(
        HEADER + "| Keep A | B, C | A is smaller | high |\n| Name it x | y | shorter | medium |\n",
        result="partial"))

    assert report.state == decision_rows.DECIDED and report.result == "partial"
    assert [(row.status, row.decision, row.alternatives, row.rationale, row.confidence)
            for row in report.rows] == [
        ("parsed", "Keep A", "B, C", "A is smaller", "high"),
        ("parsed", "Name it x", "y", "shorter", "medium")]


@pytest.mark.parametrize(("decisions", "state"), [
    ("None", decision_rows.NONE),
    ("None.", decision_rows.NONE),
    (HEADER, decision_rows.NONE),
    (HEADER + "| None | | | |\n", decision_rows.NONE),
    ("", decision_rows.NONE),
    (None, decision_rows.NO_SECTION),
])
def test_none_an_empty_table_and_a_missing_section_give_no_rows(decisions, state):
    report = decision_rows.parse(body(decisions))

    assert report.rows == () and report.state == state


def test_a_description_without_a_report_gives_no_rows():
    assert decision_rows.parse("Lands a pull request.") == decision_rows.Report("no-report")


def test_a_missing_cell_and_a_changed_header_come_out_unparsed_with_their_text():
    missing = decision_rows.parse(body(HEADER + "| Keep A | B | high |\n| Keep C | D | E | low |"))
    header = "| Decision | Why | Confidence |\n|---|---|---|\n| Keep A | small | high |"
    changed = decision_rows.parse(body(header))
    prose = decision_rows.parse(body("- Kept A, as it is smaller."))

    assert [(row.status, row.text, row.decision) for row in missing.rows] == [
        ("unparsed", "| Keep A | B | high |", ""), ("parsed", "", "Keep C")]
    assert [(row.status, row.text) for row in changed.rows] == [("unparsed", header)]
    assert [(row.status, row.text) for row in prose.rows] == [
        ("unparsed", "- Kept A, as it is smaller.")]


def test_an_escaped_pipe_does_not_split_a_cell():
    report = decision_rows.parse(body(HEADER + r"| Use `a \| b` | `c` | one \| two | high |"))

    assert [(row.status, row.decision, row.rationale) for row in report.rows] == [
        ("parsed", "Use `a | b`", "one | two")]


def test_the_core_gives_the_same_rows_each_time():
    text = body(HEADER + "| A | B | C | high |\n| D | E | F | low |\n")

    assert decision_rows.parse(text) == decision_rows.parse(text)
    assert [row.decision for row in decision_rows.parse(text).rows] == ["A", "D"]


# A window's landings, as the session's GitHub tools answer them: the landing pull requests carry
# the field report of their work pull request by its marker.

def pull(number: int, body_text: str, merged: str | None, head: str, base: str = "main") -> dict:
    return {"number": number, "title": head, "body": body_text, "head": {"ref": head, "sha": "0" * 40},
            "base": {"ref": base}, "merged_at": merged, "state": "closed"}


def landing(number: int, work_pull: int, issue: int, merged: str) -> dict:
    text = work_tickets.landing_description(
        f"https://github.com/owner/repo/pull/{work_pull}", work_pull,
        f"https://github.com/owner/repo/issues/{issue}")
    return pull(number, text, merged, f"land/feat/{issue}")


@pytest.fixture
def answers(tmp_path: Path) -> Path:
    directory = tmp_path / "answers"
    directory.mkdir()
    pulls = [
        pull(20, body(HEADER + "| Old one | - | before the window | high |"), None, "feat/old"),
        landing(21, 20, 10, "2026-11-13T10:00:00Z"),  # before the window
        pull(30, body(HEADER + "| Keep A | B | smaller | high |\n| Name x | y | short | low |"),
             None, "feat/a"),
        landing(31, 30, 11, "2026-11-14T10:00:00Z"),
        pull(32, body(None), None, "feat/b"),
        landing(33, 32, 12, "2026-11-14T11:00:00Z"),
        pull(34, "Refs https://github.com/owner/repo/issues/13\n\nA hand-made change.",
             "2026-11-14T12:00:00Z", "feat/c"),
        pull(35, body(HEADER + "| Pick D | E | F | medium |"), None, "feat/d"),
        landing(36, 35, 14, "2026-11-14T13:00:00Z"),
        pull(37, body("None"), "2026-11-14T14:00:00Z", "feat/e", base="other"),  # not main
    ]
    (directory / "pulls.json").write_text(json.dumps(pulls), encoding="utf-8")
    for issue in (10, 11, 12, 13, 14):
        (directory / f"issue-{issue}.json").write_text(json.dumps(
            {"number": issue, "title": f"feat/topic-{issue}", "state": "closed"}), encoding="utf-8")
    return directory


def listed(answers: Path, tmp_path: Path, *extra: str) -> list[str]:
    return ["list", "--since", "2026-11-14", "--answers", str(answers), "--repo", REPO,
            "--worktree", str(tmp_path), *extra]


def test_the_rows_are_grouped_by_pull_request_newest_first_and_each_gap_named(
        answers, tmp_path, fake_git_door, capsys):
    assert decision_rows.main(listed(answers, tmp_path)) == 0
    out = capsys.readouterr().out

    assert out.startswith("Decisions of 4 landings merged after 2026-11-14T00:00:00Z: 3 rows, "
                          "2 landings without them.")
    headings = [line for line in out.splitlines() if line.startswith("#")]
    assert headings == [
        "#36 (field report in #35) landed 2026-11-14, work issue #14 feat/topic-14, Result complete",
        "#34 landed 2026-11-14, work issue #13 feat/topic-13",
        "#33 (field report in #32) landed 2026-11-14, work issue #12 feat/topic-12, Result complete",
        "#31 (field report in #30) landed 2026-11-14, work issue #11 feat/topic-11, Result complete"]
    assert "#34 landed 2026-11-14, work issue #13 feat/topic-13\n  NO FIELD REPORT\n" in out
    assert "Result complete\n  NO DECISIONS SECTION\n" in out
    assert ("  - Decision: Keep A\n    Alternatives: B\n    Rationale: smaller\n"
            "    Confidence: high\n  - Decision: Name x\n") in out
    assert "Old one" not in out and "#37" not in out


def test_json_prints_the_same_rows_and_parses_back(answers, tmp_path, fake_git_door, capsys):
    assert decision_rows.main(listed(answers, tmp_path, "--json")) == 0
    found = json.loads(capsys.readouterr().out)

    assert [(row["pull"], row["report_pull"], row["issue"], row["title"], row["decision"])
            for row in found["rows"]] == [
        (36, 35, 14, "feat/topic-14", "Pick D"), (31, 30, 11, "feat/topic-11", "Keep A"),
        (31, 30, 11, "feat/topic-11", "Name x")]
    assert found["rows"][0] == {
        "landed": "2026-11-14T13:00:00Z", "pull": 36, "report_pull": 35, "issue": 14,
        "title": "feat/topic-14", "result": "complete", "status": "parsed", "decision": "Pick D",
        "alternatives": "E", "rationale": "F", "confidence": "medium", "text": ""}
    assert [(gap["pull"], gap["state"]) for gap in found["gaps"]] == [
        (34, "no-report"), (33, "no-section")]


def test_until_ends_the_window_at_the_end_of_its_day(answers, tmp_path, fake_git_door, capsys):
    command = ["list", "--since", "2026-11-12", "--until", "2026-11-13", "--answers",
               str(answers), "--repo", REPO, "--worktree", str(tmp_path), "--json"]

    assert decision_rows.main(command) == 0
    found = json.loads(capsys.readouterr().out)
    assert [row["decision"] for row in found["rows"]] == ["Old one"]


def test_without_answers_the_steps_are_printed_and_nothing_written(
        tmp_path, fake_git_door, capsys):
    directory = tmp_path / "answers"
    directory.mkdir()

    assert decision_rows.main(listed(directory, tmp_path)) == 0
    out = capsys.readouterr().out
    assert "1. list_pull_requests" in out and "pulls.json" in out
    assert f"Then: decision_rows.py list --since 2026-11-14 --answers {directory}" in out
    assert list(directory.iterdir()) == []


def test_a_usage_error_exits_2(tmp_path, fake_git_door, capsys):
    with pytest.raises(SystemExit) as missing:
        decision_rows.main(["list"])
    assert missing.value.code == 2
    assert decision_rows.main(["list", "--since", "soon", "--repo", REPO,
                               "--worktree", str(tmp_path)]) == 2
    assert "--since soon" in capsys.readouterr().err


# Off by default: nothing SE runs or ships names the command.
WIRED = (".github/workflows", ".github/hooks", ".github/actions", ".githooks", ".claude-plugin", "agents", "skills", "src", "components",
         "se.toml", "wiring.toml")


def test_no_workflow_hook_plugin_file_layout_or_wiring_names_the_command():
    paths = [path for name in WIRED for path in
             ([ROOT / name] if (ROOT / name).is_file() else sorted((ROOT / name).rglob("*")))
             if path.is_file()]
    named = [path.relative_to(ROOT).as_posix() for path in paths
             if b"decision_rows" in path.read_bytes()]

    assert len(paths) > 20 and named == []
