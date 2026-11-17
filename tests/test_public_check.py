"""Tests for scripts/public_check.py and se's hooks that run it. Leaky sample values are assembled
at runtime from fragments, so this file itself passes the check.

git is the door's fake behind a state file (`shared_fake_git`, tests/conftest.py), which the check,
the hooks and the setup scripts reach as child processes; the fake holds an se checkout at this
one's root at SE_HEAD, so a verdict names that commit. SE's own checkout is checked by
scripts/hygiene.py, a step of CI's `check` job."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import fake_git
import git_door
import hygiene

SE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SE_ROOT / "scripts" / "public_check.py"
SE_HEAD = "5e" * 20  # the commit of the se checkout the fake holds at SE_ROOT
BS = "\\"
AT = "@"

_spec = importlib.util.spec_from_file_location("public_check", SCRIPT)
public_check = importlib.util.module_from_spec(_spec)
sys.modules["public_check"] = public_check
_spec.loader.exec_module(public_check)

POSITIVE = {
    "user-profile-path": [
        "C:" + BS + "Users" + BS + "alice" + BS + "repo",
        "d:" + "/users/alice/repo",
        "C:" + BS * 2 + "Users" + BS * 2 + "alice",
        "/" + "home/alice/repo",
        "/" + "Users/alice/Documents",
    ],
    "email-address": [
        "alice" + AT + "corp.test",
        "Alice.Smith+x" + AT + "mail.corp.test",
        "alice" + AT + "github.com",
        "alice" + AT + "anthropic.com",
        "noreply" + AT + "mail.github.com",
    ],
    "enterprise-github-host": [
        "https://acme" + ".ghe" + ".com/org/repo",
        "git" + AT + "code.acme" + ".ghe" + ".com:org/repo",
    ],
    "unc-machine-name": [
        BS * 2 + "fileserver01" + BS + "share",
        '"' + BS * 4 + "fileserver01" + BS * 2 + 'share"',
    ],
}

NEGATIVE = {
    "user-profile-path": [
        "C:" + BS + "Users" + BS + "<name>" + BS + "repo",
        "C:" + BS + "Users" + BS + "%USERNAME%",
        "C:" + BS + "Users" + BS + "Public" + BS + "Documents",
        "/" + "home/<name>",
        "/" + "home/user/repo",
        "/" + "Users/{name}/x",
        "https://site.test/home/about",
    ],
    "email-address": [
        "12345+someone" + AT + "users.noreply.github.com",
        "noreply" + AT + "github.com",
        "noreply" + AT + "anthropic.com",
        "Claude <noreply" + AT + "anthropic.com>",
        "alice" + AT + "example.com",
        "bob" + AT + "mail.example.org",
        "git" + AT + "github.com:owner/repo",
        "package" + AT + "1.2.3",
    ],
    "enterprise-github-host": [
        "*" + ".ghe" + ".com",
        "github.com/org/repo",
    ],
    "unc-machine-name": [
        BS * 2 + "?" + BS + "C:" + BS + "long",
        BS * 2 + "." + BS + "pipe" + BS + "x",
        BS * 2 + "localhost" + BS + "c$",
        BS * 2 + "<server>" + BS + "share",
        "C:" + BS * 2 + "tools" + BS * 2 + "x",
        '"' + BS * 2 + 'n"',
        # JSON-escaped control characters and backslashes in source text, not UNC paths.
        '"%%' + BS * 2 + "nkept" + BS * 2 + 'n%%"',
        '"%%' + BS * 2 + "tkept" + BS * 2 + 't%%"',
        '"%%' + BS * 2 + "rkept" + BS * 2 + 'r%%"',
        '"%%' + BS * 4 + "kept" + BS * 4 + '%%"',
    ],
}


def labels(text: str) -> set[str]:
    return {label for _, _, label in public_check.find(text, public_check.GENERIC_PATTERNS)}


@pytest.mark.parametrize(
    ("label", "text"), [(label, text) for label, texts in POSITIVE.items() for text in texts]
)
def test_generic_pattern_hits(label: str, text: str) -> None:
    assert label in labels(f"prefix {text} suffix")


@pytest.mark.parametrize(
    ("label", "text"), [(label, text) for label, texts in NEGATIVE.items() for text in texts]
)
def test_generic_pattern_ignores(label: str, text: str) -> None:
    assert label not in labels(f"prefix {text} suffix")


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`git -C repo <args>` through the door; a refusal fails the test, naming git's answer."""
    result = git_door.run(*args, root=repo, env=env)
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr.strip()}"
    return result


def se_checkout(state: fake_git.StateFile) -> None:
    """The se checkout the check runs from, as the fake holds it: SE_ROOT at commit SE_HEAD."""
    with state.edit() as fake:
        moment = datetime.now(timezone.utc)
        fake.commits[SE_HEAD] = fake_git.Commit(fake.store_tree({}), (), "se\n", ("alice", "alice"),
                                                ("alice", "alice"), moment, moment)
        fake.repositories[SE_ROOT] = fake_git.Repository(SE_ROOT, False, head=SE_HEAD)
        fake.repositories[SE_ROOT].config["remote.origin.url"] = "https://github.com/alice/SE"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared_fake_git: fake_git.StateFile) -> Path:
    """A repository with a generic identity and an empty, ignored local list, so a run is a full
    check; checked without the machine's ~/.se/local.toml or a machine-level list."""
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "home"))
    monkeypatch.delenv(public_check.MACHINE_ENV, raising=False)
    se_checkout(shared_fake_git)
    path = tmp_path / "repo"
    path.mkdir()
    fake_git.init(path, "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test" + AT + "example.com")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (path / ".git" / "info").mkdir(exist_ok=True)
    (path / ".git" / "info" / "exclude").write_text(f"{public_check.LOCAL_FILE}\n",
                                                    encoding="utf-8")
    (path / public_check.LOCAL_FILE).write_text("# no terms\n", encoding="utf-8")
    return path


@pytest.fixture
def local(repo: Path) -> Path:
    """The repository's local list."""
    return repo / public_check.LOCAL_FILE


def commit(repo: Path, files: dict[str, str | bytes], message: str = "Add files",
           *config: str) -> None:
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    configs = [arg for item in config for arg in ("-c", item)]
    git(repo, *configs, "commit", "-q", "-m", message)


def run_check(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """`public_check.py <args>` in this process, from `cwd`, under the test's environment, its git
    the door's fake (`shared_fake_git`, the state file a process run reads): stdout and stderr
    apart, and the exit code as Python would exit with what main returns or raises
    (test_the_check_answers_alike_in_its_own_process holds it to the process)."""
    argv = [sys.executable, str(SCRIPT), *args]
    out, err = io.StringIO(), io.StringIO()
    before = os.getcwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = public_check.main(list(args))
            except SystemExit as exit:
                code = exit.code
            if code is None:
                code = 0
            elif not isinstance(code, int):
                print(code, file=sys.stderr)
                code = 1
    finally:
        os.chdir(before)
    return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())


def test_the_check_answers_alike_in_its_own_process(repo: Path) -> None:
    """run_check answers as `python scripts/public_check.py` run as a process does, clean and with
    a hit: the same exit code and stdout. stderr is not compared: argparse names the program after
    sys.argv[0], which is pytest here, and no test of the check reads its stderr."""
    commit(repo, {"README.md": "clean\n"})
    for planted, expected in ((False, 0), (True, 1)):
        if planted:
            commit(repo, {"leak.txt": "/" + "home/alice/repo\n"})
        process = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                 cwd=repo, check=False)
        in_test = run_check(cwd=repo)
        assert process.returncode == expected, process.stdout + process.stderr
        assert (in_test.returncode, in_test.stdout) == (process.returncode, process.stdout)


def test_clean_repository_passes(repo: Path) -> None:
    commit(repo, {"README.md": "Paths look like C:" + BS + "Users" + BS + "<name>.\n"})
    result = run_check(cwd=repo)
    assert result.returncode == 0, result.stdout
    assert f"public-check: passed (1 files, 1 commits, se {SE_HEAD[:7]})" in result.stdout
    assert "warning" not in result.stdout


def test_a_check_at_the_pinned_se_passes(repo: Path) -> None:
    commit(repo, {"se.toml": f'[modules.se]\nurl = "https://example.com/se.git"\nref = "{SE_HEAD}"\n'})
    result = run_check(cwd=repo)
    assert result.returncode == 0, result.stdout


def test_a_stale_se_refuses_naming_both_commits_and_the_remedy(repo: Path) -> None:
    pin = "0123456" + "0" * 33
    commit(repo, {"se.toml": f'[modules.se]\nurl = "https://example.com/se.git"\nref = "{pin}"\n'})
    result = run_check(cwd=repo)
    assert result.returncode == 2, result.stdout
    assert (f"public-check: error (se {SE_HEAD[:7]}): se.toml pins se at 0123456, but this check "
            f"runs se {SE_HEAD[:7]}; bring the se clone to the pin") in result.stdout
    assert "passed" not in result.stdout


SE_VERSION = tomllib.loads((SE_ROOT / "se.toml").read_text(encoding="utf-8"))["project"]["version"]
SE_MAJOR, SE_MINOR, _ = (int(part) for part in SE_VERSION.split("."))


def range_manifest(text: str) -> str:
    return f'[modules.se]\nurl = "https://example.com/se.git"\nversion = "{text}"\n'


def test_an_se_within_the_pinned_version_range_passes_whatever_its_commit(repo: Path) -> None:
    stale = "0123456" + "0" * 33
    commit(repo, {"se.toml": range_manifest(f"~{SE_MAJOR}.{SE_MINOR}"),
                  "se.lock": f'[modules.se]\nversion = "{SE_VERSION}"\nref = "{stale}"\n'})
    result = run_check(cwd=repo)
    assert result.returncode == 0, result.stdout


def test_an_se_outside_the_pinned_version_range_refuses_naming_both_and_the_remedy(repo: Path) -> None:
    commit(repo, {"se.toml": range_manifest(f"^{SE_MAJOR + 1}.0")})
    result = run_check(cwd=repo)
    assert result.returncode == 2, result.stdout
    assert (f"se.toml pins se at version '^{SE_MAJOR + 1}.0', but this check runs se {SE_VERSION}; "
            "bring the se clone into the range (scripts/se_modules.py sync) or widen the range"
            ) in result.stdout
    assert "passed" not in result.stdout


@pytest.mark.parametrize("project, found", [
    ("", "sets no version in its se.toml"),
    ('[project]\nversion = "one"\n', "is not MAJOR.MINOR.PATCH"),
])
def test_an_se_whose_version_cannot_be_read_refuses_a_version_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str, found: str,
) -> None:
    se = tmp_path / "se"
    se.mkdir()
    (se / "se.toml").write_text(project, encoding="utf-8")
    checked = tmp_path / "checked"
    checked.mkdir()
    (checked / "se.toml").write_text(range_manifest("^1.0"), encoding="utf-8")
    monkeypatch.setattr(public_check, "SE_ROOT", se)
    with pytest.raises(public_check.SetupError) as error:
        public_check.check_se_version(checked, SE_HEAD)
    assert "se.toml pins se at version '^1.0', but" in str(error.value)
    assert found in str(error.value)
    assert "bring the se clone into the range" in str(error.value)


def test_a_malformed_version_range_refuses(repo: Path) -> None:
    commit(repo, {"se.toml": range_manifest("latest")})
    result = run_check(cwd=repo)
    assert result.returncode == 2 and "version must be a semver range" in result.stdout


def test_file_hit_names_location_and_label_only(repo: Path) -> None:
    secret_path = "/" + "home/alice/project"
    commit(repo, {"notes.txt": "first\nsee " + secret_path + "\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "notes.txt:2:5: user-profile-path" in result.stdout
    assert "alice" not in result.stdout


def test_file_name_hit(repo: Path) -> None:
    commit(repo, {"alice" + AT + "corp.test.txt": "clean\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "(file name): email-address" in result.stdout


def test_binary_file_hit(repo: Path) -> None:
    payload = ("C:" + BS + "Users" + BS + "alice").encode("utf-16-le")
    commit(repo, {"image.bin": b"\x89PNG\x00\x01\n" + payload + b"\x00\xff"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "image.bin:2:1 (binary): user-profile-path" in result.stdout


def test_a_public_term_found(repo: Path) -> None:
    commit(repo, {"notes.md": "Mirror at https://acme" + ".ghe" + ".com/x\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "notes.md:1:19: enterprise-github-host" in result.stdout


def test_the_public_list_is_the_data_file_beside_the_script() -> None:
    data = tomllib.loads(public_check.TERMS_FILE.read_text(encoding="utf-8"))
    assert public_check.TERMS_FILE.parent == SCRIPT.parent
    assert [p.label for p in public_check.GENERIC_PATTERNS] == [t["label"] for t in data["term"]]
    assert [p.regex.pattern for p in public_check.GENERIC_PATTERNS] == [
        t["regex"] for t in data["term"]]


def test_a_local_term_found_without_printing_the_term(repo: Path, local: Path) -> None:
    local.write_text("# kept private\n\nexample-secret\\w*\n", encoding="utf-8")
    commit(repo, {"src/app.py": "print('built for Example-SecretCorp')\n"},
           "Port the Example-SecretCorp tool")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "src/app.py:1:18: local-term:3" in result.stdout
    assert "message:1: local-term:3" in result.stdout
    assert "secret" not in result.stdout.lower()


def test_paths_with_local_terms_are_redacted(repo: Path, local: Path) -> None:
    local.write_text("example-secret\\w*\n", encoding="utf-8")
    commit(repo, {"src/example-secretTools/app.py": "x = 1\nbuilt by example-secret\n",
                  "docs/alice" + AT + "corp.test.md": "/" + "home/alice\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert "src/<local-term:1>/app.py (file name): local-term:1" in lines
    assert "src/<local-term:1>/app.py:2:10: local-term:1" in lines
    assert "docs/<email-address>:1:1: user-profile-path" in lines
    assert "secret" not in result.stdout.lower()
    assert "alice" not in result.stdout


def test_a_local_override_silences_a_public_term(repo: Path, local: Path) -> None:
    local.write_text("off:email-address  # this source lists contact addresses by design\n",
                     encoding="utf-8")
    commit(repo, {"contacts.md": "alice" + AT + "corp.test\n", "home.md": "/" + "home/alice\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "email-address" not in result.stdout.replace("off locally: email-address", "")
    assert "home.md:1:1: user-profile-path" in result.stdout
    assert "public entries off locally: email-address" in result.stdout.splitlines()[-1]


@pytest.mark.parametrize(("line", "error"), [
    ("off:email-address\n", ".public-check.local:1: write '<regex>' or 'off:<public label>  # reason'"),
    ("off:no-such-label  # why\n", ".public-check.local:1: no public entry is labelled 'no-such-label'"),
    ("example-secret(\n", ".public-check.local:1 is not a valid regex"),
])
def test_a_malformed_local_list_is_a_setup_error(repo: Path, local: Path, line: str,
                                                 error: str) -> None:
    local.write_text(line, encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 2
    assert error in result.stdout
    assert "secret" not in result.stdout.lower()


@pytest.mark.parametrize("mode", [[], ["--staged"], ["--rev", "HEAD"]])
def test_a_tracked_local_list_is_refused(repo: Path, local: Path, mode: list[str]) -> None:
    commit(repo, {"README.md": "clean\n"})
    git(repo, "add", "-f", public_check.LOCAL_FILE)
    git(repo, "commit", "-q", "-m", "Track the local list")
    result = run_check("--repo", str(repo), *mode)
    assert result.returncode == 2
    assert (".public-check.local is tracked by git, but a local list is never checked in: run "
            "git rm --cached .public-check.local, then ignore it") in result.stdout


def test_a_local_list_tracked_only_in_the_checked_commit_is_refused(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    git(repo, "add", "-f", public_check.LOCAL_FILE)
    git(repo, "commit", "-q", "-m", "Track the local list")
    git(repo, "rm", "-q", "--cached", public_check.LOCAL_FILE)
    result = run_check("--repo", str(repo), "--rev", "HEAD")
    assert result.returncode == 2
    assert ".public-check.local is tracked by git" in result.stdout


@pytest.mark.parametrize("configure", ["default", "variable"])
def test_the_machine_list_is_refused_with_its_remedy(repo: Path, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     configure: str) -> None:
    if configure == "default":
        machine = tmp_path / "home" / ".se" / "private-terms.txt"
        machine.parent.mkdir(parents=True)
    else:
        machine = tmp_path / "elsewhere.txt"
        monkeypatch.setenv(public_check.MACHINE_ENV, str(machine))
    machine.write_text("example-secret\n", encoding="utf-8")
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 2
    assert "the machine-level term list" in result.stdout
    assert ("is retired: move its terms into <source>/.public-check.local, the local list at the "
            "root of each repository or vault that needs them") in result.stdout
    assert "secret" not in result.stdout.lower() and str(tmp_path) not in result.stdout


def test_the_variable_of_the_retired_cloud_list_is_no_source(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A made-up term, written apart so this file never holds it whole.
    term = "zorbl" + "quux"
    commit(repo, {"README.md": f"made at {term}\n"}, f"Port the {term} tool",
           f"user.name={term}")
    unset = run_check("--repo", str(repo))
    monkeypatch.setenv("SE_PUBLIC_CHECK_TERMS", f"{term}\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout
    assert (result.returncode, result.stdout, result.stderr) == (
        unset.returncode, unset.stdout, unset.stderr)


def test_missing_local_list_warns(repo: Path, local: Path) -> None:
    local.unlink()
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 0
    assert ("public-check: warning: no local list (.public-check.local); only the public list was "
            "checked") in result.stdout


def test_commit_message_hit(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"}, "Mirror of https://acme" + ".ghe" + ".com/x/y")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "message:1: enterprise-github-host" in result.stdout


def test_author_and_committer_identity_hits(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"}, "Add readme",
           "user.email=alice" + AT + "corp.test")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert " author: email-address" in result.stdout
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    env = {**os.environ, "GIT_COMMITTER_EMAIL": "bob" + AT + "corp.test"}
    git(repo, "commit", "-qam", "Change readme", env=env)
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 1
    assert result.stdout.splitlines()[0].endswith(" committer: email-address")


PROJECT_IDENTITY = '[project]\nidentity = "mb <mb>"\n'


def test_a_commit_not_yet_pushed_with_a_foreign_identity_is_refused_naming_the_remedy(
        repo: Path) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    commit(repo, {"README.md": "clean\n"}, "Add readme", "user.name=agent",
           "user.email=agent" + AT + "example.com")
    sha = git(repo, "rev-parse", "--short=12", "HEAD").stdout.strip()
    result = run_check("--repo", str(repo), "--range", "HEAD~1..HEAD")
    assert result.returncode == 1, result.stdout
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    assert [hit.split(":", 1)[0] for hit in hits] == [f"commit {sha} author", f"commit {sha} committer"]
    assert ("'agent <agent" + AT + "example.com>' is not the project identity 'mb <mb>'; set the "
            "project identity in the checkout (work_tickets.py sync") in hits[0]
    assert "git commit --amend --no-edit --reset-author" in hits[0]
    assert "remove them or add a reasoned entry" not in result.stdout
    # History already pushed stays as it is: a full check and the project's own commits pass.
    assert run_check("--repo", str(repo)).returncode == 0
    assert run_check("--repo", str(repo), "--range", "HEAD~1").returncode == 0


def test_a_foreign_committer_alone_is_refused_and_a_redacted_identity_names_no_person(
        repo: Path) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    (repo / "README.md").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "README.md")
    env = {**os.environ, "GIT_COMMITTER_EMAIL": "bob" + AT + "corp.test"}
    git(repo, "commit", "-qm", "Add readme", env=env)
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 1
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    assert len(hits) == 1 and " committer: foreign-identity " in hits[0]
    assert "corp.test" not in result.stdout


WEB_FLOW = {"GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply" + AT + "github.com"}


NOREPLY = "users.noreply.github.com"


FAST_FORWARD = '\n[integrate]\nlanding = "fast-forward"\n'


@pytest.mark.parametrize("origin, author, committer, squash, strict", [
    # GitHub's squash merge of a pull request into main, for the owning account: it passes while
    # landings are squash merges, and is foreign once they are the integrator's fast-forwards.
    ("https://github.com/alice/example.git", "Alice <123+alice" + AT + NOREPLY + ">", "web-flow",
     [], ["author", "committer"]),
    ("git" + AT + "github.com:Alice/example.git", "alice <alice" + AT + NOREPLY + ">", "web-flow",
     [], ["author", "committer"]),
    # The project identity as author with GitHub's committer: a commit made on GitHub.
    ("https://github.com/alice/example.git", "mb <mb>", "web-flow", [], ["committer"]),
    # Another account's noreply address stays foreign, as does the owner's off GitHub.
    ("https://github.com/alice/example.git", "Bob <456+bob" + AT + NOREPLY + ">", "web-flow",
     ["author"], ["author", "committer"]),
    ("https://github.com/alice/example.git", "Alice <alice" + AT + "example.com>", "web-flow",
     ["author"], ["author", "committer"]),
    ("https://github.com/alice/example.git", "Alice <123+alice" + AT + "noreply.github.com.example.com>",
     "web-flow", ["author"], ["author", "committer"]),
    ("https://github.com/alice/example.git", "Alice <123+alice" + AT + NOREPLY + ">", "author",
     ["author", "committer"], ["author", "committer"]),
    # Without an origin on github.com no account owns the repository.
    ("", "agent <agent>", "web-flow", ["author"], ["author", "committer"]),
    # The integrator's own landing commit: the project identity in both roles.
    ("https://github.com/alice/example.git", "mb <mb>", "author", [], []),
])
@pytest.mark.parametrize("landing", ["squash", "fast-forward"])
def test_a_commit_github_made_passes_the_gate_only_while_landings_are_squash_merges(
        repo: Path, origin: str, author: str, committer: str, squash: list[str],
        strict: list[str], landing: str) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY + (FAST_FORWARD if landing == "fast-forward" else "")})
    if origin:
        git(repo, "remote", "add", "origin", origin)
    (repo / "README.md").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "README.md")
    name, email = author[:-1].split(" <")
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           **(WEB_FLOW if committer == "web-flow" else
              {"GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email})}
    git(repo, "commit", "-qm", "Squash the topic", env=env)
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    refused = strict if landing == "fast-forward" else squash
    assert [hit.split(": ", 1)[0].rsplit(" ", 1)[1] for hit in hits] == refused, result.stdout
    assert result.returncode == (1 if refused else 0), result.stdout


def test_an_unknown_landing_setting_stops_the_gate(repo: Path) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY + '\n[integrate]\nlanding = "rebase"\n'})
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 2 and "[integrate] landing" in result.stdout, result.stdout


@pytest.mark.parametrize("address", [
    "alice" + AT + "corp.test",
    "123+mb" + AT + NOREPLY,
    "noreply" + AT + "github.com",
    "noreply" + AT + "anthropic.com",
    "someone" + AT + "example.com",
])
def test_a_message_with_any_address_fails_both_commit_gates_naming_no_address(
        repo: Path, tmp_path: Path, address: str) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    text = f"Land the topic\n\nReviewed with {address} and again {address}\n"
    commit(repo, {"README.md": "clean\n"}, text)
    sha = git(repo, "rev-parse", "--short=12", "HEAD").stdout.strip()
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    hits = [line for line in result.stdout.splitlines() if "message-address" in line]
    assert [hit.split(": ", 1)[0] for hit in hits] == [f"commit {sha} message:3"] * 2, result.stdout
    assert "no e-mail address" in hits[0] and "git commit --amend" in hits[0]
    assert address not in result.stdout
    assert result.returncode == 1
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(text, encoding="utf-8")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 1
    assert "commit message:3: message-address" in result.stdout
    # A full check leaves history already pushed to the public list alone.
    assert "message-address" not in run_check("--repo", str(repo)).stdout


def test_a_message_without_an_address_passes_the_gates(repo: Path, tmp_path: Path) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    commit(repo, {"README.md": "clean\n"},
           "Integrate fix/topic: load se" + AT + "se:work-model\n\nRelease: minor\n")
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 0, result.stdout


def test_without_a_project_identity_any_generic_identity_passes_the_gate(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 0, result.stdout


def test_identity_without_mail_domain_is_generic(repo: Path, tmp_path: Path) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"README.md": "clean\n"})
    assert "mb <mb>" in git(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("Change readme\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 0, result.stdout
    git(repo, "config", "user.email", "mb" + AT + "corp.test")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 1
    assert "commit author: email-address" in result.stdout


def test_staged_scan_reads_the_index(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    (repo / "README.md").write_text("/" + "home/alice\n", encoding="utf-8")
    git(repo, "add", "README.md")
    (repo / "README.md").write_text("clean again\n", encoding="utf-8")
    assert run_check("--repo", str(repo)).returncode == 0
    staged = run_check("--repo", str(repo), "--staged")
    assert staged.returncode == 1
    assert "README.md:1:1: user-profile-path" in staged.stdout
    assert f"(1 files, 0 commits, se {SE_HEAD[:7]})" in staged.stdout


def test_rev_scan_reads_the_commit_tree(repo: Path) -> None:
    commit(repo, {"a.txt": "/" + "home/alice\n"})
    commit(repo, {"a.txt": "clean\n"})
    result = run_check("--repo", str(repo), "--rev", "HEAD~1", "--no-history")
    assert result.returncode == 1
    assert "a.txt:1:1: user-profile-path" in result.stdout


def test_message_file_scan(repo: Path, tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("Fix it\n# comment " + "/" + "home/alice\nsee /" + "home/alice\n",
                       encoding="utf-8")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 1
    assert result.stdout.splitlines()[0] == "commit message:3: user-profile-path"
    assert f"(0 files, 1 commits, se {SE_HEAD[:7]})" in result.stdout


def allow_repo(repo: Path, allow: str) -> None:
    leak = "/" + "home/alice"
    commit(repo, {
        "docs/a.md": leak + "\n",
        "docs/b.md": leak + "\n",
        "src/x.py": "ok = 1\n" + leak + "\n",
        "src/y.py": leak + "\n",
        public_check.ALLOW_FILE: allow,
    })


def test_allowlist_globs_and_file_lines(repo: Path) -> None:
    allow_repo(repo, "# exceptions\ndocs/*.md  # sample paths in docs\n"
                     "src/x.py:2  # fixture path\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    hits = [line for line in result.stdout.splitlines() if not line.startswith("public-check")]
    assert hits == ["src/y.py:1:1: user-profile-path"]


def test_unused_allow_entry_fails_a_full_check(repo: Path) -> None:
    allow_repo(repo, "docs/*  # sample paths\nsrc/*.py  # fixtures\nsrc/x.py:1  # stale\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert (".public-check-allow:3: unused-allow-entry ('<path>:<line>' entry; unused: remove it "
            "or correct it in place)") in result.stdout
    assert "unverifiable" not in result.stdout


def test_used_allow_entries_are_counted_in_the_verdict(repo: Path) -> None:
    allow_repo(repo, "docs/*  # sample paths\nsrc/*.py  # fixtures\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout
    assert "2 allow entries used" in result.stdout.splitlines()[-1]
    assert "unused" not in result.stdout and "unverifiable" not in result.stdout


def test_without_local_list_an_unused_entry_is_unverifiable_not_unused(
        repo: Path, local: Path) -> None:
    local.unlink()
    allow_repo(repo, "docs/*  # sample paths\nsrc/*.py  # fixtures\nold/*  # moved away\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout
    assert ("public-check: warning: allow entry .public-check-allow:3 ('<path glob>' entry) is "
            "unverifiable without the local list: run with it ") in result.stdout
    assert "unused" not in result.stdout and "remove it" not in result.stdout
    assert "2 allow entries used" in result.stdout.splitlines()[-1]


def test_without_local_list_an_unused_commit_entry_in_a_gate_is_unverifiable(
        repo: Path, local: Path) -> None:
    local.unlink()
    commit(repo, {"a.txt": "a\n"}, "Clean message")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} message  # stale\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 0, result.stdout
    assert ("allow entry .public-check-allow:1 ('commit:<full sha> message' entry) is "
            "unverifiable without the local list") in result.stdout


def test_allow_entry_needs_a_reason(repo: Path) -> None:
    allow_repo(repo, "docs/*\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 2
    assert ".public-check-allow:1:" in result.stdout


def test_allowlist_does_not_cover_commit_messages(repo: Path) -> None:
    commit(repo, {public_check.ALLOW_FILE: "*  # everything\n", "a.txt": "/" + "home/alice\n"},
           "Copy from /" + "home/alice")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "message:1: user-profile-path" in result.stdout
    assert "a.txt" not in result.stdout


def commit_entry_repo(repo: Path) -> tuple[str, str]:
    """A project-identity repository with two commits by a foreign author; returns their SHAs."""
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    shas = []
    for name in ("a.txt", "b.txt"):
        (repo / name).write_text("clean\n", encoding="utf-8")
        git(repo, "add", name)
        env = {**os.environ, "GIT_AUTHOR_NAME": "Claude",
               "GIT_AUTHOR_EMAIL": "noreply" + AT + "anthropic.com"}
        git(repo, "commit", "-qm", f"Add {name}", env=env)
        shas.append(git(repo, "rev-parse", "HEAD").stdout.strip())
    return shas[0], shas[1]


def test_a_commit_entry_allows_that_identity_on_that_commit_only(repo: Path) -> None:
    listed, other = commit_entry_repo(repo)
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{listed} author  # merge made by a bot, already published\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--range", "HEAD~2..HEAD")
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    assert [hit.split(":", 1)[0] for hit in hits] == [f"commit {other[:12]} author"], result.stdout
    assert result.returncode == 1
    assert "or, for a commit already published" in hits[0]
    assert run_check("--repo", str(repo), "--range", "HEAD~2..HEAD~1").returncode == 0
    # A full check never sees the gate's hit, so the entry is not reported unused there.
    assert run_check("--repo", str(repo)).returncode == 0


def test_a_commit_entry_covers_pattern_hits_of_its_role_only(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"}, "Add readme", "user.email=alice" + AT + "corp.test")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} committer  # wrong role\n", encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1 and " author: email-address" in result.stdout
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} author  # imported history\n", encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("entry", [
    "commit:{sha} author",
    "commit:{sha} author  #",
    "commit:{short} author  # an abbreviated SHA",
    "commit:{sha} reviewer  # no such role",
    "commit:{sha}  # no role",
])
def test_a_commit_entry_without_reason_full_sha_or_role_is_rejected(repo: Path, entry: str) -> None:
    commit(repo, {"README.md": "clean\n"})
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        entry.format(sha=sha, short=sha[:12]) + "\n", encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 2, result.stdout
    assert ".public-check-allow:1:" in result.stdout


def message_entry_repo(repo: Path) -> tuple[str, str]:
    """Two commits whose messages carry the same tracker reference; returns their SHAs."""
    shas = []
    for name in ("a.txt", "b.txt"):
        commit(repo, {name: "clean\n"}, f"Merge work into {name} (" + "#7)")
        shas.append(git(repo, "rev-parse", "HEAD").stdout.strip())
    return shas[0], shas[1]


def test_a_message_entry_allows_the_message_of_that_commit_only(repo: Path) -> None:
    listed, other = message_entry_repo(repo)
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{listed} message  # merge already published\n", encoding="utf-8")
    assert run_check("--repo", str(repo), "--range", "HEAD~1").returncode == 0
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 1
    hits = [line for line in result.stdout.splitlines() if "tracker-reference" in line]
    assert [hit.split(" message:")[0] for hit in hits] == [f"commit {other[:12]}"], result.stdout


def test_a_message_entry_covers_pattern_hits_in_its_message(repo: Path) -> None:
    commit(repo, {"a.txt": "a\n"}, "Copy from /" + "home/alice")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} message  # imported history\n", encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout


def test_a_message_entry_without_reason_is_rejected(repo: Path) -> None:
    listed, _ = message_entry_repo(repo)
    (repo / public_check.ALLOW_FILE).write_text(f"commit:{listed} message\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--range", "HEAD~1")
    assert result.returncode == 2, result.stdout
    assert ".public-check-allow:1: write" in result.stdout
    assert "author|committer|message" in result.stdout


def test_an_unused_commit_entry_in_a_gate_is_reported_with_its_line_and_form(repo: Path) -> None:
    commit(repo, {"a.txt": "a\n"}, "Clean message")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} message  # stale\n", encoding="utf-8")
    assert run_check("--repo", str(repo)).returncode == 0  # a full check does not decide it
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 1
    assert (".public-check-allow:1: unused-allow-entry ('commit:<full sha> message' entry; "
            "unused: remove it or correct it in place)") in result.stdout


def shallow_clone(repo: Path, tmp_path: Path, depth: int) -> Path:
    for index in range(4):
        commit(repo, {f"f{index}.txt": "x\n"}, f"Change {index}")
    clone = tmp_path / "shallow"
    fake_git.clone(repo.as_uri(), clone, "--depth", str(depth))
    return clone


def test_a_range_beyond_a_shallow_clone_is_refused_naming_the_remedy(
        repo: Path, tmp_path: Path) -> None:
    clone = shallow_clone(repo, tmp_path, 2)
    result = run_check("--repo", str(clone), "--range", "HEAD")
    assert result.returncode == 2, result.stdout
    assert "reaches beyond the fetched history of this shallow clone" in result.stdout
    assert "git fetch --unshallow" in result.stdout


def test_a_range_within_a_shallow_clone_passes(repo: Path, tmp_path: Path) -> None:
    clone = shallow_clone(repo, tmp_path, 2)
    result = run_check("--repo", str(clone), "--range", "HEAD~1..HEAD")
    assert result.returncode == 0, result.stdout
    assert ", 1 commits," in result.stdout


def git_sh() -> str | None:
    """The POSIX shell: on PATH, or the one shipped with Git for Windows."""
    found = shutil.which("sh")
    if found:
        return found
    found = shutil.which("git")
    if found is None:
        return None
    root = Path(found).resolve().parents[1]  # Git for Windows: <root>/cmd/git.exe
    for candidate in (root / "bin" / "sh.exe", root / "usr" / "bin" / "sh.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


SETUPS = ["sh"] + (["powershell"] if os.name == "nt" else [])


def setup_hooks(kind: str, target: Path, copilot: bool = False) -> subprocess.CompletedProcess[str]:
    if kind == "powershell":
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(SE_ROOT / "scripts" / "setup.ps1"), "-Repo", str(target)] + (["-Copilot"] if copilot else [])
    else:
        shell = git_sh()
        if shell is None:
            pytest.skip("no POSIX shell")
        command = [shell, str(SE_ROOT / "scripts" / "setup.sh"), str(target)] + (["--copilot"] if copilot else [])
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("kind", SETUPS)
def test_setup_names_the_own_hooks_ignores_the_local_list_once_and_sets_the_identity(
        kind: str, repo: Path) -> None:
    """Three preconditions that do not interfere share one repository and its two setup runs: the
    checkout's own hooks in core.hooksPath, a .gitignore without a trailing newline, and the
    project's commit identity."""
    folder = repo.parent / "own-hooks"  # the checkout's own hook set, which core.hooksPath names now
    folder.mkdir()
    git(repo, "config", "core.hooksPath", str(folder))
    (folder / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    (folder / "commit-msg.sample").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / ".gitignore").write_text("build/", encoding="utf-8")
    (repo / "se.toml").write_text('[project]\nidentity = "alice <alice>"\n', encoding="utf-8")
    result = setup_hooks(kind, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    named = next(line for line in result.stdout.splitlines() if "no longer run" in line)
    assert "no longer run: pre-commit, as core.hooksPath" in named and "sample" not in named
    assert f"config core.hooksPath {folder.as_posix()}" in named
    lines = result.stdout.splitlines()
    assert lines.index(named) < next(i for i, line in enumerate(lines) if line.startswith("core.hooksPath of "))
    assert git(repo, "config", "user.name").stdout.strip() == "alice"
    assert git(repo, "config", "user.email").stdout.strip() == "alice"
    again = setup_hooks(kind, repo)  # se's hooks in place: nothing else stops
    assert again.returncode == 0, again.stdout + again.stderr
    assert "no longer run" not in again.stdout
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert text == f"build/\n{public_check.LOCAL_FILE}\n"


def se_as_a_local_module(repo: Path) -> None:
    """The machine's local list points the module se at this checkout, so `sync se` clones nothing
    (README "Modules", ~/.se/local.toml [paths]); the repo fixture's HOME holds it."""
    local = Path(os.environ["HOME"]) / ".se" / "local.toml"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(f"[paths]\nse = '{SE_ROOT.as_posix()}'\n", encoding="utf-8")


@pytest.mark.parametrize("kind", SETUPS)
def test_setup_with_copilot_merges_the_settings_pins_se_and_ignores_its_folder(kind: str, repo: Path) -> None:
    se_as_a_local_module(repo)
    settings = repo / ".github" / "copilot" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "x", "enabledPlugins": {"other@else": true}}\n', encoding="utf-8")
    (repo / "se.toml").write_text('[project]\nidentity = "alice <alice>"\n', encoding="utf-8")
    for _ in range(2):
        result = setup_hooks(kind, repo, copilot=True)
        assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data == {"model": "x",
                    "enabledPlugins": {"other@else": True, "se@se": True},
                    "extraKnownMarketplaces": {"se": {"source": {"source": "github", "repo": "alice/SE"}}}}
    pin = tomllib.loads((repo / "se.toml").read_text(encoding="utf-8"))["modules"]["se"]
    major, minor = tomllib.loads((SE_ROOT / "se.toml").read_text(encoding="utf-8"))["project"]["version"].split(".")[:2]
    assert pin == {"url": "https://github.com/alice/SE.git", "version": f"^{major}.{minor}"}
    assert (repo / ".gitignore").read_text(encoding="utf-8").splitlines().count(".se/") == 1
    assert "se: local" in result.stdout, result.stdout


def test_se_ignores_its_local_list() -> None:
    lines = (SE_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert public_check.LOCAL_FILE in lines


def repository_config(state: fake_git.StateFile, repo: Path) -> dict[str, str]:
    """The fake's config of `repo`."""
    return dict(state.load().repositories[repo.resolve()].config)


def repository_files(repo: Path) -> dict[str, bytes]:
    """Every file under `repo`, its .git included, by its path relative to `repo`."""
    return {path.relative_to(repo).as_posix(): path.read_bytes()
            for path in sorted(repo.rglob("*")) if path.is_file()}


# What each setup kind did to a fresh `repo` (its config and its .gitignore), recorded by its first
# run, `first_setup`: the fresh setup test asserts that run, and a hook test after it replays the
# record instead of paying for setup's script processes again.
SETUP_RESULTS: dict[str, tuple[dict[str, str], bytes]] = {}


def first_setup(kind: str, repo: Path,
                state: fake_git.StateFile) -> subprocess.CompletedProcess[str]:
    """Run setup of `kind` on the fresh `repo` and record what it changed in SETUP_RESULTS."""
    before = repository_config(state, repo)
    files = repository_files(repo)
    result = setup_hooks(kind, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    after = repository_config(state, repo)
    changed = {key: value for key, value in after.items() if before.get(key) != value}
    assert not set(before) - set(after), "setup removed config"
    assert not any(str(repo.parent) in value for value in changed.values()), changed
    now = repository_files(repo)
    now.pop(".gitignore", None)
    files.pop(".gitignore", None)
    assert now == files, "setup changed a file other than .gitignore"
    SETUP_RESULTS[kind] = changed, (repo / ".gitignore").read_bytes()
    return result


@pytest.mark.parametrize("kind", SETUPS)
def test_setup_points_core_hooks_path_at_se_hooks_and_writes_nothing_for_copilot_without_it(
        kind: str, repo: Path, shared_fake_git: fake_git.StateFile) -> None:
    result = first_setup(kind, repo, shared_fake_git)
    assert result.returncode == 0, result.stdout + result.stderr
    hooks = git(repo, "config", "core.hooksPath").stdout.strip()
    assert Path(hooks).resolve() == (SE_ROOT / ".githooks").resolve()
    assert not (repo / ".github").exists()
    assert not (repo / "se.toml").exists()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"{public_check.LOCAL_FILE}\n"
    assert "copilot install:" not in result.stdout


@pytest.fixture(params=SETUPS)
def hooked(request: pytest.FixtureRequest, repo: Path, shared_fake_git: fake_git.StateFile) -> Path:
    kind = request.param
    if kind not in SETUP_RESULTS:
        first_setup(kind, repo, shared_fake_git)
        return repo
    changed, ignore = SETUP_RESULTS[kind]
    with shared_fake_git.edit() as fake:
        fake.repositories[repo.resolve()].config.update(changed)
    (repo / ".gitignore").write_bytes(ignore)
    return repo


def try_commit(repo: Path, message: str = "Add file") -> subprocess.CompletedProcess[str]:
    git(repo, "add", "-A")
    return git_door.run("commit", "-q", "-m", message, root=repo)


def test_pre_commit_hook_blocks_a_planted_user_path(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    assert try_commit(hooked).returncode == 0
    (hooked / "leak.txt").write_text("C:" + BS + "Users" + BS + "alice\n", encoding="utf-8")
    result = try_commit(hooked)
    assert result.returncode != 0
    assert "leak.txt:1:1: user-profile-path" in result.stdout + result.stderr
    assert git(hooked, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_commit_msg_hook_blocks_a_leaky_message(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    result = try_commit(hooked, "Copied from /" + "home/alice")
    assert result.returncode != 0
    assert "commit message:1: user-profile-path" in result.stdout + result.stderr


def test_pre_push_hook_checks_pushed_commits(hooked: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    fake_git.init(remote, "--bare")
    git(hooked, "remote", "add", "origin", str(remote))
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    assert try_commit(hooked).returncode == 0
    push = ["push", "-q", "origin", "main:topic"]  # not the integration branch
    assert git_door.run(*push, root=hooked).returncode == 0
    (hooked / "clean.txt").write_text("still clean\n", encoding="utf-8")
    git(hooked, "add", "-A")
    git(hooked, "commit", "-q", "--no-verify", "-m", "Mirror https://acme" + ".ghe" + ".com/x")
    result = git_door.run(*push, root=hooked)
    assert result.returncode != 0
    assert "message:1: enterprise-github-host" in result.stdout + result.stderr
    assert f"(2 files, 1 commits, se {SE_HEAD[:7]})" in result.stdout + result.stderr


# SE's own line of history, which scripts/hygiene.py's public check covers.
SE_LINE_MARKER, se_line = hygiene.SE_LINE_MARKER, hygiene.se_line


def foreign_line(repo: Path) -> None:
    """A line without the public check whose commit publishes an address, as the Go line does."""
    git(repo, "config", "user.email", "alice" + AT + "corp.test")
    commit(repo, {"main.go": "package main\n"}, "Old line")
    git(repo, "config", "user.email", "alice" + AT + "example.com")


def test_se_line_leaves_a_foreign_line_below_it_alone(repo: Path) -> None:
    foreign_line(repo)
    commit(repo, {SE_LINE_MARKER: "# check\n"}, "Switch to se")
    assert run_check("--repo", str(repo)).returncode == 1
    result = run_check("--repo", str(repo), "--history", se_line(repo))
    assert result.returncode == 0, result.stdout
    assert "1 commits" in result.stdout


def test_se_line_still_refuses_a_foreign_identity_on_it(repo: Path) -> None:
    foreign_line(repo)
    commit(repo, {SE_LINE_MARKER: "# check\n"}, "Switch to se")
    git(repo, "config", "user.email", "bob" + AT + "corp.test")
    commit(repo, {"README.md": "clean\n"}, "Add readme")
    result = run_check("--repo", str(repo), "--history", se_line(repo))
    assert result.returncode == 1
    assert "author" in result.stdout and "corp.test" not in result.stdout
    assert "2 commits" in result.stdout


def test_se_line_includes_both_sides_of_a_merge_ref(repo: Path) -> None:
    """GitHub's merge ref of a pull request into main: first parent the Go line's tip, second the
    switch commits; both the merge and the switch commits are SE's line."""
    foreign_line(repo)
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    commit(repo, {SE_LINE_MARKER: "# check\n"}, "Switch to se")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "checkout", "-q", "--detach", base)
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge", head)
    assert se_line(repo) == f"HEAD --not {base}"
    result = run_check("--repo", str(repo), "--history", se_line(repo))
    assert result.returncode == 0, result.stdout
    assert "2 commits" in result.stdout


def test_history_and_range_exclude_each_other(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo), "--history", "HEAD", "--range", "HEAD")
    assert result.returncode == 2
    assert "--range and --history exclude each other" in result.stdout


@pytest.mark.parametrize(("text", "found"), [
    ("Worker role (" + "#593, requirement 3)", ["#593"]),
    ("See GH" + "-12 and #7", ["GH-12", "#7"]),
    ("Fixes https://github.com/o/r/" + "issues/8", ["https://github.com/o/r/issues/8"]),
    ("Port the C# client; #include <stdio.h>; issue #x", []),
    ("Escape &" + "#39; and color #fff", []),
    ("Integrate fix/breaking-release-without-" + "gh-20261106: release kind", []),
    ("Branch issue_" + "gh-3 and fix/" + "gh-4", []),
    ("GH" + "-12", ["GH-12"]),
    ("gh" + "-12", ["gh-12"]),
    ("(GH" + "-12)", ["GH-12"]),
    ("As obs" + "#627 showed", ["obs#627"]),
    ("Fix SE" + "#874, then o-1/my.repo" + "#9.", ["SE#874", "o-1/my.repo#9"]),
    ("(repo" + "#1)", ["repo#1"]),
    ("F" + "#6 and C" + "#5 stay, as do ab" + "#12x and a/b" + "#c", []),
])
def test_tracker_references(text: str, found: list[str]) -> None:
    assert [match for _, match in public_check.tracker_references(text)] == found


def test_commit_msg_hook_refuses_a_tracker_reference(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    result = try_commit(hooked, "Worker role (" + "#593)")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "commit message:1: tracker-reference '#593'" in output
    assert "commit messages carry no tracker numbers" in output
    assert "reword the message before committing" in output
    assert git(hooked, "rev-list", "--all", "--count").stdout.strip() == "0"


def test_commit_msg_hook_refuses_a_repository_tracker_reference(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    result = try_commit(hooked, "Landing checks, as obs" + "#627 showed")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "commit message:1: tracker-reference 'obs#627'" in output
    assert "reword the message before committing" in output
    assert git(hooked, "rev-list", "--all", "--count").stdout.strip() == "0"
    assert try_commit(hooked, "Landing checks, as an obs landing showed").returncode == 0


def test_commit_msg_hook_accepts_csharp_and_include(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    result = try_commit(hooked, "Port the C# client\n\nKeep #include lines")
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_push_hook_refuses_a_tracker_reference_naming_the_commit(
        hooked: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    fake_git.init(remote, "--bare")
    git(hooked, "remote", "add", "origin", str(remote))
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    git(hooked, "add", "-A")
    git(hooked, "commit", "-q", "--no-verify", "-m", "Worker role (" + "#593)")
    sha = git(hooked, "rev-parse", "HEAD").stdout.strip()
    result = git_door.run("push", "-q", "origin", "main", root=hooked)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert f"commit {sha[:12]} message:1: tracker-reference '#593'" in output
    assert "git commit --amend" in output and "git rebase -i" in output


@pytest.mark.parametrize("reference", ["#" + "1", "repo#" + "1", "owner/repo#" + "1"])
def test_full_check_leaves_tracker_references_in_old_history_alone(
        repo: Path, reference: str) -> None:
    commit(repo, {"a.txt": "a\n"}, f"Old work ({reference})")
    assert run_check("--repo", str(repo)).returncode == 0
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 1
    assert f"tracker-reference '{reference}'" in result.stdout


CO_AUTHOR = "Co-Authored-By: Bot <bot" + AT + "example.com>"
SESSION = "Claude-Session: https://session.example.com/s1"


@pytest.mark.parametrize(("trailer", "key"), [
    (CO_AUTHOR, "Co-Authored-By"),
    ("co-authored-by: Bot", "co-authored-by"),
    (SESSION, "Claude-Session"),
])
def test_the_message_gate_refuses_an_attribution_trailer(
        repo: Path, tmp_path: Path, trailer: str, key: str) -> None:
    message = tmp_path / "msg"
    message.write_text(f"Add file\n\nBody\n\n{trailer}\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 1, result.stdout
    assert f"commit message:5: attribution-trailer '{key}:'" in result.stdout
    assert "commits carry no attribution trailers" in result.stdout
    assert "reword the message before committing" in result.stdout


def test_the_message_gate_passes_a_clean_message(repo: Path, tmp_path: Path) -> None:
    message = tmp_path / "msg"
    message.write_text("Add file\n\nThe co-authored-by rule is named in prose.\n",
                       encoding="utf-8")
    result = run_check("--repo", str(repo), "--message-file", str(message))
    assert result.returncode == 0, result.stdout


def test_the_range_gate_refuses_unpushed_trailers_and_leaves_published_ones(
        repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    fake_git.init(remote, "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    commit(repo, {"a.txt": "a\n"}, f"Published work\n\n{CO_AUTHOR}")
    git(repo, "push", "-q", "origin", "main")
    unpushed = "HEAD --not --remotes"
    assert run_check("--repo", str(repo), "--range", unpushed).returncode == 0
    commit(repo, {"b.txt": "b\n"}, f"New work\n\n{SESSION}")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    result = run_check("--repo", str(repo), "--range", unpushed)
    assert result.returncode == 1, result.stdout
    hits = [line for line in result.stdout.splitlines() if "attribution-trailer" in line]
    assert len(hits) == 1, result.stdout
    assert f"commit {sha[:12]} message:3: attribution-trailer 'Claude-Session:'" in hits[0]
    assert "git commit --amend" in hits[0]


CI_WORKFLOW = SE_ROOT / ".github" / "workflows" / "check.yml"


def ci_script() -> str:
    """The shell the check workflow's gate runs, its one `run: |` block, calling this se's scripts
    (the check and the git door)."""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "run: |") + 1
    block = []
    for line in lines[start:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block).replace("python3 scripts/", f"'{Path(sys.executable).as_posix()}' '{SCRIPT.parent.as_posix()}'/")


def owner_push(repo: Path, tmp_path: Path, message: str) -> tuple[str, str]:
    """The owner, with the project identity, pushes one commit to main; returns (before, after)."""
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    remote = tmp_path / "remote.git"
    fake_git.init(remote, "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    commit(repo, {"a.txt": "a\n"}, message)
    git(repo, "push", "-q", "origin", "main")
    return before, git(repo, "rev-parse", "HEAD").stdout.strip()


def run_ci(tmp_path: Path, before: str, after: str, base_ref: str = "", branch: str = "main",
           default: str = "main") -> subprocess.CompletedProcess[str]:
    """The workflow's gate step as its runner runs it, in a fresh full clone: on a push to `branch`
    of a repository whose default branch is `default`, detached at `after`; or with `base_ref` on
    a pull request into that branch, whose head is `after`, detached at the merge of `after` into
    refs/remotes/origin/<base_ref>, as the runner checks out refs/pull/<n>/merge."""
    runner = tmp_path / "runner"
    shutil.rmtree(runner, ignore_errors=True)
    fake_git.clone(tmp_path / "remote.git", runner, "-b", "main")
    if base_ref:
        git(runner, "checkout", "-q", "--detach", f"refs/remotes/origin/{base_ref}")
        git(runner, "-c", "user.name=runner", "-c", "user.email=runner", "merge", "-q",
            "--no-ff", "--no-edit", after)
    else:
        git(runner, "checkout", "-q", "--detach", after)
    env = {**os.environ, "BEFORE": before, "AFTER": after, "BRANCH": base_ref or branch,
           "DEFAULT": default, "BASE_REF": base_ref}
    return subprocess.run(["bash", "-e", "-c", ci_script()], cwd=runner, env=env,
                          capture_output=True, text=True, check=False)


@pytest.mark.parametrize("known_before", [True, False])
def test_ci_refuses_the_owners_pushed_co_author_line_naming_its_source_and_remedy(
        repo: Path, tmp_path: Path, known_before: bool) -> None:
    before, after = owner_push(repo, tmp_path, "Fix the build\n\nco-authored-by: Copilot")
    result = run_ci(tmp_path, before if known_before else "0" * 40, after)
    assert result.returncode == 1, result.stdout
    hits = [line for line in result.stdout.splitlines() if "attribution-trailer" in line]
    assert [hit.split(": ", 1)[0] for hit in hits] == [f"commit {after[:12]} message:3"]
    assert "git commit --amend" in hits[0] and "VS Code: git.addAICoAuthor off" in hits[0]
    assert "::error::public-check (scripts/public_check.py" in result.stdout
    assert "turn off the editor's co-author setting" in result.stdout


def test_ci_passes_an_allow_listed_co_author_commit(repo: Path, tmp_path: Path) -> None:
    before, listed = owner_push(repo, tmp_path, f"Old work\n\n{CO_AUTHOR}")
    commit(repo, {public_check.ALLOW_FILE: f"commit:{listed} message  # published before the rule\n"})
    git(repo, "push", "-q", "origin", "main")
    result = run_ci(tmp_path, before, git(repo, "rev-parse", "HEAD").stdout.strip())
    assert result.returncode == 0, result.stdout
    assert "1 allow entries used" in result.stdout


def test_ci_passes_a_clean_push(repo: Path, tmp_path: Path) -> None:
    before, after = owner_push(repo, tmp_path, "Fix the build")
    assert run_ci(tmp_path, before, after).returncode == 0


def test_ci_is_the_check_main_requires_on_pull_requests_and_pushes_to_main() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"(?m)^jobs:\n  check:\n", workflow), "main's ruleset requires a job named check"
    assert re.search(r"(?m)^on:\n  pull_request:\n.*\n  push:\n    branches: \[main\]$", workflow)
    # An edited report reruns, and so does a label change (the issue rule's housekeeping exemption).
    assert "types: [opened, synchronize, reopened, edited, labeled, unlabeled]" in workflow
    # One job, every check the integration runs; the layouts before the suite, which rebuilds them.
    steps = ["public_check.py --rev", "scripts/se_plugin.py check", "scripts/work_tickets.py docs --check",
             "scripts/hygiene.py", "scripts/work_tickets.py field-report --check",
             "scripts/work_tickets.py suite --worktree ."]
    assert [workflow.index(step) for step in steps] == sorted(workflow.index(step) for step in steps)
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", workflow)[1]
    assert "pytest" not in check, "the suite runs through work_tickets.py suite, within its budget"
    # The nightly run alone is full: it runs every suite beside, also one its paths skip.
    suite = check[check.index("- name: The complete suite and kern's tests"):]
    suite = suite[:suite.index("\n      - ")]
    assert "EVENT: ${{ github.event_name }}" in suite
    assert 'if [ "$EVENT" = schedule ]; then full=(--full); fi' in suite
    assert 'scripts/work_tickets.py suite --worktree . "${full[@]}"' in suite


def field_report_script() -> str:
    """The shell of the check workflow's field-report step, its second `run: |` block."""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "run: |"]
    block = []
    for line in lines[starts[1] + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block)


@pytest.mark.parametrize("first_line, checked", [
    ("Refs https://github.com/alice/example/issues/7", True),
    ("Fixes https://github.com/alice/example/issues/7\r", True),
    ("Refs #7", True),  # the short form pr_issues.py accepts too
    ("Closes https://github.com/Alice/Example/issues/7", True),
    ("", False),  # a landing pull request: no field report
])
def test_ci_checks_a_pull_requests_field_report_against_its_work_issue(
        tmp_path: Path, first_line: str, checked: bool) -> None:
    calls = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in {"gh": f'echo "gh $*" >> \'{calls}\'\necho "issue body"\n',
                         "uv": f'echo "uv $*" >> \'{calls}\'\n'}.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + script, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    body = f"{first_line}\n\n<!-- se:field-report -->\nreport\n" if first_line else "Land a branch\n"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "PR_BODY": body,
           "RUNNER_TEMP": str(tmp_path), "REPOSITORY": "alice/example",
           "GITHUB_ENV": str(tmp_path / "github-env")}
    result = subprocess.run(["bash", "-e", "-c", field_report_script()], env=env, cwd=SE_ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    made = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    if checked:
        assert made[0] == "gh api repos/alice/example/issues/7 --jq .body"
        # A work pull request's Component kinds reach the suite's release guard through the
        # job's environment (README "Component versions").
        assert made[1].startswith("uv run python scripts/work_tickets.py field-report --check ")
        assert made[1].endswith(f" --component-kinds-to {tmp_path / 'github-env'}")
        assert (tmp_path / "issue-body.md").read_text(encoding="utf-8") == "issue body\n"
    else:
        assert made == [] and "no field report in the description" in result.stdout


def test_ci_checks_a_landing_pull_requests_field_report_in_the_work_pull_request(
        tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    report = "Fixes https://github.com/alice/example/issues/5\n\n<!-- se:field-report -->\nreport"
    gh = (f'echo "gh $*" >> \'{calls}\'\n'
          f'case "$2" in */pulls/7) printf \'%s\\n\' \'{report}\';; *) echo "issue body";; esac\n')
    for name, script in {"gh": gh, "uv": f'echo "uv $*" >> \'{calls}\'\n'}.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + script, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    body = work_tickets_landing_description()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "PR_BODY": body,
           "RUNNER_TEMP": str(tmp_path), "REPOSITORY": "alice/example",
           "GITHUB_ENV": str(tmp_path / "github-env")}
    result = subprocess.run(["bash", "-e", "-c", field_report_script()], env=env, cwd=SE_ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    made = calls.read_text(encoding="utf-8").splitlines()
    assert made[:2] == [
        "gh api repos/alice/example/pulls/7 --jq .body",
        "gh api repos/alice/example/issues/5 --jq .body"]
    # A landing's release commit carries the component versions: it gives the guard no kinds.
    assert made[2].startswith("uv run python scripts/work_tickets.py field-report --check ")
    assert "--component-kinds-to" not in made[2]
    assert "the landing's report is the description of pull request 7" in result.stdout
    assert (tmp_path / "pr-body.md").read_text(encoding="utf-8").endswith("report\n")


def work_tickets_landing_description() -> str:
    """The landing description integrate writes, for work pull request 7 of work issue 5."""
    import work_tickets  # scripts/ is on the path (tests/conftest.py)
    return work_tickets.landing_description("https://github.com/alice/example/pull/7", 7,
                                      "https://github.com/alice/example/issues/5")


@pytest.mark.parametrize("first_line", [
    "",
    "Refs https://github.com/bob/other/issues/7",  # another repository's issue
])
def test_ci_refuses_a_field_report_that_names_no_work_issue(tmp_path: Path, first_line: str) -> None:
    env = {**os.environ, "PR_BODY": f"{first_line}\n<!-- se:field-report -->\nreport\n",
           "RUNNER_TEMP": str(tmp_path), "REPOSITORY": "alice/example"}
    result = subprocess.run(["bash", "-e", "-c", field_report_script()], env=env, cwd=SE_ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "::error::field-report: the description's first line names no work issue" in result.stdout


@pytest.mark.parametrize("message, refused", [("Fix the build", False),
                                              ("Fix the build\n\nco-authored-by: Copilot", True)])
def test_ci_gates_the_commits_of_a_pull_request(repo: Path, tmp_path: Path, message: str,
                                                refused: bool) -> None:
    owner_push(repo, tmp_path, "On main")
    git(repo, "checkout", "-q", "-b", "topic")
    commit(repo, {"b.txt": "b\n"}, message)
    git(repo, "push", "-q", "origin", "topic")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    result = run_ci(tmp_path, "", head, base_ref="main")
    assert "gating refs/remotes/origin/main.." in result.stdout
    assert "the commits of the pull request into main" in result.stdout
    assert " files, 1 commits, se " in result.stdout  # the PR's one commit, not main's
    hits = [line for line in result.stdout.splitlines() if "attribution-trailer" in line]
    assert [hit.split(": ", 1)[0] for hit in hits] == ([f"commit {head[:12]} message:3"] if refused else [])
    assert result.returncode == (1 if refused else 0), result.stdout



def test_ci_pull_request_gate_scans_the_merge_it_lands(repo: Path, tmp_path: Path) -> None:
    """Three heads cut before main moved one entry and narrowed a glob: the gate judges the merge
    each would land, by the merge's own allow list."""
    leak = "/" + "home/alice"
    owner_push(repo, tmp_path, "On main")
    commit(repo, {"t.txt": f"one\n{leak}\n", "docs/a.md": f"{leak}\n",
                  public_check.ALLOW_FILE: "# made-up paths\nt.txt:2  # in t\n"
                                           "docs/*  # in the docs\n# end\n"}, "Start")
    git(repo, "push", "-q", "origin", "main")
    start = git(repo, "rev-parse", "HEAD").stdout.strip()
    heads = {}
    for name, files in (
            ("moved", {"b.txt": "b\n"}),
            ("own", {"n.txt": f"{leak}\n", public_check.ALLOW_FILE:
                     "# made-up paths\nt.txt:2  # in t\ndocs/*  # in the docs\n# end\n"
                     "n.txt:1  # its own new path\n"}),
            ("narrowed", {"docs/b.md": "new /" + "home/bob\n"})):
        git(repo, "checkout", "-q", "-b", name, start)
        commit(repo, files, f"Add {name}")
        git(repo, "push", "-q", "origin", name)
        heads[name] = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "checkout", "-q", "main")
    commit(repo, {"t.txt": f"zero\none\n{leak}\n", public_check.ALLOW_FILE:
                  "# made-up paths\nt.txt:3  # in t\ndocs/a.md:1  # in the docs\n# end\n"},
           "Move the line, narrow the docs entry")
    git(repo, "push", "-q", "origin", "main")
    for name in ("moved", "own"):
        result = run_ci(tmp_path, "", heads[name], base_ref="main")
        assert result.returncode == 0, f"{name}: {result.stdout}"
    result = run_ci(tmp_path, "", heads["narrowed"], base_ref="main")
    assert result.returncode == 1, result.stdout
    hits = [line for line in result.stdout.splitlines() if not line.startswith(("public-check", "::"))]
    assert hits == ["docs/b.md:1:5: user-profile-path"]


def test_a_rev_check_applies_that_commits_allow_list(repo: Path) -> None:
    commit(repo, {"u.txt": "/" + "home/alice\n"})
    (repo / public_check.ALLOW_FILE).write_text("u.txt:1  # a made-up path\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--rev", "HEAD", "--no-history")
    assert result.returncode == 1
    assert "u.txt:1:1: user-profile-path" in result.stdout
    commit(repo, {}, "Allow the path")
    result = run_check("--repo", str(repo), "--rev", "HEAD", "--no-history")
    assert result.returncode == 0, result.stdout
    assert "1 allow entries used" in result.stdout


def test_a_staged_check_applies_the_staged_allow_list(repo: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    (repo / "v.txt").write_text("/" + "home/alice\n", encoding="utf-8")
    git(repo, "add", "v.txt")
    (repo / public_check.ALLOW_FILE).write_text("v.txt:1  # a made-up path\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--staged")
    assert result.returncode == 1
    assert "v.txt:1:1: user-profile-path" in result.stdout
    git(repo, "add", public_check.ALLOW_FILE)
    result = run_check("--repo", str(repo), "--staged")
    assert result.returncode == 0, result.stdout
    assert "1 allow entries used" in result.stdout


def test_a_working_tree_check_applies_the_working_tree_allow_list(repo: Path) -> None:
    commit(repo, {"w.txt": "/" + "home/alice\n"})
    assert run_check("--repo", str(repo), "--no-history").returncode == 1
    (repo / public_check.ALLOW_FILE).write_text("w.txt:1  # a made-up path\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--no-history")
    assert result.returncode == 0, result.stdout
    assert "1 allow entries used" in result.stdout


# A push's range (push_range): a work branch is gated on what it brings past the integration
# branch, whose commits were gated where they reached it; the integration branch's push is whole.

GITHUB_ACCOUNT = {"GIT_AUTHOR_NAME": "acct", "GIT_AUTHOR_EMAIL": "1+acct" + AT + NOREPLY, **WEB_FLOW}


def github_commit(repo: Path, files: dict[str, str], message: str) -> str:
    """A commit GitHub made for the account (a squash landing): its noreply author, web-flow
    committer; returns its sha."""
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message, env={**os.environ, **GITHUB_ACCOUNT})
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def landed(repo: Path, tmp_path: Path) -> dict[str, str]:
    """A strict project whose main holds a GitHub squash landing made after the branch `work`
    left it: main's first commit (`main0`), work's pushed tip (`before`) and the landing."""
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY + FAST_FORWARD}, "Start the project")
    remote = tmp_path / "remote.git"
    fake_git.init(remote, "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    main0 = head(repo)
    git(repo, "switch", "-q", "-c", "work")
    commit(repo, {"a.txt": "a\n"}, "Add a")
    git(repo, "push", "-q", "origin", "work")
    before = head(repo)
    git(repo, "switch", "-q", "main")
    landing = github_commit(repo, {"l.txt": "l\n"}, "Integrate old-landing: a squash landing")
    git(repo, "push", "-q", "origin", "main")
    return {"main0": main0, "before": before, "landing": landing}


def merged_work(repo: Path) -> str:
    """`work` merges main and adds one commit, pushed; returns its tip."""
    git(repo, "switch", "-q", "work")
    git(repo, "merge", "-q", "--no-edit", "main")
    commit(repo, {"b.txt": "b\n"}, "Add b")
    git(repo, "push", "-q", "origin", "work")
    return head(repo)


def foreign_hits(result: subprocess.CompletedProcess[str]) -> list[str]:
    return sorted({line.split(" ", 2)[1] for line in result.stdout.splitlines()
                   if "foreign-identity" in line})


def test_ci_gates_only_the_commits_a_work_branch_brings_past_main(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    after = merged_work(repo)
    result = run_ci(tmp_path, landed["before"], after, branch="work")
    assert f"gating {landed['before']}..{after} --not refs/remotes/origin/main, the commits " \
           "pushed to work" in result.stdout
    assert " files, 2 commits, se " in result.stdout  # the merge and b, not main's landing
    assert result.returncode == 0, result.stdout


def test_ci_refuses_a_work_branchs_own_foreign_commit_naming_only_it(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    after = merged_work(repo)
    foreign = github_commit(repo, {"c.txt": "c\n"}, "Add c")
    git(repo, "push", "-q", "origin", "work")
    result = run_ci(tmp_path, after, foreign, branch="work")
    assert result.returncode == 1, result.stdout
    assert foreign_hits(result) == [foreign[:12]]
    assert landed["landing"][:12] not in result.stdout
    assert "::error::public-check (scripts/public_check.py" in result.stdout


def test_ci_refuses_a_foreign_landing_pushed_to_main(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    result = run_ci(tmp_path, landed["main0"], landed["landing"])
    assert f"gating {landed['main0']}..{landed['landing']}, the commits pushed to main" in result.stdout
    assert result.returncode == 1, result.stdout
    assert foreign_hits(result) == [landed["landing"][:12]]


def test_ci_gates_a_new_branch_on_what_main_does_not_hold(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    git(repo, "switch", "-q", "-c", "work2", landed["before"])
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "push", "-q", "origin", "work2")
    result = run_ci(tmp_path, "0" * 40, head(repo), branch="work2")
    assert f"gating {head(repo)} --not refs/remotes/origin/main, " in result.stdout
    assert result.returncode == 0, result.stdout


def test_ci_refuses_a_new_branch_made_from_a_foreign_commit_another_branch_holds(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    git(repo, "switch", "-q", "-c", "held", landed["main0"])
    held = github_commit(repo, {}, "Held elsewhere")
    git(repo, "push", "-q", "origin", "held")
    git(repo, "switch", "-q", "-c", "work3", held)
    commit(repo, {"d.txt": "d\n"}, "Add d")
    git(repo, "push", "-q", "origin", "work3")
    result = run_ci(tmp_path, "0" * 40, head(repo), branch="work3")
    assert result.returncode == 1, result.stdout
    assert foreign_hits(result) == [held[:12]]


def push_clone(tmp_path: Path) -> Path:
    """A fresh full clone of the project's origin, on main."""
    runner = tmp_path / "runner"
    shutil.rmtree(runner, ignore_errors=True)
    fake_git.clone(tmp_path / "remote.git", runner, "-b", "main")
    return runner


@pytest.mark.parametrize("pushed, known, expected", [
    # A work branch leaves out what the integration branch holds, its old tip known or not.
    ("work", True, "{before}..{after} --not refs/remotes/origin/main"),
    ("work", False, "{after} --not refs/remotes/origin/main"),
    # The integration branch is gated whole, or on what no other branch holds.
    ("main", True, "{before}..{after}"),
    ("main", False, "{after} --not refs/remotes/origin/work"),
])
def test_push_range(repo: Path, tmp_path: Path, landed: dict[str, str], pushed: str, known: bool,
                    expected: str) -> None:
    after = merged_work(repo) if pushed == "work" else landed["landing"]
    before = landed["before"] if pushed == "work" else landed["main0"]
    clone = push_clone(tmp_path)
    found = public_check.push_range(clone, before if known else "0" * 40, after, pushed, "main")
    assert found == expected.format(before=before, after=after)


@pytest.mark.parametrize("before", ["", "0" * 40, "1" * 40])
def test_push_range_takes_an_old_tip_this_clone_lacks_as_unknown(
        repo: Path, tmp_path: Path, landed: dict[str, str], before: str) -> None:
    after = merged_work(repo)
    found = public_check.push_range(push_clone(tmp_path), before, after, "work", "main")
    assert found == f"{after} --not refs/remotes/origin/main"


def test_push_range_without_the_integration_ref(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    after = merged_work(repo)
    clone = push_clone(tmp_path)
    git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    assert public_check.push_range(clone, landed["before"], after, "work", "main") \
        == f"{landed['before']}..{after}"
    assert public_check.push_range(clone, "", after, "work", "main") == f"{after} --not"


def test_push_range_gates_whole_where_se_toml_names_another_branch(
        repo: Path, tmp_path: Path, landed: dict[str, str]) -> None:
    git(repo, "switch", "-q", "work")
    commit(repo, {"se.toml": PROJECT_IDENTITY.replace("[project]\n", "[project]\nintegration_branch = \"trunk\"\n")
                  + FAST_FORWARD}, "Name trunk")
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "push", "-q", "origin", "work")
    after = head(repo)
    clone = push_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach", after)
    assert public_check.push_range(clone, landed["before"], after, "work", "main") \
        == f"{landed['before']}..{after}"
    result = run_ci(tmp_path, landed["before"], after, branch="work")
    assert result.returncode == 1, result.stdout  # main's landing is gated again, and refused
    assert foreign_hits(result) == [landed["landing"][:12]]


@pytest.mark.parametrize("args, named", [
    (["--push", "x", "--branch", "b", "--default-branch", "main"], "--push needs --rev"),
    (["--rev", "HEAD", "--push", "x", "--default-branch", "main"], "--push needs --branch"),
    (["--rev", "HEAD", "--push", "x", "--branch", "b"], "--push needs --default-branch"),
    (["--rev", "HEAD", "--push", "x", "--branch", "b", "--default-branch", "main", "--range", "HEAD"],
     "--push and --range exclude each other"),
    (["--rev", "HEAD", "--push", "x", "--branch", "b", "--default-branch", "main", "--history", "HEAD"],
     "--push and --history exclude each other"),
    (["--rev", "HEAD", "--push", "x", "--branch", "b", "--default-branch", "main", "--no-history"],
     "--push and --no-history exclude each other"),
    (["--rev", "HEAD", "--branch", "b"], "--branch needs --push"),
])
def test_push_options_missing_or_clashing_are_a_setup_error(repo: Path, args: list[str],
                                                            named: str) -> None:
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo), *args)
    assert result.returncode == 2, result.stdout
    assert named in result.stdout

# --built: a built page, or a folder of them, checked as a source of its own. Pages are written
# here from fragments, so no tracked file holds the value a test plants.

def island(data: dict, encoding: str = "gzip") -> str:
    """obs's data island holding `data`: base64 gzip of its JSON, plain JSON, or another encoding."""
    import base64
    import gzip
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    if encoding == "plain":
        return f'<script id="artifact-data" type="application/json" data-artifact-data>{text}</script>'
    body = base64.b64encode(gzip.compress(text.encode("utf-8"), mtime=0)).decode("ascii")
    return ('<script id="artifact-data" type="application/octet-stream" data-artifact-data '
            f'data-compression="{encoding}" data-encoding="{encoding}">{body}</script>')


def page(body: str = "<p>clean</p>", data: dict | None = None, encoding: str = "gzip") -> str:
    found = island(data, encoding) if data is not None else ""
    return f"<!doctype html>\n<html>\n<body>\n{body}\n{found}\n</body>\n</html>\n"


def built(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / "site"
    for name, content in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return folder


def test_a_local_term_in_a_built_page_attribute_is_named_by_line_and_column(
        repo: Path, local: Path, tmp_path: Path) -> None:
    local.write_text("# kept private\n\nexample-secret\\w*\n", encoding="utf-8")
    commit(repo, {"README.md": "clean\n"})
    site = built(tmp_path, {"index.html": page('<a title="by Example-SecretCorp">x</a>',
                                               {"notes": []})})
    result = run_check("--repo", str(repo), "--built", str(site / "index.html"))
    assert result.returncode == 1, result.stdout
    assert "built:index.html:4:14: local-term:3" in result.stdout
    assert "secret" not in result.stdout.lower()
    assert "public-check: FAILED with 1 hit(s) (1 built files, " in result.stdout
    assert " commits" not in result.stdout


def test_an_address_in_a_gzip_island_is_named_by_its_field_path(repo: Path, tmp_path: Path) -> None:
    commit(repo, {"README.md": "clean\n"})
    address = "alice" + AT + "corp.test"
    site = built(tmp_path, {"docs/index.html": page(data={"notes": [
        {"id": "a", "html": "<p>clean</p>"}, {"id": "b", "html": f"<p>Write to {address}</p>"}]})})
    result = run_check("--repo", str(repo), "--built", str(site))
    assert result.returncode == 1, result.stdout
    assert "built:docs/index.html artifact-data notes[1].html: email-address" in result.stdout
    assert address not in result.stdout and "corp" not in result.stdout


def test_a_key_and_a_plain_island_are_scanned_by_line_and_by_field_path(
        repo: Path, local: Path, tmp_path: Path) -> None:
    local.write_text("example-secret\\w*\n", encoding="utf-8")
    commit(repo, {"README.md": "clean\n"})
    site = built(tmp_path, {"p.html": page(data={"Example-SecretCorp": {"x": 1}}, encoding="plain")})
    result = run_check("--repo", str(repo), "--built", str(site / "p.html"))
    assert result.returncode == 1, result.stdout
    assert "built:p.html artifact-data <local-term:1> (the key): local-term:1" in result.stdout
    assert "built:p.html:5:" in result.stdout  # the raw text of a plain island, by line too
    assert "secret" not in result.stdout.lower()


def test_a_built_file_name_hit_is_redacted(repo: Path, local: Path, tmp_path: Path) -> None:
    local.write_text("example-secret\\w*\n", encoding="utf-8")
    commit(repo, {"README.md": "clean\n"})
    site = built(tmp_path, {"example-secretcorp/index.html": page()})
    result = run_check("--repo", str(repo), "--built", str(site))
    assert result.returncode == 1, result.stdout
    assert "built:<local-term:1>/index.html (file name): local-term:1" in result.stdout
    assert "secret" not in result.stdout.lower()


def test_clean_built_pages_pass_and_no_allow_entry_applies(repo: Path, tmp_path: Path) -> None:
    commit(repo, {public_check.ALLOW_FILE: "# reasoned\nnowhere.txt:1\n", "README.md": "clean\n"})
    site = built(tmp_path, {"index.html": page(data={"notes": [{"html": "<p>clean</p>"}]}),
                            "timeline.html": page(), "assets/app.js": "console.log(1)\n"})
    for target, count in ((site / "index.html", 1), (site, 3)):
        result = run_check("--repo", str(repo), "--built", str(target))
        assert result.returncode == 0, result.stdout
        assert f"public-check: passed ({count} built files, se {SE_HEAD[:7]})" in result.stdout
        assert "allow" not in result.stdout
        assert "verdict recorded" not in result.stdout


def test_built_files_are_read_in_sorted_order_of_their_relative_paths(tmp_path: Path) -> None:
    site = built(tmp_path, {"b/z.html": "z", "a.html": "a", "b/a.html": "b"})
    assert [name for name, _ in public_check.built_files(site)] == ["a.html", "b/a.html", "b/z.html"]


@pytest.mark.parametrize("make, named", [
    (lambda site: site / "missing.html", "missing.html: no such file or folder"),
    (lambda site: site, "the folder holds no file"),
    (lambda site: (site / "p.html").write_text(page(data={}, encoding="zstd"), encoding="utf-8")
     and site / "p.html", "built:p.html: its artifact-data island has data-encoding 'zstd'"),
    (lambda site: (site / "p.html").write_text(
        page().replace("<p>clean</p>", '<script id="artifact-data" type="application/json">{'
                       '</script>'), encoding="utf-8") and site / "p.html",
     "built:p.html: its artifact-data island is not JSON"),
    (lambda site: (site / "p.html").write_text(
        page().replace("<p>clean</p>", '<script id="artifact-data" type="application/octet-stream" '
                       'data-encoding="gzip">not base64!</script>'), encoding="utf-8")
     and site / "p.html", "built:p.html: its artifact-data island is no base64 gzip"),
])
def test_what_the_built_check_cannot_read_is_a_setup_error_naming_it(
        repo: Path, tmp_path: Path, make, named: str) -> None:
    commit(repo, {"README.md": "clean\n"})
    site = tmp_path / "site"
    site.mkdir()
    result = run_check("--repo", str(repo), "--built", str(make(site)))
    assert result.returncode == 2, result.stdout
    assert named in result.stdout


@pytest.mark.parametrize("option", ["--range", "--history"])
def test_built_with_a_history_option_is_a_setup_error_naming_both(
        repo: Path, tmp_path: Path, option: str) -> None:
    commit(repo, {"README.md": "clean\n"})
    site = built(tmp_path, {"index.html": page()})
    result = run_check("--repo", str(repo), "--built", str(site), option, "HEAD")
    assert result.returncode == 2, result.stdout
    assert f"--built and {option} exclude each other" in result.stdout


@pytest.mark.parametrize("option", ["--staged", "--rev=HEAD", "--message-file=m.txt"])
def test_built_excludes_the_other_sources(tmp_path: Path, option: str) -> None:
    with pytest.raises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
        public_check.parse_args(["--built", str(tmp_path), option])
    assert raised.value.code == 2
