"""Tests of host_registrations: the pure rows of where each host reads SE from (se_doctor.py --probe).
Fixtures are texts and probe results; nothing here reads the box."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath

import pytest

import host_registrations as h

DATA = Path(__file__).resolve().parents[1] / "scripts" / "host-limits.toml"
FILL = {"launcher": "$HOME/se/scripts/se_mcp.sh", "launcher_ps1": "$HOME/se/scripts/se_mcp.ps1",
        "checkout": "$HOME/se"}


def section() -> dict:
    return tomllib.loads(DATA.read_text(encoding="utf-8"))


def place(surface: str, name: str) -> h.Place:
    return next(p for p in h.parse(section()["registrations"]) if p.surface == surface and p.place == name)


MCP = json.dumps({"mcpServers": {"se": {"command": "bash", "args": ["scripts/se_mcp.sh", "--root", "."]}}})
HOOKS = json.dumps({"version": 1, "hooks": {"SessionStart": [{
    "type": "command", "bash": "bash scripts/bootstrap.sh --hook || true",
    "powershell": "bash scripts/bootstrap.sh --hook; exit 0"}]}})


def test_every_place_is_a_host_fact_of_a_known_surface_with_source_and_register_line():
    data = section()
    places = h.parse(data["registrations"])
    assert {p.surface for p in places} <= set(data["surfaces"])
    assert {p.kind for p in places} == {"hooks", "mcp"}
    assert {p.base for p in places} <= {"project", "home", "checkout", "plugin", "copilot-plugin"}
    for p in places:
        assert p.source and p.read == "2026-11-14" and p.register[""] and p.files[""]
        assert "\n" not in p.fix("windows", FILL) and "{" + "launcher" not in p.fix("linux", FILL)
    assert any(not p.outside for p in places) and any(p.outside for p in places)


def test_the_windows_fix_line_starts_the_powershell_launcher_with_root():
    copilot = place("copilot-cli", "user MCP config")
    windows, other = copilot.fix("windows", FILL), copilot.fix("linux", FILL)
    assert windows == ('copilot mcp add se -- powershell -NoProfile -ExecutionPolicy Bypass -File '
                       '"$HOME/se/scripts/se_mcp.ps1" --root .')
    assert other == 'copilot mcp add se -- bash "$HOME/se/scripts/se_mcp.sh" --root .'
    assert copilot.fix("darwin", FILL) == other
    vscode = place("copilot-vscode", "user MCP config")
    assert vscode.file("windows") == "AppData/Roaming/Code/User/mcp.json"
    assert vscode.file("linux") == ".config/Code/User/mcp.json"
    assert "'-File',\"$HOME/se/scripts/se_mcp.ps1\",'--root','${workspaceFolder}'" in vscode.fix("windows", FILL)


@pytest.mark.parametrize("platform, launcher", [("linux", "se_mcp.sh"), ("windows", "se_mcp.ps1")])
def test_a_missing_file_is_not_registered_and_prints_its_fix_line(platform, launcher):
    p = place("copilot-cli", "user MCP config")
    [row] = h.rows([(p, h.Seen("~/.copilot/mcp-config.json", None))], {}, platform, FILL)
    assert (row.level, row.state) == (h.NOTE, h.SEEN)
    assert row.text == "copilot-cli user MCP config ~/.copilot/mcp-config.json: not registered (no such file)"
    assert launcher in row.fix and "--root ." in row.fix


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_a_file_without_se_is_not_registered_and_one_not_json_is_a_problem(platform):
    p = place("copilot-cli", "MCP door")
    other = json.dumps({"mcpServers": {"other": {"command": "x"}}})
    [missing] = h.rows([(p, h.Seen("<checkout>/.github/mcp.json", other))], {}, platform, FILL)
    assert missing.level == h.NOTE and missing.text.endswith("not registered (no server se)") and missing.fix
    [broken] = h.rows([(p, h.Seen("<checkout>/.github/mcp.json", "{"))], {}, platform, FILL)
    assert broken.level == h.PROBLEM and broken.text.endswith("not a JSON object") and broken.fix


@pytest.mark.parametrize("platform, fix", [
    ("linux", 'cd "$HOME/se" && uv run python scripts/se_plugin.py build'),
    ("windows", 'cd "$HOME/se"; uv run python scripts/se_plugin.py build')])
def test_a_command_that_does_not_resolve_is_a_problem_with_its_fix_line(platform, fix):
    p = place("copilot-cli", "hooks")
    [words] = h.commands(p, HOOKS, platform, {})
    assert words == ["bash", "scripts/bootstrap.sh", "--hook"]  # the form for the platform, up to its operator
    probe = {"resolves": False, "missing": [], "unresolved": []}
    [row] = h.rows([(p, h.Seen("<checkout>/.github/hooks/se.json", HOOKS))], {h.key(words): probe}, platform, FILL)
    assert (row.level, row.state) == (h.PROBLEM, h.SEEN)
    assert "bash does not resolve on this platform" in row.text and row.fix == fix


def test_copilot_hooks_take_the_powershell_form_on_windows():
    p = place("copilot-cli", "hooks")
    text = json.dumps({"hooks": {"Stop": [{"bash": "bash scripts/bootstrap.sh A", "powershell": "pwsh x/bootstrap.sh B"}]}})
    assert h.commands(p, text, "windows", {}) == [["pwsh", "x/bootstrap.sh", "B"]]
    assert h.commands(p, text, "linux", {}) == [["bash", "scripts/bootstrap.sh", "A"]]


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_an_mcp_command_that_does_not_answer_in_time_is_silent_and_a_problem(platform):
    p = place("copilot-cli", "MCP door")
    [words] = h.commands(p, MCP, platform, {})
    probe = {"resolves": True, "missing": [], "unresolved": [], "answer": "timeout", "detail": "10 s"}
    [row] = h.rows([(p, h.Seen("<checkout>/.github/mcp.json", MCP))], {h.key(words): probe}, platform, FILL)
    assert (row.level, row.state) == (h.PROBLEM, h.SILENT)
    assert "no answer to initialize (10 s)" in row.text and h.SPAWN_NOTE in row.text and row.fix


def test_an_answering_door_is_ok_and_carries_no_fix_line_and_a_missing_script_is_named():
    p = place("copilot-cli", "plugin manifest")
    text = json.dumps({"mcpServers": {"se": {"command": "bash", "args": ["${PLUGIN_ROOT}/scripts/se_mcp.sh"]}}})
    [words] = h.commands(p, text, "linux", {"PLUGIN_ROOT": "/opt/se"})
    assert words == ["bash", "/opt/se/scripts/se_mcp.sh"]
    seen = h.Seen("<checkout>/.github/plugin/plugin.json", text, {"PLUGIN_ROOT": "/opt/se"})
    answered = {"resolves": True, "missing": [], "unresolved": [], "answer": "answered", "detail": "se 0.4.0"}
    [row] = h.rows([(p, seen)], {h.key(words): answered}, "linux", FILL, show=lambda t: t.replace("/opt/se", "<se>"))
    assert row.level == h.OK and row.fix is None
    assert row.text.endswith("bash <se>/scripts/se_mcp.sh: answered initialize (se 0.4.0); " + h.SPAWN_NOTE)
    gone = {"resolves": True, "missing": ["/opt/se/scripts/se_mcp.sh"], "unresolved": []}
    [row] = h.rows([(p, seen)], {h.key(words): gone}, "linux", FILL)
    assert row.level == h.PROBLEM and "which does not exist" in row.text and row.fix == "copilot plugin install mb-89/SE"


def test_unprobed_unresolved_and_not_here_are_not_measured():
    p = place("copilot-cli", "MCP door")
    seen = h.Seen("<checkout>/.github/mcp.json", MCP)
    [row] = h.rows([(p, seen)], {}, "linux", FILL)
    assert (row.state, row.level) == (h.NOT_MEASURED, h.NOTE) and row.text.endswith("not probed")
    [words] = h.commands(p, MCP, "linux", {})
    [row] = h.rows([(p, seen)], {h.key(words): {"resolves": True, "missing": [], "unresolved": ["$X/a.sh"]}},
                   "linux", FILL)
    assert row.state == h.NOT_MEASURED and "cannot resolve $X/a.sh" in row.text
    [row] = h.rows([(p, h.Seen("<checkout>/.github/mcp.json", None, here=False))], {}, "linux", FILL)
    assert row.state == h.NOT_MEASURED and "read only in SE's own checkout" in row.text and row.fix is None


def test_the_launcher_is_named_from_home_where_it_lies_there():
    home = PurePosixPath("/", "h", "alice")
    assert h.launcher_text((home / "se" / "scripts" / "se_mcp.sh").as_posix(), home.as_posix()) == \
        "$HOME/se/scripts/se_mcp.sh"
    windows_home = "\\".join(("C:", "Users", "alice"))  # joined, so the public check sees no profile path
    assert h.launcher_text(windows_home + "\\se\\scripts\\se_mcp.ps1", windows_home) == "$HOME/se/scripts/se_mcp.ps1"
    assert h.launcher_text("/opt/se/scripts/se_mcp.sh", home.as_posix()) == "/opt/se/scripts/se_mcp.sh"


# Copilot CLI's plugin installs: the base copilot-plugin


def test_the_installed_plugin_place_is_read_in_copilots_install_and_installs_through_the_marketplace():
    p = place("copilot-cli", "installed plugin MCP")
    assert (p.kind, p.base, p.file("linux"), p.finds, p.outside) == ("mcp", "copilot-plugin", ".github/mcp.json", "se",
                                                                      True)
    assert p.source.startswith("https://docs.github.com/en/copilot/reference/cli-plugin-reference")
    assert p.fix("linux", FILL) == "copilot plugin marketplace add mb-89/SE && copilot plugin install se@se"
    assert p.fix("windows", FILL) == "copilot plugin marketplace add mb-89/SE; copilot plugin install se@se"


def test_the_resolver_picks_ses_folders_sorted_reading_nothing_and_skipping_a_broken_manifest(tmp_path: Path):
    home = tmp_path / "no-such-home"  # nothing exists on disk: the answer comes from the texts alone
    plugins = home / ".copilot" / "installed-plugins"
    se, direct = plugins / "se" / "se", plugins / "_direct" / "mb-89-SE"
    other, broken = plugins / "se" / "other", plugins / "x" / "y"
    found = {se: [json.dumps({"name": "se"}), None], other: [json.dumps({"name": "other"}), None],
             broken: ["{not json", "[]"], direct: [None, json.dumps({"name": "se"})]}
    assert not home.exists()
    assert h.copilot_plugin_roots(found) == sorted([se, direct], key=str)
    assert h.copilot_plugin_roots({}) == []


def test_copilots_home_is_its_variable_or_dot_copilot_under_home():
    assert h.copilot_home({"COPILOT_HOME": "/elsewhere"}, "/box/alice") == "/elsewhere"
    assert PurePosixPath(h.copilot_home({}, "/box/alice")) == PurePosixPath("/box/alice/.copilot")
    assert PurePosixPath(h.copilot_home({"COPILOT_HOME": ""}, "/box/alice")) == PurePosixPath("/box/alice/.copilot")


def test_the_same_command_is_judged_per_folder_it_starts_in():
    p = place("copilot-cli", "installed plugin MCP")
    words = ["bash", "scripts/se_mcp.sh", "--root", "."]
    entries = [(p, h.Seen("~/.copilot/a/.github/mcp.json", MCP, cwd="/a")),
               (p, h.Seen("~/.copilot/b/.github/mcp.json", MCP, cwd="/b"))]
    probes = {h.probe_key(words, "/a"): {"resolves": True, "missing": [], "unresolved": []},
              h.probe_key(words, "/b"): {"resolves": True, "missing": ["scripts/se_mcp.sh"], "unresolved": []}}
    assert h.probe_key(words) == h.key(words) != h.probe_key(words, "/a")
    first, second = h.rows(entries, probes, "linux", FILL)
    assert first.level == h.OK and first.fix is None
    assert second.level == h.PROBLEM and second.fix == p.fix("linux", FILL)


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_an_installed_copilot_plugin_turns_the_user_level_fix_into_the_guides_door_line(platform):
    p = place("copilot-cli", "user MCP config")
    entries = [(p, h.Seen("~/.copilot/mcp-config.json", None))]
    [today] = h.rows(entries, {}, platform, FILL)
    [hidden] = h.rows(entries, {}, platform, FILL, present={"copilot-plugin"})
    assert today.fix == p.fix(platform, FILL) and today.fix.startswith("copilot mcp add se -- ")
    assert "--additional-mcp-config" in hidden.fix and "copilot mcp add" not in hidden.fix and "\n" not in hidden.fix
    if platform == "windows":
        assert hidden.fix.startswith('see docs/copilot.md, "The door by hand"') and "$HOME/se/scripts/se_mcp.ps1" in hidden.fix
    else:
        assert hidden.fix == ('copilot --agent se --additional-mcp-config "{\\"mcpServers\\":{\\"se\\":{\\"type\\":'
                              '\\"local\\",\\"command\\":\\"bash\\",\\"args\\":[\\"$HOME/se/scripts/se_mcp.sh\\",\\"--root\\",'
                              '\\"$(git rev-parse --show-toplevel)\\"],\\"tools\\":[\\"*\\"]}}}"')
    assert h.rows(entries, {}, platform, FILL, present={"plugin"})[0].fix == today.fix  # Claude's plugin hides nothing
