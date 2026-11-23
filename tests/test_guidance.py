"""SE's guidance (scripts/se_guidance.py), the command component `guidance`: collect resolves the
guidance trees of a project and its modules for a template or a set of tags in docs/guidance.md's
order, and check refuses each thing that note refuses, each on a fixture of its own."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import templates
import se_guidance

ROOT = Path(__file__).resolve().parents[1]
MODULE_REF = "0" * 40


@pytest.fixture(autouse=True)
def direct(monkeypatch, tmp_path):
    """Every command runs directly, never through a kern that may serve this checkout, and reads
    no machine's ~/.se/local.toml."""
    monkeypatch.setenv("SE_KERN", "off")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


def note(root: Path, path: str, name: str, *, tags: list[str] | None = None,
         overrides: str = "", extra: str = "", body: str = "") -> Path:
    """A note at `root`/`path` (a posix path below the source's root) with its front matter."""
    lines = ["---", f"name: {name}", f"description: 'What {name} says.'"]
    if tags is not None:
        lines.append(f"tags: [{', '.join(tags)}]")
    if overrides:
        lines.append(f"overrides: {overrides}")
    if extra:
        lines.append(extra)
    file = root.joinpath(*path.split("/"))
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("\n".join([*lines, "---", "", body or f"{name}'s text.", ""]), encoding="utf-8")
    return file


def template(root: Path, name: str, tags: list[str] | None = None) -> None:
    folder = root / "templates"
    folder.mkdir(parents=True, exist_ok=True)
    tagged = "" if tags is None else f"tags: {json.dumps(tags)}\n"
    (folder / f"{name}.md").write_text(f"---\nname: {name}\n{tagged}---\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path) -> Path:
    """A project with one module, `lib`, placed where se_modules.py places it, and a tree that
    passes the check: notes at depths 0 to 3, one with front-matter tags at each of two depths."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "se.toml").write_text(
        f'[modules.lib]\nurl = "https://git.example/lib.git"\nref = "{MODULE_REF}"\n',
        encoding="utf-8")
    note(root, "guidance/base.md", "base")
    note(root, "guidance/aaa-worker.md", "aaa-worker", tags=["worker"])
    note(root, "guidance/work/rules.md", "rules")
    note(root, "guidance/work/testing/general.md", "general")
    note(root, "guidance/work/testing/a.md", "a")
    note(root, "guidance/work/testing/b-integrator.md", "b-integrator", tags=["integrator"])
    note(root, "guidance/work/testing/go/repeat.md", "repeat")
    note(root, "guidance/other/x.md", "x")
    lib = root / ".se" / "modules" / "lib"
    note(lib, "guidance/work/lib-rules.md", "lib-rules")
    note(lib, "guidance/zzz-lib.md", "zzz-lib")
    template(root, "worker", ["work", "testing", "go", "worker"])
    template(root, "integrator", ["work", "testing", "integrator"])
    template(root, "other", ["other"])
    template(lib, "plain")
    (root / "templates" / "terms.toml").write_text('[[terms]]\nterm = "x"\n', encoding="utf-8")
    return root


def run(capsys, *arguments: str) -> tuple[int, str, str]:
    code = se_guidance.main([*arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def names(capsys, root: Path, *asked: str) -> list[str]:
    code, out, err = run(capsys, "collect", *asked, "--json", "--root", str(root))
    assert code == 0, out + err
    return [item["name"] for item in json.loads(out)]


def test_a_template_gets_the_notes_whose_tags_it_carries_general_first_modules_first(
        capsys, project):
    # Depth first; at depth 0 the untagged notes before aaa-worker's one tag; at depth 1 the
    # module's note before the project's; at depth 2 by path; never a note with a tag it lacks.
    assert names(capsys, project, "--template", "worker") == [
        "zzz-lib", "base", "aaa-worker", "lib-rules", "rules", "a", "general", "repeat"]
    # Three tags after two at one depth, and a module's template (`plain`, no tags) gets the
    # untagged notes at depth 0 alone.
    assert names(capsys, project, "--template", "integrator") == [
        "zzz-lib", "base", "lib-rules", "rules", "a", "general", "b-integrator"]
    assert names(capsys, project, "--template", "plain") == ["zzz-lib", "base"]


def test_the_answer_prints_each_note_under_its_name_with_its_file_depth_and_tags(capsys, project):
    code, out, _ = run(capsys, "collect", "--template", "other", "--root", str(project))
    assert code == 0
    assert out.splitlines()[0] == ("Guidance for the template other: 3 notes, general before "
                                   "specific.")
    assert out.index("## zzz-lib") < out.index("## base") < out.index("## x")
    assert "`lib:guidance/zzz-lib.md` · depth 0 · tags: none" in out
    assert "`guidance/other/x.md` · depth 1 · tags: other\n\nx's text.\n" in out


def test_a_tag_query_gets_the_notes_carrying_every_asked_tag_and_those_at_depth_0(
        capsys, project):
    assert names(capsys, project, "--tags", "testing") == [
        "zzz-lib", "base", "aaa-worker", "a", "general", "b-integrator", "repeat"]
    assert names(capsys, project, "--tags", "testing,go") == [
        "zzz-lib", "base", "aaa-worker", "repeat"]
    # The asked tags in any order, and a front-matter tag as much as a folder's.
    assert names(capsys, project, "--tags", "integrator, work") == [
        "zzz-lib", "base", "aaa-worker", "b-integrator"]


def test_a_tag_nothing_carries_is_named_with_the_tags_that_exist(capsys, project):
    code, out, _ = run(capsys, "collect", "--tags", "nope", "--root", str(project))
    assert code == 0
    assert out.splitlines()[0] == ("No note carries the tag nope; the tags are: go, integrator, "
                                   "other, testing, work, worker.")
    assert "## base" in out and "## a\n" not in out


def test_an_unknown_template_is_answered_with_the_templates(capsys, project):
    code, out, _ = run(capsys, "collect", "--template", "nope", "--root", str(project))
    assert code == 2
    assert out.strip() == ("se_guidance.py collect: no template 'nope'; the templates are: "
                           "integrator, other, plain, worker")


def test_an_override_drops_the_note_it_names_from_every_resolution_it_is_in(capsys, project):
    note(project, "guidance/work/testing/go/narrow.md", "narrow", overrides="general")
    assert run(capsys, "check", "--root", str(project))[0] == 0
    assert names(capsys, project, "--template", "worker") == [
        "zzz-lib", "base", "aaa-worker", "lib-rules", "rules", "a", "narrow", "repeat"]
    assert names(capsys, project, "--tags", "testing") == [
        "zzz-lib", "base", "aaa-worker", "a", "b-integrator", "narrow", "repeat"]
    # A resolution the overriding note is not in keeps the note it names.
    assert "general" in names(capsys, project, "--template", "integrator")
    # A project note may override a module's.
    note(project, "guidance/work/testing/lib-narrow.md", "lib-narrow", overrides="lib-rules")
    assert run(capsys, "check", "--root", str(project))[0] == 0
    assert names(capsys, project, "--template", "integrator") == [
        "zzz-lib", "base", "rules", "a", "general", "lib-narrow", "b-integrator"]


def test_the_tree_of_the_fixture_passes(capsys, project):
    assert run(capsys, "check", "--root", str(project)) == (
        0, "passes: 10 notes, 4 templates\n", "")


def big(project: Path) -> None:
    limit = se_guidance.page_limit()
    note(project, "guidance/work/big.md", "big", body="x" * (limit // 4))


REFUSALS = {
    "duplicate name": (
        lambda root: note(root, "guidance/work/testing/again.md", "general"),
        "guidance/work/testing/general.md: duplicate name 'general', also "
        "guidance/work/testing/again.md; rename one, names are unique across the trees"),
    "duplicate name across trees": (
        lambda root: note(root, "guidance/work/lib-rules.md", "lib-rules"),
        "guidance/work/lib-rules.md: duplicate name 'lib-rules', also "
        "lib:guidance/work/lib-rules.md; rename one, names are unique across the trees"),
    "unknown key": (
        lambda root: note(root, "guidance/work/keyed.md", "keyed", extra="priority: 1"),
        "guidance/work/keyed.md: unknown key priority; a note has only name, description, tags, "
        "overrides (docs/guidance.md \"Notes in folders\")"),
    "orphan": (
        lambda root: note(root, "guidance/work/orphan.md", "orphan", tags=["other"]),
        "guidance/work/orphan.md: orphan, no template carries all its tags (other, work); fix "
        "its tags or delete it"),
    "override of a note no tree holds": (
        lambda root: note(root, "guidance/work/o.md", "o", overrides="missing"),
        "guidance/work/o.md: bad override of 'missing': no tree holds that note; name an "
        "existing note"),
    "override of a more specific note": (
        lambda root: note(root, "guidance/work/o.md", "o", overrides="general"),
        "guidance/work/o.md: bad override of 'general' (guidance/work/testing/general.md): it "
        "lacks its tags testing; only a more specific note may override"),
    "override of itself": (
        lambda root: note(root, "guidance/work/o.md", "o", overrides="o"),
        "guidance/work/o.md: bad override of 'o': a note cannot override itself; drop overrides"),
    "module overriding the project": (
        lambda root: note(root / ".se" / "modules" / "lib", "guidance/work/testing/m.md", "m",
                          overrides="general"),
        "lib:guidance/work/testing/m.md: bad override of 'general' "
        "(guidance/work/testing/general.md): a module never overrides the project"),
    "override in a cycle": (
        lambda root: (note(root, "guidance/work/testing/c1.md", "c1", overrides="c2"),
                      note(root, "guidance/work/testing/c2.md", "c2", overrides="c1")),
        "guidance/work/testing/c1.md: bad override of 'c2': the overrides form a cycle "
        "(c1 -> c2 -> c1); break it\n"
        "guidance/work/testing/c2.md: bad override of 'c1': the overrides form a cycle "
        "(c2 -> c1 -> c2); break it"),
    "over a quarter page": (
        big,
        lambda root: f"guidance/work/big.md: {(root / 'guidance/work/big.md').stat().st_size} "
                     "bytes, over a quarter of kern's page limit (11250 of 45000); split it into "
                     "more specific notes"),
    "no front matter": (
        lambda root: (root / "guidance" / "bare.md").write_text("text\n", encoding="utf-8"),
        "guidance/bare.md: has no front matter; start it with a --- line, name: and "
        "description:, and ---"),
    "no description": (
        lambda root: (root / "guidance" / "half.md").write_text("---\nname: half\n---\n",
                                                                encoding="utf-8"),
        "guidance/half.md: no description; a note is also a skill and needs name and "
        "description"),
    "a folder that is no tag": (
        lambda root: note(root, "guidance/Work_Stuff/n.md", "n"),
        "guidance/Work_Stuff/n.md: folder 'Work_Stuff' is no tag, lowercase words joined by "
        "dashes; rename the folder\n"
        "guidance/Work_Stuff/n.md: orphan, no template carries all its tags (Work_Stuff); fix "
        "its tags or delete it"),
    "a template whose tags are no list": (
        lambda root: (root / "templates" / "bad.md").write_text("---\nname: bad\ntags: work\n---\n",
                                                             encoding="utf-8"),
        "templates/bad.md: tags is no list of tags, lowercase words joined by dashes; fix the "
        "template's tags"),
}


@pytest.mark.parametrize("refusal", sorted(REFUSALS))
def test_the_check_refuses_each_rule_on_a_fixture(capsys, project, refusal):
    make, finding = REFUSALS[refusal]
    make(project)
    code, out, _ = run(capsys, "check", "--root", str(project))
    assert (code, out) == (1, (finding(project) if callable(finding) else finding) + "\n")


def test_collect_leaves_out_a_note_that_does_not_load_and_names_it(capsys, project):
    (project / "guidance" / "bare.md").write_text("text\n", encoding="utf-8")
    code, out, err = run(capsys, "collect", "--template", "plain", "--root", str(project))
    assert code == 0 and "## base" in out
    assert err == ("left out: guidance/bare.md: has no front matter; start it with a --- line, "
                   "name: and description:, and --- (se_guidance.py check)\n")


def test_a_template_with_tags_loads_and_gets_the_notes_of_those_tags(capsys, tmp_path):
    """SE's template notes are the templates: se_guidance.py reads their `tags` as templates.py
    reads the note."""
    folder = tmp_path / "project" / "templates"
    shutil.copytree(ROOT / "templates", folder)
    assert set(templates.load(ROOT, folder=folder)) == set(templates.load(ROOT, tree=True))
    root = folder.parent
    note(root, "guidance/work/w.md", "w")
    assert names(capsys, root, "--template", "work") == ["w"]
    assert names(capsys, root, "--template", "ticket") == []


def test_a_template_note_that_does_not_load_is_a_finding(capsys, project):
    (project / "templates" / "broken.md").write_text("name: broken\n", encoding="utf-8")
    code, out, _ = run(capsys, "check", "--root", str(project))
    assert (code, out) == (1, "templates/broken.md: a template opens with its front matter between "
                              "`---` lines\n")


def test_ses_own_tree_passes_and_its_seed_note_reaches_every_template(capsys):
    code, out, _ = run(capsys, "check", "--root", str(ROOT))
    assert code == 0 and out.startswith("passes: ")
    for template_name in sorted(templates.load(ROOT, tree=True)):
        assert "guidance-comes-first" in names(capsys, ROOT, "--template", template_name), (
            template_name)


# Change after filing: implementations live in the note, and tool files are their projections.

def implementation(path: str, text: str) -> str:
    return f"The rule in words.\n\n```implements {path}\n{text}```\n"


def test_project_writes_each_tool_file_from_the_notes_that_implement_it(capsys, project):
    note(project, "guidance/work/short-lines.md", "short-lines",
         body=implementation("pyproject.toml", "[tool.ruff]\nline-length = 100\n"))
    lib = project / ".se" / "modules" / "lib"
    note(lib, "guidance/work/lint-select.md", "lint-select",
         body=implementation("pyproject.toml", "[tool.ruff.lint]\nselect = [\"E\"]\n"))
    (project / "pyproject.toml").write_text('[project]\nname = "p"\n', encoding="utf-8")
    assert run(capsys, "check", "--root", str(project)) == (1, (
        "pyproject.toml: does not match its notes (lint-select, short-lines); run "
        "`se_guidance.py project`, never edit it by hand\n"), "")
    assert run(capsys, "project", "--root", str(project)) == (0, "wrote pyproject.toml\n", "")
    # The project's own part of the file stays; the generated part says so, its notes in their
    # order: the module's before the project's.
    assert (project / "pyproject.toml").read_text(encoding="utf-8") == (
        '[project]\nname = "p"\n\n'
        "# Generated by `se_guidance.py project` from the guidance notes lint-select, short-lines;"
        " edit them, never this part.\n"
        '[tool.ruff.lint]\nselect = ["E"]\n[tool.ruff]\nline-length = 100\n'
        "# End of what `se_guidance.py project` generates.\n")
    assert run(capsys, "project", "--root", str(project)) == (
        0, "pyproject.toml: up to date\n", "")
    assert run(capsys, "check", "--root", str(project))[0] == 0
    # A file no tool had yet is the generated part alone.
    note(project, "guidance/work/ignore.md", "ignore", body=implementation(".gitignore", "*.tmp\n"))
    assert run(capsys, "project", "--root", str(project))[1] == (
        "wrote .gitignore\npyproject.toml: up to date\n")
    assert (project / ".gitignore").read_text(encoding="utf-8").splitlines()[1:] == [
        "*.tmp", "# End of what `se_guidance.py project` generates."]


def test_the_check_refuses_a_generated_file_edited_by_hand_or_changed_notes(capsys, project):
    note(project, "guidance/work/short-lines.md", "short-lines",
         body=implementation("ruff.toml", "line-length = 100\n"))
    assert run(capsys, "project", "--root", str(project))[0] == 0
    ruff = project / "ruff.toml"
    ruff.write_text(ruff.read_text(encoding="utf-8").replace("100", "120"), encoding="utf-8")
    stale = ("ruff.toml: does not match its notes (short-lines); run `se_guidance.py project`, "
             "never edit it by hand\n")
    assert run(capsys, "check", "--root", str(project)) == (1, stale, "")
    run(capsys, "project", "--root", str(project))
    note(project, "guidance/work/short-lines.md", "short-lines",
         body=implementation("ruff.toml", "line-length = 90\n"))
    assert run(capsys, "check", "--root", str(project)) == (1, stale, "")


IMPLEMENTATION_REFUSALS = {
    "two for one target": (
        "The rule.\n\n```implements ruff.toml\na = 1\n```\n\n```implements ruff.toml\nb = 2\n```\n",
        "guidance/work/n.md: implements ruff.toml twice; one implementation per target"),
    "a target outside the project": (
        implementation("../elsewhere.toml", "a = 1\n"),
        "guidance/work/n.md: implements '../elsewhere.toml', no path inside the project; name a "
        "file relative to the project's root"),
    "a target whose comments are unknown": (
        implementation("data.json", "{}\n"),
        "guidance/work/n.md: implements data.json, a file whose comment syntax the guidance "
        "command does not know, so it cannot say it is generated; use a file of #-comments"),
    "a TOML file that does not parse": (
        implementation("ruff.toml", "line-length = \n"),
        "ruff.toml: its projection is not TOML (Invalid value (at line 2, column 15)); fix the "
        "implementations of short-lines"),
}


@pytest.mark.parametrize("refusal", sorted(IMPLEMENTATION_REFUSALS))
def test_the_check_refuses_each_bad_implementation_on_a_fixture(capsys, project, refusal):
    body, finding = IMPLEMENTATION_REFUSALS[refusal]
    note(project, "guidance/work/n.md", "short-lines" if "TOML" in refusal else "n", body=body)
    code, out, _ = run(capsys, "check", "--root", str(project))
    assert (code, out.splitlines()[0]) == (1, finding)


# Delivery (docs/guidance.md "Delivery"): once per session, in pages.

def record_file(root: Path, session: str) -> Path:
    return root / ".se" / ".runtime" / "sessions" / session / "guidance.yaml"


def test_a_second_call_in_a_session_names_the_notes_already_printed(capsys, project):
    asked = ("collect", "--template", "other", "--session", "s-1", "--root", str(project))
    code, first, _ = run(capsys, *asked)
    assert code == 0 and "## base" in first and "already printed" not in first
    assert record_file(project, "s-1").is_file()
    code, second, _ = run(capsys, *asked)
    assert code == 0
    assert second.splitlines()[0] == ("Guidance for the template other: 3 notes, general before "
                                      "specific; 3 already printed this session.")
    assert "already printed this session: zzz-lib, base, x" in second and "## " not in second
    # A tag query in the same session names the notes it shares and prints the others.
    code, tags, _ = run(capsys, "collect", "--tags", "testing", "--session", "s-1",
                        "--root", str(project))
    assert "already printed this session: zzz-lib, base\n" in tags and "## aaa-worker" in tags
    # A note whose text changed since it was printed prints again; another session prints all.
    note(project, "guidance/other/x.md", "x", body="x's new text.")
    code, changed, _ = run(capsys, *asked)
    assert "already printed this session: zzz-lib, base\n" in changed and "x's new text." in changed
    code, other, _ = run(capsys, *asked[:-4], "--session", "s-2", "--root", str(project))
    assert "already printed" not in other and other.count("## ") == 3


def test_without_a_session_every_call_prints_every_note_and_keeps_nothing(capsys, project):
    for _ in range(2):
        code, out, _ = run(capsys, "collect", "--template", "other", "--root", str(project))
        assert code == 0 and out.count("## ") == 3 and "already printed" not in out
    assert not (project / ".se" / ".runtime").exists()


def test_the_record_refuses_a_session_id_no_file_name_holds(capsys, project):
    code, out, _ = run(capsys, "collect", "--template", "other", "--session", "../x",
                       "--root", str(project))
    assert code == 2 and "is no session id" in out


def long_project(root: Path, count: int, size: int) -> None:
    for index in range(count):
        note(root, f"guidance/long/n{index}.md", f"n{index}", body=f"n{index} " + "word " * (size // 5))


def test_pages_break_between_notes_with_the_template_on_the_last(project):
    long_project(project, 6, 1000)
    loaded = se_guidance.load(project)
    notes = se_guidance.for_tags(loaded.notes, frozenset({"long"}))
    limit, tail = 3000, "\n## The template long\n\nTAIL\n"
    pages, page = [], 1
    while True:
        text = se_guidance.delivered(project, notes, "Guidance for long", page=page, tail=tail,
                                     limit=limit)
        pages.append(text)
        if "--page" not in text:
            break
        page += 1
    assert len(pages) > 2
    for number, text in enumerate(pages, 1):
        assert len(text.encode("utf-8")) <= limit
        if number < len(pages):
            assert (f"[page {number} of {len(pages)}, the template on the last: call again with "
                    f"the same arguments and --page {number + 1} for the next.]") in text
            assert "TAIL" not in text
    assert pages[-1].rstrip().endswith("TAIL") and "TAIL" not in "".join(pages[:-1])
    # Every note whole on one page, each once, in order.
    printed = [line[3:] for text in pages for line in text.splitlines() if line.startswith("## n")]
    assert printed == [item.name for item in notes if item.name.startswith("n")]
    for item in notes:
        assert sum(item.body.rstrip() in text for text in pages) == 1
    with pytest.raises(se_guidance.Usage, match="has 4 pages|pages"):
        se_guidance.delivered(project, notes, "Guidance for long", page=len(pages) + 1,
                              tail=tail, limit=limit)


def test_in_a_session_the_same_call_answers_the_next_page(project):
    long_project(project, 6, 1000)
    loaded = se_guidance.load(project)
    notes = se_guidance.for_tags(loaded.notes, frozenset({"long"}))
    tail, answers = "\n## The template long\n\nTAIL\n", []
    for _ in range(10):
        text = se_guidance.delivered(project, notes, "Guidance for long", session="s", tail=tail,
                                     limit=3000)
        answers.append(text)
        if "TAIL" in text:
            break
    assert len(answers) > 2 and "TAIL" not in "".join(answers[:-1])
    assert "more pages follow, the template on the last: call again with the same arguments" \
        in answers[0]
    # Each page prints the notes the record lacks; at the end every note is in it, once.
    printed = [line[3:] for text in answers for line in text.splitlines() if line.startswith("## n")]
    assert printed == [item.name for item in notes if item.name.startswith("n")]
    with pytest.raises(se_guidance.Usage, match="--page is for a call without --session"):
        se_guidance.delivered(project, notes, "Guidance for long", session="s", page=2)
