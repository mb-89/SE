"""Tests for scripts/se_modules.py on the fake git behind one state file, shared with the scripts it runs (no network)."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import fake_git

# Its git is the fake in memory; a test whose scripts or binaries run git as child processes takes
# the fake behind one state file, `shared_fake_git` (tests/conftest.py `door_fake`).
pytestmark = pytest.mark.usefixtures("door_fake")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "se_modules.py"

_spec = importlib.util.spec_from_file_location("se_modules", SCRIPT)
se_modules = importlib.util.module_from_spec(_spec)
sys.modules["se_modules"] = se_modules
_spec.loader.exec_module(se_modules)

SHA_A = "a" * 40


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# Requirement 1: se.toml lists components by name, with no address.


def test_manifest_declares_components(tmp_path):
    write(
        tmp_path / "se.toml",
        f"""
[components.obs]
ref = "{SHA_A}"

[components.style]
ref = "{SHA_A.upper()}"
path = "themes/plain"
optional = true
""",
    )
    modules = se_modules.load_manifest(tmp_path)
    assert [m.name for m in modules] == ["obs", "style"]
    assert modules[0].ref == SHA_A
    assert modules[0].path is None and modules[0].optional is False, "an entry without optional is required"
    assert modules[1].ref == SHA_A
    assert modules[1].path == "themes/plain" and modules[1].optional is True


def test_an_entry_with_url_is_refused_naming_finding_by_name(tmp_path):
    for url in ("../obs.git", "https://git.example.org/team/obs.git"):
        write(tmp_path / "se.toml", f'[components.obs]\nurl = "{url}"\nref = "{SHA_A}"\n')
        with pytest.raises(se_modules.ModuleError, match="component obs: url is refused in se.toml: a "
                           "component is found by its name under the owners of the checkout's remotes"):
            se_modules.load_manifest(tmp_path)


def test_the_old_modules_table_is_refused_naming_the_rename(tmp_path):
    write(tmp_path / "se.toml", f'[modules.obs]\nurl = "../obs.git"\nref = "{SHA_A}"\n')
    with pytest.raises(se_modules.ModuleError, match=re.escape("[modules] is [components] since se 6")):
        se_modules.load_manifest(tmp_path)


def test_manifest_without_components_is_empty(tmp_path):
    write(tmp_path / "se.toml", "")
    assert se_modules.load_manifest(tmp_path) == []


def test_manifest_accepts_project_settings(tmp_path):
    write(
        tmp_path / "se.toml",
        '[project]\nauthored_content = ["README.md", "docs/**/*.md"]\n',
    )
    assert se_modules.load_manifest(tmp_path) == []
    assert se_modules.main(["--root", str(tmp_path), "status"]) == 0


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('path = "sub"', "ref"),
        ('ref = "main"', "full commit SHA"),
        ('ref = "abc1234"', "full commit SHA"),
        (f'ref = "{SHA_A}"\npath = "../up"', "path"),
        (f'ref = "{SHA_A}"\npath = "/abs"', "path"),
        (f'ref = "{SHA_A}"\nbranch = "dev"', "unknown key"),
        (f'ref = "{SHA_A}"\noptional = "yes"', "optional must be true or false"),
    ],
)
def test_manifest_rejects_invalid_module(tmp_path, body, message):
    write(tmp_path / "se.toml", f"[components.m]\n{body}\n")
    with pytest.raises(se_modules.ModuleError, match=message):
        se_modules.load_manifest(tmp_path)


@pytest.mark.parametrize("name", ["a/b", "a.b", "a_b", "-a", "a" * 33])
def test_manifest_rejects_a_name_no_repository_carries(tmp_path, name):
    write(tmp_path / "se.toml", f'[components."{name}"]\nref = "{SHA_A}"\n')
    with pytest.raises(se_modules.ModuleError, match="1 to 32 letters, digits and '-'"):
        se_modules.load_manifest(tmp_path)


def test_manifest_missing_is_an_error(tmp_path):
    with pytest.raises(se_modules.ModuleError, match="se.toml"):
        se_modules.load_manifest(tmp_path)


# Requirement 2: machine-local ~/.se/local.toml.


def module(name="lib", ref=SHA_A, path=None):
    return se_modules.Module(name, ref, path)


def test_local_config_default_is_in_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert se_modules.default_local_config() == tmp_path / ".se" / "local.toml"


def test_local_config_missing_is_empty(tmp_path):
    local = se_modules.load_local(tmp_path / "absent.toml")
    assert local.paths == {} and local.urls == {}


def test_local_config_paths_and_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = write(
        tmp_path / "cfg" / "local.toml",
        """
[paths]
rel = "../checkouts/rel"
home = "~/src/home"

[urls]
"https://git.example.org/" = "https://mirror.example.net/git/"
"https://git.example.org/team/" = "ssh://git@mirror.example.net/team/"
""",
    )
    local = se_modules.load_local(config)
    assert local.paths["rel"] == (tmp_path / "checkouts" / "rel").resolve()
    assert local.paths["home"] == (tmp_path / "src" / "home").resolve()
    assert local.rewrite("https://git.example.org/team/lib.git") == "ssh://git@mirror.example.net/team/lib.git"
    assert local.rewrite("https://git.example.org/other/x.git") == "https://mirror.example.net/git/other/x.git"
    assert local.rewrite("https://elsewhere.example/x.git") == "https://elsewhere.example/x.git"


@pytest.mark.parametrize(
    "text",
    ["[paths]\nlib = 3\n", "[urls]\n'a' = 3\n", "[other]\nx = 1\n", "[path]\nx = 1\n", "paths = 'x'\n"],
)
def test_local_config_rejects_invalid(tmp_path, text):
    config = write(tmp_path / "local.toml", text)
    with pytest.raises(se_modules.ModuleError):
        se_modules.load_local(config)


def test_local_config_accepts_work_ticket_sections(tmp_path):
    config = write(
        tmp_path / "local.toml",
        """
integrator_session = "agent-session:/example"
public_identity = "mb <mb>"

[paths]
lib = "../lib"

[urls]
"https://example.com/" = "https://mirror.example.com/"

[trackers]
se = "tracker.example.com/example/se"

[worktree_roots]
se = "../worktrees"

[repos."tracker.example.com/example/se"]
integrator_session = "agent-session:/repository"

[mirrors]
se = [{ remote = "mirror", branch = "main", fetch = true, public = true }]
""",
    )

    local = se_modules.load_local(config)

    assert local.paths == {"lib": (tmp_path.parent / "lib").resolve()}
    assert local.urls == {"https://example.com/": "https://mirror.example.com/"}


def test_resolve_uses_existing_local_path(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "sub").mkdir(parents=True)
    local = se_modules.LocalConfig(paths={"lib": checkout}, urls={})
    source = se_modules.resolve(tmp_path / "repo", module(path="sub"), local)
    assert source.kind == "local"
    assert source.checkout == checkout
    assert source.dir == checkout / "sub"


def test_resolve_falls_back_to_pin_when_local_path_is_missing(tmp_path):
    local = se_modules.LocalConfig(paths={"lib": tmp_path / "absent"}, urls={})
    source = se_modules.resolve(tmp_path / "repo", module(), local)
    assert source.kind == "pinned"
    assert source.checkout == tmp_path / "repo" / ".se" / "modules" / "lib"
    assert "missing" in source.note


# Requirement 3: sync, status, update, path on the fake git's temporary repositories.


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Isolate git from the machine's configuration and allow only local transports."""
    gitconfig = write(tmp_path / "gitconfig", "[init]\n\tdefaultBranch = main\n")
    for key, value in {
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }.items():
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str) -> str:
    return se_modules.git(repo, *args)


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, text in files.items():
        write(repo / name, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_upstream(path: Path, count: int = 3) -> list[str]:
    path.mkdir(parents=True)
    fake_git.init(path, "-b", "main")
    return [commit(path, f"change {i}", {"version.txt": f"{i}\n", "sub/file.txt": f"sub {i}\n"}) for i in range(1, count + 1)]


#: The consumer's origin: its owner `team` on a host SE lists no repositories of, so a component
#: is read directly beside it (`host_listing`), at the address the machine's [urls] rewrites to the
#: fake upstreams (`World.urls`).
ORIGIN = "https://git.example.org/team/consumer"


@pytest.fixture
def world(tmp_path):
    """An upstream component with three commits and a consumer pinned to the first one, which finds
    it beside its origin: `https://git.example.org/team/lib`, rewritten to the upstream's folder."""
    upstream = tmp_path / "upstream" / "lib"
    shas = make_upstream(upstream)
    consumer = fake_git.init(tmp_path / "consumer")
    git(consumer, "remote", "add", "origin", ORIGIN)
    manifest = write(
        consumer / "se.toml",
        f"""# components of the consumer
[components.lib]  # the library
ref = "{shas[0]}"  # pinned
path = "sub"

[tool.other]
ref = "keep"
""",
    )
    local = tmp_path / "home" / ".se" / "local.toml"

    class World:
        pass

    w = World()
    w.upstream, w.shas, w.root, w.manifest, w.local = upstream, shas, consumer, manifest, local
    w.urls = f'[urls]\n"https://git.example.org/team/" = "{upstream.parent.as_posix()}/"\n'
    write(local, w.urls)
    w.cache = consumer / ".se" / "modules" / "lib"
    return w


def run(w, capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    code = se_modules.main(["--root", str(w.root), "--local", str(w.local), *args])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_sync_clones_at_pin(world, capsys):
    code, out = run(world, capsys, "sync")
    assert code == 0, out
    assert git(world.cache, "rev-parse", "HEAD") == world.shas[0]
    assert (world.cache / "version.txt").read_text() == "1\n"
    assert "lib: pinned" in out


def test_a_clean_sync_finds_the_component_beside_the_origin_and_clones_it(world, capsys):
    assert not world.cache.exists()

    code, out = run(world, capsys, "sync")

    assert code == 0, out
    assert git(world.cache, "rev-parse", "HEAD") == world.shas[0]
    assert Path(git(world.cache, "remote", "get-url", "origin")) == world.upstream
    assert ("origin: the mark of git.example.org/team/lib could not be checked (SE_COMPONENT_LISTING=off); "
            "its repository is read directly") in out


def test_a_placed_clone_at_its_pin_is_used_without_asking_any_remote(world, capsys):
    assert run(world, capsys, "sync")[0] == 0
    git(world.root, "remote", "set-url", "origin", "https://git.example.invalid/gone/consumer")

    code, out = run(world, capsys, "sync")

    assert code == 0, out
    assert "lib: pinned" in out and "could not be checked" not in out


def test_sync_follows_a_changed_pin_and_fetches(world, capsys):
    assert run(world, capsys, "sync")[0] == 0
    new = commit(world.upstream, "change 4", {"version.txt": "4\n"})
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], new))
    code, out = run(world, capsys, "sync")
    assert code == 0, out
    assert git(world.cache, "rev-parse", "HEAD") == new


def test_sync_refuses_a_dirty_clone(world, capsys):
    assert run(world, capsys, "sync")[0] == 0
    (world.cache / "version.txt").write_text("edited\n")
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], world.shas[1]))
    code, out = run(world, capsys, "sync")
    assert code == 1
    assert "local changes" in out
    assert (world.cache / "version.txt").read_text() == "edited\n"


def test_sync_reports_an_unknown_pin(world, capsys):
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], "b" * 40))
    code, out = run(world, capsys, "sync")
    assert code == 1
    assert "bbbbbbb" in out and "not found" in out


def test_sync_reports_a_path_missing_at_the_pin(world, capsys):
    world.manifest.write_text(world.manifest.read_text().replace('path = "sub"', 'path = "absent"'))
    code, out = run(world, capsys, "sync")
    assert code == 1
    assert "absent" in out


def test_sync_applies_the_url_rewrite_to_the_found_address(world, capsys):
    write(world.local, "")
    code, out = run(world, capsys, "sync")
    assert code == 1 and "https://git.example.org/team/lib could not be read" in out, out
    write(world.local, world.urls)
    code, out = run(world, capsys, "sync")
    assert code == 0, out
    assert git(world.cache, "rev-parse", "HEAD") == world.shas[0]


def test_sync_and_path_use_an_existing_local_path(world, capsys):
    write(world.local, world.urls + f'[paths]\nlib = "{world.upstream.as_posix()}"\n')
    code, out = run(world, capsys, "sync")
    assert code == 0, out
    assert "lib: local" in out
    assert not world.cache.exists()
    code, out = run(world, capsys, "path", "lib")
    assert code == 0
    assert Path(out.strip()) == world.upstream.resolve() / "sub"


def test_path_of_a_pinned_module(world, capsys):
    code, out = run(world, capsys, "path", "lib")
    assert code == 0
    assert Path(out.strip()) == world.cache / "sub"


def test_unknown_module_name_is_an_error(world, capsys):
    code, out = run(world, capsys, "sync", "nope")
    assert code == 1
    assert "nope" in out


def test_update_moves_the_pin_to_newest_main(world, capsys):
    write(world.local, world.urls + f'[paths]\nother = "{(world.root / "elsewhere").as_posix()}"\n')
    before = world.manifest.read_text()
    code, out = run(world, capsys, "update", "lib")
    assert code == 0, out
    after = world.manifest.read_text()
    assert after == before.replace(world.shas[0], world.shas[2])
    assert "elsewhere" not in after
    assert f"{world.shas[0][:7]} -> {world.shas[2][:7]}" in out
    assert "2 commits" in out and "change 2" in out and "change 3" in out
    assert git(world.cache, "rev-parse", "HEAD") == world.shas[2]


def test_update_to_a_tag_or_commit(world, capsys):
    git(world.upstream, "tag", "v2", world.shas[1])
    code, out = run(world, capsys, "update", "lib", "--to", "v2")
    assert code == 0, out
    assert se_modules.load_manifest(world.root)[0].ref == world.shas[1]
    code, out = run(world, capsys, "update", "lib", "--to", world.shas[0])
    assert code == 0, out
    assert se_modules.load_manifest(world.root)[0].ref == world.shas[0]
    assert "back" in out and "change 2" in out


def test_update_to_an_unknown_ref_is_an_error(world, capsys):
    code, out = run(world, capsys, "update", "lib", "--to", "no-such-ref")
    assert code == 1
    assert "no-such-ref" in out
    assert se_modules.load_manifest(world.root)[0].ref == world.shas[0]


def test_update_when_already_newest(world, capsys):
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], world.shas[2]))
    code, out = run(world, capsys, "update", "lib")
    assert code == 0, out
    assert "already at" in out


def test_update_all(world, capsys, tmp_path):
    other = tmp_path / "upstream" / "other"
    other_shas = make_upstream(other, 2)
    with world.manifest.open("a") as handle:
        handle.write(f'\n[components."other"]\nref = \'{other_shas[0]}\'\n')
    code, out = run(world, capsys, "update", "--all")
    assert code == 0, out
    assert {m.name: m.ref for m in se_modules.load_manifest(world.root)} == {
        "lib": world.shas[2],
        "other": other_shas[1],
    }
    assert 'ref = "keep"' in world.manifest.read_text()


@pytest.mark.parametrize("args", [["update"], ["update", "lib", "--all"], ["update", "--all", "--to", "main"]])
def test_update_arguments(world, capsys, args):
    with pytest.raises(SystemExit):
        se_modules.main(["--root", str(world.root), *args])


def test_status_of_a_pinned_module(world, capsys):
    code, out = run(world, capsys, "status")
    assert code == 0
    assert "lib" in out and "pinned" in out and "not synced" in out
    run(world, capsys, "sync")
    code, out = run(world, capsys, "status")
    assert "at pin" in out
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], world.shas[1]))
    code, out = run(world, capsys, "status")
    assert "run sync" in out


def test_status_of_a_missing_local_path(world, capsys):
    write(world.local, world.urls + f'[paths]\nlib = "{(world.root / "absent").as_posix()}"\n')
    code, out = run(world, capsys, "status")
    assert code == 0
    assert "pinned" in out and "local path missing" in out


def test_status_shows_drift_of_a_local_path(world, capsys, tmp_path):
    checkout = tmp_path / "checkout"
    fake_git.clone(world.upstream.as_posix(), checkout)
    write(world.local, world.urls + f'[paths]\nlib = "{checkout.as_posix()}"\n')

    code, out = run(world, capsys, "status")
    assert code == 0
    assert "local" in out and str(checkout.resolve()) in out
    assert "2 ahead of pin" in out

    git(checkout, "checkout", "-q", "--detach", world.shas[0])
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], world.shas[2]))
    code, out = run(world, capsys, "status")
    assert "2 behind pin" in out

    world.manifest.write_text(world.manifest.read_text().replace(world.shas[2], world.shas[0]))
    code, out = run(world, capsys, "status")
    assert "at pin" in out

    (checkout / "version.txt").write_text("edited\n")
    code, out = run(world, capsys, "status")
    assert "uncommitted changes" in out

    new = commit(world.upstream, "change 4", {"version.txt": "4\n"})
    world.manifest.write_text(world.manifest.read_text().replace(world.shas[0], new))
    code, out = run(world, capsys, "status")
    assert "pin not in local checkout" in out


def test_status_of_a_local_path_that_is_no_git_checkout(world, capsys, tmp_path):
    plain = tmp_path / "plain"
    (plain / "sub").mkdir(parents=True)
    write(world.local, world.urls + f'[paths]\nlib = "{plain.as_posix()}"\n')
    code, out = run(world, capsys, "status")
    assert code == 0
    assert "not a git checkout" in out


def test_root_is_found_from_a_subdirectory(world, capsys, monkeypatch):
    (world.root / "deep" / "er").mkdir(parents=True)
    monkeypatch.chdir(world.root / "deep" / "er")
    capsys.readouterr()
    assert se_modules.main(["--local", str(world.local), "status"]) == 0
    assert "lib" in capsys.readouterr().out


# Requirement 4: the suite needs no network, and the script runs as a command.


def test_network_transports_are_blocked(world, capsys):
    """An address that is not rewritten to a local path fails instead of reaching the network."""
    write(world.local, "")
    code, out = run(world, capsys, "sync")
    assert code == 1
    assert "the required component lib is missing" in out and "could not be read" in out, out
    assert not (world.cache / ".git" / "index").exists()


@pytest.mark.usefixtures("shared_fake_git")  # its child processes run git
def test_script_runs_as_a_command(world):
    args = [sys.executable, str(SCRIPT), "--root", str(world.root), "--local", str(world.local)]
    synced = subprocess.run([*args, "sync"], capture_output=True, text=True)
    assert synced.returncode == 0, synced.stderr
    status = subprocess.run([*args, "status"], capture_output=True, text=True)
    assert status.returncode == 0, status.stderr
    assert status.stdout.startswith("lib: pinned") and "at pin" in status.stdout
    failed = subprocess.run([*args, "path", "nope"], capture_output=True, text=True)
    assert failed.returncode == 1
    assert "error: unknown module(s): nope" in failed.stderr


def module_commands(markdown: str) -> list[str]:
    """The lines of `markdown`'s code fences that run se_modules.py: its commands; prose that
    names the script, wrapped or not, is a mention and not checked."""
    commands, fenced = [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif fenced and "se_modules.py" in line:
            commands.append(line.strip())
    return commands


def spelled_one_way(commands: list[str]) -> bool:
    return bool(commands) and all(
        line.startswith("uv run python <se>/scripts/se_modules.py ") for line in commands)


def test_readme_spells_the_module_command_one_way():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    commands = module_commands(readme)
    assert spelled_one_way(commands), commands


def test_the_invocation_check_judges_commands_not_mentions():
    prose = ("Run the sync first; it is the\nse_modules.py sync of the pin, and `se_modules.py`\n"
             "owns it.\n\n```sh\nuv run python <se>/scripts/se_modules.py sync\n```\n")
    assert module_commands(prose) == ["uv run python <se>/scripts/se_modules.py sync"]
    assert spelled_one_way(module_commands(prose))
    assert not spelled_one_way(module_commands("```sh\npython se_modules.py sync\n```\n"))


# Semantic versions: ranges resolve to the highest matching tag; local paths report their version.


@pytest.mark.parametrize(("text", "low", "high"), [
    ("^1.4", (1, 4, 0), (2, 0, 0)),
    ("^1.4.2", (1, 4, 2), (2, 0, 0)),
    ("^0.4", (0, 4, 0), (0, 5, 0)),
    ("^0.0.3", (0, 0, 3), (0, 0, 4)),
    ("^0", (0, 0, 0), (1, 0, 0)),
    ("~1.4.2", (1, 4, 2), (1, 5, 0)),
    ("~1", (1, 0, 0), (2, 0, 0)),
    ("1.4", (1, 4, 0), (1, 5, 0)),
    ("1.4.2", (1, 4, 2), (1, 4, 3)),
    ("=1.4.2", (1, 4, 2), (1, 4, 3)),
])
def test_a_range_admits_its_semver_versions(text, low, high):
    assert se_modules.version_bounds("lib", text) == (low, high)


@pytest.mark.parametrize("text", ["latest", "^v1", ">=1.0", "1.4.2.1", "=1.4", "^01.2"])
def test_a_malformed_range_is_an_error_naming_the_module(text):
    with pytest.raises(se_modules.ModuleError, match="module lib: .*1\\.4"):
        se_modules.version_bounds("lib", text)


@pytest.fixture
def released(world):
    """The upstream tagged v1.3.0, v1.4.0, v1.4.2, v1.10.1 and v2.0.0; the consumer pins ^1.4."""
    tags = {}
    for tag in ["v1.3.0", "v1.4.0", "v1.4.2", "v1.10.1", "v2.0.0", "nightly", "v1.11.0-rc1"]:
        tags[tag] = commit(world.upstream, tag, {"version.txt": f"{tag}\n"})
        git(world.upstream, "tag", tag)
    world.manifest.write_text('[components.lib]\nversion = "^1.4"\npath = "sub"\n')
    world.tags = tags
    return world


def locked(w) -> dict:
    return se_modules.read_lock(w.root)


def test_a_range_resolves_to_the_highest_matching_tag_and_is_locked(released, capsys):
    code, out = run(released, capsys, "sync")
    assert code == 0, out
    assert locked(released) == {"lib": ("1.10.1", released.tags["v1.10.1"])}
    assert git(released.cache, "rev-parse", "HEAD") == released.tags["v1.10.1"]
    assert f"({released.tags['v1.10.1'][:12]}, ^1.4 locked)" in out
    assert "version" in released.manifest.read_text() and "ref" not in released.manifest.read_text()


def test_a_locked_range_stays_until_update_and_status_says_a_newer_tag_exists(released, capsys):
    assert run(released, capsys, "sync")[0] == 0
    newer = commit(released.upstream, "v1.11.0", {"version.txt": "1.11.0\n"})
    git(released.upstream, "tag", "v1.11.0")
    assert run(released, capsys, "sync")[0] == 0
    assert locked(released)["lib"] == ("1.10.1", released.tags["v1.10.1"])
    se_modules.fetch(released.cache)
    code, out = run(released, capsys, "status")
    assert code == 0, out
    assert "(version ^1.4, pin " in out and "1.11.0 available: run update" in out
    code, out = run(released, capsys, "update", "lib")
    assert code == 0, out
    assert locked(released)["lib"] == ("1.11.0", newer)
    assert "(highest tag matching ^1.4)" in out and "4 commits added" in out
    assert git(released.cache, "rev-parse", "HEAD") == newer


def test_a_changed_range_is_resolved_again(released, capsys):
    assert run(released, capsys, "sync")[0] == 0
    released.manifest.write_text(released.manifest.read_text().replace("^1.4", "~1.4.0"))
    assert run(released, capsys, "sync")[0] == 0
    assert locked(released) == {"lib": ("1.4.2", released.tags["v1.4.2"])}


def rewrite_history(upstream: Path) -> dict[str, str]:
    """Move every tag of `upstream` to a new commit with the same tree, as a history rewrite does."""
    moved = {}
    for tag in git(upstream, "tag", "--list").splitlines():
        old = git(upstream, "rev-parse", f"refs/tags/{tag}^{{commit}}")
        moved[tag] = git(upstream, "commit-tree", f"{old}^{{tree}}", "-m", f"{tag} rewritten")
        git(upstream, "tag", "-f", tag, moved[tag])
    git(upstream, "update-ref", "refs/heads/main", moved["v1.11.0-rc1"])
    git(upstream, "gc", "-q", "--prune=now")
    return moved


def test_an_existing_clone_follows_tags_the_upstream_moved(released, capsys):
    assert run(released, capsys, "sync")[0] == 0
    moved = rewrite_history(released.upstream)
    se_modules.fetch(released.cache)
    assert git(released.cache, "rev-parse", "refs/tags/v1.10.1") == moved["v1.10.1"]
    assert run(released, capsys, "sync")[0] == 0
    assert git(released.cache, "rev-parse", "HEAD") == released.tags["v1.10.1"], "the lock pins the commit"
    code, out = run(released, capsys, "update", "lib")
    assert code == 0, out
    assert locked(released) == {"lib": ("1.10.1", moved["v1.10.1"])}
    assert git(released.cache, "rev-parse", "HEAD") == moved["v1.10.1"]
    assert git(released.cache, "rev-parse", "refs/tags/v1.4.2") == moved["v1.4.2"]


def test_the_fetch_prunes_branches_deleted_upstream(released, capsys):
    git(released.upstream, "branch", "topic")
    assert run(released, capsys, "sync")[0] == 0
    se_modules.fetch(released.cache)
    assert has_ref(released.cache, "refs/remotes/origin/topic")
    git(released.upstream, "branch", "-D", "topic")
    se_modules.fetch(released.cache)
    assert not has_ref(released.cache, "refs/remotes/origin/topic")


def has_ref(repo: Path, ref: str) -> bool:
    return se_modules.git_ok(repo, "show-ref", "--verify", "--quiet", ref)


def test_a_lock_naming_a_moved_tag_syncs_in_an_existing_clone(released, capsys):
    assert run(released, capsys, "sync")[0] == 0
    old = released.tags["v1.10.1"]
    moved = rewrite_history(released.upstream)
    lock = released.root / se_modules.LOCK
    lock.write_text(lock.read_text().replace(old, moved["v1.10.1"]))
    code, out = run(released, capsys, "sync")
    assert code == 0, out
    assert git(released.cache, "rev-parse", "HEAD") == moved["v1.10.1"]


def test_a_range_no_tag_matches_is_an_error_naming_the_remedy(released, capsys):
    released.manifest.write_text(released.manifest.read_text().replace("^1.4", "^3"))
    code, out = run(released, capsys, "sync")
    assert code == 1
    assert "the required component lib is missing (consumer -> lib)" in out, out
    assert "with a release its pin ^3 admits (read: origin)" in out
    assert "offers no release the pin admits" in out and "git remote add <remote> <address>" in out


def test_ref_and_version_together_or_update_to_a_ranged_module_are_errors(released, capsys):
    code, out = run(released, capsys, "update", "lib", "--to", "v1.4.0")
    assert code == 1 and "change the range in" in out
    write(released.manifest, released.manifest.read_text() + f'ref = "{SHA_A}"\n')
    with pytest.raises(se_modules.ModuleError, match="either ref or version"):
        se_modules.load_manifest(released.root)


def test_a_local_path_is_used_as_it_is_and_its_version_reported_not_updated(released, capsys):
    checkout = released.upstream
    write(checkout / "se.toml", '[project]\nversion = "1.12.0"\n')
    git(checkout, "add", "se.toml")
    head = commit(checkout, "local work", {"sub/local.txt": "mine\n"})
    write(checkout / "sub" / "uncommitted.txt", "draft\n")
    write(released.local, released.urls + f'[paths]\nlib = "{checkout.as_posix()}"\n')
    for command in ("sync", "status"):
        code, out = run(released, capsys, command)
        assert code == 0, out
        assert "lib: local" in out and "version 1.12.0" in out
    assert git(checkout, "rev-parse", "HEAD") == head
    assert (checkout / "sub" / "uncommitted.txt").read_text() == "draft\n"
    assert not released.cache.exists() and locked(released) == {}
    write(checkout / "se.toml", '[project]\nversion = "2.1.0"\n')
    assert "version 2.1.0, outside ^1.4" in run(released, capsys, "sync")[1]


@pytest.mark.parametrize(("text", "message"), [
    ("", "sets no version, so range '^1.4' cannot be checked"),
    ('[project]\nversion = "1.4"\n', "version '1.4' is not MAJOR.MINOR.PATCH"),
    ('[project]\nversion = 2\n', "version 2 is not MAJOR.MINOR.PATCH"),
])
def test_a_missing_or_malformed_local_version_is_an_error_naming_the_file_and_the_remedy(
        released, capsys, text, message):
    write(released.upstream / "se.toml", text)
    write(released.local, released.urls + f'[paths]\nlib = "{released.upstream.as_posix()}"\n')
    code, out = run(released, capsys, "sync")
    assert code == 1
    assert str(released.upstream / "se.toml") in out and message in out
    assert 'set version = "MAJOR.MINOR.PATCH" under [project]' in out


# SE's workflows follow its pin: update regenerates the project's copies of them (se_workflows.py).

RELEASE = ".github/workflows/release.yml"


def se_at_upstream(w) -> None:
    """The component `se` is found beside the origin, at the address the upstream's folder holds."""
    write(w.local, w.urls + f'"https://git.example.org/team/se" = "{w.upstream.as_posix()}"\n')


def test_update_regenerates_the_copies_of_ses_workflows_at_the_new_pin(world, capsys):
    import se_workflows
    shas = [commit(world.upstream, f"release {i}", {RELEASE: f"name: release\non:\n  workflow_call:\n# {i}\n"})
            for i in (1, 2)]
    world.manifest.write_text(f'[components.se]\nref = "{shas[0]}"\n')
    se_at_upstream(world)
    assert run(world, capsys, "sync")[0] == 0
    clone = world.root / ".se" / "modules" / "se"
    place = "${{ github.repository_owner }}/SE"
    se_workflows.write(world.root, se_workflows.plan(world.root, [RELEASE], repository=place, source=clone))
    copy = world.root / RELEASE
    marker = "# Code generated by se_workflows.py write from SE's {} at {} of {}. DO NOT EDIT.\n"
    assert copy.read_text().startswith(marker.format(RELEASE, shas[0], place))

    code, out = run(world, capsys, "update", "se")

    assert code == 0, out
    assert f"  {RELEASE}: generated from SE at {shas[1][:12]}" in out
    text = copy.read_text()
    assert text.startswith(marker.format(RELEASE, shas[1], place)) and text.endswith("# 2\n")
    assert se_workflows.check(world.root, se_workflows.plan(world.root, [], source=clone)) == []
    code, out = run(world, capsys, "update", "se")
    assert code == 0 and "generated" not in out  # already there: nothing to write


def test_update_of_another_module_leaves_the_workflows_alone(world, capsys):
    calls = write(world.root / ".github" / "workflows" / "check.yml", "jobs: {}\n")
    code, out = run(world, capsys, "update", "lib")
    assert code == 0, out
    assert calls.read_text() == "jobs: {}\n" and "generated" not in out


# The core switch of SE's session hooks (README "Machine-local `~/.se/local.toml`"): `[hooks] core`
# in the local file, read by hooks_core after SE_HOOK_CORE.
def local_hooks(tmp_path: Path, text: str) -> se_modules.LocalConfig:
    return se_modules.load_local(write(tmp_path / "local.toml", text))


@pytest.mark.parametrize(("text", "core"), [
    ('[hooks]\ncore = "off"\n', "off"), ("[hooks]\ncore = false\n", False), ("[hooks]\n", None)])
def test_local_config_accepts_hooks_core_as_a_string_or_a_boolean(tmp_path, text, core):
    local = local_hooks(tmp_path, text)
    assert local.hooks == ({} if core is None else {"core": core})
    assert se_modules.LocalConfig(paths={}, urls={}).hooks == {}


@pytest.mark.parametrize("text", ["[hooks]\ncore = 1\n", '[hooks]\ncor = "off"\n',
                                  '[hooks]\ncore = "off"\nother = "x"\n', 'hooks = "off"\n',
                                  "[hooks]\ncore = [\"off\"]\n"])
def test_local_config_refuses_any_other_hooks_naming_the_file(tmp_path, text):
    with pytest.raises(se_modules.ModuleError, match="local.toml: \\[hooks\\]"):
        local_hooks(tmp_path, text)


@pytest.mark.parametrize(("environment", "text", "answer"), [
    ({}, "", ("on", "default")),
    ({"SE_HOOK_CORE": "off"}, "", ("off", "environment")),
    ({"SE_HOOK_CORE": "OFF"}, "", ("off", "environment")),
    ({"SE_HOOK_CORE": "Off"}, '[hooks]\ncore = "on"\n', ("off", "environment")),
    ({"SE_HOOK_CORE": ""}, '[hooks]\ncore = "off"\n', ("on", "environment")),
    *(({"SE_HOOK_CORE": value}, "", ("on", "environment")) for value in (" off", "off ", "0", "false", "on")),
    ({}, '[hooks]\ncore = "off"\n', ("off", "local")),
    ({}, '[hooks]\ncore = "oFF"\n', ("off", "local")),
    ({}, "[hooks]\ncore = false\n", ("off", "local")),
    ({}, "[hooks]\ncore = true\n", ("on", "local")),
    ({}, '[hooks]\ncore = "no"\n', ("on", "local")),
    ({}, "[hooks]\n", ("on", "default")),
])
def test_hooks_core_reads_the_environment_first_then_the_local_file(tmp_path, environment, text, answer):
    assert se_modules.hooks_core(environment, local_hooks(tmp_path, text)) == answer


def test_hooks_core_command_needs_no_manifest_and_names_a_refused_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no se.toml here or above
    monkeypatch.delenv("SE_HOOK_CORE", raising=False)
    config = write(tmp_path / "local.toml", '[hooks]\ncore = "off"\n')
    assert se_modules.main(["--local", str(config), "hooks-core"]) == 0
    assert capsys.readouterr().out == "off local\n"
    monkeypatch.setenv("SE_HOOK_CORE", "on")
    assert se_modules.main(["--local", str(config), "hooks-core"]) == 0
    assert capsys.readouterr().out == "on environment\n"
    monkeypatch.delenv("SE_HOOK_CORE")
    assert se_modules.main(["--local", str(tmp_path / "absent.toml"), "hooks-core"]) == 0
    assert capsys.readouterr().out == "on default\n"
    write(config, "[hooks]\ncore = 1\n")
    assert se_modules.main(["--local", str(config), "hooks-core"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and str(config) in captured.err


@pytest.mark.parametrize("text", ['[hooks]\ncore = "off"\n', "[hooks]\ncore = 1\n", '[hooks]\ncor = "off"\n'])
def test_sync_accepts_hooks_core_and_refuses_any_other_hooks(world, capsys, text):
    write(world.local, world.urls + text)
    code, out = run(world, capsys, "sync")
    if text == '[hooks]\ncore = "off"\n':
        assert code == 0 and "lib: pinned" in out, out
    else:
        assert code == 1 and str(world.local) in out, out


def switches_json(monkeypatch, capsys, home: Path, root: Path) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import se_switches

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    capsys.readouterr()
    se_switches.main(["--json", "--root", str(root)])
    [effect] = [e for e in json.loads(capsys.readouterr().out)["switches"] if e["name"] == "SE_HOOK_CORE"]
    return effect


def test_the_switch_table_shows_hook_core_by_its_answering_layer(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / ".se").mkdir(parents=True)
    monkeypatch.delenv("SE_HOOK_CORE", raising=False)
    effect = switches_json(monkeypatch, capsys, home, tmp_path)
    assert (effect["state"], effect["layer"]) == ("on", "default")
    write(home / ".se" / "local.toml", '[hooks]\ncore = "off"\n')
    effect = switches_json(monkeypatch, capsys, home, tmp_path)
    assert (effect["state"], effect["layer"]) == ("off", "local")
    monkeypatch.setenv("SE_HOOK_CORE", "OFF")
    (home / ".se" / "local.toml").unlink()
    effect = switches_json(monkeypatch, capsys, home, tmp_path)
    assert (effect["state"], effect["layer"]) == ("off", "environment")


# A `go` pin: the version a go.mod requires of the module is the pin (README "Modules").

GO_MOD = "module example.com/app\n\ngo 1.25.0\n\nrequire (\n\tgithub.com/x/y v1.0.0\n\tlib v{version}\n)\n"


@pytest.fixture
def go_pinned(released):
    """The consumer pins lib by its components/go.mod's require lib v1.4.2."""
    released.manifest.write_text('[components.lib]\ngo = "components/go.mod"\n')
    released.gomod = write(released.root / "components" / "go.mod", GO_MOD.format(version="1.4.2"))
    return released


def test_a_go_pin_reads_the_version_its_go_mod_requires_and_locks_its_tag(go_pinned, capsys):
    module = se_modules.load_manifest(go_pinned.root)[0]
    assert (module.version, module.go, module.ref) == ("1.4.2", "components/go.mod", "")
    code, out = run(go_pinned, capsys, "sync")
    assert code == 0, out
    assert locked(go_pinned) == {"lib": ("1.4.2", go_pinned.tags["v1.4.2"])}
    assert git(go_pinned.cache, "rev-parse", "HEAD") == go_pinned.tags["v1.4.2"]
    assert "components/go.mod v1.4.2 locked" in out
    code, out = run(go_pinned, capsys, "status")
    assert code == 0 and "(components/go.mod v1.4.2, pin " in out and out.rstrip().endswith("at pin"), out
    go_pinned.gomod.write_text(GO_MOD.format(version="1.10.1"))
    assert run(go_pinned, capsys, "sync")[0] == 0
    assert locked(go_pinned) == {"lib": ("1.10.1", go_pinned.tags["v1.10.1"])}, "a moved require locks again"


def test_go_true_names_the_roots_go_mod(go_pinned):
    write(go_pinned.root / "go.mod", "module x\n\nrequire lib v2.0.0 // the pin\n")
    go_pinned.manifest.write_text(go_pinned.manifest.read_text().replace('"components/go.mod"', "true"))
    assert se_modules.load_manifest(go_pinned.root)[0].version == "2.0.0"


@pytest.mark.parametrize(("gomod", "message"), [
    ("module x\n\nrequire other v1.0.0\n", "components/go.mod has no require lib v<version>; add one"),
    ("module x\n\nrequire lib v0.0.0-20260101000000-abcdefabcdef\n", "not vMAJOR.MINOR.PATCH"),
    (None, "no components/go.mod in"),
])
def test_a_go_mod_without_the_require_is_refused(go_pinned, gomod, message):
    if gomod is None:
        go_pinned.gomod.unlink()
    else:
        go_pinned.gomod.write_text(gomod)
    with pytest.raises(se_modules.ModuleError, match=re.escape(message)):
        se_modules.load_manifest(go_pinned.root)


def test_a_go_pin_beside_ref_or_version_is_refused(go_pinned):
    write(go_pinned.manifest, go_pinned.manifest.read_text() + 'version = "^1.4"\n')
    with pytest.raises(se_modules.ModuleError, match="go pins the version; drop ref and version"):
        se_modules.load_manifest(go_pinned.root)


def test_a_go_pin_whose_version_has_no_tag_is_refused(go_pinned, capsys):
    go_pinned.gomod.write_text(GO_MOD.format(version="1.4.1"))
    code, out = run(go_pinned, capsys, "sync")
    assert code == 1
    assert "the required component lib is missing" in out and "its pin components/go.mod v1.4.1 admits" in out, out


def test_update_of_a_go_pin_is_refused_naming_the_go_mod_line(go_pinned, capsys):
    code, out = run(go_pinned, capsys, "update", "lib")
    assert code == 1
    assert "pinned by components/go.mod's require lib v1.4.2; change that line" in out
    code, out = run(go_pinned, capsys, "update", "--all")
    assert code == 0 and "lib: pinned by components/go.mod, left as it is" in out, out


def test_a_local_checkout_of_a_go_pin_reports_its_release_toml_version(go_pinned, capsys):
    checkout = go_pinned.upstream
    write(checkout / "se.toml", "[tests]\ncommand = []\n")
    write(checkout / "release.toml", 'version = "1.4.2"\n')
    write(go_pinned.local, go_pinned.urls + f'[paths]\nlib = "{checkout.as_posix()}"\n')
    for command in ("sync", "status"):
        code, out = run(go_pinned, capsys, command)
        assert code == 0 and "lib: local" in out and "version 1.4.2" in out and "off the pin" not in out, out
    write(checkout / "release.toml", 'version = "1.5.0"\n')
    assert "version 1.5.0, off the pin 1.4.2" in run(go_pinned, capsys, "status")[1]
    (checkout / "release.toml").unlink()
    code, out = run(go_pinned, capsys, "sync")
    assert code == 1 and "release.toml sets no version, so the pin 1.4.2 cannot be checked" in out


def test_work_tickets_sync_moves_the_se_clone_to_the_pin_the_merged_lock_names(world, capsys, monkeypatch):
    # A repository that pins se: after sync merges main, whose se.lock names a newer se, the clone
    # `.se/modules/se` is there too, so the public check runs at that pin (work_tickets.py sync).
    import work_tickets
    monkeypatch.setattr(se_modules, "default_local_config", lambda: world.local)
    world.manifest.write_text('[components.se]\nversion = "^1.0"\n')
    se_at_upstream(world)

    def lock(version: str, sha: str) -> None:
        write(world.root / "se.lock", f'[components.se]\nversion = "{version}"\nref = "{sha}"\n')

    git(world.upstream, "tag", "v1.0.0", world.shas[0])
    git(world.upstream, "tag", "v1.0.2", world.shas[2])
    lock("1.0.0", world.shas[0])
    assert run(world, capsys, "sync")[0] == 0
    clone = world.root / ".se" / "modules" / "se"
    assert git(clone, "rev-parse", "HEAD") == world.shas[0]

    lock("1.0.2", world.shas[2])  # what the merge brought
    work_tickets.se_module_at_lock(world.root)
    assert git(clone, "rev-parse", "HEAD") == world.shas[2]
    assert f"Moved se: pinned {clone}" in capsys.readouterr().out

    work_tickets.se_module_at_lock(world.root)  # at the pin already: nothing to say
    assert capsys.readouterr().out == ""


def test_work_tickets_sync_leaves_a_repository_without_an_se_clone_alone(world, monkeypatch):
    import work_tickets
    monkeypatch.setattr(se_modules, "default_local_config", lambda: world.local)
    work_tickets.se_module_at_lock(world.root)  # se.toml pins only lib, and no se clone exists
    assert not (world.root / ".se" / "modules" / "se").exists()


# Finding a component by name under the owners of the checkout's remotes (docs/components.md
# "Finding a component"), on the fake door with a fake host listing (SE_COMPONENT_LISTING=fake:).


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """A consumer whose remotes are `origin` (owner team) and `fork` (owner alice) on one host, its
    machine's [urls] rewriting that host to folders, and a fake listing of both owners."""
    consumer = fake_git.init(tmp_path / "consumer")
    git(consumer, "remote", "add", "origin", "https://git.example.org/team/consumer.git")
    git(consumer, "remote", "add", "fork", "https://git.example.org/alice/consumer.git")
    folders = tmp_path / "hosts"
    local = write(tmp_path / "home" / ".se" / "local.toml",
                  f'[urls]\n"https://git.example.org/" = "{folders.as_posix()}/"\n')
    listing = tmp_path / "listing.json"

    class Hosts:
        root, manifest = consumer, consumer / "se.toml"

        def __init__(self) -> None:
            self.local = local

        def list(self, owners: dict) -> None:
            listing.write_text(json.dumps(owners), encoding="utf-8")
            monkeypatch.setenv(se_modules.LISTING_VARIABLE, f"fake:{listing}")

        def release(self, owner: str, name: str, versions: list[str], manifest: str = "") -> dict[str, str]:
            """`<owner>/<name>.git` with a commit per version, each tagged `v<version>`."""
            repo = folders / owner / f"{name}.git"
            if not (repo / ".git").exists():
                repo.mkdir(parents=True)
                fake_git.init(repo, "-b", "main")
            tags = {}
            for version in versions:
                tags[version] = commit(repo, f"{name} {version}", {"version.txt": f"{owner} {version}\n",
                                                                   "se.toml": manifest})
                git(repo, "tag", f"v{version}")
            return tags

    hosts = Hosts()
    hosts.list({"git.example.org/team": [], "git.example.org/alice": []})
    return hosts


def finds(hosts, capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    code = se_modules.main(["--root", str(hosts.root), "--local", str(hosts.local), *args])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def origin_of(hosts, name: str) -> str:
    return Path(git(hosts.root / ".se" / "modules" / name, "remote", "get-url", "origin")).as_posix()


def test_a_component_is_found_under_the_first_remotes_owner(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"])
    alice = hosts.release("alice", "lib", ["1.1.0"])
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": ["lib"]})
    write(hosts.manifest, '[components.lib]\nversion = "^1.0"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert origin_of(hosts, "lib").endswith("/hosts/team/lib.git"), "origin's owner first, though alice's is newer"
    assert se_modules.read_lock(hosts.root)["lib"][0] == "1.0.0" and alice["1.1.0"]
    assert "could not be checked" not in out


def test_a_component_is_found_under_a_later_remotes_owner(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"])  # beside origin, but not marked as a component
    alice = hosts.release("alice", "Lib", ["1.1.0"])  # named without case, reached as listed
    hosts.list({"git.example.org/team": ["other"], "git.example.org/alice": ["Lib"]})
    write(hosts.manifest, '[components.lib]\nversion = "^1.0"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert origin_of(hosts, "lib").endswith("/hosts/alice/Lib.git")
    assert se_modules.read_lock(hosts.root) == {"lib": ("1.1.0", alice["1.1.0"])}


def test_the_first_owner_whose_release_the_pin_admits_wins_and_an_owner_is_read_once(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"])
    alice = hosts.release("alice", "lib", ["2.0.0"])
    git(hosts.root, "remote", "add", "mirror", "https://git.example.org/team/elsewhere.git")
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": ["lib"]})
    write(hosts.manifest, '[components.lib]\nversion = "^2"\n')
    calls = []
    finder = se_modules.Finder(hosts.root, se_modules.load_local(hosts.local),
                               lambda host, owner: calls.append(owner) or se_modules.host_listing(host, owner))

    found = finder.find("lib", lambda offer: any(v[0] == 2 for v in offer.releases))

    assert found.offer.owner == "git.example.org/alice" and found.offer.releases == {(2, 0, 0): alice["2.0.0"]}
    assert found.read == ["origin", "fork"], "mirror's owner is origin's, read once at its first place"
    assert calls == ["team", "alice"]


def test_an_owner_the_host_cannot_list_is_one_line_and_finding_goes_on(hosts, capsys):
    alice = hosts.release("alice", "lib", ["1.0.0"])
    hosts.list({"git.example.org/team": "no login for a private owner", "git.example.org/alice": ["lib"]})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert ("origin: git.example.org cannot list the repositories of team: no login for a private owner"
            in out.splitlines())
    assert se_modules.read_lock(hosts.root) == {"lib": ("1.0.0", alice["1.0.0"])}


def test_a_required_component_no_owner_offers_fails_naming_the_path_the_remotes_and_the_remedy(hosts, capsys):
    write(hosts.manifest, '[components.obs]\nversion = "^4.0"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 1
    assert ("the required component obs is missing (consumer -> obs).\nNo remote's owner offers a repository "
            "obs marked as a component with a release its pin ^4.0 admits (read: origin, fork).") in out
    assert "origin: git.example.org/team marks no repository obs as a component" in out
    assert "Add a remote of an owner that offers it: git remote add <remote> <address>" in out


def test_an_optional_component_missing_is_one_line_and_the_rest_is_placed(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"])
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.style]\nversion = "^1"\noptional = true\n\n'
                          '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert "optional component consumer -> style not found on any remote's owner" in out.splitlines()
    assert set(se_modules.read_lock(hosts.root)) == {"lib"}


# A found tag checked against se.lock's commit.


def test_a_found_tag_at_another_commit_than_the_lock_records_is_refused_naming_both(hosts, capsys):
    tags = hosts.release("team", "lib", ["1.0.0"])
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')
    write(hosts.root / "se.lock", f'[components.lib]\nversion = "1.0.0"\nref = "{SHA_A}"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 1
    assert (f"component lib: the release v1.0.0 that {(hosts.root.parent / 'hosts/team/lib.git').as_posix()} offers "
            f"(origin's owner git.example.org/team) points to {tags['1.0.0']}, but se.lock records {SHA_A}") in out
    assert "run se_modules.py update lib to lock the found one" in out
    assert not (hosts.root / ".se" / "modules" / "lib").exists()

    code, out = finds(hosts, capsys, "update", "lib")
    assert code == 0, out
    assert se_modules.read_lock(hosts.root) == {"lib": ("1.0.0", tags["1.0.0"])}


# The tree: each component's own list, read from its release, one version per name.


def test_the_tree_places_a_components_own_components_and_locks_them(hosts, capsys):
    style = hosts.release("team", "style", ["1.2.0", "1.3.0"])
    lib = hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nversion = "~1.2"\n')
    hosts.list({"git.example.org/team": ["lib", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert se_modules.read_lock(hosts.root) == {"lib": ("1.0.0", lib["1.0.0"]), "style": ("1.2.0", style["1.2.0"])}
    assert git(hosts.root / ".se" / "modules" / "style", "rev-parse", "HEAD") == style["1.2.0"]
    assert "(for lib)" in [line for line in out.splitlines() if line.startswith("style:")][0]


def test_two_hosts_whose_pins_admit_no_common_release_fail_naming_both_paths_and_pins(hosts, capsys):
    hosts.release("team", "style", ["1.2.0", "2.0.0"])
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nversion = "^1.2"\n')
    hosts.list({"git.example.org/team": ["lib", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n\n[components.style]\nversion = "^2.0"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 1
    assert ("component style: consumer -> style pins ^2.0 and consumer -> lib -> style pins ^1.2, and no "
            "release of style admits both; align the two pins") in out


def test_two_hosts_whose_pins_admit_a_common_release_take_it(hosts, capsys):
    style = hosts.release("team", "style", ["1.2.0", "1.5.0"])
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nversion = "~1.2"\n')
    hosts.list({"git.example.org/team": ["lib", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.style]\nversion = "^1"\n\n[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 0, out
    assert se_modules.read_lock(hosts.root)["style"] == ("1.2.0", style["1.2.0"]), "the newest both admit"


def test_a_name_already_on_the_path_is_that_component_checked_against_its_pin(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.consumer]\nversion = "^2"\n')
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": []})
    write(hosts.manifest, '[project]\nversion = "1.4.0"\n\n[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 1
    assert ("component consumer: consumer -> lib -> consumer pins ^2, but consumer is the root, at 1.4.0; "
            "change that pin") in out
    write(hosts.manifest, '[project]\nversion = "2.0.0"\n\n[components.lib]\nversion = "^1"\n')
    assert finds(hosts, capsys, "sync")[0] == 0
    assert not (hosts.root / ".se" / "modules" / "consumer").exists(), "the root is never placed again"


def test_a_component_whose_release_lists_url_is_refused_naming_its_path(hosts, capsys):
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nurl = "../style.git"\nversion = "^1"\n')
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "sync")

    assert code == 1 and "component style: url is refused in se.toml of consumer -> lib" in out, out


# Breaking releases beyond a pin (work issue 1719): the check lists each pin of the tree whose
# component's newest release breaks it, on the fake door with a fake host listing.


def unchanged(hosts):
    """se.toml's bytes and se.lock's absence, to hold the check to changing no pin."""
    return hosts.manifest.read_bytes(), (hosts.root / "se.lock").exists()


def test_the_check_names_a_pin_one_major_behind_with_both_versions(hosts, capsys):
    hosts.release("team", "obs", ["5.0.0", "5.3.0", "10.0.0"])
    hosts.list({"git.example.org/team": ["obs"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.obs]\nversion = "^5.0"\n')
    before = unchanged(hosts)

    code, out = finds(hosts, capsys, "breaking")

    assert (code, out) == (0, "consumer pins obs ^5.0, newest 10.0.0\n")
    assert unchanged(hosts) == before, "the check changes no pin and writes no lock"


def test_the_check_prints_one_line_where_every_pin_admits_its_newest_release(hosts, capsys):
    hosts.release("team", "obs", ["5.0.0", "5.3.0"])
    hosts.release("team", "style", ["1.4.2", "1.6.0"])  # beyond ~1.4.2, but not breaking
    hosts.list({"git.example.org/team": ["obs", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.obs]\nversion = "^5.0"\n\n[components.style]\nversion = "~1.4.2"\n')

    code, out = finds(hosts, capsys, "breaking")

    assert (code, out) == (0, "no breaking release beyond a pin: 2 pins checked (obs, style)\n")


def test_the_check_names_a_nested_pin_a_major_behind_by_its_holder(hosts, capsys):
    hosts.release("team", "style", ["1.2.0", "2.0.0"])
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nversion = "^1.2"\n')
    hosts.list({"git.example.org/team": ["lib", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "breaking")

    assert (code, out) == (0, "lib pins style ^1.2, newest 2.0.0 (consumer -> lib -> style)\n")


def test_the_check_reports_each_pin_where_sync_would_refuse_the_two(hosts, capsys):
    hosts.release("team", "style", ["1.2.0", "2.0.0"])
    hosts.release("team", "lib", ["1.0.0"], manifest='[components.style]\nversion = "^1.2"\n')
    hosts.list({"git.example.org/team": ["lib", "style"], "git.example.org/alice": []})
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n\n[components.style]\nversion = "^2.0"\n')

    code, out = finds(hosts, capsys, "breaking", "--all")

    assert code == 0, out
    assert out.splitlines() == ["consumer pins lib ^1, newest 1.0.0: admitted",
                                "consumer pins style ^2.0, newest 2.0.0: admitted",
                                "lib pins style ^1.2, newest 2.0.0 (consumer -> lib -> style): breaking"]
    assert finds(hosts, capsys, "sync")[0] == 1, "sync refuses the two pins the check reports"


def test_a_go_pin_below_1_0_is_broken_by_a_higher_minor(hosts, capsys):
    hosts.release("team", "kern", ["0.14.1", "0.14.3", "0.15.0"])
    hosts.list({"git.example.org/team": ["kern"], "git.example.org/alice": []})
    write(hosts.root / "go.mod", "module consumer\n\nrequire kern v0.14.1\n")
    write(hosts.manifest, '[components.kern]\ngo = true\n')

    code, out = finds(hosts, capsys, "breaking")

    assert (code, out) == (0, "consumer pins kern 0.14.1 (go.mod), newest 0.15.0\n")


def test_a_ref_pin_is_judged_by_the_release_at_its_commit(hosts, capsys):
    tags = hosts.release("team", "lib", ["1.0.0", "2.1.0"])
    hosts.list({"git.example.org/team": ["lib"], "git.example.org/alice": []})
    write(hosts.manifest, f'[components.lib]\nref = "{tags["1.0.0"]}"\n')

    code, out = finds(hosts, capsys, "breaking")

    assert (code, out) == (0, f"consumer pins lib ref {tags['1.0.0'][:12]} (1.0.0), newest 2.1.0\n")


def test_a_component_whose_releases_no_offer_names_fails_the_listing_naming_it(hosts, capsys, tmp_path):
    checkout = fake_git.init(tmp_path / "work" / "lib")
    write(checkout / "se.toml", '[project]\nversion = "1.0.0"\n')
    write(hosts.local, hosts.local.read_text(encoding="utf-8") + f'\n[paths]\nlib = "{checkout.as_posix()}"\n')
    write(hosts.manifest, '[components.lib]\nversion = "^1"\n')

    code, out = finds(hosts, capsys, "breaking")

    assert code == 1
    assert out.splitlines()[0] == "no breaking release beyond a pin: 1 pin checked (lib)"
    assert ("error: the releases of lib (consumer -> lib) could not be read: origin: git.example.org/team "
            "marks no repository lib as a component") in out


@pytest.mark.parametrize("base, newest, breaks", [
    ((5, 0, 0), (10, 0, 0), True), ((5, 0, 0), (5, 9, 0), False), ((0, 14, 1), (0, 15, 0), True),
    ((0, 14, 1), (0, 14, 9), False), ((0, 14, 1), (1, 0, 0), True), ((1, 4, 0), (1, 5, 0), False)])
def test_a_breaking_release_is_a_higher_major_or_below_1_0_a_higher_minor(base, newest, breaks):
    assert se_modules.is_breaking(base, newest) is breaks


# The host's listing: github.com's search for the topic, with the person's login where one is set.


class Answer:
    def __init__(self, data: dict) -> None:
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.data


def test_github_lists_an_owners_repositories_marked_component_with_the_login(monkeypatch):
    seen = []

    def urlopen(request, timeout):
        seen.append((request.full_url, request.get_header("Authorization")))
        return Answer({"items": [{"name": "kern"}, {"name": "obs"}]})

    monkeypatch.setattr(se_modules.urllib.request, "urlopen", urlopen)
    monkeypatch.delenv(se_modules.LISTING_VARIABLE)
    monkeypatch.setenv("GH_TOKEN", "token-value")
    assert se_modules.host_listing("github.com", "alice") == {"kern": "kern", "obs": "obs"}
    assert seen == [("https://api.github.com/search/repositories?q=topic%3Acomponent%20user%3Aalice&per_page=100",
                     "Bearer token-value")]


@pytest.mark.parametrize(("error", "kind", "message"), [
    (se_modules.urllib.error.HTTPError("u", 422, "Unprocessable", {}, None), "Unlisted",
     "github.com knows no owner alice it can list (HTTP 422)"),
    (se_modules.urllib.error.HTTPError("u", 403, "rate limited", {}, None), "NoListing", "github.com answered HTTP 403"),
    (se_modules.urllib.error.URLError("offline"), "NoListing", "github.com could not be read: offline"),
])
def test_a_listing_github_refuses_names_why(monkeypatch, error, kind, message):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(se_modules.urllib.request, "urlopen", urlopen)
    monkeypatch.delenv(se_modules.LISTING_VARIABLE)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(getattr(se_modules, kind), match=re.escape(message)):
        se_modules.host_listing("github.com", "alice")


def test_a_host_se_lists_nothing_of_or_the_listing_off_reads_beside_the_remote(monkeypatch):
    monkeypatch.delenv(se_modules.LISTING_VARIABLE)
    with pytest.raises(se_modules.NoListing, match="SE lists no repositories on git.example.org"):
        se_modules.host_listing("git.example.org", "team")
    monkeypatch.setenv(se_modules.LISTING_VARIABLE, "off")
    with pytest.raises(se_modules.NoListing, match="SE_COMPONENT_LISTING=off"):
        se_modules.host_listing("github.com", "team")
