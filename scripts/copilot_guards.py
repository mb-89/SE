# se:template se/python-module 1.0.0
"""SE's request guards under GitHub Copilot: each path where SE, under Copilot, would make Copilot
call its model more often than the person's own prompts, and the se.toml setting that turns that
guard off. docs/copilot.md "What a session costs" owns the costs and their sources.

    [copilot]
    refuse_stop = false     # built in: the Stop hook never refuses; it says what is undelivered
    start_sessions = true   # built in: SE dispatches sessions automatically

The project's se.toml can override either default: false enables the guard, true disables it.
Under Claude Code nothing reads them. A pure module: the project's root in, the settings and
the lines that name them out.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

TABLE = "copilot"
#: Each guard's setting and what the guard does while it is on, the setting false.
GUARDS = {
    "refuse_stop": "the Stop hook never refuses a stop; it says what is undelivered",
    "start_sessions": "SE starts no session; it prints the line that starts one",
}
DEFAULTS = {"refuse_stop": False, "start_sessions": True}


def settings(root: Path | None) -> dict[str, bool]:
    """Each guard's setting in the project's se.toml `[copilot]`, built-in default where unset. Raises
        ValueError for a `copilot` value that is not a table, a setting that is not true or false, or
        an se.toml that does not parse."""
    table: object = {}
    path = root / "se.toml" if root is not None else None
    if path is not None and path.is_file():
        try:
            table = tomllib.loads(path.read_text(encoding="utf-8")).get(TABLE, {})
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot read {path}: {error}") from error
    if not isinstance(table, dict):
        raise ValueError(f"{TABLE} in {path} must be a table; fix it or remove it for the built-in "
                         "defaults")
    found = {}
    for name, default in DEFAULTS.items():
        value = table.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"{TABLE}.{name} in {path} must be true or false; fix it or remove it "
                             f"for the built-in {str(default).lower()}")
        found[name] = value
    return found


def guarded(root: Path | None, name: str) -> bool:
    """Whether the guard `name` is on under Copilot: its effective setting is false. An unreadable
    setting keeps the guard on, so a typo never spends requests."""
    try:
        return not settings(root)[name]
    except ValueError:
        return True


def state(root: Path | None) -> list[str]:
    """One line per guard: `on` with what it does, or `off` with what returned; an unreadable
    se.toml says so and names the guards on."""
    try:
        found = settings(root)
        broken = ""
    except ValueError as error:
        found, broken = dict.fromkeys(GUARDS, False), f" ({error}; every guard stays on)"
    return [f"[{TABLE}] {name} = {str(value).lower()}: "
            + (f"off, today's behaviour{broken}" if value else f"on, {GUARDS[name]}{broken}")
            for name, value in found.items()]


def greeting(root: Path | None, host: str) -> list[str]:
    """The start context's line under Copilot that names the guards' state; none elsewhere, so
    Claude Code's greeting stays as it is."""
    if host != "copilot":
        return []
    return ["Copilot guards: " + "; ".join(state(root))
            + ". docs/copilot.md \"What a session costs\" says what each costs."]
