"""The overhaul's pruning facts (scripts/overhaul.py facts) on a fixture checkout and on se itself."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

import overhaul

ROOT = Path(__file__).resolve().parents[1]

# A block written twice, in two scripts: the duplicate the facts must find.
COPIED = """\
    total = 0
    for value in values:
        if value is None:
            continue
        total = total + value * weight
    average = total / max(len(values), 1)
    return round(average, places)
"""

APP = f'''\
"""The fixture's application."""

import argparse

import lib


def used(values, weight, places):
{COPIED}

def tested_only():
    return helper_of_tested()


def helper_of_tested():
    return 1


def nothing_reaches():
    return 2


def documented():
    return 3


def run_ship(args):
    return lib.shared() + used([1], 2, 3)


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ship").set_defaults(handler=run_ship)
    commands.add_parser("forgotten")
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    main()
'''

LIB = f'''\
"""The fixture's library."""


def shared():
    return used_again([1, 2], 3, 4)


def used_again(values, weight, places):
{COPIED}
'''

TEST = '''\
import app


def test_tested_only():
    assert app.tested_only() == 1
'''

README = """\
# Fixture

Run `uv run python scripts/app.py ship` to ship; `documented` is the library's interface, and
`scripts/lib.py` holds the rest.
"""


def git(root: Path, *arguments: str, when: str = "2026-01-01T00:00:00Z") -> None:
    environment = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=alice", "-c", "user.email=alice@example.com",
                    *arguments], check=True, capture_output=True, env=environment)


@pytest.fixture(scope="module")
def checkout(tmp_path_factory) -> Path:
    """The fixture checkout, built once: facts only reads it."""
    root = tmp_path_factory.mktemp("checkout")
    git(root, "init", "-q")
    (root / "se.toml").write_text('[project]\nauthored_content = ["README.md"]\n', encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    (root / "scripts" / "lib.py").write_text(LIB, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "The library", when="2026-01-01T00:00:00Z")
    (root / "scripts" / "app.py").write_text(APP, encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(TEST, encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "The application", when="2026-03-01T00:00:00Z")
    return root


def facts(root: Path, capsys) -> dict:
    assert overhaul.main(["facts", "--json", "--repo", str(root)]) == 0
    return json.loads(capsys.readouterr().out)


def test_facts_find_unreached_code_duplicates_and_unnamed_commands(checkout, capsys):
    found = facts(checkout, capsys)
    unreached = {item["what"]: item["tests"] for item in found["unreached"]}
    assert unreached == {"function tested_only": True, "function helper_of_tested": True,
                         "function nothing_reaches": False}
    assert [(block["a"].split(":")[0], block["b"].split(":")[0], block["lines"])
            for block in found["duplicates"]] == [("scripts/app.py", "scripts/lib.py", 7)]
    assert [(pair["a"].split()[1], pair["b"].split()[1]) for pair in found["near"]] == [("used", "used_again")]
    assert found["near"][0]["alike"] >= overhaul.NEAR_ALIKE
    assert found["unnamed"] == ["app.py forgotten"]
    assert overhaul.main(["facts", "--repo", str(checkout)]) == 0
    report = capsys.readouterr().out
    assert "- scripts/app.py:26 function nothing_reaches (not even tests)" in report
    assert "- app.py forgotten" in report


def test_facts_measure_sizes_lengths_and_the_untouched_and_change_nothing(checkout, capsys):
    found = facts(checkout, capsys)
    sizes = {row["script"]: (row["lines"], row["test_lines"]) for row in found["sizes"]}
    assert sizes["scripts/app.py"][1] == 3 and sizes["scripts/lib.py"][1] == 0
    assert [(item["what"], item["lines"]) for item in found["long_functions"][:3]] == [
        ("used", 8), ("used_again", 8), ("main", 7)]
    assert found["long_files"][0]["at"] == "scripts/app.py"
    assert [(item["what"], item["parameters"]) for item in found["long_parameters"][:2]] == [
        ("used", 3), ("used_again", 3)]
    assert found["untouched"][0] == {"at": "scripts/lib.py", "last": "2026-01-01"}
    status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True,
                            text=True, check=True).stdout
    assert status == ""


def test_facts_on_se_answer_within_the_budget(capsys):
    started = time.perf_counter()
    found = facts(ROOT, capsys)
    assert time.perf_counter() - started < 10
    assert {row["script"] for row in found["sizes"]} >= {"scripts/work_tickets.py"}


# The overhaul issue: new, read and file, on a fake door.

import retro  # noqa: E402
import work_tickets  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

REPO = "github.com/owner/repo"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
THIS = 50


def issue(number: int, title: str, closed: str | None, body: str = "", reason: str = "completed",
          labels: tuple[str, ...] = ()) -> dict:
    return {"number": number, "title": title, "state": "closed" if closed else "open",
            "closed_at": closed, "state_reason": reason if closed else None, "body": body,
            "labels": [{"name": name} for name in labels]}


def retro_block(classes: list[str], broken: bool) -> str:
    block = {"version": 1, "sizes": {"closed": 6, "landed": 5, "duplicates": 0, "escalated": 1},
             "rule_checks": [{"name": "field-report", "kept": not broken},
                             {"name": "check", "kept": True}],
             "classes": [{"name": name, "fix": "f"} for name in classes],
             "findings": [{"kind": "work"}, {"kind": "work"}, {"kind": "decision"}],
             "previous": {"findings": [{"state": "closed", "recurred": False},
                                       {"state": "none", "recurred": True}]}}
    return f"Report.\n\n{retro.BLOCK_MARKER}\n```yaml\n{json.dumps(block)}\n```\n"


def overhaul_block() -> str:
    block = {"version": 1, "overhaul": 40, "facts": {"unreached": 9, "lines": 100},
             "findings": [{"finding": 1, "title": "Prune the unused door", "rule": "des-015",
                           "kind": "work"},
                          {"finding": 2, "title": "Split the long command", "rule": "des-007",
                           "kind": "work"},
                          {"finding": 3, "title": "Add a rule on speed", "rule": "new",
                           "kind": "decision"}]}
    return f"Report.\n\n{overhaul.BLOCK_MARKER}\n```yaml\n{json.dumps(block)}\n```\n"


def answers() -> dict[str, object]:
    """Overhaul #40 closed 1 Oct; since then retros #42 and #43 closed with their blocks and #46
    without one; #41 closed before it. #44 took finding 1 and closed, open #45 takes finding 2."""
    return {
        "issues.json": [
            issue(40, "docs/overhaul-20260930", "2026-10-01T00:00:00Z"),
            issue(41, "docs/retro-20260920", "2026-09-20T00:00:00Z"),
            issue(42, "docs/retro-20261020", "2026-10-20T00:00:00Z"),
            issue(43, "retro: fleet 20261101", "2026-11-01T00:00:00Z", labels=("retro",)),
            issue(44, "feat/prune-20261010", "2026-10-11T00:00:00Z", "Takes overhaul #40 finding 1.",
                  labels=("work",)),
            issue(46, "docs/retro-20261105", "2026-11-05T00:00:00Z"),
            issue(47, "fix/other-20261012", "2026-10-12T00:00:00Z", "Overhaul #39 finding 1.",
                  reason="not_planned"),
        ],
        "open-issues.json": [
            issue(45, "feat/split-20261102", None, "Refs overhaul #40 finding 2."),
            issue(THIS, "docs/overhaul-20261112", None)],
        "comments-40.json": [{"body": overhaul_block()}],
        "comments-42.json": [{"body": retro_block(["Lost reports", "Slow suite"], True)}],
        "comments-43.json": [{"body": "Hello."}, {"body": retro_block(["Lost reports"], False)}],
        "comments-41.json": [], "comments-46.json": [],
    }


class FakeDoor:
    """The read's GitHub reads, recorded, from `given`."""

    def __init__(self, given: dict[str, object]) -> None:
        self.given, self.reads, self.missing = given, [], []

    def read(self, name: str) -> object:
        self.reads.append(name)
        return self.given[name]

    def closed_issues(self):
        return self.read("issues.json")

    def open_issues(self):
        return self.read("open-issues.json")

    def issue(self, number):
        return self.read(f"issue-{number}.json")

    def comments(self, number):
        return self.read(f"comments-{number}.json")


def gathered(checkout: Path, given: dict[str, object] | None = None) -> overhaul.Gathered:
    door = FakeDoor(given or answers())
    found = overhaul.gather(THIS, door, overhaul.book_rules(ROOT),
                            overhaul.find(overhaul.read(checkout)), NOW)
    assert found is not None
    return found


def test_the_draft_names_every_rule_with_what_checks_it(checkout):
    found = gathered(checkout)
    text = overhaul.draft(found)
    rules = overhaul.book_rules(ROOT)
    assert len(rules) > 40
    for rule in rules:
        assert f"- **{rule.id} {rule.name}** (checked by: " in text
    block = overhaul.read_block(text)
    assert [rule["id"] for rule in block["rules"]] == [rule.id for rule in rules]
    checks = {rule["id"]: rule["checked_by"] for rule in block["rules"]}
    assert checks["gen-002"] == ["test", "check", "judgment"]
    assert checks["gen-004"] == ["judgment"]
    assert checks["pub-001"] == ["check"]
    assert checks["p-go-001"] == []
    assert block["looked_at"] == {part: "" for part in overhaul.LOOKED_AT}
    assert block["verdicts"] == block["findings"] == block["went_well"] == []


def test_the_draft_holds_the_retros_since_the_last_overhaul_and_its_findings(checkout):
    found = gathered(checkout)
    assert (found.since_overhaul, found.since) == (40, "2026-10-01T00:00:00Z")
    assert [row["retro"] for row in found.retros] == [42, 43, 46]
    assert found.retros[0]["broken"] == ["field-report"]
    assert found.retros[0]["findings"] == {"work": 2, "decision": 1}
    assert found.retros[0]["previous"] == {"scored": 2, "closed": 1, "recurred": 1}
    assert found.retros[2] == {"retro": 46, "closed_at": "2026-11-05T00:00:00Z", "block": False}
    assert [(item["finding"], item["issues"], item["state"])
            for item in found.previous["findings"]] == [(1, [44], "closed"), (2, [45], "open"),
                                                        (3, [], "none")]
    text = overhaul.draft(found)
    assert "Since overhaul #40 closed, 2026-10-01T00:00:00Z" in text
    assert "| #42 | 6 | 5 | 1 | field-report | 2, 1 | 1 of 2, 1 |" in text
    assert "| #46 | no report block found | | | | | |" in text
    assert "Finding classes more than one retro named: Lost reports." in text
    assert "| 2. Split the long command | des-007 | work | #45 | open |" in text
    assert "Against overhaul #40: unreached 9 then, 3 now" in text
    assert "### Reached by nothing but tests" in text


def test_without_a_closed_overhaul_the_window_is_the_whole_history(checkout):
    given = answers()
    given["issues.json"] = [item for item in given["issues.json"] if item["number"] != 40]
    found = gathered(checkout, given)
    assert found.since is None and found.previous is None
    assert [row["retro"] for row in found.retros] == [41, 42, 43, 46]
    assert "no overhaul issue has closed" in overhaul.draft(found)


def test_without_gh_read_prints_its_reads_round_by_round_and_takes_the_answers(
        checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    directory, out = tmp_path / "answers", tmp_path / "draft.md"
    directory.mkdir()
    arguments = ["read", str(THIS), "--answers", str(directory), "--out", str(out), "--repo", REPO,
                 "--worktree", str(checkout)]
    given = answers()
    # The host's list_issues names no close time: each retro and overhaul is read one by one.
    listed = {name: [{key: value for key, value in item.items() if key != "closed_at"}
                     for item in given[name]] for name in ("issues.json", "open-issues.json")}
    rounds = [listed, {f"issue-{item['number']}.json": item for item in given["issues.json"]
                       if item["number"] in (40, 41, 42, 43, 46)},
              {name: value for name, value in given.items() if name.startswith("comments-")}]
    expected = [["list_issues", "list_issues"], ["issue_read"] * 5, ["issue_read"] * 4]
    for answer, tools in zip(rounds, expected):
        assert overhaul.main(arguments) == 0
        output = capsys.readouterr().out
        steps = [line.split(" ", 2)[1] for line in output.splitlines() if line[:1].isdigit()]
        assert steps == tools, output
        assert f"Then: overhaul.py read {THIS} --answers {directory}" in output
        for name, value in answer.items():
            (directory / name).write_text(json.dumps(value), encoding="utf-8")
    assert overhaul.main(arguments) == 0
    assert "Wrote the overhaul draft of #50" in capsys.readouterr().out
    assert overhaul.read_block(out.read_text(encoding="utf-8"))["since_overhaul"] == 40


def judged_draft(checkout: Path, **changes: object) -> str:
    """The draft of overhaul #50 with its block judged; `changes` replace parts of the judgment."""
    text = overhaul.draft(gathered(checkout))
    data = overhaul.read_block(text)
    data.update({
        "verdicts": [{"rule": rule["id"], "strays": "none", "how": "Holds."}
                     for rule in data["rules"]],
        "looked_at": {part: "Nothing to change." for part in overhaul.LOOKED_AT},
        "findings": [
            {"title": "Prune the three functions only tests reach", "body": "See the facts.",
             "rule": "des-015", "place": "scripts/overhaul.py", "controversial": False},
            {"title": "Name the speed of the suite as a rule", "body": "The suite grows.",
             "rule": "tst-002", "place": overhaul.BOOK.as_posix(), "controversial": False},
            {"title": "Add a rule that every overhaul compares itself", "body": "None compares.",
             "rule": "new", "place": "src/agents/se.md", "controversial": False,
             "sources": ["https://example.com/practice"]}],
        "went_well": ["The retros kept their blocks."]})
    data.update(changes)
    return text[:text.rfind(overhaul.BLOCK_MARKER)] + overhaul.BLOCK_MARKER + "\n```yaml\n" + \
        json.dumps(data, indent=2) + "\n```\n"


def finding(**changes: object) -> dict:
    return {"title": "Prune the three functions only tests reach", "body": "See the facts.",
            "rule": "des-015", "place": "scripts/overhaul.py", "controversial": False, **changes}


def verdicts(**changes: object) -> list[dict]:
    rules = overhaul.book_rules(ROOT)
    return [{"rule": rule.id, "strays": "none", "how": "Holds.", **changes} for rule in rules]


@pytest.mark.parametrize(("changes", "refusal"), [
    ({"verdicts": verdicts()[1:]}, "gen-001 has no verdict"),
    ({"verdicts": [*verdicts(), verdicts()[0]]}, "gen-001 has two verdicts"),
    ({"verdicts": verdicts(strays="a bit")}, "the verdict on gen-001: strays is one of none"),
    ({"verdicts": verdicts(how=" ")}, "the verdict on gen-001 has no how"),
    ({"verdicts": [*verdicts(), {"rule": "gen-999", "strays": "none", "how": "x"}]},
     "the verdict on gen-999 names no rule of the book"),
    ({"looked_at": {**{part: "x" for part in overhaul.LOOKED_AT}, "speed": ""}},
     '`looked_at.speed` is empty ("nothing to change" is an answer)'),
    ({"looked_at": {part: "x" for part in overhaul.LOOKED_AT[1:]}}, "`looked_at.outside` is empty"),
    ({"findings": [finding(rule="")]}, "has no rule: a rule's id, or new"),
    ({"findings": [finding(rule="des-999")]}, 'names the rule "des-999", which is not in the book'),
    ({"findings": [finding(place="")]}, "has no place: the file it changes"),
    ({"findings": [finding(body="")]}, "has no body"),
    ({"findings": [finding(title="Prune it")]}, "needs a title of 5 words or more"),
    ({"findings": [finding(controversial=True)]}, "is controversial without a why"),
    ({"findings": [finding(issue=60)]}, "has the unknown field issue"),
    ({"went_well": [" "]}, "`went_well` is empty: record what went well"),
])
def test_file_refuses_an_incomplete_judgment_and_writes_nothing(checkout, tmp_path, monkeypatch,
                                                                changes, refusal):
    writes = []
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "run_plan", lambda plan, actions: writes.append(plan))
    draft = tmp_path / "draft.md"
    draft.write_text(judged_draft(checkout, **changes), encoding="utf-8")

    assert overhaul.main(["file", str(THIS), "--draft", str(draft), "--repo", REPO,
                          "--worktree", str(checkout)]) == 1
    assert writes == []
    with pytest.raises(work_tickets.QueueError) as raised:
        overhaul.judged(draft.read_text(encoding="utf-8"), THIS)
    assert "The judgment of overhaul #50 is not complete, so nothing was written" in str(raised.value)
    assert refusal in str(raised.value)


def test_file_refuses_another_overhauls_draft_and_a_draft_without_its_block(checkout):
    with pytest.raises(work_tickets.QueueError, match="The draft is overhaul #50's, not #51's"):
        overhaul.judged(judged_draft(checkout), 51)
    with pytest.raises(work_tickets.QueueError, match="The draft has no"):
        overhaul.judged("# Overhaul draft for #50\n", THIS)


class FakeTracker:
    """The issue writes of the gh door, recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def actions(self, root, repo):
        return {name: (lambda arguments, _, name=name: self.calls.append((name, arguments)))
                for name in ("comment_issue", "close_issue", "add_label", "remove_label")}


def test_file_marks_rule_changes_for_the_person_posts_the_report_and_files_nothing(
        checkout, tmp_path, monkeypatch, capsys):
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    draft = tmp_path / "draft.md"
    draft.write_text(judged_draft(checkout), encoding="utf-8")

    assert overhaul.main(["file", str(THIS), "--draft", str(draft), "--repo", REPO,
                          "--worktree", str(checkout)]) == 0
    assert [name for name, _ in tracker.calls] == ["comment_issue", "close_issue"]
    assert all(arguments["issue_number"] == THIS for _, arguments in tracker.calls)
    comment = tracker.calls[0][1]["body"]
    assert comment.startswith(overhaul.REPORT_MARKER + "\n## Overhaul #50: the report\n")
    assert "| gen-001 Mechanize first | none | Holds. |" in comment
    assert "- **outside**: Nothing to change." in comment
    assert ("- **1. Prune the three functions only tests reach** (work, for SE to bundle; rule "
            "des-015; place `scripts/overhaul.py`)") in comment
    assert ("- **2. Name the speed of the suite as a rule** (decision, for the owner's decision "
            "list: it changes a rule; a rule change; rule tst-002; place "
            "`src/skills/work-model/references/rules.md`)") in comment
    assert ("- **3. Add a rule that every overhaul compares itself** (decision, for the owner's "
            "decision list: it changes a rule; a rule change; rule new;") in comment
    assert "  - Source: https://example.com/practice" in comment
    assert "This overhaul filed no issue." in comment and "`overhaul #50 finding <k>`" in comment
    assert "### The facts" in comment and "\n#### The rule book (" in comment
    assert overhaul.JUDGE_BEGIN not in comment and "## Judgment" not in comment
    block = overhaul.read_block(comment)
    assert [(item["finding"], item["kind"], item["rule_change"]) for item in block["findings"]] == [
        (1, "work", False), (2, "decision", True), (3, "decision", True)]
    out = capsys.readouterr().out
    assert "1 work and 2 decision finding(s), 2 of them rule changes; no issue filed" in out


def test_the_next_read_scores_the_findings_file_posted(checkout, tmp_path, monkeypatch):
    tracker = FakeTracker()
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "tracker_actions", tracker.actions)
    draft = tmp_path / "draft.md"
    draft.write_text(judged_draft(checkout), encoding="utf-8")
    assert overhaul.main(["file", str(THIS), "--draft", str(draft), "--repo", REPO,
                          "--worktree", str(checkout)]) == 0
    given = answers()
    given["issues.json"].append(issue(THIS, "docs/overhaul-20261112", "2026-11-12T13:00:00Z"))
    given["open-issues.json"] = [issue(51, "feat/rules-20261113", None, "overhaul #50 finding 2")]
    given[f"comments-{THIS}.json"] = [{"body": tracker.calls[0][1]["body"]}]

    found = overhaul.gather(60, FakeDoor(given), overhaul.book_rules(ROOT),
                            overhaul.find(overhaul.read(checkout)), NOW)
    assert found.since_overhaul == THIS and found.retros == []
    assert [(item["finding"], item["kind"], item["issues"], item["state"])
            for item in found.previous["findings"]] == [
        (1, "work", [], "none"), (2, "decision", [51], "open"), (3, "decision", [], "none")]


def test_file_without_gh_prints_the_comment_and_the_close(checkout, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    draft = tmp_path / "draft.md"
    draft.write_text(judged_draft(checkout), encoding="utf-8")

    assert overhaul.main(["file", str(THIS), "--draft", str(draft), "--repo", REPO,
                          "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "GitHub plan: the report of overhaul #50" in out
    assert '1. add_issue_comment {"body": "<!-- se:overhaul-report -->' in out
    assert ('2. issue_write {"issue_number": 50, "method": "update", "owner": "owner", '
            '"repo": "repo", "state": "closed", "state_reason": "completed"}') in out
    assert '"method": "create"' not in out


def test_new_files_the_overhaul_issue_through_file_labelled_discovery(checkout, monkeypatch,
                                                                       capsys):
    filed = []
    real = work_tickets.file_work_issue

    def recorded(root, title, file, blockers, repo, extra=()):
        filed.append((title, file.read_text(encoding="utf-8"), blockers, repo, extra))
        return real(root, title, file, blockers, repo, extra)

    monkeypatch.setattr(work_tickets, "file_work_issue", recorded)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "today_stamp", lambda: "20261112")

    assert overhaul.main(["new", "--repo", REPO, "--worktree", str(checkout)]) == 0
    title, body, blockers, repo, extra = filed[0]
    assert (title, blockers, repo, extra) == ("docs/overhaul-20261112", [], REPO, ("discovery",))
    assert body.startswith("<!-- se:fleet -->\n\n## Goal\n") and "---" not in body.split("\n")[0]
    assert "overhaul.py read <this issue> --out <draft>" in body
    assert "overhaul.py file <this issue> --draft <draft>" in body
    out = capsys.readouterr().out
    assert "GitHub plan: file docs/overhaul-20261112" in out
    assert '"labels": ["work", "ready", "repo:repo", "discovery"]' in out
    assert '"title": "docs/overhaul-20261112"' in out
