"""`se new app` (docs/applications.md "New application"): an application from kern's template at SE's kern pin.

These tests build no Go: they create applications from a small SE with a small kern, its clone at
the pin (`se_modules.kern_dir`), in a temporary directory. The application's own test run, which builds the core, is the suite beside,
`tests/beside_new_app.py` (se.toml `[tests.beside.new-app]`).
"""

from __future__ import annotations

import os
from pathlib import Path
import tomllib

import pytest

import git_door
import fake_git as git_fake
import se
import se_home
import se_modules
import se_new
import se_workflows

PROJECT = Path(__file__).resolve().parents[1]

TEMPLATE = {
    "README.md": "# app\n\nA bare application; `se new app <name> --path <dir>` copies it.\n",
    "go.mod": ("module example.com/app\n\ngo 1.24.7\n\nrequire kern v0.0.1\n\n"
               "// The template builds against the kern one folder up, in kern's repository.\n"
               "replace kern => ../\n"),
    "se.toml": '[project]\nidentity = "<name> <name>"\n\n[modules.kern]\nurl = "../kern.git"\ngo = true\n',
    ".gitignore": ".venv/\n.se/.runtime/\n",
    "cmd/app/main.go": 'package main\n\nfunc main() { run("app") } // happy apps stay\n',
    ".github/workflows/check.yml": "jobs:\n  check:\n    uses: ./.github/workflows/kern-battery.yml\n",
    # The generic pair, as SE's root holds it (des-016).
    **{name: (PROJECT / name).read_text(encoding="utf-8") for name in ("RUNME.sh", "RUNME.ps1")},
}
# The battery the template's CI calls, as SE ships it (scripts/se_workflows.py).
BATTERY = ("name: kern-battery\non:\n  workflow_call:\njobs:\n  trust:\n    steps:\n"
           "      - uses: actions/checkout@v7\n        with:\n          repository: ${{ job.workflow_repository }}\n"
           "          ref: ${{ job.workflow_sha }}\n")
# The action the battery calls, as SE ships it.
KERN_AT_PIN = "name: kern at the pin\nruns:\n  using: composite\n  steps: []\n"


def git(cwd: Path, *args: str) -> str:
    done = git_door.run(*args, cwd=cwd)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def fake_git(fake_git_door):
    """Every repository here, the small SE's and the new application's, is in the fake git."""
    return fake_git_door


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No machine-local public_identity: the identity is the SE's se.toml's."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


# kern's own project files, which kern's repository holds beside its source; the application gets
# neither, only the template.
KERN_OWN = {".github/workflows/check.yml": "jobs: {}\n", "se.toml": "[tests]\ncommand = []\n",
            "se.lock": "", "AGENTS.md": "# kern\n", "pyproject.toml": "[project]\n", "uv.lock": "",
            ".gitignore": ".se/\n"}


def small_se(root: Path, version: str = "0.1.0", tag: bool = True, lock: bool = True) -> Path:
    """An SE that pins kern by components/go.mod's require kern v<version>, with kern's clone at
    its pin in .se/modules/kern, tagged v<version> where `tag` and its commit locked in se.lock
    where `lock`; a commit after the tag changes the template's README, which the pin leaves out."""
    git_fake.init(root, "-b", "main")
    write(root, {"se.toml": '[project]\nidentity = "alice <alice>"\n\n'
                            '[components.kern]\ngo = "components/go.mod"\n',
                 "components/go.mod": f"module se/components\n\nrequire kern {se_modules.go_version(version)}\n",
                 ".github/workflows/kern-battery.yml": BATTERY,
                 ".github/actions/kern-at-pin/action.yml": KERN_AT_PIN})
    git(root, "add", "-A")
    git(root, "-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-m", "se")
    kern = se_modules.kern_dir(root)
    git_fake.init(kern, "-b", "main")
    write(kern, {"release.toml": f'version = "{version}"\ndownload = "releases/download/v{{version}}"\n',
                 "go.mod": "module kern\n\ngo 1.24.7\n", "index/index.go": "package index\n", **KERN_OWN,
                 **{f"template/{name}": text for name, text in TEMPLATE.items()}})
    git(kern, "add", "-A")
    git(kern, "-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-m", "kern")
    if tag:
        git(kern, "tag", f"v{version}")
    if lock:
        (root / "se.lock").write_text(se_modules.lock_text({"kern": (version, git(kern, "rev-parse", "HEAD"))}),
                                      encoding="utf-8", newline="\n")
    write(kern, {"template/README.md": "# app\n\nchanged after the release\n"})
    git(kern, "-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-am", "later")
    return root


def test_the_application_comes_from_kerns_template_at_the_pin_with_its_name_and_pins_ses_kern(
        tmp_path: Path, home: None, capsys) -> None:
    source = small_se(tmp_path / "se")
    git(source, "remote", "add", "origin", "https://github.com/alice/se.git")
    app = tmp_path / "apps" / "ledger"
    lines = se_new.create("ledger", app, source)
    assert lines[0].startswith(f"se new app: ledger created in {app} from kern's template at v0.1.0 (")
    assert (app / "README.md").read_text() == (
        "# ledger\n\nA bare application; `se new app <name> --path <dir>` copies it.\n")
    assert (app / "cmd" / "ledger" / "main.go").read_text() == (
        'package main\n\nfunc main() { run("ledger") } // happy apps stay\n')
    assert not (app / "cmd" / "app").exists()
    # It pins the kern SE pins and carries none: go.mod requires it and replaces it by its clone.
    go_mod = (app / "go.mod").read_text()
    assert go_mod.startswith("module example.com/ledger\n") and "require kern v0.1.0\n" in go_mod
    assert go_mod.endswith("// there (se.toml [components.kern]).\nreplace kern => ./.se/modules/kern\n")
    assert "se_modules.py sync kern" in go_mod
    assert "=> ../" not in go_mod and "one folder up" not in go_mod
    assert not (app / "kern").exists(), "no copy of kern's source"
    assert not (app / "index").exists() and not (app / "release.toml").exists(), "only the template"
    assert not (app / "AGENTS.md").exists(), "kern's own project files stay in kern's repository"
    settings = tomllib.loads((app / "se.toml").read_text())
    assert settings["components"]["kern"] == {"go": True} and "modules" not in settings, "se 6's table, found by name"
    assert (app / "se.lock").read_text() == (source / "se.lock").read_text(), "SE's kern lock line"
    # SE's clone at the pin, beside it and ignored, so it builds before it has an origin.
    kern = se_modules.kern_dir(app)
    pin = git(se_modules.kern_dir(source), "rev-parse", "v0.1.0^{commit}")
    assert git(kern, "rev-parse", "HEAD") == pin and (kern / "template" / "go.mod").is_file()
    assert (kern / "template" / "README.md").read_text() == TEMPLATE["README.md"], "the pin, not the clone's later commit"
    assert (app / ".gitignore").read_text().splitlines()[-1] == ".se/modules/"
    assert git(app, "check-ignore", ".se/modules/kern") == ".se/modules/kern"
    assert lines[1] == (f"kern 0.1.0 placed in {kern}, which git ignores; run uv run python "
                        "<se>/scripts/se_modules.py sync kern there to keep it at the pin")
    tracked = git(app, "ls-files").splitlines()
    assert not [name for name in tracked if name.startswith(("kern/", ".se/"))], tracked
    # Once it has an origin, its clone is at the pin, and sync keeps it there without searching:
    # a clone that holds the locked commit is used as it is (se_modules.py's finder).
    git(app, "remote", "add", "origin", "https://github.com/alice/ledger.git")
    assert se_modules.main(["--root", str(app), "status", "kern"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].endswith(": at pin")
    assert se_modules.main(["--root", str(app), "sync", "kern"]) == 0
    assert git(kern, "rev-parse", "HEAD") == pin
    assert 'identity = "alice <alice>"' in (app / "se.toml").read_text()
    # The generic pair, byte for byte SE's, RUNME.sh executable.
    for name in ("RUNME.sh", "RUNME.ps1"):
        expected = (PROJECT / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert (app / name).read_bytes() == expected, name
    assert os.access(app / "RUNME.sh", os.X_OK) or os.name == "nt"
    # Its CI calls the battery's copy beside it, at the SE it was made from, reaching SE beside it.
    assert "uses: ./.github/workflows/kern-battery.yml" in (app / ".github" / "workflows" / "check.yml").read_text()
    pin = git(source, "rev-parse", "HEAD^{commit}")
    battery = (app / ".github" / "workflows" / "kern-battery.yml").read_text()
    assert battery.startswith("# Code generated by se_workflows.py write from SE's "
                              f".github/workflows/kern-battery.yml at {pin} of "
                              "${{ github.repository_owner }}/se. DO NOT EDIT.\n")
    assert f"          repository: ${{{{ github.repository_owner }}}}/se\n          ref: {pin}\n" in battery
    assert "alice" not in battery and "job.workflow" not in battery
    action = (app / ".github" / "actions" / "kern-at-pin" / "action.yml").read_text()
    assert action == se_workflows.generate(KERN_AT_PIN, ".github/actions/kern-at-pin/action.yml", pin,
                                           "${{ github.repository_owner }}/se"), "the action the battery calls"
    # One commit on main, as the project identity, and nothing left over.
    assert git(app, "log", "--format=%an <%ae>|%cn <%ce>|%s") == (
        "alice <alice>|alice <alice>|Start ledger, a bare application on kern 0.1.0")
    assert git(app, "branch", "--show-current") == "main" and git(app, "status", "--porcelain") == ""


def test_an_application_on_kern_2_requires_it_as_go_spells_a_major_above_1(tmp_path: Path, home: None) -> None:
    source = small_se(tmp_path / "se", version="2.1.0")
    app = tmp_path / "apps" / "ledger"
    lines = se_new.create("ledger", app, source)
    assert "from kern's template at v2.1.0 (" in lines[0]
    assert "require kern v2.1.0+incompatible\n" in (app / "go.mod").read_text()
    assert se_modules.kern_pin(app)[0] == "2.1.0"


def test_the_owners_github_step_is_one_line_and_the_command_touches_no_remote(tmp_path: Path, home: None) -> None:
    source = small_se(tmp_path / "se")
    git(source, "remote", "add", "origin", "git@github.com:alice/se.git")
    app = tmp_path / "ledger"
    step = se_new.create("ledger", app, source)[-1]
    assert step == (f'Owner\'s step: create the GitHub repository alice/ledger, empty, with a ruleset on main '
                    f'that requires the check "check / battery", then run: git -C {app} remote add origin '
                    f"https://github.com/alice/ledger.git && git -C {app} push -u origin main")
    assert "\n" not in step
    assert git(app, "remote") == "", "creating the repository and its first push stay the owner's"


def test_a_pin_without_its_tag_is_refused_naming_the_sync(tmp_path: Path, home: None) -> None:
    source = small_se(tmp_path / "se", version="0.2.0", tag=False)
    app = tmp_path / "ledger"
    with pytest.raises(se_new.NewError, match=r"has no tag v0\.2\.0: run uv run python scripts/se_modules\.py sync kern"):
        se_new.create("ledger", app, source)
    assert not (app / "README.md").exists()


def test_a_lock_that_is_missing_or_off_the_pins_tag_is_refused_naming_the_sync(tmp_path: Path, home: None) -> None:
    """The application locks the commit SE's se.lock locks, which must be the pin's tag's."""
    source = small_se(tmp_path / "se", lock=False)
    with pytest.raises(se_new.NewError, match=r"se\.lock locks no kern, but the pin is kern 0\.1\.0: run uv run "
                                              r"python scripts/se_modules\.py sync kern in "):
        se_new.create("ledger", tmp_path / "a", source)
    later = git(se_modules.kern_dir(source), "rev-parse", "HEAD")
    (source / "se.lock").write_text(se_modules.lock_text({"kern": ("0.1.0", later)}), encoding="utf-8", newline="\n")
    with pytest.raises(se_new.NewError, match=rf"locks kern 0\.1\.0 at {later[:12]}, but its tag v0\.1\.0 is "):
        se_new.create("ledger", tmp_path / "b", source)
    (source / "se.lock").write_text(se_modules.lock_text({"kern": ("0.0.9", later)}), encoding="utf-8", newline="\n")
    with pytest.raises(se_new.NewError, match=r"se\.lock locks kern 0\.0\.9, but the pin is kern 0\.1\.0"):
        se_new.create("ledger", tmp_path / "c", source)
    assert not any((tmp_path / name).exists() for name in "abc"), "refused before anything is written"


def test_without_an_origin_on_github_the_owner_is_a_placeholder(tmp_path: Path, home: None) -> None:
    lines = se_new.create("ledger", tmp_path / "ledger", small_se(tmp_path / "se"))
    assert "<owner>/ledger" in lines[-1], "no origin on github.com names no owner"


@pytest.mark.parametrize("name", ["Ledger", "9lives", "my_app", ""])
def test_a_name_that_is_no_application_name_is_refused(tmp_path: Path, home: None, name: str) -> None:
    with pytest.raises(se_new.NewError, match="is no application name"):
        se_new.create(name, tmp_path / "x", small_se(tmp_path / "se"))
    assert not (tmp_path / "x").exists()


def test_a_folder_that_is_not_empty_is_refused(tmp_path: Path, home: None, capsys) -> None:
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "notes.md").write_text("mine\n")
    assert se.main(["new", "app", "ledger", "--path", str(tmp_path / "taken")]) == 1
    assert capsys.readouterr().err == (
        f"se new app: {tmp_path / 'taken'} exists and is not empty: name a new or empty folder with --path\n")
    assert sorted(p.name for p in (tmp_path / "taken").iterdir()) == ["notes.md"]


def test_kerns_template_holds_what_the_command_fills_in() -> None:
    """The real template, as it stands: what create() replaces is there, so its next release still
    makes applications (the release at the pin is held by the suite beside)."""
    template = se_modules.kern_dir(PROJECT) / "template"  # kern at its pin (tests/conftest.py)
    assert se_new.KERN_REPLACE.search((template / "go.mod").read_text(encoding="utf-8"))
    assert se_new.KERN_REQUIRE.search((template / "go.mod").read_text(encoding="utf-8"))
    settings = (template / "se.toml").read_text(encoding="utf-8")
    assert se_new.TEMPLATE_IDENTITY in settings
    assert se_new.KERN_TABLE in settings or se_new.TEMPLATE_KERN_TABLE.search(settings), "its kern pin"
    assert (template / "cmd" / "app" / "main.go").is_file()


def pinned(root: Path, require: str = "1.2.3", download: str | None = "releases/download/v{version}") -> Path:
    """`root` pinning kern by its go.mod's require, with the clone's release.toml naming `download`."""
    write(root, {"se.toml": '[components.kern]\ngo = true\n',
                 "go.mod": f"module app\n\nrequire kern v{require}\n",
                 ".se/modules/kern/release.toml": 'version = "9.9.9"\n'
                 + (f'download = "{download}"\n' if download else "")})
    return root


def test_the_pin_is_the_version_go_mod_requires_and_the_tag_the_clones_release_toml_names(tmp_path: Path) -> None:
    assert se_modules.kern_pin(PROJECT) == (se_modules.kern_pin(PROJECT)[0], f"v{se_modules.kern_pin(PROJECT)[0]}")
    assert se_modules.kern_pin(pinned(tmp_path / "a")) == ("1.2.3", "v1.2.3"), "the require, not the clone's version"
    with pytest.raises(se_modules.ModuleError, match=r"not vMAJOR\.MINOR\.PATCH"):
        se_modules.kern_pin(pinned(tmp_path / "b", require="1.2"))
    with pytest.raises(se_modules.ModuleError, match=r"no \[components\.kern\] with go"):
        se_modules.kern_pin(tmp_path / "none")
    (tmp_path / "a" / ".se" / "modules" / "kern" / "release.toml").unlink()
    with pytest.raises(se_modules.ModuleError, match="kern is not placed; run uv run python scripts/se_modules.py sync kern"):
        se_modules.kern_pin(tmp_path / "a")


def test_kern_pin_prints_the_version_and_where_its_release_is_published(tmp_path, capsys):
    """bootstrap.sh reads the pin through this one reader (docs/start.md "Kern")."""
    root = pinned(tmp_path, download="https://example.com/releases/download/v{version}")
    assert se_modules.main(["--root", str(root), "kern-pin"]) == 0
    assert capsys.readouterr().out == "1.2.3 https://example.com/releases/download/v1.2.3\n"
    pinned(tmp_path, download=None)
    assert se_modules.main(["--root", str(root), "kern-pin"]) == 1
    assert "download names no URL" in capsys.readouterr().err


def test_app_binary_is_ses_own_binary_where_se_toml_names_one(monkeypatch) -> None:
    """bootstrap.sh reads the application binary through this one reader: SE's is the `se` binary,
    kern's core plus SE's Go components (components/release.toml), published under the home the
    checkout's origin names (se_home.py)."""
    monkeypatch.setattr(se_modules.se_home, "find", lambda root: se_home.Home("example.com", "alice", "project"))
    b = se_modules.app_binary(PROJECT)
    assert (b.name, b.build_dir, b.package) == ("se", "components", "./cmd/se")
    release = tomllib.loads((PROJECT / "components" / "release.toml").read_text(encoding="utf-8"))
    assert "://" not in release["download"], "components/release.toml names no home"
    assert b.download == "https://example.com/alice/project/" + release["download"].format(version=b.version)
    assert b.download.endswith(f"/releases/download/se-v{b.version}")


def test_a_download_path_lies_under_origins_home_and_without_one_there_is_none(
        tmp_path: Path, monkeypatch, capsys) -> None:
    """A release.toml's download path resolves under the home origin names; where origin names
    none, app-binary answers `-` and the start builds the binary from its folder."""
    pinned(tmp_path, require="0.3.0")
    write(tmp_path, {"se.toml": '[binary]\nrelease = "components/release.toml"\n\n'
                                '[components.kern]\ngo = true\n',
                     "components/release.toml": 'version = "2.0.0"\ndownload = "releases/download/app-v{version}"\n'
                     'binary = "app"\npackage = "./cmd/app"\n'})
    kern = se_modules.kern_dir(tmp_path)
    # kern's release lies under the home its clone's origin names, kern's own repository.
    monkeypatch.setattr(se_modules.se_home, "find", lambda root: se_home.Home(
        "example.com", "alice", "kern" if root == kern else "project"))
    assert se_modules.app_binary(tmp_path).download == "https://example.com/alice/project/releases/download/app-v2.0.0"
    assert se_modules.kern_download(tmp_path) == "https://example.com/alice/kern/releases/download/v0.3.0"
    monkeypatch.setattr(se_modules.se_home, "find", lambda root: None)
    assert se_modules.app_binary(tmp_path).download == ""
    assert se_modules.main(["--root", str(tmp_path), "app-binary"]) == 0
    assert capsys.readouterr().out == f"app 2.0.0 - components ./cmd/app {tmp_path.resolve().as_posix()}\n"
    assert se_modules.main(["--root", str(tmp_path), "kern-pin"]) == 0
    assert capsys.readouterr().out == "0.3.0 -\n"


def test_app_binary_falls_back_to_the_bare_kern_without_a_binary_section(tmp_path: Path) -> None:
    """An application with no Go components sets no [binary] and runs the bare kern."""
    pinned(tmp_path, require="0.3.0", download="https://example.com/alice/kern/releases/download/v{version}")
    b = se_modules.app_binary(tmp_path)
    assert (b.name, b.version, b.build_dir, b.package) == ("kern", "0.3.0", ".se/modules/kern", "./cmd/kern")
    assert b.download == "https://example.com/alice/kern/releases/download/v0.3.0"


def test_app_binary_refuses_a_binary_release_that_cannot_build(tmp_path: Path) -> None:
    write(tmp_path, {"se.toml": '[binary]\nrelease = "bin/release.toml"\n',
                     "bin/release.toml": 'version = "0.1.0"\ndownload = "https://x/releases/download/app-v{version}"\n'})
    with pytest.raises(se_modules.ModuleError, match="binary must name"):
        se_modules.app_binary(tmp_path)


def test_the_pins_come_from_the_project_where_it_is_ses_own_checkout(tmp_path) -> None:
    binary = "[binary]\nrelease = \"r.toml\"\n"
    se, own, other, plain = (tmp_path / name for name in ("se", "own", "other", "plain"))
    write(se, {".claude-plugin/plugin.json": '{"name": "se"}', "se.toml": binary})
    write(own, {".claude-plugin/plugin.json": '{"name": "se"}', "se.toml": binary})
    write(other, {".claude-plugin/plugin.json": '{"name": "app"}', "se.toml": binary})
    write(plain, {"se.toml": "[project]\n"})
    assert se_modules.app_root(se, own) == own
    assert [se_modules.app_root(se, p) for p in (other, plain, None, se)] == [se] * 4


def test_app_binary_prints_every_field_bootstrap_reads(tmp_path, capsys) -> None:
    write(tmp_path, {"se.toml": '[binary]\nrelease = "components/release.toml"\n',
                     "components/release.toml": 'version = "2.0.0"\n'
                     'download = "https://github.com/o/n/releases/download/app-v{version}"\n'
                     'binary = "app"\npackage = "./cmd/app"\n'})
    assert se_modules.main(["--root", str(tmp_path), "app-binary"]) == 0
    assert capsys.readouterr().out == (
        f"app 2.0.0 https://github.com/o/n/releases/download/app-v2.0.0 components ./cmd/app "
        f"{tmp_path.resolve().as_posix()}\n")
