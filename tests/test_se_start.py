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

# Its git, and that of every script and binary it starts, is the fake behind one state file.
pytestmark = pytest.mark.usefixtures("shared_fake_git")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("se_start", ROOT / "scripts" / "se_start.py")
se_start = importlib.util.module_from_spec(_spec)
sys.modules["se_start"] = se_start
_spec.loader.exec_module(se_start)
se_modules = se_start.se_modules

SE_URL = "https://git.example.org/team/se.git"
LIB_URL = "https://git.example.org/team/lib.git"
TOOL_URL = "https://git.example.org/team/tool.git"
OBS_URL = "https://git.example.org/team/obs.git"
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
[modules.lib]
url = "{LIB_URL}"
version = "^1.2"

[modules.tool]
url = "{TOOL_URL}"
version = "~2.0.1"

[modules.mine]
url = "https://git.example.org/team/mine.git"
version = "^3"

[modules.obs]
url = "{OBS_URL}"
ref = "{SHA}"
""")
    write(project / "se.lock", f"""
[modules.lib]
version = "1.2.0"
ref = "{SHA}"

[modules.tool]
version = "2.0.3"
ref = "{SHA}"
""")
    config = write(tmp_path / "local.toml", f'[paths]\nmine = "{local_dir.as_posix()}"\n')
    clock = Clock()
    tags = {SE_URL: ["v1.2.0", "v1.3.0", "v2.0.0"], LIB_URL: ["v1.2.0", "v1.4.1", "v2.0.0"],
            TOOL_URL: ["v2.0.3", "v2.1.0"], OBS_URL: ["v0.9.0"]}
    remotes = Remotes(clock, tags)
    world = se_start.World(clock=clock, remote=remotes, spawn=Spawns(), work=Work())
    return dict(se=se, project=project, config=config, cache=tmp_path / "cache.json",
                clock=clock, remotes=remotes, world=world)


def report(s, command="status", offline=False):
    if command == "check":
        return se_start.check(s["se"], s["project"], s["config"], s["cache"], s["world"])
    return se_start.status(s["se"], s["project"], s["config"], s["cache"], s["world"], offline)


def by_name(rep):
    return {state.item.name: state for state in rep.states}


# Requirement 1: counts from what loaded.


def test_counts_come_from_the_fixture_plugin(setup):
    rep = report(setup, offline=True)
    rules = len(se_start.public_check.RULES)
    assert se_start.greeting(rep, setup["se"])[0] == (
        f"SE 1.2.0 started: 2 skills, {rules} rules, 2 sub-agents. "
        "Documentation: https://docs.example.com/se/")


def test_the_rules_are_the_public_checks_labels():
    labels = {pattern.label for pattern in se_start.public_check.GENERIC_PATTERNS}
    messages = {"tracker-reference", "attribution-trailer"}
    assert set(se_start.public_check.RULES) == labels | messages
    assert len(se_start.public_check.RULES) == len(labels) + len(messages)


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
                               "applied by refresh; to take it, set version = \"^2.1\" in [modules.tool] of ")
               for line in lines)
    assert any(line.startswith("lib: in use 1.2.0; latest 2.0.0; update due to 1.4.1; 2.0.0 is outside ^1.2, "
                               "never applied by refresh; to take it, set version = \"^2.0\" in [modules.lib] of ")
               for line in lines)
    assert any(line.startswith("mine: in use 3.1.0 (local path ") and line.endswith("local, refresh never touches it")
               for line in lines)
    assert any(line.startswith("obs: in use none (pinned to commit aaaaaaa); latest 0.9.0; pinned by commit")
               for line in lines)
    assert sorted(setup["remotes"].calls) == sorted([SE_URL, LIB_URL, TOOL_URL, OBS_URL])  # one read each


def test_the_greeting_names_only_what_is_out_of_date_and_the_refresh(setup):
    report(setup, "check")
    lines = se_start.greeting(report(setup), setup["se"])
    manifest, se = (setup["project"] / "se.toml").as_posix(), setup["se"].as_posix()
    assert lines[1:] == [
        "  SE: 1.2.0 -> 1.3.0",
        "  lib: 1.2.0 -> 1.4.1",
        "  SE: 2.0.0 is outside SE's major 1; refresh never applies it; to take it, install SE 2.0.0 "
        "again as README \"Install\" says",
        f"  lib: 2.0.0 is outside ^1.2; refresh never applies it; to take it, set version = \"^2.0\" in "
        f"[modules.lib] of {manifest}, then run: uv run python {se}/scripts/se_modules.py update lib",
        f"  tool: 2.1.0 is outside ~2.0.1; refresh never applies it; to take it, set version = \"^2.1\" in "
        f"[modules.tool] of {manifest}, then run: uv run python {se}/scripts/se_modules.py update tool",
        f"Refresh: uv run python {setup['se'].as_posix()}/scripts/se_start.py refresh",
    ]


def test_an_up_to_date_greeting_is_one_line(setup):
    setup["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}
    report(setup, "check")
    assert len(se_start.greeting(report(setup), setup["se"])) == 1


def _manifest(root: Path, name: str = "se") -> None:
    write(root / se_start.PLUGIN_MANIFEST, json.dumps({"name": name}))


def test_a_plugin_older_than_the_se_checkout_it_works_on_is_named_in_one_line(setup):
    """A cloud container restored from a cached snapshot runs an older plugin than the checkout."""
    setup["remotes"].tags = {SE_URL: ["v1.2.0"], LIB_URL: ["v1.2.0"], TOOL_URL: ["v2.0.3"]}
    report(setup, "check")
    _manifest(setup["se"])
    _manifest(setup["project"])
    write(setup["project"] / "se.toml", '[project]\nversion = "1.4.0"\n')
    lines = se_start.greeting(report(setup), setup["se"])
    assert lines[1:] == ["SE 1.2.0 runs, older than this checkout's SE 1.4.0: in the cloud, a container "
                         "restored from a cached snapshot, which the environment rebuilds only when its "
                         "setup script changes (README \"Cloud sessions\")"]
    # Current, or a checkout of another plugin: no line.
    for version, name in (("1.2.0", "se"), ("1.4.0", "other")):
        write(setup["project"] / "se.toml", f'[project]\nversion = "{version}"\n')
        _manifest(setup["project"], name)
        assert len(se_start.greeting(report(setup), setup["se"])) == 1


# Requirement 4: errors say where they come from and the remedy; the greeting still appears.


def test_offline_marks_the_check_as_not_done(setup):
    setup["remotes"].offline = True
    assert report(setup, "check").errors
    lines = se_start.greeting(report(setup), setup["se"])
    assert lines[0].startswith("SE 1.2.0 started: ")
    assert f"Update check not done: lib: cannot reach {LIB_URL}: Could not resolve host; run it by hand to see " \
           f"the cause: uv run python {setup['se'].as_posix()}/scripts/se_start.py check" in lines


def test_a_bad_manifest_is_named_and_the_greeting_still_appears(setup):
    write(setup["project"] / "se.toml", "[modules.lib]\nurl = 1\n")
    lines = se_start.greeting(report(setup, offline=True), setup["se"])
    assert lines[0].startswith("SE 1.2.0 started: ")
    assert any("modules of" in line and "url is required" in line for line in lines)


def test_an_installed_copy_is_checked_against_its_plugin_manifests_repository(setup):
    shutil.rmtree(setup["se"] / ".git")
    write(setup["se"] / ".claude-plugin" / "plugin.json", json.dumps({"name": "se", "repository": SE_URL}))
    states = by_name(report(setup, "check"))
    assert states["SE"].item.note == "an installed copy" and states["SE"].due == (1, 3, 0)
    assert SE_URL in setup["remotes"].calls


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
    lines = se_start.greeting(report(setup), setup["se"])
    assert lines[-1] == "Update check not done: running in the background; the next start shows its result"
    assert setup["remotes"].calls == []


def test_a_new_module_without_a_cached_answer_starts_a_check(setup):
    report(setup, "check")
    write(setup["project"] / "se.toml", f'[modules.new]\nurl = "https://git.example.org/team/new.git"\nversion = "^1"\n')
    report(setup)
    assert len(setup["world"].spawn) == 1


def test_the_hook_output_shows_the_greeting_and_hands_it_to_the_session():
    data = json.loads(se_start.hook_output(["SE 1.2.0 started: ..."], ["se bootstrap: installing uv"],
                                           Path("/opt/se")))
    assert data["systemMessage"] == "se bootstrap: installing uv\nSE 1.2.0 started: ..."
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert data["hookSpecificOutput"]["additionalContext"].startswith(data["systemMessage"])


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

def kern_greeting(setup, capsys, monkeypatch, *args, answer=None):
    """The hook's greeting lines with bootstrap.sh's kern arguments, kern's status answering `answer`."""
    monkeypatch.setattr(se_start, "SE_ROOT", setup["se"])
    write(setup["se"] / "kern" / "release.toml",
          'version = "0.2.0"\ndownload = "https://github.com/mb-89/SE/releases/download/kern-v{version}"\n')
    asked = []
    world = dataclasses.replace(setup["world"], kern=lambda binary, root: asked.append((binary, root)) or answer)
    assert se_start.main(["--root", str(setup["project"]), "--local", str(setup["config"]),
                          "--cache", str(setup["cache"]), "status", "--hook", "--offline", *args],
                         world=world) == 0
    return json.loads(capsys.readouterr().out)["systemMessage"].splitlines(), asked


def test_the_greeting_names_a_running_kern_under_its_first_line(setup, capsys, monkeypatch):
    lines, asked = kern_greeting(setup, capsys, monkeypatch, "--kern-bin", "/k/kern-0.2.0",
                                 answer={"state": "running", "health": {"pid": 42}})
    assert lines[1] == "kern 0.2.0: running, pid 42"
    assert asked == [(Path("/k/kern-0.2.0"), setup["project"].resolve())]


@pytest.mark.parametrize(("args", "answer", "line"), [
    (["--kern-bin", "/k"], {"state": "starting"}, "kern 0.2.0: starting"),
    (["--kern-starting", "fetching release kern-v0.2.0 for linux-amd64 in the background"], None,
     "kern 0.2.0: starting: fetching release kern-v0.2.0 for linux-amd64 in the background"),
    (["--kern-failed", "kern start: boom", "--kern-bin", "/k"], {"state": "running"}, "kern 0.2.0: failed: kern start: boom"),
    (["--kern-bin", "/k"], {"state": "not running"}, "kern 0.2.0: failed: not running after its start; see "),
    (["--kern-bin", "/k"], None, "kern 0.2.0: failed: its status does not answer; see "),
])
def test_the_greeting_names_kern_starting_or_failed_with_the_cause(setup, capsys, monkeypatch, args, answer, line):
    lines, _ = kern_greeting(setup, capsys, monkeypatch, *args, answer=answer)
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


def test_without_word_of_kern_the_greeting_names_none(setup, capsys, monkeypatch):
    lines, asked = kern_greeting(setup, capsys, monkeypatch)
    assert not any(line.startswith("kern") for line in lines) and asked == []


def test_the_greeting_names_the_applications_own_binary_where_it_builds_one(setup, capsys, monkeypatch):
    # Where se.toml names a [binary] release, the line is the application's own binary, not the bare
    # kern: SE's is se (components/release.toml), kern's core plus SE's Go components.
    write(setup["se"] / "se.toml", '[project]\nversion = "5.0.0"\n[binary]\nrelease = "components/release.toml"\n')
    write(setup["se"] / "components" / "release.toml",
          'version = "0.1.0"\ndownload = "https://github.com/mb-89/SE/releases/download/se-v{version}"\n'
          'binary = "se"\npackage = "./cmd/se"\n')
    lines, asked = kern_greeting(setup, capsys, monkeypatch, "--kern-bin", "/k/se-0.1.0",
                                 answer={"state": "running", "health": {"pid": 7}})
    assert lines[1] == "se 0.1.0: running, pid 7"


# What is due in the work: a retro, an overhaul and the fleet's findings, from the cache (work
# issue "start names what's due"; the overhaul countdown).

DUE = {"retro": {"landed": 12, "due_after": 10}, "overhaul": {"retros": 3, "due_after": 3},
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


OVERHAUL_LINE = ("Overhaul due: 3 retros closed since the last overhaul (due after 3); file one "
                 "with: uv run python {se}/scripts/overhaul.py new, then run: uv run python "
                 "{se}/scripts/overhaul.py read <overhaul issue> --out <draft>")


def test_a_due_retro_overhaul_and_the_fleets_findings_appear_from_a_seeded_cache(setup):
    seed(setup, DUE)
    se = setup["se"].as_posix()
    expected = [
        "Retro due: 12 work issues landed since the last retro (due after 10); file one from "
        f".github/ISSUE_TEMPLATE/retro.md, then run: uv run python {se}/scripts/retro.py collect "
        "<retro issue> --out <draft>",
        OVERHAUL_LINE.format(se=se),
        "Fleet: 3 findings (failed check #7; stray branch #3, #5); see each with its remedy: "
        f"uv run python {se}/scripts/work_tickets.py fleet-check --worktree {setup['project'].as_posix()}",
    ]
    rep = report(setup)
    assert se_start.greeting(rep, setup["se"])[1:] == expected
    assert work_lines(se_start.full(rep, setup["se"])) == expected
    assert setup["remotes"].calls == [] and setup["world"].work == [] and setup["world"].spawn == []


def test_the_parts_kern_holds_live_replace_the_cached_ones_and_say_so(setup):
    seed(setup, DUE)
    asked = []
    live = {"fleet": {"findings": [{"kind": "conflict", "issue": 9}], "issues": 14, "from": "kern"}}
    setup["world"] = dataclasses.replace(setup["world"], live=lambda root: asked.append(root) or live)
    se = setup["se"].as_posix()
    assert work_lines(se_start.greeting(report(setup), setup["se"])) == [
        "Retro due: 12 work issues landed since the last retro (due after 10); file one from "
        f".github/ISSUE_TEMPLATE/retro.md, then run: uv run python {se}/scripts/retro.py collect "
        "<retro issue> --out <draft>",
        OVERHAUL_LINE.format(se=se),
        "Fleet: 1 finding (conflict #9), live from kern over 14 issues read; see each with its "
        f"remedy: uv run python {se}/scripts/work_tickets.py fleet-check --worktree "
        f"{setup['project'].as_posix()}"]
    assert asked == [setup["project"]]
    live["retro"] = {"landed": 3, "due_after": 3, "issues": 14, "from": "kern"}
    assert work_lines(se_start.greeting(report(setup), setup["se"]))[0].startswith(
        "Retro due: 3 work issues landed since the last retro (due after 3, live from kern); ")
    live["overhaul"] = {"retros": 4, "due_after": 3, "issues": 14, "from": "kern"}
    assert work_lines(se_start.greeting(report(setup), setup["se"]))[1].startswith(
        "Overhaul due: 4 retros closed since the last overhaul (due after 3, live from kern); ")
    live["overhaul"] = {"retros": 2, "due_after": 3, "issues": 14, "from": "kern"}
    assert not any(line.startswith("Overhaul") for line in work_lines(
        se_start.greeting(report(setup), setup["se"])))


def test_without_a_core_the_live_read_answers_none_and_the_cache_stands(setup, tmp_path):
    assert se_start.kern_names.live_work(tmp_path) is None
    write(tmp_path / ".se" / ".runtime" / "standing.json", '{"bus": "nats://127.0.0.1:9", "users": {"client": "x"}}')
    assert se_start.kern_names.live_work(tmp_path) is None  # a standing file whose bus is gone
    seed(setup, DUE)
    assert len(work_lines(se_start.greeting(report(setup), setup["se"]))) == 3


def test_the_live_read_keeps_only_the_parts_whose_names_hold_issues(monkeypatch):
    names = {"fleet/findings": {"issues": 0, "findings": []},
             "retro-due/due": {"issues": 4, "landed": 1, "due_after": 10, "due": False}}
    monkeypatch.setattr(se_start.kern_names, "read", lambda root, wanted: names)
    assert se_start.kern_names.live_work(Path(".")) == {
        "retro": {"landed": 1, "due_after": 10, "issues": 4, "from": "kern"}}
    # The overhaul part comes from the same name, retro-due/due, where it counts the retros.
    names["retro-due/due"].update(retros=2, overhaul_after=3)
    assert se_start.kern_names.live_work(Path("."))["overhaul"] == {
        "retros": 2, "due_after": 3, "issues": 4, "from": "kern"}
    # A partial view of the fleet is no verdict: the cached check stands; a complete one replaces it.
    names["fleet/findings"] = {"issues": 1, "complete": False, "findings": []}
    assert "fleet" not in se_start.kern_names.live_work(Path("."))
    names["fleet/findings"] = {"issues": 9, "complete": True, "findings": []}
    assert se_start.kern_names.live_work(Path("."))["fleet"] == {"findings": [], "issues": 9,
                                                                  "from": "kern"}
    names["fleet/findings"] = {"issues": 0, "findings": []}
    names["retro-due/due"]["issues"] = 0
    assert se_start.kern_names.live_work(Path(".")) is None


@pytest.mark.parametrize("work", [None, {"retro": {"landed": 9, "due_after": 10}, "fleet": {"findings": []}}])
def test_the_lines_are_absent_without_gh_without_a_cache_or_with_nothing_due(setup, work):
    assert work_lines(se_start.greeting(report(setup), setup["se"])) == []  # no cache yet
    seed(setup, work)
    lines = se_start.greeting(report(setup), setup["se"])
    assert work_lines(lines) == [] and len(lines) == 1


def test_a_failed_read_names_its_part_and_the_remedy(setup):
    seed(setup, {"retro": {"error": "gh api failed: HTTP 502"}, "fleet": {"findings": []}})
    assert work_lines(se_start.greeting(report(setup), setup["se"])) == [
        "Retro check not done: gh api failed: HTTP 502; run it by hand to see the cause: "
        f"uv run python {setup['se'].as_posix()}/scripts/se_start.py check"]


def test_status_reads_the_seeded_cache_within_its_budget(setup):
    seed(setup, DUE)
    started = time.perf_counter()
    lines = se_start.greeting(report(setup), setup["se"])
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
    assert se_start.work_check(project) == {"retro": {"error": "gh api issues failed: HTTP 502"},
                                            "overhaul": {"error": "gh api issues failed: HTTP 502"},
                                            "fleet": {"findings": [{"kind": "stray branch", "issue": 3}]}}
    monkeypatch.setattr(retro, "GhDoor", lambda *args: "door")
    monkeypatch.setattr(retro, "landed_since_retro", lambda door, repo, branch: 11)
    monkeypatch.setattr(se_start._load("overhaul"), "retros_since_overhaul", lambda door: 2)
    work = se_start.work_check(project)
    assert work["retro"] == {"landed": 11, "due_after": 10}
    assert work["overhaul"] == {"retros": 2, "due_after": 3}


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


@pytest.fixture
def repos(tmp_path, isolated_git):
    """An se remote with v1.0.0, v1.1.0 and v2.0.0, a clone of it at v1.0.0; module remotes lib
    (v1.0.0, v1.1.0, v2.0.0) and tool (v1.0.0 only); a project locked at lib 1.0.0 and tool 1.0.0."""
    scripts = {f"scripts/{name}": (ROOT / "scripts" / name).read_text(encoding="utf-8")
               for name in ("se_start.py", "git_door.py", "se_modules.py", "public_check.py",
                             "metrics.py", "feedback.py", "kern_names.py", "se_plugin.py", "public-check-terms.toml")}
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
        remote = tmp_path / f"{name}-remote"
        remote.mkdir()
        fake_git.init(remote, "-b", "main")
        for version in versions:
            release(remote, version)
        remotes[name] = remote
    project = tmp_path / "project"
    local_dir = tmp_path / "local-lib"
    write(local_dir / "se.toml", '[project]\nversion = "0.1.0"\n')
    write(project / "se.toml", "".join(
        f'[modules.{name}]\nurl = "{remote.as_uri()}"\nversion = "^1"\n\n' for name, remote in remotes.items())
        + f'[modules.mine]\nurl = "{remotes["lib"].as_uri()}"\nversion = "^0.1"\n')
    config = write(tmp_path / "local.toml", f'[paths]\nmine = "{local_dir.as_posix()}"\n')
    for name, remote in remotes.items():
        se_modules.write_lock(project, name, "1.0.0", git(remote, "rev-parse", "v1.0.0"))
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
    assert (f"lib: 2.0.0 is outside ^1; not applied; to take it, set version = \"^2.0\" in [modules.lib] of "
            f"{(repos['project'] / 'se.toml').as_posix()}, then run: uv run python {repos['se'].as_posix()}"
            "/scripts/se_modules.py update lib") in lines
    assert ("SE: 2.0.0 is outside SE's major 1; not applied; to take it, install SE 2.0.0 again as README "
            "\"Install\" says") in lines
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
    greeting = text[text.index("- **Greeting**"):text.index("- **Turn-start check**")]
    assert "Without gh (the cloud) it names neither: at your first turn run" in greeting
    assert "`work_tickets.py fleet-check --worktree <main checkout>`, run the plan it prints" in greeting


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
    return [line for line in se_start.greeting(report(s), s["se"]) if "SE's agents" in line
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
    lines = se_start.greeting(report(setup), setup["se"])
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
            "install plugin-dev@claude-plugins-official") in se_start.greeting(rep, se)
