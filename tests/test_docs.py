"""The documentation builds from docs.md with obs, and any obs warning fails it (README "Documentation")."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs.py"
# The decision skill's worked example, the one note that asks for a verdict (its decks build from it).
WORKED_EXAMPLE = ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md"
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402
# Every build syncs the obs module into the checkout; the fixture `obs` (conftest.py) prepares it first,
# once at a time.


def build(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)


def test_documentation_builds_without_warnings(tmp_path, obs):
    destination = tmp_path / "index.html"
    result = build("--destination", str(destination))
    assert result.returncode == 0, result.stderr + result.stdout
    assert destination.stat().st_size > 0
    # The page asks for no verdict: obs ships neither its bless nor its answers feature, whose canary
    # it writes only for an included feature (obs's adapters/html/spec/artifact-ui.md).
    page = destination.read_text(encoding="utf-8")
    assert 'id="canary-bless"' not in page
    assert 'id="canary-answers"' not in page
    # It was the copy that changed: the worked example still asks, for the decks built from it.
    assert WORKED_EXAMPLE.read_text(encoding="utf-8").startswith("---\nobs: {bless: pending}\n---\n")


def test_a_destination_inside_the_manifest_folder_is_refused_before_any_copy(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "docs.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    inside = vault / "site" / "index.html"
    result = build("--source", str(vault / "docs.md"), "--destination", str(inside))
    assert result.returncode == 2, result.stderr + result.stdout
    assert str(inside) in result.stderr and str(vault) in result.stderr
    assert sorted(path.name for path in vault.iterdir()) == ["docs.md"]


def test_no_note_of_the_copy_asks_for_a_verdict():
    assert build_docs.without_verdict("---\nobs: {bless: pending}\n---\n\n# T\n") == "\n# T\n"
    assert build_docs.without_verdict("---\ntitle: t\nobs: {bless: pending, k: 1}\n---\n") == (
        "---\ntitle: t\nobs: {k: 1}\n---\n")
    assert build_docs.without_verdict("---\nobs:\n  bless:\n    a: 1\n  k: 2\ntitle: t\n---\nb") == (
        "---\nobs:\n  k: 2\ntitle: t\n---\nb")
    assert build_docs.without_verdict("---\nobs:\n  bless: pending\n---\nb") == "b"
    unchanged = "---\ntitle: t\nobs: {other: 1}\n---\nb"
    assert build_docs.without_verdict(unchanged) == unchanged


def test_a_missing_note_fails_the_build(tmp_path, obs):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Chapter\n\nSee [[no-such-note]].\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "no-such-note" in result.stderr


def test_a_paragraph_over_obs_default_limit_fails_the_build(tmp_path, obs):
    vault = tmp_path / "vault"
    vault.mkdir()
    long_paragraph = " ".join(["word"] * 100)  # six lines at 80 characters, over obs's default of five
    (vault / "chapter.md").write_text(f"# Chapter\n\n{long_paragraph}\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "long paragraph" in result.stderr
