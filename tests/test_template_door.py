"""The door to SE's Go template engine (scripts/template_door.py): each call runs `se template
<verb>` through the process door, the session's binary first, and builds the engine from SE's
components with `go run` where that binary is older than the verb or missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import template_door
from fake_processes import Answer


@pytest.fixture
def binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    named = tmp_path / "se-9.9.9"
    named.write_text("", encoding="utf-8")
    (tmp_path / ".se" / ".runtime").mkdir(parents=True)
    (tmp_path / ".se" / ".runtime" / "kern.path").write_text(f"{named}\n", encoding="utf-8")
    return named


def test_the_door_runs_the_sessions_binary_with_the_request_on_stdin(tmp_path, binary, fake_processes):
    fake_processes.on(lambda call: call.words[:3] == [str(binary), "template", "check"],
                      lambda call: Answer(0, json.dumps({"template": "work", "refused": False, "findings": [],
                                                         "asked": json.loads(call.stdin)})))
    answer = template_door.check("body", template="work", root=tmp_path)
    assert answer["asked"] == {"template": "work", "action": "", "body": "body"}
    assert fake_processes.calls[-1].words[3:] == ["--root", str(tmp_path)]


def test_a_binary_older_than_the_verb_hands_the_call_to_go_run_in_ses_components(tmp_path, binary, fake_processes):
    fake_processes.on(lambda call: call.words[:2] == [str(binary), "template"],
                      lambda call: Answer(2, "", 'se: no command "template"\n'))
    fake_processes.on("go", lambda call: Answer(0, json.dumps({"document": "# Filled\n"})))
    assert template_door.fill("retro-deck", {"title": "T"}, root=tmp_path) == "# Filled\n"
    ran = fake_processes.calls[-1]
    assert ran.words[:5] == ["go", "run", "./cmd/se", "template", "fill"]
    assert ran.cwd == template_door.ROOT / "components"


def test_a_refusal_raises_with_the_engines_reason(tmp_path, binary, fake_processes):
    fake_processes.on(lambda call: call.words[:2] == [str(binary), "template"],
                      lambda call: Answer(1, "", "se template fill: templates fill work: refused\n"))
    with pytest.raises(template_door.TemplateDoorError, match="templates fill work: refused"):
        template_door.fill("work", {}, root=tmp_path)


def test_the_binary_is_the_sessions_else_the_installed_one(tmp_path, binary, monkeypatch):
    assert template_door.binary(tmp_path) == str(binary)
    binary.unlink()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".se" / "bin").mkdir()
    (tmp_path / ".se" / "bin" / "se").write_text("", encoding="utf-8")
    assert template_door.binary(tmp_path) == str(tmp_path / ".se" / "bin" / "se")


def test_no_binary_at_all_hands_the_call_to_go_run(tmp_path, binary, fake_processes):
    def missing(call):
        raise FileNotFoundError(call.words[0])
    fake_processes.on(lambda call: call.words[:2] == [str(binary), "template"], missing)
    fake_processes.on("go", lambda call: Answer(0, json.dumps({"template": "", "refused": False, "findings": []})))
    assert template_door.check("free text", root=tmp_path)["refused"] is False
