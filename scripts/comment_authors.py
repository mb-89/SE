# se:template se/python-module 1.0.0
"""Who wrote a work issue's comment: its author's login and one flag, written by the repository's
owner account or not.

SE's repositories can be public, so anyone may comment on a work issue. `work_tickets.py` keeps the
flag beside each comment it reads (`byOwner`, from `by_owner`), on every path that hands an issue's
comments to an agent: `intake`, `refresh`, kern's relay reads and the field-report check. Where it
prints a line naming a comment, `mark` ends the line for one the owner did not write; the owner's
own comments print as they always did. It is information only: how a worker treats such a comment is
not decided here. Everything here is pure.
"""

from __future__ import annotations

NOT_OWNER = "not the repository owner"


def owner(repo: str) -> str:
    """The owner account of `repo`, `[HOST/]OWNER/NAME`."""
    parts = [part for part in repo.split("/") if part]
    return parts[-2] if len(parts) >= 2 else ""


def by_owner(author: str, repo: str) -> bool:
    """Whether `author`'s login is the owner account of `repo` (logins compare case-insensitively,
    as GitHub's do)."""
    account = owner(repo)
    return bool(author) and bool(account) and author.lower() == account.lower()


def mark(comment: dict[str, object]) -> str:
    """What a line naming the comment ends with: ` [not the repository owner]` where the comment
    is known not to be the owner's, else nothing, so the owner's comments, and one recorded before
    the flag existed, print exactly as before and the line's text up to here never changes."""
    return f" [{NOT_OWNER}]" if comment.get("byOwner") is False else ""
