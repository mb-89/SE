"""Look at a built page as its reader will: each chapter at phone and desktop width, light and dark.

Reader: the agent that built a decision deck (scripts/deck.py build) or any other page for the person,
before handing it over, and whoever changes this command. Nothing runs it by itself: it is opt-in, and
`deck.py build` does not call it.

  look PAGE [--capabilities NAME,...] [--shots DIR]   Opens the built HTML PAGE in headless Chromium
      through node's Playwright (scripts/deck_look.js, the thin browser half), at each of VIEWS, visits
      each chapter and prints one line per finding, then one summary line. A finding names the chapter,
      the views it showed in and the element:
        - `overflow`: an element reaches past the viewport, so the page scrolls sideways (content in
          a container that scrolls sideways on purpose is not one);
        - `cut off`: an element hides part of its text (it clips its overflow, an ellipsis among them);
        - `overlap`: two text elements cover each other;
        - `empty`: a chapter with no text and no media, or a figure with no size, nothing in it or a
          broken image;
        - `script error`: an uncaught error on the page;
        - `capability`: the page asked the Claude app's runtime (`claude.use`) for a capability that
          --capabilities does not name, the ones the page is to be published with. The page runs beside
          a stand-in runtime that grants only those, so it behaves as in the app; a request only a click
          would make (a Send button) is not seen.
      --shots DIR saves one screenshot per chapter and width, in the light theme, as
      `<chapter>-<view>.png`; without it nothing is written.
      Where node, Playwright or its browser is missing, it prints one line saying so and exits 0.

The judging is pure: `judge` takes the measurements scripts/deck_look.js prints (one entry per view:
its chapters with their elements and figures, its script errors and capability requests, each field
named where `judge`'s helpers read it) and returns the findings; `look` is the wiring around it. Exit
code 0: no findings, or no browser; 1: findings; 2: setup error (no such page, or the browser failed).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().with_name("deck_look.js")
# Where the page is looked at: a phone and a desktop, each in both themes.
VIEWS = [
    {"name": f"{device}-{theme}", "width": width, "height": height, "theme": theme}
    for device, width, height in (("phone", 390, 844), ("desktop", 1280, 800))
    for theme in ("light", "dark")
]
TOLERANCE = 1  # px: subpixel layout is no finding.
OVERLAP = 2  # px: text boxes that share less than this in either direction do not cover each other.


def _ancestors(elements: list[dict], index: int) -> set[int]:
    found = set()
    parent = elements[index]["parent"]
    while parent >= 0:
        found.add(parent)
        parent = elements[parent]["parent"]
    return found


def _overflows(chapter: dict, width: int) -> list[tuple[str, str]]:
    """Elements that reach past the viewport outside a sideways scroller: the outermost of each run.

    A page that scrolls sideways with no such element in any chapter is one finding of its own (``judge``)."""
    elements = chapter["elements"]
    past = {index for index, element in enumerate(elements) if not element["scroller"]
            and (element["right"] > width + TOLERANCE or element["left"] < -TOLERANCE)}
    found = [(elements[index]["name"], "overflow: reaches past the viewport")
             for index in sorted(past) if elements[index]["parent"] not in past]
    return found


def _cut_off(chapter: dict) -> list[tuple[str, str]]:
    """Elements that clip text: they hide their overflow (or end it in an ellipsis) and it is there."""
    elements = chapter["elements"]
    texts = {index for index, element in enumerate(elements) if element["text"]}
    holding = {ancestor for index in texts for ancestor in _ancestors(elements, index)} | texts
    found = []
    for index, element in enumerate(elements):
        if index not in holding or element["client_width"] <= 2 or element["client_height"] <= 2:
            continue  # A visually hidden label (1 px, clipped) is meant for screen readers only.
        wide = element["scroll_width"] > element["client_width"] + TOLERANCE
        tall = element["scroll_height"] > element["client_height"] + TOLERANCE
        if element["clip_x"] and wide:
            found.append((element["name"], "cut off: part of its text is hidden sideways"))
        elif element["clip_y"] and tall:
            found.append((element["name"], "cut off: part of its text is hidden below"))
    return found


def _overlaps(chapter: dict) -> list[tuple[str, str]]:
    """Pairs of text elements, neither inside the other, whose boxes cover each other."""
    elements = chapter["elements"]
    texts = [index for index, element in enumerate(elements) if element["text"]]
    found = []
    for position, first in enumerate(texts):
        a = elements[first]
        for second in texts[position + 1:]:
            b = elements[second]
            across = min(a["right"], b["right"]) - max(a["left"], b["left"])
            down = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if across > OVERLAP and down > OVERLAP and first not in _ancestors(elements, second) \
                    and second not in _ancestors(elements, first):
                found.append((a["name"], f"overlap: covers {b['name']}"))
    return found


def _empties(chapter: dict) -> list[tuple[str, str]]:
    found = []
    if not chapter["text"] and not chapter["media"]:
        found.append(("chapter", "empty: no text and no media"))
    for figure in chapter["figures"]:
        if figure["width"] < 2 or figure["height"] < 2:
            found.append((figure["name"], "empty: the figure has no size"))
        elif figure["broken"]:
            found.append((figure["name"], "empty: an image did not load"))
        elif not figure["text"] and not figure["media"]:
            found.append((figure["name"], "empty: nothing in the figure"))
    return found


def judge(views: list[dict], declared: list[str]) -> list[str]:
    """The findings of one page's measurements: one line per chapter, element and kind, naming its views.

    ``views`` is what scripts/deck_look.js measured, ``declared`` the capabilities the page is to be
    published with. A finding seen in several views is one line listing them, in the order of the views."""
    seen: dict[tuple[str, str, str], list[str]] = {}

    def add(chapter: str, element: str, what: str, view: str) -> None:
        names = seen.setdefault((chapter, element, what), [])
        if view not in names:
            names.append(view)

    for view in views:
        blamed = False
        for chapter in view["chapters"]:
            overflows = _overflows(chapter, view["width"])
            blamed = blamed or bool(overflows)
            for element, what in overflows + _cut_off(chapter) + _overlaps(chapter) + _empties(chapter):
                add(chapter["name"], element, what, view["name"])
        widest = max((chapter["scroll_width"] for chapter in view["chapters"]), default=0)
        if not blamed and widest > view["width"] + TOLERANCE:
            add("page", "page", "overflow: the page scrolls sideways", view["name"])
        for error in view["errors"]:
            add(error["chapter"], "script", f"script error: {error['message']}", view["name"])
        for asked in view["requests"]:
            if asked["capability"] not in declared:
                add(asked["chapter"], "claude.use", f"capability: asks for `{asked['capability']}`, which the page "
                    "does not declare (--capabilities)", view["name"])
    every = [view["name"] for view in views]
    return [f"look: {chapter} ({'every view' if len(every) > 1 and names == every else ', '.join(names)}): {element}: {what}"
            for (chapter, element, what), names in seen.items()]


def summary(findings: list[str], views: list[dict], page: Path) -> str:
    chapters = len(views[0]["chapters"]) if views else 0
    shown = ", ".join(view["name"] for view in views)
    count = f"{len(findings)} finding(s)" if findings else "no findings"
    return f"look: {count} in {page.name}, {chapters} chapter(s) at {shown}"


def _browser(request: dict) -> dict:
    """Run the browser half with ``request``: its measurements, or ``{"skip": reason}``."""
    if shutil.which("node") is None:
        return {"skip": "node is not installed"}
    result = subprocess.run(["node", str(HARNESS), json.dumps(request)], capture_output=True, text=True,
                            encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"the browser exited with {result.returncode}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def look(page: Path, declared: list[str], shots: Path | None, browser=_browser) -> int:
    if not page.is_file():
        print(f"look: {page} is no built page", file=sys.stderr)
        return 2
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    request = {"url": page.resolve().as_uri(), "views": VIEWS, "declared": declared,
               "shots": str(shots.resolve()) if shots else None}
    try:
        measured = browser(request)
    except (RuntimeError, ValueError, IndexError) as error:
        print(f"look: the browser failed: {error}", file=sys.stderr)
        return 2
    if "skip" in measured:
        print(f"look: skipped, {measured['skip']}")
        return 0
    findings = judge(measured["views"], declared)
    for line in findings:
        print(line)
    print(summary(findings, measured["views"], page))
    return 1 if findings else 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deck_look.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    looked = commands.add_parser("look", help="render a built page's chapters and report what the reader would miss")
    looked.add_argument("page", type=Path)
    looked.add_argument("--capabilities", default="",
                        help="the capabilities the page is published with, comma-separated")
    looked.add_argument("--shots", type=Path, help="save one screenshot per chapter and width here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    declared = [name.strip() for name in args.capabilities.split(",") if name.strip()]
    return look(args.page, declared, args.shots)


if __name__ == "__main__":
    sys.exit(main())
