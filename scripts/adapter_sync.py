"""The adapter sync contract's helper: a verb guard, one logged write path, secrets and artifacts.

The contract itself is owned by the work model's "Adapter sync contract"
(src/skills/work-model/SKILL.md); this module is its reusable part, standard library only, so an
adapter in any project imports it from its se module (`<se>/scripts/adapter_sync.py`).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REDACTED = "***"

# send(method, url, headers, body) -> (status, body): the one place a transport reaches the outside.
Send = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]
Clock = Callable[[], datetime]


class WriteRefused(RuntimeError):
    """A non-read request outside apply mode."""


def add_apply_argument(parser: argparse.ArgumentParser) -> None:
    """Adds the contract's one switch: without `--apply` the command is a dry run."""
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the writes; without it the command reads, plans and reports only",
    )


def secret_from_env(name: str, environ: Mapping[str, str] | None = None) -> str:
    """Reads a secret from the environment at run time, failing fast without naming its value."""
    value = (os.environ if environ is None else environ).get(name, "")
    if not value:
        raise SystemExit(f"adapter_sync: environment variable {name} is not set; set it in this shell")
    return value


def scrub(value: Any, secrets: Iterable[str]) -> Any:
    """Returns value with every secret replaced by `***`, recursing into lists and mappings."""
    secrets = [secret for secret in secrets if secret]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, bytes):
        return scrub(value.decode("utf-8", "replace"), secrets).encode("utf-8")
    if isinstance(value, Mapping):
        return {scrub(key, secrets): scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(item, secrets) for item in value]
    return value


def urllib_send(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> tuple[int, bytes]:
    """The real `send`, through urllib; an HTTP error status is returned, not raised."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@dataclass
class Transport:
    """The single write path: every request goes through `request`, guarded and logged.

    `apply` is the command's `--apply`; outside it a non-read request is refused before it is sent.
    `secrets` are scrubbed from every log entry and recorded response.
    """

    base_url: str
    apply: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)
    secrets: Iterable[str] = ()
    send: Send = urllib_send
    clock: Clock = lambda: datetime.now(UTC)
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.secrets = tuple(secret for secret in self.secrets if secret)

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """Sends one request; returns its status and its body, parsed as JSON where it is JSON."""
        method = method.upper()
        if method not in READ_METHODS and not self.apply:
            self._record(method, path, "refused")
            raise WriteRefused(
                f"adapter_sync: {method} {scrub(path, self.secrets)} refused: dry run; pass --apply to write"
            )
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = dict(self.headers)
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
        status, raw = self.send(method, self.base_url.rstrip("/") + path, headers, data)
        self._record(method, path, status)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    def recorded(self, response: Any) -> Any:
        """A response as it may be stored or committed: with every secret scrubbed."""
        return scrub(response, self.secrets)

    def write_log(self, path: Path) -> None:
        """Writes the audit log as JSON lines."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(entry, sort_keys=True) + "\n" for entry in self.log), encoding="utf-8")

    def _record(self, method: str, path: str, status: int | str) -> None:
        # Headers and bodies never enter the log: they are where secrets travel.
        self.log.append(
            {
                "method": method,
                "path": scrub(path, self.secrets),
                "status": status,
                "time": self.clock().isoformat(),
            }
        )


@dataclass(frozen=True)
class Preflight:
    """The outcome of repeating the reads on apply: what may be written and what is skipped."""

    write: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


def preflight(changes: Iterable[Mapping[str, Any]], revisions: Mapping[str, Any]) -> Preflight:
    """Keeps each planned change whose object's external revision is still the one it was planned at.

    A change is a mapping with `id` and `revision` (the revision the dry run read); `revisions`
    maps each id to its revision as the apply's repeated read found it. A changed or vanished object
    is skipped, with the revision found.
    """
    write: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for change in changes:
        found = revisions.get(change["id"])
        if found == change["revision"]:
            write.append(dict(change))
        else:
            skipped.append({**change, "found_revision": found})
    return Preflight(write=write, skipped=skipped)


def write_artifact(path: Path, data: Any) -> None:
    """Writes a plan or result file as sorted, indented JSON, so runs compare line by line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
