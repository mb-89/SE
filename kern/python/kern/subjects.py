"""How names, command names and verbs ride as NATS subject tokens.

Every byte but letters, digits, dashes and underscores rides percent-encoded, so
``tally note`` rides as ``tally%20note`` and the family key ``v1.2`` as ``v1%2E2``;
a name's segments, split by ``/``, become one token each. The Go bus encodes the
same way (``bus.Token``, ``bus.Subject``); ``contract/subjects.json`` holds both to it.
"""

from __future__ import annotations

import re

_PLAIN = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")


def token(word: str) -> str:
    """One subject token for a word: a command name, a verb, a name's segment."""
    return "".join(chr(b) if b in _PLAIN else f"%{b:02X}" for b in word.encode("utf-8"))


def word(tok: str) -> str:
    """The word a token stands for."""
    if "%" not in tok:
        return tok
    raw = bytearray()
    i = 0
    data = tok.encode("utf-8")
    while i < len(data):
        m = _ESCAPE.match(tok, i) if data[i] == ord("%") else None
        if m:
            raw.append(int(m.group(1), 16))
            i += 3
        else:
            raw.append(data[i])
            i += 1
    return raw.decode("utf-8", errors="replace")


def subject(name: str) -> str:
    """A name's subject tokens: ``fleet/findings`` rides as ``fleet.findings``."""
    return ".".join(token(seg) for seg in name.split("/"))


def name(subj: str) -> str:
    """The name a subject's tokens stand for."""
    return "/".join(word(tok) for tok in subj.split("."))


def inbox(user: str) -> str:
    """The prefix of a user's reply subjects, as the bus permits them (``bus.Inbox``)."""
    return "_INBOX" if user == "core" else "_INBOX." + user.encode("utf-8").hex()
