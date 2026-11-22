"""SE's home from the checkout's origin (`scripts/se_home.py`): the forms it reads, the fixed answer
for every other form, and the settings it derives. git runs behind the door's fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fake_git
import git_door
import se_home
import se_modules
from se_home import Home


# The one table of origins and answers, which kern's Go helper (kern's home) reads too, from the
# clone of kern se.toml pins (tests/conftest.py places it before collection).
TABLE = json.loads((se_modules.kern_dir(Path(__file__).resolve().parents[1]) / "home" / "testdata"
                    / "origins.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", TABLE["origins"], ids=lambda case: repr(case["origin"]))
def test_every_origin_of_the_shared_table_names_its_home(case: dict) -> None:
    want = case["home"]
    assert se_home.parse(case["origin"]) == (None if want is None else Home(**want))


@pytest.mark.parametrize("case", TABLE["answers"], ids=lambda case: case["url"])
def test_every_home_of_the_shared_table_gives_its_answers(case: dict) -> None:
    home = Home(**case["home"])

    assert (home.url, home.tracker, home.docs_url) == (case["url"], case["tracker"], case["docs"])
    assert {path: home.at(path) for path in case["at"]} == case["at"]
    assert {entry: home.named(entry) for entry in case["named"]} == case["named"]


def test_https_and_ssh_origins_name_the_home_without_credentials() -> None:
    home = se_home.parse("https://alice:token@example.com:443/alice/project.git")

    assert home == Home("example.com", "alice", "project")
    assert home.url == "https://example.com/alice/project"
    assert home.tracker == "alice/project"


@pytest.mark.parametrize(("origin", "want"), [
    ("https://example.com/alice/project", "https://example.com/alice/obs.git"),
    ("https://example.com/alice/project.git", "https://example.com/alice/obs.git"),
    ("git@example.com:alice/project.git", "git@example.com:alice/obs.git"),
    ("http://local_proxy@127.0.0.1:41231/git/alice/project", "http://local_proxy@127.0.0.1:41231/git/alice/obs.git"),
    ("/srv/alice/project", "/srv/alice/obs.git"),
    ("ssh://git@example.com:2222/alice/project.git", "ssh://git@example.com:2222/alice/obs.git"),
    ("file:///srv/alice/project.git", "file:///srv/alice/obs.git"),
    ("C:\\repos\\alice\\project.git", "C:/repos/alice/obs.git"),
    ("C:/repos/alice/project.git", "C:/repos/alice/obs.git"),
    ("\\\\server\\share\\project.git", "//server/share/obs.git"),
])
def test_a_relative_module_url_resolves_against_origin_as_git_does(origin: str, want: str) -> None:
    assert se_home.module_url(origin, "../obs.git") == want
    assert se_home.module_url(origin, "https://example.org/bob/obs.git") == "https://example.org/bob/obs.git"


def test_a_module_url_that_climbs_above_the_origin_is_refused() -> None:
    with pytest.raises(se_home.NoHome, match="climbs above"):
        se_home.module_url("https://example.com/alice", "../../../obs.git")


def test_the_checkout_home_comes_from_origin(tmp_path: Path, fake_git_door) -> None:
    root = fake_git.init(tmp_path / "project")
    git_door.run("remote", "add", "origin", "git@example.com:alice/project.git", root=root)

    assert se_home.home(root) == Home("example.com", "alice", "project")
    assert se_home.resolve_module(root, "../obs.git") == "git@example.com:alice/obs.git"


def test_a_relative_path_origin_resolves_from_the_checkout_not_the_working_directory(
        tmp_path: Path, fake_git_door, monkeypatch) -> None:
    # git reads a relative path origin from the checkout; a module cache clones from elsewhere (#1525).
    root = fake_git.init(tmp_path / "work" / "project")
    git_door.run("remote", "add", "origin", "../../srv/project.git", root=root)
    monkeypatch.chdir(tmp_path / "work")

    resolved = se_home.resolve_module(root, "../obs.git")

    assert Path(resolved) == tmp_path / "srv" / "obs.git"
    assert Path(resolved).is_absolute()


def test_the_remotes_come_origin_first_then_in_the_order_git_lists_them(tmp_path: Path, fake_git_door) -> None:
    root = fake_git.init(tmp_path / "project")
    assert se_home.remotes(root) == []
    for name, url in (("backup", "git@example.com:bob/project.git"), ("origin", "https://example.com/alice/project"),
                      ("mirror", "../mirror/project.git")):
        fake_git.git("-C", str(root), "remote", "add", name, url)
    assert se_home.remotes(root) == [
        ("origin", "https://example.com/alice/project"), ("backup", "git@example.com:bob/project.git"),
        ("mirror", (tmp_path / "mirror" / "project.git").as_posix())]


@pytest.mark.parametrize(("url", "want"), [
    ("https://example.com/alice/project", "https://example.com/alice/kern"),
    ("https://example.com/alice/project.git", "https://example.com/alice/kern.git"),
    ("https://example.com/alice/project/", "https://example.com/alice/kern"),
    ("git@example.com:bob/project.git", "git@example.com:bob/kern.git"),
    ("ssh://git@example.com/bob/project", "ssh://git@example.com/bob/kern"),
])
def test_the_repository_beside_a_remote_is_reached_as_the_remote_is(url: str, want: str) -> None:
    assert se_home.beside(url, "kern") == want


def test_without_an_origin_nothing_guesses_a_home(tmp_path: Path, fake_git_door, capsys) -> None:
    root = fake_git.init(tmp_path / "project")

    with pytest.raises(se_home.NoHome, match="no origin remote"):
        se_home.home(root)
    assert se_home.find(root) is None
    with pytest.raises(se_home.NoHome, match="relative to origin"):
        se_home.resolve_module(root, "../obs.git")
    assert se_home.resolve_module(root, "https://example.com/alice/obs.git") == "https://example.com/alice/obs.git"
    assert se_home.main(["--repo", str(root), "url"]) == 1
    assert "cannot be known" in capsys.readouterr().err


def test_a_proxy_origin_gets_the_fixed_answer(tmp_path: Path, fake_git_door) -> None:
    root = fake_git.init(tmp_path / "project")
    git_door.run("remote", "add", "origin", "http://local_proxy@127.0.0.1:41231/git/alice/project", root=root)

    with pytest.raises(se_home.NoHome, match="no https or ssh repository URL"):
        se_home.home(root)


def test_the_command_prints_each_answer(tmp_path: Path, fake_git_door, capsys) -> None:
    root = fake_git.init(tmp_path / "project")
    git_door.run("remote", "add", "origin", "https://github.com/alice/project", root=root)

    for command, want in (("url", "https://github.com/alice/project"), ("tracker", "alice/project"),
                          ("docs", "https://alice.github.io/project/")):
        assert se_home.main(["--repo", str(root), command]) == 0
        assert capsys.readouterr().out == want + "\n"
    assert se_home.main(["--repo", str(root), "module", "../obs.git"]) == 0
    assert capsys.readouterr().out == "https://github.com/alice/obs.git\n"
