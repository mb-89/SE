"""SE's home from the checkout's origin (`scripts/se_home.py`): the forms it reads, the fixed answer
for every other form, and the settings it derives. git runs behind the door's fake."""

from __future__ import annotations

from pathlib import Path

import pytest

import fake_git
import git_door
import se_home
from se_home import Home


@pytest.mark.parametrize("url", [
    "https://example.com/alice/project",
    "https://example.com/alice/project.git",
    "https://example.com/alice/project/",
    "https://alice:token@example.com/alice/project.git",
    "https://x-access-token@example.com:443/alice/project",
    "ssh://git@example.com/alice/project.git",
    "ssh://git@example.com:2222/alice/project",
    "git@example.com:alice/project.git",
    "example.com:alice/project",
])
def test_https_and_ssh_origins_name_the_home_without_credentials(url: str) -> None:
    home = se_home.parse(url)

    assert home == Home("example.com", "alice", "project")
    assert home.url == "https://example.com/alice/project"
    assert home.tracker == "alice/project"


@pytest.mark.parametrize("url", [
    "http://local_proxy@127.0.0.1:41231/git/alice/project",
    "http://example.com/alice/project",
    "https://example.com/alice",
    "https://example.com/group/alice/project",
    "file:///srv/alice/project.git",
    "/srv/alice/project.git",
    "C:\\work\\project",
    "",
])
def test_every_other_form_has_no_home(url: str) -> None:
    assert se_home.parse(url) is None


def test_the_docs_url_is_the_pages_site_of_a_github_home_only() -> None:
    assert Home("github.com", "Alice", "project").docs_url == "https://alice.github.io/project/"
    assert Home("example.com", "alice", "project").docs_url == ""


def test_a_bare_name_lies_beside_the_home_and_a_longer_one_stays_absolute() -> None:
    home = Home("example.com", "alice", "project")

    assert home.named("obs") == "example.com/alice/obs"
    assert home.named("bob/tool") == "example.com/bob/tool"
    assert home.named("git.example.org/bob/tool") == "git.example.org/bob/tool"


@pytest.mark.parametrize(("origin", "want"), [
    ("https://example.com/alice/project", "https://example.com/alice/obs.git"),
    ("https://example.com/alice/project.git", "https://example.com/alice/obs.git"),
    ("git@example.com:alice/project.git", "git@example.com:alice/obs.git"),
    ("http://local_proxy@127.0.0.1:41231/git/alice/project", "http://local_proxy@127.0.0.1:41231/git/alice/obs.git"),
    ("/srv/alice/project", "/srv/alice/obs.git"),
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
