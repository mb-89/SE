import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import quiet_git


PROJECT = Path(__file__).resolve().parents[1]
HELPER = PROJECT / "scripts" / "work_tickets.py"
SPEC = importlib.util.spec_from_file_location("work_tickets", HELPER)
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    # Nested Git repositories add over 100 characters below the case root; rooted in the
    # checkout they exceeded the Windows path limit in deep worktrees.
    root = tmp_path / "worktree"
    root.mkdir()
    return root


def run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )


def command(worktree: Path, *args: str) -> list[str]:
    return [*args, "--worktree", str(worktree)]


def initialize(worktree: Path) -> None:
    result = run_helper(*command(worktree, "init"))
    assert result.returncode == 0, result.stderr


def create(worktree: Path, ticket_id: str = "T-1") -> Path:
    result = run_helper(
        *command(worktree, "create"), "--id", ticket_id, "--title", "Example ticket"
    )
    assert result.returncode == 0, result.stderr
    return worktree / ".se" / "work" / "todo" / f"{ticket_id}.md"


def move(worktree: Path, ticket_id: str, state: str) -> subprocess.CompletedProcess[str]:
    return run_helper(*command(worktree, "move"), "--id", ticket_id, "--to", state)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def git_worktree(case_root: Path) -> tuple[Path, Path]:
    coordinator = case_root / "coordinator"
    worker = case_root / "worker"
    coordinator.mkdir(parents=True)
    quiet_git.init(coordinator, "-b", "coordinator")
    assert git(coordinator, "config", "user.name", "Worker test").returncode == 0
    assert git(coordinator, "config", "user.email", "worker-test@example.invalid").returncode == 0
    (coordinator / ".gitignore").write_text("/.se/\n", encoding="utf-8")
    (coordinator / "README").write_text("baseline\n", encoding="utf-8")
    assert git(coordinator, "add", ".").returncode == 0
    assert git(coordinator, "commit", "-m", "baseline").returncode == 0
    assert git(coordinator, "worktree", "add", "-b", "worker", str(worker)).returncode == 0
    return coordinator, worker


def test_project_checks_run_all_commands_and_report_failures(tmp_path: Path) -> None:
    passed = tmp_path / "passed.txt"
    first_failed = tmp_path / "first-failed.txt"
    second_failed = tmp_path / "second-failed.txt"
    script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text(Path.cwd().as_posix(), encoding='utf-8'); "
        "print(sys.argv[2]); raise SystemExit(int(sys.argv[3]))"
    )
    commands = [
        [sys.executable, "-c", script, str(first_failed), "first failure", "1"],
        [sys.executable, "-c", script, str(passed), "passing output", "0"],
        [sys.executable, "-c", script, str(second_failed), "second failure", "2"],
    ]

    with pytest.raises(work_tickets.QueueError, match="Project check failed") as error:
        work_tickets.run_project_checks(tmp_path, commands, True)

    assert passed.is_file()
    assert first_failed.is_file()
    assert second_failed.is_file()
    assert "check 1" in str(error.value)
    assert "first failure" in str(error.value)
    assert "check 3" in str(error.value)
    assert "second failure" in str(error.value)
    assert passed.read_text(encoding="utf-8") != first_failed.read_text(encoding="utf-8")
    assert first_failed.read_text(encoding="utf-8") != second_failed.read_text(encoding="utf-8")
    assert passed.read_text(encoding="utf-8") != tmp_path.as_posix()


def test_guard_reports_removed_tests_until_field_report_names_them(worktree: Path) -> None:
    repository = worktree.parent / "guard-case"
    repository.mkdir()
    quiet_git.init(repository, "-b", "main")
    assert git(repository, "config", "user.name", "Guard test").returncode == 0
    assert git(repository, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (repository / "test_example.py").write_text(
        "def test_removed_python():\n    pass\n\n"
        "def test_kept_python():\n    pass\n",
        encoding="utf-8",
    )
    (repository / "example.test.js").write_text(
        'it("removed JavaScript", () => {});\n'
        'test("kept JavaScript", () => {});\n',
        encoding="utf-8",
    )
    assert git(repository, "add", ".").returncode == 0
    assert git(repository, "commit", "-m", "baseline tests").returncode == 0
    assert git(repository, "checkout", "-b", "remove-tests").returncode == 0
    (repository / "test_example.py").write_text(
        "def test_kept_python():\n    pass\n",
        encoding="utf-8",
    )
    (repository / "example.test.js").write_text(
        'test("kept JavaScript", () => {});\n',
        encoding="utf-8",
    )
    assert git(repository, "commit", "-am", "remove protected tests").returncode == 0
    report = repository / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )

    guarded = run_helper(
        "guard", "--branch", "remove-tests", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert guarded.returncode != 0
    assert "test_removed_python" in guarded.stderr
    assert "removed JavaScript" in guarded.stderr

    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\n"
        "- `test_removed_python`: user approved its removal.\n"
        '- "removed JavaScript": user approved its removal.\n<!-- se:field-report:end -->\n',
        encoding="utf-8",
    )
    approved = run_helper(
        "guard", "--branch", "remove-tests", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert approved.returncode == 0, approved.stderr
    assert "test_removed_python" in approved.stdout
    assert "removed JavaScript" in approved.stdout


def test_guard_compares_against_the_fetched_remote_integration_branch(worktree: Path) -> None:
    upstream = worktree.parent / "guard-upstream"
    upstream.mkdir()
    quiet_git.init(upstream, "-b", "main")
    assert git(upstream, "config", "user.name", "Guard test").returncode == 0
    assert git(upstream, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (upstream / "test_example.py").write_text(
        "def test_removed_upstream():\n    pass\n", encoding="utf-8"
    )
    assert git(upstream, "add", ".").returncode == 0
    assert git(upstream, "commit", "-m", "baseline tests").returncode == 0
    clone = worktree.parent / "guard-clone"
    quiet_git.clone(upstream, clone)
    assert git(upstream, "rm", "-q", "test_example.py").returncode == 0
    assert git(upstream, "commit", "-m", "remove a test on the integration branch").returncode == 0
    assert git(clone, "fetch", "-q", "origin").returncode == 0
    assert git(clone, "checkout", "-q", "-b", "feature", "origin/main").returncode == 0
    report = clone / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )

    guarded = run_helper(
        "guard", "--branch", "feature", "--pr-description", str(report), "--worktree", str(clone),
    )

    assert guarded.returncode == 0, guarded.stderr
    assert "No removed protected content found." in guarded.stdout


def test_guard_reads_a_branch_the_clone_only_fetched_and_names_the_fetch_otherwise(
        worktree: Path) -> None:
    upstream = worktree.parent / "guard-upstream"
    upstream.mkdir()
    quiet_git.init(upstream, "-b", "main")
    assert git(upstream, "config", "user.name", "Guard test").returncode == 0
    assert git(upstream, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (upstream / "test_example.py").write_text("def test_removed_on_feature():\n    pass\n",
                                              encoding="utf-8")
    assert git(upstream, "add", ".").returncode == 0
    assert git(upstream, "commit", "-m", "baseline tests").returncode == 0
    assert git(upstream, "checkout", "-q", "-b", "feature").returncode == 0
    assert git(upstream, "rm", "-q", "test_example.py").returncode == 0
    assert git(upstream, "commit", "-m", "remove a test").returncode == 0
    clone = worktree.parent / "guard-clone"
    quiet_git.clone(upstream, clone, "-b", "main")
    report = clone / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )

    # Only origin/feature exists, as in an integrator's cloud clone: the guard reads it.
    guarded = run_helper(
        "guard", "--branch", "feature", "--pr-description", str(report), "--worktree", str(clone),
    )
    assert guarded.returncode != 0
    assert "test_removed_on_feature" in guarded.stderr
    assert "ambiguous argument" not in guarded.stderr

    # Neither feature nor origin/feature: the refusal names the fetch, not git's bare error.
    missing = run_helper(
        "guard", "--branch", "other", "--pr-description", str(report), "--worktree", str(clone),
    )
    assert missing.returncode != 0
    assert "Cannot find branch other" in missing.stderr and "fetch origin other" in missing.stderr
    assert "ambiguous argument" not in missing.stderr


def test_authored_content_globs_ignores_pyproject_settings(worktree: Path) -> None:
    (worktree / "pyproject.toml").write_text(
        "[tool.se]\nauthored_content = [\"docs/**/*.md\"]\n", encoding="utf-8"
    )
    assert work_tickets.authored_content_globs(worktree) == []


def authored_repository(repository: Path, branch: str, guide_text: str) -> tuple[Path, Path]:
    """A repository whose authored content is docs/**/*.md, with docs/guide.md holding
    `guide_text` committed on main, checked out on the new branch `branch`."""
    repository.mkdir()
    quiet_git.init(repository, "-b", "main")
    assert git(repository, "config", "user.name", "Guard test").returncode == 0
    assert git(repository, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (repository / "se.toml").write_text(
        "[project]\nauthored_content = [\"docs/**/*.md\"]\n", encoding="utf-8"
    )
    guide = repository / "docs" / "guide.md"
    guide.parent.mkdir()
    guide.write_text(guide_text, encoding="utf-8")
    assert git(repository, "add", ".").returncode == 0
    assert git(repository, "commit", "-m", "baseline prose").returncode == 0
    assert git(repository, "checkout", "-b", branch).returncode == 0
    return repository, guide


def test_guard_reports_removed_authored_sentences_until_field_report_names_them(
    worktree: Path,
) -> None:
    repository, guide = authored_repository(
        worktree.parent / "authored-content-case", "remove-prose",
        "This sentence is removed.\nThis sentence is moved.\nThis sentence is retained.\n",
    )
    guide.write_text("This sentence is retained.\n", encoding="utf-8")
    (repository / "docs" / "moved.md").write_text("This sentence is moved.\n", encoding="utf-8")
    assert git(repository, "add", ".").returncode == 0
    assert git(repository, "commit", "-m", "move and remove prose").returncode == 0
    report = repository / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )

    guarded = run_helper(
        "guard", "--branch", "remove-prose", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert guarded.returncode != 0
    assert "docs/guide.md: This sentence is removed." in guarded.stderr
    assert "This sentence is moved." not in guarded.stderr

    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\n"
        "- `docs/guide.md: This sentence is removed.`\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )
    approved = run_helper(
        "guard", "--branch", "remove-prose", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert approved.returncode == 0, approved.stderr
    assert "docs/guide.md: This sentence is removed." in approved.stdout


def test_guard_keeps_dots_in_protected_content_whole(worktree: Path) -> None:
    repository, guide = authored_repository(
        worktree.parent / "guard-protected-content-case", "remove-protected-content",
        "Deleting `pyproject.toml` keeps this sentence whole.\n"
        "Visit https://example.com/path.name before removal.\n\n"
        "```powershell\n"
        "uv run python scripts/work_tickets.py\n"
        "```\n"
        "The fenced block stays with this sentence.\n",
    )
    guide.write_text("", encoding="utf-8")
    assert git(repository, "commit", "-am", "remove protected prose").returncode == 0

    removed = work_tickets.deleted_authored_sentences(repository, "remove-protected-content")

    assert removed == [
        "docs/guide.md: Deleting `pyproject.toml` keeps this sentence whole.",
        "docs/guide.md: Visit https://example.com/path.name before removal.",
        "docs/guide.md: ```powershell uv run python scripts/work_tickets.py ```",
        "docs/guide.md: The fenced block stays with this sentence.",
    ]


OBS_627_GUIDE = (
    "Run the check before landing.\n\n"
    "```sh\n"
    "uv run python scripts/work_tickets.py guard\n"
    "```\n\n"
    "## Landing\n\n"
    "The integrator lands it.\n"
)
OBS_627_INSERTED = "A paragraph between the block and the heading. It has two sentences.\n\n"


@pytest.mark.parametrize(("base", "branch", "removed"), [
    # obs#627: a paragraph inserted between a fenced block and a heading removes nothing.
    (OBS_627_GUIDE, OBS_627_GUIDE.replace("## Landing", OBS_627_INSERTED + "## Landing"), []),
    # The same paragraph taken out again is reported alone.
    (OBS_627_GUIDE.replace("## Landing", OBS_627_INSERTED + "## Landing"), OBS_627_GUIDE,
     ["A paragraph between the block and the heading.", "It has two sentences."]),
])
def test_guard_reports_only_the_paragraph_changed_between_two_unchanged_blocks(
    worktree: Path, base: str, branch: str, removed: list[str],
) -> None:
    repository, guide = authored_repository(
        worktree.parent / f"guard-structure-case-{len(removed)}", "change-paragraph", base,
    )
    guide.write_text(branch, encoding="utf-8")
    assert git(repository, "commit", "-am", "change one paragraph").returncode == 0

    assert work_tickets.deleted_authored_sentences(repository, "change-paragraph") == [
        f"docs/guide.md: {sentence}" for sentence in removed
    ]


def test_authored_sentences_end_at_fences_headings_and_block_ids() -> None:
    text = (
        "Before the fence has no dot\n"
        "~~~text\n"
        "a. b\n"
        "~~~\n"
        "After the fence\n"
        "# A heading. With a dot\n"
        "Under the heading\n"
        "^block-id-1\n"
        "After the block id.\n"
    )
    assert work_tickets.authored_sentences(text) == [
        "Before the fence has no dot",
        "~~~text a. b ~~~",
        "After the fence",
        "# A heading. With a dot",
        "Under the heading",
        "^block-id-1",
        "After the block id.",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Each role follows its agent file (.github/agents/worker.agent.md) and the work model.",
            ["Each role follows its agent file (.github/agents/worker.agent.md) and the work model."],
        ),
        (
            "See [the work model](../skills/work-model/SKILL.md#tests) for the rules.",
            ["See [the work model](../skills/work-model/SKILL.md#tests) for the rules."],
        ),
        (
            "SE v5.3.0 reads se.toml at start.",
            ["SE v5.3.0 reads se.toml at start."],
        ),
        (
            "The first sentence ends here. (The second one ends in brackets.) A third! A `x? y` fourth?",
            [
                "The first sentence ends here.",
                "(The second one ends in brackets.)",
                "A third!",
                "A `x? y` fourth?",
            ],
        ),
    ],
)
def test_authored_sentences_split_only_where_a_sentence_ends(
    text: str, expected: list[str],
) -> None:
    assert work_tickets.authored_sentences(text) == expected


def test_guard_accepts_the_whole_sentence_with_a_path_quoted_across_lines(worktree: Path) -> None:
    sentence = (
        "Each role follows its agent file (.github/agents/worker.agent.md) and the work model."
    )
    repository, guide = authored_repository(
        worktree.parent / "guard-path-sentence-case", "remove-path-sentence",
        f"{sentence}\nThis sentence stays.\n",
    )
    guide.write_text("This sentence stays.\n", encoding="utf-8")
    assert git(repository, "commit", "-am", "remove a sentence holding a path").returncode == 0

    assert work_tickets.deleted_authored_sentences(repository, "remove-path-sentence") == [
        f"docs/guide.md: {sentence}",
    ]
    report = repository / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\n"
        "- docs/guide.md: Each role follows its agent file\n"
        "  (.github/agents/worker.agent.md) and the work model.\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )
    approved = run_helper(
        "guard", "--branch", "remove-path-sentence", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert approved.returncode == 0, approved.stderr


def test_guard_leaves_out_a_regenerated_command_reference(worktree: Path) -> None:
    stale = (f"# Guide\n\nThis sentence stays.\n\n{work_tickets.REFERENCE_BEGIN}\n"
             "```text\nwork_tickets.py gone\n    A command that is gone.\n```\n"
             f"{work_tickets.REFERENCE_END}\n\nThis sentence is removed.\n")
    repository, guide = authored_repository(
        worktree.parent / "generated-reference-case", "regenerate-reference", stale,
    )
    guide.write_text(
        work_tickets.with_command_reference(stale).replace("This sentence is removed.\n", ""),
        encoding="utf-8",
    )
    assert git(repository, "commit", "-am", "regenerate the command reference").returncode == 0

    assert work_tickets.deleted_authored_sentences(repository, "regenerate-reference") == [
        "docs/guide.md: This sentence is removed.",
    ]


def test_authored_text_keeps_markers_quoted_in_prose() -> None:
    begin, end = work_tickets.generated_markers("tool")
    text = f"Quote `{begin}` here.\nThis sentence stays.\nAnd `{end}` there.\n"
    assert work_tickets.authored_text(text) == text


def test_guard_leaves_out_a_file_the_build_generates_whole(worktree: Path) -> None:
    se_plugin = work_tickets.sibling("se_plugin")
    repository, guide = authored_repository(
        worktree.parent / "generated-file-case", "remove-generated-file",
        "---\nname: guide\n---\n" + se_plugin.notice("src/guide.md") + "\nA generated sentence.\n",
    )
    guide.unlink()
    assert git(repository, "commit", "-am", "remove the generated file").returncode == 0

    assert work_tickets.deleted_authored_sentences(repository, "remove-generated-file") == []


def test_guard_ignores_rewrapped_authored_sentences(worktree: Path) -> None:
    repository, guide = authored_repository(
        worktree.parent / "rewrapped-content-case", "rewrap-prose",
        "This paragraph has the same words after it is rewrapped for Markdown readability.\n",
    )
    guide.write_text(
        "This paragraph has the same words after it is rewrapped for Markdown\n"
        "readability.\n",
        encoding="utf-8",
    )
    assert git(repository, "commit", "-am", "rewrap authored prose").returncode == 0
    report = repository / "field-report.md"
    report.write_text(
        "<!-- se:field-report -->\n## Removed behaviour, deleted or weakened tests, and authored prose\n\nNone\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )

    guarded = run_helper(
        "guard", "--branch", "rewrap-prose", "--pr-description", str(report),
        "--worktree", str(repository),
    )
    assert guarded.returncode == 0, guarded.stderr
    assert "No removed protected content found." in guarded.stdout


def test_deliver_and_its_check_run_the_landing_guard_before_any_push_or_pull_request(
    worktree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    repository, guide = authored_repository(
        worktree.parent / "deliver-guard-case", "rewrite-prose",
        "This sentence is rewritten.\nThis sentence stays.\n",
    )
    guide.write_text("This sentence is reworded.\nThis sentence stays.\n", encoding="utf-8")
    assert git(repository, "commit", "-am", "rewrite prose").returncode == 0
    report = repository / ".se" / "work" / "field-report.md"
    report.parent.mkdir(parents=True)
    section = "## Removed behaviour, deleted or weakened tests, and authored prose\n\n"
    report.write_text(
        f"<!-- se:field-report -->\n**Work issue:** #1\n{section}None\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )
    issue_body = repository / "issue.md"
    issue_body.write_text("## Acceptance\n\n- [ ] A test.\n", encoding="utf-8")
    issue = {"number": 1, "title": "rewrite-prose", "url": "https://git.example/o/r/issues/1",
             "body": issue_body.read_text(encoding="utf-8")}
    pushed: list[str] = []
    posted: list[str] = []
    monkeypatch.setattr(work_tickets, "required_snapshot", lambda root: issue)
    monkeypatch.setattr(work_tickets, "check_issue_read", lambda *args: None)
    monkeypatch.setattr(work_tickets, "sync", lambda root: None)
    monkeypatch.setattr(work_tickets, "field_report_problems", lambda report, body: [])
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/o/r")
    monkeypatch.setattr(work_tickets, "push", lambda root, branch: pushed.append(branch))
    monkeypatch.setattr(work_tickets, "open_pull_request_number", lambda *args: None)
    monkeypatch.setattr(work_tickets, "run_gh_with_body", lambda root, arguments, body: (
        posted.append(body) or "https://git.example/o/r/pull/9"))
    unlisted = "docs/guide.md: This sentence is rewritten."
    check = ["field-report", "--check", str(report), "--worktree", str(repository),
             "--issue-body", str(issue_body)]

    with pytest.raises(work_tickets.QueueError) as refused:
        work_tickets.deliver(repository)
    message = str(refused.value)
    assert message.startswith("Field report must name each deleted or renamed test")
    assert unlisted in message and "This sentence stays." not in message
    assert "merge it first (work_tickets.py sync" in message
    assert pushed == [] and posted == []
    assert work_tickets.main(check) == 1
    assert unlisted in capsys.readouterr().err

    report.write_text(
        report.read_text(encoding="utf-8").replace(f"{section}None", f"{section}- `{unlisted}`"),
        encoding="utf-8",
    )
    assert work_tickets.main(check) == 0
    assert work_tickets.deliver(repository) == 9
    assert pushed == ["rewrite-prose"] and unlisted in posted[0]


GUIDE = "First line.\nMiddle line one.\nMiddle line two.\nLast line.\n"


def behind_main_repository(case: Path, main_text: str, branch_text: str) -> tuple[Path, Path]:
    """A clone on the branch `behind-main` that wrote docs/guide.md (first `GUIDE`) as
    `branch_text`, while main on origin has since landed it as `main_text`; its field report names
    the first line as removed."""
    case.mkdir()
    origin = case / "origin.git"
    quiet_git.init(origin, "--bare", "-b", "main")
    repository, guide = authored_repository(
        case / "clone", "behind-main", GUIDE,
    )
    assert git(repository, "remote", "add", "origin", str(origin)).returncode == 0
    assert git(repository, "push", "-q", "origin", "main").returncode == 0
    guide.write_text(branch_text, encoding="utf-8")
    assert git(repository, "commit", "-qam", "branch change").returncode == 0
    landed = case / "landed"
    quiet_git.clone(origin, landed)
    assert git(landed, "config", "user.name", "Guard test").returncode == 0
    assert git(landed, "config", "user.email", "guard-test@example.invalid").returncode == 0
    (landed / "docs" / "guide.md").write_text(main_text, encoding="utf-8")
    assert git(landed, "commit", "-qam", "another landing").returncode == 0
    assert git(landed, "push", "-q", "origin", "main").returncode == 0
    report = repository / ".se" / "work" / "field-report.md"
    report.parent.mkdir(parents=True)
    report.write_text(
        "<!-- se:field-report -->\n**Work issue:** #1\n## Removed behaviour, deleted or weakened "
        "tests, and authored prose\n\n- `docs/guide.md: First line.`\n<!-- se:field-report:end -->\n",
        encoding="utf-8",
    )
    return repository, landed


def stub_delivery_outside_git(monkeypatch: pytest.MonkeyPatch, pushed: list[str]) -> None:
    """deliver's GitHub side and its template gate stubbed out; its git side stays real."""
    issue = {"number": 1, "title": "behind-main", "url": "https://git.example/o/r/issues/1",
             "body": "## Acceptance\n\n- [ ] A test.\n"}
    monkeypatch.setattr(work_tickets, "required_snapshot", lambda root: issue)
    monkeypatch.setattr(work_tickets, "check_issue_read", lambda *args: None)
    monkeypatch.setattr(work_tickets, "field_report_problems", lambda report, body: [])
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "git.example/o/r")
    monkeypatch.setattr(work_tickets, "push", lambda root, branch: pushed.append(
        git(root, "rev-parse", "HEAD").stdout.strip()))
    monkeypatch.setattr(work_tickets, "open_pull_request_number", lambda *args: None)
    monkeypatch.setattr(work_tickets, "run_gh_with_body",
                        lambda root, arguments, body: "https://git.example/o/r/pull/9")


def test_deliver_merges_current_main_first_so_a_stale_branch_passes_the_guard(
    worktree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    repository, landed = behind_main_repository(
        worktree.parent / "behind-main-case",
        GUIDE.replace("Last line.", "Last line, as main landed it."),
        GUIDE.replace("First line.", "First, reworded."),
    )
    pushed: list[str] = []
    stub_delivery_outside_git(monkeypatch, pushed)
    main_head = git(landed, "rev-parse", "HEAD").stdout.strip()

    assert work_tickets.deliver(repository) == 9
    assert len(pushed) == 1
    assert git(repository, "merge-base", "--is-ancestor", main_head, pushed[0]).returncode == 0
    assert "Merged origin/main" in capsys.readouterr().out


def test_deliver_stops_on_a_conflicting_merge_naming_its_files(
    worktree: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = behind_main_repository(
        worktree.parent / "conflict-case",
        GUIDE.replace("First line.", "First, as main landed it."),
        GUIDE.replace("First line.", "First, as the branch wrote it."),
    )
    pushed: list[str] = []
    stub_delivery_outside_git(monkeypatch, pushed)
    tip = git(repository, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(work_tickets.QueueError) as refused:
        work_tickets.deliver(repository)
    message = str(refused.value)
    assert "docs/guide.md" in message and "work_tickets.py sync" in message
    assert pushed == []
    assert git(repository, "rev-parse", "HEAD").stdout.strip() == tip
    assert git(repository, "status", "--porcelain", "--untracked-files=no").stdout == ""


def test_queue_lifecycle_requires_checklist_and_evidence(worktree: Path) -> None:
    initialize(worktree)
    initialize(worktree)
    queue = worktree / ".se" / "work"
    assert {path.name for path in queue.iterdir()} == {"todo", "held", "done", "notes"}
    empty_status = run_helper(*command(worktree, "status"), "--json")
    assert empty_status.returncode == 0
    empty_report = json.loads(empty_status.stdout)
    assert empty_report["initialized"] is True
    assert empty_report["complete"] is True

    ticket = create(worktree)
    body = ticket.read_text(encoding="utf-8")
    assert all(f"## {heading}" in body for heading in (
        "Design", "Scope", "Dependencies", "Acceptance", "Evidence"
    ))
    assert "- [ ]" in body

    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = queue / "held" / "T-1.md"
    assert held_ticket.exists() and not ticket.exists()
    held_status = run_helper(*command(worktree, "status"), "--json")
    assert json.loads(held_status.stdout)["complete"] is False
    assert move(worktree, "T-1", "done").returncode != 0
    assert "not found" in move(worktree, "missing", "held").stderr.lower()
    returned = move(worktree, "T-1", "todo")
    assert returned.returncode == 0, returned.stderr
    assert ticket.exists() and not held_ticket.exists()
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = queue / "held" / "T-1.md"

    body = held_ticket.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
    held_ticket.write_text(body, encoding="utf-8")
    assert move(worktree, "T-1", "done").returncode != 0
    held_ticket.write_text(body + "\nEvidence: focused test passed.\n", encoding="utf-8")
    completed = move(worktree, "T-1", "done")
    assert completed.returncode == 0, completed.stderr

    (queue / "notes" / "result.txt").write_text("validated", encoding="utf-8")
    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["initialized"] is True
    assert status["counts"] == {"todo": 0, "held": 0, "done": 1}
    assert status["tickets"] == {"todo": [], "held": [], "done": ["T-1"]}
    assert status["notes"] == ["result.txt"]
    assert status["note_counts"] == {"resolved": 0, "unresolved": 1}
    assert "validated" not in result.stdout
    assert status["complete"] is False
    assert "percent" not in result.stdout.lower()
    assert move(worktree, "T-1", "todo").returncode != 0
    reviewed = run_helper(
        *command(worktree, "review-note"),
        "--note", "result.txt", "--disposition", "Review complete",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    reviewed_status = run_helper(*command(worktree, "status"), "--json")
    assert json.loads(reviewed_status.stdout)["complete"] is True


def test_done_validation_checks_every_acceptance_section(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    content = ticket.read_text(encoding="utf-8")
    content = content.replace(
        "## Evidence\n",
        "## Acceptance: additional criteria\n\n"
        "- [ ] Complete the additional criterion.\n\n"
        "## Evidence\n",
    ).replace("- [ ] Add a checkable acceptance criterion.", "- [x] Add a checkable acceptance criterion.")
    ticket.write_text(content, encoding="utf-8")
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr
    held_ticket = worktree / ".se" / "work" / "held" / "T-1.md"
    held_ticket.write_text(
        held_ticket.read_text(encoding="utf-8") + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )

    incomplete = move(worktree, "T-1", "done")
    assert incomplete.returncode != 0
    assert "unchecked" in incomplete.stderr.lower()

    held_ticket.write_text(
        held_ticket.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    complete = move(worktree, "T-1", "done")
    assert complete.returncode == 0, complete.stderr


def test_done_validation_lists_unchecked_acceptance_items(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    ticket.write_text(
        ticket.read_text(encoding="utf-8") + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr

    incomplete = move(worktree, "T-1", "done")
    assert incomplete.returncode != 0
    assert "Add a checkable acceptance criterion." in incomplete.stderr


def test_done_validation_allows_tickets_without_checklists(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    ticket.write_text(
        ticket.read_text(encoding="utf-8")
        .replace("- [ ] Add a checkable acceptance criterion.", "No checklist needed.")
        + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0, held.stderr

    completed = move(worktree, "T-1", "done")
    assert completed.returncode == 0, completed.stderr


def test_create_acceptance_replaces_placeholder_and_finishes_without_editing(
    worktree: Path,
) -> None:
    initialize(worktree)
    created = run_helper(
        *command(worktree, "create"), "--id", "T-1", "--title", "Example ticket",
        "--acceptance", "Focused test passes.", "--acceptance", "Help names the option.",
    )
    assert created.returncode == 0, created.stderr
    ticket = worktree / ".se" / "work" / "todo" / "T-1.md"
    content = ticket.read_text(encoding="utf-8")
    assert "Add a checkable acceptance criterion." not in content
    assert "- [ ] Focused test passes.\n- [ ] Help names the option.\n" in content

    assert move(worktree, "T-1", "held").returncode == 0
    held_ticket = worktree / ".se" / "work" / "held" / "T-1.md"
    held_ticket.write_text(
        held_ticket.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
        + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    completed = move(worktree, "T-1", "done")
    assert completed.returncode == 0, completed.stderr


def test_create_refuses_multiline_acceptance(worktree: Path) -> None:
    initialize(worktree)
    result = run_helper(
        *command(worktree, "create"), "--id", "T-1", "--title", "Example ticket",
        "--acceptance", "one\ntwo",
    )
    assert result.returncode != 0
    assert "--acceptance" in result.stderr
    assert not (worktree / ".se" / "work" / "todo" / "T-1.md").exists()


def test_done_refusing_placeholder_names_file_line_and_remedy(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    ticket.write_text(
        ticket.read_text(encoding="utf-8") + "\nEvidence: focused test passed.\n",
        encoding="utf-8",
    )
    assert move(worktree, "T-1", "held").returncode == 0
    held_ticket = worktree / ".se" / "work" / "held" / "T-1.md"
    line = held_ticket.read_text(encoding="utf-8").splitlines().index(
        "- [ ] Add a checkable acceptance criterion."
    ) + 1

    refused = move(worktree, "T-1", "done")
    assert refused.returncode != 0
    assert f".se/work/held/T-1.md:{line}" in refused.stderr
    assert "create --acceptance" in refused.stderr
    assert f"edit line {line}" in refused.stderr


def test_move_rejects_acceptance_override_flag(worktree: Path) -> None:
    initialize(worktree)
    result = run_helper(
        *command(worktree, "move"),
        "--id",
        "T-1",
        "--to",
        "done",
        "--force",
    )
    assert result.returncode != 0
    assert "unrecognized arguments: --force" in result.stderr


def test_status_uninitialized_does_not_create_queue(worktree: Path) -> None:
    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["initialized"] is False
    assert status["complete"] is False
    assert status["cleanup_eligible"] is False
    assert status["note_counts"] == {"resolved": 0, "unresolved": 0}
    assert status["errors"]
    assert not (worktree / ".se").exists()


@pytest.mark.parametrize("ticket_id", ["../escape", "..", "bad/name", ""])
def test_create_rejects_unsafe_ids(worktree: Path, ticket_id: str) -> None:
    initialize(worktree)
    result = run_helper(
        *command(worktree, "create"), "--id", ticket_id, "--title", "Unsafe"
    )
    assert result.returncode != 0
    assert not (worktree / "escape.md").exists()


def test_create_and_move_never_overwrite_existing_ticket(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    original = ticket.read_text(encoding="utf-8")
    duplicate = run_helper(
        *command(worktree, "create"), "--id", "T-1", "--title", "Replacement"
    )
    assert duplicate.returncode != 0
    assert ticket.read_text(encoding="utf-8") == original

    collision = worktree / ".se" / "work" / "held" / "T-1.md"
    collision.write_text("do not overwrite", encoding="utf-8")
    result = move(worktree, "T-1", "held")
    assert result.returncode != 0
    assert collision.read_text(encoding="utf-8") == "do not overwrite"


def test_duplicate_ids_are_reported_and_move_is_ambiguous(worktree: Path) -> None:
    initialize(worktree)
    ticket = create(worktree)
    duplicate = worktree / ".se" / "work" / "held" / "copy.md"
    duplicate.write_text(ticket.read_text(encoding="utf-8"), encoding="utf-8")

    status = run_helper(*command(worktree, "status"), "--json")
    assert status.returncode != 0
    report = json.loads(status.stdout)
    assert any("duplicate" in error.lower() for error in report["errors"])
    assert report["complete"] is False
    moved = move(worktree, "T-1", "held")
    assert moved.returncode != 0
    assert "ambiguous" in moved.stderr.lower()


def test_status_reports_malformed_state(worktree: Path) -> None:
    initialize(worktree)
    (worktree / ".se" / "work" / "todo" / "broken.md").write_text(
        "not a ticket", encoding="utf-8"
    )

    result = run_helper(*command(worktree, "status"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert any("malformed" in error.lower() for error in report["errors"])
    assert report["complete"] is False


def test_symlinked_state_directory_cannot_escape_worktree(worktree: Path) -> None:
    initialize(worktree)
    outside = worktree.parent / "outside"
    outside.mkdir()
    todo = worktree / ".se" / "work" / "todo"
    todo.rmdir()
    if os.name == "nt":
        link_path = str(todo).replace("'", "''")
        target_path = str(outside).replace("'", "''")
        junction = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"New-Item -ItemType Junction -Path '{link_path}' "
                f"-Target '{target_path}' | Out-Null",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(
                "directory junctions are unavailable: "
                f"{junction.stdout}{junction.stderr}".strip()
            )
    else:
        try:
            os.symlink(outside, todo, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks are unavailable")

    result = run_helper(
        *command(worktree, "create"), "--id", "T-escape", "--title", "Escape"
    )
    assert result.returncode != 0
    assert list(outside.iterdir()) == []


def test_review_note_appends_local_disposition_without_leaking_text(worktree: Path) -> None:
    initialize(worktree)
    note = worktree / ".se" / "work" / "notes" / "private.txt"
    private_text = "PRIVATE unfiltered finding: credentials and details"
    note.write_text(private_text, encoding="utf-8")

    before = run_helper(*command(worktree, "status"), "--json")
    assert before.returncode == 0, before.stderr
    report = json.loads(before.stdout)
    assert report["note_counts"] == {"resolved": 0, "unresolved": 1}
    assert report["complete"] is False
    assert private_text not in before.stdout

    reviewed = run_helper(
        *command(worktree, "review-note"),
        "--note", "private.txt",
        "--disposition", "Resolved after owner review",
        "--backlog-ref", "backlog/future.md",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    assert "Resolved after owner review" not in reviewed.stdout
    assert private_text in note.read_text(encoding="utf-8")
    assert "Disposition: Resolved after owner review" in note.read_text(encoding="utf-8")
    assert "backlog-ref: backlog/future.md" in note.read_text(encoding="utf-8")

    after = run_helper(*command(worktree, "status"), "--json")
    report = json.loads(after.stdout)
    assert report["note_counts"] == {"resolved": 1, "unresolved": 0}
    assert report["complete"] is True
    assert report["notes"] == ["private.txt"]
    assert private_text not in after.stdout
    assert "Resolved after owner review" not in after.stdout
    assert "backlog/future.md" not in after.stdout


def test_close_refuses_active_queue_and_unresolved_notes(worktree: Path) -> None:
    initialize(worktree)
    create(worktree)
    unresolved = worktree / ".se" / "work" / "notes" / "question.txt"
    unresolved.write_text("private question", encoding="utf-8")

    result = run_helper(*command(worktree, "close"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["cleanup_eligible"] is False
    assert report["complete"] is False
    assert "todo" in " ".join(report["cleanup_reasons"]).lower()
    assert "unresolved" in " ".join(report["cleanup_reasons"]).lower()
    assert unresolved.read_text(encoding="utf-8") == "private question"


def test_close_refuses_invalid_completed_ticket(worktree: Path) -> None:
    initialize(worktree)
    create(worktree)
    held = move(worktree, "T-1", "held")
    assert held.returncode == 0
    held_path = worktree / ".se" / "work" / "held" / "T-1.md"
    body = held_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
    held_path.write_text(body + "\nEvidence: present.\n", encoding="utf-8")
    assert move(worktree, "T-1", "done").returncode == 0
    done_path = worktree / ".se" / "work" / "done" / "T-1.md"
    done_path.write_text(
        done_path.read_text(encoding="utf-8").replace("- [x]", "- [ ]"),
        encoding="utf-8",
    )

    result = run_helper(*command(worktree, "close"), "--json")
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert any("invalid completed ticket" in error.lower() for error in report["errors"])
    assert report["complete"] is False
    assert report["cleanup_eligible"] is False


def test_close_checks_git_cleanliness_primary_and_integration(worktree: Path) -> None:
    coordinator, worker = git_worktree(worktree.parent / "git-case")
    initialize(worker)
    (worker / "unintegrated.txt").write_text("not yet integrated\n", encoding="utf-8")
    assert git(worker, "add", "unintegrated.txt").returncode == 0
    assert git(worker, "commit", "-m", "unintegrated worker change").returncode == 0

    not_integrated = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert not_integrated.returncode != 0
    assert "integrat" in not_integrated.stdout.lower()

    (worker / "change.txt").write_text("worker change\n", encoding="utf-8")
    assert git(worker, "add", "change.txt").returncode == 0
    assert git(worker, "commit", "-m", "worker change").returncode == 0
    (worker / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    dirty = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert dirty.returncode != 0
    assert "dirty" in dirty.stdout.lower()
    (worker / "dirty.txt").unlink()

    assert git(coordinator, "merge", "--no-ff", "worker", "-m", "integrate worker").returncode == 0
    note = worker / ".se" / "work" / "notes" / "reviewed.txt"
    note.write_text("short local reminder", encoding="utf-8")
    reviewed_note = run_helper(
        *command(worker, "review-note"),
        "--note", note.name,
        "--disposition", "No follow-up required",
    )
    assert reviewed_note.returncode == 0, reviewed_note.stderr
    clean = run_helper(
        *command(worker, "close"), "--integration-target", "coordinator", "--json"
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    clean_report = json.loads(clean.stdout)
    assert clean_report["cleanup_eligible"] is True
    assert clean_report["note_counts"] == {"resolved": 1, "unresolved": 0}

    primary = run_helper(
        *command(coordinator, "close"), "--integration-target", "coordinator", "--json"
    )
    assert primary.returncode != 0
    assert "primary" in primary.stdout.lower()


def test_close_remove_requires_explicit_target_and_removes_normally(worktree: Path) -> None:
    coordinator, worker = git_worktree(worktree.parent / "remove-case")
    initialize(worker)
    (worker / "change.txt").write_text("integrated\n", encoding="utf-8")
    assert git(worker, "add", "change.txt").returncode == 0
    assert git(worker, "commit", "-m", "worker work").returncode == 0
    assert git(coordinator, "merge", "--no-ff", "worker", "-m", "integrate worker").returncode == 0

    missing_target = run_helper(*command(worker, "close"), "--remove", "--json")
    assert missing_target.returncode != 0
    assert worker.exists()

    removed = run_helper(
        *command(worker, "close"),
        "--remove",
        "--integration-target", "coordinator",
        "--json",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout)["removed"] is True
    assert not worker.exists()


def test_se_is_ignored_in_full() -> None:
    result = git(PROJECT, "check-ignore", ".se/work/notes/private.txt")
    assert result.returncode == 0


def test_readme_command_reference_is_what_docs_writes():
    assert work_tickets.main(["docs", "--check"]) == 0


def test_docs_check_refuses_a_stale_reference_and_docs_rewrites_it(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    stale = (f"# Title\n\nProse stays.\n\n{work_tickets.REFERENCE_BEGIN}\nstale\n"
             f"{work_tickets.REFERENCE_END}\n\nMore prose.\n")
    readme.write_text(stale, encoding="utf-8")
    monkeypatch.setattr(work_tickets, "README", readme)

    assert work_tickets.main(["docs", "--check"]) == 1
    assert readme.read_text(encoding="utf-8") == stale
    assert "differs from the registry" in capsys.readouterr().err

    assert work_tickets.main(["docs"]) == 0
    written = readme.read_text(encoding="utf-8")
    assert written.startswith("# Title\n\nProse stays.\n\n")
    assert written.endswith(f"{work_tickets.REFERENCE_END}\n\nMore prose.\n")
    assert "work_tickets.py backlog list --worktree WORKTREE" in written
    assert "stale" not in written
    assert work_tickets.main(["docs", "--check"]) == 0



def test_format_applies_every_fix_the_check_job_checks_and_a_second_run_writes_nothing(
        tmp_path, capsys):
    """format writes what se_plugin.py check and docs --check refuse: the generated layouts and
    the README's command reference, in a misformatted copy of the checkout."""
    root = tmp_path / "se"
    shutil.copytree(PROJECT / "src", root / "src")
    shutil.copy(PROJECT / "se.toml", root)
    se_plugin = work_tickets.sibling("se_plugin")
    se_plugin.build(root)
    stale = root / "skills" / "work-model" / "SKILL.md"
    stale.write_text("edited by hand\n", encoding="utf-8")
    (root / "agents" / "worker.md").unlink()
    (root / "skills" / "orphan.md").write_text("no source\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# Title\n\n{work_tickets.REFERENCE_BEGIN}\nstale\n{work_tickets.REFERENCE_END}\n",
        encoding="utf-8")
    assert len(se_plugin.differences(root)) == 3

    assert work_tickets.main(["format", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "wrote skills/work-model/SKILL.md" in output
    assert "wrote README.md" in output
    assert se_plugin.differences(root) == []
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert readme == work_tickets.with_command_reference(readme)

    assert work_tickets.main(["format", "--root", str(root)]) == 0
    assert capsys.readouterr().out == "format: nothing to change\n"


# refs request and refs apply: the Actions API faked behind its door, Workflows.

OLD, NEW = "1" * 40, "2" * 40  # replaced by real commits where origin must hold them


class FakeWorkflows:
    """Issue comments, labels and ref-maintenance runs on the bare origin of the checkout it is
    opened for: a real run (dry_run "false") of a passing `conclusion` moves origin's refs as the
    workflow's atomic push does, unless `moves` is off."""

    def __init__(self) -> None:
        self.comments_posted: list[dict] = []
        self.labels: set[str] = set()
        self.runs: list[dict] = []
        self.dispatched: list[tuple] = []
        self.conclusion = "success"
        self.moves = True
        self.log = ("2026-11-12T10:00:00.0000000Z ##[group]Run set -euo pipefail\n"
                    "2026-11-12T10:00:01.0000000Z set    refs/heads/main a -> b\n"
                    "2026-11-12T10:00:02.0000000Z To https://git.example/owner/repo\n"
                    "2026-11-12T10:00:02.0000000Z +\tb:refs/heads/main\ta...b (forced update)\n"
                    "2026-11-12T10:00:02.0000000Z Done\n")
        self.origin: Path | None = None

    def __call__(self, root: Path, repo: str) -> "FakeWorkflows":
        self.origin = Path(git(root, "remote", "get-url", "origin").stdout.strip())
        return self

    def comments(self, number: int) -> list[dict]:
        return list(self.comments_posted)

    def comment(self, number: int, body: str) -> dict:
        self.comments_posted.append({"id": 100 + len(self.comments_posted), "body": body})
        return self.comments_posted[-1]

    def add_label(self, number: int, label: str) -> None:
        self.labels.add(label)

    def remove_label(self, number: int, label: str) -> None:
        self.labels.discard(label)

    def newest_run(self, workflow: str) -> int:
        return self.runs[-1]["id"] if self.runs else 0

    def dispatch(self, workflow: str, ref: str, inputs: dict) -> None:
        self.dispatched.append((workflow, ref, inputs))
        if inputs["dry_run"] == "false" and self.conclusion == "success" and self.moves:
            words = inputs["updates"].split()
            for index in range(0, len(words), 3):
                old, new, name = words[index:index + 3]
                assert git(self.origin, "update-ref", name, new, old).returncode == 0
        self.runs.append({"id": 900 + len(self.runs), "status": "completed",
                          "conclusion": self.conclusion,
                          "html_url": f"https://git.example/owner/repo/actions/runs/{900 + len(self.runs)}"})

    def run(self, run_id: int) -> dict:
        return next(run for run in self.runs if run["id"] == run_id)

    def run_log(self, run_id: int) -> str:
        return self.log


@pytest.fixture
def refs_checkout(tmp_path: Path, monkeypatch) -> tuple[Path, FakeWorkflows, str, str]:
    """A checkout whose origin holds main and a branch `next` one commit ahead; the fake door."""
    origin, checkout = tmp_path / "origin.git", tmp_path / "main"
    quiet_git.init(origin, "--bare", "-b", "main")
    quiet_git.clone(origin, checkout)
    identity = ("-c", "user.name=mb", "-c", "user.email=mb")
    assert git(checkout, *identity, "commit", "-q", "--allow-empty", "-m", "base").returncode == 0
    base = git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert git(checkout, *identity, "commit", "-q", "--allow-empty", "-m", "next").returncode == 0
    ahead = git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert git(checkout, "push", "-q", "origin", f"{base}:refs/heads/main",
               f"{ahead}:refs/heads/next").returncode == 0
    fake = FakeWorkflows()
    monkeypatch.setattr(work_tickets, "Workflows", fake)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)  # gh signed in: the local runner
    monkeypatch.setattr(work_tickets, "wait", lambda seconds: None)
    return checkout, fake, base, ahead


def triples_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "triples.txt"
    path.write_text(text, encoding="utf-8")
    return path


REPO = "git.example/owner/repo"


def test_refs_request_posts_the_triples_runs_the_dry_run_and_escalates(refs_checkout, tmp_path):
    checkout, fake, base, ahead = refs_checkout
    triples = f"{base} {ahead} refs/heads/main\n{ahead} {'0' * 40} refs/heads/next\n"
    line = work_tickets.refs_request(checkout, 5, triples_file(tmp_path, triples), REPO)
    assert fake.dispatched == [("ref-maintenance.yml", "main",
                                {"updates": triples, "dry_run": "true"})]
    request, dry_run = (comment["body"] for comment in fake.comments_posted)
    assert request.startswith(work_tickets.REFS_REQUEST_MARKER)
    assert f"```text\n{triples}```" in request
    assert f"move refs/heads/main {base[:12]} -> {ahead[:12]}" in request
    assert f"delete refs/heads/next (now {ahead[:12]})" in request
    assert dry_run.startswith(work_tickets.REFS_DRY_RUN_MARKER)
    assert "<!-- se:refs-request-id 100 -->" in dry_run
    assert "Dry run of `ref-maintenance`: success (https://git.example/owner/repo/actions/runs/900)" in dry_run
    assert "set    refs/heads/main a -> b\nTo https://git.example/owner/repo\n+\tb:refs/heads/main" in dry_run
    assert "##[group]" not in dry_run
    assert fake.labels == {"escalated"}
    assert line == ("escalated #5: apply the ref change (2 ref(s), dry run passed)? "
                    "On yes: work_tickets.py refs apply 5")
    # Nothing moved: a dry run only shows the push.
    assert git(checkout, "ls-remote", "origin", "refs/heads/main").stdout.startswith(base)


@pytest.mark.parametrize("text, message", [
    ("abc def", "got 2 words"),
    (f"{OLD} {NEW}", "got 2 words"),
    (f"{OLD} {'2' * 39} refs/heads/main", "is not a full 40-character"),
    (f"{OLD} {NEW} refs/pull/1/head", "only refs/heads/... and refs/tags/..."),
    (f"{OLD} {NEW} refs/tags/v1 {NEW} {OLD} refs/tags/v1", "one triple only"),
])
def test_refs_request_refuses_malformed_triples_before_any_call(refs_checkout, tmp_path, text, message):
    checkout, fake, _, _ = refs_checkout
    with pytest.raises(work_tickets.QueueError, match=re.escape(message)):
        work_tickets.refs_request(checkout, 5, triples_file(tmp_path, text), REPO)
    assert fake.comments_posted == [] and fake.dispatched == []


def test_refs_request_posts_a_failed_dry_run_and_escalates_nothing(refs_checkout, tmp_path):
    checkout, fake, base, ahead = refs_checkout
    fake.conclusion = "failure"
    fake.log = "2026-11-12T10:00:01Z ::error::refs/heads/main: x is not a commit on the remote; push it first\n"
    with pytest.raises(work_tickets.QueueError, match="concluded failure .*nothing was escalated"):
        work_tickets.refs_request(checkout, 5, triples_file(tmp_path, f"{base} {ahead} refs/heads/main"), REPO)
    assert "::error::refs/heads/main: x is not a commit" in fake.comments_posted[-1]["body"]
    assert fake.labels == set()


def test_refs_apply_runs_the_posted_triples_for_real_and_reads_them_back(refs_checkout, tmp_path):
    checkout, fake, base, ahead = refs_checkout
    triples = f"{base} {ahead} refs/heads/main\n{ahead} {'0' * 40} refs/heads/next\n"
    work_tickets.refs_request(checkout, 5, triples_file(tmp_path, triples), REPO)
    line = work_tickets.refs_apply(checkout, 5, REPO)
    assert fake.dispatched[-1] == ("ref-maintenance.yml", "main",
                                   {"updates": triples, "dry_run": "false"})
    assert git(checkout, "ls-remote", "origin", "refs/heads/main").stdout.startswith(ahead)
    assert git(checkout, "ls-remote", "origin", "refs/heads/next").stdout == ""
    applied = fake.comments_posted[-1]["body"]
    assert applied.startswith(work_tickets.REFS_APPLIED_MARKER)
    assert "run: success (https://git.example/owner/repo/actions/runs/901); refs applied" in applied
    assert fake.labels == set()
    assert line == "refs applied on #5 (https://git.example/owner/repo/actions/runs/901): verify and close out"


def test_refs_apply_refuses_a_request_without_a_passed_dry_run(refs_checkout, tmp_path):
    checkout, fake, base, ahead = refs_checkout
    with pytest.raises(work_tickets.QueueError, match="carries no refs request"):
        work_tickets.refs_apply(checkout, 5, REPO)
    fake.conclusion = "failure"
    with pytest.raises(work_tickets.QueueError):
        work_tickets.refs_request(checkout, 5, triples_file(tmp_path, f"{base} {ahead} refs/heads/main"), REPO)
    fake.conclusion = "success"
    with pytest.raises(work_tickets.QueueError, match="no passed dry run"):
        work_tickets.refs_apply(checkout, 5, REPO)
    assert [inputs["dry_run"] for _, _, inputs in fake.dispatched] == ["true"]


def test_refs_apply_refuses_refs_origin_does_not_hold_as_requested(refs_checkout, tmp_path):
    checkout, fake, base, ahead = refs_checkout
    work_tickets.refs_request(checkout, 5, triples_file(tmp_path, f"{base} {ahead} refs/heads/main"), REPO)
    fake.moves = False
    with pytest.raises(work_tickets.QueueError, match="not as requested on origin: refs/heads/main"):
        work_tickets.refs_apply(checkout, 5, REPO)
    assert "refs not applied; not as requested on origin" in fake.comments_posted[-1]["body"]
    assert fake.labels == {"escalated"}


# The hand-off: where gh is not signed in, refs prints its GitHub steps as a plan for the
# session's GitHub tools, and --read-back checks the refs through git ls-remote.


def test_refs_request_hands_off_a_plan_for_the_triples(refs_checkout, tmp_path, monkeypatch, capsys):
    checkout, fake, base, ahead = refs_checkout
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    triples = f"{base} {ahead} refs/heads/main\n{ahead} {'0' * 40} refs/heads/next\n"
    file = triples_file(tmp_path, triples)

    assert work_tickets.main(["refs", "request", "5", "--triples-file", str(file), "--repo", REPO,
                              "--worktree", str(checkout)]) == 0

    out = capsys.readouterr().out
    assert fake.comments_posted == [] and fake.dispatched == []  # the session runs the steps
    assert "GitHub plan: refs request on #5\n1. add_issue_comment " in out
    assert f"move refs/heads/main {base[:12]} -> {ahead[:12]}" in out
    dispatch = next(line for line in out.splitlines() if line.startswith("2. "))
    assert dispatch.startswith("2. actions_run_trigger ")
    assert json.loads(dispatch.removeprefix("2. actions_run_trigger ")) == {
        "owner": "owner", "repo": "repo", "method": "run_workflow",
        "workflow_id": "ref-maintenance.yml", "ref": "main",
        "inputs": {"updates": triples, "dry_run": "true"}}
    assert "3. actions_list " in out and "4. get_job_logs " in out
    assert (f"Then: work_tickets.py refs request 5 --triples-file {file} --read-back --request-id "
            "<comment id from step 1>") in out


def run_log_file(tmp_path: Path, fake: FakeWorkflows) -> Path:
    path = tmp_path / "run.log"
    path.write_text(fake.log, encoding="utf-8")
    return path


def test_refs_request_read_back_checks_the_old_refs_and_hands_off_the_escalation(
        refs_checkout, tmp_path, monkeypatch, capsys):
    checkout, fake, base, ahead = refs_checkout
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    file = triples_file(tmp_path, f"{base} {ahead} refs/heads/main\n")
    arguments = ["refs", "request", "5", "--triples-file", str(file), "--repo", REPO, "--read-back",
                 "--request-id", "100", "--run-url", "https://git.example/owner/repo/actions/runs/9",
                 "--conclusion", "success", "--log-file", str(run_log_file(tmp_path, fake)),
                 "--worktree", str(checkout)]

    assert work_tickets.main(arguments) == 0
    out = capsys.readouterr().out
    assert "1. add_issue_comment " in out and "<!-- se:refs-request-id 100 -->" in out
    assert "set    refs/heads/main a -> b" in out and "##[group]" not in out
    assert "2. issue_write " in out and "<the issue's labels with escalated>" in out
    assert "after these steps, escalated #5: apply the ref change (1 ref(s), dry run passed)?" in out

    # origin moved main since the triples were written: nothing is escalated.
    assert git(checkout, "push", "-q", "origin", f"{ahead}:refs/heads/main").returncode == 0
    assert work_tickets.main(arguments) == 1
    captured = capsys.readouterr()
    assert "issue_write" not in captured.out
    assert "no longer holds refs/heads/main at the old sha" in captured.err
    assert fake.comments_posted == [] and fake.labels == set()


def test_refs_apply_hands_off_the_real_run_and_reads_the_new_refs_back(
        refs_checkout, tmp_path, monkeypatch, capsys):
    checkout, fake, base, ahead = refs_checkout
    triples = f"{base} {ahead} refs/heads/main\n"
    work_tickets.refs_request(checkout, 5, triples_file(tmp_path, triples), REPO)  # as gh did
    comments = tmp_path / "comments.json"
    comments.write_text(json.dumps(fake.comments_posted), encoding="utf-8")
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    posted, dispatched = len(fake.comments_posted), len(fake.dispatched)
    capsys.readouterr()

    assert work_tickets.main(["refs", "apply", "5", "--comments-file", str(comments), "--repo", REPO,
                              "--worktree", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert '"dry_run": "false"' in out and "1. actions_run_trigger " in out
    assert "--read-back --run-url <run url from step 2>" in out

    read_back = ["refs", "apply", "5", "--comments-file", str(comments), "--repo", REPO,
                 "--read-back", "--run-url", "https://git.example/owner/repo/actions/runs/9",
                 "--conclusion", "success", "--worktree", str(checkout)]
    assert work_tickets.main(read_back) == 1  # the session has not run it: main is still at base
    captured = capsys.readouterr()
    assert "not as requested on origin: refs/heads/main" in captured.err
    assert "refs not applied" in captured.out and "issue_write" not in captured.out

    assert git(checkout, "push", "-q", "origin", f"{ahead}:refs/heads/main").returncode == 0
    assert work_tickets.main(read_back) == 0
    out = capsys.readouterr().out
    assert "refs applied" in out and "<the issue's labels without escalated>" in out
    assert "after these steps, refs applied on #5" in out
    assert (len(fake.comments_posted), len(fake.dispatched)) == (posted, dispatched)


def test_refs_apply_without_gh_needs_the_saved_comments(refs_checkout, monkeypatch, capsys):
    checkout, fake, _, _ = refs_checkout
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    assert work_tickets.main(["refs", "apply", "5", "--repo", REPO, "--worktree", str(checkout)]) == 1
    assert "--comments-file <file>" in capsys.readouterr().err


def test_the_workflows_door_speaks_the_actions_api(monkeypatch, tmp_path):
    calls: list[tuple[list[str], object]] = []

    def gh(root: Path, arguments: list[str]) -> str:
        data = None
        if "--input" in arguments:
            data = json.loads(Path(arguments[arguments.index("--input") + 1]).read_text(encoding="utf-8"))
        calls.append((arguments[:4], data))
        path = arguments[3]
        if path.endswith("/runs?event=workflow_dispatch&per_page=1"):
            return json.dumps({"workflow_runs": [{"id": 41}]})
        if path.endswith("/jobs"):
            return json.dumps({"jobs": [{"id": 7}]})
        if path.endswith("/logs"):
            return "plain log\n"
        return ""

    monkeypatch.setattr(work_tickets, "run_gh", gh)
    door = work_tickets.Workflows(tmp_path, "github.com/owner/repo")
    assert door.newest_run("ref-maintenance.yml") == 41
    door.dispatch("ref-maintenance.yml", "main", {"updates": "x", "dry_run": "true"})
    assert door.run_log(41) == "plain log\n"
    assert calls == [
        (["api", "-X", "GET", "repos/owner/repo/actions/workflows/ref-maintenance.yml/runs?event=workflow_dispatch&per_page=1"], None),
        (["api", "-X", "POST", "repos/owner/repo/actions/workflows/ref-maintenance.yml/dispatches"],
         {"ref": "main", "inputs": {"updates": "x", "dry_run": "true"}}),
        (["api", "-X", "GET", "repos/owner/repo/actions/runs/41/jobs"], None),
        (["api", "-X", "GET", "repos/owner/repo/actions/jobs/7/logs"], None),
    ]


NOW = work_tickets.datetime(2026, 11, 12, 12, 0, tzinfo=work_tickets.timezone.utc)


def fleet_issue(number: int, title: str, *labels: str, state: str = "open", reason: str = "",
                blocked_by: tuple[int, ...] = ()) -> dict:
    blockers = "\n".join(f"#{blocker}" for blocker in blocked_by) or "None"
    return {"number": number, "title": title, "state": state, "state_reason": reason,
            "labels": [{"name": label} for label in labels],
            "body": f"## Goal\n\nWork.\n\n## Blocked by\n\n{blockers}\n",
            "html_url": f"https://github.com/owner/repo/issues/{number}"}


def fleet_pull(number: int, head: str, issue: int, mergeable: str = "clean",
               check: str = "success") -> dict:
    body = (f"{work_tickets.REPORT_BEGIN}\n**Work issue:** #{issue}\n{work_tickets.REPORT_END}\n")
    return {"number": number, "head": {"ref": head, "sha": f"{number:040d}"}, "body": body,
            "mergeable_state": mergeable, "check": check,
            "html_url": f"https://github.com/owner/repo/pull/{number}"}


class FakeFleet:
    """The fleet check's door: issues, pull requests and origin's branches, held in memory."""

    def __init__(self, issues: list[dict], pulls: list[dict] = (),
                 branches: dict[str, object] | None = None,
                 comments: dict[int, list[dict] | None] | None = None) -> None:
        self.issue_list, self.pull_list = list(issues), list(pulls)
        self.branch_times = dict(branches or {})
        self.comment_lists = dict(comments or {})
        self.calls: list[str] = []

    def __call__(self, root: Path, repo: str, base: str) -> "FakeFleet":
        return self

    def issues(self, state: str) -> list[dict]:
        self.calls.append(f"issues {state}")
        return [issue for issue in self.issue_list if issue["state"] == state]

    def issue(self, number: int) -> dict | None:
        self.calls.append(f"issue {number}")
        return next((issue for issue in self.issue_list if issue["number"] == number), None)

    def comments(self, number: int) -> list[dict] | None:
        self.calls.append(f"comments {number}")
        return self.comment_lists.get(number, [])

    def pulls(self) -> list[dict]:
        return list(self.pull_list)

    def branches(self) -> dict[str, object]:
        return dict(self.branch_times)


def fleet_findings(door: FakeFleet, tmp_path: Path) -> list:
    return work_tickets.fleet_findings(door, NOW, work_tickets.timedelta(hours=3), "repo")


def test_fleet_check_is_healthy_on_a_clean_fleet(tmp_path: Path) -> None:
    fresh = NOW - work_tickets.timedelta(minutes=20)
    door = FakeFleet(
        [fleet_issue(1, "feat/a", "work", "in-progress"), fleet_issue(2, "feat/b", "work", "ready"),
         fleet_issue(3, "feat/c", "work", state="closed", reason="completed"),
         fleet_issue(4, "feat/d", "work", "ready", blocked_by=(2,)),
         fleet_issue(5, "feat/elsewhere", "work", "in-progress", "repo:other")],
        [fleet_pull(10, "feat/a", 1)], {"main": fresh, "feat/a": fresh})
    assert fleet_findings(door, tmp_path) == []
    assert work_tickets.fleet_report([], as_json=False) == "healthy"
    assert json.loads(work_tickets.fleet_report([], as_json=True)) == {"healthy": True, "findings": []}


def test_fleet_check_finds_each_kind_once_with_its_remedy(tmp_path: Path) -> None:
    old = NOW - work_tickets.timedelta(hours=5)
    fresh = NOW - work_tickets.timedelta(minutes=5)
    door = FakeFleet(
        [fleet_issue(1, "feat/no-branch", "work", "in-progress", "repo:REPO"),
         fleet_issue(2, "feat/quiet", "work", "in-progress"),
         fleet_issue(3, "feat/red", "work", "in-progress"),
         fleet_issue(4, "feat/conflict", "work", "in-progress"),
         fleet_issue(5, "feat/landed", "work", state="closed", reason="completed"),
         fleet_issue(6, "feat/dropped", "work", state="closed", reason="not_planned"),
         fleet_issue(7, "feat/waits-on-dropped", "work", "ready", blocked_by=(6,)),
         fleet_issue(8, "feat/cycle-a", "work", "ready", blocked_by=(9,)),
         fleet_issue(9, "feat/cycle-b", "work", "ready", blocked_by=(8,)),
         fleet_issue(11, "Which name?", "se-person"),
         fleet_issue(12, "feat/after-answer", "work", "ready", blocked_by=(11,)),
         fleet_issue(13, "feat/after-that", "work", "ready", blocked_by=(12,))],
        [fleet_pull(20, "feat/red", 3, check="failure"),
         fleet_pull(21, "feat/conflict", 4, mergeable="dirty")],
        {"main": fresh, "feat/quiet": old, "feat/red": fresh, "feat/conflict": fresh,
         "feat/landed": old})
    found = fleet_findings(door, tmp_path)
    by_kind = {finding.kind: finding for finding in found}
    assert [finding.kind for finding in found] == list(work_tickets.FLEET_KINDS)
    assert (by_kind["no branch"].issue, by_kind["no branch"].branch) == (1, "feat/no-branch")
    assert "start" in by_kind["no branch"].remedy
    assert by_kind["quiet branch"].issue == 2 and "5 hours" in by_kind["quiet branch"].what
    assert (by_kind["failed check"].issue, by_kind["failed check"].pull) == (3, 20)
    assert "check" in by_kind["failed check"].remedy
    assert (by_kind["conflict"].issue, by_kind["conflict"].pull) == (4, 21)
    assert "merge origin/main" in by_kind["conflict"].remedy and "never rebase" in by_kind["conflict"].remedy
    assert (by_kind["stray branch"].issue, by_kind["stray branch"].branch) == (5, "feat/landed")
    assert "git push origin --delete feat/landed" in by_kind["stray branch"].remedy
    assert by_kind["impossible block"].issue == 7 and "#6" in by_kind["impossible block"].what
    assert by_kind["block cycle"].issue == 8 and "#8 -> #9 -> #8" in by_kind["block cycle"].what
    assert (by_kind["waiting on the person"].issue, by_kind["waiting on the person"].holds) == (11, (12, 13))
    report = work_tickets.fleet_report(found, as_json=False)
    assert "conflict #4 PR #21" in report and "remedy:" in report
    data = json.loads(work_tickets.fleet_report(found, as_json=True))
    assert data["healthy"] is False and data["findings"][3]["pull"] == 21
    # A closed blocker outside the lists is read once, through the door.
    assert door.calls.count("issue 6") == 0


def started_comment(ago: object, body: str = "Started: worker session on branch `feat/x`") -> dict:
    when = (NOW - ago).isoformat().replace("+00:00", "Z")
    return {"body": body, "created_at": when}


def test_fleet_check_lists_a_fresh_in_progress_issue_as_starting_not_stray(tmp_path: Path) -> None:
    hours = work_tickets.timedelta(hours=1)
    door = FakeFleet(
        [fleet_issue(1, "feat/fresh", "work", "in-progress"),
         fleet_issue(2, "feat/late", "work", "in-progress"),
         fleet_issue(3, "feat/no-started", "work", "in-progress"),
         fleet_issue(4, "feat/unread", "work", "in-progress")],
        comments={1: [started_comment(20 * work_tickets.timedelta(minutes=1))],
                  2: [started_comment(5 * hours), {"body": "a note", "created_at": "x"}],
                  3: [{"body": "Integrated in abc", "created_at": NOW.isoformat()}],
                  4: None})
    found = fleet_findings(door, tmp_path)
    assert [(finding.kind, finding.issue) for finding in found] == [
        ("no branch", 2), ("no branch", 3), ("no branch", 4), ("starting", 1)]
    by_issue = {finding.issue: finding for finding in found}
    assert not by_issue[1].stuck and "started 20 minutes ago" in by_issue[1].what
    assert "5 hours after its Started comment" in by_issue[2].what
    assert "cannot be counted: it has no Started: comment" in by_issue[3].what
    assert "cannot be counted: its comments were not read" in by_issue[4].what
    # Starting alone is healthy, and still listed.
    starting = [by_issue[1]]
    assert work_tickets.fleet_report(starting, as_json=False).splitlines()[0] == "healthy"
    assert "starting #1: started 20 minutes ago" in work_tickets.fleet_report(starting, False)
    assert json.loads(work_tickets.fleet_report(starting, as_json=True))["healthy"] is True


def test_fleet_check_reads_a_blocker_it_did_not_list_through_the_door(tmp_path: Path) -> None:
    door = FakeFleet([fleet_issue(7, "feat/waits", "work", "ready", blocked_by=(6,))])
    door.issue_list.append(fleet_issue(6, "feat/old", "work", state="closed", reason="not_planned"))
    door.issues = lambda state: [issue for issue in door.issue_list
                                 if issue["state"] == state and issue["number"] != 6]
    found = fleet_findings(door, tmp_path)
    assert [(finding.kind, finding.issue) for finding in found] == [("impossible block", 7)]
    assert door.calls == ["issue 6"]


def test_fleet_check_command_prints_findings_and_exits_one(tmp_path: Path, monkeypatch, capsys) -> None:
    door = FakeFleet([fleet_issue(1, "feat/no-branch", "work", "in-progress")], branches={})
    monkeypatch.setattr(work_tickets, "Fleet", door)
    monkeypatch.setattr(work_tickets, "hand_off", lambda: False)
    monkeypatch.setattr(work_tickets, "fleet_branches", lambda root: {})
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/owner/repo")
    assert work_tickets.main(["fleet-check", "--worktree", str(tmp_path), "--repo", "owner/repo"]) == 1
    assert "no branch #1" in capsys.readouterr().out


def test_fleet_check_reads_the_cores_fleet_live_and_falls_back_without_it(
        tmp_path: Path, monkeypatch, capsys) -> None:
    kern_names = work_tickets.sibling("kern_names")
    finding = {"kind": "conflict", "issue": 6, "pull": 106, "branch": "feat/f", "what": "feat/f conflicts",
               "remedy": "a worker on feat/f syncs", "holds": []}
    live = {"at": "2026-11-13T12:00:00Z", "issues": 12, "pulls": 3, "complete": True,
            "since": "2026-11-13T11:50:00Z", "findings": [finding]}
    asked = []
    monkeypatch.setattr(kern_names, "read", lambda root, names: asked.append(names) or {names[0]: live})
    monkeypatch.setattr(work_tickets, "Fleet", lambda *a: pytest.fail("the live read reads no GitHub"))
    arguments = ["fleet-check", "--worktree", str(tmp_path), "--repo", "owner/repo"]
    assert work_tickets.main(arguments) == 1
    assert capsys.readouterr().out.splitlines() == [
        "live from kern over the 12 issues and 3 pull requests it has read, complete since "
        "2026-11-13T11:50:00Z, 2026-11-13T12:00:00Z",
        "conflict #6 PR #106: feat/f conflicts", "  remedy: a worker on feat/f syncs"]
    assert work_tickets.main([*arguments, "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"healthy": False, "findings": [finding]}
    assert asked == [["fleet/findings"]] * 2
    # A core that has read no issue yet, only part of the open fleet, or none at all: the Python
    # check reads GitHub; the partial view says how much it saw and since when, never "healthy".
    partial = {**live, "issues": 1, "pulls": 0, "complete": False, "findings": []}
    for answer in ({"fleet/findings": {**live, "issues": 0}}, {"fleet/findings": partial}, None):
        monkeypatch.setattr(kern_names, "read", lambda root, names, answer=answer: answer)
        monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
        monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/owner/repo")
        assert work_tickets.main(arguments) == 0
        said = capsys.readouterr()
        assert "GitHub plan: fleet check" in said.out and "healthy" not in said.out
        assert ("kern has seen 1 issues and 0 pull requests since 2026-11-13T11:50:00Z, not a "
                "complete read" in said.err) == (answer is not None and answer["fleet/findings"] is partial)


def test_fleet_check_without_gh_prints_its_plan_then_reads_the_answers(
        tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "fleet_branches", lambda root: {"feat/landed": NOW})
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: "github.com/owner/repo")
    arguments = ["fleet-check", "--worktree", str(tmp_path), "--repo", "owner/repo"]
    assert work_tickets.main(arguments) == 0
    plan = capsys.readouterr().out
    assert "GitHub plan: fleet check" in plan and "list_issues" in plan
    assert "pull_request_read" in plan and "--open-issues" in plan
    open_file, closed_file, pulls_file = (tmp_path / name for name in ("open.json", "closed.json", "pulls.json"))
    open_file.write_text(json.dumps({"issues": []}), encoding="utf-8")
    closed_file.write_text(json.dumps([{**fleet_issue(5, "feat/landed", "work", state="closed"),
                                        "state": "CLOSED", "state_reason": "COMPLETED",
                                        "labels": ["work"]}]), encoding="utf-8")
    pulls_file.write_text("[]", encoding="utf-8")
    assert work_tickets.main([*arguments, "--open-issues", str(open_file), "--closed-issues",
                              str(closed_file), "--pulls", str(pulls_file), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [(item["kind"], item["issue"]) for item in data["findings"]] == [("stray branch", 5)]

    # The open issues carry their comments, as the plan says: a fresh one is starting, exit code 0.
    fresh = fleet_issue(1, "feat/fresh", "work", "in-progress")
    when = work_tickets.datetime.now(work_tickets.timezone.utc) - work_tickets.timedelta(minutes=5)
    open_file.write_text(json.dumps([{**fresh, "comments": [
        {"body": "Started: worker session", "createdAt": when.isoformat()}]}]), encoding="utf-8")
    closed_file.write_text("[]", encoding="utf-8")
    assert work_tickets.main([*arguments, "--open-issues", str(open_file), "--closed-issues",
                              str(closed_file), "--pulls", str(pulls_file)]) == 0
    assert capsys.readouterr().out.splitlines()[:2] == [
        "healthy", "starting #1: started 5 minutes ago, within the lease of 3 hours; origin has "
        "no branch feat/fresh yet"]


# The Stop hook: `stop-check` holds a worker's turn to a delivered pull request.

def stop_checkout(case_root: Path, monkeypatch, *, queue: bool = True) -> Path:
    """A worker's checkout on its branch, its ticket queue for a work issue unless `queue` is
    false; gh is not usable until a test fakes it."""
    root = case_root / "stop"
    root.mkdir(parents=True)
    quiet_git.init(root, "-b", "main")
    for key, value in (("user.name", "Worker test"), ("user.email", "worker-test@example.invalid")):
        assert git(root, "config", key, value).returncode == 0
    (root / ".gitignore").write_text("/.se/\n", encoding="utf-8")
    assert git(root, "add", ".").returncode == 0
    assert git(root, "commit", "-q", "-m", "baseline").returncode == 0
    assert git(root, "checkout", "-q", "-b", "feat/example-20261112").returncode == 0
    if queue:
        (root / ".se" / "work").mkdir(parents=True)
        (root / ".se" / "work" / "body-read.json").write_text('{"sha256": "0"}\n', encoding="utf-8")
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: False)
    monkeypatch.setattr(work_tickets, "_stop_gh_unusable_at", [])
    return root


def stop_hook(root: Path, monkeypatch, capsys, event: str = "Stop", **extra: str) -> dict:
    """Run stop-check as the plugin's hook runs it in `root`; its JSON answer, {} for none."""
    payload = {"hook_event_name": event, "cwd": str(root), "stop_hook_active": False, **extra}
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    assert work_tickets.main(["stop-check"]) == 0
    output = capsys.readouterr().out.strip()
    return json.loads(output) if output else {}


def delivered_description(root: Path) -> str:
    """A pull request description whose field report passes field-report --check at the tip."""
    from test_work_ticket_issues import COMPLETE_REPORT
    tip = git(root, "rev-parse", "HEAD").stdout.strip()
    return "Fixes https://git.example/owner/repo/issues/5\n\n" + COMPLETE_REPORT.replace(
        "**Branch tip:** `abc1234`", f"**Branch tip:** `{tip}`")


def fake_pull_requests(monkeypatch, root: Path, body: str | None) -> list[list[str]]:
    """gh signed in, answering one open pull request with `body`, or none where it is None."""
    calls: list[list[str]] = []

    def gh(_: Path, arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[:2] == ["pr", "list"]:
            return json.dumps([] if body is None else [{"number": 7, "url": "u"}])
        if arguments[:2] == ["pr", "view"]:
            return json.dumps({"body": body})
        raise AssertionError(arguments)

    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "_stop_gh_unusable_at", [])
    monkeypatch.setattr(work_tickets, "run_gh", gh)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda _: "git.example/owner/repo")
    return calls


def test_stop_check_refuses_a_worker_without_a_pull_request_naming_the_commands(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    fake_pull_requests(monkeypatch, root, None)
    answer = stop_hook(root, monkeypatch, capsys)
    assert answer["decision"] == "block"
    reason = answer["reason"]
    assert "(1 of 5 in a row)" in reason
    assert "Branch feat/example-20261112 has no open pull request to main" in reason
    assert "field-report --check" in reason and "deliver --worktree" in reason
    assert "stop-check --pull <number> --pr-description <file>" in reason


def test_stop_check_passes_a_worker_whose_pull_request_carries_a_passing_report(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    calls = fake_pull_requests(monkeypatch, root, delivered_description(root))
    assert stop_hook(root, monkeypatch, capsys) == {}
    assert [call[:2] for call in calls] == [["pr", "list"], ["pr", "view"]]


def test_stop_check_refuses_a_report_that_fails_the_check_or_lags_the_branch(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    fake_pull_requests(monkeypatch, root, "Fixes the issue, no report")
    reason = stop_hook(root, monkeypatch, capsys)["reason"]
    assert "holds no field report" in reason
    fake_pull_requests(monkeypatch, root, delivered_description(root))
    (root / "late.txt").write_text("late\n", encoding="utf-8")
    assert git(root, "add", ".").returncode == 0
    assert git(root, "commit", "-q", "-m", "late").returncode == 0
    reason = stop_hook(root, monkeypatch, capsys)["reason"]
    assert "(2 of 5 in a row)" in reason
    assert "a commit after delivery needs the check and the delivery again" in reason


def test_stop_check_without_gh_judges_by_the_recorded_pull_request_and_else_fails_open(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    answer = stop_hook(root, monkeypatch, capsys)
    assert "decision" not in answer
    assert "cannot judge" in answer["systemMessage"] and "gh is not usable" in answer["systemMessage"]

    description = tmp_path / "description.md"
    description.write_text("Fixes it\n", encoding="utf-8")
    assert work_tickets.main(["stop-check", "--pull", "7", "--pr-description", str(description),
                              "--worktree", str(root)]) == 1
    assert "the Stop hook would refuse" in capsys.readouterr().err
    assert stop_hook(root, monkeypatch, capsys)["decision"] == "block"

    description.write_text(delivered_description(root), encoding="utf-8")
    assert work_tickets.main(["stop-check", "--pull", "7", "--pr-description", str(description),
                              "--worktree", str(root)]) == 0
    assert "the Stop hook passes" in capsys.readouterr().out
    assert stop_hook(root, monkeypatch, capsys) == {}
    assert not (root / ".se" / "work" / work_tickets.STOP_COUNT).exists()  # a pass resets the count


def test_stop_check_never_refuses_without_a_work_issue_queue_or_for_other_agents(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch, queue=False)
    fake_pull_requests(monkeypatch, root, None)
    assert stop_hook(root, monkeypatch, capsys) == {}  # SE's or a person's session
    (root / ".se" / "work" / "todo").mkdir(parents=True)
    assert stop_hook(root, monkeypatch, capsys) == {}  # a queue, but for no work issue
    outside = tmp_path / "outside"
    outside.mkdir()
    assert stop_hook(outside, monkeypatch, capsys) == {}  # no checkout at all

    worker = stop_checkout(tmp_path / "worker", monkeypatch)
    fake_pull_requests(monkeypatch, worker, None)
    assert stop_hook(worker, monkeypatch, capsys, "SubagentStop", agent_type="Explore") == {}
    assert stop_hook(worker, monkeypatch, capsys, "SubagentStop") == {}  # an unnamed sub-agent
    blocked = stop_hook(worker, monkeypatch, capsys, "SubagentStop", agent_type="se:worker")
    assert blocked["decision"] == "block"
    assert git(worker, "checkout", "-q", "main").returncode == 0
    assert stop_hook(worker, monkeypatch, capsys) == {}  # the integration branch: no worker's


def test_stop_check_refuses_at_most_its_cap_in_a_row(tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    (root / "se.toml").write_text("[stop]\nrefusals = 2\n", encoding="utf-8")
    fake_pull_requests(monkeypatch, root, None)
    assert "(1 of 2 in a row)" in stop_hook(root, monkeypatch, capsys)["reason"]
    assert "(2 of 2 in a row)" in stop_hook(root, monkeypatch, capsys)["reason"]
    released = stop_hook(root, monkeypatch, capsys)
    assert "decision" not in released
    assert "refused 2 times in a row; the turn may end undelivered" in released["systemMessage"]
    assert "(1 of 2 in a row)" in stop_hook(root, monkeypatch, capsys)["reason"]  # counted afresh
    (root / "se.toml").unlink()
    assert work_tickets.stop_refusals(root) == 5  # built in


def subagent_transcript(path: Path, prompt: str, *commands: str) -> Path:
    """A sub-agent's transcript: its prompt, then one Bash call per command."""
    entries = [{"type": "user", "message": {"role": "user", "content": prompt}}]
    entries += [{"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}
                for command in commands]
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    return path


def test_stop_check_judges_the_hook_kern_hands_it_as_the_one_on_stdin(
        tmp_path, monkeypatch, capsys):
    root = stop_checkout(tmp_path, monkeypatch)
    fake_pull_requests(monkeypatch, root, None)
    payload = {"hook_event_name": "Stop", "cwd": str(root), "stop_hook_active": False}
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(""))
    assert work_tickets.main(["stop-check", "--hook", json.dumps(payload)]) == 0
    from_kern = json.loads(capsys.readouterr().out)
    (root / ".se" / "work" / work_tickets.STOP_COUNT).unlink()
    assert from_kern == stop_hook(root, monkeypatch, capsys)
    assert from_kern["decision"] == "block"


def test_stop_check_holds_an_unusable_gh_a_while_and_a_usable_one_for_the_process(monkeypatch):
    asked: list[bool] = []
    usable = [False]
    monkeypatch.setattr(work_tickets, "gh_usable", lambda: asked.append(True) or usable[0])
    monkeypatch.setattr(work_tickets, "_stop_gh_unusable_at", [])
    clock = [1000.0]
    monkeypatch.setattr(work_tickets.time, "monotonic", lambda: clock[0])
    assert (work_tickets.stop_gh_usable(), work_tickets.stop_gh_usable()) == (False, False)
    assert len(asked) == 1
    usable[0] = True
    clock[0] += work_tickets.STOP_GH_UNUSABLE_FOR
    assert work_tickets.stop_gh_usable() and len(asked) == 2


def test_stop_check_judges_a_worker_sub_agent_in_the_worktree_its_prompt_names(
        tmp_path, monkeypatch, capsys):
    worktree = stop_checkout(tmp_path / "worktree", monkeypatch)
    session = stop_checkout(tmp_path / "session", monkeypatch, queue=False)  # the hook's cwd
    other = stop_checkout(tmp_path / "other", monkeypatch)
    fake_pull_requests(monkeypatch, worktree, None)
    transcript = subagent_transcript(
        tmp_path / "agent.jsonl", f"Work issue #5. Your worktree: {worktree}.",
        f"cat {other}/.se/work/todo/1.md")
    answer = stop_hook(session, monkeypatch, capsys, "SubagentStop", agent_type="se:worker",
                       agent_transcript_path=str(transcript))
    assert answer["decision"] == "block"
    assert f"--worktree {worktree}" in answer["reason"]
    assert (worktree / ".se" / "work" / work_tickets.STOP_COUNT).exists()
    assert not (other / ".se" / "work" / work_tickets.STOP_COUNT).exists()


def test_stop_check_judges_a_worker_sub_agent_in_the_queue_its_transcript_last_touched(
        tmp_path, monkeypatch, capsys):
    first = stop_checkout(tmp_path / "first", monkeypatch)
    last = stop_checkout(tmp_path / "last", monkeypatch)
    session = stop_checkout(tmp_path / "session", monkeypatch, queue=False)
    fake_pull_requests(monkeypatch, last, None)
    transcript = subagent_transcript(
        tmp_path / "agent.jsonl", "Work issue #5, no path named.",
        f"uv run python scripts/work_tickets.py status --worktree {first}",
        f"ls {last}/.se/work/todo", "git status")
    answer = stop_hook(session, monkeypatch, capsys, "SubagentStop", agent_type="worker",
                       agent_transcript_path=str(transcript))
    assert f"--worktree {last}" in answer["reason"]


def test_stop_check_falls_back_to_the_cwd_and_says_why_it_cannot_judge_a_worker_sub_agent(
        tmp_path, monkeypatch, capsys):
    cwd = stop_checkout(tmp_path / "cwd", monkeypatch)
    fake_pull_requests(monkeypatch, cwd, None)
    transcript = subagent_transcript(tmp_path / "agent.jsonl", "Work in /nowhere/at/all.", "ls /tmp")
    event = {"agent_type": "se:worker", "agent_transcript_path": str(transcript)}
    assert stop_hook(cwd, monkeypatch, capsys, "SubagentStop", **event)["decision"] == "block"
    session = stop_checkout(tmp_path / "session", monkeypatch, queue=False)
    note = stop_hook(session, monkeypatch, capsys, "SubagentStop", **event)["systemMessage"]
    assert "cannot judge the worker sub-agent's delivery" in note
    assert "neither its prompt nor its transcript names a checkout" in note and str(session) in note
    missing = {**event, "agent_transcript_path": str(tmp_path / "gone.jsonl")}
    assert "cannot judge" in stop_hook(session, monkeypatch, capsys, "SubagentStop", **missing)[
        "systemMessage"]


# Metrics (README "Metrics")


class FakeClock:
    """A monotonic clock and a wall clock that move only when told."""

    def __init__(self, monkeypatch, start: str = "2026-11-10T08:00:00+00:00") -> None:
        self.seconds = 100.0
        self.wall = work_tickets.datetime.fromisoformat(start)
        monkeypatch.setattr(work_tickets.metrics, "clock", lambda: self.seconds)
        monkeypatch.setattr(work_tickets.metrics, "now", lambda: self.wall)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def metrics_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_command_appends_one_metrics_line_with_its_github_calls(tmp_path, monkeypatch, capsys):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("SE_METRICS", str(path))
    clock = FakeClock(monkeypatch)
    answers = iter([
        subprocess.CompletedProcess([], 1, "", "HTTP 403: API rate limit exceeded"),
        subprocess.CompletedProcess([], 0, "{}", ""),
    ])

    def door(*_, **__):  # the fake door: gh answers without GitHub
        clock.advance(2.5)
        return next(answers)

    monkeypatch.setattr(work_tickets, "gh_executable", lambda: "gh")
    monkeypatch.setattr(work_tickets.subprocess, "run", door)
    monkeypatch.setattr(work_tickets, "wait", lambda seconds: clock.advance(seconds))

    def handler(root, args):
        with pytest.raises(work_tickets.QueueError):
            work_tickets.run_gh(tmp_path, ["api", "user"])
        work_tickets.github_wait(60)
        work_tickets.run_gh(tmp_path, ["api", "user"])
        return 0

    monkeypatch.setattr(work_tickets, "run_command", lambda args: handler(None, args))

    assert work_tickets.main(["metrics"]) == 0

    assert metrics_lines(path) == [{
        "command": "work_tickets.py metrics", "start": "2026-11-10T08:00:00Z",
        "wall_seconds": 65.0, "gh_calls": 2, "gh_refusals": 1, "gh_wait_seconds": 60.0,
        "exit_code": 0, "budget_seconds": 5.0,  # metrics is interactive (feedback.py)
    }]


def test_a_group_command_is_recorded_by_its_words_and_its_exit_code(tmp_path, monkeypatch, capsys):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("SE_METRICS", str(path))
    FakeClock(monkeypatch)

    assert work_tickets.main(["field-report", "--check", str(tmp_path / "missing.md")]) == 1

    line, = metrics_lines(path)
    assert (line["command"], line["exit_code"]) == ("work_tickets.py field-report", 1)
    assert work_tickets.command_words(work_tickets.make_parser().parse_args(
        ["refs", "apply", "7", "--worktree", "."])) == ["refs", "apply"]


def test_a_metrics_write_that_fails_never_fails_the_command(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("SE_METRICS", str(blocker / "metrics.jsonl"))  # its parent is a file

    assert work_tickets.main(["metrics", "--file", str(tmp_path / "none.jsonl")]) == 0
    assert "Metrics: 0 runs" in capsys.readouterr().out


def test_integrate_notes_the_suite_and_the_landed_issue_and_prints_its_line(
        tmp_path, monkeypatch, capsys):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("SE_METRICS", str(path))
    clock = FakeClock(monkeypatch)

    def integrate(root, args):
        work_tickets.metrics.note(issue=749)
        clock.advance(130)
        work_tickets.metrics.note(suite_seconds=130.0, suite_limit_seconds=120)
        return 0

    monkeypatch.setattr(work_tickets, "run_command", lambda args: integrate(None, args))

    assert work_tickets.main(["integrate", "7", "--worktree", str(tmp_path)]) == 0

    line, = metrics_lines(path)
    assert (line["issue"], line["suite_seconds"], line["suite_limit_seconds"]) == (749, 130.0, 120)
    assert f"Metrics: {json.dumps(line, sort_keys=True)}" in capsys.readouterr().out


def test_the_metrics_report_ranks_spenders_and_flags_an_overrun():
    lines = [
        {"command": "work_tickets.py sync", "start": "2026-11-01T09:00:00Z", "wall_seconds": 900,
         "gh_calls": 1, "gh_refusals": 0, "gh_wait_seconds": 0, "exit_code": 0},
        {"command": "work_tickets.py integrate", "start": "2026-11-10T09:00:00Z",
         "wall_seconds": 300, "gh_calls": 40, "gh_refusals": 2, "gh_wait_seconds": 120,
         "exit_code": 0, "issue": 749, "suite_seconds": 130.5, "suite_limit_seconds": 120},
        {"command": "work_tickets.py sync", "start": "2026-11-11T09:00:00Z", "wall_seconds": 5,
         "gh_calls": 0, "gh_refusals": 0, "gh_wait_seconds": 0, "exit_code": 0},
        {"command": "se_start.py status", "start": "2026-11-12T09:00:00Z", "wall_seconds": 1.5,
         "gh_calls": 0, "gh_refusals": 0, "gh_wait_seconds": 0, "exit_code": 0,
         "budget_seconds": 1.0},
        {"command": "work_tickets.py suite", "start": "2026-11-12T10:00:00Z", "wall_seconds": 50,
         "gh_calls": 0, "gh_refusals": 0, "gh_wait_seconds": 0, "exit_code": 0,
         "suite_seconds": 49, "suite_limit_seconds": 120},
    ]

    text = work_tickets.metrics.report(lines, since="2026-11-10")

    assert text.splitlines() == [
        "Metrics: 4 runs since 2026-11-10",
        "Top spenders by wall time:",
        "  work_tickets.py integrate: 1 runs, 300.0 s wall, 40 GitHub calls, 2 refused, 120 s waiting",
        "  work_tickets.py suite: 1 runs, 50.0 s wall, 0 GitHub calls, 0 refused, 0 s waiting",
        "  work_tickets.py sync: 1 runs, 5.0 s wall, 0 GitHub calls, 0 refused, 0 s waiting",
        "  se_start.py status: 1 runs, 1.5 s wall, 0 GitHub calls, 0 refused, 0 s waiting",
        "Top spenders by GitHub calls:",
        "  work_tickets.py integrate: 1 runs, 300.0 s wall, 40 GitHub calls, 2 refused, 120 s waiting",
        "Overruns: 2",
        "  2026-11-10T09:00:00Z work_tickets.py integrate #749: suite 130.5 s over its budget 120 s",
        "  2026-11-12T09:00:00Z se_start.py status: wall time 1.5 s over its budget 1 s",
    ]


def test_the_metrics_report_flags_a_suite_beside_over_its_limit_as_it_does_the_suite():
    line = {"command": "work_tickets.py suite", "start": "2026-11-13T10:00:00Z", "wall_seconds": 90,
            "suite_seconds": 49, "suite_limit_seconds": 120,
            "beside_seconds": {"kern": 61.5, "web": 10}, "beside_limit_seconds": {"kern": 60, "web": 30}}

    assert work_tickets.metrics.overruns(line) == ["suite kern 61.5 s over its budget 60 s"]
    assert work_tickets.metrics.report([line]).splitlines()[-2:] == [
        "Overruns: 1",
        "  2026-11-13T10:00:00Z work_tickets.py suite: suite kern 61.5 s over its budget 60 s",
    ]


def test_the_metrics_command_reads_its_file_and_skips_unreadable_lines(tmp_path, capsys):
    source = tmp_path / "metrics.jsonl"
    source.write_text('{"command": "work_tickets.py sync", "start": "2026-11-12T00:00:00Z", '
                      '"wall_seconds": 3}\nnot json\n', encoding="utf-8")

    assert work_tickets.main(["metrics", "--file", str(source), "--since", "2026-11-12"]) == 0

    out = capsys.readouterr().out
    assert "Metrics: 1 runs since 2026-11-12 in" in out and "1 unreadable lines skipped" in out
    assert "work_tickets.py sync: 1 runs, 3.0 s wall" in out
    with pytest.raises(SystemExit):
        work_tickets.make_parser().parse_args(["metrics", "--since", "12 Nov"])


PAUSE_REPO = "github.com/owner/repo"
PAUSE_ISSUE = {"number": 3, "title": "Pause the fleet", "url": "https://github.com/owner/repo/issues/3"}


def pause_door(monkeypatch, paused: bool, answers=lambda arguments: None) -> list[list[str]]:
    """gh signed in, the pause search answering PAUSE_ISSUE where `paused`, every other call
    by `answers` (a call it answers None for fails the test); the calls made."""
    calls: list[list[str]] = []

    def gh(_: Path, arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[:6] == ["issue", "list", "--state", "open", "--label", "pause"]:
            return json.dumps([PAUSE_ISSUE] if paused else [])
        answer = answers(arguments)
        if answer is None:
            raise AssertionError(f"gh {arguments} while {'paused' if paused else 'not paused'}")
        return answer

    monkeypatch.setattr(work_tickets, "gh_usable", lambda: True)
    monkeypatch.setattr(work_tickets, "run_gh", gh)
    return calls


def only_the_pause_search(calls: list[list[str]]) -> bool:
    return [call[:6] for call in calls] == [["issue", "list", "--state", "open", "--label", "pause"]]


def assert_paused_refusal(code: int, error: str, command: str) -> None:
    assert code == 1
    assert (f"work_tickets.py {command}: the fleet is paused by the open pause issue "
            f"#3 Pause the fleet {PAUSE_ISSUE['url']}") in error
    assert "closing it" in error


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_paused_answers_by_the_open_pause_issue(worktree, monkeypatch, capsys, paused):
    calls = pause_door(monkeypatch, paused)

    code = work_tickets.main(["paused", "--worktree", str(worktree), "--repo", PAUSE_REPO])

    out = capsys.readouterr().out
    assert only_the_pause_search(calls) and calls[0][-2:] == ["--repo", PAUSE_REPO]
    if paused:
        assert code == 1 and f"Paused by #3 Pause the fleet {PAUSE_ISSUE['url']}" in out
    else:
        assert code == 0 and f"Not paused: no open issue labelled pause in {PAUSE_REPO}" in out


def test_paused_hands_its_search_off_as_a_plan_without_gh(worktree, monkeypatch, capsys):
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    monkeypatch.setattr(work_tickets, "run_gh", lambda root, args: pytest.fail(f"gh {args}"))

    assert work_tickets.main(["paused", "--worktree", str(worktree), "--repo", PAUSE_REPO]) == 2

    out = capsys.readouterr().out
    assert out.startswith(f"GitHub plan: paused? pause issues of {PAUSE_REPO}\n1. list_issues "
                          '{"labels": ["pause"], "owner": "owner", "perPage": 20, "repo": "repo", '
                          '"state": "OPEN"}')
    assert "the fleet is paused: stop here" in out and "Then: no issue listed: not paused" in out


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_queue_refuses_while_paused(worktree, monkeypatch, capsys, paused):
    calls = pause_door(monkeypatch, paused, lambda arguments: "[]")  # no escalations
    monkeypatch.setattr(work_tickets, "sync", lambda root: "abc1234")
    monkeypatch.setattr(work_tickets, "delivered_pull_requests", lambda root, repo: [])
    monkeypatch.setattr(work_tickets, "ready_issues",
                        lambda root, repo, all_repos: [{"number": 1, "title": "feat/one"}])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo, all_repos: 2)

    code = work_tickets.main(["queue", "--worktree", str(worktree), "--repo", PAUSE_REPO])

    captured = capsys.readouterr()
    assert any("pause" in call for call in calls)
    if paused:
        assert_paused_refusal(code, captured.err, "queue")
        assert "ready #1" not in captured.out  # nothing to start is offered
    else:
        assert code == 0 and "ready #1 feat/one" in captured.out


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_start_refuses_while_paused(worktree, monkeypatch, capsys, paused):
    calls = pause_door(monkeypatch, paused,
                       lambda arguments: "" if arguments[:2] == ["issue", "edit"] else None)
    read: list[int] = []
    monkeypatch.setattr(work_tickets, "ready_issues", lambda root, repo, allow_existing_branch=False:
                        read.append(1) or [{"number": 5, "title": "feat/five"}])
    monkeypatch.setattr(work_tickets, "capacity", lambda root, repo: 1)

    code = work_tickets.main(["start", "5", "--cloud-agent", "bot", "--worktree", str(worktree),
                              "--repo", PAUSE_REPO])

    captured = capsys.readouterr()
    if paused:
        assert_paused_refusal(code, captured.err, "start")
        assert only_the_pause_search(calls) and read == []  # nothing read, nothing labelled
    else:
        assert code == 0 and "Started #5" in captured.out
        assert ["issue", "edit", "5", "--add-assignee", "bot", "--remove-label", "ready",
                "--add-label", "in-progress", "--repo", PAUSE_REPO] in calls


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_integrate_refuses_while_paused(worktree, monkeypatch, capsys, paused):
    calls = pause_door(monkeypatch, paused)
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: None)  # the next step's refusal

    code = work_tickets.main(["integrate", "7", "--worktree", str(worktree), "--repo", PAUSE_REPO])

    error = capsys.readouterr().err
    assert only_the_pause_search(calls)  # paused: before anything else; unpaused: on to landing
    if paused:
        assert_paused_refusal(code, error, "integrate")
    else:
        assert code == 1 and "has no origin remote to land on" in error


@pytest.mark.parametrize("paused", [True, False], ids=["paused", "unpaused"])
def test_the_landing_plan_runs_the_pause_search_before_it_opens_the_pull_request(
        worktree, monkeypatch, paused):
    pause_door(monkeypatch, paused)
    plan = work_tickets.landing_plan("github.com/owner/repo", "land/feat/x", "main", "a" * 40,
                                     "b" * 40, "Integrate feat/x", "Release-kind: minor", "body",
                                     "then", PAUSE_REPO)
    step = plan.steps[0]
    assert (step.action, step.tool) == ("paused", "list_issues")
    assert step.arguments["labels"] == ["pause"]
    paused_action = work_tickets.landing_actions(worktree, None, "land/feat/x", "main", "a" * 40,
                                                 PAUSE_REPO)["paused"]
    if paused:
        with pytest.raises(work_tickets.PausedError, match="integrate: the fleet is paused"):
            paused_action({}, "")
    else:
        assert paused_action({}, "") is None


def test_route_routes_nothing_while_paused(worktree, monkeypatch, capsys):
    calls = pause_door(monkeypatch, True)
    routing = worktree / "route.md"
    routing.write_text("## Requirements\n\n1. One.\n", encoding="utf-8")

    code = work_tickets.main(["route", "1", "--routing-file", str(routing),
                              "--worktree", str(worktree), "--repo", PAUSE_REPO])

    assert_paused_refusal(code, capsys.readouterr().err, "route")
    assert only_the_pause_search(calls)  # the issue is neither read nor edited


BUDGET_SUITE = 'print("0.20s call     tests/test_fast.py::test_quick")\nprint("3 passed")\n'


def budget_suite(root: Path, monkeypatch, seconds: float, ci: float | None,
                 extra: str = "") -> list[int]:
    """A suite in se.toml `[tests]` (limit 120 s, plus the `extra` lines) that a fake clock times
    at `seconds`, and CI's suite time on main faked as `ci` (None: unknown); returns a list
    that counts CI reads."""
    (root / "suite.py").write_text(BUDGET_SUITE, encoding="utf-8")
    (root / "se.toml").write_text(
        f"[tests]\ncommand = {json.dumps([sys.executable, 'suite.py'])}\n"
        f"target_seconds = 60\nlimit_seconds = 120\n{extra}", encoding="utf-8")
    readings = iter([0.0, seconds])
    monkeypatch.setattr(work_tickets, "clock", lambda: next(readings))
    reads: list[int] = []

    def ci_suite_time(checkout):
        reads.append(1)
        if ci is None:
            return None, "no successful check run on the last 5 commits of origin/main reports one"
        return work_tickets.CiSuiteTime(ci, "a" * 40, "https://github.com/o/r/runs/1"), ""

    monkeypatch.setattr(work_tickets, "ci_suite_time", ci_suite_time)
    return reads


def test_a_slow_local_suite_with_a_fast_ci_time_passes_with_a_warning_and_notes_both_times(
        worktree, monkeypatch, capsys):
    path = worktree / "metrics.jsonl"
    monkeypatch.setenv("SE_METRICS", str(path))
    budget_suite(worktree, monkeypatch, 130.0, 45.0)

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == 0

    captured = capsys.readouterr()
    assert "warning: the complete suite took 130.0 s here (" in captured.err
    assert re.search(r"here \((load [\d./]+ \(1/5/15 min\) on|\d+ CPUs, load average)", captured.err)
    assert "CI's suite time on main is 45.0 s, from its last run (commit aaaaaaaaaaaa" in captured.err
    assert "CI's check on the landing pull request judges the budget" in captured.err
    assert "Suite: 3 passed; 130.0 s (target 60 s, limit 120 s)" in captured.out
    line, = metrics_lines(path)
    assert (line["suite_seconds"], line["ci_suite_seconds"]) == (130.0, 45.0)


@pytest.mark.parametrize("ci", [108.0, 130.0, None])
def test_a_local_overrun_with_ci_close_to_the_limit_or_unknown_refuses(
        worktree, monkeypatch, capsys, ci):
    budget_suite(worktree, monkeypatch, 130.0, ci)

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == \
        work_tickets.SUITE_OVER_LIMIT_EXIT_CODE
    error = capsys.readouterr().err
    assert "Complete suite passed (3 passed) but took 130.0 s here (" in error
    assert "over its limit of 120 s" in error and "test_quick" in error
    if ci is None:
        assert "CI's suite time is unknown: no successful check run" in error
        assert "so this run decides" in error
    else:
        assert f"CI's suite time on main is {ci:.1f} s" in error
        assert "within 10% of the limit" in error


def test_a_ci_suite_over_the_limit_fails_check_with_its_time_and_slowest_tests(
        worktree, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    reads = budget_suite(worktree, monkeypatch, 130.0, 10.0)

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == \
        work_tickets.SUITE_OVER_LIMIT_EXIT_CODE

    captured = capsys.readouterr()
    assert "::notice title=se suite time::Suite time: 130.0 s (limit 120 s)" in captured.out
    assert ("Complete suite passed (3 passed) but took 130.0 s on CI, the budget's reference, "
            "over its limit of 120 s") in captured.err
    assert "0.20s call tests/test_fast.py::test_quick" in captured.err
    assert reads == []  # the reference reads no other time


@pytest.mark.parametrize("reference", [True, False], ids=["ci", "local"])
def test_an_overrun_only_warns_where_the_project_declares_warn_only(
        worktree, monkeypatch, capsys, reference):
    if reference:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    budget_suite(worktree, monkeypatch, 130.0, 118.0, 'over_limit = "warn"\n')

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == 0

    captured = capsys.readouterr()
    assert "warning: the complete suite took 130.0 s" in captured.err
    assert ('over its limit of 120 s; [tests] over_limit = "warn" in se.toml, so the overrun '
            "is not refused") in captured.err
    assert "Suite: 3 passed; 130.0 s (target 60 s, limit 120 s)" in captured.out


def test_over_limit_takes_fail_or_warn_only(worktree, monkeypatch, capsys):
    budget_suite(worktree, monkeypatch, 40.0, None, 'over_limit = "ignore"\n')

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == 1
    assert 'over_limit must be "fail" (the default) or "warn"' in capsys.readouterr().err


def test_a_ci_suite_within_the_limit_reports_its_time_as_a_notice(worktree, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    budget_suite(worktree, monkeypatch, 40.0, None)

    assert work_tickets.main(["suite", "--worktree", str(worktree)]) == 0
    assert "::notice title=se suite time::Suite time: 40.0 s (limit 120 s)" in capsys.readouterr().out


def test_a_local_suite_within_the_limit_reads_ci_only_for_integrate(worktree, monkeypatch, capsys):
    reads = budget_suite(worktree, monkeypatch, 40.0, 45.0)

    work_tickets.run_suite(worktree)
    assert reads == []
    monkeypatch.setattr(work_tickets, "clock", iter([0.0, 40.0]).__next__)
    work_tickets.run_suite(worktree, read_ci=True)
    assert reads == [1]


def record_two_shards(root: Path, monkeypatch, fast: float, slow: float) -> Path:
    """Two shards, `fast` and `slow`, recorded by suite-shard as a fake clock times them."""
    records = root / "shards"
    for name, seconds in (("fast", fast), ("slow", slow)):
        monkeypatch.setattr(work_tickets, "clock", iter([0.0, seconds]).__next__)
        assert work_tickets.main(["suite-shard", "--worktree", str(root), "--name", name,
                                  "--record", str(records), "--",
                                  sys.executable, "-c", "print('shard ran')"]) == 0
    return records


def test_a_sharded_suite_reports_its_slowest_shard_as_ci_s_suite_time(
        worktree, monkeypatch, capsys):
    budget_suite(worktree, monkeypatch, 0.0, None)
    records = record_two_shards(worktree, monkeypatch, 20.0, 55.5)
    assert json.loads((records / "slow.json").read_text(encoding="utf-8")) == {
        "shard": "slow", "seconds": 55.5, "exit_code": 0}

    assert work_tickets.main(["suite-time", "--worktree", str(worktree), "--shards", str(records),
                              "--expect", "2"]) == 0

    out = capsys.readouterr().out
    assert "  fast: 20.0 s, exit code 0\n  slow: 55.5 s, exit code 0" in out
    assert ("::notice title=se suite time::Suite time: 55.5 s (limit 120 s; slowest of 2 shards: "
            "55.5 s (shard slow))") in out


def test_the_shards_notice_round_trips_through_ci_suite_time(
        worktree, tmp_path, monkeypatch, capsys):
    read_ci = work_tickets.ci_suite_time  # the real one, reading the fake check run below
    budget_suite(worktree, monkeypatch, 0.0, None)
    records = record_two_shards(worktree, monkeypatch, 20.0, 55.5)
    work_tickets.main(["suite-time", "--worktree", str(worktree), "--shards", str(records)])
    notice, = (line for line in capsys.readouterr().out.splitlines() if line.startswith("::notice"))
    title, message = re.fullmatch(r"::notice title=(.*?)::(.*)", notice).groups()
    root = quiet_git.init(tmp_path / "repo", "-b", "main")
    subprocess.run(["git", "-C", str(root), "-c", "user.name=a", "-c", "user.email=a@example.com",
                    "commit", "-q", "--allow-empty", "-m", "one"], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "https://github.com/example/repo.git"], check=True)
    subprocess.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", "HEAD"],
                   check=True)

    def github_read(repo, path):
        if path.startswith("commits/"):
            return {"check_runs": [{"id": 3, "status": "completed", "conclusion": "success",
                                    "html_url": "u"}]}
        return [{"title": title, "message": message}]

    monkeypatch.setattr(work_tickets, "github_read", github_read)
    found, _ = read_ci(root)
    assert found is not None and found.seconds == 55.5


@pytest.mark.parametrize("warn_only", [False, True], ids=["fail", "warn"])
def test_a_sharded_overrun_fails_unless_the_project_declares_warn_only(
        worktree, monkeypatch, capsys, warn_only):
    budget_suite(worktree, monkeypatch, 0.0, None, 'over_limit = "warn"\n' if warn_only else "")
    records = record_two_shards(worktree, monkeypatch, 20.0, 130.0)

    code = work_tickets.main(["suite-time", "--worktree", str(worktree), "--shards", str(records)])

    out = capsys.readouterr().out.splitlines()
    level = "warning" if warn_only else "error"
    annotation, = (line for line in out if line.startswith(f"::{level}::"))
    assert out.index(annotation) > out.index("Shards:")
    if warn_only:
        assert code == 0 and '[tests] over_limit = "warn" in se.toml' in annotation
    else:
        assert code == work_tickets.SUITE_OVER_LIMIT_EXIT_CODE
        assert "took 130.0 s, the slowest of 2 shards (shard slow)" in annotation
        assert "over its limit ([tests] limit_seconds in se.toml)" in annotation


def test_a_failed_or_missing_shard_fails_the_suite_time(worktree, monkeypatch, capsys):
    budget_suite(worktree, monkeypatch, 0.0, None)
    records = record_two_shards(worktree, monkeypatch, 20.0, 30.0)
    arguments = ["suite-time", "--worktree", str(worktree), "--shards", str(records)]

    assert work_tickets.main([*arguments, "--expect", "3"]) == 1
    assert "::error::suite-time: 2 shard records in" in capsys.readouterr().out
    monkeypatch.setattr(work_tickets, "clock", iter([0.0, 5.0]).__next__)
    assert work_tickets.main(["suite-shard", "--worktree", str(worktree), "--name", "red",
                              "--record", str(records), "--", sys.executable, "-c",
                              "raise SystemExit(4)"]) == 4
    capsys.readouterr()
    assert work_tickets.main(arguments) == 1
    out = capsys.readouterr().out
    assert "Suite time" not in out  # a failed run's shorter time never stands as CI's
    assert "::notice" not in out
    error, = (line for line in out.splitlines() if line.startswith("::error::"))
    assert error.startswith("::error::suite-time: the run failed: shard red failed (exit code 4)")
    assert out.index("  red: 5.0 s, exit code 4") < out.index("::error::")


def test_a_sharded_suite_over_its_target_warns_as_an_annotation(worktree, monkeypatch, capsys):
    budget_suite(worktree, monkeypatch, 0.0, None)
    records = record_two_shards(worktree, monkeypatch, 20.0, 70.0)
    capsys.readouterr()

    assert work_tickets.main(["suite-time", "--worktree", str(worktree), "--shards",
                              str(records)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert ("::warning::the sharded suite took 70.0 s, over its target of 60 s ([tests] "
            "target_seconds in se.toml)") in captured.out.splitlines()


def test_a_workflow_annotation_keeps_line_breaks_and_percent_signs_as_text():
    assert work_tickets.workflow_annotation("error", "100% done\nnext\r") == \
        "::error::100%25 done%0Anext%0D"


def test_ci_suite_time_reads_the_notice_of_the_newest_completed_check_on_main(
        tmp_path, monkeypatch):
    root = quiet_git.init(tmp_path / "repo", "-b", "main")
    for name in ("one", "two"):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=a", "-c", "user.email=a@example.com",
                        "commit", "-q", "--allow-empty", "-m", name], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "https://github.com/example/repo.git"], check=True)
    subprocess.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", "HEAD"],
                   check=True)
    tip, parent = subprocess.run(["git", "-C", str(root), "rev-list", "HEAD"], capture_output=True,
                                 text=True, check=True).stdout.split()
    runs = {tip: [{"id": 9, "status": "in_progress"}],
            parent: [{"id": 7, "status": "completed", "conclusion": "success",
                      "html_url": "https://github.com/run/7"}]}
    notes = {7: [{"title": "", "message": "Node.js 20 is deprecated"},
                 {"title": "se suite time", "message": "Suite time: 48.5 s (limit 120 s)"}]}
    paths: list[str] = []

    def github_read(repo, path):
        paths.append(path)
        assert repo == "github.com/example/repo"
        if path.startswith("commits/"):
            return {"check_runs": runs[path.split("/")[1]]}
        return notes[int(path.split("/")[1])]

    monkeypatch.setattr(work_tickets, "github_read", github_read)

    found, reason = work_tickets.ci_suite_time(root)

    assert (found, reason) == (
        work_tickets.CiSuiteTime(48.5, parent, "https://github.com/run/7", (48.5,)), "")
    assert paths == [f"commits/{tip}/check-runs?check_name=check",
                     f"commits/{parent}/check-runs?check_name=check", "check-runs/7/annotations"]
    notes[7] = []
    assert work_tickets.ci_suite_time(root) == (None, (
        "no successful check run on the last 2 commits of origin/main reports a suite time"))


def fake_ci_runs(tmp_path, monkeypatch, runs: list[tuple[float, str]]):
    """A clone whose origin/main has one commit per entry of `runs` (newest first), each with one
    completed `check` run of that suite time and conclusion; returns the commits and the API paths
    ci_suite_time reads."""
    root = quiet_git.init(tmp_path / "repo", "-b", "main")
    for index in range(len(runs)):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=a", "-c", "user.email=a@example.com",
                        "commit", "-q", "--allow-empty", "-m", f"c{index}"], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "https://github.com/example/repo.git"], check=True)
    subprocess.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", "HEAD"],
                   check=True)
    commits = subprocess.run(["git", "-C", str(root), "rev-list", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.split()
    paths: list[str] = []

    def github_read(repo, path):
        paths.append(path)
        if path.startswith("commits/"):
            index = commits.index(path.split("/")[1])
            return {"check_runs": [{"id": index, "status": "completed",
                                    "conclusion": runs[index][1],
                                    "html_url": f"https://github.com/run/{index}"}]}
        seconds = runs[int(path.split("/")[1])][0]
        return [{"title": "se suite time", "message": f"Suite time: {seconds} s (limit 120 s)"}]

    monkeypatch.setattr(work_tickets, "github_read", github_read)
    return root, commits, paths


def test_ci_suite_time_is_the_median_of_five_runs_so_one_slow_runner_does_not_count(
        tmp_path, monkeypatch):
    root, commits, paths = fake_ci_runs(tmp_path, monkeypatch, [
        (35.7, "success"), (39.2, "success"), (78.4, "success"), (36.0, "success"),
        (41.0, "success"), (30.0, "success")])  # newest first; the sixth is not read

    found, reason = work_tickets.ci_suite_time(root)

    assert reason == ""
    assert found == work_tickets.CiSuiteTime(
        39.2, commits[1], "https://github.com/run/1", (35.7, 39.2, 78.4, 36.0, 41.0))
    assert not any(commits[5] in path for path in paths)  # five runs read, no more requests
    assert work_tickets.ci_suite_text(found, "main") == (
        "CI's suite time on main is 39.2 s, the median of its last 5 runs "
        f"(35.7, 39.2, 78.4, 36, 41 s; median commit {commits[1][:12]}, https://github.com/run/1)")


def test_ci_suite_time_skips_a_check_run_that_did_not_succeed(tmp_path, monkeypatch):
    root, commits, paths = fake_ci_runs(tmp_path, monkeypatch, [
        (35.7, "success"), (12.0, "failure"), (78.4, "success"), (36.0, "success"),
        (41.0, "success"), (30.0, "success")])

    found, _ = work_tickets.ci_suite_time(root)

    assert found is not None and found.readings == (35.7, 78.4, 36.0, 41.0, 30.0)
    assert (found.seconds, found.commit) == (36.0, commits[3])
    assert "check-runs/1/annotations" not in paths  # the failed run's time is never read


def test_refs_request_runs_its_steps_through_kerns_relay_as_one_call(
        refs_checkout, tmp_path, monkeypatch, capsys):
    """Where refs request runs as one call through kern (se_relay.steps set), its dry run is asked
    step by step through kern's github.step and read back in the same call: no plan is handed off,
    no comment id, run url or log is retyped into a read-back."""
    checkout, fake, base, ahead = refs_checkout
    monkeypatch.setattr(work_tickets, "hand_off", lambda: True)
    file = triples_file(tmp_path, f"{base} {ahead} refs/heads/main\n")
    asked: list[tuple[str, dict]] = []
    runs = [{"id": 8}]

    def session(tool: str, input_: dict, note: str, wait: str) -> object:
        asked.append((tool, input_))
        method = input_.get("method")
        if tool == "add_issue_comment":
            return {"id": "100" if len(asked) == 1 else "101",
                    "url": "https://git.example/owner/repo/issues/5#issuecomment-100"}
        if tool == "actions_run_trigger":
            runs.append({"id": 9})
            return {"message": "Workflow run has been queued"}
        if tool == "actions_list" and method == "list_workflow_runs":
            return {"total_count": len(runs), "workflow_runs": list(reversed(runs))}
        if tool == "actions_get":
            return {"id": 9, "status": "completed", "conclusion": "success",
                    "html_url": "https://git.example/owner/repo/actions/runs/9"}
        if tool == "actions_list" and method == "list_workflow_jobs":
            return {"total_count": 1, "jobs": [{"id": 3}]}
        if tool == "get_job_logs":
            return {"logs_content": fake.log}
        if tool == "issue_read" and method == "get_labels":
            return [{"name": "work"}]
        if tool == "issue_write":
            return {"id": "1"}
        raise AssertionError(f"refs request asked an unexpected step: {tool} {input_}")

    with work_tickets.sibling("se_relay").stepping(session):
        assert work_tickets.main(["refs", "request", "5", "--triples-file", str(file), "--repo",
                                  REPO, "--worktree", str(checkout)]) == 0

    assert [tool for tool, _ in asked] == [
        "add_issue_comment", "actions_list", "actions_run_trigger", "actions_list", "actions_get",
        "actions_list", "get_job_logs", "add_issue_comment", "issue_read", "issue_write"]
    assert asked[2][1]["inputs"] == {"updates": f"{base} {ahead} refs/heads/main\n",
                                     "dry_run": "true"}
    assert asked[4][1] == {"owner": "owner", "repo": "repo", "method": "get_workflow_run",
                           "resource_id": "9"}
    dry_run = asked[7][1]["body"]
    assert "<!-- se:refs-request-id 100 -->" in dry_run and "set    refs/heads/main a -> b" in dry_run
    assert asked[9][1]["labels"] == ["work", "escalated"]
    out = capsys.readouterr().out
    assert "GitHub plan:" not in out
    assert "escalated #5: apply the ref change (1 ref(s), dry run passed)?" in out
    assert "after these steps" not in out
    assert fake.comments_posted == [] and fake.dispatched == []  # nothing went through gh
