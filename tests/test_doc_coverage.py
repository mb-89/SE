"""SE's guides against the documentation they make up: two checks, files read only (no git, no
network, no process).

- Named or left out: each authored note (`NOTES`) is a chapter, named by a `[[...]]` entry of
  docs.md, the manifest README "Documentation" owns, or a key of `UNLISTED` with a one-line reason,
  so a new note stays out of the documentation only by a stated decision. `UNLISTED` stays true: a
  key docs.md names, or one that is no scanned note, fails. `drafts/` (kept out of docs.md by
  `tests/test_skill_drafts.py`), the generated layouts, the template and story folders and the
  evals' prompts are no authored notes.
- Links and anchors: every relative Markdown link in the guides (`LINKED`) resolves, and its
  `#anchor` is one of the target's headings, by the rule and the `anchors()` of
  `tests/test_agent_definitions.py`, which holds the agent and skill texts and the GitHub templates
  the same way.

Each check is a sweep over a tree root that returns its findings; a positive control proves each
on a planted case before the real tree's silence counts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from positive_control import positive_control
from test_agent_definitions import ANCHOR_LINK, anchors

ROOT = Path(__file__).resolve().parents[1]

NOTES = ("src/agents/*.md", "src/skills/**/*.md", "docs/**/*.md", "components/README.md")
LINKED = ("README.md", "AGENTS.md", "docs/**/*.md", "components/README.md", "tests/evals/README.md")

UNLISTED = {
    "src/agents/reviewer.md": "the reviewer's role definition; the other three roles are chapters, "
                              "so whether it joins them is the owner's call",
    "src/agents/retro.md": "the retro agent's role definition, as the reviewer's: whether it "
                           "joins the chapters is the owner's call",
    "src/skills/catch-up/references/integrator-prompt.md": "a prompt template the catch-up skill fills",
    "docs/copilot.md": "the owner's guide to installing SE into Copilot, linked from README",
    "docs/components.md": "the design of finding components, linked from docs/go-core.md",
    "docs/go-core.md": "the Go core's design, linked from README and AGENTS.md",
    "docs/method.md": "the design of SE's method staying in SE, linked from docs/components.md",
    "docs/guidance.md": "the guidance system's design, read by the workers of its packages",
    "docs/templates.md": "the template system's design, linked from README \"Templates\"",
    "docs/doors/copilot.md": "outside facts for whoever changes the Copilot layout",
    "docs/doors/mcp.md": "outside facts for whoever changes the MCP door",
    "docs/harvest-2026-11.md": "a dated record",
    "docs/obs-3-range-trial-2026-11.md": "a dated record",
    "docs/retro-2026-11-12-to-13.md": "a dated record",
    "docs/retro-2026-11-13-to-24.md": "a dated record",
    "components/README.md": "a guide read beside SE's Go components",
}

ENTRY = re.compile(r"\[\[([^\]]+)\]\]")


def files(root: Path, patterns: tuple[str, ...]) -> list[str]:
    return sorted({path.relative_to(root).as_posix() for pattern in patterns
                   for path in root.glob(pattern) if path.is_file()})


def chapters(root: Path) -> set[str]:
    """The notes docs.md names: each entry's part before `|` or `#`, `.md` added where it lacks it."""
    names = set()
    for entry in ENTRY.findall((root / "docs.md").read_text(encoding="utf-8")):
        name = re.split(r"[|#]", entry, maxsplit=1)[0].strip()
        names.add(name if name.endswith(".md") else f"{name}.md")
    return names


def coverage(root: Path, unlisted: Mapping[str, str] = UNLISTED) -> list[str]:
    """Each scanned note neither docs.md nor `unlisted` names, and each `unlisted` key that docs.md
    names or that is no scanned note."""
    notes, named = files(root, NOTES), chapters(root)
    findings = [f"{note}: neither a chapter nor left out; add it to docs.md as a chapter, or to "
                f"UNLISTED with its reason" for note in notes if note not in named and note not in unlisted]
    findings += [f"UNLISTED {key}: docs.md names it" for key in unlisted if key in named]
    findings += [f"UNLISTED {key}: no scanned note" for key in unlisted if key not in notes]
    return findings


def links(root: Path) -> list[tuple[str, str]]:
    """(file, link) for each relative link whose target or `#anchor` is missing."""
    found = []
    for name in files(root, LINKED):
        path = root / name
        for link in ANCHOR_LINK.findall(path.read_text(encoding="utf-8")):
            if "://" in link or not link:
                continue
            target, _, anchor = link.partition("#")
            resolved = (path.parent / target).resolve() if target else path
            if not resolved.exists() or (anchor and not (resolved.is_file() and anchor in anchors(resolved))):
                found.append((name, link))
    return found


def tree(tmp_path: Path, docs: str = "- [[README|se]]\n- [[src/agents/se.md|SE]]\n") -> Path:
    (tmp_path / "src" / "agents").mkdir(parents=True)
    (tmp_path / "docs.md").write_text(docs, encoding="utf-8")
    (tmp_path / "README.md").write_text("# se\n\n## Install\n\n[here](#install)\n", encoding="utf-8")
    (tmp_path / "src" / "agents" / "se.md").write_text("# SE\n\n[install](../../README.md#install)\n",
                                                       encoding="utf-8")
    return tmp_path


def test_coverage_finds_a_planted_note(tmp_path):
    root = tree(tmp_path)
    positive_control("coverage", lambda root: coverage(root, {}), root, "src/agents/new.md", "# New\n",
                     "src/agents/new.md: neither a chapter nor left out; add it to docs.md as a chapter, "
                     "or to UNLISTED with its reason")


def test_links_find_a_planted_missing_heading(tmp_path):
    root = tree(tmp_path)
    positive_control("links", links, root, "docs/note.md", "[x](../README.md#no-such-heading)\n",
                     ("docs/note.md", "../README.md#no-such-heading"))


def test_links_name_a_missing_heading_in_readme(tmp_path):
    root = tree(tmp_path)
    (root / "README.md").write_text("# se\n\n[x](README.md#no-such-heading)\n", encoding="utf-8")
    assert links(root) == [("README.md", "README.md#no-such-heading")]


def test_coverage_names_each_failure(tmp_path):
    root = tree(tmp_path)
    (root / "src" / "agents" / "reviewer.md").write_text("# Reviewer\n", encoding="utf-8")
    assert coverage(root, {}) == ["src/agents/reviewer.md: neither a chapter nor left out; add it to "
                                  "docs.md as a chapter, or to UNLISTED with its reason"]
    assert coverage(root, {"src/agents/reviewer.md": "why"}) == []
    assert coverage(root, {"src/agents/reviewer.md": "why", "docs/gone.md": "why"}) == [
        "UNLISTED docs/gone.md: no scanned note"]
    assert coverage(root, {"src/agents/reviewer.md": "why", "src/agents/se.md": "why"}) == [
        "UNLISTED src/agents/se.md: docs.md names it"]


def test_without_the_reviewer_entry_the_real_tree_fails():
    unlisted = {key: reason for key, reason in UNLISTED.items() if key != "src/agents/reviewer.md"}
    assert [finding.split(":")[0] for finding in coverage(ROOT, unlisted)] == ["src/agents/reviewer.md"]


def test_unlisted_reasons_are_one_line():
    assert [key for key, reason in UNLISTED.items() if not reason.strip() or "\n" in reason] == []


def test_every_note_is_a_chapter_or_left_out_with_a_reason():
    assert coverage(ROOT) == []


def test_every_guide_link_and_anchor_resolves():
    assert links(ROOT) == []
