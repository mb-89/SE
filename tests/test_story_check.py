"""scripts/story_check.py: a story deck's arc, its slides' two halves and its claims not yet run.

The two vaults under components/render/story/ build with build_docs.py and check as their issue says;
every other case is a made-up story checked by the pure core.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

import build_docs
import story_check
from story_check import NOT_YET_RUN, check, halves, main, render, slides

ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "components" / "render" / "story"
TEMPLATE = STORY / "template" / "deck.md"
EXAMPLE = STORY / "copilot-install" / "deck.md"


def _slide(part: str | None, claim: str | None = "The actor does one thing.", evidence: str | None = "It ran.",
           title: str | None = "A slide") -> str:
    lines = ["---", f"part: {part}", "---"] if part is not None else []
    lines += [f"# {title}", ""] if title is not None else []
    lines += ["## Claim", "", claim, ""] if claim is not None else []
    lines += ["## Evidence", "", evidence, ""] if evidence is not None else []
    return "\n".join(lines)


ARC = {"p": _slide("problem"), "s": _slide("start"), "a": _slide("step"), "r": _slide("result")}


def _manifest(names: list[str], actor: str | None = "actor: alice") -> str:
    front = ["---", "title: A story", *([actor] if actor is not None else []), "---", ""]
    return "\n".join(front + [f"- [[{name}|{name.title()}]]" for name in names]) + "\n"


def _problems(notes: dict[str, str | None], names: list[str] | None = None, **manifest) -> list[str]:
    names = list(notes) if names is None else names
    return check("deck.md", _manifest(names, **manifest), notes).problems


def _run(manifest: Path) -> list[str]:
    return render(check(manifest.name, manifest.read_text(encoding="utf-8"),
                        {name: (manifest.parent / f"{name}.md").read_text(encoding="utf-8")
                         for name in slides(manifest.read_text(encoding="utf-8"))}))


@pytest.mark.spawns("tool: build_docs.py builds each vault with the real obs, obs-document in obs's own Python "
                    "environment, whose warnings are the point; it runs only as a process")
def test_both_vaults_build_with_build_docs_without_a_warning(tmp_path, obs, capsys):
    for manifest in (TEMPLATE, EXAMPLE):
        destination = tmp_path / f"{manifest.parent.name}.html"
        code = build_docs.main(["--source", str(manifest), "--destination", str(destination)])
        result = capsys.readouterr()
        assert code == 0, result.err + result.out
        assert "warning" not in (result.out + result.err).casefold(), result.err
        assert destination.stat().st_size > 0


def test_the_example_tells_the_whole_arc_with_four_claims_not_yet_run():
    assert _run(EXAMPLE) == ["story: Copilot install pass", "actor: The owner", "slides: 6, steps: 3",
                             "not yet run: 4 of 6 evidence halves", "problems: none"]


def test_the_bare_template_lacks_exactly_the_problem_start_and_result():
    assert [line for line in _run(TEMPLATE) if ".md: " in line] == [
        "deck.md: no problem slide", "deck.md: no start slide", "deck.md: no result slide"]


def test_a_missing_evidence_section_and_an_empty_claim_are_named_with_their_slide():
    notes = {**ARC, "a": _slide("step", evidence=None), "b": _slide("step", claim="")}
    assert _problems(notes, ["p", "s", "a", "b", "r"]) == ["a.md: no evidence half", "b.md: no claim half"]


@pytest.mark.parametrize(("case", "notes", "names", "actor", "expected"), [
    ("no actor", ARC, None, None, ["deck.md: no actor"]),
    ("an empty actor", ARC, None, "actor:   # nobody yet", ["deck.md: no actor"]),
    ("two actor lines", ARC, None, "actor: alice\nactor: bob", ["deck.md: more than one actor"]),
    ("an actor list", ARC, None, "actor: [alice, bob]", ["deck.md: more than one actor"]),
    ("an indented actor list", ARC, None, "actor:\n  - alice\n  - bob", ["deck.md: more than one actor"]),
    ("no part", {**ARC, "a": _slide(None)}, None, "actor: alice", ["deck.md: no step slide", "a.md: no part"]),
    ("an unknown part", {**ARC, "a": _slide("middle")}, None, "actor: alice",
     ["deck.md: no step slide", "a.md: unknown part middle"]),
    ("a second result", {**ARC, "r2": _slide("result")}, None, "actor: alice", ["r2.md: result out of order"]),
    ("seven steps", {**ARC, **{f"a{n}": _slide("step") for n in range(6)}},
     ["p", "s", "a", *[f"a{n}" for n in range(6)], "r"], "actor: alice", ["a5.md: more than six steps"]),
    ("a result before the steps", ARC, ["p", "s", "r", "a"], "actor: alice", ["a.md: step out of order"]),
    ("a missing part", {"p": ARC["p"], "a": ARC["a"], "r": ARC["r"]}, None, "actor: alice",
     ["deck.md: no start slide"]),
    ("a link to a missing note", {**ARC, "gone": None}, ["p", "s", "a", "gone", "r"], "actor: alice",
     ["gone.md: no such note"]),
    ("no title", {**ARC, "a": _slide("step", title=None)}, None, "actor: alice", ["a.md: no title"]),
    ("evidence above the claim",
     {**ARC, "a": "---\npart: step\n---\n# A\n\n## Evidence\n\nIt ran.\n\n## Claim\n\nOne thing.\n"},
     None, "actor: alice", ["a.md: evidence before claim"]),
    ("a claim with a list", {**ARC, "a": _slide("step", claim="It does:\n\n1. one\n2. two")}, None,
     "actor: alice", ["a.md: claim holds a list"]),
])
def test_each_problem_prints_for_its_case(case, notes, names, actor, expected):
    assert _problems(notes, names, actor=actor) == expected, case


@pytest.mark.parametrize("bullet", ["- ", "* ", "+ ", "12. "])
def test_every_list_marker_makes_a_claim_a_list(bullet):
    assert _problems({**ARC, "a": _slide("step", claim=f"{bullet}one")}) == ["a.md: claim holds a list"]


def test_the_manifests_problems_print_before_the_slides_in_link_order():
    notes = {**ARC, "a": _slide("step", title=None), "s": _slide("start", evidence=None)}
    assert _problems(notes, ["p", "s", "a"], actor=None) == [
        "deck.md: no actor", "deck.md: no result slide", "s.md: no evidence half", "a.md: no title"]


def test_halves_finds_the_claim_and_the_evidence_sections():
    found = halves("---\npart: step\n---\n# T\n\n## Claim\n\nOne claim.\n\n### Detail\n\nMore.\n\n"
                   "## Evidence\n\n```\n## Claim\n```\n\n# Other\n\nNot evidence.\n")
    assert found.claim == "One claim.\n\n### Detail\n\nMore."
    assert found.evidence == "```\n## Claim\n```"
    assert not found.evidence_first
    assert halves("# T\n\nNo sections.\n") == story_check.Halves(None, None, False)


def test_the_templates_evidence_is_the_fixed_block():
    assert halves((TEMPLATE.parent / "slide.md").read_text(encoding="utf-8")).evidence == NOT_YET_RUN


def test_only_the_fixed_block_counts_as_not_yet_run():
    def not_yet_run(evidence: str) -> int:
        return check("deck.md", _manifest(["a"]), {"a": _slide("step", evidence=evidence)}).not_yet_run

    assert not_yet_run(f"\n\n{NOT_YET_RUN}\n\n") == 1
    assert not_yet_run(NOT_YET_RUN.replace("\n", "\r\n")) == 1
    assert not_yet_run("The self-test printed 10 passed.") == 0
    assert not_yet_run(NOT_YET_RUN + "\n\nThe self-test printed 10 passed.") == 0


def test_the_module_imports_only_the_standard_library():
    tree = ast.parse(Path(story_check.__file__).read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    # se_script, the shared part of every script, is itself standard library only
    # (tests/test_code_templates.py holds it to that)
    assert modules and modules <= set(sys.stdlib_module_names) | {"__future__", "se_script"}, modules


def test_nothing_names_the_checker():
    own = (ROOT / "scripts" / "story_check.py").resolve()
    name = "story" + "_check"
    suffixes = {".py", ".go", ".md", ".sh", ".toml", ".json", ".yml"}
    naming = []
    for top in ("scripts", "components", "kern", "src", ".github"):
        for directory, folders, files in os.walk(ROOT / top):
            folders[:] = [folder for folder in folders if folder not in ("__pycache__", ".venv")]
            for file in files:
                path = Path(directory) / file
                if path.suffix in suffixes and path.resolve() != own and name in path.read_text(
                        encoding="utf-8", errors="replace"):
                    naming.append(path.relative_to(ROOT).as_posix())
    assert naming == []


def test_main_exits_0_on_a_story_with_problems_and_2_on_a_missing_manifest(tmp_path, capsys):
    (tmp_path / "deck.md").write_text(_manifest(["a", "gone"], actor=None), encoding="utf-8")
    (tmp_path / "a.md").write_text(_slide("step"), encoding="utf-8")
    assert main([str(tmp_path / "deck.md")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:4] == ["story: A story", "actor: ", "slides: 2, steps: 1", "not yet run: 0 of 2 evidence halves"]
    assert out[4:] == ["deck.md: no actor", "deck.md: no problem slide", "deck.md: no start slide",
                       "deck.md: no result slide", "gone.md: no such note"]
    assert main([str(tmp_path / "missing.md")]) == 2
    assert "cannot read" in capsys.readouterr().err
