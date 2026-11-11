"""The rule book's check (scripts/rule_book.py) and se's own book."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

import rule_book

ROOT = Path(__file__).resolve().parents[1]

RULE = """\
### {id} {name}

{statement}

- **Why:** a reason.
- **Without it:** what we lose.
- **Prevents:** drift between two copies.
- **Implementations:**
  - se: {implementation}
- **Related:** {related}
"""


def rule(rule_id="gen-001", name="A rule", statement="State the rule in one sentence.",
         implementation="[a check](scripts/rule_book.py).", related="none", extra=""):
    return RULE.format(id=rule_id, name=name, statement=statement,
                       implementation=implementation, related=related) + extra


def book(*sections: tuple[str, list[str]]) -> str:
    text = "# Rules\n\n"
    for prefix, rules in sections:
        text += f"## {prefix}: a section\n\n" + "\n".join(rules) + "\n"
    return text


def run(tmp_path, capsys, text: str) -> tuple[int, str]:
    path = tmp_path / "rules.md"
    path.write_text(text, encoding="utf-8")
    code = rule_book.main(["--book", str(path)])
    return code, capsys.readouterr().out


def test_a_well_formed_book_passes(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(
        ("gen", [rule(), rule("gen-1000", "Past nine hundred and ninety-nine", related="gen-001")]),
        ("p-se", [rule("p-se-001", "A project rule", related="gen-001, gen-1000")]),
        ("p-obs2", [rule("p-obs2-001")])))
    assert code == 0, out
    assert "rule_book.py: passed" in out


@pytest.mark.parametrize("rule_id", ["gen-01", "GEN-001", "gen001", "gen-00a", "p--001", "p-Se-001"])
def test_a_malformed_id_is_refused(tmp_path, capsys, rule_id):
    code, out = run(tmp_path, capsys, book(("gen", [rule(rule_id)])))
    assert code == 1
    assert f"malformed id {rule_id!r}" in out


def test_a_project_id_without_p_is_refused_naming_the_p_form(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("gen", [rule("se-001")])))
    assert code == 1
    assert "a project rule's id starts with 'p-' (p-se-001)" in out


def test_a_project_section_without_p_is_refused(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("se", [rule("p-se-001")])))
    assert code == 1
    assert "section prefix 'se' is neither an area" in out


def test_no_area_prefix_starts_with_p():
    assert rule_book.area_problems() == []
    assert not any(area.startswith("p-") for area in rule_book.AREAS)


def test_a_rule_outside_its_section_is_refused(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("gen", [rule("des-001")])))
    assert code == 1
    assert "des-001 stands in section 'gen'" in out


def test_a_duplicate_id_is_refused(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("gen", [rule(), rule(name="Another")])))
    assert code == 1
    assert "duplicate id gen-001" in out


def test_a_reused_retired_id_is_refused(tmp_path, capsys):
    retired = rule(extra="- **Retired:** its intent no longer holds.\n")
    code, out = run(tmp_path, capsys, book(("gen", [retired, rule(name="A new rule")])))
    assert code == 1
    assert "gen-001 reuses a retired id" in out


@pytest.mark.parametrize("field", rule_book.FIELDS)
def test_a_rule_missing_a_field_is_refused(tmp_path, capsys, field):
    text = re.sub(rf"^- \*\*{field}:\*\*.*\n(?:  - .*\n)*", "", rule(), flags=re.MULTILINE)
    code, out = run(tmp_path, capsys, book(("gen", [text])))
    assert code == 1
    assert f"gen-001: missing field {field}" in out


def test_a_rule_missing_its_sentence_or_with_two_is_refused(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("gen", [
        rule(statement=""), rule("gen-002", statement="One sentence. And another.")])))
    assert code == 1
    assert "gen-001: missing the one sentence stating the rule" in out
    assert "gen-002: the rule is stated in exactly one sentence" in out


def test_a_related_id_and_a_mapped_id_must_exist(tmp_path, capsys):
    text = "| Principle | Rule |\n|---|---|\n| 1 | gen-009 |\n\n" + book(("gen", [rule(related="gen-002")]))
    code, out = run(tmp_path, capsys, text)
    assert code == 1
    assert "Related names 'gen-002'" in out
    assert "principle 1 maps to 'gen-009'" in out


def test_rules_followed_only_by_judgment_are_listed_without_failing(tmp_path, capsys):
    code, out = run(tmp_path, capsys, book(("gen", [
        rule(implementation="by judgment."),
        rule("gen-002", implementation="[a check](x.py); otherwise by judgment.")])))
    assert code == 0, out
    assert "by judgment only: gen-001 A rule" in out
    assert "gen-002" not in out
    assert "1 rule(s) followed by judgment only" in out


def test_a_missing_book_is_a_setup_error(tmp_path, capsys):
    assert rule_book.main(["--book", str(tmp_path / "none.md")]) == 2
    assert "cannot read the rule book" in capsys.readouterr().err


def test_se_rule_book_passes_and_lists_its_judgment_rules(capsys):
    code = rule_book.main([])
    out = capsys.readouterr().out
    assert code == 0, out
    listed = [line for line in out.splitlines() if line.startswith("by judgment only:")]
    if listed:
        warnings.warn("rules followed by judgment only:\n" + "\n".join(listed), stacklevel=1)
