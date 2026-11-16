"""The GitHub component's names as docs/go-core.md "GitHub in the cloud" names them: every family the
doc names is one the component declares (kern/components/github/github.go), every family it declares
the doc names, and the doc's example key is the key a read of it takes (se_relay.key, which
tests/beside_se_relay.py reads from the real core)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import se_relay  # noqa: E402


def section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_the_docs_github_names_are_the_components() -> None:
    doc = section((ROOT / "docs" / "go-core.md").read_text(encoding="utf-8"), "GitHub in the cloud")
    named = set(re.findall(r"`github/([a-z-]+)(?:/<key>)?`", doc))
    source = (ROOT / "kern" / "components" / "github" / "github.go").read_text(encoding="utf-8")
    declared = set(re.findall(r'index\.Family\("([a-z-]+)"', source))
    assert declared, "github.go declares its families with index.Family"
    assert named == declared, (sorted(named - declared), sorted(declared - named))


def test_the_docs_example_key_is_the_key_a_read_takes() -> None:
    doc = section((ROOT / "docs" / "go-core.md").read_text(encoding="utf-8"), "GitHub in the cloud")
    found = re.search(r"SE's issue (\d+) stands at `github/issues/([^`]+)`", doc)
    assert found, "the doc names one issue's snapshot name as its example"
    assert found[2] == se_relay.key("mb-89", "SE", int(found[1])), found[2]
