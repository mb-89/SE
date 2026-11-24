#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Input log: the person's own words from session transcripts, word for word, kept on this machine.

It reads transcript files given by hand (or directories searched for `*.jsonl` files) and writes
each of the person's turns as one dated, numbered file that is never edited afterwards, with one
line in an index, under `<repo>/.se/input/`, a folder git ignores. Nothing calls it: no hook, role,
skill or rule runs it; a person runs it when they want their words kept.

The core is pure, data in and data out:

- An adapter turns the lines of one transcript into the person's `Turn`s. `claude_code_turns`
  reads Claude Code's JSONL; another host's format needs only another adapter in `ADAPTERS`.
- The person rule is a deliberate copy of the transcript reader's (the retro's module that counts
  signals): a `user` record that is not `isMeta`, not `promptSource: system`, of an origin kind
  `human`, `user` or none, whose text does not open with `<`. Neither module names the other while
  nothing calls them; tests/test_input_log.py holds the two to the same lines.
  - Beyond it: compaction records (`isCompactSummary`, `isVisibleInTranscriptOnly`), sub-agent
    prompts (`isSidechain`) and the interrupt markers (`INTERRUPTS`) are no words of the person;
    a message typed while the agent worked (a `queued_command` attachment in `prompt` mode, of an
    origin kind `human` or none) is.
- `plan` takes the turns and the index as written so far and gives the new files (name and
  bytes), the image files beside them (only with `images`) and the index lines to append. A turn
  whose id the index holds already gives nothing, so a run never rewrites what an earlier one kept.

The thin wiring, `main`, reads the transcripts and the index, asks git through its door whether the
folder is ignored (`check-ignore`; not a checkout counts as ignored), writes only new files and
appends only to the index, and prints the count of new files and the folder. No turn's text reaches
stdout or stderr.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import se_script

sys.path.insert(0, str(Path(__file__).resolve().parent))

import git_door  # noqa: E402  (the one door to git, beside this module)

FOLDER = (".se", "input")  # the log's folder, relative to the repository
INDEX = "index.md"
FIRST_LINE = 80  # the index keeps at most this many characters of a turn's first line
INTERRUPTS = ("[Request interrupted by user]", "[Request interrupted by user for tool use]")
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/gif": "gif",
              "image/webp": "webp"}
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-(\d{4,})\.md$")


@dataclass(frozen=True)
class Image:
    """One image part of a turn: its media type and its base64 data, as recorded."""

    media_type: str
    data: str


@dataclass(frozen=True)
class Turn:
    """One of the person's turns, as an adapter read it from a transcript."""

    id: str  # the record's uuid, else `<transcript>:<line>`
    transcript: str  # the transcript file's basename, never a path
    line: int  # 1-based line in that file
    time: datetime | None  # UTC; a turn without one is not written
    parts: tuple[str | Image, ...]  # text and image parts, in order
    queued: bool = False  # typed while the agent worked


# The adapter: Claude Code's transcript JSONL.


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _origin_kind(*holders: dict) -> object:
    for holder in holders:
        origin = holder.get("origin")
        if isinstance(origin, dict):
            return origin.get("kind")
    return None


def _parts(content: object) -> tuple[str | Image, ...]:
    """The person's text and image parts of a content (a string or a list of parts); tool results,
    text that opens with `<` and the interrupt markers are dropped."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return ()
    parts: list[str | Image] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            text = part["text"]
            if not text.lstrip().startswith("<") and text not in INTERRUPTS:
                parts.append(text)
        elif part.get("type") == "image" and isinstance(part.get("source"), dict):
            source = part["source"]
            if isinstance(source.get("data"), str):
                parts.append(Image(str(source.get("media_type", "")), source["data"]))
    return tuple(parts)


def _claude_code_turn(record: dict, transcript: str, line: int) -> Turn | None:
    if record.get("isMeta") or record.get("isSidechain") is True or record.get("isCompactSummary") \
            or record.get("isVisibleInTranscriptOnly"):
        return None
    queued = False
    if record.get("type") == "user":
        if record.get("promptSource") == "system" or _origin_kind(record) not in (None, "human", "user"):
            return None
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
    elif record.get("type") == "attachment":
        attachment = record.get("attachment")
        if not isinstance(attachment, dict) or attachment.get("type") != "queued_command" \
                or attachment.get("commandMode") != "prompt" \
                or _origin_kind(attachment, record) not in (None, "human"):
            return None
        content, queued = attachment.get("prompt"), True
    else:
        return None
    parts = _parts(content)
    if not parts:
        return None
    uuid = record.get("uuid")
    return Turn(uuid if isinstance(uuid, str) and uuid else f"{transcript}:{line}", transcript, line,
                _time(record.get("timestamp")), parts, queued)


def claude_code_turns(lines: Iterable[str], transcript: str) -> list[Turn]:
    """The person's turns of one Claude Code transcript, its lines given in order; a line that is
    not a JSON object gives nothing. `queue-operation` lines are not read, so a message typed while
    the agent worked gives one turn, from its `queued_command` attachment."""
    turns = []
    for number, raw in enumerate(lines, 1):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        turn = _claude_code_turn(record, transcript, number) if isinstance(record, dict) else None
        if turn is not None:
            turns.append(turn)
    return turns


ADAPTERS: dict[str, Callable[[Iterable[str], str], list[Turn]]] = {"claude-code": claude_code_turns}


# The plan: turns and the index in, new files and index lines out.


@dataclass(frozen=True)
class Plan:
    files: tuple[tuple[str, bytes], ...]  # (name, bytes), in writing order; images beside their turn
    index: bytes  # what is appended to the index


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def index_entries(index: str) -> tuple[set[str], int]:
    """The ids the index holds and the highest number of its file names (0 for none)."""
    ids, highest = set(), 0
    for line in index.split("\n"):
        fields = line.split(" | ", 3)
        if len(fields) < 3:
            continue
        ids.add(fields[2])
        match = NAME.match(fields[0])
        if match:
            highest = max(highest, int(match.group(1)))
    return ids, highest


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def one_line(text: str) -> str:
    """An id as the index writes it: on one line."""
    return " ".join(_lf(text).split("\n"))


def extension(media_type: str) -> str:
    return EXTENSIONS.get(media_type.lower(), "bin")


def render(turn: Turn) -> str:
    """A turn's file text: its header line, a blank line, then its parts joined by newlines."""
    said = f"Said {stamp(turn.time)} in {turn.transcript}, line {turn.line}"
    if turn.queued:
        said += ", typed while the agent worked"
    lines, k = [], 0
    for part in turn.parts:
        if isinstance(part, str):
            lines.append(_lf(part))
        else:
            k += 1
            lines.append(f"[image {k}]")
    body = "\n".join(lines)
    return f"{said}\n\n{body}\n"


def _decoded(image: Image) -> bytes | None:
    try:
        return base64.b64decode(image.data, validate=False)
    except (binascii.Error, ValueError):
        return None


def plan(turns: Iterable[Turn], index: str, images: bool = False) -> Plan:
    """The files and index lines the new turns give: in order of time, transcript, then line; a
    turn without a time, or whose id the index (or an earlier turn) holds, gives nothing."""
    seen, highest = index_entries(index)
    files: list[tuple[str, bytes]] = []
    lines: list[str] = []
    for turn in sorted((t for t in turns if t.time is not None),
                       key=lambda t: (t.time, t.transcript, t.line)):
        key = one_line(turn.id)
        if key in seen:
            continue
        seen.add(key)
        highest += 1
        stem = f"{turn.time.astimezone(timezone.utc):%Y-%m-%d}-{highest:04d}"
        text = render(turn)
        files.append((f"{stem}.md", text.encode("utf-8")))
        if images:
            pictures = [part for part in turn.parts if isinstance(part, Image)]
            for k, image in enumerate(pictures, 1):
                data = _decoded(image)
                if data is not None:
                    files.append((f"{stem}-{k}.{extension(image.media_type)}", data))
        first = text.split("\n\n", 1)[1].split("\n", 1)[0][:FIRST_LINE]
        lines.append(f"{stem}.md | {stamp(turn.time)} | {key} | {first}\n")
    lead = "\n" if lines and index and not index.endswith("\n") else ""
    return Plan(tuple(files), (lead + "".join(lines)).encode("utf-8"))


# The wiring: transcripts and the index in, new files out.


def make_parser() -> argparse.ArgumentParser:
    parser = se_script.parser(
        prog="input_log.py",
        description="Keep the person's own words from session transcripts: each of their turns as "
                    "one new numbered file with one index line, under <repo>/.se/input/ (ignored "
                    "by git). Never rewrites a file; prints only the count of new files.")
    parser.add_argument("paths", nargs="+", type=Path,
                        help="transcript files, or directories searched for *.jsonl files")
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="the repository whose .se/input/ is written (default: the working "
                             "directory)")
    parser.add_argument("--images", action="store_true",
                        help="also write each image part beside its turn's file")
    parser.add_argument("--adapter", choices=sorted(ADAPTERS), default="claude-code",
                        help="the transcript format (default: claude-code)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    adapter = ADAPTERS[args.adapter]
    turns: list[Turn] = []
    for given in args.paths:
        files = sorted(given.rglob("*.jsonl")) if given.is_dir() else [given]
        for path in files:
            if not path.is_file():
                print(f"error: no transcript at {path.name}", file=sys.stderr)
                return 2
            lines = [line.removesuffix("\r") for line in
                     path.read_bytes().decode("utf-8", "replace").split("\n")]
            turns.extend(adapter(lines, path.name))
    folder = args.repo.joinpath(*FOLDER)
    where = "/".join(FOLDER)
    ignored = git_door.run("check-ignore", "-q", f"{where}/{INDEX}", root=args.repo).returncode
    if ignored not in (0, 128):
        print(f"error: git does not ignore {where}/; nothing written", file=sys.stderr)
        return 1
    index_path = folder / INDEX
    index = index_path.read_bytes().decode("utf-8", "replace") if index_path.is_file() else ""
    result = plan(turns, index, args.images)
    taken = [name for name, _ in result.files if (folder / name).exists()]
    if taken:
        print(f"error: {where}/{taken[0]} exists already; nothing written", file=sys.stderr)
        return 1
    if result.files:
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in result.files:
            with (folder / name).open("xb") as handle:
                handle.write(data)
        with index_path.open("ab") as handle:
            handle.write(result.index)
    count = sum(1 for name, _ in result.files if name.endswith(".md"))
    print(f"input log: {count} new file{'s' if count != 1 else ''} in {where}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
