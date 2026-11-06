"""se_plugin.py generates the Copilot and Claude Code layouts from src/ and refuses hand edits."""
from pathlib import Path
import importlib.util
import json
import re
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("se_plugin", ROOT / "scripts" / "se_plugin.py")
se_plugin = importlib.util.module_from_spec(_spec)
sys.modules["se_plugin"] = se_plugin
_spec.loader.exec_module(se_plugin)
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


@pytest.fixture(scope="module")
def checkout(tmp_path_factory):
    """A copy of the sources and their generated layouts, built once."""
    root = tmp_path_factory.mktemp("se")
    shutil.copy(ROOT / "se.toml", root)
    shutil.copytree(ROOT / "src", root / "src")
    shutil.copytree(ROOT / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / ".github" / "ISSUE_TEMPLATE", root / ".github" / "ISSUE_TEMPLATE")
    for name in ("README.md", "AGENTS.md"):
        shutil.copy(ROOT / name, root)
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    return root


def test_the_committed_layouts_match_their_source(capsys):
    assert se_plugin.main(["check"]) == 0, capsys.readouterr().err


def test_check_refuses_a_hand_edit_and_passes_after_rebuild(checkout, capsys):
    generated = checkout / "agents" / "worker.md"
    original = generated.read_bytes()
    generated.write_bytes(original + b"\nedited by hand\n")
    assert se_plugin.main(["check", "--root", str(checkout)]) == 1
    err = capsys.readouterr().err
    assert "agents/worker.md: differs from its source (edited by hand?)" in err
    assert "python scripts/se_plugin.py build" in err
    assert se_plugin.main(["build", "--root", str(checkout)]) == 0
    assert generated.read_bytes() == original
    assert se_plugin.main(["check", "--root", str(checkout)]) == 0


def test_check_refuses_a_generated_file_without_source_and_build_removes_it(checkout, capsys):
    stray = checkout / ".github" / "skills" / "stray" / "SKILL.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("---\nname: stray\n---\n", encoding="utf-8")
    assert se_plugin.main(["check", "--root", str(checkout)]) == 1
    assert ".github/skills/stray/SKILL.md: not generated from src/" in capsys.readouterr().err
    assert se_plugin.main(["build", "--root", str(checkout)]) == 0
    assert not stray.parent.exists()
    assert se_plugin.main(["check", "--root", str(checkout)]) == 0


def test_each_agent_and_skill_has_one_source_and_both_layouts(checkout):
    for role in ("se", "integrator", "worker"):
        assert (checkout / "src" / "agents" / f"{role}.md").is_file()
        assert (checkout / ".github" / "agents" / f"{role}.agent.md").is_file()
        assert (checkout / "agents" / f"{role}.md").is_file()
    for skill in (checkout / "src" / "skills").iterdir():
        assert (checkout / ".github" / "skills" / skill.name / "SKILL.md").is_file()
        assert (checkout / "skills" / skill.name / "SKILL.md").is_file()


def test_front_matter_keys_go_only_to_their_layout(checkout):
    copilot = (checkout / ".github" / "agents" / "worker.agent.md").read_text(encoding="utf-8")
    claude = (checkout / "agents" / "worker.md").read_text(encoding="utf-8")
    copilot_front, claude_front = copilot.split("---")[1], claude.split("---")[1]
    assert "tools: ['execute', 'read', 'edit', 'search', 'send_message']" in copilot_front
    assert "disallowedTools" not in copilot_front
    assert "disallowedTools: AskUserQuestion" in claude_front
    assert "tools:" not in claude_front and "copilot." not in claude_front
    assert "name: se\n" in (checkout / "agents" / "se.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("layout", (".github/agents", ".github/skills", "agents", "skills"))
def test_relative_links_resolve_in_each_layout(checkout, layout):
    for path in (checkout / layout).rglob("*.md"):
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if "://" not in target:
                assert (path.parent / target).exists(), f"{path.relative_to(checkout)}: {target}"


def test_the_plugin_manifests_install_the_whole_checkout_and_bootstrap_it(checkout):
    plugin = json.loads((checkout / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((checkout / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "se" and plugin["version"] == "1.0.0"  # se.toml [project] version
    assert marketplace["name"] == "se"
    assert marketplace["plugins"] == [{"name": "se", "source": "./", "description": plugin["description"]}]
    hook = plugin["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["command"] == 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh" || true'
    assert (ROOT / "scripts" / "bootstrap.sh").is_file()


def test_the_readme_installs_the_plugin_the_marketplace_declares():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8").split("## Install", 1)[1].split("\n## ", 1)[0]
    plugin = marketplace["plugins"][0]["name"]
    assert f"`claude plugin install {plugin} --marketplace mb-89/SE#se`" in readme
    assert f"`{plugin}@{marketplace['name']}`" in readme
    for agent in sorted(path.stem for path in (ROOT / "src" / "agents").glob("*.md")):
        assert f"`{plugin}:{agent}`" in readme
