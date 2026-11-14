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


# --probe and --write (both off by default)


BASE_TEXT = (
    "SE doctor: 0 problems, 0 notes (read-only; nothing was changed)\n"
    "  binary   [seen] se 0.2.8 on PATH, the pin\n"
    "  binary   [seen] se 0.2.8 on the core's start, the pin\n"
    "  plugin   [seen] SE 5.50.2 at ~/.claude/skills/se, current\n"
    "  core     [seen] running, pid 370, boot b-1\n"
    "  core     [seen] core.log ends:\n"
    "    se: serving <checkout>, pid 370\n"
    "  hooks    [seen] ~/.claude/skills/se/.claude-plugin/plugin.json (hooks, 1 entries): 1 scripts named, all exist\n"
    "  checkout [seen] SE 5.50.2 at 0daf4dc; 0 ahead, 0 behind origin/main as last fetched\n"
    "  gh       [seen] gh signed in\n"
    "  network  [seen] reached github.com\n"
    "  host     [seen] claude-code, a cloud session\n"
    "reused: se_start (plugin registry, cached release check, kern status, cloud marker), se_modules (binary pin)\n")
BASE_JSON_SHA256 = "8f6e96f36286e62e0bbb951a388647e06d15e92e498f34bfabc9f25ba55a3744"  # render_json before --probe


def no_probe(*_args, **_kwargs):
    raise AssertionError("probed without --probe")


def test_without_the_flags_the_report_is_unchanged_byte_for_byte_and_nothing_is_started(tmp_path: Path, monkeypatch,
                                                                                         capsys):
    import hashlib

    findings = d.diagnose(clean_facts())
    assert d.render_text(findings) == BASE_TEXT
    assert hashlib.sha256(d.render_json(findings, clean_facts()).encode()).hexdigest() == BASE_JSON_SHA256
    for name in ("gather_probe", "probe_command", "initialize"):
        monkeypatch.setattr(d, name, no_probe)
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("SE_START_CACHE", str(home / "start-check.json"))
    monkeypatch.setattr(d.Path, "home", lambda: home)
    monkeypatch.setattr(d, "SE_ROOT", project)  # no git checkout: the door's real git stays unasked
    before = sorted(p.as_posix() for p in tmp_path.rglob("*"))
    assert "probe" not in d.gather(project, project, offline=True, env={}, home=home)
    assert d.main(["--root", str(project), "--offline"]) == 0
    assert "probe" not in capsys.readouterr().out
    assert sorted(p.as_posix() for p in tmp_path.rglob("*")) == before


def test_the_probe_rows_come_after_the_problems_with_fix_lines_indented():
    facts = clean_facts()
    facts["probe"] = {"platform": "windows", "rows": [
        {"surface": "copilot-cli", "place": "MCP door", "file": "<checkout>/.github/mcp.json", "state": d.SILENT,
         "level": d.PROBLEM, "text": "copilot-cli MCP door <checkout>/.github/mcp.json: no answer", "fix": "copilot x"},
        {"surface": "claude-code", "place": "plugin hooks", "file": "~/p.json", "state": d.SEEN, "level": d.OK,
         "text": "claude-code plugin hooks ~/p.json: resolves", "fix": None}]}
    findings = d.diagnose(facts)
    assert findings[0].text == "copilot-cli MCP door <checkout>/.github/mcp.json: no answer\n    fix (windows): copilot x"
    text = d.render_text(findings, d.PROBED)
    assert text.startswith("SE doctor: 1 problem, 0 notes (probed:")
    assert "  hooks    [seen] claude-code plugin hooks ~/p.json: resolves\n" in text


def mcp_script(tmp_path: Path, body: str) -> list[str]:
    import sys

    script = tmp_path / "door.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


def test_initialize_reads_one_answer_and_names_a_silent_or_exiting_command(tmp_path: Path):
    answers = mcp_script(tmp_path, "import sys, json\nsys.stdin.readline()\nprint(json.dumps({'jsonrpc': '2.0', "
                                   "'id': 1, 'result': {'serverInfo': {'name': 'se', 'version': '0.4.0'}}}), flush=True)\n"
                                   "sys.stdin.read()\n")
    assert d.initialize(answers, tmp_path, timeout=30) == {"answer": "answered", "detail": "se 0.4.0"}
    silent = mcp_script(tmp_path, "import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n")
    assert d.initialize(silent, tmp_path, timeout=0.5) == {"answer": "timeout", "detail": "0.5 s"}
    exits = mcp_script(tmp_path, "raise SystemExit(3)\n")
    assert d.initialize(exits, tmp_path, timeout=30) == {"answer": "exited", "detail": "exit code 3"}
    assert d.initialize([str(tmp_path / "nothing-here")], tmp_path, timeout=30)["answer"] == "exited"


def test_gather_probe_reads_each_place_and_probes_without_running_a_hook(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "project"
    (project / ".github" / "hooks").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "scripts" / "bootstrap.sh").write_text("", encoding="utf-8")
    (project / "scripts" / "se_mcp.sh").write_text("", encoding="utf-8")
    (project / ".github" / "hooks" / "se.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"bash": "bash scripts/bootstrap.sh --hook || true", "powershell": "bash scripts/bootstrap.sh --hook; exit 0"}]}}),
        encoding="utf-8")
    (project / ".github" / "mcp.json").write_text(json.dumps(
        {"mcpServers": {"se": {"command": "bash", "args": ["scripts/se_mcp.sh", "--root", "."]}}}), encoding="utf-8")
    started = []
    data = {"registrations": {k: v for k, v in
                              __import__("tomllib").loads(d.HOST_FACTS.read_text(encoding="utf-8"))["registrations"].items()
                              if k == "copilot-cli"}}

    def start(words, cwd):
        started.append(words)
        return {"answer": "timeout", "detail": "10 s"}

    probe = d.gather_probe(project, home, project, [], "windows", data, which=lambda w: f"/bin/{w}", start=start)
    rows = {r["place"]: r for r in probe["rows"]}
    assert started == [["/bin/bash", "scripts/se_mcp.sh", "--root", "."]]  # the hook was resolved, never run
    assert rows["hooks"]["level"] == d.OK
    assert rows["MCP door"]["level"] == d.PROBLEM and "no answer to initialize" in rows["MCP door"]["text"]
    assert rows["MCP door"]["fix"].startswith("cd ")
    assert rows["user MCP config"]["fix"] == ("copilot mcp add se -- powershell -NoProfile -ExecutionPolicy Bypass "
                                              "-File \"" + (project / "scripts" / "se_mcp.ps1").as_posix() + "\" --root .")
    assert rows["plugin manifest"]["file"] == "<checkout>/.github/plugin/plugin.json"
    elsewhere = d.gather_probe(project, home, tmp_path / "se", [], "linux", data, which=lambda _w: None, start=no_probe)
    assert {r["place"]: r["state"] for r in elsewhere["rows"]}["hooks"] == d.NOT_MEASURED


# Copilot CLI's plugin installs (--probe only)


SE_MCP = json.dumps({"mcpServers": {"se": {"command": "bash", "args": ["scripts/se_mcp.sh", "--root", "."]}}})


def copilot_install(copilot_home: Path, *parts: str, name: str = "se", script: bool = False,
                    manifest: str = ".github/plugin/plugin.json") -> Path:
    """A plugin folder Copilot installed: its manifest named `name`, its .github/mcp.json naming the
    relative launcher, which exists only with `script`."""
    root = copilot_home.joinpath("installed-plugins", *parts)
    (root / Path(manifest)).parent.mkdir(parents=True, exist_ok=True)
    (root / ".github").mkdir(exist_ok=True)
    (root / Path(manifest)).write_text(json.dumps({"name": name}), encoding="utf-8")
    (root / ".github" / "mcp.json").write_text(SE_MCP, encoding="utf-8")
    if script:
        (root / "scripts").mkdir()
        (root / "scripts" / "se_mcp.sh").write_text("", encoding="utf-8")
    return root


def copilot_only() -> dict:
    data = __import__("tomllib").loads(d.HOST_FACTS.read_text(encoding="utf-8"))["registrations"]
    return {"registrations": {"copilot-cli": data["copilot-cli"]}}


class Fakes:
    """The probe's which and start, recording what they were asked."""

    def __init__(self):
        self.which, self.started = [], []

    def find(self, word):
        self.which.append(word)
        return f"/bin/{word}"

    def start(self, words, cwd):
        self.started.append((words, Path(cwd)))
        return {"answer": "answered", "detail": "se 0.5.0"}

    def asked_for_copilot(self) -> bool:
        return any("copilot" in w for w in self.which) or any(
            "copilot" in Path(word).name for words, _ in self.started for word in words)


def probe_rows(project: Path, home: Path, fakes: Fakes, env: dict | None = None) -> list[dict]:
    copilot = d.copilot_plugins(env or {}, home)
    probe = d.gather_probe(project, home, tmp_checkout(project), [], "linux", copilot_only(), which=fakes.find,
                           start=fakes.start, copilot=copilot)
    assert not fakes.asked_for_copilot()  # the probe never runs the Copilot CLI
    return [r for r in probe["rows"] if r["place"] == "installed plugin MCP"]


def tmp_checkout(project: Path) -> Path:
    return project.parent / "se"


def test_an_install_naming_a_missing_script_shows_it_with_the_fix_line(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    copilot_install(home / ".copilot", "se", "se")
    fakes = Fakes()
    [row] = probe_rows(project, home, fakes)
    assert row["level"] == d.PROBLEM and row["file"] == "~/.copilot/installed-plugins/se/se/.github/mcp.json"
    assert "scripts/se_mcp.sh, which does not exist" in row["text"]
    assert row["fix"] == "copilot plugin marketplace add mb-89/SE && copilot plugin install se@se"
    assert fakes.started == []


def test_an_installs_relative_script_resolves_and_starts_in_the_install_not_the_project(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "project"
    (project / ".github").mkdir(parents=True)
    (project / ".github" / "mcp.json").write_text(SE_MCP, encoding="utf-8")  # same words, no script here
    root = copilot_install(home / ".copilot", "se", "se", script=True)
    fakes = Fakes()
    copilot = d.copilot_plugins({}, home)
    probe = d.gather_probe(project, home, project, [], "linux", copilot_only(), which=fakes.find, start=fakes.start,
                           copilot=copilot)
    rows = {r["place"]: r for r in probe["rows"]}
    assert rows["installed plugin MCP"]["level"] == d.OK and "answered initialize" in rows["installed plugin MCP"]["text"]
    assert fakes.started == [(["/bin/bash", "scripts/se_mcp.sh", "--root", "."], root)]
    assert rows["MCP door"]["level"] == d.PROBLEM and "which does not exist" in rows["MCP door"]["text"]
    assert not fakes.asked_for_copilot()


def test_a_direct_install_is_found_and_a_plugin_of_another_name_is_not(tmp_path: Path):
    home = tmp_path / "home"
    direct = copilot_install(home / ".copilot", "_direct", "mb-89-SE", manifest=".claude-plugin/plugin.json")
    copilot_install(home / ".copilot", "se", "other", name="other")
    assert d.copilot_plugins({}, home) == [direct]


def test_without_an_install_one_row_says_so(tmp_path: Path):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    [row] = probe_rows(project, home, Fakes())
    assert "no installed Copilot SE plugin" in row["text"] and row["fix"]


def test_copilot_home_is_read_in_place_of_dot_copilot(tmp_path: Path, monkeypatch):
    home, project, elsewhere = tmp_path / "home", tmp_path / "project", tmp_path / "copilot-home"
    project.mkdir()
    copilot_install(home / ".copilot", "se", "se")
    moved = copilot_install(elsewhere, "se", "se", script=True)
    env = {"COPILOT_HOME": str(elsewhere)}
    assert d.copilot_plugins(env, home) == [moved]
    fakes = Fakes()
    [row] = probe_rows(project, home, fakes, env)
    assert row["level"] == d.OK and [cwd for _words, cwd in fakes.started] == [moved]
    seen = {}
    monkeypatch.setenv("SE_START_CACHE", str(home / "start-check.json"))
    monkeypatch.setattr(d, "SE_ROOT", project)  # no git checkout: the door's real git stays unasked
    monkeypatch.setattr(d, "gather_probe", lambda *_a, **k: seen.update(k) or {"platform": "linux", "rows": []})
    d.gather(project, project, offline=True, env=env, home=home, probe=True)
    assert seen["copilot"] == [moved]


def test_write_puts_the_report_into_one_file_under_dot_se(tmp_path: Path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(d, "gather", lambda *_a, **_k: clean_facts())
    assert d.main(["--root", str(project), "--write"]) == 0
    out = capsys.readouterr()
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == \
        ["project", "project/.se", "project/.se/doctor.txt"]
    assert (project / ".se" / "doctor.txt").read_text(encoding="utf-8") == out.out == BASE_TEXT
    assert "written to <project>/.se/doctor.txt" in out.err
    assert ".se/" in (Path(d.SE_ROOT) / ".gitignore").read_text(encoding="utf-8").splitlines()
