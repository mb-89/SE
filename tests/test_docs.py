"""The documentation builds from docs.md with obs, and any obs warning fails it (README "Documentation")."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs.py"
# The decision skill's worked example, the one note that asks for a verdict (its decks build from it).
WORKED_EXAMPLE = ROOT / "src" / "skills" / "decision" / "references" / "decision-deck.md"
NOTES = "src/skills/work-model/references/"
BOOK = ROOT / NOTES / "rules.md"
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs  # noqa: E402
# Every build syncs the obs module into the checkout; the fixture `obs` (conftest.py) prepares it first,
# once at a time.


def build(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)


def nodes(items):
    for item in items:
        if isinstance(item, dict):
            yield item
            yield from nodes(item.get("children") or [])


def snapshot() -> dict[Path, bytes]:
    """The notes a build reads and could write: the manifest, the top-level notes and ``src``."""
    return {path: path.read_bytes() for path in [*ROOT.glob("*.md"), *(ROOT / "src").rglob("*")]
            if path.is_file()}


def test_documentation_builds_without_warnings(tmp_path, obs):
    destination = tmp_path / "index.html"
    before = snapshot()
    result = build("--destination", str(destination), "--document", str(tmp_path / "docs.json"))
    assert result.returncode == 0, result.stderr + result.stdout
    assert snapshot() == before
    assert destination.stat().st_size > 0
    # The page asks for no verdict: obs ships neither its bless nor its answers feature, whose canary
    # it writes only for an included feature (obs's adapters/html/spec/artifact-ui.md).
    page = destination.read_text(encoding="utf-8")
    assert 'id="canary-bless"' not in page
    assert 'id="canary-answers"' not in page
    # It opens in the reader's system theme: System is obs's default, so docs.md declares none.
    assert '<html lang="en" data-theme="system"' in page
    # It was the copy that changed: the worked example still asks, for the decks built from it.
    assert WORKED_EXAMPLE.read_text(encoding="utf-8").startswith("---\nobs: {bless: pending}\n---\n")
    # The rule book shows as one table of its rules, each rule its own note that rule links open.
    text = BOOK.read_text(encoding="utf-8")
    rules = re.findall(r"^### (\S+) (.+?)\s*$", text, re.MULTILINE)
    sections = re.findall(r"^## ([a-z0-9-]+: .+?)\s*$", text, re.MULTILINE)
    document = json.loads((tmp_path / "docs.json").read_text(encoding="utf-8"))
    titles = {chapter["title"] for chapter in document["chapters"]}
    assert {f"{rule} {name}" for rule, name in rules} <= titles
    chapter = next(chapter for chapter in document["chapters"] if chapter["title"] == "Rule book")
    tables = [node for node in nodes(chapter["content"]) if node["type"] == "bases"]
    assert len(tables) == 1
    view = tables[0]["attrs"]["spec"]["views"][0]
    assert view["groupBy"]["property"] == "section"
    assert view["obsHtml"]["groupOrder"] == sections
    assert view["obsHtml"]["detailFields"] == []
    headings = ["".join(text.get("text", "") for text in node["children"])
                for node in nodes(chapter["content"]) if node["type"] == "section"]
    assert not [heading for heading in headings if re.match(r"\S+-\d{3,} ", heading)]
    ids = {rule for rule, _ in rules}
    named = [link["href"] for link in document["links"]
             if re.search(r"rules\.md#[a-z0-9-]+-\d{3}|(?:^|/)[a-z0-9-]+-\d{3,}\.md$", link["href"])]
    assert named
    assert [href for href in named if href.removeprefix(NOTES).removesuffix(".md") not in ids
            or not href.startswith(NOTES)] == []


def test_a_destination_inside_the_manifest_folder_is_refused_before_any_copy(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "docs.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    inside = vault / "site" / "index.html"
    result = build("--source", str(vault / "docs.md"), "--destination", str(inside))
    assert result.returncode == 2, result.stderr + result.stdout
    assert str(inside) in result.stderr and str(vault) in result.stderr
    assert sorted(path.name for path in vault.iterdir()) == ["docs.md"]


def test_a_rule_note_that_would_overwrite_a_file_fails_the_build_naming_it(tmp_path, obs):
    vault = tmp_path / "vault"
    references = vault / NOTES
    references.mkdir(parents=True)
    (references / "rules.md").write_text(
        "# Rules\n\n## gen: everything\n\n### gen-001 A rule\n\nOne sentence.\n", encoding="utf-8")
    (references / "gen-001.md").write_text("mine\n", encoding="utf-8")
    (vault / "docs.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    result = build("--source", str(vault / "docs.md"), "--destination", str(tmp_path / "out.html"))
    assert result.returncode == 1, result.stderr + result.stdout
    assert f"{NOTES}gen-001.md" in result.stderr
    assert {path: path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before


def test_a_link_to_a_rule_heading_opens_the_rule_note_and_others_stay(tmp_path):
    vault = tmp_path / "vault"
    references = vault / NOTES
    references.mkdir(parents=True)
    (references / "rules.md").write_text(
        "# Rules\n\n## gen: everything\n\nAbout it.\n\n### gen-001 A rule\n\nOne sentence.\n",
        encoding="utf-8")
    (vault / "README.md").write_text(
        f"[a]({NOTES}rules.md#gen-001-a-rule) [b]({NOTES}rules.md#gen-everything) [c]({NOTES}rules.md)\n",
        encoding="utf-8")
    build_docs.rule_table(vault)
    assert (vault / "README.md").read_text(encoding="utf-8") == (
        f"[a]({NOTES}gen-001.md) [b]({NOTES}rules.md#gen-everything) [c]({NOTES}rules.md)\n")
    assert (references / "gen-001.md").read_text(encoding="utf-8").endswith("\nOne sentence.\n")
    assert "```base" in (references / "rules.md").read_text(encoding="utf-8")


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
