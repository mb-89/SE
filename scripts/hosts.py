"""The host table, `scripts/hosts.sh`, as the Python scripts read it: which cloud runs SE, where the
project is, and a hook payload in snake_case whatever host wrote it.

`hosts.sh` owns the table (one line `SE_<NAME>=(<entry> ...)` per table, so bash sources it and this
reads it); every script asks here instead of checking a host's variable on its own.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from functools import cache
from pathlib import Path

TABLE = Path(__file__).with_name("hosts.sh")
LINE = re.compile(r"^(SE_[A-Z_]+)=\((.*)\)$", re.MULTILINE)


@cache
def table(path: Path = TABLE) -> dict[str, tuple[str, ...]]:
    """Every `SE_<NAME>=(...)` line of the host table, by name."""
    return {name: tuple(shlex.split(entries)) for name, entries in LINE.findall(path.read_text(encoding="utf-8"))}


def _marks() -> list[tuple[str, str, str | None]]:
    """The cloud marks: (cloud, variable, value or None for set and not empty)."""
    found = []
    for entry in table()["SE_CLOUD_MARKS"]:
        cloud, _, mark = entry.partition(":")
        variable, equals, value = mark.partition("=")
        found.append((cloud, variable, value if equals else None))
    return found


def variables() -> list[str]:
    """Every variable the cloud marks read."""
    return list(dict.fromkeys(variable for _, variable, _ in _marks()))


def clouds(environment: Mapping[str, str] | None = None) -> list[str]:
    """The clouds whose mark `environment` (default: this process's) carries, in the table's order."""
    environment = os.environ if environment is None else environment
    found = []
    for cloud, variable, value in _marks():
        given = environment.get(variable, "")
        if (given.lower() == value.lower()) if value is not None else bool(given):
            found.append(cloud)
    return list(dict.fromkeys(found))


def in_cloud(name: str | None = None, environment: Mapping[str, str] | None = None) -> bool:
    """Whether a cloud runs this (any, or the one named: claude, copilot, ci, se)."""
    found = clouds(environment)
    return bool(found) if name is None else name in found


def project_dir(environment: Mapping[str, str] | None = None) -> str | None:
    """The project a host names, from the first project variable that is set; None without one."""
    environment = os.environ if environment is None else environment
    return next((environment[name] for name in table()["SE_PROJECT_VARIABLES"] if environment.get(name)), None)


def payload_keys() -> dict[str, str]:
    """Copilot's camelCase payload fields and their snake_case names."""
    return dict(entry.split(":", 1) for entry in table()["SE_PAYLOAD_KEYS"])


def payload(event: dict[str, object]) -> dict[str, object]:
    """A hook payload in snake_case: each camelCase field of the table renamed, a field already in
    snake_case kept."""
    keys = payload_keys()
    renamed: dict[str, object] = {}
    for key, value in event.items():
        name = keys.get(key, key)
        if name not in renamed or key == name:
            renamed[name] = value
    return renamed


def payload_host(event: Mapping[str, object]) -> str:
    """`copilot` where the payload carries a camelCase field of the table, else `claude`."""
    return "copilot" if set(event) & set(payload_keys()) else "claude"
