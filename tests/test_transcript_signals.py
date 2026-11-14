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


# The more signals (--more), the research list (--research) and their privacy.


def failed(file, line, call_id, text, tool="Bash", denied=False):
    return Event(file, line, "tool", "tool_result", tool, text, None, call_id, {}, True, denied)


def agent(file, line, text, seconds=None):
    return Event(file, line, "agent", "message", text=text,
                 time=None if seconds is None else at(seconds))


def test_without_more_the_new_signals_stay_out_of_the_tally():
    events = [call("s", 1, "Bash", "c1", command="ls"), failed("s", 2, "c1", "Exit code 1")]
    assert list(signals.tally(events, ["s", "t"])["signals"]) == list(signals.SIGNALS)
    assert "unread" not in signals.tally(events, ["s", "t"])
    more = signals.tally(events, ["s", "t"], more=True)
    assert list(more["signals"]) == [*signals.SIGNALS, *signals.MORE_SIGNALS]
    assert list(signals.MORE_SIGNALS) == [
        "repeated-failures", "misuse", "voids", "lacked", "greeting"]


def test_failures_of_one_shape_and_clause_form_one_group():
    events = [
        call("s", 1, "Bash", "c1", command="git push topic1"),
        failed("s", 2, "c1", "Exit code 1\nrejected"),
        call("t", 1, "Bash", "c2", command="git push topic2"),
        failed("t", 2, "c2", "Exit code 1\nrejected again"),
        call("t", 3, "Bash", "c3", command="git pull topic1"),  # another shape
        failed("t", 4, "c3", "Exit code 1"),
        call("t", 5, "Bash", "c4", command="git push topic3"),  # another clause
        failed("t", 6, "c4", "Exit code 128"),
        call("t", 7, "Bash", "c5", command="git push topic4"),  # misuse
        failed("t", 8, "c5", "<tool_use_error>Blocked: Exit code 1</tool_use_error>"),
        call("t", 9, "Edit", "c6"), failed("t", 10, "c6", "Exit code 1", tool="Edit"),  # another tool
        call("t", 11, "Bash", "c7", command="git push topic5"),  # a refusal
        failed("t", 12, "c7", "Exit code 1", denied=True),
    ]
    hits = signals.repeated_failures(events)
    assert [(h.file, h.line, h.key) for h in hits] == [
        ("s", 2, "Bash git push <arg>: exit 1"), ("t", 2, "Bash git push <arg>: exit 1")]
    assert [(h.line, h.key) for h in signals.misuse(events)] == [(8, "Bash")]
    two_edits = [call("s", 1, "Edit", "c1"), failed("s", 2, "c1", "boom", tool="Edit"),
                 call("s", 3, "Edit", "c2"), failed("s", 4, "c2", "bang", tool="Edit")]
    assert {h.key for h in signals.repeated_failures(two_edits)} == {"Edit: other"}


def test_the_clause_is_the_lacked_class_then_the_exit_code_then_other():
    assert signals.failure_clause("Exit code 2\nbash: jq: command not found") == "command-not-found"
    assert signals.failure_clause("  Exit code 3\nno") == "exit 3"
    assert signals.failure_clause("it says Exit code 3") == "other"
    assert signals.MISUSE.search("InputValidationError: missing field")


def test_a_void_is_a_long_gap_before_an_agent_event_with_no_call_open():
    events = [
        person("s", 1, "go"), Event("s", 1, "person", "message", text="go", time=at(0)),
        call("s", 2, "Bash", "c1", seconds=10), result("s", 3, "c1", seconds=20),
        call("s", 4, "Bash", "c2", seconds=620),  # 10 minutes after a result: a void
        result("s", 5, "c2", seconds=630),
        Event("s", 6, "person", "message", text="next", time=at(1230)),  # waiting, no void
        call("s", 7, "Bash", "c3", seconds=1240),
        agent("s", 8, "still running", seconds=1840),  # a call is open: no void
        result("s", 9, "c3", seconds=1850),
        agent("t", 1, "first", seconds=0), agent("t", 2, "later", seconds=301),  # another session
    ]
    assert [(h.file, h.line, h.key) for h in signals.voids(events)] == [
        ("s", 4, "tool"), ("t", 2, "agent")]
    assert signals.voids(events, seconds=1000) == []


def test_what_the_environment_lacked_is_found_by_class():
    events = [
        call("s", 1, "Bash", "c1", command="jq . data.json"),
        failed("s", 2, "c1", "Exit code 127\nbash: jq: command not found"),
        call("s", 3, "Bash", "c2", command="make all"),
        failed("s", 4, "c2", "Exit code 2\nsh: 1: secret-tool: command not found"),
        call("s", 5, "Bash", "c3", command="cat /etc/shadow"),
        failed("s", 6, "c3", "cat: /etc/shadow: Permission denied"),
        call("s", 7, "Bash", "c4", command="curl https://example.com"),
        failed("s", 8, "c4", "request blocked: no rule allows host example.com"),
        call("s", 9, "Bash", "c5", command="curl https://example.com"),
        failed("s", 10, "c5", "curl: (56) CONNECT tunnel failed, response 403"),
        call("s", 11, "Bash", "c6", command="rm x"),
        failed("s", 12, "c6", "Permission denied by the host", denied=True),  # a refusal
        call("s", 13, "Bash", "c7", command="ls"),
        failed("s", 14, "c7", "<tool_use_error>command not found</tool_use_error>"),  # misuse
    ]
    assert [(h.line, h.key) for h in signals.lacked(events)] == [
        (2, "command-not-found jq"), (4, "command-not-found <arg>"), (6, "permission-refused"),
        (8, "host-blocked"), (10, "host-blocked")]
    windows = [call("w", 1, "PowerShell", "c1", command="rg foo"),
               failed("w", 2, "c1", "'rg' is not recognized as an internal or external command",
                      tool="PowerShell")]
    assert [h.key for h in signals.lacked(windows)] == ["command-not-found rg"]


GREETING = "SE 5.73.0 started: 3 skills, 6 rules, 3 sub-agents"


def context(file, line, text, sidechain=False):
    return Event(file, line, "system", "context", text=text, sidechain=sidechain)


def handed(file, line, text):
    return Event(file, line, "tool", "tool_result", "Bash", text, None, "g")


def test_the_greeting_at_the_first_agent_message_is_classed():
    other = "SE none started: 1 skill, 1 rule, 1 sub-agent"
    sessions = [
        context("same", 1, f"hello\n{GREETING}"), agent("same", 2, f"{GREETING}\nhi"),
        handed("tool", 1, GREETING), agent("tool", 2, GREETING),
        context("other", 1, GREETING), agent("other", 2, other),
        agent("unchecked", 1, other),
        context("none", 1, GREETING), agent("none", 2, "hi"), agent("none", 3, GREETING),
        person("silent", 1, "go"),
        context("latest", 1, other), handed("latest", 2, GREETING), agent("latest", 3, GREETING),
        context("side", 1, other, sidechain=True), context("side", 2, GREETING),
        Event("side", 3, "agent", "message", text="x", sidechain=True), agent("side", 4, GREETING),
        Event("sub", 1, "agent", "message", text=GREETING, sidechain=True),
    ]
    assert {h.file: h.key for h in signals.greeting(sessions)} == {
        "same": "same", "tool": "same", "other": "other", "unchecked": "unchecked",
        "none": "none", "silent": "none", "latest": "same", "side": "same"}
    assert signals.GREETING.search(other)


def test_the_hook_context_is_read_only_with_more_and_carries_the_sidechain_mark():
    rows = lines(
        {"type": "attachment", "timestamp": "2026-01-01T10:00:00Z", "attachment": {
            "type": "hook_additional_context", "hookEvent": "SessionStart",
            "content": ["one", "two"]}},
        {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "isSidechain": True, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}},
    )
    assert [e.kind for e in signals.read_events(rows, "t")] == ["tool_call", "tool_result"]
    events = signals.read_events(rows, "t", more=True)
    assert [(e.who, e.kind, e.text) for e in events][0] == ("system", "context", "one\ntwo")
    assert [(e.tool, e.sidechain) for e in events[1:]] == [("Bash", True), ("Bash", True)]
    assert Event("f", 1, "agent", "message").sidechain is False


def test_a_three_argument_adapter_still_reads_with_more(monkeypatch):
    monkeypatch.setitem(signals.ADAPTERS, "plain", lambda raw, file, line: [
        Event(file, line, "person", "message", text=raw)])
    assert len(signals.read_events(["a", "b"], "p", adapter="plain", more=True)) == 2


def test_the_research_list_holds_exact_search_and_fetch_calls():
    events = [
        call("s", 1, "WebSearch", "c1", seconds=5, query="what is x"),
        call("s", 2, "web_search", "c2", query="no"),
        call("s", 3, "mcp__x__WebFetch", "c3", url="https://no.example.com"),
        call("s", 4, "WebFetch", "c4", seconds=9, url="https://example.com/a", prompt="p"),
    ]
    assert signals.research(events) == [
        {"tool": "WebSearch", "query": "what is x", "time": at(5).isoformat()},
        {"tool": "WebFetch", "url": "https://example.com/a", "time": at(9).isoformat()}]
    assert signals.research(events, adapter="other") == []
    now = datetime(2026, 11, 14, 8, 9, 10, tzinfo=timezone.utc)
    assert signals.research_name(now, []) == "20261114T080910Z.jsonl"
    assert signals.research_name(now, ["20261114T080910Z.jsonl", "20261114T080910Z-2.jsonl"]) == (
        "20261114T080910Z-3.jsonl")


SEARCHED = "zanzibar quokka recipe"
FETCHED = "https://example.com/quokka-page"


def research_transcript(folder: Path, searches: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "timestamp": "2026-01-01T10:00:00Z",
             "message": {"role": "user", "content": "go"}}]
    if searches:
        rows.append({"type": "assistant", "timestamp": "2026-01-01T10:00:01Z", "message": {
            "role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "WebSearch", "input": {"query": SEARCHED}},
                {"type": "tool_use", "id": "2", "name": "WebFetch", "input": {"url": FETCHED}}]}})
    path = folder / "s.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_research_is_written_only_on_request_and_never_printed(tmp_path):
    import re
    transcript = research_transcript(tmp_path / "in")
    repo = tmp_path / "repo"
    repo.mkdir()
    folder = repo / ".se" / "research"
    assert run(transcript, "--repo", repo, "--more", "--json")[0] == 0 and not folder.exists()
    outputs = [run(transcript, "--research", "--repo", repo, *extra)
               for extra in ((), ("--more", "--json"))]
    assert len(list(folder.iterdir())) == 2
    named = set()
    for code, out in outputs:
        found = re.fullmatch(r"research: 2 in \.se/research/(\d{8}T\d{6}Z(-\d+)?\.jsonl)\n", out)
        assert code == 0 and found, out
        named.add(found.group(1))
        path = folder / found.group(1)
        assert SEARCHED not in out and "quokka" not in out and "corrections" not in out
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [entry.get("query") or entry.get("url") for entry in entries] == [SEARCHED, FETCHED]
    assert len(named) == 2
    quiet = research_transcript(tmp_path / "quiet", searches=False)
    assert run(quiet, "--research", "--repo", repo) == (0, "research: 0, no file written\n")
    assert len(list(folder.iterdir())) == 2


def test_the_research_folder_is_ignored_in_ses_checkout(fake_git_door, tmp_path):
    import fake_git
    import git_door
    root = fake_git.init(tmp_path / "project", "-b", "main")
    (root / ".gitignore").write_text((PROJECT / ".gitignore").read_text(encoding="utf-8"),
                                     encoding="utf-8")
    assert git_door.run("check-ignore", "-q", ".se/research/probe.jsonl", root=root).returncode == 0


def test_under_more_a_file_without_events_is_nothing_read(tmp_path):
    (tmp_path / "empty.jsonl").write_text('{"type": "summary"}\n', encoding="utf-8")
    research_transcript(tmp_path / "full", searches=False)
    code, out = run(tmp_path, "--more", "--json", "--repo", tmp_path)
    result = json.loads(out)
    assert code == 0 and result["unread"] == ["empty.jsonl"]
    assert all("empty.jsonl" not in s["sessions"] for s in result["signals"].values())
    assert "nothing read: empty.jsonl\n" in run(tmp_path, "--more", "--repo", tmp_path)[1]
    (tmp_path / "full" / "s.jsonl").unlink()
    code, out = run(tmp_path, "--more", "--json", "--repo", tmp_path)
    assert json.loads(out)["signals"] == {} and json.loads(out)["unread"] == ["empty.jsonl"]
    text = run(tmp_path, "--more", "--repo", tmp_path)[1]
    assert text == "transcript signals: 1 transcript(s), 0 events\nnothing read: empty.jsonl\n"
    assert "nothing read" not in run(tmp_path, "--repo", tmp_path)[1]


def test_the_more_output_never_shows_error_text_context_queries_or_addresses(tmp_path):
    name = "Zebulon" + " Quarrington"
    outside = "/ho" + "me/zebulon/private/plan.txt"
    host = "secret-host" + ".example.org"
    secret = "the secret launch plan"
    record = lambda content, role="user", **extra: {
        "type": role, "timestamp": "2026-01-01T10:00:00Z", **extra,
        "message": {"role": role, "content": content}}
    use = lambda id, tool="Bash", **arguments: record(
        [{"type": "tool_use", "id": id, "name": tool, "input": arguments}], "assistant")
    fail = lambda id, text: record([{"type": "tool_result", "tool_use_id": id, "is_error": True,
                                     "content": text}])
    rows = [
        {"type": "attachment", "timestamp": "2026-01-01T09:59:00Z", "attachment": {
            "type": "hook_additional_context", "hookEvent": "SessionStart",
            "content": [f"{GREETING}\n{name} works in {outside}"]}},
        record([{"type": "text", "text": f"{GREETING}\n{secret}"}], "assistant"),
        use("1", command=f"curl https://{host}/{secret.replace(' ', '-')}"),
        fail("1", f"request blocked: no rule allows host {host}"),
        use("2", command=f"zebtool {outside}"),
        fail("2", f"bash: zebtool-{name}: command not found"),
        use("3", command=f"cat {outside}"), fail("3", f"Exit code 1\n{secret} {name}"),
        use("4", command=f"cat {outside}"), fail("4", f"Exit code 1\n{secret} {name}"),
        use("5", tool="Edit", file_path=outside),
        fail("5", f"<tool_use_error>{secret} {outside}</tool_use_error>"),
        use("6", tool="WebSearch", query=f"{name} {secret}"),
        use("7", tool="WebFetch", url=f"https://{host}/x"),
    ]
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    shown = run(transcript, "--more", "--repo", tmp_path)[1] + run(
        transcript, "--more", "--json", "--repo", tmp_path)[1]
    for expected in ("1x same", "1x host-blocked", "1x command-not-found <arg>",
                     "2x Bash cat <arg>: exit 1", "1x Edit"):
        assert expected in shown, expected
    for planted in (name, *name.split(), outside, "zebulon", "zebtool", host, "secret", secret,
                    "launch", str(tmp_path), tmp_path.as_posix(), "works in"):
        assert planted.lower() not in shown.lower(), planted
