"""SE's composite actions for a sharded suite (README "Test budget")."""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ACTIONS = sorted((PROJECT / ".github" / "actions").glob("*/action.yml"))
# The first major of each action they use that runs on Node 24 (its own action.yml, `using:`).
NODE_24 = {"actions/upload-artifact": 6, "actions/download-artifact": 7}


def test_the_actions_are_composite_and_use_only_node_24_actions():
    assert ACTIONS
    for path in ACTIONS:
        text = path.read_text(encoding="utf-8")
        assert "  using: composite\n" in text, path
        for action, major in re.findall(r"uses: ([\w.-]+/[\w.-]+)@v(\d+)", text):
            assert action in NODE_24, f"{path}: {action} is not in NODE_24; add its Node 24 major"
            assert int(major) >= NODE_24[action], f"{path}: {action}@v{major} runs on Node 20"
        assert "node20" not in text, path


def test_the_actions_run_python_unbuffered_so_their_output_stays_in_order():
    for path in ACTIONS:
        text = path.read_text(encoding="utf-8")
        assert text.count("python3 ") == text.count('PYTHONUNBUFFERED: "1"') == 1, path


def test_the_readme_states_the_actions_python_requirement_and_notice():
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    budget = readme[readme.index("### Test budget"):]
    budget = budget[:budget.index("\n### ", 1)]
    assert "Python 3.11 or later" in budget and "`tomllib`" in budget
    assert "Node 24" in budget
    assert ("`Suite time: 66.1 s (limit 120 s; slowest of 2 shards: 66.1 s (shard\n  1))`"
            in budget)
    assert "Where a shard failed, it prints no time" in budget
