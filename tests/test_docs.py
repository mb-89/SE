"""The documentation builds from docs.md with obs, and any obs warning fails it (README "Documentation")."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs.py"


def build(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)


def test_documentation_builds_without_warnings(tmp_path):
    destination = tmp_path / "index.html"
    result = build("--destination", str(destination))
    assert result.returncode == 0, result.stderr + result.stdout
    assert destination.stat().st_size > 0


def test_a_missing_note_fails_the_build(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Chapter\n\nSee [[no-such-note]].\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "no-such-note" in result.stderr


def test_a_paragraph_over_obs_default_limit_fails_the_build(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    long_paragraph = " ".join(["word"] * 100)  # six lines at 80 characters, over obs's default of five
    (vault / "chapter.md").write_text(f"# Chapter\n\n{long_paragraph}\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n\n- [[chapter|Chapter]]\n", encoding="utf-8")
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert "long paragraph" in result.stderr
