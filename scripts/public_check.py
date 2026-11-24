#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Public-safety check: refuse content that identifies an employer, work project, person,
machine, account or internal host. The rule is owned by AGENTS.md, section "Public safety".

Scans tracked file names and contents (binary files as bytes), commit messages and author and
committer identities against the public term list (public-check-terms.toml, beside this script)
and the source's local list (.public-check.local at its root, never checked in; a linked git
worktree without its own reads its main checkout's, `local_list_path`), which adds the
source's own terms and switches public entries off for it; its `remote:<remote name> <regex>` line
is a term only of a push to that remote (--remote, which the pre-push hook and work_tickets.py
push pass), whose gate is every commit that remote does not hold yet, and a refusal there names
the commit whose tree it read. Output names the location and the
pattern label only, never the matched text. A tracked local list, and the retired machine-level
list (~/.se/private-terms.txt, SE_PRIVATE_TERMS), stop the check with their remedy.

The commit gates (a message file, the commits of a --range) also refuse tracker references,
attribution trailers (`Co-Authored-By:`, `Claude-Session:`) and any e-mail address, whatever the
address, in messages, from every author, naming the reference, trailer or line and the remedy; a
full check leaves old history to them. CI runs
the --range gate on every pull request, in the checked-out merge of its head into its base
(--rev HEAD), and on every push (.github/workflows/check.yml). A push's range (--push,
push_range) goes by branch. To the integration branch: the commits after its old tip, or where
that tip is unknown those no other branch holds, gated whole. To a work branch, where the
integration branch is the default branch and origin's ref for it exists: the commits after its old
tip, or all its commits where that tip is unknown, without those the integration branch holds,
which are not gated again; otherwise as to the integration branch. The commits of a --range must
also carry the project identity (se.toml [project] identity, unless the machine sets
public_identity), where one is set. Strict, where se.toml [integrate] landing is
"fast-forward" (landings are the integrator's own commits): a commit GitHub made is foreign like
any other. Otherwise, while GitHub squash-merges the landings, its web-flow identity passes as
committer, and on such a commit the author may be the GitHub noreply address of the account
owning origin on github.com (the squash merge of a pull request into main). A hit names the
identity found, redacted. A
`commit:<full sha> author|committer` entry in .public-check-allow allows the identity in that role
on that one commit, and a `commit:<full sha> message` entry the message hits of that one commit,
for history already published. A --range on a shallow clone that reaches beyond the fetched
history is refused, so the check never passes over commits it cannot see.

A built page, or a folder of them (--built), is checked as a source of its own: its files' paths
and raw text with the patterns tracked files get, and obs's data island (`<script
id="artifact-data">`, plain JSON or base64 gzip of it, the format obs's artifact_data.py owns),
decoded with the standard library and scanned key by key and string by string, each hit named by
its field path. It reads no history, applies no allow entry and records no verdict; an island that
does not decode is a setup error, never a pass.

Every verdict names the se commit that ran it. A checked repository that pins se (`[components.se]`
in its se.toml) is refused when this se is not at that `ref`, or when the version this se's
se.toml sets lies outside that `version` range, so a stale clone never gives another verdict
silently.

The allow list (.public-check-allow) is read from the source the files are read from: the commit
of --rev, whatever is checked out; the index with --staged; else the working tree. A source
without one has no entries.

An allow entry `<path> <label> sha256:<digest>` keys a public label's content hit by its text, so
it covers that hit on any line of its file: the digest is the first 16 hex digits of SHA-256 over
the UTF-8 bytes of the hit's whole match, as the check decodes the file, and only --digests prints
it. A local-term hit gets no digest, as a word list would reverse it, and no committed entry keys
one: the local list allows its own term by the term's line <n>, `allow:<path> local-term:<n>`,
covering that term's content hits in that file, and output names such an entry only by its line
there. A content hit no entry covers, in a file an unused `<path>:<line>` entry names, names that
entry, as its line may have moved.

Allow entries are reported by kind: used ones are counted in the verdict; an unused one is a hit
where the source has a local list, and without it a warning that it is unverifiable, as it may
cover a local-term hit the run cannot see. An unused digest entry is a hit with or without the
local list, unless that list switches its label off; an unused local entry is only a warning. With
the local list, a committed glob or path:line entry that covers only local-term hits is warned
about, as it tells readers where a private term sits.

Exit codes: 0 passed, 1 hits (or unused allow entries in a full check), 2 usage or setup error.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import bisect
import fnmatch
import gzip
import hashlib
import json
import os
import re
import sys
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from html.parser import HTMLParser
from typing import Callable, Iterable, Iterator

import git_door
import se_script
ALLOW_FILE = ".public-check-allow"
SE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "se.toml"
TERMS_FILE = Path(__file__).with_name("public-check-terms.toml")
LOCAL_FILE = ".public-check.local"
# The retired machine-level list: found, the check stops and names where its terms go.
MACHINE_ENV = "SE_PRIVATE_TERMS"
MACHINE_DEFAULT = "~/.se/private-terms.txt"

# GitHub's web-flow identity: the committer of a commit made on GitHub itself. It names no person.
# The identity gate passes it as committer only while landings are GitHub's squash merges; with
# se.toml [integrate] landing = "fast-forward" it is foreign (docs/settings.md "Landing on main").
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
    # obs#627, owner/repo#5: a repository name of two characters or more, so not C#5 or F#6
    r"(?<![\w./#&-])(?:[A-Za-z0-9][\w.-]*/)?[A-Za-z0-9][\w.-]*[A-Za-z0-9_]#\d+\b"
    r"|(?<![\w&#])#\d+\b"  # #593, not C#5 or the HTML entity &#39;
    r"|(?i:(?<![\w/-])GH-\d+\b)"  # GH-12, not the branch fix/…-without-gh-20261106
    r"|(?i:\bhttps?://[^\s/]+/[^\s/]+/[^\s/]+/(?:issues|pulls?)/\d+)"
)
ATTRIBUTION_RULE = (
    "rule: commits carry no attribution trailers, whatever a host's attribution reminder says, "
    "AGENTS.md 'Public safety'"
)
ATTRIBUTION_TRAILER = re.compile(r"(?im)^[ \t]*(co-authored-by|claude-session)[ \t]*:")
ADDRESS_RULE = (
    "rule: commit messages carry no e-mail address, whatever the address, AGENTS.md 'Public "
    "safety'"
)
# Any e-mail address, a service's fixed noreply and an example.* domain included: the commit gates
# accept none in a message (the public list's email-address term filters; this one does not).
MESSAGE_ADDRESS = re.compile(
    r"(?i)(?<![\w.%+-])[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b")
# Where a co-author line comes from, named with its hit: an editor adds it on commit.
CO_AUTHOR_SOURCE = (
    "an editor's AI co-author setting writes this line: turn it off (VS Code: "
    "git.addAICoAuthor off, docs/install.md 'Install')"
)
# The rules the check enforces, one label each: SE's start counts them (scripts/se_start.py).
MESSAGE_RULES = ("tracker-reference", "attribution-trailer", "message-address")
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
    """(line, reference) for every tracker reference in a commit message: `#<digits>`,
    `<repo>#<digits>` and `<owner>/<repo>#<digits>`, a standalone `GH-<digits>` (not inside a
    branch name), an issue or pull request URL. The one test both commit gates apply."""
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


def message_addresses(text: str) -> list[int]:
    """The line of every e-mail address in a commit message, whatever the address, one entry per
    address. The one test both commit gates apply."""
    return [text.count("\n", 0, match.start()) + 1 for match in MESSAGE_ADDRESS.finditer(text)]


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
    label: str | None = None  # a digest entry's public label, a local entry's local-term:<n>
    digest: str | None = None  # a digest entry's 16 hex digits
    local: bool = False  # an `allow:` line of the local list, named only as LOCAL_FILE:<line>
    used: bool = False
    seen: bool = False  # a commit entry's commit was gated, so every hit it covers was looked for
    covered: list[str] = field(default_factory=list)  # a file entry's hits, '<path> <label>'
    public: bool = False  # a file entry covers a public-label hit

    @property
    def form(self) -> str:
        """The entry's form as the header of the allow file writes it."""
        if self.commit is not None:
            return f"commit:<full sha> {self.role}"
        if self.local:
            return LOCAL_ALLOW_FORM
        if self.digest is not None:
            return DIGEST_FORM
        return "<path glob>" if self.glob is not None else "<path>:<line>"

    @property
    def where(self) -> str:
        """The entry's place: its list and line."""
        return f"{LOCAL_FILE if self.local else ALLOW_FILE}:{self.line}"

    def matches(self, path: str, line: int | None, label: str = "",
                digest: str | None = None) -> bool:
        """Whether the entry covers a hit of `label` in `path`: on `line`, None for its name;
        `digest` that of a public label's content hit."""
        if self.glob is not None:
            return fnmatch.fnmatchcase(path, self.glob)
        if self.path != path:
            return False
        if self.label is not None:  # a digest or local entry: content hits on any line
            return (line is not None and label == self.label
                    and (self.local or digest == self.digest))
        return line == self.path_line


COMMIT_ENTRY = re.compile(r"commit:(\S*)(?:\s+(\S+))?")
ROLES = ("author", "committer", "message")
COMMIT_FORM = "commit:<full sha> author|committer|message"
DIGEST_FORM = "<path> <label> sha256:<digest>"
DIGEST_PREFIX = "sha256:"
DIGEST_DIGITS = 16
LOCAL_ALLOW_FORM = "allow:<path> local-term:<n>"
LOCAL_TERM = re.compile(r"local-term(?::(\d+))?")
MOVE_TO_LOCAL = (f"move it to {LOCAL_FILE} as '{LOCAL_ALLOW_FORM}  # reason', <n> the term's line "
                 "there")


def digest(text: str) -> str:
    """A public label's hit keyed by its text: the first 16 hex digits of SHA-256 over the UTF-8
    bytes of its whole match. A local term gets none, as a word list would reverse it."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:DIGEST_DIGITS]


@dataclass
class Report:
    hits: list[Hit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    digests: list[str] = field(default_factory=list)  # with --digests, one per public content hit
    files: int = 0
    commits: int = 0
    allow_used: int = 0
    off: list[str] = field(default_factory=list)  # public labels the local list switches off


@dataclass
class LocalList:
    """A source's local list: its own terms, the public labels it switches off, and its allow
    entries for its own terms."""
    terms: list[Pattern] = field(default_factory=list)
    off: set[str] = field(default_factory=set)
    allow: list[AllowEntry] = field(default_factory=list)
    remotes: dict[int, str] = field(default_factory=dict)  # a `remote:` term's line: its remote


LOCAL_OFF = re.compile(r"off:(\S+)")
LOCAL_ALLOW = "allow:"
LOCAL_REMOTE = re.compile(r"remote:(\S*)\s*")
LOCAL_REMOTE_FORM = "remote:<remote name> <regex>"
LOCAL_FORMS = (f"'<regex>', '{LOCAL_REMOTE_FORM}', 'off:<public label>  # reason' or "
               f"'{LOCAL_ALLOW_FORM}  # reason'")
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


def local_list_path(root: Path) -> Path:
    """The local list of the source at ``root``: its own, or, in a linked git worktree that has
    none, its main checkout's, so a worktree is checked with the same private terms as the
    checkout it was made from rather than passing with only the public list. Only a linked
    worktree's git directory has a `commondir`; a submodule's has none and keeps its own."""
    own = root / LOCAL_FILE
    dot_git = root / ".git"
    if own.is_file() or not dot_git.is_file():
        return own
    text = dot_git.read_text(encoding="utf-8").strip()
    if not text.startswith("gitdir:"):
        return own
    gitdir = (root / text[len("gitdir:"):].strip()).resolve()
    commondir = gitdir / "commondir"
    if not commondir.is_file():  # a submodule: a source of its own, not a linked worktree
        return own
    main = (gitdir / commondir.read_text(encoding="utf-8").strip()).resolve().parent / LOCAL_FILE
    return main if main.is_file() else own


def load_local(root: Path, remote: str | None = None) -> LocalList | None:
    """The local list at the source's root, or None where it has none. Hits name only its line
    number, never the term. A `remote:<remote name> <regex>` line is a term only of a push to
    that remote (`remote`, None where the check names no destination), and so is the
    `allow:` line of its term; every other term applies to every check."""
    path = local_list_path(root)
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
        if text.startswith(LOCAL_ALLOW):
            local.allow.append(local_allow(number, text[len(LOCAL_ALLOW):], public))
            continue
        scoped = LOCAL_REMOTE.match(text)
        if scoped:
            text = text[scoped.end():]
            if not scoped.group(1) or not text:
                raise SetupError(f"{LOCAL_FILE}:{number}: write '{LOCAL_REMOTE_FORM}', the "
                                 "remote as git names it")
            local.remotes[number] = scoped.group(1)
        try:
            regex = re.compile(text, re.IGNORECASE)
        except re.error as error:
            raise SetupError(
                f"{LOCAL_FILE}:{number} is not a valid regex ({error.msg})"
            ) from None
        local.terms.append(Pattern(f"local-term:{number}", regex))
    terms = {pattern.label for pattern in local.terms}
    for entry in local.allow:
        if entry.label not in terms:
            raise SetupError(f"{LOCAL_FILE}:{entry.line}: {entry.label.split(':')[1]} is no term's "
                             f"line; write '{LOCAL_ALLOW_FORM}  # reason', <n> the line of one of "
                             "this list's terms")
    other = {f"local-term:{number}" for number, name in local.remotes.items() if name != remote}
    local.terms = [pattern for pattern in local.terms if pattern.label not in other]
    local.allow = [entry for entry in local.allow if entry.label not in other]
    return local


def unknown_remotes(root: Path, local: LocalList) -> list[str]:
    """A warning for each `remote:` line whose remote this checkout lacks, by line only: its term
    stops no push, so a misspelt name would let it through to the remote meant."""
    names = set(git(root, "remote").decode().split())
    return [f"{LOCAL_FILE}:{number}: no remote of this checkout is named {name!r}, so its term "
            "applies to no push" for number, name in sorted(local.remotes.items())
            if name not in names]


def local_allow(number: int, body: str, public: set[str]) -> AllowEntry:
    """The local list's `allow:<path> local-term:<n>  # reason` line `number`, past `allow:`. Its
    term's line is checked once every term is read."""
    entry, _, reason = body.partition("#")
    words = entry.split()
    committed = (f"{LOCAL_FILE}:{number}: a public label is allowed by the committed form "
                 f"'{DIGEST_FORM}  # reason' in {ALLOW_FILE}, never in the local list")
    if words and (words[-1].startswith(DIGEST_PREFIX) or words[-1] in public
                  or (len(words) > 1 and words[-2] in public)):
        raise SetupError(committed)
    form = f"{LOCAL_FILE}:{number}: write '{LOCAL_ALLOW_FORM}  # reason'"
    path, _, label = entry.strip().rpartition(" ")
    term = LOCAL_TERM.fullmatch(label)
    if not path.strip() or term is None or term.group(1) is None or not reason.strip():
        raise SetupError(form)
    return AllowEntry(number, path=path.strip(), label=label, local=True)


def digest_entry(number: int, entry: str) -> AllowEntry:
    """The committed entry `<path> <label> sha256:<digest>` of line `number`, its last word
    `sha256:…`."""
    form = (f"{ALLOW_FILE}:{number}: write '{DIGEST_FORM}  # reason', <digest> the first "
            f"{DIGEST_DIGITS} lowercase hex digits --digests prints")
    words = entry.rsplit(None, 2)
    if len(words) < 3 or not re.fullmatch(rf"[0-9a-f]{{{DIGEST_DIGITS}}}",
                                          words[2][len(DIGEST_PREFIX):]):
        raise SetupError(form)
    path, label, value = words
    if LOCAL_TERM.fullmatch(label):
        raise SetupError(f"{ALLOW_FILE}:{number}: no committed entry keys a local term: "
                         f"{MOVE_TO_LOCAL}")
    public = sorted({pattern.label for pattern in GENERIC_PATTERNS})
    if label not in public:
        raise SetupError(f"{ALLOW_FILE}:{number}: no public entry is labelled {label!r}; the "
                         f"labels are {', '.join(public)}")
    return AllowEntry(number, path=path, label=label, digest=value[len(DIGEST_PREFIX):])


def load_allow(root: Path, files: list[tuple[str, bytes]] | None = None) -> list[AllowEntry]:
    """The allow list of the source the files are read from: its blob among `files` (a commit's
    tree or the index, object_files' answer), none where they hold none; without `files`, the
    working tree's file."""
    if files is not None:
        blob = next((data for path, data in files if path == ALLOW_FILE), None)
        text = None if blob is None else blob.decode("utf-8")
    else:
        path = root / ALLOW_FILE
        text = path.read_text(encoding="utf-8") if path.is_file() else None
    if text is None:
        return []
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        entry, _, reason = text.partition("#")
        entry = entry.strip()
        if not entry or not reason.strip():
            raise SetupError(f"{ALLOW_FILE}:{number}: write '<path glob or file:line>  # reason', "
                             f"'{DIGEST_FORM}  # reason' or '{COMMIT_FORM}  # reason'")
        if entry.split()[-1].startswith(DIGEST_PREFIX):
            entries.append(digest_entry(number, entry))
            continue
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
    return [(line, column, label) for line, column, label, _ in matches(text, patterns)]


def matches(text: str, patterns: Iterable[Pattern]) -> list[tuple[int, int, str, str]]:
    """Return sorted (line, column, label, matched text) for every accepted match, one per place
    and label."""
    line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
    found: dict[tuple[int, int, str], str] = {}
    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            if pattern.accept(match):
                line = bisect.bisect_right(line_starts, match.start())
                place = (line, match.start() - line_starts[line - 1] + 1, pattern.label)
                found.setdefault(place, match.group())
    return sorted((*place, matched) for place, matched in found.items())


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
    result = git_door.run(*args, root=root, stdin=stdin, binary=True)
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


def is_local_term(label: str) -> bool:
    return label.startswith("local-term:")


def scan_files(files: Iterable[tuple[str, bytes]], patterns: list[Pattern],
               allow: list[AllowEntry], report: Report, digests: bool = False) -> None:
    """Hits in tracked files, without those an entry of `allow` covers. With `digests`, each
    public-label content hit's digest is printed (report.digests), and an uncovered one's hit
    ends with it; a local-term hit never gets one."""
    def covering(path: str, shown: str, line: int | None, label: str,
                 value: str | None) -> list[AllowEntry]:
        found = [entry for entry in allow if entry.matches(path, line, label, value)]
        for entry in found:
            entry.used = True
            if entry.label is None:  # a glob or path:line entry
                entry.public = entry.public or not is_local_term(label)
                entry.covered.append(f"{shown} {label}")
        return found

    for path, data in files:
        report.files += 1
        shown = redact(path, patterns)
        for _, _, label in find(path, patterns):
            if not covering(path, shown, None, label, None):
                report.hits.append(Hit(f"{shown} (file name)", label))
        binary = " (binary)" if is_binary(data) else ""
        uncovered = []
        for line, column, label, text in matches(decode(data), patterns):
            value = None if is_local_term(label) else digest(text)
            place = f"{shown}:{line}:{column}"
            found = covering(path, shown, line, label, value)
            if digests and value is not None:
                named = ", ".join(entry.where for entry in found)
                report.digests.append(f"digest {place} {label} sha256:{value}"
                                      + (f" ({named})" if named else ""))
            if not found:
                uncovered.append((Hit(f"{place}{binary}", label), value))
        moved = [entry for entry in allow if entry.path == path and entry.path_line is not None
                 and not entry.used]
        for hit, value in uncovered:
            hit.detail = moved_entries(moved, shown, hit.label)
            if digests and value is not None:
                hit.detail += f" sha256:{value}"
            report.hits.append(hit)


def moved_entries(moved: list[AllowEntry], shown: str, label: str) -> str:
    """The end of a content hit no entry covers, in a file `moved` path:line entries name and
    cover no hit of: each names itself, then how to key the hit by its text."""
    if not moved:
        return ""
    named = "".join(f"; {entry.where} names {shown}:{entry.path_line} and covers no hit"
                    for entry in moved)
    if is_local_term(label):
        key = f"key it in {LOCAL_FILE} by its term's line ('{LOCAL_ALLOW_FORM}  # reason')"
    else:
        key = f"key it by its text ('{DIGEST_FORM}', which --digests prints)"
    return f"{named}: if it was for this one, its line moved; {key}"


# obs's data island, as obs's artifact_data.py finds it: the first script element whose opening tag
# starts `<script id="artifact-data"`, its body up to the first closing tag. Found as two searches,
# as obs does, not one pattern with a lazy body over a megabyte page.
ISLAND_OPENING = re.compile(r'<script id="artifact-data"[^>]*>')
ISLAND_CLOSING = "</script>"
ISLAND = "artifact-data"


class _Attributes(HTMLParser):
    """The attributes of one opening tag, as HTML reads them."""

    def __init__(self) -> None:
        super().__init__()
        self.attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.attrs = dict(attrs)


def island_text(where: str, text: str) -> str | None:
    """The JSON text of the page's data island, None where it has none; one that is neither plain
    JSON nor base64 gzip of UTF-8 JSON is a setup error naming the file and the reason."""
    opening = ISLAND_OPENING.search(text)
    if opening is None:
        return None
    end = text.find(ISLAND_CLOSING, opening.end())
    if end < 0:
        raise SetupError(f"{where}: its {ISLAND} island has no closing </script>")
    body = text[opening.end():end]
    parser = _Attributes()
    parser.feed(opening.group())
    kind, encoding = parser.attrs.get("type"), parser.attrs.get("data-encoding")
    if encoding == "gzip":
        if kind != "application/octet-stream":
            raise SetupError(f"{where}: its {ISLAND} island is gzip of type {kind!r}, not "
                             "application/octet-stream")
        try:
            return gzip.decompress(base64.b64decode(re.sub(r"\s", "", body), validate=True)
                                   ).decode("utf-8")
        except (binascii.Error, ValueError, OSError, EOFError, zlib.error) as error:
            raise SetupError(f"{where}: its {ISLAND} island is no base64 gzip of UTF-8 text "
                             f"({error})") from error
    if encoding is None and kind == "application/json":
        return body
    raise SetupError(f"{where}: its {ISLAND} island has data-encoding {encoding!r} and type "
                     f"{kind!r}, neither gzip nor plain JSON")


def island_strings(value: object, where: str) -> Iterator[tuple[str, str]]:
    """Every key and string value of the island with its field path, named as obs's exposure.py
    names them: `artifact-data notes[0].html`, a key's path followed by ` (the key)`."""
    if isinstance(value, str):
        yield where.rstrip(), value
    elif isinstance(value, dict):
        for key, item in value.items():
            path = f"{where}{'' if where.endswith(' ') else '.'}{key}"
            yield f"{path} (the key)", str(key)
            yield from island_strings(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from island_strings(item, f"{where.rstrip()}[{index}]")


def built_files(path: Path) -> list[tuple[str, bytes]]:
    """The built file at `path`, named by its file name, or every regular file under the folder
    `path`, recursively, named and sorted by their paths relative to it."""
    if path.is_file():
        return [(path.name, path.read_bytes())]
    if not path.is_dir():
        raise SetupError(f"--built {path}: no such file or folder")
    found = sorted((item.relative_to(path).as_posix(), item) for item in path.rglob("*")
                   if item.is_file())
    if not found:
        raise SetupError(f"--built {path}: the folder holds no file, so nothing would be checked")
    return [(name, item.read_bytes()) for name, item in found]


def scan_built(files: Iterable[tuple[str, bytes]], patterns: list[Pattern], report: Report) -> None:
    """Hits in built files: each path and raw line as a tracked file's, then its decoded island."""
    for path, data in files:
        report.files += 1
        shown = f"built:{redact(path, patterns)}"
        for _, _, label in find(path, patterns):
            report.hits.append(Hit(f"{shown} (file name)", label))
        binary = " (binary)" if is_binary(data) else ""
        text = decode(data)
        for line, column, label in find(text, patterns):
            report.hits.append(Hit(f"{shown}:{line}:{column}{binary}", label))
        island = island_text(shown, text)
        if island is None:
            continue
        try:
            value = json.loads(island)
        except json.JSONDecodeError as error:
            raise SetupError(f"{shown}: its {ISLAND} island is not JSON ({error})") from error
        for where, string in island_strings(value, f"{ISLAND} "):
            for label in sorted({label for _, _, label in find(string, patterns)}):
                report.hits.append(Hit(f"{shown} {redact(where, patterns)}", label))


def scan_message(where: str, message: str, patterns: list[Pattern], report: Report,
                 remedy: str | None = None) -> None:
    """Hits in a commit message; with a remedy, tracker references, attribution trailers and
    e-mail addresses too (the commit gates)."""
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
    for line in message_addresses(message):  # the address may name a person: never shown
        report.hits.append(Hit(f"{where} message:{line}", "message-address",
                               f" ({ADDRESS_RULE}); {remedy}"))


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


def strict_identity(root: Path) -> bool:
    """Whether the gate refuses GitHub's own commits too: se.toml [integrate] landing is
    "fast-forward", so every landing is the integrator's commit (work_tickets.landing_mode)."""
    work_tickets = sibling("work_tickets")
    try:
        return work_tickets.landing_mode(root) == work_tickets.FAST_FORWARD
    except work_tickets.QueueError as error:
        raise SetupError(str(error)) from error


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
                          patterns: list[Pattern], report: Report, strict: bool) -> None:
    if identity != expected and (strict or (role, identity) != ("committer", WEB_FLOW)):
        shown = redact(identity, patterns)  # a foreign identity may name a person
        report.hits.append(Hit(f"{where} {role}", "foreign-identity",
                               f" '{shown}' is not the project identity '{expected}'; "
                               f"{REIDENTIFY_BEFORE_PUSH}"))


def scan_history(root: Path, revisions: list[str], patterns: list[Pattern], report: Report,
                 gate: bool, allow: list[AllowEntry]) -> None:
    """Hits in the identities and messages of `revisions`; a gate (commits not yet pushed) also
    refuses tracker references, attribution trailers, e-mail addresses in messages and identities
    other than the project identity (GitHub's own too where the identity is strict). A commit entry of
    `allow` drops the hits of its role (an identity, or the message) on its commit; in a gate,
    where every hit it may cover is looked for, one that drops none is reported unused."""
    expected = project_identity(root) if gate else None
    strict = expected is not None and strict_identity(root)
    owner = repository_owner(root) if expected is not None and not strict else None
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
        if expected is not None and (strict or not made_on_github_by_owner(author, committer, owner)):
            scan_project_identity(where, "author", author, expected, patterns, report, strict)
        if expected is not None:
            scan_project_identity(where, "committer", committer, expected, patterns, report, strict)
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


def has_commit(root: Path, rev: str) -> bool:
    """Whether `rev` names a commit this clone holds; an empty or all-zeros tip names none."""
    if not rev or set(rev) == {"0"}:
        return False
    return git_door.run("cat-file", "-e", f"{rev}^{{commit}}", root=root).returncode == 0


def remote_refs(root: Path) -> list[str]:
    return git(root, "for-each-ref", "--format=%(refname)", "refs/remotes/origin").decode().split()


def push_range(root: Path, before: str, after: str, branch: str, default_branch: str) -> str:
    """The revisions a push of `after` to `branch` gates, its old tip `before` (unknown where it
    is empty, all zeros or no commit here), by branch. To the integration branch (se.toml
    [project] integration_branch): the commits after its old tip, or where that tip is unknown
    those no other branch of origin holds, gated whole. To a work branch, where the integration
    branch is the default branch (`default_branch`) and origin's ref for it
    (refs/remotes/origin/<integration branch>) exists: the commits after its old tip, or all its
    commits where that tip is unknown, without those the integration branch holds, which were
    gated where they reached it; otherwise as to the integration branch."""
    try:
        integration = sibling("work_tickets").integration_branch(root)
    except sibling("work_tickets").QueueError as error:
        raise SetupError(str(error)) from error
    held = f"refs/remotes/origin/{integration}"
    refs = remote_refs(root)
    narrow = branch != integration and integration == default_branch and held in refs
    if has_commit(root, before):
        return f"{before}..{after}" + (f" --not {held}" if narrow else "")
    if narrow:
        return f"{after} --not {held}"
    others = [ref for ref in refs if ref not in (f"refs/remotes/origin/{branch}",
                                                 "refs/remotes/origin/HEAD")]
    return " ".join([after, "--not", *others])


def scan_message_file(root: Path, path: Path, patterns: list[Pattern], report: Report) -> None:
    report.commits += 1
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scan_message("commit", "\n".join("" if line.startswith("#") else line for line in lines),
                 patterns, report, REWORD_BEFORE_COMMIT)
    for role, variable in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        identity = git(root, "var", variable).decode("utf-8", "replace")
        scan_identity("commit", role, identity.rsplit(">", 1)[0] + ">", patterns, report)


def has_head(root: Path) -> bool:
    return git_door.run("rev-parse", "--verify", "--quiet", "HEAD", root=root).returncode == 0


def se_commit() -> str | None:
    """The commit of the se checkout this script runs from, or None outside a git checkout."""
    result = git_door.run("rev-parse", "HEAD", root=SE_ROOT)
    return result.stdout.strip().lower() if result.returncode == 0 else None


def se_pin(root: Path) -> dict | None:
    """`[components.se]` of the checked repository's se.toml, or None where it pins none."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        return None
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise SetupError(f"cannot read {MANIFEST} of the checked repository: {error}") from error
    modules = data.get("components")
    module = modules.get("se") if isinstance(modules, dict) else None
    if module is None:
        return None
    if not isinstance(module, dict) or not isinstance(module.get("ref", module.get("version")), str):
        raise SetupError(f"[components.se] in {MANIFEST} has no ref; pin a full commit SHA or a version range")
    return module


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded under its own name."""
    import importlib.util
    qualified = f"public_check_{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
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
    the integration branch needs; one of `--built` records none, nor one for a push to another
    remote than origin, as its `remote:` terms are not origin's."""
    if not args.rev or args.no_history or args.built is not None:
        return
    if args.remote not in (None, "origin"):
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
    parser = se_script.parser(
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
    source.add_argument("--built", type=Path,
                        help="scan a built page, or every file of a folder of them, with obs's "
                             "data island decoded, instead of the repository; no history, no "
                             "allow entries, no verdict recorded")
    parser.add_argument("--range", dest="revisions",
                        help="git log revisions whose messages and identities are checked, split "
                             "on spaces (for example 'A..B' or 'B --not --remotes'); default: "
                             "HEAD. Given, it gates commits: their messages must carry no tracker "
                             "references or attribution trailers either")
    history = parser.add_mutually_exclusive_group()
    history.add_argument("--history", dest="history",
                         help="git log revisions whose messages and identities are checked as "
                              "in a full check, without the gate of --range, split on spaces "
                              "(for example 'HEAD --not A'); default: HEAD")
    history.add_argument("--no-history", action="store_true",
                         help="skip commit messages and identities")
    parser.add_argument("--push", metavar="BEFORE",
                        help="gate the commits a push of --rev to --branch brings, BEFORE its "
                             "old tip (empty or all zeros where unknown); a work branch's range "
                             "leaves out what the integration branch holds (push_range)")
    parser.add_argument("--digests", action="store_true",
                        help="print the digest of every public-label hit in a tracked file, for "
                             f"a '{DIGEST_FORM}' entry in {ALLOW_FILE}; never of a local term")
    parser.add_argument("--remote", metavar="NAME",
                        help="the remote a push goes to: the local list's 'remote:NAME <regex>' "
                             "lines apply too, and without --range or --push the gate is the "
                             "commits of --rev that remote does not hold yet "
                             "('<rev> --not --remotes=NAME')")
    parser.add_argument("--branch", help="with --push: the branch pushed")
    parser.add_argument("--default-branch", help="with --push: the repository's default branch")
    return parser.parse_args(argv)


def check(args: argparse.Namespace, commit: str | None) -> Report:
    if args.built is not None:
        for option, value in (("--range", args.revisions), ("--history", args.history)):
            if value:
                raise SetupError(f"--built and {option} exclude each other: a built page has no "
                                 "commits")
    check_push_options(args)
    root = Path(git(Path(args.repo).resolve(), "rev-parse", "--show-toplevel").decode().strip())
    check_se_version(root, commit)
    if args.push is not None:
        args.revisions = push_range(root, args.push, args.rev, args.branch, args.default_branch)
        print(f"public-check: gating {args.revisions}, the commits pushed to {args.branch}")
    elif args.remote is not None and not args.revisions:
        args.revisions = f"{args.rev} --not --remotes={args.remote}"
        print(f"public-check: gating {args.revisions}, the commits {args.remote} does not hold yet")
    check_machine_list()
    check_untracked(root, args.rev)
    report = Report()
    local = load_local(root, args.remote)
    has_local = local is not None
    if local is None:
        local = LocalList()
        report.warnings.append(f"no local list ({LOCAL_FILE}); only the public list was checked")
    else:
        report.off = sorted(local.off)
        report.warnings += unknown_remotes(root, local)
    patterns = [p for p in GENERIC_PATTERNS if p.label not in local.off] + local.terms
    if args.message_file is not None:
        scan_message_file(root, args.message_file, patterns, report)
        return report
    if args.built is not None:
        scan_built(built_files(args.built.resolve()), patterns, report)
        return report
    if args.staged or args.rev:
        files: Iterable[tuple[str, bytes]] = object_files(root, args.staged, args.rev)
        allow = load_allow(root, files)
    else:
        allow = load_allow(root)
        files = worktree_files(root)
    allow += local.allow
    found = len(report.hits)
    scan_files(files, patterns, allow, report, args.digests)
    if args.remote is not None:  # a push's refusal names the commit whose tree it read
        tree = git(root, "rev-parse", "--verify", f"{args.rev}^{{commit}}").decode().strip()
        for hit in report.hits[found:]:
            hit.location = f"commit {tree[:12]} {hit.location}"
    if args.revisions and args.history:
        raise SetupError("--range and --history exclude each other: a gate or a full check")
    revisions = args.revisions or args.history or ("" if args.staged else args.rev or "HEAD")
    if not args.no_history and revisions and (args.revisions or has_head(root)):
        if args.revisions:
            check_fetched(root, args.revisions)
        scan_history(root, revisions.split(), patterns, report, gate=bool(args.revisions),
                     allow=allow)
    report_unused(allow, has_local, local.off, report)
    return report


def check_push_options(args: argparse.Namespace) -> None:
    """--push needs --rev, --branch and --default-branch, and takes no other history; --remote
    needs --rev, the commit pushed."""
    if args.remote is not None and not args.rev:
        raise SetupError("--remote needs --rev: it names the commit pushed to that remote")
    if args.push is None:
        for option, value in (("--branch", args.branch), ("--default-branch", args.default_branch)):
            if value is not None:
                raise SetupError(f"{option} needs --push: it names the branch a push gates")
        return
    for option, value in (("--rev", args.rev), ("--branch", args.branch),
                          ("--default-branch", args.default_branch)):
        if not value:
            raise SetupError(f"--push needs {option}: a push's range is computed from it")
    for option, value in (("--range", args.revisions), ("--history", args.history),
                          ("--no-history", args.no_history)):
        if value:
            raise SetupError(f"--push and {option} exclude each other: --push gates the commits "
                             "the push brings")


def report_unused(allow: list[AllowEntry], full: bool, off: set[str], report: Report) -> None:
    """Each entry this run could judge, by kind: used (counted in the verdict); unused, a hit
    where the check is full; unverifiable, a warning without the local list, as the entry may
    cover a local-term hit this run cannot see. A commit entry is judged only where its
    commit was gated, as a gate's hit is not seen by every check. A digest entry covers no local
    term, so unused it is a hit with or without the local list, unless that list switches its
    label off; an unused local entry is only warned about, as one clone's list serves every
    branch it checks. With the local list, a committed file entry that covers only local-term
    hits is warned about, as it tells readers where a private term sits."""
    for entry in allow:
        if entry.used:
            report.allow_used += 1
            if full and entry.covered and not entry.public:
                report.warnings.append(
                    f"allow entry {entry.where} covers only local-term hits, so it tells readers "
                    f"where a private term sits: move it to {LOCAL_FILE} as "
                    f"'{LOCAL_ALLOW_FORM}  # reason' lines, <n> the term's line there: "
                    f"{', '.join(dict.fromkeys(entry.covered))}")
        elif entry.commit is not None and not entry.seen:
            continue
        elif entry.local:
            report.warnings.append(f"allow entry {entry.where} covers no hit in this tree")
        elif entry.digest is not None and entry.label in off:
            report.warnings.append(f"allow entry {entry.where} ('{entry.form}' entry) is "
                                   f"unverifiable: the local list switches {entry.label} off")
        elif full or entry.digest is not None:
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
    for line in report.digests:
        print(f"public-check: {line}")
    for hit in report.hits:
        print(hit)
    used = f"{report.allow_used} allow entries used, " if report.allow_used else ""
    off = f"public entries off locally: {', '.join(report.off)}, " if report.off else ""
    counted = (f"{report.files} built files" if args.built is not None
               else f"{report.files} files, {report.commits} commits")
    scope = f"{counted}, {used}{off}{version}"
    if report.hits:
        remedy = "fix each as its line says"
        if args.built is not None:
            remedy = "remove them from what the page is built from; no allow entry applies to it"
        elif any(hit.label not in OWN_REMEDY for hit in report.hits):
            remedy = f"remove them or add a reasoned entry to {ALLOW_FILE}"
        print(f"public-check: FAILED with {len(report.hits)} hit(s) ({scope}); {remedy}")
        return 1
    print(f"public-check: passed ({scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
