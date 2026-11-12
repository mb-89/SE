"""Dangling references: se's own text names no missing file and no undefined subcommand
(`scripts/references.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import references  # noqa: E402

TOOL = '''import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    group = commands.add_parser("group").add_subparsers(dest="action", required=True)
    group.add_parser("leaf")
    return parser.parse_args(argv)
'''


def scanned_texts(root: Path) -> list[Path]:
    """The texts the repository check scans: agents, skills (the rule book among them), README.md
    and AGENTS.md."""
    sources = [path for folder in ("src/agents", "src/skills")
               for path in sorted((root / folder).rglob("*.md"))]
    return [*sources, root / "README.md", root / "AGENTS.md"]


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text(TOOL, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.md").write_text("# Real\n", encoding="utf-8")
    return tmp_path


def test_the_scanned_texts_include_the_rule_book() -> None:
    assert ROOT / "src" / "skills" / "work-model" / "references" / "rules.md" in scanned_texts(ROOT)


def test_se_names_no_missing_file_and_no_undefined_subcommand() -> None:
    found = [f"{path.relative_to(ROOT).as_posix()} {finding}"
             for path in scanned_texts(ROOT)
             for finding in references.dangling(path.read_text(encoding="utf-8"), ROOT, path)]
    assert not found, "\n".join(found)


def test_a_dead_path_and_an_unknown_subcommand_fail(repository: Path) -> None:
    source = repository / "README.md"
    text = ("See [real](src/real.md), [gone](src/gone.md#part) and `src/missing.md`.\n"
            "Run `scripts/tool.py run`, then `scripts/tool.py jump --fast`.\n"
            "\n```sh\nuv run python scripts/tool.py group nothing\n```\n")
    found = references.dangling(text, repository, source)
    assert [(finding.line, finding.item) for finding in found] == [
        (1, "src/gone.md#part"), (1, "src/missing.md"), (2, "tool.py jump"),
        (5, "tool.py group nothing")]
    assert "defines group, run" in str(found[2])


def test_code_spans_wrap_across_lines(repository: Path) -> None:
    found = references.dangling("Run `tool.py\njump` now.\n", repository)
    assert [(finding.line, finding.item) for finding in found] == [(1, "tool.py jump")]


def test_placeholders_anchors_urls_and_flags_pass(repository: Path) -> None:
    text = ("[url](https://example.com/x.md), [anchor](#here), [real](src/real.md#top), "
            "`src/<name>.md`, `tests/*.py`, `scripts/tool.py --help`, `scripts/tool.py <command>`, "
            "`<se>/scripts/tool.py group leaf`, `src/real.md:3`, `scripts/`\n"
            "A link in code is no link: `[x](gone.md)`.\n")
    assert references.dangling(text, repository, repository / "README.md") == []


def test_without_paths_only_commands_and_scripts_are_checked(repository: Path) -> None:
    text = "`src/missing.md`, [gone](gone.md), `scripts/gone.py`, `tool.py jump`\n"
    found = references.dangling(text, repository, repository / "README.md", paths=False)
    assert [finding.item for finding in found] == ["scripts/gone.py", "tool.py jump"]


def test_the_parser_is_the_registry_and_its_main_never_runs(tmp_path: Path) -> None:
    script = tmp_path / "loud.py"
    script.write_text(TOOL.replace("    return parser.parse_args(argv)",
                                   "    args = parser.parse_args(argv)\n"
                                   "    raise SystemExit('ran')"), encoding="utf-8")
    assert references.command_tree(script) == {"run": {}, "group": {"leaf": {}}}
