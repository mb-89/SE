"""Bring decisions to the person as one deck: build it with obs, serve it locally and read its answers.

Reader: the agent that asks the person for decisions, and whoever changes this command. The decision
skill (src/skills/decision/SKILL.md) says when to use it; this file owns what each subcommand does.

  build FOLDER --destination HTML   FOLDER holds the decision notes and their manifest (obs's
      `manifest.md`, or what the folder's cfg.json names). obs builds them into one HTML artifact in one
      call, with se's answers bundle (scripts/deck_answers.js) as its trusted runtime bundle. A chapter
      asks for a bless (`obs: {bless: pending}`) or is a record: what was decided without the person, or
      their tasks. It fails on a deck where no chapter asks, on a decision (a `pugh` fence) that does
      not ask, outside a record built with the answers, and on any obs warning.
  serve HTML --wait [--timeout S]   Serves the deck with obs-html serve: prints the URL to open first,
      then, once the person sends, the answers payload as one JSON line (also written to answers.json
      beside HTML). For Claude Code, Copilot and any local browser.
  answers ANSWERS [--record FOLDER --destination HTML]   Prints, per decision, what to act on: the
      verdict, the picked option, the comment and the weights, marks and rulings the person changed.
      With --record it also builds FOLDER again with the answers (obs-document --answers): that
      artifact is the decision's record.

The answers payload's fields are owned by obs's src/obs/answers.schema.json. Exit code 0: done;
1: the build failed, obs warned, no chapter or no decision asks for a bless, or the answers are
malformed; 2: setup error, or no answers within --timeout.
"""

from __future__ import annotations

import argparse
import json
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
        document = Path(scratch) / "document.json"
        code = obs_document(obs, [
            "--source", str(vault), "--document", str(document), "--destination", str(destination.resolve()),
            "--adapter-option", f"trusted-runtime-bundle={BUNDLE_ID}={BUNDLE_FILE}",
            *(["--answers", str(answers.resolve())] if answers else []),
        ], "deck")
        if code:
            return code
        chapters = json.loads(document.read_text(encoding="utf-8"))["chapters"]
    refusal = _refusal(chapters, recorded=answers is not None)
    if refusal:
        destination.unlink(missing_ok=True)
        print(f"deck: {refusal}", file=sys.stderr)
        return 1
    print(f"deck: built {destination}")
    return 0


def _holds_pugh(nodes: list[dict]) -> bool:
    return any(node["type"] == "pugh" or _holds_pugh(node["children"]) for node in nodes)


def _refusal(chapters: list[dict], recorded: bool) -> str | None:
    """Why the deck's chapters are refused: a decision that asks for no bless, unless the build ``recorded``
    the answers, or no chapter that asks."""
    remedy = "give each decision note `obs: {bless: pending}` in its frontmatter"
    silent = [chapter["id"] for chapter in chapters if not recorded and "bless" not in chapter
              and _holds_pugh(chapter["content"])]
    if silent:
        return (f"decision(s) {', '.join(silent)} ask for no bless; {remedy}, or build it as a record with "
                "`deck.py answers --record`")
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
