# se:template se/python-module 1.0.0
"""A retro's and an overhaul's one output, its deck: the retro-deck template rendered, checked and built.

Reader: retro.py and overhaul.py, whose `deck` commands build it from their judged draft, and whoever
changes how the deck is laid out. The template, `templates/retro-deck.md` (TEMPLATE_NAME), owns what
the deck holds; this module owns how its text becomes an obs vault and one HTML file.

- `text(title, subtitle, steps, decisions)` renders the template from the run's parts: each step and
  each decision a `(heading, body)` pair, the body written as a chapter note's (its own headings `##`
  and deeper), shifted two levels down under the template's `### <heading>`. It refuses, raising
  DeckError, what breaks the template.
- `vault(text, folder)` reads that text back through the template and writes it as obs notes: the
  manifest, whose front matter makes the title page (obs's cover: the title, the subtitle and
  DOCUMENT_TYPE, `obsHtml.pages` with the cover), one note per step in order, then one note per
  decision, last, each asking the person for a bless (`obs: {bless: pending}`). The build machine's
  home folder in the quoted text is written as `~`, as obs-html refuses to publish it (`homeless`), and
  each ISO time of day as the template states it, `22 Nov 20:16` in UTC (`times`), as obs-html's
  provenance check refuses an ISO timestamp.
- `build(text, destination, host, answers)` builds that vault with scripts/deck.py's build (the answers
  bundle for `host`, whose adapter takes the answers back) into `destination`, the run's one report
  file: nothing else is written beside it. With `answers` it is the record of the person's answers.
  The deck quotes the draft's facts and the judge's findings as they stand, so it is built `quoted`:
  obs's long-paragraph lint and obs-html's provenance findings of an absolute path refuse nothing in
  it (deck.py build, build_docs.py QUOTED).

The engine has no title page, no table field and no data inside a fence (docs/what-should-be-templates.md,
C2, C6 and C10); the deck needs none of them from it. The title page is the template's two label lines,
which `vault` writes as obs's cover metadata; the tables are Markdown inside the step's text, which obs
renders; the decisions are bless chapters, no `pugh` fence.
"""

from __future__ import annotations

import contextlib
import io
import re
from datetime import datetime, timezone
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deck  # noqa: E402
import review  # noqa: E402
import templates  # noqa: E402

TEMPLATE_NAME = "retro-deck"
#: The title page's document type (obs's cover metadata).
DOCUMENT_TYPE = "Retro report"
#: The chapter notes' level under the template: a step's or a decision's `### <heading>`.
CHAPTER = 3
#: What the template's decisions hold where the run brings no finding.
NONE = "None."
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
COMMENT = re.compile(r"<!--.*?-->[ \t]*\n?", re.DOTALL)


#: An ISO time of day after a date (`2026-11-22T20:16:05Z`, `2026-11-22 20:16`), which obs-html's provenance
#: check refuses in a page; the deck writes it as the retro-deck template states it, `22 Nov 20:16` in UTC
#: (`times`).
ISO_TIME = re.compile(r"\b(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(:\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?(?![\d:])")


class DeckError(ValueError):
    """The deck cannot be written: what is wrong and its remedy."""


def template():
    """The retro-deck template, as SE's checkout holds it."""
    return templates.own(TEMPLATE_NAME)


def chapters(text: str) -> list[tuple[str, str]]:
    """The `### <heading>` chapters of a template field's `text`, outside fences, each with its body
    as a chapter note's (its headings two levels higher)."""
    found: list[tuple[str, list[str]]] = []
    fence = None
    for line in text.splitlines():
        opened = FENCE.match(line)
        if fence is not None:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened:
            fence = opened.group(1)
        elif line.startswith("#" * CHAPTER + " "):
            found.append((line[CHAPTER + 1:].strip(), []))
            continue
        if found:
            found[-1][1].append(line)
    return [(heading, review.demoted("\n".join(body), 1 - CHAPTER).strip()) for heading, body in found]


def _part(heading: str, body: str) -> str:
    heading = " ".join(heading.split())
    if not heading:
        raise DeckError("a chapter of the deck has no heading")
    body = COMMENT.sub("", body).strip() or NONE
    return f"{'#' * CHAPTER} {heading}\n\n{review.demoted(body, CHAPTER - 1)}"


def text(title: str, subtitle: str, steps: list[tuple[str, str]],
         decisions: list[tuple[str, str]]) -> str:
    """The deck as the retro-deck template writes it: the title page's lines, every step, then the
    decisions ("None." where there are none); DeckError names what breaks the template."""
    if not steps:
        raise DeckError("the deck has no step: write each step the run ran as a chapter")
    fields = {"title": " ".join(title.split()), "subtitle": " ".join(subtitle.split()),
              "steps": "\n\n".join(_part(*step) for step in steps),
              "decisions": "\n\n".join(_part(*item) for item in decisions) or NONE}
    written = templates.render(template(), fields)
    refused = [finding.fix for finding in templates.check(template(), templates.parse(template(), written))
               if finding.severity == templates.REFUSE]
    if refused:
        raise DeckError("the deck breaks the retro-deck template (templates/retro-deck.md): " + "; ".join(refused))
    return written


def _yaml(value: str) -> str:
    """`value` as a double-quoted YAML (and JSON) string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _label(heading: str) -> str:
    """A chapter's heading as a wikilink label: no `|`, `[` or `]`, which would end the link."""
    return re.sub(r"[|\[\]]", " ", heading).strip()


def times(text: str) -> str:
    """`text` with each ISO time of day (ISO_TIME) written as `22 Nov 20:16`, the day without a leading
    zero, in UTC where it names an offset; a calendar date alone stays as it is."""
    def written(match: re.Match) -> str:
        zone = match[4] or "Z"
        moment = datetime.fromisoformat(f"{match[1]}T{match[2]}{match[3] or ''}"
                                        f"{'+00:00' if zone == 'Z' else zone}").astimezone(timezone.utc)
        return f"{moment.day} {moment:%b %H:%M}"
    return ISO_TIME.sub(written, text)


def homeless(text: str, home: str) -> str:
    """`text` with the build machine's home folder `home` written as `~`, as obs-html asks of a path it
    would otherwise refuse to publish (a field report that quotes a cloud container's `/root/...`)."""
    home = home.rstrip("/\\")
    if len(home) < 2:
        return text
    return re.sub(rf"(?<![\w/\\.-]){re.escape(home)}(?=[/\\]|(?![\w.-]))", "~", text)


def vault(written: str, folder: Path, home: str | None = None) -> list[str]:
    """Write the deck `written` (`text`) into `folder` as obs notes: the manifest with the title page,
    a note per step, then a note per decision asking for a bless; the ids of the decisions' notes. The
    build machine's home folder (`home`, by default this one's) is written as `~` (`homeless`)."""
    written = times(homeless(written, str(Path.home()) if home is None else home))
    fields = templates.parse(template(), written).fields
    steps = chapters(fields["steps"])
    decisions = [] if fields["decisions"].strip() == NONE else chapters(fields["decisions"])
    folder.mkdir(parents=True, exist_ok=True)
    links, asked = [], []
    for kind, items in (("step", steps), ("decision", decisions)):
        for index, (heading, body) in enumerate(items, 1):
            name = f"{kind}-{index:02d}"
            front = "---\nobs: {bless: pending}\n---\n" if kind == "decision" else ""
            (folder / f"{name}.md").write_text(f"{front}# {heading}\n\n{body}\n", encoding="utf-8", newline="\n")
            links.append(f"- [[{name}|{_label(heading)}]]")
            if kind == "decision":
                asked.append(name)
    manifest = ["---", f"title: {_yaml(fields['title'])}", f"subtitle: {_yaml(fields['subtitle'])}",
                f"document type: {_yaml(DOCUMENT_TYPE)}",
                "obsHtml: {layout: paged, pages: [{page: cover}]}", "---", "", *links, ""]
    (folder / "manifest.md").write_text("\n".join(manifest), encoding="utf-8", newline="\n")
    return asked


def build(written: str, destination: Path, host: str | None = None, answers: Path | None = None) -> int:
    """Build the deck `written` into `destination`, its one HTML file, with the answers bundle for
    `host` (scripts/deck.py HOSTS; None, the host this runs under); with `answers`, the record. Exit
    code as deck.py build's."""
    with tempfile.TemporaryDirectory() as scratch:
        notes = Path(scratch) / "deck"
        asked = vault(written, notes)
        built = Path(scratch) / "built" / destination.name
        built.parent.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):  # its line names the scratch copy
            code = deck.build(notes, built, answers, host, asks=bool(asked), quoted=True)
        if code:
            destination.unlink(missing_ok=True)
            return code
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built, destination)
    return 0
