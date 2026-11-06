#!/usr/bin/env python3
"""The verdicts of se's checks on a tree, recorded in the checkout's git directory.

`work_tickets.py suite` and `public_check.py --rev` record theirs. Before the integration branch is
pushed, `work_tickets.py push` and the pre-push hook read them: nothing reaches it without a passing
verdict of each check on exactly the tree pushed. A release commit carries its parent's suite
verdict. A verdict is keyed by tree hash, so every worktree of a repository shares it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


STORE = "se-verdicts"


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(arguments)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def tree(root: Path, commit: str) -> str:
    return git(root, "rev-parse", "--verify", "--quiet", f"{commit}^{{tree}}")


def path(root: Path, check: str, tree_hash: str) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else root / common) / STORE / check / f"{tree_hash}.json"


def record(root: Path, check: str, commit: str, passed: bool, seconds: float | None = None,
           carried_from: str | None = None) -> str:
    """Record `check`'s verdict on `commit`'s tree; the tree hash."""
    tree_hash = tree(root, commit)
    target = path(root, check, tree_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = {"check": check, "passed": passed, "commit": git(root, "rev-parse", commit),
               "seconds": None if seconds is None else round(seconds, 1)}
    if carried_from:
        verdict["carried_from"] = carried_from
    target.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8", newline="\n")
    return tree_hash


def verdict(root: Path, check: str, tree_hash: str) -> dict | None:
    try:
        return json.loads(path(root, check, tree_hash).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def carry(root: Path, check: str, parent: str, commit: str) -> None:
    """`commit` (a release commit, which changes only version files) carries `parent`'s verdict."""
    parent_tree = tree(root, parent)
    found = verdict(root, check, parent_tree)
    if found is not None:
        record(root, check, commit, bool(found.get("passed")), found.get("seconds"), parent_tree)


def refusal(root: Path, check: str, commit: str, remedy: str) -> str | None:
    """Why `commit` may not be pushed for `check`, or None where a passing verdict is on its tree."""
    tree_hash = tree(root, commit)
    found = verdict(root, check, tree_hash)
    if found is not None and found.get("passed") is True:
        return None
    state = "no verdict is recorded" if found is None else "its recorded verdict is a failure"
    return (f"{check}: {state} for commit {commit[:12]} (tree {tree_hash[:12]}); "
            f"nothing reaches the integration branch without a passing {check} on exactly that "
            f"tree. Remedy: {remedy}")
