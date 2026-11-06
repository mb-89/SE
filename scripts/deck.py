"""Bring decisions to the person as one deck: build it with obs, serve it locally and read its answers.

Reader: the agent that asks the person for decisions, and whoever changes this command. The decision
skill (src/skills/decision/SKILL.md) says when to use it; this file owns what each subcommand does.

  build FOLDER --destination HTML   FOLDER holds the decision notes and their manifest (obs's
      `manifest.md`, or what the folder's cfg.json names). obs builds them into one HTML artifact in one
      call, with se's answers bundle (scripts/deck_answers.js) as its trusted runtime bundle, in obs's
      screens layout (one chapter per phone screen) unless the manifest sets `obsHtml.layout`. A chapter
      asks for a bless (`obs: {bless: pending}`) or is a record: what was decided without the person, or
      their tasks. It fails on a deck where no chapter asks, on a decision (a `pugh` fence) that does
      not ask, outside a record built with the answers, on a decision without `## Current situation`
      and `## The problem`, in that order, before its fence (the decision skill's note shape), and on
      any obs warning. It warns, building all the same, of each option without `success` and each
      mark off the datum without `because` (the decision skill's fence fields), naming the note and the option.
  serve HTML --wait [--timeout S]   Serves the deck with obs-html serve: prints the URL to open first,
      then, once the person sends, the answers payload as one JSON line (also written to answers.json
      beside HTML). For Claude Code, Copilot and any local browser.
  answers ANSWERS [--record FOLDER --destination HTML]   Prints, per decision, what to act on: the
      verdict, the picked option, the comment and the weights, marks and rulings the person changed.
      With --record it also builds FOLDER again with the answers (obs-document --answers): that
      artifact is the decision's record.

The answers payload's fields are owned by obs's src/obs/answers.schema.json. Exit code 0: done;
1: the build failed, obs warned, no chapter or no decision asks for a bless, or the answers are
malformed, or a decision does not explain its problem before its options; 2: setup error, or no answers within --timeout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_docs import child_environment, obs_dir, obs_document  # noqa: E402

BUNDLE = Path(__file__).resolve().with_name("deck_answers.js")
BUNDLE_ID = "se-answers"  # The id deck_answers.js registers with.
BUNDLE_FILE = f"{BUNDLE_ID}.js"


def build(folder: Path, destination: Path, answers: Path | None = None) -> int:
    """Build ``folder`` into ``destination`` with the answers bundle; with ``answers``, the record."""
    if not folder.is_dir():
        print(f"deck: {folder} is no folder of decision notes", file=sys.stderr)
        return 2
    if (folder / BUNDLE_FILE).exists():
        print(f"deck: {folder / BUNDLE_FILE} is se's bundle name; rename that file", file=sys.stderr)
        return 1
    obs = obs_dir()
    with tempfile.TemporaryDirectory() as scratch:
        vault = Path(scratch) / folder.name
        shutil.copytree(folder, vault, ignore=shutil.ignore_patterns(".*"))
        shutil.copyfile(BUNDLE, vault / BUNDLE_FILE)
        _screens(vault)
        document = Path(scratch) / "document.json"
        code = obs_document(obs, [
            "--source", str(vault), "--document", str(document), "--destination", str(destination.resolve()),
            "--adapter-option", f"trusted-runtime-bundle={BUNDLE_ID}={BUNDLE_FILE}",
            *(["--answers", str(answers.resolve())] if answers else []),
        ], "deck")
        if code:
            return code
        chapters = json.loads(document.read_text(encoding="utf-8"))["chapters"]
    for warning in _warnings(chapters):
        print(f"deck: warning: {warning}", file=sys.stderr)
    refusal = _refusal(chapters, recorded=answers is not None)
    if refusal:
        destination.unlink(missing_ok=True)
        print(f"deck: {refusal}", file=sys.stderr)
        return 1
    print(f"deck: built {destination}")
    return 0


def _screens(vault: Path) -> None:
    """Give the vault's manifest ``obsHtml.layout: screens``, the phone view of one chapter per screen (obs's
    adapters/html/spec/input-model.md, Author presentation), unless its frontmatter sets a layout."""
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
    manifest.write_text("\n".join(lines), encoding="utf-8")


def _holds_pugh(nodes: list[dict]) -> bool:
    return any(node["type"] == "pugh" or _holds_pugh(node["children"]) for node in nodes)


def _matrices(nodes: list[dict]) -> list[dict]:
    """The matrices of the ``pugh`` fences in ``nodes``, in order."""
    return [matrix for node in nodes for matrix in
            ([node["attrs"]["matrix"]] if node["type"] == "pugh" else _matrices(node["children"]))]


def _warnings(chapters: list[dict]) -> list[str]:
    """Each option without ``success`` and each mark off the datum without ``because``, the fields the decision skill asks
    of the fence (src/skills/decision/SKILL.md), as ``<note>, option <letter>: <what is missing>``."""
    warnings = []
    for chapter in chapters:
        for matrix in _matrices(chapter["content"]):
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


SECTIONS = ["Current situation", "The problem"]  # The decision skill's note shape, before the fence.


def _explains(content: list[dict]) -> bool:
    """Whether the ``##`` sections before the chapter's first ``pugh`` fence include SECTIONS, in order."""
    headings = []
    for node in content:
        if _holds_pugh([node]):
            break
        if node["type"] == "section" and node["attrs"].get("level") == 2:
            headings.append("".join(child.get("text", "") for child in node["children"]).strip())
    found = iter(headings)
    return all(section in found for section in SECTIONS)


def _refusal(chapters: list[dict], recorded: bool) -> str | None:
    """Why the deck's chapters are refused: a decision that asks for no bless, unless the build ``recorded``
    the answers, a decision that does not explain its problem before its options, or no chapter that asks."""
    remedy = "give each decision note `obs: {bless: pending}` in its frontmatter"
    decisions = [chapter for chapter in chapters if _holds_pugh(chapter["content"])]
    silent = [chapter["id"] for chapter in decisions if not recorded and "bless" not in chapter]
    if silent:
        return (f"decision(s) {', '.join(silent)} ask for no bless; {remedy}, or build it as a record with "
                "`deck.py answers --record`")
    unexplained = [chapter["id"] for chapter in decisions if not _explains(chapter["content"])]
    if unexplained:
        return (f"decision(s) {', '.join(unexplained)} do not explain the problem before the options; write "
                "`## Current situation` and `## The problem` before the `pugh` fence, as the decision skill's "
                "note shape (src/skills/decision/SKILL.md) says")
    if not any("bless" in chapter for chapter in chapters):
        return f"no chapter asks for a bless, so the deck asks the person nothing; {remedy}"
    return None


def serve(artifact: Path, wait: bool, timeout: str | None) -> int:
    """Serve ``artifact`` with the html adapter's serve command, from obs as obs-document --serve runs it."""
    obs = obs_dir()
    adapters = json.loads((obs / "adapters.json").read_text(encoding="utf-8"))["adapters"]
    command = json.loads((obs / adapters["html"]).read_text(encoding="utf-8"))["serve"]
    sys.stdout.flush()
    return subprocess.run([*command, str(artifact.resolve()), *(["--wait"] if wait else []),
                           *(["--timeout", timeout] if timeout is not None else [])],
                          cwd=obs, env=child_environment(), check=False).returncode


def _changes(name: str, change: dict) -> list[str]:
    """One line per kind of change the person made to decision figure ``name``."""
    lines = []
    if change.get("weights"):
        lines.append(f"{name} weights: " + ", ".join(f"{key} {value:g}" for key, value in change["weights"].items()))
    for letter, marks in sorted(change.get("marks", {}).items()):
        if marks:
            lines.append(f"{name} marks of {letter}: " + ", ".join(f"{key} {value:+d}" for key, value in marks.items()))
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
        if not isinstance(verdict, dict) or not {"chapter", "verdict"} <= verdict.keys():
            raise ValueError(f"verdict {number} has no chapter and verdict")
        head = f"{verdict['chapter']}: {verdict['verdict']}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deck.py", description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[5:]))
    commands = parser.add_subparsers(dest="command", required=True)
    built = commands.add_parser("build", help="build a folder of decision notes into one deck")
    built.add_argument("folder", type=Path)
    built.add_argument("--destination", type=Path, required=True, help="the HTML file to write, outside FOLDER")
    served = commands.add_parser("serve", help="serve a deck locally and print the answers it is sent")
    served.add_argument("artifact", type=Path)
    served.add_argument("--wait", action="store_true", help="exit after the first answers, printing them")
    served.add_argument("--timeout", metavar="S", help="with --wait: fail after S seconds without answers")
    read = commands.add_parser("answers", help="print what the answers ask the agent to act on")
    read.add_argument("answers", type=Path)
    read.add_argument("--record", type=Path, metavar="FOLDER", help="build FOLDER again with the answers")
    read.add_argument("--destination", type=Path, help="with --record: the record's HTML file")
    arguments = parser.parse_args(argv)
    if arguments.command == "build":
        return build(arguments.folder, arguments.destination)
    if arguments.command == "serve":
        return serve(arguments.artifact, arguments.wait, arguments.timeout)
    if bool(arguments.record) != bool(arguments.destination):
        parser.error("--record and --destination go together")
    return answers(arguments.answers, arguments.record, arguments.destination)


if __name__ == "__main__":
    sys.exit(main())
