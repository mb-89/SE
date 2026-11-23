"""Component versions assigned at the landing (scripts/component_versions.py, README "Component
versions"): a work branch states the kind of each component it changes, and integrate writes the
next version of that kind into the landing; a branch that still claims a number lands too."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import fake_processes as fakes
import git_door
import se_modules
import time_bound
from test_work_ticket_issues import (  # noqa: F401  (the landing's fixtures: checkout, GitHub, config)
    PROJECT, git_ok, git_run, github, integration_fakes, local_config, main_checkout, reported_at,
    squashed_onto_origin, work_tickets,
)

pytestmark = pytest.mark.usefixtures("fake_git_door")

versions = work_tickets.component_versions

SE_RELEASE = ('version = "{version}"\n'
              'download = "https://github.com/example/se/releases/download/se-v{{version}}"\n'
              'binary = "se"\npackage = "./cmd/se"\n')
# A file that pins the se binary at its release tag, as a workflow that downloads it would: the
# landing's list names it in these tests (`listed`); none does in SE.
TEMPLATE = "docs/example/.github/workflows/check.yml"
PINNED = "jobs:\n  check:\n    uses: example/se/.github/workflows/se.yml@se-v{version}\n"
# components/go.mod, whose require kern is the kern the se binary is built on (se.toml [components.kern]).
GO_MOD = "module se/components\n\ngo 1.25.0\n\nrequire kern v{kern}\n\nreplace kern => ../.se/modules/kern\n"


@pytest.fixture(autouse=True)
def listed(monkeypatch):
    monkeypatch.setattr(versions, "PINS", {**versions.PINS, "se": (TEMPLATE,)})


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
    assert versions.stated_kinds("**Release kind:** patch\n\n## Delivered\n\n**Component kinds:** x\n") == {}
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


def components_on_main(checkout: Path, se: str = "0.2.9") -> None:
    """Origin's main with SE's one component, the se binary, its [binary], on kern 0.14.1."""
    git_ok("-C", str(checkout), "fetch", "-q", "origin")
    git_ok("-C", str(checkout), "reset", "-q", "--hard", "origin/main")
    (checkout / "components").mkdir()
    (checkout / TEMPLATE).parent.mkdir(parents=True)
    (checkout / TEMPLATE).write_text(PINNED.format(version=se), encoding="utf-8", newline="\n")
    (checkout / "components" / "release.toml").write_text(SE_RELEASE.format(version=se), encoding="utf-8", newline="\n")
    (checkout / "components" / "se.go").write_text("package se\n", encoding="utf-8", newline="\n")
    (checkout / "components" / "go.mod").write_text(GO_MOD.format(kern="0.14.1"), encoding="utf-8", newline="\n")
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
        (worker / name).parent.mkdir(parents=True, exist_ok=True)
        (worker / name).write_text(text, encoding="utf-8", newline="\n")
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

    commit = land(main_checkout, monkeypatch, "fix/second", second, 8, "se patch")
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.2.11"
    assert "se 0.2.10 -> 0.2.11 (patch, stated); the push to the integration branch cuts se-v0.2.11" in (
        capsys.readouterr().out)


def test_the_closing_comment_names_the_component_release_the_landing_cut(
        main_checkout, monkeypatch, github, capsys):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout)
    head = work_branch(main_checkout, "fix/first", {"components/se.go": "package se // first\n"})
    bodies: list[str] = []
    closeout = work_tickets.closeout_plan
    monkeypatch.setattr(work_tickets, "closeout_plan", lambda *arguments: bodies.append(
        arguments[5]) or closeout(*arguments))  # its comment: the work issue's closing comment

    land(main_checkout, monkeypatch, "fix/first", head, 7, "se patch")
    closing = [body for body in bodies if body.startswith("Integrated in ")]
    assert closing and all("component releases: https://git.example/owner/repo/releases/tag/se-v0.2.10." in body
                           for body in closing), bodies


def test_release_line_names_the_recorded_kind_and_each_component_release():
    url = "https://git.example/owner/repo/pull/20"
    recorded = "Release kind: minor, recorded; the version moves when SE asks for a release"
    assert work_tickets.release_line(url, "minor") == recorded + "."
    assert work_tickets.release_line(url, "minor", []) == recorded + "."
    assert work_tickets.release_line(url, "minor", ["kern-v0.14.2"]) == (
        recorded + "; component releases: https://git.example/owner/repo/releases/tag/kern-v0.14.2.")
    assert work_tickets.release_line("PR #20", "minor", ["se-v0.2.10"]) == (
        recorded + "; component releases: se-v0.2.10.")


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
        TEMPLATE: PINNED.format(version="0.2.10"), "components/more.go": "package se // second\n"})

    land(main_checkout, monkeypatch, "feat/first", first, 7)
    assert version_on_main(main_checkout, "components/release.toml") == "0.3.0"
    assert "se 0.2.9 -> 0.3.0 (minor, claimed 0.3.0); the push" in capsys.readouterr().out

    # Its se claim (0.2.10, a patch) conflicts with main's 0.3.0: the landing resolves it.
    commit = land(main_checkout, monkeypatch, "feat/second", second, 8)
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.3.1"
    out = capsys.readouterr().out
    assert ("Component version: se 0.3.0 -> 0.3.1 (patch, claimed 0.2.10, replaced by the next "
            "free patch version); the push to the integration branch cuts se-v0.3.1") in out
    assert git_run(main_checkout, "show", f"origin/main:{TEMPLATE}", check=True).stdout == (
        PINNED.format(version="0.3.1")), "the pin moves with the assigned number"


SE = versions.Component("se", "components/release.toml", ("components",), "se-v{version}")


def test_the_landing_moves_every_listed_pin_and_leaves_the_rest_of_the_text_alone():
    texts = {TEMPLATE: PINNED.format(version="1.2.3") + "# @se-v1.2.3.\n",
             "docs/other.md": "uses: x@se-v1.2.3\n"}
    assert versions.moved_pins(SE, texts, (1, 3, 0)) == {
        TEMPLATE: PINNED.format(version="1.3.0") + "# @se-v1.3.0.\n"}  # only the listed file
    # A pin the branch already moved by hand, to the assigned number, stays as it is.
    assert versions.moved_pins(SE, {TEMPLATE: PINNED.format(version="1.3.0")}, (1, 3, 0)) == {}
    assert versions.pin_pattern(SE, (1, 2, 3)).search("@se-v1.2.30") is None


# What the completeness check skips: git's own folder, local and generated caches, never tracked.
UNTRACKED = {".git", ".venv", ".se", "__pycache__", ".pytest_cache", "node_modules"}


def unlisted_pins_in(root: Path) -> list[str]:
    """The checkout's files that pin a component's current release tag outside `PINS`."""
    texts = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and not UNTRACKED & set(relative.parts):
            texts[relative.as_posix()] = path.read_bytes().decode("utf-8", errors="replace")
    found = []
    for release in ("components/release.toml",):
        if release in texts:
            settings = versions.tomllib.loads(texts[release])
            component = versions.Component(str(settings.get("binary") or "kern"), release, (),
                                           versions.release_tag(texts[release]))
            version = versions.read_version(texts[release], release)
            found += versions.unlisted_pins(component, version, texts)
    return found


def test_every_file_that_pins_a_component_s_current_tag_is_on_the_landing_s_list():
    assert unlisted_pins_in(PROJECT) == [], (
        "these files pin a component's current release tag, which the landing would leave behind: "
        "add each to component_versions.PINS")


def test_the_completeness_check_fails_on_a_made_up_file_with_a_stale_pin(tmp_path: Path):
    for name, text in {TEMPLATE: PINNED.format(version="4.5.6"),
                       "components/release.toml": SE_RELEASE.format(version="4.5.6"),
                       "docs/made-up.yml": "uses: example/se/.github/workflows/x.yml@se-v4.5.6\n",
                       "docs/history.md": "se-v4.5.6 shipped; the template once said @se-v4.4.0\n",
                       ".se/work/note.md": "@se-v4.5.6\n"}.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    assert unlisted_pins_in(tmp_path) == ["docs/made-up.yml"]
    (tmp_path / "docs" / "made-up.yml").write_text("uses: x@se-v4.5.6\n", encoding="utf-8", newline="\n")
    assert unlisted_pins_in(tmp_path) == ["docs/made-up.yml"]


def test_a_branch_that_moves_only_the_kern_require_and_states_se_patch_gets_ses_next_patch(
        main_checkout, monkeypatch, github, capsys):
    """kern's pin is components/go.mod's require kern (se.toml [components.kern]): moving it changes
    an input of se, so its stated kind gives se its next version, the listed pin moved with it."""
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout, se="0.5.1")
    head = work_branch(main_checkout, "feat/kern-pin", {"components/go.mod": GO_MOD.format(kern="0.15.0")})

    commit = land(main_checkout, monkeypatch, "feat/kern-pin", head, 7, "se patch")
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.5.2"
    assert git_run(main_checkout, "show", f"origin/main:{TEMPLATE}", check=True).stdout == PINNED.format(version="0.5.2")
    assert "se 0.5.1 -> 0.5.2 (patch, stated); the push to the integration branch cuts se-v0.5.2" in (
        capsys.readouterr().out)


def test_branches_that_pinned_the_number_by_hand_land_unchanged_or_on_the_next_free_one(
        main_checkout, monkeypatch, github, capsys):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    components_on_main(main_checkout, se="0.5.1")
    claim = {"components/release.toml": SE_RELEASE.format(version="0.6.0"),
             TEMPLATE: PINNED.format(version="0.6.0")}
    first = work_branch(main_checkout, "feat/first", {**claim, "components/se.go": "package se // 1\n"})
    second = work_branch(main_checkout, "feat/second", {**claim, "components/more.go": "package se\n"})
    third = work_branch(main_checkout, "fix/third", {
        "components/release.toml": SE_RELEASE.format(version="0.5.2"),
        TEMPLATE: PINNED.format(version="0.5.2"), "components/fix.go": "package se\n"})

    land(main_checkout, monkeypatch, "feat/first", first, 7)  # the stopgap: claimed by hand
    assert version_on_main(main_checkout, "components/release.toml") == "0.6.0"
    assert git_run(main_checkout, "show", f"origin/main:{TEMPLATE}", check=True).stdout == (
        PINNED.format(version="0.6.0"))
    assert "se 0.5.1 -> 0.6.0 (minor, claimed 0.6.0); the push" in capsys.readouterr().out

    # The same claim, now taken: the next free minor, the pin moved with it.
    land(main_checkout, monkeypatch, "feat/second", second, 8)
    assert version_on_main(main_checkout, "components/release.toml") == "0.7.0"
    assert git_run(main_checkout, "show", f"origin/main:{TEMPLATE}", check=True).stdout == (
        PINNED.format(version="0.7.0"))

    # A claim whose pin conflicts with main's: main's pin first, then the assigned one.
    commit = land(main_checkout, monkeypatch, "fix/third", third, 9)
    assert squashed_onto_origin(main_checkout, commit)
    assert version_on_main(main_checkout, "components/release.toml") == "0.7.1"
    assert git_run(main_checkout, "show", f"origin/main:{TEMPLATE}", check=True).stdout == (
        PINNED.format(version="0.7.1"))
    assert "se 0.7.0 -> 0.7.1 (patch, claimed 0.5.2, replaced by the next free patch" in (
        capsys.readouterr().out)


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
    report.write_text("**Component kinds:** se patch, kern minor\n", encoding="utf-8", newline="\n")
    work_tickets.stated_component_kinds(main_checkout)
    assert work_tickets.os.environ[versions.ENVIRONMENT] == "kern=minor,se=patch"
    assert "the release guard reads fix/kinds's Component kinds: kern=minor,se=patch" in (
        capsys.readouterr().out)
    # On the integration branch the release commit carries the versions: no kinds.
    monkeypatch.delenv(versions.ENVIRONMENT)
    git_ok("-C", str(main_checkout), "switch", "-q", "main")
    work_tickets.stated_component_kinds(main_checkout)
    assert versions.ENVIRONMENT not in work_tickets.os.environ


def test_field_report_check_appends_the_guard_s_environment_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "check_field_report", lambda *arguments: None)  # passes
    body = tmp_path / "body.md"
    body.write_text(reported_at("abc1234").replace(
        "**Release kind:**", "**Component kinds:** se minor\n**Release kind:**", 1), encoding="utf-8", newline="\n")
    environment = tmp_path / "github-env"
    environment.write_text("EARLIER=1\n", encoding="utf-8", newline="\n")
    assert work_tickets.main(["field-report", "--check", str(body),
                              "--component-kinds-to", str(environment)]) == 0
    assert environment.read_text(encoding="utf-8") == "EARLIER=1\nSE_COMPONENT_KINDS=se=minor\n"
    assert "Component kinds for the release guard: SE_COMPONENT_KINDS=se=minor" in capsys.readouterr().out


# A build that writes the project version into a generated file, as se_plugin.py build writes the
# plugin manifests: gen.json carries se.toml's [project] version.
GENERATE = ("import json, pathlib, tomllib; version = tomllib.loads(pathlib.Path('se.toml')"
            ".read_text())['project']['version']; pathlib.Path('gen.json').write_text("
            "json.dumps({'version': version}) + '\\n')")


def generate(invocation: fakes.Invocation) -> fakes.Answer:
    """The build `python -c GENERATE`, in this process as the child would run it."""
    assert invocation.words[1:] == ["-c", GENERATE], invocation.text()
    code = compile(GENERATE, "<string>", "exec")
    return fakes.run_main(lambda _arguments: exec(code, {"__name__": "__main__"}), invocation)


def test_a_branch_adding_a_generated_file_with_the_version_lands_after_main_released(
        main_checkout, monkeypatch, github, capsys, fake_processes):
    monkeypatch.setattr(work_tickets, "public_check_enabled", lambda root: False)
    build = [work_tickets.sys.executable, "-c", GENERATE]
    fake_processes.on(lambda invocation: invocation.words == build, generate)
    git_ok("-C", str(main_checkout), "fetch", "-q", "origin")
    git_ok("-C", str(main_checkout), "reset", "-q", "--hard", "origin/main")
    settings = main_checkout / "se.toml"
    base = settings.read_text(encoding="utf-8") + f"version = \"1.0.0\"\nrelease_build = {json.dumps(build)}\n"
    settings.write_text(base, encoding="utf-8", newline="\n")
    git_ok("-C", str(main_checkout), "commit", "-qam", "version")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "HEAD:main")
    # The branch adds the generated file at 1.0.0; then main releases 1.0.1.
    head = work_branch(main_checkout, "fix/generated", {"gen.json": '{"version": "1.0.0"}\n'})
    settings.write_text(base.replace('"1.0.0"', '"1.0.1"'), encoding="utf-8", newline="\n")
    git_ok("-C", str(main_checkout), "commit", "-qam", "Release v1.0.1")
    git_ok("-C", str(main_checkout), "push", "-q", "origin", "HEAD:main")

    def suite(root, **_):  # the real suite's start rebuilds the layouts (tests/conftest.py)
        work_tickets.process_door.run(build, cwd=root, check=True)
        work_tickets.record_suite_verdict(root, work_tickets.clean_commit(root), True, 1.0)
        return "1 passed"

    report = reported_at(head)
    integration_fakes(monkeypatch, head)
    monkeypatch.setattr(work_tickets, "run_suite", suite)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: (
        json.dumps({"headRefName": "fix/generated", "headRefOid": head, "body": report,
                    "url": "https://git.example/owner/repo/pull/7"})
        if args[:2] == ["pr", "view"] else ""))
    commit = work_tickets.integrate(main_checkout, 7, None, None)

    assert squashed_onto_origin(main_checkout, commit)
    out = capsys.readouterr().out
    assert "Suite verdict recorded: passed" in out
    assert "Merge: release_build regenerated gen.json" in out
    landed = json.loads(git_run(main_checkout, "show", "origin/main:gen.json", check=True).stdout)
    on_main = git_run(main_checkout, "show", "origin/main:se.toml", check=True).stdout
    assert landed["version"] == work_tickets.tomllib.loads(on_main)["project"]["version"] == "1.0.1"


GUARD_RELEASE = ('version = "0.2.9"\ndownload = "releases/download/se-v{version}"\n'
                 'binary = "se"\npackage = "./cmd/se"\n')
GUARD_MOD = "module se/components\n\ngo 1.25.0\n\nrequire kern v{kern}\n\nreplace kern => ./kern\n"


@pytest.mark.skipif(shutil.which("go") is None, reason="Go is not installed")
@pytest.mark.timeout(time_bound.BOUND + time_bound.COLD_CACHE_SECONDS)  # Go's caches may be empty
@pytest.mark.spawns("go: builds and runs kern's release guard (kern/tools/release), a Go program, with "
                    "`go run`; the one test of the guard on SE's components/go.mod")
def test_the_guard_refuses_a_branch_that_moves_only_the_kern_require_without_a_stated_kind(
        tmp_path, shared_fake_git):
    """kern's release guard (kern/tools/release, run as se.toml [tests.beside.release-guard] runs
    it) counts components/go.mod as an input of se: where se-v<version> is cut, moving its
    require kern alone is refused until the field report states se's kind."""
    with git_door.use(shared_fake_git):  # the fake kern's release guard, a child process, reads too
        repo = guard_repository(tmp_path)
    # The released tool imports no reader of the fake's state file; one file more in its package,
    # given to the build as an overlay, imports kern's gitfake, which registers it.
    reader = tmp_path / "fake_reader.go"
    reader.write_text('package main\n\nimport _ "kern/git/gitfake"\n', encoding="utf-8", newline="\n")
    overlay = tmp_path / "overlay.json"
    tool = se_modules.kern_dir(PROJECT) / "tools" / "release" / "zz_fake_reader.go"
    overlay.write_text(json.dumps({"Replace": {str(tool): str(reader)}}), encoding="utf-8", newline="\n")

    def guard(kinds: str | None) -> subprocess.CompletedProcess:
        environment = {k: v for k, v in os.environ.items() if k != versions.ENVIRONMENT}
        environment["GOFLAGS"] = "-buildvcs=false"  # the fake's checkout is no repository Go can stamp
        if kinds is not None:
            environment[versions.ENVIRONMENT] = kinds
        return subprocess.run(["go", "run", "-overlay", str(overlay), "kern/tools/release", "guard",
                               "--dir", str(repo / "components")],
                              cwd=PROJECT / "components", capture_output=True, text=True, env=environment)

    refused = guard(None)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert ("release guard: se-v0.2.9 is cut, and 1 of the se binary's inputs changed since: "
            "components/go.mod; state its kind in the field report, **Component kinds:** se") in refused.stderr
    stated = guard("se=patch")
    assert stated.returncode == 0, stated.stdout + stated.stderr
    assert "the field report states se patch, so the landing assigns its next version" in stated.stdout


def guard_repository(tmp_path: Path) -> Path:
    """A repository whose se-v0.2.9 is cut on kern 0.14.1, then one commit that moves only
    components/go.mod's require kern to 0.15.0."""
    repo = tmp_path / "repo"
    git_door.run("init", "-q", "-b", "main", str(repo))
    files = {"components/release.toml": GUARD_RELEASE, "components/go.mod": GUARD_MOD.format(kern="0.14.1"),
             "components/cmd/se/main.go": "package main\n\nfunc main() {}\n",
             "components/kern/go.mod": "module kern\n\ngo 1.25.0\n"}
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8", newline="\n")
    identity = git_door.identity_environment(("alice", "alice@example.com"))
    git_ok("-C", str(repo), "add", "-A")
    assert git_door.run("commit", "-q", "-m", "se 0.2.9", root=repo, env=identity).returncode == 0
    git_ok("-C", str(repo), "tag", "se-v0.2.9")
    (repo / "components" / "go.mod").write_text(GUARD_MOD.format(kern="0.15.0"), encoding="utf-8", newline="\n")
    git_ok("-C", str(repo), "add", "-A")
    assert git_door.run("commit", "-q", "-m", "kern 0.15.0", root=repo, env=identity).returncode == 0
    return repo
