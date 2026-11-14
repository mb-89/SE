"""The review gate's decision (scripts/review_gate.py): the change's facts, the reviews on its pull
request and the setting in, land or refuse with its reason out. integrate's wiring is tested in
tests/test_work_ticket_issues.py."""

import json

import pytest

import work_tickets

gate = work_tickets.sibling("review_gate")
HEAD = "a" * 40
ON = gate.Settings(on=True)


def comment(verdict: str, head: str = HEAD, marker: str = gate.VERDICT_MARKER) -> dict:
    data = json.dumps({"pull": 7, "verdict": verdict, "head": head})
    return {"body": f"{marker}\n## Review of pull request #7: {verdict}\n\n```json\n{data}\n```\n"}


def test_the_gate_is_off_without_its_setting_and_lands_everything():
    assert gate.settings({}) == gate.Settings(on=False, risky=gate.RISKS)
    major = gate.facts("major", ["AGENTS.md"], "breaking; rewrites history")
    assert gate.decide(major, [], HEAD, gate.settings({})) == gate.Decision(True)


@pytest.mark.parametrize(("facts", "risks"), [
    (gate.facts("major", ["README.md"], ""), ("major",)),
    (gate.facts("minor", ["AGENTS.md"], ""), ("rule-book",)),
    (gate.facts("patch", ["src/skills/work-model/references/rules.md"], ""), ("rule-book",)),
    (gate.facts("minor", ["src/agents/worker.md"], ""), ("role-file",)),
    (gate.facts("minor", ["scripts/rewrite_history.py"], ""), ("history",)),
    (gate.facts("minor", ["README.md"], "Standard; it rewrites history on main"), ("history",)),
    (gate.facts("major", ["AGENTS.md", "src/agents/se.md"], ""), ("major", "rule-book",
                                                                  "role-file")),
    (gate.facts("minor", ["README.md", "src/agents/sub/deep.md", "docs/AGENTS.md"], ""), ()),
])
def test_each_kind_of_risk_is_read_from_the_facts(facts, risks):
    assert gate.risks(facts) == risks


def test_the_setting_lists_which_kinds_count_as_risky():
    only_major = gate.settings({"review_gate": True, "review_gate_risky": ["major"]})
    assert only_major == gate.Settings(True, ("major",))
    rule = gate.facts("minor", ["AGENTS.md"], "")
    assert gate.decide(rule, [], HEAD, only_major).land
    assert not gate.decide(gate.facts("major", [], ""), [], HEAD, only_major).land


@pytest.mark.parametrize("table", [
    {"review_gate": "yes"},
    {"review_gate": True, "review_gate_risky": "major"},
    {"review_gate": True, "review_gate_risky": ["major", "docs"]},
])
def test_an_unreadable_setting_is_refused_naming_the_key(table):
    with pytest.raises(gate.SettingError, match=r"integrate\.review_gate"):
        gate.settings(table)


def test_an_unreviewed_risky_change_is_refused_naming_the_setting_and_the_remedy():
    decision = gate.decide(gate.facts("major", [], ""), [], HEAD, ON)
    assert not decision.land
    assert decision.risks == ("major",)
    assert decision.reason.startswith("the change is risky (major) and it has no review; ")
    assert "se.toml [integrate] review_gate = true" in decision.reason
    assert "review.py brief, then review.py file" in decision.reason


@pytest.mark.parametrize("verdict", ["pass", "pass with open points"])
def test_a_pass_of_the_head_lands_a_risky_change(verdict):
    found = gate.reviews([comment(verdict, HEAD[:12])])
    decision = gate.decide(gate.facts("minor", ["AGENTS.md"], ""), found, HEAD, ON)
    assert decision == gate.Decision(True, f"risky (rule-book), reviewed: {verdict} at "
                                           f"{HEAD[:12]}", ("rule-book",))


def test_the_newest_review_of_the_head_decides_and_a_review_of_another_head_counts_not():
    rule = gate.facts("minor", ["AGENTS.md"], "")
    declined = gate.reviews([comment("pass"), comment("decline")])
    assert "its newest review of aaaaaaaaaaaa is decline" in gate.decide(
        rule, declined, HEAD, ON).reason
    stale = gate.reviews([comment("pass", "b" * 40)])
    refused = gate.decide(rule, stale, HEAD, ON)
    assert not refused.land
    assert "its reviews are of bbbbbbbbbbbb, not of its head aaaaaaaaaaaa" in refused.reason


def test_only_review_comments_with_their_json_block_are_reviews():
    found = gate.reviews([
        {"body": "pass, looks fine"},
        comment("pass", marker="<!-- se:field-report -->"),
        {"body": f"{gate.VERDICT_MARKER}\nno block"},
        {"body": f"{gate.VERDICT_MARKER}\n```json\nnot json\n```"},
        "not a comment",
        comment("pass with open points"),
    ])
    assert found == [gate.Review("pass with open points", HEAD)]
