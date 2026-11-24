"""SE's manual as the tests read it: README.md, the one-page landing (SE#1796), and the pages under
docs/ its sections moved to, which se.toml's `authored_content` names."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The manual's pages under docs/, in se.toml's order.
DOCS_PAGES = [ROOT / entry for entry in tomllib.loads((ROOT / "se.toml").read_text(
    encoding="utf-8"))["project"]["authored_content"] if entry.startswith("docs/")]
#: README.md and every page of the manual.
PAGES = [ROOT / "README.md", *DOCS_PAGES]


def page(name: str) -> str:
    """The text of one page of the manual, `docs/<name>.md`."""
    return (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")


def text() -> str:
    """The whole manual, its pages joined in order."""
    return "\n".join(path.read_text(encoding="utf-8") for path in PAGES)
