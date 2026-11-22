"""The bash SE's shell scripts run in, and paths as that bash names them, on every platform.

On Windows the `bash` on PATH may be WSL's launcher (System32), and Git's `bin/bash.exe` is a
launcher too, which puts Git's own tools first on PATH, before a test's fakes: the bash is Git's
MSYS bash itself, `usr/bin/bash.exe`, found beside `git`. It mounts drive C: at /c."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

WINDOWS = os.name == "nt"


def git_bash() -> str | None:
    """Git's MSYS bash on Windows (<Git>/usr/bin/bash.exe, beside <Git>/cmd/git.exe); elsewhere
    the bash on PATH; None without one."""
    if not WINDOWS:
        return shutil.which("bash")
    git = shutil.which("git")
    if git is None:
        return None
    for folder in Path(git).resolve().parents:
        candidate = folder / "usr" / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


BASH = git_bash()


def sh(path: Path) -> str:
    """`path` as the scripts' bash names it."""
    if not WINDOWS:
        return str(path)
    drive, rest = os.path.splitdrive(str(path))
    return f"/{drive.rstrip(':').lower()}{rest.replace(os.sep, '/')}"


LATER = ".later"


def _ranks(folder: Path) -> list[Path]:
    """`folder`'s rank folders, `.later/1`, `.later/2`, ..., in order."""
    later = folder / LATER
    if not later.is_dir():
        return []
    return sorted((rank for rank in later.iterdir() if rank.name.isdigit()), key=lambda rank: int(rank.name))


def link_tools(folder: Path, tools) -> Path:
    """Links every file PATH holds for each of `tools`, in PATH's order, into a sealed PATH.

    The first file of a tool goes into `folder`, the k-th into `folder/.later/<k>`; a file reached
    through two PATH entries counts once, and a tool PATH lacks is skipped. Bash runs the first,
    as on the real PATH, and a wrapper that hands over to the next file of its name past its own
    entry (a harness's rm guard) finds it in the rank after, so it stays first and keeps checking.
    Where every tool has one file there are no ranks. On Windows a linked Git tool would not find
    the DLLs beside it, so each link is a shim that runs its file by its path; a wrapper there does
    not find its own entry, as before. `tool_path` names the PATH; `drop_tool` takes a tool away."""
    folder.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        seen: list[str] = []
        files: list[str] = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            found = shutil.which(tool, path=entry)
            if found is None:
                continue
            real = os.path.normcase(os.path.realpath(found))
            if real in seen:
                continue
            seen.append(real)
            files.append(found)
        for rank, found in enumerate(files):
            target = folder if rank == 0 else folder / LATER / str(rank)
            target.mkdir(parents=True, exist_ok=True)
            if WINDOWS:
                (target / tool).write_text(f'#!/bin/sh\nexec "{sh(Path(found))}" "$@"\n', encoding="utf-8",
                                           newline="\n")
                (target / tool).chmod(0o755)
            else:
                (target / tool).symlink_to(found)
    return folder


def tool_path(folder: Path, *after: Path) -> str:
    """The PATH bash gets: `folder`, its rank folders in order, then `after`, as bash names them."""
    return ":".join(sh(entry) for entry in (folder, *_ranks(folder), *after))


def drop_tool(folder: Path, tool: str) -> None:
    """Takes `tool` off `folder` and every rank folder of it."""
    for entry in (folder, *_ranks(folder)):
        (entry / tool).unlink(missing_ok=True)
