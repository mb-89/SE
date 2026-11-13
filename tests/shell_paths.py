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
