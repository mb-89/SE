"""session_cost.py: the token count and weight of sessions, over synthetic transcripts written here.

Every fixture below is synthetic: made-up ids, models and counts, priced with the test's own table
(`TEST_PRICES`), never a real transcript.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("session_cost", PROJECT / "scripts" / "session_cost.py")
cost = importlib.util.module_from_spec(_spec)
sys.modules["session_cost"] = cost
_spec.loader.exec_module(cost)

MARKER = "SYNTHETIC-PRIVATE-MARKER-7f3a"
MODEL = "m-test"
TEST_PRICES = """\
# synthetic test table
[[price]]
model = "m-test"
speed = "standard"
input = 1
cache_read = 0.1
write_5m = 1.25
write_1h = 2
output = 5
source = "test"
date = "2026-11-16"

[[price]]
model = "m-tiered"
speed = "standard"
input = 1
cache_read = 0.1
write_5m = 1.25
write_1h = 2
output = 5
above_tokens = 100
above = { input = 2, cache_read = 0.2, write_5m = 2.5, write_1h = 4, output = 10 }
source = "test"
date = "2026-11-16"
"""


def usage(input_=0, read=0, w5=0, w1=0, output=0, split=True, **more):
    block = {"input_tokens": input_, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": w5 + w1, "output_tokens": output, **more}
    if split:
        block["cache_creation"] = {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}
    return block


def assistant(message_id, use, model=MODEL, session="sess-a", tools=(), sidechain=False,
              request=None):
    content = [{"type": "text", "text": f"answer {MARKER}"}]
    content += [{"type": "tool_use", "id": f"t-{name}", "name": name,
                 "input": {"command": MARKER, "file_path": f"/srv/outside/{MARKER}"}} for name in tools]
    message = {"model": model, "role": "assistant", "content": content, "usage": use}
    if message_id:
        message["id"] = message_id
    record = {"type": "assistant", "sessionId": session, "isSidechain": sidechain, "message": message}
    if request:
        record["requestId"] = request
    return json.dumps(record)


def user(text, session="sess-a"):
    return json.dumps({"type": "user", "sessionId": session,
                       "message": {"role": "user", "content": text}})


def write(path: Path, lines) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def prices(tmp_path) -> Path:
    return write(tmp_path / "prices.toml", [TEST_PRICES])


@pytest.fixture
def folder(tmp_path) -> Path:
    """One session file with two calls (one id over three rows, one 1-hour write) and its sub-agent."""
    root = tmp_path / "transcripts"
    write(root / "sess-a.jsonl", [
        user(f"please {MARKER}"),
        assistant("msg-a", usage(10, 100, w5=20, output=1)),
        assistant("msg-a", usage(10, 100, w5=20, output=5)),
        assistant("msg-a", usage(10, 100, w5=20, output=7), tools=["Bash"]),
        json.dumps({"type": "user", "sessionId": "sess-a", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t-Bash", "content": MARKER}]}}),
        assistant("msg-b", usage(4, 200, w1=30, output=10), tools=["Edit"]),
    ])
    write(root / "sess-a" / "subagents" / "agent-1.jsonl", [
        assistant("msg-c", usage(2, 50, w5=8, output=3), sidechain=True),
    ])
    return root


def run(capsys, *args) -> tuple[int, str, str]:
    code = cost.main([str(arg) for arg in args])
    out, err = capsys.readouterr()
    return code, out, err


def run_json(capsys, *args) -> dict:
    code, out, _ = run(capsys, *args, "--json")
    assert code == 0
    return json.loads(out)


# Hand-computed with TEST_PRICES (input 1, cache read 0.1, 5m 1.25, 1h 2, output 5):
# msg-a: 10 + 100*0.1 + 20*1.25 + 7*5 = 80; context 130
# msg-b: 4 + 200*0.1 + 30*2 + 10*5 = 134; context 234
# msg-c (sub-agent): 2 + 50*0.1 + 8*1.25 + 3*5 = 32


def test_tokens_and_units_equal_the_hand_computed_values(capsys, folder, prices):
    result = run_json(capsys, folder, "--prices", prices)
    assert [entry["session"] for entry in result["sessions"]] == ["sess-a"]
    entry = result["sessions"][0]
    assert (entry["calls"], entry["main_calls"], entry["subagent_calls"]) == (3, 2, 1)
    assert entry["tokens"]["all"] == {"input": 16, "cache_read": 350, "write_5m": 28,
                                      "write_1h": 30, "output": 20}
    assert entry["tokens"]["subagent"] == {"input": 2, "cache_read": 50, "write_5m": 8,
                                           "write_1h": 0, "output": 3}
    assert entry["units"] == {MODEL: {"all": 246.0, "main": 214.0, "subagent": 32.0}}
    assert entry["models"] == {MODEL: 3}
    assert entry["context"] == {"first": 130, "first_edit": 234, "peak": 234}
    assert entry["before_first_edit"] == {MODEL: pytest.approx(80 / 214)}
    assert entry["write_ttl_split"] is True
    assert entry["files"] == ["sess-a.jsonl", "sess-a/subagents/agent-1.jsonl"]
    assert result["total"] == {MODEL: {"calls": 3, "units": 246.0, "tokens": entry["tokens"]["all"]}}


def test_the_text_prints_the_same_figures(capsys, folder, prices):
    code, out, _ = run(capsys, folder, "--prices", prices)
    assert code == 0
    assert "session sess-a: 3 calls (2 main, 1 sub-agent)" in out
    assert f"units {MODEL} 246.00 (main 214.00, sub-agent 32.00)" in out
    assert "tokens    input 16  cache read 350  write 5m 28  write 1h 30  output 20" in out
    assert f"before first edit: {MODEL} 37.4%" in out
    assert "context first 130, first edit 234, peak 234" in out
    assert out.count("session ") == 1
    assert out.rstrip().endswith(f"{MODEL}: 3 calls  input 16  cache read 350  write 5m 28  "
                                 "write 1h 30  output 20  units 246.00")


def test_a_subagent_file_without_its_parent_shows_no_main_calls(capsys, folder, prices):
    result = run_json(capsys, folder / "sess-a" / "subagents", "--prices", prices)
    entry, = result["sessions"]
    assert (entry["session"], entry["main_calls"], entry["subagent_calls"]) == ("sess-a", 0, 1)
    assert entry["context"] == {"first": None, "first_edit": None, "peak": None}
    assert entry["before_first_edit"] == "no edit"


def test_a_subagent_file_without_a_session_id_joins_its_folder_session(tmp_path, capsys, prices):
    record = json.loads(assistant("msg-c", usage(1)))
    del record["sessionId"]
    write(tmp_path / "sess-z" / "subagents" / "agent-9.jsonl", [json.dumps(record)])
    entry, = run_json(capsys, tmp_path, "--prices", prices)["sessions"]
    assert (entry["session"], entry["subagent_calls"]) == ("sess-z", 1)


def test_an_unpriced_call_counts_in_tokens_and_its_units_read_unknown(tmp_path, capsys, prices):
    write(tmp_path / "s.jsonl", [assistant("x1", usage(5, output=2), model="m-other"),
                                 assistant("x2", usage(1, output=1), model=MODEL),
                                 assistant("x3", usage(1, output=1, speed="fast"), model=MODEL)])
    result = run_json(capsys, tmp_path, "--prices", prices)
    entry, = result["sessions"]
    assert entry["tokens"]["all"]["input"] == 7
    assert entry["units"]["m-other"]["all"] is None
    assert entry["units"][MODEL]["all"] is None  # its fast call has no row
    assert result["total"]["m-other"] == {"calls": 1, "units": None, "tokens": {
        "input": 5, "cache_read": 0, "write_5m": 0, "write_1h": 0, "output": 2}}
    _, out, _ = run(capsys, tmp_path, "--prices", prices)
    assert "units m-other unknown" in out


def test_a_file_without_usage_reads_no_usage_read(tmp_path, capsys, prices):
    write(tmp_path / "empty.jsonl", [user("hello")])
    write(tmp_path / "other-host.jsonl", [json.dumps({"kind": "turn", "tokens": 9})])
    result = run_json(capsys, tmp_path, "--prices", prices)
    assert result["sessions"] == [] and result["total"] == {}
    assert result["no_usage"] == ["empty.jsonl", "other-host.jsonl"]
    _, out, _ = run(capsys, tmp_path, "--prices", prices)
    assert "no usage read: empty.jsonl" in out and "no usage read: other-host.jsonl" in out


def test_synthetic_records_and_iterations_add_nothing(tmp_path, capsys, prices):
    nested = usage(3, output=1, iterations=[usage(100, output=100), usage(100, output=100)])
    write(tmp_path / "s.jsonl", [assistant("y1", nested),
                                 assistant("y2", usage(999, output=999), model="<synthetic>")])
    entry, = run_json(capsys, tmp_path, "--prices", prices)["sessions"]
    assert entry["calls"] == 1
    assert entry["tokens"]["all"]["input"] == 3 and entry["tokens"]["all"]["output"] == 1


def test_a_call_is_its_message_id_else_its_request_id_else_its_own(tmp_path, capsys, prices):
    write(tmp_path / "s.jsonl", [assistant(None, usage(1), request="req-1"),
                                 assistant(None, usage(2), request="req-1"),
                                 assistant(None, usage(1)), assistant(None, usage(1))])
    entry, = run_json(capsys, tmp_path, "--prices", prices)["sessions"]
    assert entry["calls"] == 3 and entry["tokens"]["all"]["input"] == 4


def test_a_write_without_the_ttl_split_counts_as_5_minutes(tmp_path, capsys, prices):
    write(tmp_path / "s.jsonl", [assistant("z1", usage(w5=40, split=False))])
    entry, = run_json(capsys, tmp_path, "--prices", prices)["sessions"]
    assert entry["tokens"]["all"]["write_5m"] == 40 and entry["write_ttl_split"] is False
    assert entry["units"][MODEL]["all"] == 50.0
    _, out, _ = run(capsys, tmp_path, "--prices", prices)
    assert "write TTL not split" in out


def test_a_call_over_above_tokens_takes_the_second_ratios(tmp_path, capsys, prices):
    write(tmp_path / "s.jsonl", [assistant("t1", usage(50, 50, output=1), model="m-tiered"),
                                 assistant("t2", usage(51, 50, output=1), model="m-tiered")])
    entry, = run_json(capsys, tmp_path, "--prices", prices)["sessions"]
    # t1: context 100, flat: 50 + 5 + 5 = 60; t2: context 101, above: 102 + 10 + 10 = 122
    assert entry["units"]["m-tiered"]["all"] == pytest.approx(182.0)


def test_the_share_before_the_first_edit_counts_main_calls_only(tmp_path, capsys, prices):
    write(tmp_path / "s.jsonl", [assistant("e1", usage(10)),
                                 assistant("e2", usage(30), tools=["Write"]),
                                 assistant("e3", usage(60), tools=["Edit"])])
    write(tmp_path / "s" / "subagents" / "agent-1.jsonl",
          [assistant("e0", usage(1000), sidechain=True)])
    write(tmp_path / "n.jsonl", [assistant("n1", usage(5), session="sess-n", tools=["Read"])])
    result = run_json(capsys, tmp_path, "--prices", prices)
    by_id = {entry["session"]: entry for entry in result["sessions"]}
    assert by_id["sess-a"]["before_first_edit"] == {MODEL: pytest.approx(0.1)}
    assert by_id["sess-a"]["context"]["first_edit"] == 30
    assert by_id["sess-n"]["before_first_edit"] == "no edit"
    assert [entry["session"] for entry in result["sessions"]] == ["sess-a", "sess-n"]
    _, out, _ = run(capsys, tmp_path, "--prices", prices)
    assert "before first edit: no edit" in out


def test_sessions_sort_by_their_main_model_units_unknown_last(tmp_path, capsys, prices):
    write(tmp_path / "a.jsonl", [assistant("a1", usage(5), session="s-low")])
    write(tmp_path / "b.jsonl", [assistant("b1", usage(50), session="s-high")])
    write(tmp_path / "c.jsonl", [assistant("c1", usage(500), session="s-unknown", model="m-none")])
    write(tmp_path / "d.jsonl", [assistant("d1", usage(5), session="s-alsolow")])
    result = run_json(capsys, tmp_path, "--prices", prices)
    assert [entry["session"] for entry in result["sessions"]] == [
        "s-high", "s-alsolow", "s-low", "s-unknown"]


def test_no_text_tool_input_or_outside_path_reaches_the_output(capsys, folder, prices):
    for args in ((folder, "--prices", prices), (folder, "--prices", prices, "--json")):
        _, out, _ = run(capsys, *args)
        assert MARKER not in out
        assert "/srv/outside" not in out and str(folder.parent) not in out


JSON_SESSION_KEYS = ["before_first_edit", "calls", "context", "files", "main_calls", "models",
                     "session", "subagent_calls", "tokens", "units", "write_ttl_split"]


def test_the_json_keys_are_pinned(capsys, folder, prices):
    result = run_json(capsys, folder, "--prices", prices)
    assert sorted(result) == ["no_usage", "sessions", "total"]
    entry = result["sessions"][0]
    assert sorted(entry) == JSON_SESSION_KEYS
    assert sorted(entry["tokens"]) == ["all", "main", "subagent"]
    assert sorted(entry["tokens"]["all"]) == sorted(cost.KINDS)
    assert sorted(entry["context"]) == ["first", "first_edit", "peak"]
    assert sorted(entry["units"][MODEL]) == ["all", "main", "subagent"]
    assert sorted(result["total"][MODEL]) == ["calls", "tokens", "units"]


def test_prices_replaces_the_table(capsys, folder, prices):
    shipped = run_json(capsys, folder)
    assert shipped["sessions"][0]["units"][MODEL]["all"] is None  # m-test is no shipped model
    assert run_json(capsys, folder, "--prices", prices)["sessions"][0]["units"][MODEL]["all"] == 246.0


def test_an_unreadable_path_or_prices_file_exits_2_naming_it(tmp_path, capsys, folder, prices):
    missing = tmp_path / "nowhere"
    code, out, err = run(capsys, missing)
    assert code == 2 and str(missing) in err and out == ""
    code, _, err = run(capsys, folder, "--prices", missing)
    assert code == 2 and str(missing) in err
    broken = write(tmp_path / "broken.toml", ["[[price]", "model ="])
    code, _, err = run(capsys, folder, "--prices", broken)
    assert code == 2 and str(broken) in err
    partial = write(tmp_path / "partial.toml", ['[[price]]', 'model = "m"', 'speed = "standard"'])
    code, _, err = run(capsys, folder, "--prices", partial)
    assert code == 2 and str(partial) in err


def test_every_shipped_row_names_its_source_and_date():
    assert cost.PRICES
    for row in cost.PRICES:
        assert row["source"] and row["date"]
        assert {kind for kind in cost.KINDS if kind in row} == set(cost.KINDS)
        if row["speed"] == "standard":
            assert row["input"] == 1
    keys = [(row["model"], row["speed"]) for row in cost.PRICES]
    assert len(keys) == len(set(keys))


def test_a_dated_model_id_takes_its_rows_price():
    assert cost.price_row(cost.PRICES, "claude-opus-4-20250514", "standard")["model"] == "claude-opus-4"
    assert cost.price_row(cost.PRICES, "claude-opus-4-9", "standard") is None


def test_nothing_calls_the_command():
    """Standalone: no hook, greeting, retro, gate or setting names it."""
    callers = [path.relative_to(PROJECT).as_posix()
               for folder in ("scripts", "components", "kern", "src")
               for path in (PROJECT / folder).rglob("*")
               if path.is_file() and path.suffix in (".py", ".go", ".md", ".sh", ".toml")
               and path.name != "session_cost.py"
               and "session_cost" in path.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
