"""The suite's git repositories hold still: no background maintenance runs in them, and a copy of
them never trips over a lock file that git creates and removes while it copies.

Git (2.56 on the CI runner) starts `git maintenance run --auto` in the background after a commit,
fetch or push; it creates `objects/maintenance.lock` and removes it again, which a copy that listed
the file a moment before then fails to find. Every repository the suite creates or clones comes from
`init` or `clone`, which quiet it before anything else (tests/test_repository.py refuses a git `init`
or `clone` anywhere else in tests/), and every copy of fixture repositories goes through `copy`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import git_door

# maintenance.auto covers `git maintenance run --auto`, gc.auto 0 the `gc --auto` of older gits and of
# receive-pack (receive.autogc follows it).
QUIET = "[maintenance]\n\tauto = false\n[gc]\n\tauto = 0\n"
LOCKS = shutil.ignore_patterns("*.lock")


def quiet(repository: Path) -> Path:
    """Switch background maintenance off in `repository` (a checkout or a bare repository); a file
    append, so it costs no git command."""
    git_dir = repository / ".git" if (repository / ".git").is_dir() else repository
    with open(git_dir / "config", "a", encoding="utf-8") as config:
        config.write(QUIET)
    return repository


def init(repository: Path, *options: str) -> Path:
    """`git init -q <options> <repository>`, quieted: a checkout, or a bare one with `--bare`."""
    git("init", "-q", *options, str(repository))
    return quiet(repository)


def clone(source: str | Path, destination: Path, *options: str) -> Path:
    """`git clone -q <options> <source> <destination>`, the clone quieted."""
    git("clone", "-q", *options, str(source), str(destination))
    return quiet(destination)


def git(*arguments: str) -> None:
    result = git_door.run(*arguments)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")


def copy(source: Path, destination: Path) -> None:
    """Copy the fixture repositories under `source` into `destination`, without git's lock files."""
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True, ignore=LOCKS)
