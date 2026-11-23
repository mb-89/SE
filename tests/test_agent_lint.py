"""agent_lint.py: standalone validators, a file in and its findings out, for any repository."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_lint.py"
sys.path.insert(0, str(ROOT / "scripts"))
import agent_lint  # noqa: E402


def run(*files: Path) -> subprocess.CompletedProcess:
    """The script as a command: the one entry-point test's."""
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, files)], capture_output=True, text=True,
                          timeout=60)


def lint(capsys, *files: Path) -> tuple[int, str, str]:
    """The script's `main` in-process: its exit code, standard output and error."""
    code = agent_lint.main([str(path) for path in files])
    out, err = capsys.readouterr()
    return code, out, err


def test_another_repositorys_valid_agent_and_skill_have_no_findings(tmp_path, capsys):
    agent = tmp_path / ".github" / "agents" / "helper.agent.md"
    skill = tmp_path / ".github" / "skills" / "write-notes" / "SKILL.md"
    for path, text in ((agent, "---\nname: helper\ndescription: 'Helps.'\ntools: ['read', 'github/*']\n"
                                "target: vscode\n---\n# Helper\n"),
                       (skill, "---\nname: write-notes\ndescription: \"Writes notes.\"\n---\n")):
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    assert lint(capsys, agent, skill) == (0, "", "")


@pytest.mark.spawns("entry: scripts/agent_lint.py")
def test_findings_name_each_file_and_exit_one(tmp_path):
    agent = tmp_path / "x.agent.md"
    agent.write_text("---\nname: x\ndescription: ''\ntools: ['bash', 'read']\nhandoffs: []\n---\n", encoding="utf-8")
    skill = tmp_path / "My_Skill" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("---\nname: My_Skill\ndescription: 'x'\n---\n", encoding="utf-8")
    result = run(agent, skill)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{agent}: handoffs is no Copilot agent field",
        f"{agent}: a Copilot agent needs a description",
        f"{skill}: skill name 'My_Skill' is not 1 to 64 lowercase letters, digits and single hyphens",
    ]


def test_a_plugin_agent_both_hosts_read_may_carry_claude_codes_disallowed_tools(tmp_path, capsys):
    """Copilot ignores `disallowedTools`; on a `*.agent.md`, Copilot's own file, it is a finding."""
    text = "---\nname: x\ndescription: 'X.'\ndisallowedTools: AskUserQuestion\n---\n"
    shared, copilot = tmp_path / "agents" / "x.md", tmp_path / "x.agent.md"
    shared.parent.mkdir()
    for path in (shared, copilot):
        path.write_text(text, encoding="utf-8")
    assert lint(capsys, shared, copilot)[:2] == (1, f"{copilot}: disallowedTools is no Copilot agent field\n")


def test_an_unreadable_file_is_a_setup_error(tmp_path, capsys):
    code, _out, err = lint(capsys, tmp_path / "missing.agent.md")
    assert code == 2 and "missing.agent.md" in err


def test_a_long_name_and_a_quoted_description_are_measured_as_the_host_reads_them():
    path = Path("a" * 65) / "SKILL.md"
    assert agent_lint.skill(path, f"---\nname: {'a' * 65}\ndescription: 'it''s'\n---\n") == [
        f"{path}: skill name {'a' * 65!r} is not 1 to 64 lowercase letters, digits and single hyphens"]
    assert agent_lint.scalar("'it''s'") == "it's"


def test_a_file_with_crlf_line_endings_reads_as_one_with_lf():
    """git on Windows checks the sources out with CRLF; the kern-platforms leg builds from them."""
    text = "---\r\nname: decision\r\ndescription: 'Decides.'\r\n---\r\n# Decision\r\n"
    assert agent_lint.fields(text) == {"name": "decision", "description": "'Decides.'"}
    assert agent_lint.skill(Path("decision") / "SKILL.md", text) == []
