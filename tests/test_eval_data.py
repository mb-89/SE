"""The evaluation data under tests/evals/ keeps its shape (tests/evals/README.md).

Files only: no test here starts a model or runs an evaluation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "tests" / "evals"
TRIGGERS = EVALS / "triggers"
OUTCOMES = EVALS / "outcomes"
SKILLS = sorted(path.parent.name for path in (ROOT / "src" / "skills").glob("*/SKILL.md"))
TRIGGER_FILES = sorted(TRIGGERS.glob("*.json"))
CASES = sorted(path for path in OUTCOMES.iterdir() if path.is_dir())

PROMPT_KEYS = {
    "schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome",
    "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env",
}
GRADER_KEYS = {
    "regex": {"pattern", "flags", "match", "target"},
    "tool_used": {"tool", "input_match", "min", "max"},
    "tool_order": {"before", "after"},
    "file_exists": {"path", "exists"},
}
COMMON_GRADER_KEYS = {"type", "weight", "arm"}
WORD = re.compile(r"[a-z]{4,}")


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match, f"{path.as_posix()}: no frontmatter"
    return yaml.safe_load(match.group(1)) or {}, match.group(2).strip()


def description_words(skill: str) -> set[str]:
    meta, _ = frontmatter(ROOT / "src" / "skills" / skill / "SKILL.md")
    return set(WORD.findall(meta["description"].lower()))


def graders(case: Path) -> dict[str, dict]:
    return {path.stem: frontmatter(path)[0] for path in sorted((case / "graders").glob("*.md"))}


def is_skill_grader(grader: dict) -> bool:
    return grader["type"] == "tool_used" and grader["tool"] == "Skill"


def js_regex(pattern: str, flags: str = "") -> re.Pattern:
    """The tool's patterns are JavaScript regexes; these are the parts Python reads the same."""
    assert "(?" not in pattern.replace("(?:", ""), f"inline group in {pattern!r}"
    assert set(flags) <= set("dgimsuvy"), flags
    python = (re.IGNORECASE if "i" in flags else 0) | (re.MULTILINE if "m" in flags else 0)
    return re.compile(pattern, python | (re.DOTALL if "s" in flags else 0))


def stringify(value: object) -> str:
    """JSON.stringify, as the tool writes a tool call's input before `input_match` reads it."""
    return json.dumps(value, separators=(",", ":"))


CASE_SKILL = {
    "catch-up-ends-the-turn": "catch-up",
    "decision-note-has-matrix": "decision",
    "work-model-field-report": "work-model",
}

# For each case, the text its result grader reads: one a correct run writes, one it must refuse.
SAMPLES = {
    "catch-up-ends-the-turn": {
        "turn-end": (
            "Release 1.4.0 is out. Pull request 33 is delivered and waits for the integrator; "
            "issue 32 is ready for a worker.\n\nNo input needed from you right now: the integrator "
            "lands 33, and a worker starts on 32.",
            "Pull request 33 is delivered.\n\n## Your input needed\n\nShall I start a worker on 32?",
        ),
    },
    "decision-note-has-matrix": {
        "note-written": (
            stringify({
                "file_path": "decisions/settings-source.md",
                "content": "# Settings source\n\n## Current situation\n\nOne file, app.toml.\n\n"
                "## The problem\n\nCI runners cannot edit it.\n\n## What others do\n\nGit reads the "
                "environment over its files.\n\n```pugh\noptions: [file, both]\n```\n",
            }),
            stringify({
                "file_path": "decisions/settings-source.md",
                "content": "# Settings source\n\n## The problem\n\nCI runners cannot edit it.\n\n"
                "## Current situation\n\nOne file, app.toml.\n\n| option | score |\n|---|---|\n",
            }),
        ),
    },
    "work-model-field-report": {
        "report-template": (
            "<!-- se:field-report -->\n## Field report\n\nRequirements 1 and 2 are done.\n\n"
            "## Not delivered\n\n- Requirement 3, CSV export: not started; adding a CSV library "
            "is not this issue's to decide.\n<!-- se:field-report:end -->",
            "<!-- se:field-report -->\n## Field report\n\nJSON output, since filter and CSV export "
            "are done.\n\n## Not delivered\n\nNothing.\n<!-- se:field-report:end -->",
        ),
    },
}


def test_one_trigger_file_per_skill():
    assert [path.stem for path in TRIGGER_FILES] == SKILLS


@pytest.mark.parametrize("path", TRIGGER_FILES, ids=lambda path: path.stem)
def test_trigger_file_shape(path):
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and 16 <= len(entries) <= 24
    for entry in entries:
        assert set(entry) == {"query", "should_trigger", "split"}, entry
        assert isinstance(entry["query"], str) and entry["query"].strip()
        assert isinstance(entry["should_trigger"], bool)
        assert entry["split"] in {"train", "validation"}
    for label in (True, False):
        assert sum(entry["should_trigger"] is label for entry in entries) >= 8, label
        for split in ("train", "validation"):
            count = sum(e["should_trigger"] is label and e["split"] == split for e in entries)
            assert count >= 3, (label, split)
    train = sum(entry["split"] == "train" for entry in entries)
    assert 0.5 <= train / len(entries) <= 0.7


@pytest.mark.parametrize("path", TRIGGER_FILES, ids=lambda path: path.stem)
def test_each_near_miss_shares_a_word_with_the_description(path):
    words = description_words(path.stem)
    for entry in json.loads(path.read_text(encoding="utf-8")):
        if not entry["should_trigger"]:
            assert set(WORD.findall(entry["query"].lower())) & words, entry["query"]


def test_no_query_twice():
    queries = [e["query"] for path in TRIGGER_FILES for e in json.loads(path.read_text(encoding="utf-8"))]
    assert len(queries) == len(set(queries))


def test_one_case_per_skill():
    fired = set()
    for case in CASES:
        for grader in graders(case).values():
            if is_skill_grader(grader):
                fired |= {skill for skill in SKILLS if js_regex(grader["input_match"]).search(
                    stringify({"skill": f"se:{skill}"}))}
    assert len(CASES) == 3 and fired == set(SKILLS)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_case_prompt(case):
    meta, prompt = frontmatter(case / "prompt.md")
    assert set(meta) <= PROMPT_KEYS and "model" not in meta
    assert meta["name"] == case.name and prompt
    assert sorted(meta["allowed_tools"]) == ["Read", "Skill"]
    assert meta["max_turns"] == 20 and meta["timeout_seconds"] == 600


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_case_graders_call_no_judge(case):
    found = graders(case)
    for name, grader in found.items():
        assert grader["type"] in GRADER_KEYS, (name, grader["type"])
        assert set(grader) <= COMMON_GRADER_KEYS | GRADER_KEYS[grader["type"]], name
    skill = [grader for grader in found.values() if is_skill_grader(grader)]
    assert "skill-fired" in found and is_skill_grader(found["skill-fired"]) and len(skill) == 1
    assert len(found) > len(skill), "no grader on the result"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_skill_grader_names_the_skill_with_or_without_prefix(case):
    grader = graders(case)["skill-fired"]
    skill = CASE_SKILL[case.name]
    pattern = js_regex(grader["input_match"])
    assert pattern.search(stringify({"skill": f"se:{skill}"}))
    assert pattern.search(stringify({"skill": skill}))
    others = [other for other in SKILLS if other != skill]
    assert not any(pattern.search(stringify({"skill": f"se:{other}"})) for other in others)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_result_graders_pass_and_refuse_their_samples(case):
    result = {name: g for name, g in graders(case).items() if not is_skill_grader(g)}
    assert set(result) == set(SAMPLES[case.name])
    for name, grader in result.items():
        source = grader.get("pattern") or grader.get("input_match")
        pattern = js_regex(source, grader.get("flags", ""))
        good, bad = SAMPLES[case.name][name]
        assert pattern.search(good), name
        assert not pattern.search(bad), name


def test_every_pattern_is_plain_javascript():
    for case in CASES:
        for grader in graders(case).values():
            for key in ("pattern", "input_match"):
                if key in grader:
                    js_regex(grader[key], grader.get("flags", ""))


def test_no_mocks_and_results_ignored():
    assert not [path for path in OUTCOMES.rglob("mocks") if path.is_dir()]
    lines = (OUTCOMES / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "results/" in lines


def test_nothing_under_evals_is_a_test():
    assert not list(EVALS.rglob("*.py"))


def test_public_text_only():
    private = re.compile(r"[\w.+-]+@[\w-]+\.\w+|/home/|/Users/|[A-Za-z]:\\")
    texts = [path.read_text(encoding="utf-8") for path in EVALS.rglob("*") if path.is_file()]
    assert not [match for text in texts for match in private.findall(text)]
