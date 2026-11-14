"""The host size report (scripts/host_size.py): made-up files and limits in, rows out; off by default."""
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import host_size  # noqa: E402

FACTS = host_size.parse({
    "surfaces": {"cli": {"name": "A CLI", "instructions": ["AGENTS.md"], "agent": ["agents/*.md"],
                         "skill": ["skills/*/SKILL.md"], "reference": ["skills/*/references/*"]}},
    "limits": [
        {"surface": "cli", "subject": "agent-body", "value": 10, "unit": "characters", "mark": "documented"},
        {"surface": "cli", "subject": "skill-description", "value": 100, "unit": "characters", "mark": "measured"},
        {"surface": "cli", "subject": "skill-description", "value": 5, "unit": "tokens", "mark": "documented"},
        {"surface": "cli", "subject": "skill-length", "value": 4, "unit": "lines", "mark": "documented"},
        {"surface": "cli", "subject": "skill-length", "value": 1000, "unit": "bytes", "mark": "documented"},
        {"surface": "cli", "subject": "tool-name", "value": 8, "unit": "characters", "measures": "{server}-{tool}",
         "mark": "documented"},
    ]})
SKILL = "---\nname: probe\ndescription: 'Probes.'\n---\none\ntwo\nthree\n"
FILES = {"AGENTS.md": b"root\n", "agents/big.md": b"---\nname: big\n---\n" + b"x" * 11,
         "agents/small.md": b"---\nname: small\n---\nshort", "skills/probe/SKILL.md": SKILL.encode(),
         "skills/probe/references/more.md": b"r" * 50, "notes/unread.md": b"no host reads this"}


def rows(files=FILES, tools=None) -> dict[tuple[str, str], host_size.Row]:
    return {(row.item, row.subject): row for row in host_size.measure(files, FACTS, tools)}


def test_a_size_over_its_limit_is_over_and_one_under_is_under():
    found = rows()
    assert (found["agents/big.md", "agent-body"].status, found["agents/big.md", "agent-body"].size) == ("over", 11)
    assert (found["agents/small.md", "agent-body"].status, found["agents/small.md", "agent-body"].size) == ("under", 5)


def test_a_limit_the_data_lacks_is_not_measured_never_under():
    found = rows()
    for key in (("AGENTS.md", "instructions-file"), ("skills/probe/SKILL.md", "skill-name"),
                ("skills/probe/references/more.md", "reference-file")):
        assert (found[key].status, found[key].limit) == ("not measured", None)
    assert ("notes/unread.md", "reference-file") not in found


def test_a_limit_in_a_unit_that_cannot_be_counted_is_skipped_for_the_one_that_can():
    """Tokens are not counted: the description is judged against its 100 characters only."""
    row = rows()["skills/probe/SKILL.md", "skill-description"]
    assert (row.status, row.size, row.unit, row.limit.value) == ("under", 7, "characters", 100)
    only_tokens = host_size.parse({"surfaces": {"cli": {"skill": ["skills/*/SKILL.md"]}}, "limits": [
        {"surface": "cli", "subject": "skill-name", "value": 1, "unit": "tokens", "mark": "documented"}]})
    row = next(row for row in host_size.measure(FILES, only_tokens) if row.subject == "skill-name")
    assert (row.status, row.limit.unit) == ("not measured", "tokens")


def test_the_tightest_limit_is_the_one_the_size_takes_most_of():
    row = rows()["skills/probe/SKILL.md", "skill-length"]
    assert (row.status, row.size, row.unit, row.load) == ("over", 7, "lines", "on demand")


def test_a_tool_is_measured_by_its_description_and_by_the_name_the_host_builds():
    tools = host_size.tool_list({"jsonrpc": "2.0", "result": {"tools": [{"name": "status", "description": "d"}]}})
    found = rows(tools=tools)
    assert (found["tool status", "tool-name"].status, found["tool status", "tool-name"].size) == ("over", 9)
    assert found["tool status", "mcp-tool-description"].status == "not measured"
    assert host_size.tool_list({"tools": tools}) == tools == host_size.tool_list(tools)


def test_always_on_and_on_demand_bytes_are_summed_apart():
    tools = [{"name": "t"}]
    sums = {total.agent: total for total in host_size.totals(FILES, FACTS, tools)}
    listed = len("probe") + len("Probes.")
    shared = len(FILES["AGENTS.md"]) + listed + len(json.dumps(tools[0], separators=(",", ":")))
    assert sums["agents/big.md"].always == shared + len(FILES["agents/big.md"])
    assert sums["agents/small.md"].always == shared + len(FILES["agents/small.md"])
    on_demand = len(SKILL.encode()) - listed + len(FILES["skills/probe/references/more.md"])
    assert sums["agents/big.md"].on_demand == sums["agents/small.md"].on_demand == on_demand


def test_rows_come_in_a_stable_order_largest_overrun_first():
    first = host_size.measure(FILES, FACTS)
    again = host_size.measure(dict(reversed(list(FILES.items()))), FACTS)
    assert first == again
    statuses = [row.status for row in first]
    assert statuses == sorted(statuses, key=host_size.STATUSES.index)
    assert [(row.item, row.subject) for row in first[:2]] == [("skills/probe/SKILL.md", "skill-length"),
                                                              ("agents/big.md", "agent-body")]


def test_the_data_file_says_a_missing_limit_is_not_measured_and_every_row_names_its_source():
    text = host_size.DATA.read_text(encoding="utf-8")
    assert "A limit this file lacks is not measured" in text
    data = tomllib.loads(text)
    facts = host_size.parse(data)
    assert {surface.id for surface in facts.surfaces} == {"copilot-cli", "copilot-vscode", "copilot-github",
                                                          "claude-code"}
    for limit in facts.limits:
        assert limit.surface in data["surfaces"] and limit.mark in ("documented", "measured"), limit
        assert limit.source.startswith("https://") and limit.read, limit


def test_the_command_reads_any_root_writes_nothing_and_exits_0(tmp_path, capsys):
    for name, content in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(content)
    before = sorted(path.as_posix() for path in tmp_path.rglob("*"))
    assert host_size.main(["report", "--root", str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {row["item"] for row in report["rows"]} >= {"AGENTS.md", "agents/big.md", "skills/probe/SKILL.md"}
    assert host_size.main(["report", "--root", str(tmp_path), "--tools", str(tmp_path / "missing.json")]) == 0
    assert "nothing measured" in capsys.readouterr().out
    assert sorted(path.as_posix() for path in tmp_path.rglob("*")) == before


def test_nothing_in_se_calls_the_command():
    """Off by default: no hook, workflow, se.toml entry, build, check or generated layout names it."""
    places = [ROOT / "se.toml", ROOT / "wiring.toml", ROOT / ".claude-plugin" / "plugin.json",
              ROOT / "scripts" / "hygiene.py", ROOT / "scripts" / "se_plugin.py", ROOT / "scripts" / "agent_lint.py"]
    for folder in (".githooks", ".github/workflows", ".github/agents", ".github/skills", "agents", "skills"):
        places += [path for path in (ROOT / folder).rglob("*") if path.is_file()]
    assert len(places) > 10
    callers = [path.relative_to(ROOT).as_posix() for path in places
               if "host_size" in path.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
