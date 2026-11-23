"""Tests for scripts/upgrade_guide.py: the sections between any two versions of a guide, and the
refusal of a breaking release without its section (docs/upgrading.md "How the guide is kept")."""

from __future__ import annotations

from pathlib import Path

import pytest

import upgrade_guide  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]

GUIDE = """# Upgrading

Intro, no section.

## SE 6

Forms are templates.

### Check

`git grep -n forms`

## obs 10

obs's own.

## SE 7

What others do.

## SE 12

Kern 2.

## obs-html 0.3

The style component.

## Not a section

Ends the one above.
"""


def titles(found):
    return [s.title for s in found]


def test_the_sections_between_two_versions_are_the_named_ones_oldest_first():
    found = upgrade_guide.sections(GUIDE, "se", (5, 134, 2), (12, 0, 1))
    assert titles(found) == ["SE 6", "SE 7", "SE 12"]
    assert found[0].text == "## SE 6\n\nForms are templates.\n\n### Check\n\n`git grep -n forms`\n"
    assert titles(upgrade_guide.sections(GUIDE, "SE", (6, 0, 0), (7, 0, 0))) == ["SE 7"]
    assert titles(upgrade_guide.sections(GUIDE, "SE", (12, 0, 0), (12, 0, 1))) == []
    assert titles(upgrade_guide.sections(GUIDE, "obs-html", (0, 2, 5), (0, 5, 0))) == ["obs-html 0.3"]
    assert upgrade_guide.sections(GUIDE, "obs-html", (0, 2, 5), (0, 5, 0))[0].text.endswith(
        "The style component.\n")


def test_show_prints_the_sections_to_follow_in_order(tmp_path, capsys):
    guide = tmp_path / "upgrading.md"
    guide.write_text(GUIDE, encoding="utf-8")
    assert upgrade_guide.main(["show", "--guide", str(guide), "--name", "SE", "--from", "5.134.2",
                               "--to", "v12.0.1"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"SE: 3 section(s) of {guide.as_posix()}, follow in order: SE 6, SE 7, SE 12\n")
    assert out.index("## SE 6") < out.index("## SE 7") < out.index("## SE 12")
    assert "## obs 10" not in out
    assert upgrade_guide.main(["show", "--guide", str(guide), "--name", "SE", "--from", "12",
                               "--to", "12.0.1"]) == 0
    assert capsys.readouterr().out == f"SE: no section of {guide.as_posix()} lies between 12.0.0 and 12.0.1\n"
    assert upgrade_guide.main(["show", "--guide", str(guide), "--name", "SE", "--from", "five",
                               "--to", "12"]) == 2


def test_a_breaking_release_without_its_section_is_refused(tmp_path):
    refusal = upgrade_guide.missing(tmp_path, "SE", (13, 0, 0))
    assert refusal is not None and refusal.startswith("docs/upgrading.md has no section `## SE 13`")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "upgrading.md").write_text(GUIDE, encoding="utf-8")
    assert upgrade_guide.missing(tmp_path, "se", (12, 0, 0)) is None
    assert upgrade_guide.missing(tmp_path, "obs-html", (0, 3, 0)) is None
    assert upgrade_guide.missing(tmp_path, "obs-html", (0, 4, 0)).startswith(
        "docs/upgrading.md has no section `## obs-html 0.4`")


@pytest.mark.parametrize("text", ["6", "6.1", "v6.1.2"])
def test_versions_parse_with_or_without_minor_and_patch(text):
    assert upgrade_guide.parse(text)[0] == 6

