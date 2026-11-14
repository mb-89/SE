"""Component versions assigned at the landing (scripts/component_versions.py, README "Component
versions"): a work branch states the kind of each component it changes, and integrate writes the
next version of that kind into the landing; a branch that still claims a number lands too."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_work_ticket_issues import (  # noqa: F401  (the landing's fixtures: checkout, GitHub, config)
    git_ok, git_run, github, integration_fakes, local_config, main_checkout, reported_at,
    squashed_onto_origin, work_tickets,
)

pytestmark = pytest.mark.usefixtures("fake_git_door")

versions = work_tickets.component_versions

SE_RELEASE = ('version = "{version}"\n'
              'download = "https://github.com/example/se/releases/download/se-v{{version}}"\n'
              'binary = "se"\npackage = "./cmd/se"\n')
KERN_RELEASE = ('version = "{version}"\n'
                'download = "https://github.com/example/se/releases/download/kern-v{{version}}"\n')


@pytest.mark.parametrize(("base", "claimed", "kind"), [
    ((0, 2, 9), (0, 2, 10), "patch"), ((0, 2, 9), (0, 3, 0), "minor"),
    ((0, 4, 9), (1, 0, 0), "major"), ((0, 2, 9), (0, 2, 9), None), ((0, 3, 0), (0, 2, 10), None),
])
def test_a_claim_gives_the_highest_part_it_raised_as_its_kind(base, claimed, kind):
    assert versions.claimed_kind(base, claimed) == kind


def test_the_landing_assigns_the_next_version_of_each_stated_kind_after_main_s():
    main = {"kern": (0, 4, 9), "se": (0, 2, 9)}
    assert versions.assigned_versions(main, {"se": "patch"}) == {"se": (0, 2, 10)}
    assert versions.assigned_versions(main, {"kern": "minor", "se": "major"}) == {
        "kern": (0, 5, 0), "se": (1, 0, 0)}
    assert versions.assigned_versions(main, {}) == {}
    with pytest.raises(versions.VersionError, match="name other, which the integration branch"):
        versions.assigned_versions(main, {"other": "patch"})


def test_the_field_report_states_component_kinds_in_its_header_or_none():
    assert versions.stated_kinds("**Component kinds:** se patch, kern minor — the guard\n") == {
        "se": "patch", "kern": "minor"}
    assert versions.stated_kinds("**Release kind:** patch — x\n") == {}
    template = work_tickets.field_report_template()
    assert "**Component kinds:**" in template and versions.stated_kinds(template) == {}
    assert versions.environment_value({"se": "patch", "kern": "minor"}) == "kern=minor,se=patch"
    assert versions.kinds_problems("**Component kinds:** se patch\n") == []
    problems = versions.kinds_problems("**Component kinds:** se huge\n")
    assert len(problems) == 1 and "'se huge' is no <component> patch|minor|major" in problems[0]


def test_field_report_check_refuses_an_unreadable_component_kinds_line():
    report = reported_at("abc1234").replace(
        "**Release kind:**", "**Component kinds:** se big\n**Release kind:**", 1)
    body = work_tickets.report_in(report, "test")
    assert any("'se big' is no <component>" in problem
               for problem in work_tickets.field_report_problems(body, None))


def components_on_main(checkout: Path, se: str = "0.2.9", kern: str = "0.4.9") -> None:
    """Origin's main with SE's two components: kern and the se binary, its [binary]."""
    git_ok("-C", str(checkout), "fetch", "-q", "origin")
    git_ok("-C", str(checkout), "reset", "-q", "--hard", "origin/main")
    (checkout / "kern").mkdir()
    (checkout / "components").mkdir()
    (checkout / "kern" / "release.toml").write_text(KERN_RELEASE.format(version=kern), encoding="utf-8")
    (checkout / "kern" / "core.go").write_text("package kern\n", encoding="utf-8")
    (checkout / "components" / "release.toml").write_text(SE_RELEASE.format(version=se), encoding="utf-8")
    (checkout / "components" / "se.go").write_text("package se\n", encoding="utf-8")
    with (checkout / "se.toml").open("a", encoding="utf-8") as stream:
        stream.write('\n[binary]\nrelease = "components/release.toml"\n')
    git_ok("-C", str(checkout), "add", "-A")
    git_ok("-C", str(checkout), "commit", "-q", "-m", "components")
    git_ok("-C", str(checkout), "push", "-q", "origin", "HEAD:main")


def work_branch(checkout: Path, branch: str, changes: dict[str, str]) -> str:
    """`branch` from origin's main as it is now, with `changes` committed and pushed; its head."""
    worker = checkout.parent / branch.replace("/", "-")
    git_ok("-C", str(checkout), "fetch", "-q", "origin")
    git_ok("-C", str(checkout), "worktree", "add", "-q", "-b", branch, str(worker), "origin/main")
    for name, text in changes.items():
        (worker / name).write_text(text, encoding="utf-8")
    git_ok("-C", str(worker), "add", "-A")
    git_ok("-C", str(worker), "commit", "-q", "-m", f"Change {branch}")
    git_ok("-C", str(worker), "push", "-q", "origin", branch)
    return git_run(worker, "rev-parse", "HEAD", check=True).stdout.strip()


def land(checkout: Path, monkeypatch, branch: str, head: str, number: int, kinds: str = "") -> str:
    """Integrate `branch` at `head` as pull request `number`, its report stating `kinds`."""
    report = reported_at(head)
    if kinds:
        report = report.replace("**Release kind:**", f"**Component kinds:** {kinds}\n**Release kind:**", 1)
    integration_fakes(monkeypatch, head)
    monkeypatch.setattr(work_tickets, "fetch_issue", lambda root, n, repo: {"body": report})
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: (
        json.dumps({"headRefName": branch, "headRefOid": head, "body": report,
                    "url": f"https://git.example/owner/repo/pull/{number}"})
        if args[:2] == ["pr", "view"] else ""))
    return work_tickets.integrate(checkout, number, None, None)


def version_on_main(checkout: Path, path: str) -> str:
    text = git_run(checkout, "show", f"origin/main:{path}", check=True).stdout
    return text.split('"', 2)[1]


def test_two_branches_that_change_the_se_binary_land_one_after_the_other_without_redelivery(
        main_checkout, monkeypatch, github, capsys):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout)
    # Both branches start from the same main and state only the kind; neither claims a number.
    first = work_branch(main_checkout, "fix/first", {"components/se.go": "package se // first\n"})
    second = work_branch(main_checkout, "fix/second", {"components/more.go": "package se\n"})

    commit = land(main_checkout, monkeypatch, "fix/first", first, 7, "se patch")
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.2.10"
    out = capsys.readouterr().out
    assert ("Component version: se 0.2.9 -> 0.2.10 (patch, stated); the push to the integration "
            "branch cuts se-v0.2.10") in out
    assert version_on_main(main_checkout, "kern/release.toml") == "0.4.9"  # kern did not change

    commit = land(main_checkout, monkeypatch, "fix/second", second, 8, "se patch")
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.2.11"
    assert "se 0.2.10 -> 0.2.11 (patch, stated); the push to the integration branch cuts se-v0.2.11" in (
        capsys.readouterr().out)


def test_a_branch_that_still_claims_a_taken_number_gets_the_next_free_one_of_its_kind(
        main_checkout, monkeypatch, github, capsys):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout)
    # Both claim se 0.3.0 the old way; the second's claim is taken once the first lands.
    claim = SE_RELEASE.format(version="0.3.0")
    first = work_branch(main_checkout, "feat/first", {
        "components/release.toml": claim, "components/se.go": "package se // first\n"})
    second = work_branch(main_checkout, "feat/second", {
        "components/release.toml": SE_RELEASE.format(version="0.2.10"),
        "kern/release.toml": KERN_RELEASE.format(version="0.5.0"),
        "kern/core.go": "package kern // second\n"})

    land(main_checkout, monkeypatch, "feat/first", first, 7)
    assert version_on_main(main_checkout, "components/release.toml") == "0.3.0"
    assert "se 0.2.9 -> 0.3.0 (minor, claimed 0.3.0); the push" in capsys.readouterr().out

    # Its se claim (0.2.10, a patch) conflicts with main's 0.3.0: the landing resolves it.
    commit = land(main_checkout, monkeypatch, "feat/second", second, 8)
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.3.1"
    assert version_on_main(main_checkout, "kern/release.toml") == "0.5.0"
    out = capsys.readouterr().out
    assert ("Component version: se 0.3.0 -> 0.3.1 (patch, claimed 0.2.10, replaced by the next "
            "free patch version); the push to the integration branch cuts se-v0.3.1") in out
    assert "kern 0.4.9 -> 0.5.0 (minor, claimed 0.5.0); the push to the integration branch cuts kern-v0.5.0" in out


def test_a_stated_kind_for_no_component_is_refused_and_nothing_lands(
        main_checkout, monkeypatch, github):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout)
    head = work_branch(main_checkout, "fix/other", {"components/se.go": "package se // x\n"})
    before = git_run(main_checkout, "rev-parse", "origin/main", check=True).stdout.strip()
    with pytest.raises(work_tickets.QueueError, match="Component kinds name tool, which"):
        land(main_checkout, monkeypatch, "fix/other", head, 7, "tool patch")
    assert git_run(main_checkout, "rev-parse", "origin/main", check=True).stdout.strip() == before
    assert git_run(main_checkout, "branch", "--show-current", check=True).stdout.strip() == "main"


def test_the_suite_gives_the_release_guard_the_work_branch_s_stated_kinds(
        main_checkout, monkeypatch, capsys):
    monkeypatch.setenv(versions.ENVIRONMENT, "")  # restored, unset, after the test
    monkeypatch.delenv(versions.ENVIRONMENT)
    git_ok("-C", str(main_checkout), "switch", "-q", "-c", "fix/kinds")
    report = main_checkout / ".se" / "work" / "field-report.md"
    report.parent.mkdir(parents=True)
    report.write_text("**Component kinds:** se patch, kern minor\n", encoding="utf-8")
    work_tickets.stated_component_kinds(main_checkout)
    assert work_tickets.os.environ[versions.ENVIRONMENT] == "kern=minor,se=patch"
    assert "the release guard reads fix/kinds's Component kinds: kern=minor,se=patch" in (
        capsys.readouterr().out)
    # On the integration branch the release commit carries the versions: no kinds.
    monkeypatch.delenv(versions.ENVIRONMENT)
    git_ok("-C", str(main_checkout), "switch", "-q", "main")
    work_tickets.stated_component_kinds(main_checkout)
    assert versions.ENVIRONMENT not in work_tickets.os.environ


def test_component_kinds_prints_the_guard_s_environment_line(tmp_path, capsys):
    body = tmp_path / "body.md"
    body.write_text("Fixes x\n\n**Component kinds:** se minor\n", encoding="utf-8")
    assert work_tickets.main(["component-kinds", str(body)]) == 0
    assert capsys.readouterr().out == "SE_COMPONENT_KINDS=se=minor\n"
