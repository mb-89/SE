"""Tests for scripts/se_modules.py on the fake git behind one state file, shared with the scripts it runs (no network)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import fake_git

# Its git, and that of every script and binary it starts, is the fake behind one state file.
pytestmark = pytest.mark.usefixtures("shared_fake_git")

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


# Requirement 1: se.toml declares modules.


def test_manifest_declares_modules(tmp_path):
    write(
        tmp_path / "se.toml",
        f"""
[modules.obs]
url = "https://git.example.org/team/obs.git"
ref = "{SHA_A}"

[modules.style]
url = "https://git.example.org/team/style.git"
ref = "{SHA_A.upper()}"
path = "themes/plain"
""",
    )
    modules = se_modules.load_manifest(tmp_path)
    assert [m.name for m in modules] == ["obs", "style"]
    assert modules[0].url == "https://git.example.org/team/obs.git"
    assert modules[0].ref == SHA_A
    assert modules[0].path is None
    assert modules[1].ref == SHA_A
    assert modules[1].path == "themes/plain"


def test_manifest_without_modules_is_empty(tmp_path):
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
        ('url = "https://x.example/a.git"', "ref"),
        (f'ref = "{SHA_A}"', "url"),
        ('url = "https://x.example/a.git"\nref = "main"', "full commit SHA"),
        ('url = "https://x.example/a.git"\nref = "abc1234"', "full commit SHA"),
        (f'url = "https://x.example/a.git"\nref = "{SHA_A}"\npath = "../up"', "path"),
        (f'url = "https://x.example/a.git"\nref = "{SHA_A}"\npath = "/abs"', "path"),
        (f'url = "https://x.example/a.git"\nref = "{SHA_A}"\nbranch = "dev"', "unknown key"),
    ],
)
def test_manifest_rejects_invalid_module(tmp_path, body, message):
    write(tmp_path / "se.toml", f"[modules.m]\n{body}\n")
    with pytest.raises(se_modules.ModuleError, match=message):
        se_modules.load_manifest(tmp_path)


def test_manifest_rejects_bad_module_name(tmp_path):
    write(tmp_path / "se.toml", f'[modules."a/b"]\nurl = "u"\nref = "{SHA_A}"\n')
    with pytest.raises(se_modules.ModuleError, match="name"):
        se_modules.load_manifest(tmp_path)


def test_manifest_missing_is_an_error(tmp_path):
    with pytest.raises(se_modules.ModuleError, match="se.toml"):
        se_modules.load_manifest(tmp_path)


# Requirement 2: machine-local ~/.se/local.toml.


def module(name="lib", url="https://git.example.org/team/lib.git", ref=SHA_A, path=None):
    return se_modules.Module(name, url, ref, path)


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


def test_resolve_pinned_applies_url_rewrite(tmp_path):
    local = se_modules.LocalConfig(paths={}, urls={"https://git.example.org/": "https://mirror.example.net/"})
    source = se_modules.resolve(tmp_path, module(), local)
    assert source.kind == "pinned"
    assert source.url == "https://mirror.example.net/team/lib.git"


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


@pytest.fixture
def world(tmp_path):
    """An upstream module with three commits and a consumer pinned to the first one."""
    upstream = tmp_path / "upstream" / "lib"
    shas = make_upstream(upstream)
    consumer = tmp_path / "consumer"
    manifest = write(
        consumer / "se.toml",
        f"""# modules of the consumer
[modules.lib]  # the library
url = "{upstream.as_posix()}"
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


def test_sync_applies_url_rewrite(world, capsys):
    world.manifest.write_text(
        world.manifest.read_text().replace(world.upstream.as_posix(), "https://git.example.invalid/team/lib")
    )
    write(world.local, f'[urls]\n"https://git.example.invalid/team/" = "{world.upstream.parent.as_posix()}/"\n')
    code, out = run(world, capsys, "sync")
    assert code == 0, out
    assert git(world.cache, "rev-parse", "HEAD") == world.shas[0]
    assert "example.invalid" in world.manifest.read_text()


def test_sync_and_path_use_an_existing_local_path(world, capsys):
    write(world.local, f'[paths]\nlib = "{world.upstream.as_posix()}"\n')
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
    write(world.local, f'[paths]\nother = "{(world.root / "elsewhere").as_posix()}"\n')
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
        handle.write(f'\n[modules."other"]\nurl = "{other.as_posix()}"\nref = \'{other_shas[0]}\'\n')
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
    write(world.local, f'[paths]\nlib = "{(world.root / "absent").as_posix()}"\n')
    code, out = run(world, capsys, "status")
    assert code == 0
    assert "pinned" in out and "local path missing" in out


def test_status_shows_drift_of_a_local_path(world, capsys, tmp_path):
    checkout = tmp_path / "checkout"
    fake_git.clone(world.upstream.as_posix(), checkout)
    write(world.local, f'[paths]\nlib = "{checkout.as_posix()}"\n')

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
    write(world.local, f'[paths]\nlib = "{plain.as_posix()}"\n')
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
    """A url that is not rewritten to a local path fails instead of reaching the network."""
    world.manifest.write_text(
        world.manifest.read_text().replace(world.upstream.as_posix(), "https://git.example.invalid/team/lib")
    )
    code, out = run(world, capsys, "sync")
    assert code == 1
    assert "not allowed" in out or "transport" in out
    assert not (world.cache / ".git" / "index").exists()


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
    world.manifest.write_text(
        f'[modules.lib]\nurl = "{world.upstream.as_posix()}"\nversion = "^1.4"\npath = "sub"\n'
    )
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
    assert "no tag vMAJOR.MINOR.PATCH" in out and "matches version '^3'" in out
    assert "widen the range or release the module" in out


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
    write(released.local, f'[paths]\nlib = "{checkout.as_posix()}"\n')
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
    write(released.local, f'[paths]\nlib = "{released.upstream.as_posix()}"\n')
    code, out = run(released, capsys, "sync")
    assert code == 1
    assert str(released.upstream / "se.toml") in out and message in out
    assert 'set version = "MAJOR.MINOR.PATCH" under [project]' in out


# The actions a module ships follow its pin: update moves the workflows' calls of them.


def workflow(root: Path, ref: str) -> Path:
    return write(root / ".github" / "workflows" / "check.yml", f"""jobs:
  check:
    steps:
      - uses: actions/checkout@v7
      - uses: upstream/lib/.github/actions/suite-shard@{ref}
      - uses: 'Upstream/Lib/.github/actions/suite-time@{ref}'
      - uses: upstream/lib/.github/workflows/release.yml@v1
      - uses: other/lib/.github/actions/suite-time@{ref}
""")


def test_update_moves_the_workflows_calls_of_the_module_s_actions_to_its_new_tag(released, capsys):
    assert run(released, capsys, "sync")[0] == 0
    calls = workflow(released.root, "v1.10.1")
    newer = commit(released.upstream, "v1.11.0", {"version.txt": "1.11.0\n"})
    git(released.upstream, "tag", "v1.11.0")

    code, out = run(released, capsys, "update", "lib")

    assert code == 0, out
    assert locked(released)["lib"] == ("1.11.0", newer)
    assert ".github/workflows/check.yml: 2 action calls moved to @v1.11.0" in out
    text = calls.read_text(encoding="utf-8")
    assert "upstream/lib/.github/actions/suite-shard@v1.11.0\n" in text
    assert "'Upstream/Lib/.github/actions/suite-time@v1.11.0'" in text
    assert "upstream/lib/.github/workflows/release.yml@v1\n" in text  # a workflow, at its major
    assert "other/lib/.github/actions/suite-time@v1.10.1\n" in text  # another repository's
    code, out = run(released, capsys, "update", "lib")
    assert code == 0 and "action call" not in out  # already there: nothing to move


def test_update_moves_an_untagged_pin_s_action_calls_to_its_commit(world, capsys):
    calls = workflow(world.root, "v0.1.0")

    code, out = run(world, capsys, "update", "lib")

    assert code == 0, out
    text = calls.read_text(encoding="utf-8")
    assert f"upstream/lib/.github/actions/suite-shard@{world.shas[2]}" in text
    assert f"'Upstream/Lib/.github/actions/suite-time@{world.shas[2]}'" in text
    assert "other/lib/.github/actions/suite-time@v0.1.0" in text
