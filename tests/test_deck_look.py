"""`deck_look.py look`: the pure judge on measurements everywhere, the browser run where node has Playwright."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import deck_look  # noqa: E402


def _element(name: str, parent: int = -1, *, left: float = 0, right: float = 100, top: float = 0,
             bottom: float = 20, text: bool = True, scroller: bool = False, clip_x: bool = False,
             clip_y: bool = False, scroll: tuple[int, int] = (100, 20), client: tuple[int, int] = (100, 20)) -> dict:
    return {"name": name, "parent": parent, "left": left, "right": right, "top": top, "bottom": bottom,
            "text": text, "scroller": scroller, "clip_x": clip_x, "clip_y": clip_y,
            "scroll_width": scroll[0], "scroll_height": scroll[1],
            "client_width": client[0], "client_height": client[1]}


def _chapter(name: str = "one", elements: list[dict] | None = None, figures: list[dict] | None = None,
             text: int = 10, media: int = 0, scroll_width: int = 390) -> dict:
    return {"name": name, "text": text, "media": media, "height": 100, "scroll_width": scroll_width,
            "elements": elements if elements is not None else [_element("p \"Fine\"")],
            "figures": figures or []}


def _view(chapters: list[dict], name: str = "phone-light", width: int = 390, errors: list[dict] | None = None,
          requests: list[dict] | None = None) -> dict:
    return {"name": name, "width": width, "height": 844, "theme": "light", "chapters": chapters,
            "errors": errors or [], "requests": requests or []}


def test_a_clean_page_has_no_findings():
    assert deck_look.judge([_view([_chapter()])], []) == []


def test_an_element_past_the_viewport_is_one_finding_for_its_outermost_box():
    elements = [_element("section"), _element("div.wide", 0, right=900), _element("span", 1, right=890)]
    assert deck_look.judge([_view([_chapter(elements=elements)])], []) == [
        'look: one (phone-light): div.wide: overflow: reaches past the viewport']


def test_overflow_inside_a_container_that_scrolls_sideways_is_none():
    elements = [_element("div.table", right=390), _element("table", 0, right=900, scroller=True)]
    assert deck_look.judge([_view([_chapter(elements=elements)])], []) == []


def test_a_page_wider_than_its_viewport_without_an_element_to_blame_scrolls_sideways():
    assert deck_look.judge([_view([_chapter(scroll_width=500), _chapter("two")])], []) == [
        "look: page (phone-light): page: overflow: the page scrolls sideways"]


def test_text_a_box_clips_is_cut_off_but_a_visually_hidden_label_is_not():
    elements = [_element("p.title", clip_x=True, scroll=(180, 20), client=(100, 20)),
                _element("div.box", clip_y=True, text=False, scroll=(100, 60), client=(100, 20)),
                _element("span", 1, top=40, bottom=60),
                _element("span.sr-only", top=70, bottom=71, clip_x=True, clip_y=True, scroll=(80, 20), client=(1, 1))]
    assert deck_look.judge([_view([_chapter(elements=elements)])], []) == [
        'look: one (phone-light): p.title: cut off: part of its text is hidden sideways',
        'look: one (phone-light): div.box: cut off: part of its text is hidden below']


def test_text_boxes_that_cover_each_other_overlap_but_nested_ones_do_not():
    elements = [_element("p.a"), _element("strong", 0, right=40, bottom=8), _element("p.b", top=10, bottom=30),
                _element("p.c", top=29, bottom=40)]
    assert deck_look.judge([_view([_chapter(elements=elements)])], []) == [
        'look: one (phone-light): p.a: overlap: covers p.b']


def test_an_empty_chapter_and_empty_figures_are_named():
    figures = [{"name": "figure#flat", "width": 300, "height": 0, "text": 0, "media": 0, "broken": False},
               {"name": "figure#bare", "width": 300, "height": 50, "text": 0, "media": 0, "broken": False},
               {"name": "img", "width": 300, "height": 50, "text": 0, "media": 1, "broken": True},
               {"name": "figure#chart", "width": 300, "height": 50, "text": 0, "media": 1, "broken": False}]
    assert deck_look.judge([_view([_chapter("blank", elements=[], text=0), _chapter(figures=figures)])], []) == [
        "look: blank (phone-light): chapter: empty: no text and no media",
        "look: one (phone-light): figure#flat: empty: the figure has no size",
        "look: one (phone-light): figure#bare: empty: nothing in the figure",
        "look: one (phone-light): img: empty: an image did not load"]


def test_script_errors_and_undeclared_capabilities_name_their_chapter():
    view = _view([_chapter()], errors=[{"message": "Error: planted", "chapter": "page"}],
                 requests=[{"capability": "downloads", "chapter": "page"},
                           {"capability": "artifact", "chapter": "one"}])
    assert deck_look.judge([view], ["artifact"]) == [
        "look: page (phone-light): script: script error: Error: planted",
        "look: page (phone-light): claude.use: capability: asks for `downloads`, which the page does not "
        "declare (--capabilities)"]


def test_a_finding_in_several_views_is_one_line_naming_them():
    wide = _chapter(elements=[_element("div.wide", right=900)])
    views = [_view([wide], name) for name in ("phone-light", "phone-dark")]
    views.append(_view([_chapter(elements=[_element("div.wide", right=900)])], "desktop-light", width=1280))
    assert deck_look.judge(views, []) == ["look: one (phone-light, phone-dark): div.wide: overflow: reaches past the viewport"]
    assert deck_look.judge(views[:2], []) == ["look: one (every view): div.wide: overflow: reaches past the viewport"]


def _look(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "deck_look.py"), "look", *args],
                          capture_output=True, text=True, env=env)


def test_without_node_look_says_so_in_one_line_and_passes(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<p>Hi</p>", encoding="utf-8")
    result = _look(str(page), env={**os.environ, "PATH": str(tmp_path)})
    assert (result.returncode, result.stdout, result.stderr) == (0, "look: skipped, node is not installed\n", "")


def test_without_playwright_or_its_browser_look_skips_and_writes_no_shots(tmp_path, capsys):
    page = tmp_path / "page.html"
    page.write_text("<p>Hi</p>", encoding="utf-8")
    code = deck_look.look(page, [], None, browser=lambda request: {"skip": "node has no playwright"})
    assert (code, capsys.readouterr().out) == (0, "look: skipped, node has no playwright\n")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["page.html"]


def test_a_missing_page_is_a_setup_error(tmp_path):
    result = _look(str(tmp_path / "none.html"))
    assert result.returncode == 2 and "is no built page" in result.stderr


def _playwright() -> bool:
    return shutil.which("node") is not None and not subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True).returncode


browser = pytest.mark.skipif(not _playwright(), reason="node with playwright is not installed")

PLANTED = """<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body {margin: 0; font: 16px sans-serif} section {padding: 8px}</style></head>
<body>
<section id="wide"><h2>Wide</h2><div class="row" style="width: 2000px">A row wider than any screen.</div></section>
<section id="blank"></section>
<section id="fine"><h2>Fine</h2><p>Text that fits.</p></section>
<script>throw new Error("planted");</script>
</body></html>
"""


@browser
def test_look_finds_the_planted_overflow_empty_chapter_and_script_error_and_shoots_on_request(tmp_path):
    page = tmp_path / "planted.html"
    page.write_text(PLANTED, encoding="utf-8")
    shots = tmp_path / "shots"
    result = _look(str(page), "--shots", str(shots))
    assert result.returncode == 1, result.stderr
    assert result.stdout.splitlines() == [
        'look: wide (every view): div.row "A row wider than any screen.": overflow: reaches past the viewport',
        "look: blank (every view): chapter: empty: no text and no media",
        "look: page (every view): script: script error: planted",
        "look: 3 finding(s) in planted.html, 3 chapter(s) at phone-light, phone-dark, desktop-light, desktop-dark",
    ]
    assert sorted(path.name for path in shots.iterdir()) == sorted(
        f"{chapter}-{device}-light.png" for chapter in ("wide", "blank", "fine") for device in ("phone", "desktop"))


@browser
def test_a_clean_built_deck_has_no_findings_and_writes_nothing(tmp_path, obs):
    folder = tmp_path / "decisions"
    folder.mkdir()
    (folder / "decision-deck.md").write_text(
        (ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md").read_text(encoding="utf-8"),
        encoding="utf-8")
    (folder / "manifest.md").write_text("---\ntitle: Decisions\n---\n\n- [[decision-deck|Decision deck]]\n",
                                        encoding="utf-8")
    deck = tmp_path / "deck.html"
    built = subprocess.run([sys.executable, str(SCRIPTS / "deck.py"), "build", str(folder), "--destination", str(deck)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    before = sorted(path.name for path in tmp_path.iterdir())
    result = _look(str(deck), "--capabilities", "artifact,comments,downloads")
    assert (result.returncode, result.stdout) == (0, "look: no findings in deck.html, 1 chapter(s) at phone-light, "
                                                     "phone-dark, desktop-light, desktop-dark\n"), result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == before
