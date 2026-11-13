"""The suite's fixture repositories hold still (tests/quiet_git.py): a lock file that git's background
maintenance creates and removes while the fixture copy runs does not fail the copy, and every
fixture repository has background maintenance switched off."""
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from quiet_git import quiet


def build_locked(tmp_path: Path) -> None:
    """A bare repository, quieted, whose objects/maintenance.lock git's maintenance holds."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    quiet(origin)
    (origin / "objects" / "maintenance.lock").write_text("", encoding="utf-8")


@pytest.fixture
def vanishing_locks(monkeypatch):
    """Every directory listing still names its lock files, which vanish right after it: as on the
    runner, where maintenance removed objects/maintenance.lock between the listing and its copy."""
    real = os.scandir

    @contextmanager
    def listing(path):
        with real(path) as iterator:
            entries = list(iterator)
        for entry in entries:
            if entry.name.endswith(".lock"):
                os.remove(entry.path)
        yield iter(entries)

    monkeypatch.setattr(os, "scandir", listing)


def test_the_fixture_copy_passes_while_a_lock_appears_and_vanishes(repositories, tmp_path,
                                                                   vanishing_locks):
    target = tmp_path / "copy"
    repositories(build_locked, target)
    assert (target / "origin.git" / "HEAD").is_file()
    assert not (target / "origin.git" / "objects" / "maintenance.lock").exists()


def test_a_plain_copy_fails_on_the_vanished_lock(tmp_path, vanishing_locks):
    """The fault the helper removes, so the test above proves the fix and not the platform."""
    build_locked(tmp_path / "template")
    with pytest.raises(shutil.Error, match="maintenance.lock"):
        shutil.copytree(tmp_path / "template", tmp_path / "copy", symlinks=True)


def test_a_quiet_repository_runs_no_background_maintenance(tmp_path):
    for repository, arguments in ((tmp_path / "bare.git", ["--bare"]), (tmp_path / "work", [])):
        subprocess.run(["git", "init", "-q", *arguments, str(repository)], check=True)
        quiet(repository)
        read = lambda key: subprocess.run(["git", "-C", str(repository), "config", key],  # noqa: E731
                                          capture_output=True, text=True, check=True).stdout.strip()
        assert (read("maintenance.auto"), read("gc.auto")) == ("false", "0")
