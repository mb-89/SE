"""Transcript signals (scripts/transcript_signals.py): the adapter, each signal on its own events,
the command shape, the fixture transcripts with planted signals and a clean one, the privacy of
the output, and that nothing calls the module."""

import contextlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"


def load(name: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


signals = load("transcript_signals")
Event = signals.Event
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = signals.main([str(arg) for arg in argv])
    return code, out.getvalue()


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def call(file, line, tool, call_id, seconds=0, **arguments):
    return Event(file, line, "agent", "tool_call", tool, str(arguments.get("command", "")),
                 at(seconds), call_id, arguments)


def result(file, line, call_id, seconds=0, error=False, denied=False, tool=""):
    return Event(file, line, "tool", "tool_result", tool, "", at(seconds), call_id, {}, error,
                 denied)


def person(file, line, text, who="person"):
    return Event(file, line, who, "message", text=text)


def lines(*records) -> list[str]:
    return [json.dumps(record) for record in records]


# Requirement 1: the adapter turns each line into plain events.


def test_claude_code_adapter_reads_messages_calls_and_results():
    events = signals.read_events(lines(
        {"type": "user", "timestamp": "2026-01-01T10:00:00Z",
         "message": {"role": "user", "content": "go"}},
        {"type": "user", "promptSource": "system", "message": {"role": "user", "content": "note"}},
        {"type": "assistant", "timestamp": "2026-01-01T10:00:01Z", "message": {
            "role": "assistant", "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "permissionDecision": {"decision": "reject"}, "message": {
            "role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "x", "content": "no", "is_error": True}]}},
        {"type": "summary"},
        "{broken",
    ), "t.jsonl")
    assert [(e.line, e.who, e.kind, e.tool) for e in events] == [
        (1, "person", "message", ""), (2, "system", "message", ""),
        (3, "agent", "message", ""), (3, "agent", "tool_call", "Bash"),
        (4, "tool", "tool_result", "Bash")]
    assert events[0].time == datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    assert events[3].text == "ls" and events[4].denied and events[4].error


def test_another_format_needs_only_another_adapter(monkeypatch):
    monkeypatch.setitem(signals.ADAPTERS, "plain", lambda raw, file, line: [
        Event(file, line, "person", "message", text=raw)])
    events = signals.read_events(["a", "b"], "p.txt", adapter="plain")
    assert [(e.line, e.text) for e in events] == [(1, "a"), (2, "b")]


# Requirement 2: each signal, one pure function with its own test.


def test_corrections_are_short_redirecting_turns_right_after_an_agent_action():
    events = [
        person("s", 1, "No, the other branch instead."),  # no action before it
        call("s", 2, "Bash", "c1", command="ls"), result("s", 3, "c1"),
        person("s", 4, "No, the other branch instead."),  # a correction
        call("s", 5, "Bash", "c2", command="ls"),
        person("s", 6, "Stop, wrong file.", who="system"),  # not the person's
        person("s", 7, "Thanks, continue with the next part of the work as planned please."),
        call("s", 8, "Bash", "c3", command="ls"),
        person("s", 9, "no " + "word " * 20),  # too long
        call("s", 10, "Bash", "c4", command="ls"),
        person("s", 11, "[Request interrupted by user]"),  # an interrupt redirects
    ]
    assert [hit.line for hit in signals.corrections(events)] == [4, 11]


def test_retries_are_the_same_call_repeated_after_a_failure():
    events = [
        call("s", 1, "Bash", "c1", command="make a"), result("s", 2, "c1", error=True),
        call("s", 3, "Bash", "c2", command="make b"),  # another call
        call("s", 4, "Bash", "c3", command="make a"),  # the retry
        call("s", 5, "Bash", "c4", command="make a"),  # the first retry succeeded
        call("s", 6, "Read", "c5", file_path="x"), result("s", 7, "c5", error=True, denied=True),
        call("s", 8, "Read", "c6", file_path="x"),  # after a denial: no retry
        call("t", 1, "Bash", "c7", command="make a"),  # another session
    ]
    assert [(h.file, h.line, h.key) for h in signals.retries(events)] == [("s", 4, "Bash")]


def test_repeated_commands_are_one_shape_used_three_times_across_sessions():
    events = [
        call("s", 1, "Bash", "c1", command="gh pr view 12 --json body"),
        call("s", 2, "Bash", "c2", command="gh pr view 34 --json title"),
        call("t", 1, "Bash", "c3", command="cd /repo && gh pr view 56 --json state"),
        call("t", 2, "Bash", "c4", command="ls"),
        call("t", 3, "Bash", "c5", command="ls"),
        call("t", 4, "Read", "c6", file_path="gh pr view 1 --json x"),
    ]
    hits = signals.repeated_commands(events)
    assert [(h.file, h.line) for h in hits] == [("s", 1), ("s", 2), ("t", 1)]
    assert {h.key for h in hits} == {"gh pr view <arg> --json <arg>"}
    assert len(signals.repeated_commands(events, repeats=2)) == 5


def test_command_shape_masks_every_argument_but_names_options_and_repository_paths():
    keep = {"scripts/retro.py"}.__contains__
    shape = signals.command_shape
    assert shape("uv run python scripts/retro.py collect --since 2026-01-01 x", keep) == (
        "uv run python scripts/retro.py collect --since <arg>")
    assert shape("/usr/bin/git commit --author=someone -m 'a message'") == (
        "git commit --author=<arg> -m <arg>")
    assert shape("TOKEN=abc ./run.sh | grep -c foo > out.txt") == (
        "TOKEN=<arg> run.sh | grep -c <arg> > <arg>")
    assert shape("python3 - <<'EOF'\nprint('body')\nEOF") == "python3 <arg> << <arg>"
    assert shape("echo 'unbalanced") == "echo <arg>"


def test_scripts_written_twice_are_near_identical_writes_in_different_sessions():
    script = "\n".join(f"line_{n} = {n}" for n in range(8))
    events = [
        call("s", 1, "Write", "c1", file_path="a.py", content=script),
        call("s", 2, "Write", "c2", file_path="b.py", content=script),  # same session
        call("t", 1, "Write", "c3", file_path="c.py", content=script + "\nextra = 9"),
        call("t", 2, "Write", "c4", file_path="notes.md", content=script),  # no script
        call("u", 1, "Write", "c5", file_path="d.py", content="x = 1\ny = 2"),  # too small
        call("u", 2, "Write", "c6", file_path="e.py",
             content="\n".join(f"other_{n}()" for n in range(8))),  # different
    ]
    hits = signals.scripts_written_twice(events)
    assert [(h.file, h.line) for h in hits] == [("t", 1)]


def test_denials_are_counted_by_tool():
    events = [
        call("s", 1, "Bash", "c1"), result("s", 2, "c1", error=True, denied=True, tool="Bash"),
        call("s", 3, "Edit", "c2"), result("s", 4, "c2", error=True, tool="Edit"),
    ]
    assert [(h.line, h.key) for h in signals.denials(events)] == [(2, "Bash")]


def test_long_waits_are_gaps_over_the_threshold_between_a_call_and_its_result():
    events = [
        call("s", 1, "Bash", "c1", seconds=0), result("s", 2, "c1", seconds=121),
        call("s", 3, "Read", "c2", seconds=200), result("s", 4, "c2", seconds=210),
        call("t", 1, "Bash", "c1", seconds=0), result("t", 2, "c1", seconds=5),
    ]
    assert [(h.file, h.line, h.key) for h in signals.long_waits(events)] == [("s", 1, "Bash")]
    assert len(signals.long_waits(events, seconds=4)) == 3


# Requirement 3 and the acceptance: counts per signal, per session and in total, text and JSON.


EXPECTED = {
    "corrections": {"a.jsonl": 1, "b.jsonl": 0},
    "retries": {"a.jsonl": 1, "b.jsonl": 0},
    "repeated-commands": {"a.jsonl": 3, "b.jsonl": 1},
    "scripts-written-twice": {"a.jsonl": 0, "b.jsonl": 1},
    "denials": {"a.jsonl": 1, "b.jsonl": 1},
    "long-waits": {"a.jsonl": 0, "b.jsonl": 1},
}


def test_the_planted_fixtures_give_the_expected_counts_as_json():
    code, out = run(FIXTURES / "planted", "--json", "--repo", PROJECT)
    assert code == 0
    result = json.loads(out)
    assert result["files"] == 2
    assert {name: s["sessions"] for name, s in result["signals"].items()} == EXPECTED
    assert {name: s["total"] for name, s in result["signals"].items()} == {
        name: sum(counts.values()) for name, counts in EXPECTED.items()}
    assert result["signals"]["denials"]["by"] == {"Bash": 1, "Edit": 1}
    assert result["signals"]["repeated-commands"]["by"] == {
        "uv run python scripts/transcript_signals.py --json <arg>": 4}
    assert result["signals"]["long-waits"]["locations"] == [{"file": "b.jsonl", "line": 6}]


def test_the_text_output_names_each_count_and_location():
    code, out = run(FIXTURES / "planted" / "a.jsonl", FIXTURES / "planted" / "b.jsonl")
    assert code == 0
    assert "corrections: 1\n  a.jsonl: 1\n  at a.jsonl:6" in out
    assert "denials: 2\n  a.jsonl: 1\n  b.jsonl: 1\n  at a.jsonl:15, b.jsonl:5\n  1x Bash" in out


def test_a_clean_transcript_gives_zeros():
    code, out = run(FIXTURES / "clean.jsonl", "--json")
    assert code == 0
    assert {name: s["total"] for name, s in json.loads(out)["signals"].items()} == dict.fromkeys(
        signals.SIGNALS, 0)


def test_at_most_five_locations_are_shown(tmp_path):
    many = [call("s", n, "Bash", f"c{n}", command=f"ls {n}") for n in range(1, 9)]
    result = signals.tally(many, ["s"])
    assert result["signals"]["repeated-commands"]["total"] == 8
    assert len(result["signals"]["repeated-commands"]["locations"]) == signals.LOCATIONS


def test_a_missing_path_is_refused(tmp_path):
    code, out = run(tmp_path / "missing.jsonl")
    assert code == 2 and out == ""


# Requirement 4: privacy. Each private thing is planted; none comes through.


def test_the_output_never_shows_text_names_outside_paths_tokens_or_addresses(tmp_path):
    name = "Zebulon" + " Quarrington"
    address = "zebulon.q" + "@" + "mail-host.org"
    token = "ghp_" + "Q7x" * 12
    outside = "/ho" + "me/zebulon/private/plan.txt"
    secret = "the secret launch plan"
    record = lambda content, role="user", **extra: {
        "type": role, "timestamp": "2026-01-01T10:00:00Z", **extra,
        "message": {"role": role, "content": content}}
    use = lambda id, **arguments: record(
        [{"type": "tool_use", "id": id, "name": "Bash", "input": arguments}], "assistant")
    rows = [
        record(f"{name} here, {secret}, mail {address}"),
        record([{"type": "text", "text": f"Writing {secret} to {outside}"}], "assistant"),
        use("1", command=f"curl -H 'Authorization: {token}' {outside} --user {address}"),
        record([{"type": "tool_result", "tool_use_id": "1", "is_error": True,
                 "content": f"denied by hook: {secret} {token}"}]),
        use("2", command=f"curl -H 'Authorization: {token}' {outside} --user {address}"),
        record(f"No, {name} says stop."),
        use("3", command=f"git commit --author '{name} <{address}>' -m '{secret}'"),
        use("4", command=f"cat {outside}"), use("5", command=f"cat {outside}"),
        use("6", command=f"cat {token}"),
    ]
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    shown = run(transcript, "--repo", tmp_path)[1] + run(transcript, "--json", "--repo",
                                                          tmp_path)[1]
    assert "repeated-commands: 3" in shown and "corrections: 1" in shown
    for planted in (name, *name.split(), address, token, outside, "zebulon", secret, "launch",
                    str(tmp_path), tmp_path.as_posix(), "Authorization"):
        assert planted.lower() not in shown.lower(), planted


# Requirement 5: not wired in.


def test_nothing_calls_the_module():
    callers = [path.relative_to(PROJECT).as_posix()
               for folder in ("scripts", "components", "kern", "src")
               for path in (PROJECT / folder).rglob("*")
               if path.is_file() and path.suffix in (".py", ".go", ".md", ".sh", ".toml")
               and path.name != "transcript_signals.py"
               and "transcript_signals" in path.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
