"""Tests of se_usage: the ad hoc components' use log the kern core writes and retro.py collect
reads (docs/go-core.md "Scripts are ad hoc, components are long-term")."""

from __future__ import annotations

from pathlib import Path

import se_usage


def test_record_appends_one_json_line_per_use_and_read_parses_it(tmp_path: Path):
    se_usage.record(tmp_path, "probe", session="s1", at="2026-11-05T00:00:00Z")
    se_usage.record(tmp_path, "probe", session="s2", at="2026-11-06T00:00:00Z")
    log = se_usage.path(tmp_path)
    assert log == tmp_path / ".se" / "usage" / "adhoc.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
    records = se_usage.read(tmp_path)
    assert [r["session"] for r in records] == ["s1", "s2"]
    assert all(r["component"] == "probe" and r["path"] == ".se/components/probe" for r in records)


def test_read_skips_a_malformed_line_and_missing_log_is_empty(tmp_path: Path):
    assert se_usage.read(tmp_path) == []
    log = se_usage.path(tmp_path)
    log.parent.mkdir(parents=True)
    log.write_text('{"component": "a", "session": "s1", "at": "2026-11-05T00:00:00Z"}\n'
                   "not json\n"
                   '{"no": "component"}\n'
                   '{"component": "b", "session": "s2", "at": "2026-11-06T00:00:00Z"}\n',
                   encoding="utf-8")
    assert [r["component"] for r in se_usage.read(tmp_path)] == ["a", "b"]


def always(_: str) -> bool:
    return True


def test_candidates_counts_distinct_sessions_and_applies_the_threshold(tmp_path: Path):
    for session in ("s1", "s1", "s2", "s3"):  # s1 twice: four uses, three sessions
        se_usage.record(tmp_path, "keep", session=session, at="2026-11-05T00:00:00Z")
    for session in ("s1", "s2"):  # two sessions: under the threshold
        se_usage.record(tmp_path, "drop", session=session, at="2026-11-05T00:00:00Z")
    found = se_usage.candidates(se_usage.read(tmp_path), always)
    assert [c["component"] for c in found] == ["keep"]
    assert found[0] == {"component": "keep", "path": ".se/components/keep", "sessions": 3, "uses": 4}


def test_candidates_takes_only_uses_in_the_window(tmp_path: Path):
    for session in ("s1", "s2", "s3"):
        se_usage.record(tmp_path, "probe", session=session, at="2026-11-05T00:00:00Z")
    se_usage.record(tmp_path, "probe", session="s4", at="2026-10-01T00:00:00Z")
    in_window = lambda at: at > "2026-11-01T00:00:00Z"  # noqa: E731
    found = se_usage.candidates(se_usage.read(tmp_path), in_window)
    assert found[0]["sessions"] == 3 and found[0]["uses"] == 3
    # Outside the window there are no in-window uses, so nothing is a candidate.
    assert se_usage.candidates(se_usage.read(tmp_path), lambda at: False) == []


def test_an_empty_session_is_one_anonymous_bucket_below_the_threshold(tmp_path: Path):
    for _ in range(5):
        se_usage.record(tmp_path, "probe", session="", at="2026-11-05T00:00:00Z")
    assert se_usage.candidates(se_usage.read(tmp_path), always) == []
