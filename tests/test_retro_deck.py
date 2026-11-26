"""The retro's and the overhaul's one output, its deck (scripts/retro_deck.py): the retro-deck template
rendered from a run's parts, read back into obs notes, and one real build whose destination is the one
file it writes."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

import retro_deck
import templates

STEPS = [("2. Table of what happened", "| chapter | steps |\n|---|---|\n| 1 | #11 |"),
         ("3. The standing questions", "| question | 1 |\n|---|---|\n| Has the process gone stale? | #11 |\n\n"
                                       "## Answers to the standing questions\n\n### Has the process gone stale?\n\nNo.\n\n"
                                       "```sh\n# not a heading\n```")]
CHANGE = {"key": "a", "label": "Refuse it at the landing", "what": "integrate refuses it.",
          "wins": "No lost report.", "losses": "One more check.", "success": "No landing lacks one.",
          "marks": {"cause": {"mark": 1, "because": "it removes the cause"}}}
KEEP = {"key": "b", "label": "Keep what we have", "what": "Nothing changes.", "wins": "No work.",
        "losses": "Reports stay lost.", "success": "Nothing to check.", "marks": {"cause": 0}}
CRITERIA = [{"key": "cause", "label": "Removes the cause", "weight": 1, "better": "higher", "kind": "judged"}]


def note(situation: str) -> str:
    return retro_deck.decision_note(situation, "Reports get lost.", "Gerrit and GitHub both gate merges on checks.",
                                    CRITERIA, [CHANGE, KEEP], "b")


DECISIONS = [("1. Refuse a landing without a field report", note("#14 closed without a field report.")),
             ("2. Make the field report a rule", note("The field report is a habit, not a rule.")),
             retro_deck.ANYTHING_ELSE]


def deck_text(decisions=DECISIONS) -> str:
    return retro_deck.text("example: Retro #30", "", STEPS, decisions)


def test_the_cover_names_retro_report_once_as_its_document_type(tmp_path):
    """A project's retro deck: the cover rendered "Retro report" twice, as subtitle and document type."""
    retro_deck.vault(deck_text(), tmp_path)
    front = (tmp_path / "manifest.md").read_text(encoding="utf-8").split("---")[1]
    assert front.count("Retro report") == 1
    assert f'document type: "{retro_deck.DOCUMENT_TYPE}"' in front and "subtitle" not in front


@pytest.mark.spawns("tool: the retro's deck builds with the real obs, obs-document in obs's own Python "
                    "environment, which runs only as a process")
def test_the_built_cover_is_exactly_the_title_and_retro_report_once(tmp_path, obs):
    """Retro #20's cover, checked in a browser: the title and one "Retro report", nothing else."""
    destination = tmp_path / "retro-30.html"
    assert retro_deck.build(deck_text(), destination, "copilot") == 0
    page = destination.read_text(encoding="utf-8")
    cover = json.loads(html.unescape(re.search(r'id="running-header-script" data-header-metadata="([^"]*)"', page)[1]))
    assert list(cover.values()) == ["example: Retro #30", "Retro report"]


def test_a_free_form_decision_chapter_is_refused_naming_it():
    with pytest.raises(retro_deck.DeckError, match=r'decision "1\. Refuse it".*Current situation is missing'):
        deck_text([("1. Refuse it", "**Work, for your go**: Bless sends it to SE.")])
    with pytest.raises(retro_deck.DeckError, match='decision "2. Bare".*What others do is empty'):
        deck_text([("2. Bare", retro_deck.decision_note("A.", "B.", "", CRITERIA, [CHANGE, KEEP], "b"))])


def test_every_decision_page_has_the_same_sections_and_the_pugh_block(tmp_path):
    asked = retro_deck.vault(deck_text(), tmp_path)
    shapes = set()
    for name in asked:
        page = (tmp_path / f"{name}.md").read_text(encoding="utf-8")
        before, fence = page.split("```pugh\n", 1)
        shapes.add(tuple(re.findall(r"^## (.+)$", before, re.MULTILINE)))
        assert "\ncandidates:\n" in fence and "\ndatum: " in fence
    assert shapes == {("Current situation", "The problem", "What others do")}


def test_the_deck_is_a_document_of_the_retro_deck_template_steps_first_decisions_last():
    text = deck_text()
    template = retro_deck.template()
    assert templates.select(templates.load(templates.ROOT, tree=True), "deck.build", text).template.name == "retro-deck"
    fields = templates.parse(template, text).fields
    assert (fields["title"], fields.get("subtitle") or "") == ("example: Retro #30", "")
    assert text.index("\n## Steps\n") < text.index("\n### 2. Table of what happened\n") < text.index(
        "\n#### Answers to the standing questions\n") < text.index("\n## Decisions\n") < text.index(
        "\n### 1. Refuse a landing without a field report\n") < text.index("\n### Anything else?\n")
    assert "\n# not a heading\n" in text  # a fence's lines are no headings


def test_the_chapters_read_back_as_the_parts_were_given():
    fields = templates.parse(retro_deck.template(), deck_text()).fields
    assert retro_deck.chapters(fields["steps"]) == [(heading, body) for heading, body in STEPS]
    assert retro_deck.chapters(fields["decisions"]) == DECISIONS


def test_a_run_without_a_step_or_with_an_empty_heading_is_refused():
    with pytest.raises(retro_deck.DeckError, match="the deck has no step"):
        retro_deck.text("Retro #30", "x", [], [])
    with pytest.raises(retro_deck.DeckError, match="has no heading"):
        retro_deck.text("Retro #30", "x", [(" ", "Body.")], [])
    with pytest.raises(retro_deck.DeckError, match="Title"):
        retro_deck.text(" ", "", STEPS, [])


def test_the_vault_has_the_title_page_every_step_and_each_decision_last_asking_a_bless(tmp_path):
    asked = retro_deck.vault(deck_text(), tmp_path)
    assert asked == ["decision-01", "decision-02", "decision-03"]
    manifest = (tmp_path / "manifest.md").read_text(encoding="utf-8")
    front = manifest.split("---")[1]
    assert 'title: "example: Retro #30"' in front
    assert f'document type: "{retro_deck.DOCUMENT_TYPE}"' in front
    assert "obsHtml: {layout: paged, pages: [{page: cover}]}" in front
    assert re.findall(r"^- \[\[([\w-]+)\|", manifest, re.MULTILINE) == [
        "step-01", "step-02", "decision-01", "decision-02", "decision-03"]
    step = (tmp_path / "step-02.md").read_text(encoding="utf-8")
    assert step.startswith("# 3. The standing questions\n\n| question | 1 |")
    assert "\n## Answers to the standing questions\n\n### Has the process gone stale?\n" in step
    decision = (tmp_path / "decision-02.md").read_text(encoding="utf-8")
    assert decision.startswith("---\nobs: {bless: pending}\n---\n# 2. Make the field report a rule\n")
    anything_else = (tmp_path / "decision-03.md").read_text(encoding="utf-8")
    assert anything_else.startswith("---\nobs: {bless: pending}\n---\n# Anything else?\n\n## Current situation\n")
    assert '"label": "Nothing else"' in anything_else and '"fits": false' in anything_else
    assert "obs: {bless: pending}" in anything_else
    assert "bless" not in step


def test_a_run_without_findings_has_no_decision_chapter(tmp_path):
    text = deck_text(decisions=[])
    assert templates.parse(retro_deck.template(), text).fields["decisions"] == retro_deck.NONE
    assert retro_deck.vault(text, tmp_path) == []
    assert not list(tmp_path.glob("decision-*.md"))


@pytest.mark.parametrize(("text", "home", "written"), [
    ("in `/srv/box/.config/obs` and /srv/box, not /srv/boxes or x/srv/box/y", "/srv/box",
     "in `~/.config/obs` and ~, not /srv/boxes or x/srv/box/y"),
    ("D:\\Data\\box\\SE and D:\\Data\\boxes", "D:\\Data\\box", "~\\SE and D:\\Data\\boxes"),
    ("/ stays", "/", "/ stays"),
], ids=["posix", "windows", "root-folder"])
def test_the_build_machines_home_is_written_as_a_tilde(text, home, written):
    assert retro_deck.homeless(text, home) == written


def test_the_vault_writes_the_home_folder_as_a_tilde(tmp_path):
    text = retro_deck.text("Retro #30", "x", [("1. Collect", "It read /srv/box/.cache.")], [])
    retro_deck.vault(text, tmp_path, home="/srv/box")
    assert "It read ~/.cache." in (tmp_path / "step-01.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(("text", "written"), [
    ("from 2026-11-22T20:16:05Z to 2026-11-23 08:05", "from 22 Nov 20:16 to 23 Nov 08:05"),
    ("at 2026-11-22T21:16:00+01:00.", "at 22 Nov 20:16."),
    ("on 2026-11-22 only, version 2026-11-22T20", "on 2026-11-22 only, version 2026-11-22T20"),
], ids=["utc", "offset", "dates-stay"])
def test_iso_times_are_written_as_the_template_states_them(text, written):
    """kern retro #56: obs-html's provenance check refuses an ISO time; the deck writes `22 Nov 20:16`."""
    assert retro_deck.times(text) == written


def test_the_vault_writes_times_as_the_template_states_them(tmp_path):
    text = retro_deck.text("Retro #30", "x", [("Table", "| 1 | 2026-11-02T10:00:00Z | #11 |")], [])
    retro_deck.vault(text, tmp_path)
    assert "| 1 | 2 Nov 10:00 | #11 |" in (tmp_path / "step-01.md").read_text(encoding="utf-8")


@pytest.mark.spawns("tool: the retro's deck builds with the real obs, obs-document in obs's own Python "
                    "environment, which runs only as a process")
def test_the_real_build_writes_one_file_and_its_data_names_the_host_and_the_decisions(tmp_path, obs):
    destination = tmp_path / "report" / "retro-30.html"
    long = " ".join(["A finding the judge wrote in one long paragraph."] * 40)
    steps = [*STEPS, ("5. Classes and homes", f"{long}\n\nThe chapter from 2026-11-02T10:00:00Z.")]
    assert retro_deck.build(retro_deck.text("Retro #30", "x", steps, DECISIONS), destination, "copilot") == 0
    assert [path.name for path in destination.parent.iterdir()] == ["retro-30.html"]
    page = destination.read_text(encoding="utf-8")
    data = json.loads(re.search(r"globalThis\.seDeck = Object\.freeze\((\{.*?\})\);", page)[1])
    assert data["host"] == "copilot" and data["title"] == "Retro #30"
