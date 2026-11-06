"""Tests for scripts/public_check.py. Leaky sample values are assembled at runtime from
fragments, so this file itself passes the check."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

SE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SE_ROOT / "scripts" / "public_check.py"
SE_HEAD = subprocess.run(["git", "-C", str(SE_ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
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


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


@pytest.fixture
def terms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An existing, empty deny list, so a run is a full check without the user's own list."""
    path = tmp_path / "private-terms.txt"
    path.write_text("# no terms\n", encoding="utf-8")
    monkeypatch.setenv(public_check.TERMS_ENV, str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path, terms: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with a generic identity, checked without the machine's ~/.se/local.toml."""
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "home"))
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test" + AT + "example.com")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    return path


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
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd,
        check=False,
    )


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


def test_private_terms_hit_without_printing_the_term(repo: Path, terms: Path) -> None:
    terms.write_text("# employer\n\nacme\\w*\n", encoding="utf-8")
    commit(repo, {"src/app.py": "print('built for AcmeCorp')\n"}, "Port the AcmeCorp tool")
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    assert "src/app.py:1:18: private-term:3" in result.stdout
    assert "message:1: private-term:3" in result.stdout
    assert "acme" not in result.stdout.lower()


def test_paths_with_private_terms_are_redacted(repo: Path, terms: Path) -> None:
    terms.write_text("acme\\w*\n", encoding="utf-8")
    commit(repo, {"src/AcmeTools/app.py": "x = 1\nbuilt by acme\n",
                  "docs/alice" + AT + "corp.test.md": "/" + "home/alice\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert "src/<private-term:1>/app.py (file name): private-term:1" in lines
    assert "src/<private-term:1>/app.py:2:10: private-term:1" in lines
    assert "docs/<email-address>:1:1: user-profile-path" in lines
    assert "acme" not in result.stdout.lower()
    assert "alice" not in result.stdout


def test_invalid_private_term_is_a_setup_error(repo: Path, terms: Path) -> None:
    terms.write_text("acme(\n", encoding="utf-8")
    result = run_check("--repo", str(repo))
    assert result.returncode == 2
    assert "line 1 of the private deny list is not a valid regex" in result.stdout
    assert "acme" not in result.stdout.lower()


def test_missing_private_list_warns(repo: Path, tmp_path: Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(public_check.TERMS_ENV, str(tmp_path / "missing.txt"))
    commit(repo, {"README.md": "clean\n"})
    result = run_check("--repo", str(repo))
    assert result.returncode == 0
    assert "public-check: warning: no private deny list" in result.stdout


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
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "Change readme"], env=env,
                   check=True)
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
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Add readme"], env=env, check=True)
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    assert result.returncode == 1
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    assert len(hits) == 1 and " committer: foreign-identity " in hits[0]
    assert "corp.test" not in result.stdout


WEB_FLOW = {"GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply" + AT + "github.com"}


@pytest.mark.parametrize("author, refused", [("mb", []), ("agent", ["author"])])
def test_a_commit_made_on_github_passes_only_with_the_project_author(
        repo: Path, author: str, refused: list[str]) -> None:
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    (repo / "README.md").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "README.md")
    env = {**os.environ, **WEB_FLOW, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": author}
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Add readme"], env=env, check=True)
    result = run_check("--repo", str(repo), "--range", "HEAD^!")
    hits = [line for line in result.stdout.splitlines() if "foreign-identity" in line]
    assert [hit.split(": ", 1)[0].rsplit(" ", 1)[1] for hit in hits] == refused, result.stdout
    assert result.returncode == (1 if refused else 0), result.stdout


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


def test_without_private_list_an_unused_entry_is_unverifiable_not_unused(
        repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(public_check.TERMS_ENV, str(tmp_path / "missing.txt"))
    allow_repo(repo, "docs/*  # sample paths\nsrc/*.py  # fixtures\nold/*  # moved away\n")
    result = run_check("--repo", str(repo))
    assert result.returncode == 0, result.stdout
    assert ("public-check: warning: allow entry .public-check-allow:3 ('<path glob>' entry) is "
            "unverifiable without the private deny list: run with it ") in result.stdout
    assert "unused" not in result.stdout and "remove it" not in result.stdout
    assert "2 allow entries used" in result.stdout.splitlines()[-1]


def test_without_private_list_an_unused_commit_entry_in_a_gate_is_unverifiable(
        repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(public_check.TERMS_ENV, str(tmp_path / "missing.txt"))
    commit(repo, {"a.txt": "a\n"}, "Clean message")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / public_check.ALLOW_FILE).write_text(
        f"commit:{sha} message  # stale\n", encoding="utf-8")
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 0, result.stdout
    assert ("allow entry .public-check-allow:1 ('commit:<full sha> message' entry) is "
            "unverifiable without the private deny list") in result.stdout


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
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", f"Add {name}"], env=env,
                       check=True)
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
    subprocess.run(["git", "clone", "-q", "--depth", str(depth), repo.as_uri(), str(clone)],
                   capture_output=True, check=True)
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
    exec_path = Path(git(Path.cwd(), "--exec-path").stdout.strip())
    for candidate in (exec_path.parents[2] / "bin" / "sh.exe",
                      exec_path.parents[2] / "usr" / "bin" / "sh.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


SETUPS = ["sh"] + (["powershell"] if os.name == "nt" else [])


def setup_hooks(kind: str, target: Path) -> subprocess.CompletedProcess[str]:
    if kind == "powershell":
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(SE_ROOT / "scripts" / "setup.ps1"), "-Repo", str(target)]
    else:
        shell = git_sh()
        if shell is None:
            pytest.skip("no POSIX shell")
        command = [shell, str(SE_ROOT / "scripts" / "setup.sh"), str(target)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("kind", SETUPS)
def test_setup_points_core_hooks_path_at_se_hooks(kind: str, repo: Path) -> None:
    result = setup_hooks(kind, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    hooks = git(repo, "config", "core.hooksPath").stdout.strip()
    assert Path(hooks).resolve() == (SE_ROOT / ".githooks").resolve()


@pytest.fixture(params=SETUPS)
def hooked(request: pytest.FixtureRequest, repo: Path) -> Path:
    result = setup_hooks(request.param, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return repo


def try_commit(repo: Path, message: str = "Add file") -> subprocess.CompletedProcess[str]:
    git(repo, "add", "-A")
    return subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message],
                          capture_output=True, text=True, check=False)


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
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(hooked, "remote", "add", "origin", str(remote))
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    assert try_commit(hooked).returncode == 0
    push = ["git", "-C", str(hooked), "push", "-q", "origin", "main:topic"]  # not the integration branch
    assert subprocess.run(push, capture_output=True, text=True).returncode == 0
    (hooked / "clean.txt").write_text("still clean\n", encoding="utf-8")
    git(hooked, "add", "-A")
    git(hooked, "commit", "-q", "--no-verify", "-m", "Mirror https://acme" + ".ghe" + ".com/x")
    result = subprocess.run(push, capture_output=True, text=True)
    assert result.returncode != 0
    assert "message:1: enterprise-github-host" in result.stdout + result.stderr
    assert f"(1 files, 1 commits, se {SE_HEAD[:7]})" in result.stdout + result.stderr


def test_se_itself_passes() -> None:
    """se must stay publishable; uses this machine's private deny list when it has one."""
    result = run_check("--repo", str(SE_ROOT))
    assert result.returncode == 0, result.stdout


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


def test_commit_msg_hook_accepts_csharp_and_include(hooked: Path) -> None:
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    result = try_commit(hooked, "Port the C# client\n\nKeep #include lines")
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_push_hook_refuses_a_tracker_reference_naming_the_commit(
        hooked: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(hooked, "remote", "add", "origin", str(remote))
    (hooked / "clean.txt").write_text("clean\n", encoding="utf-8")
    git(hooked, "add", "-A")
    git(hooked, "commit", "-q", "--no-verify", "-m", "Worker role (" + "#593)")
    sha = git(hooked, "rev-parse", "HEAD").stdout.strip()
    result = subprocess.run(["git", "-C", str(hooked), "push", "-q", "origin", "main"],
                            capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert f"commit {sha[:12]} message:1: tracker-reference '#593'" in output
    assert "git commit --amend" in output and "git rebase -i" in output


def test_full_check_leaves_tracker_references_in_old_history_alone(repo: Path) -> None:
    commit(repo, {"a.txt": "a\n"}, "Old work (" + "#1)")
    assert run_check("--repo", str(repo)).returncode == 0
    result = run_check("--repo", str(repo), "--range", "HEAD")
    assert result.returncode == 1
    assert "tracker-reference '#1'" in result.stdout


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
    git(tmp_path, "init", "-q", "--bare", str(remote))
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


CI_WORKFLOW = SE_ROOT / ".github" / "workflows" / "public-check.yml"


def ci_script() -> str:
    """The shell the public-check workflow runs, its one `run: |` block, calling this se's check."""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "run: |") + 1
    block = []
    for line in lines[start:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block).replace("python3 scripts/public_check.py", f"'{sys.executable}' '{SCRIPT}'")


def owner_push(repo: Path, tmp_path: Path, message: str) -> tuple[str, str]:
    """The owner, with the project identity, pushes one commit to se; returns (before, after)."""
    git(repo, "config", "user.name", "mb")
    git(repo, "config", "user.email", "mb")
    commit(repo, {"se.toml": PROJECT_IDENTITY})
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main:se")
    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    commit(repo, {"a.txt": "a\n"}, message)
    git(repo, "push", "-q", "origin", "main:se")
    return before, git(repo, "rev-parse", "HEAD").stdout.strip()


def run_ci(tmp_path: Path, before: str, after: str) -> subprocess.CompletedProcess[str]:
    """The workflow's step as its runner runs it: in a fresh full clone, on a push to se."""
    runner = tmp_path / "runner"
    shutil.rmtree(runner, ignore_errors=True)
    git(tmp_path, "clone", "-q", "-b", "se", str(tmp_path / "remote.git"), str(runner))
    env = {**os.environ, "BEFORE": before, "AFTER": after, "BRANCH": "se"}
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
    git(repo, "push", "-q", "origin", "main:se")
    result = run_ci(tmp_path, before, git(repo, "rev-parse", "HEAD").stdout.strip())
    assert result.returncode == 0, result.stdout
    assert "1 allow entries used" in result.stdout


def test_ci_passes_a_clean_push(repo: Path, tmp_path: Path) -> None:
    before, after = owner_push(repo, tmp_path, "Fix the build")
    assert run_ci(tmp_path, before, after).returncode == 0
