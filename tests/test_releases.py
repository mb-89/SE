"""work_tickets.py push releases the integration branch: it bumps se.toml's version and tags it."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def settings(version: str | None) -> str:
    line = f'version = "{version}"\n' if version is not None else ""
    return f"[project]\n# the released version\n{line}public_check = false\n"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch) -> Path:
    """A clone of a bare origin on main, the integration branch, with se.toml at 1.2.3 tagged."""
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: tmp_path / "no-local.toml")
    origin, root = tmp_path / "origin.git", tmp_path / "main"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(root)], check=True,
                   capture_output=True)
    git(root, "config", "user.name", "mb")
    git(root, "config", "user.email", "mb")
    (root / "se.toml").write_text(settings("1.2.3"), encoding="utf-8")
    git(root, "add", "se.toml")
    git(root, "commit", "-q", "-m", "base")
    git(root, "tag", "v1.2.3")
    git(root, "push", "-q", "origin", "main", "v1.2.3")
    return root


def issue_body(breaking: bool) -> str:
    return f"## Goal\n\nx\n\n## Package kind\n\nStandard{', breaking' if breaking else ''}.\n"


def integrate(root: Path, branch: str, breaking: bool = False, trailer: str | None = None) -> None:
    """Merge `branch` as integrate does: its trailer from work_tickets.release_trailer, unless given."""
    git(root, "switch", "-q", "-c", branch)
    (root / f"{branch.replace('/', '-')}.txt").write_text(branch, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", branch)
    git(root, "switch", "-q", "main")
    trailer = work_tickets.release_trailer(branch, issue_body(breaking)) if trailer is None else trailer
    git(root, "merge", "-q", "--no-ff", "-m", f"Integrate {branch}: work",
        *(("-m", trailer) if trailer else ()), branch)


def push(root: Path) -> int:
    return work_tickets.main(["push", "--worktree", str(root)])


def released(root: Path) -> tuple[str, str]:
    """The version in se.toml on origin's main and origin's newest tag."""
    origin = root.parent / "origin.git"
    text = subprocess.run(["git", "--git-dir", str(origin), "show", "main:se.toml"],
                          capture_output=True, text=True, check=True).stdout
    tags = subprocess.run(["git", "--git-dir", str(origin), "tag", "--sort=-v:refname"],
                          capture_output=True, text=True, check=True).stdout.split()
    return text.split('version = "')[1].split('"')[0], tags[0]


@pytest.mark.parametrize(("branch", "breaking", "version"), [
    ("feature/topic-20261106", False, "1.3.0"),
    ("fix/topic-20261106", False, "1.2.4"),
    ("perf/topic-20261106", False, "1.2.4"),
    ("chore/topic-20261106", False, "1.2.4"),
    ("docs/topic-20261106", False, "1.2.4"),
    ("fix/topic-20261106", True, "2.0.0"),
])
def test_each_package_kind_bumps_its_part_and_the_tag_is_pushed_with_the_merge(
        checkout, capsys, branch, breaking, version):
    integrate(checkout, branch, breaking)
    assert push(checkout) == 0
    assert released(checkout) == (version, f"v{version}")
    assert git(checkout, "rev-parse", f"v{version}") == git(checkout, "rev-parse", "origin/main")
    assert git(checkout, "log", "-1", "--format=%s", "main") == f"Release v{version}"
    assert (checkout / "se.toml").read_text(encoding="utf-8") == settings(version)
    assert f"Release: v{version} (" in capsys.readouterr().out


def test_several_integrations_release_once_by_the_highest_kind(checkout):
    integrate(checkout, "fix/one-20261106")
    integrate(checkout, "feature/two-20261106")
    integrate(checkout, "docs/three-20261106")
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")
    # Pushing again releases nothing new: the integrations are behind the tag.
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")


def test_a_failed_push_is_retried_without_a_second_bump(checkout, monkeypatch):
    integrate(checkout, "feature/topic-20261106")
    real = work_tickets.run_git_push
    refusals = [subprocess.CompletedProcess(["git", "push"], 1, "", "error: permission denied (403)")]
    monkeypatch.setattr(work_tickets, "run_git_push",
                        lambda root, arguments: refusals.pop() if refusals else real(root, arguments))
    assert push(checkout) == 1
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")


def test_an_untagged_version_is_tagged_as_it_is(checkout, capsys):
    (checkout / "se.toml").write_text(settings("2.0.0"), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "start at 2.0.0")
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert released(checkout) == ("2.0.0", "v2.0.0")
    assert "v2.0.0 tagged, the first tag of project.version" in capsys.readouterr().out


def test_other_branches_and_merges_release_nothing(checkout, capsys):
    integrate(checkout, "feature/topic-20261106")
    git(checkout, "switch", "-q", "-c", "fix/other-20261106")
    assert work_tickets.main(["push", "fix/other-20261106", "--worktree", str(checkout)]) == 0
    git(checkout, "switch", "-q", "main")
    git(checkout, "reset", "-q", "--hard", "origin/main")
    integrate(checkout, "side", trailer="")  # a merge named like no integration
    git(checkout, "commit", "-q", "--amend", "-m", "Merge branch 'side'")
    assert push(checkout) == 0
    assert released(checkout) == ("1.2.3", "v1.2.3")
    assert "is no integration; it bumps nothing" in capsys.readouterr().out


def release_trailer(tmp_path: Path, branch: str, breaking: bool) -> int:
    body = tmp_path / "issue.md"
    body.write_text(issue_body(breaking), encoding="utf-8")
    return work_tickets.main(["release-trailer", branch, "--issue-body", str(body)])


def test_an_unknown_branch_prefix_is_refused_before_anything_is_merged(tmp_path, capsys):
    assert release_trailer(tmp_path, "refactor/topic-20261106", False) == 1
    error = capsys.readouterr().err
    assert "Cannot release refactor/topic-20261106: its prefix 'refactor' names no package kind" in error
    assert "feature, feat, fix, perf, chore, docs" in error
    assert "nothing was merged" in error


def test_a_breaking_package_integrated_by_hand_releases_major(checkout, tmp_path, capsys):
    assert release_trailer(tmp_path, "fix/topic-20261106", True) == 0
    trailer = capsys.readouterr().out.strip()
    assert trailer == "Release-kind: major"
    integrate(checkout, "fix/topic-20261106", trailer=trailer)
    assert push(checkout) == 0
    assert released(checkout) == ("2.0.0", "v2.0.0")


@pytest.mark.parametrize(("trailer", "stated"), [
    ("", "states no kind"),
    ("Breaking-change: yes", "states no kind"),
    ("Release-kind: breaking", "states 'breaking'"),
    ("Release-kind: minor\nRelease-kind: major", "states 'minor', 'major'"),
])
def test_a_merge_whose_kind_cannot_be_told_is_refused_with_the_remedy(checkout, capsys, trailer, stated):
    integrate(checkout, "fix/topic-20261106", trailer=trailer)
    before = git(checkout, "rev-parse", "HEAD")
    assert push(checkout) == 1
    assert git(checkout, "rev-parse", "HEAD") == before
    assert released(checkout) == ("1.2.3", "v1.2.3")
    error = capsys.readouterr().err
    assert f"Cannot release merge {before[:7]} (Integrate fix/topic-20261106: work): it {stated}" in error
    assert ("Reword the merge to end with one trailer Release-kind: major|minor|patch, as "
            "work_tickets.py release-trailer <branch> --issue-body <file> prints it") in error


def test_without_a_version_push_says_how_to_release(checkout, capsys):
    (checkout / "se.toml").write_text(settings(None), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "no version")
    assert push(checkout) == 0
    assert (f"Release off: no project.version in {checkout / 'se.toml'}; write it as "
            'version = "MAJOR.MINOR.PATCH" under [project]') in capsys.readouterr().out


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "01.2.3", "1.2.3-rc1", "", 1])
def test_a_malformed_version_is_an_error_naming_the_file_and_the_remedy(checkout, capsys, version):
    value = f'"{version}"' if isinstance(version, str) else str(version)
    (checkout / "se.toml").write_text(f"[project]\nversion = {value}\npublic_check = false\n",
                                      encoding="utf-8")
    assert push(checkout) == 1
    error = capsys.readouterr().err
    assert f"project.version in {checkout / 'se.toml'} is {version!r}, not MAJOR.MINOR.PATCH" in error
    assert 'write it as version = "MAJOR.MINOR.PATCH" under [project]' in error


@pytest.mark.parametrize(("kind", "breaking"), [
    ("Standard, medium.", False),
    ("Standard, medium, **breaking**: removes the old flag.", True),
    ("<!-- mark a breaking change here -->\nStandard.", False),
])
def test_the_work_issue_marks_a_breaking_change_in_its_package_kind(kind, breaking):
    assert work_tickets.is_breaking(f"## Goal\n\nx\n\n## Package kind\n\n{kind}\n\n## Blocked by\n") is breaking


def by_workflow(root: Path, version: str = "1.2.3") -> None:
    (root / "se.toml").write_text(settings(version) + 'release = "workflow"\n', encoding="utf-8")
    git(root, "commit", "-q", "-am", "release by workflow")


def origin_tags(root: Path) -> list[str]:
    return subprocess.run(["git", "--git-dir", str(root.parent / "origin.git"), "tag"],
                          capture_output=True, text=True, check=True).stdout.split()


def test_with_release_by_workflow_push_bumps_and_pushes_the_branch_only(checkout, capsys):
    by_workflow(checkout)
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert origin_tags(checkout) == ["v1.2.3"]
    assert git(checkout, "show", "origin/main:se.toml").count('version = "1.3.0"') == 1
    assert git(checkout, "log", "-1", "--format=%s", "origin/main") == "Release v1.3.0"
    out = capsys.readouterr().out
    assert ("Release: v1.3.0 is tagged by the release workflow (.github/workflows/release.yml of se) "
            "on its push, as se.toml [project] release = \"workflow\" says") in out


def test_with_release_by_workflow_an_untagged_version_waits_for_the_workflow(checkout, capsys):
    by_workflow(checkout, "2.0.0")
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert origin_tags(checkout) == ["v1.2.3"]
    assert git(checkout, "tag", "--list", "v2.0.0") == ""
    assert git(checkout, "rev-parse", "origin/main") == git(checkout, "rev-parse", "main")
    assert "Release: v2.0.0 is tagged by the release workflow" in capsys.readouterr().out


def test_another_release_setting_is_an_error_naming_the_file(checkout, capsys):
    (checkout / "se.toml").write_text(settings("1.2.3") + 'release = "manual"\n', encoding="utf-8")
    assert push(checkout) == 1
    assert (f"project.release in {checkout / 'se.toml'} is 'manual'; set it to \"workflow\" or remove it"
            in capsys.readouterr().err)


def test_a_pushed_merge_without_a_kind_is_never_read_again(checkout, capsys):
    """Integrations pushed before the trailer existed are behind origin: push reads none of them."""
    integrate(checkout, "fix/old-20261106", trailer="")
    git(checkout, "push", "-q", "origin", "main")
    integrate(checkout, "feature/new-20261106")
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")
    assert "Release: v1.3.0 (minor: feature/new-20261106)" in capsys.readouterr().out


def test_with_release_by_workflow_a_stale_local_tag_causes_no_bump(checkout, capsys):
    """The released versions are origin's tags: a local tag origin lacks releases nothing."""
    by_workflow(checkout, "2.0.0")
    git(checkout, "push", "-q", "origin", "main")
    git(checkout, "tag", "v2.0.0")  # stale: origin has no v2.0.0
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert git(checkout, "show", "origin/main:se.toml").count('version = "2.0.0"') == 1
    assert git(checkout, "log", "-1", "--format=%s", "origin/main") == "Integrate feature/topic-20261106: work"
    assert origin_tags(checkout) == ["v1.2.3"]
    assert "Release: v2.0.0 is tagged by the release workflow" in capsys.readouterr().out


def test_with_release_by_workflow_origin_tags_count_without_local_ones(checkout):
    """A checkout without the tags locally still releases from origin's, and makes no local tag."""
    by_workflow(checkout)
    git(checkout, "tag", "-d", "v1.2.3")
    integrate(checkout, "fix/topic-20261106")
    assert push(checkout) == 0
    assert git(checkout, "log", "-1", "--format=%s", "origin/main") == "Release v1.2.4"
    assert git(checkout, "tag", "--list") == ""


def plugin_checkout(checkout: Path, build: list[str]) -> Path:
    """The checkout made an se plugin: se's sources and generator, its layouts built and pushed."""
    shutil.copytree(PROJECT / "src", checkout / "src")
    (checkout / "scripts").mkdir()
    shutil.copy2(PROJECT / "scripts" / "se_plugin.py", checkout / "scripts" / "se_plugin.py")
    (checkout / "se.toml").write_text(
        settings("1.2.3") + f"release_build = {json.dumps(build)}\n", encoding="utf-8")
    plugin("build", checkout)
    git(checkout, "add", ".")
    git(checkout, "commit", "-q", "-m", "plugin")
    git(checkout, "push", "-q", "origin", "main")
    return checkout


def plugin(command: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(root / "scripts" / "se_plugin.py"), command, "--root", str(root)],
                          capture_output=True, text=True, check=False)


def test_the_release_commit_carries_what_release_build_regenerates(checkout):
    plugin_checkout(checkout, [sys.executable, "scripts/se_plugin.py", "build"])
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 0
    assert git(checkout, "log", "-1", "--format=%s", "origin/main") == "Release v1.3.0"
    assert git(checkout, "status", "--porcelain") == ""
    assert plugin("check", checkout).returncode == 0
    manifest = json.loads(git(checkout, "show", "origin/main:.claude-plugin/plugin.json"))
    assert manifest["version"] == "1.3.0"


def test_se_regenerates_its_plugin_in_each_release_commit():
    project = tomllib.loads((PROJECT / "se.toml").read_text(encoding="utf-8"))["project"]
    assert project["release_build"][-2:] == ["scripts/se_plugin.py", "build"]


def test_a_failing_release_build_restores_se_toml_and_commits_nothing(checkout, capsys):
    plugin_checkout(checkout, [sys.executable, "-c", "raise SystemExit('generator broke')"])
    integrate(checkout, "feature/topic-20261106")
    before = git(checkout, "rev-parse", "HEAD")
    assert push(checkout) == 1
    assert git(checkout, "rev-parse", "HEAD") == before
    assert git(checkout, "status", "--porcelain") == ""
    error = capsys.readouterr().err
    assert "Cannot release v1.3.0: project.release_build (" in error
    assert "se.toml is restored and nothing was committed" in error
    assert "generator broke" in error


def test_a_malformed_release_build_is_an_error_naming_the_file(checkout, capsys):
    (checkout / "se.toml").write_text(settings("1.2.3") + 'release_build = "make"\n', encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "malformed")
    integrate(checkout, "feature/topic-20261106")
    assert push(checkout) == 1
    assert (f"project.release_build in {checkout / 'se.toml'} must be a non-empty argument array"
            in capsys.readouterr().err)


WORKFLOW = PROJECT / ".github" / "workflows" / "release.yml"


def workflow_script() -> str:
    """The Python the release workflow runs, its one `run: |` block."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "run: |") + 1
    block = []
    for line in lines[start:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block) + "\n"


def run_workflow(checkout: Path, ref: str = "main") -> subprocess.CompletedProcess[str]:
    """Run the workflow as its runner does: in a fresh full clone of origin, on a push of `ref`."""
    runner = checkout.parent / "runner"
    shutil.rmtree(runner, ignore_errors=True)
    subprocess.run(["git", "clone", "-q", "-b", ref, str(checkout.parent / "origin.git"), str(runner)],
                   check=True, capture_output=True)
    script = checkout.parent / "release.py"
    script.write_text(workflow_script(), encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(script)], cwd=runner, capture_output=True, text=True,
                          check=False, env={**os.environ, "GITHUB_REF_NAME": ref})


def origin_tag(checkout: Path, tag: str) -> str:
    return git(checkout.parent / "origin.git", "rev-parse", f"{tag}^{{commit}}")


def missed_release(checkout: Path) -> str:
    """1.3.0 integrated but never tagged, then 1.3.1 tagged: SE's missed v1.0.0. Its first commit."""
    by_workflow(checkout)
    git(checkout, "switch", "-q", "-c", "feature/topic-20261106")
    (checkout / "se.toml").write_text(settings("1.3.0") + 'release = "workflow"\n', encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "bump in the branch")
    git(checkout, "switch", "-q", "main")
    git(checkout, "merge", "-q", "--no-ff", "-m", "Integrate feature/topic-20261106: work", "feature/topic-20261106")
    first = git(checkout, "rev-parse", "HEAD")
    (checkout / "note.txt").write_text("x", encoding="utf-8")
    git(checkout, "add", ".")
    git(checkout, "commit", "-q", "-m", "still 1.3.0")
    (checkout / "se.toml").write_text(settings("1.3.1") + 'release = "workflow"\n', encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "Release v1.3.1")
    git(checkout, "tag", "v1.3.1")
    git(checkout, "push", "-q", "origin", "main", "v1.3.1")
    return first


def test_the_workflow_backfills_a_missed_version_on_its_first_commit(checkout):
    first = missed_release(checkout)
    before = {tag: origin_tag(checkout, tag) for tag in ("v1.2.3", "v1.3.1")}
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert f"Release v1.3.0: tagged {first[:7]}" in result.stdout
    assert origin_tag(checkout, "v1.3.0") == first
    assert {tag: origin_tag(checkout, tag) for tag in before} == before


def test_a_second_workflow_run_changes_nothing(checkout):
    missed_release(checkout)
    assert run_workflow(checkout).returncode == 0
    tags = git(checkout.parent / "origin.git", "show-ref", "--tags")
    second = run_workflow(checkout)
    assert second.returncode == 0, second.stderr + second.stdout
    assert second.stdout.splitlines() == [line for line in second.stdout.splitlines() if "tagged already" in line]
    assert git(checkout.parent / "origin.git", "show-ref", "--tags") == tags


def test_the_workflow_never_moves_an_existing_tag(checkout):
    by_workflow(checkout, "1.3.0")
    stray = git(checkout, "rev-parse", "HEAD~1")
    git(checkout, "tag", "v1.3.0", stray)
    git(checkout, "push", "-q", "origin", "main", "v1.3.0")
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "::warning::Release v1.3.0: the tag names" in result.stdout
    assert origin_tag(checkout, "v1.3.0") == stray


def test_the_workflow_tags_nothing_on_another_branch(checkout):
    missed_release(checkout)
    git(checkout, "push", "-q", "origin", "main:fix/other-20261106")
    result = run_workflow(checkout, "fix/other-20261106")
    assert result.returncode == 0
    assert "No release: fix/other-20261106 is not the integration branch main" in result.stdout
    assert origin_tags(checkout) == ["v1.2.3", "v1.3.1"]


def test_se_runs_the_release_workflow_on_pushes_to_its_integration_branch_only():
    project = tomllib.loads((PROJECT / "se.toml").read_text(encoding="utf-8"))["project"]
    caller = (PROJECT / ".github" / "workflows" / "release-tag.yml").read_text(encoding="utf-8")
    assert f"on:\n  push:\n    branches: [{project['integration_branch']}]\n" in caller
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    shown = readme.split("`.github/workflows/release-tag.yml`", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    own = caller.split("\n", 1)[1].replace(f"[{project['integration_branch']}]", "[<integration branch>]")
    assert shown == own
