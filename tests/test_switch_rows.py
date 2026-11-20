"""The switch rows of the plugin, copilot and release groups (scripts/switches/): each row's default
is the state of what its real reader answers with nothing set."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import pytest

import se_switches  # scripts/ is on the path (tests/conftest.py)

ROOT = Path(__file__).resolve().parents[1]


def row(name: str) -> se_switches.Switch:
    return next(switch for switch in se_switches.load().switches if switch.name == name)


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """A root whose se.toml is empty: `se_plugin._plugin_settings` always opens se.toml."""
    (tmp_path / "se.toml").write_text("", encoding="utf-8")
    return tmp_path


def test_the_copilot_switch_defaults_match_the_reader_without_se_toml(tmp_path):
    import copilot_guards

    settings = copilot_guards.settings(tmp_path)
    assert settings == {"refuse_stop": False, "start_sessions": True}
    for name, value in settings.items():
        switch = row(f"[copilot] {name}")
        assert switch.default == se_switches.state(switch, value) == ("on" if value else "off")


def test_the_plugin_build_settings_are_off_on_an_empty_se_toml(empty_project):
    import se_plugin

    assert se_plugin.root_mcp(empty_project) is False
    assert se_plugin.powershell_hooks(empty_project) == "bash"
    assert se_plugin.copilot_manifest(empty_project) == PurePosixPath(".github/plugin/plugin.json")
    assert row("[plugin] root_mcp").default == "off"
    for name, unset in (("[plugin] powershell_hooks", "bash"), ("[plugin] copilot_manifest", "github")):
        switch = row(name)
        assert switch.default == "off" and se_switches.state(switch, unset) == "off"


def test_release_by_workflow_is_off_without_se_toml(tmp_path):
    import work_tickets

    switch = row("[project] release")
    assert work_tickets.release_by_workflow(tmp_path) is False
    assert switch.default == "off" and se_switches.state(switch, "workflow") == "on"


def test_the_mcp_plugin_project_follows_the_shell_launcher():
    text = (ROOT / "scripts" / "se_mcp.sh").read_text(encoding="utf-8")
    assert re.search(r'"\$\{SE_MCP_PLUGIN_PROJECT:-\}" != off\b', text)
    switch = row("SE_MCP_PLUGIN_PROJECT")
    assert switch.default == "on" and not switch.fold
    assert se_switches.state(switch, "off") == "off"
    assert se_switches.state(switch, "OFF") == "on"
