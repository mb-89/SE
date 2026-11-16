"""The request guards under Copilot (scripts/copilot_guards.py, docs/copilot.md "What a session
costs"): each on unless se.toml `[copilot]` sets its setting true."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_guards  # noqa: E402


def project(tmp_path: Path, text: str | None) -> Path:
    if text is not None:
        (tmp_path / "se.toml").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("text", (None, "", "[project]\nversion = \"1.0.0\"\n", "[copilot]\n",
                                  "[copilot]\nrefuse_stop = false\nstart_sessions = false\n"))
def test_by_default_every_guard_is_on(tmp_path, text):
    root = project(tmp_path, text)
    assert copilot_guards.settings(root) == {"refuse_stop": False, "start_sessions": False}
    assert all(copilot_guards.guarded(root, name) for name in copilot_guards.GUARDS)
    assert all(": on, " in line for line in copilot_guards.state(root))
    assert copilot_guards.guarded(None, "refuse_stop")


@pytest.mark.parametrize("name", sorted(copilot_guards.GUARDS))
def test_each_setting_true_turns_its_guard_off_alone(tmp_path, name):
    root = project(tmp_path, f"[copilot]\n{name} = true\n")
    assert [copilot_guards.guarded(root, guard) for guard in sorted(copilot_guards.GUARDS)] == [
        guard != name for guard in sorted(copilot_guards.GUARDS)]
    assert f"[copilot] {name} = true: off, today's behaviour" in copilot_guards.state(root)


@pytest.mark.parametrize("text", ('[copilot]\nstart_sessions = "yes"\n', "[copilot\n"))
def test_an_unreadable_setting_keeps_every_guard_on_and_says_so(tmp_path, text):
    root = project(tmp_path, text)
    with pytest.raises(ValueError):
        copilot_guards.settings(root)
    assert all(copilot_guards.guarded(root, name) for name in copilot_guards.GUARDS)
    assert all("every guard stays on" in line for line in copilot_guards.state(root))


def test_the_greeting_names_the_guards_under_copilot_only(tmp_path):
    root = project(tmp_path, "[copilot]\nstart_sessions = true\n")
    assert copilot_guards.greeting(root, "claude") == []
    [line] = copilot_guards.greeting(root, "copilot")
    assert line.startswith("Copilot guards: [copilot] refuse_stop = false: on, ")
    assert "[copilot] start_sessions = true: off" in line


COPILOT_PROCEDURES = (".github/agents/se.agent.md", ".github/agents/integrator.agent.md",
                      ".github/skills/catch-up/SKILL.md", ".github/skills/work-model/SKILL.md")
CLAUDE_PROCEDURES = ("agents/se.md", "agents/integrator.md", "skills/catch-up/SKILL.md",
                     "skills/work-model/SKILL.md")


def test_every_role_that_starts_sessions_starts_none_under_copilot_unless_the_setting_says_so():
    """No code starts a Copilot session (the roles do, by their procedure): each procedure that
    starts one prints its line instead under Copilot, unless the greeting reads the setting true;
    Claude Code's layout does not carry it."""
    for name in COPILOT_PROCEDURES:
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "`[copilot] start_sessions = true`" in text, name
        assert "start no session" in text or "starts no session" in text or "start no worker" in text, name
    for name in CLAUDE_PROCEDURES:
        assert "start_sessions" not in (ROOT / name).read_text(encoding="utf-8"), name
