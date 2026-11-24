# se:template se/python-module 1.0.0
"""The review gate: whether `work_tickets.py integrate` lands a risky change that no reviewer passed.

se.toml `[integrate] review_gate` switches it on (`true`); absent or `false`, the built-in, it
decides nothing and `integrate` reads no review. `[integrate] review_gate_risky` lists which kinds
of change count as risky, RISKS by default:

- `major`: the landing releases a major version (its release trailer's kind);
- `rule-book`: the change edits the rule book, AGENTS.md or the work model's rules.md;
- `role-file`: the change edits an agent's role file, `src/agents/<name>.md`;
- `history`: the change rewrites history: it edits `scripts/rewrite_history.py`, or its work
  issue's Package kind says it rewrites history.

A risky change lands only with a reviewer's verdict `pass` or `pass with open points` on its work
pull request (`review.py file`'s comment) for the head that lands; otherwise `integrate` refuses it
before anything is pushed, naming the risks, the setting and the remedy (README "Review gate").

Everything here is pure: `settings` reads the table it is handed, `facts` the change's facts,
`reviews` the pull request's comments, and `decide` takes the facts, the reviews and the settings
and answers land or refuse with its reason. `work_tickets.py integrate` is the thin wiring that
reads them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

#: The kinds of risky change, in the order a refusal names them.
RISKS = ("major", "rule-book", "role-file", "history")
#: The paths each path-borne kind of risk watches, from the checkout's root (`matches`).
RISK_PATHS = {
    "rule-book": ("AGENTS.md", "src/skills/work-model/references/rules.md"),
    "role-file": ("src/agents/*.md",),
    "history": ("scripts/rewrite_history.py",),
}
#: What a work issue's Package kind says for a change that rewrites history.
HISTORY_WORDS = re.compile(r"\brewrit\w*\s+(?:the\s+|its\s+|git\s+)?history\b|\bhistory\s+rewrite",
                           re.IGNORECASE)
#: review.py's verdict comment: its marker, and the verdicts that let a change land.
VERDICT_MARKER = "<!-- se:review -->"
LANDING_VERDICTS = ("pass", "pass with open points")
JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
SETTING = "[integrate] review_gate"


class SettingError(ValueError):
    """The `[integrate]` table holds a review-gate value that cannot be read."""


@dataclass(frozen=True)
class Settings:
    """Whether the gate is on and which kinds of change it counts as risky."""

    on: bool = False
    risky: tuple[str, ...] = RISKS


@dataclass(frozen=True)
class Facts:
    """What the gate knows of one change: its release kind, the paths it changes and whether its
    work issue says it rewrites history."""

    kind: str
    paths: tuple[str, ...] = ()
    rewrites_history: bool = False


@dataclass(frozen=True)
class Review:
    """One reviewer's verdict on the pull request, and the head commit it reviewed."""

    verdict: str
    head: str


@dataclass(frozen=True)
class Decision:
    """`land`, or not with `reason`; `risks` names the kinds of risk the change carries."""

    land: bool
    reason: str = ""
    risks: tuple[str, ...] = ()


def settings(table: dict[str, object]) -> Settings:
    """The gate's settings from se.toml's `[integrate]` table `table`."""
    on = table.get("review_gate", False)
    if not isinstance(on, bool):
        raise SettingError(f"integrate.review_gate must be true or false (built in false); "
                           f"got {on!r}")
    risky = table.get("review_gate_risky", list(RISKS))
    if not isinstance(risky, list) or not all(isinstance(item, str) for item in risky):
        raise SettingError("integrate.review_gate_risky must be a list of "
                           f"{', '.join(RISKS)}; got {risky!r}")
    unknown = [item for item in risky if item not in RISKS]
    if unknown:
        raise SettingError(f"integrate.review_gate_risky names {', '.join(map(repr, unknown))}; "
                           f"each must be one of {', '.join(RISKS)}")
    return Settings(on, tuple(item for item in RISKS if item in risky))


def facts(kind: str, paths: list[str] | tuple[str, ...], package_kind: str) -> Facts:
    """The facts of a change from its release kind, the paths it changes and the text of its work
    issue's Package kind section."""
    return Facts(kind, tuple(paths), HISTORY_WORDS.search(package_kind) is not None)


def matches(path: str, pattern: str) -> bool:
    """Whether `path` matches `pattern` segment by segment: a `*` never crosses a `/`."""
    names, parts = path.split("/"), pattern.split("/")
    return len(names) == len(parts) and all(map(fnmatchcase, names, parts))


def risks(change: Facts, risky: tuple[str, ...] = RISKS) -> tuple[str, ...]:
    """The kinds of risk in `risky` that `change` carries, in RISKS order."""
    found = []
    for risk in RISKS:
        if risk not in risky:
            continue
        if risk == "major" and change.kind == "major":
            found.append(risk)
        elif risk == "history" and change.rewrites_history:
            found.append(risk)
        elif any(matches(path, pattern) for path in change.paths
                 for pattern in RISK_PATHS.get(risk, ())):
            found.append(risk)
    return tuple(found)


def reviews(comments: list[object]) -> list[Review]:
    """The reviewers' verdicts among a pull request's comments, oldest first: each comment that
    opens with review.py's marker and carries its JSON block."""
    found = []
    for comment in comments:
        body = str(comment.get("body") or "") if isinstance(comment, dict) else ""
        if not body.lstrip().startswith(VERDICT_MARKER):
            continue
        blocks = JSON_BLOCK.findall(body)
        try:
            data = json.loads(blocks[-1]) if blocks else None
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("verdict"), str):
            found.append(Review(data["verdict"], str(data.get("head") or "")))
    return found


def same_commit(one: str, other: str) -> bool:
    """Whether two commit names, either abbreviated, name the same commit."""
    return bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))


def decide(change: Facts, found: list[Review], head: str, gate: Settings) -> Decision:
    """Land or refuse `change`, whose pull request's head is `head`, by the reviews `found` on it
    (oldest first) and the gate's settings: the newest review of `head` decides."""
    if not gate.on:
        return Decision(True)
    carried = risks(change, gate.risky)
    if not carried:
        return Decision(True)
    named = ", ".join(carried)
    of_head = [review for review in found if same_commit(review.head, head)]
    if of_head and of_head[-1].verdict in LANDING_VERDICTS:
        return Decision(True, f"risky ({named}), reviewed: {of_head[-1].verdict} at {head[:12]}",
                        carried)
    if of_head:
        why = f"its newest review of {head[:12]} is {of_head[-1].verdict}"
    elif found:
        why = (f"its reviews are of {', '.join(sorted({r.head[:12] or 'no head' for r in found}))}, "
               f"not of its head {head[:12]}")
    else:
        why = "it has no review"
    return Decision(
        False,
        f"the change is risky ({named}) and {why}; se.toml {SETTING} = true lands a risky change "
        f"only with a reviewer's {' or '.join(LANDING_VERDICTS)} of the head that lands: review "
        f"it (review.py brief, then review.py file) and integrate again (README \"Review gate\")",
        carried)
