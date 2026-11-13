"""`se new app` (README "New application"): an application from kern's template at SE's kern pin.

These tests build no Go: they create applications from a small SE with a small kern in a temporary
directory. The application's own test run, which builds the core, is the suite beside,
`tests/beside_new_app.py` (se.toml `[tests.beside.new-app]`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import quiet_git
import se
import se_modules
import se_new

PROJECT = Path(__file__).resolve().parents[1]

TEMPLATE = {
    "README.md": "# app\n\nA bare application; `se new app <name> --path <dir>` copies it.\n",
    "go.mod": ("module example.com/app\n\ngo 1.24.7\n\nrequire github.com/mb-89/kern v0.1.0\n\n"
               "// While kern is incubated in SE, the template builds against the kern beside it.\n"
               "replace github.com/mb-89/kern => ../\n"),
    "se.toml": '[project]\nidentity = "<name> <name>"\n\n[modules.kern]\ngo = true\n',
    "cmd/app/main.go": 'package main\n\nfunc main() { run("app") } // happy apps stay\n',
    ".github/workflows/check.yml": "jobs:\n  check:\n    uses: mb-89/SE/.github/workflows/kern-battery.yml@kern-v0.1.0\n",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No machine-local public_identity: the identity is the SE's se.toml's."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


def small_se(root: Path, version: str = "0.1.0", tag: bool = True) -> Path:
    """An SE with a small kern at `version`, tagged kern-v<version> where `tag`; a commit after the
    tag changes the template's README, which the pin leaves out."""
    quiet_git.init(root, "-b", "main")
    write(root, {"se.toml": '[project]\nidentity = "alice <alice>"\n',
                 "kern/release.toml": f'version = "{version}"\n',
                 "kern/go.mod": "module github.com/mb-89/kern\n\ngo 1.24.7\n",
                 "kern/index/index.go": "package index\n",
                 **{f"kern/template/{name}": text for name, text in TEMPLATE.items()}})
    git(root, "add", "-A")
    git(root, "-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-m", "kern")
    if tag:
        git(root, "tag", f"kern-v{version}")
    write(root, {"kern/template/README.md": "# app\n\nchanged after the release\n"})
    git(root, "-c", "user.name=alice", "-c", "user.email=alice", "commit", "-q", "-am", "later")
    return root


def test_the_application_comes_from_kerns_template_at_the_pin_with_its_name_and_kern_beside_it(
        tmp_path: Path, home: None) -> None:
    source = small_se(tmp_path / "se")
    git(source, "remote", "add", "origin", "https://github.com/alice/se.git")
    app = tmp_path / "apps" / "ledger"
    lines = se_new.create("ledger", app, source)
    assert lines[0].startswith(f"se new app: ledger created in {app} from kern's template at kern-v0.1.0 (")
    assert (app / "README.md").read_text() == (
        "# ledger\n\nA bare application; `se new app <name> --path <dir>` copies it.\n")
    assert (app / "cmd" / "ledger" / "main.go").read_text() == (
        'package main\n\nfunc main() { run("ledger") } // happy apps stay\n')
    assert not (app / "cmd" / "app").exists()
    go_mod = (app / "go.mod").read_text()
    assert go_mod.startswith("module example.com/ledger\n") and "require github.com/mb-89/kern v0.1.0\n" in go_mod
    assert go_mod.endswith(se_new.APP_REPLACE) and "=> ../" not in go_mod and "beside it" not in go_mod
    assert (app / "kern" / "index" / "index.go").is_file() and (app / "kern" / "release.toml").is_file()
    assert not (app / "kern" / "template").exists(), "kern's source at the pin, without its template"
    assert 'identity = "alice <alice>"' in (app / "se.toml").read_text()
    assert "@kern-v0.1.0" in (app / ".github" / "workflows" / "check.yml").read_text()
    # One commit on main, as the project identity, and nothing left over.
    assert git(app, "log", "--format=%an <%ae>|%cn <%ce>|%s") == (
        "alice <alice>|alice <alice>|Start ledger, a bare application on kern 0.1.0")
    assert git(app, "branch", "--show-current") == "main" and git(app, "status", "--porcelain") == ""


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


def test_an_unreleased_version_comes_from_head_and_says_so(tmp_path: Path, home: None) -> None:
    source = small_se(tmp_path / "se", version="0.2.0", tag=False)
    app = tmp_path / "ledger"
    lines = se_new.create("ledger", app, source)
    head = git(source, "rev-parse", "--short=12", "HEAD")
    assert lines[0] == f"kern-v0.2.0 is not released yet: kern and its template come from {source}'s HEAD, {head}"
    assert (app / "README.md").read_text() == "# ledger\n\nchanged after the release\n"
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
    template = PROJECT / "kern" / "template"
    assert se_new.KERN_REPLACE.search((template / "go.mod").read_text(encoding="utf-8"))
    assert se_new.TEMPLATE_IDENTITY in (template / "se.toml").read_text(encoding="utf-8")
    assert (template / "cmd" / "app" / "main.go").is_file()


def test_the_pin_is_kerns_release_version_and_its_tag(tmp_path: Path) -> None:
    assert se_modules.kern_pin(PROJECT)[1] == f"kern-v{se_modules.kern_pin(PROJECT)[0]}"
    write(tmp_path, {"kern/release.toml": 'version = "1.2"\n'})
    with pytest.raises(se_modules.ModuleError, match=r"version must be MAJOR\.MINOR\.PATCH"):
        se_modules.kern_pin(tmp_path)
    with pytest.raises(se_modules.ModuleError, match="incubates no kern"):
        se_modules.kern_pin(tmp_path / "none")
