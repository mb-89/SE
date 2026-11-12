"""se_plugin.py generates the Copilot and Claude Code layouts from src/ and refuses hand edits."""
from pathlib import Path
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib

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
    shutil.copy(ROOT / ".github" / "pull_request_template.md", root / ".github")
    for name in ("README.md", "AGENTS.md"):
        shutil.copy(ROOT / name, root)
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    return root


def test_the_committed_layouts_match_their_source(capsys):
    assert se_plugin.main(["check"]) == 0, capsys.readouterr().err


def suite_run(checkout: Path) -> subprocess.CompletedProcess:
    """A pytest run in the copy, with se's conftest.py and one probe test, as the suite runs."""
    shutil.copytree(ROOT / "tests", checkout / "tests", dirs_exist_ok=True,
                    ignore=lambda folder, names: [name for name in names if name != "conftest.py"])
    (checkout / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (checkout / "tests" / "test_probe.py").write_text(
        "from pathlib import Path\n"
        "def test_the_layout_has_the_change():\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    for layout in ('skills', '.github/skills'):\n"
        "        text = (root / layout / 'work-model' / 'SKILL.md').read_text(encoding='utf-8')\n"
        "        assert 'unbuilt change' in text\n", encoding="utf-8")
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "tests/test_probe.py"],
                          cwd=checkout, capture_output=True, text=True, check=False)


def test_the_suite_builds_an_unbuilt_source_change_before_its_tests(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "se.toml", tmp_path)
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 0
    source = tmp_path / "src" / "skills" / "work-model" / "SKILL.md"
    source.write_text(source.read_text(encoding="utf-8") + "\nAn unbuilt change.\n", encoding="utf-8")
    assert se_plugin.differences(tmp_path)
    result = suite_run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "se_plugin.py build: wrote skills/work-model/SKILL.md" in result.stdout
    assert se_plugin.differences(tmp_path) == []


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
    version = tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert plugin["name"] == "se" and plugin["version"] == version  # se.toml [project] version
    assert marketplace["name"] == "se"
    assert marketplace["plugins"] == [{"name": "se", "source": "./", "description": plugin["description"]}]
    hook = plugin["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["command"] == 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh" --hook || true'
    assert (ROOT / "scripts" / "bootstrap.sh").is_file()


def test_the_readme_installs_the_plugin_the_marketplace_declares():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8").split("## Install", 1)[1].split("\n## ", 1)[0]
    plugin = marketplace["plugins"][0]["name"]
    assert f"`claude plugin install {plugin} --marketplace mb-89/SE`" in readme
    assert f"`{plugin}@{marketplace['name']}`" in readme
    for agent in sorted(path.stem for path in (ROOT / "src" / "agents").glob("*.md")):
        assert f"`{plugin}:{agent}`" in readme


def test_the_cloud_install_clones_the_plugin_and_each_role_prompt_names_a_built_file(checkout):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cloud = readme.split("### Claude Code cloud\n", 1)[1].split("\n## ", 1)[0]
    script = cloud.split("```bash\n", 1)[1].split("```", 1)[0]
    assert "git clone --depth 1 https://github.com/mb-89/SE ~/.claude/skills/se ||" in script
    assert "-b se" not in readme and "#se`" not in readme  # se replaced main: no command names it
    row = next(line for line in readme.splitlines() if line.startswith("| Claude Code cloud"))
    for kind in ("agents", "skills"):
        for name in sorted(path.stem for path in (ROOT / "src" / kind).iterdir()):
            assert f"`se:{name}`" in row, name
    work_model = (ROOT / "src" / "skills" / "work-model" / "SKILL.md").read_text(encoding="utf-8")
    prompts = re.findall(r"Act as the \w+ agent defined in <se>/(\S+?\.md)", cloud + work_model)
    assert {"github/agents/se.agent.md", "github/agents/worker.agent.md"} <= {p.lstrip(".") for p in prompts}
    for path in prompts:
        assert (checkout / path).is_file(), path


@pytest.mark.parametrize("named", ("`uv run python scripts/deck.py build`", "<se checkout>/scripts/se_start.py",
                                   "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh"))
def test_a_source_naming_a_script_without_ses_root_is_refused(checkout, capsys, named):
    source = checkout / "src" / "skills" / "decision" / "SKILL.md"
    original = source.read_text(encoding="utf-8")
    source.write_text(original + f"\nRun {named}.\n", encoding="utf-8")
    try:
        assert se_plugin.main(["check", "--root", str(checkout)]) == 2
        assert "src/skills/decision/SKILL.md:" in capsys.readouterr().err
        assert se_plugin.main(["build", "--root", str(checkout)]) == 2
    finally:
        source.write_text(original, encoding="utf-8")


def test_a_script_under_ses_root_a_relative_link_and_another_folder_pass(checkout):
    source = checkout / "src" / "skills" / "decision" / "SKILL.md"
    original = source.read_text(encoding="utf-8")
    source.write_text(original + "\nRun `uv run python <se>/scripts/deck.py`, see "
                      "[it](../../../scripts/deck.py) and `src/scripts/`.\n", encoding="utf-8")
    try:
        assert se_plugin.main(["build", "--root", str(checkout)]) == 0
    finally:
        source.write_text(original, encoding="utf-8")
        assert se_plugin.main(["build", "--root", str(checkout)]) == 0
