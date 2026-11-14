"""The host table, `scripts/hosts.sh`, as a pure module: an environment (and a hook payload) in;
the host, the clouds, the project and the payload in snake_case out.

`hosts.sh` owns the table (one line `SE_<NAME>=(<entry> ...)` per table, so the hook scripts source
it and this reads it). Nothing here reads the process's own environment: every caller passes it.
"""

from __future__ import annotations

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


def _marks(name: str) -> list[tuple[str, str, str | None]]:
    """A mark table: (host or cloud, variable, value or None for set and not empty)."""
    found = []
    for entry in table()[name]:
        owner, _, mark = entry.partition(":")
        variable, equals, value = mark.partition("=")
        found.append((owner, variable, value if equals else None))
    return found


def _marked(name: str, environment: Mapping[str, str]) -> list[str]:
    found = []
    for owner, variable, value in _marks(name):
        given = environment.get(variable, "")
        if (given.lower() == value.lower()) if value is not None else bool(given):
            found.append(owner)
    return list(dict.fromkeys(found))


def variables() -> list[str]:
    """Every variable the host and cloud marks read."""
    return list(dict.fromkeys(variable for name in ("SE_HOST_MARKS", "SE_CLOUD_MARKS")
                              for _, variable, _ in _marks(name)))


def host(environment: Mapping[str, str]) -> str | None:
    """The host `environment` marks (claude, copilot), the table's first; None where none does."""
    found = _marked("SE_HOST_MARKS", environment)
    return found[0] if found else None


def clouds(environment: Mapping[str, str]) -> list[str]:
    """The clouds whose mark `environment` carries (claude, copilot, ci, se), in the table's order."""
    return _marked("SE_CLOUD_MARKS", environment)


def project_dir(environment: Mapping[str, str]) -> str | None:
    """The project a host names, from the first project variable that is set; None without one."""
    return next((environment[name] for name in table()["SE_PROJECT_VARIABLES"] if environment.get(name)), None)


def payload_keys() -> dict[str, str]:
    """Copilot's camelCase payload fields and their snake_case names."""
    return dict(entry.split(":", 1) for entry in table()["SE_PAYLOAD_KEYS"])


def payload(event: Mapping[str, object]) -> dict[str, object]:
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
