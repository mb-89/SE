#!/usr/bin/env python3
"""Manage the Markdown-backed worker ticket queue, its work issues and the field reports in pull requests."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.request
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree


STATES = ("todo", "held", "done")
DIRECTORIES = (*STATES, "notes")
ID_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
HEADING_PATTERN = re.compile(r"^#\s+([^:\s]+):\s+(.+?)\s*$")
CHECKBOX_PATTERN = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$")
DISPOSITION_PATTERN = re.compile(r"^\s*Disposition:\s*(.*?)\s*$", re.IGNORECASE)
REQUIREMENT_PATTERN = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")
REQUIREMENT_SECTIONS = ("Requirements", "Changes after filing")
# A review's open points (`review.py file`, verdict "pass with open points"): numbered requirements
# under "Changes after filing" between these markers, which name the head commit the review passed.
# That commit lands without them; every later delivery on the issue delivers them.
OPEN_POINTS_END = "<!-- se:open-points:end -->"
OPEN_POINTS_PATTERN = re.compile(
    r"^<!-- se:open-points ([0-9a-f]{40}) -->\n(.*?)^<!-- se:open-points:end -->[ \t]*(?:\n|\Z)",
    re.MULTILINE | re.DOTALL)
# The section `route` appends to an outside issue, owned by the work model's "Outside issues": the
# work.md sections it lacks, each one heading level down, read as if the body held them itself.
ROUTING_SECTION = "Routing"
FRONT_MATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
ISSUE_URL_PATTERN = re.compile(r"^https?://([^/]+)/([^/]+)/([^/]+)/issues/\d+$")
CROSS_REFERENCE_PATTERN = re.compile(
    r"https?://(?P<host>[\w.-]+)/(?P<url_owner>[\w.-]+)/(?P<url_repo>[\w.-]+)"
    r"/(?:issues|pull|blob|tree)(?![\w.-])[^\s)>\]]*(?<![.,;:!?])"
    r"|(?<![\w/.-])(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#\d+"
)
REMOVED_PYTHON_TEST_PATTERN = re.compile(r"^-\s*def\s+(test_[A-Za-z0-9_]+)\s*\(")
REMOVED_JAVASCRIPT_TEST_PATTERN = re.compile(
    r"""^-\s*(?:test|it)\s*\(\s*(?P<quote>["'`])(?P<name>.*?)(?P=quote)"""
)
# A sentence ends at ".", "!" or "?" (and any closing quotes or brackets) followed by whitespace,
# or at the end of its block, so a dot inside a path, file name or version never ends one.
SENTENCE_PATTERN = re.compile(r"\S.*?(?:[.!?]+[\"')\]]*(?=\s|$)|$)")
# Markdown structure that ends a sentence: a fenced block's opening and closing line, a heading
# line and an Obsidian block-id line (`^id` alone).
FENCE_LINE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_LINE_PATTERN = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
BLOCK_ID_LINE_PATTERN = re.compile(r"^\s*\^[A-Za-z0-9-]+\s*$")
PROTECTED_SENTENCE_CONTENT_PATTERN = re.compile(r"```.*?```|`[^`\n]*`|https?://[^\s`<>()]+", re.DOTALL)
PROTECTED_DOT = "\uE000"
PROTECTED_BANG = "\uE001"
PROTECTED_QUESTION = "\uE002"
FIELD_REPORT_RESULT_PATTERN = re.compile(r"\*\*Result:\*\*\s*(complete|partial)\s*(?:\n|$)")
BRANCH_TIP_FIELD = re.compile(r"(\*\*Branch tip:\*\*[ \t]*)(`[^`\n]*`|\S*)")
BRANCH_TIP_PATTERN = re.compile(r"\*\*Branch tip:\*\*[ \t]*`?([0-9a-f]{7,40})`?(?=[ \t]|$)", re.MULTILINE)
REINTEGRATION_KIND_PATTERN = re.compile(r"\*\*Re-integration kind:\*\*[ \t]*([^\s<]*)")
RELEASE_KIND_PATTERN = re.compile(r"\*\*Release kind:\*\*[ \t]*(\w*)[ \t]*[—–:,-]*[ \t]*([^\n]*)")
BREAKING_PATTERN = re.compile(r"\*\*Breaking:\*\*")
REMOVED_SECTION = "Removed behaviour, deleted or weakened tests, and authored prose"
WORK_ISSUE_PATTERN = re.compile(r"\bWork issue:\*{0,2}\s*#(\d+)\b", re.IGNORECASE)
PUBLIC_HOST_PATTERN = re.compile(r"(?:[a-z][a-z0-9+.-]*://|@)", re.IGNORECASE)
IDENTITY_PATTERN = re.compile(r"(?P<name>.+?)\s*<(?P<email>[^<>\s]+)>")
ISSUE_FIELDS = "number,title,body,url,updatedAt,comments,labels"
ISSUE_SNAPSHOT = "issue.json"
COMMENTS_READ = "comments-read.json"
BODY_READ = "body-read.json"
# The issue templates belong to se, wherever a project keeps it; messages name them relative to it.
TEMPLATE_DIRECTORY = ".github/ISSUE_TEMPLATE"
TEMPLATES = Path(__file__).resolve().parents[1] / TEMPLATE_DIRECTORY
# The field report's one form, the pull request template a worker's pull request description is
# drawn from; the report sits between REPORT_BEGIN and REPORT_END, where the integration reads it.
FIELD_REPORT_TEMPLATE = ".github/pull_request_template.md"
REPORT_BEGIN = "<!-- se:field-report -->"
REPORT_END = "<!-- se:field-report:end -->"
DELIVERY_TICKET = "delivery"
# The fleet's marks on GitHub, owned by the work model's "Outside issues": every issue the fleet
# files carries FLEET_MARKER (as does every issue labelled FLEET_LABEL, the field-report issues of
# before field reports moved into pull requests, kept as history), and the comment that records an
# outside issue as handled carries HANDLED_MARKER.
FLEET_MARKER = "<!-- se:fleet -->"
HANDLED_MARKER = "<!-- se:handled -->"
FLEET_LABEL = "field-report"
# A backlog issue, owned by the work model's "Issues": a far-out idea for the person, never work.
BACKLOG_LABEL = "backlogged"
PERSON_LABEL = "se-person"
PAUSE_LABEL = "pause"  # an open issue with it pauses the fleet (work model, Pause)
# Work, owned by the work model's "Issues": SE files a work issue, or routes an outside issue, with
# WORK_LABELS (its record that the issue was checked and may be worked) and the issue's `repo:`
# label; `ready` and `start` take only those, and never an issue that carries a NOT_STARTABLE label.
WORK_LABELS = ("work", "ready")
IN_PROGRESS_LABEL = "in-progress"
NOT_STARTABLE_LABELS = frozenset({BACKLOG_LABEL, FLEET_LABEL, IN_PROGRESS_LABEL})
LABEL_DESCRIPTIONS = {
    "work": "A work issue: one package for one worker",
    "ready": "Checked by SE and may be worked",
    BACKLOG_LABEL: "A far-out idea for the person; not work until SE re-files it",
}
OUTSIDE_PAGE = 100
DISCOVERY_DIRECTORY = Path(".se") / "work" / "probe"
DISCOVERY_INDEX = "evidence.md"
DISCOVERY_CONFIG = "discovery.json"
DISCOVERY_LABEL = "discovery"
LOCAL_CORES_PER_WORKER = 2
LOCAL_MEMORY_MIB_PER_WORKER = 4096


class QueueError(Exception):
    """A queue operation cannot be completed safely."""


# Relative to se's checkout: an absolute path would carry a user profile path into logs.
WITHOUT_GH = "src/skills/work-model/SKILL.md#without-gh"


class MissingGhError(QueueError):
    """The GitHub CLI a command needs is not on PATH; main names the command."""


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    state: str
    path: Path
    content: str


@dataclass(frozen=True)
class Mirror:
    remote: str
    branch: str
    fetch: bool
    public: bool


def valid_id(value: str) -> bool:
    return bool(ID_PATTERN.fullmatch(value)) and value not in {".", ".."}


def worktree_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise QueueError(f"Worktree is not an existing directory: {root}")
    return root


def default_worktree_root(root: Path) -> Path:
    return root.parent / f"{root.name}.worktrees"


def inside_root(root: Path, path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise QueueError(f"Path escapes the selected worktree: {path}") from error
    if path.is_symlink():
        raise QueueError(f"Symbolic links are not allowed in the queue: {path}")


def queue_paths(root: Path) -> dict[str, Path]:
    paths = {name: root / ".se" / "work" / name for name in DIRECTORIES}
    for path in (root / ".se", root / ".se" / "work", *paths.values()):
        inside_root(root, path)
    return paths


def initialize(root: Path) -> None:
    queue = root / ".se" / "work"
    for directory in (root / ".se", queue, *(queue / name for name in DIRECTORIES)):
        inside_root(root, directory)
        if directory.exists():
            if not directory.is_dir():
                raise QueueError(f"Expected a directory: {directory}")
        else:
            directory.mkdir()


def discovery_directory(root: Path, configured: str | None = None) -> Path:
    directory = Path(configured) if configured else DISCOVERY_DIRECTORY
    if directory.is_absolute():
        raise QueueError("Discovery output root must be relative to the selected worktree")
    path = root / directory
    inside_root(root, path)
    return path


def discovery_index(root: Path) -> Path | None:
    config = root / ".se" / "work" / DISCOVERY_CONFIG
    if not config.is_file():
        return None
    try:
        configured = json.loads(config.read_text(encoding="utf-8"))["root"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise QueueError(f"Cannot read discovery configuration {config}: {error}") from error
    if not isinstance(configured, str):
        raise QueueError(f"Discovery configuration {config} has an invalid root")
    return discovery_directory(root, configured) / DISCOVERY_INDEX


def initialize_discovery(root: Path, configured: str | None) -> Path:
    initialize(root)
    directory = discovery_directory(root, configured)
    directory.mkdir(parents=True, exist_ok=True)
    index = directory / DISCOVERY_INDEX
    inside_root(root, index)
    if not index.exists():
        index.write_text(
            "# Discovery evidence\n\n| Command | Output |\n|---|---|\n",
            encoding="utf-8", newline="\n",
        )
    config = root / ".se" / "work" / DISCOVERY_CONFIG
    config.write_text(
        json.dumps({"root": directory.relative_to(root).as_posix()}, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return index


def append_discovery_evidence(root: Path, command: str, output: str) -> Path:
    """Append `command` and its `output` path to the evidence index; where no intake created one
    (without gh, intake cannot run), the first probe creates the default index."""
    if not command.strip() or not output.strip():
        raise QueueError("Discovery evidence requires a command and output path")
    if any(character in command + output for character in "\r\n|"):
        raise QueueError("Discovery evidence command and output cannot contain newlines or pipes")
    index = discovery_index(root) or initialize_discovery(root, None)
    with index.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"| `{command}` | `{output}` |\n")
    return index


def read_ticket(path: Path, state: str) -> Ticket:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".md":
        raise QueueError(f"Malformed ticket entry: {path.name}")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Cannot read ticket {path.name}: {error}") from error
    first_line = content.splitlines()[0] if content.splitlines() else ""
    match = HEADING_PATTERN.fullmatch(first_line)
    if match is None or not valid_id(match.group(1)):
        raise QueueError(f"Malformed ticket identity in {path.name}")
    return Ticket(match.group(1), state, path, content)


def scan_queue(root: Path) -> tuple[dict[str, Path], list[Ticket], list[str]]:
    paths = queue_paths(root)
    errors: list[str] = []
    for state, path in paths.items():
        if not path.is_dir():
            errors.append(f"Missing or invalid queue directory: {state}")

    tickets: list[Ticket] = []
    for state in STATES:
        if not paths[state].is_dir():
            continue
        for path in sorted(
            paths[state].iterdir(),
            key=lambda item: (item.name.casefold(), item.name),
        ):
            try:
                tickets.append(read_ticket(path, state))
            except (QueueError, OSError) as error:
                errors.append(str(error))

    by_id: dict[str, list[Ticket]] = {}
    for ticket in tickets:
        by_id.setdefault(ticket.ticket_id, []).append(ticket)
    for ticket_id, matches in sorted(by_id.items()):
        if len(matches) > 1:
            locations = ", ".join(
                f"{ticket.state}/{ticket.path.name}" for ticket in matches
            )
            errors.append(f"Duplicate ticket ID {ticket_id}: {locations}")
    return paths, tickets, errors


def section_content(content: str, section_name: str) -> list[str]:
    lines = content.splitlines()
    active = False
    selected: list[str] = []
    for line in lines:
        heading = SECTION_PATTERN.fullmatch(line)
        if heading:
            active = heading.group(1).strip().casefold().startswith(
                section_name.casefold()
            )
            continue
        if active:
            selected.append(line)
    return selected


def checklist_and_evidence_errors(content: str) -> list[str]:
    acceptance = section_content(content, "acceptance")
    unchecked_items = [
        match.group(2)
        for line in acceptance
        if (match := CHECKBOX_PATTERN.fullmatch(line)) is not None
        and match.group(1).casefold() != "x"
    ]
    problems: list[str] = []
    if unchecked_items:
        problems.append(
            "unchecked acceptance items: " + "; ".join(unchecked_items)
        )

    evidence = "\n".join(section_content(content, "evidence"))
    evidence = re.sub(r"<!--.*?-->", "", evidence, flags=re.DOTALL).strip()
    if not evidence:
        problems.append("empty Evidence section")
    return problems


def note_is_resolved(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return any(
        match.group(1).strip()
        for line in content.splitlines()
        if (match := DISPOSITION_PATTERN.fullmatch(line)) is not None
    )


def review_note(root: Path, note_name: str, disposition: str, backlog_ref: str | None) -> None:
    if (
        not note_name
        or note_name in {".", ".."}
        or Path(note_name).name != note_name
        or "/" in note_name
        or "\\" in note_name
    ):
        raise QueueError("Unsafe note filename")
    if not disposition.strip() or any(character in disposition for character in "\r\n"):
        raise QueueError("Disposition must be nonempty and on one line")
    if backlog_ref is not None and (
        not backlog_ref.strip() or any(character in backlog_ref for character in "\r\n")
    ):
        raise QueueError("Backlog reference must be nonempty and on one line")
    paths = queue_paths(root)
    note_path = paths["notes"] / note_name
    inside_root(root, note_path)
    if not note_path.is_file() or note_path.is_symlink():
        raise QueueError("Note file not found or not a regular file")
    entry = f"Disposition: {disposition.strip()}"
    if backlog_ref is not None:
        entry += f" (backlog-ref: {backlog_ref.strip()})"
    try:
        with note_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(("" if note_path.stat().st_size == 0 else "\n") + entry + "\n")
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Could not append note disposition: {error}") from error


PLACEHOLDER_ACCEPTANCE = "Add a checkable acceptance criterion."


def create_ticket(
    root: Path, ticket_id: str, title: str, acceptance: list[str] | None = None
) -> None:
    if not valid_id(ticket_id):
        raise QueueError(f"Unsafe ticket ID: {ticket_id!r}")
    title = title.strip()
    if not title or any(character in title for character in "\r\n"):
        raise QueueError("Ticket title must be nonempty and on one line")
    items = [item.strip() for item in acceptance or [PLACEHOLDER_ACCEPTANCE]]
    if any(not item or any(character in item for character in "\r\n") for item in items):
        raise QueueError(
            "create: each --acceptance must be one nonempty line; "
            "pass one --acceptance per acceptance item"
        )
    paths, tickets, errors = scan_queue(root)
    if errors:
        raise QueueError("; ".join(errors))
    if any(ticket.ticket_id == ticket_id for ticket in tickets):
        raise QueueError(f"Ticket ID already exists: {ticket_id}")

    path = paths["todo"] / f"{ticket_id}.md"
    inside_root(root, path)
    template = (
        f"# {ticket_id}: {title}\n\n"
        "## Design\n\n"
        "Link to the approved design owner.\n\n"
        "## Scope\n\n"
        "Describe the bounded objective and behavior to preserve.\n\n"
        "## Dependencies\n\n"
        "List dependencies, or write `None`.\n\n"
        "## Acceptance\n\n"
        + "".join(f"- [ ] {item}\n" for item in items)
        + "\n## Evidence\n"
    )
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(template)
    except FileExistsError as error:
        raise QueueError(f"Refusing to overwrite existing ticket: {path.name}") from error


def move_ticket(root: Path, ticket_id: str, destination: str) -> None:
    if not valid_id(ticket_id):
        raise QueueError(f"Unsafe ticket ID: {ticket_id!r}")
    if destination not in STATES:
        raise QueueError(f"Invalid destination state: {destination}")
    paths, tickets, errors = scan_queue(root)
    matches = [ticket for ticket in tickets if ticket.ticket_id == ticket_id]
    if len(matches) > 1:
        raise QueueError(f"Ticket ID is ambiguous: {ticket_id}")
    if not matches:
        if errors:
            raise QueueError("; ".join(errors))
        raise QueueError(f"Ticket not found: {ticket_id}")
    ticket = matches[0]
    allowed = {
        "todo": {"held"},
        "held": {"todo", "done"},
        "done": set(),
    }
    if destination not in allowed[ticket.state]:
        raise QueueError(f"Invalid transition: {ticket.state} -> {destination}")
    if errors:
        raise QueueError("; ".join(errors))
    if destination == "done":
        problems = checklist_and_evidence_errors(ticket.content)
        location = ticket.path.relative_to(root).as_posix()
        lines = ticket.content.splitlines()
        placeholder = f"- [ ] {PLACEHOLDER_ACCEPTANCE}"
        if placeholder in lines:
            line = lines.index(placeholder) + 1
            problems.append(
                f"{location}:{line} still holds the placeholder acceptance item; "
                "remedy: create tickets with `work_tickets.py create --acceptance <text>` "
                f"(repeatable), or edit line {line} into a real, checked criterion"
            )
        if problems:
            raise QueueError(
                f"Cannot move {ticket_id} ({location}) to done: {'; '.join(problems)}"
            )

    target = paths[destination] / ticket.path.name
    inside_root(root, target)
    try:
        with ticket.path.open("rb") as source, target.open("xb") as destination_file:
            shutil.copyfileobj(source, destination_file)
        ticket.path.unlink()
    except FileExistsError as error:
        raise QueueError(f"Refusing to overwrite existing ticket: {target.name}") from error
    except OSError as error:
        raise QueueError(f"Could not move ticket {ticket_id}: {error}") from error


def git_cleanup_reasons(root: Path, integration_target: str | None) -> list[str]:
    reasons: list[str] = []

    top = run_git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return ["Worktree is not inside a Git repository"]
    git_root = Path(top.stdout.strip()).resolve()
    if git_root != root:
        reasons.append("Selected path is not the Git worktree root")
    if (git_root / ".git").is_dir():
        reasons.append("Cannot close the primary checkout")
    listed = run_git(root, "worktree", "list", "--porcelain")
    if listed.returncode != 0 or not primary_checkout_path(listed.stdout):
        reasons.append("Could not identify the primary checkout")

    dirty = run_git(root, "-C", str(git_root), "status", "--porcelain=v1", "--untracked-files=all")
    if dirty.returncode != 0:
        reasons.append("Could not inspect Git worktree status")
    elif dirty.stdout.strip():
        reasons.append("Git worktree has dirty or untracked files")

    if not integration_target:
        reasons.append("An integration target is required")
    else:
        head = run_git(root, "-C", str(git_root), "rev-parse", "--verify", "HEAD^{commit}")
        target = run_git(root, 
            "-C", str(git_root), "rev-parse", "--verify",
            f"{integration_target}^{{commit}}",
        )
        if head.returncode != 0 or target.returncode != 0:
            reasons.append("Could not resolve the worktree or integration target commit")
        else:
            integrated = run_git(root, 
                "-C", str(git_root), "merge-base", "--is-ancestor",
                head.stdout.strip(), target.stdout.strip(),
            )
            if integrated.returncode != 0:
                reasons.append("Worker commits are not integrated into the target")
    return reasons


def primary_checkout_path(worktree_listing: str) -> Path | None:
    for line in worktree_listing.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line.removeprefix("worktree ")).resolve()
        if (candidate / ".git").is_dir():
            return candidate
    return None


def make_worktree_removable(root: Path) -> None:
    for current, directories, files in os.walk(root):
        for name in (*directories, *files):
            path = Path(current) / name
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
            if not mode & stat.S_IWUSR:
                path.chmod(mode | stat.S_IWUSR)
    mode = stat.S_IMODE(root.stat().st_mode)
    if not mode & stat.S_IWUSR:
        root.chmod(mode | stat.S_IWUSR)


def remove_private_queue(path: Path) -> None:
    def onerror(function, failed_path, error_info) -> None:
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    shutil.rmtree(path, onerror=onerror)


def remove_worktree(root: Path, report: dict[str, object]) -> None:
    """Remove the worker's worktree `root` from its primary checkout, recording the outcome in
    `report` (`removed`, or `cleanup_eligible` false with the reason)."""
    listing = run_git(root, "worktree", "list", "--porcelain")
    try:
        admin_path = primary_checkout_path(listing.stdout)
        if listing.returncode != 0 or admin_path is None:
            raise OSError("Could not identify the primary checkout")
        remove_private_queue(root / ".se")
        make_worktree_removable(root)
        removed = run_git(admin_path, "worktree", "remove", str(root))
    except OSError:
        removed = None
    if removed is None or removed.returncode != 0:
        report["cleanup_eligible"] = False
        detail = (
            removed.stderr.strip()
            if removed is not None and removed.stderr.strip()
            else "Normal Git worktree removal failed"
        )
        report["cleanup_reasons"] = [detail]
    else:
        report["removed"] = True


def status_report(
    root: Path, integration_target: str | None = None
) -> dict[str, object]:
    try:
        paths, tickets, errors = scan_queue(root)
    except QueueError as error:
        return {
            "initialized": False,
            "counts": {state: 0 for state in STATES},
            "tickets": {state: [] for state in STATES},
            "notes": [],
            "note_counts": {"resolved": 0, "unresolved": 0},
            "complete": False,
            "cleanup_eligible": False,
            "cleanup_reasons": [str(error)],
            "errors": [str(error)],
        }
    initialized = not any(
        not paths[name].is_dir() for name in DIRECTORIES
    )
    if not initialized and not errors:
        errors.append("Queue is not initialized")

    state_tickets = {
        state: sorted(
            (ticket for ticket in tickets if ticket.state == state),
            key=lambda ticket: ticket.ticket_id,
        )
        for state in STATES
    }
    for ticket in state_tickets["done"]:
        problems = checklist_and_evidence_errors(ticket.content)
        if problems:
            errors.append(
                f"Invalid completed ticket {ticket.ticket_id}: {', '.join(problems)}"
            )

    note_names: list[str] = []
    unresolved_notes = 0
    notes = paths["notes"]
    if notes.is_dir():
        for path in sorted(
            notes.iterdir(), key=lambda item: (item.name.casefold(), item.name)
        ):
            note_names.append(path.name)
            if path.is_symlink():
                errors.append(f"Symbolic link in notes directory: {path.name}")
                unresolved_notes += 1
            elif path.is_file():
                if not note_is_resolved(path):
                    unresolved_notes += 1
            else:
                errors.append(f"Invalid note entry: {path.name}")
                unresolved_notes += 1

    counts = Counter(ticket.state for ticket in tickets)
    cleanup_reasons = list(errors)
    if state_tickets["todo"]:
        cleanup_reasons.append("Tickets remain in todo")
    if state_tickets["held"]:
        cleanup_reasons.append("Tickets remain in held")
    if unresolved_notes:
        cleanup_reasons.append(f"{unresolved_notes} unresolved note(s) remain")
    complete = initialized and not cleanup_reasons
    cleanup_reasons.extend(git_cleanup_reasons(root, integration_target))
    return {
        "initialized": initialized,
        "counts": {state: counts[state] for state in STATES},
        "tickets": {
            state: [ticket.ticket_id for ticket in state_tickets[state]]
            for state in STATES
        },
        "notes": note_names,
        "note_counts": {
            "resolved": len(note_names) - unresolved_notes,
            "unresolved": unresolved_notes,
        },
        "complete": complete,
        "cleanup_eligible": not cleanup_reasons,
        "cleanup_reasons": sorted(set(cleanup_reasons)),
        "errors": sorted(errors),
    }


GH_ENVIRONMENT = {"GH_PROMPT_DISABLED": "1"}
# GitHub's refusal of a call for its primary or secondary rate limit, as gh reports it.
RATE_LIMITED = re.compile(r"rate limit|HTTP 429|abuse detection", re.IGNORECASE)
_signed_in_gh: set[str] = set()
_signing_in = threading.Lock()


def gh_executable() -> str:
    """The `gh` on PATH, refused where it is missing or `gh auth status` fails: a `gh` that is
    installed but not signed in counts as no `gh`. A passed check holds for the process."""
    executable = shutil.which("gh")
    if executable is None:
        raise MissingGhError(
            "needs the GitHub CLI (gh), which is not on PATH. Install it with the setup command "
            "the project's AGENTS.md names, or, where the host has no gh (Claude's cloud), do this "
            f"step by hand as the se checkout's {WITHOUT_GH} says"
        )
    with _signing_in:  # concurrent first calls check once
        signed_in(executable)
    return executable


def signed_in(executable: str) -> None:
    """Refuse a `gh` that `gh auth status` finds not signed in; a passed check holds for the
    process."""
    if executable not in _signed_in_gh:
        feedback.reading("GitHub", ["gh", "auth", "status"])
        status = subprocess.run(
            [executable, "auth", "status"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, env={**os.environ, **GH_ENVIRONMENT}, check=False,
        )
        if status.returncode != 0:
            raise MissingGhError(
                "needs the GitHub CLI (gh), which is installed but not signed in "
                f"(gh auth status: exit code {status.returncode}), so it counts as no gh. Sign in "
                "with gh auth login, or, where the host gives gh no account (Claude's cloud), do "
                f"this step by hand as the se checkout's {WITHOUT_GH} says"
            )
        _signed_in_gh.add(executable)


def gh_usable() -> bool:
    try:
        gh_executable()
    except MissingGhError:
        return False
    return True


def run_gh(root: Path, arguments: list[str]) -> str:
    """One call to GitHub through gh, announced before it is made (feedback.reading)."""
    executable = gh_executable()
    feedback.reading("GitHub", ["gh", *arguments])
    result = subprocess.run(
        [executable, *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env={**os.environ, **GH_ENVIRONMENT},
        check=False,
    )
    refused = result.returncode != 0 and bool(RATE_LIMITED.search(result.stderr + result.stdout))
    metrics.door_call(refused)
    if result.returncode != 0:
        detail = failure_detail(result)
        raise QueueError(f"gh {' '.join(arguments[:2])} failed: {detail}")
    return result.stdout


def run_gh_with_body(root: Path, arguments: list[str], body: str) -> str:
    # Bodies always travel in a file: quotes inside native arguments break Windows
    # PowerShell 5.1 callers, and long bodies exceed the command-line limit.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "body.md"
        path.write_text(body, encoding="utf-8", newline="\n")
        return run_gh(root, [*arguments, "--body-file", str(path)])


def repo_arguments(repo: str | None) -> list[str]:
    return ["--repo", repo] if repo else []


REMOTE_URL_PATTERN = re.compile(
    r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?(?P<host>[^/:@]+)(?::\d+)?/(?P<path>[^:]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
SCP_REMOTE_PATTERN = re.compile(r"^(?:[^@/]+@)?(?P<host>[^/:@]{2,}):(?P<path>[^\\]+?)(?:\.git)?/?$")


def remote_repo(root: Path) -> str | None:
    """`<host>/<owner>/<repo>` of the checkout's `origin` remote, without credentials."""
    result = run_git(root, "remote", "get-url", "origin")
    url = result.stdout.strip() if result.returncode == 0 else ""
    match = REMOTE_URL_PATTERN.match(url) or SCP_REMOTE_PATTERN.match(url)
    if match is None:
        return None
    parts = match.group("path").strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return "/".join((match.group("host"), *parts))


def repository_name(root: Path) -> str:
    """The local project name used to scope tracker issues."""
    repo = remote_repo(root)
    return repo.rsplit("/", 1)[-1] if repo else root.name


def checkout_keys(root: Path) -> list[str]:
    remote = run_git(root, "remote", "get-url", "origin")
    keys = [root.name, repository_name(root)]
    if remote.returncode == 0 and remote.stdout.strip():
        keys.insert(0, remote.stdout.strip())
    return keys


def tracker_repo(root: Path) -> str | None:
    """The configured tracker for this checkout, if it has one."""
    trackers = local_config().get("trackers")
    if not isinstance(trackers, dict):
        return None
    for key in checkout_keys(root):
        value = trackers.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def resolve_repo(root: Path, explicit: str | None) -> str:
    """The argument, configured tracker, or the `origin` remote's repository."""
    if explicit:
        return explicit
    repo = tracker_repo(root) or remote_repo(root)
    if repo is None:
        raise QueueError(
            "No repository: pass --repo [HOST/]OWNER/REPO, configure a tracker, or add a git "
            "remote origin"
        )
    return repo


def local_config_path() -> Path:
    return Path.home() / ".se" / "local.toml"


def local_config() -> dict[str, object]:
    path = local_config_path()
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise QueueError(f"Cannot read the machine-local config {path}: {error}") from error


def se_table(root: Path, name: str) -> dict[str, object]:
    """The `[<name>]` table of the checkout's se.toml, or {} without one."""
    path = root / "se.toml"
    if not path.is_file():
        return {}
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise QueueError(f"Cannot read the project config {path}: {error}") from error
    table = config.get(name)
    return table if isinstance(table, dict) else {}


def project_config(root: Path) -> dict[str, object]:
    """The `[project]` table of the checkout's se.toml, or {} without one."""
    return se_table(root, "project")


def integration_branch(root: Path) -> str:
    """`project.integration_branch` in se.toml, the branch the integrator writes; default main."""
    configured = project_config(root).get("integration_branch", "main")
    if not isinstance(configured, str) or not configured.strip():
        raise QueueError(
            f"project.integration_branch in {root / 'se.toml'} must be a non-empty branch name; "
            "fix it or remove it to use main"
        )
    return configured.strip()


def public_check_enabled(root: Path) -> bool:
    """`project.public_check` in se.toml: whether pushes need se's check; on unless set false."""
    configured = project_config(root).get("public_check", True)
    if not isinstance(configured, bool):
        raise QueueError(
            f"project.public_check in {root / 'se.toml'} must be true or false; fix it"
        )
    return configured


RELEASE_WORKFLOW = ".github/workflows/release.yml of se"


def release_by_workflow(root: Path) -> bool:
    """`project.release = "workflow"` in se.toml: the release workflow pushes the tags, not push."""
    configured = project_config(root).get("release")
    if configured not in (None, "workflow"):
        raise QueueError(
            f"project.release in {root / 'se.toml'} is {configured!r}; set it to \"workflow\" or remove it"
        )
    return configured == "workflow"


def workflow_tags(tag: str) -> None:
    print(
        f"Release: {tag} is tagged by the release workflow ({RELEASE_WORKFLOW}) on its push, "
        'as se.toml [project] release = "workflow" says'
    )


VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
VERSION_REMEDY = 'write it as version = "MAJOR.MINOR.PATCH" under [project], for example "1.0.0"'


def project_version(root: Path) -> tuple[int, int, int] | None:
    """`project.version` in se.toml as (major, minor, patch), or None where the project sets none."""
    configured = project_config(root).get("version")
    if configured is None:
        return None
    match = VERSION_PATTERN.fullmatch(configured) if isinstance(configured, str) else None
    if match is None:
        raise QueueError(
            f"project.version in {root / 'se.toml'} is {configured!r}, not MAJOR.MINOR.PATCH; "
            f"{VERSION_REMEDY}"
        )
    return (int(match[1]), int(match[2]), int(match[3]))


def version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


PUBLIC_CHECK = Path(__file__).resolve().parent / "public_check.py"
PUBLIC_CHECK_OPT_OUT = (
    "a project without a public check sets `public_check = false` in `[project]` of "
)


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded once."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


metrics = sibling("metrics")
feedback = sibling("feedback")


def tracker_references(text: str) -> list[tuple[int, str]]:
    """The public check's tracker-reference test (one owner: public_check.tracker_references)."""
    return sibling("public_check").tracker_references(text)


SUITE_VERDICT, PUBLIC_CHECK_VERDICT = "suite", "public-check"


def pushed_tree_refusals(root: Path, commit: str) -> list[str]:
    """Why `commit` may not reach the integration branch: each check (the public check unless
    se.toml turns it off) needs a passing verdict recorded on exactly its tree (scripts/verdicts.py)."""
    verdicts = sibling("verdicts")
    try:
        commit = verdicts.git(root, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        refusals = [verdicts.refusal(
            root, SUITE_VERDICT, commit,
            f"check out {commit[:12]} clean and run work_tickets.py suite --worktree <checkout> "
            "until it passes, then push again; there is no other way past",
        )]
        if public_check_enabled(root):
            refusals.append(verdicts.refusal(
                root, PUBLIC_CHECK_VERDICT, commit,
                f"run public_check.py --repo <checkout> --rev {commit[:12]} until it passes "
                "(work_tickets.py push runs it), then push again",
            ))
    except ValueError as error:
        return [f"cannot read the verdicts of {commit}: {error}"]
    return [refusal for refusal in refusals if refusal]


def guard_pushed_tree(root: Path, commit: str) -> None:
    refusals = pushed_tree_refusals(root, commit)
    if refusals:
        raise QueueError(
            f"Refusing to push {commit} to the integration branch {integration_branch(root)}; "
            "nothing was pushed:\n" + "\n".join(f"  {refusal}" for refusal in refusals)
        )


def run_public_check(root: Path, previous: str) -> None:
    """se's public check on the merged tree and every commit since `previous`; refuse on failure."""
    result = subprocess.run(
        [sys.executable, str(PUBLIC_CHECK), "--repo", str(root), "--rev", "HEAD",
         "--range", f"{previous}..HEAD"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"
        raise QueueError(
            f"Public check failed ({PUBLIC_CHECK.name}, required by project.public_check in "
            f"se.toml); nothing was pushed. Remove the hits on the branch or add a reasoned allow "
            f"entry, then integrate again: {detail}; "
            f"{PUBLIC_CHECK_OPT_OUT}{root / 'se.toml'}"
        )


def authored_content_globs(root: Path) -> list[str]:
    configured = project_config(root).get("authored_content")
    if configured is None:
        return []
    if not isinstance(configured, list) or not all(
        isinstance(glob, str) and glob for glob in configured
    ):
        raise QueueError("project.authored_content must be a list of non-empty globs")
    return configured


def config_value(key: str, repo: str | None, explicit: str | None) -> str | None:
    """The argument, else `[repos."<repo>"]` in ~/.se/local.toml, else its top-level key."""
    if explicit:
        return explicit
    config = local_config()
    repos = config.get("repos")
    override = repos.get(repo) if isinstance(repos, dict) and repo else None
    for table in (override, config):
        if isinstance(table, dict) and isinstance(table.get(key), str) and table[key]:
            return table[key]
    return None


def configured_worktree_root(root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    worktree_roots = local_config().get("worktree_roots")
    if not isinstance(worktree_roots, dict):
        return None
    for key in checkout_keys(root):
        value = worktree_roots.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def configured_mirrors(root: Path) -> list[Mirror]:
    """Return machine-local mirror settings for this checkout."""
    mirrors = local_config().get("mirrors")
    if not isinstance(mirrors, dict):
        return []
    configured: object | None = None
    for key in checkout_keys(root):
        if key in mirrors:
            configured = mirrors[key]
            break
    if configured is None:
        return []
    if not isinstance(configured, list):
        raise QueueError("Each [mirrors] checkout entry must be an array of tables")
    result: list[Mirror] = []
    for entry in configured:
        if not isinstance(entry, dict):
            raise QueueError("Each configured mirror must be a table")
        remote = entry.get("remote")
        branch = entry.get("branch")
        fetch = entry.get("fetch")
        public = entry.get("public")
        if not isinstance(remote, str) or not remote:
            raise QueueError("Each configured mirror needs a non-empty remote name")
        if not isinstance(branch, str) or not branch:
            raise QueueError("Each configured mirror needs a non-empty branch name")
        if not isinstance(fetch, bool) or not isinstance(public, bool):
            raise QueueError("Each configured mirror needs boolean fetch and public settings")
        result.append(Mirror(remote, branch, fetch, public))
    return result


def api_repo(repo: str) -> str:
    parts = repo.split("/")
    return "/".join(parts[-2:])


def repo_host(repo: str) -> str | None:
    parts = repo.split("/")
    return parts[0] if len(parts) == 3 else None


def current_branch(root: Path) -> str:
    result = run_git(root, "branch", "--show-current")
    return result.stdout.strip() if result.returncode == 0 else ""


def tested_main(root: Path) -> str:
    """The newest integration-branch commit merged into the branch, local or remote alike."""
    target = integration_branch(root)
    refs = [ref for ref in (target, f"origin/{target}")
            if run_git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0]
    base = run_git(root, "merge-base", "HEAD", *refs) if refs else None
    if base is None or base.returncode != 0:
        raise QueueError(
            f"work_tickets.py: cannot find the {target} commit merged into this branch; "
            "run work_tickets.py sync first"
        )
    return run_git(root, "rev-parse", "--short", base.stdout.strip()).stdout.strip()


def set_commit_identity(root: Path, command: str) -> tuple[str, str, str] | None:
    """Set the checkout's user.name and user.email to its commit identity, as `sync` and the
    setup scripts do; (name, email, source), or None where neither config sets one."""
    identity = commit_identity(root)
    if identity is not None:
        for key, value in zip(("user.name", "user.email"), identity[:2]):
            configured = run_git(root, "config", key, value)
            if configured.returncode != 0:
                detail = failure_detail(configured)
                raise QueueError(
                    f"work_tickets.py {command}: cannot set {key} from {identity[2]}: {detail}"
                )
    return identity


def sync(root: Path) -> str:
    set_commit_identity(root, "sync")
    remote = remote_repo(root)
    if remote is not None:
        fetched = run_git(root, "fetch", "origin")
        if fetched.returncode != 0:
            detail = failure_detail(fetched)
            raise QueueError(f"Cannot fetch origin: {detail}")
        main_ref = f"origin/{integration_branch(root)}"
    else:
        main_ref = integration_branch(root)
    merged = run_git(root, "merge", "--no-edit", main_ref)
    if merged.returncode != 0:
        detail = failure_detail(merged)
        raise QueueError(
            f"Cannot merge {main_ref} due to a merge conflict or merge failure: {detail}"
        )
    for mirror in configured_mirrors(root):
        if not mirror.fetch:
            continue
        fetched = run_git(root, "fetch", mirror.remote)
        if fetched.returncode != 0:
            detail = failure_detail(fetched)
            raise QueueError(f"Cannot fetch mirror {mirror.remote}: {detail}")
        mirror_ref = f"{mirror.remote}/{mirror.branch}"
        merged = run_git(root, "merge", "--no-edit", mirror_ref)
        if merged.returncode != 0:
            detail = failure_detail(merged)
            raise QueueError(
                f"Cannot merge {mirror_ref} due to a merge conflict or merge failure: {detail}"
            )
    commit = run_git(root, "rev-parse", "--short", main_ref)
    if commit.returncode != 0 or not commit.stdout.strip():
        raise QueueError(f"Merged {main_ref} but cannot determine its commit")
    return commit.stdout.strip()


def fetch_issue(root: Path, number: int, repo: str | None) -> dict[str, object]:
    return issue_record(json.loads(run_gh(
        root, ["issue", "view", str(number), "--json", ISSUE_FIELDS, *repo_arguments(repo)]
    )))


def first_of(item: dict[str, object], *keys: str) -> object:
    """The first of `keys` that `item` holds a value for: gh's camelCase name or the REST API's
    and the GitHub tools' snake_case one."""
    return next((item[key] for key in keys if item.get(key) not in (None, "")), "")


def web_url(item: dict[str, object]) -> str:
    """The page address of an issue or comment: `html_url` in the REST API's and the GitHub
    tools' form, where `url` is the API address; `url` in gh's."""
    return str(first_of(item, "html_url", "url"))


def comment_record(comment: dict[str, object]) -> dict[str, object]:
    """One comment as the snapshot keeps it, from gh's, the REST API's or the GitHub tools' form."""
    author = first_of(comment, "author", "user")
    return {
        "id": str(comment.get("id", "")),
        "author": str(author.get("login", "")) if isinstance(author, dict) else str(author),
        "createdAt": str(first_of(comment, "createdAt", "created_at")),
        "url": web_url(comment),
        "body": str(comment.get("body") or "").replace("\r\n", "\n"),
    }


def issue_record(
    data: dict[str, object], comments: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """The work issue as the snapshot keeps it, from gh's `issue view --json` (its comments
    inline), or from the REST API's or the GitHub tools' answer with `comments` read apart (the
    tools name labels as strings and the issue's comments only as their count)."""
    url = web_url(data)
    match = ISSUE_URL_PATTERN.fullmatch(url)
    if match is None:
        raise QueueError(f"Unexpected issue URL: {url!r}; the work issue's page address "
                         "(`html_url` or `url`) is needed")
    if comments is None:
        inline = data.get("comments")
        if isinstance(inline, list):
            comments = inline
        elif inline:
            raise QueueError(
                f"The work issue has {inline} comment(s) and none were given: save them as your "
                "GitHub tools read them and pass --comments-file <file>")
        else:
            comments = []
    return {
        "repo": "/".join(match.groups()),
        "number": int(data["number"]),
        "url": url,
        "title": str(data["title"]),
        "body": str(data.get("body") or "").replace("\r\n", "\n"),
        "updatedAt": str(first_of(data, "updatedAt", "updated_at")),
        "labels": [{"name": label["name"] if isinstance(label, dict) else str(label)}
                   for label in data.get("labels") or []],
        "comments": [comment_record(comment) for comment in comments],
    }


def json_answer(file: Path, what: str) -> object:
    """The JSON a GitHub tool answered, as the session saved it to `file`."""
    try:
        return json.loads(read_file(file, what))
    except ValueError as error:
        raise QueueError(
            f"The {what} {file} is no JSON: {error}; save the GitHub tool's answer to the file "
            "as it came (work-model skill, \"Without gh\")") from error


def issue_answer(issue_file: Path) -> dict[str, object]:
    """The issue a GitHub tool's or the REST API's answer saved to `issue_file` holds."""
    data = json_answer(issue_file, "work issue")
    if not isinstance(data, dict) or "number" not in data or "title" not in data:
        raise QueueError(
            f"The work issue file {issue_file} holds no issue: save the answer of your GitHub "
            "tools' issue read (number, title, body, html_url) to it")
    return data


def answered_issue(issue_file: Path, comments_file: Path | None) -> dict[str, object]:
    """The work issue from the files the session saved its GitHub tools' answers to: the issue as
    `issue_read` (method `get`) or the REST API answers it, and its comments as `issue_read`
    (method `get_comments`) or the REST API list them."""
    data = issue_answer(issue_file)
    comments = None
    if comments_file is not None:
        listed = json_answer(comments_file, "work issue comments")
        if isinstance(listed, dict):
            listed = listed.get("comments", listed.get("items"))
        if not isinstance(listed, list) or not all(isinstance(item, dict) for item in listed):
            raise QueueError(
                f"The comments file {comments_file} holds no list of comments: save the answer "
                "of your GitHub tools' comment read to it")
        comments = listed
    return issue_record(data, comments)


def issue_body_text(file: Path) -> str:
    """The work issue's body from `file`: the body itself, or the issue as a GitHub tool, the
    REST API or gh answers it, saved as JSON."""
    text = read_file(file, "work issue body")
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return text
        if isinstance(data, dict) and isinstance(data.get("body"), str):
            return data["body"].replace("\r\n", "\n")
    return text


def snapshot_path(root: Path) -> Path:
    path = queue_paths(root)["todo"].parent / ISSUE_SNAPSHOT
    inside_root(root, path)
    return path


def load_snapshot(root: Path) -> dict[str, object] | None:
    path = snapshot_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise QueueError(f"Cannot read the work issue snapshot {path}: {error}") from error


def required_snapshot(root: Path) -> dict[str, object]:
    snapshot = load_snapshot(root)
    if snapshot is None:
        raise QueueError("No work issue recorded; run intake --issue N or refresh --issue N first")
    return snapshot


def save_snapshot(root: Path, issue: dict[str, object]) -> None:
    initialize(root)
    snapshot_path(root).write_text(
        json.dumps(issue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def comment_state(comments: list[dict[str, object]]) -> dict[str, object]:
    """What a read of the work issue's comments records: their count and the newest one's id."""
    return {"count": len(comments), "newest": str(comments[-1]["id"]) if comments else ""}


def comments_read_path(root: Path) -> Path:
    path = queue_paths(root)["todo"].parent / COMMENTS_READ
    inside_root(root, path)
    return path


def load_comments_read(root: Path) -> dict[str, object] | None:
    path = comments_read_path(root)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return {"count": int(record["count"]), "newest": str(record["newest"])}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise QueueError(
            f"Cannot read the comments-read record {path}: {error}; record the comments again "
            "with comments-read --count <n> --newest <id>"
        ) from error


def record_comments_read(root: Path, state: dict[str, object]) -> None:
    if int(state["count"]) < 0 or bool(state["newest"]) != bool(state["count"]):
        raise QueueError(
            "comments-read: --count must be 0 with an empty --newest, or positive with the newest "
            f"comment's id; got --count {state['count']} --newest {state['newest']!r}"
        )
    initialize(root)
    comments_read_path(root).write_text(
        json.dumps({"count": int(state["count"]), "newest": str(state["newest"])}) + "\n",
        encoding="utf-8", newline="\n",
    )


def body_hash(body: str) -> str:
    """What a read of the work issue's body records: the hash of its text, line endings and
    surrounding whitespace aside, so a body read with gh and one saved by hand agree."""
    return hashlib.sha256(body.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


def body_read_path(root: Path) -> Path:
    path = queue_paths(root)["todo"].parent / BODY_READ
    inside_root(root, path)
    return path


def load_body_read(root: Path) -> str | None:
    path = body_read_path(root)
    if not path.is_file():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["sha256"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise QueueError(
            f"Cannot read the body-read record {path}: {error}; record the body again with "
            "body-read"
        ) from error


def record_body_read(root: Path, body: str) -> None:
    initialize(root)
    body_read_path(root).write_text(
        json.dumps({"sha256": body_hash(body)}) + "\n", encoding="utf-8", newline="\n",
    )


def body_read(root: Path, file: Path | None) -> None:
    """Record the work issue's body as read: from `file`, as the worker's GitHub tools read it,
    or, without one, as gh reads it now."""
    if file is not None:
        body = issue_body_text(file)
    else:
        snapshot = required_snapshot(root)
        body = str(fetch_issue(root, int(snapshot["number"]), str(snapshot["repo"]))["body"])
    record_body_read(root, body)


def changed_body_error(recorded: str, body: str, issue: str) -> QueueError | None:
    """The refusal where the work issue's body changed after it was recorded as read."""
    if recorded == body_hash(body):
        return None
    return QueueError(
        f"The body of the work issue {issue} changed after it was last recorded as read. "
        "Read its \"Changes after filing\", apply them, add their evidence rows to the field "
        "report, then record the body as read: work_tickets.py body-read --worktree <worktree> "
        "(without gh: add --body-file <file>, the body as your GitHub tools read it now)"
    )


EMPTY_ARGUMENT = "''"


def unread_comments_error(
    recorded: dict[str, object], current: dict[str, object],
    comments: list[dict[str, object]] | None,
) -> QueueError | None:
    """The refusal where the work issue's comments moved past what was recorded as read.

    `comments` is the issue's comment list where it was read with gh; given by hand, only the
    current count and newest id are known."""
    if recorded == current:
        return None
    if comments is not None:
        ids = [str(comment["id"]) for comment in comments]
        start = ids.index(str(recorded["newest"])) + 1 if recorded["newest"] in ids else 0
        named = [
            f"{comment['createdAt']} {comment['author']}: {comment['url'] or comment['id']}"
            for comment in comments[start:]
        ] or [f"comment(s) were deleted: {recorded['count']} recorded, {current['count']} now"]
    else:
        named = [f"{current['count']} comment(s) now, {recorded['count']} recorded as read; "
                 f"newest now {current['newest'] or 'none'}, recorded {recorded['newest'] or 'none'}"]
    return QueueError(
        "The work issue has comments that arrived after they were last recorded as read:\n"
        + "".join(f"- {line}\n" for line in named)
        + "Read them, apply them or answer them in the field report's Review responses, then "
        f"record them as read: work_tickets.py comments-read --count {current['count']} "
        f"--newest {current['newest'] or EMPTY_ARGUMENT} --worktree <worktree>"
    )


def markdown_sections(body: str, level: int = 2) -> dict[str, str]:
    """The body's sections at one heading level (`##` by default), heading -> text."""
    pattern = re.compile(rf"^{'#' * level}\s+(.+?)\s*$")
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else pattern.fullmatch(line)
        if heading:
            current = sections.setdefault(heading.group(1).strip().casefold(), [])
        elif current is not None:
            current.append(line)
    return {
        name: HTML_COMMENT_PATTERN.sub("", "\n".join(lines)).strip()
        for name, lines in sections.items()
    }


def section(sections: dict[str, str], name: str) -> str:
    return next(
        (text for heading, text in sections.items() if heading.startswith(name.casefold())), ""
    )


def routed_sections(body: str) -> dict[str, str]:
    """The sections under the body's routing heading, which `route` wrote one level down."""
    return markdown_sections(section(markdown_sections(body), ROUTING_SECTION), level=3)


def issue_sections(body: str) -> dict[str, str]:
    """An issue's sections as its readers see them: the body's own, then the routed ones."""
    sections = markdown_sections(body)
    for name, text in routed_sections(body).items():
        sections[name] = "\n\n".join(part for part in (sections.get(name, ""), text) if part)
    return sections


def requirement_items(body: str) -> dict[int, tuple[str, str]]:
    """The one parser of an issue's requirements: number -> (section, text).

    Numbered items under "Changes after filing", and under the routing section's requirements,
    are requirements too, numbered as written; a number two sections use is one requirement,
    named by the section that first lists it.
    """
    sections = markdown_sections(body)
    sources = [(name, section(sections, name)) for name in REQUIREMENT_SECTIONS]
    sources.append((ROUTING_SECTION, section(routed_sections(body), "requirements")))
    items: dict[int, tuple[str, list[str]]] = {}
    for name, text in sources:
        current: list[str] | None = None
        for line in text.splitlines():
            match = REQUIREMENT_PATTERN.fullmatch(line)
            if match:
                current = items.setdefault(int(match.group(1)), (name, []))[1]
                current.append(match.group(2))
            elif current is not None:
                current.append(line)
    return {
        number: (name, "\n".join(lines).strip()) for number, (name, lines) in items.items()
    }


def same_commit(one: str, other: str) -> bool:
    """Whether two commit names, either abbreviated, name the same commit."""
    return bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))


def without_open_points(body: str, tip: str | None) -> str:
    """`body` without the open points a review left on commit `tip`: that commit lands without
    them, as work for after it, not as requirements it delivers."""
    if not tip:
        return body
    return OPEN_POINTS_PATTERN.sub(lambda match: "" if same_commit(match[1], tip) else match[0],
                                   body)


def open_points(body: str, tip: str | None) -> list[str]:
    """The open points a review left on commit `tip`, as their `<n>. <text>` lines."""
    return [line.strip() for match in OPEN_POINTS_PATTERN.finditer(body)
            if tip and same_commit(match[1], tip)
            for line in match[2].splitlines() if REQUIREMENT_PATTERN.fullmatch(line.strip())]


def with_open_points(body: str, head: str, points: list[str]) -> str:
    """`body` with `points` numbered after its last requirement, in one open-points block naming
    commit `head` at the end of "Changes after filing", which is added where the body has none.
    Each point names its own source: the block's markers are comments, and any other line in it
    would read as part of a requirement."""
    first = max(requirement_items(body), default=0) + 1
    block = [f"<!-- se:open-points {head} -->",
             *(f"{number}. {' '.join(point.split())}" for number, point in enumerate(points, first)),
             OPEN_POINTS_END]
    lines = body.rstrip("\n").split("\n")
    start = next((index for index, line in enumerate(lines)
                  if (match := SECTION_PATTERN.match(line))
                  and match[1].casefold() == REQUIREMENT_SECTIONS[1].casefold()), None)
    if start is None:
        return "\n".join([*lines, "", f"## {REQUIREMENT_SECTIONS[1]}", "", *block]) + "\n"
    end = next((index for index in range(start + 1, len(lines))
                if SECTION_PATTERN.match(lines[index])), len(lines))
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    rest = ["", *lines[end:]] if end < len(lines) else []
    return "\n".join([*lines[:last], "", *block, *rest]) + "\n"


def field_report_evidence_items(body: str) -> dict[str, str]:
    """Every item a field report needs a row for -> the issue section that lists it."""
    requirements = {
        f"Requirement {number}": name for number, (name, _) in requirement_items(body).items()
    }
    acceptance_items = [
        match.group(2)
        for line in section(issue_sections(body), "acceptance").splitlines()
        if (match := CHECKBOX_PATTERN.fullmatch(line)) is not None
    ]
    acceptance = {
        f"Acceptance {number}": "Acceptance" for number, _ in enumerate(acceptance_items, 1)
    }
    return {**requirements, **acceptance}


def field_report_evidence_errors(issue_body: str, report_body: str) -> list[str]:
    delivered = section_content(report_body, "delivered")
    not_delivered = "\n".join(section_content(report_body, "not delivered"))
    missing: list[str] = []
    for item, where in field_report_evidence_items(issue_body).items():
        item_pattern = re.compile(rf"^{re.escape(item)}(?:\b|:)", re.IGNORECASE)
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in delivered
            if line.strip().startswith("|")
        ]
        has_evidence = any(
            row and item_pattern.match(row[0]) and len(row) >= 4 and bool(row[-1])
            for row in rows
        )
        listed_as_not_delivered = re.search(
            rf"\b{re.escape(item)}\b", not_delivered, flags=re.IGNORECASE
        )
        if not has_evidence and not listed_as_not_delivered:
            missing.append(
                item if where in (REQUIREMENT_SECTIONS[0], "Acceptance")
                else f'{item} (under "{where}")'
            )
    if not missing:
        return []
    return ["missing evidence for: " + "; ".join(missing)]


def slug(text: str, limit: int = 40) -> str:
    result = ""
    for word in re.findall(r"[a-z0-9]+", text.casefold()):
        candidate = f"{result}-{word}" if result else word
        if len(candidate) > limit:
            break
        result = candidate
    return result or "item"


def one_line(text: str, limit: int = 90) -> str:
    line = " ".join(text.split()).replace("**", "")
    if len(line) <= limit:
        return line
    return line[: limit - 3].rsplit(" ", 1)[0] + "..."


def requirement_prefix(number: int) -> str:
    return f"r{number}-"


def is_discovery_issue(issue: dict[str, object]) -> bool:
    return DISCOVERY_LABEL in issue_labels(issue)


def planned_tickets(issue: dict[str, object]) -> list[tuple[str, str]]:
    """Derives one ticket per numbered requirement plus the delivery ticket."""
    sections = issue_sections(issue["body"])
    requirements = {n: text for n, (_, text) in requirement_items(issue["body"]).items()}
    if not requirements:
        requirements = {1: section(sections, "goal") or issue["title"]}
    owner = section(sections, "design owner") or "Named in the work issue."
    tickets: list[tuple[str, str]] = []
    previous = "None"
    discovery = is_discovery_issue(issue)
    for number, text in sorted(requirements.items()):
        ticket_id = requirement_prefix(number) + slug(text)
        verification = (
            "- [ ] Discovery evidence is recorded in the evidence index.\n"
            if discovery
            else "- [ ] Its focused tests and the affected real command pass.\n"
        )
        tickets.append((ticket_id, (
            f"# {ticket_id}: {one_line(text.splitlines()[0])}\n\n"
            "## Design\n\n"
            f"Work issue {issue['url']}, requirement {number}; re-read its body and its comments "
            "before starting.\n\n"
            f"Design owner: {owner}\n\n"
            f"## Scope\n\n{text}\n\n"
            f"## Dependencies\n\n{previous}\n\n"
            "## Acceptance\n\n"
            f"- [ ] Requirement {number} is implemented as the work issue states it now.\n"
            f"{verification}\n"
            "## Evidence\n"
        )))
        previous = f"`{ticket_id}` (the work issue orders its requirements)."
    acceptance = section(sections, "acceptance")
    verification = (
        "Discovery evidence from the work issue."
        if discovery
        else section(sections, "verification") or "As the work issue states."
    )
    tickets.append((DELIVERY_TICKET, (
        f"# {DELIVERY_TICKET}: Deliver {issue['title']}\n\n"
        "## Design\n\n"
        f"Work issue {issue['url']}, sections Acceptance and Verification; the delivery steps "
        "are in `src/agents/worker.md`.\n\n"
        f"## Scope\n\nVerification from the work issue:\n\n{verification}\n\n"
        "## Dependencies\n\n"
        + ", ".join(f"`{ticket_id}`" for ticket_id, _ in tickets) + "\n\n"
        "## Acceptance\n\n"
        + (
            "- [ ] Discovery evidence is complete and linked from the field report.\n"
            if discovery else f"{acceptance}\n"
        )
        + "- [ ] Branch pushed, pull request to the integration branch opened with the field "
          "report as its description.\n\n"
        "## Evidence\n"
    )))
    return tickets


def intake(
    root: Path, number: int | None, repo: str | None, discovery: bool = False,
    probe_root: str | None = None, answered: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str], list[str]]:
    """Write the work issue's tickets: read with gh, or `answered`, as the session's GitHub tools
    read it (`answered_issue`)."""
    initialize(root)
    paths, tickets, errors = scan_queue(root)
    if errors:
        raise QueueError("; ".join(errors))
    issue = answered if answered is not None else fetch_issue(root, number, resolve_repo(root, repo))
    existing = [ticket.ticket_id for ticket in tickets]
    created: list[str] = []
    kept: list[str] = []
    for ticket_id, content in planned_tickets(issue):
        key = DELIVERY_TICKET if ticket_id == DELIVERY_TICKET else ticket_id.split("-", 1)[0] + "-"
        if any(name == key or name.startswith(key) for name in existing):
            kept.append(ticket_id)
            continue
        path = paths["todo"] / f"{ticket_id}.md"
        inside_root(root, path)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        created.append(ticket_id)
    if discovery or is_discovery_issue(issue):
        initialize_discovery(root, probe_root)
    save_snapshot(root, issue)
    record_comments_read(root, comment_state(issue["comments"]))
    record_body_read(root, str(issue["body"]))
    return issue, created, kept


def outside_cutoffs(root: Path) -> dict[str, int]:
    """se.toml's `[outside]` table: each repository SE watches for outside issues and the last
    issue number that existed before the fleet marked its own (the work model's "Outside issues")."""
    table = se_table(root, "outside")
    remedy = (
        f'name each repository and its cut-off in {root / "se.toml"}, as '
        '[outside] "<host>/<owner>/<repo>" = <last issue number before the fleet marker> '
        '(the se checkout\'s src/skills/work-model/SKILL.md#outside-issues)'
    )
    if not table:
        raise QueueError(f"intake --outside: no [outside] table; {remedy}")
    cutoffs: dict[str, int] = {}
    for repo, cutoff in table.items():
        if len(repo.split("/")) != 3 or not all(repo.split("/")) or isinstance(cutoff, bool) \
                or not isinstance(cutoff, int) or cutoff < 0:
            raise QueueError(f"intake --outside: [outside] entry {repo!r} = {cutoff!r} is invalid; {remedy}")
        cutoffs[repo] = cutoff
    if len({repo.split("/")[0] for repo in cutoffs}) != 1:
        raise QueueError(
            "intake --outside: [outside] names repositories on more than one host, which one "
            f"query cannot read; {remedy}")
    return cutoffs


def outside_query(repos: list[str]) -> str:
    """One GraphQL query for the open issues of every repository, newest first."""
    parts = []
    for index, repo in enumerate(repos):
        _, owner, name = repo.split("/")
        parts.append(
            f"r{index}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ "
            f"issues(states: OPEN, first: {OUTSIDE_PAGE}, "
            "orderBy: {field: CREATED_AT, direction: DESC}) { pageInfo { hasNextPage } "
            "nodes { number title url body labels(first: 50) { nodes { name } } "
            "comments(last: 100) { nodes { body } } } } }"
        )
    return "query { " + " ".join(parts) + " }"


def outside_issues(cutoffs: dict[str, int], data: dict[str, object]) -> list[dict[str, object]]:
    """The open issues above each cut-off that carry neither the fleet marker nor its label, are
    not backlogged and have no handled comment; refused where an unread page could hold more."""
    found: list[dict[str, object]] = []
    for index, (repo, cutoff) in enumerate(cutoffs.items()):
        repository = (data.get("data") or {}).get(f"r{index}")
        if not repository:
            raise QueueError(f"intake --outside: GitHub returned no repository {repo}; check [outside] in se.toml")
        issues = repository["issues"]
        nodes = issues["nodes"]
        if issues["pageInfo"]["hasNextPage"] and nodes and min(n["number"] for n in nodes) > cutoff + 1:
            raise QueueError(
                f"intake --outside: {repo} has more than {OUTSIDE_PAGE} open issues above its "
                "cut-off, more than one query reads; handle or close some, or raise its cut-off "
                "in se.toml [outside]")
        for issue in nodes:
            labels = {label["name"] for label in issue["labels"]["nodes"]}
            body = issue.get("body") or ""
            if (issue["number"] <= cutoff or FLEET_MARKER in body or HANDLED_MARKER in body
                    or FLEET_LABEL in labels or BACKLOG_LABEL in labels
                    or any(HANDLED_MARKER in (comment.get("body") or "")
                           for comment in issue["comments"]["nodes"])):
                continue
            found.append({"repo": repo, "number": issue["number"], "title": issue["title"],
                          "url": issue["url"]})
    return found


def intake_outside(root: Path) -> list[dict[str, object]]:
    """The outside issues SE has not handled yet, read in one batched query."""
    cutoffs = outside_cutoffs(root)
    host = next(iter(cutoffs)).split("/")[0]
    query = outside_query(list(cutoffs))
    return outside_issues(cutoffs, json.loads(
        run_gh(root, ["api", "graphql", "--hostname", host, "-f", f"query={query}"])))


def bare_cross_repository_references(body: str, repo: str) -> list[str]:
    """References in a work issue to another repository with no quoted block next to them.

    A cloud worker reads only its own repository, so what it needs from another one is quoted
    inline (work-model skill, "Writing work issues"): a reference counts as quoted when it sits in
    a quote or code block, follows one directly (an attribution), or the nearest non-blank line
    after it opens one. The URL form counts only on GitHub hosts (github.com, or the host of the
    work issue's own repository) and only for issue, pull request, blob and tree paths."""
    parts = [part.casefold() for part in repo.split("/")]
    own_owner, own_repo = parts[-2:]
    github_hosts = {"github.com", *parts[:-2]}
    lines = body.splitlines()
    fenced, in_block = False, []
    for line in lines:
        opens_fence = line.lstrip().startswith("```")
        in_block.append(fenced or opens_fence or line.lstrip().startswith(">"))
        fenced = fenced != opens_fence

    def quoted(index: int) -> bool:
        if in_block[index] or (index > 0 and in_block[index - 1]):
            return True
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        return index < len(lines) and in_block[index]

    bare = []
    for index, line in enumerate(lines):
        if quoted(index):
            continue
        for match in CROSS_REFERENCE_PATTERN.finditer(line):
            if match.group("host") and match.group("host").casefold() not in github_hosts:
                continue
            owner = match.group("url_owner") or match.group("owner")
            name = match.group("url_repo") or match.group("repo")
            if (owner.casefold(), name.casefold()) != (own_owner, own_repo):
                bare.append(match.group(0))
    return bare


def issue_changes(previous: dict[str, object] | None, issue: dict[str, object]) -> dict[str, object]:
    old_comments = {comment["id"]: comment for comment in (previous or {}).get("comments", [])}
    changes: dict[str, object] = {
        "issue": issue["url"],
        "number": issue["number"],
        "updatedAt": issue["updatedAt"],
        "first_read": previous is None,
        "title": None,
        "body_diff": [],
        "requirements_changed": [],
        "requirements_added": [],
        "requirements_removed": [],
        "new_comments": [c for c in issue["comments"] if c["id"] not in old_comments],
        "edited_comments": [
            c for c in issue["comments"]
            if c["id"] in old_comments and old_comments[c["id"]]["body"] != c["body"]
        ],
    }
    if previous is not None:
        if previous["title"] != issue["title"]:
            changes["title"] = [previous["title"], issue["title"]]
        changes["body_diff"] = list(difflib.unified_diff(
            previous["body"].splitlines(), issue["body"].splitlines(),
            "before", "now", lineterm="", n=1,
        ))
        old_items, new_items = requirement_items(previous["body"]), requirement_items(issue["body"])
        changes["requirements_changed"] = sorted(
            n for n in new_items if n in old_items and old_items[n] != new_items[n])
        changes["requirements_added"] = sorted(set(new_items) - set(old_items))
        changes["requirements_removed"] = sorted(set(old_items) - set(new_items))
    changes["changed"] = bool(
        changes["first_read"] or changes["title"] or changes["body_diff"]
        or changes["new_comments"] or changes["edited_comments"]
    )
    return changes


def refresh(root: Path, number: int | None, repo: str | None) -> dict[str, object]:
    previous = load_snapshot(root)
    if number is None:
        if previous is None:
            raise QueueError("No work issue recorded; pass --issue N")
        number = previous["number"]
    if repo is None and previous is not None and previous["number"] == number:
        repo = previous["repo"]
    if repo is None:
        repo = remote_repo(root)
        if repo is None:
            raise QueueError(
                "No repository: pass --repo [HOST/]OWNER/REPO or add a git remote origin")
    feedback.phase(f"read work issue #{number}")
    issue = fetch_issue(root, number, repo)
    if previous is not None and previous["number"] != number:
        previous = None
    feedback.phase("compare it with the last read")
    changes = issue_changes(previous, issue)
    save_snapshot(root, issue)
    return changes


def print_changes(changes: dict[str, object]) -> None:
    header = f"Work issue #{changes['number']} ({changes['issue']})"
    if not changes["changed"]:
        print(f"{header}: unchanged since the last read (updated {changes['updatedAt']})")
        return
    print(f"{header}: {'first read' if changes['first_read'] else 'CHANGED since the last read'}")
    if changes["title"]:
        print(f"title: {changes['title'][0]!r} -> {changes['title'][1]!r}")
    if changes["body_diff"]:
        print("body:")
        for line in changes["body_diff"]:
            print(f"  {line}")
    for key, verb in (("requirements_changed", "changed"), ("requirements_added", "added"),
                      ("requirements_removed", "removed")):
        for number in changes[key]:
            print(f"requirement {number} {verb}")
    if changes["requirements_added"]:
        print("run intake again to add tickets for added requirements")
    for key, label in (("new_comments", "comment"), ("edited_comments", "edited comment")):
        for comment in changes[key]:
            print(f"{label} by {comment['author']} at {comment['createdAt']} ({comment['url']}):")
            for line in comment["body"].splitlines():
                print(f"  {line}")


def template_name(name: str) -> str:
    """An issue template as messages name it: relative to the se checkout, never absolute."""
    return f"the se checkout's {TEMPLATE_DIRECTORY}/{name}.md"


def issue_template(name: str) -> tuple[dict[str, str], str]:
    try:
        text = (TEMPLATES / f"{name}.md").read_text(encoding="utf-8")
    except OSError as error:
        raise QueueError(f"Issue template not found: {template_name(name)}: {error}") from error
    match = FRONT_MATTER_PATTERN.match(text)
    if match is None:
        raise QueueError(f"Issue template has no front matter: {template_name(name)}")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def template_labels(value: str) -> list[str]:
    return [label.strip().strip("\"'") for label in value.strip("[]").split(",") if label.strip()]


FIELD_REPORT_TEMPLATE_NAME = f"the se checkout's {FIELD_REPORT_TEMPLATE}"


def field_report_template() -> str:
    """The pull request template, the field report's one form, markers included."""
    path = Path(__file__).resolve().parents[1] / FIELD_REPORT_TEMPLATE
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise QueueError(f"Field-report template not found: {FIELD_REPORT_TEMPLATE_NAME}: {error}") from error


def report_in(text: str, where: str) -> str:
    """The field report a pull request description (or a file holding one) carries between its
    markers; refused where it carries none."""
    begin = text.find(REPORT_BEGIN)
    end = text.find(REPORT_END, begin + len(REPORT_BEGIN)) if begin >= 0 else -1
    if begin < 0 or end < 0:
        raise QueueError(
            f"{where} holds no field report: the report goes between the lines {REPORT_BEGIN} and "
            f"{REPORT_END} of the pull request description, as {FIELD_REPORT_TEMPLATE_NAME} has "
            "them; field-report --draft --worktree <worktree> writes them"
        )
    return text[begin + len(REPORT_BEGIN):end].strip("\n") + "\n"


def marked_report(report: str) -> str:
    """`report` without its template comments, between the markers, as a description carries it."""
    cleaned = re.sub(r"\n{3,}", "\n\n", HTML_COMMENT_PATTERN.sub("", report)).strip()
    return f"{REPORT_BEGIN}\n{cleaned}\n{REPORT_END}\n"


def published_ref(root: Path, ref: str) -> str:
    """`origin/<ref>` where `ref` names a branch origin has, as `sync` fetched it; `ref` otherwise.

    `sync` merges the remote branch and never moves a local copy, which is older the longer a
    clone lives."""
    found = run_git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}")
    return f"origin/{ref}" if found.returncode == 0 else ref


def integration_ref(root: Path) -> str:
    """`origin/<integration branch>` as `sync` fetched it; the local branch only without it."""
    return published_ref(root, integration_branch(root))


def deleted_tests(root: Path, branch: str) -> list[str]:
    base = integration_ref(root)
    result = run_git(root, "diff", "--unified=0", f"{base}...{branch}")
    if result.returncode != 0:
        detail = failure_detail(result)
        raise QueueError(f"Cannot diff {base} against {branch}: {detail}")
    found: list[str] = []
    for line in result.stdout.splitlines():
        python = REMOVED_PYTHON_TEST_PATTERN.match(line)
        javascript = REMOVED_JAVASCRIPT_TEST_PATTERN.match(line)
        name = python.group(1) if python is not None else (
            javascript.group("name") if javascript is not None else None
        )
        if name is not None and name not in found:
            found.append(name)
    return found


# Text a generator writes into an authored file is marked once, where it is written: a block between
# the marker lines `generated_markers` makes for its generator, or a whole file under the notice of
# se_plugin.py's build. The landing guard reads the marks and leaves that text out.
GENERATED_BLOCK_PATTERN = re.compile(
    r"^<!-- generated by [^\n]*: begin -->$.*?^<!-- generated by [^\n]*: end -->$",
    re.DOTALL | re.MULTILINE)


def generated_markers(generator: str) -> tuple[str, str]:
    """The begin and end lines around a block `generator` writes into an authored file."""
    return f"<!-- generated by {generator}: begin -->", f"<!-- generated by {generator}: end -->"


def authored_text(text: str) -> str:
    """`text` without what a generator wrote into it: nothing of a file the build generates whole,
    and none of the marked generated blocks of any other."""
    if sibling("se_plugin").NOTICE_PATTERN.search(text):
        return ""
    return GENERATED_BLOCK_PATTERN.sub("", text)


def authored_blocks(text: str) -> list[tuple[bool, str]]:
    """`text` cut where Markdown structure ends a sentence, as (prose, block) pairs: each fenced
    block whole, each heading and block-id line alone, and the prose between them."""
    blocks: list[tuple[bool, str]] = []
    prose: list[str] = []
    fence: list[str] = []
    marker = ""

    def flush() -> None:
        if prose:
            blocks.append((True, "\n".join(prose)))
            prose.clear()

    for line in HTML_COMMENT_PATTERN.sub("", authored_text(text)).splitlines():
        if marker:
            fence.append(line)
            stripped = line.strip()
            if stripped.startswith(marker) and not stripped.strip(marker[0]):
                blocks.append((False, "\n".join(fence)))
                fence.clear()
                marker = ""
        elif (opening := FENCE_LINE_PATTERN.match(line)) is not None:
            flush()
            fence.append(line)
            marker = opening[1]
        elif HEADING_LINE_PATTERN.match(line) or BLOCK_ID_LINE_PATTERN.match(line):
            flush()
            blocks.append((False, line))
        else:
            prose.append(line)
    if fence:
        blocks.append((False, "\n".join(fence)))
    flush()
    return blocks


def authored_sentences(text: str) -> list[str]:
    """The sentences of authored `text`, whitespace collapsed: the one splitter of the guard, at
    landing and at delivery. A fenced block, a heading and a block-id line are each one sentence
    and end the one before them; in prose, code spans and URLs stay whole with their sentence."""

    def protect_dots(match: re.Match[str]) -> str:
        protected = match.group()
        trailing = protected[len(protected.rstrip(".!?")):]
        body = protected[:len(protected) - len(trailing)] if trailing else protected
        return body.replace(".", PROTECTED_DOT).replace("!", PROTECTED_BANG).replace(
            "?", PROTECTED_QUESTION
        ) + trailing

    sentences: list[str] = []
    for is_prose, block in authored_blocks(text):
        normalized = re.sub(r"\s+", " ", block).strip()
        if not normalized:
            continue
        if not is_prose:
            sentences.append(normalized)
            continue
        protected = PROTECTED_SENTENCE_CONTENT_PATTERN.sub(protect_dots, normalized)
        sentences.extend(
            sentence.replace(PROTECTED_DOT, ".").replace(PROTECTED_BANG, "!").replace(
                PROTECTED_QUESTION, "?"
            ).strip()
            for sentence in SENTENCE_PATTERN.findall(protected)
        )
    return sentences


def deleted_authored_sentences(root: Path, branch: str) -> list[str]:
    globs = authored_content_globs(root)
    if not globs:
        return []
    base = integration_ref(root)
    changed = run_git(root, "diff", "--name-status", "-z", f"{base}...{branch}")
    if changed.returncode != 0:
        detail = failure_detail(changed)
        raise QueueError(f"Cannot diff {base} against {branch}: {detail}")
    paths = changed.stdout.split("\0")
    old_files: list[tuple[str, str | None]] = []
    new_files: list[tuple[str, str | None]] = []
    index = 0
    while index < len(paths) - 1:
        status = paths[index]
        index += 1
        if status.startswith(("R", "C")):
            old_path, new_path = paths[index:index + 2]
            index += 2
        else:
            old_path = new_path = paths[index]
            index += 1
            if status == "A":
                old_path = None
            elif status == "D":
                new_path = None
        if any(
            authored_content_matches(path, glob)
            for path in (old_path, new_path)
            if path is not None
            for glob in globs
        ):
            old_files.append((old_path, base))
            new_files.append((new_path, branch))

    def content(path: str | None, revision: str) -> str:
        if path is None:
            return ""
        result = run_git(root, "show", f"{revision}:{path}")
        if result.returncode != 0:
            detail = failure_detail(result)
            raise QueueError(f"Cannot read {path} at {revision}: {detail}")
        return result.stdout

    new_sentences = {
        sentence
        for path, revision in new_files
        for sentence in authored_sentences(content(path, revision))
    }
    found: list[str] = []
    for path, revision in old_files:
        if path is None:
            continue
        for sentence in authored_sentences(content(path, revision)):
            removed = f"{path}: {sentence}"
            if sentence not in new_sentences and removed not in found:
                found.append(removed)
    return found


def authored_content_matches(path: str, glob: str) -> bool:
    pattern = re.escape(glob)
    pattern = pattern.replace(r"\*\*/", r"(?:.*/)?")
    pattern = pattern.replace(r"\*\*", r".*")
    pattern = pattern.replace(r"\*", r"[^/]*")
    pattern = pattern.replace(r"\?", r"[^/]")
    return re.fullmatch(pattern, path) is not None


def guard(root: Path, branch: str, report: str) -> list[str]:
    """The tests and authored sentences `branch` (the local branch, else `origin/<branch>`)
    removes, refused where the field report `report` does not name each under its Removed
    behaviour."""
    branch = branch_head(root, branch)
    removed_tests = deleted_tests(root, branch)
    removed_sentences = deleted_authored_sentences(root, branch)
    named = re.sub(r"\s+", " ", "\n".join(section_content(report, REMOVED_SECTION)))
    missing = [
        *[name for name in removed_tests if name not in named],
        *[sentence for sentence in removed_sentences if sentence not in named],
    ]
    if missing:
        raise QueueError(
            "Field report must name each deleted or renamed test and authored sentence: "
            + ", ".join(missing)
        )
    return [*removed_tests, *removed_sentences]


def delivery_branch(root: Path, issue: dict[str, object]) -> str:
    branch = current_branch(root)
    if branch != issue["title"]:
        raise QueueError(
            f"Branch {branch!r} does not match the work issue title {issue['title']!r}"
        )
    return branch


def open_pull_request_number(root: Path, repo: str, branch: str) -> int | None:
    data = json.loads(run_gh(
        root, [
            "pr", "list", "--head", branch, "--base", integration_branch(root), "--state", "open",
            "--json", "number,url", *repo_arguments(repo),
        ]
    ))
    return int(data[0]["number"]) if data else None


PUSH_ATTEMPTS = 10
PUSH_RETRY_SECONDS = 60
# Refusals a push never retries: the same push is refused again until something changes.
PUSH_FINAL_REFUSALS = (
    ("non-fast-forward", re.compile(r"non-fast-forward|\(fetch first\)|\[rejected\]", re.I)),
    ("permission", re.compile(
        r"permission to .* denied|permission denied|\b403\b|authentication failed|"
        r"protected branch", re.I)),
    ("pre-push hook", re.compile(r"pre-push hook declined", re.I)),
)
# Refusals GitHub withdraws on its own: the same push is accepted minutes later.
PUSH_TRANSIENT_REFUSALS = (
    ("commit_refs_rules", re.compile(r"commit_refs_rules", re.I)),
    ("HTTP 5xx", re.compile(
        r"(?:HTTP|returned error:|status)\s*5\d\d\b|\b5\d\d (?:Internal|Bad Gateway|Service|"
        r"Gateway)", re.I)),
    ("connection reset", re.compile(r"connection reset|reset by peer|unexpected disconnect", re.I)),
)
wait = time.sleep


def github_wait(seconds: float) -> None:
    """Wait `seconds` on GitHub (a retry after its refusal, a poll), counted in the run's metrics."""
    metrics.door_wait(seconds)
    wait(seconds)


def push_refusal(output: str) -> tuple[str, bool]:
    """Name a push refusal and whether it is transient; a final refusal wins over a transient one."""
    for name, pattern in PUSH_FINAL_REFUSALS:
        if pattern.search(output):
            return name, False
    for name, pattern in PUSH_TRANSIENT_REFUSALS:
        if pattern.search(output):
            return name, True
    return "unknown refusal", False


def run_git_push(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return run_git(root, "push", *arguments)


def git_push(root: Path, arguments: list[str]) -> None:
    """`git push <arguments>`, retried once a minute, ten attempts, on a transient refusal."""
    command = f"git push {' '.join(arguments)}"
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        print(f"Push attempt {attempt}/{PUSH_ATTEMPTS}: {command}")
        pushed = run_git_push(root, arguments)
        if pushed.returncode == 0:
            metrics.door_call()
            print(f"Pushed: {command}")
            return
        detail = (pushed.stderr + pushed.stdout).strip() or f"exit code {pushed.returncode}"
        refusal, transient = push_refusal(detail)
        metrics.door_call(transient)
        if not transient:
            raise QueueError(
                f"{command} refused by the remote ({refusal}, attempt {attempt}, not retried "
                f"because it is not transient): {detail}. Remedy: fix the cause first, for a "
                f"non-fast-forward run work_tickets.py sync, then work_tickets.py push again"
            )
        if attempt < PUSH_ATTEMPTS:
            print(f"Push refused ({refusal}, transient); retrying in {PUSH_RETRY_SECONDS} s: {detail}")
            github_wait(PUSH_RETRY_SECONDS)
    raise QueueError(
        f"{command} refused by the remote ({refusal}, transient) on all {PUSH_ATTEMPTS} attempts, "
        f"one every {PUSH_RETRY_SECONDS} s: {detail}. Remedy: check "
        f"GitHub's status page, then run the same command again"
    )


def push_gate(root: Path, branch: str) -> None:
    """The public check's push gate on `branch`, as the pre-push hook runs it, unless se.toml turns it off."""
    if not public_check_enabled(root):
        print(
            f"Public check off: project.public_check = false in {root / 'se.toml'}; "
            "set it to true (or remove it) to check every push"
        )
        return
    pushed = run_git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    revisions = (
        f"{pushed.stdout.strip()}..{branch}" if pushed.returncode == 0 and pushed.stdout.strip()
        else f"{branch} --not --remotes"
    )
    result = subprocess.run(
        [sys.executable, str(PUBLIC_CHECK), "--repo", str(root), "--rev", branch,
         "--range", revisions],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"
        raise QueueError(
            f"Public check failed ({PUBLIC_CHECK.name}, required by project.public_check in "
            f"se.toml); nothing was pushed. Remove the hits from {branch} or add a reasoned allow "
            f"entry, then run work_tickets.py push again: {detail}; "
            f"{PUBLIC_CHECK_OPT_OUT}{root / 'se.toml'}"
        )


RELEASE_KINDS = {
    "feature": "minor", "feat": "minor",
    "fix": "patch", "perf": "patch", "chore": "patch", "docs": "patch",
}
RELEASE_ORDER = ("patch", "minor", "major")
RELEASE_TRAILER = "Release-kind"
RELEASE_TRAILER_PATTERN = re.compile(rf"^{RELEASE_TRAILER}:[ \t]*(\S*)[ \t]*$", re.MULTILINE)
RELEASE_TRAILER_HELP = (
    "work_tickets.py release-trailer <branch> --issue-body <file> --pr-description <file> prints "
    "it from the field report in the pull request description"
)
INTEGRATION_SUBJECT_PATTERN = re.compile(r"Integrate ([^\s:()]+)")


def is_breaking(issue_body: str) -> bool:
    """Whether a work issue marks a breaking change: the word in its Package kind section."""
    kind = HTML_COMMENT_PATTERN.sub("", section(issue_sections(issue_body), "Package kind"))
    return re.search(r"\bbreaking\b", kind, re.IGNORECASE) is not None


def default_release_kind(branch: str, issue_body: str) -> str | None:
    """The kind field-report --draft proposes: major where the work issue marks a breaking change,
    else by the branch prefix; None for a prefix that names none."""
    if is_breaking(issue_body):
        return "major"
    return RELEASE_KINDS.get(branch.split("/", 1)[0] if "/" in branch else "")


def release_kind_problems(report_body: str, issue_body: str | None) -> list[str]:
    """Where the field report's Release kind, the one source of a first integration's kind, is
    missing, unknown, without its reason, or below major although the report's Removed behaviour
    lists a breaking change (a **Breaking:** line) or the work issue marks one."""
    header = HTML_COMMENT_PATTERN.sub("", "\n".join(ordered_sections(report_body)[0][1]))
    match = RELEASE_KIND_PATTERN.search(header)
    where = "header (above the first section): Release kind"
    if match is None:
        return [f"{where} is missing; write **Release kind:** patch|minor|major — <reason>, "
                "what changed decides it (work model, Release kind)"]
    kind, reason = match[1], match[2].strip()
    problems = []
    if kind not in RELEASE_ORDER:
        problems.append(f"{where} {kind!r} must be one of {', '.join(RELEASE_ORDER)}")
    if not reason:
        problems.append(f"{where} needs a one-line reason after the kind")
    if kind in RELEASE_ORDER and kind != "major":
        removed = HTML_COMMENT_PATTERN.sub("", "\n".join(section_content(report_body, REMOVED_SECTION)))
        problems.extend(
            f"{where} is {kind}, but section \"## {REMOVED_SECTION}\" lists a breaking change, "
            f"which is major: {line.strip()}"
            for line in removed.splitlines() if BREAKING_PATTERN.search(line)
        )
        if issue_body is not None and is_breaking(issue_body):
            problems.append(f"{where} is {kind}, but the work issue's Package kind marks a "
                            "breaking change, which is major")
    return problems


def declared_release_kind(branch: str, report_body: str | None, issue_body: str) -> str:
    """The kind a first integration of `branch` releases: its field report's Release kind."""
    problems = (["no field report given; pass --pr-description <file>, the pull request "
                 "description that carries it"] if report_body is None
                else release_kind_problems(report_body, issue_body))
    if problems:
        raise QueueError(f"Cannot release {branch}: " + "; ".join(problems) + "; nothing was merged")
    return RELEASE_KIND_PATTERN.search(report_body)[1]


def integrated_before(root: Path, branch: str) -> bool:
    """Whether a first-parent integration `Integrate <branch>` is already on the integration
    branch: the squash commit its landing pull request left, or a merge commit of the older
    direct path."""
    subjects = checked_git(root, "log", "--first-parent", "--format=%s", integration_branch(root))
    return any(
        (match := INTEGRATION_SUBJECT_PATTERN.match(subject)) is not None and match[1] == branch
        for subject in subjects.splitlines()
    )


def reintegration_kind(report_body: str | None) -> str:
    """The kind a field report states for a later integration of its branch; patch without one."""
    match = REINTEGRATION_KIND_PATTERN.search(report_body or "")
    if match is None:
        return "patch"
    if match[1] not in RELEASE_ORDER:
        raise QueueError(
            f"Field report states Re-integration kind {match[1]!r}; write one of "
            f"{', '.join(RELEASE_ORDER)}; nothing was merged"
        )
    return match[1]


def release_trailer(root: Path, branch: str, issue_body: str, report_body: str | None = None) -> str:
    """The trailer every integration merge carries, the one source of its release kind: the field
    report's Release kind on a first integration, and on a re-integration (an earlier merge of
    `branch` is on the integration branch) its Re-integration kind, patch without a report."""
    if integrated_before(root, branch):
        return f"{RELEASE_TRAILER}: {reintegration_kind(report_body)}"
    return f"{RELEASE_TRAILER}: {declared_release_kind(branch, report_body, issue_body)}"


def branch_head(root: Path, branch: str) -> str:
    """The ref `release-trailer`, `guard` and `integrate` read `branch` at: the local branch where
    the clone has one, else `origin/<branch>`, the ref an integrator clone that only fetched it
    has; refused with neither."""
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        if run_git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0:
            return ref.removeprefix("refs/heads/").removeprefix("refs/remotes/")
    raise QueueError(
        f"Cannot find branch {branch}: neither {branch} nor origin/{branch} exists in {root}; "
        f"fetch it with git -C {root} fetch origin {branch}, then run the command again"
    )


def reported_tip(report_body: str) -> str:
    match = BRANCH_TIP_PATTERN.search(report_body)
    if match is None:
        raise QueueError(
            "Field report names no Branch tip; the worker runs field-report --check --worktree "
            "<worktree>, which fills it from the branch, and delivers again, which updates the pull "
            "request description; nothing was merged"
        )
    return match[1]


def late_commits(root: Path, report_body: str, head: str) -> list[str]:
    """The commits on `head` the field report's Branch tip does not cover, as `<short> <subject>`:
    those after the tip that are not already on the integration branch. A merge carries none of
    its own, so a sync of the integration branch after the report is not one."""
    return checked_git(
        root, "log", "--no-merges", "--format=%h %s", head, f"^{reported_tip(report_body)}",
        f"^{integration_branch(root)}",
    ).splitlines()


def check_branch_tip(root: Path, report_body: str, branch: str, head: str,
                     included: str | None) -> list[str]:
    """Refuse where `branch` at `head` has commits past the field report's Branch tip, unless the
    integrator states in `included` why they are included; returns those commits."""
    late = late_commits(root, report_body, head)
    if late and not included:
        raise QueueError(
            f"Branch {branch} has commits after the field report's Branch tip "
            f"{reported_tip(report_body)[:12]}:\n" + "\n".join(f"- {commit}" for commit in late)
            + "\nNothing was merged. Either the worker updates the field report in place "
            "(field-report --check --worktree <worktree> fills the new tip; deliver writes it "
            "into the pull request description again), or the integrator states why the extra "
            "commits are included with --include-late <reason>"
        )
    return late


def merge_release_kind(commit: str, subject: str, message: str) -> str:
    """The release kind an integration merge states in its trailer; refused where it states none."""
    kinds = RELEASE_TRAILER_PATTERN.findall(message)
    if len(kinds) == 1 and kinds[0] in RELEASE_ORDER:
        return kinds[0]
    stated = f"states {', '.join(map(repr, kinds))}" if kinds else "states no kind"
    raise QueueError(
        f"Cannot release merge {commit[:7]} ({one_line(subject)}): it {stated}; nothing was "
        f"written. Reword the merge to end with one trailer {RELEASE_TRAILER}: "
        f"{'|'.join(reversed(RELEASE_ORDER))}, as {RELEASE_TRAILER_HELP}, then push again"
    )


def bumped(version: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = version
    return {
        "major": (major + 1, 0, 0), "minor": (major, minor + 1, 0), "patch": (major, minor, patch + 1),
    }[kind]


def failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    """What a failed command said on stderr, or its exit code where it said nothing."""
    return result.stderr.strip() or f"exit code {result.returncode}"


REMOTE_GIT = {"fetch", "ls-remote", "pull"}  # git commands that read a remote, announced


def run_git(root: Path, *arguments: str,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if arguments and arguments[0] in REMOTE_GIT:
        feedback.reading("the remote", ["git", *arguments])
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env,
    )


def checked_git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    result = run_git(root, *arguments, env=env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        raise QueueError(f"git {' '.join(arguments)} failed in {root}: {detail}")
    return result.stdout


def local_tag(root: Path, tag: str) -> str | None:
    """The commit the local tag `tag` names, or None without it."""
    result = run_git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def remote_tags(root: Path) -> dict[str, str]:
    """Each tag on origin and the commit it names, read with `git ls-remote --tags`; local tags,
    which may be stale, are never read."""
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in checked_git(root, "ls-remote", "--tags", "origin").splitlines():
        commit, _, ref = line.partition("\t")
        name = ref.strip().removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = commit
        else:
            tags[name] = commit
    return tags | peeled


def integrated_packages(root: Path, branch: str, released: str,
                        upstream_ref: str | None = None) -> list[tuple[str, str]]:
    """(branch, release kind) of each integration on `branch` since `upstream_ref` (default:
    origin's `branch`) and the commit `released`, the last release's.

    An integration is a first-parent commit whose subject starts `Integrate <branch>`, the message
    integrate writes: the merge it builds, or the squash commit that merge landed as; its kind is
    its Release-kind trailer, and one without it is refused. Other merges release nothing and are
    named."""
    upstream = run_git(root, "rev-parse", "--verify", "--quiet",
                       upstream_ref or f"refs/remotes/origin/{branch}")
    revisions = [f"^{upstream.stdout.strip()}"] if upstream.returncode == 0 else ["--not", "--remotes", "--not"]
    log = checked_git(
        root, "log", "--first-parent", "--format=%H%x00%P%x00%B%x1e",
        branch, f"^{released}", *revisions,
    )
    packages = []
    for record in filter(str.strip, log.split("\x1e")):
        commit, _, rest = record.strip().partition("\x00")
        parents, _, message = rest.partition("\x00")
        subject = message.splitlines()[0] if message else ""
        match = INTEGRATION_SUBJECT_PATTERN.match(subject)
        if match is None:
            if len(parents.split()) > 1:
                print(f"Release: merge {commit[:7]} ({one_line(subject)}) is no integration; it bumps nothing")
            continue
        packages.append((match[1], merge_release_kind(commit, subject, message)))
    return list(reversed(packages))


def set_project_version(root: Path, version: str) -> None:
    """Rewrite only the `version` value of `[project]` in se.toml, keeping the rest byte for byte."""
    path = root / "se.toml"
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    inside = False
    for index, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        if re.match(r"\s*\[", bare):
            inside = re.match(r"\s*\[\s*project\s*\]\s*(?:#.*)?$", bare) is not None
            continue
        match = re.match(r"""(\s*version\s*=\s*)(["'])[^"']*\2""", bare) if inside else None
        if match:
            lines[index] = f"{match[1]}{match[2]}{version}{match[2]}{line[match.end():]}"
            path.write_bytes("".join(lines).encode("utf-8"))
            return
    raise QueueError(f"{path}: write project.version as version = \"MAJOR.MINOR.PATCH\" inside [project]")


def release_build(root: Path) -> list[str] | None:
    """`project.release_build` in se.toml: the command that regenerates what copies the version."""
    configured = project_config(root).get("release_build")
    if configured is not None and not is_argument_array(configured):
        raise QueueError(
            f"project.release_build in {root / 'se.toml'} must be a non-empty argument array, the "
            'command that regenerates what copies the version, for example release_build = '
            '["uv", "run", "python", "scripts/se_plugin.py", "build"]; fix it or remove it'
        )
    return configured


def changed_paths(root: Path) -> set[str]:
    """The paths `git status` names as changed or untracked in the checkout."""
    status = checked_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = status.split("\0")
    paths, index = set(), 0
    while index < len(entries):
        entry = entries[index]
        if entry:
            paths.add(entry[3:])
            if entry[0] in "RC":
                index += 1  # a rename's or copy's source follows it
        index += 1
    return paths


def build_release(root: Path, tag: str) -> list[str]:
    """Write `tag`'s version into se.toml and run `project.release_build`, if set; the paths the
    release commit carries. A failing build restores se.toml and is refused with its output."""
    command = release_build(root)
    before = changed_paths(root)
    set_project_version(root, tag[1:])
    if command is None:
        return ["se.toml"]
    result = subprocess.run(command, cwd=root, shell=False, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        checked_git(root, "checkout", "HEAD", "--", "se.toml")
        output = (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"
        raise QueueError(
            f"Cannot release {tag}: project.release_build ({' '.join(command)}) failed in {root}; "
            f"se.toml is restored and nothing was committed. Fix the build and push again:\n{output}"
        )
    return sorted({"se.toml"} | (changed_paths(root) - before))


def release(root: Path, branch: str, upstream_ref: str | None = None) -> str | None:
    """Release what was integrated into `branch` since `upstream_ref` (default: origin's
    `branch`): bump project.version by the packages' highest kind, commit it with what
    `project.release_build` regenerates and tag `v<version>`; the tag to push, or None where
    nothing is released.
    Where the release workflow tags, the released versions are origin's tags, and a version without
    its tag there is left for the workflow to tag."""
    by_workflow = release_by_workflow(root)
    version = project_version(root)
    if version is None:
        print(f"Release off: no project.version in {root / 'se.toml'}; {VERSION_REMEDY} to tag each integration")
        return None
    origin = remote_tags(root) if by_workflow else None

    def tagged(tag: str) -> str | None:
        return origin.get(tag) if origin is not None else local_tag(root, tag)

    current = f"v{version_text(version)}"
    released = tagged(current)
    if released is None:
        if by_workflow:
            return current
        checked_git(root, "tag", current, branch)
        print(f"Release: {current} tagged, the first tag of project.version")
        return current
    packages = integrated_packages(root, branch, released, upstream_ref)
    if not packages:
        pushed = run_git(root, "merge-base", "--is-ancestor", released,
                         upstream_ref or f"refs/remotes/origin/{branch}")
        return None if pushed.returncode == 0 else current
    kind = max((kind for _, kind in packages), key=RELEASE_ORDER.index)
    tag = f"v{version_text(bumped(version, kind))}"
    if tagged(tag) is not None:
        raise QueueError(
            f"Cannot release {tag}: the tag exists already; fetch the tags (work_tickets.py sync) "
            f"and check project.version in {root / 'se.toml'}"
        )
    environment = identity_environment(required_identity(root, "push"))
    paths = build_release(root, tag)
    trailer = config_value("commit_trailer", remote_repo(root), None)
    checked_git(root, "add", "--", *paths)
    checked_git(root, "commit", "-q", "-m", f"Release {tag}", *(("-m", trailer) if trailer else ()),
                env=environment)
    sibling("verdicts").carry(root, SUITE_VERDICT, "HEAD~1", "HEAD")
    if not by_workflow:
        checked_git(root, "tag", tag)
    print(f"Release: {tag} ({kind}: {', '.join(name for name, _ in packages)})")
    return tag


def push(root: Path, branch: str | None = None) -> str | None:
    """Gate `branch` (default: the current one), then push it to origin with its upstream set; the
    integration branch is released first and its new tag pushed with it, unless the release
    workflow pushes the tags (`project.release = "workflow"`). A landing branch `land/<branch>`
    (README "Landing on main") is released the same way against origin's integration branch and,
    like it, needs the verdicts on its tree; its tag waits for the squash commit. Returns the
    release's tag, None where nothing is released."""
    required_identity(root, "push")
    branch = branch or current_branch(root)
    target = integration_branch(root)
    landing = branch.startswith(LANDING_PREFIX)
    released = tag = (release(root, branch) if branch == target
                      else release(root, branch, f"refs/remotes/origin/{target}") if landing
                      else None)
    if tag and release_by_workflow(root):
        workflow_tags(tag)
        tag = None
    if tag and landing:
        print(f"Release: tag {tag} once the squash commit is on {target}; it is not pushed now")
        tag = None
    push_gate(root, branch)
    if branch == target or landing:
        guard_pushed_tree(root, branch)
    git_push(root, ["-u", "origin", branch, *((f"refs/tags/{tag}",) if tag else ())])
    return released


# Acceptance that can only be seen after the merge: a run, release or deployment on the integration
# branch. A pull request then names its issue without a closing keyword, and the integrator closes it.
POST_MERGE_PATTERN = re.compile(
    r"\bafter (?:the |a |its )?(?:merge|integration)\b|\bpost-merge\b|"
    r"\bon (?:main|the integration branch)\b|\breleased?\b(?!-)|\bdeploy(?:ed|ment|s)?\b",
    re.IGNORECASE,
)


def post_merge_acceptance(body: str) -> list[str]:
    """The work issue's acceptance lines that can only be seen after the merge."""
    return [
        line.strip() for line in section(issue_sections(body), "acceptance").splitlines()
        if POST_MERGE_PATTERN.search(line)
    ]


def pull_request_body(issue: dict[str, object], report: str) -> str:
    """The pull request description: `Fixes <issue>` where all its acceptance shows before the
    merge, else `Refs <issue>`, so GitHub never closes an issue before its acceptance can be seen;
    then the field report `report` between its markers, without the template's comments."""
    keyword = "Refs" if post_merge_acceptance(str(issue.get("body", ""))) else "Fixes"
    return f"{keyword} {issue['url']}\n\n{marked_report(report)}"


def deliver(root: Path) -> int:
    """Sync, check the field report, push, and open or update the pull request whose description
    carries the report; returns the pull request's number. No issue is filed."""
    issue = required_snapshot(root)
    check_issue_read(root, None, None, str(issue["url"]))
    branch = delivery_branch(root, issue)
    sync(root)
    file = root / ".se" / "work" / "field-report.md"
    if not file.exists():
        draft_field_report(root, file)
    report = checked_report(root, file, str(issue["body"]))
    if f"#{issue['number']}" not in report and str(issue["url"]) not in report:
        raise field_report_error(file.name, [f"does not link work issue #{issue['number']}"])
    remote = remote_repo(root)
    if remote is None:
        raise QueueError(
            f"deliver: {root} has no origin remote to push {branch} to and open its pull request "
            "on; add it with git remote add origin <url>"
        )
    push(root, branch)
    pr = open_pull_request_number(root, remote, branch)
    body = pull_request_body(issue, report)
    if pr is None:
        output = run_gh_with_body(
            root,
            ["pr", "create", "--base", integration_branch(root), "--head", branch, "--title", branch,
             *repo_arguments(remote)],
            body,
        )
        match = re.search(r"/pull/(\d+)\b", output)
        if match is None:
            raise QueueError("Pull request creation did not return a pull request URL")
        return int(match.group(1))
    run_gh_with_body(root, ["pr", "edit", str(pr), "--title", branch, *repo_arguments(remote)], body)
    return pr


# The Stop hook: a worker's turn ends only with its work issue delivered (README "Stop hook").
STOP_REFUSALS = 5
STOP_COUNT = "stop-refusals.json"
DELIVERED_PULL = "pull-request.json"
WORKER_AGENT = "worker"


class CannotJudge(QueueError):
    """The Stop hook cannot tell whether the work is delivered; it lets the turn end."""


@dataclass(frozen=True)
class StopVerdict:
    """What the Stop hook answers: `block`, the reason the agent reads, or a pass; `note` says
    why a pass let the turn end where that needs saying."""

    block: str | None = None
    note: str | None = None

    def hook_output(self) -> str:
        """The hook's JSON on stdout: a block with its reason, a pass with its note, or nothing."""
        if self.block is not None:
            return json.dumps({"decision": "block", "reason": self.block})
        return json.dumps({"systemMessage": self.note}) if self.note else ""


def stop_refusals(root: Path) -> int:
    """`[stop] refusals` in se.toml: how often in a row the Stop hook refuses; built in 5."""
    value = se_table(root, "stop").get("refusals", STOP_REFUSALS)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QueueError(f"stop.refusals in {root / 'se.toml'} must be a positive whole number; "
                         f"fix it or remove it for the built-in {STOP_REFUSALS}")
    return value


def checkout_top(path: Path) -> Path | None:
    """The top of the git checkout holding `path`; None outside one."""
    if not path.is_dir():
        return None
    result = run_git(path, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def has_work_issue(root: Path) -> bool:
    """Whether the checkout's ticket queue is for a work issue: intake's snapshot, or what the
    worker recorded as read of it without gh (comments-read, body-read)."""
    work = root / ".se" / "work"
    return any((work / name).is_file() for name in (ISSUE_SNAPSHOT, COMMENTS_READ, BODY_READ))


def is_worker_agent(event: dict[str, object]) -> bool:
    """Whether a SubagentStop's sub-agent is a worker (`worker`, `se:worker`); a sub-agent the
    event does not name is not judged."""
    agent = event.get("agent_type")
    return isinstance(agent, str) and agent.rsplit(":", 1)[-1] == WORKER_AGENT


# Where a worker sub-agent works: the checkout its prompt names, else the one whose ticket queue its
# transcript last touched (a path into `.se/work/`, or `--worktree <path>`).
PROMPT_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s\"'`<>|*?()\[\]{},;]+")
QUEUE_TOUCH = re.compile(
    r"((?:[A-Za-z]:)?[\\/][^\s\"'`<>|*?]*?)[\\/]\.se[\\/]work(?![\w.-])"
    r"|--worktree[= ]+[\"']?((?:[A-Za-z]:)?[\\/][^\s\"'`<>|*?]+)")


def transcript_entries(path: object) -> list[dict[str, object]]:
    """The entries of a Claude Code transcript (JSON lines); [] where it cannot be read."""
    if not isinstance(path, str) or not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def texts_of(value: object) -> list[str]:
    """Every string in a JSON value, in order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in texts_of(item)]
    if isinstance(value, list):
        return [text for item in value for text in texts_of(item)]
    return []


def work_checkout(candidate: str) -> Path | None:
    """The checkout holding `candidate` where its ticket queue is for a work issue."""
    path = Path(candidate.rstrip(".:"))
    try:
        top = checkout_top(path) if path.is_absolute() else None
    except OSError:
        return None
    return top if top is not None and has_work_issue(top) else None


def subagent_checkout(event: dict[str, object]) -> Path | None:
    """The checkout a worker sub-agent works in, from the sub-agent itself: a checkout its prompt
    (its transcript's first user entry) names, else the one whose ticket queue its transcript last
    touched; None where neither names a checkout whose queue is for a work issue."""
    entries = transcript_entries(event.get("agent_transcript_path"))
    prompt = next((entry for entry in entries if entry.get("type") == "user"), None)
    for text in texts_of((prompt or {}).get("message")):
        for candidate in PROMPT_PATH.findall(text):
            if (found := work_checkout(candidate)) is not None:
                return found
    for entry in reversed(entries):
        for text in reversed(texts_of(entry.get("message"))):
            for queue_path, worktree in reversed(QUEUE_TOUCH.findall(text)):
                if (found := work_checkout(queue_path or worktree)) is not None:
                    return found
    return None


def delivered_pull_path(root: Path) -> Path:
    return root / ".se" / "work" / DELIVERED_PULL


def record_delivered_pull(root: Path, number: int, description: Path) -> None:
    """Keep the pull request the session's GitHub tools opened, the Stop hook's answer file
    without gh: its number, its description as they read it, and the branch it is from."""
    body = read_file(description, "pull request description")
    path = delivered_pull_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"number": number, "branch": current_branch(root), "body": body},
                               indent=2) + "\n", encoding="utf-8", newline="\n")


def delivered_pull(root: Path, branch: str) -> tuple[int, str] | None:
    """The branch's open pull request to the integration branch and its description: read with
    gh, or without gh from the answer file `stop-check --pull` keeps; None where there is none.
    Refused as unjudgeable without gh and without an answer file for the branch."""
    if gh_usable():
        remote = remote_repo(root)
        if remote is None:
            raise CannotJudge(f"{root} has no origin remote to look for the pull request on")
        number = open_pull_request_number(root, remote, branch)
        if number is None:
            return None
        data = json.loads(run_gh(root, ["pr", "view", str(number), "--json", "body",
                                        *repo_arguments(remote)]))
        return number, str(data.get("body") or "")
    path = delivered_pull_path(root)
    try:
        recorded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        recorded = None
    if not isinstance(recorded, dict) or recorded.get("branch") != branch:
        raise CannotJudge(
            "gh is not usable and no pull request is recorded for this branch (stop-check --pull "
            "<number> --pr-description <file> records the one your GitHub tools opened)")
    return int(recorded["number"]), str(recorded.get("body") or "")


def script_command(root: Path, words: str) -> str:
    """`words` as the command line that runs this script on the checkout `root`."""
    return f"uv run python {Path(__file__).resolve()} {words} --worktree {root}"


def delivery_problem(root: Path, branch: str) -> str | None:
    """What keeps the branch from being delivered, with the commands that deliver it; None where an
    open pull request carries a field report that passes field-report --check at the branch tip."""
    report_file = root / ".se" / "work" / "field-report.md"
    check = script_command(root, f"field-report --check {report_file}")
    deliver_line = (
        f"check it with `{check}` and deliver with `{script_command(root, 'deliver')}`; without "
        f"gh, open or update the pull request with your GitHub tools as {WITHOUT_GH} says and "
        f"record it with `{script_command(root, 'stop-check --pull <number> --pr-description <file>')}`."
        " A worker that cannot finish delivers what it has, naming the rest under Not delivered"
    )
    pull = delivered_pull(root, branch)
    if pull is None:
        return (f"Branch {branch} has no open pull request to {integration_branch(root)}: the work "
                f"issue is not delivered. Complete {report_file}, {deliver_line}.")
    number, body = pull
    try:
        report = report_in(body, f"Pull request #{number}'s description")
    except QueueError as error:
        return f"{error}. Complete {report_file}, {deliver_line}."
    snapshot = load_snapshot(root)
    problems = field_report_problems(report, None if snapshot is None else str(snapshot["body"]))
    match = BRANCH_TIP_PATTERN.search(report)
    tip = branch_tip(root)
    if match is None or tip is None or not same_commit(match[1], tip):
        problems.append(f"its Branch tip is not the branch's commit {(tip or '')[:12]}: "
                        "a commit after delivery needs the check and the delivery again")
    if not problems:
        try:
            guard(root, branch, report)
        except QueueError as error:
            problems.append(str(error))
    if not problems:
        return None
    return (f"Pull request #{number}'s field report does not pass field-report --check:\n"
            + "\n".join(f"- {problem}" for problem in problems)
            + f"\nFix {report_file}, {deliver_line}.")


def stop_count_path(root: Path) -> Path:
    return root / ".se" / "work" / STOP_COUNT


def stop_count(root: Path) -> int:
    try:
        value = json.loads(stop_count_path(root).read_text(encoding="utf-8")).get("refused", 0)
    except (OSError, UnicodeError, ValueError, AttributeError):
        return 0
    return value if isinstance(value, int) and value > 0 else 0


def set_stop_count(root: Path, count: int) -> None:
    path = stop_count_path(root)
    if count <= 0:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"refused": count}) + "\n", encoding="utf-8", newline="\n")


def stop_verdict(path: Path, event: dict[str, object], count: bool = True) -> StopVerdict:
    """The Stop hook's verdict for the checkout holding `path`: refuse while a worker's work issue
    is not delivered, at most `[stop] refusals` times in a row; everywhere else, and where it cannot
    judge, let the turn end (advice fails open). `count` false judges without counting."""
    if event.get("hook_event_name") == "SubagentStop" and not is_worker_agent(event):
        return StopVerdict()
    root = checkout_top(path)
    if root is None or not has_work_issue(root):
        if event.get("hook_event_name") == "SubagentStop":
            return StopVerdict(note=(
                "se Stop hook: cannot judge the worker sub-agent's delivery, so it may end: "
                "neither its prompt nor its transcript names a checkout whose ticket queue is for "
                f"a work issue, and its working directory {path} holds none"))
        return StopVerdict()
    try:
        branch = current_branch(root)
        if not branch or branch == integration_branch(root):
            return StopVerdict()
        problem = delivery_problem(root, branch)
        cap = stop_refusals(root)
    except Exception as error:  # advice fails open, whatever broke
        return StopVerdict(note=f"se Stop hook: cannot judge the delivery, so the turn may end: "
                                f"{one_line(str(error), 300)}")
    if not count:
        return StopVerdict(block=problem)
    if problem is None:
        set_stop_count(root, 0)
        return StopVerdict()
    refused = stop_count(root) + 1
    if refused > cap:
        set_stop_count(root, 0)
        return StopVerdict(note=f"se Stop hook: refused {cap} times in a row; the turn may end "
                                f"undelivered: {one_line(problem, 300)}")
    set_stop_count(root, refused)
    return StopVerdict(block=f"se Stop hook ({refused} of {cap} in a row): {problem}")


def hook_event() -> dict[str, object]:
    """The hook's JSON on stdin; {} where there is none."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        data = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def block(root: Path, number: int, blocker: int, repo: str | None) -> None:
    issue = fetch_issue(root, number, resolve_repo(root, repo))
    target_repo = issue["repo"]
    hostname = repo_host(target_repo)
    hostname_argument = ["--hostname", hostname] if hostname else []
    blocker_id = run_gh(
        root,
        [
            "api", f"repos/{api_repo(target_repo)}/issues/{blocker}",
            *hostname_argument, "--jq", ".id",
        ],
    ).strip()
    try:
        internal_blocker_id = int(blocker_id)
    except ValueError as error:
        raise QueueError(f"Cannot determine the internal id of blocker #{blocker}") from error
    run_gh(
        root,
        [
            "api", f"repos/{api_repo(target_repo)}/issues/{number}/dependencies/blocked_by", "-X", "POST",
            *hostname_argument, "-F", f"issue_id={internal_blocker_id}",
        ],
    )
    sections = markdown_sections(issue["body"])
    blocked = sections.get("blocked by", "")
    entries = [line for line in blocked.splitlines() if line.strip()]
    reference = f"#{blocker}"
    if reference not in entries:
        entries.append(reference)
    replacement = "## Blocked by\n\n" + "\n".join(entries).rstrip() + "\n"
    body = issue["body"]
    pattern = r"^## Blocked by\s*\n.*?(?=^## |\Z)"
    if re.search(pattern, body, flags=re.MULTILINE | re.DOTALL):
        body = re.sub(pattern, replacement + "\n", body, flags=re.MULTILINE | re.DOTALL)
    else:
        body = body.rstrip() + "\n\n" + replacement
    run_gh_with_body(
        root, ["issue", "edit", str(number), *repo_arguments(target_repo)], body
    )


def issue_api(root: Path, repo: str, path: str) -> dict[str, object]:
    arguments = ["api", f"repos/{api_repo(repo)}/{path}"]
    hostname = repo_host(repo)
    if hostname:
        arguments.extend(["--hostname", hostname])
    try:
        return json.loads(run_gh(root, arguments))
    except json.JSONDecodeError as error:
        raise QueueError(f"GitHub returned invalid JSON for {path}") from error


def mark_in_progress(root: Path, number: int, repo: str) -> None:
    run_gh(
        root,
        [
            "issue",
            "edit",
            str(number),
            "--remove-label",
            "ready",
            "--add-label",
            "in-progress",
            *repo_arguments(repo),
        ],
    )


def start(
    root: Path,
    number: int,
    repo: str | None,
    worktree_root: str | None,
    create: bool,
    cloud_agent: str | None = None,
) -> Path | None:
    """Starts a startable work issue, locally or with a cloud worker."""
    repo = resolve_repo(root, repo)
    refuse_while_paused("start", pause_issues(root, repo))
    candidates = (
        ready_issues(root, repo, allow_existing_branch=True)
        if not create else ready_issues(root, repo)
    )
    issue = next(
        (candidate for candidate in candidates if candidate["number"] == number),
        None,
    )
    if issue is None:
        raise QueueError(f"Issue #{number} is not startable")
    slots = capacity(root, repo)
    if slots is not None and slots <= 0:
        raise QueueError(f"Issue #{number} is not startable: local capacity is exhausted")

    cloud = os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or cloud_agent is not None
    agent = cloud_agent or os.environ.get("SE_CLOUD_AGENT", "")
    if cloud:
        if not agent:
            raise QueueError("Cloud start requires --cloud-agent or SE_CLOUD_AGENT")
        run_gh(
            root,
            [
                "issue",
                "edit",
                str(number),
                "--add-assignee",
                agent,
                "--remove-label",
                "ready",
                "--add-label",
                "in-progress",
                *repo_arguments(repo),
            ],
        )
        return None

    branch = str(issue["title"])
    path = None
    if create:
        sync(root)
        directory = configured_worktree_root(root, worktree_root)
        directory_path = (
            Path(directory).expanduser().resolve()
            if directory is not None else default_worktree_root(root)
        )
        try:
            directory_path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise QueueError(f"Cannot create worktree root {directory_path}: {error}") from error
        path = directory_path / branch.replace("/", "-")
        if path.exists():
            raise QueueError(f"Worktree path already exists: {path}")
        for arguments in (("fetch", "origin"),
                          ("worktree", "add", "-b", branch, str(path),
                           f"origin/{integration_branch(root)}")):
            result = run_git(root, *arguments)
            if result.returncode != 0:
                detail = failure_detail(result)
                raise QueueError(f"git {arguments[0]} failed: {detail}")
    else:
        listed = run_git(root, "worktree", "list", "--porcelain")
        if listed.returncode != 0:
            detail = failure_detail(listed)
            raise QueueError(f"Cannot list worktrees: {detail}")
        worktree = ""
        path = None
        for line in listed.stdout.splitlines():
            if line.startswith("worktree "):
                worktree = line.removeprefix("worktree ")
            elif line == f"branch refs/heads/{branch}" and worktree:
                path = Path(worktree).resolve()
                break
        if path is None:
            raise QueueError(f"No worktree exists for branch {branch}")
        if current_branch(path) != branch:
            raise QueueError(f"Worktree {path} is not on branch {branch}")
        sync(path)
    mark_in_progress(root, number, repo)
    return path


def issue_labels(issue: dict[str, object]) -> set[str]:
    """Label names, from gh's and the REST API's objects or the GitHub tools' strings."""
    return {
        str(label.get("name", "")) if isinstance(label, dict) else str(label)
        for label in issue.get("labels", [])
    }


def repository_label(root: Path) -> str:
    return f"repo:{repository_name(root)}"


def repository_label_arguments(root: Path, all_repos: bool) -> list[str]:
    return [] if all_repos else ["--label", repository_label(root)]


def issue_ownership(issue: dict[str, object]) -> set[str]:
    value = section(issue_sections(str(issue.get("body", ""))), "file ownership")
    return {
        line.strip("` -")
        for line in value.splitlines()
        if line.strip() and line.strip().lower() not in {"none", "n/a"}
    }


def branch_exists(root: Path, branch: str) -> bool:
    local = run_git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if local.returncode == 0:
        return True
    origin = run_git(root, "remote", "get-url", "origin")
    if origin.returncode != 0:
        return False
    remote = run_git(root, "ls-remote", "--heads", "origin", branch)
    if remote.returncode != 0:
        raise QueueError(f"Cannot check whether branch {branch} exists")
    return bool(remote.stdout.strip())


def concurrently(*calls: Callable[[], object]) -> list[object]:
    """The results of `calls`, in their order, made at the same time: reads that wait on GitHub
    wait once, not once each. The first exception raised is raised."""
    if len(calls) < 2:
        return [call() for call in calls]
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        return [future.result() for future in futures]


def ready_issues(
    root: Path, repo: str, all_repos: bool = False, allow_existing_branch: bool = False
) -> list[dict[str, object]]:
    """The startable work issues: open, `work` and `ready`, not held, unblocked, with no branch
    yet and no file ownership an issue in progress holds. The two listings are read at once,
    then each candidate's blockers and branch at once."""
    labels = repository_label_arguments(root, all_repos)
    candidates, active = (json.loads(listing) for listing in concurrently(
        lambda: run_gh(root, [
            "issue", "list", "--state", "open", "--label", "work", "--label", "ready",
            "--json", "number,title,body,labels", "--limit", "200", *labels, *repo_arguments(repo),
        ]),
        lambda: run_gh(root, [
            "issue", "list", "--state", "open", "--label", "in-progress",
            "--json", "number,title,body,labels", "--limit", "200", *labels, *repo_arguments(repo),
        ]),
    ))
    active_ownership = set().union(*(issue_ownership(item) for item in active))
    startable = [candidate for candidate in candidates
                 if not issue_labels(candidate) & NOT_STARTABLE_LABELS
                 and not issue_ownership(candidate) & active_ownership]

    def ready(candidate: dict[str, object]) -> bool:
        detail = issue_api(root, repo, f"issues/{int(candidate['number'])}")
        blockers = int((detail.get("issue_dependencies_summary") or {}).get("blocked_by", 0))
        return blockers == 0 and (allow_existing_branch
                                  or not branch_exists(root, str(candidate["title"])))

    verdicts = concurrently(*(lambda candidate=candidate: ready(candidate)
                              for candidate in startable))
    return [candidate for candidate, verdict in zip(startable, verdicts) if verdict]


def capacity(root: Path, repo: str | None, all_repos: bool = False) -> int | None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return None
    if repo is None:
        raise QueueError("No repository for local capacity")
    active = json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", "work", "--label", "in-progress",
        "--json", "number", "--limit", "200",
        *repository_label_arguments(root, all_repos), *repo_arguments(repo),
    ]))
    slots = max(1, (os.cpu_count() or 1) // LOCAL_CORES_PER_WORKER)
    if sys.platform == "win32":
        import ctypes
        memory = ctypes.c_ulonglong()
        if not ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(memory)):
            raise QueueError("Cannot determine physical memory for local capacity")
        memory_slots = max(1, (memory.value // 1024) // LOCAL_MEMORY_MIB_PER_WORKER)
    else:
        memory_slots = slots
    slots = min(slots, memory_slots)
    return max(0, slots - len(active))


def delivered_pull_requests(root: Path, repo: str) -> list[dict[str, object]]:
    """Delivered, waiting for integration: the open pull requests to the integration branch whose
    description carries a complete field report, one that follows its form."""
    pulls = json.loads(run_gh(root, [
        "pr", "list", "--state", "open", "--base", integration_branch(root),
        "--json", "number,title,url,body", "--limit", "200", *repo_arguments(remote_repo(root) or repo),
    ]))
    delivered = []
    for pull in pulls:
        try:
            report = report_in(str(pull.get("body") or ""), f"pull request #{pull['number']}")
        except QueueError:
            continue
        if not field_report_problems(report, None):
            delivered.append(pull)
    return delivered


def queue(
    root: Path, repo: str, all_repos: bool = False
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], int | None]:
    """The integrator's queue: the delivered pull requests, the escalations, the startable work
    issues and the capacity, read at once with the pause switch while the checkout syncs (within
    the interactive budget, feedback.py); refused while the fleet is paused."""
    labels = repository_label_arguments(root, all_repos)
    pause, _, escalations, delivered, ready, slots = concurrently(
        lambda: pause_issues(root, repo),
        lambda: sync(root),
        lambda: json.loads(run_gh(root, [
            "issue", "list", "--state", "open", "--label", "escalated",
            "--json", "number,title,url", "--limit", "200", *labels, *repo_arguments(repo),
        ])),
        lambda: delivered_pull_requests(root, repo),
        lambda: ready_issues(root, repo, all_repos),
        lambda: capacity(root, repo, all_repos),
    )
    refuse_while_paused("queue", pause)
    return delivered, escalations, ready, slots


def quoted(text: str) -> str:
    lines = text.splitlines() or [""]
    if all(line.startswith(">") or not line.strip() for line in lines):
        return text
    return "\n".join(f"> {line}".rstrip() for line in lines)


def draft_field_report(root: Path, file: Path, issue_file: Path | None = None) -> None:
    """Write the field-report template, markers included, to `file` with the work issue, branch,
    integration-branch commit, branch tip, proposed release kind and user requirement filled in;
    the work issue from intake's snapshot, or from `issue_file`, as the session's GitHub tools
    read it."""
    issue = required_snapshot(root) if issue_file is None else issue_record(issue_answer(issue_file), [])
    branch = delivery_branch(root, issue)
    body = field_report_template().replace("#<n>", f"#{issue['number']}", 1)
    kind = default_release_kind(branch, str(issue["body"]))
    if kind is not None:
        body = body.replace("**Release kind:** <kind>", f"**Release kind:** {kind}", 1)
    body = (body.replace("<integration branch>", integration_branch(root))
            .replace("<branch>", branch).replace("<commit>", tested_main(root)))
    requirement = section(issue_sections(issue["body"]), "user requirement")
    if requirement:
        body = re.sub(
            r"(^## User requirement[^\n]*\n(?:\s*<!--.*?-->)?\s*\n)>[ \t]*$",
            lambda match: match.group(1) + quoted(requirement),
            body, count=1, flags=re.MULTILINE | re.DOTALL,
        )
    index = discovery_index(root)
    if index is not None:
        relative_index = index.relative_to(root).as_posix()
        body = body.replace(
            "## Delivered\n\n",
            f"## Delivered\n\n[Discovery evidence index]({relative_index})\n\n",
            1,
        )
    with file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(with_branch_tip(root, body.lstrip("\n")))


def ordered_sections(body: str) -> list[tuple[str, list[str]]]:
    """The body's `## ` sections in order, outside code fences; the header above them is ``""``."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else SECTION_PATTERN.fullmatch(line)
        if heading:
            sections.append((heading.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    return sections


def table_cells(line: str) -> list[str]:
    """A Markdown table row's cells; an escaped pipe `\\|` stays inside its cell."""
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def label_pattern(label: str) -> re.Pattern[str]:
    """A template field label such as **Tested against `<integration branch>`:** as a regex."""
    parts = re.split(r"<[^<>\n]+>", label)
    return re.compile(r"\*\*" + r"[^*\n]+?".join(map(re.escape, parts)) + r"\*\*")


def field_report_problems(body: str, issue_body: str | None) -> list[str]:
    """Where the field report `body` departs from the pull request template, the one owner of its
    form (the report between the markers).

    Every section the template has, every bold field label it writes (`**Result:**`,
    `**Commit groupings:**`), every table's header row and width, the header's placeholders and
    Result, and, given the work issue's body, the evidence gate. A section whose template text
    allows "None" may say only that.
    """
    template = report_in(field_report_template(), FIELD_REPORT_TEMPLATE_NAME)
    report = {heading.casefold(): lines for heading, lines in ordered_sections(body)}
    if issue_body is not None:
        tip = BRANCH_TIP_PATTERN.search("\n".join(report.get("", [])))
        issue_body = without_open_points(issue_body, tip[1] if tip else None)
    problems: list[str] = []
    for heading, raw in ordered_sections(template):
        where = "header (above the first section)" if not heading else f'section "## {heading}"'
        lines = report.get(heading.casefold())
        if lines is None:
            problems.append(f'missing {where}; the template has the heading "## {heading}"')
            continue
        text = HTML_COMMENT_PATTERN.sub("", "\n".join(lines))
        expected = HTML_COMMENT_PATTERN.sub("", "\n".join(raw)).splitlines()
        if '"None"' in "\n".join(raw) and text.strip().rstrip(".").casefold() == "none":
            continue
        for line in expected:
            for label in re.findall(r"\*\*([^*\n]+?:)\*\*", line):
                if label_pattern(label).search(text) is None:
                    problems.append(
                        f'{where}: missing "**{label}**"; the template\'s line: {line.strip()}'
                    )
        template_header = next((line.strip() for line in expected if line.strip().startswith("|")), None)
        if template_header is not None:
            problems.extend(table_problems(where, template_header, text))
    header = "\n".join(report[""])
    problems.extend(
        f'header (above the first section): unfilled placeholder {placeholder}; '
        "replace it with its value"
        for placeholder in field_report_placeholders()
        if placeholder in header and placeholder != "<tip>"
    )
    if BRANCH_TIP_PATTERN.search(header) is None:
        problems.append(
            "header (above the first section): Branch tip must be the branch's commit; "
            "field-report --check --worktree <worktree> fills it from the branch"
        )
    problems.extend(release_kind_problems(body, issue_body))
    kind = REINTEGRATION_KIND_PATTERN.search(header)
    if kind is not None and kind[1] not in RELEASE_ORDER:
        problems.append(
            f"header (above the first section): Re-integration kind {kind[1]!r} must be one of "
            f"{', '.join(RELEASE_ORDER)}"
        )
    if FIELD_REPORT_RESULT_PATTERN.search(header) is None:
        problems.append(
            'header (above the first section): Result must be exactly complete or partial, '
            'as "**Result:** complete" or "**Result:** partial"'
        )
    if issue_body is not None:
        problems.extend(field_report_evidence_errors(issue_body, body))
    return problems


def table_problems(where: str, template_header: str, text: str) -> list[str]:
    width = len(table_cells(template_header))
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if not rows:
        return [f"{where}: missing its table; the template's header row: {template_header}"]
    problems = []
    if [cell.casefold() for cell in table_cells(rows[0])] != [
        cell.casefold() for cell in table_cells(template_header)
    ]:
        problems.append(
            f"{where}: table header {rows[0]} does not match the template's {template_header}"
        )
    problems.extend(
        f"{where}: table row {row} has {len(table_cells(row))} columns; "
        f"the template's table has {width}: {template_header}"
        for row in rows[1:]
        if len(table_cells(row)) != width
    )
    return problems


def field_report_error(name: str, problems: list[str]) -> QueueError:
    return QueueError(
        f"Field report {name} does not follow the template {FIELD_REPORT_TEMPLATE_NAME}:\n"
        + "\n".join(f"- {problem}" for problem in problems)
    )


def check_issue_read(
    root: Path, current: dict[str, object] | None, body: str | None, issue: str,
) -> None:
    """Refuse where the work issue has comments past those recorded as read, or a body other than
    the one recorded as read.

    `current` and `body` are the issue's comment state and body as the worker's own GitHub tools
    read them; where either is missing, the issue is read with gh, once, and where gh is not
    usable the check refuses (it guards). `issue` names the work issue in the refusals."""
    recorded = load_comments_read(root)
    recorded_body = load_body_read(root)
    if recorded is None or recorded_body is None:
        what = "comments" if recorded is None else "body"
        raise QueueError(
            f"No {what} recorded as read for the work issue: run intake, or, without gh, "
            + ("comments-read --count <n> --newest <id>" if recorded is None
               else "body-read --body-file <file>")
            + " with what your GitHub tools read"
        )
    comments = None
    if current is None or body is None:
        snapshot = load_snapshot(root)
        if snapshot is None or not gh_usable():
            raise QueueError(
                "Cannot compare the work issue with what was recorded as read: gh is not usable "
                "or intake's snapshot is missing; pass --comment-count <n> --newest-comment <id> "
                "and --issue-body <file> as your GitHub tools read the issue now"
            )
        fetched = fetch_issue(root, int(snapshot["number"]), str(snapshot["repo"]))
        if current is None:
            comments = fetched["comments"]
            current = comment_state(comments)
        if body is None:
            body = str(fetched["body"])
    for error in (unread_comments_error(recorded, current, comments),
                  changed_body_error(recorded_body, body, issue)):
        if error is not None:
            raise error


def checked_report(root: Path | None, file: Path, issue_body: str) -> str:
    """The field report `file` carries between its markers (a worker's draft or a whole pull
    request description), refused where it departs from its template or misses evidence against
    `issue_body`. In a worktree its Branch tip is first set to the branch's commit and written back,
    and `integrate`'s guard runs against the checked-out branch, so a delivery shows the refusal
    the landing would."""
    text = read_file(file, "field report")
    if root is not None:
        text = with_branch_tip(root, text)
    report = report_in(text, f"Field report {file.name}")
    problems = field_report_problems(report, issue_body)
    if problems:
        raise field_report_error(file.name, problems)
    if root is not None:
        branch = current_branch(root)
        if branch:
            guard(root, branch, report)
        file.write_text(text, encoding="utf-8", newline="\n")
    return report


def check_field_report(
    root: Path | None, file: Path, issue_body_file: Path | None,
    comments: dict[str, object] | None = None,
) -> None:
    """Validate a field report, the one a pull request description carries between its markers,
    against the template without writing GitHub or, given the issue body, without a worktree; in a
    worktree with a comments-read or body-read record, also refuse comments that arrived after it
    and a body changed since (read with gh, unless `comments` and the issue body file give them).
    In a worktree its Branch tip is first set to the branch's commit."""
    if issue_body_file is not None:
        issue_body = issue_body_text(issue_body_file)
    elif root is None:
        raise QueueError(
            "field-report --check needs the work issue's body for the evidence gate: "
            "pass --issue-body <file>, or --worktree <worktree> to read intake's snapshot"
        )
    else:
        snapshot = load_snapshot(root)
        if snapshot is None:
            raise QueueError(
                "field-report --check needs the work issue's body for the evidence gate: "
                "run intake, or save the work issue's body to a file and pass --issue-body <file>"
            )
        issue_body = str(snapshot["body"])
    report = checked_report(root, file, issue_body)
    if root is not None and (comments is not None or load_comments_read(root) is not None
                             or load_body_read(root) is not None):
        snapshot = load_snapshot(root)
        named = WORK_ISSUE_PATTERN.search(report)
        issue = (str(snapshot["url"]) if snapshot is not None
                 else f"#{named[1]}" if named else "named in the field report")
        check_issue_read(root, comments, None if issue_body_file is None else issue_body, issue)


def branch_tip(root: Path) -> str | None:
    """The commit the branch checked out in `root` is at; None without one."""
    result = run_git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def with_branch_tip(root: Path, body: str) -> str:
    """`body` with its Branch tip set to the branch's commit in `root`, the one value it records;
    unchanged where `root` has no commit, and the template check then names an unfilled tip."""
    tip = branch_tip(root)
    if tip is None:
        return body
    return BRANCH_TIP_FIELD.sub(lambda match: f"{match[1]}`{tip}`", body, count=1)


def fleet_marked(body: str) -> str:
    """`body` with the fleet marker as its first line, once."""
    return body if FLEET_MARKER in body else f"{FLEET_MARKER}\n{body}"


def field_report_placeholders() -> list[str]:
    """The placeholders in the field report's header, its template the one owner: `<name>` or
    `#<name>`."""
    template = report_in(field_report_template(), FIELD_REPORT_TEMPLATE_NAME)
    header = re.split(r"^## ", HTML_COMMENT_PATTERN.sub("", template), maxsplit=1,
                      flags=re.MULTILINE)[0]
    return list(dict.fromkeys(re.findall(r"#?<[^<>\n]+>", header)))


def ensure_labels(root: Path, repo: str, labels: list[str]) -> None:
    """Create each of `labels` that `repo` does not have yet, after one listing."""
    existing = json.loads(run_gh(root, [
        "label", "list", "--json", "name", "--limit", "500", *repo_arguments(repo),
    ]) or "[]")
    names = {label["name"] for label in existing}
    for label in labels:
        if label not in names:
            run_gh(root, [
                "label", "create", label, "--color", "c5def5",
                *(("--description", LABEL_DESCRIPTIONS[label]) if label in LABEL_DESCRIPTIONS else ()),
                *repo_arguments(repo),
            ])


def work_labels(root: Path, explicit: str | None) -> list[str]:
    """WORK_LABELS and the `repo:` label of the repository the issue is for: the named one, else
    this checkout's (whose tracker may hold the issue)."""
    name = explicit.rstrip("/").rsplit("/", 1)[-1] if explicit else repository_name(root)
    return [*WORK_LABELS, f"repo:{name}"]


def read_file(file: Path, what: str) -> str:
    """The UTF-8 text of `file`; the error names it as `what`."""
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Cannot read {what} {file}: {error}") from error


def read_text_file(file: Path, what: str) -> str:
    text = read_file(file, what).strip()
    if not text:
        raise QueueError(f"The {what} {file} is empty")
    return text


# Dedupe before filing (work model, Issues): every command that files an issue, or turns one into
# a work issue (`file`, `backlog file`, `route`), re-reads the open issues just before it writes and
# answers a twin instead of filing one; after filing it reads again and closes the new issue as a
# duplicate of a lower-numbered twin that raced it. One plan holds the steps: the local runner runs
# it through gh, the cloud hand-off prints it for the session's GitHub tools.

DATE_SUFFIX_PATTERN = re.compile(r"-\d{8}$")
ROUTED_FROM_PATTERN = re.compile(r"^Routed from: (.+?)[ \t]*$", re.MULTILINE)


def purpose_key(title: str, body: str) -> tuple[str, str | None]:
    """The purpose of an issue, the one owner of sameness: its title without a trailing
    `-yyyymmdd` and, for a routed issue, its `Routed from:` line. Two open issues of one
    repository with the same key are twins."""
    routed = ROUTED_FROM_PATTERN.search(body)
    return DATE_SUFFIX_PATTERN.sub("", title.strip()), routed[1] if routed else None


def twins(issues: list[dict[str, object]], key: tuple[str, str | None],
          exclude: int | None = None) -> list[int]:
    """The numbers of `issues` with purpose `key`, lowest first, without `exclude`."""
    return sorted(int(str(issue["number"])) for issue in issues
                  if int(str(issue["number"])) != exclude
                  and purpose_key(str(issue.get("title") or ""), str(issue.get("body") or "")) == key)


def twin_rule(key: tuple[str, str | None]) -> str:
    """The sameness condition of `key` in words, as a plan's note states it."""
    stem, routed = key
    return (f"whose title without a trailing -yyyymmdd is `{stem}` and whose body has "
            + (f"the line `Routed from: {routed}`" if routed else "no `Routed from:` line"))


def comment_quote(text: str) -> str:
    """`text` as a Markdown quote, without the fleet marker, so a comment shows it as data."""
    lines = text.replace(FLEET_MARKER, "").strip().splitlines()
    return "\n".join(f"> {line}".rstrip() for line in lines)


def twin_comment(command: str, title: str, body: str, existing: int | None) -> str:
    """The comment a twin gets instead of a new issue: what `command` would have filed."""
    what = (f"would have routed #{existing} as" if existing is not None
            else "would have filed")
    return (f"Not filed again: `work_tickets.py {command}` {what} a twin of this issue, "
            f"answered here instead.\n\n**{title}**\n\n{comment_quote(body)}\n")


def open_issues_step(action: str, repo: str, key: tuple[str, str | None], note: str,
                     gives: str) -> Step:
    return Step(action, "list_issues", {
        **owner_repo(repo), "state": "OPEN", "perPage": 100, "fields": ["number", "title", "body"]},
        note=f"Read every open issue (page with `after` until none is left); a twin is one "
             f"{twin_rule(key)}. {note}", gives=(gives,))


def close_duplicate_steps(repo: str, number: object, of: Later, why: str,
                          condition: str, last: str = "") -> tuple[Step, ...]:
    """Comment on `number` that it duplicates `of`, then close it with state_reason duplicate;
    the local runner skips both where `of` is none."""
    return (
        Step(f"comment_duplicate:{of.name}", "add_issue_comment", {
            **owner_repo(repo), "issue_number": number, "body": f"Duplicate of #{of}: {why}.\n"},
            note=condition),
        Step(f"close_duplicate:{of.name}", "issue_write", {
            **owner_repo(repo), "method": "update", "issue_number": number, "state": "closed",
            "state_reason": "duplicate", "duplicate_of": of}, note=condition + last),
    )


def filing_plan(repo: str, command: str, title: str, body: str, filing: Step,
                existing: int | None = None) -> Plan:
    """The dedupe plan around `filing`, the step that files the issue (or, for `route`, turns
    `existing` into a work issue): read the open issues just before; with a twin, comment on it
    what would have been filed (and close `existing` as its duplicate) and file nothing; otherwise
    file, read again, and close the new issue as a duplicate of a lower-numbered twin."""
    key = purpose_key(title, body)
    twin = Later("twin", 1)
    stop = " Then stop: nothing is filed."
    on_twin: tuple[Step, ...] = (
        Step("comment_twin", "add_issue_comment", {
            **owner_repo(repo), "issue_number": twin,
            "body": twin_comment(command, title, body, existing)},
            note="Only where step 1 found a twin." + ("" if existing is not None else stop)),
        *(close_duplicate_steps(repo, existing, twin, "routed as a twin of it",
                                "Only where step 1 found a twin.", stop) if existing is not None else ()),
    )
    at = len(on_twin) + 2
    number: object = existing if existing is not None else Later("number", at)
    lower = Later("lower", at + 1)
    filed = Step(filing.action, filing.tool, filing.arguments,
                 note=" ".join(part for part in ("Only where step 1 found no twin.", filing.note)
                               if part), gives=filing.gives)
    return Plan(f"{command} {title}", (
        open_issues_step("find_twin", repo, key, (
            f"Gives the lowest-numbered twin{f' other than #{existing}' if existing else ''}, "
            "or none."), "twin"),
        *on_twin,
        filed,
        open_issues_step("find_lower", repo, key, (
            f"Only where step {at} ran: gives the lowest-numbered twin with a lower number than "
            f"#{number}, or none: two creators raced."), "lower"),
        *close_duplicate_steps(repo, number, lower, "filed in a race with it",
                               f"Only where step {at + 1} found a lower twin."),
    ))


@dataclass(frozen=True)
class Filed:
    """What a dedupe plan did: the twin it answered, or the issue it filed (`number`, `url`) and
    the lower twin it then closed it as a duplicate of; all None where it was handed off."""

    twin: int | None = None
    number: int | None = None
    url: str = ""
    lower: int | None = None

    @property
    def duplicate(self) -> bool:
        return self.lower is not None

    def line(self, repo: str, what: str) -> str:
        """The command's answer for `what` it files: the twin's number, the new issue's URL, or
        the hand-off."""
        if self.twin is not None:
            return (f"Not filed: #{self.twin} {issue_url(repo, self.twin)} has the same purpose; "
                    "commented on it instead")
        if self.number is None:
            return f"Run the GitHub plan above to file the {what} once"
        url = self.url or issue_url(repo, self.number)
        return f"Filed {what} {url}" + (
            f", closed as a duplicate of #{self.lower}" if self.lower is not None else "")


def open_issues(root: Path, repo: str) -> list[dict[str, object]]:
    """Every open issue of `repo`, read now, with its title and body."""
    return json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--json", "number,title,body", "--limit", "5000",
        *repo_arguments(repo),
    ]) or "[]")


SE_ROOT = Path(__file__).resolve().parents[1]


def refuse_dangling(repo: str, command: str, body: str) -> None:
    """Refuse an issue body that names a missing se command or subcommand, unless one of its
    Requirements says it is new work of that issue (one owner: references.dangling). A bare `scripts/…` path names se's
    own scripts only in an issue of se's own repository; elsewhere it may be that repository's."""
    own = remote_repo(SE_ROOT)
    found = sibling("references").dangling(
        body, SE_ROOT, paths=False, created=True,
        bare_scripts=own is not None and api_repo(own).lower() == api_repo(repo).lower())
    if found:
        raise QueueError(
            f"{command}: the body names what se does not have; correct it, or say in its "
            "Requirements that it is new work of this issue (\"new\", \"add\" or \"create\"):\n"
            + "\n".join(f"  {finding}" for finding in found))


def filed_once(root: Path, repo: str, command: str, title: str, body: str, filing: Step,
               existing: int | None = None) -> Filed:
    """Run the dedupe plan around `filing` through gh, or print it where gh is not signed in; a
    body naming a missing se command is refused first (`refuse_dangling`)."""
    refuse_dangling(repo, command, body)
    plan = filing_plan(repo, command, title, body, filing, existing)
    if hand_off():
        print(plan.text())
        return Filed()
    key = purpose_key(title, body)
    state: dict[str, object] = {}

    def find_twin(_: dict[str, object], __: str) -> dict[str, object]:
        found = twins(open_issues(root, repo), key, existing)
        state["twin"] = found[0] if found else None
        return {"twin": state["twin"]}

    def comment_twin(arguments: dict[str, object], _: str) -> None:
        if state["twin"] is not None:
            run_gh_with_body(root, ["issue", "comment", str(state["twin"]), *repo_arguments(repo)],
                             str(arguments["body"]))

    def create(arguments: dict[str, object], _: str) -> dict[str, object] | None:
        if state["twin"] is not None:
            return {"number": None}
        labels = [str(label) for label in arguments["labels"]]  # type: ignore[union-attr]
        ensure_labels(root, repo, labels)
        output = run_gh_with_body(root, [
            "issue", "create", "--title", str(arguments["title"]),
            *(argument for label in labels for argument in ("--label", label)),
            *repo_arguments(repo)], str(arguments["body"]))
        url = output.strip().splitlines()[-1] if output.strip() else ""
        match = re.search(r"/issues/(\d+)$", url)
        if match is None:
            raise QueueError(f"{command}: gh issue create printed no issue URL: {output.strip()!r}")
        state.update(number=int(match[1]), url=url)
        return {"number": state["number"]}

    def route(arguments: dict[str, object], _: str) -> None:
        if state["twin"] is not None:
            return
        labels = work_labels(root, repo)
        ensure_labels(root, repo, labels)
        run_gh_with_body(root, [
            "issue", "edit", str(existing), "--title", str(arguments["title"]),
            *(argument for label in labels for argument in ("--add-label", label)),
            *repo_arguments(repo)], str(arguments["body"]))
        state["number"] = existing

    def find_lower(_: dict[str, object], __: str) -> dict[str, object]:
        number = state.get("number")
        found = ([twin for twin in twins(open_issues(root, repo), key, int(str(number)))
                  if twin < int(str(number))] if number is not None else [])
        state["lower"] = found[0] if found else None
        return {"lower": state["lower"]}

    def comment_duplicate(arguments: dict[str, object], source: str) -> None:
        if state[source] is None:
            return
        body = re.sub(r"#<[^>]*>", f"#{state[source]}", str(arguments["body"]))
        run_gh_with_body(root, ["issue", "comment", str(arguments["issue_number"]),
                                *repo_arguments(repo)], body)

    def close_duplicate(arguments: dict[str, object], source: str) -> None:
        if state[source] is None:
            return
        hostname = repo_host(repo)
        run_gh(root, ["api", "-X", "PATCH",
                      f"repos/{api_repo(repo)}/issues/{arguments['issue_number']}",
                      "-f", "state=closed", "-f", "state_reason=duplicate",
                      *(("--hostname", hostname) if hostname else ())])

    run_plan(plan, {"find_twin": find_twin, "comment_twin": comment_twin, "create": create,
                    "route": route, "find_lower": find_lower,
                    "comment_duplicate": comment_duplicate, "close_duplicate": close_duplicate})
    number = state.get("number")
    return Filed(twin=state["twin"],  # type: ignore[arg-type]
                 number=None if number is None else int(str(number)), url=str(state.get("url", "")),
                 lower=state.get("lower"))  # type: ignore[arg-type]


def work_issue_filing(repo: str, title: str, body: str, labels: list[str]) -> Step:
    """The step that files a work issue titled `title` with `labels`, for `filed_once`."""
    return Step("create", "issue_write", {
        **owner_repo(repo), "method": "create", "title": title, "body": body, "labels": labels},
        gives=("number",))


def file_work_issue(
    root: Path, title: str, file: Path, blockers: list[int], repo: str | None,
    extra: tuple[str, ...] = ()
) -> str:
    """File a work issue with its labels and the `extra` ones, once (dedupe: work model, Issues);
    with blockers, link them first and add `ready` last, so the issue is never startable before its
    blockers are linked. Returns the filed issue's URL, or the line naming the twin it answered."""
    if not title.strip():
        raise QueueError("file needs a title, the branch name")
    body = fleet_marked(read_text_file(file, "work issue body") + "\n")
    labels = [*work_labels(root, repo), *(label for label in extra if label.strip())]
    repo = resolve_repo(root, repo)
    first = [label for label in labels if not blockers or label != "ready"]
    if hand_off() and blockers:
        raise QueueError(
            "file --blocked-by links blockers through gh, which is not signed in here; file "
            "without --blocked-by and link the blockers on GitHub, or run it where gh is signed in")
    outcome = filed_once(root, repo, "file", title.strip(), body,
                         work_issue_filing(repo, title.strip(), body, first))
    if outcome.number is not None and not outcome.duplicate and blockers:
        for blocker in blockers:
            block(root, outcome.number, blocker, repo)
        run_gh(root, ["issue", "edit", str(outcome.number), "--add-label", "ready",
                      *repo_arguments(repo)])
    return outcome.line(repo, "work issue")


def today_stamp() -> str:
    """Today as a branch name's date, `<yyyymmdd>`."""
    return time.strftime("%Y%m%d")


def routed_branch(title: str, kind: str) -> str:
    """The branch name derived from an outside issue's title: `<kind>/<topic>-<yyyymmdd>`, without
    a leading label such as "Proposal:"."""
    if kind not in RELEASE_KINDS:
        raise QueueError(f"route --type {kind!r} names no package kind; use one of "
                         f"{', '.join(RELEASE_KINDS)}")
    topic = re.sub(r"^\s*\w+:\s*(?=\S)", "", title)
    return f"{kind}/{slug(topic)}-{today_stamp()}"


def routed_body(body: str, title: str, routing: str) -> str:
    """The body unchanged, then the handled record and the routing section: the original title as
    "Routed from" and the routing file's sections, each one heading level down."""
    fenced = False
    lines = []
    for line in routing.strip().splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        lines.append(f"#{line}" if not fenced and SECTION_PATTERN.fullmatch(line) else line)
    return (f"{body.rstrip()}\n\n{HANDLED_MARKER}\n## {ROUTING_SECTION}\n\n"
            f"Routed from: {title.strip()}\n\n" + "\n".join(lines) + "\n")


def route_outside_issue(
    root: Path, number: int, title: str | None, kind: str, file: Path, repo: str | None,
    read: tuple[str, Path] | None = None
) -> str:
    """Route a checked outside issue as a work issue in one edit, once
    (dedupe: work model, Issues): its title becomes its branch name (given, or derived from
    the title), it gets the work labels, and its body gets the routing section, whose handled
    record `intake --outside` reads as done. Returns the line naming the result. `read` is the
    issue's title and a file with its body as the host's GitHub tools read them, where gh is not
    signed in."""
    routing = read_text_file(file, "routing sections")
    repo = resolve_repo(root, repo)
    handing_off = hand_off()
    if read is None and handing_off:
        raise QueueError(
            f"route reads #{number} through gh, which is not signed in here; read the issue with "
            "the GitHub tools and pass --issue-title <title> --issue-body <file with its body>")
    if handing_off:  # the pause search runs first, as its own plan
        print(Plan(pause_plan(repo).title, (pause_step(repo),),
                   "no issue listed: run the plan below").text())
    else:
        refuse_while_paused("route", pause_issues(root, repo))
    issue = (fetch_issue(root, number, repo) if read is None
             else {"title": read[0], "body": read_file(read[1], "issue body")})
    if section(markdown_sections(str(issue["body"])), ROUTING_SECTION):
        raise QueueError(f"route: #{number} is routed already; edit its {ROUTING_SECTION} section")
    branch = title.strip() if title is not None else routed_branch(str(issue["title"]), kind)
    if not branch:
        raise QueueError("route needs a title, the branch name, or none to derive it")
    body = routed_body(str(issue["body"]), str(issue["title"]), routing)
    filing = Step("route", "issue_write", {
        **owner_repo(repo), "method": "update", "issue_number": number, "title": branch,
        "body": body, "labels": f"<the issue's labels with {', '.join(work_labels(root, repo))}>"},
        note="issue_read get_labels reads the issue's labels; issue_write sets the whole list")
    outcome = filed_once(root, repo, "route", branch, body, filing, existing=number)
    if outcome.twin is not None:
        return outcome.line(repo, branch)
    if outcome.number is None:
        return f"Run the GitHub plan above to route #{number} as {branch} once"
    return f"Routed issue #{number} as {branch}" + (
        f"; closed as a duplicate of #{outcome.lower}" if outcome.duplicate else "")


def backlog_file(root: Path, title: str, file: Path, repo: str | None) -> str:
    """File a far-out idea as a backlog issue for the person, once
    (dedupe: work model, Issues), creating its label where missing."""
    repo = resolve_repo(root, repo)
    body = read_file(file, "backlog body").strip()
    if not title.strip() or not body:
        raise QueueError("backlog file needs a title and a body")
    filing = Step("create", "issue_write", {
        **owner_repo(repo), "method": "create", "title": title.strip(),
        "body": fleet_marked(body + "\n"), "labels": [BACKLOG_LABEL, PERSON_LABEL]},
        gives=("number",))
    return filed_once(root, repo, "backlog file", title.strip(), fleet_marked(body + "\n"),
                      filing).line(repo, "backlog issue")


def backlog_list(root: Path, search: str | None, repo: str | None) -> list[dict[str, object]]:
    """The open backlog issues, those whose title or body matches `search` where given."""
    query = ["--search", f"{search} in:title,body"] if search else []
    return json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", BACKLOG_LABEL,
        "--json", "number,title,url", "--limit", "200", *query,
        *repo_arguments(resolve_repo(root, repo)),
    ]))


def escalate(root: Path, number: int, file: Path, repo: str | None) -> None:
    repo = resolve_repo(root, repo)
    question = read_file(file, "escalation").strip()
    if not question:
        raise QueueError("The escalation needs a question")
    run_gh_with_body(root, ["issue", "comment", str(number), *repo_arguments(repo)], question + "\n")
    run_gh(root, ["issue", "edit", str(number), "--add-label", "escalated", *repo_arguments(repo)])


def pull_request_report(
    root: Path, pull_number: int, tracker: str
) -> tuple[dict[str, object], str, dict[str, object], int]:
    """The pull request, the field report its description carries, its work issue and that
    issue's number; refused where the description has no report, the report names no work issue,
    or it departs from its template or misses evidence."""
    pull = json.loads(run_gh(root, [
        "pr", "view", str(pull_number), "--json", "number,url,body,headRefName,headRefOid",
        *repo_arguments(remote_repo(root) or tracker),
    ]))
    where = f"pull request #{pull_number}"
    report = report_in(str(pull.get("body") or ""), f"The description of {where}")
    work = WORK_ISSUE_PATTERN.search(report)
    if work is None:
        raise QueueError(
            f"The field report in {where} names no work issue; the worker writes "
            "**Work issue:** #<n> in its header and delivers again"
        )
    work_issue = fetch_issue(root, int(work[1]), tracker)
    problems = field_report_problems(report, str(work_issue["body"]))
    if problems:
        raise field_report_error(f"in {where}", problems)
    return pull, report, work_issue, int(work[1])


def run_project_command(root: Path, command: str, description: str) -> str:
    result = subprocess.run(
        command, cwd=root, shell=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"
        raise QueueError(f"{description} failed: {detail}")
    output = (result.stdout + result.stderr).strip()
    return output.splitlines()[-1] if output else "passed"


@dataclass(frozen=True)
class SuiteBudget:
    """se.toml `[tests]`: the complete suite and its time budget (README "Test budget")."""

    command: list[str]
    target_seconds: float
    limit_seconds: float
    setup: list[str] | None = None
    tier: str | None = None  # `<module>:<function>`, the project's tier function
    over_limit: str = "fail"  # "warn": an overrun only warns (README "Test budget")


def is_argument_array(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(argument, str) and argument for argument in value
    )


SLOWEST_TESTS = 10
OUTPUT_TAIL_LINES = 5
DURATION_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(call|setup|teardown)\s+(\S.*?)\s*$")
# Noise in a passing suite's tail: pytest's progress lines and its section banners.
TAIL_NOISE = (re.compile(r"^[.sFEx]+\s+\[\s*\d+%\]$"), re.compile(r"^=+ .* =+$"))
TEST_REPORTS_VARIABLE = "SE_TEST_REPORTS"
NO_SLOWEST_TESTS = (
    f"  not reported by the runner; write JUnit XML to ${TEST_REPORTS_VARIABLE} "
    "(the suite command's report directory) to name them"
)
clock = time.monotonic
# Apart from 1 (failed tests and every other refusal), so a caller can tell a slow suite from a red one.
SUITE_OVER_LIMIT_EXIT_CODE = 3


class SuiteOverLimitError(QueueError):
    """The complete suite passed but ran over its limit; exits with SUITE_OVER_LIMIT_EXIT_CODE."""


def suite_budget(root: Path) -> SuiteBudget:
    """Read and validate `[tests]` of se.toml; refuse, naming the key and the remedy."""
    tests = se_table(root, "tests")
    where = f"[tests] in {root / 'se.toml'}"
    command = tests.get("command")
    if not is_argument_array(command):
        raise QueueError(
            f"{where} must declare command, the complete suite as a non-empty argument array, "
            'for example command = ["uv", "run", "pytest", "-q"]'
        )
    setup = tests.get("setup")
    if setup is not None and not is_argument_array(setup):
        raise QueueError(
            f"{where}: setup must be a non-empty argument array, the command that installs the "
            'test dependencies, for example setup = ["uv", "sync"]; fix it or remove it'
        )
    tier = tests.get("tier")
    if tier is not None and not (isinstance(tier, str) and TIER_SETTING.fullmatch(tier)):
        raise QueueError(
            f"{where}: tier must name the project's tier function as \"<module>:<function>\", "
            'a module importable from the project root, for example tier = "tests.tiers:tier"; '
            "fix it or remove it"
        )
    over_limit = tests.get("over_limit", "fail")
    if over_limit not in OVER_LIMIT_CHOICES:
        raise QueueError(
            f'{where}: over_limit must be "fail" (the default) or "warn", what a run over '
            "limit_seconds does; fix it or remove it"
        )
    values: dict[str, float] = {}
    for key, default in (("target_seconds", 60), ("limit_seconds", 120)):
        value = tests.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise QueueError(f"{where}: {key} must be a positive number of seconds; fix it")
        values[key] = float(value)
    if values["target_seconds"] > values["limit_seconds"]:
        raise QueueError(f"{where}: target_seconds must not exceed limit_seconds; fix it")
    return SuiteBudget(command, values["target_seconds"], values["limit_seconds"], setup, tier,
                       over_limit)


OVER_LIMIT_CHOICES = ("fail", "warn")
TIER_SETTING = re.compile(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*")


def tier_function(root: Path, setting: str):
    """Import `[tests]` tier, `<module>:<function>`, with the project root first on the path;
    refuses, naming the setting, a module or function it cannot load."""
    module_name, function_name = setting.split(":")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        raise QueueError(
            f"[tests] tier in {root / 'se.toml'}: cannot import {module_name} from the project "
            f"root: {error}; fix the module or the setting"
        ) from error
    finally:
        sys.path.remove(str(root))
    function = getattr(module, function_name, None)
    if not callable(function):
        raise QueueError(
            f"[tests] tier in {root / 'se.toml'}: {module_name} has no function {function_name}; "
            "fix the setting"
        )
    return function


def tier_lines(parts: list[SuitePart], tier_of) -> list[str]:
    """Per tier, by name, its slowest test and its time: `<tier>: <seconds>s <part> <test>`.
    `tier_of` maps a test id, `<classname>::<name>` as the JUnit report names it, to its tier."""
    slowest: dict[str, tuple[float, str]] = {}
    for part in parts:
        for seconds, test in part.cases:
            tier = str(tier_of(test))
            if tier not in slowest or seconds > slowest[tier][0]:
                slowest[tier] = (seconds, f"{seconds:.2f}s {part.name} {test}")
    return [f"{tier}: {line}" for tier, (_, line) in sorted(slowest.items())]


def output_tail(output: str) -> str:
    """The last lines of a command's output, indented, for the person reading the run."""
    return "\n".join(f"  {line}" for line in output.splitlines()[-OUTPUT_TAIL_LINES:])


def run_suite_setup(root: Path, setup: list[str]) -> None:
    """Run `[tests]` setup before the suite and time it apart: it is not held to the budget.

    Prints its time and its last lines; refuses a failing setup with its whole output."""
    started = clock()
    result = subprocess.run(
        setup, cwd=root, shell=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    seconds = clock() - started
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise QueueError(
            f"Suite setup failed (exit code {result.returncode}; {seconds:.1f} s) running "
            f"{' '.join(setup)} ([tests] setup in se.toml); the suite did not run. Fix the setup:\n"
            f"{output or 'no output'}"
        )
    print(f"Setup time: {seconds:.1f} s (not budgeted)")
    if output:
        print(output_tail(output))


def with_durations(command: list[str], count: int) -> list[str]:
    """Ask pytest for its `count` slowest tests; other runners are run as declared."""
    is_pytest = any(Path(argument).stem == "pytest" for argument in command)
    if not is_pytest or any(argument.startswith("--durations") for argument in command):
        return command
    return [*command, f"--durations={count}"]


SLOW_SETUP_SECONDS = 2.0


@dataclass(frozen=True)
class SuiteSetup:
    """A test case's setup phase, from its `setup_time` property in a JUnit report."""

    seconds: float
    test: str
    name: str  # its `fixture` property, else the test's module (the JUnit classname)
    worker: str | None  # its `worker` property (pytest-xdist: the worker id), where it writes one


@dataclass(frozen=True)
class SuitePart:
    """One JUnit XML report of the suite: a part, named by the file's stem."""

    name: str
    wall_seconds: float | None  # the report's own `time`, where it writes one
    workers: int  # its `workers` testsuite property (pytest: record_testsuite_property), else 1
    cases: list[tuple[float, str]]  # (seconds, test) of every test case
    setups: tuple[SuiteSetup, ...] = ()  # the test cases that report a setup time

    def line(self) -> str:
        """`<part>: <wall> s wall; <sum> s test time / <n> workers = <per worker> s; slowest <s> s`:
        a part bound by its total work has a per-worker time near its wall time, one bound by a
        long test a slowest test near it."""
        total = sum(seconds for seconds, _ in self.cases)
        wall = "wall not reported" if self.wall_seconds is None else f"{self.wall_seconds:.1f} s wall"
        workers = f"{self.workers} worker{'s' if self.workers != 1 else ''}"
        slowest = max((seconds for seconds, _ in self.cases), default=0.0)
        return (
            f"{self.name}: {wall}; {total:.1f} s test time / {workers} = "
            f"{total / self.workers:.1f} s; slowest {slowest:.1f} s"
        )

    def setup_lines(self) -> list[str]:
        """The tests whose setup took over SLOW_SETUP_SECONDS, slowest first, then each slow setup
        name paid on more than one worker: one shared setup run again per worker is the signature
        of broken test grouping. Empty where the report has no setup times."""
        slow = sorted((s for s in self.setups if s.seconds > SLOW_SETUP_SECONDS),
                      key=lambda setup: -setup.seconds)
        lines = [
            f"slow setup {s.seconds:.1f} s {s.test} ({s.name}"
            + (f", worker {s.worker})" if s.worker else ")")
            for s in slow
        ]
        paid: dict[str, list[SuiteSetup]] = {}
        for setup in slow:
            paid.setdefault(setup.name, []).append(setup)
        for name, setups in paid.items():
            workers = sorted({s.worker for s in setups if s.worker})
            if len(workers) > 1:
                lines.append(
                    f"setup {name} paid on {len(workers)} workers ({', '.join(workers)}): "
                    f"{sum(s.seconds for s in setups):.1f} s; group its tests on one worker"
                )
        return lines


def read_part(report: Path) -> SuitePart:
    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    times = [float(suite.get("time")) for suite in suites if suite.get("time")]
    wall = float(root.get("time")) if root.get("time") else (sum(times) if times else None)
    workers = [
        int(prop.get("value") or 0) for prop in root.iter("property") if prop.get("name") == "workers"
    ]
    cases, setups = [], []
    for case in root.iter("testcase"):
        test = "::".join(filter(None, (case.get("classname"), case.get("name"))))
        cases.append((float(case.get("time") or 0), test))
        properties = {prop.get("name"): prop.get("value") for prop in case.iter("property")}
        if properties.get("setup_time"):
            setups.append(SuiteSetup(
                float(properties["setup_time"]), test,
                properties.get("fixture") or case.get("classname") or test, properties.get("worker"),
            ))
    return SuitePart(report.stem, wall, max([1, *workers]), cases, tuple(setups))


def report_parts(reports: Path) -> list[SuitePart]:
    """Every JUnit XML report under `reports`, one part each, by name.

    A report that cannot be read is named on stderr and skipped: the parts are advice."""
    found = []
    for report in sorted(reports.rglob("*.xml")):
        try:
            found.append(read_part(report))
        except (ElementTree.ParseError, ValueError, OSError) as error:
            print(f"warning: suite skipped the test report {report}: {error}", file=sys.stderr)
    return found


def slowest_tests(output: str, parts: list[SuitePart], count: int) -> list[str]:
    """The `count` slowest tests, slowest first: from the runner's JUnit reports where it wrote any,
    otherwise from its output's `<seconds>s <phase> <test>` lines (pytest's --durations)."""
    found = [
        (seconds, f"{seconds:.2f}s {part.name} {test}") for part in parts for seconds, test in part.cases
    ]
    if not found:
        found = [
            (float(match[1]), f"{match[1]}s {match[2]} {match[3]}")
            for match in map(DURATION_LINE.match, output.splitlines()) if match
        ]
    return [line for _, line in sorted(found, key=lambda item: -item[0])][:count]


@dataclass(frozen=True)
class SuiteRun:
    """One timed run of the suite command in one checkout."""

    seconds: float
    returncode: int
    stdout: str
    output: str  # stdout and stderr, stripped
    parts: list[SuitePart]

    def refuse_failed(self, budget: SuiteBudget) -> str:
        """The run's result line; refuses a run whose tests failed, with its output."""
        report = self.stdout.strip() or self.output
        summary = report.splitlines()[-1] if report else "no result line"
        if self.returncode != 0:
            raise QueueError(
                f"Complete suite failed ({summary}; {self.seconds:.1f} s) running "
                f"{' '.join(budget.command)} ([tests] command in se.toml); fix the failing tests:\n"
                f"{self.output or f'exit code {self.returncode}'}"
            )
        return summary


def time_suite(checkout: Path, command: list[str]) -> SuiteRun:
    """Run the suite command once in `checkout` and time it; its JUnit reports become its parts."""
    with tempfile.TemporaryDirectory(prefix="se-test-reports-") as reports:
        started = clock()
        result = subprocess.run(
            command, cwd=checkout, shell=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False,
            env={**os.environ, TEST_REPORTS_VARIABLE: reports},
        )
        seconds = clock() - started
        parts = report_parts(Path(reports))
    return SuiteRun(seconds, result.returncode, result.stdout,
                    (result.stdout + result.stderr).strip(), parts)


def clean_commit(root: Path) -> str | None:
    """HEAD where the checkout holds exactly its tree (nothing changed or untracked), else None."""
    head = run_git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    if head.returncode != 0 or changed_paths(root):
        return None
    return head.stdout.strip()


def record_suite_verdict(root: Path, commit: str | None, passed: bool, seconds: float) -> None:
    """Record the suite's verdict on `commit`'s tree, where the checkout still holds exactly it."""
    if commit is None or clean_commit(root) != commit:
        print("Suite verdict not recorded: the checkout differs from a commit (changed or untracked "
              "files, or HEAD moved); commit, then run suite again to push the integration branch")
        return
    tree = sibling("verdicts").record(root, SUITE_VERDICT, commit, passed, seconds)
    print(f"Suite verdict recorded: {'passed' if passed else 'failed'} on tree {tree[:12]} "
          f"(commit {commit[:12]})")


# The reference run of the budget (README "Test budget"): the CI `check` job on GitHub's runner.
CI_VARIABLE = "GITHUB_ACTIONS"
CI_SUITE_TITLE = "se suite time"
CI_SUITE_MESSAGE = re.compile(r"Suite time: (\d+(?:\.\d+)?) s")
CI_SUITE_COMMITS = 8  # first-parent commits of the integration branch searched for CI's time
CI_SUITE_RUNS = 5  # CI's time is the median of this many runs, so one slow runner does not count
CI_MARGIN = 0.9  # CI within 10% of the limit: a local overrun refuses
CI_READ_SECONDS = 10


def suite_is_reference() -> bool:
    """Whether this run is the budget's reference: the CI `check` job (GitHub Actions)."""
    return os.environ.get(CI_VARIABLE) == "true"


@dataclass(frozen=True)
class CiSuiteTime:
    """CI's suite time on the integration branch: the median of its last runs' times (`readings`,
    newest first), and the commit and `check` run whose time is that median."""

    seconds: float
    commit: str
    url: str
    readings: tuple[float, ...] = ()


def ci_suite_text(ci: CiSuiteTime, branch: str) -> str:
    """CI's suite time as run_suite names it: the median, the runs it was taken from, its run."""
    where = f"commit {ci.commit[:12]}{f', {ci.url}' if ci.url else ''}"
    if len(ci.readings) < 2:
        return f"CI's suite time on {branch} is {ci.seconds:.1f} s, from its last run ({where})"
    times = ", ".join(f"{reading:g}" for reading in ci.readings)
    return (f"CI's suite time on {branch} is {ci.seconds:.1f} s, the median of its last "
            f"{len(ci.readings)} runs ({times} s; median {where})")


def github_read(repo: str, path: str) -> object:
    """GET `repos/<repo>/<path>` of github.com's API without an account, as a public repository's
    check runs need none; so `suite` still runs without gh."""
    url = f"https://api.github.com/repos/{api_repo(repo)}/{path}"
    feedback.reading("GitHub", ["GET", url])
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=CI_READ_SECONDS) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def ci_suite_time(root: Path) -> tuple[CiSuiteTime | None, str]:
    """CI's suite time on the integration branch: the median of the `Suite time` notices of up to
    CI_SUITE_RUNS runs, the newest successful `check` run with one on each of its last
    CI_SUITE_COMMITS first-parent commits, as origin has them; it stops reading once it has them.
    A run that failed or was cancelled is skipped: a shorter failed run's time is not CI's time.
    With an even count the slower middle run counts. None with the reason where no time can be
    read."""
    repo = remote_repo(root)
    if repo is None or repo_host(repo) != "github.com":
        return None, "the checkout's origin is not on github.com"
    target = integration_branch(root)
    listed = run_git(root, "rev-list", "--first-parent", f"--max-count={CI_SUITE_COMMITS}",
                     f"refs/remotes/origin/{target}")
    commits = listed.stdout.split() if listed.returncode == 0 else []
    if not commits:
        return None, f"origin/{target} is not fetched"
    found_times: list[CiSuiteTime] = []
    try:
        for commit in commits:
            if len(found_times) == CI_SUITE_RUNS:
                break
            reading = ci_suite_time_of(repo, commit)
            if reading is not None:
                found_times.append(reading)
    except (OSError, ValueError) as error:  # urllib's errors are OSErrors
        return None, f"GitHub could not be read without an account ({error})"
    if not found_times:
        return None, (f"no successful {CHECK_NAME} run on the last {len(commits)} commits of "
                      f"origin/{target} reports a suite time")
    median = sorted(found_times, key=lambda reading: reading.seconds)[len(found_times) // 2]
    return CiSuiteTime(median.seconds, median.commit, median.url,
                       tuple(reading.seconds for reading in found_times)), ""


def ci_suite_time_of(repo: str, commit: str) -> CiSuiteTime | None:
    """The `Suite time` notice of the newest successful `check` run on `commit` that reports one."""
    found = github_read(repo, f"commits/{commit}/check-runs?check_name={CHECK_NAME}")
    runs = [run for run in (found.get("check_runs") or [])
            if run.get("status") == "completed" and run.get("conclusion") == "success"
            ] if isinstance(found, dict) else []
    for run in sorted(runs, key=lambda run: -int(run.get("id") or 0)):
        notes = github_read(repo, f"check-runs/{run['id']}/annotations")
        for note in notes if isinstance(notes, list) else []:
            match = CI_SUITE_MESSAGE.search(str(note.get("message") or ""))
            if note.get("title") == CI_SUITE_TITLE and match:
                return CiSuiteTime(float(match[1]), commit, str(run.get("html_url") or ""))
    return None


def suite_notice(seconds: float, limit: float, detail: str = "") -> str:
    """CI's suite time as the workflow notice ci_suite_time reads from the `check` run."""
    return (f"::notice title={CI_SUITE_TITLE}::Suite time: {seconds:.1f} s "
            f"(limit {limit:g} s{detail})")


# A sharded suite (README "Test budget"): each shard records its time, `check` judges the slowest.
SHARD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class ShardTime:
    """One shard's record: its name, its command's wall time and exit code."""

    name: str
    seconds: float
    exit_code: int


def record_shard(root: Path, name: str, directory: Path, command: list[str]) -> int:
    """Run one shard's command in `root`, its output shown as it runs, time it and write its
    record, `<directory>/<name>.json`, for suite_time_of_shards; returns the command's exit code."""
    if not SHARD_NAME.fullmatch(name):
        raise QueueError(f"suite-shard: the shard name {name!r} must be letters, digits, '.', '_' "
                         "or '-', starting with a letter or digit; name it so")
    if not command:
        raise QueueError("suite-shard: no shard command; give it after --, for example "
                         "suite-shard --worktree . --name one --record <dir> -- pytest -q tests/a")
    feedback.phase(f"suite shard {name}: {' '.join(command)}")
    started = clock()
    try:
        code = subprocess.run(command, cwd=root, shell=False, check=False).returncode
    except OSError as error:
        raise QueueError(f"suite-shard: cannot run {command[0]}: {error}") from error
    seconds = clock() - started
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps({"shard": name, "seconds": round(seconds, 3), "exit_code": code}),
                    encoding="utf-8")
    print(f"Shard {name}: {seconds:.1f} s, exit code {code}; recorded in {path}")
    return code


def shard_times(directory: Path) -> list[ShardTime]:
    """The shard records in `directory`, by name; refuses one it cannot read, naming the file."""
    shards = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            shard = ShardTime(str(record["shard"]), float(record["seconds"]),
                              int(record["exit_code"]))
        except (ValueError, KeyError, TypeError) as error:
            raise QueueError(f"suite-time: {path} is no shard record suite-shard wrote ({error}); "
                             "run the shard again") from error
        shards.append(shard)
    return shards


def workflow_annotation(level: str, message: str) -> str:
    """`message` as a GitHub workflow command `::<level>::` (error, warning), escaped so a line
    break or `%` in it survives as text."""
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::{level}::{escaped}"


def suite_time_of_shards(root: Path, directory: Path, expect: int | None) -> str:
    """CI's suite time of a sharded suite: the slowest shard's, as the shards run side by side.
    Prints each shard, then holds the run to the budget as the reference run: refuses a missing
    shard, and a failed one without printing a time, as a failed run's time is no suite time; prints
    the notice ci_suite_time reads, and refuses a time over the limit with SuiteOverLimitError
    unless `[tests]` over_limit is "warn". Its warnings are `::warning` annotations on stdout, in
    order with what it printed before them."""
    budget = suite_budget(root)
    shards = shard_times(directory)
    if not shards:
        raise QueueError(f"suite-time: no shard records in {directory}; each shard runs "
                         "suite-shard --record <dir> and the check job collects them there")
    if expect is not None and len(shards) != expect:
        raise QueueError(f"suite-time: {len(shards)} shard records in {directory}, expected "
                         f"{expect} ({', '.join(shard.name for shard in shards)}); a shard that "
                         "did not record its time is missing; run it again")
    print("Shards:\n" + "\n".join(f"  {shard.name}: {shard.seconds:.1f} s, exit code "
                                   f"{shard.exit_code}" for shard in shards), flush=True)
    failed = [shard for shard in shards if shard.exit_code != 0]
    if failed:
        raise QueueError(
            f"suite-time: the run failed: shard {', '.join(shard.name for shard in failed)} failed "
            f"(exit code {', '.join(str(shard.exit_code) for shard in failed)}), so it reports no "
            "suite time; fix the failing tests its job names")
    slowest = max(shards, key=lambda shard: shard.seconds)
    seconds, limit = slowest.seconds, budget.limit_seconds
    print(suite_notice(seconds, limit, f"; slowest of {len(shards)} shards: {seconds:.1f} s "
                                       f"(shard {slowest.name})"), flush=True)
    metrics.note(suite_seconds=round(seconds, 3), suite_limit_seconds=limit)
    timing = (f"{seconds:.1f} s, the slowest of {len(shards)} shards (shard {slowest.name}) "
              f"(target {budget.target_seconds:g} s, limit {limit:g} s)")
    if seconds > limit and budget.over_limit == "warn":
        print(workflow_annotation("warning", over_limit_warning(seconds, limit)), flush=True)
    elif seconds > limit:
        raise SuiteOverLimitError(
            f"Sharded suite passed but took {timing} on CI, the budget's reference, over its "
            "limit ([tests] limit_seconds in se.toml). Remedy: make the slowest shard's tests "
            "faster or split them across the shards more evenly."
        )
    elif seconds > budget.target_seconds:
        print(workflow_annotation(
            "warning", f"the sharded suite took {seconds:.1f} s, over its target of "
                       f"{budget.target_seconds:g} s ([tests] target_seconds in se.toml)"),
              flush=True)
    return timing


def host_load() -> str:
    """The host's load averages over its CPUs, for a warning about a slow run."""
    cpus = os.cpu_count() or 1
    try:
        one, five, fifteen = os.getloadavg()
    except (AttributeError, OSError):  # Windows has no load average
        return f"{cpus} CPUs, load average unknown"
    return f"load {one:.1f}/{five:.1f}/{fifteen:.1f} (1/5/15 min) on {cpus} CPUs"


def over_limit_warning(seconds: float, limit: float) -> str:
    """The warning of an overrun where the project declares warn-only (`[tests] over_limit`)."""
    return (f"warning: the complete suite took {seconds:.1f} s, over its limit of {limit:g} s; "
            '[tests] over_limit = "warn" in se.toml, so the overrun is not refused; make the '
            "slowest tests faster")


def run_suite(root: Path, slowest_count: int = SLOWEST_TESTS, read_ci: bool = False) -> str:
    """Run se.toml's complete suite, measure it and hold it to its budget (README "Test budget").

    The suite command may write JUnit XML reports into the directory named by $SE_TEST_REPORTS.
    Runs `[tests]` setup first, outside the budget. Prints the last result lines of the suite's
    stdout (without progress lines, banners and durations), its time, one line per JUnit report
    (SuitePart.line) with its slow setups under it (SuitePart.setup_lines), its `slowest_count` slowest tests
    and, where `[tests]` names a tier function, each tier's slowest test (tier_lines);
    warns above the target; refuses failed tests.

    The reference run (suite_is_reference, CI) prints its time as a notice for ci_suite_time and
    refuses a passing suite above the limit with SuiteOverLimitError. Any other run above the limit
    warns with the host's load and refuses only where CI's suite time on the integration
    branch (ci_suite_time, read there and also where `read_ci`) is unknown or within 10% of the
    limit. Where `[tests]` over_limit is "warn", no overrun refuses: each only warns.
    Records its verdict on HEAD's tree where the checkout holds exactly it (clean_commit);
    push reads it before the integration branch is pushed."""
    budget = suite_budget(root)
    tier_of = tier_function(root, budget.tier) if budget.tier else None
    if budget.setup:
        feedback.phase(f"suite setup: {' '.join(budget.setup)}")
        run_suite_setup(root, budget.setup)
    commit = clean_commit(root)
    feedback.phase(f"complete suite: {' '.join(budget.command)} (limit {budget.limit_seconds:g} s)")
    result = time_suite(root, with_durations(budget.command, slowest_count))
    seconds, output, parts = result.seconds, result.output, result.parts
    reference = suite_is_reference()
    over = seconds > budget.limit_seconds
    ci, unknown = (None, "")
    if not reference and (over or read_ci):
        feedback.phase(f"CI's suite time on {integration_branch(root)}")
        ci, unknown = ci_suite_time(root)
    metrics.note(suite_seconds=round(seconds, 3), suite_limit_seconds=budget.limit_seconds,
                 **({"ci_suite_seconds": ci.seconds} if ci else {}))
    close = ci is None or ci.seconds >= CI_MARGIN * budget.limit_seconds
    enforced = budget.over_limit == "fail"
    refused = over and enforced and (reference or close)
    record_suite_verdict(root, commit, result.returncode == 0 and not refused, seconds)
    slowest = slowest_tests(output, parts, slowest_count)
    summary = result.refuse_failed(budget)
    listing = "\n".join(f"  {line}" for line in slowest) or NO_SLOWEST_TESTS
    timing = (
        f"{seconds:.1f} s (target {budget.target_seconds:g} s, limit {budget.limit_seconds:g} s)"
    )
    if reference:
        print(suite_notice(seconds, budget.limit_seconds))
    ci_text = (ci_suite_text(ci, integration_branch(root)) if ci
               else f"CI's suite time is unknown: {unknown}")
    if refused and reference:
        raise SuiteOverLimitError(
            f"Complete suite passed ({summary}) but took {seconds:.1f} s on CI, the budget's "
            f"reference, over its limit of {budget.limit_seconds:g} s ([tests] limit_seconds in "
            f"se.toml). Slowest tests:\n{listing}\n"
            "Remedy: make the slowest tests above faster (the work model's test rules)."
        )
    if refused:
        why = (f"{ci_text}, within 10% of the limit, so the suite is near its budget on the "
               "reference too" if ci else f"{ci_text}, so this run decides")
        raise SuiteOverLimitError(
            f"Complete suite passed ({summary}) but took {seconds:.1f} s here ({host_load()}), "
            f"over its limit of {budget.limit_seconds:g} s ([tests] limit_seconds in se.toml); "
            f"{why}. Slowest tests:\n{listing}\n"
            "Remedy: make the slowest tests above faster (the work model's test rules)."
        )
    if over and not enforced:
        print(over_limit_warning(seconds, budget.limit_seconds), file=sys.stderr)
    elif over:
        print(
            f"warning: the complete suite took {seconds:.1f} s here ({host_load()}), over its "
            f"limit of {budget.limit_seconds:g} s; {ci_text}, under 90% of the limit, so this "
            f"host is slow and the run is not refused: CI's {CHECK_NAME} on the landing pull "
            "request judges the budget",
            file=sys.stderr,
        )
    own_lines = "\n".join(  # stdout only; the durations are listed below, as the slowest tests
        line for line in result.stdout.strip().splitlines()
        if not DURATION_LINE.match(line) and not any(noise.match(line) for noise in TAIL_NOISE)
    )
    if own_lines:
        print(f"Suite output (last lines):\n{output_tail(own_lines)}")
    print(f"Suite time: {timing}")
    if parts:
        print("Parts:\n" + "\n".join(
            "\n".join([f"  {part.line()}", *(f"    {line}" for line in part.setup_lines())])
            for part in parts
        ))
    print(f"Slowest tests:\n{listing}")
    if tier_of and parts:
        print("Slowest per tier:\n" + "\n".join(f"  {line}" for line in tier_lines(parts, tier_of)))
    if budget.target_seconds < seconds <= budget.limit_seconds:
        print(
            f"warning: the complete suite took {seconds:.1f} s, over its target of "
            f"{budget.target_seconds:g} s ([tests] target_seconds in se.toml); make the slowest "
            "tests above faster",
            file=sys.stderr,
        )
    return f"{summary}; {timing}"


COMPARE_RUNS = 2


@contextmanager
def ref_checkout(root: Path, ref: str):
    """A temporary detached worktree of `ref` as published (`published_ref`), removed afterwards;
    yields its path and what it checked out, `<ref> (<published ref> at <commit>)`."""
    resolved = published_ref(root, ref)
    with tempfile.TemporaryDirectory(prefix="se-compare-") as directory:
        path = Path(directory) / "ref"
        added = run_git(root, "worktree", "add", "--detach", str(path), resolved)
        if added.returncode != 0:
            detail = failure_detail(added)
            raise QueueError(
                f"suite --compare cannot check out {ref}: {detail}; name a branch, tag or commit "
                "this checkout has (fetch it first)"
            )
        try:
            commit = run_git(path, "rev-parse", "--short", "HEAD").stdout.strip()
            where = f"{resolved} at {commit}" if resolved != ref else commit
            yield path, ref if where == ref else f"{ref} ({where})"
        finally:
            run_git(root, "worktree", "remove", "--force", str(path))


def compare_verdict(current: list[float], other: list[float]) -> tuple[float, float, str]:
    """The difference of the means (current minus other), the observed spread (the larger range
    of the two states' wall times) and the verdict: "not slower" where the difference is within
    the spread, otherwise "slower by <difference> s"."""
    difference = sum(current) / len(current) - sum(other) / len(other)
    spread = max(max(times) - min(times) for times in (current, other))
    within = round(difference - spread, 6) <= 0  # rounded: float means land a hair off the edge
    return difference, spread, "not slower" if within else f"slower by {difference:.1f} s"


def compare_suites(root: Path, ref: str, runs: int = COMPARE_RUNS) -> str:
    """Time the suite on this checkout and on `ref` (in a temporary worktree), interleaved,
    `runs` times each, after one untimed warm-up run of each; each state runs its own se.toml
    `[tests]`, setup included. Prints per state its wall times, mean and Parts lines, then the
    difference of the means and the verdict, which it returns. Failed tests refuse; the budget
    does not apply: this is a measurement."""
    with ref_checkout(root, ref) as (other, described):
        if se_table(other, "tests").get("command") is None:
            raise QueueError(
                f"suite --compare: {described} declares no [tests] command in its se.toml; it "
                "predates [tests]: compare against a ref that declares it, a newer commit or the "
                "branch as origin has it (git fetch origin first)"
            )
        states = [("HEAD", root), (ref, other)]
        budgets = {label: suite_budget(checkout) for label, checkout in states}
        for label, checkout in states:
            if budgets[label].setup:
                feedback.phase(f"suite setup of {label}")
                run_suite_setup(checkout, budgets[label].setup)

        def timed(label: str, checkout: Path) -> SuiteRun:
            result = time_suite(checkout, budgets[label].command)
            result.refuse_failed(budgets[label])
            return result

        for label, checkout in states:  # warm-up: caches, environments, bytecode; not counted
            feedback.phase(f"untimed warm-up run of {label}")
            timed(label, checkout)
        results: dict[str, list[SuiteRun]] = {label: [] for label, _ in states}
        for run in range(1, runs + 1):
            for label, checkout in states:
                feedback.phase(f"timed run {run}/{runs} of {label}")
                results[label].append(timed(label, checkout))
    print(f"Suite compare: HEAD against {described}, {runs} timed runs each, interleaved, "
          "after one untimed warm-up run of each")
    for label, _ in states:
        times = [result.seconds for result in results[label]]
        print(f"{label}:\n  Wall times: {', '.join(f'{seconds:.1f} s' for seconds in times)}"
              f"\n  Mean: {sum(times) / len(times):.1f} s")
        for number, result in enumerate(results[label], 1):
            if result.parts:
                print(f"  Parts (run {number}):\n"
                      + "\n".join(f"    {part.line()}" for part in result.parts))
    difference, spread, verdict = compare_verdict(
        *([result.seconds for result in results[label]] for label, _ in states))
    print(f"Difference of the means: {difference:+.1f} s (HEAD minus {ref}); "
          f"observed spread {spread:.1f} s")
    return verdict


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"expected a whole number of at least 1, not {value!r}")
    return number


def parse_check_commands(value: str) -> list[list[str]]:
    try:
        commands = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(
            "--check-command must be a JSON list of non-empty argument arrays"
        ) from error
    if not isinstance(commands, list) or not commands:
        raise argparse.ArgumentTypeError(
            "--check-command must be a non-empty JSON list of argument arrays"
        )
    if any(
        not isinstance(command, list)
        or not command
        or any(not isinstance(argument, str) or not argument for argument in command)
        for command in commands
    ):
        raise argparse.ArgumentTypeError(
            "--check-command must contain only non-empty argument arrays"
        )
    return commands


def run_project_checks(
    root: Path,
    commands: list[list[str]],
    temporary_working_directory: bool,
) -> str:
    failures: list[str] = []
    outputs: list[str] = []
    for index, command in enumerate(commands, start=1):
        if temporary_working_directory:
            with tempfile.TemporaryDirectory(prefix="se-check-") as directory:
                result = subprocess.run(
                    command, cwd=directory, shell=False, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", check=False,
                )
        else:
            result = subprocess.run(
                command, cwd=root, shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
        output = one_line(result.stdout + result.stderr)
        reference = f"check {index} ({' '.join(command)})"
        if result.returncode:
            failures.append(
                f"{reference}: exit code {result.returncode}; output: {output or 'none'}"
            )
        else:
            outputs.append(f"{reference}: {output or 'passed'}")
    if failures:
        raise QueueError("Project check failed:\n" + "\n".join(failures))
    return "; ".join(outputs) or "passed"


def worker_worktree(root: Path, branch: str) -> Path:
    listing = run_git(root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        raise QueueError("Cannot list Git worktrees")
    path: Path | None = None
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    raise QueueError(f"Cannot find the worktree for branch {branch}")


def remove_worker_worktree(root: Path, branch: str, landed: str | None = None) -> None:
    """Remove `branch`'s worker worktree once its commits are in `landed` (default: the
    integration branch), the tip a squash landing merged."""
    worker = worker_worktree(root, branch)
    report = status_report(worker, landed or integration_branch(root))
    if not report["cleanup_eligible"]:
        reasons = "; ".join(report["cleanup_reasons"])
        raise QueueError(f"Worker worktree is not ready for removal: {reasons}")
    remove_private_queue(worker / ".se")
    make_worktree_removable(worker)
    removed = run_git(root, "worktree", "remove", str(worker))
    if removed.returncode != 0:
        detail = failure_detail(removed)
        raise QueueError(f"Cannot remove worker worktree: {detail}")


def delete_merged_branch(root: Path, branch: str, head: str, landed: str | None = None) -> None:
    """Delete `branch` locally and on origin once `landed` (default: the integration branch), the
    tip a squash landing merged, contains its `head`."""
    target = landed or integration_branch(root)
    contained = run_git(root, "merge-base", "--is-ancestor", head, target)
    if contained.returncode != 0:
        print(
            f"warning: merged branch was retained because {landed[:12] if landed else target} "
            "does not contain its tip",
            file=sys.stderr,
        )
        return
    local = run_git(root, "branch", "-D", branch)  # contained in `target`, checked above
    if local.returncode != 0:
        detail = failure_detail(local)
        print(f"warning: merged branch was retained locally: {detail}", file=sys.stderr)
    else:
        print("Cleanup: local merged branch deleted")
    remote = run_git(root, "push", f"--force-with-lease=refs/heads/{branch}:{head}", "origin", f":refs/heads/{branch}")
    if remote.returncode != 0:
        detail = failure_detail(remote)
        print(
            f"warning: merged branch was retained on origin, which refused deleting {branch} "
            f"({detail}); left to the repository's automatic head-branch deletion, not retried",
            file=sys.stderr,
        )
    else:
        print("Cleanup: origin merged branch deleted")


def release_line(pull_url: str, tag: str | None) -> str:
    """The closing comment's release: the release page of `tag` beside the pull request at
    `pull_url`, the tag alone without its URL, or none."""
    if not tag:
        return "Release: none."
    project, separator, _ = pull_url.rpartition("/pull/")
    return f"Release: {project}/releases/tag/{tag}." if separator else f"Release: {tag}."


GOAL_SECTION = "goal"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
PARENTHESISED = re.compile(r"\s*\([^()]*\)")


def without_tracker_references(sentence: str) -> str:
    """`sentence` without the tracker references the public check finds (pub-004), its
    punctuation tidied; "" where fewer than two words are left.

    A parenthesised aside that holds one goes whole, `(SE#851, PR #853)`; so does a pointer word
    before one, `see #12`, and a connective before one that ends its clause, `found in obs#627.`;
    elsewhere the reference alone goes, with the comma that only listed it."""
    reference = f"(?:{sibling('public_check').TRACKER_REFERENCE.pattern})"
    text = PARENTHESISED.sub(
        lambda aside: "" if tracker_references(aside.group()) else aside.group(), sentence)
    for form in (
        rf"\b(?:see|cf\.)\s+{reference}",
        rf"\s*\b(?:in|from|via|by|after|of|on|at|for|per|with|and|or)\s+{reference}"
        r"(?=\s*(?:[,;:.!?]|$))",
        rf"{reference}\s*,\s*",
        rf"\s*,\s*{reference}",
        reference,
    ):
        text = re.sub(form, "", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+([,;:.!?)])", r"\1", text)
    text = re.sub(r"[,;:]+(?=[.!?;:,]|$)", "", text)
    text = text.strip(" ,;:")
    if len(re.findall(r"[^\W\d_]+", text)) < 2:
        return ""
    return text[0].upper() + text[1:]


def goal_summary(issue_body: str) -> str:
    """The first sentence of the work issue's Goal, without its tracker references: what the work
    is, as the landing's title names it; "" where the Goal is missing or names no more than that."""
    goal = re.sub(r"<!--.*?-->", "", section(markdown_sections(issue_body), GOAL_SECTION),
                  flags=re.DOTALL)
    text = " ".join(goal.split())
    if not text:
        return ""
    sentence = without_tracker_references(SENTENCE_END.split(text, maxsplit=1)[0])
    if not sentence or tracker_references(sentence) or PUBLIC_HOST_PATTERN.search(sentence):
        return ""
    return one_line(sentence, 120)


def integration_merge_message(
    branch: str, work_number: int, pull_number: int, public: bool, issue_body: str
) -> str:
    """The integration's title, the landing pull request's and the squash commit's: `Integrate
    <branch>: <the first sentence of the work issue's Goal>`, never a commit's subject; without
    a public check it also names the work issue and pull request."""
    summary = goal_summary(issue_body)
    title = f"Integrate {branch}" + (f": {summary}" if summary else "")
    if not public:
        return f"{title} (work issue #{work_number}, PR #{pull_number})"
    if tracker_references(title) or PUBLIC_HOST_PATTERN.search(title):
        raise QueueError("Public merge messages cannot contain tracker references or host addresses")
    return title


FIELD_REPORT_IN = "<!-- se:field-report-in {number} -->"


def landing_description(work_pull_url: str, work_pull_number: int, issue_url: str,
                        metrics_line: dict[str, object] | None = None) -> str:
    """The landing pull request's description: short enough for any tool argument, it names the
    work issue and the work pull request whose description is the field report, and the marker
    CI's field-report step reads that report by (.github/workflows/check.yml); it ends in the
    integration's metrics line, which outlives a cloud integrator's container for `retro.py
    collect` (README "Metrics")."""
    return (f"Refs {issue_url}\n\n"
            f"Lands {work_pull_url}, whose description is the field report.\n\n"
            + FIELD_REPORT_IN.format(number=work_pull_number) + "\n"
            + (f"\n{metrics.text(metrics_line)}\n" if metrics_line is not None else ""))


def parsed_identity(configured: object, source: str) -> tuple[str, str]:
    identity = IDENTITY_PATTERN.fullmatch(configured) if isinstance(configured, str) else None
    if identity is None:
        raise QueueError(
            f"{source} must have the form \"Name <email>\", for example \"mb <mb>\"; fix or remove it"
        )
    return identity["name"], identity["email"]


def commit_identity(root: Path) -> tuple[str, str, str] | None:
    """(name, email, source) of the commit identity: the machine-local `public_identity`, else
    se.toml `project.identity`; None when neither is set."""
    configured = config_value("public_identity", remote_repo(root), None)
    if configured:
        source = f"public_identity in {local_config_path()}"
        return (*parsed_identity(configured, source), source)
    configured = project_config(root).get("identity")
    if configured is None or configured == "":
        return None
    source = f"project.identity in {root / 'se.toml'}"
    return (*parsed_identity(configured, source), source)


def required_identity(root: Path, command: str) -> tuple[str, str]:
    """(name, email) every commit `command` makes carries; refused without a commit identity."""
    identity = commit_identity(root)
    if identity is None:
        raise QueueError(
            f"work_tickets.py {command}: no commit identity; set identity = \"Name <email>\" in "
            f"[project] of {root / 'se.toml'} (README \"Project settings\"), run "
            "work_tickets.py sync and try again"
        )
    return identity[0], identity[1]


def identity_environment(identity: tuple[str, str]) -> dict[str, str]:
    """The environment that makes a git commit carry `identity` as author and committer, whatever
    the clone's configuration or the environment's own GIT_AUTHOR_* and GIT_COMMITTER_* say."""
    name, email = identity
    return {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}


def configured_public_identity(root: Path) -> tuple[str, str]:
    identity = commit_identity(root)
    if identity is not None:
        return identity[0], identity[1]
    values: list[str] = []
    for key in ("user.name", "user.email"):
        result = run_git(root, "config", "--get", key)
        if result.returncode != 0 or not result.stdout.strip():
            raise QueueError(
                "A public mirror requires public_identity in the machine-local config, "
                "project.identity in se.toml or a configured git user.name and user.email"
            )
        values.append(result.stdout.strip())
    return values[0], values[1]


def public_push_commits(root: Path, mirror: Mirror) -> list[str]:
    remote_head = run_git(root, "ls-remote", mirror.remote, f"refs/heads/{mirror.branch}")
    if remote_head.returncode != 0:
        detail = failure_detail(remote_head)
        raise QueueError(f"Cannot read public mirror {mirror.remote}: {detail}")
    head = remote_head.stdout.split(maxsplit=1)
    target = integration_branch(root)
    revision = f"{head[0]}..{target}" if head else target
    commits = run_git(root, "rev-list", "--reverse", revision)
    if commits.returncode != 0:
        detail = failure_detail(commits)
        raise QueueError(f"Cannot list commits for public mirror {mirror.remote}: {detail}")
    return [commit for commit in commits.stdout.splitlines() if commit]


def guard_public_push(root: Path, mirror: Mirror) -> None:
    expected_name, expected_email = configured_public_identity(root)
    public_check = sibling("public_check")
    host, _, path = (remote_repo(root) or "").partition("/")
    owner = path.split("/", 1)[0].lower() if host.lower() == "github.com" else None
    for commit in public_push_commits(root, mirror):
        details = run_git(root, "show", "-s", "--format=%B%x00%an%x00%ae%x00%cn%x00%ce", commit)
        if details.returncode != 0:
            detail = failure_detail(details)
            raise QueueError(f"Cannot inspect {commit} before public push: {detail}")
        values = details.stdout.rstrip("\n").split("\x00")
        if len(values) != 5:
            raise QueueError(f"Cannot parse {commit} before public push")
        message, author_name, author_email, committer_name, committer_email = values
        if tracker_references(message):
            raise QueueError(f"Cannot push {commit} to a public mirror: message has a tracker reference")
        if public_check.made_on_github_by_owner(f"{author_name} <{author_email}>",
                                                f"{committer_name} <{committer_email}>", owner):
            continue  # the squash commit of a landing pull request
        if (author_name, author_email) != (expected_name, expected_email):
            raise QueueError(f"Cannot push {commit} to a public mirror: author differs from public_identity")
        if (committer_name, committer_email) != (expected_name, expected_email):
            raise QueueError(
                f"Cannot push {commit} to a public mirror: committer differs from public_identity"
            )


CHECK_NAME = "check"
CHECK_POLL_SECONDS = 30
CHECK_POLLS = 120  # an hour: the suite's limit is minutes, a queued runner may add some
LANDING_PREFIX = "land/"
HANDOFF_DIRECTORY = "handoff"


# The GitHub boundary. A command that talks to GitHub does everything local itself and states its
# GitHub steps as one Plan: numbered steps, each a tool of the host's GitHub tools (the GitHub MCP
# server's names) with its arguments. Where gh is signed in the command runs the plan itself
# through its door; where it is not (Claude's cloud) it prints the plan, the session runs it with
# its own GitHub tools, and the command's --read-back checks the result through git alone.


@dataclass(frozen=True)
class Later:
    """An argument a step takes from what an earlier step gave: `name` from step `step`."""

    name: str
    step: int

    def __str__(self) -> str:
        return f"<{self.name} from step {self.step}>"


@dataclass(frozen=True)
class Step:
    """One GitHub step: the host's `tool` with its `arguments`, what to watch for (`note`) and the
    values it gives later steps or the read-back (`gives`). `action` names what the local runner
    does for it, with an optional `:<detail>` (the label an issue step adds or removes)."""

    action: str
    tool: str
    arguments: dict[str, object]
    note: str = ""
    gives: tuple[str, ...] = ()


def plain(value: object) -> object:
    """`value` as the plan prints it: each Later as its placeholder."""
    if isinstance(value, Later):
        return str(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


@dataclass(frozen=True)
class Plan:
    """The GitHub steps of one command, in order, and the command that follows them (`then`)."""

    title: str
    steps: tuple[Step, ...]
    then: str = ""

    def data(self) -> dict[str, object]:
        return {"title": self.title, "then": self.then, "steps": [
            {"step": index, "tool": step.tool, "arguments": plain(step.arguments),
             **({"note": step.note} if step.note else {}),
             **({"gives": list(step.gives)} if step.gives else {})}
            for index, step in enumerate(self.steps, 1)]}

    def text(self) -> str:
        lines = [f"GitHub plan: {self.title}"]
        for index, step in enumerate(self.steps, 1):
            lines.append(f"{index}. {step.tool} "
                         f"{json.dumps(plain(step.arguments), ensure_ascii=False, sort_keys=True)}")
            if step.note:
                lines.append(f"   {step.note}")
            if step.gives:
                lines.append(f"   Gives: {', '.join(step.gives)}")
        if self.then:
            lines.append(f"Then: {self.then}")
        return "\n".join(lines)


Action = Callable[[dict[str, object], str], "dict[str, object] | None"]


def run_plan(plan: Plan, actions: dict[str, Action]) -> dict[str, object]:
    """Run `plan` here, through the door: each step's action with its arguments, every Later
    resolved from what its step gave; every value given, by name."""
    given: dict[tuple[str, int], object] = {}
    named: dict[str, object] = {}

    def resolved(value: object) -> object:
        if isinstance(value, Later):
            return given[(value.name, value.step)]
        if isinstance(value, dict):
            return {key: resolved(item) for key, item in value.items()}
        return value

    for index, step in enumerate(plan.steps, 1):
        action, _, detail = step.action.partition(":")
        for name, value in (actions[action](resolved(step.arguments), detail) or {}).items():
            given[(name, index)] = value
            named[name] = value
    return named


def hand_off() -> bool:
    """Whether a command hands its GitHub steps to the session: where gh is not signed in."""
    return not gh_usable()


def owner_repo(repo: str) -> dict[str, str]:
    owner, name = api_repo(repo).split("/")
    return {"owner": owner, "repo": name}


def pull_url(repo: str, number: int) -> str:
    host = repo_host(repo) or "github.com"
    return "https://" + f"{host}/{api_repo(repo)}/pull/{number}"


def issue_url(repo: str, number: int) -> str:
    host = repo_host(repo) or "github.com"
    return "https://" + f"{host}/{api_repo(repo)}/issues/{number}"


class PausedError(QueueError):
    """The fleet is paused: an open issue labelled PAUSE_LABEL (work model, Pause)."""


def pause_issues(root: Path, repo: str) -> list[dict[str, object]]:
    """The open issues labelled PAUSE_LABEL in `repo`, read now: the owner's pause switch
    (work model, Pause). None open: not paused."""
    return json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", PAUSE_LABEL,
        "--json", "number,title,url", "--limit", "20", *repo_arguments(repo),
    ]) or "[]")


def pause_names(found: list[dict[str, object]]) -> str:
    return ", ".join(f"#{issue['number']} {issue['title']} {issue['url']}" for issue in found)


def refuse_while_paused(command: str, found: list[dict[str, object]]) -> None:
    """Raise PausedError naming `command`, the pause issue and the remedy, where `found` holds
    one."""
    if found:
        raise PausedError(
            f"work_tickets.py {command}: the fleet is paused by the open {PAUSE_LABEL} issue "
            f"{pause_names(found)}; {command} starts, lands and routes nothing while it is open. "
            "The owner resumes the fleet by closing it (work model, Pause)")


def pause_step(repo: str) -> Step:
    """The plan step that runs the pause search with the host's GitHub tools."""
    return Step("paused", "list_issues", {
        **owner_repo(repo), "state": "OPEN", "labels": [PAUSE_LABEL], "perPage": 20},
        note="An issue listed means the fleet is paused: stop here, run no later step and start, "
             "land or route nothing; the owner resumes it by closing that issue")


def pause_plan(repo: str) -> Plan:
    return Plan(f"paused? {PAUSE_LABEL} issues of {repo}", (pause_step(repo),),
                "no issue listed: not paused")


def tracker_actions(root: Path, repo: str) -> dict[str, Action]:
    """The local runner's issue steps on `repo`, through gh."""
    def comment(arguments: dict[str, object], _: str) -> None:
        run_gh_with_body(root, ["issue", "comment", str(arguments["issue_number"]),
                                *repo_arguments(repo)], str(arguments["body"]))

    def add_label(arguments: dict[str, object], label: str) -> None:
        run_gh(root, ["issue", "edit", str(arguments["issue_number"]), "--add-label", label,
                      *repo_arguments(repo)])

    def remove_label(arguments: dict[str, object], label: str) -> None:
        run_gh(root, ["issue", "edit", str(arguments["issue_number"]), "--remove-label", label,
                      *repo_arguments(repo)])

    def close(arguments: dict[str, object], _: str) -> None:
        run_gh(root, ["issue", "close", str(arguments["issue_number"]), *repo_arguments(repo)])

    return {"comment_issue": comment, "add_label": add_label, "remove_label": remove_label,
            "close_issue": close}


def label_step(repo: str, number: int, label: str, add: bool) -> Step:
    change = "with" if add else "without"
    return Step(f"{'add' if add else 'remove'}_label:{label}", "issue_write", {
        **owner_repo(repo), "method": "update", "issue_number": number,
        "labels": f"<the issue's labels {change} {label}>"},
        note="issue_read get_labels reads the issue's labels; issue_write sets the whole list")


def escalation_plan(repo: str, number: int, reason: str) -> Plan:
    return Plan(f"escalate #{number}", (
        Step("comment_issue", "add_issue_comment", {
            **owner_repo(repo), "issue_number": number, "body": f"Integration stopped: {reason}\n"}),
        label_step(repo, number, "escalated", add=True),
    ))


def integration_escalation(root: Path, number: int, repo: str, reason: str) -> None:
    plan = escalation_plan(repo, number, reason)
    if hand_off():
        print(plan.text())
        return
    run_plan(plan, tracker_actions(root, repo))


class GitHub:
    """The door to GitHub's pull requests and check runs for `repo` (`<host>/<owner>/<repo>`),
    through `gh api`; the one place the local runner of a plan talks to GitHub about pull requests,
    so tests replace it with a fake."""

    def __init__(self, root: Path, repo: str) -> None:
        self.root, self.slug, self.host = root, api_repo(repo), repo_host(repo)

    def text(self, path: str, method: str = "GET", data: dict[str, object] | None = None) -> str:
        """The raw response to `method` on `repos/<repo>/<path>`, with `data` as its JSON body."""
        arguments = ["api", "-X", method, f"repos/{self.slug}/{path}",
                     *(("--hostname", self.host) if self.host and self.host != "github.com" else ())]
        if data is None:
            return run_gh(self.root, arguments)
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "body.json"
            body.write_text(json.dumps(data), encoding="utf-8")
            return run_gh(self.root, [*arguments, "--input", str(body)])

    def api(self, path: str, method: str = "GET", data: dict[str, object] | None = None) -> object:
        output = self.text(path, method, data)
        return json.loads(output) if output.strip() else {}

    def pull(self, number: int) -> dict[str, object]:
        return self.api(f"pulls/{number}")

    def open_pull(self, head: str, base: str) -> dict[str, object] | None:
        owner = self.slug.split("/")[0]
        found = self.api(f"pulls?state=open&head={owner}:{head}&base={base}")
        return found[0] if found else None

    def create_pull(self, head: str, base: str, title: str, body: str) -> dict[str, object]:
        return self.api("pulls", "POST", {"head": head, "base": base, "title": title, "body": body})

    def update_pull(self, number: int, title: str, body: str) -> dict[str, object]:
        return self.api(f"pulls/{number}", "PATCH", {"title": title, "body": body})

    def comment(self, number: int, body: str) -> dict[str, object]:
        return self.api(f"issues/{number}/comments", "POST", {"body": body})

    def close_pull(self, number: int) -> None:
        self.api(f"pulls/{number}", "PATCH", {"state": "closed"})

    def check_run(self, sha: str, name: str) -> dict[str, object] | None:
        """The newest check run `name` on commit `sha`, or None before one exists."""
        runs = self.api(f"commits/{sha}/check-runs?check_name={name}").get("check_runs") or []
        return max(runs, key=lambda run: int(run.get("id") or 0)) if runs else None

    def squash(self, number: int, sha: str, title: str, message: str) -> str:
        """Squash-merge pull request `number` at head `sha` with exactly `title` and `message`;
        the merged commit's sha."""
        merged = self.api(f"pulls/{number}/merge", "PUT", {
            "merge_method": "squash", "sha": sha, "commit_title": title, "commit_message": message,
        })
        return str(merged.get("sha") or "")


def wait_for_check(door: GitHub, sha: str, pull_url: str) -> str:
    """Wait for the required check `check` on the landing head `sha`; its run's URL once it
    succeeds, refused when it concludes otherwise or does not finish within CHECK_POLLS polls."""
    for poll in range(1, CHECK_POLLS + 1):
        run = door.check_run(sha, CHECK_NAME)
        if run is not None and run.get("status") == "completed":
            url = str(run.get("html_url") or pull_url)
            if run.get("conclusion") == "success":
                print(f"Check {CHECK_NAME}: success ({url})")
                return url
            raise QueueError(
                f"The required check {CHECK_NAME} concluded {run.get('conclusion')} on {sha[:12]} "
                f"({url}); nothing was merged into the integration branch. Read the run, fix the "
                "cause on the work branch, then integrate again"
            )
        state = "not started" if run is None else str(run.get("status"))
        print(f"Check {CHECK_NAME}: {state} on {sha[:12]} (poll {poll}/{CHECK_POLLS}); "
              f"waiting {CHECK_POLL_SECONDS} s")
        github_wait(CHECK_POLL_SECONDS)
    raise QueueError(
        f"The required check {CHECK_NAME} did not finish on {sha[:12]} within "
        f"{CHECK_POLLS * CHECK_POLL_SECONDS // 60} minutes ({pull_url}); nothing was merged. Look at "
        "the pull request's checks, then integrate again, which reuses the pull request"
    )


def remote_head(root: Path, branch: str) -> str:
    listed = checked_git(root, "ls-remote", "origin", f"refs/heads/{branch}").split()
    return listed[0] if listed else ""


def tree_of(root: Path, commit: str) -> str:
    return checked_git(root, "rev-parse", f"{commit}^{{tree}}").strip()


def abandon_landing(root: Path, target: str, landing: str) -> None:
    """Leave the landing branch: back on the integration branch, the local landing branch gone."""
    subprocess.run(["git", "-C", str(root), "merge", "--abort"], capture_output=True, check=False)
    checked_git(root, "switch", "-q", "--discard-changes", target)
    run_git(root, "branch", "-D", landing)


def landing_plan(remote: str, landing: str, target: str, base: str, landed: str, title: str,
                 message: str, description: str, then: str, tracker: str) -> Plan:
    """The pause search on `tracker`, then open or reuse the landing pull request, wait for
    `check` on `landed`, squash-merge it there with exactly `title` and `message`: the GitHub
    steps of landing on `target`."""
    where = owner_repo(remote)
    number = Later("pull number", 2)
    return Plan(f"land {landing} on {target}", (
        pause_step(tracker),
        Step("open_pull", "create_pull_request", {
            **where, "head": landing, "base": target, "title": title, "body": description},
            note=f"Where list_pull_requests (state open, head {where['owner']}:{landing}, base "
                 f"{target}) lists one, update_pull_request that one with this title and body "
                 "instead",
            gives=("pull number", "pull url")),
        Step("wait_check", "pull_request_read", {
            **where, "method": "get_check_runs", "pullNumber": number},
            note=f"Every {CHECK_POLL_SECONDS} s, up to {CHECK_POLLS * CHECK_POLL_SECONDS // 60} "
                 f"minutes, until the check run {CHECK_NAME} on {landed} completes; any conclusion "
                 "but success: merge nothing, fix the cause on the work branch, integrate again",
            gives=("check run url",)),
        Step("squash", "merge_pull_request", {
            **where, "pullNumber": number, "merge_method": "squash", "commit_title": title,
            "commit_message": message, "expectedHeadSha": landed},
            note=f"Only while origin's {target} is still {base} (git ls-remote origin "
                 f"refs/heads/{target}); where it moved, merge nothing and integrate again",
            gives=("merge commit sha",)),
    ), then)


def landing_actions(root: Path, door: GitHub, landing: str, target: str, base: str,
                    tracker: str) -> dict[str, Action]:
    """The local runner of a landing plan, through the door."""
    seen: dict[str, str] = {}

    def paused(_: dict[str, object], __: str) -> None:
        refuse_while_paused("integrate", pause_issues(root, tracker))

    def open_pull(arguments: dict[str, object], _: str) -> dict[str, object]:
        title, body = str(arguments["title"]), str(arguments["body"])
        pull = door.open_pull(landing, target)
        if pull is None:
            pull = door.create_pull(landing, target, title, body)
            print(f"Landing pull request opened: {pull.get('html_url')}")
        else:
            pull = door.update_pull(int(pull["number"]), title, body)
            print(f"Landing pull request reused: {pull.get('html_url')}")
        seen["url"] = str(pull.get("html_url") or "")
        return {"pull number": int(pull["number"]), "pull url": seen["url"]}

    def check(arguments: dict[str, object], _: str) -> dict[str, object]:
        landed = checked_git(root, "rev-parse", landing).strip()
        return {"check run url": wait_for_check(door, landed, seen["url"])}

    def squash(arguments: dict[str, object], _: str) -> dict[str, object]:
        number, url = int(arguments["pullNumber"]), seen["url"]
        moved = remote_head(root, target)
        if moved != base:
            raise QueueError(
                f"origin's {target} moved from {base[:12]} to {moved[:12] or 'nothing'} while "
                f"{url} waited; nothing was merged, as a squash onto it would land an untested "
                "tree. Integrate again, which merges the newest integration branch and reuses the "
                "pull request"
            )
        merged = door.squash(number, str(arguments["expectedHeadSha"]),
                             str(arguments["commit_title"]), str(arguments["commit_message"]))
        read = door.pull(number)
        if not read.get("merged") or str(read.get("merge_commit_sha") or "") != merged or not merged:
            raise QueueError(
                f"{url} reads back as merged={read.get('merged')} at "
                f"{read.get('merge_commit_sha')!r}, not the squash commit {merged!r} the merge "
                "returned; check the pull request on GitHub before integrating anything else"
            )
        return {"merge commit sha": merged}

    return {"paused": paused, "open_pull": open_pull, "wait_check": check, "squash": squash}


def landing_read_back(root: Path, target: str, base: str, landed: str,
                      merged: str | None = None) -> str:
    """Read the landing back through git alone: origin's `target` (`merged`, where the merge
    returned one) is one commit on `base` with the tree of `landed`, the tree the checks passed;
    that commit."""
    checked_git(root, "fetch", "-q", "origin", f"+refs/heads/{target}:refs/remotes/origin/{target}")
    head = remote_head(root, target)
    if merged is None and head == base:
        raise QueueError(
            f"origin's {target} is still {base[:12]}, the base the landing was tested on: the "
            "squash merge has not landed. Run the plan's merge step, then read back again")
    commit = merged or head
    problems = []
    if head != commit:
        problems.append(f"origin's {target} is not {commit[:12]}")
    if checked_git(root, "rev-parse", f"{commit}^").strip() != base:
        problems.append(f"its parent is not {base[:12]}")
    if tree_of(root, commit) != tree_of(root, landed):
        problems.append(f"its tree is not the tree of {landed[:12]} that the checks passed")
    if problems:
        raise QueueError(
            f"The squash commit {commit[:12]} does not read back as tested: "
            + "; ".join(problems) + f". Check origin's {target} before integrating anything else"
        )
    print(f"Landed: {commit[:12]} on {target}, on {base[:12]} with the tree of {landed[:12]}")
    return commit


def closeout_plan(remote: str, tracker: str, pull_number: int, work_number: int, landed: str,
                  comment: str, pending: list[str]) -> Plan:
    """Close the work pull request with a line naming the landing, comment on the work issue,
    take it out of progress and close it unless post-merge acceptance keeps it open."""
    pulls = owner_repo(remote)
    issues = owner_repo(tracker)
    return Plan(f"close out #{work_number}", (
        Step("comment_pull", "add_issue_comment",
             {**pulls, "issue_number": pull_number, "body": landed}),
        Step("close_pull", "update_pull_request",
             {**pulls, "pullNumber": pull_number, "state": "closed"}),
        Step("comment_issue", "add_issue_comment",
             {**issues, "issue_number": work_number, "body": comment}),
        label_step(tracker, work_number, "in-progress", add=False),
        *(() if pending else (Step("close_issue", "issue_write", {
            **issues, "method": "update", "issue_number": work_number, "state": "closed",
            "state_reason": "completed"}),)),
    ))


def handoff_path(root: Path, branch: str) -> Path:
    return root / ".se" / HANDOFF_DIRECTORY / f"{slug(branch, 80)}.json"


def handed_pull_request(root: Path, pull_number: int, remote: str, description: Path | None,
                        issue_body: Path | None, branch: str | None
                        ) -> tuple[dict[str, object], str, dict[str, object], int]:
    """What `pull_request_report` reads through gh, from the files the session saved with its
    GitHub tools: the pull request (its head from origin), its field report, its work issue and
    that issue's number."""
    if description is None or issue_body is None or not branch:
        raise QueueError(
            f"work_tickets.py integrate hands its GitHub steps to the session, as gh is not signed "
            f"in: save pull request #{pull_number}'s description and its work issue's body with the "
            "GitHub tools and pass --pr-description <file> --issue-body <file> --branch <its head "
            "branch>")
    text = read_file(description, "pull request description")
    where = f"pull request #{pull_number}"
    report = report_in(text, f"The description of {where}")
    work = WORK_ISSUE_PATTERN.search(report)
    if work is None:
        raise QueueError(
            f"The field report in {where} names no work issue; the worker writes "
            "**Work issue:** #<n> in its header and delivers again")
    body = issue_body_text(issue_body)
    problems = field_report_problems(report, body)
    if problems:
        raise field_report_error(f"in {where}", problems)
    checked_git(root, "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    pull = {"number": pull_number, "url": pull_url(remote, pull_number), "body": text,
            "headRefName": branch, "headRefOid": remote_head(root, branch)}
    return pull, report, {"body": body}, int(work[1])


def integrate(
    root: Path,
    pull_number: int,
    repo: str | None,
    build_command: str | None,
    check_commands: list[list[str]] | None = None,
    check_temporary_working_directory: bool = False,
    included: str | None = None,
    pr_description: Path | None = None,
    issue_body: Path | None = None,
    head_branch: str | None = None,
) -> str | None:
    """Land a delivered pull request's branch on the integration branch through a squash pull
    request: merge it into the newest integration branch on `land/<branch>`, run the checks,
    release and push; then the landing plan (open or reuse the landing pull request, the field
    report its description, wait for `check`, squash-merge), the read-back of the merged commit
    and the close-out. Where gh is not signed in the plan is printed for the session and None
    returned: `integrate --read-back <branch>` finishes. `included` states why commits after the
    field report's Branch tip are merged too."""
    tracker = resolve_repo(root, repo)
    handing_off = hand_off()
    if not handing_off:  # handed off, the landing plan's first step runs the pause search
        refuse_while_paused("integrate", pause_issues(root, tracker))
    remote = remote_repo(root)
    if remote is None:
        raise QueueError(
            f"work_tickets.py integrate: {root} has no origin remote to land on; add it with "
            "git remote add origin <url>"
        )
    feedback.phase(f"read pull request #{pull_number} and its field report")
    if handing_off:
        pull, report, work_issue, work_number = handed_pull_request(
            root, pull_number, remote, pr_description, issue_body, head_branch)
    else:
        pull, report, work_issue, work_number = pull_request_report(root, pull_number, tracker)
    metrics.note(issue=work_number)
    branch = str(pull.get("headRefName", ""))
    if not branch:
        raise QueueError(f"Pull request #{pull_number} has no head branch")
    feedback.phase(f"guard {branch} against its field report")
    guard(root, branch, report)

    target = integration_branch(root)
    if current_branch(root) != target:
        raise QueueError(
            f"work_tickets.py integrate: {root} is not on the integration branch {target}; "
            f"run git -C {root} switch {target}, or set project.integration_branch in se.toml"
        )
    feedback.phase(f"sync {target}")
    sync(root)
    base = checked_git(root, "rev-parse", "HEAD").strip()
    if base != remote_head(root, target):
        raise QueueError(
            f"work_tickets.py integrate: {target} in {root} is not origin's {target}; a landing "
            f"starts from origin's newest {target}, so reset the checkout to it "
            f"(git -C {root} reset --keep origin/{target}) and integrate again"
        )
    head = str(pull.get("headRefOid", ""))
    late = check_branch_tip(root, report, branch, head or branch, included)
    mirrors = configured_mirrors(root)
    trailer = config_value("commit_trailer", remote, None)
    kind = release_trailer(root, branch, str(work_issue["body"]), report)
    title = integration_merge_message(
        branch, work_number, pull_number,
        public_check_enabled(root) or any(mirror.public for mirror in mirrors),
        str(work_issue.get("body") or ""),
    )
    message = "\n\n".join((kind, *((trailer,) if trailer else ())))
    landing = f"{LANDING_PREFIX}{branch}"
    feedback.phase(f"merge {branch} on {landing}")
    checked_git(root, "switch", "-q", "-C", landing, base)
    merged = run_git(root, "merge", "--no-ff", "-m", title, "-m", message, branch_head(root, branch))
    if merged.returncode != 0:
        conflicts = run_git(root, "diff", "--name-only", "--diff-filter=U")
        abandon_landing(root, target, landing)
        files = ", ".join(line for line in conflicts.stdout.splitlines() if line.strip())
        raise QueueError(f"Cannot merge {branch}; conflicts: {files or 'unknown files'}")
    contained = run_git(root, "merge-base", "--is-ancestor", head, landing)
    if not head or contained.returncode != 0:
        abandon_landing(root, target, landing)
        reason = f"the merged {landing} does not contain the pull request head"
        integration_escalation(root, work_number, tracker, reason)
        raise QueueError(reason)

    has_public_mirror = any(mirror.public for mirror in mirrors)
    try:
        suite_result = run_suite(root, read_ci=True)
        if build_command:
            feedback.phase(f"output regeneration: {build_command}")
            run_project_command(root, build_command, "Output regeneration")
        if check_commands and not has_public_mirror:
            feedback.phase("project checks")
            run_project_checks(root, check_commands, check_temporary_working_directory)
        if public_check_enabled(root):
            feedback.phase("public check")
            run_public_check(root, base)
        feedback.phase("release")
        tag = release(root, landing, f"refs/remotes/origin/{target}")
        landed = checked_git(root, "rev-parse", "HEAD").strip()
        feedback.phase(f"push {landing}")
        push_gate(root, landing)
        guard_pushed_tree(root, landing)
        git_push(root, ["--force", "origin", f"{landing}:refs/heads/{landing}"])
        state = {
            "branch": branch, "landing": landing, "target": target, "base": base,
            "landed": landed, "head": head, "tag": tag, "tracker": tracker, "remote": remote,
            "pull_number": pull_number, "pull_url": str(pull.get("url") or ""),
            "work_number": work_number, "suite": suite_result, "late": late,
            "included": included, "pending": post_merge_acceptance(str(work_issue.get("body", ""))),
            "open_points": open_points(str(work_issue.get("body", "")), reported_tip(report)),
            "check_commands": check_commands,
            "check_temporary_working_directory": check_temporary_working_directory,
        }
        then = (f"work_tickets.py integrate --read-back {branch} --landing-pull <pull number from "
                f"step 2> --check-run <check run url from step 3> --landing-description <file: "
                f"the landing pull request's description, as pull_request_read get reads it "
                f"after step 4> --worktree {root}")
        description = landing_description(
            str(pull.get("url") or pull_url(remote, pull_number)), pull_number,
            issue_url(tracker, work_number), metrics.snapshot())
        plan = landing_plan(remote, landing, target, base, landed, title, message, description,
                            then, tracker)
        if handing_off:
            path = handoff_path(root, branch)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**state, "plan": plan.data()}, indent=2, sort_keys=True)
                            + "\n", encoding="utf-8")
            checked_git(root, "switch", "-q", target)
            print(f"Pushed {landing} at {landed[:12]}; gh is not signed in, so the session runs "
                  f"these GitHub steps with its GitHub tools (kept in {path}):")
            print(plan.text())
            return None
        feedback.phase("landing plan: the landing pull request, its check, the squash merge")
        door = GitHub(root, remote)
        given = run_plan(plan, landing_actions(root, door, landing, target, base, tracker))
        feedback.phase("read back the landed commit")
        commit = landing_read_back(root, target, base, landed, str(given["merge commit sha"]))
    except QueueError as error:
        abandon_landing(root, target, landing)
        if not isinstance(error, PausedError):  # a pause is the owner's, no escalation
            integration_escalation(root, work_number, tracker, str(error))
        raise
    return finish_integration(root, state, commit, str(given["pull url"]),
                              str(given["check run url"]), door)


def landed_metrics(state: dict[str, object], landing_pull: int, description: str) -> None:
    """Refuse a landing pull request whose `description` does not end in the metrics line the
    hand-off's plan gave it (step 2's body): the line `retro.py collect` reads the cloud
    integration's costs back from (README "Metrics")."""
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    bodies = [str((step.get("arguments") or {}).get("body") or "") for step in plan.get("steps", [])
              if isinstance(step, dict) and step.get("tool") == "create_pull_request"]
    expected = metrics.of_text(bodies[0]) if bodies else None
    found = metrics.of_text(description)
    if found is None or (expected is not None and found != expected):
        what = "names another metrics line" if found is not None else "has no metrics line"
        line = metrics.text(expected) if expected is not None else "Metrics: {...}"
        raise QueueError(
            f"The landing pull request #{landing_pull}'s description {what}: it ends in "
            f"`{line}`, the body of the plan's step 2. Update it to that body (update_pull_request "
            f"#{landing_pull}), save it again and read back again; nothing was closed")


def read_back_integration(root: Path, branch: str, landing_pull: int, check_run: str,
                          description: str) -> str:
    """The hand-off's second half: check the landing pull request's `description` for its
    metrics line, read the landing of `branch` back through git and finish the close-out,
    printing its GitHub steps for the session."""
    path = handoff_path(root, branch)
    if not path.is_file():
        raise QueueError(
            f"No hand-off for {branch} in {root} ({path} is missing); integrate <pull request> "
            "first, which writes it")
    state = json.loads(path.read_text(encoding="utf-8"))
    metrics.note(issue=state["work_number"])
    landed_metrics(state, landing_pull, description)
    feedback.phase(f"read back the landing of {branch}")
    commit = landing_read_back(root, state["target"], state["base"], state["landed"])
    short = finish_integration(root, state, commit, pull_url(state["remote"], landing_pull),
                               check_run, None)
    path.unlink()
    return short


def finish_integration(root: Path, state: dict[str, object], commit: str, landing_url: str,
                       run_url: str, door: GitHub | None) -> str:
    """After the read-back: the checkout at the landed commit, the release tag, the landing branch
    gone, the mirrors pushed, the close-out plan run through `door` (or, without one, printed for
    the session), the worker's worktree and branch removed and, with a door, what is unblocked
    started."""
    target, landing, tag = str(state["target"]), str(state["landing"]), state["tag"]
    tracker, remote = str(state["tracker"]), str(state["remote"])
    pull_number, work_number = int(state["pull_number"]), int(state["work_number"])
    check_commands = state.get("check_commands")
    temporary = bool(state.get("check_temporary_working_directory"))
    feedback.phase(f"close out: {target} at the landed commit, the release tag, the mirrors, "
                   "the work issue")
    checked_git(root, "switch", "-q", target)
    checked_git(root, "merge", "-q", "--ff-only", commit)
    run_git(root, "branch", "-D", landing)
    if tag and release_by_workflow(root):
        workflow_tags(str(tag))
    elif tag:
        checked_git(root, "tag", "-f", str(tag), commit)
        git_push(root, ["origin", f"refs/tags/{tag}"])
    deleted = run_git(root, "push", "origin", f":refs/heads/{landing}")
    if deleted.returncode != 0:
        print(f"Cleanup: {landing} left on origin ({failure_detail(deleted)}); the repository's "
              "automatic head-branch deletion removes it")
    for mirror in configured_mirrors(root):
        if mirror.public and check_commands:
            run_project_checks(root, check_commands, temporary)
        if mirror.public:
            guard_public_push(root, mirror)
        git_push(root, [mirror.remote, f"{target}:{mirror.branch}"])
    short = run_git(root, "rev-parse", "--short", commit).stdout.strip()
    suite_result = state["suite"]
    print(f"Suite: {suite_result}")
    late, included = state.get("late") or [], state.get("included")
    extra = (f"Includes {len(late)} commit(s) after the field report's Branch tip: {included}\n"
             if late else "")
    pending = list(state.get("pending") or [])
    points = list(state.get("open_points") or [])
    waits = ("Stays open until this acceptance is seen after the merge: "
             + "; ".join(pending) + "\n") if pending else ""
    if points:
        waits += ("Stays open for the review's open points, which a worker takes on this issue: "
                  + "; ".join(points) + "\n")
    comment = (
        f"Integrated in {short} from {state['pull_url'] or f'PR #{pull_number}'}, landed through "
        f"{landing_url} (check: {run_url}). {release_line(landing_url, tag)} "
        f"Suite: {suite_result}.\n{extra}{waits}")
    plan = closeout_plan(remote, tracker, pull_number, work_number,
                         f"Landed on {target} in {commit[:12]} through {landing_url}.",
                         comment, [*pending, *points])
    if door is None:
        print(plan.text())
    else:
        run_plan(plan, {**tracker_actions(root, tracker),
                        "comment_pull": lambda arguments, _: door.comment(
                            int(arguments["issue_number"]), str(arguments["body"])) and None,
                        "close_pull": lambda arguments, _: door.close_pull(
                            int(arguments["pullNumber"]))})
        state_read = run_gh(root, [
            "issue", "view", str(work_number), "--json", "state", "--jq", ".state",
            *repo_arguments(tracker),
        ]).strip() or "unreadable"
        print(f"Issue #{work_number}: {state_read} on GitHub after the merge")
    if pending:
        print(f"Close #{work_number} once its post-merge acceptance is seen: {'; '.join(pending)}")
    if points:
        print(f"#{work_number} stays open for the review's open points; start a worker on it for "
              f"them: {'; '.join(points)}")
    branch, landed = str(state["branch"]), str(state["landed"])
    try:
        remove_worker_worktree(root, branch, landed)
        print("Cleanup: worker worktree removed")
    except QueueError as error:
        print(f"warning: worker worktree was not removed: {error}", file=sys.stderr)
        print("Cleanup: worker worktree retained")
    delete_merged_branch(root, branch, str(state["head"]), landed)
    if door is None:
        print(f"Started: none here; start what is unblocked with the host's session tool ({WITHOUT_GH})")
        return short
    started = 0
    for candidate in ready_issues(root, tracker):
        slots = capacity(root, tracker)
        if slots is not None and slots <= 0:
            break
        start(root, int(candidate["number"]), tracker, None, True)
        started += 1
    print(f"Started: {started}")
    return short


REF_WORKFLOW = "ref-maintenance.yml"
REFS_REQUEST_MARKER = "<!-- se:refs-request -->"
REFS_DRY_RUN_MARKER = "<!-- se:refs-dry-run -->"
REFS_APPLIED_MARKER = "<!-- se:refs-applied -->"
REFS_REQUEST_ID_PATTERN = re.compile(r"<!-- se:refs-request-id (\d+) -->")
REFS_BLOCK_PATTERN = re.compile(r"```text\n(.*?)```", re.DOTALL)
ZERO_SHA = "0" * 40
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
RUN_POLL_SECONDS = 10
RUN_POLLS = 90  # fifteen minutes: the run pushes refs, a queued runner may add some
TIMESTAMP_PATTERN = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z ")
DRY_RUN_LINE_PATTERN = re.compile(r"^(?:set |delete |::error::|To |[ +*=!-]\t|Done$|error: |! )")


class Workflows(GitHub):
    """The door to the issue comments, labels and workflow runs `refs` uses, through `gh api`;
    tests replace it with a fake."""

    def comments(self, number: int) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        page = 1
        while True:
            batch = self.api(f"issues/{number}/comments?per_page=100&page={page}")
            found.extend(batch)
            if len(batch) < 100:
                return found
            page += 1

    def add_label(self, number: int, label: str) -> None:
        self.api(f"issues/{number}/labels", "POST", {"labels": [label]})

    def remove_label(self, number: int, label: str) -> None:
        try:
            self.api(f"issues/{number}/labels/{label}", "DELETE")
        except QueueError:
            pass  # a label already gone is the state asked for

    def newest_run(self, workflow: str) -> int:
        """The id of the newest workflow_dispatch run of `workflow`, 0 before any."""
        runs = self.api(f"actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=1")
        listed = runs.get("workflow_runs") or []
        return int(listed[0]["id"]) if listed else 0

    def dispatch(self, workflow: str, ref: str, inputs: dict[str, str]) -> None:
        self.api(f"actions/workflows/{workflow}/dispatches", "POST", {"ref": ref, "inputs": inputs})

    def run(self, run_id: int) -> dict[str, object]:
        return self.api(f"actions/runs/{run_id}")

    def run_log(self, run_id: int) -> str:
        """The log of the run's first job: the one job ref-maintenance has."""
        jobs = self.api(f"actions/runs/{run_id}/jobs").get("jobs") or []
        return self.text(f"actions/jobs/{jobs[0]['id']}/logs") if jobs else ""


def parse_triples(text: str) -> list[tuple[str, str, str]]:
    """Whitespace-separated `<old-sha> <new-sha> <ref>` triples, checked as ref-maintenance checks
    them, so a malformed request fails here and not in a run."""
    words = text.split()
    if not words or len(words) % 3:
        raise QueueError(
            "The triples must be whitespace-separated <old-sha> <new-sha> <ref>; got "
            f"{len(words)} words")
    triples = [tuple(words[index:index + 3]) for index in range(0, len(words), 3)]
    for old, new, ref in triples:
        for sha in (old, new):
            if not SHA_PATTERN.match(sha):
                raise QueueError(f"{ref}: '{sha}' is not a full 40-character lowercase sha")
        if not ref.startswith(("refs/heads/", "refs/tags/")):
            raise QueueError(f"{ref}: only refs/heads/... and refs/tags/... are maintained")
    if len({ref for _, _, ref in triples}) != len(triples):
        raise QueueError("Each ref may appear in one triple only")
    return triples


def triples_text(triples: list[tuple[str, str, str]]) -> str:
    return "".join(f"{old} {new} {ref}\n" for old, new, ref in triples)


def triple_line(old: str, new: str, ref: str) -> str:
    if new == ZERO_SHA:
        return f"delete {ref} (now {old[:12]})"
    if old == ZERO_SHA:
        return f"create {ref} at {new[:12]}"
    return f"move {ref} {old[:12]} -> {new[:12]}"


def workflow_steps(repo: str, ref: str, triples: list[tuple[str, str, str]], dry_run: bool,
                   first: int) -> tuple[Step, ...]:
    """Dispatch ref-maintenance on `ref` with the triples and wait for its run (steps `first` and
    `first` + 1); a dry run also reads the run's log. The workflow's concurrency group queues runs
    in order, so the first run newer than the newest before the dispatch is this one."""
    where = owner_repo(repo)
    wait_for = f"{RUN_POLLS * RUN_POLL_SECONDS // 60} minutes"
    steps = (
        Step("dispatch", "actions_run_trigger", {
            **where, "method": "run_workflow", "workflow_id": REF_WORKFLOW, "ref": ref,
            "inputs": {"updates": triples_text(triples), "dry_run": "true" if dry_run else "false"}},
            note=f"First note the newest workflow_dispatch run of {REF_WORKFLOW} (actions_list "
                 "list_workflow_runs): the run this dispatch starts is the first one newer"),
        Step("wait_run", "actions_list", {
            **where, "method": "list_workflow_runs", "resource_id": REF_WORKFLOW,
            "workflow_runs_filter": {"event": "workflow_dispatch"}},
            note=f"Every {RUN_POLL_SECONDS} s, up to {wait_for}, until that run completes",
            gives=("run url", "conclusion")),
    )
    if not dry_run:
        return steps
    return (*steps, Step("run_log", "get_job_logs", {
        **where, "job_id": f"<the one job of the run from step {first + 1}, as actions_list "
                           "list_workflow_jobs lists it>", "return_content": True},
        note="Save the log to a file", gives=("log file",)))


def workflow_actions(door: Workflows) -> dict[str, Action]:
    """The local runner of the refs plans, through the door."""
    seen: dict[str, object] = {}

    def comment(arguments: dict[str, object], _: str) -> dict[str, object]:
        posted = door.comment(int(arguments["issue_number"]), str(arguments["body"]))
        return {"comment id": int(posted["id"])}

    def dispatch(arguments: dict[str, object], _: str) -> None:
        seen["before"] = door.newest_run(REF_WORKFLOW)
        door.dispatch(str(arguments["workflow_id"]), str(arguments["ref"]),
                      dict(arguments["inputs"]))

    def wait_run(arguments: dict[str, object], _: str) -> dict[str, object]:
        run_id, run = 0, {}
        for poll in range(1, RUN_POLLS + 1):
            if not run_id:
                newest = door.newest_run(REF_WORKFLOW)
                run_id = newest if newest > int(seen["before"]) else 0
            if run_id:
                run = door.run(run_id)
                if run.get("status") == "completed":
                    seen["run"] = run_id
                    return {"run url": str(run.get("html_url") or ""),
                            "conclusion": str(run.get("conclusion"))}
            state = "not started" if not run_id else str(run.get("status"))
            print(f"ref-maintenance: {state} (poll {poll}/{RUN_POLLS}); waiting {RUN_POLL_SECONDS} s")
            github_wait(RUN_POLL_SECONDS)
        raise QueueError(
            f"ref-maintenance did not finish within {RUN_POLLS * RUN_POLL_SECONDS // 60} minutes; "
            "look at the repository's Actions runs, then run the command again")

    def run_log(arguments: dict[str, object], _: str) -> dict[str, object]:
        return {"log": door.run_log(int(seen["run"]))}

    return {
        "comment_issue": comment, "dispatch": dispatch, "wait_run": wait_run, "run_log": run_log,
        "add_label": lambda arguments, label: door.add_label(int(arguments["issue_number"]), label),
        "remove_label": lambda arguments, label: door.remove_label(
            int(arguments["issue_number"]), label),
    }


def dry_run_lines(log: str) -> list[str]:
    """The lines of a ref-maintenance log that say what the push did or would do."""
    lines = (TIMESTAMP_PATTERN.sub("", line).rstrip() for line in log.splitlines())
    return [line for line in lines if DRY_RUN_LINE_PATTERN.match(line)]


def remote_refs(root: Path, refs: list[str]) -> dict[str, str]:
    listed = checked_git(root, "ls-remote", "origin", *refs)
    return {name: sha for sha, name in (line.split("\t", 1) for line in listed.splitlines() if line)}


def refs_not_at(root: Path, triples: list[tuple[str, str, str]], new: bool) -> list[str]:
    """The refs origin does not hold at their old (or, with `new`, their new) sha, by
    `git ls-remote`; all zeros means absent."""
    found = remote_refs(root, [ref for _, _, ref in triples])
    return [ref for old, wanted, ref in triples
            if found.get(ref, ZERO_SHA) != (wanted if new else old)]


def hand_off_or_run(plan: Plan, door: Workflows | None) -> dict[str, object]:
    """Run `plan` through `door`, or, without one, print it for the session."""
    if door is None:
        print(plan.text())
        return {}
    return run_plan(plan, workflow_actions(door))


def refs_request(root: Path, number: int, file: Path, repo: str | None) -> str:
    """Post the triples on issue `number` and run ref-maintenance's dry run with them, then read
    back; where gh is not signed in, print these GitHub steps for the session and the read-back
    that follows them."""
    repo = resolve_repo(root, repo)
    triples = parse_triples(read_text_file(file, "triples"))
    lines = "\n".join(f"- {triple_line(*triple)}" for triple in triples)
    then = (f"work_tickets.py refs request {number} --triples-file {file} --read-back "
            "--request-id <comment id from step 1> --run-url <run url from step 3> "
            "--conclusion <conclusion from step 3> --log-file <log file from step 4> "
            f"--worktree {root}")
    plan = Plan(f"refs request on #{number}", (
        Step("comment_issue", "add_issue_comment", {
            **owner_repo(repo), "issue_number": number, "body": (
                f"{REFS_REQUEST_MARKER}\nOne-way ref change for `ref-maintenance`, prepared by the "
                f"integrator:\n\n{lines}\n\n```text\n{triples_text(triples)}```\n")},
            gives=("comment id",)),
        *workflow_steps(repo, integration_branch(root), triples, dry_run=True, first=2),
    ), then)
    door = None if hand_off() else Workflows(root, repo)
    given = hand_off_or_run(plan, door)
    if door is None:
        return "Then read back as the plan's last line says"
    return refs_request_read_back(root, number, triples, int(given["comment id"]),
                                  str(given["conclusion"]), str(given["run url"]),
                                  str(given["log"]), repo, door)


def refs_request_read_back(root: Path, number: int, triples: list[tuple[str, str, str]],
                           request_id: int, conclusion: str, url: str, log: str, repo: str,
                           door: Workflows | None) -> str:
    """Read the dry run back: post its output and, where it passed and origin still holds every
    ref at its old sha (`git ls-remote`), label the issue escalated; the one-line escalation for
    SE. Otherwise nothing is escalated and the request is refused."""
    stale = refs_not_at(root, triples, new=False)
    passed = conclusion == "success" and not stale
    output = "\n".join(dry_run_lines(log)) or "(no push lines in the log)"
    plan = Plan(f"refs dry run on #{number}", (
        Step("comment_issue", "add_issue_comment", {**owner_repo(repo), "issue_number": number, "body": (
            f"{REFS_DRY_RUN_MARKER}\n<!-- se:refs-request-id {request_id} -->\n"
            f"Dry run of `ref-maintenance`: {conclusion} ({url})\n\n```text\n{output}\n```\n")}),
        *((label_step(repo, number, "escalated", add=True),) if passed else ()),
    ))
    hand_off_or_run(plan, door)
    if conclusion != "success":
        raise QueueError(
            f"The dry run concluded {conclusion} ({url}); nothing was escalated. Fix the triples or "
            "push the commits they need, then run refs request again")
    if stale:
        raise QueueError(
            f"origin no longer holds {', '.join(stale)} at the old sha of its triple "
            "(git ls-remote); nothing was escalated. Write the triples from origin's refs, then "
            "run refs request again")
    after = "after these steps, " if door is None else ""
    return (f"{after}escalated #{number}: apply the ref change ({len(triples)} ref(s), dry run "
            f"passed)? On yes: work_tickets.py refs apply {number}")


def posted_request(comments: list[dict[str, object]], number: int
                   ) -> tuple[list[tuple[str, str, str]], int]:
    """The triples of the newest refs request among the issue's `comments`, refused unless its
    dry run passed."""
    requests = [comment for comment in comments
                if str(comment.get("body") or "").startswith(REFS_REQUEST_MARKER)]
    if not requests:
        raise QueueError(f"#{number} carries no refs request; the integrator posts one with refs request")
    request = requests[-1]
    block = REFS_BLOCK_PATTERN.search(str(request.get("body")))
    triples = parse_triples(block.group(1) if block else "")
    dry_runs = [comment for comment in comments
                if str(comment.get("body") or "").startswith(REFS_DRY_RUN_MARKER)
                and (match := REFS_REQUEST_ID_PATTERN.search(str(comment.get("body"))))
                and int(match.group(1)) == int(request["id"])]
    if not dry_runs or ": success (" not in str(dry_runs[-1].get("body")):
        raise QueueError(
            f"The newest refs request on #{number} has no passed dry run; the integrator runs refs "
            "request again")
    return triples, int(request["id"])


def saved_comments(file: Path | None, number: int) -> list[dict[str, object]]:
    """The issue's comments as the session's GitHub tools read them (issue_read get_comments),
    saved as a JSON list to `file`."""
    if file is None:
        raise QueueError(
            f"work_tickets.py refs apply hands its GitHub steps to the session, as gh is not "
            f"signed in: save #{number}'s comments (issue_read get_comments) as JSON and pass "
            "--comments-file <file>")
    comments = json.loads(read_text_file(file, "issue comments"))
    if not isinstance(comments, list):
        raise QueueError(f"{file} holds no JSON list of comments")
    return comments


def refs_apply(root: Path, number: int, repo: str | None, comments_file: Path | None = None) -> str:
    """For SE, on the person's yes: run ref-maintenance for real with the triples posted on issue
    `number`, then read the refs back; where gh is not signed in, print these GitHub steps for the
    session and the read-back that follows them."""
    repo = resolve_repo(root, repo)
    door = None if hand_off() else Workflows(root, repo)
    comments = saved_comments(comments_file, number) if door is None else door.comments(number)
    triples, request_id = posted_request(comments, number)
    then = (f"work_tickets.py refs apply {number} --comments-file {comments_file} --read-back "
            "--run-url <run url from step 2> --conclusion <conclusion from step 2> "
            f"--worktree {root}")
    plan = Plan(f"refs apply on #{number}",
                workflow_steps(repo, integration_branch(root), triples, dry_run=False, first=1),
                then)
    given = hand_off_or_run(plan, door)
    if door is None:
        return "Then read back as the plan's last line says"
    return refs_apply_read_back(root, number, triples, request_id, str(given["conclusion"]),
                                str(given["run url"]), repo, door)


def refs_apply_read_back(root: Path, number: int, triples: list[tuple[str, str, str]],
                         request_id: int, conclusion: str, url: str, repo: str,
                         door: Workflows | None) -> str:
    """Read the real run back: origin holds every ref at its new sha (`git ls-remote`); post the
    result and, where applied, take the issue out of escalated; the line for the integrator."""
    wrong = refs_not_at(root, triples, new=True) if conclusion == "success" else []
    applied = conclusion == "success" and not wrong
    mismatch = f"; not as requested on origin: {', '.join(wrong)}" if wrong else ""
    plan = Plan(f"refs applied on #{number}", (
        Step("comment_issue", "add_issue_comment", {**owner_repo(repo), "issue_number": number, "body": (
            f"{REFS_APPLIED_MARKER}\n<!-- se:refs-request-id {request_id} -->\n"
            f"`ref-maintenance` run: {conclusion} ({url}); refs "
            f"{'applied' if applied else 'not applied'}{mismatch}\n")}),
        *((label_step(repo, number, "escalated", add=False),) if applied else ()),
    ))
    hand_off_or_run(plan, door)
    if not applied:
        raise QueueError(
            f"The ref change on #{number} was not applied: run {conclusion} ({url}){mismatch}; "
            "read the run, then bring it to the person again")
    after = "after these steps, " if door is None else ""
    return f"{after}refs applied on #{number} ({url}): verify and close out"



# The fleet check: one read of GitHub and origin's branches that lists every stuck or stray piece
# of work with its remedy, and says healthy otherwise. It only reads.

FLEET_KINDS = ("no branch", "quiet branch", "failed check", "conflict", "stray branch",
               "impossible block", "block cycle", "waiting on the person")
# Listed, but neither stuck nor stray: in-progress work within its lease and still without a branch.
STARTING = "starting"
STARTED_PREFIX = "Started:"
FLEET_LEASE_HOURS = 3
FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "cancelled", "startup_failure",
                                "action_required"})
BLOCKER_PATTERN = re.compile(r"(?<![\w/.-])#(\d+)\b")
FLEET_PAGES = 5


@dataclass(frozen=True)
class Finding:
    """One thing the fleet check found: its kind, its issue, its pull request and branch where
    there are some, what is wrong, the remedy and the open issues it holds up."""

    kind: str
    issue: int
    what: str
    remedy: str
    pull: int | None = None
    branch: str | None = None
    holds: tuple[int, ...] = ()

    @property
    def stuck(self) -> bool:
        """Whether it is stuck or stray; a "starting" issue is listed, but healthy."""
        return self.kind != STARTING


def fleet_lease(root: Path) -> timedelta:
    """`[fleet] lease_hours` in se.toml: how long in-progress work may go without a push to its
    branch, and without a branch from its Started comment on; built in FLEET_LEASE_HOURS."""
    hours = se_table(root, "fleet").get("lease_hours", FLEET_LEASE_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise QueueError(f"fleet.lease_hours in {root / 'se.toml'} must be a positive number of "
                         "hours; fix it or remove it for the built-in 3")
    return timedelta(hours=hours)


def fleet_issue(raw: dict[str, object]) -> dict[str, object]:
    """An issue as the fleet check reads it, from gh's, the REST API's or the GitHub tools' form:
    number, title, state and state reason in lower case, label names, body and url."""
    labels = {str(label.get("name", "")) if isinstance(label, dict) else str(label)
              for label in raw.get("labels") or []}
    reason = raw.get("state_reason") or raw.get("stateReason") or ""
    return {"number": int(raw["number"]), "title": str(raw.get("title") or ""),
            "state": str(raw.get("state") or "").lower(), "reason": str(reason).lower(),
            "labels": labels, "body": str(raw.get("body") or ""),
            "url": str(raw.get("html_url") or raw.get("url") or "")}


def fleet_pull(raw: dict[str, object]) -> dict[str, object]:
    """A pull request as the fleet check reads it: number, head branch, description, mergeable
    state and the conclusion of its `check` run, in lower case."""
    head = raw.get("head") if isinstance(raw.get("head"), dict) else {}
    return {"number": int(raw["number"]),
            "head": str(head.get("ref") or raw.get("headRefName") or ""),
            "body": str(raw.get("body") or ""),
            "mergeable": str(raw.get("mergeable_state") or raw.get("mergeStateStatus") or "").lower(),
            "check": str(raw.get("check") or "").lower()}


def started_at(comments: object) -> datetime | None | str:
    """When the newest `Started:` comment of an issue was written, from the comments as gh, the REST
    API or the GitHub tools give them; a string saying why where it cannot be told."""
    if not isinstance(comments, list):
        return "its comments were not read"
    times = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if not str(comment.get("body") or "").lstrip().startswith(STARTED_PREFIX):
            continue
        when = comment.get("created_at") or comment.get("createdAt")
        try:
            times.append(datetime.fromisoformat(str(when).replace("Z", "+00:00")))
        except ValueError:
            continue
    if not times:
        return f"it has no {STARTED_PREFIX} comment with a time"
    return max(times)


def blockers_of(issue: dict[str, object]) -> list[int]:
    """The issues of the same repository its body's `## Blocked by` names."""
    blocked = section(issue_sections(str(issue["body"])), "blocked by")
    return sorted({int(number) for number in BLOCKER_PATTERN.findall(blocked)})


def fleet_branches(root: Path) -> dict[str, datetime]:
    """Origin's branches, each with the committer time of its tip, fetched with git."""
    checked_git(root, "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    listed = checked_git(root, "for-each-ref", "--format=%(refname:lstrip=3)%09%(committerdate:iso-strict)",
                         "refs/remotes/origin/")
    branches = {}
    for line in listed.splitlines():
        name, _, when = line.partition("\t")
        if name and name != "HEAD" and when:
            branches[name] = datetime.fromisoformat(when)
    return branches


def unlisted(data: object, key: str) -> list[dict[str, object]]:
    """The items of a list the GitHub tools gave, bare or under `key`."""
    if isinstance(data, dict):
        data = data.get(key, [])
    if not isinstance(data, list):
        raise QueueError(f"Expected a JSON list of {key}")
    return [item for item in data if isinstance(item, dict)]


class Fleet:
    """The fleet check's door through gh: issues of the tracker `repo`, the open pull requests to
    the integration branch `base` with their `check` run, origin's branches through git."""

    def __init__(self, root: Path, repo: str, base: str) -> None:
        self.root, self.base, self.github = root, base, GitHub(root, repo)

    def issues(self, state: str) -> list[dict[str, object]]:
        found = []
        query = "&labels=work&sort=updated" if state == "closed" else ""
        for page in range(1, FLEET_PAGES + 1):
            items = self.github.api(f"issues?state={state}{query}&per_page=100&page={page}")
            found += [item for item in items if "pull_request" not in item]
            if len(items) < 100 or state == "closed":
                break
        return found

    def issue(self, number: int) -> dict[str, object] | None:
        try:
            return self.github.api(f"issues/{number}")
        except QueueError:
            return None

    def comments(self, number: int) -> list[dict[str, object]] | None:
        try:
            return self.github.api(f"issues/{number}/comments?per_page=100")
        except QueueError:
            return None

    def pulls(self) -> list[dict[str, object]]:
        pulls = []
        for listed in self.github.api(f"pulls?state=open&base={self.base}&per_page=100"):
            pull = self.github.pull(int(listed["number"]))
            run = self.github.check_run(str(pull["head"]["sha"]), CHECK_NAME)
            pulls.append({**pull, "check": (run or {}).get("conclusion") or ""})
        return pulls

    def branches(self) -> dict[str, datetime]:
        return fleet_branches(self.root)


class FileFleet:
    """The fleet check's door without gh: what the session's GitHub tools read, from files."""

    def __init__(self, root: Path, open_issues: Path, closed_issues: Path, pulls: Path) -> None:
        self.root = root
        self.listed = {state: unlisted(json.loads(read_file(file, f"{state} issues")), "issues")
                       for state, file in (("open", open_issues), ("closed", closed_issues))}
        self.pull_list = unlisted(json.loads(read_file(pulls, "pull requests")), "pull_requests")

    def issues(self, state: str) -> list[dict[str, object]]:
        return self.listed[state]

    def issue(self, number: int) -> dict[str, object] | None:
        return None

    def comments(self, number: int) -> list[dict[str, object]] | None:
        listed = next((issue for issue in self.listed["open"]
                       if str(issue.get("number")) == str(number)), {})
        comments = listed.get("comments")
        return comments if isinstance(comments, list) else None

    def pulls(self) -> list[dict[str, object]]:
        return self.pull_list

    def branches(self) -> dict[str, datetime]:
        return fleet_branches(self.root)


def fleet_plan(repo: str, base: str) -> Plan:
    where = owner_repo(repo)
    return Plan("fleet check", (
        Step("open", "list_issues", {**where, "state": "OPEN", "perPage": 100},
             note="every page; for each issue labelled in-progress, add its comments "
                  "(issue_read get_comments) as \"comments\"; save the issues, with their bodies "
                  "and labels, as one JSON list",
             gives=("open issues file",)),
        Step("closed", "list_issues", {**where, "state": "CLOSED", "labels": ["work"],
                                       "orderBy": "UPDATED_AT", "direction": "DESC",
                                       "perPage": 100},
             note="first page; list_issues gives no state_reason, so replace each closed "
                  "issue an open issue's Blocked by names with what issue_read get gives (its "
                  "state_reason) and add those in neither list; save as one JSON list",
             gives=("closed issues file",)),
        Step("pulls", "list_pull_requests", {**where, "state": "open", "base": base,
                                             "perPage": 100},
             note="then pull_request_read get for each (its mergeable_state) and get_check_runs "
                  "on its head; save each pull request with \"check\": the conclusion of its "
                  f"{CHECK_NAME} run, as one JSON list", gives=("pulls file",)),
    ), then="work_tickets.py fleet-check --open-issues <open issues file> --closed-issues "
            "<closed issues file> --pulls <pulls file>")


def fleet_findings(door: object, now: datetime, lease: timedelta, repository: str
                   ) -> list[Finding]:
    """What is stuck or stray in the fleet `door` reads, in FLEET_KINDS order, lowest issue first
    within a kind; `repository` is the checkout's name, whose `repo:` label (or none) marks the
    issues whose branches live on this origin."""
    open_issues = {issue["number"]: issue for issue in map(fleet_issue, door.issues("open"))}
    closed = {issue["number"]: issue for issue in map(fleet_issue, door.issues("closed"))}
    pulls = [fleet_pull(pull) for pull in door.pulls()]
    branches = door.branches()
    found: list[Finding] = []

    def here(issue: dict[str, object]) -> bool:
        labels = {label.lower() for label in issue["labels"] if label.lower().startswith("repo:")}
        return not labels or f"repo:{repository.lower()}" in labels

    # In-progress work: a branch and a push within the lease, a delivered pull request that is green
    # and merges.
    for number, issue in open_issues.items():
        if IN_PROGRESS_LABEL not in issue["labels"] or not here(issue):
            continue
        branch = issue["title"]
        if branch not in branches:
            started = started_at(door.comments(number))
            if isinstance(started, datetime) and now - started <= lease:
                minutes = max(0, int((now - started).total_seconds() // 60))
                found.append(Finding(
                    STARTING, number,
                    f"started {minutes} minutes ago, within the lease of "
                    f"{lease.total_seconds() / 3600:g} hours; origin has no branch {branch} yet",
                    "none: its worker pushes the branch; listed again as no branch once the "
                    "lease has passed", branch=branch))
                continue
            since = (f"{int((now - started).total_seconds() // 3600)} hours after its Started "
                     "comment" if isinstance(started, datetime)
                     else f"and the lease cannot be counted: {started}")
            found.append(Finding(
                "no branch", number, f"in progress, but origin has no branch {branch}, {since}",
                f"start a worker on #{number} (work_tickets.py start), or take in-progress off "
                "and label it ready", branch=branch))
        elif now - branches[branch] > lease:
            hours = int((now - branches[branch]).total_seconds() // 3600)
            found.append(Finding(
                "quiet branch", number,
                f"no push to {branch} for {hours} hours, over the lease of "
                f"{lease.total_seconds() / 3600:g}",
                f"read its worker's session; where it stopped, start a worker again on {branch}, "
                "which syncs and delivers what it has", branch=branch))
    for pull in pulls:
        report = REPORT_BEGIN in pull["body"]
        work = WORK_ISSUE_PATTERN.search(pull["body"])
        number = int(work[1]) if work else next(
            (n for n, issue in open_issues.items() if issue["title"] == pull["head"]), 0)
        if not report:
            continue
        if pull["check"] in FAILED_CONCLUSIONS:
            found.append(Finding(
                "failed check", number, f"{CHECK_NAME} concluded {pull['check']} on {pull['head']}",
                f"a worker on {pull['head']} syncs, makes {CHECK_NAME} pass and delivers again",
                pull=pull["number"], branch=pull["head"]))
        if pull["mergeable"] in {"dirty", "conflicting"}:
            found.append(Finding(
                "conflict", number, f"{pull['head']} conflicts with the integration branch",
                f"a worker on {pull['head']} runs work_tickets.py sync (merge origin/main, never "
                "rebase), resolves and delivers again", pull=pull["number"], branch=pull["head"]))

    # Branches of closed issues, unless an open issue or pull request still uses the name.
    in_use = {issue["title"] for issue in open_issues.values()} | {pull["head"] for pull in pulls}
    for number, issue in closed.items():
        branch = issue["title"]
        if branch in branches and branch not in in_use and here(issue):
            found.append(Finding(
                "stray branch", number, f"#{number} is closed, but origin still has {branch}",
                f"git push origin --delete {branch}, once nothing on it is wanted", branch=branch))

    # Blocks: by an issue closed as not planned, or by itself through a cycle.
    blocked = {number: blockers_of(issue) for number, issue in open_issues.items()}
    for number, blockers in blocked.items():
        for blocker in blockers:
            if blocker in open_issues:
                continue
            issue = closed.get(blocker)
            if issue is None:
                raw = door.issue(blocker)
                issue = fleet_issue(raw) if raw else None
                if issue is not None:
                    closed[blocker] = issue
            if issue is not None and issue["reason"] == "not_planned":
                found.append(Finding(
                    "impossible block", number, f"blocked by #{blocker}, closed as not planned",
                    f"take #{blocker} out of #{number}'s Blocked by and its dependency, or close "
                    f"#{number} too"))
    cycles: set[int] = set()
    for start in sorted(blocked):
        path, seen = [start], {start}
        while path:
            following = [b for b in blocked.get(path[-1], []) if b in blocked]
            if start in following:
                if start not in cycles:
                    cycles.update(path)
                    loop = " -> ".join(f"#{n}" for n in [*path, start])
                    found.append(Finding(
                        "block cycle", start, f"blocked by itself: {loop}",
                        "SE decides which of them does not block the other and takes that block "
                        "out"))
                break
            step = next((b for b in following if b not in seen), None)
            if step is None:
                break
            path.append(step)
            seen.add(step)

    # What waits on the person, and the open issues it holds up.
    for number, issue in open_issues.items():
        if PERSON_LABEL not in issue["labels"]:
            continue
        holds, queue_ = set(), [number]
        while queue_:
            current = queue_.pop()
            for waiting, blockers in blocked.items():
                if current in blockers and waiting not in holds and waiting != number:
                    holds.add(waiting)
                    queue_.append(waiting)
        held = ", ".join(f"#{n}" for n in sorted(holds))
        found.append(Finding(
            "waiting on the person", number,
            f"waits for the person ({PERSON_LABEL})" + (f", holding up {held}" if held else ""),
            "SE presents it to the person with the decision skill", holds=tuple(sorted(holds))))

    rank = {kind: index for index, kind in enumerate((*FLEET_KINDS, STARTING))}
    return sorted(found, key=lambda finding: (rank[finding.kind], finding.issue))


def fleet_report(found: list[Finding], as_json: bool) -> str:
    """The findings, "healthy" where none is stuck; "starting" issues are listed either way."""
    stuck = [finding for finding in found if finding.stuck]
    if as_json:
        return json.dumps({"healthy": not stuck, "findings": [
            {"kind": f.kind, "issue": f.issue, "pull": f.pull, "branch": f.branch, "what": f.what,
             "remedy": f.remedy, "holds": list(f.holds)} for f in found]}, indent=2)
    lines = [] if stuck else ["healthy"]
    for finding in found:
        pull = f" PR #{finding.pull}" if finding.pull else ""
        lines += [f"{finding.kind} #{finding.issue}{pull}: {finding.what}",
                  f"  remedy: {finding.remedy}"]
    return "\n".join(lines)


@dataclass(frozen=True)
class Arg:
    """One argument, as argparse's add_argument takes it."""

    flags: tuple[str, ...]
    options: dict[str, object]


def arg(*flags: str, **options: object) -> Arg:
    return Arg(flags, options)


@dataclass(frozen=True)
class Exclusive:
    """Arguments of which at most one, or with required exactly one, is given."""

    members: tuple[Arg, ...]
    required: bool = False


@dataclass
class Command:
    """One command of the registry: its name, help and arguments, and either its handler or its
    subcommands. A handler takes the selected worktree (None without --worktree) and the parsed
    arguments and returns the exit code."""

    name: str
    help: str
    arguments: tuple[Arg | Exclusive, ...] = ()
    handler: Callable[[Path | None, argparse.Namespace], int] | None = None
    subcommands: list[Command] = field(default_factory=list)
    dest: str = "command"


COMMANDS = Command("work_tickets.py", __doc__ or "")


def command(name: str, help: str, *arguments: Arg | Exclusive, parent: Command = COMMANDS
            ) -> Callable[[Callable[[Path | None, argparse.Namespace], int]],
                          Callable[[Path | None, argparse.Namespace], int]]:
    """Register the decorated handler as the command `name` of `parent`, in declaration order."""
    def register(handler: Callable[[Path | None, argparse.Namespace], int]
                 ) -> Callable[[Path | None, argparse.Namespace], int]:
        parent.subcommands.append(Command(name, help, arguments, handler))
        return handler
    return register


def command_group(name: str, help: str, dest: str) -> Command:
    """Register a command whose subcommands, registered with parent=, do its work."""
    group = Command(name, help, dest=dest)
    COMMANDS.subcommands.append(group)
    return group


WORKTREE = arg("--worktree", required=True, help="path to the selected worktree")
OPTIONAL_WORKTREE = arg(
    "--worktree", default=".", help="path to the selected worktree; default: current checkout")
INCLUDE_LATE = arg(
    "--include-late", metavar="REASON",
    help="why commits on the branch after the field report's Branch tip are merged too; "
         "without it they are refused")
REPO = arg("--repo", help="[HOST/]OWNER/REPO; default: argument, [trackers], then origin")
WORKTREE_ROOT = arg(
    "--worktree-root",
    help="directory for new worktrees; default: sibling <checkout>.worktrees or "
         "[worktree_roots] in ~/.se/local.toml")
SESSION_HELP = "integrator session; default: integrator_session in ~/.se/local.toml"
JSON_OUTPUT = arg("--json", action="store_true", help="emit JSON")
INTEGRATION_TARGET = arg("--integration-target", help="Git ref containing worker commits")
ISSUE_BODY = arg("--issue-body", required=True, type=Path, help="file holding the work issue's body")


@command("init", "initialize the ticket queue", WORKTREE)
def run_init(root: Path, args: argparse.Namespace) -> int:
    initialize(root)
    print(f"Initialized ticket queue in {root / '.se' / 'work'}")
    return 0


@command("create", "create a ticket in todo",
         WORKTREE,
         arg("--id", required=True, help="stable ticket ID"),
         arg("--title", required=True, help="ticket title"),
         arg("--acceptance", action="append",
             help="one acceptance item, repeatable; replaces the placeholder item"))
def run_create(root: Path, args: argparse.Namespace) -> int:
    create_ticket(root, args.id, args.title, args.acceptance)
    print(f"Created ticket {args.id} in todo")
    return 0


@command("move", "move a ticket between states",
         WORKTREE,
         arg("--id", required=True, help="ticket ID"),
         arg("--to", required=True, choices=STATES))
def run_move(root: Path, args: argparse.Namespace) -> int:
    move_ticket(root, args.id, args.to)
    print(f"Moved ticket {args.id} to {args.to}")
    return 0


@command("status", "report queue status", WORKTREE, JSON_OUTPUT, INTEGRATION_TARGET)
def run_status(root: Path, args: argparse.Namespace) -> int:
    report = status_report(root, args.integration_target)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Initialized: {'yes' if report['initialized'] else 'no'}")
        print("Counts: " + ", ".join(f"{state}={report['counts'][state]}" for state in STATES))
        for state in STATES:
            print(f"{state}: {', '.join(report['tickets'][state]) or '(none)'}")
        print(f"notes: {', '.join(report['notes']) or '(none)'}")
        print("notes resolved/unresolved: "
              f"{report['note_counts']['resolved']}/{report['note_counts']['unresolved']}")
        print(f"complete: {'yes' if report['complete'] else 'no'}")
        print(f"cleanup eligible: {'yes' if report['cleanup_eligible'] else 'no'}")
        for reason in report["cleanup_reasons"]:
            print(f"cleanup reason: {reason}")
        for error in report["errors"]:
            print(f"error: {error}")
    return 0 if report["initialized"] and not report["errors"] else 1


@command("review-note", "append a local note disposition",
         WORKTREE,
         arg("--note", required=True, help="note filename in work/notes"),
         arg("--disposition", required=True, help="local review decision"),
         arg("--backlog-ref", help="optional authored backlog reference"))
def run_review_note(root: Path, args: argparse.Namespace) -> int:
    review_note(root, args.note, args.disposition, args.backlog_ref)
    print(f"Reviewed note {args.note}")
    return 0


@command("close", "check or close an integrated worktree",
         WORKTREE, INTEGRATION_TARGET,
         arg("--remove", action="store_true", help="remove eligible linked worktree"),
         JSON_OUTPUT)
def run_close(root: Path, args: argparse.Namespace) -> int:
    if args.remove and not args.integration_target:
        raise QueueError("--remove requires --integration-target")
    report = status_report(root, args.integration_target)
    report["removed"] = False
    if report["cleanup_eligible"] and args.remove:
        remove_worktree(root, report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Cleanup eligible: {'yes' if report['cleanup_eligible'] else 'no'}")
        for reason in report["cleanup_reasons"]:
            print(f"reason: {reason}")
        if report["removed"]:
            print("removed: yes")
    return 0 if report["cleanup_eligible"] else 1


@command("intake", "read the work issue with gh, or from the files your GitHub tools' answers "
                   "were saved to, and write its tickets into todo",
         WORKTREE,
         Exclusive((
             arg("--issue", type=int, help="work issue number"),
             arg("--issue-body", type=Path, metavar="FILE",
                 help="without gh: the work issue as your GitHub tools read it (issue_read, "
                      "method get), its JSON saved to FILE; the REST API's answer also serves"),
             arg("--outside", action="store_true",
                 help="for SE: list the open issues of se.toml's [outside] repositories that carry "
                      "no fleet marker and no handled comment, in one query; writes nothing"),
         ), required=True),
         arg("--comments-file", type=Path, metavar="FILE",
             help="with --issue-body: the work issue's comments as your GitHub tools read them "
                  "(issue_read, method get_comments), their JSON list saved to FILE"),
         REPO,
         arg("--discovery", action="store_true",
             help="create the ignored discovery evidence folder and index"),
         arg("--probe-root",
             help="relative ignored discovery output root; default: .se/work/probe"))
def run_intake(root: Path, args: argparse.Namespace) -> int:
    if args.outside:
        if args.repo or args.discovery or args.probe_root:
            raise QueueError("intake --outside takes its repositories from se.toml [outside], "
                             "and no --repo, --discovery or --probe-root")
        found = intake_outside(root)
        if not found:
            print("No outside issues to handle.")
        else:
            print(f"Outside issues ({len(found)}), not yet handled:")
            for issue in found:
                print(f"  {issue['repo']}#{issue['number']} {issue['title']} {issue['url']}")
        return 0
    if args.comments_file is not None and args.issue_body is None:
        raise QueueError("intake: --comments-file goes with --issue-body; with --issue, gh reads "
                         "the comments")
    if args.issue_body is not None and args.repo:
        raise QueueError("intake --issue-body takes the repository from the issue's address, "
                         "and no --repo")
    answered = (None if args.issue_body is None
                else answered_issue(args.issue_body, args.comments_file))
    issue, created, kept = intake(root, args.issue, args.repo, args.discovery, args.probe_root,
                                  answered)
    print(f"Work issue #{issue['number']}: {issue['title']} ({issue['url']})")
    for ticket_id in created:
        print(f"created todo/{ticket_id}.md")
    for ticket_id in kept:
        print(f"kept existing ticket for {ticket_id}")
    for reference in bare_cross_repository_references(issue["body"], issue["repo"]):
        print(
            f"warning: intake: work issue #{issue['number']} cites {reference} with no "
            "quoted block next to it; a cloud worker cannot read another repository, so "
            "quote what it needs inline, with its source (work-model skill, "
            '"Writing work issues")',
            file=sys.stderr,
        )
    if issue["comments"]:
        print(f"{len(issue['comments'])} comment(s) may change the requirements:")
        for comment in issue["comments"]:
            print(f"  {comment['createdAt']} {comment['author']}: {comment['url']}")
    return 0


@command("probe", "append a command and output path to the discovery evidence index",
         WORKTREE,
         arg("--command", required=True, dest="probe_command",
             help="command that produced the output"),
         arg("--output", required=True, help="path to the command output"))
def run_probe(root: Path, args: argparse.Namespace) -> int:
    print(f"Appended discovery evidence to "
          f"{append_discovery_evidence(root, args.probe_command, args.output)}")
    return 0


@command("refresh", "re-read the work issue and its comments and report changes",
         WORKTREE,
         arg("--issue", type=int, help="work issue number; default: recorded"),
         REPO, JSON_OUTPUT)
def run_refresh(root: Path, args: argparse.Namespace) -> int:
    changes = refresh(root, args.issue, args.repo)
    if args.json:
        print(json.dumps(changes, indent=2, ensure_ascii=False))
    else:
        print_changes(changes)
    return 0


@command("comments-read",
         "record the work issue's comments as read: their count and the newest one's id "
         "(intake records them; field-report --check and deliver refuse comments after it)",
         WORKTREE,
         arg("--count", required=True, type=int, help="number of comments"),
         arg("--newest", required=True, help="id of the newest comment ('' for none)"))
def run_comments_read(root: Path, args: argparse.Namespace) -> int:
    record_comments_read(root, {"count": args.count, "newest": args.newest})
    print(f"Recorded {args.count} comment(s) as read, newest {args.newest or 'none'}")
    return 0


@command("body-read",
         "record the work issue's body as read (intake records it; field-report --check and "
         "deliver refuse a body changed after it)",
         WORKTREE,
         arg("--body-file", type=Path, metavar="FILE",
             help="the work issue's body as your GitHub tools read it now; default: read with gh"))
def run_body_read(root: Path, args: argparse.Namespace) -> int:
    body_read(root, args.body_file)
    print("Recorded the work issue's body as read")
    return 0


PR_DESCRIPTION_HELP = ("file holding the pull request description, or the worker's draft: the "
                       "field report between its se:field-report markers")


@command("field-report",
         f"draft or check the field report a pull request description carries, in the form of "
         f"{FIELD_REPORT_TEMPLATE}",
         arg("--worktree",
             help="path to the selected worktree; needed except by --check with --issue-body"),
         Exclusive((
             arg("--draft", type=Path, metavar="FILE",
                 help="write the template, markers included, to FILE with work issue, branch, "
                      "tested commit, branch tip, release kind and user requirement filled in"),
             arg("--check", type=Path, metavar="FILE",
                 help="only validate the report in FILE (" + PR_DESCRIPTION_HELP + ") against "
                      "the template, without writing GitHub: its header lines, sections, tables, "
                      "field labels, placeholders and evidence gate, and, in a worktree with a "
                      "comments-read or body-read record, refuse comments after it and a changed "
                      "body; in a worktree also integrate's guard against its branch; refuses a "
                      "FILE without the markers"),
         ), required=True),
         arg("--issue-body", type=Path, metavar="FILE",
             help="with --check: the work issue's body as your GitHub tools read it now, for the "
                  "evidence gate and the body-read check (the body, or the issue's JSON as the "
                  "tools answered it); default: intake's snapshot, the body read with gh; with "
                  "--draft: the issue's JSON as your GitHub tools answered it, in place of "
                  "intake's snapshot"),
         arg("--comment-count", type=int, metavar="N",
             help="with --check: the work issue's comment count as your GitHub tools read it now; "
                  "default: read with gh"),
         arg("--newest-comment", metavar="ID",
             help="with --check: the id of the work issue's newest comment, as your GitHub tools "
                  "read it now ('' for none)"))
def run_field_report(root: Path | None, args: argparse.Namespace) -> int:
    if args.check is not None:
        if (args.comment_count is None) != (args.newest_comment is None):
            raise QueueError(
                "field-report --check: --comment-count and --newest-comment go together")
        comments = None if args.comment_count is None else {
            "count": args.comment_count, "newest": args.newest_comment}
        check_field_report(root, args.check, args.issue_body, comments)
        print(f"Field report {args.check.name} follows the template")
    elif root is None:
        raise QueueError("field-report --draft needs --worktree <worktree>, the worker's checkout")
    else:
        draft_field_report(root, args.draft, args.issue_body)
        print(f"Drafted {args.draft}")
    return 0


@command("escalate", "comment a question on an issue and label it escalated",
         WORKTREE,
         arg("--issue", required=True, type=int, help="issue to escalate"),
         arg("--file", required=True, type=Path, help="Markdown question"),
         REPO)
def run_escalate(root: Path, args: argparse.Namespace) -> int:
    escalate(root, args.issue, args.file, args.repo)
    print(f"Escalated #{args.issue}")
    return 0


@command("file", "for SE: file a work issue labelled work, ready and repo:<name>; with "
                 "--blocked-by, ready only once its blockers are linked",
         WORKTREE,
         arg("--title", required=True, help="the branch name"),
         arg("--body-file", required=True, type=Path,
             help="the filled .github/ISSUE_TEMPLATE/work.md body"),
         arg("--blocked-by", type=int, action="append", default=[], metavar="N",
             help="a native blocker to link before it is ready, repeatable"),
         arg("--label", action="append", default=[], metavar="LABEL",
             help="a further label, such as discovery, repeatable"),
         REPO)
def run_file(root: Path, args: argparse.Namespace) -> int:
    print(file_work_issue(root, args.title, args.body_file, args.blocked_by, args.repo,
                          tuple(args.label)))
    return 0


@command("route", "for SE: route a checked outside issue as a work issue in one edit: retitle it "
                  "to its branch name, label it work, ready and repo:<name>, and append the "
                  "routing section with the handled record to its body",
         WORKTREE,
         arg("issue", type=int),
         arg("--title", help="the branch name; derived from the issue's title where omitted"),
         arg("--type", default="feat", help="the derived branch name's type (default feat)"),
         arg("--routing-file", required=True, type=Path,
             help="the work.md sections the issue lacks, completed, appended to its body under "
                  f"## {ROUTING_SECTION} with the handled marker"),
         arg("--issue-title", help="without gh: the issue's title as the GitHub tools read it"),
         arg("--issue-body", type=Path,
             help="without gh: a file with the issue's body as the GitHub tools read it"),
         REPO)
def run_route(root: Path, args: argparse.Namespace) -> int:
    if (args.issue_title is None) != (args.issue_body is None):
        raise QueueError("route takes --issue-title and --issue-body together")
    read = None if args.issue_body is None else (args.issue_title, args.issue_body)
    print(route_outside_issue(
        root, args.issue, args.title, args.type, args.routing_file, args.repo, read))
    return 0


BACKLOG = command_group(
    "backlog", f"for SE: file or list backlog issues, far-out ideas labelled {BACKLOG_LABEL} and "
               f"{PERSON_LABEL} that no role takes as work", dest="backlog_action")


@command("file", f"file one backlog issue with both labels, creating {BACKLOG_LABEL} where missing",
         WORKTREE,
         arg("--title", required=True, help="the idea in one line"),
         arg("--body-file", required=True, type=Path, help="Markdown body"),
         REPO, parent=BACKLOG)
def run_backlog_file(root: Path, args: argparse.Namespace) -> int:
    print(backlog_file(root, args.title, args.body_file, args.repo))
    return 0


@command("list", "list the open backlog issues, or those whose title or body matches --search",
         WORKTREE, arg("--search", help="text to find in title or body"), REPO, parent=BACKLOG)
def run_backlog_list(root: Path, args: argparse.Namespace) -> int:
    found = backlog_list(root, args.search, args.repo)
    if not found:
        print("No backlog issues.")
    else:
        print(f"Backlog issues ({len(found)}):")
        for issue in found:
            print(f"  #{issue['number']} {issue['title']} {issue['url']}")
    return 0


REFS = command_group(
    "refs", "one-way ref changes through the repository's ref-maintenance workflow: the integrator "
            "requests, SE applies on the person's yes", dest="refs_action")


READ_BACK_RUN = (
    arg("--run-url", help="with --read-back: the ref-maintenance run's URL"),
    arg("--conclusion", help="with --read-back: the run's conclusion (success, failure, ...)"),
)


def read_back_arguments(args: argparse.Namespace, *names: str) -> None:
    """Refuse a --read-back without the values its plan's steps gave."""
    missing = [f"--{name.replace('_', '-')}" for name in names if getattr(args, name) in (None, "")]
    if missing:
        raise QueueError(f"--read-back needs {', '.join(missing)}, from the plan's steps")


@command("request", "for the integrator: post the triples on the issue, run ref-maintenance's dry "
                    "run, post its output and label the issue escalated; prints the line for SE. "
                    "Where gh is not signed in it prints these GitHub steps as a plan for the "
                    "session's GitHub tools; --read-back then checks the refs and finishes",
         WORKTREE,
         arg("issue", type=int, help="the work issue the ref change belongs to"),
         arg("--triples-file", required=True, type=Path,
             help="whitespace-separated <old-sha> <new-sha> <ref> triples; all zeros as new deletes"),
         REPO,
         arg("--read-back", action="store_true",
             help="after the plan's steps: check through git ls-remote that origin still holds "
                  "every ref at its old sha, then print the dry run's comment and label steps"),
         arg("--request-id", type=int, help="with --read-back: the id of the posted request comment"),
         *READ_BACK_RUN,
         arg("--log-file", type=Path, help="with --read-back: the run's job log, saved to a file"),
         parent=REFS)
def run_refs_request(root: Path, args: argparse.Namespace) -> int:
    if not args.read_back:
        print(refs_request(root, args.issue, args.triples_file, args.repo))
        return 0
    read_back_arguments(args, "request_id", "run_url", "conclusion", "log_file")
    repo = resolve_repo(root, args.repo)
    print(refs_request_read_back(
        root, args.issue, parse_triples(read_text_file(args.triples_file, "triples")),
        args.request_id, args.conclusion, args.run_url, read_text_file(args.log_file, "run log"),
        repo, None))
    return 0


@command("apply", "for SE, on the person's yes: run ref-maintenance for real with "
                  "the triples the issue's newest request posted, read the refs back and post the "
                  "result; prints the line for the integrator. Where gh is not signed in it prints "
                  "these GitHub steps as a plan for the session's GitHub tools; --read-back then "
                  "checks the refs and finishes",
         WORKTREE, arg("issue", type=int, help="the issue carrying the refs request"),
         REPO,
         arg("--comments-file", type=Path,
             help="where gh is not signed in: the issue's comments as a JSON list "
                  "(issue_read get_comments)"),
         arg("--read-back", action="store_true",
             help="after the plan's steps: check through git ls-remote that origin holds every "
                  "ref at its new sha, then print the result's comment and label steps"),
         *READ_BACK_RUN, parent=REFS)
def run_refs_apply(root: Path, args: argparse.Namespace) -> int:
    if not args.read_back:
        print(refs_apply(root, args.issue, args.repo, args.comments_file))
        return 0
    read_back_arguments(args, "run_url", "conclusion")
    repo = resolve_repo(root, args.repo)
    triples, request_id = posted_request(saved_comments(args.comments_file, args.issue), args.issue)
    print(refs_apply_read_back(root, args.issue, triples, request_id, args.conclusion,
                               args.run_url, repo, None))
    return 0


@command("sync", "merge the newest integration branch (se.toml project.integration_branch, "
                 "default main) from origin, or locally without origin", WORKTREE)
def run_sync(root: Path, args: argparse.Namespace) -> int:
    print(f"Merged {integration_branch(root)} {sync(root)}")
    return 0


@command("identity", "set the checkout's commit identity (machine-local public_identity, else "
                     "se.toml project.identity) as sync does, without fetching or merging; "
                     "scripts/setup.sh and setup.ps1 run it", WORKTREE)
def run_identity(root: Path, args: argparse.Namespace) -> int:
    identity = set_commit_identity(root, "identity")
    if identity is None:
        print(f"No commit identity configured for {root}; git's own user.name and user.email stay")
    else:
        print(f"Commit identity of {root} set to {identity[0]} from {identity[2]}")
    return 0


@command("suite", "run se.toml's complete suite against its [tests] time budget, as integrate "
                  "does; exit code 1 when tests fail, 3 when they pass over the limit and the "
                  "budget refuses them (README \"Test budget\")",
         WORKTREE,
         arg("--slowest", type=positive_int, default=SLOWEST_TESTS, metavar="N",
             help=f"how many slowest tests to list, from the JUnit reports or pytest's --durations "
                  f"(default {SLOWEST_TESTS})"),
         arg("--compare", metavar="REF",
             help="instead of the budget check, time the suite here and on REF (a temporary "
                  "worktree; a branch as origin has it, the local branch only where origin has "
                  "none), interleaved, after one untimed warm-up of each, and say whether this "
                  "checkout is \"not slower\" or \"slower by X s\" than REF"),
         arg("--runs", type=positive_int, default=COMPARE_RUNS, metavar="N",
             help=f"with --compare: timed runs of each state (default {COMPARE_RUNS})"))
def run_suite_command(root: Path, args: argparse.Namespace) -> int:
    if args.compare:
        print(f"Verdict: {compare_suites(root, args.compare, args.runs)}")
        return 0
    print(f"Suite: {run_suite(root, args.slowest)}")
    return 0


@command("suite-shard", "on CI, run one shard of a sharded suite, the COMMAND after --, show its "
                        "output, time it and write its record DIR/NAME.json for suite-time; exit "
                        "code the command's (README \"Test budget\")",
         WORKTREE,
         arg("--name", required=True, help="the shard's name, unique among the shards"),
         arg("--record", required=True, type=Path, metavar="DIR",
             help="directory the record is written to, collected for suite-time"),
         arg("shard_command", nargs=argparse.REMAINDER, metavar="-- COMMAND",
             help="the shard's command and its arguments, run without a shell"))
def run_suite_shard(root: Path, args: argparse.Namespace) -> int:
    command = args.shard_command[1:] if args.shard_command[:1] == ["--"] else args.shard_command
    return record_shard(root, args.name, args.record, command)


@command("suite-time", "in CI's check job, judge a sharded suite: its time is its slowest "
                       "shard's, from the records suite-shard wrote; prints it as the notice CI's "
                       "suite time is read from, and no time when a shard failed; refusals and "
                       "warnings are workflow annotations; exit code 1 when a shard failed or is "
                       "missing, 3 when the time is over the limit and the budget refuses it "
                       "(README \"Test budget\")",
         WORKTREE,
         arg("--shards", required=True, type=Path, metavar="DIR",
             help="directory holding the shards' records"),
         arg("--expect", type=positive_int, metavar="N",
             help="how many shards run; fewer or more records refuse"))
def run_suite_time(root: Path, args: argparse.Namespace) -> int:
    # Its refusals are `::error` annotations on stdout, after the shards it listed.
    try:
        timing = suite_time_of_shards(root, args.shards, args.expect)
    except SuiteOverLimitError as error:
        print(workflow_annotation("error", str(error)), flush=True)
        return SUITE_OVER_LIMIT_EXIT_CODE
    except QueueError as error:
        print(workflow_annotation("error", str(error)), flush=True)
        return 1
    print(f"Suite time: {timing}", flush=True)
    return 0


def iso_day(text: str) -> str:
    """A `YYYY-MM-DD` date argument, as given."""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a date YYYY-MM-DD: {text}") from error
    return text


@command("metrics", "print what the commands cost, from the line every run of a command "
                    "appends (README Metrics): top spenders by total wall time and by GitHub "
                    "calls, and each overrun of a declared budget (the suite's [tests] "
                    "limit_seconds in se.toml)",
         arg("--since", type=iso_day, metavar="DATE",
             help="only runs that started on or after DATE (YYYY-MM-DD)"),
         arg("--file", type=Path,
             help=f"the lines to read; default: ${metrics.PATH_ENV} or {metrics.PATH_DEFAULT}"))
def run_metrics(root: None, args: argparse.Namespace) -> int:
    source = args.file or metrics.path()
    lines, skipped = metrics.read(source)
    print(metrics.report(lines, args.since, source, skipped))
    return 0


@command("guard", "require the field report to name removed protected content, against "
                  "origin/<integration branch> as sync fetched it (the local branch without "
                  "origin)",
         WORKTREE,
         arg("--branch", required=True, help="branch to compare with the integration branch"),
         arg("--pr-description", required=True, type=Path, metavar="FILE",
             help=PR_DESCRIPTION_HELP + ", naming approved removed behaviour and tests"))
def run_guard(root: Path, args: argparse.Namespace) -> int:
    file = args.pr_description
    removed = guard(root, args.branch, report_in(read_file(file, "field report"), str(file)))
    if removed:
        for name in removed:
            print(f"Field report names removed protected content: {name}")
    else:
        print("No removed protected content found.")
    return 0


@command("deliver", "sync, check the field report, push, and create or update the pull request "
                    "whose description carries it; files no issue",
         WORKTREE,
         arg("--integrator-session", help=f"{SESSION_HELP} to notify"))
def run_deliver(root: Path, args: argparse.Namespace) -> int:
    session = config_value(
        "integrator_session", str(required_snapshot(root)["repo"]), args.integrator_session)
    pr = deliver(root)
    print(f"Notify {session or '<integrator session>'}: field report in PR #{pr} for "
          f"{current_branch(root)}")
    return 0


@command("push", "public check's push gate, then git push -u origin <branch>; retries a "
                 "transient refusal once a minute, ten attempts; the integration branch needs a "
                 "passing suite and public check recorded on the tree pushed",
         OPTIONAL_WORKTREE,
         arg("branch", nargs="?", help="branch to push; default: the current one"))
def run_push(root: Path, args: argparse.Namespace) -> int:
    push(root, args.branch)
    return 0


@command("verified", "the pre-push hook's guard: refuse a push of <commit> to <remote ref> where "
                     "the ref is the integration branch and no passing suite and public check are "
                     "recorded on its tree; push runs the same check",
         OPTIONAL_WORKTREE,
         arg("remote_ref", help="the pushed remote ref, for example refs/heads/main"),
         arg("commit", help="the pushed commit"))
def run_verified(root: Path, args: argparse.Namespace) -> int:
    if args.remote_ref == f"refs/heads/{integration_branch(root)}":
        guard_pushed_tree(root, args.commit)
        print(f"Verified: {args.commit[:12]} carries the verdicts the integration branch needs")
    return 0


@command("pr-body", "print the pull request description deliver writes: Fixes <issue> where all "
                    "its acceptance shows before the merge, else Refs <issue>, then the field "
                    "report between its markers",
         OPTIONAL_WORKTREE, ISSUE_BODY,
         arg("--issue-url", required=True, help="the work issue's URL, ending in /issues/<n>"),
         arg("--field-report", required=True, type=Path, metavar="FILE",
             help="the checked field report: " + PR_DESCRIPTION_HELP))
def run_pr_body(root: Path, args: argparse.Namespace) -> int:
    number = re.search(r"/issues/(\d+)/?$", args.issue_url)
    if number is None:
        raise QueueError(f"pr-body: --issue-url {args.issue_url!r} does not end in /issues/<n>")
    body = issue_body_text(args.issue_body)
    report = report_in(read_file(args.field_report, "field report"), str(args.field_report))
    print(pull_request_body({"number": number.group(1), "url": args.issue_url, "body": body},
                            report), end="")
    return 0


@command("release-trailer", "print the Release-kind trailer an integration merge of <branch> "
                            "carries, from its field report's Release kind (a re-integration's "
                            "from its Re-integration kind); push requires it",
         OPTIONAL_WORKTREE,
         arg("branch", help="the integrated branch: the local branch, else origin/<branch>"),
         ISSUE_BODY,
         arg("--pr-description", type=Path, metavar="FILE",
             help=PR_DESCRIPTION_HELP + "; required on a first integration: its Release kind; "
                  "refuses commits on <branch> after its Branch tip, and gives a re-integration "
                  "its Re-integration kind (default patch)"),
         INCLUDE_LATE)
def run_release_trailer(root: Path, args: argparse.Namespace) -> int:
    body = issue_body_text(args.issue_body)
    file = args.pr_description
    report = None if file is None else report_in(read_file(file, "pull request description"), str(file))
    if report is not None:
        late = check_branch_tip(root, report, args.branch,
                                branch_head(root, args.branch), args.include_late)
        if late:
            print(f"Includes {len(late)} commit(s) after the field report's Branch tip: "
                  f"{args.include_late}", file=sys.stderr)
    print(release_trailer(root, args.branch, body, report))
    return 0


@command("integrate", "validate the field report a pull request's description carries, merge it "
                      "on land/<branch>, test, land it through a squash pull request once check "
                      "passes, and close the work issue. Where gh is not signed in it pushes "
                      "land/<branch> and prints the GitHub steps as a plan for the session's "
                      "GitHub tools; --read-back <branch> then checks the landing through git and "
                      "finishes the close-out",
         WORKTREE,
         arg("pull_request", type=int, nargs="?", help="the delivered pull request's number"),
         REPO,
         arg("--pr-description", type=Path, metavar="FILE",
             help="where gh is not signed in: the pull request's description, saved to a file"),
         arg("--issue-body", type=Path, metavar="FILE",
             help="where gh is not signed in: its work issue's body, saved to a file"),
         arg("--branch", help="where gh is not signed in: the pull request's head branch"),
         arg("--read-back", metavar="BRANCH",
             help="after the plan's steps: check that origin's integration branch is the squash "
                  "commit of land/BRANCH on the tested base with the tested tree, and finish"),
         arg("--landing-pull", type=int, help="with --read-back: the landing pull request's number"),
         arg("--check-run", help="with --read-back: the URL of its passed check run"),
         arg("--landing-description", type=Path, metavar="FILE",
             help="with --read-back: the landing pull request's description after the merge, "
                  "saved to a file; it must end in the plan's metrics line"),
         arg("--build-command", help="project's output regeneration command"),
         INCLUDE_LATE,
         arg("--check-command", type=parse_check_commands, metavar="JSON",
             help="project checks as a JSON list of argument arrays"),
         arg("--check-command-temporary-directory", action="store_true",
             help="run every project check in its own temporary working directory"))
def run_integrate(root: Path, args: argparse.Namespace) -> int:
    if args.check_command_temporary_directory and not args.check_command:
        raise QueueError("--check-command-temporary-directory requires --check-command")
    if (args.read_back is None) == (args.pull_request is None):
        raise QueueError("integrate takes a pull request number or --read-back <branch>, one of them")
    if args.read_back is not None:
        read_back_arguments(args, "landing_pull", "check_run", "landing_description")
        description = read_file(args.landing_description, "the landing pull request's description")
        commit = read_back_integration(root, args.read_back, args.landing_pull, args.check_run,
                                       description)
        print(f"Integrated {args.read_back} in {commit}")
        return 0
    commit = integrate(
        root, args.pull_request, args.repo, args.build_command,
        args.check_command, args.check_command_temporary_directory, args.include_late,
        args.pr_description, args.issue_body, args.branch,
    )
    if commit is None:
        print(f"Run the plan's steps, then its last line for pull request #{args.pull_request}")
    else:
        print(f"Integrated pull request #{args.pull_request} in {commit}")
    return 0


@command("config", "show the repository and the machine-local settings in effect",
         WORKTREE, REPO, WORKTREE_ROOT, arg("--integrator-session", help=SESSION_HELP))
def run_config(root: Path, args: argparse.Namespace) -> int:
    repo = resolve_repo(root, args.repo)
    print(f"repository: {repo}")
    print(f"machine-local config: {local_config_path()}")
    directory = configured_worktree_root(root, args.worktree_root)
    print(f"worktree root: {directory or default_worktree_root(root)}")
    session = config_value("integrator_session", repo, args.integrator_session)
    print(f"integrator session: {session or '(not set)'}")
    return 0


@command("start", "start a ready work issue: worktree from the newest main, label in-progress",
         WORKTREE,
         arg("issue", type=int),
         REPO, WORKTREE_ROOT,
         arg("--no-create", dest="create", action="store_false",
             help="only change the labels; the project's own script created the worktree"),
         arg("--cloud-agent", help="GitHub login for a cloud worker"))
def run_start(root: Path, args: argparse.Namespace) -> int:
    path = start(root, args.issue, args.repo, args.worktree_root, args.create, args.cloud_agent)
    if path is not None:
        issue = fetch_issue(root, args.issue, resolve_repo(root, args.repo))
        print(f"Launch worker: agent=worker issue={issue['url']} worktree={path}")
    print(f"Started #{args.issue}")
    return 0


@command("block", "link an issue to a native blocker",
         WORKTREE, arg("issue", type=int), arg("--by", required=True, type=int, dest="blocker"),
         REPO)
def run_block(root: Path, args: argparse.Namespace) -> int:
    block(root, args.issue, args.blocker, args.repo)
    print(f"Blocked #{args.issue} by #{args.blocker}")
    return 0


TRACKER_QUERY = (OPTIONAL_WORKTREE, REPO,
                 arg("--all-repos", action="store_true",
                     help="include tracker issues for every repository"))


@command("ready", "list startable ready work issues", *TRACKER_QUERY)
def run_ready(root: Path, args: argparse.Namespace) -> int:
    for issue in ready_issues(root, resolve_repo(root, args.repo), args.all_repos):
        print(f"#{issue['number']} {issue['title']}")
    return 0


@command("capacity", "show local worker capacity or cloud unlimited capacity", *TRACKER_QUERY)
def run_capacity(root: Path, args: argparse.Namespace) -> int:
    slots = capacity(root, resolve_repo(root, args.repo), args.all_repos)
    print("Capacity: unlimited (cloud)" if slots is None else f"Capacity: {slots}")
    return 0


@command("queue", "list delivered pull requests (open, to the integration branch, with a complete "
                  "field report), escalations and startable work issues", *TRACKER_QUERY)
def run_queue(root: Path, args: argparse.Namespace) -> int:
    repo = resolve_repo(root, args.repo)
    delivered, escalations, ready, slots = queue(root, repo, args.all_repos)
    for pull in delivered:
        print(f"delivered PR #{pull['number']} {pull['title']} {pull['url']}")
    for escalation in escalations:
        print(f"escalated #{escalation['number']} {escalation['title']} {escalation['url']}")
    print("Capacity: unlimited (cloud)" if slots is None else f"Capacity: {slots}")
    for issue in ready:
        print(f"ready #{issue['number']} {issue['title']}")
    return 0


@command("paused", f"whether the fleet is paused: exit code 1 and the issue while an issue "
                   f"labelled {PAUSE_LABEL} is open in the repository (the owner's switch; closing "
                   "it resumes), exit code 0 while none is. queue, start, integrate and route "
                   "refuse while paused. Without gh it prints the search as a plan for the "
                   "session's GitHub tools, exit code 2", OPTIONAL_WORKTREE, REPO)
def run_paused(root: Path, args: argparse.Namespace) -> int:
    repo = resolve_repo(root, args.repo)
    if hand_off():
        print(pause_plan(repo).text())
        return 2
    found = pause_issues(root, repo)
    if found:
        print(f"Paused by {pause_names(found)}: nothing starts, lands or is routed until the owner "
              "closes it")
        return 1
    print(f"Not paused: no open issue labelled {PAUSE_LABEL} in {repo}")
    return 0


@command("fleet-check", "list every stuck or stray piece of work, each with its issue, pull request "
                        "and remedy: in-progress work without a branch once the lease has passed "
                        "since its Started comment (listed as starting before) or without a push "
                        "within the lease, a delivered pull request whose check failed or that conflicts, a branch "
                        "of a closed issue, a block by an issue closed as not planned or by itself, "
                        "an se-person issue and what it holds up; 'healthy' and exit code 0 when "
                        "there is none, exit code 1 otherwise. It only reads. Without gh it prints "
                        "its GitHub plan and takes the answers from files",
         OPTIONAL_WORKTREE, REPO, JSON_OUTPUT,
         arg("--open-issues", type=Path, help="without gh: the open issues the plan read"),
         arg("--closed-issues", type=Path, help="without gh: the closed issues the plan read"),
         arg("--pulls", type=Path, help="without gh: the open pull requests the plan read"))
def run_fleet_check(root: Path, args: argparse.Namespace) -> int:
    repo = resolve_repo(root, args.repo)
    base = integration_branch(root)
    files = (args.open_issues, args.closed_issues, args.pulls)
    if hand_off():
        if not all(files):
            print(fleet_plan(repo, base).text())
            return 0
        door = FileFleet(root, *files)
    else:
        door = Fleet(root, repo, base)
    found = fleet_findings(door, datetime.now(timezone.utc), fleet_lease(root),
                           repository_name(root))
    print(fleet_report(found, args.json))
    return 1 if any(finding.stuck for finding in found) else 0


@command("stop-check", "the plugin's Stop and SubagentStop hook: in a checkout whose ticket queue "
                       "is for a work issue, refuse the turn's end while its branch has no open "
                       "pull request whose description carries a field report that passes "
                       "field-report --check at the branch tip, naming what is missing and the "
                       "commands; at most [stop] refusals times in a row (se.toml, built in 5). "
                       "Anywhere else, for a sub-agent that is no worker, and where it cannot "
                       "judge (no gh and no recorded pull request) it lets the turn end. It reads "
                       "the hook's JSON on stdin and answers the hook's JSON on stdout",
         arg("--worktree", help="the checkout to judge; default: for a worker sub-agent the "
                                "checkout its prompt names, else the one whose ticket queue its "
                                "transcript last touched; else the hook's cwd, else the current "
                                "directory"),
         arg("--pull", type=int, metavar="NUMBER",
             help="without gh: record the pull request your GitHub tools opened, the hook's "
                  "answer file, then say whether the hook passes; exit code 1 where it would "
                  "refuse"),
         arg("--pr-description", type=Path, metavar="FILE",
             help="with --pull: its description as your GitHub tools read it"))
def run_stop_check(root: Path | None, args: argparse.Namespace) -> int:
    if args.pull is not None:
        if args.pr_description is None:
            raise QueueError("stop-check --pull needs --pr-description <file>")
        path = root or Path.cwd()
        top = checkout_top(path)
        if top is None:
            raise QueueError(f"stop-check --pull: {path} is not in a git checkout")
        record_delivered_pull(top, args.pull, args.pr_description)
        verdict = stop_verdict(top, {}, count=False)
        if verdict.block is not None:
            print(f"Recorded pull request #{args.pull}; the Stop hook would refuse:\n"
                  f"{verdict.block}", file=sys.stderr)
            return 1
        print(f"Recorded pull request #{args.pull}; the Stop hook passes"
              + (f" ({verdict.note})" if verdict.note else ""))
        return 0
    event = hook_event()
    cwd = event.get("cwd")
    own = (subagent_checkout(event) if root is None and event.get("hook_event_name") ==
           "SubagentStop" and is_worker_agent(event) else None)
    path = root or own or (Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd())
    output = stop_verdict(path, event).hook_output()
    if output:
        print(output)
    return 0


README = Path(__file__).resolve().parents[1] / "README.md"
REFERENCE_BEGIN, REFERENCE_END = generated_markers("`work_tickets.py docs`")
REFERENCE_WIDTH = 100


@command("docs", "write the README's command reference from this registry; with --check, only "
                 "refuse a README that differs",
         arg("--check", action="store_true",
             help="exit code 1, writing nothing, when README.md differs from what docs writes"))
def run_docs(root: None, args: argparse.Namespace) -> int:
    text = README.read_text(encoding="utf-8")
    expected = with_command_reference(text)
    if text == expected:
        print(f"{README.name}: the command reference is up to date")
        return 0
    if args.check:
        print(f"error: {README.name}: the command reference differs from the registry; run "
              "work_tickets.py docs", file=sys.stderr)
        return 1
    README.write_text(expected, encoding="utf-8", newline="\n")
    print(f"{README.name}: wrote the command reference")
    return 0



@command("format", "apply the fix of every check the check job runs that a fix can satisfy: write "
                   "the generated layouts (se_plugin.py build) and the README's command reference "
                   "(docs); a second run writes nothing",
         arg("--root", type=Path, default=README.parent,
             help="the se checkout to write; default: the one this script runs from"))
def run_format(root: None, args: argparse.Namespace) -> int:
    se_plugin = sibling("se_plugin")
    try:
        written = [str(path) for path in se_plugin.build(args.root)]
    except se_plugin.SourceError as error:
        raise QueueError(f"format: se_plugin.py build: {error}") from error
    readme = args.root / README.name
    text = readme.read_text(encoding="utf-8")
    expected = with_command_reference(text)
    if text != expected:
        readme.write_text(expected, encoding="utf-8", newline="\n")
        written.append(README.name)
    for path in written:
        print(f"wrote {path}")
    if not written:
        print("format: nothing to change")
    return 0


def leaf_commands(group: Command = COMMANDS, path: tuple[str, ...] = ()
                  ) -> list[tuple[tuple[str, ...], Command]]:
    """Every command with a handler, as its words after work_tickets.py, in registry order."""
    found = []
    for command_ in group.subcommands:
        words = (*path, command_.name)
        found += leaf_commands(command_, words) if command_.subcommands else [(words, command_)]
    return found


def add_arguments(parser: argparse.ArgumentParser, command_: Command) -> None:
    for argument in command_.arguments:
        if isinstance(argument, Exclusive):
            group = parser.add_mutually_exclusive_group(required=argument.required)
            for member in argument.members:
                group.add_argument(*member.flags, **member.options)
        else:
            parser.add_argument(*argument.flags, **argument.options)


def build_parser(parser: argparse.ArgumentParser, command_: Command) -> argparse.ArgumentParser:
    add_arguments(parser, command_)
    if command_.subcommands:
        subparsers = parser.add_subparsers(dest=command_.dest, required=True)
        for sub in command_.subcommands:
            build_parser(subparsers.add_parser(sub.name, help=sub.help), sub)
    else:
        parser.set_defaults(handler=command_.handler)
    return parser


def make_parser() -> argparse.ArgumentParser:
    return build_parser(argparse.ArgumentParser(description=COMMANDS.help), COMMANDS)


def command_reference() -> str:
    """The README's command reference: each command's usage and help, from the registry."""
    def formatter(prog: str) -> argparse.HelpFormatter:
        return argparse.HelpFormatter(prog, width=REFERENCE_WIDTH)
    entries = []
    for words, command_ in leaf_commands():
        parser = argparse.ArgumentParser(
            prog=" ".join((COMMANDS.name, *words)), add_help=False, formatter_class=formatter)
        add_arguments(parser, command_)
        # Without argparse's "usage: " prefix, its continuation lines move left by as much.
        usage = "\n".join(line[len("usage: "):]
                          for line in parser.format_usage().rstrip().splitlines())
        help_text = textwrap.fill(command_.help, REFERENCE_WIDTH, initial_indent="    ",
                                  subsequent_indent="    ")
        entries.append(f"{usage}\n{help_text}")
    return "```text\n" + "\n\n".join(entries) + "\n```"


def with_command_reference(text: str) -> str:
    """`text` with the block between the reference markers replaced by the generated one."""
    before, begin, rest = text.partition(REFERENCE_BEGIN)
    _, end, after = rest.partition(REFERENCE_END)
    if not begin or not end:
        raise QueueError(f"{README.name}: no {REFERENCE_BEGIN} ... {REFERENCE_END} block; add the "
                         "markers where the command reference belongs")
    return f"{before}{begin}\n{command_reference()}\n{end}{after}"


def main(argv: list[str] | None = None) -> int:
    # Issue text may hold characters a legacy console code page cannot show.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = make_parser().parse_args(argv)
    code, line = metrics.recorded(f"work_tickets.py {' '.join(command_words(args))}",
                                  lambda: run_command(args))
    if line is not None and args.command == "integrate":
        print(metrics.text(line))
    return code


def command_words(args: argparse.Namespace) -> list[str]:
    """The words of the command `args` selected, `backlog file` for a subcommand."""
    words, node = [], COMMANDS
    while node.subcommands:
        name = getattr(args, node.dest)
        node = next(command_ for command_ in node.subcommands if command_.name == name)
        words.append(name)
    return words


def run_command(args: argparse.Namespace) -> int:
    """Run the selected command's handler; its errors become an exit code and a message."""
    try:
        worktree = getattr(args, "worktree", None)
        return args.handler(worktree_root(worktree) if worktree is not None else None, args)
    except MissingGhError as error:
        print(f"error: work_tickets.py {args.command} {error}", file=sys.stderr)
        return 1
    except SuiteOverLimitError as error:
        print(f"error: {error}", file=sys.stderr)
        return SUITE_OVER_LIMIT_EXIT_CODE
    except (QueueError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
