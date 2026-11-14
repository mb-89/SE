"""work_tickets.py push releases the integration branch: it bumps se.toml's version and tags it."""
import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest
import fake_git
import git_door


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)


def git(root: Path, *arguments: str) -> str:
    result = git_door.run(*arguments, root=root)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


IDENTITY = 'identity = "mb <mb>"\n'


def settings(version: str | None) -> str:
    line = f'version = "{version}"\n' if version is not None else ""
    return f"[project]\n# the released version\n{line}public_check = false\n{IDENTITY}"


def build_checkout(tmp_path: Path) -> None:
    origin, root = tmp_path / "origin.git", tmp_path / "main"
    fake_git.init(origin, "--bare", "-b", "main")
    fake_git.clone(origin, root)
    git(root, "config", "user.name", "mb")
    git(root, "config", "user.email", "mb")
    (root / "se.toml").write_text(settings("1.2.3"), encoding="utf-8")
    git(root, "add", "se.toml")
    git(root, "commit", "-q", "-m", "base")
    git(root, "tag", "v1.2.3")
    git(root, "push", "-q", "origin", "main", "v1.2.3")


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch, fake_git_door) -> Path:
    """A clone of a bare origin on main, the integration branch, with se.toml at 1.2.3 tagged, on
    the git door's fake."""
    monkeypatch.setattr(work_tickets, "local_config_path", lambda: tmp_path / "no-local.toml")
    build_checkout(tmp_path)
    return tmp_path / "main"


def issue_body(breaking: bool) -> str:
    return f"## Goal\n\nx\n\n## Package kind\n\nStandard{', breaking' if breaking else ''}.\n"


def declared(kind: str, removed: str = "None") -> str:
    """A field report's header and Removed behaviour section declaring `kind`."""
    return (f"**Release kind:** {kind} — what changed\n\n"
            f"## Removed behaviour, deleted or weakened tests, and authored prose\n\n{removed}\n")


def commit_on(root: Path, branch: str, text: str) -> str:
    """Commit `text` on `branch` (created where missing), back on main; returns the commit."""
    present = git_door.run("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", root=root)
    git(root, "switch", "-q", branch) if present.returncode == 0 else git(root, "switch", "-q", "-c", branch)
    (root / f"{branch.replace('/', '-')}.txt").write_text(text, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", text)
    commit = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "main")
    return commit


def integrate(root: Path, branch: str, breaking: bool = False, trailer: str | None = None,
              text: str | None = None, report: str | None = None) -> None:
    """Merge `branch` as integrate does: its trailer from work_tickets.release_trailer, unless given."""
    commit_on(root, branch, text or branch)
    if trailer is None:
        if report is None:
            report = declared(work_tickets.default_release_kind(branch, issue_body(breaking)))
        trailer = work_tickets.release_trailer(root, branch, issue_body(breaking), report)
    git(root, "merge", "-q", "--no-ff", "-m", f"Integrate {branch}: work",
        *(("-m", trailer) if trailer else ()), branch)


def push(root: Path) -> int:
    """work_tickets.py push, after the suite passed on HEAD (its verdict recorded as suite does)."""
    work_tickets.sibling("verdicts").record(root, "suite", "HEAD", True)
    return work_tickets.main(["push", "--worktree", str(root)])


def released(root: Path) -> tuple[str, str]:
    """The version in se.toml on origin's main and origin's newest tag."""
    origin = root.parent / "origin.git"
    text = git(origin, "show", "main:se.toml")
    return text.split('version = "')[1].split('"')[0], newest(origin_tags(root))


def newest(tags: list[str]) -> str:
    """The highest of the version tags `tags`, as `git tag --sort=-v:refname` lists it first."""
    return max(tags, key=lambda tag: tuple(int(part) for part in re.findall(r"\d+", tag)))


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
    refusals = [subprocess.CompletedProcess(["push"], 1, "", "error: permission denied (403)")]
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


def release_trailer(root: Path, branch: str, breaking: bool, *arguments: str) -> int:
    body = root.parent / "issue.md"
    body.write_text(issue_body(breaking), encoding="utf-8")
    return work_tickets.main(["release-trailer", branch, "--issue-body", str(body),
                              "--worktree", str(root), *arguments])


def test_the_declared_kind_wins_over_the_branch_prefix(checkout, capsys):
    integrate(checkout, "fix/topic-20261106", report=declared("minor"))
    integrate(checkout, "refactor/other-20261106", report=declared("patch"))
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")


@pytest.mark.parametrize(("report", "refusal"), [
    (None, "no field report given; pass --pr-description <file>, the pull request description "
           "that carries it"),
    ("**Branch tip:** `abc1234`\n", "Release kind is missing; write **Release kind:**"),
    ("**Release kind:** big — x\n", "Release kind 'big' must be one of patch, minor, major"),
    ("**Release kind:** minor\n", "Release kind needs a one-line reason after the kind"),
    (declared("minor", "- **Breaking:** renamed the --all option to --every"),
     "Release kind is minor, but section \"## Removed behaviour, deleted or weakened tests, and "
     "authored prose\" lists a breaking change, which is major: - **Breaking:** renamed the --all "
     "option to --every"),
])
def test_a_missing_unknown_or_too_small_kind_is_refused_before_anything_is_merged(
        checkout, report, refusal):
    with pytest.raises(work_tickets.QueueError) as error:
        work_tickets.release_trailer(checkout, "fix/topic-20261106", issue_body(False), report)
    assert refusal in str(error.value)
    assert str(error.value).endswith("nothing was merged")


def test_a_work_issue_marked_breaking_refuses_a_smaller_declared_kind(checkout):
    with pytest.raises(work_tickets.QueueError, match="Release kind is minor, but the work "
                       "issue's Package kind marks a breaking change, which is major"):
        work_tickets.release_trailer(checkout, "fix/topic-20261106", issue_body(True),
                                     declared("minor"))


def test_a_breaking_removal_declared_major_releases_major(checkout):
    integrate(checkout, "fix/topic-20261106",
              report=declared("major", "- **Breaking:** made the `kind` field required"))
    assert push(checkout) == 0
    assert released(checkout) == ("2.0.0", "v2.0.0")


def test_a_breaking_package_integrated_by_hand_releases_major(checkout, capsys):
    tip = commit_on(checkout, "fix/topic-20261106", "reported")
    assert release_trailer(checkout, "fix/topic-20261106", True,
                           "--pr-description", report_at(checkout, tip, "major")) == 0
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
            "work_tickets.py release-trailer <branch> --issue-body <file> --pr-description <file> "
            "prints it from the field report in the pull request description") in error


def test_a_second_integration_of_a_branch_releases_a_patch_and_the_first_its_kind(checkout):
    integrate(checkout, "feature/topic-20261106")
    assert release_kind(checkout) == "minor"
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")
    integrate(checkout, "feature/topic-20261106", text="a late prose fix")
    assert release_kind(checkout) == "patch"
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.1", "v1.3.1")


def release_kind(root: Path) -> str:
    """The Release-kind trailer of HEAD's message."""
    message = git(root, "log", "-1", "--format=%B")
    return "\n".join(line.partition(": ")[2] for line in message.splitlines() if line.startswith("Release-kind: "))


def squash_on_origin(root: Path, branch: str, text: str, trailer: str) -> None:
    """Land `branch` as a squash pull request does: one commit on origin's main with the
    `Integrate <branch>` subject and `trailer`, then fetched and fast-forwarded into main."""
    commit_on(root, branch, text)
    squash = git(root, "commit-tree", f"{branch}^{{tree}}", "-p", "main", "-m", f"Integrate {branch}: work",
                 "-m", trailer)
    git(root, "push", "-q", "origin", f"{squash}:refs/heads/main")
    git(root, "fetch", "-q", "origin")
    git(root, "merge", "-q", "--ff-only", "origin/main")


def test_a_squash_landed_integration_counts_as_integrated_and_releases_its_kind(checkout):
    squash_on_origin(checkout, "feature/topic-20261106", "work", "Release-kind: minor")
    # A later integration of the same branch is a re-integration: the squash commit counts.
    assert work_tickets.integrated_before(checkout, "feature/topic-20261106")
    assert work_tickets.release_trailer(
        checkout, "feature/topic-20261106", issue_body(False), declared("minor")) == "Release-kind: patch"
    # The squash commit's trailer is the kind a release counts, as the merge commit's was.
    assert work_tickets.integrated_packages(checkout, "main", "v1.2.3", "refs/tags/v1.2.3") == [
        ("feature/topic-20261106", "minor")]


def test_push_of_a_landing_branch_releases_against_origin_s_main_and_waits_with_the_tag(
        checkout, capsys):
    git(checkout, "switch", "-q", "-c", "land/feature/topic-20261106")
    integrate(checkout, "feature/topic-20261106")
    git(checkout, "switch", "-q", "land/feature/topic-20261106")
    git(checkout, "merge", "-q", "--ff-only", "main")
    assert push(checkout) == 0
    origin = checkout.parent / "origin.git"
    shown = git_door.run("show", "land/feature/topic-20261106:se.toml", root=origin).stdout
    assert shown == settings("1.3.0")
    assert "v1.3.0" not in origin_tags(checkout)
    assert "Release: tag v1.3.0 once the squash commit is on main" in capsys.readouterr().out


def test_a_re_integration_releases_the_kind_its_own_report_states(checkout, capsys):
    integrate(checkout, "fix/topic-20261106")
    report = "**Branch tip:** `abc1234`  **Re-integration kind:** minor\n"
    integrate(checkout, "fix/topic-20261106", text="more", report=report)
    assert push(checkout) == 0
    assert released(checkout) == ("1.3.0", "v1.3.0")
    with pytest.raises(work_tickets.QueueError, match="Re-integration kind 'big'; write one of"):
        work_tickets.release_trailer(checkout, "fix/topic-20261106", issue_body(False),
                                     "**Re-integration kind:** big\n")


def report_at(root: Path, tip: str, kind: str = "patch") -> str:
    """A pull request description whose field report describes the branch at `tip`."""
    path = root.parent / "description.md"
    path.write_text(f"Fixes https://git.example/owner/repo/issues/5\n\n{work_tickets.REPORT_BEGIN}\n"
                    f"**Branch tip:** `{tip}`  **Re-integration kind:** patch\n{declared(kind)}"
                    f"{work_tickets.REPORT_END}\n", encoding="utf-8")
    return str(path)


def test_release_trailer_refuses_a_pull_request_description_without_a_report(checkout, capsys):
    tip = commit_on(checkout, "fix/topic-20261106", "reported")
    path = Path(report_at(checkout, tip))
    path.write_text(path.read_text(encoding="utf-8").replace(work_tickets.REPORT_END, ""),
                    encoding="utf-8")
    assert release_trailer(checkout, "fix/topic-20261106", False, "--pr-description", str(path)) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "holds no field report" in captured.err


def test_release_trailer_passes_a_branch_at_its_reported_tip(checkout, capsys):
    tip = commit_on(checkout, "fix/topic-20261106", "reported")
    assert release_trailer(checkout, "fix/topic-20261106", False,
                           "--pr-description", report_at(checkout, tip)) == 0
    assert capsys.readouterr().out.strip() == "Release-kind: patch"


def test_release_trailer_reads_a_branch_only_origin_has(checkout, capsys):
    tip = commit_on(checkout, "fix/topic-20261106", "reported")
    git(checkout, "push", "-q", "origin", "fix/topic-20261106")
    git(checkout, "branch", "-q", "-D", "fix/topic-20261106")
    report = report_at(checkout, tip)
    assert release_trailer(checkout, "fix/topic-20261106", False, "--pr-description", report) == 0
    assert capsys.readouterr().out.strip() == "Release-kind: patch"


def test_release_trailer_prefers_the_local_branch_to_origin(checkout, capsys):
    pushed = commit_on(checkout, "fix/topic-20261106", "pushed")
    git(checkout, "push", "-q", "origin", "fix/topic-20261106")
    local = commit_on(checkout, "fix/topic-20261106", "local only")
    assert release_trailer(checkout, "fix/topic-20261106", False,
                           "--pr-description", report_at(checkout, local)) == 0
    assert capsys.readouterr().out.strip() == "Release-kind: patch"
    assert release_trailer(checkout, "fix/topic-20261106", False,
                           "--pr-description", report_at(checkout, pushed)) == 1
    assert "- " + local[:7] + " local only" in capsys.readouterr().err


def test_release_trailer_without_the_branch_names_both_refs_and_the_fetch(checkout, capsys):
    report = report_at(checkout, git(checkout, "rev-parse", "HEAD"))
    assert release_trailer(checkout, "fix/topic-20261106", False, "--pr-description", report) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ("Cannot find branch fix/topic-20261106: neither fix/topic-20261106 nor "
            "origin/fix/topic-20261106 exists") in captured.err
    assert "fetch origin fix/topic-20261106" in captured.err


def test_release_trailer_refuses_a_commit_after_the_reported_tip_naming_it(checkout, capsys):
    tip = commit_on(checkout, "fix/topic-20261106", "reported")
    late = commit_on(checkout, "fix/topic-20261106", "pushed after delivery")
    git(checkout, "merge", "-q", "--no-ff", "-m", "unrelated", commit_on(checkout, "side", "x"))
    git(checkout, "switch", "-q", "fix/topic-20261106")
    git(checkout, "merge", "-q", "--no-ff", "-m", "sync main", "main")  # a sync adds nothing late
    git(checkout, "switch", "-q", "main")
    report = report_at(checkout, tip)
    assert release_trailer(checkout, "fix/topic-20261106", False, "--pr-description", report) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (f"Branch fix/topic-20261106 has commits after the field report's Branch tip "
            f"{tip[:12]}:\n- {late[:7]} pushed after delivery\nNothing was merged.") in captured.err
    assert "the worker updates the field report in place" in captured.err
    assert "--include-late <reason>" in captured.err
    assert release_trailer(checkout, "fix/topic-20261106", False, "--pr-description", report,
                           "--include-late", "the late commit fixes a typo the review asked for") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "Release-kind: patch"
    assert "Includes 1 commit(s) after the field report's Branch tip: the late commit" in captured.err


def test_without_a_version_push_says_how_to_release(checkout, capsys):
    (checkout / "se.toml").write_text(settings(None), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "no version")
    assert push(checkout) == 0
    assert (f"Release off: no project.version in {checkout / 'se.toml'}; write it as "
            'version = "MAJOR.MINOR.PATCH" under [project]') in capsys.readouterr().out


def test_a_clone_with_a_foreign_identity_releases_with_the_project_identity(checkout, monkeypatch):
    git(checkout, "config", "user.name", "agent")
    git(checkout, "config", "user.email", "agent@example.com")
    integrate(checkout, "fix/topic-20261106")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "agent@example.com")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "agent@example.com")
    assert push(checkout) == 0
    assert git(checkout, "log", "-1", "--format=%s|%an <%ae>|%cn <%ce>", "origin/main") == (
        "Release v1.2.4|mb <mb>|mb <mb>")


def test_without_an_identity_push_refuses_naming_the_setting_and_sync(checkout, capsys):
    (checkout / "se.toml").write_text(settings("1.2.3").replace(IDENTITY, ""), encoding="utf-8")
    git(checkout, "commit", "-q", "-am", "no identity")
    integrate(checkout, "fix/topic-20261106")
    before = git(checkout, "rev-parse", "origin/main")
    assert push(checkout) == 1
    error = capsys.readouterr().err
    assert (f'work_tickets.py push: no commit identity; set identity = "Name <email>" in [project] '
            f"of {checkout / 'se.toml'}") in error and "run work_tickets.py sync" in error
    git(checkout, "fetch", "-q", "origin")
    assert git(checkout, "rev-parse", "origin/main") == before
    assert git(checkout, "log", "-1", "--format=%s") == "Integrate fix/topic-20261106: work"


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "01.2.3", "1.2.3-rc1", "", 1])
def test_a_malformed_version_is_an_error_naming_the_file_and_the_remedy(checkout, capsys, version):
    value = f'"{version}"' if isinstance(version, str) else str(version)
    (checkout / "se.toml").write_text(f"[project]\nversion = {value}\npublic_check = false\n{IDENTITY}",
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
    return git(root.parent / "origin.git", "tag", "--list").split()


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
    for name in ("se_plugin.py", "agent_lint.py"):  # the generator and the validators it loads
        shutil.copy2(PROJECT / "scripts" / name, checkout / "scripts" / name)
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


class Workflow:
    """A run of the release workflow's script, as its runner runs it (a fresh full clone of
    origin, on a push of a ref), in this process: the script's `subprocess.run` of git goes through
    the git door to the test's fake. `refused` stands in for GitHub's ruleset: origin refuses a
    push of that ref, `why`. `pushed` is each ref the script pushed, one push each."""

    def __init__(self, checkout: Path, ref: str, refused: str, why: str) -> None:
        self.checkout, self.ref, self.refused, self.why = checkout, ref, refused, why
        self.pushed: list[str] = []
        self.returncode, self.stdout, self.stderr = 0, "", ""

    def run(self, argv, *, capture_output=False, text=False, check=False, **_):
        assert argv[0] == "git" and capture_output and text, argv
        arguments = list(argv[1:])
        if arguments[0] == "push":
            self.pushed.append(arguments[-1])
            if arguments[-1].lstrip("+") == self.refused:
                return subprocess.CompletedProcess(argv, 1, "", f"remote: Cannot create {self.refused}: "
                                                   f"{self.why}\n ! [remote rejected] {self.refused}\n")
        done = git_door.run(*arguments, cwd=Path.cwd())
        if check and done.returncode != 0:
            raise subprocess.CalledProcessError(done.returncode, argv, done.stdout, done.stderr)
        return subprocess.CompletedProcess(argv, done.returncode, done.stdout, done.stderr)


def run_workflow(checkout: Path, ref: str = "main", refused: str = "",
                 why: str = "a tag ruleset forbids it") -> Workflow:
    """Run the workflow's script on a push of `ref` (Workflow)."""
    runner = checkout.parent / "runner"
    shutil.rmtree(runner, ignore_errors=True)
    fake_git.clone(checkout.parent / "origin.git", runner, "-b", ref)
    workflow = Workflow(checkout, ref, refused, why)
    out, err = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subprocess, "run", workflow.run)
        patch.setenv("GITHUB_REF_NAME", ref)
        patch.chdir(runner)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(compile(workflow_script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
        except SystemExit as exited:
            workflow.returncode = exited.code if isinstance(exited.code, int) else int(bool(exited.code))
    workflow.stdout, workflow.stderr = out.getvalue(), err.getvalue()
    return workflow


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


def test_the_workflow_creates_the_major_tag_of_its_own_release_only(checkout):
    missed_release(checkout)
    older = git(checkout, "rev-parse", "v1.2.3")
    git(checkout, "tag", "v0.9.0", older)
    git(checkout, "push", "-q", "origin", "v0.9.0")
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    newest = origin_tag(checkout, "v1.3.1")
    assert f"Release v1: moved to {newest[:7]} (v1.3.1)" in result.stdout
    assert origin_tag(checkout, "v1") == newest
    assert "v0" not in origin_tags(checkout)


def next_major(checkout: Path) -> None:
    """se since 4.0: older majors released without their major tag, the newest release 4.4.0 untagged."""
    git(checkout, "tag", "v3.1.0", "v1.2.3")
    git(checkout, "push", "-q", "origin", "v3.1.0")
    by_workflow(checkout, "4.4.0")
    git(checkout, "push", "-q", "origin", "main")


def test_a_release_pushes_exactly_its_version_tag_and_its_major_tag_each_on_its_own(checkout):
    next_major(checkout)
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.pushed == ["refs/tags/v4.4.0", "+refs/tags/v4"]
    assert origin_tag(checkout, "v4") == origin_tag(checkout, "v4.4.0") == git(checkout, "rev-parse", "HEAD")
    assert not {"v1", "v3"} & set(origin_tags(checkout))


def test_a_refused_ref_fails_the_run_naming_it_and_the_remedy_and_the_others_land(checkout):
    next_major(checkout)
    result = run_workflow(checkout, refused="refs/tags/v4")
    assert result.returncode == 1, result.stderr + result.stdout
    errors = [line for line in result.stdout.splitlines() if line.startswith("::error::")]
    assert len(errors) == 1, result.stdout
    assert errors[0].startswith("::error::Release: origin refused refs/tags/v4 (")
    assert "a tag ruleset forbids it" in errors[0]
    assert "tag rulesets" in errors[0] and "rerun" in errors[0]
    assert "v4.4.0" in origin_tags(checkout) and "v4" not in origin_tags(checkout)


def test_a_ref_refused_for_another_reason_names_a_rerun_and_no_ruleset(checkout):
    next_major(checkout)
    result = run_workflow(checkout, refused="refs/tags/v4", why="missing necessary objects")
    assert result.returncode == 1, result.stderr + result.stdout
    error, = (line for line in result.stdout.splitlines() if line.startswith("::error::"))
    assert "missing necessary objects" in error
    remedy = error.split("); ", 1)[1]
    assert remedy.startswith("rerun this job"), error
    assert "Settings > Rules > Rulesets" not in error


def test_the_workflow_force_updates_a_major_tag_behind_its_newest_release(checkout):
    missed_release(checkout)
    git(checkout, "tag", "v1", "v1.2.3")
    git(checkout, "push", "-q", "origin", "v1")
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert origin_tag(checkout, "v1") == origin_tag(checkout, "v1.3.1")


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
    assert f"on:\n  push:\n    branches: [{project.get('integration_branch', 'main')}]\n" in caller


def test_the_release_workflow_is_one_copy_whose_only_se_lines_are_its_branch_and_uses():
    """Consumers copy se's own release-tag.yml and change its branch and its uses, the README's
    major tag in place of se's own commit, so no other line is se's."""
    branch = tomllib.loads((PROJECT / "se.toml").read_text(encoding="utf-8"))["project"].get("integration_branch", "main")
    caller = (PROJECT / ".github" / "workflows" / "release-tag.yml").read_text(encoding="utf-8")
    own = [line for line in caller.splitlines() if line.strip() == f"branches: [{branch}]"]
    assert len(own) == 1
    local = "uses: ./.github/workflows/release.yml"
    assert caller.count(local) == 1
    for line in caller.replace(own[0], "").replace(local, "").splitlines():
        assert f"[{branch}]" not in line and "uses:" not in line, line
        assert not line.lstrip().startswith("#") or "set branches to your integration branch" in line \
            or "its own workflow" in line, line
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    assert "name: release-tag" not in readme
    assert "](.github/workflows/release-tag.yml)" in readme
    assert "`mb-89/SE/.github/workflows/release.yml@v<major>`" in readme


def test_nothing_calls_an_se_workflow_at_a_branch():
    """se's workflows are referenced at `@v<major>` (README "Release tags"), never at a branch."""
    for path in [*(PROJECT / ".github" / "workflows").glob("*.yml"), PROJECT / "README.md"]:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"mb-89/SE/\S+@(se|main)\b", line), f"{path.name}: {line}"


def test_every_runner_image_is_pinned():
    """se's jobs, and the README's example jobs, name their runner image's version, never a
    `-latest` label, so a new image arrives by a deliberate edit, not by GitHub moving the label."""
    for path in [*(PROJECT / ".github" / "workflows").glob("*.yml"), PROJECT / "README.md"]:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"runs-on:.*-latest\b", line), f"{path.name}: {line}"


def test_the_squash_commit_onto_an_unrelated_main_releases_its_version_and_major_only(checkout):
    """se becoming main: main's first-parent history holds a line that never had an se.toml, then
    one squash commit with se's tree at a new major; se's own tags stay where they are."""
    old = origin_tag(checkout, "v1.2.3")
    git(checkout, "push", "-q", "origin", "main:se")
    git(checkout, "switch", "-q", "--orphan", "go")
    for name in ("go.mod", "main.go"):
        (checkout / name).write_text(name, encoding="utf-8")
        git(checkout, "add", name)
        git(checkout, "commit", "-q", "-m", f"Add {name}")
    git(checkout, "rm", "-q", "go.mod", "main.go")
    git(checkout, "checkout", "-q", "main", "--", ".")
    (checkout / "se.toml").write_text(settings("2.0.0") + 'release = "workflow"\n', encoding="utf-8")
    git(checkout, "add", ".")
    git(checkout, "commit", "-q", "-m", "se becomes main")
    squash = git(checkout, "rev-parse", "HEAD")
    git(checkout, "push", "-q", "--force", "origin", "go:main")
    result = run_workflow(checkout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.pushed == ["refs/tags/v2.0.0", "+refs/tags/v2"]
    assert origin_tag(checkout, "v2.0.0") == origin_tag(checkout, "v2") == squash
    assert origin_tag(checkout, "v1.2.3") == old and "v1" not in origin_tags(checkout)
