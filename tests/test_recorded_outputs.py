"""Whole outputs no other test pins, held to their recordings in tests/recorded/ (tests/recorded.py).

One test per recording; a later issue registers its off-state output with one more line in RECORDINGS.
The helper's own behaviour runs on a temporary copy of a recording.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import deck
import public_check
import recorded as r
import se_doctor
import test_se_doctor
import timeline

WORKED_EXAMPLE = r.ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md"
TIMELINE_FIXTURE = r.ROOT / "tests" / "fixtures" / "timeline-planned.json"


def decision_deck(tmp_path: Path) -> str:
    """The obs Document of the deck `deck.py build` makes from the decision skill's worked example (the
    deck's HTML is obs-html's bundle around it, 0.8 MB of obs's own code)."""
    folder = tmp_path / "decisions"
    folder.mkdir()
    shutil.copy(WORKED_EXAMPLE, folder / WORKED_EXAMPLE.name)
    (folder / "manifest.md").write_text("---\ntitle: Decisions\n---\n\n- [[decision-deck|Decision deck]]\n",
                                        encoding="utf-8")
    destination = tmp_path / "deck.html"
    assert deck.build(folder, destination) == 0
    return _drawn(deck.document_path(destination).read_text(encoding="utf-8"))


DRAWN = "<svg the build machine drew from the source>"
# A component that built the deck (obs-html) is recorded by name and kind: its version and commit are
# whichever release the build machine installed (`obs-components install obs-html`).
INSTALLED_VERSION = "<the version installed on the build machine>"
INSTALLED_COMMIT = "<its commit>"


def _drawn(document: str) -> str:
    """``document`` with each diagram's drawn ``svg`` replaced by DRAWN once it is one: its size follows
    the machine's fonts (301 px high here, 299 on CI's runner), while its ``source`` is the note's own;
    and each component's version and commit by INSTALLED_VERSION and INSTALLED_COMMIT."""
    def walk(node):
        if isinstance(node, dict):
            if "source" in node and "svg" in node:
                assert node["svg"].startswith("<svg ") and node["svg"].endswith("</svg>"), node["svg"][:80]
                node["svg"] = DRAWN
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        return node
    found = walk(json.loads(document))
    for component in found.get("components", []):  # the release this machine installed
        component.update(version=INSTALLED_VERSION, commit=INSTALLED_COMMIT)
    return json.dumps(found, indent=2, ensure_ascii=False) + "\n"


def timeline_page(_: Path) -> str:
    """The notes obs builds the Timeline from, made from the tracked snapshot of planned days (the page is
    obs-html's bundle around them)."""
    files = timeline.vault(json.loads(TIMELINE_FIXTURE.read_text(encoding="utf-8")))
    return "".join(f"=== {path}\n{text}" for path, text in files.items())


def doctor_report(_: Path) -> str:
    """The doctor's default report on the clean box its own tests start from."""
    return se_doctor.render_text(se_doctor.diagnose(test_se_doctor.clean_facts()))


# name: what builds it from a tracked fixture. One line per registered output.
RECORDINGS = {
    "decision-deck": decision_deck,
    "timeline": timeline_page,
    "doctor": doctor_report,
}
NEEDS_OBS = {"decision-deck"}
# A recording obs builds runs obs-document, an outside program in obs's own environment (`uv run
# --project <obs>`, scripts/build_docs.py), so its test starts processes.
OBS_RUNS = pytest.mark.spawns("obs: the deck is obs-document's output, which runs in obs's own environment "
                              "(scripts/build_docs.py), an outside program SE's process cannot import")


@pytest.mark.parametrize("name", [pytest.param(name, marks=OBS_RUNS) if name in NEEDS_OBS else name
                                  for name in RECORDINGS])
def test_the_output_is_its_recording(name, tmp_path, request):
    if name in NEEDS_OBS:
        request.getfixturevalue("obs")
    r.recorded(name, RECORDINGS[name](tmp_path))


@pytest.mark.parametrize("name", RECORDINGS)
def test_a_recording_passes_the_public_check(name):
    text = (r.RECORDINGS / f"{name}.txt").read_text(encoding="utf-8")
    assert public_check.find(text, public_check.load_public_terms()) == []
    assert str(r.ROOT) not in text and r.ROOT.as_posix() not in text


def test_a_changed_recording_fails_with_its_diff_and_the_rewrite_command(tmp_path, monkeypatch):
    monkeypatch.delenv(r.VARIABLE, raising=False)
    text = doctor_report(tmp_path)
    copy = tmp_path / "doctor.txt"
    shutil.copy(r.RECORDINGS / "doctor.txt", copy)
    original = copy.read_text(encoding="utf-8")
    copy.write_text(original.replace("SE doctor", "SE Doctor", 1), encoding="utf-8")

    with pytest.raises(r.Differs) as failure:
        r.recorded("doctor", text, directory=tmp_path)
    message = str(failure.value)
    assert "-SE Doctor: 0 problems" in message and "+SE doctor: 0 problems" in message
    assert message.endswith("SE_RECORD=1 uv run pytest -q tests/test_recorded_outputs.py -k doctor")

    monkeypatch.setenv(r.VARIABLE, "1")
    r.recorded("doctor", text, directory=tmp_path)
    assert copy.read_text(encoding="utf-8") == original
    monkeypatch.delenv(r.VARIABLE)
    r.recorded("doctor", text, directory=tmp_path)


def test_a_missing_recording_names_the_command_that_records_it(tmp_path, monkeypatch):
    monkeypatch.delenv(r.VARIABLE, raising=False)
    with pytest.raises(r.Differs, match=r"no recording new\.txt .*SE_RECORD=1 uv run pytest .* -k new$"):
        r.recorded("new", "text\n", directory=tmp_path)
    assert not (tmp_path / "new.txt").exists()


@pytest.mark.parametrize(("name", "text", "expected"), [
    ("clock", "read at 2026-11-12T15:00:00+00:00 and 2026-11-12 15:00 UTC on 2026-11-12",
     "read at <time> and <time> on 2026-11-12"),
    ("session id", "session_01HPuFoHdKQZBroKjMW3CExe ended", "<session> ended"),
    ("checkout", str(r.ROOT / "scripts" / "x.py"), str(Path("<checkout>") / "scripts" / "x.py")),
])
def test_what_changes_from_run_to_run_is_a_named_substitution(name, text, expected):
    assert name in r.SUBSTITUTIONS
    assert r.normalise(text) == expected


def test_the_se_version_and_line_ends_are_normalised():
    version = r._version()
    assert version and r.normalise(f"SE {version}\r\n") == "SE <se-version>\n"


def test_a_home_of_one_part_cuts_no_path():
    assert r._paths(Path("/"), "~")("/usr/bin") == "/usr/bin"
