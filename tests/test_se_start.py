"""Tests for scripts/se_start.py: the greeting, status from its cache, check and refresh, on fakes and
temporary local git repositories (no network)."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

import pytest
import fake_git
import fake_processes as fake_programs

# Its git is the fake in memory; a test whose scripts or binaries run git as child processes takes
# the fake behind one state file, `shared_fake_git` (tests/conftest.py `door_fake`).
pytestmark = pytest.mark.usefixtures("door_fake")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("se_start", ROOT / "scripts" / "se_start.py")
se_start = importlib.util.module_from_spec(_spec)
sys.modules["se_start"] = se_start
_spec.loader.exec_module(se_start)
se_modules = se_start.se_modules
import se_runtimes  # noqa: E402  (scripts/ is on the path, tests/conftest.py)

SE_URL = "https://git.example.org/team/se.git"
LIB_URL = "https://git.example.org/team/lib.git"
TOOL_URL = "https://git.example.org/team/tool.git"
OBS_URL = "https://git.example.org/team/obs.git"
DEEP_URL = "https://git.example.org/team/deep.git"
SHA = "a" * 40


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Clock:
    """A fake clock: time moves only where a test or a fake remote moves it."""

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Remotes:
    """Fake remotes: tags per url, or offline; each read costs 5 seconds of the fake clock."""

    def __init__(self, clock: Clock, tags: dict[str, list[str]], offline: bool = False):
        self.clock, self.tags, self.offline, self.calls = clock, tags, offline, []

    def __call__(self, url: str):
        self.calls.append(url)
        self.clock.now += 5
        if self.offline:
            raise se_start.RemoteError(f"cannot reach {url}: Could not resolve host")
        return [se_modules.parse_version(tag[1:]) for tag in self.tags.get(url, [])]


class Placed(list):
    """The fake placing of SE's own tree (se_modules.place_tree): records each root, or refuses with
    `refusal`."""

    def __init__(self, refusal: str = ""):
        super().__init__()
        self.refusal = refusal

    def __call__(self, root, local):
        self.append(root)
        if self.refusal:
            raise se_modules.ModuleError(self.refusal)


class Loaders(list):
    """The fake of the loaders' commands (se_start.run_command), in-process: obs's probe answers
    `obs` and the components in `installed`; `obs-components install` installs one where `offered`
    holds it; an adapter's `--help` answers 0 unless its name is in `broken`. Records each command."""

    def __init__(self, obs: str | None = "10.3.2", installed: dict | None = None, offered: tuple = (),
                 broken: tuple = ()):
        super().__init__()
        self.obs, self.installed, self.offered, self.broken = obs, dict(installed or {}), offered, broken

    def __call__(self, argv, cwd, timeout):
        self.append(list(argv))
        if argv[-2:-1] == ["-c"] and argv[-1] == se_start.OBS_PROBE:
            if self.obs is None:
                return 1, "", "ModuleNotFoundError: No module named 'obs'"
            return 0, json.dumps({"obs": self.obs, "installed": self.installed}) + "\n", ""
        if "obs-components" in argv:
            name, version = argv[-2], argv[-1]
            if name not in self.offered:
                return 1, "", f"obs-components: install: {name}: no remote offers it"
            self.installed[name] = {"version": version, "kind": "adapter", "folder": f"/obs/{name}",
                                    "command": ["uv", "run", name]}
            return 0, f"obs-components: installed {name} {version} (adapter)\n", ""
        if argv[-1] == "--help":
            return (1, "", "ImportError: broken") if argv[2] in self.broken else (0, "usage: ...\n", "")
        raise AssertionError(f"unexpected loader command {argv}")


class Spawns(list):
    def __call__(self, argv):
        self.append(argv)


class Work(list):
    """The fake work check: records each project it reads and answers `found` (None: no gh)."""

    def __init__(self, found: dict | None = None):
        super().__init__()
        self.found = found

    def __call__(self, root):
        self.append(root)
        return self.found


def plugin(path: Path, version: str = "1.2.0", *, origin: str | None = SE_URL) -> Path:
    """A fixture plugin: three agents (SE and two sub-agents) and two skills in its Claude layout."""
    write(path / "se.toml", f'[project]\nversion = "{version}"\ndocs_url = "https://docs.example.com/se/"\n')
    for name in ("se", "integrator", "worker"):
        write(path / "agents" / f"{name}.md", f"---\nname: {name}\n---\n")
    for name in ("catch-up", "decision"):
        write(path / "skills" / name / "SKILL.md", f"---\nname: {name}\n---\n")
    write(path / "skills" / "decision" / "example.md", "not a skill\n")
    if origin:
        write(path / ".git" / "HEAD", "")
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    se = plugin(tmp_path / "se")
    monkeypatch.setattr(se_start, "_origin", lambda root: SE_URL if (root / ".git").exists() else None)
    project = tmp_path / "project"
    local_dir = tmp_path / "local-lib"
    write(local_dir / "se.toml", '[project]\nversion = "3.1.0"\n')
    write(project / "se.toml", f"""
[components.lib]
version = "^1.2"

[components.tool]
version = "~2.0.1"

[components.mine]
version = "^3"

[components.obs]
ref = "{SHA}"
""")
    # Where each placed component was found: its clone's origin (se_start._found_at).
    monkeypatch.setattr(se_start, "_found_at", lambda clone: f"https://git.example.org/team/{clone.name}.git")
    write(project / "se.lock", f"""
[components.lib]
version = "1.2.0"
ref = "{SHA}"

[components.tool]
version = "2.0.3"
ref = "{SHA}"
""")
    config = write(tmp_path / "local.toml", f'[paths]\nmine = "{local_dir.as_posix()}"\n')
    clock = Clock()
    tags = {SE_URL: ["v1.2.0", "v1.3.0", "v2.0.0"], LIB_URL: ["v1.2.0", "v1.4.1", "v2.0.0"],
            TOOL_URL: ["v2.0.3", "v2.1.0"], OBS_URL: ["v0.9.0"]}
    remotes = Remotes(clock, tags)
    world = se_start.World(clock=clock, remote=remotes, spawn=Spawns(), work=Work(), place=Placed(),
                           run=Loaders())
    return dict(se=se, project=project, config=config, cache=tmp_path / "cache.json",
                clock=clock, remotes=remotes, world=world)


def report(s, command="status", offline=False):
    if command == "check":
        return se_start.check(s["se"], s["project"], s["config"], s["cache"], s["world"])
    return se_start.status(s["se"], s["project"], s["config"], s["cache"], s["world"], offline)


def by_name(rep):
    return {state.item.name: state for state in rep.states}


def said(rep, se):
    """The start report, then what the start found for the session alone."""
    return se_start.greeting(rep, se) + se_start.session_lines(rep, se)


# Requirement 1: counts from what loaded.


def test_counts_come_from_the_fixture_plugin(setup):
    write(setup["se"] / "skills" / "work-model" / "references" / "rules.md",
          "# Rules\n\n### gen-001 Mechanize first\n\n### pub-002 A generic identity\n")
    write(setup["se"] / "skills" / "a-note" / "SKILL.md", "---\nname: a-note\ndescription: 'A note.'\n---\n"
          "<!-- Code generated by se_plugin.py build from guidance/a-note.md. DO NOT EDIT. -->\n")
    rep = report(setup, offline=True)
    docs = "https://docs.example.com/se/"
    assert se_start.greeting(rep, setup["se"])[:5] == [
        "SE 1.2.0 started", f"[2 skills]({docs}#docs-skills)", f"[3 rules]({docs}#docs-rules)",
        f"[2 sub-agents]({docs}#docs-sub-agents)", f"[Documentation]({docs})"]


def test_the_rules_are_the_public_checks_labels():
    labels = {pattern.label for pattern in se_start.public_check.GENERIC_PATTERNS}
    messages = {"tracker-reference", "attribution-trailer", "message-address"}
    assert set(se_start.public_check.RULES) == labels | messages
    assert len(se_start.public_check.RULES) == len(labels) + len(messages)



def test_the_detached_start_on_linux_and_macos_is_a_new_session_as_before():
    assert se_start.detached_options("posix") == {"start_new_session": True}

# Requirement 1: each module's state.


def test_up_to_date_out_of_date_newer_major_local_path_and_commit_pin(setup):
    states = by_name(report(setup, "check"))
    assert states["tool"].due is None and states["tool"].outside == (2, 1, 0)  # ~2.0.1 admits 2.0.x
    assert states["lib"].due == (1, 4, 1) and states["lib"].outside == (2, 0, 0)
    assert states["SE"].due == (1, 3, 0) and states["SE"].outside == (2, 0, 0)
    assert states["mine"].item.kind == "local" and states["mine"].item.version == (3, 1, 0)
    assert states["obs"].due is None and states["obs"].latest == (0, 9, 0)
    lines = se_start.full(report(setup), setup["se"])
    assert any(line.startswith("tool: in use 2.0.3; latest 2.1.0; up to date; 2.1.0 is outside ~2.0.1, never "
                               "applied by refresh; to take it, set version = \"^2.1\" in [components.tool] of ")
               for line in lines)
    assert any(line.startswith("lib: in use 1.2.0; latest 2.0.0; update due to 1.4.1; 2.0.0 is outside ^1.2, "
                               "never applied by refresh; to take it, set version = \"^2.0\" in [components.lib] of ")
               for line in lines)
    assert any(line.startswith("mine: in use 3.1.0 (local path ") and line.endswith("local, refresh never touches it")
               for line in lines)
    assert any(line.startswith("obs: in use none (pinned to commit aaaaaaa); latest 0.9.0; pinned by commit")
               for line in lines)
    assert sorted(setup["remotes"].calls) == sorted([SE_URL, LIB_URL, TOOL_URL, OBS_URL])  # one read each


def test_the_report_is_its_template_filled_a_table_of_every_component_and_the_one_update_line(setup):
    """The person's shape of 23 Nov: no paths, no `uv run`, no per-module lines; one update line."""
    report(setup, "check")
    lines = se_start.greeting(report(setup), setup["se"])
    assert lines[5:] == ["", "| component | loaded | newest |", "|---|---|---|",
                         "| SE | 1.2.0 | 2.0.0 |", "| lib | 1.2.0 | 2.0.0 |", "| tool | 2.0.3 | 2.1.0 |",
                         "| mine | 3.1.0 | local |", "| obs | none | 0.9.0 |", "", "To update: /se:update"]
    text = "\n".join(lines)
    assert "uv run" not in text and setup["se"].as_posix() not in text
    catalog = se_start._load("templates").load(ROOT, tree=True)
    template = catalog[se_start.REPORT]
    assert se_start._load("templates").check(template, se_start._load("templates").parse(template, text)) == []


def test_an_se_several_majors_behind_is_one_row_and_the_one_update_line(setup):
    """SE 5.x with SE 12 released: SE's row names both, and a project's own pin of se is no second row."""
    plugin(setup["se"], "5.134.2")
    write(setup["project"] / "se.toml", '[components.se]\nversion = "^5.134"\n')
    write(setup["project"] / "se.lock", f'[components.se]\nversion = "5.134.2"\nref = "{SHA}"\n')
    setup["remotes"].tags = {SE_URL: ["v5.134.2", "v11.1.0", "v12.0.0"]}
    report(setup, "check")
    lines = se_start.greeting(report(setup), setup["se"])
    assert lines[-4:] == ["|---|---|---|", "| SE | 5.134.2 | 12.0.0 |", "", "To update: /se:update"]


def test_an_up_to_date_report_says_so_in_its_last_line_and_the_session_gets_nothing(setup):
    write(setup["project"] / "se.toml", '[components.lib]\nversion = "^1.2"\n\n[components.tool]\n'
          'version = "~2.0.1"\n')
    setup["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}
    report(setup, "check")
    assert se_start.greeting(report(setup), setup["se"])[-1] == "Everything is current."
    assert se_start.session_lines(report(setup), setup["se"]) == []


def test_a_report_before_the_first_check_says_the_newest_versions_are_not_read_yet(setup):
    lines = se_start.greeting(report(setup, offline=True), setup["se"])
    assert "| lib | 1.2.0 | unknown |" in lines
    assert lines[-1] == "Newest versions not read yet; the next start shows them."


def test_a_nested_component_the_lock_holds_is_a_row_of_its_own(setup):
    with (setup["project"] / "se.lock").open("a", encoding="utf-8") as lock:
        lock.write(f'\n[components.deep]\nversion = "0.3.0"\nref = "{SHA}"\n')
    setup["remotes"].tags[DEEP_URL] = ["v0.3.0", "v0.4.0"]
    report(setup, "check")
    assert "| deep | 0.3.0 | 0.4.0 |" in se_start.greeting(report(setup), setup["se"])


def _manifest(root: Path, name: str = "se") -> None:
    write(root / se_start.PLUGIN_MANIFEST, json.dumps({"name": name}))


def test_a_plugin_older_than_the_se_checkout_it_works_on_is_named_in_one_line(setup):
    """A cloud container restored from a cached snapshot runs an older plugin than the checkout."""
    setup["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}
    report(setup, "check")
    _manifest(setup["se"])
    _manifest(setup["project"])
    write(setup["project"] / "se.toml", '[project]\nversion = "1.4.0"\n')
    lines = se_start.session_lines(report(setup), setup["se"])
    assert lines == ["SE 1.2.0 runs, older than this checkout's SE 1.4.0: in the cloud, a container "
                         "restored from a cached snapshot, which the environment rebuilds only when its "
                         "setup script changes (README \"Cloud sessions\")"]
    # Current, or a checkout of another plugin: no line.
    for version, name in (("1.2.0", "se"), ("1.4.0", "other")):
        write(setup["project"] / "se.toml", f'[project]\nversion = "{version}"\n')
        _manifest(setup["project"], name)
        assert se_start.session_lines(report(setup), setup["se"]) == []


# Requirement 4: errors say where they come from and the remedy; the greeting still appears.


def test_offline_marks_the_check_as_not_done(setup):
    setup["remotes"].offline = True
    assert report(setup, "check").errors
    lines = said(report(setup), setup["se"])
    assert lines[0] == "SE 1.2.0 started"
    assert f"Update check not done: lib: cannot reach {LIB_URL}: Could not resolve host; run it by hand to see " \
           f"the cause: uv run python {setup['se'].as_posix()}/scripts/se_start.py check" in lines


def test_a_bad_manifest_is_named_and_the_greeting_still_appears(setup):
    write(setup["project"] / "se.toml", "[components.lib]\nurl = 1\n")
    lines = said(report(setup, offline=True), setup["se"])
    assert lines[0] == "SE 1.2.0 started"
    assert any("modules of" in line and "url is refused" in line for line in lines)


def test_an_installed_copy_is_checked_against_its_plugin_manifests_repository(setup):
    shutil.rmtree(setup["se"] / ".git")
    write(setup["se"] / ".claude-plugin" / "plugin.json", json.dumps({"name": "se", "repository": SE_URL}))
    states = by_name(report(setup, "check"))
    assert states["SE"].item.note == "an installed copy" and states["SE"].due == (1, 3, 0)
    assert SE_URL in setup["remotes"].calls


def test_an_installed_copy_is_checked_against_the_marketplace_claude_code_installed_it_from(
        setup, tmp_path, monkeypatch):
    shutil.rmtree(setup["se"] / ".git")
    claude = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    write(claude / "plugins" / "installed_plugins.json",
          json.dumps({"plugins": {"se@team": [{"installPath": str(setup["se"])}]}}))
    write(claude / "plugins" / "known_marketplaces.json",
          json.dumps({"team": {"source": {"source": "git", "url": SE_URL}}}))
    states = by_name(report(setup, "check"))
    assert states["SE"].item.note == "an installed copy" and states["SE"].due == (1, 3, 0)
    assert SE_URL in setup["remotes"].calls
    write(claude / "plugins" / "known_marketplaces.json",
          json.dumps({"team": {"source": {"source": "github", "repo": "alice/se"}}}))
    assert se_start._marketplace_repository(setup["se"]) == "https://github.com/alice/se"


def test_an_installed_copy_without_a_repository_is_not_checked(setup):
    shutil.rmtree(setup["se"] / ".git")
    states = by_name(report(setup, "check"))
    assert states["SE"].item.url is None and states["SE"].due is None
    assert SE_URL not in setup["remotes"].calls


# Requirement 1 and acceptance: status answers within its budget from the cache.


def test_status_answers_from_a_fresh_cache_without_the_network(setup):
    report(setup, "check")
    setup["remotes"].calls.clear()
    start = setup["clock"].now
    rep = report(setup)
    assert setup["remotes"].calls == [] and setup["world"].spawn == []
    assert setup["clock"].now - start < se_start.feedback.budget("se_start.py status")
    assert by_name(rep)["lib"].due == (1, 4, 1)


def test_a_stale_cache_answers_at_once_and_checks_in_the_background(setup):
    report(setup, "check")
    setup["remotes"].calls.clear()
    setup["clock"].now += se_start.MAX_AGE + 1
    start = setup["clock"].now
    rep = report(setup)
    assert setup["clock"].now - start < se_start.feedback.budget("se_start.py status") and setup["remotes"].calls == []
    assert [argv[-1] for argv in setup["world"].spawn] == ["check"]
    assert by_name(rep)["lib"].due == (1, 4, 1)  # the last check's answer meanwhile
    report(setup)  # a second start while the check runs starts no second one
    assert len(setup["world"].spawn) == 1


def test_no_cache_yet_says_the_check_runs_in_the_background(setup):
    lines = said(report(setup), setup["se"])
    assert lines[-1] == "Update check not done: running in the background; the next start shows its result"
    assert setup["remotes"].calls == []


def test_a_new_module_without_a_cached_answer_starts_a_check(setup):
    report(setup, "check")
    write(setup["project"] / "se.toml", f'[components.new]\nversion = "^1"\n')
    report(setup)
    assert len(setup["world"].spawn) == 1


def test_the_hook_shows_the_person_the_report_a_stop_above_it_and_hands_the_rest_to_the_session():
    data = json.loads(se_start.hook_output(["SE 1.2.0 started", "Everything is current."],
                                           ["se bootstrap: installing uv", "SE cannot start: no lib"],
                                           Path("/opt/se"), session=["Retro due: 9 issues"]))
    assert data["systemMessage"] == "SE cannot start: no lib\nSE 1.2.0 started\nEverything is current."
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = data["hookSpecificOutput"]["additionalContext"]
    assert context.startswith(data["systemMessage"] + "\n\n" + se_start.FOR_SESSION
                              + "\nse bootstrap: installing uv\nRetro due: 9 issues\n\n")


def test_copilots_hook_output_hands_the_same_greeting_as_its_one_field():
    """Copilot's sessionStart reads only `additionalContext` (scripts/hosts.sh)."""
    claude = json.loads(se_start.hook_output(["SE 1.2.0 started: ..."], [], Path("/opt/se")))
    copilot = json.loads(se_start.hook_output(["SE 1.2.0 started: ..."], [], Path("/opt/se"), "copilot"))
    context = claude["hookSpecificOutput"]["additionalContext"]
    assert copilot == {"additionalContext": context.replace(", already shown to the person", "", 1)}
    assert "SE's start report. As SE, open your first message" in copilot["additionalContext"]


def _agent_root(tmp_path: Path) -> Path:
    agents = tmp_path / "se" / "agents"
    agents.mkdir(parents=True)
    (agents / "se.md").write_text("# se\n", encoding="utf-8")
    return tmp_path / "se"


def _contexts(root: Path) -> dict[str, dict]:
    return {host: json.loads(se_start.hook_output(["SE 1.2.0 started: ..."], ["n"], root, host))
            for host in ("claude", "copilot")}


def _context(data: dict) -> str:
    return data.get("additionalContext") or data["hookSpecificOutput"]["additionalContext"]


def test_default_agent_se_ends_the_hand_over_with_the_sentence_for_both_hosts(tmp_path, monkeypatch):
    root = _agent_root(tmp_path)
    monkeypatch.setenv("SE_DEFAULT_AGENT", "se")
    sentence = ("This session acts as the se agent unless it was started as another agent (--agent, an agent "
                "picker) or its first message names another agent file, also where a compaction summarized "
                f"that message: read {root}/agents/se.md first and act as it defines.")
    for host, data in _contexts(root).items():
        assert _context(data).endswith("\n\n" + sentence), host
        assert _context(data).count(sentence) == 1
    assert "acts as the se agent" not in _contexts(root)["claude"]["systemMessage"]


@pytest.mark.parametrize("value", ["worker", "se"])
def test_default_agent_that_names_no_agent_gives_the_note_and_no_sentence(tmp_path, monkeypatch, value):
    """`worker` is no agent a session starts as; `se` without its agent file names none either."""
    root = tmp_path / "se" if value == "se" else _agent_root(tmp_path)
    monkeypatch.setenv("SE_DEFAULT_AGENT", value)
    note = f"SE: SE_DEFAULT_AGENT names no agent a session starts as: {value}"
    for host, data in _contexts(root).items():
        assert _context(data).startswith(f"SE 1.2.0 started: ...\n\n{se_start.FOR_SESSION}\n{note}\nn\n"), host
        assert "acts as the se agent" not in _context(data)
    assert _contexts(root)["claude"]["systemMessage"] == "SE 1.2.0 started: ..."


@pytest.mark.parametrize("value", [None, ""])
def test_default_agent_unset_or_empty_leaves_the_output_byte_identical(tmp_path, monkeypatch, value):
    root = _agent_root(tmp_path)
    monkeypatch.delenv("SE_DEFAULT_AGENT", raising=False)
    before = {host: se_start.hook_output(["SE 1.2.0 started: ..."], ["n"], root, host)
              for host in ("claude", "copilot")}
    if value is not None:
        monkeypatch.setenv("SE_DEFAULT_AGENT", value)
    for host, output in before.items():
        assert se_start.hook_output(["SE 1.2.0 started: ..."], ["n"], root, host) == output
        assert "acts as the se agent" not in output
        assert "SE_DEFAULT_AGENT" not in output


def test_the_hook_context_names_ses_root_for_the_session_only(setup, capsys, monkeypatch):
    """The session finds SE's scripts at the root the hook names, not by searching for the plugin."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    assert se_start.main(["--root", str(setup["project"]), "--local", str(setup["config"]),
                          "--cache", str(setup["cache"]), "status", "--hook", "--offline"],
                         world=setup["world"]) == 0
    data = json.loads(capsys.readouterr().out)
    context = data["hookSpecificOutput"]["additionalContext"]
    assert f"\nSE root: {setup['se']}\n" in context
    assert "<se>/scripts/<name>.py" in context
    assert "SE root" not in data["systemMessage"]


# kern's state, as bootstrap.sh hands it over (README "Kern").

def bare_kern(se: Path) -> None:
    """The installed SE pins kern 0.2.0 by its go.mod (se.toml [components.kern]), its clone placed."""
    manifest = se / "se.toml"
    text = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
    write(manifest, text + '\n[components.kern]\ngo = true\n')
    write(se / "go.mod", "module se\n\nrequire kern v0.2.0\n")
    write(se / ".se" / "modules" / "kern" / "release.toml",
          'version = "0.2.0"\ndownload = "https://example.com/alice/kern/releases/download/v{version}"\n')


def kern_greeting(setup, capsys, monkeypatch, *args, answer=None, stops=None):
    """The hook's greeting lines with bootstrap.sh's kern arguments, kern's status answering `answer`,
    the project inside a git checkout, so the core runs for it. kern is SE's one required component
    here: the report shows the person its row and, where it did not load, the stop."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    bare_kern(setup["se"])
    write(setup["project"] / ".git" / "HEAD", "")
    asked = []
    world = dataclasses.replace(setup["world"], kern=lambda binary, root: asked.append((binary, root)) or answer)
    assert se_start.main(["--root", str(setup["project"]), "--local", str(setup["config"]),
                          "--cache", str(setup["cache"]), "status", "--hook", "--offline", *args],
                         world=world) == 0
    data = json.loads(capsys.readouterr().out)
    shown = data["systemMessage"].splitlines()
    assert not any(line.startswith("kern 0.2.0:") for line in shown), "no daemon line in the report"
    stop = [line for line in shown if line.startswith(se_start.STOP)]
    if stops is not None:
        assert len(stop) == 1 and stop[0].startswith(f"{se_start.STOP}: the required component kern did not "
                                                     f"load: {stops}")
    context = data["hookSpecificOutput"]["additionalContext"].splitlines()
    return context[context.index(se_start.FOR_SESSION):], asked


def test_the_greeting_names_a_running_kern_under_its_first_line(setup, capsys, monkeypatch):
    lines, asked = kern_greeting(setup, capsys, monkeypatch, "--kern-bin", "/k/kern-0.2.0",
                                 answer={"state": "running", "health": {"pid": 42}}, stops=None)
    assert lines[1] == "kern 0.2.0: running", "no pid"
    assert asked == [(Path("/k/kern-0.2.0"), setup["project"].resolve())], "asked once, for its line and its row"


@pytest.mark.parametrize(("args", "answer", "line", "stop"), [
    (["--kern-bin", "/k"], {"state": "starting"}, "kern 0.2.0: starting", "/k the core is starting; see "),
    (["--kern-failed", "kern start: boom", "--kern-bin", "/k"], {"state": "running"},
     "kern 0.2.0: failed: kern start: boom", "kern start: boom"),
    (["--kern-bin", "/k"], {"state": "not running"}, "kern 0.2.0: failed: not running after its start; see ",
     "/k the core is not running; see "),
    (["--kern-bin", "/k"], None, "kern 0.2.0: failed: its status does not answer; see ",
     "/k its status does not answer; see "),
])
def test_the_greeting_names_kern_starting_or_failed_with_the_cause(setup, capsys, monkeypatch, args, answer, line,
                                                                   stop):
    """A kern that does not answer running stops the start, naming it and the cause (docs/boot.md
    "Required components"); the session's line says the same as before."""
    lines, _ = kern_greeting(setup, capsys, monkeypatch, *args, answer=answer, stops=stop)
    assert lines[1].startswith(line)
    if "see " in line:
        assert lines[1].endswith(str(setup["project"].resolve() / ".se" / ".runtime" / "core.log"))


def test_the_greeting_names_a_core_that_ended_at_its_start_with_the_first_lines_it_said(
        setup, capsys, monkeypatch):
    # kern's status names what a core that ended at its start said (its died file); the greeting
    # says failed with it, not starting: the core se-v0.1.0 shipped refused main's wiring so.
    said = ("kern serve: index: the catalog is broken:\n"
            "  wiring line 58: instance retro-due: no component retro-due is registered")
    lines, _ = kern_greeting(setup, capsys, monkeypatch, "--kern-bin", "/k",
                             answer={"state": "not running", "health": {}, "died": said})
    log = setup["project"].resolve() / ".se" / ".runtime" / "core.log"
    assert lines[1:5] == ["kern 0.2.0: failed: the core ended at its start; it said:",
                          "  kern serve: index: the catalog is broken:",
                          "    wiring line 58: instance retro-due: no component retro-due is registered",
                          f"  (all of it in {log})"]


@pytest.mark.parametrize(("host", "args", "said"), [
    ("copilot", ["--kern-failed", "no se 0.3.0 release, and no go to build it"], True),
    ("claude", ["--kern-failed", "no se 0.3.0 release, and no go to build it"], False),
])
def test_under_copilot_a_failed_kern_says_se_runs_without_it(setup, capsys, monkeypatch, host, args, said):
    """Copilot's sessions work with no core, through SE's scripts and gh, and the greeting says so;
    Claude Code's greeting stays as it is."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    bare_kern(setup["se"])
    assert se_start.main(["--root", str(setup["project"]), "--local", str(setup["config"]), "--cache",
                          str(setup["cache"]), "status", "--hook", "--offline", "--host", host, *args],
                         world=setup["world"]) == 0
    out = json.loads(capsys.readouterr().out)
    text = out["additionalContext"] if host == "copilot" else out["hookSpecificOutput"]["additionalContext"]
    assert (se_start.WITHOUT_KERN in text.splitlines()) is said
    if said:
        lines = text.splitlines()
        assert lines[lines.index(se_start.WITHOUT_KERN) - 1].startswith("kern 0.2.0: failed: ")


# SE's required components (docs/boot.md "Required components"): kern, obs and obs-html, loaded from
# SE's root wherever the session starts, each row the version that answered.

OBS_HTML = {"version": "0.5.2", "kind": "adapter", "folder": "/obs/obs-html", "command": ["uv", "run", "obs-html"]}


def required_se(se: Path) -> None:
    """The installed SE declares kern (by its go.mod), obs and obs-html, and locks them; kern's clone
    is placed, its binary named in SE's runtime as bootstrap.sh names it for SE's root."""
    bare_kern(se)
    manifest = se / "se.toml"
    write(manifest, manifest.read_text(encoding="utf-8")
          + '\n[components.obs]\nversion = "^10.3.2"\n\n[components.obs-html]\nversion = "^0.5.2"\n')
    write(se / "se.lock", f'[components.kern]\nversion = "0.2.0"\nref = "{SHA}"\n\n'
          f'[components.obs]\nversion = "10.3.2"\nref = "{SHA}"\n\n'
          f'[components.obs-html]\nversion = "0.5.2"\nref = "{SHA}"\n')
    write(se / ".se" / ".runtime" / "kern.path", "/bin/se-kern-0.2.0\n")


def required_start(setup, monkeypatch, capsys, *args, loaders=None, answer=None, placed=None, where=None):
    """`status --greeting` of the SE `required_se` made, started in `where` (default: a folder that
    is no repository and holds no project), each door an in-process fake: the placing, the loaders'
    commands and kern's status, which answers `answer` (default: running). The report's lines, what
    the session alone gets, and the fakes."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    if not (setup["se"] / "se.lock").is_file():
        required_se(setup["se"])
    folder = where or setup["se"].parent / "home"
    folder.mkdir(exist_ok=True)
    asked = []
    loaders = Loaders(installed={"obs-html": dict(OBS_HTML)}) if loaders is None else loaders
    placed = Placed() if placed is None else placed
    answer = {"state": "running", "health": {"pid": 7}} if answer is None else answer
    world = dataclasses.replace(setup["world"], run=loaders, place=placed,
                                kern=lambda binary, root: asked.append((binary, root)) or answer)
    assert se_start.main(["--root", str(folder), "--local", str(setup["config"]), "--cache", str(setup["cache"]),
                          "status", "--greeting", "--offline", *args], world=world) == 0
    out = capsys.readouterr().out
    report, _, session = out.partition(f"\n\n{se_start.FOR_SESSION}\n")
    return report.splitlines(), session.splitlines(), dict(asked=asked, loaders=loaders, placed=placed)


def table(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("| ") and not line.startswith("| component")]


def test_started_in_a_folder_that_is_no_repository_the_report_lists_se_kern_obs_and_obs_html_as_they_answered(
        setup, monkeypatch, capsys):
    report, _, fakes = required_start(setup, monkeypatch, capsys)
    assert table(report) == ["| SE | 1.2.0 | unknown |", "| kern | 0.2.0 | unknown |",
                             "| obs | 10.3.2 | unknown |", "| obs-html | 0.5.2 | unknown |"]
    assert not any(line.startswith(se_start.STOP) for line in report)
    assert report[-1] == "Newest versions not read yet; the next start shows them.", "the required rows count too"
    assert fakes["placed"] == [setup["se"]], "SE's own tree, placed from SE's root"
    assert fakes["asked"] == [(Path("/bin/se-kern-0.2.0"), setup["se"])], "the core runs for SE's root"
    probe, run = fakes["loaders"]
    assert probe[:5] == ["uv", "run", "--quiet", "--project", str(setup["se"] / ".se" / "modules" / "obs")]
    assert run == ["uv", "run", "obs-html", "--help"], "obs-html runs, not only installs"


def test_the_update_line_counts_the_required_rows_whose_newest_is_not_read(setup, monkeypatch, capsys):
    """SE's own row is read and current, the required rows' newest not read yet: the last line says
    so, not that everything is current."""
    se_start.Cache(setup["clock"](), None, {SE_URL: {"versions": [[1, 2, 0]]}}).write(setup["cache"])
    report, _, _ = required_start(setup, monkeypatch, capsys)
    assert table(report)[0] == "| SE | 1.2.0 | 1.2.0 |" and "| obs | 10.3.2 | unknown |" in table(report)
    assert report[-1] == "Newest versions not read yet; the next start shows them."


def test_the_loaded_column_is_the_version_that_answered_never_the_locked_one(setup, monkeypatch, capsys):
    """obs answers 10.4.0 from its clone while SE locks 10.3.2: the row says 10.4.0."""
    report, _, _ = required_start(setup, monkeypatch, capsys,
                                  loaders=Loaders(obs="10.4.0", installed={"obs-html": dict(OBS_HTML)}))
    assert "| obs | 10.4.0 | unknown |" in table(report)


def test_obs_html_missing_is_installed_at_ses_locked_version_and_then_answers(setup, monkeypatch, capsys):
    loaders = Loaders(installed={}, offered=("obs-html",))
    report, _, _ = required_start(setup, monkeypatch, capsys, loaders=loaders)
    assert "| obs-html | 0.5.2 | unknown |" in table(report)
    install = [argv for argv in loaders if "obs-components" in argv]
    assert install == [["uv", "run", "--quiet", "--project", str(setup["se"] / ".se" / "modules" / "obs"),
                        "obs-components", "install", "obs-html", "0.5.2"]]


def test_obs_html_at_another_version_is_installed_at_the_locked_one(setup, monkeypatch, capsys):
    loaders = Loaders(installed={"obs-html": {**OBS_HTML, "version": "0.4.0"}}, offered=("obs-html",))
    report, _, _ = required_start(setup, monkeypatch, capsys, loaders=loaders)
    assert "| obs-html | 0.5.2 | unknown |" in table(report)
    assert any(argv[-3:] == ["install", "obs-html", "0.5.2"] for argv in loaders)


@pytest.mark.parametrize(("loaders", "stops"), [
    (Loaders(installed={}), ["obs-html did not load: `obs-components install obs-html 0.5.2` from "]),
    (Loaders(installed={"obs-html": dict(OBS_HTML)}, broken=("obs-html",)),
     ["obs-html did not load: uv run obs-html --help in /obs/obs-html failed: ImportError: broken"]),
    (Loaders(obs=None), ["obs did not load: obs does not import from ", "obs-html did not load: obs does not import"]),
], ids=["not-offered", "does-not-run", "obs-does-not-import"])
def test_a_required_component_that_does_not_load_stops_the_start_naming_it_and_the_cause(
        setup, monkeypatch, capsys, loaders, stops):
    report, _, _ = required_start(setup, monkeypatch, capsys, loaders=loaders)
    shown = [line for line in report if line.startswith(se_start.STOP)]
    assert len(shown) == len(stops)
    for line, stop in zip(shown, stops):
        assert line.startswith(f"{se_start.STOP}: the required component {stop}")
    assert report.index(shown[-1]) < report.index(next(line for line in report if line.endswith(" started")))
    assert any(line.startswith(f"| {stops[-1].split()[0]} | none |") for line in table(report))


def test_with_kerns_binary_missing_the_start_stops_naming_kern_and_the_command_that_places_it(
        setup, monkeypatch, capsys):
    required_se(setup["se"])
    (setup["se"] / ".se" / ".runtime" / "kern.path").unlink()
    report, _, fakes = required_start(setup, monkeypatch, capsys)
    stop = [line for line in report if line.startswith(se_start.STOP)]
    assert stop == [f"{se_start.STOP}: the required component kern did not load: no binary is placed for "
                    f"{setup['se']}; the start's hook places and starts it: bash "
                    f"{setup['se'].as_posix()}/scripts/bootstrap.sh --hook"]
    assert "| kern | none | unknown |" in table(report) and fakes["asked"] == []


def test_a_kern_bootstrap_could_not_place_stops_the_start_with_its_cause(setup, monkeypatch, capsys):
    report, _, _ = required_start(setup, monkeypatch, capsys, "--kern-failed",
                                  "no se 1.1.0 release at https://example.com, and no go to build it")
    assert [line for line in report if line.startswith(se_start.STOP)] == [
        f"{se_start.STOP}: the required component kern did not load: no se 1.1.0 release at "
        "https://example.com, and no go to build it"]


def test_a_core_the_machine_switched_off_is_no_stop_and_the_session_is_told(setup, monkeypatch, capsys):
    report, session, fakes = required_start(setup, monkeypatch, capsys, "--kern-off",
                                            "SE_HOOK_CORE is off in the environment")
    assert "| kern | off | unknown |" in table(report)
    assert not any(line.startswith(se_start.STOP) for line in report) and fakes["asked"] == []
    assert "kern is not loaded: SE_HOOK_CORE is off in the environment" in session


def test_se_s_tree_that_cannot_be_placed_stops_the_start_naming_its_components(setup, monkeypatch, capsys):
    report, _, _ = required_start(setup, monkeypatch, capsys,
                                  placed=Placed("the required component obs is missing (se -> obs)."))
    assert [line for line in report if line.startswith(se_start.STOP)] == [
        f"{se_start.STOP}: SE's required components (kern, obs, obs-html) cannot be placed in {setup['se']}: "
        "the required component obs is missing (se -> obs)."]


def test_in_a_project_its_own_components_follow_and_one_ses_rows_show_is_not_listed_twice(
        setup, monkeypatch, capsys):
    """The project of `setup` locks lib and tool; it also locks obs at 10.1.0, which SE's row already
    shows as loaded: one row, and the session is told the project's lock differs."""
    project = setup["project"]
    write(project / "se.lock", (project / "se.lock").read_text(encoding="utf-8")
          + f'\n[components.obs]\nversion = "10.1.0"\nref = "{SHA}"\n')
    write(project / "se.toml", (project / "se.toml").read_text(encoding="utf-8").replace(
        f'[components.obs]\nref = "{SHA}"', '[components.obs]\nversion = "^10.1"'))
    report, session, _ = required_start(setup, monkeypatch, capsys, where=project)
    names = [line.split(" | ")[0][2:] for line in table(report)]
    assert names == ["SE", "kern", "obs", "obs-html", "lib", "tool", "mine"]
    assert "obs: the project locks 10.1.0; SE loaded 10.3.2 for itself" in session


def test_the_hook_shows_the_stop_above_the_report(setup, monkeypatch, capsys):
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    required_se(setup["se"])
    world = dataclasses.replace(setup["world"], run=Loaders(obs=None), kern=lambda binary, root: {"state": "running"})
    assert se_start.main(["--root", str(setup["se"].parent / "home"), "--local", str(setup["config"]),
                          "--cache", str(setup["cache"]), "status", "--hook", "--offline"], world=world) == 0
    shown = json.loads(capsys.readouterr().out)["systemMessage"].splitlines()
    assert shown[0].startswith(f"{se_start.STOP}: the required component obs did not load: ")
    assert shown[2] == "SE 1.2.0 started"


@pytest.mark.parametrize("host", ("copilot", "claude"))
def test_under_copilot_the_start_context_names_the_request_guards(setup, capsys, monkeypatch, host):
    """docs/copilot.md "What a session costs": the session reads which guards are on; Claude Code's
    greeting stays as it is."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    assert se_start.main(["--root", str(setup["project"]), "--local", str(setup["config"]), "--cache",
                          str(setup["cache"]), "status", "--hook", "--offline", "--host", host],
                         world=setup["world"]) == 0
    out = json.loads(capsys.readouterr().out)
    text = out["additionalContext"] if host == "copilot" else out["hookSpecificOutput"]["additionalContext"]
    guards = [line for line in text.splitlines() if line.startswith("Copilot guards: ")]
    if host == "claude":
        assert guards == []
    else:
        assert len(guards) == 1 and "refuse_stop = false: on" in guards[0]
        assert "start_sessions = true: off" in guards[0]


def test_without_word_of_kern_the_greeting_names_none(setup, capsys, monkeypatch):
    lines, asked = kern_greeting(setup, capsys, monkeypatch)
    assert not any(line.startswith("kern") for line in lines) and asked == []


def test_the_greeting_names_the_applications_own_binary_where_it_builds_one(setup, capsys, monkeypatch):
    # Where se.toml names a [binary] release, the line is the application's own binary, not the bare
    # kern: SE's is se (components/release.toml), kern's core plus SE's Go components.
    write(setup["se"] / "se.toml", '[project]\nversion = "5.0.0"\n[binary]\nrelease = "components/release.toml"\n')
    write(setup["se"] / "components" / "release.toml",
          'version = "0.1.0"\ndownload = "https://example.com/alice/SE/releases/download/se-v{version}"\n'
          'binary = "se"\npackage = "./cmd/se"\n')
    lines, asked = kern_greeting(setup, capsys, monkeypatch, "--kern-bin", "/k/se-0.1.0",
                                 answer={"state": "running", "health": {"pid": 7}})
    assert lines[1] == "se 0.1.0: running"


# What is due in the work: a retro, an overhaul and the fleet's findings, from the cache (work
# issue "start names what's due"; the overhaul countdown).

DUE = {"retro": {"count": 12, "landed": 12, "failed": 0, "due_after": 10, "due": True,
                 "reason": "12 came back since the last retro (due at 10)", "open": []},
       "overhaul": {"count": 3, "due_after": 3, "due": True,
                    "reason": "3 retros closed since the last overhaul (due at 3)", "open": []},
       "fleet": {"findings": [{"kind": "failed check", "issue": 7}, {"kind": "stray branch", "issue": 3},
                              {"kind": "stray branch", "issue": 5}]}}


def seed(s, work):
    """A fresh cache from an earlier check: every remote up to date, and `work`."""
    s["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}
    remotes = se_start.run_check({SE_URL, LIB_URL, TOOL_URL, OBS_URL}, s["remotes"])
    se_start.Cache(s["clock"].now, None, remotes, work).write(s["cache"])
    s["remotes"].calls.clear()


def work_lines(lines):
    return [line for line in lines if line.startswith(("Retro", "Overhaul", "Fleet"))]


RUN = ("; the next issue SE files (work_tickets.py file) files it first, and a retro agent runs it "
       "in its own session: ")
RETRO_LINE = ("Retro due: 12 came back since the last retro (due at 10)" + RUN
              + "uv run python {se}/scripts/retro.py collect <retro issue> --out <draft>")
OVERHAUL_LINE = ("Overhaul due: 3 retros closed since the last overhaul (due at 3)" + RUN
                 + "uv run python {se}/scripts/overhaul.py read <overhaul issue> --out <draft>")


def test_with_the_overhaul_countdown_off_the_greeting_is_unchanged(setup):
    """A cache from a work check with the countdown off holds no overhaul part, and the greeting
    is the one it was before the countdown: the retro and the fleet lines alone."""
    seed(setup, {key: value for key, value in DUE.items() if key != "overhaul"})
    se = setup["se"].as_posix()
    assert work_lines(said(report(setup), setup["se"])) == [
        RETRO_LINE.format(se=se),
        "Fleet: 3 findings (failed check #7; stray branch #3, #5); see each with its remedy: "
        f"uv run python {se}/scripts/work_tickets.py fleet-check --worktree {setup['project'].as_posix()}"]


def test_a_due_retro_overhaul_and_the_fleets_findings_appear_from_a_seeded_cache(setup):
    seed(setup, DUE)
    se = setup["se"].as_posix()
    expected = [
        RETRO_LINE.format(se=se),
        OVERHAUL_LINE.format(se=se),
        "Fleet: 3 findings (failed check #7; stray branch #3, #5); see each with its remedy: "
        f"uv run python {se}/scripts/work_tickets.py fleet-check --worktree {setup['project'].as_posix()}",
    ]
    rep = report(setup)
    assert se_start.session_lines(rep, setup["se"]) == expected
    assert work_lines(se_start.full(rep, setup["se"])) == expected
    assert setup["remotes"].calls == [] and setup["world"].work == [] and setup["world"].spawn == []


def test_the_parts_kern_holds_live_replace_the_cached_ones_and_say_so(setup):
    seed(setup, DUE)
    asked = []
    live = {"fleet": {"findings": [{"kind": "conflict", "issue": 9}], "issues": 14, "from": "kern"}}
    setup["world"] = dataclasses.replace(setup["world"], live=lambda root: asked.append(root) or live)
    se = setup["se"].as_posix()
    assert work_lines(said(report(setup), setup["se"])) == [
        RETRO_LINE.format(se=se),
        OVERHAUL_LINE.format(se=se),
        "Fleet: 1 finding (conflict #9), live from kern over 14 issues read; see each with its "
        f"remedy: uv run python {se}/scripts/work_tickets.py fleet-check --worktree "
        f"{setup['project'].as_posix()}"]
    assert asked == [setup["project"]]
    live["retro"] = {"count": 3, "due_after": 3, "due": True, "open": [],
                     "reason": "3 came back since the last retro (due at 3)", "issues": 14,
                     "from": "kern"}
    assert work_lines(said(report(setup), setup["se"]))[0].startswith(
        "Retro due: 3 came back since the last retro (due at 3), live from kern; ")
    live["overhaul"] = {"count": 4, "due_after": 3, "due": True, "open": [], "issues": 14,
                        "reason": "4 retros closed since the last overhaul (due at 3)",
                        "from": "kern"}
    assert work_lines(said(report(setup), setup["se"]))[1].startswith(
        "Overhaul due: 4 retros closed since the last overhaul (due at 3), live from kern; ")
    live["overhaul"] = {"count": 2, "due_after": 3, "due": False, "open": [], "reason": "",
                        "issues": 14, "from": "kern"}
    assert not any(line.startswith("Overhaul") for line in work_lines(
        said(report(setup), setup["se"])))
    # An open run is named while it is open, due or not: it holds back SE's filing.
    live["retro"] = {**live["retro"], "due": False, "open": [41]}
    assert work_lines(said(report(setup), setup["se"]))[0] == (
        "Retro open: #41, live from kern; SE files no new issue until the person has decided its "
        "findings in an SE session; a retro agent runs it in its own session: uv run python "
        f"{se}/scripts/retro.py collect <retro issue> --out <draft>")


def test_without_a_core_the_live_read_answers_none_and_the_cache_stands(setup, tmp_path):
    assert se_start.kern_names.live_work(tmp_path) is None
    write(tmp_path / ".se" / ".runtime" / "standing.json", '{"bus": "nats://127.0.0.1:9", "users": {"client": "x"}}')
    assert se_start.kern_names.live_work(tmp_path) is None  # a standing file whose bus is gone
    seed(setup, DUE)
    assert len(work_lines(said(report(setup), setup["se"]))) == 3


def test_the_live_read_keeps_only_the_parts_whose_names_hold_issues(monkeypatch):
    names = {"fleet/findings": {"issues": 0, "findings": []},
             "retro-due/due": {"issues": 4, "count": 6, "landed": 1, "failed": 1, "due_after": 10,
                               "due": False, "reason": "", "open": None}}
    monkeypatch.setattr(se_start.kern_names, "read", lambda root, wanted: names)
    assert se_start.kern_names.live_work(Path(".")) == {
        "retro": {"count": 6, "landed": 1, "failed": 1, "due_after": 10, "due": False,
                  "reason": "", "open": [], "issues": 4, "from": "kern"}}
    # The overhaul part comes from the same name, retro-due/due, where it counts the retros, and
    # only where its countdown is on: with overhaul_after and overhaul_days 0 the core names no
    # overhaul part.
    names["retro-due/due"].update(retros=2, overhaul_after=0, overhaul_days=0)
    assert "overhaul" not in se_start.kern_names.live_work(Path("."))
    names["retro-due/due"].update(retros=2, overhaul_after=0, overhaul_days=30, overhaul_due=True,
                                  overhaul_reason="r", overhaul_open=[7])
    assert se_start.kern_names.live_work(Path("."))["overhaul"] == {
        "count": 2, "due_after": 0, "due": True, "reason": "r", "open": [7], "issues": 4,
        "from": "kern"}
    # A partial view of the fleet is no verdict: the cached check stands; a complete one replaces it.
    names["fleet/findings"] = {"issues": 1, "complete": False, "findings": []}
    assert "fleet" not in se_start.kern_names.live_work(Path("."))
    names["fleet/findings"] = {"issues": 9, "complete": True, "findings": []}
    assert se_start.kern_names.live_work(Path("."))["fleet"] == {"findings": [], "issues": 9,
                                                                  "from": "kern"}
    names["fleet/findings"] = {"issues": 0, "findings": []}
    names["retro-due/due"]["issues"] = 0
    assert se_start.kern_names.live_work(Path(".")) is None


@pytest.mark.parametrize("work", [None, {"retro": {"count": 9, "due_after": 10, "due": False, "open": []},
                                         "fleet": {"findings": []}}])
def test_the_lines_are_absent_without_gh_without_a_cache_or_with_nothing_due(setup, work):
    assert work_lines(said(report(setup), setup["se"])) == []  # no cache yet
    seed(setup, work)
    lines = said(report(setup), setup["se"])
    assert work_lines(lines) == [] and lines == se_start.greeting(report(setup), setup["se"])


def test_a_failed_read_names_its_part_and_the_remedy(setup):
    seed(setup, {"retro": {"error": "gh api failed: HTTP 502"}, "fleet": {"findings": []}})
    assert work_lines(said(report(setup), setup["se"])) == [
        "Retro check not done: gh api failed: HTTP 502; run it by hand to see the cause: "
        f"uv run python {setup['se'].as_posix()}/scripts/se_start.py check"]


def test_status_reads_the_seeded_cache_within_its_budget(setup):
    seed(setup, DUE)
    started = time.perf_counter()
    lines = said(report(setup), setup["se"])
    assert time.perf_counter() - started < se_start.feedback.budget("se_start.py status")
    assert len(work_lines(lines)) == 3 and setup["world"].work == []


def test_check_caches_the_work_and_refreshs_checks_keep_it(setup):
    setup["world"].work.found = DUE
    setup["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}  # nothing moves
    report(setup, "check")
    assert setup["world"].work == [setup["project"]]
    assert se_start.Cache.read(setup["cache"]).work == DUE
    se_start.refresh(setup["se"], setup["project"], setup["config"], setup["cache"], setup["world"])
    assert setup["world"].work == [setup["project"]]  # refresh reads no work
    assert se_start.Cache.read(setup["cache"]).work == DUE


def test_without_gh_the_work_check_reads_nothing(tmp_path, monkeypatch):
    work_tickets = se_start._load("work_tickets")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "Fleet", lambda *a: pytest.fail("no read without gh"))
    assert se_start.work_check(project) is None
    assert se_start.work_check(None) is None


def test_with_gh_each_part_keeps_its_answer_when_the_other_fails(tmp_path, monkeypatch):
    work_tickets, retro = se_start._load("work_tickets"), se_start._load("retro")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "resolve_repo", lambda root, repo: "github.com/owner/repo")
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/owner/repo")
    monkeypatch.setattr(work_tickets, "repository_name", lambda root: "repo")
    monkeypatch.setattr(work_tickets, "Fleet", lambda root, repo, base: (root, repo, base))
    monkeypatch.setattr(work_tickets, "fleet_findings", lambda door, now, lease, name: [
        work_tickets.Finding("stray branch", 3, "closed", "delete it", branch="feat/x"),
        work_tickets.Finding("starting", 4, "started 5 minutes ago", "none")])  # healthy: not named

    def no_door(*args):
        raise work_tickets.QueueError("gh api issues failed: HTTP 502")

    monkeypatch.setattr(retro, "GhDoor", no_door)
    # The overhaul countdown is on by default: a failed read names both countdowns.
    assert se_start.work_check(project) == {"retro": {"error": "gh api issues failed: HTTP 502"},
                                            "overhaul": {"error": "gh api issues failed: HTTP 502"},
                                            "fleet": {"findings": [{"kind": "stray branch", "issue": 3}]}}
    (project / "se.toml").write_text("[overhaul]\ndue_after = 0\ndays = 0\n", encoding="utf-8")
    assert "overhaul" not in se_start.work_check(project)  # off: read not, named not
    (project / "se.toml").unlink()
    monkeypatch.setattr(retro, "GhDoor", lambda *args: "door")

    def counted(door, repo, branch, root, now):
        return {"retro": retro.Countdown("retro", None, None, 11, 1, 16, 20, 7, 3, False, "", [41]),
                "overhaul": retro.Countdown("overhaul", None, None, 2, 0, 2, 3, 30, 3, False, "")}

    monkeypatch.setattr(retro, "countdowns", counted)
    work = se_start.work_check(project)
    assert work["retro"] == {"count": 16, "landed": 11, "failed": 1, "due_after": 20, "due": False,
                             "reason": "", "open": [41]}
    assert work["overhaul"] == {"count": 2, "due_after": 3, "due": False, "reason": "", "open": []}


# The project's components: its listing command, run by the check, reported by the greeting.


LISTING = """component  kind     installed      newest  repository
html       adapter  1.0.0          1.1.0   https://git.example.org/team/obs-html.git  (update)
dark       style    not installed  2.0.0   https://git.example.org/team/obs-dark.git
plain      style    1.0.0          1.0.0   https://git.example.org/team/obs-plain.git
gone       style    0.3.0          -       -
"""


class Listing(list):
    """The fake component listing: records each project and command it runs, answers `answer`."""

    def __init__(self, answer: dict):
        super().__init__()
        self.answer = answer

    def __call__(self, root, command):
        self.append((root, command))
        return self.answer


def with_components(s, command=("uv", "run", "obs-components")):
    manifest = s["project"] / "se.toml"
    command_text = ", ".join(f'"{part}"' for part in command)
    manifest.write_text(f"[project]\ncomponents = [{command_text}]\n" + manifest.read_text(encoding="utf-8"),
                        encoding="utf-8")


def component_lines(lines):
    return [line for line in lines if line.startswith("Component")]


def test_the_greeting_names_each_new_component_and_each_update_with_the_command_that_takes_it(setup):
    with_components(setup)
    listing = Listing({"offers": se_start.parse_listing(LISTING)})
    setup["world"] = dataclasses.replace(setup["world"], components=listing)
    report(setup, "check")
    assert listing == [(setup["project"], ["uv", "run", "obs-components"])]
    lines = said(report(setup), setup["se"])
    assert component_lines(lines) == [
        "Component html (adapter): 1.0.0 -> 1.1.0; update it: uv run obs-components update html",
        "Component dark (style): not installed, newest 2.0.0; install it: uv run obs-components install dark"]
    assert component_lines(se_start.full(report(setup), setup["se"])) == component_lines(lines)
    assert len(listing) == 1  # status answers from the cache and runs nothing


def test_a_project_without_the_setting_prints_nothing_new_and_runs_no_listing(setup):
    listing = Listing({"error": "never run"})
    setup["world"] = dataclasses.replace(setup["world"], components=listing)
    report(setup, "check")
    before = said(report(setup), setup["se"])
    assert listing == [] and component_lines(before) == []
    assert se_start.Cache.read(setup["cache"]).components is None


def test_a_listing_not_yet_run_for_the_projects_command_starts_the_check(setup):
    seed(setup, None)
    assert said(report(setup), setup["se"]) and setup["world"].spawn == []
    with_components(setup)
    lines = said(report(setup), setup["se"])
    assert len(setup["world"].spawn) == 1 and setup["world"].spawn[0][-1] == "check"
    assert component_lines(lines) == [
        "Component check not done: running in the background; the next start shows its result"]


def test_a_failed_listing_is_one_warning_line_and_the_greeting_still_appears(setup):
    with_components(setup)
    setup["world"] = dataclasses.replace(setup["world"], components=Listing({"error": "obs-components failed"}))
    report(setup, "check")
    lines = said(report(setup), setup["se"])
    assert lines[0].startswith("SE 1.2.0 started")
    assert component_lines(lines) == [
        "Component check not done: obs-components failed; run it by hand to see the cause: "
        f"uv run python {setup['se'].as_posix()}/scripts/se_start.py check"]


def test_a_setting_that_is_no_argument_array_is_one_warning_line(setup):
    manifest = setup["project"] / "se.toml"
    manifest.write_text('[project]\ncomponents = "uv run obs-components"\n' + manifest.read_text(encoding="utf-8"),
                        encoding="utf-8")
    report(setup, "check")
    assert component_lines(said(report(setup), setup["se"])) == [
        f"Component check not done: [project] components of {manifest.as_posix()} is no argument "
        'array; set it as components = ["uv", "run", "obs-components"]']


# The listing is the project's own command (obs-components), answered by the process door's fake.
LISTING_COMMAND = ["obs-components"]


def test_the_listing_runs_in_the_checkout_and_its_table_is_read(tmp_path, fake_processes):
    project = tmp_path / "project"
    project.mkdir()

    def listing(call):
        assert call.options["stdin"] == se_start.subprocess.DEVNULL, "read-only: it is asked nothing"
        return fake_programs.Answer(0, LISTING if call.cwd == project else "elsewhere\n",
                                    "obs-components: warning: a host cannot be listed\n")

    fake_processes.on("obs-components", listing)
    found = se_start.list_components(project, LISTING_COMMAND)
    assert [offer["name"] for offer in found["offers"]] == ["html", "dark", "plain", "gone"]
    assert found["offers"][1] == {"name": "dark", "kind": "style", "installed": "not installed",
                                  "newest": "2.0.0"}


def taking(seconds: float, answer: fake_programs.Answer):
    """A listing that answers `answer` after `seconds`: past the call's timeout, the door raises."""
    def listing(call):
        if call.options.get("timeout") is not None and call.options["timeout"] < seconds:
            raise se_start.subprocess.TimeoutExpired(call.argv, call.options["timeout"])
        return answer
    return listing


@pytest.mark.parametrize(("answer", "error"), [
    (fake_programs.Answer(1, "", "obs-components: no remote\n"),
     " failed with exit code 1: obs-components: no remote"),
    (fake_programs.Answer(0, "nothing here\n"),
     ": its output holds no table headed component  kind  installed  newest  repository"),
    (None, " took longer than 0.5 s"),
], ids=["fails", "no-table", "too-long"])
def test_a_listing_that_fails_or_takes_too_long_answers_its_error(tmp_path, monkeypatch, fake_processes,
                                                                  answer, error):
    monkeypatch.setattr(se_start, "COMPONENTS_TIMEOUT", 0.5)
    fake_processes.on("obs-components", taking(5, fake_programs.Answer(0, LISTING)) if answer is None
                      else taking(0, answer))
    found = se_start.list_components(tmp_path, LISTING_COMMAND)
    assert found == {"error": " ".join(LISTING_COMMAND) + error}


def test_a_listing_that_does_not_start_answers_its_error(tmp_path, fake_processes):
    missing = tmp_path / "no-such-command"

    def not_found(call):
        raise FileNotFoundError(2, "No such file or directory", str(missing))

    fake_processes.on("no-such-command", not_found)
    found = se_start.list_components(tmp_path, [str(missing)])
    assert found["error"].startswith(f"{missing} did not start: ")


# Requirement 3: refresh moves only what is due, on the fake git's repositories.


@pytest.fixture
def isolated_git(tmp_path, monkeypatch):
    gitconfig = write(tmp_path / "gitconfig", "[init]\n\tdefaultBranch = main\n")
    for key, value in {
        "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }.items():
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str) -> str:
    return se_modules.git(repo, *args)


def release(repo: Path, version: str, files: dict[str, str] | None = None, *, says: str | None = None) -> None:
    write(repo / "se.toml", f'[project]\nversion = "{says or version}"\n' + (
        repo.joinpath("se.toml.extra").read_text(encoding="utf-8") if (repo / "se.toml.extra").exists() else ""))
    for name, text in (files or {}).items():
        write(repo / name, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"release {version}")
    git(repo, "tag", f"v{version}")


def trial_start(call) -> fake_programs.Answer:
    """SE's start in a refresh's trial (se_start.py `_starts`): the trial's own se_start.py, loaded
    from its worktree and its `main` run in-process as the child would run it; its sibling scripts
    are SE's, which the trial holds as copies."""
    name = f"trial_se_start_{abs(hash(call.script.as_posix()))}"

    def main(argv: list[str]) -> object:
        spec = importlib.util.spec_from_file_location(name, call.script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            return module.main(argv)
        finally:
            sys.modules.pop(name, None)

    return fake_programs.run_main(main, call)


@pytest.fixture
def repos(tmp_path, isolated_git, fake_processes):
    """An se remote with v1.0.0, v1.1.0 and v2.0.0, a clone of it at v1.0.0; module remotes lib
    (v1.0.0, v1.1.0, v2.0.0) and tool (v1.0.0 only); a project locked at lib 1.0.0 and tool 1.0.0.
    A refresh's trial start runs in-process (`trial_start`)."""
    fake_processes.on("se_start.py", trial_start)
    scripts = {f"scripts/{name}": (ROOT / "scripts" / name).read_text(encoding="utf-8")
               for name in ("se_start.py", "git_door.py", "process_door.py", "se_modules.py", "se_home.py",
                             "public_check.py", "metrics.py", "feedback.py", "kern_names.py", "se_plugin.py",
                             "agent_lint.py", "generated.py", "interfaces.py", "public-check-terms.toml")}
    scripts.update({f"scripts/interfaces/{path.name}": path.read_text(encoding="utf-8")
                    for path in (ROOT / "scripts" / "interfaces").glob("*.json")})
    upstream = tmp_path / "se-remote"
    upstream.mkdir()
    fake_git.init(upstream, "-b", "main")
    write(upstream / "se.toml.extra", 'docs_url = "https://docs.example.com/se/"\n')
    for version in ("1.0.0", "1.1.0", "2.0.0"):
        release(upstream, version, scripts)
    se = tmp_path / "se"
    fake_git.clone(upstream.as_uri(), se)
    git(se, "reset", "-q", "--hard", "v1.0.0")
    remotes = {}
    for name, versions in {"lib": ("1.0.0", "1.1.0", "2.0.0"), "tool": ("1.0.0",)}.items():
        remote = tmp_path / "hosts" / name  # beside the project's origin, as its [urls] rewrites it
        remote.mkdir(parents=True)
        fake_git.init(remote, "-b", "main")
        for version in versions:
            release(remote, version)
        remotes[name] = remote
    project = fake_git.init(tmp_path / "project")
    git(project, "remote", "add", "origin", "https://git.example.org/team/project")
    local_dir = tmp_path / "local-lib"
    write(local_dir / "se.toml", '[project]\nversion = "0.1.0"\n')
    write(project / "se.toml", "".join(f'[components.{name}]\nversion = "^1"\n\n' for name in remotes)
          + '[components.mine]\nversion = "^0.1"\n')
    config = write(tmp_path / "local.toml", f'[urls]\n"https://git.example.org/team/" = '
                                            f'"{(tmp_path / "hosts").as_posix()}/"\n\n[paths]\nmine = "{local_dir.as_posix()}"\n')
    se_modules.write_lock(project, {name: ("1.0.0", git(remote, "rev-parse", "v1.0.0"))
                                    for name, remote in remotes.items()})
    assert se_modules.main(["--root", str(project), "--local", str(config), "sync"]) == 0
    clock = Clock()
    world = se_start.World(clock=clock, spawn=Spawns(), work=Work())
    return dict(se=se, project=project, config=config, cache=tmp_path / "cache.json", world=world,
                remotes=remotes, upstream=upstream)


def refresh(r):
    return se_start.refresh(r["se"], r["project"], r["config"], r["cache"], r["world"])


# The refresh at the session's start (start_refresh): SE alone, in place, failing open.


def test_start_refresh_moves_se_to_the_latest_release_of_its_major(repos):
    line, moved = se_start.start_refresh(repos["se"], repos["project"], repos["config"])
    assert moved and line == f"SE: 1.0.0 -> 1.1.0, refreshed at this start ({repos['se'].as_posix()})"
    assert se_modules.checkout_version(repos["se"]) == (1, 1, 0)
    assert se_modules.read_lock(repos["project"])["lib"][0] == "1.0.0", "the modules wait for refresh"
    assert se_start.start_refresh(repos["se"], repos["project"], repos["config"]) == ("", False)
    # Moved to the tag, the clone is ahead of its stale origin/main, and still moves at a later start.
    release(repos["upstream"], "1.2.0", says="1.2.0")
    line, moved = se_start.start_refresh(repos["se"], repos["project"], repos["config"])
    assert moved and line.startswith("SE: 1.1.0 -> 1.2.0, refreshed at this start"), line


def test_start_refresh_fails_open_with_one_line(repos):
    def offline(url):
        raise se_start.RemoteError(f"cannot reach {url}: offline")

    line, moved = se_start.start_refresh(repos["se"], repos["project"], repos["config"], offline)
    assert not moved and line.startswith("SE: no refresh at start, this session starts with SE 1.0.0: "
                                         "cannot reach ")
    assert "\n" not in line and se_modules.checkout_version(repos["se"]) == (1, 0, 0)
    git(repos["upstream"], "tag", "v1.2.0")  # a tag whose se.toml names another version: no start
    line, moved = se_start.start_refresh(repos["se"], repos["project"], repos["config"])
    assert not moved and line.startswith("SE: no refresh at start to 1.2.0, this session starts with SE 1.0.0: ")
    assert se_modules.checkout_version(repos["se"]) == (1, 0, 0)


def test_start_refresh_leaves_a_development_checkout_and_the_sessions_own_tree(repos):
    assert se_start.start_refresh(repos["se"], repos["se"], repos["config"]) == ("", False)
    write(repos["se"] / "notes.md", "mine\n")
    git(repos["se"], "add", "notes.md")
    assert se_start.start_refresh(repos["se"], repos["project"], repos["config"]) == ("", False)  # changes
    git(repos["se"], "commit", "-q", "-m", "mine")
    assert se_start.start_refresh(repos["se"], repos["project"], repos["config"]) == ("", False)  # own commit
    git(repos["se"], "reset", "-q", "--hard", "v1.0.0")
    git(repos["se"], "checkout", "-q", "-b", "feature")
    assert se_start.start_refresh(repos["se"], repos["project"], repos["config"]) == ("", False)  # its branch
    assert se_modules.checkout_version(repos["se"]) == (1, 0, 0)


def test_refresh_moves_only_what_is_due_and_twice_is_a_no_op(repos):
    lock_before = se_modules.read_lock(repos["project"])
    assert lock_before["lib"][0] == "1.0.0" and lock_before["tool"][0] == "1.0.0"
    lines, failed = refresh(repos)
    assert not failed, lines
    assert any(line.startswith("SE: ") and line.endswith(" -> v1.1.0") for line in lines)
    assert "lib: 1.0.0 -> 1.1.0 (se.lock; commit it)" in lines
    assert (f"lib: 2.0.0 is outside ^1; not applied; to take it, set version = \"^2.0\" in [components.lib] of "
            f"{(repos['project'] / 'se.toml').as_posix()}, then run: uv run python {repos['se'].as_posix()}"
            "/scripts/se_modules.py update lib") in lines
    assert ("SE: 2.0.0 is outside SE's major 1; not applied; to take it, install SE 2.0.0 again as README "
            "\"Install\" says, then follow SE's docs/upgrading.md, section \"SE 2\"") in lines
    assert "mine: local, not touched" in lines
    assert not any(line.startswith("tool:") for line in lines)
    lock = se_modules.read_lock(repos["project"])
    assert lock["lib"] == ("1.1.0", git(repos["remotes"]["lib"], "rev-parse", "v1.1.0"))
    assert lock["tool"] == lock_before["tool"]
    clone = repos["project"] / ".se" / "modules" / "lib"
    assert git(clone, "rev-parse", "HEAD") == lock["lib"][1]
    assert se_modules.checkout_version(repos["se"]) == (1, 1, 0)
    assert git(repos["se"], "rev-parse", "--abbrev-ref", "HEAD") == "main"  # fast-forwarded, still on main
    assert git(repos["se"], "worktree", "list").count("\n") == 0  # the trial worktrees are gone
    again, failed = refresh(repos)
    assert not failed and again[0] == "Everything is up to date; nothing moved."
    assert not any("->" in line for line in again)
    cache = json.loads(repos["cache"].read_text(encoding="utf-8"))
    assert cache["checked_at"] is not None  # the greeting after a refresh shows the new state


def test_a_due_version_that_fails_its_trial_leaves_the_old_one_in_use(repos):
    release(repos["remotes"]["lib"], "1.2.0", says="1.0.0")  # its se.toml names another version
    before = se_modules.read_lock(repos["project"])["lib"]
    lines, failed = refresh(repos)
    assert failed
    assert any(line.startswith("lib: not refreshed, 1.0.0 stays in use: module lib v1.2.0: v1.2.0 sets "
                               "version 1.0.0") for line in lines)
    assert lines[-1] == f"Try again with: uv run python {repos['se'].as_posix()}/scripts/se_start.py refresh"
    assert se_modules.read_lock(repos["project"])["lib"] == before
    clone = repos["project"] / ".se" / "modules" / "lib"
    assert git(clone, "rev-parse", "HEAD") == before[1]
    assert any(line.startswith("SE: ") and line.endswith(" -> v1.1.0") for line in lines)  # the rest moves


def test_an_se_version_that_does_not_start_is_not_switched_to(repos):
    release(repos["upstream"], "1.2.0", {"scripts/se_start.py": "raise SystemExit('broken start')\n"})
    head = git(repos["se"], "rev-parse", "HEAD")
    lines, failed = refresh(repos)
    assert failed
    assert any(line.startswith("SE: not refreshed, 1.0.0 stays in use: SE v1.2.0 does not start: broken start")
               for line in lines)
    assert git(repos["se"], "rev-parse", "HEAD") == head


def test_a_development_checkout_of_se_is_left_alone(repos):
    write(repos["se"] / "notes.txt", "work in progress\n")
    git(repos["se"], "add", "notes.txt")
    lines, failed = refresh(repos)
    assert failed
    assert any(line.startswith("SE: not refreshed, 1.0.0 stays in use: the se checkout ") and "local changes" in line
               for line in lines)


# Refresh by the way SE is installed: a Claude Code plugin, a cloud setup-script clone, a Copilot
# copy, a local path.


def installed(repos, tag: str, where: Path) -> Path:
    """A copy of the se remote at `tag` without git, as an installer leaves it."""
    where.parent.mkdir(parents=True, exist_ok=True)
    fake_git.clone(repos["upstream"].as_uri(), where, "--branch", tag)
    shutil.rmtree(where / ".git")
    write(where / ".claude-plugin" / "plugin.json", json.dumps({"name": "se", "repository": repos["upstream"].as_uri()}))
    return where


class FakeClaude:
    """Claude Code's command line on a fake record: `plugin list --json` reads it; `plugin update`
    installs the se remote at `serves` as a new versioned copy and rewrites the record."""

    def __init__(self, repos, record: Path, entries: list[dict], serves: str | None = None):
        self.repos, self.record, self.serves, self.calls = repos, record, serves, []
        write(record, json.dumps(entries))

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["plugin", "list"]:
            return se_start.subprocess.CompletedProcess(args, 0, self.record.read_text(encoding="utf-8"), "")
        if args[:2] == ["plugin", "update"]:
            entries = json.loads(self.record.read_text(encoding="utf-8"))
            entry = next(e for e in entries if e["id"] == args[2])
            path = installed(self.repos, self.serves, Path(entry["installPath"]).parent / self.serves[1:])
            entry.update(installPath=str(path), version=self.serves[1:])
            self.record.write_text(json.dumps(entries), encoding="utf-8")
            return se_start.subprocess.CompletedProcess(args, 0, '{"ok": true}', "")
        return se_start.subprocess.CompletedProcess(args, 1, "", "unknown command")


def as_plugin(repos, tmp_path, monkeypatch, serves: str) -> FakeClaude:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    cache = tmp_path / "claude" / "plugins" / "cache" / "se" / "se"
    repos["se"] = installed(repos, "v1.0.0", cache / "1.0.0")
    fake = FakeClaude(repos, se_start.plugin_registry(), [
        {"id": "se@se", "version": "1.0.0", "scope": "user", "enabled": True, "installPath": str(repos["se"])}],
        serves)
    repos["world"] = se_start.World(clock=repos["world"].clock, spawn=Spawns(), claude=fake, work=Work())
    return fake


def test_an_installed_plugin_is_updated_through_claude_code(repos, tmp_path, monkeypatch):
    fake = as_plugin(repos, tmp_path, monkeypatch, "v1.1.0")
    lines, failed = refresh(repos)
    assert not failed, lines
    assert "SE: 1.0.0 -> 1.1.0 (claude plugin update se@se; restart Claude Code to load it)" in lines
    assert ["plugin", "update", "se@se", "--scope", "user", "--json"] in fake.calls
    entry = json.loads(fake.record.read_text(encoding="utf-8"))[0]
    assert entry["version"] == "1.1.0" and se_modules.checkout_version(Path(entry["installPath"])) == (1, 1, 0)


def test_an_updated_plugin_that_does_not_start_leaves_the_old_install_in_use(repos, tmp_path, monkeypatch):
    release(repos["upstream"], "1.2.0", {"scripts/se_start.py": "raise SystemExit('broken start')\n"})
    fake = as_plugin(repos, tmp_path, monkeypatch, "v1.2.0")
    record = fake.record.read_bytes()
    lines, failed = refresh(repos)
    assert failed
    line = next(line for line in lines if line.startswith("SE: not refreshed, 1.0.0 stays in use: "))
    assert "SE v1.2.0 does not start: broken start" in line and "is back in" in line
    assert fake.record.read_bytes() == record


def test_a_cloud_setup_script_clone_is_pulled_like_a_checkout(repos, tmp_path):
    git(repos["upstream"], "branch", "release", "v1.0.0")
    git(repos["upstream"], "symbolic-ref", "HEAD", "refs/heads/release")  # the clone takes the default
    clone = tmp_path / "home" / ".claude" / "skills" / "se"
    fake_git.clone(repos["upstream"].as_uri(), clone, "--depth", "1")
    repos["se"] = clone
    lines, failed = refresh(repos)
    assert not failed, lines
    assert any(line.startswith("SE: ") and line.endswith(" -> v1.1.0") for line in lines)
    assert se_modules.checkout_version(clone) == (1, 1, 0)
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "release"


def test_a_copilot_copy_names_the_one_command_and_why(repos, tmp_path, monkeypatch):
    fake = as_plugin(repos, tmp_path, monkeypatch, "v1.1.0")
    fake.record.write_text("[]", encoding="utf-8")  # Claude Code has no plugin here
    repos["se"] = installed(repos, "v1.0.0", tmp_path / "copilot" / "se")
    lines, failed = refresh(repos)
    assert not failed, lines
    line = next(line for line in lines if line.startswith("SE: 1.0.0 -> 1.1.0 is due, but "))
    assert "only VS Code can update" in line and "Chat: Install Plugin from Source" in line
    assert se_modules.checkout_version(repos["se"]) == (1, 0, 0)
    assert not any(args[:2] == ["plugin", "update"] for args in fake.calls)


def test_se_at_a_local_path_is_never_touched(repos):
    write(repos["config"], repos["config"].read_text(encoding="utf-8") + f'se = "{repos["se"].as_posix()}"\n')
    head = git(repos["se"], "rev-parse", "HEAD")
    lines, failed = refresh(repos)
    assert not failed, lines
    assert "SE: local, not touched" in lines
    assert not any(line.startswith("SE: ") and "->" in line for line in lines)
    assert git(repos["se"], "rev-parse", "HEAD") == head


def test_without_gh_the_se_agent_runs_the_fleet_checks_plan_at_its_first_turn():
    text = (ROOT / "src" / "agents" / "se.md").read_text(encoding="utf-8")
    greeting = text[text.index("- **Start report**"):text.index("- **Turn-start check**")]
    assert ("Without gh (neither signed in nor answered over REST) it names no retro or fleet: the "
            "turn-start check below prints the fleet check's plan") in " ".join(greeting.split())
    assert "pass the lists back to `work_tickets.py fleet-check` as it says" in " ".join(greeting.split())


def test_the_se_agent_updates_after_its_report_at_once_in_the_cloud_and_on_a_yes_locally():
    text = (ROOT / "src" / "agents" / "se.md").read_text(encoding="utf-8")
    report, update = text.index("- **Start report**"), text.index("- **Update**")
    step = " ".join(text[update:text.index("- **Under Copilot**")].split())
    assert report < update, "the update comes after the report, never before it"
    assert "opens with SE's start report, as it is, and adds nothing to it" in " ".join(text[report:update].split())
    assert "the skill [update](../skills/update/SKILL.md)" in step
    assert ("In a cloud session (`CLAUDE_CODE_REMOTE` is `true`) follow the update skill as your first action, "
            "before any other work, right after the report") in step
    assert "On a local machine the report's line offers it: follow the update skill on the person's yes" in step
    assert "report once" in step
    skill = (ROOT / "src" / "skills" / "update" / "SKILL.md").read_text(encoding="utf-8")
    assert "`uv run python <se>/scripts/se_start.py --root <main checkout> update`" in skill
    assert "**Follow the sections** it printed, in order: every step, then its check" in skill


# The outside skills SE's agents rely on (se.toml [roles]): the greeting names one the session lacks.

PLUGIN_DEV = "plugin-dev@claude-plugins-official:plugin-structure"


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    """An empty Claude Code configuration folder on a local machine."""
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv(se_start.CLOUD_ENV, raising=False)
    return home


def with_roles(s, roles: str):
    (s["se"] / "se.toml").write_text((s["se"] / "se.toml").read_text(encoding="utf-8") + roles,
                                     encoding="utf-8")


def skill_line(s) -> list[str]:
    return [line for line in said(report(s), s["se"]) if "SE's agents" in line
            or line.startswith("Skills check")]


def test_a_listed_skill_the_session_lacks_is_named_in_one_line_with_its_install(setup, claude_home):
    with_roles(setup, f'[roles.worker]\nskills = ["{PLUGIN_DEV}"]\n[roles.reviewer]\nskills = ["{PLUGIN_DEV}",'
                      ' "example-skills@anthropic-agent-skills:skill-creator"]\n')
    assert skill_line(setup) == [
        "Missing for SE's agents: plugin-dev:plugin-structure (worker, reviewer); "
        "example-skills:skill-creator (reviewer). Install: claude plugin install "
        "plugin-dev@claude-plugins-official && claude plugin install example-skills@anthropic-agent-skills"]


def test_an_installed_or_skills_folder_plugin_is_not_named(setup, claude_home):
    with_roles(setup, f'[roles.worker]\nskills = ["{PLUGIN_DEV}", "tools@team:lint"]\n')
    write(claude_home / "plugins" / "installed_plugins.json",
          json.dumps({"version": 2, "plugins": {"plugin-dev@claude-plugins-official": [{}]}}))
    write(claude_home / "skills" / "tools" / ".claude-plugin" / "plugin.json", "{}")
    assert skill_line(setup) == []


def test_a_plugin_from_another_marketplace_does_not_count(setup, claude_home):
    with_roles(setup, f'[roles.worker]\nskills = ["{PLUGIN_DEV}"]\n')
    write(claude_home / "plugins" / "installed_plugins.json",
          json.dumps({"version": 2, "plugins": {"plugin-dev@elsewhere": [{}]}}))
    assert len(skill_line(setup)) == 1


def test_in_the_cloud_the_line_says_the_environment_provides_plugins(setup, claude_home, monkeypatch):
    monkeypatch.setenv(se_start.CLOUD_ENV, "true")
    with_roles(setup, f'[roles.worker]\nskills = ["{PLUGIN_DEV}"]\n')
    assert skill_line(setup) == [
        "Missing for SE's agents: plugin-dev:plugin-structure (worker). This cloud session lacks them; "
        "the cloud environment provides plugins (README \"Claude Code cloud\")"]


def test_a_bad_roles_list_is_named_and_the_greeting_still_appears(setup, claude_home):
    with_roles(setup, '[roles.worker]\nskills = ["plugin-dev"]\n')
    lines = said(report(setup), setup["se"])
    assert lines[0].startswith("SE 1.2.0 started")
    assert skill_line(setup) == [f"Skills check not done: {setup['se'] / 'se.toml'}: [roles.worker] skills "
                                 "entry 'plugin-dev' is not `<plugin>@<marketplace>:<skill>`"]


def test_the_round_trip_list_then_build_then_the_greeting_names_the_missing_item(tmp_path, claude_home):
    se = tmp_path / "se"
    shutil.copytree(ROOT / "src", se / "src")
    manifest = (ROOT / "se.toml").read_text(encoding="utf-8").split("\n[roles.", 1)[0]
    write(se / "se.toml", manifest + f'\n[roles.worker]\nskills = ["{PLUGIN_DEV}"]\n')
    se_start.se_plugin.build(se)
    worker = (se / "agents" / "worker.md").read_text(encoding="utf-8")
    assert "\nskills: plugin-dev:plugin-structure\n" in worker.split("\n---\n", 1)[0] + "\n"
    rep = se_start.status(se, None, tmp_path / "local.toml", tmp_path / "cache.json",
                          se_start.World(clock=Clock(), spawn=Spawns(), work=Work()), offline=True)
    assert ("Missing for SE's agents: plugin-dev:plugin-structure (worker). Install: claude plugin "
            "install plugin-dev@claude-plugins-official") in said(rep, se)


# The hooks at start (bootstrap.sh --hook): a checkout whose core.hooksPath is unset gets se's hooks.

def hooks_path(repo: Path) -> str | None:
    found = se_start.git_door.run("config", "--get", "core.hooksPath", root=repo)
    return found.stdout.strip() if found.returncode == 0 else None


def fresh_clone(base: Path, name: str = "clone") -> Path:
    """A fresh clone of a project with an se.toml, as a cloud session's container clones it: no
    core.hooksPath, which git never copies."""
    origin = base / "origin"
    if not origin.exists():
        fake_git.init(origin, "-b", "main")
        write(origin / "se.toml", '[project]\nversion = "0.1.0"\n')
        git(origin, "add", "-A")
        git(origin, "-c", "user.name=alice", "-c", "user.email=alice@example.com", "commit", "-q", "-m", "one")
    clone = fake_git.clone(origin.as_uri(), base / name)
    assert hooks_path(clone) is None
    return clone


@pytest.fixture
def fresh(tmp_path):
    return fresh_clone(tmp_path), tmp_path


def test_start_hooks_points_a_fresh_clone_of_se_at_its_own_hooks_once(fresh):
    clone, base = fresh
    write(clone / ".githooks" / "se-script", "#!/bin/sh\n")  # se's own checkout carries its hooks
    assert se_start.start_hooks(base / "plugin", clone, base / "local.toml") == ""
    assert hooks_path(clone) == ".githooks"  # as setup.sh sets it in se's own checkout
    assert se_start.start_hooks(base / "plugin", clone, base / "local.toml") == ""  # again: no change
    assert hooks_path(clone) == ".githooks"


def test_start_hooks_leaves_a_set_hooks_path_alone(fresh):
    clone, base = fresh
    git(clone, "config", "core.hooksPath", "custom/hooks")
    assert se_start.start_hooks(base / "plugin", clone, base / "local.toml") == ""
    assert hooks_path(clone) == "custom/hooks"


def own_hooks_folder(clone: Path) -> Path:
    found = se_start.git_door.run("rev-parse", "--git-path", "hooks", root=clone).stdout.strip()
    return Path(found) if Path(found).is_absolute() else clone / found


def test_start_hooks_names_the_checkouts_own_hooks_that_stop_running_and_the_command_that_keeps_them(fresh):
    clone, base = fresh
    folder = own_hooks_folder(clone)
    write(folder / "pre-commit", "#!/bin/sh\n").chmod(0o755)  # a hook set such as the pre-commit framework's
    write(folder / "pre-push.sample", "#!/bin/sh\n")
    line = se_start.start_hooks(base / "plugin", clone, base / "local.toml")
    assert hooks_path(clone) == (base / "plugin" / ".githooks").as_posix()  # set exactly as before
    assert line == (f"SE: the hooks in {folder.as_posix()} no longer run: pre-commit, as core.hooksPath now names "
                    f"se's; to keep them, run: git -C {clone.as_posix()} config core.hooksPath {folder.as_posix()} "
                    "(se's public check then does not run on this checkout's commits)")
    assert se_start.start_hooks(base / "plugin", clone, base / "local.toml") == ""  # a set one stays


def test_start_hooks_says_nothing_of_a_hooks_folder_with_only_samples(fresh):
    clone, base = fresh
    write(own_hooks_folder(clone) / "pre-commit.sample", "#!/bin/sh\n")
    assert se_start.start_hooks(base / "plugin", clone, base / "local.toml") == ""
    assert hooks_path(clone) == (base / "plugin" / ".githooks").as_posix()


def test_the_hooks_that_stop_running_are_every_name_but_a_sample_sorted():
    assert se_start.stopped_hooks(["pre-push", "commit-msg.sample", "pre-commit", "post-merge"]) == [
        "post-merge", "pre-commit", "pre-push"]
    assert se_start.stopped_hooks(["pre-commit.sample"]) == [] == se_start.stopped_hooks([])


def test_stopped_hooks_names_them_for_setup_and_none_where_the_folder_is_ses_own(fresh, capsys):
    clone, base = fresh
    folder = own_hooks_folder(clone)
    write(folder / "pre-commit", "#!/bin/sh\n")
    assert se_start.main(["stopped-hooks", "--repo", str(clone), "--hooks", ".githooks"]) == 0
    assert "no longer run: pre-commit" in capsys.readouterr().out
    assert se_start.main(["stopped-hooks", "--repo", str(clone), "--hooks", str(folder)]) == 0
    assert capsys.readouterr().out == ""


def test_start_hooks_takes_the_hooks_of_the_se_module_a_project_pins_else_this_ses(fresh):
    clone, base = fresh
    plugin = base / "plugin"
    assert se_start.start_hooks(plugin, clone, base / "local.toml") == ""
    assert hooks_path(clone) == (plugin / ".githooks").as_posix()  # no se module: this SE's hooks
    clone = fresh_clone(base, "pinning")
    module = base / "se-module"
    write(module / ".githooks" / "se-script", "#!/bin/sh\n")
    write(clone / "se.toml", '[components.se]\nref = "%s"\n' % ("0" * 40))
    config = write(base / "local.toml", f'[paths]\nse = "{module.as_posix()}"\n')
    assert se_start.start_hooks(plugin, clone, config) == ""
    assert hooks_path(clone) == (module / ".githooks").as_posix()  # the pinned se's, as its setup.sh sets


def test_start_hooks_changes_nothing_outside_a_project_checkout(tmp_path):
    plain = tmp_path / "plain"
    write(plain / "se.toml", '[project]\nversion = "0.1.0"\n')  # an se.toml, but no git
    assert se_start.start_hooks(tmp_path / "plugin", plain, None) == ""
    assert se_start.start_hooks(tmp_path / "plugin", None, None) == ""
    assert se_start.main(["--root", str(plain), "start-hooks"]) == 0


def test_without_docs_url_the_greeting_names_the_docs_of_ses_home(tmp_path: Path, fake_git_door) -> None:
    se_root = fake_git.init(tmp_path / "se")
    write(se_root / "se.toml", '[project]\nversion = "1.0.0"\n')
    assert se_start._docs_url(se_root) == ""  # no origin: nothing guesses one
    se_start.git_door.run("remote", "add", "origin", "https://github.com/alice/se.git", root=se_root)
    assert se_start._docs_url(se_root) == "https://alice.github.io/se/"
    write(se_root / "se.toml", '[project]\nversion = "1.0.0"\ndocs_url = "https://docs.example.com/se/"\n')
    assert se_start._docs_url(se_root) == "https://docs.example.com/se/"


# The components at the session's start (start_components, docs/components.md "Required and optional
# at start"): the tree resolved from what is placed first, a required component missing stopping the
# start, an optional one a line.


@pytest.fixture
def tree(tmp_path, isolated_git, monkeypatch):
    """SE's checkout, origin `team/se` on a host its machine's [urls] rewrites to folders, with a fake
    listing of origin's owner (SE_COMPONENT_LISTING=fake:) that marks no repository yet."""
    root = fake_git.init(tmp_path / "se")
    git(root, "remote", "add", "origin", SE_URL)
    folders = tmp_path / "hosts"
    local = write(tmp_path / "home" / ".se" / "local.toml",
                  f'[urls]\n"https://git.example.org/" = "{folders.as_posix()}/"\n')
    listing = tmp_path / "listing.json"

    class Tree:
        def __init__(self) -> None:
            self.root, self.local, self.folders = root, local, folders

        def list(self, owners: dict) -> None:
            listing.write_text(json.dumps(owners), encoding="utf-8")
            monkeypatch.setenv(se_modules.LISTING_VARIABLE, f"fake:{listing}")

        def release(self, name: str, version: str, manifest: str = "") -> str:
            """`team/<name>.git` with one commit, tagged `v<version>`, marked as a component; its
            se.toml holds `manifest` where one is given."""
            repo = folders / "team" / f"{name}.git"
            repo.mkdir(parents=True)
            fake_git.init(repo, "-b", "main")
            write(repo / "version.txt", f"{version}\n")
            if manifest:
                write(repo / "se.toml", manifest)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", f"{name} {version}")
            git(repo, "tag", f"v{version}")
            return git(repo, "rev-parse", "HEAD")

        def components(self, text: str) -> None:
            write(root / "se.toml", '[project]\nversion = "1.0.0"\n\n' + text)

        def start(self) -> tuple[list[str], bool]:
            return se_start.start_components(root, local)

        def machine(self, have: dict, get: dict | None = None) -> Path:
            """The fake machine the runtime check reads (SE_RUNTIMES=fake:): what it has, what RUNME gets."""
            file = write(tmp_path / "machine.json", json.dumps({"have": have, "get": get or {}}))
            monkeypatch.setenv(se_runtimes.VARIABLE, f"fake:{file}")
            return file

    found = Tree()
    found.list({"git.example.org/team": []})
    return found


def test_a_required_component_missing_stops_the_start_naming_its_path_the_remotes_read_and_the_remedy(tree):
    tree.components('[components.obs]\nversion = "^4.0"\n')

    lines, stopped = tree.start()

    assert stopped
    assert lines[0] == "SE cannot start: the required component obs is missing (se -> obs)."
    assert lines[1] == ("No remote's owner offers a repository obs marked as a component with a release its "
                        "pin ^4.0 admits (read: origin).")
    assert "  origin: git.example.org/team marks no repository obs as a component" in lines
    assert lines[-1] == "Add a remote of an owner that offers it: git remote add <remote> <address>"
    assert not (tree.root / se_modules.MODULES_DIR / "obs").exists(), "nothing half-placed"


def test_a_remote_that_could_not_be_read_is_named_with_gits_message(tree, monkeypatch):
    monkeypatch.setenv(se_modules.LISTING_VARIABLE, "off")  # the repository beside origin, read directly
    tree.components('[components.obs]\nversion = "^4.0"\n')

    lines, stopped = tree.start()

    assert stopped and lines[0] == "SE cannot start: the required component obs is missing (se -> obs)."
    unread = [line for line in lines if line.startswith("  origin: ")]
    assert len(unread) == 1 and " could not be read: git ls-remote --tags " in unread[0], lines
    assert unread[0].split(" failed in ", 1)[1].split(": ", 1)[1], "git's own message follows"


def test_an_optional_component_missing_is_one_line_and_the_start_goes_on(tree):
    lib = tree.release("lib", "1.0.0")
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[components.style]\nversion = "^1"\noptional = true\n\n[components.lib]\nversion = "^1"\n')

    lines, stopped = tree.start()

    assert not stopped
    assert lines == ["optional component se -> style not found on any remote's owner"]
    assert git(tree.root / se_modules.MODULES_DIR / "lib", "rev-parse", "HEAD") == lib
    assert se_modules.read_lock(tree.root) == {"lib": ("1.0.0", lib)}


def test_a_start_with_every_component_placed_at_its_locked_commit_asks_no_remote(tree, door_fake, monkeypatch):
    tree.release("lib", "1.0.0")
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[components.lib]\nversion = "^1"\n')
    assert tree.start() == ([], False)
    assert any("ls-remote" in call for call in door_fake.calls), "the first start found lib on its remote"
    shutil.rmtree(tree.folders)  # no remote offers anything now
    monkeypatch.setenv(se_modules.LISTING_VARIABLE, "fake:" + (tree.folders / "gone.json").as_posix())
    door_fake.calls.clear()

    assert tree.start() == ([], False)

    asked = [call for call in door_fake.calls if {"ls-remote", "fetch", "clone"} & set(call)]
    assert asked == [], "a placed tree asks no remote"


# The tree's runtimes (docs/components.md "Runtimes"): the union over the tree, checked before any
# component runs, what RUNME.conf gets got through RUNME.


def test_a_tree_needing_two_runtimes_one_missing_stops_the_start_before_any_component_runs_naming_it(tree):
    tree.release("lib", "1.0.0", '[runtimes]\ngo = "^1.22"\n')
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[runtimes]\nuv = "^0.5"\n\n[components.lib]\nversion = "^1"\n')
    tree.machine({"uv": "0.5.4"})

    lines, stopped = tree.start()

    assert stopped, "the core never starts"
    assert lines[0] == ("SE cannot start: the component tree needs 1 runtime this machine lacks; no component "
                        "runs until each is present:")
    assert lines[1:] == ["  go ^1.22 (for se -> lib): missing; RUNME.conf names no way to get it: add a line "
                         "get go <way> <what> (RUNME.sh's header), or install go yourself"]
    assert not (tree.root / se_modules.LOCK).exists(), "nothing locked"


def test_a_runtime_runme_conf_gets_is_got_through_runme_and_the_start_goes_on(tree):
    tree.release("lib", "1.0.0", '[runtimes]\ngo = "^1.22"\n')
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[components.lib]\nversion = "^1"\n')
    write(tree.root / "RUNME.conf", "path ~/.local/bin\nget go apt golang\nget go unix ./get-go.sh\nrun se\n")
    tree.machine({}, {"go": "1.23.0"})

    lines, stopped = tree.start()

    assert not stopped
    assert lines == ["runtime go 1.23.0: got through RUNME.conf (for se -> lib)"]
    conf = (tree.root / se_runtimes.GET_DIR / "RUNME.conf").read_text(encoding="utf-8").splitlines()
    assert conf[0] == f"path {(Path.home() / '.local' / 'bin').as_posix()}"
    assert conf[1:3] == ["need go command go", "get go apt golang"]
    assert conf[3].startswith("get go unix cd ") and conf[3].endswith(" && ./get-go.sh"), "a command runs in the root"
    assert conf[-1] == "run true"


def test_a_runtime_runme_cannot_get_or_at_a_version_its_range_refuses_is_named_with_the_remedy(tree):
    tree.release("lib", "1.0.0", '[runtimes]\ngo = "^1.22"\npython = "^3.12"\n')
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[runtimes]\npython = "^3.11"\n\n[components.lib]\nversion = "^1"\n')
    write(tree.root / "RUNME.conf", "get go apt golang\nrun se\n")
    tree.machine({"python": "3.11.4"})

    lines, stopped = tree.start()

    assert stopped
    assert lines[1:] == [
        "  python ^3.11 and ^3.12 (for se, se -> lib): found 3.11.4, outside the range; install a python it admits",
        "  go ^1.22 (for se -> lib): missing; RUNME could not get it: go is missing; run: golang"]


def test_two_ranges_of_one_runtime_that_admit_no_common_version_stop_the_start_naming_both(tree):
    tree.release("lib", "1.0.0", '[runtimes]\npython = "^3.12"\n')
    tree.list({"git.example.org/team": ["lib"]})
    tree.components('[runtimes]\npython = "~3.11.2"\n\n[components.lib]\nversion = "^1"\n')
    tree.machine({"python": "3.12.1"})

    lines, stopped = tree.start()

    assert stopped
    assert lines == ["SE cannot start: runtime python: se -> lib needs ^3.12 and se needs ~3.11.2, and no "
                     "version of python admits both; align the two ranges"]


@pytest.mark.parametrize(("table", "refusal"), [
    ('[runtimes]\ncobol = "^1"\n', "SE cannot start: se.toml: runtime 'cobol' is none SE knows; known: go, node, "
                                    "python, uv (se_runtimes.py PROBES adds one)"),
    ('[runtimes]\ngo = ">=1.22"\n', "SE cannot start: se.toml: runtime go: module go: version must be a semver range "
                                     "such as ^1.4, ~1.4.2 or 1.4.2, got '>=1.22'"),
    ('[[runtimes]]\ngo = "^1"\n', 'SE cannot start: se.toml: [runtimes] must be a table of <runtime> = "<version range>"'),
])
def test_a_runtimes_table_it_cannot_read_stops_the_start_naming_it(tree, table, refusal):
    tree.components(table)
    tree.machine({"go": "1.23.0"})

    assert tree.start() == ([refusal], True)


def test_start_components_prints_the_stop_and_exits_1(tree, capsys):
    tree.components('[components.obs]\nversion = "^4.0"\n')

    code = se_start.main(["--root", str(tree.root), "--local", str(tree.local), "start-components"])

    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("SE cannot start: the required component obs is missing (se -> obs).\n")


def test_start_components_of_a_project_without_components_says_nothing(tmp_path, capsys):
    write(tmp_path / "plain" / "se.toml", '[project]\nversion = "0.1.0"\n')
    assert se_start.start_components(tmp_path / "plain", None) == ([], False)
    assert se_start.start_components(None, None) == ([], False)


# The boot (docs/boot.md "The boot"): the checkout current, every dependency listed, upgraded on --upgrade.


@pytest.fixture
def checkout(tmp_path, isolated_git):
    """An origin with one commit on main and a clone of it, both with an identity to merge with."""
    origin = fake_git.init(tmp_path / "origin", "-b", "main")
    write(origin / "a.txt", "one\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "one")
    clone = fake_git.clone(origin, tmp_path / "clone")
    for repo in (origin, clone):
        git(repo, "config", "user.name", "alice")
        git(repo, "config", "user.email", "alice@example.com")
    return origin, clone


def commit(repo: Path, name: str, text: str) -> str:
    write(repo / name, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"change {name}")
    return git(repo, "rev-parse", "HEAD")


def test_the_boot_fast_forwards_the_integration_branch_and_says_when_it_is_current(checkout):
    origin, clone = checkout
    before = git(clone, "rev-parse", "HEAD")
    assert se_start.current_checkout(clone, "main") == (
        f"Checkout: main at {before[:7]}, current with origin/main", False)
    tip = commit(origin, "b.txt", "two\n")
    write(clone / "notes.txt", "untracked work\n")  # local work the fast-forward never touches
    line, stopped = se_start.current_checkout(clone, "main")
    assert not stopped and line == f"Checkout: main {before[:7]} -> {tip[:7]} (fast-forward to origin/main)"
    assert git(clone, "rev-parse", "HEAD") == tip and (clone / "notes.txt").read_text() == "untracked work\n"


def test_the_boot_merges_the_integration_branch_into_a_work_branch(checkout):
    origin, clone = checkout
    git(clone, "checkout", "-q", "-b", "work")
    mine = commit(clone, "mine.txt", "mine\n")
    tip = commit(origin, "b.txt", "two\n")
    line, stopped = se_start.current_checkout(clone, "main")
    assert not stopped and line.startswith(f"Checkout: work {mine[:7]} -> ") and line.endswith("(merged origin/main)")
    assert se_modules.git_ok(clone, "merge-base", "--is-ancestor", tip, "HEAD")
    assert (clone / "mine.txt").read_text() == "mine\n"


def test_the_boot_stops_where_a_merge_needs_a_clean_tree_or_conflicts_and_discards_nothing(checkout):
    origin, clone = checkout
    git(clone, "checkout", "-q", "-b", "work")
    mine = commit(clone, "a.txt", "mine\n")
    commit(origin, "a.txt", "theirs\n")
    write(clone / "mine.txt", "")
    git(clone, "add", "mine.txt")  # a staged change: a merge would need a clean tree
    line, stopped = se_start.current_checkout(clone, "main")
    assert stopped and line == ("Checkout: work needs a merge of origin/main and has local changes, the boot "
                                "stops; commit them, then boot again")
    git(clone, "commit", "-q", "-m", "staged")
    head = git(clone, "rev-parse", "HEAD")
    line, stopped = se_start.current_checkout(clone, "main")
    assert stopped and line.startswith("Checkout: merging origin/main into work does not merge cleanly, the boot "
                                       "stops; the merge was aborted, nothing was discarded: ")
    assert git(clone, "rev-parse", "HEAD") == head and (clone / "a.txt").read_text() == "mine\n"
    assert mine != head


def test_the_boot_moves_a_detached_head_its_integration_branch_leads_on_from(checkout):
    origin, clone = checkout
    before = git(clone, "rev-parse", "HEAD")
    git(clone, "checkout", "-q", "--detach", before)
    tip = commit(origin, "b.txt", "two\n")
    assert se_start.current_checkout(clone, "main") == (
        f"Checkout: detached {before[:7]} -> {tip[:7]} (origin/main)", False)
    commit(clone, "c.txt", "own\n")  # its own commit: nothing to lead on from
    line, stopped = se_start.current_checkout(clone, "main")
    assert not stopped and line.endswith("which origin/main does not lead on from; left as it is")


def test_the_boot_stops_where_origin_cannot_be_fetched(checkout, tmp_path):
    _, clone = checkout
    git(clone, "remote", "set-url", "origin", str(tmp_path / "gone"))
    line, stopped = se_start.current_checkout(clone, "main")
    assert stopped and line.startswith("Checkout: fetching origin failed, the boot stops: ")


@pytest.fixture
def booted(repos, monkeypatch):
    """The `repos` project, its checkout step answered: its origin is no repository here."""
    monkeypatch.setattr(se_start, "current_checkout", lambda root, integration: (
        f"Checkout: main current with origin/{integration}", False))
    return repos


def boot(r, upgrade=False):
    return se_start.boot(r["se"], r["project"], r["config"], r["world"], upgrade)


def test_the_boot_lists_se_and_every_pin_with_pinned_locked_and_newest_version(booted):
    lines, failed = boot(booted)
    assert not failed, lines
    root, se = booted["project"].as_posix(), booted["se"].as_posix()
    holder = se_modules.root_name(booted["project"])
    assert lines[:3] == [f"SE boot of {root}, checking", "Checkout: main current with origin/main",
                         "SE: installed 1.0.0, newest 2.0.0: the upgrade takes 2.0.0"]
    assert (f"  {holder} pins lib ^1, locked 1.0.0, newest 2.0.0: the upgrade takes 1.1.0; breaking release "
            f"2.0.0 beyond the pin, not taken; to take it: set version = \"^2.0\" in [components.lib] of "
            f"{root}/se.toml, then run: uv run python {se}/scripts/se_start.py boot --upgrade") in lines
    assert f"  {holder} pins tool ^1, locked 1.0.0, newest 1.0.0: current" in lines
    assert any(line.startswith(f"  {holder} pins mine ^0.1, locked none, ") and
               line.endswith(": a local path, the boot never touches it") for line in lines)
    assert lines[-2:] == [f"Upgrade: 2 items to take within the pins; run: uv run python {se}/scripts/se_start.py "
                          "boot --upgrade", "Left: 1 release beyond a pin, 1 of them breaking"]
    assert se_modules.read_lock(booted["project"])["lib"][0] == "1.0.0", "the check moves nothing"
    assert se_modules.checkout_version(booted["se"]) == (1, 0, 0)


def test_the_upgrade_moves_se_and_each_lock_within_its_pin_and_takes_no_breaking_release(booted):
    lines, failed = boot(booted, upgrade=True)
    assert not failed, lines
    holder = se_modules.root_name(booted["project"])
    assert lines[2] == "SE: installed 1.0.0, newest 2.0.0: SE: " + lines[2].split(": SE: ")[1]
    assert lines[2].endswith(" -> v2.0.0") and se_modules.checkout_version(booted["se"]) == (2, 0, 0)
    assert any(line.startswith(f"  {holder} pins lib ^1, locked 1.1.0, newest 2.0.0: moved 1.0.0 -> 1.1.0 "
                               "(se.lock; commit it); breaking release 2.0.0 beyond the pin, not taken")
               for line in lines), lines
    lock = se_modules.read_lock(booted["project"])
    assert lock["lib"] == ("1.1.0", git(booted["remotes"]["lib"], "rev-parse", "v1.1.0"))
    assert lock["tool"][0] == "1.0.0"
    assert lines[-2:] == ["Moved: 2 items", "Left: 1 release beyond a pin, 1 of them breaking"]
    again, failed = boot(booted, upgrade=True)
    assert not failed and again[2] == "SE: installed 2.0.0, newest 2.0.0: current"
    assert "Moved: 0 items" in again and se_modules.read_lock(booted["project"]) == lock


def test_a_project_that_pins_se_keeps_se_within_that_pin(booted):
    se_toml = booted["project"] / "se.toml"
    state = se_start.SEState(se_start.Item("SE", "se", (1, 0, 0), "x"), (2, 0, 0), (1, 1, 0), "^1")
    assert se_start.se_line(state) == ("SE: installed 1.0.0, pinned ^1 by the project, newest 2.0.0: the upgrade "
                                       "takes 1.1.0; 2.0.0 lies beyond the pin, not taken; to take it, set "
                                       "version = \"^2.0\" in [components.se] of the project's se.toml")
    assert se_toml.is_file()


def test_the_boot_stops_after_a_checkout_it_cannot_bring_current(booted, monkeypatch):
    monkeypatch.setattr(se_start, "current_checkout", lambda root, integration: ("Checkout: stops", True))
    lines, failed = boot(booted, upgrade=True)
    assert failed and lines[1:] == ["Checkout: stops"]
    assert se_modules.checkout_version(booted["se"]) == (1, 0, 0)


def test_the_boot_command_runs_from_the_command_line(booted, monkeypatch, capsys):
    monkeypatch.setattr(se_start, "SE_ROOT", booted["se"])
    monkeypatch.setattr(se_start, "World", lambda: booted["world"])
    code = se_start.main(["--root", str(booted["project"]), "--local", str(booted["config"]), "boot"])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith(f"SE boot of {booted['project'].as_posix()}, checking\n"), out


# The update (docs/boot.md "The update"): every newer release, across a major too, then the guide.


def test_the_update_takes_se_across_its_major_moves_every_own_pin_and_lock_and_hands_over_the_guide(booted):
    guide = ("# Upgrading\n\n## SE 2\n\nStep two.\n\n## SE 3\n\nStep three.\n\n## lib 2\n\n"
             "Lib step.\n")
    release(booted["upstream"], "3.0.0", {"docs/upgrading.md": guide})
    se, project = booted["se"], booted["project"]
    lines, failed = se_start.update(se, project, booted["config"], booted["world"])
    assert not failed, lines
    assert lines[:2] == [f"SE update of {project.as_posix()}", "Checkout: main current with origin/main"]
    assert lines[2].endswith(" -> v3.0.0") and se_modules.checkout_version(se) == (3, 0, 0)
    assert "lib: pin ^1 -> ^2.0.0 (se.toml; commit it)" in lines
    assert 'version = "^2.0.0"' in (project / "se.toml").read_text(encoding="utf-8")
    assert se_modules.read_lock(project)["lib"] == ("2.0.0", git(booted["remotes"]["lib"], "rev-parse", "v2.0.0"))
    assert "lib: 1.0.0 -> 2.0.0 (se.lock; commit it)" in lines
    text = "\n".join(lines)
    assert text.index("Upgrade guide: follow 3 sections in this order, every step and then its check, "
                      "and commit after each:") < text.index("## SE 2") < text.index("## SE 3") \
        < text.index("## lib 2") < text.index("Lib step.")
    again, failed = se_start.update(se, project, booted["config"], booted["world"])
    assert not failed and again[2:] == ["SE: 3.0.0, current",
                                        "Upgrade guide: no section lies between the versions; the update is done"]


def test_the_update_moves_no_pin_a_component_holds_and_names_the_repository_that_does(booted):
    from types import SimpleNamespace
    pin = SimpleNamespace(beyond=True, path=("project", "lib"), newest=(2, 0, 0),
                          module=se_modules.Module("tool", "", version="^1"),
                          line=lambda: "lib pins tool ^1, newest 2.0.0 (project -> lib -> tool)")
    assert se_start.move_pins(booted["project"], [pin]) == ([], [
        "lib pins tool ^1, newest 2.0.0 (project -> lib -> tool): lib moves it in its own repository (a ticket "
        "there)"])


def test_the_update_command_runs_from_the_command_line(booted, monkeypatch, capsys):
    monkeypatch.setattr(se_start, "SE_ROOT", booted["se"])
    monkeypatch.setattr(se_start, "World", lambda: booted["world"])
    code = se_start.main(["--root", str(booted["project"]), "--local", str(booted["config"]), "update"])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith(f"SE update of {booted['project'].as_posix()}\n"), out


def test_a_lock_outside_its_pin_is_one_the_upgrade_moves_into_it(booted):
    se_modules.write_lock(booted["project"], {**se_modules.read_lock(booted["project"]),
                                              "lib": ("2.0.0", git(booted["remotes"]["lib"], "rev-parse", "v2.0.0"))})
    holder = se_modules.root_name(booted["project"])
    lines, _ = boot(booted)
    assert any(line.startswith(f"  {holder} pins lib ^1, locked 2.0.0, newest 2.0.0: the upgrade takes 1.1.0")
               for line in lines), lines
