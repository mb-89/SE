#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Bring decisions to the person as one deck: build it with obs, serve it locally and read its answers.

Reader: the agent that asks the person for decisions, and whoever changes this command. The decision
skill (src/skills/decision/SKILL.md) says when to use it; this file owns what each subcommand does.

  build FOLDER --destination HTML [--host HOST]   FOLDER holds the decision notes and their manifest (obs's
      `manifest.md`, or what the folder's cfg.json names). obs parses them, then builds them into one
      HTML artifact, with se's answers bundle (scripts/deck_answers.js) as its trusted runtime bundle, in
      obs's screens layout (one chapter per phone screen) unless the manifest sets `obsHtml.layout`. A chapter
      asks for a bless (`obs: {bless: pending}`) or is a record: what was decided without the person, or
      their tasks. It fails on a deck where no chapter asks, on a decision (a `pugh` fence) that does
      not ask, outside a record built with the answers, on a decision without `## Current situation`,
      `## The problem` and `## What others do`, in that order, before its fence (the decision skill's note shape), and on
      any obs warning. It writes the obs Document the deck was built from beside it, `<deck>.document.json`
      (its chapters, their versions and answers): read that, never the built page. It warns, building all
      the same, of each option without `success`, each mark off the datum without `because` (the
      decision skill's fence fields) and each option whose text names another option by its key or
      short name (the decision skill: only the matrix compares them), naming the note and the option.
      It builds with obs-html's passing line after Send on for four seconds (`BRIEF_NOTICE_MILLISECONDS`,
      obs's `artifact.reading.briefNoticeMilliseconds`), set in the vault copy's cfg.json beside the
      folder's own keys (`brief_notice`); a value the folder's cfg.json sets wins, so 0 turns it off there.
      HOST (HOSTS) is the host the answers go back to, written into the deck's data, where the answers
      bundle picks its adapter (the bundle's header owns each): `claude-app`, `claude-code`, `copilot`, or
      `local`, obs-html's own sinks; without it, the host this command runs under (`default_host`).
      In the Claude app, publish the deck with the Artifact tool and `capabilities: {artifact: {},
      comments: {}, downloads: true}`: the full-form `comments` lets Send send the answers to Claude as a
      comment, which wakes the watching session, and `artifact` lets it also save answers.json (the
      record the session reads). Send succeeds when either works; a deck published without them shows
      the answers as text to copy. `downloads` keeps obs-html's file offers (its download and export
      links) working, which without it do nothing (obs-html's spec/capabilities/file-offers.md). The
      bundle's header owns how Send uses them and how the reader is told.
  serve HTML --wait [--timeout S]   Serves the deck with obs-html serve: prints the URL to open first,
      then, once the person sends, the answers payload as one JSON line (also written to answers.json
      beside HTML). For Claude Code, Copilot and any local browser. Without --wait it serves until stopped
      and writes answers.json beside HTML at each send, so a session that runs it in the background reads
      that file on its next turn and never waits on the person.
  answers ANSWERS [--record FOLDER --destination HTML]   Prints, per decision, what to act on: the
      verdict, the picked option, the comment and the weights, marks, vetoes, lifted vetoes, datum and
      rulings the person changed.
      An entry with a comment and no verdict reads `<chapter>: comment`: the decision is still open.
      With --record it also builds FOLDER again with the answers (obs-document --answers): that
      artifact is the decision's record.

The answers payload's fields are owned by obs's src/obs/answers.schema.json. Exit code 0: done;
1: the build failed, obs warned, no chapter or no decision asks for a bless, or the answers are
malformed, or a decision does not explain its problem and how others solve it before its options; 2: setup error, or no answers within --timeout.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
import se_script

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hosts  # noqa: E402
import process_door  # noqa: E402
import se_components  # noqa: E402
import templates  # noqa: E402
from build_docs import QUOTED, child_environment, obs_dir, obs_document, ready_adapter  # noqa: E402

BUNDLE = Path(__file__).resolve().with_name("deck_answers.js")
BUNDLE_ID = "se-answers"  # The id deck_answers.js registers with.
BUNDLE_FILE = f"{BUNDLE_ID}.js"
# How long obs-html's passing line after Send ("Sent to Claude.") shows on SE's decks, in ms
# (obs-html's spec/artifact-ui.md, Dock menu: `artifact.reading.briefNoticeMilliseconds`, default 0, off).
BRIEF_NOTICE_MILLISECONDS = 4000
#: The hosts a deck's answers go back to, one adapter each in the answers bundle (scripts/deck_answers.js,
#: its header): the Claude app, Claude Code, Copilot, and `local`, which leaves obs-html's own sinks.
HOSTS = ("claude-app", "claude-code", "copilot", "local")


def default_host(environment: dict[str, str]) -> str:
    """The host a deck built under ``environment`` sends its answers to, by the host table's marks
    (scripts/hosts.sh): Copilot where its hook file names it, the Claude app in Claude's cloud, Claude
    Code where it started the process, else ``local``."""
    if environment.get(hosts.table()["SE_HOOK_HOSTS"][0]) == "copilot":
        return "copilot"
    if "claude" in hosts.clouds(environment):
        return "claude-app"
    return "claude-code" if hosts.host(environment) == "claude" else "local"


def document_path(destination: Path) -> Path:
    """Where ``build`` writes the obs Document a deck at ``destination`` was built from: ``<deck>.document.json``."""
    return destination.with_suffix(".document.json")


def build(folder: Path, destination: Path, answers: Path | None = None, host: str | None = None,
          asks: bool = True, quoted: bool = False) -> int:
    """Build ``folder`` into ``destination`` with the answers bundle for ``host`` (HOSTS; None, the host
    this runs under, ``default_host``); with ``answers``, the record.

    obs parses the notes into a Document first; its chapters decide the refusals and give the bundle its
    data (``_bundle``). The deck's build writes its own Document beside it (``document_path``), so tests
    and agents read its chapters and versions there, never from the built page. Without ``asks`` a deck
    where no chapter asks for a bless is built all the same: a retro's deck with no finding to decide.
    A ``quoted`` deck holds text it quotes rather than authors (a retro's facts and findings), so the
    warnings build_docs.py ``QUOTED`` names (obs's long-paragraph lint, obs-html's provenance finding of
    an absolute path) refuse nothing there."""
    host = host or default_host(dict(os.environ))
    if host not in HOSTS:
        print(f"deck: --host {host} is none of {', '.join(HOSTS)}", file=sys.stderr)
        return 2
    if not folder.is_dir():
        print(f"deck: {folder} is no folder of decision notes", file=sys.stderr)
        return 2
    if (folder / BUNDLE_FILE).exists():
        print(f"deck: {folder / BUNDLE_FILE} is se's bundle name; rename that file", file=sys.stderr)
        return 1
    obs = obs_dir()
    recorded = ["--answers", str(answers.resolve())] if answers else []
    written = document_path(destination)
    with tempfile.TemporaryDirectory() as scratch:
        vault = Path(scratch) / folder.name
        shutil.copytree(folder, vault, ignore=shutil.ignore_patterns(".*"))
        _screens(vault)
        _settings(vault)
        parsed = Path(scratch) / "document.json"
        allowed = QUOTED if quoted else ()
        code = obs_document(obs, ["--source", str(vault), "--document", str(parsed), *recorded], "deck",
                            adapter=False, allowed=allowed)
        if code:
            return code
        document = json.loads(parsed.read_text(encoding="utf-8"))
        chapters = document["chapters"]
        for warning in _warnings(chapters):
            print(f"deck: warning: {warning}", file=sys.stderr)
        refusal = _refusal(chapters, recorded=answers is not None, asks=asks)
        if refusal:
            destination.unlink(missing_ok=True)
            written.unlink(missing_ok=True)
            print(f"deck: {refusal}", file=sys.stderr)
            return 1
        (vault / BUNDLE_FILE).write_text(_bundle(document, host), encoding="utf-8", newline="\n")
        code = obs_document(obs, [
            "--source", str(vault), "--document", str(parsed), "--destination", str(destination.resolve()),
            "--adapter-option", f"trusted-runtime-bundle={BUNDLE_ID}={BUNDLE_FILE}", *recorded,
        ], "deck", allowed=allowed)
        if code:
            return code
        shutil.copyfile(parsed, written)
    print(f"deck: built {destination}, its Document {written}")
    return 0


def _bundle(document: dict, host: str = "claude-app") -> str:
    """The answers bundle with the deck's own data in front, ``globalThis.seDeck``: the deck's ``title``, its
    ``decisions``, the ids of the chapters with a ``pugh`` fence, and the ``host`` whose adapter takes the
    answers (HOSTS; deck_answers.js reads it)."""
    data = {"title": document["manifest"]["title"],
            "decisions": [chapter["id"] for chapter in document["chapters"] if _holds_pugh(chapter["content"])],
            "host": host}
    # JSON in a script: "<" escaped, so no "</script" or "<!--" ends or changes it.
    text = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f"globalThis.seDeck = Object.freeze({text});\n" + BUNDLE.read_text(encoding="utf-8")


def brief_notice(text: str | None) -> str | None:
    """A deck folder's ``cfg.json`` text with ``artifact.reading.briefNoticeMilliseconds`` set to
    ``BRIEF_NOTICE_MILLISECONDS``; ``None`` (no file) gives a file holding that key alone.

    Every other key is kept, and a value the folder sets itself wins (0 turns the line off for that deck).
    Text that is not JSON, not an object, or holds no object at ``artifact`` or ``artifact.reading`` comes
    back as it is, so obs names what is wrong with it."""
    try:
        config = {} if text is None else json.loads(text)
    except ValueError:
        return text
    if not isinstance(config, dict):
        return text
    artifact = config.setdefault("artifact", {})
    if not isinstance(artifact, dict):
        return text
    reading = artifact.setdefault("reading", {})
    if not isinstance(reading, dict):
        return text
    reading.setdefault("briefNoticeMilliseconds", BRIEF_NOTICE_MILLISECONDS)
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def _settings(vault: Path) -> None:
    """Give the vault copy's ``cfg.json`` the passing line's time (``brief_notice``): obs-document carries
    that file in the Document (``projectConfig``), which is how obs-html's settings reach a deck."""
    path = vault / "cfg.json"
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    merged = brief_notice(text)
    if merged != text:
        path.write_text(merged, encoding="utf-8", newline="\n")


def _screens(vault: Path) -> None:
    """Give the vault's manifest ``obsHtml.layout: screens``, the phone view of one chapter per screen
    (obs-html's spec/input-model.md, Author presentation), unless its frontmatter sets a layout."""
    try:
        name = json.loads((vault / "cfg.json").read_text(encoding="utf-8"))["input"]["manifestFilename"]
    except (OSError, ValueError, KeyError, TypeError):
        name = "manifest.md"
    manifest = vault / name
    if not manifest.is_file():
        return  # obs-document names the missing manifest.
    lines = manifest.read_text(encoding="utf-8").split("\n")
    if lines[0].strip() != "---" or "---" not in (line.strip() for line in lines[1:]):
        lines[:0] = ["---", "obsHtml: {layout: screens}", "---"]
    else:
        end = next(n for n in range(1, len(lines)) if lines[n].strip() == "---")
        start = next((n for n in range(1, end) if re.match(r"obsHtml\s*:", lines[n])), None)
        if start is None:
            lines.insert(end, "obsHtml: {layout: screens}")
        else:
            value = lines[start].split(":", 1)[1].strip()
            if value.startswith("{"):
                if not re.search(r"[{,]\s*layout\s*:", value):
                    empty = value[1:].strip().startswith("}")
                    lines[start] = re.sub(r"\{\s*", "{layout: screens" + ("" if empty else ", "), lines[start], count=1)
            else:
                children = []
                for line in lines[start + 1:end]:
                    if line.strip() and line[:1] not in (" ", "\t"):
                        break
                    if line.strip():
                        children.append(line)
                indent = re.match(r"\s*", children[0]).group() if children else "  "
                if not any(re.match(re.escape(indent) + r"layout\s*:", line) for line in children):
                    lines.insert(start + 1, f"{indent}layout: screens")
    manifest.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _holds_pugh(nodes: list[dict]) -> bool:
    return any(node["type"] == "pugh" or _holds_pugh(node["children"]) for node in nodes)


def _matrices(nodes: list[dict]) -> list[dict]:
    """The matrices of the ``pugh`` fences in ``nodes``, in order."""
    return [matrix for node in nodes for matrix in
            ([node["attrs"]["matrix"]] if node["type"] == "pugh" else _matrices(node["children"]))]


def _warnings(chapters: list[dict]) -> list[str]:
    """Each option that names another (``_cross_names``), each option without ``success`` and each mark off the datum
    without ``because``, what the decision skill asks of the fence (src/skills/decision/SKILL.md), as
    ``<note>, option <letter>: <what is wrong>``."""
    warnings = []
    for chapter in chapters:
        for matrix in _matrices(chapter["content"]):
            warnings.extend(_cross_names(chapter["id"], matrix["candidates"]))
            for index, option in enumerate(matrix["candidates"]):
                where = f"{chapter['id']}, option {chr(ord('A') + index)}"
                if not option.get("success"):
                    warnings.append(f"{where}: no `success`, its success criterion")
                if option["key"] in matrix.get("datum", {}).get("prefer", [])[:1]:
                    continue  # The datum is marked against itself: its marks need no reason.
                warnings.extend(f"{where}: the mark on `{key}` has no `because`, its reason"
                                for key, mark in option.get("marks", {}).items()
                                if not (isinstance(mark, dict) and mark.get("because")))
    return warnings


def _cross_names(chapter: str, candidates: list[dict]) -> list[str]:
    """Each option whose text names another option by its key or short name, as ``<note>, option <letter>: it names
    option <letter> (`<name>`)``: deciding for one already decides against the rest, and only the matrix compares them
    (src/skills/decision/SKILL.md). A text is the option's label, what, wins, losses, success and its marks' reasons; a
    name is matched as a whole word in any case, and one of a single character, which reads as a word, is not."""
    def names(option: dict) -> list[str]:
        found = {}
        for field in ("key", "short"):
            name = str(option.get(field) or "").strip()
            if len(name) > 1:
                found.setdefault(name.casefold(), name)
        return list(found.values())

    def texts(option: dict) -> str:
        reasons = [mark.get("because") for mark in option.get("marks", {}).values() if isinstance(mark, dict)]
        return "\n".join(str(text) for text in [*(option.get(field) for field in ("label", "what", "wins", "losses",
                                                                                     "success")), *reasons] if text)

    warnings = []
    for index, option in enumerate(candidates):
        text = texts(option)
        for other_index, other in enumerate(candidates):
            if other_index == index:
                continue
            named = [name for name in names(other)
                     if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE)]
            if named:
                warnings.append(f"{chapter}, option {chr(ord('A') + index)}: it names option "
                                f"{chr(ord('A') + other_index)} ({', '.join(f'`{name}`' for name in named)}); "
                                "an option says only what it is, the matrix compares them")
    return warnings


DECISION = Path(__file__).resolve().parents[1] / "templates" / "decision.md"


@functools.cache
def sections() -> tuple[str, ...]:
    """The ``##`` sections a decision note writes before its ``pugh`` fence, in order: the headings of
    the decision template's fields listed before its options node (templates/decision.md)."""
    data = templates.note_data(DECISION.read_text(encoding="utf-8"), "templates/decision.md")
    headings = []
    for entry in data["fields"]:
        if entry.get("fence"):
            break
        headings.append(entry["heading"])
    return tuple(headings)


def _named_sections() -> str:
    *first, last = (f"`## {heading}`" for heading in sections())
    return f"{', '.join(first)} and {last}" if first else last


def _explains(content: list[dict]) -> bool:
    """Whether the ``##`` sections before the chapter's first ``pugh`` fence include ``sections()``, in order."""
    headings = []
    for node in content:
        if _holds_pugh([node]):
            break
        if node["type"] == "section" and node["attrs"].get("level") == 2:
            headings.append("".join(child.get("text", "") for child in node["children"]).strip())
    found = iter(headings)
    return all(section in found for section in sections())


def pugh_problems(text: str) -> list[str]:
    """What SE asks of a ``pugh`` fence, the pugh block template's check (templates/pugh.md): ``text`` holds
    one, whose matrix names its ``criteria`` and at least two options under ``candidates``. Everything
    else in the fence is obs's contract, checked at the build (obs's spec/capabilities/pugh-decisions.md)."""
    span = templates._fence_span(text, "pugh")
    if span is None:
        return ["no `pugh` fence: write the options as obs's ```pugh fence"]
    lines = text[span[0]:span[1]].splitlines()[1:]
    if lines and templates.FENCE.match(lines[-1]):
        lines = lines[:-1]
    problems = []
    for key, least in (("criteria", 1), ("candidates", 2)):
        count = _items(lines, key)
        if count is None:
            problems.append(f"the `pugh` fence has no `{key}:`; write its {key}, as the decision skill's fence says")
        elif count < least:
            problems.append(f"the `pugh` fence's `{key}` lists {count}; write at least {least}")
    return problems


def _items(lines: list[str], key: str) -> int | None:
    """How many items the top-level ``key`` of a fence's YAML lists: its ``- `` items at their first
    indent, or the entries of a flow list on its own line; None where the fence has no such key."""
    start = next((index for index, line in enumerate(lines) if re.match(rf"{key}[ \t]*:", line)), None)
    if start is None:
        return None
    flow = lines[start].split(":", 1)[1].strip()
    if flow:
        inner = flow.strip()[1:-1] if flow.startswith("[") and flow.endswith("]") else flow
        depth, count, seen = 0, 0, False
        for char in inner:
            depth += char in "[{"
            depth -= char in "]}"
            if char == "," and depth == 0:
                count, seen = count + seen, False
            elif not char.isspace():
                seen = True
        return count + seen
    count, indent = 0, None
    for line in lines[start + 1:]:
        if line.strip() and not line[:1].isspace() and not line.startswith("- "):
            break
        item = re.match(r"([ \t]*)- ", line)
        if item and indent in (None, len(item.group(1))):
            indent, count = len(item.group(1)), count + 1
    return count


#: Stock openings a chapter that asks the person may not start with (SE#1826, requirement 10): it opens with
#: its current situation in plain technical English. Matched in any case at the start of its first paragraph.
STOCK_OPENINGS = ("this is one case of", "this is one instance of", "this is a case of")


def _text(node: dict) -> str:
    return node.get("text", "") + "".join(_text(child) for child in node.get("children", []))


def _opening(nodes: list[dict]) -> str:
    """The text of the first paragraph in ``nodes``, in document order; "" without one."""
    for node in nodes:
        if node["type"] == "paragraph":
            return " ".join(_text(node).split())
        found = _opening(node.get("children", []))
        if found:
            return found
    return ""


def _refusal(chapters: list[dict], recorded: bool, asks: bool = True) -> str | None:
    """Why the deck's chapters are refused: a decision that asks for no bless, unless the build ``recorded``
    the answers, a decision that does not explain its problem before its options, a chapter asking for a
    bless that opens with a stock phrase (STOCK_OPENINGS), or, where it ``asks``, no chapter that asks."""
    remedy = "give each decision note `obs: {bless: pending}` in its frontmatter"
    decisions = [chapter for chapter in chapters if _holds_pugh(chapter["content"])]
    silent = [chapter["id"] for chapter in decisions if not recorded and "bless" not in chapter]
    if silent:
        return (f"decision(s) {', '.join(silent)} ask for no bless; {remedy}, or build it as a record with "
                "`deck.py answers --record`")
    unexplained = [chapter["id"] for chapter in decisions if not _explains(chapter["content"])]
    if unexplained:
        return (f"decision(s) {', '.join(unexplained)} do not explain the problem before the options; write "
                f"{_named_sections()} before the `pugh` fence, as the decision skill's note shape "
                "(src/skills/decision/SKILL.md) and the decision template (templates/decision.md) say")
    stock = [chapter["id"] for chapter in chapters if "bless" in chapter
             and _opening(chapter["content"]).casefold().startswith(STOCK_OPENINGS)]
    if stock:
        return (f"chapter(s) {', '.join(stock)} open with a stock phrase such as \"This is one case of\"; open with "
                "the current situation in plain technical English, as the decision skill's note shape says")
    if asks and not any("bless" in chapter for chapter in chapters):
        return f"no chapter asks for a bless, so the deck asks the person nothing; {remedy}"
    return None


def serve(artifact: Path, wait: bool, timeout: str | None) -> int:
    """Serve ``artifact`` with obs-html's serve command, from its folder as obs-document --serve runs it,
    installed first where it is missing."""
    adapter, refusal = ready_adapter(obs_dir())
    if adapter is None:
        print(f"deck: {refusal}", file=sys.stderr)
        return 2
    sys.stdout.flush()
    return process_door.run([*adapter["serve"], str(artifact.resolve()), *(["--wait"] if wait else []),
                           *(["--timeout", timeout] if timeout is not None else [])],
                          cwd=adapter["folder"], env=child_environment(), check=False).returncode


def _changes(name: str, change: dict) -> list[str]:
    """One line per kind of change the person made to decision figure ``name``.

    The fields are obs's ``figureChanges``; ``vetoes``, ``lifts`` and ``datum`` as obs v3.2.0's
    answers.schema.json defines them (se reads that schema nowhere as data). A field absent is unchanged."""
    lines = []
    if change.get("weights"):
        lines.append(f"{name} weights: " + ", ".join(f"{key} {value:g}" for key, value in change["weights"].items()))
    for letter, marks in sorted(change.get("marks", {}).items()):
        if marks:
            lines.append(f"{name} marks of {letter}: " + ", ".join(f"{key} {value:+d}" for key, value in marks.items()))
    if change.get("vetoes"):
        lines.append(f"{name} vetoes: " + ", ".join(sorted(change["vetoes"])))
    for letter, lifted in sorted(change.get("lifts", {}).items()):
        if lifted:
            lines.append(f"{name} lifted vetoes of {letter}: " + ", ".join(lifted))
    if change.get("datum"):
        lines.append(f"{name} datum: {change['datum']}")
    for letter, ruling in sorted(change.get("rulings", {}).items()):
        tripwire = f", tripwire: {ruling['tripwire']}" if ruling.get("tripwire") else ""
        lines.append(f"{name} ruling on {letter}: {ruling.get('ruling', 'none')}{tripwire}")
    if change.get("winner"):
        lines.append(f"{name} winner with these changes: {change['winner']}")
    return lines


def summary(payload: object) -> str:
    """What the agent acts on, per decision; ValueError names what is malformed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("verdicts"), list):
        raise ValueError("the payload is no object with a verdicts list (obs's src/obs/answers.schema.json)")
    blocks = []
    for number, verdict in enumerate(payload["verdicts"], 1):
        commented = isinstance(verdict, dict) and isinstance(verdict.get("comment"), str) and verdict["comment"].strip()
        if not isinstance(verdict, dict) or "chapter" not in verdict or not (verdict.get("verdict") or commented):
            raise ValueError(f"verdict {number} has no chapter, or neither a verdict nor a comment")
        # An entry with a comment and no verdict answers nothing: the decision is still open.
        head = f"{verdict['chapter']}: {verdict.get('verdict') or 'comment'}"
        if verdict.get("pick"):
            head += f" {verdict['pick']['option']} (figure {verdict['pick']['figure']})"
        lines = [head]
        if verdict.get("comment"):
            lines.append(f"comment: {verdict['comment']}")
        for name, change in sorted(verdict.get("figures", {}).items()):
            lines.extend(_changes(name, change))
        blocks.append("\n  ".join(lines))
    return "\n".join(blocks) if blocks else "no verdicts"


def answers(path: Path, record: Path | None, destination: Path | None) -> int:
    try:
        text = summary(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:  # json.JSONDecodeError is a ValueError.
        print(f"deck: {path}: {error}", file=sys.stderr)
        return 1
    print(text)
    return build(record, destination, path) if record else 0


#: deck.py's commands in the render component timeline.py names (docs/start.md "Commands as
#: components"); each command's usage and help come from make_parser.
COMPONENTS = (se_components.script("timeline").COMPONENTS[0]._replace(
    commands=("build", "serve", "answers")),)
#: The commands that go through kern where it runs (se_components.routed): none, as build writes,
#: serve waits for the person, and answers is read by the agent, not a person.
INTERACTIVE_COMMANDS: frozenset[str] = frozenset()


def make_parser() -> argparse.ArgumentParser:
    parser = se_script.parser(prog="deck.py", description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[5:]))
    commands = parser.add_subparsers(dest="command", required=True)
    built = commands.add_parser("build", help="build a folder of decision notes into one deck")
    built.add_argument("folder", type=Path)
    built.add_argument("--destination", type=Path, required=True, help="the HTML file to write, outside FOLDER")
    built.add_argument("--host", choices=HOSTS, help="the host the answers go back to (default: the one this runs "
                                                     "under: claude-app in Claude's cloud, claude-code under Claude "
                                                     "Code, copilot under Copilot's hooks, else local)")
    served = commands.add_parser("serve", help="serve a deck locally and print the answers it is sent")
    served.add_argument("artifact", type=Path)
    served.add_argument("--wait", action="store_true", help="exit after the first answers, printing them")
    served.add_argument("--timeout", metavar="S", help="with --wait: fail after S seconds without answers")
    read = commands.add_parser("answers", help="print what the answers ask the agent to act on")
    read.add_argument("answers", type=Path)
    read.add_argument("--record", type=Path, metavar="FOLDER", help="build FOLDER again with the answers")
    read.add_argument("--destination", type=Path, help="with --record: the record's HTML file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    arguments = parser.parse_args(argv)
    words = [arguments.command]
    routed = se_components.routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        arguments.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    if arguments.command == "build":
        return build(arguments.folder, arguments.destination, host=arguments.host)
    if arguments.command == "serve":
        return serve(arguments.artifact, arguments.wait, arguments.timeout)
    if bool(arguments.record) != bool(arguments.destination):
        parser.error("--record and --destination go together")
    return answers(arguments.answers, arguments.record, arguments.destination)


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
