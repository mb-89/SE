"""Skill drafts under drafts/skills: each folder keeps the skill rules, and no host reads it.

A draft is off because nothing reads it: no generator, no host surface, no instructions file. The
walk is a function of a drafts/skills path and each check a function of a folder or of files, so
made-up folders and files in tmp_path can fail them. The test reads files from disk and runs no git.
"""
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_lint  # noqa: E402
import host_size  # noqa: E402
import references  # noqa: E402
import se_plugin  # noqa: E402

DRAFTS = PurePosixPath("drafts")
SKILLS = ROOT / DRAFTS / "skills"
MAX_LINES = 150
# The old system's marks: wiki links, `#work` tags (an anchor such as #working-a-problem passes) and
# its snake-case field names.
OLD_MARKS = (
    re.compile(r"\[\[[^\[\]]+\]\]"),
    re.compile(r"(?<!(?:[\w/#]))#work(?!(?:[\w-]))"),
    re.compile(r"\bsource_refs\b"),
    re.compile(r"\bverify_method\b"),
    re.compile(r"\bbreaks_if_removed\b"),
)
TO_COME = re.compile(r"^## To come[ \t]*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
ITEM = re.compile(r"^[ \t]*[-*+][ \t]+`([^`]+)`", re.MULTILINE)
# A method card under references/cards/: a `Reader:` line under its title, four sections, at most seven
# numbered steps and at most sixty lines.
CARD_SECTIONS = ("When", "Steps", "Where it goes in SE", "Source")
CARD_STEPS = 7
CARD_LINES = 60
READER = re.compile(r"\A# [^\n]+\n\nReader: ")
STEP = re.compile(r"^\d+\.[ \t]", re.MULTILINE)


# The walk and the checks of one draft folder.

def walk(skills: Path) -> list[Path]:
    """Every draft folder under a drafts/skills path."""
    return sorted(path for path in skills.iterdir() if path.is_dir()) if skills.is_dir() else []


def walk_findings(skills: Path) -> list[str]:
    return [] if walk(skills) else [f"{skills}: holds no draft folder"]


def markdown(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.md"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def lint_findings(folder: Path) -> list[str]:
    path = folder / "SKILL.md"
    return agent_lint.skill(path, read(path)) if path.is_file() else [f"{path}: missing"]


def invocation_findings(folder: Path) -> list[str]:
    path = folder / "SKILL.md"
    value = agent_lint.scalar(agent_lint.fields(read(path)).get("disable-model-invocation", ""))
    return [] if value == "true" else [f"{path}: disable-model-invocation is {value or 'missing'}, not true"]


def length_findings(folder: Path) -> list[str]:
    path = folder / "SKILL.md"
    lines = len(read(path).splitlines())
    return [] if lines < MAX_LINES else [f"{path}: {lines} lines, not under {MAX_LINES}"]


def dangling_findings(folder: Path) -> list[str]:
    return [f"{path}: {finding}" for path in markdown(folder)
            for finding in references.dangling(read(path), ROOT, path)]


def outside_findings(folder: Path) -> list[str]:
    """Relative links that resolve outside the folder."""
    found = []
    inside = folder.resolve()
    for path in markdown(folder):
        prose, _ = references.split_code(read(path))
        for match in references.LINK.finditer(prose):
            target = match.group(1).split("#", 1)[0]
            if not target or references.SCHEME.match(target) or references.PLACEHOLDER.search(target):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(inside):
                found.append(f"{path}: link {match.group(1)} leaves the draft folder")
    return found


def to_come(folder: Path) -> list[str]:
    """The paths a SKILL.md's `## To come` section lists, relative to the folder; none without it."""
    section = TO_COME.search(read(folder / "SKILL.md"))
    return ITEM.findall(section.group(1)) if section else []


def to_come_findings(folder: Path) -> list[str]:
    return [f"{folder / 'SKILL.md'}: To come path {path} exists; link it with its reading condition instead"
            for path in to_come(folder) if (folder / path).exists()]


def section(text: str, title: str) -> str | None:
    """The body of a `## <title>` section, up to the next `## ` heading; None without it."""
    match = re.search(rf"^## {re.escape(title)}[ \t]*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


def card_findings(folder: Path) -> list[str]:
    """Every card under references/cards/ that breaks the card shape."""
    found = []
    for path in sorted((folder / "references" / "cards").glob("*.md")):
        text = read(path)
        if not READER.match(text):
            found.append(f"{path}: no Reader: line under its title")
        found += [f"{path}: no ## {title} section" for title in CARD_SECTIONS if section(text, title) is None]
        steps = len(STEP.findall(section(text, "Steps") or ""))
        if steps > CARD_STEPS:
            found.append(f"{path}: {steps} steps, more than {CARD_STEPS}")
        if (lines := len(text.splitlines())) > CARD_LINES:
            found.append(f"{path}: {lines} lines, more than {CARD_LINES}")
    return found


def unrooted_findings(folder: Path) -> list[str]:
    """A Markdown line naming a script without SE's root, which the build refuses (se_plugin.UNROOTED_SCRIPT)."""
    return [f"{path}:{number}: names a script without SE's root; write `<se>/scripts/<name>.py`"
            for path in markdown(folder) for number, line in enumerate(read(path).splitlines(), 1)
            if se_plugin.UNROOTED_SCRIPT.search(line)]


def mark_findings(folder: Path) -> list[str]:
    """The old marks in SKILL.md and every file under references/."""
    files = [folder / "SKILL.md", *sorted(path for path in (folder / "references").rglob("*") if path.is_file())]
    return [f"{path}: old mark {match.group()!r}" for path in files if path.is_file()
            for pattern in OLD_MARKS for match in pattern.finditer(read(path))]


CHECKS = (lint_findings, invocation_findings, length_findings, dangling_findings, outside_findings,
          to_come_findings, card_findings, unrooted_findings, mark_findings)


def folder_findings(folder: Path) -> list[str]:
    if not (folder / "SKILL.md").is_file():
        return [f"{folder}: holds no SKILL.md"]
    return [finding for check in CHECKS for finding in check(folder)]


# The host checks: files in, findings out.

def under_drafts(path: str | PurePosixPath) -> bool:
    return PurePosixPath(path).parts[:1] == DRAFTS.parts


def surface_findings(surfaces: Iterable[host_size.Surface], files: Iterable[str]) -> list[str]:
    """A draft file some host surface reads in a role."""
    return [f"{surface.id}: reads {path} as {found}" for surface in surfaces for path in files
            if under_drafts(path) and (found := host_size.role(surface, path))]


def generated_findings(generated: Mapping[PurePosixPath, bytes]) -> list[str]:
    """A generated file under drafts/, or a generated file that is not Markdown naming drafts/."""
    found = [f"{path}: generated under drafts/" for path in generated if under_drafts(path)]
    found += [f"{path}: names drafts/, so a host may read it" for path, data in generated.items()
              if path.suffix != ".md" and b"drafts/" in data]
    return found


def instruction_findings(texts: Mapping[str, str]) -> list[str]:
    return [f"{path}: names drafts/" for path, text in texts.items() if "drafts/" in text]


def surfaces() -> tuple[host_size.Surface, ...]:
    return host_size.parse(tomllib.loads(host_size.DATA.read_text(encoding="utf-8"))).surfaces


def instruction_files(root: Path, all_surfaces: Iterable[host_size.Surface]) -> dict[str, str]:
    """docs.md and every file a surface's `instructions` patterns match, by posix path."""
    paths = {root / "docs.md"} | {path for surface in all_surfaces
                                  for pattern in surface.reads.get("instructions", ())
                                  for path in root.glob(pattern) if path.is_file()}
    return {path.relative_to(root).as_posix(): read(path) for path in sorted(paths) if path.is_file()}


# SE's checkout.

def test_every_draft_folder_keeps_the_skill_rules():
    assert walk_findings(SKILLS) == []
    assert [finding for folder in walk(SKILLS) for finding in folder_findings(folder)] == []


CARDS = ("stakeholders", "use-cases", "quality-scenarios", "options", "spike", "prior-art", "working-a-problem",
         "design-brief")


def test_the_systematic_draft_links_its_nine_references():
    folder = SKILLS / "systematic"
    text = read(folder / "SKILL.md")
    assert TO_COME.search(text) is None and to_come(folder) == []
    linked = {match.group(1) for match in references.LINK.finditer(references.split_code(text)[0])}
    paths = ["references/process.md", *(f"references/cards/{name}.md" for name in CARDS)]
    assert [path for path in paths if path not in linked] == []
    assert sorted(path.stem for path in (folder / "references" / "cards").glob("*.md")) == sorted(CARDS)
    assert card_findings(folder) == []


def test_no_host_surface_reaches_drafts():
    files = [path.relative_to(ROOT).as_posix() for path in (ROOT / DRAFTS).rglob("*") if path.is_file()]
    assert files
    assert surface_findings(surfaces(), files) == []
    assert generated_findings(se_plugin.expected(ROOT)) == []
    texts = instruction_files(ROOT, surfaces())
    assert "AGENTS.md" in texts and "docs.md" in texts
    assert instruction_findings(texts) == []


# Made-up folders, each failing one check.

GOOD = ("---\nname: {name}\ndescription: 'Does one thing.'\ndisable-model-invocation: true\n---\n\n# Draft\n\n"
        "Read [the reference](references/one.md) when needed.\n")


def draft(tmp_path: Path, name: str = "good", skill: str | None = None, extra: Mapping[str, str] = {}) -> Path:
    folder = tmp_path / "skills" / name
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(GOOD.format(name=name) if skill is None else skill, encoding="utf-8")
    (folder / "references" / "one.md").write_text("# One\n", encoding="utf-8")
    for relative, text in extra.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(text, encoding="utf-8")
    return folder


def test_a_good_made_up_draft_passes(tmp_path):
    folder = draft(tmp_path)
    assert walk_findings(tmp_path / "skills") == []
    assert folder_findings(folder) == []


def test_an_empty_drafts_skills_fails_the_walk(tmp_path):
    (tmp_path / "skills").mkdir()
    assert walk_findings(tmp_path / "skills") == [f"{tmp_path / 'skills'}: holds no draft folder"]
    assert walk_findings(tmp_path / "missing") != []


def test_a_name_unlike_its_folder_fails(tmp_path):
    folder = draft(tmp_path, "good", GOOD.format(name="other"))
    assert lint_findings(folder) and folder_findings(folder) == lint_findings(folder)


def test_the_key_missing_or_false_fails(tmp_path):
    missing = draft(tmp_path, "missing", GOOD.format(name="missing").replace("disable-model-invocation: true\n", ""))
    false = draft(tmp_path, "false", GOOD.format(name="false").replace(": true", ": false"))
    for folder in (missing, false):
        assert invocation_findings(folder) and folder_findings(folder) == invocation_findings(folder)


def test_a_150_line_skill_fails(tmp_path):
    text = GOOD.format(name="long")
    folder = draft(tmp_path, "long", text + "line\n" * (MAX_LINES - len(text.splitlines())))
    assert len((folder / "SKILL.md").read_text(encoding="utf-8").splitlines()) == MAX_LINES
    assert length_findings(folder) and folder_findings(folder) == length_findings(folder)


def test_a_dead_link_fails(tmp_path):
    folder = draft(tmp_path, extra={"references/two.md": "See [three](three.md).\n"})
    assert dangling_findings(folder) and folder_findings(folder) == dangling_findings(folder)


def test_a_link_out_of_the_folder_fails(tmp_path):
    folder = draft(tmp_path, extra={"references/two.md": "See [another](../../other/SKILL.md).\n",
                                    "../other/SKILL.md": GOOD.format(name="other")})
    assert outside_findings(folder) and folder_findings(folder) == outside_findings(folder)


def test_a_to_come_path_that_exists_fails(tmp_path):
    folder = draft(tmp_path, skill=GOOD.format(name="good") + "\n## To come\n\n- `references/one.md`: read later.\n"
                                                            "- `references/cards/two.md`: read later.\n")
    assert to_come(folder) == ["references/one.md", "references/cards/two.md"]
    assert to_come_findings(folder) == [f"{folder / 'SKILL.md'}: To come path references/one.md exists; link it "
                                        "with its reading condition instead"]
    assert folder_findings(folder) == to_come_findings(folder)


def test_a_draft_without_to_come_has_no_to_come_paths(tmp_path):
    assert to_come(draft(tmp_path)) == []


def test_a_bare_script_path_fails_and_a_rooted_one_passes(tmp_path):
    bare = draft(tmp_path, "bare", extra={"references/two.md": "Run `uv run python scripts/x.py`.\n"})
    assert unrooted_findings(bare) == [f"{bare / 'references' / 'two.md'}:1: names a script without SE's root; "
                                       "write `<se>/scripts/<name>.py`"]
    real = draft(tmp_path, "real", extra={"references/two.md": "Run `uv run python scripts/review.py`.\n"})
    assert folder_findings(real) == unrooted_findings(real) != []
    rooted = draft(tmp_path, "rooted", extra={"references/two.md": "Run `uv run python <se>/scripts/review.py`.\n"})
    assert folder_findings(rooted) == []


CARD = "# Card\n\nReader: someone.\n\n## When\n\n- Now.\n\n## Steps\n\n{steps}\n## Where it goes in SE\n\n" \
       "The work issue's Situation section.\n\n## Source\n\nAn Author, 2000.\n"


def card(steps: int = 3, text: str | None = None) -> str:
    return CARD.format(steps="".join(f"{n}. Step.\n" for n in range(1, steps + 1))) if text is None else text


def test_a_good_made_up_card_passes(tmp_path):
    folder = draft(tmp_path, extra={"references/cards/one.md": card(CARD_STEPS)})
    assert folder_findings(folder) == []


def test_each_broken_card_fails(tmp_path):
    seven = card(CARD_STEPS)
    broken = {
        "no-where": (card().replace("## Where it goes in SE", "## Elsewhere"), "no ## Where it goes in SE section"),
        "no-reader": (card().replace("Reader: someone.\n\n", ""), "no Reader: line under its title"),
        "eight-steps": (card(CARD_STEPS + 1), f"8 steps, more than {CARD_STEPS}"),
        "long": (seven + "\n" * (CARD_LINES + 1 - len(seven.splitlines())), f"61 lines, more than {CARD_LINES}"),
    }
    for name, (text, finding) in broken.items():
        folder = draft(tmp_path, name, extra={"references/cards/one.md": card(text=text)})
        assert card_findings(folder) == [f"{folder / 'references' / 'cards' / 'one.md'}: {finding}"], name
        assert folder_findings(folder) == card_findings(folder), name


def test_a_work_tag_fails_and_an_anchor_passes(tmp_path):
    tagged = draft(tmp_path, "tagged", extra={"references/two.md": "Filed as #work today.\n"})
    assert mark_findings(tagged) and folder_findings(tagged) == mark_findings(tagged)
    anchored = draft(tmp_path, "anchored", extra={"references/two.md": "See [it](one.md#working-a-problem) "
                                                                       "and [#work-flow](one.md).\n"})
    assert folder_findings(anchored) == []


def test_each_old_mark_fails(tmp_path):
    for index, text in enumerate(("[[a note]]", "#work", "source_refs:", "verify_method:", "breaks_if_removed:")):
        folder = draft(tmp_path, f"mark-{index}", extra={"references/two.md": f"{text}\n"})
        assert len(mark_findings(folder)) == 1, text


# Made-up files, each failing one host check.

SURFACE = host_size.Surface("made-up", "A made-up host", {"instructions": ("AGENTS.md",), "agent": (),
                                                          "skill": ("drafts/skills/*/SKILL.md",), "reference": ()})


def test_a_surface_whose_pattern_matches_a_draft_file_fails():
    files = ["drafts/skills/x/SKILL.md", "skills/x/SKILL.md"]
    assert surface_findings([SURFACE], files) == ["made-up: reads drafts/skills/x/SKILL.md as skill"]
    assert surface_findings(surfaces(), files) == []


def test_a_generated_file_under_drafts_fails():
    assert generated_findings({PurePosixPath("drafts/skills/x/SKILL.md"): b"# X\n"}) != []


def test_a_manifest_whose_skills_path_lies_under_drafts_fails():
    manifest = {PurePosixPath(".claude-plugin/plugin.json"): b'{"skills": "./drafts/skills/"}'}
    assert generated_findings(manifest) == [".claude-plugin/plugin.json: names drafts/, so a host may read it"]


def test_a_generated_skill_whose_prose_names_drafts_passes():
    assert generated_findings({PurePosixPath("skills/x/SKILL.md"): b"Drafts lie under drafts/skills.\n"}) == []


def test_an_instructions_text_naming_drafts_fails(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Read drafts/skills too.\n", encoding="utf-8")
    (tmp_path / "docs.md").write_text("# Docs\n", encoding="utf-8")
    texts = instruction_files(tmp_path, [SURFACE])
    assert sorted(texts) == ["AGENTS.md", "docs.md"]
    assert instruction_findings(texts) == ["AGENTS.md: names drafts/"]
