#!/usr/bin/env python3
"""Rewrite a fresh clone's history once so the public check's commit gates pass over all of it.

Every local branch and tag of the clone is rewritten in place, through `git fast-export`, a filter
and `git fast-import` (standard library only):

- commit messages lose their attribution trailers (`Co-Authored-By:`, `Claude-Session:`, any case)
  and their tracker references, with the same detectors as the commit gates
  (scripts/public_check.py, AGENTS.md "Public safety");
- an author or committer other than the project identity (se.toml `[project] identity`, or the
  machine's `public_identity`) becomes it; GitHub's web-flow committer passes, as in the gates;
- every tag moves to its commit's rewritten commit; trees and dates stay as they are, so each
  rewritten branch carries exactly its old tree.

It writes the commit map (`<old> <new>` per line) to `<git dir>/rewrite-commit-map` and prints the
counts, each branch's old and new head, the tags moved and the `.public-check-allow` commit
entries left stale at each branch tip (a commit entry names a sha the rewrite replaces).

Run it on a fresh full clone only: it refuses a shallow clone or one with local changes. It
pushes nothing; pushing the result is the switch runbook's step. Exit code 0 rewritten, 2 setup
error.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import git_door

def _public_check():
    """scripts/public_check.py beside this script, whose detectors the commit gates apply."""
    name = "rewrite_history_public_check"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("public_check.py"))
    module = sys.modules[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


public_check = _public_check()

MAP_FILE = "rewrite-commit-map"
IDENTITY_LINE = re.compile(rb"^(author|committer) (.*?) ?<([^>]*)> (\S+ \S+)\n$")
REFERENCE = f"(?:{public_check.TRACKER_REFERENCE.pattern})"
# A reference and the punctuation that only existed for it: "(#5)", "#5, ", ", #5", then "#5".
REFERENCE_FORMS = (
    re.compile(rf"[ \t]*\([ \t]*{REFERENCE}[ \t]*\)"),
    re.compile(rf"{REFERENCE}[ \t]*,[ \t]*"),
    re.compile(rf"[ \t]*,[ \t]*{REFERENCE}"),
    re.compile(rf"[ \t]*{REFERENCE}"),
)


class SetupError(Exception):
    """A usage or repository problem; exit code 2."""


@dataclass
class Counts:
    commits: int = 0
    trailers: int = 0  # trailer lines dropped
    trailer_commits: int = 0
    references: int = 0  # tracker references removed
    reference_commits: int = 0
    identity_commits: int = 0  # commits with an author or committer set to the project identity
    originals: dict[str, str] = field(default_factory=dict)  # mark -> original commit


def clean_message(message: str) -> tuple[str, int, int]:
    """`message` without attribution trailers and tracker references, with the number of each
    removed; an untouched message comes back as it was."""
    trailers = len(public_check.attribution_trailers(message))
    references = len(public_check.tracker_references(message))
    if not trailers and not references:
        return message, 0, 0
    lines = [line for line in message.split("\n")
             if not public_check.ATTRIBUTION_TRAILER.match(line)]
    cleaned = []
    for line in lines:
        if public_check.tracker_references(line):
            for form in REFERENCE_FORMS:
                line = form.sub("", line)
            line = line.rstrip()
        cleaned.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip("\n")
    return text + "\n", trailers, references


def fix_identity(line: bytes, identity: tuple[str, str]) -> bytes:
    """An `author` or `committer` line of the stream with the project identity where it differs."""
    match = IDENTITY_LINE.match(line)
    if match is None:
        raise SetupError(f"cannot read the identity line {line!r} of git fast-export")
    role, name, email, when = match.groups()
    found = f"{name.decode('utf-8', 'replace')} <{email.decode('utf-8', 'replace')}>"
    wanted = f"{identity[0]} <{identity[1]}>"
    if found == wanted or (role == b"committer" and found == public_check.WEB_FLOW):
        return line
    return b"%s %s <%s> %s\n" % (role, identity[0].encode(), identity[1].encode(), when)


def filter_stream(source: BinaryIO, sink: BinaryIO, identity: tuple[str, str],
                  counts: Counts) -> None:
    """Copy a `git fast-export` stream to `sink`, cleaning each commit's message and identities."""
    header: list[bytes] | None = None  # the lines of a commit before its message
    mark = original = None
    while line := source.readline():
        if line.startswith(b"commit "):
            header, mark, original = [line], None, None
            counts.commits += 1
            continue
        if header is None:
            if line.startswith(b"data "):
                sink.write(line)
                sink.write(source.read(int(line[5:])))
            else:
                sink.write(line)
            continue
        if line.startswith(b"data "):
            raw = source.read(int(line[5:]))
            text, trailers, references = clean_message(raw.decode("utf-8", "surrogateescape"))
            message = text.encode("utf-8", "surrogateescape") if trailers or references else raw
            counts.trailers += trailers
            counts.trailer_commits += bool(trailers)
            counts.references += references
            counts.reference_commits += bool(references)
            fixed = [fix_identity(item, identity) if item.startswith((b"author ", b"committer "))
                     else item for item in header]
            counts.identity_commits += fixed != header
            sink.writelines(fixed)
            sink.write(b"data %d\n" % len(message))
            sink.write(message)
            if mark is not None and original is not None:
                counts.originals[mark] = original
            header = None
            continue
        if line.startswith(b"mark "):
            mark = line[5:].strip().decode()
        elif line.startswith(b"original-oid "):
            original = line[13:].strip().decode()
        header.append(line)


def git(repo: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=repo)
    if result.returncode != 0:
        raise SetupError(f"git {' '.join(arguments)} failed in {repo}: "
                         f"{(result.stderr or result.stdout).strip()}")
    return result.stdout


def refs(repo: Path) -> dict[str, str]:
    """Each local branch and tag with the commit it names (an annotated tag peeled)."""
    output = git(repo, "for-each-ref", "--format=%(refname) %(objectname) %(*objectname)",
                 "refs/heads", "refs/tags")
    named = {}
    for line in output.splitlines():
        name, target, *peeled = line.split()
        named[name] = peeled[0] if peeled else target
    return named


def check_fresh(repo: Path) -> None:
    if git(repo, "rev-parse", "--is-bare-repository").strip() == "true":
        raise SetupError(f"{repo} is a bare repository; rewrite a fresh clone with a working tree")
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise SetupError(f"{repo} is a shallow clone, whose history the rewrite cannot see; run "
                         f"git -C {repo} fetch --unshallow --tags, or clone it again in full")
    if git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise SetupError(f"{repo} has local changes; rewrite a fresh clone")


def project_identity(repo: Path, given: str | None) -> tuple[str, str]:
    text = given
    if text is None:
        try:
            text = public_check.project_identity(repo)
        except public_check.SetupError as error:
            raise SetupError(str(error)) from error
    match = re.fullmatch(r"(.+?) <([^<>]+)>", text or "")
    if match is None:
        raise SetupError(f"no project identity for {repo}: set se.toml [project] identity "
                         "(\"Name <email>\") or pass --identity")
    return match[1], match[2]


def stale_allow_entries(repo: Path, branch: str) -> list[str]:
    """The `.public-check-allow` commit entries at `branch`'s tip, as `<line>: <entry>`."""
    shown = git_door.run("show", f"{branch}:.public-check-allow", root=repo)
    if shown.returncode != 0:
        return []
    return [f"{number}: {line.split('#', 1)[0].strip()}"
            for number, line in enumerate(shown.stdout.splitlines(), 1)
            if line.startswith("commit:")]


def fast_export_options(repo: Path) -> list[str]:
    options = ["--branches", "--tags", "--signed-tags=strip", "--tag-of-filtered-object=rewrite",
               "--reencode=yes", "--show-original-ids", "--mark-tags"]
    usage = git_door.run("fast-export", "-h", root=repo)
    if "--signed-commits" in usage.stdout + usage.stderr:
        options.append("--signed-commits=strip")  # a rewritten commit's signature is void anyway
    return options


def rewrite(repo: Path, identity: tuple[str, str]) -> tuple[Counts, dict[str, str], dict, dict]:
    """Rewrite every local branch and tag of `repo`; (counts, commit map, refs before, after)."""
    before = refs(repo)
    if not before:
        raise SetupError(f"{repo} has no branch or tag to rewrite")
    counts = Counts()
    with tempfile.TemporaryDirectory() as scratch:
        marks, errors = Path(scratch) / "marks", Path(scratch) / "errors"
        with errors.open("wb") as log:
            exporter = git_door.popen("fast-export", *fast_export_options(repo), root=repo,
                                      stdout=subprocess.PIPE, stderr=log)
            importer = git_door.popen("fast-import", "--force", "--quiet",
                                      f"--export-marks={marks}", root=repo,
                                      stdin=subprocess.PIPE, stderr=log)
            try:
                filter_stream(exporter.stdout, importer.stdin, identity, counts)
            finally:
                importer.stdin.close()
            exported, imported = exporter.wait(), importer.wait()
        if exported or imported:
            detail = errors.read_text(encoding="utf-8", errors="replace").strip()
            raise SetupError(f"the rewrite of {repo} failed: {detail}")
        new = dict(line.split() for line in marks.read_text().splitlines() if line.strip())
    mapping = {old: new[mark] for mark, old in counts.originals.items()}
    after = refs(repo)
    if git(repo, "symbolic-ref", "-q", "HEAD").strip():
        git(repo, "reset", "-q", "--hard")  # the checked-out branch moved under its index
    for name, old in before.items():
        if after.get(name) != mapping.get(old):
            raise SetupError(f"{name} names {after.get(name)} after the rewrite, not the rewrite "
                             f"of {old}")
        if name.startswith("refs/heads/") and \
                git(repo, "rev-parse", f"{old}^{{tree}}") != git(repo, "rev-parse", f"{name}^{{tree}}"):
            raise SetupError(f"{name} carries another tree after the rewrite")
    map_file = Path(git(repo, "rev-parse", "--absolute-git-dir").strip()) / MAP_FILE
    map_file.write_text("".join(f"{old} {mapping[old]}\n" for old in sorted(mapping)),
                        encoding="utf-8")
    return counts, mapping, before, after


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--repo", type=Path, required=True,
                        help="the fresh full clone to rewrite in place")
    parser.add_argument("--identity", help="'Name <email>'; default: the project identity "
                                           "(se.toml [project] identity, or public_identity)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        check_fresh(repo)
        identity = project_identity(repo, args.identity)
        counts, mapping, before, after = rewrite(repo, identity)
    except SetupError as error:
        print(f"rewrite-history: {error}", file=sys.stderr)
        return 2
    changed = sum(old != new for old, new in mapping.items())
    print(f"rewrite-history: {counts.commits} commits rewritten, {changed} with a new id; "
          f"{counts.trailers} trailer lines dropped from {counts.trailer_commits} commits, "
          f"{counts.references} tracker references from {counts.reference_commits}, the identity "
          f"'{identity[0]} <{identity[1]}>' set on {counts.identity_commits}")
    for name in sorted(before):
        if name.startswith("refs/heads/"):
            print(f"rewrite-history: {name[11:]} {before[name][:12]} -> {after[name][:12]} "
                  "(same tree)")
    tags = [name for name in before if name.startswith("refs/tags/")]
    moved = sum(before[name] != after[name] for name in tags)
    print(f"rewrite-history: {moved} of {len(tags)} tags moved to their rewritten commits")
    for name in sorted(before):
        if name.startswith("refs/heads/"):
            for entry in stale_allow_entries(repo, name):
                print(f"rewrite-history: {name[11:]}: .public-check-allow line {entry} names a "
                      "commit the rewrite replaced; delete it")
    git_dir = git(repo, "rev-parse", "--absolute-git-dir").strip()
    print(f"rewrite-history: commit map in {Path(git_dir) / MAP_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
