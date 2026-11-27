"""The retro's and the overhaul's one output, its deck (scripts/retro_deck.py): the retro-deck template
rendered from a run's parts, read back into obs notes, and one real build whose destination is the one
file it writes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import retro_deck
import templates
from test_docs import obs_in_process

STEPS = [("2. Table of what happened", "| chapter | steps |\n|---|---|\n| 1 | #11 |"),
         ("3. The standing questions", "| question | 1 |\n|---|---|\n| Has the process gone stale? | #11 |\n\n"
                                       "## Answers to the standing questions\n\n### Has the process gone stale?\n\nNo.\n\n"
                                       "```sh\n# not a heading\n```")]
DECISIONS = [("1. Refuse a landing without a field report", "**Work, for your go**: Bless sends it to SE."),
             ("2. Make the field report a rule", "**Decision, for your decision**: it changes a rule."),
             ("Anything else?", "Nothing else")]


def deck_text(decisions=DECISIONS) -> str:
    return retro_deck.text("example: Retro #30", "Retro report", STEPS, decisions)


def test_the_deck_is_a_document_of_the_retro_deck_template_steps_first_decisions_last():
    text = deck_text()
    template = retro_deck.template()
    assert templates.select(templates.load(templates.ROOT, tree=True), "deck.build", text).template.name == "retro-deck"
    fields = templates.parse(template, text).fields
    assert (fields["title"], fields["subtitle"]) == ("example: Retro #30", "Retro report")
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
    with pytest.raises(retro_deck.DeckError, match="Subtitle"):
        retro_deck.text("Retro #30", " ", STEPS, [])


def test_the_vault_has_the_title_page_every_step_and_each_decision_last_asking_a_bless(tmp_path):
    asked = retro_deck.vault(deck_text(), tmp_path)
    assert asked == ["decision-01", "decision-02", "decision-03"]
    manifest = (tmp_path / "manifest.md").read_text(encoding="utf-8")
    front = manifest.split("---")[1]
    assert 'title: "example: Retro #30"' in front and 'subtitle: "Retro report"' in front
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
    assert anything_else.startswith("---\nobs: {bless: pending}\n---\n# Anything else?\n\nNothing else\n")
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


def test_the_real_build_writes_one_file_and_its_data_names_the_host_and_the_decisions(tmp_path, obs_in_process):
    destination = tmp_path / "report" / "retro-30.html"
    long = " ".join(["A finding the judge wrote in one long paragraph."] * 40)
    steps = [*STEPS, ("5. Classes and homes", f"{long}\n\nThe chapter from 2026-11-02T10:00:00Z.")]
    assert retro_deck.build(retro_deck.text("Retro #30", "x", steps, DECISIONS), destination, "copilot") == 0
    assert [path.name for path in destination.parent.iterdir()] == ["retro-30.html"]
    page = destination.read_text(encoding="utf-8")
    data = json.loads(re.search(r"globalThis\.seDeck = Object\.freeze\((\{.*?\})\);", page)[1])
    assert data["host"] == "copilot" and data["title"] == "Retro #30"
