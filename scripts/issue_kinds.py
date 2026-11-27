# se:template se/python-module 1.0.0
"""The kinds of issue SE's commands take, one row each: how an issue shows its kind, the command that
takes it, and what a run of its kind writes.

Reader: every command that takes an issue number (retro.py, overhaul.py, work_tickets.py), and
whoever adds a kind or a command that takes one. A command never trusts that a number names the
right kind of issue (overhaul #1993, finding 1: `retro.py collect` ran on an overhaul issue and
wrote an empty retro draft): it calls `check` once, where it first reads the issue, and the wrong
kind is refused before anything is written, naming the command that takes it.

- `kind_of(issue)` reads an issue's kind, strongest sign first: its template marker
  (`<!-- se:template se/<kind> ... -->`, which every issue SE files carries), then its title (an
  overhaul's `overhaul-<yyyymmdd>`, an old retro's `docs/retro-...`), then its labels; a discovery
  label without a work label is an overhaul's, as discovery work issues carry both. None where
  nothing shows it.
- `check(issue, want, command)` refuses an issue of another kind, raising `error` with the remedy.
  An issue whose kind nothing shows (one filed before issues carried their template marker) is
  taken with one warning line naming `work_tickets.py stamp`, which marks it: the rule fires from
  day one, and UNKNOWN_LEVEL steps to `error` once no unmarked issue is taken any more.
- KINDS is the table: per run kind (retro, overhaul) also the deck's cover (`document_type`),
  whether its deck closes with the field-feedback question "Anything else?" (`anything_else`: a
  retro asks for field feedback, an overhaul is about drift, the person's rule of 27 Nov) and its
  filing rule (`report_blesses`: an overhaul's report is its blessing and opens filing at once, a
  retro's waits for `retro.py bless`). retro_deck.py and retro.py's `file_steps` read them here,
  never a run's name; retro.py RUN_KINDS names which issues are runs and their finding references.

Everything here is pure.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

#: How an issue that shows no kind is taken: `warn` (one line, and the command goes on) while
#: unmarked issues are still taken, then `error`.
UNKNOWN_LEVEL = "warn"
TEMPLATE_MARKER = re.compile(r"^[ \t]*<!-- se:template (?:[\w.-]+/)*([\w-]+) \S+(?: sha256:[0-9a-f]+)? -->",
                             re.MULTILINE)


@dataclass(frozen=True)
class Kind:
    """One kind of issue: its name (its issue template's, .github/ISSUE_TEMPLATE/<name>.md), what it
    is called (with its article), the labels that show it, its title pattern, the command that takes it, and, for a run,
    its deck's cover, closing question and filing rule."""
    name: str
    noun: str
    labels: tuple[str, ...]
    command: str
    title: re.Pattern | None = None
    document_type: str | None = None
    anything_else: bool = False
    report_blesses: bool = False


WORK = Kind("work", "a work issue", ("work", "ready"), "work_tickets.py intake --issue {number}")
RETRO = Kind("retro", "a retro issue", ("retro",), "retro.py collect {number}",
             title=re.compile(r"docs/retro-"), document_type="Retro report", anything_else=True)
OVERHAUL = Kind("overhaul", "an overhaul issue", ("discovery",), "overhaul.py read {number}",
                title=re.compile(r"(?:docs/)?overhaul-\d{8}$"), document_type="Overhaul report",
                report_blesses=True)
KINDS = {kind.name: kind for kind in (WORK, RETRO, OVERHAUL)}


def labels_of(issue: dict) -> set[str]:
    """Label names, from gh's and the REST API's objects or the GitHub tools' strings."""
    labels = issue.get("labels") or []
    if isinstance(labels, dict):
        labels = labels.get("nodes") or []
    return {str(label.get("name", "")) if isinstance(label, dict) else str(label) for label in labels}


def kind_of(issue: dict) -> Kind | None:
    """The kind `issue` shows (module docstring), None where nothing shows one."""
    marker = TEMPLATE_MARKER.search(str(issue.get("body") or ""))
    if marker and marker[1] in KINDS:
        return KINDS[marker[1]]
    title = str(issue.get("title") or "").strip()
    for kind in KINDS.values():
        if kind.title is not None and kind.title.match(title):
            return kind
    labels = labels_of(issue)
    if labels & set(RETRO.labels):
        return RETRO
    if labels & set(WORK.labels):
        return WORK
    if labels & set(OVERHAUL.labels):
        return OVERHAUL
    return None


def check(issue: dict, want: Kind, command: str, error: type[Exception] = ValueError) -> Kind | None:
    """`issue`'s kind where it is `want`; raises `error` naming the command that takes it where it is
    another; None, with one warning line, where nothing shows a kind (UNKNOWN_LEVEL `warn`)."""
    number = issue.get("number")
    found = kind_of(issue)
    if found == want:
        return found
    if found is not None:
        raise error(f"{command} takes {want.noun}, and #{number} is {found.noun}: run "
                    f"`{found.command.format(number=number)}` for it; nothing was written")
    *first, last = KINDS
    message = (f"{command}: nothing shows #{number}'s kind (no template marker, title or label of "
               f"{', '.join(first)} or {last} issue); mark it with `work_tickets.py stamp {number}`")
    if UNKNOWN_LEVEL == "error":
        raise error(message)
    print(f"warning: {message}; taken as {want.noun}", file=sys.stderr)
    return None
