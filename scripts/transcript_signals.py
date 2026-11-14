"""Transcript signals: counts of what sessions actually did, read from their transcripts, for a
retro to rate on request. It draws no conclusions, files nothing and is called by nothing.

The core is pure, data in and data out:

- An adapter turns one transcript line into plain `Event`s (who, kind, tool, text, time).
  `claude_code_events` reads Claude Code's JSONL; another host's format needs only another adapter
  in `ADAPTERS`.
- Each signal is one small function, events in and `Hit`s out; `SIGNALS` lists them, so one is
  added or dropped there alone.
- `tally` counts the hits per signal, per session and in total, with up to `LOCATIONS` locations
  (file and line) each; `render_text` and `render_json` print it.

Privacy: the output names signals, counts, file labels (relative to the directory read, or the
file's name), line numbers and tool names. Its one quotation is a command's shape (`command_shape`),
which keeps the program, its leading subcommand words, option names and paths inside the
repository, and masks every other argument as `<arg>`. Message text, names, outside paths, tokens
and addresses never reach it.

The thin wiring, `main`, reads the files and passes their lines through the core.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shlex
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

LOCATIONS = 5  # the locations shown per signal
WAIT_SECONDS = 120.0  # a gap over it between a tool call and its result is a long wait
SHAPE_REPEATS = 3  # a command shape used this often stands in for a missing command
CORRECTION_WORDS = 12  # a person's turn of at most this many words can be a correction
SCRIPT_SIMILARITY = 0.9  # two scripts at least this similar are the same script
SCRIPT_LINES = 5  # a script shorter than this is too small to compare
SCRIPT_SUFFIXES = (".py", ".sh", ".ps1", ".js", ".ts", ".go", ".rb", ".pl")
SHELL_TOOLS = ("Bash", "PowerShell", "execute", "run_in_terminal")
WRITE_TOOLS = ("Write", "create_file", "edit")

# A short turn that undoes or redirects: English and German markers, a word list to tune later.
CORRECTION = re.compile(
    r"(?i)^\s*(no|nope|nein|stop|stopp|wait|halt|don'?t|do not|nicht|undo|revert|rückgängig|"
    r"wrong|falsch|not (that|this|like)|instead|actually|eigentlich|rather|lieber)\b"
    r"|\b(instead|revert|undo|rückgängig|wrong|falsch|not what i)\b"
    r"|^\[request interrupted by user")
DENIAL = re.compile(
    r"(?i)doesn'?t want to proceed|tool use was rejected|permission to use .* (has been )?denied"
    r"|denied by|blocked by (a |the )?(hook|policy|rule)|not allowed")
DENIED_DECISIONS = ("deny", "denied", "reject", "rejected", "block", "blocked")


@dataclass(frozen=True)
class Event:
    """One thing that happened in a session, as an adapter read it from one transcript line."""

    file: str  # the transcript's label: relative to the directory read, or its name
    line: int  # 1-based line in that file
    who: str  # person, agent, tool or system
    kind: str  # message, tool_call or tool_result
    tool: str = ""  # the tool called, or whose result this is
    text: str = ""  # a message's text, a tool call's main argument, a result's text
    time: datetime | None = None
    call: str = ""  # the id tying a tool call to its result
    arguments: dict = field(default_factory=dict, compare=False, hash=False)
    error: bool = False  # the result is an error
    denied: bool = False  # the call was refused or denied


@dataclass(frozen=True)
class Hit:
    """One occurrence of a signal: where, and an optional key it is counted by (a tool, a shape)."""

    file: str
    line: int
    key: str = ""


# The adapter: Claude Code's transcript JSONL.


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(part.get("text", part.get("content", "")))
                         for part in content if isinstance(part, dict))
    return ""


def _main_argument(tool: str, arguments: dict) -> str:
    for key in ("command", "file_path", "path", "pattern", "query", "url"):
        if isinstance(arguments.get(key), str):
            return arguments[key]
    return ""


def _is_system_turn(record: dict, text: str) -> bool:
    origin = record.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return bool(record.get("isMeta") or record.get("promptSource") == "system"
                or (kind not in (None, "human", "user")) or text.lstrip().startswith("<"))


def claude_code_events(raw: str, file: str, line: int) -> list[Event]:
    """The events of one line of a Claude Code transcript; a line that is no event gives none."""
    try:
        record = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(record, dict) or record.get("type") not in ("user", "assistant"):
        return []
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    time = _time(record.get("timestamp"))
    content = message.get("content")
    decision = record.get("permissionDecision")
    decision = decision.get("decision", "") if isinstance(decision, dict) else decision or ""
    refused = str(decision).lower() in DENIED_DECISIONS
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    events = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "tool_use":
            arguments = part.get("input") if isinstance(part.get("input"), dict) else {}
            tool = str(part.get("name", ""))
            events.append(Event(file, line, "agent", "tool_call", tool,
                                _main_argument(tool, arguments), time, str(part.get("id", "")),
                                arguments))
        elif kind == "tool_result":
            text = _text_of(part.get("content"))
            error = bool(part.get("is_error"))
            denied = refused or (error and bool(DENIAL.search(text)))
            events.append(Event(file, line, "tool", "tool_result", "", text, time,
                                str(part.get("tool_use_id", "")), error=error, denied=denied))
        elif kind == "text" and message.get("role") == "assistant":
            events.append(Event(file, line, "agent", "message", text=str(part.get("text", "")),
                                time=time))
        elif kind == "text":
            text = str(part.get("text", ""))
            who = "system" if _is_system_turn(record, text) else "person"
            events.append(Event(file, line, who, "message", text=text, time=time))
    return events


ADAPTERS: dict[str, Callable[[str, str, int], list[Event]]] = {"claude-code": claude_code_events}


def read_events(lines: Iterable[str], file: str, adapter: str = "claude-code") -> list[Event]:
    """Every event of one transcript, its lines given in order; tool results get their tool."""
    read = ADAPTERS[adapter]
    events = [event for number, raw in enumerate(lines, 1) for event in read(raw, file, number)]
    tools = {event.call: event.tool for event in events if event.kind == "tool_call"}
    return [Event(e.file, e.line, e.who, e.kind, tools.get(e.call, e.tool), e.text, e.time, e.call,
                  e.arguments, e.error, e.denied) if e.kind == "tool_result" else e
            for e in events]


# The command shape: what a shell command may show of itself.


_WORD = re.compile(r"^[a-z][a-z-]{0,23}$")  # a subcommand word: no digits, no underscores
_PROGRAM = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,31}$")
_ENV = re.compile(r"^([A-Z_][A-Z0-9_]{0,31})=")
_OPTION = re.compile(r"^(--?[A-Za-z][A-Za-z0-9-]{0,31})(=.*)?$")


def _operator(token: str) -> bool:
    """A shell operator: a pipe, a list separator or a redirection (`2>`, `2>&1` among them)."""
    return token in ("2>", "2>&1") or set(token) <= set("|&;<>")


def _segments(command: str) -> list[list[str]]:
    first = command.strip().splitlines()[0] if command.strip() else ""
    try:
        lexer = shlex.shlex(first, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = first.split()
    segments, current = [], []
    for token in tokens:
        if _operator(token):
            segments.append(current)
            segments.append([token])
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [segment for segment in segments if segment]


def _shape_segment(tokens: list[str], keep_path: Callable[[str], bool]) -> list[str]:
    shaped, leading = [], True
    for index, token in enumerate(tokens):
        env = _ENV.match(token)
        if env and not shaped:
            shaped.append(f"{env.group(1)}=<arg>")
            continue
        if not shaped or (shaped and all(s.endswith("=<arg>") for s in shaped)):
            name = PurePosixPath(token.replace("\\", "/")).name
            shaped.append(name if _PROGRAM.match(name) else "<arg>")
            continue
        option = _OPTION.match(token)
        if option:
            shaped.append(option.group(1) + ("=<arg>" if option.group(2) else ""))
            leading = False
        elif keep_path(token):
            shaped.append(token)
        elif leading and _WORD.match(token):
            shaped.append(token)
        else:
            shaped.append("<arg>")
            leading = False
    collapsed: list[str] = []
    for token in shaped:
        if not (token == "<arg>" and collapsed and collapsed[-1] == "<arg>"):
            collapsed.append(token)
    return collapsed


def command_shape(command: str, keep_path: Callable[[str], bool] = lambda token: False) -> str:
    """A shell command with its arguments masked: the program's name, its leading subcommand words,
    option names and the paths `keep_path` accepts (the repository's own) stay, all else is
    `<arg>`. A leading `cd <dir> &&` is dropped; only the first line counts."""
    segments = _segments(command)
    while len(segments) >= 2 and segments[0][0] == "cd" and segments[1] in (["&&"], [";"]):
        segments = segments[2:]
    parts: list[str] = []
    for segment in segments:
        if len(segment) == 1 and _operator(segment[0]):
            parts.append(segment[0])
        elif parts and parts[-1].lstrip("2") and set(parts[-1].lstrip("2")) <= set("<>"):
            parts.append("<arg>")  # a redirection's file, never a program
        else:
            parts.append(" ".join(_shape_segment(segment, keep_path)))
    return " ".join(parts)


# The signals: events in, hits out. Each takes every event of every session read.


def _by_file(events: Iterable[Event]) -> dict[str, list[Event]]:
    sessions: dict[str, list[Event]] = {}
    for event in events:
        sessions.setdefault(event.file, []).append(event)
    return sessions


def corrections(events: list[Event], words: int = CORRECTION_WORDS) -> list[Hit]:
    """The person corrects the agent: a short turn right after an agent action that undoes or
    redirects it."""
    hits = []
    for session in _by_file(events).values():
        acted = False
        for event in session:
            if event.who == "system":
                continue
            if event.who == "person":
                if acted and len(event.text.split()) <= words and CORRECTION.search(event.text):
                    hits.append(Hit(event.file, event.line))
                acted = False
            elif event.kind in ("tool_call", "tool_result"):
                acted = True
    return hits


def _same_call(call: Event) -> str:
    return call.tool + json.dumps(call.arguments, sort_keys=True, default=str)


def retries(events: list[Event]) -> list[Hit]:
    """The same tool call repeated after it failed (a refusal is no failure: see `denials`)."""
    hits = []
    for session in _by_file(events).values():
        calls = {event.call: event for event in session if event.kind == "tool_call"}
        failed: set[str] = set()
        for event in session:
            if event.kind == "tool_result" and event.error and not event.denied:
                if event.call in calls:
                    failed.add(_same_call(calls[event.call]))
            elif event.kind == "tool_call" and _same_call(event) in failed:
                hits.append(Hit(event.file, event.line, event.tool))
                failed.discard(_same_call(event))
    return hits


def repeated_commands(events: list[Event], repeats: int = SHAPE_REPEATS,
                      keep_path: Callable[[str], bool] = lambda token: False) -> list[Hit]:
    """A shell command standing in for a missing command: one command shape used `repeats` or more
    times across the sessions read. Each use is a hit, keyed by the shape."""
    uses: dict[str, list[Event]] = {}
    for event in events:
        if event.kind == "tool_call" and event.tool in SHELL_TOOLS and event.text.strip():
            uses.setdefault(command_shape(event.text, keep_path), []).append(event)
    return [Hit(event.file, event.line, shape)
            for shape, shaped in uses.items() if len(shaped) >= repeats for event in shaped]


def _script(event: Event) -> str | None:
    path = str(event.arguments.get("file_path", event.arguments.get("path", "")))
    content = event.arguments.get("content")
    if not isinstance(content, str) or not path.lower().endswith(SCRIPT_SUFFIXES):
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return "\n".join(lines) if len(lines) >= SCRIPT_LINES else None


def scripts_written_twice(events: list[Event],
                          similarity: float = SCRIPT_SIMILARITY) -> list[Hit]:
    """A script written twice: a file write near-identical to one an earlier session wrote."""
    written: list[tuple[str, str]] = []
    hits = []
    for event in events:
        if event.kind != "tool_call" or event.tool not in WRITE_TOOLS:
            continue
        script = _script(event)
        if script is None:
            continue
        if any(file != event.file
               and difflib.SequenceMatcher(None, earlier, script, autojunk=False).ratio()
               >= similarity for file, earlier in written):
            hits.append(Hit(event.file, event.line))
        written.append((event.file, script))
    return hits


def denials(events: list[Event]) -> list[Hit]:
    """Refused or denied tool calls, keyed by tool."""
    return [Hit(event.file, event.line, event.tool or "?")
            for event in events if event.kind == "tool_result" and event.denied]


def long_waits(events: list[Event], seconds: float = WAIT_SECONDS) -> list[Hit]:
    """A gap over `seconds` between a tool call and its result, at the call, keyed by tool."""
    calls = {(event.file, event.call): event for event in events
             if event.kind == "tool_call" and event.call and event.time}
    hits = []
    for event in events:
        call = calls.get((event.file, event.call)) if event.kind == "tool_result" else None
        if call and event.time and (event.time - call.time).total_seconds() > seconds:
            hits.append(Hit(call.file, call.line, call.tool))
    return hits


SIGNALS: dict[str, Callable[..., list[Hit]]] = {
    "corrections": corrections,
    "retries": retries,
    "repeated-commands": repeated_commands,
    "scripts-written-twice": scripts_written_twice,
    "denials": denials,
    "long-waits": long_waits,
}


# The tally and its renderings.


def tally(events: list[Event], files: list[str], options: dict | None = None) -> dict:
    """Counts per signal, per session (file) and in total, with up to `LOCATIONS` locations and,
    where a signal keys its hits, the count per key. `options` maps a signal to its keyword
    arguments."""
    options = options or {}
    result = {"files": len(files), "events": len(events), "signals": {}}
    for name, signal in SIGNALS.items():
        hits = sorted(signal(events, **options.get(name, {})),
                      key=lambda hit: (hit.file, hit.line))
        sessions = {file: 0 for file in files}
        by: dict[str, int] = {}
        for hit in hits:
            sessions[hit.file] = sessions.get(hit.file, 0) + 1
            if hit.key:
                by[hit.key] = by.get(hit.key, 0) + 1
        result["signals"][name] = {
            "total": len(hits),
            "sessions": sessions,
            "locations": [{"file": hit.file, "line": hit.line} for hit in hits[:LOCATIONS]],
            "by": dict(sorted(by.items(), key=lambda item: (-item[1], item[0]))),
        }
    return result


def render_json(result: dict) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)


def render_text(result: dict) -> str:
    lines = [f"transcript signals: {result['files']} transcript(s), {result['events']} events"]
    for name, signal in result["signals"].items():
        lines.append(f"{name}: {signal['total']}")
        for file, count in signal["sessions"].items():
            if count:
                lines.append(f"  {file}: {count}")
        if signal["locations"]:
            shown = ", ".join(f"{loc['file']}:{loc['line']}" for loc in signal["locations"])
            lines.append(f"  at {shown}")
        for key, count in signal["by"].items():
            lines.append(f"  {count}x {key}")
    return "\n".join(lines)


# The wiring: files in, the rendering out.


def transcripts(paths: list[Path]) -> Iterator[tuple[Path, str]]:
    """Each transcript file to read with its label: relative to a directory given, else its name."""
    for path in paths:
        if path.is_dir():
            for file in sorted(path.rglob("*.jsonl")):
                yield file, file.relative_to(path).as_posix()
        else:
            yield path, path.name


def repository_paths(repo: Path) -> Callable[[str], bool]:
    """Accepts a command argument that is a relative path to a file inside `repo`."""
    root = repo.resolve()

    def keep(token: str) -> bool:
        posix = PurePosixPath(token.replace("\\", "/"))
        if posix.is_absolute() or ":" in token or ".." in posix.parts or token.startswith("~"):
            return False
        try:
            candidate = (root / Path(*posix.parts)).resolve()
            return candidate.is_relative_to(root) and candidate.is_file()
        except (OSError, ValueError):
            return False

    return keep


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcript_signals.py",
        description="Count signals in session transcripts (JSONL files, or directories of them): "
                    "corrections, retries, repeated commands, scripts written twice, denials and "
                    "long waits, per session and in total. Prints counts and locations only.")
    parser.add_argument("paths", nargs="+", type=Path, help="transcript files or directories")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    parser.add_argument("--adapter", choices=sorted(ADAPTERS), default="claude-code",
                        help="the transcript format (default: claude-code)")
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="the repository whose relative paths a command shape may show "
                             "(default: the working directory)")
    parser.add_argument("--wait-seconds", type=float, default=WAIT_SECONDS,
                        help=f"a long wait is longer than this (default: {WAIT_SECONDS:g})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    events: list[Event] = []
    files: list[str] = []
    for path, label in transcripts(args.paths):
        if not path.is_file():
            print(f"error: no transcript at the path given as {label}", file=sys.stderr)
            return 2
        files.append(label)
        with path.open(encoding="utf-8", errors="replace") as handle:
            events.extend(read_events(handle, label, args.adapter))
    options = {"long-waits": {"seconds": args.wait_seconds},
               "repeated-commands": {"keep_path": repository_paths(args.repo)}}
    result = tally(events, files, options)
    print(render_json(result) if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
