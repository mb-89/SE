#!/usr/bin/env python3
"""A project's own commit checks: the commands its `se.toml` `[commit_checks]` names, run by se's
commit hook (`.githooks/pre-commit`) on the staged tree, so a commit that breaks one is refused
before it exists (docs/settings.md "Commit checks").

```toml
[commit_checks]
forbids = ["go", "run", "./cmd/kern", "forbids"]
```

Each entry is a check's name and its command, an argument array run without a shell. The hook runs
every check in a copy of the index, the tree the commit records, with the repository's git
variables removed, so neither an unstaged edit nor the working tree's untracked files decide. The
table is read from the staged `se.toml`, the settings the commit itself carries.

Exit code 0 where every check passed or none is named, 1 where one failed (each failure names its
check, its exit code and its output), 2 on a setup error: a malformed table, or a command that
cannot start. The hook refuses the commit on anything but 0.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_door  # noqa: E402
import process_door  # noqa: E402

TABLE = "commit_checks"
SETTINGS = "se.toml"
# What would point a check's git at the committing repository instead of its copy: git sets the
# index (and, in a worktree or with --git-dir, the git dir) for its hooks.
GIT_LOCATION = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")


class SetupError(Exception):
    """A table the checks cannot run from, or git failing to read the index."""


def checks(settings: str, source: str = SETTINGS) -> dict[str, list[str]]:
    """The commit checks `settings` (an `se.toml`'s text) names, in its order: name -> command.
    No table, no checks; a table that maps a name to anything but a non-empty list of strings is
    refused, naming `source` and the entry."""
    try:
        data = tomllib.loads(settings)
    except tomllib.TOMLDecodeError as error:
        raise SetupError(f"{source}: {error}") from error
    table = data.get(TABLE, {})
    if not isinstance(table, dict):
        raise SetupError(f"{source}: [{TABLE}] must be a table of check names and commands")
    found = {}
    for name, command in table.items():
        if not (isinstance(command, list) and command
                and all(isinstance(word, str) and word for word in command)):
            raise SetupError(f"{source}: [{TABLE}] {name} must be a command, a non-empty array of "
                             "strings such as [\"go\", \"run\", \"./cmd/kern\", \"forbids\"]")
        found[name] = command
    return found


def git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = git_door.run(*args, root=root, stdin=stdin, binary=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SetupError(f"git {args[0]} failed: {detail}")
    return result.stdout


def staged(root: Path) -> list[tuple[str, str, str]]:
    """The index's entries as (mode, blob, path), submodules left out, as their own repository
    checks them."""
    entries = []
    for line in git(root, "ls-files", "-s", "-z").split(b"\0"):
        if not line:
            continue
        meta, path = line.split(b"\t", 1)
        mode, blob, _stage = meta.decode().split()
        if mode != "160000":
            entries.append((mode, blob, path.decode("utf-8", "surrogateescape")))
    return entries


def blobs(root: Path, ids: list[str]) -> list[bytes]:
    if not ids:
        return []
    output = git(root, "cat-file", "--batch", stdin="".join(f"{blob}\n" for blob in ids).encode())
    found, position = [], 0
    for _ in ids:
        header_end = output.index(b"\n", position)
        size = int(output[position:header_end].split()[2])
        found.append(output[header_end + 1:header_end + 1 + size])
        position = header_end + 1 + size + 1
    return found


def settings_of(entries: list[tuple[str, str, str]], contents: list[bytes]) -> str:
    """The staged `se.toml`'s text, empty where the index holds none."""
    for (_, _, path), data in zip(entries, contents):
        if path == SETTINGS:
            return data.decode("utf-8")
    return ""


def write_tree(entries: list[tuple[str, str, str]], contents: list[bytes], folder: Path) -> None:
    """The index's files under `folder`, executable and symbolic links as git records them."""
    for (mode, _, path), data in zip(entries, contents):
        target = folder / Path(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000" and os.name != "nt":
            target.symlink_to(data.decode("utf-8", "surrogateescape"))
            continue
        target.write_bytes(data)
        if mode == "100755":
            target.chmod(0o755)


def environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in GIT_LOCATION}


def run(root: Path, out=None, err=None) -> int:
    """Every commit check of the staged tree of `root`; the exit code the module docstring names."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        entries = staged(root)
        contents = blobs(root, [blob for _, blob, _ in entries])
        named = checks(settings_of(entries, contents), f"{SETTINGS} (staged)")
    except (SetupError, UnicodeDecodeError) as error:
        print(f"commit checks: error: {error}; refusing the commit", file=err)
        return 2
    if not named:
        return 0
    failed = 0
    with tempfile.TemporaryDirectory(prefix="se-commit-checks-") as copy:
        folder = Path(copy)
        write_tree(entries, contents, folder)
        for name, command in named.items():
            shown = " ".join(command)
            try:
                result = process_door.run(command, cwd=folder, env=environment(), stdin=subprocess.DEVNULL,
                                         capture_output=True, text=True, errors="replace", check=False)
            except OSError as error:
                print(f"commit check {name}: error: `{shown}` cannot start: {error}; refusing the "
                      f"commit (se.toml [{TABLE}] {name})", file=err)
                failed = max(failed, 2)
                continue
            if result.returncode == 0:
                print(f"commit check {name}: passed", file=out)
                continue
            print(f"commit check {name}: failed with exit code {result.returncode} (`{shown}`, "
                  f"se.toml [{TABLE}] {name}); refusing the commit", file=err)
            output = (result.stdout + result.stderr).rstrip()
            if output:
                print(output, file=err)
            failed = max(failed, 1)
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="the repository whose index is checked (default: the working directory)")
    args = parser.parse_args(argv)
    return run(args.repo.resolve())


if __name__ == "__main__":
    sys.exit(main())
