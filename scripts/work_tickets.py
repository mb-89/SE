#!/usr/bin/env python3
"""Manage the Markdown-backed worker ticket queue and its work and field-report issues."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


STATES = ("todo", "held", "done")
DIRECTORIES = (*STATES, "notes")
ID_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
HEADING_PATTERN = re.compile(r"^#\s+([^:\s]+):\s+(.+?)\s*$")
CHECKBOX_PATTERN = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$")
DISPOSITION_PATTERN = re.compile(r"^\s*Disposition:\s*(.*?)\s*$", re.IGNORECASE)
REQUIREMENT_PATTERN = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")
FRONT_MATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
ISSUE_URL_PATTERN = re.compile(r"^https?://([^/]+)/([^/]+)/([^/]+)/issues/\d+$")
REMOVED_PYTHON_TEST_PATTERN = re.compile(r"^-\s*def\s+(test_[A-Za-z0-9_]+)\s*\(")
REMOVED_JAVASCRIPT_TEST_PATTERN = re.compile(
    r"""^-\s*(?:test|it)\s*\(\s*(?P<quote>["'`])(?P<name>.*?)(?P=quote)"""
)
ISSUE_FIELDS = "number,title,body,url,updatedAt,comments,labels"
ISSUE_SNAPSHOT = "issue.json"
# The issue templates belong to se, wherever a project keeps it.
TEMPLATES = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"
DELIVERY_TICKET = "delivery"
DISCOVERY_DIRECTORY = Path(".se") / "work" / "probe"
DISCOVERY_INDEX = "evidence.md"
DISCOVERY_CONFIG = "discovery.json"
LOCAL_CORES_PER_WORKER = 2
LOCAL_MEMORY_MIB_PER_WORKER = 4096


class QueueError(Exception):
    """A queue operation cannot be completed safely."""


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
        json.dumps({"root": str(directory.relative_to(root))}, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return index


def append_discovery_evidence(root: Path, command: str, output: str) -> Path:
    index = discovery_index(root)
    if index is None:
        raise QueueError("No discovery evidence index: run intake --discovery first")
    if not command.strip() or not output.strip():
        raise QueueError("Discovery evidence requires a command and output path")
    if any(character in command + output for character in "\r\n|"):
        raise QueueError("Discovery evidence command and output cannot contain newlines or pipes")
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


def create_ticket(root: Path, ticket_id: str, title: str) -> None:
    if not valid_id(ticket_id):
        raise QueueError(f"Unsafe ticket ID: {ticket_id!r}")
    title = title.strip()
    if not title or any(character in title for character in "\r\n"):
        raise QueueError("Ticket title must be nonempty and on one line")
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
        "- [ ] Add a checkable acceptance criterion.\n\n"
        "## Evidence\n"
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
        if problems:
            raise QueueError(
                f"Cannot move {ticket_id} to done: {', '.join(problems)}"
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

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    top = git("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return ["Worktree is not inside a Git repository"]
    git_root = Path(top.stdout.strip()).resolve()
    if git_root != root:
        reasons.append("Selected path is not the Git worktree root")
    if (git_root / ".git").is_dir():
        reasons.append("Cannot close the primary checkout")
    listed = git("worktree", "list", "--porcelain")
    if listed.returncode != 0 or not primary_checkout_path(listed.stdout):
        reasons.append("Could not identify the primary checkout")

    dirty = git("-C", str(git_root), "status", "--porcelain=v1", "--untracked-files=all")
    if dirty.returncode != 0:
        reasons.append("Could not inspect Git worktree status")
    elif dirty.stdout.strip():
        reasons.append("Git worktree has dirty or untracked files")

    if not integration_target:
        reasons.append("An integration target is required")
    else:
        head = git("-C", str(git_root), "rev-parse", "--verify", "HEAD^{commit}")
        target = git(
            "-C", str(git_root), "rev-parse", "--verify",
            f"{integration_target}^{{commit}}",
        )
        if head.returncode != 0 or target.returncode != 0:
            reasons.append("Could not resolve the worktree or integration target commit")
        else:
            integrated = git(
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


def run_gh(root: Path, arguments: list[str]) -> str:
    executable = shutil.which("gh")
    if executable is None:
        raise QueueError(
            "GitHub CLI (gh) not found; install it with the setup command the project's "
            "AGENTS.md names"
        )
    result = subprocess.run(
        [executable, *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
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
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
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
    remote = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
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
    result = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def tested_main(root: Path) -> str:
    """The newest main commit merged into the branch, local or remote main alike."""
    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )

    refs = [ref for ref in ("main", "origin/main")
            if git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0]
    base = git("merge-base", "HEAD", *refs) if refs else None
    if base is None or base.returncode != 0:
        raise QueueError("Cannot find the main commit merged into this branch")
    return git("rev-parse", "--short", base.stdout.strip()).stdout.strip()


def sync(root: Path) -> str:
    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )

    remote = remote_repo(root)
    if remote is not None:
        fetched = git("fetch", "origin")
        if fetched.returncode != 0:
            detail = fetched.stderr.strip() or f"exit code {fetched.returncode}"
            raise QueueError(f"Cannot fetch origin: {detail}")
        main_ref = "origin/main"
    else:
        main_ref = "main"
    merged = git("merge", "--no-edit", main_ref)
    if merged.returncode != 0:
        detail = merged.stderr.strip() or f"exit code {merged.returncode}"
        raise QueueError(
            f"Cannot merge {main_ref} due to a merge conflict or merge failure: {detail}"
        )
    for mirror in configured_mirrors(root):
        if not mirror.fetch:
            continue
        fetched = git("fetch", mirror.remote)
        if fetched.returncode != 0:
            detail = fetched.stderr.strip() or f"exit code {fetched.returncode}"
            raise QueueError(f"Cannot fetch mirror {mirror.remote}: {detail}")
        mirror_ref = f"{mirror.remote}/{mirror.branch}"
        merged = git("merge", "--no-edit", mirror_ref)
        if merged.returncode != 0:
            detail = merged.stderr.strip() or f"exit code {merged.returncode}"
            raise QueueError(
                f"Cannot merge {mirror_ref} due to a merge conflict or merge failure: {detail}"
            )
    commit = git("rev-parse", "--short", main_ref)
    if commit.returncode != 0 or not commit.stdout.strip():
        raise QueueError(f"Merged {main_ref} but cannot determine its commit")
    return commit.stdout.strip()


def fetch_issue(root: Path, number: int, repo: str | None) -> dict[str, object]:
    data = json.loads(run_gh(
        root, ["issue", "view", str(number), "--json", ISSUE_FIELDS, *repo_arguments(repo)]
    ))
    match = ISSUE_URL_PATTERN.fullmatch(data["url"])
    if match is None:
        raise QueueError(f"Unexpected issue URL: {data['url']}")
    return {
        "repo": "/".join(match.groups()),
        "number": data["number"],
        "url": data["url"],
        "title": data["title"],
        "body": (data.get("body") or "").replace("\r\n", "\n"),
        "updatedAt": data.get("updatedAt", ""),
        "labels": data.get("labels") or [],
        "comments": [
            {
                "id": comment.get("id", ""),
                "author": (comment.get("author") or {}).get("login", ""),
                "createdAt": comment.get("createdAt", ""),
                "url": comment.get("url", ""),
                "body": (comment.get("body") or "").replace("\r\n", "\n"),
            }
            for comment in data.get("comments") or []
        ],
    }


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


def markdown_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else SECTION_PATTERN.fullmatch(line)
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


def requirement_items(body: str) -> dict[int, str]:
    items: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in section(markdown_sections(body), "requirements").splitlines():
        match = REQUIREMENT_PATTERN.fullmatch(line)
        if match:
            current = items.setdefault(int(match.group(1)), [])
            current.append(match.group(2))
        elif current is not None:
            current.append(line)
    return {number: "\n".join(lines).strip() for number, lines in items.items()}


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


def planned_tickets(issue: dict[str, object]) -> list[tuple[str, str]]:
    """Derives one ticket per numbered requirement plus the delivery ticket."""
    sections = markdown_sections(issue["body"])
    requirements = requirement_items(issue["body"])
    if not requirements:
        requirements = {1: section(sections, "goal") or issue["title"]}
    owner = section(sections, "design owner") or "Named in the work issue."
    tickets: list[tuple[str, str]] = []
    previous = "None"
    for number, text in sorted(requirements.items()):
        ticket_id = requirement_prefix(number) + slug(text)
        tickets.append((ticket_id, (
            f"# {ticket_id}: {one_line(text.splitlines()[0])}\n\n"
            "## Design\n\n"
            f"Work issue {issue['url']}, requirement {number}; re-read it and its comments "
            "before starting.\n\n"
            f"Design owner: {owner}\n\n"
            f"## Scope\n\n{text}\n\n"
            f"## Dependencies\n\n{previous}\n\n"
            "## Acceptance\n\n"
            f"- [ ] Requirement {number} is implemented as the work issue states it now.\n"
            "- [ ] Its focused tests and the affected real command pass.\n\n"
            "## Evidence\n"
        )))
        previous = f"`{ticket_id}` (the work issue orders its requirements)."
    acceptance = section(sections, "acceptance")
    verification = section(sections, "verification") or "As the work issue states."
    tickets.append((DELIVERY_TICKET, (
        f"# {DELIVERY_TICKET}: Deliver {issue['title']}\n\n"
        "## Design\n\n"
        f"Work issue {issue['url']}, sections Acceptance and Verification; the delivery steps "
        "are in `.github/agents/worker.agent.md`.\n\n"
        f"## Scope\n\nVerification from the work issue:\n\n{verification}\n\n"
        "## Dependencies\n\n"
        + ", ".join(f"`{ticket_id}`" for ticket_id, _ in tickets) + "\n\n"
        "## Acceptance\n\n"
        + (f"{acceptance}\n" if acceptance else "")
        + "- [ ] Branch pushed, pull request to `main` opened, field-report issue created.\n\n"
        "## Evidence\n"
    )))
    return tickets


def intake(
    root: Path, number: int, repo: str | None, discovery: bool = False,
    probe_root: str | None = None,
) -> tuple[dict[str, object], list[str], list[str]]:
    initialize(root)
    paths, tickets, errors = scan_queue(root)
    if errors:
        raise QueueError("; ".join(errors))
    issue = fetch_issue(root, number, resolve_repo(root, repo))
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
    if discovery:
        initialize_discovery(root, probe_root)
    save_snapshot(root, issue)
    return issue, created, kept


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
    issue = fetch_issue(root, number, repo)
    if previous is not None and previous["number"] != number:
        previous = None
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


def issue_template(root: Path, name: str) -> tuple[dict[str, str], str]:
    path = TEMPLATES / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise QueueError(f"Issue template not found: {path}") from error
    match = FRONT_MATTER_PATTERN.match(text)
    if match is None:
        raise QueueError(f"Issue template has no front matter: {path}")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def template_labels(value: str) -> list[str]:
    return [label.strip().strip("\"'") for label in value.strip("[]").split(",") if label.strip()]


def deleted_tests(root: Path, branch: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--unified=0", f"main...{branch}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise QueueError(f"Cannot diff main against {branch}: {detail}")
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


def guard(root: Path, branch: str, field_report: Path) -> list[str]:
    if not field_report.is_file():
        raise QueueError(f"Field report is not a regular file: {field_report}")
    try:
        report = field_report.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Cannot read field report {field_report}: {error}") from error
    removed = deleted_tests(root, branch)
    named = "\n".join(section_content(
        report, "Removed behaviour and deleted or weakened tests"
    ))
    missing = [name for name in removed if name not in named]
    if missing:
        raise QueueError(
            "Field report must name each deleted or renamed test: " + ", ".join(missing)
        )
    return removed


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
            "pr", "list", "--head", branch, "--base", "main", "--state", "open",
            "--json", "number,url", *repo_arguments(repo),
        ]
    ))
    return int(data[0]["number"]) if data else None


def report_pull_request(root: Path, issue: dict[str, object], branch: str) -> int | None:
    remote = remote_repo(root)
    return open_pull_request_number(root, remote, branch) if remote is not None else None


def deliver(root: Path, tracker: str | None = None) -> str:
    issue = required_snapshot(root)
    branch = delivery_branch(root, issue)
    sync(root)
    remote = remote_repo(root)
    if remote is not None:
        pushed = subprocess.run(
            ["git", "-C", str(root), "push", "-u", "origin", branch],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if pushed.returncode != 0:
            detail = pushed.stderr.strip() or f"exit code {pushed.returncode}"
            raise QueueError(f"Cannot push {branch}: {detail}")
        pr = open_pull_request_number(root, remote, branch)
        if pr is None:
            body = f"Work issue #{issue['number']}: {issue['url']}\n"
            output = run_gh_with_body(
                root,
                ["pr", "create", "--base", "main", "--head", branch, "--title", branch,
                 *repo_arguments(remote)],
                body,
            )
            match = re.search(r"/pull/(\d+)\b", output)
            if match is None:
                raise QueueError("Pull request creation did not return a pull request URL")
            pr = int(match.group(1))
        else:
            run_gh_with_body(
                root, ["pr", "edit", str(pr), "--title", branch, *repo_arguments(remote)],
                f"Work issue #{issue['number']}: {issue['url']}\n",
            )
    else:
        pr = None

    report = root / ".se" / "work" / "field-report.md"
    if not report.exists():
        draft_field_report(root, report, pr)
    elif pr is not None:
        body = report.read_text(encoding="utf-8")
        body = body.replace("**Pull request:** none", f"**Pull request:** #{pr}", 1)
        report.write_text(body, encoding="utf-8", newline="\n")
    _, report_url = file_field_report(root, report, pr, tracker)
    return report_url


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
                          ("worktree", "add", "-b", branch, str(path), "origin/main")):
            result = subprocess.run(
                ["git", "-C", str(root), *arguments],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or f"exit code {result.returncode}"
                raise QueueError(f"git {arguments[0]} failed: {detail}")
    else:
        listed = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if listed.returncode != 0:
            detail = listed.stderr.strip() or f"exit code {listed.returncode}"
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
    return {
        str(label.get("name", ""))
        for label in issue.get("labels", []) if isinstance(label, dict)
    }


def repository_label(root: Path) -> str:
    return f"repo:{repository_name(root)}"


def repository_label_arguments(root: Path, all_repos: bool) -> list[str]:
    return [] if all_repos else ["--label", repository_label(root)]


def issue_ownership(issue: dict[str, object]) -> set[str]:
    value = section(markdown_sections(str(issue.get("body", ""))), "file ownership")
    return {
        line.strip("` -")
        for line in value.splitlines()
        if line.strip() and line.strip().lower() not in {"none", "n/a"}
    }


def branch_exists(root: Path, branch: str) -> bool:
    local = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if local.returncode == 0:
        return True
    origin = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if origin.returncode != 0:
        return False
    remote = subprocess.run(
        ["git", "-C", str(root), "ls-remote", "--heads", "origin", branch],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if remote.returncode != 0:
        raise QueueError(f"Cannot check whether branch {branch} exists")
    return bool(remote.stdout.strip())


def ready_issues(
    root: Path, repo: str, all_repos: bool = False, allow_existing_branch: bool = False
) -> list[dict[str, object]]:
    labels = repository_label_arguments(root, all_repos)
    arguments = [
        "issue", "list", "--state", "open", "--label", "work", "--label", "ready",
        "--json", "number,title,body,labels", "--limit", "200", *labels, *repo_arguments(repo),
    ]
    candidates = json.loads(run_gh(root, arguments))
    active = json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", "in-progress",
        "--json", "number,title,body,labels", "--limit", "200", *labels, *repo_arguments(repo),
    ]))
    active_ownership = set().union(*(issue_ownership(item) for item in active))
    ready: list[dict[str, object]] = []
    for candidate in candidates:
        number = int(candidate["number"])
        detail = issue_api(root, repo, f"issues/{number}")
        blockers = int(
            (detail.get("issue_dependencies_summary") or {}).get("blocked_by", 0)
        )
        branch = str(candidate["title"])
        if blockers == 0 and (allow_existing_branch or not branch_exists(root, branch)) and not (
            issue_ownership(candidate) & active_ownership
        ):
            ready.append(candidate)
    return ready


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


def queue(
    root: Path, repo: str, all_repos: bool = False
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], int | None]:
    sync(root)
    labels = repository_label_arguments(root, all_repos)
    reports = json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", "field-report",
        "--json", "number,title,url", "--limit", "200", *labels, *repo_arguments(repo),
    ]))
    escalations = json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--label", "escalated",
        "--json", "number,title,url", "--limit", "200", *labels, *repo_arguments(repo),
    ]))
    return (
        reports,
        escalations,
        ready_issues(root, repo, all_repos),
        capacity(root, repo, all_repos),
    )


def quoted(text: str) -> str:
    lines = text.splitlines() or [""]
    if all(line.startswith(">") or not line.strip() for line in lines):
        return text
    return "\n".join(f"> {line}".rstrip() for line in lines)


def draft_field_report(root: Path, file: Path, pr: int | None) -> int | None:
    issue = required_snapshot(root)
    branch = delivery_branch(root, issue)
    if pr is None:
        try:
            pr = report_pull_request(root, issue, branch)
        except QueueError:
            pr = None
    _, body = issue_template(root, "field-report")
    body = body.replace("#<n>", f"#{issue['number']}", 1)
    if pr is not None:
        body = body.replace("#<n>", f"#{pr}", 1)
    else:
        body = body.replace("**Pull request:** #<n>", "**Pull request:** none", 1)
    body = body.replace("<branch>", branch).replace("<commit>", tested_main(root))
    requirement = section(markdown_sections(issue["body"]), "user requirement")
    if requirement:
        body = re.sub(
            r"(^## User requirement[^\n]*\n(?:\s*<!--.*?-->)?\s*\n)>[ \t]*$",
            lambda match: match.group(1) + quoted(requirement),
            body, count=1, flags=re.MULTILINE | re.DOTALL,
        )
    with file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(body.lstrip("\n"))
    return pr


def file_field_report(
    root: Path, file: Path, pr: int | None, tracker: str | None = None
) -> tuple[str, str]:
    issue = required_snapshot(root)
    branch = delivery_branch(root, issue)
    meta, _ = issue_template(root, "field-report")
    title = meta.get("title", "").replace("<branch>", branch)
    labels = template_labels(meta.get("labels", ""))
    labels.extend(sorted(label for label in issue_labels(issue) if label.startswith("repo:")))
    try:
        body = file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Cannot read field report {file}: {error}") from error
    body = re.sub(r"\n{3,}", "\n\n", HTML_COMMENT_PATTERN.sub("", body)).strip() + "\n"
    if pr is None:
        pr = report_pull_request(root, issue, branch)
    # The template keeps its fields in the header above the first section; below it a report
    # may mention the placeholders themselves.
    header = re.split(r"^## ", body, maxsplit=1, flags=re.MULTILINE)[0]
    problems = [
        f"unfilled placeholder {placeholder}"
        for placeholder in ("#<n>", "<branch>", "<commit>") if placeholder in header
    ]
    if f"#{issue['number']}" not in body and issue["url"] not in body:
        problems.append(f"does not link work issue #{issue['number']}")
    if pr is not None and not re.search(rf"(?:#|/pull/){pr}\b", body):
        problems.append(f"does not link pull request #{pr}")
    if problems:
        raise QueueError(f"Field report {file.name}: {'; '.join(problems)}")
    repo = repo_arguments(tracker or issue["repo"])
    open_reports = json.loads(run_gh(root, [
        "issue", "list", "--state", "open", "--json", "number,title,url", "--limit", "200",
        *(argument for label in labels for argument in ("--label", label)), *repo,
    ]))
    existing = next((report for report in open_reports if report["title"] == title), None)
    if existing is not None:
        run_gh_with_body(root, ["issue", "edit", str(existing["number"]), *repo], body)
        return "updated", existing["url"]
    output = run_gh_with_body(root, [
        "issue", "create", "--title", title,
        *(argument for label in labels for argument in ("--label", label)), *repo,
    ], body)
    return "created", output.strip().splitlines()[-1] if output.strip() else title


def escalate(root: Path, number: int, file: Path, repo: str | None) -> None:
    repo = resolve_repo(root, repo)
    try:
        question = file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise QueueError(f"Cannot read escalation {file}: {error}") from error
    if not question:
        raise QueueError("The escalation needs a question")
    run_gh_with_body(root, ["issue", "comment", str(number), *repo_arguments(repo)], question + "\n")
    run_gh(root, ["issue", "edit", str(number), "--add-label", "escalated", *repo_arguments(repo)])


FIELD_REPORT_SECTIONS = (
    "user requirement (quoted back)",
    "delivered",
    "not delivered",
    "decisions",
    "spec gaps",
    "tickets for other repositories",
    "retro",
)


def field_report_references(body: str) -> tuple[int, int]:
    work = re.search(r"\bWork issue:\*{0,2}\s*#(\d+)\b", body, re.IGNORECASE)
    pull = re.search(r"\bPull request:\*{0,2}\s*#(\d+)\b", body, re.IGNORECASE)
    if work is None or pull is None:
        missing = []
        if work is None:
            missing.append("Work issue")
        if pull is None:
            missing.append("Pull request")
        raise QueueError("Field report is missing " + " and ".join(missing) + " reference")
    return int(work.group(1)), int(pull.group(1))


def validate_field_report(root: Path, number: int, repo: str) -> tuple[dict[str, object], int, int]:
    report = fetch_issue(root, number, repo)
    sections = markdown_sections(str(report["body"]))
    missing = [heading for heading in FIELD_REPORT_SECTIONS if heading not in sections]
    if missing:
        raise QueueError("Field report is missing sections: " + ", ".join(missing))
    work, pull = field_report_references(str(report["body"]))
    return report, work, pull


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


def integration_escalation(root: Path, number: int, repo: str, reason: str) -> None:
    run_gh_with_body(
        root, ["issue", "comment", str(number), *repo_arguments(repo)],
        f"Integration stopped: {reason}\n",
    )
    run_gh(root, ["issue", "edit", str(number), "--add-label", "escalated", *repo_arguments(repo)])


def worker_worktree(root: Path, branch: str) -> Path:
    listing = subprocess.run(
        ["git", "-C", str(root), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if listing.returncode != 0:
        raise QueueError("Cannot list Git worktrees")
    path: Path | None = None
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    raise QueueError(f"Cannot find the worktree for branch {branch}")


def remove_worker_worktree(root: Path, branch: str) -> None:
    worker = worker_worktree(root, branch)
    report = status_report(worker, "main")
    if not report["cleanup_eligible"]:
        reasons = "; ".join(report["cleanup_reasons"])
        raise QueueError(f"Worker worktree is not ready for removal: {reasons}")
    remove_private_queue(worker / ".se")
    make_worktree_removable(worker)
    removed = subprocess.run(
        ["git", "-C", str(root), "worktree", "remove", str(worker)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if removed.returncode != 0:
        detail = removed.stderr.strip() or f"exit code {removed.returncode}"
        raise QueueError(f"Cannot remove worker worktree: {detail}")


def restore_pre_merge(root: Path, commit: str) -> None:
    restored = subprocess.run(
        ["git", "-C", str(root), "reset", "--hard", commit],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if restored.returncode != 0:
        detail = restored.stderr.strip() or f"exit code {restored.returncode}"
        raise QueueError(f"Cannot restore pre-merge main: {detail}")


def integrate(
    root: Path,
    report_number: int,
    repo: str | None,
    suite_command: str,
    build_command: str | None,
    check_command: str | None = None,
) -> str:
    """Merge a completed worker branch and perform the mechanical integration steps."""
    tracker = resolve_repo(root, repo)
    report, work_number, pull_number = validate_field_report(root, report_number, tracker)
    project_repo = remote_repo(root) or tracker
    pull = json.loads(run_gh(root, [
        "pr", "view", str(pull_number), "--json", "headRefName,headRefOid",
        *repo_arguments(project_repo),
    ]))
    branch = str(pull.get("headRefName", ""))
    if not branch:
        raise QueueError(f"Pull request #{pull_number} has no head branch")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", suffix=".md", delete=False
    ) as stream:
        stream.write(str(report["body"]))
        report_path = Path(stream.name)
    try:
        guard(root, branch, report_path)
    finally:
        report_path.unlink(missing_ok=True)

    sync(root)
    previous = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if previous.returncode != 0 or not previous.stdout.strip():
        raise QueueError("Cannot determine pre-merge main")
    merged = subprocess.run(
        [
            "git", "-C", str(root), "merge", "--no-ff",
            "-m", f"Integrate work issue #{work_number}, field report #{report_number}, PR #{pull_number}",
            "-m", "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
            branch,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if merged.returncode != 0:
        conflicts = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        subprocess.run(["git", "-C", str(root), "merge", "--abort"], capture_output=True, check=False)
        files = ", ".join(line for line in conflicts.stdout.splitlines() if line.strip())
        raise QueueError(f"Cannot merge {branch}; conflicts: {files or 'unknown files'}")
    head = str(pull.get("headRefOid", ""))
    contained = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", head, "main"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if not head or contained.returncode != 0:
        reason = "merged main does not contain the pull request head"
        integration_escalation(root, report_number, tracker, reason)
        raise QueueError(reason)

    mirrors = configured_mirrors(root)
    has_public_mirror = any(mirror.public for mirror in mirrors)
    try:
        suite_result = run_project_command(root, suite_command, "Complete suite")
        if build_command:
            run_project_command(root, build_command, "Output regeneration")
        if check_command and not has_public_mirror:
            run_project_command(root, check_command, "Project check")
    except QueueError as error:
        restore_pre_merge(root, previous.stdout.strip())
        integration_escalation(root, report_number, tracker, str(error))
        raise

    pushed = subprocess.run(
        ["git", "-C", str(root), "push", "origin", "main"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if pushed.returncode != 0:
        detail = pushed.stderr.strip() or f"exit code {pushed.returncode}"
        raise QueueError(f"Cannot push main: {detail}")
    for mirror in mirrors:
        if mirror.public and check_command:
            run_project_command(root, check_command, "Project check")
        pushed = subprocess.run(
            ["git", "-C", str(root), "push", mirror.remote, f"main:{mirror.branch}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if pushed.returncode != 0:
            detail = pushed.stderr.strip() or f"exit code {pushed.returncode}"
            raise QueueError(f"Cannot push main to mirror {mirror.remote}: {detail}")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    ).stdout.strip()
    print(f"Suite: {suite_result}")
    for issue in (work_number, report_number):
        run_gh_with_body(
            root, ["issue", "comment", str(issue), *repo_arguments(tracker)],
            f"Integrated in {commit} from PR #{pull_number}. Suite: {suite_result}.\n",
        )
        run_gh(root, [
            "issue", "edit", str(issue), "--remove-label", "in-progress",
            *repo_arguments(tracker),
        ])
        run_gh(root, ["issue", "close", str(issue), *repo_arguments(tracker)])
    try:
        remove_worker_worktree(root, branch)
        print("Cleanup: worker worktree removed")
    except QueueError as error:
        print(f"warning: worker worktree was not removed: {error}", file=sys.stderr)
        print("Cleanup: worker worktree retained")
    started = 0
    for candidate in ready_issues(root, tracker):
        slots = capacity(root, tracker)
        if slots is not None and slots <= 0:
            break
        start(root, int(candidate["number"]), tracker, None, True)
        started += 1
    print(f"Started: {started}")
    return commit


def add_worktree_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--worktree", required=True, help="path to the selected worktree")


def add_optional_worktree_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--worktree", default=".", help="path to the selected worktree; default: current checkout"
    )


REPO_HELP = "[HOST/]OWNER/REPO; default: argument, [trackers], then origin"
ROOT_HELP = (
    "directory for new worktrees; default: sibling <checkout>.worktrees or "
    "[worktree_roots] in ~/.se/local.toml"
)
SESSION_HELP = "integrator session; default: integrator_session in ~/.se/local.toml"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize the ticket queue")
    add_worktree_argument(init_parser)

    create_parser = subparsers.add_parser("create", help="create a ticket in todo")
    add_worktree_argument(create_parser)
    create_parser.add_argument("--id", required=True, help="stable ticket ID")
    create_parser.add_argument("--title", required=True, help="ticket title")

    move_parser = subparsers.add_parser("move", help="move a ticket between states")
    add_worktree_argument(move_parser)
    move_parser.add_argument("--id", required=True, help="ticket ID")
    move_parser.add_argument("--to", required=True, choices=STATES)

    status_parser = subparsers.add_parser("status", help="report queue status")
    add_worktree_argument(status_parser)
    status_parser.add_argument("--json", action="store_true", help="emit JSON")
    status_parser.add_argument("--integration-target", help="Git ref containing worker commits")

    review_parser = subparsers.add_parser("review-note", help="append a local note disposition")
    add_worktree_argument(review_parser)
    review_parser.add_argument("--note", required=True, help="note filename in work/notes")
    review_parser.add_argument("--disposition", required=True, help="local review decision")
    review_parser.add_argument("--backlog-ref", help="optional authored backlog reference")

    close_parser = subparsers.add_parser("close", help="check or close an integrated worktree")
    add_worktree_argument(close_parser)
    close_parser.add_argument("--integration-target", help="Git ref containing worker commits")
    close_parser.add_argument("--remove", action="store_true", help="remove eligible linked worktree")
    close_parser.add_argument("--json", action="store_true", help="emit JSON")

    intake_parser = subparsers.add_parser(
        "intake", help="read the work issue with gh and write its tickets into todo")
    add_worktree_argument(intake_parser)
    intake_parser.add_argument("--issue", required=True, type=int, help="work issue number")
    intake_parser.add_argument("--repo", help=REPO_HELP)
    intake_parser.add_argument(
        "--discovery", action="store_true",
        help="create the ignored discovery evidence folder and index",
    )
    intake_parser.add_argument(
        "--probe-root",
        help="relative ignored discovery output root; default: .se/work/probe",
    )

    probe_parser = subparsers.add_parser(
        "probe", help="append a command and output path to the discovery evidence index"
    )
    add_worktree_argument(probe_parser)
    probe_parser.add_argument(
        "--command", required=True, dest="probe_command", help="command that produced the output"
    )
    probe_parser.add_argument("--output", required=True, help="path to the command output")

    refresh_parser = subparsers.add_parser(
        "refresh", help="re-read the work issue and its comments and report changes")
    add_worktree_argument(refresh_parser)
    refresh_parser.add_argument("--issue", type=int, help="work issue number; default: recorded")
    refresh_parser.add_argument("--repo", help=REPO_HELP)
    refresh_parser.add_argument("--json", action="store_true", help="emit JSON")

    report_parser = subparsers.add_parser(
        "field-report",
        help="create or update the field-report issue from a filled "
             ".github/ISSUE_TEMPLATE/field-report.md body")
    add_worktree_argument(report_parser)
    report_parser.add_argument("--file", required=True, type=Path, help="Markdown body file")
    report_parser.add_argument(
        "--draft", action="store_true",
        help="write the template body with work issue, pull request, branch and user "
             "requirement filled in to --file instead")
    report_parser.add_argument("--pr", type=int, help="pull request number; default: the branch's")

    escalate_parser = subparsers.add_parser(
        "escalate", help="comment a question on an issue and label it escalated")
    add_worktree_argument(escalate_parser)
    escalate_parser.add_argument("--issue", required=True, type=int, help="issue to escalate")
    escalate_parser.add_argument("--file", required=True, type=Path, help="Markdown question")
    escalate_parser.add_argument("--repo", help=REPO_HELP)

    sync_parser = subparsers.add_parser("sync", help="merge the newest origin/main or local main")
    add_worktree_argument(sync_parser)

    guard_parser = subparsers.add_parser(
        "guard", help="require the field report to name deleted or renamed tests"
    )
    add_worktree_argument(guard_parser)
    guard_parser.add_argument("--branch", required=True, help="branch to compare with main")
    guard_parser.add_argument(
        "--field-report", required=True, type=Path,
        help="field report containing approved removed behaviour and tests",
    )

    deliver_parser = subparsers.add_parser(
        "deliver", help="sync, push, create or update the pull request and file report")
    add_worktree_argument(deliver_parser)
    deliver_parser.add_argument("--integrator-session", help=f"{SESSION_HELP} to notify")
    deliver_parser.add_argument(
        "--tracker", help="field-report tracker [HOST/]OWNER/REPO; default: the work issue tracker"
    )

    integrate_parser = subparsers.add_parser(
        "integrate", help="validate, merge, test, push and close a field report")
    add_worktree_argument(integrate_parser)
    integrate_parser.add_argument("field_report", type=int, help="field-report issue number")
    integrate_parser.add_argument("--repo", help=REPO_HELP)
    integrate_parser.add_argument("--suite-command", required=True, help="project's complete test command")
    integrate_parser.add_argument("--build-command", help="project's output regeneration command")
    integrate_parser.add_argument("--check-command", help="project's additional check command")

    config_parser = subparsers.add_parser(
        "config", help="show the repository and the machine-local settings in effect")
    add_worktree_argument(config_parser)
    config_parser.add_argument("--repo", help=REPO_HELP)
    config_parser.add_argument("--worktree-root", help=ROOT_HELP)
    config_parser.add_argument("--integrator-session", help=SESSION_HELP)

    start_parser = subparsers.add_parser(
        "start", help="start a ready work issue: worktree from the newest main, label in-progress")
    add_worktree_argument(start_parser)
    start_parser.add_argument("issue", type=int)
    start_parser.add_argument("--repo", help=REPO_HELP)
    start_parser.add_argument("--worktree-root", help=ROOT_HELP)
    start_parser.add_argument(
        "--no-create", dest="create", action="store_false",
        help="only change the labels; the project's own script created the worktree")
    start_parser.add_argument("--cloud-agent", help="GitHub login for a cloud worker")

    block_parser = subparsers.add_parser("block", help="link an issue to a native blocker")
    add_worktree_argument(block_parser)
    block_parser.add_argument("issue", type=int)
    block_parser.add_argument("--by", required=True, type=int, dest="blocker")
    block_parser.add_argument("--repo", help=REPO_HELP)

    for name, help_text in (
        ("ready", "list startable ready work issues"),
        ("capacity", "show local worker capacity or cloud unlimited capacity"),
        ("queue", "list open field reports and startable work issues"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        add_optional_worktree_argument(command_parser)
        command_parser.add_argument("--repo", help=REPO_HELP)
        command_parser.add_argument(
            "--all-repos", action="store_true", help="include tracker issues for every repository"
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Issue text may hold characters a legacy console code page cannot show.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = make_parser().parse_args(argv)
    try:
        root = worktree_root(args.worktree)
        if args.command == "init":
            initialize(root)
            print(f"Initialized ticket queue in {root / '.se' / 'work'}")
            return 0
        if args.command == "create":
            create_ticket(root, args.id, args.title)
            print(f"Created ticket {args.id} in todo")
            return 0
        if args.command == "move":
            move_ticket(root, args.id, args.to)
            print(f"Moved ticket {args.id} to {args.to}")
            return 0
        if args.command == "review-note":
            review_note(root, args.note, args.disposition, args.backlog_ref)
            print(f"Reviewed note {args.note}")
            return 0
        if args.command == "intake":
            issue, created, kept = intake(
                root, args.issue, args.repo, args.discovery, args.probe_root
            )
            print(f"Work issue #{issue['number']}: {issue['title']} ({issue['url']})")
            for ticket_id in created:
                print(f"created todo/{ticket_id}.md")
            for ticket_id in kept:
                print(f"kept existing ticket for {ticket_id}")
            if issue["comments"]:
                print(f"{len(issue['comments'])} comment(s) may change the requirements:")
                for comment in issue["comments"]:
                    print(f"  {comment['createdAt']} {comment['author']}: {comment['url']}")
            return 0
        if args.command == "probe":
            print(
                f"Appended discovery evidence to "
                f"{append_discovery_evidence(root, args.probe_command, args.output)}"
            )
            return 0
        if args.command == "refresh":
            changes = refresh(root, args.issue, args.repo)
            if args.json:
                print(json.dumps(changes, indent=2, ensure_ascii=False))
            else:
                print_changes(changes)
            return 0
        if args.command == "field-report":
            if args.draft:
                pr = draft_field_report(root, args.file, args.pr)
                print(f"Drafted {args.file}" + ("" if pr else "; no pull request found yet"))
            else:
                action, url = file_field_report(root, args.file, args.pr)
                print(f"Field report {action}: {url}")
            return 0
        if args.command == "escalate":
            escalate(root, args.issue, args.file, args.repo)
            print(f"Escalated #{args.issue}")
            return 0
        if args.command == "sync":
            print(f"Merged main {sync(root)}")
            return 0
        if args.command == "guard":
            removed = guard(root, args.branch, args.field_report)
            if removed:
                for name in removed:
                    print(f"Field report names removed test: {name}")
            else:
                print("No deleted or renamed tests found.")
            return 0
        if args.command == "deliver":
            session = config_value(
                "integrator_session", str(required_snapshot(root)["repo"]), args.integrator_session)
            report_url = deliver(root, args.tracker)
            print(f"Notify {session or '<integrator session>'}: field report {report_url}")
            return 0
        if args.command == "integrate":
            commit = integrate(
                root, args.field_report, args.repo, args.suite_command, args.build_command,
                args.check_command,
            )
            print(f"Integrated field report #{args.field_report} in {commit}")
            return 0
        if args.command == "config":
            repo = resolve_repo(root, args.repo)
            print(f"repository: {repo}")
            print(f"machine-local config: {local_config_path()}")
            directory = configured_worktree_root(root, args.worktree_root)
            print(f"worktree root: {directory or default_worktree_root(root)}")
            session = config_value("integrator_session", repo, args.integrator_session)
            print(f"integrator session: {session or '(not set)'}")
            return 0
        if args.command == "start":
            path = start(
                root, args.issue, args.repo, args.worktree_root, args.create, args.cloud_agent
            )
            if path is not None:
                issue = fetch_issue(root, args.issue, resolve_repo(root, args.repo))
                print(f"Launch worker: agent=worker issue={issue['url']} worktree={path}")
            print(f"Started #{args.issue}")
            return 0
        if args.command == "block":
            block(root, args.issue, args.blocker, args.repo)
            print(f"Blocked #{args.issue} by #{args.blocker}")
            return 0
        if args.command in {"ready", "capacity", "queue"}:
            repo = resolve_repo(root, args.repo)
            if args.command == "capacity":
                slots = capacity(root, repo, args.all_repos)
                print("Capacity: unlimited (cloud)" if slots is None else f"Capacity: {slots}")
                return 0
            ready = ready_issues(root, repo, args.all_repos)
            if args.command == "ready":
                for issue in ready:
                    print(f"#{issue['number']} {issue['title']}")
                return 0
            reports, escalations, _, slots = queue(root, repo, args.all_repos)
            for report in reports:
                print(f"field-report #{report['number']} {report['title']} {report['url']}")
            for escalation in escalations:
                print(f"escalated #{escalation['number']} {escalation['title']} {escalation['url']}")
            print("Capacity: unlimited (cloud)" if slots is None else f"Capacity: {slots}")
            for issue in ready:
                print(f"ready #{issue['number']} {issue['title']}")
            return 0
        if args.command == "close":
            if args.remove and not args.integration_target:
                raise QueueError("--remove requires --integration-target")
            report = status_report(root, args.integration_target)
            report["removed"] = False
            if report["cleanup_eligible"] and args.remove:
                listing = subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                try:
                    admin_path = primary_checkout_path(listing.stdout)
                    if listing.returncode != 0 or admin_path is None:
                        raise OSError("Could not identify the primary checkout")
                    remove_private_queue(root / ".se")
                    make_worktree_removable(root)
                    removed = subprocess.run(
                        [
                            "git", "-C", str(admin_path), "worktree", "remove",
                            str(root),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
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
                    report["removed"] = False
                else:
                    report["removed"] = True
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"Cleanup eligible: {'yes' if report['cleanup_eligible'] else 'no'}")
                for reason in report["cleanup_reasons"]:
                    print(f"reason: {reason}")
                if report["removed"]:
                    print("removed: yes")
            return 0 if report["cleanup_eligible"] else 1

        report = status_report(root, args.integration_target)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"Initialized: {'yes' if report['initialized'] else 'no'}")
            print("Counts: " + ", ".join(
                f"{state}={report['counts'][state]}" for state in STATES
            ))
            for state in STATES:
                print(f"{state}: {', '.join(report['tickets'][state]) or '(none)'}")
            print(f"notes: {', '.join(report['notes']) or '(none)'}")
            print(
                "notes resolved/unresolved: "
                f"{report['note_counts']['resolved']}/{report['note_counts']['unresolved']}"
            )
            print(f"complete: {'yes' if report['complete'] else 'no'}")
            print(
                f"cleanup eligible: {'yes' if report['cleanup_eligible'] else 'no'}"
            )
            for reason in report["cleanup_reasons"]:
                print(f"cleanup reason: {reason}")
            for error in report["errors"]:
                print(f"error: {error}")
        return 0 if report["initialized"] and not report["errors"] else 1
    except (QueueError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
