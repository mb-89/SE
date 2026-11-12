#!/usr/bin/env python3
"""Public-safety check: refuse content that identifies an employer, work project, person,
machine, account or internal host. The rule is owned by AGENTS.md, section "Public safety".

Scans tracked file names and contents (binary files as bytes), commit messages and author and
committer identities against the public term list (public-check-terms.toml, beside this script)
and the source's local list (.public-check.local at its root, never checked in), which adds the
source's own terms and switches public entries off for it. Output names the location and the
pattern label only, never the matched text. A tracked local list, and the retired machine-level
list (~/.se/private-terms.txt, SE_PRIVATE_TERMS), stop the check with their remedy.

The commit gates (a message file, the commits of a --range) also refuse tracker references and
attribution trailers (`Co-Authored-By:`, `Claude-Session:`) in messages, from every author,
naming the reference or trailer and the remedy; a full check leaves old history to them. CI runs
the --range gate on every pull request and every push to the integration branch
(.github/workflows/check.yml). The commits of a --range must also carry the project identity (se.toml [project] identity, unless the
machine sets public_identity), where one is set; GitHub's web-flow identity, the committer of a
commit made on GitHub, passes as committer, and on such a commit the author may be the GitHub
noreply address of the account owning origin on github.com (the squash merge of a pull request into
main). A hit names the identity found, redacted. A
`commit:<full sha> author|committer` entry in .public-check-allow allows the identity in that role
on that one commit, and a `commit:<full sha> message` entry the message hits of that one commit,
for history already published. A --range on a shallow clone that reaches beyond the fetched
history is refused, so the check never passes over commits it cannot see.

Every verdict names the se commit that ran it. A checked repository that pins se (`[modules.se]`
in its se.toml) is refused when this se is not at that `ref`, or when the version this se's
se.toml sets lies outside that `version` range, so a stale clone never gives another verdict
silently.

Allow entries are reported by kind: used ones are counted in the verdict; an unused one is a hit
where the source has a local list, and without it a warning that it is unverifiable, as it may
cover a local-term hit the run cannot see.

Exit codes: 0 passed, 1 hits (or unused allow entries in a full check), 2 usage or setup error.
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

ALLOW_FILE = ".public-check-allow"
SE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "se.toml"
TERMS_FILE = Path(__file__).with_name("public-check-terms.toml")
LOCAL_FILE = ".public-check.local"
# The retired machine-level list: found, the check stops and names where its terms go.
MACHINE_ENV = "SE_PRIVATE_TERMS"
MACHINE_DEFAULT = "~/.se/private-terms.txt"

# GitHub's web-flow identity: the committer of a commit made on GitHub itself. It names no person,
# so the identity gate accepts it as committer next to the project identity, never as author.
WEB_FLOW = "GitHub <" + "noreply" + "@github.com>"
# The author of a commit made on GitHub (a squash merge): the account that made it, by the GitHub
# noreply address of its login, `<id>+<login>` or `<login>`.
GITHUB_ACCOUNT = re.compile(r"<(?:\d+\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com>$")


def _always(match: re.Match[str]) -> bool:
    return True


@dataclass(frozen=True)
class Pattern:
    label: str
    regex: re.Pattern[str]
    accept: Callable[[re.Match[str]], bool] = _always


def _not_placeholder(data: dict, term: dict) -> Callable[[re.Match[str]], bool]:
    start = tuple(data["placeholder"]["start"])
    generic = set(data["generic"][term["generic"]])
    group = term.get("group", 1)

    def accept(match: re.Match[str]) -> bool:
        name = match.group(group)
        return not name.startswith(start) and name.lower() not in generic

    return accept


def _personal_email(data: dict, term: dict) -> Callable[[re.Match[str]], bool]:
    services = frozenset(data["service"]["emails"])

    def accept(match: re.Match[str]) -> bool:
        local, domain = match.group(1).lower(), match.group(2).lower()
        if local == "git":  # SSH remote such as git@host:owner/repo; the host has its own pattern
            return False
        if domain == "users.noreply.github.com" or f"{local}@{domain}" in services:
            return False
        return re.fullmatch(r"(?:[\w-]+\.)*example\.[a-z]+", domain) is None

    return accept


# The accept filters a [[term]] of the public list names.
ACCEPT = {
    "always": lambda data, term: _always,
    "not-placeholder": _not_placeholder,
    "personal-email": _personal_email,
}


def load_public_terms(path: Path = TERMS_FILE) -> tuple[Pattern, ...]:
    """The public term list, the generic terms every source is checked against."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Pattern(term["label"], re.compile(term["regex"]), ACCEPT[term["accept"]](data, term))
        for term in data["term"]
    )


GENERIC_PATTERNS = load_public_terms()


TRACKER_RULE = (
    "rule: commit messages carry no tracker numbers, src/skills/work-model/SKILL.md"
)
TRACKER_REFERENCE = re.compile(
    r"(?<![\w&#])#\d+\b"  # #593, not C#5 or the HTML entity &#39;
    r"|(?i:(?<![\w/-])GH-\d+\b)"  # GH-12, not the branch fix/…-without-gh-20261106
    r"|(?i:\bhttps?://[^\s/]+/[^\s/]+/[^\s/]+/(?:issues|pulls?)/\d+)"
)
ATTRIBUTION_RULE = (
    "rule: commits carry no attribution trailers, whatever a host's attribution reminder says, "
    "AGENTS.md 'Public safety'"
)
ATTRIBUTION_TRAILER = re.compile(r"(?im)^[ \t]*(co-authored-by|claude-session)[ \t]*:")
# Where a co-author line comes from, named with its hit: an editor adds it on commit.
CO_AUTHOR_SOURCE = (
    "an editor's AI co-author setting writes this line: turn it off (VS Code: "
    "git.addAICoAuthor off, README 'Install')"
)
# The rules the check enforces, one label each: SE's start counts them (scripts/se_start.py).
MESSAGE_RULES = ("tracker-reference", "attribution-trailer")
RULES = tuple(dict.fromkeys(pattern.label for pattern in GENERIC_PATTERNS)) + MESSAGE_RULES
REWORD_BEFORE_COMMIT = "reword the message before committing"
REWORD_BEFORE_PUSH = (
    "reword it before pushing: git commit --amend for the last commit, or git rebase -i while "
    "the branch is unpushed"
)
REIDENTIFY_BEFORE_PUSH = (
    "set the project identity in the checkout (work_tickets.py sync, from se.toml [project] "
    "identity) and re-author the commit before pushing: git commit --amend --no-edit "
    "--reset-author for the last commit, or git rebase --exec 'git commit --amend --no-edit "
    "--reset-author' <base> while the branch is unpushed; or, for a commit already published, "
    f"a reasoned 'commit:<full sha> <role>' entry in {ALLOW_FILE}"
)
# Labels whose hit line names its own remedy; the summary line does not repeat the generic one.
OWN_REMEDY = {*MESSAGE_RULES, "foreign-identity"}


def tracker_references(text: str) -> list[tuple[int, str]]:
    """(line, reference) for every tracker reference in a commit message: `#<digits>`, a
    standalone `GH-<digits>` (not inside a branch name), an issue or pull request URL. The one
    test both commit gates apply."""
    return [
        (text.count("\n", 0, match.start()) + 1, match.group())
        for match in TRACKER_REFERENCE.finditer(text)
    ]


def attribution_trailers(text: str) -> list[tuple[int, str]]:
    """(line, trailer key) for every `Co-Authored-By:` or `Claude-Session:` line of a commit
    message, in any case. The one test both commit gates apply."""
    return [
        (text.count("\n", 0, match.start()) + 1, match.group(1))
        for match in ATTRIBUTION_TRAILER.finditer(text)
    ]


class SetupError(Exception):
    """A usage or configuration problem; exit code 2."""


@dataclass
class Hit:
    location: str
    label: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.location}: {self.label}{self.detail}"


@dataclass
class AllowEntry:
    line: int
    glob: str | None = None
    path: str | None = None
    path_line: int | None = None
    commit: str | None = None
    role: str | None = None
    used: bool = False
    seen: bool = False  # a commit entry's commit was gated, so every hit it covers was looked for

    @property
    def form(self) -> str:
        """The entry's form as the header of the allow file writes it."""
        if self.commit is not None:
            return f"commit:<full sha> {self.role}"
        return "<path glob>" if self.glob is not None else "<path>:<line>"

    def matches(self, path: str, line: int | None) -> bool:
        if self.glob is not None:
            return fnmatch.fnmatchcase(path, self.glob)
        return self.path is not None and path == self.path and line == self.path_line


COMMIT_ENTRY = re.compile(r"commit:(\S*)(?:\s+(\S+))?")
ROLES = ("author", "committer", "message")
COMMIT_FORM = "commit:<full sha> author|committer|message"


@dataclass
class Report:
    hits: list[Hit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: int = 0
    commits: int = 0
    allow_used: int = 0
    off: list[str] = field(default_factory=list)  # public labels the local list switches off


@dataclass
class LocalList:
    """A source's local list: its own terms, and the public labels it switches off."""
    terms: list[Pattern] = field(default_factory=list)
    off: set[str] = field(default_factory=set)


LOCAL_OFF = re.compile(r"off:(\S+)")
LOCAL_FORMS = "'<regex>' or 'off:<public label>  # reason'"
UNTRACK_REMEDY = (
    f"run git rm --cached {LOCAL_FILE}, then ignore it (scripts/setup.sh or setup.ps1 adds it to "
    ".gitignore)"
)


def check_machine_list() -> None:
    """Refuse while the retired machine-level list is configured, so none of its terms is
    silently skipped."""
    if os.environ.get(MACHINE_ENV):
        where = f"the file {MACHINE_ENV} names"
    elif Path(MACHINE_DEFAULT).expanduser().is_file():
        where = MACHINE_DEFAULT
    else:
        return
    raise SetupError(
        f"the machine-level term list ({where}) is retired: move its terms into "
        f"<source>/{LOCAL_FILE}, the local list at the root of each repository or vault that "
        f"needs them (never checked in), then delete it and unset {MACHINE_ENV}; "
        "AGENTS.md 'Public safety'"
    )


def check_untracked(root: Path, rev: str | None) -> None:
    """Refuse a local list git tracks, in the index or in the checked commit."""
    tracked = git(root, "ls-files", "--", LOCAL_FILE).strip()
    if not tracked and rev:
        tracked = git(root, "ls-tree", "--name-only", rev, "--", LOCAL_FILE).strip()
    if tracked:
        raise SetupError(f"{LOCAL_FILE} is tracked by git, but a local list is never checked in: "
                         f"{UNTRACK_REMEDY}")


def load_local(root: Path) -> LocalList | None:
    """The local list at the source's root, or None where it has none. Hits name only its line
    number, never the term."""
    path = root / LOCAL_FILE
    if not path.is_file():
        return None
    public = {pattern.label for pattern in GENERIC_PATTERNS}
    local = LocalList()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        off = LOCAL_OFF.match(text)
        if off:
            label, _, reason = text[off.end():].partition("#")
            if label.strip() or not reason.strip():
                raise SetupError(f"{LOCAL_FILE}:{number}: write {LOCAL_FORMS}")
            if off.group(1) not in public:
                raise SetupError(f"{LOCAL_FILE}:{number}: no public entry is labelled "
                                 f"{off.group(1)!r}; the labels are {', '.join(sorted(public))}")
            local.off.add(off.group(1))
            continue
        try:
            regex = re.compile(text, re.IGNORECASE)
        except re.error as error:
            raise SetupError(
                f"{LOCAL_FILE}:{number} is not a valid regex ({error.msg})"
            ) from None
        local.terms.append(Pattern(f"local-term:{number}", regex))
    return local


def load_allow(root: Path) -> list[AllowEntry]:
    path = root / ALLOW_FILE
    if not path.is_file():
        return []
    entries = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        entry, _, reason = text.partition("#")
        entry = entry.strip()
        if not entry or not reason.strip():
            raise SetupError(f"{ALLOW_FILE}:{number}: write '<path glob or file:line>  # reason' "
                             f"or '{COMMIT_FORM}  # reason'")
        commit = COMMIT_ENTRY.fullmatch(entry)
        if commit:
            sha, role = commit.group(1).lower(), commit.group(2)
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) or role not in ROLES:
                raise SetupError(f"{ALLOW_FILE}:{number}: write '{COMMIT_FORM}  # reason'")
            entries.append(AllowEntry(number, commit=sha, role=role))
            continue
        file_line = re.fullmatch(r"(.+):(\d+)", entry)
        if file_line:
            entries.append(
                AllowEntry(number, path=file_line.group(1), path_line=int(file_line.group(2)))
            )
        else:
            entries.append(AllowEntry(number, glob=entry))
    return entries


def find(text: str, patterns: Iterable[Pattern]) -> list[tuple[int, int, str]]:
    """Return sorted (line, column, label) for every accepted match."""
    line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
    found = set()
    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            if pattern.accept(match):
                line = bisect.bisect_right(line_starts, match.start())
                found.add((line, match.start() - line_starts[line - 1] + 1, pattern.label))
    return sorted(found)


def redact(text: str, patterns: Iterable[Pattern]) -> str:
    """Replace every accepted match by <label>, so a printed path never shows what matched."""
    spans = sorted(
        (match.start(), match.end(), pattern.label)
        for pattern in patterns
        for match in pattern.regex.finditer(text)
        if pattern.accept(match) and match.end() > match.start()
    )
    parts, position = [], 0
    for start, end, label in spans:
        if start >= position:
            parts += [text[position:start], f"<{label}>"]
            position = end
        else:
            position = max(position, end)
    return "".join(parts) + text[position:]


def is_binary(data: bytes) -> bool:
    return b"\0" in data


def decode(data: bytes) -> str:
    if is_binary(data):
        # Keep the newline bytes so lines stay countable; dropping NULs exposes UTF-16 text.
        return data.replace(b"\0", b"").decode("latin-1")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SetupError(f"git {args[0]} failed: {detail}")
    return result.stdout


def read_blobs(root: Path, shas: list[str]) -> list[bytes]:
    if not shas:
        return []
    output = git(root, "cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in shas).encode())
    blobs, position = [], 0
    for _ in shas:
        header_end = output.index(b"\n", position)
        size = int(output[position:header_end].split()[2])
        blobs.append(output[header_end + 1 : header_end + 1 + size])
        position = header_end + 1 + size + 1
    return blobs


def object_files(root: Path, staged: bool, rev: str | None) -> list[tuple[str, bytes]]:
    """Files of the index (staged) or of a commit's tree (rev), read from the object store."""
    if staged:
        listing = git(root, "ls-files", "-s", "-z")
        sha_field, kinds = 1, None
    else:
        listing = git(root, "ls-tree", "-r", "-z", "--full-tree", rev)
        sha_field, kinds = 2, {b"blob"}
    items = []
    for line in listing.split(b"\0"):
        if not line:
            continue
        meta, path = line.split(b"\t", 1)
        fields = meta.split()
        if fields[0] == b"160000" or (kinds is not None and fields[1] not in kinds):
            continue  # submodules are checked in their own repository
        items.append((path.decode("utf-8", "replace"), fields[sha_field].decode()))
    blobs = read_blobs(root, [sha for _, sha in items])
    return [(path, blob) for (path, _), blob in zip(items, blobs)]


def worktree_files(root: Path) -> Iterable[tuple[str, bytes]]:
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", "replace")
        full = root / path
        if full.is_file():
            yield path, full.read_bytes()


def scan_files(files: Iterable[tuple[str, bytes]], patterns: list[Pattern],
               allow: list[AllowEntry], report: Report) -> None:
    def allowed(path: str, line: int | None) -> bool:
        hit = False
        for entry in allow:
            if entry.matches(path, line):
                entry.used = hit = True
        return hit

    for path, data in files:
        report.files += 1
        shown = redact(path, patterns)
        for _, _, label in find(path, patterns):
            if not allowed(path, None):
                report.hits.append(Hit(f"{shown} (file name)", label))
        binary = " (binary)" if is_binary(data) else ""
        for line, column, label in find(decode(data), patterns):
            if not allowed(path, line):
                report.hits.append(Hit(f"{shown}:{line}:{column}{binary}", label))


def scan_message(where: str, message: str, patterns: list[Pattern], report: Report,
                 remedy: str | None = None) -> None:
    """Hits in a commit message; with a remedy, tracker references and attribution trailers too
    (the commit gates)."""
    for line, _, label in find(message, patterns):
        report.hits.append(Hit(f"{where} message:{line}", label))
    if remedy is None:
        return
    for line, reference in tracker_references(message):
        shown = redact(reference, patterns)  # a URL may name a private host
        report.hits.append(Hit(f"{where} message:{line}", "tracker-reference",
                               f" '{shown}' ({TRACKER_RULE}); {remedy}"))
    for line, key in attribution_trailers(message):
        source = f"; {CO_AUTHOR_SOURCE}" if key.lower() == "co-authored-by" else ""
        report.hits.append(Hit(f"{where} message:{line}", "attribution-trailer",
                               f" '{key}:' ({ATTRIBUTION_RULE}); {remedy}{source}"))


def scan_identity(where: str, role: str, identity: str, patterns: list[Pattern],
                  report: Report) -> None:
    for label in sorted({label for _, _, label in find(identity, patterns)}):
        report.hits.append(Hit(f"{where} {role}", label))


def project_identity(root: Path) -> str | None:
    """`Name <email>` every gated commit carries: the identity work_tickets.py sync sets (one
    owner: work_tickets.commit_identity); None where the project and the machine set none."""
    work_tickets = sibling("work_tickets")
    try:
        identity = work_tickets.commit_identity(root)
    except work_tickets.QueueError as error:
        raise SetupError(str(error)) from error
    return None if identity is None else f"{identity[0]} <{identity[1]}>"


def repository_owner(root: Path) -> str | None:
    """The account owning the checkout's origin on github.com (lower case), else None."""
    repo = sibling("work_tickets").remote_repo(root)
    host, _, path = (repo or "").partition("/")
    return path.split("/", 1)[0].lower() if host.lower() == "github.com" else None


def made_on_github_by_owner(author: str, committer: str, owner: str | None) -> bool:
    """A commit GitHub made (web-flow committer) for the repository's owning account, such as
    the squash merge of a pull request into main: its author is that account's noreply address."""
    account = GITHUB_ACCOUNT.search(author)
    return (committer == WEB_FLOW and owner is not None and account is not None
            and account.group(1).lower() == owner)


def scan_project_identity(where: str, role: str, identity: str, expected: str,
                          patterns: list[Pattern], report: Report) -> None:
    if identity != expected and (role, identity) != ("committer", WEB_FLOW):
        shown = redact(identity, patterns)  # a foreign identity may name a person
        report.hits.append(Hit(f"{where} {role}", "foreign-identity",
                               f" '{shown}' is not the project identity '{expected}'; "
                               f"{REIDENTIFY_BEFORE_PUSH}"))


def scan_history(root: Path, revisions: list[str], patterns: list[Pattern], report: Report,
                 gate: bool, allow: list[AllowEntry]) -> None:
    """Hits in the identities and messages of `revisions`; a gate (commits not yet pushed) also
    refuses tracker references, attribution trailers and identities other than the project
    identity. A commit entry of
    `allow` drops the hits of its role (an identity, or the message) on its commit; in a gate,
    where every hit it may cover is looked for, one that drops none is reported unused."""
    expected = project_identity(root) if gate else None
    owner = repository_owner(root) if expected is not None else None
    output = git(root, "log", "-z", "--format=%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%B", *revisions, "--")
    for record in output.decode("utf-8", "replace").split("\0"):
        if not record.strip():
            continue
        sha, author, committer, message = record.split("\x1f", 3)
        where = f"commit {sha[:12]}"
        report.commits += 1
        found = len(report.hits)
        scan_identity(where, "author", author, patterns, report)
        if committer != author:
            scan_identity(where, "committer", committer, patterns, report)
        if expected is not None and not made_on_github_by_owner(author, committer, owner):
            scan_project_identity(where, "author", author, expected, patterns, report)
        if expected is not None:
            scan_project_identity(where, "committer", committer, expected, patterns, report)
        scan_message(where, message, patterns, report, REWORD_BEFORE_PUSH if gate else None)
        entries = {entry.role: entry for entry in allow if entry.commit == sha}
        kept = []
        for hit in report.hits[found:]:
            role = hit.location[len(where) + 1:].split(":", 1)[0]
            if role in entries:
                entries[role].used = True
            else:
                kept.append(hit)
        report.hits[found:] = kept
        if gate:
            for entry in entries.values():
                entry.seen = True


def scan_message_file(root: Path, path: Path, patterns: list[Pattern], report: Report) -> None:
    report.commits += 1
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scan_message("commit", "\n".join("" if line.startswith("#") else line for line in lines),
                 patterns, report, REWORD_BEFORE_COMMIT)
    for role, variable in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        identity = git(root, "var", variable).decode("utf-8", "replace")
        scan_identity("commit", role, identity.rsplit(">", 1)[0] + ">", patterns, report)


def has_head(root: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
        capture_output=True, check=False,
    ).returncode == 0


def se_commit() -> str | None:
    """The commit of the se checkout this script runs from, or None outside a git checkout."""
    result = subprocess.run(
        ["git", "-C", str(SE_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip().lower() if result.returncode == 0 else None


def se_pin(root: Path) -> dict | None:
    """`[modules.se]` of the checked repository's se.toml, or None where it pins none."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        return None
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise SetupError(f"cannot read {MANIFEST} of the checked repository: {error}") from error
    modules = data.get("modules")
    module = modules.get("se") if isinstance(modules, dict) else None
    if module is None:
        return None
    if not isinstance(module, dict) or not isinstance(module.get("ref", module.get("version")), str):
        raise SetupError(f"[modules.se] in {MANIFEST} has no ref; pin a full commit SHA or a version range")
    return module


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded under its own name."""
    import importlib.util
    qualified = f"public_check_{name}"
    spec = importlib.util.spec_from_file_location(qualified, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


def se_modules():
    """scripts/se_modules.py, the owner of semantic versions and ranges."""
    return sibling("se_modules")


def record_verdict(args: argparse.Namespace, passed: bool) -> None:
    """A check of `--rev` records its verdict on that tree (scripts/verdicts.py), which the push to
    the integration branch needs."""
    if not args.rev or args.no_history:
        return
    root = Path(args.repo).resolve()
    try:
        tree = sibling("verdicts").record(root, "public-check", args.rev, passed)
    except (OSError, ValueError) as error:
        print(f"public-check: warning: verdict not recorded: {error}")
        return
    print(f"public-check: verdict recorded on tree {tree[:12]}")


def check_se_range(text: str) -> None:
    """Refuse unless the version this se's own se.toml sets lies within the range `text`."""
    modules = se_modules()
    remedy = ("bring the se clone into the range (scripts/se_modules.py sync) or widen the range, "
              "and check again")
    try:
        bounds = modules.version_bounds("se", text)
        version = modules.checkout_version(SE_ROOT)
    except modules.ModuleError as error:
        raise SetupError(f"{MANIFEST} pins se at version {text!r}, but {error}; {remedy}") from error
    if version is None:
        raise SetupError(
            f"{MANIFEST} pins se at version {text!r}, but the se running this check "
            f"({SE_ROOT.name}) sets no version in its {MANIFEST}; {remedy}"
        )
    if not modules.matches(version, bounds):
        raise SetupError(
            f"{MANIFEST} pins se at version {text!r}, but this check runs se "
            f"{modules.version_text(version)}; {remedy}"
        )


def check_se_version(root: Path, commit: str | None) -> None:
    """Refuse when the checked repository pins another se than the one running: another commit
    for a `ref`, a version outside the range for a `version`."""
    module = se_pin(root)
    if module is None:
        return
    if "version" in module:
        check_se_range(module["version"])
        return
    pin = module["ref"].lower()
    if commit is None:
        raise SetupError(
            f"{MANIFEST} pins se at {pin[:7]}, but the se running this check ({SE_ROOT.name}) is "
            "not a git checkout, so its commit is unknown; run the check from an se clone"
        )
    if commit != pin:
        raise SetupError(
            f"{MANIFEST} pins se at {pin[:7]}, but this check runs se {commit[:7]}; bring the se "
            "clone to the pin (scripts/se_modules.py sync, or git checkout of the pin) and "
            "check again"
        )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refuse work-specific or personal content (rule: AGENTS.md 'Public safety')."
    )
    parser.add_argument("--repo", default=".",
                        help="repository to check; default: the working directory")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--staged", action="store_true",
                        help="scan the index instead of the working tree; no history unless --range")
    source.add_argument("--rev", help="scan the tree of this commit; history defaults to it")
    source.add_argument("--message-file", type=Path,
                        help="scan only this commit message and the current author and committer")
    parser.add_argument("--range", dest="revisions",
                        help="git log revisions whose messages and identities are checked, split "
                             "on spaces (for example 'A..B' or 'B --not --remotes'); default: "
                             "HEAD. Given, it gates commits: their messages must carry no tracker "
                             "references or attribution trailers either")
    parser.add_argument("--no-history", action="store_true",
                        help="skip commit messages and identities")
    return parser.parse_args(argv)


def check(args: argparse.Namespace, commit: str | None) -> Report:
    root = Path(git(Path(args.repo).resolve(), "rev-parse", "--show-toplevel").decode().strip())
    check_se_version(root, commit)
    check_machine_list()
    check_untracked(root, args.rev)
    report = Report()
    local = load_local(root)
    has_local = local is not None
    if local is None:
        local = LocalList()
        report.warnings.append(
            f"no local list ({LOCAL_FILE}); only the public list was checked"
        )
    else:
        report.off = sorted(local.off)
    patterns = [p for p in GENERIC_PATTERNS if p.label not in local.off] + local.terms
    if args.message_file is not None:
        scan_message_file(root, args.message_file, patterns, report)
        return report
    allow = load_allow(root)
    if args.staged or args.rev:
        files: Iterable[tuple[str, bytes]] = object_files(root, args.staged, args.rev)
    else:
        files = worktree_files(root)
    scan_files(files, patterns, allow, report)
    revisions = args.revisions or ("" if args.staged else args.rev or "HEAD")
    if not args.no_history and revisions and (args.revisions or has_head(root)):
        if args.revisions:
            check_fetched(root, args.revisions)
        scan_history(root, revisions.split(), patterns, report, gate=bool(args.revisions),
                     allow=allow)
    report_unused(allow, has_local, report)
    return report


def report_unused(allow: list[AllowEntry], full: bool, report: Report) -> None:
    """Each entry this run could judge, by kind: used (counted in the verdict); unused, a hit
    where the check is full; unverifiable, a warning without the local list, as the entry may
    cover a local-term hit this run cannot see. A commit entry is judged only where its
    commit was gated, as a gate's hit is not seen by every check."""
    for entry in allow:
        if entry.used:
            report.allow_used += 1
        elif entry.commit is not None and not entry.seen:
            continue
        elif full:
            report.hits.append(Hit(f"{ALLOW_FILE}:{entry.line}", "unused-allow-entry",
                                   f" ('{entry.form}' entry; unused: remove it or correct it in "
                                   "place)"))
        else:
            report.warnings.append(
                f"allow entry {ALLOW_FILE}:{entry.line} ('{entry.form}' entry) is unverifiable "
                f"without the local list: run with it ({LOCAL_FILE}) to check whether it is "
                "still used"
            )


def shallow_boundary(root: Path) -> set[str]:
    """The commits whose parents a shallow clone has not fetched; empty in a complete clone."""
    if git(root, "rev-parse", "--is-shallow-repository").decode().strip() != "true":
        return set()
    path = Path(git(root, "rev-parse", "--git-path", "shallow").decode().strip())
    path = path if path.is_absolute() else root / path
    return set(path.read_text(encoding="utf-8").split()) if path.is_file() else set()


def check_fetched(root: Path, revisions: str) -> None:
    """Refuse a range that reaches beyond a shallow clone's fetched history: a gate over commits
    it cannot see would pass vacuously."""
    boundary = shallow_boundary(root)
    if not boundary:
        return
    listed = git(root, "rev-list", *revisions.split(), "--").decode().split()
    beyond = sorted(boundary.intersection(listed))
    if beyond:
        raise SetupError(
            f"--range '{revisions}' reaches beyond the fetched history of this shallow clone (at "
            f"{beyond[0][:12]}, whose parents are not fetched); run git fetch --unshallow and "
            "check again"
        )


def main(argv: list[str] | None = None) -> int:
    commit = se_commit()
    version = f"se {commit[:7] if commit else 'commit unknown'}"
    args = parse_args(argv)
    try:
        report = check(args, commit)
    except SetupError as error:
        print(f"public-check: error ({version}): {error}")
        return 2
    record_verdict(args, not report.hits)
    for warning in report.warnings:
        print(f"public-check: warning: {warning}")
    for hit in report.hits:
        print(hit)
    used = f"{report.allow_used} allow entries used, " if report.allow_used else ""
    off = f"public entries off locally: {', '.join(report.off)}, " if report.off else ""
    scope = f"{report.files} files, {report.commits} commits, {used}{off}{version}"
    if report.hits:
        remedy = "fix each as its line says"
        if any(hit.label not in OWN_REMEDY for hit in report.hits):
            remedy = f"remove them or add a reasoned entry to {ALLOW_FILE}"
        print(f"public-check: FAILED with {len(report.hits)} hit(s) ({scope}); {remedy}")
        return 1
    print(f"public-check: passed ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
