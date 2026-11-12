"""The adapter sync contract's helper (work model "Adapter sync contract"), on a fake service."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import adapter_sync
import pytest

SECRET = "tok-4f9c2e"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class FakeService:
    """An external system of objects with revisions; it records what reached it."""

    def __init__(self, objects: dict[str, dict]) -> None:
        self.objects = objects
        self.received: list[tuple[str, str, dict, bytes | None]] = []

    def send(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> tuple[int, bytes]:
        self.received.append((method, url, dict(headers), body))
        key = url.rsplit("/", 1)[-1].split("?")[0]
        if method == "GET":
            return 200, json.dumps({"objects": self.objects, "echo": headers.get("Authorization")}).encode()
        self.objects[key] = {**json.loads(body or b"{}"), "revision": self.objects[key]["revision"] + 1}
        return 200, json.dumps(self.objects[key]).encode()


def transport(service: FakeService, *, apply: bool) -> adapter_sync.Transport:
    return adapter_sync.Transport(
        base_url="https://api.example.com",
        apply=apply,
        headers={"Authorization": f"Bearer {SECRET}"},
        secrets=[SECRET],
        send=service.send,
        clock=lambda: NOW,
    )


def test_a_write_in_dry_run_is_refused_naming_method_and_path_and_never_sent() -> None:
    service = FakeService({"a": {"revision": 1}})
    client = transport(service, apply=False)

    assert client.request("get", "/objects")[0] == 200
    with pytest.raises(adapter_sync.WriteRefused, match=r"PATCH /objects/a refused: dry run; pass --apply"):
        client.request("PATCH", "/objects/a", {"title": "new"})

    assert [method for method, *_ in service.received] == ["GET"]
    assert client.log[-1] == {"method": "PATCH", "path": "/objects/a", "status": "refused", "time": NOW.isoformat()}


def test_the_log_and_recorded_responses_carry_no_secret_even_when_the_request_did(tmp_path: Path) -> None:
    service = FakeService({"a": {"revision": 1}})
    client = transport(service, apply=True)

    _, read = client.request("GET", f"/objects?token={SECRET}")
    client.request("PUT", "/objects/a", {"title": "new", "note": SECRET})
    log = tmp_path / "write-log.jsonl"
    client.write_log(log)

    assert SECRET in service.received[1][2]["Authorization"]
    assert SECRET not in log.read_text(encoding="utf-8")
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert entries == [
        {"method": "GET", "path": "/objects?token=***", "status": 200, "time": NOW.isoformat()},
        {"method": "PUT", "path": "/objects/a", "status": 200, "time": NOW.isoformat()},
    ]
    assert SECRET in json.dumps(read)
    assert SECRET not in json.dumps(client.recorded(read))


def test_preflight_on_apply_skips_an_object_whose_revision_changed(tmp_path: Path) -> None:
    service = FakeService({"a": {"revision": 1}, "b": {"revision": 7}})
    planned = [{"id": key, "revision": value["revision"], "action": "update"} for key, value in service.objects.items()]
    adapter_sync.write_artifact(tmp_path / "plan.json", planned)
    service.objects["b"]["revision"] = 8  # someone else wrote b after the dry run

    client = transport(service, apply=True)
    _, current = client.request("GET", "/objects")
    result = adapter_sync.preflight(planned, {key: value["revision"] for key, value in current["objects"].items()})
    for change in result.write:
        client.request("PATCH", f"/objects/{change['id']}", {"title": "new"})

    assert [change["id"] for change in result.write] == ["a"]
    assert result.skipped == [{"id": "b", "revision": 7, "action": "update", "found_revision": 8}]
    assert [method for method, *_ in service.received] == ["GET", "PATCH"]
    assert json.loads((tmp_path / "plan.json").read_text(encoding="utf-8")) == sorted(
        planned, key=lambda change: change["id"]
    )


def test_apply_is_off_unless_named_and_a_missing_secret_fails_without_a_value() -> None:
    parser = argparse.ArgumentParser()
    adapter_sync.add_apply_argument(parser)

    assert parser.parse_args([]).apply is False
    assert parser.parse_args(["--apply"]).apply is True
    assert adapter_sync.secret_from_env("SE_EXAMPLE_TOKEN", {"SE_EXAMPLE_TOKEN": SECRET}) == SECRET
    with pytest.raises(SystemExit, match="SE_EXAMPLE_TOKEN is not set"):
        adapter_sync.secret_from_env("SE_EXAMPLE_TOKEN", {})
