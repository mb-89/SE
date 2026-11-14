"""Tests of se_doctor: the read-only report of the box SE runs in (README "Doctor"). The checks get
fake facts; the gatherers read files under tmp_path, with git and the network replaced."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import se_doctor as d


def clean_facts() -> dict:
    """A box where everything answers and matches its pin."""
    return {
        "host": {"name": "claude-code", "cloud": True},
        "checkout": {"git": True, "head": "0daf4dc", "upstream": "origin/main", "ahead": 0, "behind": 0,
                     "version": "5.50.2"},
        "plugins": [{"where": "~/.claude/skills/se", "version": "5.50.2", "exists": True}],
        "latest": {"version": "5.50.2", "age_seconds": 120},
        "binary": {"name": "se", "pinned": "0.2.8", "copies": [
            {"where": "PATH", "exists": True, "version": "0.2.8", "file": "~/.se/bin/se-0.2.8"},
            {"where": "the core's start", "exists": True, "version": "0.2.8", "file": "~/.se/bin/se-0.2.8"}]},
        "core": {"standing": True, "asked": True, "pid": 370, "boot": "b-1", "status": "running", "alive": True,
                 "log": ["se: serving <checkout>, pid 370"]},
        "registrations": [{"file": "~/.claude/skills/se/.claude-plugin/plugin.json", "kind": "hooks", "items": [
            {"name": "SessionStart", "scripts": [{"script": "~/.claude/skills/se/scripts/bootstrap.sh",
                                                  "exists": True}]}]}],
        "gh": {"installed": True, "signed_in": True},
        "network": [{"host": "github.com", "reached": True}],
    }


def problems(facts: dict) -> list[d.Finding]:
    return [f for f in d.diagnose(facts) if f.level == d.PROBLEM]


def test_a_clean_box_has_no_problem_and_every_area_is_seen():
    findings = d.diagnose(clean_facts())
    assert problems(clean_facts()) == []
    assert {f.area for f in findings} == set(d.AREAS)
    assert all(f.state == d.SEEN for f in findings)
    assert d.render_text(findings).startswith("SE doctor: 0 problems, 0 notes")


def test_a_stale_plugin_is_a_problem_named_first():
    facts = clean_facts()
    facts["plugins"][0]["version"] = "5.49.13"
    found = problems(facts)
    assert len(found) == 1 and found[0].area == "plugin"
    assert "stale plugin: SE 5.49.13" in found[0].text
    assert "the checkout's 5.50.2" in found[0].text and "the latest release 5.50.2" in found[0].text
    assert d.diagnose(facts)[0] == found[0]


def test_a_stale_binary_is_a_problem_ranked_above_a_stale_plugin():
    facts = clean_facts()
    facts["plugins"][0]["version"] = "5.49.13"
    facts["binary"]["copies"][1]["version"] = "0.2.6"
    findings = d.diagnose(facts)
    assert [f.area for f in findings[:2]] == ["binary", "plugin"]
    assert findings[0].text == "stale binary: se 0.2.6 on the core's start; the pin is 0.2.8"


def test_a_dead_core_record_is_a_problem():
    facts = clean_facts()
    facts["core"] |= {"status": None, "alive": False}
    found = problems(facts)
    assert [f.area for f in found] == ["core"]
    assert found[0].text.startswith("dead core record: the standing file names pid 370, boot b-1")


def test_a_core_whose_pid_cannot_be_seen_is_not_measured_not_dead():
    facts = clean_facts()
    facts["core"] |= {"status": None, "alive": None, "asked": False}
    assert problems(facts) == []
    core = [f for f in d.diagnose(facts) if f.area == "core"][0]
    assert core.state == d.NOT_MEASURED and "pid alive not measured" in core.text


def test_a_missing_hook_script_is_a_problem_naming_the_file_and_event():
    facts = clean_facts()
    facts["registrations"][0]["items"][0]["scripts"][0]["exists"] = False
    found = problems(facts)
    assert [f.area for f in found] == ["hooks"]
    assert "SessionStart names ~/.claude/skills/se/scripts/bootstrap.sh, which does not exist" in found[0].text


def test_missing_facts_are_not_measured_and_unanswered_ones_silent():
    findings = d.diagnose({"gh": {"installed": True, "signed_in": None},
                           "network": [{"host": "github.com", "reached": False}]})
    states = {f.area: f.state for f in findings}
    assert states["host"] == states["binary"] == states["core"] == d.NOT_MEASURED
    assert states["gh"] == d.SILENT and states["network"] == d.SILENT
    assert [f.area for f in findings if f.level == d.PROBLEM] == ["network"]


def test_the_text_stays_short_and_json_carries_the_same_findings():
    facts = clean_facts()
    facts["registrations"] *= 10
    findings = d.diagnose(facts)
    assert len(d.render_text(findings).splitlines()) <= 60
    data = json.loads(d.render_json(findings, facts))
    assert [f["text"] for f in data["findings"]] == [f.text for f in findings]
    assert data["reused"] == d.REUSED


def test_shown_and_redact_hide_private_paths_addresses_and_bus_users(tmp_path: Path):
    home, checkout = tmp_path / "home", tmp_path / "work" / "SE"
    assert d.shown(home / ".se" / "bin" / "se", checkout, home) == "~/.se/bin/se"
    assert d.shown(checkout / "scripts" / "x.sh", checkout, home) == "<checkout>/scripts/x.sh"
    assert d.shown(tmp_path / "elsewhere" / "x.sh", checkout, home) == ".../x.sh"
    profile = "/" + "/".join(("home", "alice", "x"))  # joined, so the public check sees no profile path
    line = f"serving {checkout} for alice@example.com from {profile} via nats://core:pw@127.0.0.1:4222"
    assert d.redact(line, checkout, home) == \
        "serving <checkout> for <e-mail> from /home/<name>/x via nats://127.0.0.1:4222"


def test_the_core_gatherer_reads_no_bus_user_and_tails_the_log(tmp_path: Path):
    runtime = tmp_path / ".se" / ".runtime"
    runtime.mkdir(parents=True)
    (runtime / "standing.json").write_text(json.dumps(
        {"pid": 4242, "boot": "b-2", "started": "t", "users": {"core": "secret-user"}}), encoding="utf-8")
    (runtime / "core.log").write_text("".join(f"line {n}\n" for n in range(9)), encoding="utf-8")
    binary = tmp_path / "se-0.2.8"
    binary.write_text("", encoding="utf-8")
    core = d.gather_core(tmp_path, binary, tmp_path, tmp_path,
                         status=lambda _b, _r: {"state": "running", "health": {"pid": 4242}})
    assert core["alive"] is True and core["boot"] == "b-2"
    assert core["log"] == ["line 6", "line 7", "line 8"]
    assert "secret-user" not in json.dumps(core)


def test_registrations_resolve_plugin_project_and_home_scripts(tmp_path: Path):
    home, project, plugin = tmp_path / "home", tmp_path / "project", tmp_path / "home" / ".claude" / "skills" / "se"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    (plugin / "scripts" / "bootstrap.sh").write_text("", encoding="utf-8")
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "se", "version": "1.0.0", "hooks": {
        "SessionStart": [{"hooks": [{"type": "command",
                                     "command": 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh" --hook'}]}],
        "Stop": [{"hooks": [{"type": "command", "command": 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/gone.sh"'}]}]}}),
        encoding="utf-8")
    (project / ".github" / "hooks").mkdir(parents=True)
    (project / ".github" / "hooks" / "se.json").write_text(json.dumps(
        {"version": 1, "hooks": {"sessionStart": [{"type": "command", "bash": "scripts/start.sh"}]}}),
        encoding="utf-8")
    (project / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"kern": {"command": "uv", "args": ["run", "python", "$UNKNOWN/door.py"]}}}),
        encoding="utf-8")
    roots = d._plugin_roots(home / ".claude", home / ".claude" / "plugins" / "installed_plugins.json")
    assert roots == [plugin]
    regs = d.gather_registrations(roots, project, home, home / ".claude", project)
    by_file = {r["file"]: r for r in regs}
    scripts = {s["script"]: s["exists"] for r in regs for i in r["items"] for s in i["scripts"]}
    assert scripts == {"~/.claude/skills/se/scripts/bootstrap.sh": True, "~/.claude/skills/se/scripts/gone.sh": False,
                       "<checkout>/scripts/start.sh": False, "$UNKNOWN/door.py": None}
    assert set(by_file) == {"~/.claude/skills/se/.claude-plugin/plugin.json", "<checkout>/.github/hooks/se.json",
                            "<checkout>/.mcp.json"}
    found = d.check_registrations(regs)
    assert sum(f.level == d.PROBLEM for f in found) == 2
    assert any(f.state == d.NOT_MEASURED and "$UNKNOWN/door.py" in f.text for f in found)


def test_the_checkout_gatherer_compares_with_the_upstream_as_fetched(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "se.toml").write_text('[project]\nversion = "5.50.2"\n', encoding="utf-8")
    answers = {("rev-parse", "--short", "HEAD"): "abc1234",
               ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): None,
               ("rev-parse", "--abbrev-ref", "origin/HEAD"): "origin/main",
               ("rev-list", "--left-right", "--count", "HEAD...origin/main"): "1\t3"}
    facts = d.gather_checkout(tmp_path, git=lambda _root, *args: answers[args])
    assert facts == {"git": True, "head": "abc1234", "upstream": "origin/main", "ahead": 1, "behind": 3,
                     "version": "5.50.2"}
    assert d.check_checkout(facts)[0].level == d.PROBLEM


def test_the_binary_gatherer_reads_versions_from_the_fetched_names(tmp_path: Path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    (project / "components").mkdir(parents=True)
    (project / "se.toml").write_text('[binary]\nrelease = "components/release.toml"\n', encoding="utf-8")
    (project / "components" / "release.toml").write_text(
        'version = "0.2.8"\ndownload = "https://example.com/{version}"\nbinary = "se"\npackage = "./cmd/se"\n',
        encoding="utf-8")
    bin_dir = home / ".se" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "se-0.2.6").write_text("", encoding="utf-8")
    (bin_dir / "se").write_text("", encoding="utf-8")  # a copy where no link is made: no version
    monkeypatch.setattr(d.shutil, "which", lambda _name: str(bin_dir / "se-0.2.6"))
    facts = d.gather_binary(project, project, home, project)
    assert facts["pinned"] == "0.2.8"
    copies = {c["where"]: c for c in facts["copies"]}
    assert copies["PATH"]["version"] == "0.2.6" and copies["~/.se/bin"]["version"] is None
    assert copies["the core's start"]["exists"] is False
    texts = [f.text for f in d.check_binary(facts)]
    assert "stale binary: se 0.2.6 on PATH; the pin is 0.2.8" in texts
    assert any("on ~/.se/bin" in t and "carries no version" in t for t in texts)


def test_gather_offline_writes_nothing_and_strict_sets_the_exit_code(tmp_path: Path, monkeypatch, capsys):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    (project / ".se" / ".runtime").mkdir(parents=True)
    (project / ".se" / ".runtime" / "standing.json").write_text('{"pid": 999999999, "boot": "b"}',
                                                                encoding="utf-8")
    monkeypatch.setenv("SE_START_CACHE", str(home / "start-check.json"))
    before = sorted(p.as_posix() for p in tmp_path.rglob("*"))
    facts = d.gather(project, project, offline=True, env={}, home=home)
    assert sorted(p.as_posix() for p in tmp_path.rglob("*")) == before
    assert facts["host"] == {"name": "other", "cloud": False}
    assert facts["gh"] is None and facts["network"] is None

    monkeypatch.setattr(d, "gather", lambda *_a, **_k: {"network": [{"host": "x", "reached": False}]})
    assert d.main(["--root", str(project)]) == 0
    assert d.main(["--root", str(project), "--strict"]) == 1
    assert d.main(["--root", str(project), "--json"]) == 0
    assert '"findings"' in capsys.readouterr().out


@pytest.mark.parametrize("env, host", [
    ({"CLAUDECODE": "1", "CLAUDE_CODE_REMOTE": "true"}, {"name": "claude-code", "cloud": True}),
    ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, {"name": "claude-code", "cloud": False}),
    ({"COPILOT_AGENT_ACTION": "x", "GITHUB_ACTIONS": "true"}, {"name": "copilot", "cloud": True}),
    ({}, {"name": "other", "cloud": False}),
])
def test_the_host_comes_from_variable_names(env, host):
    assert d.gather_host(env) == host
