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
agent_lint = sys.modules["agent_lint"]  # the standalone validators se_plugin.py loads
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
                    ignore=lambda folder, names: [name for name in names
                                                  if name not in ("conftest.py", "fake_git.py")])
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
    for role in ("se", "integrator", "worker", "reviewer"):
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
    assert "tools: ['execute', 'read', 'edit', 'search', 'send_message', 'se/*']" in copilot_front
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


def copilot_hooks(checkout: Path) -> dict:
    data = json.loads((checkout / ".github" / "hooks" / "se.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    return data["hooks"]


def test_copilot_starts_and_stops_through_the_same_scripts_and_both_fail_open(checkout):
    """SessionStart greets and starts kern, Stop holds a worker to its delivery (README "Stop
    hook"); PascalCase events, so Copilot sends Claude-shaped payloads with their `session_id`, and
    each hook names its host; each fails open within its timeout, in bash and in PowerShell."""
    hooks = copilot_hooks(checkout)
    assert sorted(hooks) == ["SessionStart", "Stop"]
    for event, command in (("SessionStart", "scripts/bootstrap.sh --hook"), ("Stop", "scripts/se_hook.sh Stop")):
        [hook] = hooks[event]
        assert hook["type"] == "command" and hook["cwd"] == "."
        assert hook["env"] == {"SE_HOOK_HOST": "copilot"}
        assert hook["bash"] == f"bash {command} || true"
        assert hook["powershell"] == f"bash {command}; exit 0"
        assert 30 < hook["timeoutSec"] <= 120, "an explicit timeout above Copilot's default of 30 s"
        assert (checkout / command.split()[0]).is_file()


def test_copilots_hooks_are_a_build_setting_of_its_layout(tmp_path, monkeypatch):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n")
    assert se_plugin.COPILOT_HOOKS_FILE in se_plugin.expected(tmp_path)
    off = (se_plugin.dataclasses.replace(se_plugin.LAYOUTS[0], hooks=False), se_plugin.LAYOUTS[1])
    monkeypatch.setattr(se_plugin, "LAYOUTS", off)
    files = se_plugin.expected(tmp_path)
    assert se_plugin.COPILOT_HOOKS_FILE not in files and se_plugin.MANIFESTS[0] in files
    assert se_plugin.PLUGIN_HOOKS_FILE not in files


def test_a_plugin_install_runs_the_plugins_own_scripts_guarded_and_fail_open(checkout):
    """The plugin's hooks (.github/plugin/hooks.json) run `$PLUGIN_ROOT/scripts/<script>`, the
    variable without braces; without it, or in a folder holding the repository hooks, nothing runs;
    type, cwd, env and timeouts are the repository hooks'. tests/test_se_hook.py runs them."""
    data = json.loads((checkout / ".github" / "plugin" / "hooks.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    repository = copilot_hooks(checkout)
    assert sorted(data["hooks"]) == sorted(repository) == ["SessionStart", "Stop"]
    for event, command in (("SessionStart", "scripts/bootstrap.sh --hook"), ("Stop", "scripts/se_hook.sh Stop")):
        [hook], [local] = data["hooks"][event], repository[event]
        script, arguments = command.split(" ", 1)
        assert hook["bash"] == (f'if [ -n "$PLUGIN_ROOT" ] && [ ! -f .github/hooks/se.json ]; then '
                                f'bash "$PLUGIN_ROOT/{script}" {arguments} || true; fi')
        assert hook["powershell"] == (
            "if ($env:PLUGIN_ROOT -and -not (Test-Path .github/hooks/se.json)) "
            f'{{ bash "$($env:PLUGIN_ROOT.Replace([char]92,[char]47))/{script}" {arguments} }}; exit 0')
        assert "${" not in hook["bash"] + hook["powershell"]
        assert {key: hook[key] for key in ("type", "cwd", "env", "timeoutSec")} == \
            {key: local[key] for key in ("type", "cwd", "env", "timeoutSec")}


def test_the_repository_hooks_and_the_claude_plugin_stay_as_they_were(checkout):
    """Only a plugin install reads the plugin's hooks: the repository's and Claude Code's are what
    they were before them."""
    for name in (".github/hooks/se.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        assert "PLUGIN_ROOT\"" not in (checkout / name).read_text(encoding="utf-8"), name
    assert all(hook["bash"].startswith("bash scripts/") for [hook] in copilot_hooks(checkout).values())


def test_the_plugin_holds_every_stop_to_the_worker_stop_check(checkout):
    """README "Stop hook": one hook per stop, se_hook.sh, which kern's delivery component answers
    and else stop-check as its own process."""
    plugin = json.loads((checkout / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for event in ("Stop", "SubagentStop"):
        [entry] = plugin["hooks"][event]
        [hook] = entry["hooks"]
        assert hook["type"] == "command"
        assert hook["command"] == f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/se_hook.sh" {event} || true'
    fallback = (ROOT / "scripts" / "se_hook.sh").read_text(encoding="utf-8")
    assert '"$here/work_tickets.py" stop-check' in fallback


def test_every_session_event_but_the_start_posts_to_kern_and_fails_open(checkout):
    """README "Kern": SessionStart starts kern through bootstrap.sh; every other event posts to it."""
    plugin = json.loads((checkout / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    events = ["SessionEnd", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop"]
    assert sorted(plugin["hooks"]) == sorted(["SessionStart", *events])
    for event in events:
        [entry] = plugin["hooks"][event]
        assert "matcher" not in entry, "every tool's call is posted"
        command = f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/se_hook.sh" {event} || true'
        assert [hook["command"] for hook in entry["hooks"]].count(command) == 1, event
    assert (ROOT / "scripts" / "se_hook.sh").is_file()


def test_the_readme_installs_the_plugin_the_marketplace_declares():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8").split("## Install", 1)[1].split("\n## ", 1)[0]
    plugin = marketplace["plugins"][0]["name"]
    assert f"`claude plugin install {plugin} --marketplace <owner>/<repository>`" in readme
    assert f"`{plugin}@{marketplace['name']}`" in readme
    for agent in sorted(path.stem for path in (ROOT / "src" / "agents").glob("*.md")):
        assert f"`{plugin}:{agent}`" in readme


def test_the_cloud_install_clones_the_plugin_and_each_role_prompt_names_a_built_file(checkout):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cloud = readme.split("### Claude Code cloud\n", 1)[1].split("\n## ", 1)[0]
    script = cloud.split("```bash\n", 1)[1].split("```", 1)[0]
    assert "git clone --depth 1 https://github.com/<owner>/<repository> ~/.claude/skills/se ||" in script
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


def roles_copy(tmp_path: Path, roles: str) -> Path:
    """A copy of the sources whose se.toml declares `roles` in place of its own [roles]."""
    shutil.copytree(ROOT / "src", tmp_path / "src")
    manifest = (ROOT / "se.toml").read_text(encoding="utf-8").split("\n[roles.", 1)[0]
    (tmp_path / "se.toml").write_text(manifest + "\n" + roles, encoding="utf-8")
    return tmp_path


def front(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n---\n", 1)[0].splitlines()[1:]


def test_se_toml_names_every_role_and_each_relies_on_no_outside_skill_today():
    assert se_plugin.roles() == {"se": [], "integrator": [], "reviewer": [], "worker": []}


def test_a_roles_skills_are_preloaded_into_that_agent_where_the_host_reads_them(tmp_path):
    root = roles_copy(tmp_path, '[roles.worker]\nskills = ["plugin-dev@claude-plugins-official:plugin-structure",'
                                ' "example-skills@anthropic-agent-skills:skill-creator"]\n')
    se_plugin.build(root)
    assert front(root / "agents" / "worker.md")[-1] == (
        "skills: plugin-dev:plugin-structure, example-skills:skill-creator")
    assert not any(line.startswith("skills:") for line in front(root / ".github" / "agents" / "worker.agent.md"))
    assert not any(line.startswith("skills:") for line in front(root / "agents" / "integrator.md"))


@pytest.mark.parametrize(("roles", "refusal"), (
    ('[roles.nobody]\nskills = []\n', "[roles.nobody] names no agent in src/agents"),
    ('[roles.worker]\nskills = ["plugin-dev"]\n', "is not `<plugin>@<marketplace>:<skill>`"),
    ('[roles.worker]\nskills = "plugin-dev@m:s"\n', "[roles.worker] skills is not a list"),
    ('[roles.worker]\ntools = []\n', "[roles.worker] holds only `skills = [...]`"),
))
def test_a_roles_list_the_build_cannot_write_is_refused_naming_it(tmp_path, capsys, roles, refusal):
    root = roles_copy(tmp_path, roles)
    assert se_plugin.main(["build", "--root", str(root)]) == 2
    assert refusal in capsys.readouterr().err


def test_an_agents_own_skills_field_is_refused_for_the_one_list(tmp_path, capsys):
    root = roles_copy(tmp_path, "")
    source = root / "src" / "agents" / "worker.md"
    source.write_text(source.read_text(encoding="utf-8").replace("---\n", "---\nclaude.skills: x\n", 1),
                      encoding="utf-8")
    assert se_plugin.main(["build", "--root", str(root)]) == 2
    assert "skills come from se.toml [roles.<role>] skills" in capsys.readouterr().err


def test_every_generated_copilot_agent_holds_to_copilots_fields(checkout):
    files = se_plugin.expected(checkout)
    agents = [path for path in files if path.parent.as_posix() == ".github/agents"]
    assert len(agents) == 4 and se_plugin.validate(files) == []
    for path in agents:
        fields = agent_lint.fields(files[path].decode())
        assert set(fields) <= agent_lint.COPILOT_AGENT_FIELDS, path
    worker = agent_lint.fields(files[se_plugin.PurePosixPath(".github/agents/worker.agent.md")].decode())
    assert worker["strict-tools-list"] == "true", "a Copilot field, kept as on main"


def test_every_generated_skill_holds_to_the_agentskills_rules(checkout):
    files = se_plugin.expected(checkout)
    skills = [path for path in files if path.name == "SKILL.md"]
    assert len(skills) == 2 * len(list((checkout / "src" / "skills").iterdir()))
    for path in skills:
        fields = agent_lint.fields(files[path].decode())
        name = agent_lint.scalar(fields["name"])
        assert name == path.parent.name and len(name) <= 64 and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
        assert 0 < len(agent_lint.scalar(fields["description"])) <= 1024


@pytest.mark.parametrize("front, refusal", (
    ("copilot.agents: []", "agents is no Copilot agent field"),
    ("copilot.description: ''", "a Copilot agent needs a description"),
    ("copilot.target: cli", "target is one of github-copilot, vscode"),
    ("handoffs: []", "handoffs is no Copilot agent field"),
))
def test_a_copilot_agent_its_host_would_reject_is_refused_naming_it(tmp_path, capsys, front, refusal):
    write_source(tmp_path, "src/agents/se.md", f"---\nname: se\ndescription: 'SE.'\n{front}\n---\n# SE\n")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    assert f".github/agents/se.agent.md: {refusal}" in capsys.readouterr().err


def test_copilots_other_fields_an_unknown_tool_and_a_claude_only_key_pass(tmp_path):
    """Copilot ignores a tool it does not know (`send_message`); its other fields are its own."""
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n"
                 "copilot.tools: ['read', 'github/*', 'send_message']\ncopilot.strict-tools-list: true\n"
                 "copilot.reasoning-effort: high\ncopilot.mcp-servers: {}\ncopilot.model: ['a', 'b']\n"
                 "claude.disallowedTools: AskUserQuestion\n---\n")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 0


@pytest.mark.parametrize("name, description, refusal", (
    ("Decision", "x", "skill name 'Decision' is not 1 to 64 lowercase letters"),
    ("other", "x", "skill name 'other' differs from its folder 'decision'"),
    ("de--cision", "x", "skill name 'de--cision' is not 1 to 64 lowercase letters, digits and single hyphens"),
    ("decision", "x" * 1025, "skill description has 1025 characters, not 1 to 1024"),
    ("decision", "", "skill description has 0 characters"),
))
def test_a_skill_vs_code_would_skip_is_refused_naming_it(tmp_path, capsys, name, description, refusal):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n")
    write_source(tmp_path, "src/skills/decision/SKILL.md", f"---\nname: {name}\ndescription: '{description}'\n---\n")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert f".github/skills/decision/SKILL.md: {refusal}" in err and f"skills/decision/SKILL.md: {refusal}" in err


def write_source(root: Path, path: str, text: str) -> None:
    if not (root / "se.toml").exists():
        (root / "se.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")


def test_a_checkout_with_crlf_line_endings_builds_the_same_layouts(checkout, tmp_path):
    """git on Windows checks src/ out with CRLF; the kern-platforms leg builds the layouts from it."""
    crlf = tmp_path / "crlf"
    shutil.copytree(checkout / "src", crlf / "src")
    shutil.copy(checkout / "se.toml", crlf)
    for path in (crlf / "src").rglob("*.md"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert se_plugin.expected(crlf) == se_plugin.expected(checkout)


def test_copilots_one_manifest_names_its_layout_its_hooks_and_the_door(checkout):
    manifest = json.loads((checkout / ".github" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude = json.loads((checkout / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert {key: manifest[key] for key in ("name", "version", "description")} == {
        key: claude[key] for key in ("name", "version", "description")}
    assert manifest["agents"] == ".github/agents/" and manifest["skills"] == ".github/skills/"
    assert manifest["hooks"] == ".github/plugin/hooks.json"
    for key in ("agents", "skills", "hooks"):
        assert (checkout / manifest[key]).exists(), key
    assert manifest["mcpServers"] == {"se": {"type": "stdio", "command": "bash",
                                            "args": ["${PLUGIN_ROOT}/scripts/se_mcp.sh", "--root", "."],
                                            "env": {"SE_SESSION_CWD": "${COPILOT_SESSION_CWD}"}}}


def test_copilots_door_gets_the_sessions_folder_in_both_its_files(checkout):
    """Copilot reads a plugin's own .github/mcp.json before the manifest's mcpServers: both name it."""
    project = json.loads((checkout / ".github" / "mcp.json").read_text(encoding="utf-8"))
    assert project == {"mcpServers": {"se": {"type": "stdio", "command": "bash",
                                             "args": ["scripts/se_mcp.sh", "--root", "."], "tools": ["*"],
                                             "env": {"SE_SESSION_CWD": "${COPILOT_SESSION_CWD}"}}}}


@pytest.mark.parametrize("name", (".github/mcp.json", ".github/plugin/plugin.json", ".mcp.json"))
def test_the_door_runs_the_launcher_and_a_plugin_root_only_in_its_arguments(checkout, tmp_path, name):
    """README "MCP door": every declaration runs the standalone launcher with bash; a host's plugin
    root variable stands in an argument, never in the command."""
    root = checkout
    if name == ".mcp.json":
        root = tmp_path / "on"
        shutil.copytree(checkout / "src", root / "src")
        (root / "se.toml").write_text((checkout / "se.toml").read_text(encoding="utf-8").replace(
            "root_mcp = false", "root_mcp = true"), encoding="utf-8")
        se_plugin.build(root)
    [server] = json.loads((root / name).read_text(encoding="utf-8"))["mcpServers"].values()
    assert server["command"] == "bash" and "$" not in server["command"]
    assert server["args"][0].endswith("scripts/se_mcp.sh") and server["args"][1:] == ["--root", "."]
    assert (ROOT / "scripts" / "se_mcp.sh").is_file()


def test_no_root_mcp_json_with_the_setting_off_and_check_refuses_a_stray_one(checkout, capsys):
    assert se_plugin.root_mcp(ROOT) is False, "se.toml [plugin] root_mcp is off by default"
    assert not (ROOT / ".mcp.json").exists() and not (checkout / ".mcp.json").exists()
    (checkout / ".mcp.json").write_text("{}\n", encoding="utf-8")
    assert se_plugin.main(["check", "--root", str(checkout)]) == 1
    assert ".mcp.json: not generated from src/" in capsys.readouterr().err
    assert se_plugin.main(["build", "--root", str(checkout)]) == 0
    assert not (checkout / ".mcp.json").exists()


def test_check_refuses_a_hand_edit_to_the_plugin_hooks(checkout, capsys):
    path = checkout / ".github" / "plugin" / "hooks.json"
    original = path.read_bytes()
    path.write_bytes(original.replace(b"$PLUGIN_ROOT/scripts/bootstrap.sh", b"scripts/bootstrap.sh", 1))
    try:
        assert se_plugin.main(["check", "--root", str(checkout)]) == 1
        assert ".github/plugin/hooks.json: differs from its source" in capsys.readouterr().err
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("name", (".github/plugin/plugin.json", ".github/mcp.json"))
def test_check_covers_the_copilot_manifest_and_mcp_file(checkout, capsys, name):
    path = checkout / name
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"se"', b'"other"', 1))
    try:
        assert se_plugin.main(["check", "--root", str(checkout)]) == 1
        assert f"{name}: differs from its source" in capsys.readouterr().err
    finally:
        path.write_bytes(original)


def test_a_plugin_setting_the_build_cannot_read_is_refused(tmp_path, capsys):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n")
    (tmp_path / "se.toml").write_text('[project]\nversion = "1.0.0"\n[plugin]\nroot_mcp = "yes"\n', encoding="utf-8")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    assert "[plugin] holds only `root_mcp = true|false`" in capsys.readouterr().err


LAYOUT_FOLDERS = ("agents", "skills", ".github/agents", ".github/skills")


def layout_links(root: Path) -> list[tuple[Path, str]]:
    """Every link of every generated Markdown file under `root`, with the file that holds it."""
    return [(path, target) for folder in LAYOUT_FOLDERS for path in sorted((root / folder).rglob("*.md"))
            for target in LINK.findall(path.read_text(encoding="utf-8"))]


def test_every_layout_link_resolves_in_ses_checkout_and_in_an_installed_plugins_folder(tmp_path):
    """Links stay relative to their file, so they reach their target wherever the repository lies:
    in SE's checkout and in the folder a host installs the plugin to, which holds the repository at
    another root. No link names where SE lives."""
    installed = tmp_path / "home" / ".claude" / "plugins" / "cache" / "se" / "se" / "1.0.0"
    shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns(
        ".git", ".se", ".venv", ".pytest_cache", "__pycache__", "node_modules"))
    relative = 0
    for root in (ROOT, installed):
        for path, target in layout_links(root):
            where = f"{path.relative_to(root).as_posix()}: {target}"
            assert not re.match(r"https?://[^/]+/[^/]+/[^/]+/(?:blob|tree)/", target), where
            if "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            assert resolved.is_relative_to(root.resolve()) and resolved.exists(), where
            relative += 1
    assert relative > 0, "the layouts link to the files beside them"


def test_a_layout_link_out_of_its_folder_stays_relative(tmp_path):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n# SE\n\n"
                 "See [the README](../../README.md#install) and [x](../skills/x/SKILL.md).\n")
    write_source(tmp_path, "src/skills/x/SKILL.md", "---\nname: x\ndescription: 'X.'\n---\n")
    files = se_plugin.expected(tmp_path)
    copilot = files[se_plugin.PurePosixPath(".github/agents/se.agent.md")].decode()
    claude = files[se_plugin.PurePosixPath("agents/se.md")].decode()
    assert "See [the README](../../README.md#install) and [x](../skills/x/SKILL.md)." in copilot
    assert "See [the README](../README.md#install) and [x](../skills/x/SKILL.md)." in claude


def test_the_manifests_name_no_home(checkout):
    for path in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".github/plugin/plugin.json"):
        data = json.loads((checkout / path).read_text(encoding="utf-8"))
        assert "repository" not in data and "author" not in data and "homepage" not in data, path
        assert "://" not in json.dumps({key: value for key, value in data.items() if key != "hooks"}), path


@pytest.mark.parametrize("crlf", (False, True), ids=("lf", "crlf"))
def test_check_passes_in_an_lf_and_in_a_crlf_checkout(tmp_path, capsys, crlf):
    """git's autocrlf on Windows checks out text with CRLF line endings: the sources and the
    generated layouts alike. `check` holds both to the same LF build."""
    root = tmp_path / "se"
    shutil.copytree(ROOT / "src", root / "src")
    shutil.copy(ROOT / "se.toml", root)
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    if crlf:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in (".md", ".json", ".toml", ".py", ".sh"):
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    capsys.readouterr()
    assert se_plugin.main(["check", "--root", str(root)]) == 0, capsys.readouterr().err
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before, \
        "a build of an up-to-date CRLF checkout rewrites nothing"


def test_a_copilot_part_goes_only_to_the_copilot_layout_without_its_markers(tmp_path):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n# SE\n\nBoth.\n\n"
                 "<!-- copilot -->\nOnly Copilot, see [it](../skills/x/SKILL.md).\n\n<!-- /copilot -->\nBoth again.\n")
    write_source(tmp_path, "src/skills/x/SKILL.md", "---\nname: x\ndescription: 'X.'\n---\n")
    files = se_plugin.expected(tmp_path)
    copilot = files[se_plugin.PurePosixPath(".github/agents/se.agent.md")].decode()
    claude = files[se_plugin.PurePosixPath("agents/se.md")].decode()
    assert claude.endswith("# SE\n\nBoth.\n\nBoth again.\n")
    assert copilot.endswith("# SE\n\nBoth.\n\nOnly Copilot, see [it](../skills/x/SKILL.md).\n\nBoth again.\n")
    assert "<!--" not in copilot.split("-->", 1)[1], "no marker line is left"


@pytest.mark.parametrize("body, refusal", (
    ("<!-- copilot -->\nx\n", "src/agents/se.md:6: <!-- copilot --> is never closed"),
    ("x\n<!-- /copilot -->\n", "src/agents/se.md:7: <!-- /copilot --> without its <!-- copilot -->"),
    ("<!-- copilot -->\n<!-- copilot -->\n<!-- /copilot -->\n", "src/agents/se.md:7: <!-- copilot --> inside another"),
))
def test_a_copilot_part_the_build_cannot_place_is_refused_naming_its_line(tmp_path, capsys, body, refusal):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n# SE\n" + body)
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    assert refusal in capsys.readouterr().err



def claude_layout(files: dict) -> dict:
    """The Claude layout of a build: agents/, skills/ and .claude-plugin/, without the version line."""
    return {path: re.sub(rb'\n  "version": "[^"]*",', b"", data) for path, data in files.items()
            if path.parts[0] in ("agents", "skills", ".claude-plugin")}


def test_the_claude_layout_is_byte_identical_with_and_without_the_copilot_content(checkout, tmp_path):
    """Everything Copilot gains is additive: the Claude layout built from the sources is the one
    built without any Copilot content, the Copilot parts of the bodies removed from the sources and
    the Copilot layout and its files not built at all."""
    files = se_plugin.expected(checkout)
    assert se_plugin.COPILOT_MANIFEST in files and se_plugin.COPILOT_MCP_FILE in files
    stripped = tmp_path / "stripped"
    shutil.copytree(checkout / "src", stripped / "src")
    (stripped / "se.toml").write_text((checkout / "se.toml").read_text(encoding="utf-8").replace(
        'version = "', 'version = "0.0.', 1), encoding="utf-8")
    parts = 0
    for path in (stripped / "src").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        parts += text.count(se_plugin.COPILOT_OPEN + "\n")
        path.write_text(re.sub(r"(?ms)^<!-- copilot -->\n.*?^<!-- /copilot -->\n", "", text), encoding="utf-8")
    assert parts >= 3, "the se, worker and work-model sources carry Copilot parts"
    without = se_plugin.expected(stripped, copilot=False)
    assert not any(path.parts[0] == ".github" for path in without)
    assert claude_layout(without) == claude_layout(files)


def built_with_manifest_setting(checkout: Path, root: Path, line: str | None) -> dict:
    """A build of the checkout's sources whose se.toml [plugin] carries `line` (None: as tracked)."""
    shutil.copytree(checkout / "src", root / "src")
    text = (checkout / "se.toml").read_text(encoding="utf-8")
    if line is not None:
        text = text.replace("[plugin]\n", f"[plugin]\n{line}\n", 1)
    (root / "se.toml").write_text(text, encoding="utf-8")
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    return {se_plugin.PurePosixPath(path.relative_to(root).as_posix()): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and path.parts[len(root.parts)] not in ("src", "se.toml")}


def test_the_copilot_manifest_setting_is_unset_and_unset_builds_todays_files_byte_for_byte(tmp_path):
    """Off stays off: SE's se.toml leaves [plugin] copilot_manifest unset, and unset (or set to its
    default) the build writes exactly the committed files."""
    assert "copilot_manifest" not in tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["plugin"]
    assert se_plugin.copilot_manifest(ROOT) == se_plugin.PurePosixPath(".github/plugin/plugin.json")
    committed = {path: (ROOT / path).read_bytes() for path in se_plugin._existing(ROOT)}
    assert se_plugin.PurePosixPath(".github/plugin/plugin.json") in committed
    assert not (ROOT / "plugin.json").exists()
    assert se_plugin.expected(ROOT) == committed
    shutil.copytree(ROOT / "src", tmp_path / "src")
    (tmp_path / "se.toml").write_text((ROOT / "se.toml").read_text(encoding="utf-8").replace(
        "[plugin]\n", '[plugin]\ncopilot_manifest = "github"\n', 1), encoding="utf-8")
    assert se_plugin.expected(tmp_path) == committed


def test_a_root_copilot_manifest_moves_only_the_manifest(checkout, tmp_path):
    """Set to "root", the one Copilot manifest lies at the repository root with the same content,
    its paths naming the same files under .github/; every other file, the Claude layout among them,
    is byte-identical."""
    off = built_with_manifest_setting(checkout, tmp_path / "off", None)
    on = built_with_manifest_setting(checkout, tmp_path / "on", 'copilot_manifest = "root"')
    github, root = se_plugin.PurePosixPath(".github/plugin/plugin.json"), se_plugin.PurePosixPath("plugin.json")
    assert set(off) - set(on) == {github} and set(on) - set(off) == {root}
    assert on[root] == off[github]
    manifest = json.loads(on[root])
    for key in ("agents", "skills", "hooks"):
        assert manifest[key].startswith(".github/") and (tmp_path / "on" / manifest[key]).exists(), key
    assert {path: data for path, data in on.items() if path != root} == \
        {path: data for path, data in off.items() if path != github}
    assert claude_layout(on) == claude_layout(off) and claude_layout(on)


@pytest.mark.parametrize("setting, leftover", ((None, "plugin.json"),
                                               ('copilot_manifest = "root"', ".github/plugin/plugin.json")))
def test_check_names_a_copilot_manifest_at_the_other_place_as_not_generated(checkout, tmp_path, capsys,
                                                                           setting, leftover):
    root = tmp_path / "tree"
    built_with_manifest_setting(checkout, root, setting)
    (root / leftover).parent.mkdir(parents=True, exist_ok=True)
    (root / leftover).write_text("{}\n", encoding="utf-8")
    capsys.readouterr()
    assert se_plugin.main(["check", "--root", str(root)]) == 1
    assert f"{leftover}: not generated from src/" in capsys.readouterr().err
    assert se_plugin.main(["build", "--root", str(root)]) == 0
    assert not (root / leftover).exists()
    assert se_plugin.main(["check", "--root", str(root)]) == 0


def test_a_copilot_manifest_place_the_build_cannot_read_is_refused(tmp_path, capsys):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n")
    (tmp_path / "se.toml").write_text('[project]\nversion = "1.0.0"\n[plugin]\ncopilot_manifest = ".plugin"\n',
                                      encoding="utf-8")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    assert '`copilot_manifest = "github"|"root"`' in capsys.readouterr().err


def test_every_manifest_lookup_row_is_documented_not_measured():
    assert set(se_plugin.MANIFEST_LOOKUPS) == {"copilot-cli", "vscode"}
    assert [place for place, _ in se_plugin.MANIFEST_LOOKUPS["copilot-cli"]] == [
        ".plugin/plugin.json", "plugin.json", ".github/plugin/plugin.json", ".claude-plugin/plugin.json"]
    assert dict(se_plugin.MANIFEST_LOOKUPS["vscode"]) == {"plugin.json": "copilot",
                                                          ".claude-plugin/plugin.json": "claude"}
    assert se_plugin.manifest_pick([".claude-plugin/plugin.json"], "copilot-cli").evidence == "documented"
    assert se_plugin.manifest_pick(["README.md"], "vscode") is None


@pytest.mark.parametrize("setting, host, picked, form", (
    # Unset: the Copilot CLI reads SE's Copilot manifest, VS Code only finds the Claude layout's.
    (None, "copilot-cli", ".github/plugin/plugin.json", "copilot"),
    (None, "vscode", ".claude-plugin/plugin.json", "claude"),
    # Set to "root": both hosts read the Copilot manifest at the root.
    ('copilot_manifest = "root"', "copilot-cli", "plugin.json", "copilot"),
    ('copilot_manifest = "root"', "vscode", "plugin.json", "copilot"),
))
def test_what_each_value_of_the_setting_means_per_host(checkout, tmp_path, setting, host, picked, form):
    tree = built_with_manifest_setting(checkout, tmp_path / "tree", setting)
    pick = se_plugin.manifest_pick([path.as_posix() for path in tree], host)
    assert (pick.path.as_posix(), pick.format, pick.evidence) == (picked, form, "documented")


HOOKS_FILES = (se_plugin.COPILOT_HOOKS_FILE, se_plugin.PLUGIN_HOOKS_FILE)


def test_the_powershell_hooks_setting_is_unset_and_unset_builds_todays_files_byte_for_byte(tmp_path):
    """Off stays off: SE's se.toml leaves [plugin] powershell_hooks unset, and unset (or set to its
    default) the build writes exactly the committed files, the bare `bash` lines among them."""
    assert "powershell_hooks" not in tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["plugin"]
    assert se_plugin.powershell_hooks(ROOT) == "bash"
    committed = {path: (ROOT / path).read_bytes() for path in se_plugin._existing(ROOT)}
    assert se_plugin.expected(ROOT) == committed
    hooks = json.loads(committed[se_plugin.COPILOT_HOOKS_FILE])["hooks"]
    assert hooks["SessionStart"][0]["powershell"] == "bash scripts/bootstrap.sh --hook; exit 0"
    shutil.copytree(ROOT / "src", tmp_path / "src")
    (tmp_path / "se.toml").write_text((ROOT / "se.toml").read_text(encoding="utf-8").replace(
        "[plugin]\n", '[plugin]\npowershell_hooks = "bash"\n', 1), encoding="utf-8")
    assert se_plugin.expected(tmp_path) == committed


def test_the_handoff_setting_changes_only_the_powershell_lines_of_both_hooks_files(checkout, tmp_path):
    """Set to "handoff", each PowerShell line of .github/hooks/se.json and .github/plugin/hooks.json
    starts scripts/bash.ps1 and still ends in `exit 0`; its bash line and every other file stay."""
    off = built_with_manifest_setting(checkout, tmp_path / "off", None)
    on = built_with_manifest_setting(checkout, tmp_path / "on", 'powershell_hooks = "handoff"')
    assert set(on) == set(off)
    assert {path for path in on if on[path] != off[path]} == set(HOOKS_FILES)
    for path in HOOKS_FILES:
        before, after = json.loads(off[path]), json.loads(on[path])
        for event, entries in after["hooks"].items():
            for old, new in zip(before["hooks"][event], entries, strict=True):
                assert {k: v for k, v in new.items() if k != "powershell"} == \
                    {k: v for k, v in old.items() if k != "powershell"}, (path, event)
                assert new["powershell"] != old["powershell"] and new["powershell"].endswith("; exit 0")
                assert se_plugin.HANDOFF in new["powershell"] and " bash " not in f" {new['powershell']}"
        for event in after["hooks"]:
            before["hooks"][event] = after["hooks"][event] = None
        assert after == before, path


def test_the_handoff_lines_name_the_same_script_and_arguments():
    assert se_plugin.hook_commands("scripts/se_hook.sh Stop", "handoff") == (
        "bash scripts/se_hook.sh Stop || true",
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/bash.ps1 "
        "scripts/se_hook.sh Stop; exit 0")
    bash, powershell = se_plugin.plugin_hook_commands("scripts/bootstrap.sh --hook", "handoff")
    assert bash == se_plugin.plugin_hook_commands("scripts/bootstrap.sh --hook")[0]
    assert powershell == (
        "if ($env:PLUGIN_ROOT -and -not (Test-Path .github/hooks/se.json)) { powershell -NoProfile "
        '-NonInteractive -ExecutionPolicy Bypass -File "$env:PLUGIN_ROOT/scripts/bash.ps1" '
        '"$($env:PLUGIN_ROOT.Replace([char]92,[char]47))/scripts/bootstrap.sh" --hook }; exit 0')


def test_a_powershell_hooks_value_the_build_cannot_read_is_refused(tmp_path, capsys):
    write_source(tmp_path, "src/agents/se.md", "---\nname: se\ndescription: 'SE.'\n---\n")
    (tmp_path / "se.toml").write_text('[project]\nversion = "1.0.0"\n[plugin]\npowershell_hooks = "pwsh"\n',
                                      encoding="utf-8")
    assert se_plugin.main(["build", "--root", str(tmp_path)]) == 2
    assert '`powershell_hooks = "bash"|"handoff"`' in capsys.readouterr().err
