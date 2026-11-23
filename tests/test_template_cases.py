"""The template engine's shared cases (tests/template_cases.py) stand as the Python engine answers
them: the Go engine's test (components/template/cases_test.go) reads the committed files, so a
change to scripts/templates.py or templates/ that moves an answer refreshes them in the same
change."""

from __future__ import annotations

import functools
import json

import template_cases


@functools.cache
def built() -> dict[str, str]:
    return template_cases.build()


def test_the_committed_shared_cases_are_what_the_python_engine_answers():
    assert template_cases.drift(built()) == [], (
        "the shared template cases drifted; run `uv run python tests/template_cases.py`")


def test_each_case_file_names_its_generator_first_and_stays_under_the_size_limit():
    for name, text in built().items():
        data = json.loads(text)
        assert next(iter(data)) == "generated", name
        assert "tests/template_cases.py" in data["generated"], name
        assert len(text.encode("utf-8")) < 200_000, name


def test_the_cases_cover_every_template_kind_rule_and_selection():
    files = {name: json.loads(text) for name, text in built().items()}
    cases = [case for data in files.values() for entry in data.get("templates", {}).values()
             for case in [*entry.get("fills", []), *entry.get("bodies", [])]]
    rules = {finding[1] for case in cases for finding in case.get("findings", [])}
    assert {"required", "choice", "not-picked", "duplicate", "words", "actor", "one-sentence",
            "bare-number", "board", "terms", "title-shape", "quote", "version", "node",
            "unnamed-entry", "checker"} <= rules
    kinds = {entry["template"]["kind"] for data in files.values()
             for entry in data.get("templates", {}).values()}
    assert kinds == {"document", "block", "entry", "interface"}
    assert files["load-errors.json"]["errors"]
    assert any(case["selected"] for case in files["se-select.json"]["select"])
