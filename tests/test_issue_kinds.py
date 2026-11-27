"""The kinds of issue SE's commands take (scripts/issue_kinds.py): how an issue shows its kind, the
refusal of another kind naming the command that takes it, and the warning for an issue nothing
marks."""
from __future__ import annotations

import pytest

import issue_kinds
import work_tickets

MARKER = "<!-- se:template se/{name} 1.2.0 sha256:94167a05079cc2a3b18b6b7750d9e9a63eaa7ef90e48796911ff84d35b77e7d8 -->"


def item(number=7, title="feat-x", labels=(), body="") -> dict:
    return {"number": number, "title": title, "labels": [{"name": name} for name in labels], "body": body}


@pytest.mark.parametrize(("issue", "kind"), [
    (item(body=MARKER.format(name="overhaul"), labels=("work",)), "overhaul"),  # the marker wins
    (item(body=MARKER.format(name="retro")), "retro"),
    (item(body=MARKER.format(name="work"), title="overhaul-20261127"), "work"),
    (item(title="overhaul-20261127", labels=("discovery",)), "overhaul"),
    (item(title="docs/overhaul-20261112"), "overhaul"),
    (item(title="docs/retro-20261101"), "retro"),
    (item(title="retro-due-20261126", labels=("retro",)), "retro"),
    (item(title="retro-kind-table", labels=("work",)), "work"),  # a work issue about retros
    (item(labels=("work", "discovery")), "work"),  # a discovery work issue
    (item(labels=("ready",)), "work"),
    (item(body=MARKER.format(name="routed"), labels=("work",)), "work"),  # no kind of its own
    ({"number": 7, "title": "x", "labels": ["retro"]}, "retro"),  # the GitHub tools' label strings
    (item(), None),
], ids=lambda value: value if isinstance(value, str) or value is None else value["title"])
def test_the_kind_comes_from_the_marker_then_the_title_then_the_labels(issue, kind):
    found = issue_kinds.kind_of(issue)
    assert (found.name if found else None) == kind


def test_another_kind_is_refused_naming_the_command_that_takes_it():
    """Overhaul #1993, finding 1: `retro.py collect 1993` ran on an overhaul issue."""
    overhaul = item(1993, "overhaul-20261127", ("discovery",))
    with pytest.raises(work_tickets.QueueError) as raised:
        issue_kinds.check(overhaul, issue_kinds.RETRO, "retro.py collect", work_tickets.QueueError)
    assert str(raised.value) == ("retro.py collect takes a retro issue, and #1993 is an overhaul issue: "
                                 "run `overhaul.py read 1993` for it; nothing was written")


@pytest.mark.parametrize("kind", list(issue_kinds.KINDS.values()), ids=list(issue_kinds.KINDS))
def test_every_kind_is_refused_by_every_other_kinds_command(kind):
    issue = item(body=MARKER.format(name=kind.name))
    assert issue_kinds.check(issue, kind, "x") == kind
    for other in issue_kinds.KINDS.values():
        if other != kind:
            with pytest.raises(ValueError, match=rf"x takes {other.noun}, and #7 is {kind.noun}"):
                issue_kinds.check(issue, other, "x")


def test_an_unmarked_issue_warns_from_day_one_and_errors_at_the_error_level(capsys, monkeypatch):
    assert issue_kinds.check(item(), issue_kinds.WORK, "work_tickets.py intake") is None
    warning = capsys.readouterr().err
    assert warning.startswith("warning: work_tickets.py intake: nothing shows #7's kind")
    assert "`work_tickets.py stamp 7`" in warning and warning.rstrip().endswith("taken as a work issue")
    monkeypatch.setattr(issue_kinds, "UNKNOWN_LEVEL", "error")
    with pytest.raises(ValueError, match="nothing shows #7's kind"):
        issue_kinds.check(item(), issue_kinds.WORK, "work_tickets.py intake")


def test_each_run_kind_names_its_deck_cover_closing_question_and_filing_rule():
    rows = {name: (kind.document_type, kind.anything_else, kind.outcomes)
            for name, kind in issue_kinds.KINDS.items()}
    assert rows == {"work": (None, False, False), "retro": ("Retro report", True, True),
                    "overhaul": ("Overhaul report", False, False)}


def test_intake_refuses_a_retro_issue_before_writing_a_ticket(tmp_path):
    retro = {"repo": "owner/repo", "number": 30, "url": "https://github.com/owner/repo/issues/30",
             "title": "retro-20261112", "body": "", "updatedAt": "2026-11-27T00:00:00Z",
             "labels": [{"name": "retro"}], "comments": []}
    with pytest.raises(work_tickets.QueueError, match=r"run `retro.py collect 30` for it"):
        work_tickets.intake(tmp_path, None, None, answered=retro)
    assert not list((tmp_path / ".se" / "work" / "todo").glob("*.md"))
