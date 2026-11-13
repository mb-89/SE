"""SE's command groups as kern components, against kern's Python fake core (README "Commands as
components"): each group's declaration is what docs writes and its process answers its commands with
work_tickets.py's own code."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kern" / "python"))

import se_components  # noqa: E402
import work_tickets  # noqa: E402
from kern import KernError, runner  # noqa: E402
from kern.fake import Fake  # noqa: E402

GROUPS = [name for name, *_ in work_tickets.COMMAND_COMPONENTS]


def test_every_command_is_declared_once_and_the_wiring_places_every_group() -> None:
    declared = [name for d in se_components.catalog(ROOT, GROUPS) for name in d.commands]
    leaves = [" ".join(("work_tickets.py", *words)) for words, _ in work_tickets.leaf_commands()]
    assert sorted(declared) == sorted(leaves)
    wiring = (ROOT / "wiring.toml").read_text(encoding="utf-8")
    for group in GROUPS:
        assert f'[instances.{group}]\ncomponent = "{group}"\n' in wiring
        assert f'"scripts/se_components.py", "run", "{group}"]' in wiring


@pytest.fixture(scope="module")
def components() -> dict[str, Fake]:
    """Each group's component as its process loads it, on the fake core."""
    return {group: Fake(runner.load(ROOT / "components" / group)) for group in GROUPS}


def test_each_group_answers_its_commands_with_the_scripts_code(components, tmp_path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / ".git").mkdir(parents=True)
    cwd = se_components.CWD + str(worktree)

    # tickets: a write, then a read, in the directory the call names.
    tickets = components["tickets"]
    assert tickets.run("work_tickets.py init", cwd, "--worktree", ".") == (
        f"Initialized ticket queue in {worktree / '.se' / 'work'}")
    status = json.loads(tickets.run("work_tickets.py status", cwd, "--worktree", ".", "--json"))
    assert status["initialized"] is True

    # issues: the body read the cloud path records, from a file.
    body = tmp_path / "issue.json"
    body.write_text(json.dumps({"body": "## Requirements\n\n1. One.\n"}), encoding="utf-8")
    assert "body" in components["issues"].run(
        "work_tickets.py body-read", "--worktree", str(worktree), "--body-file", str(body))

    # delivery: a refusal keeps its exit code and what it said on each stream.
    with pytest.raises(KernError, match=r"\Aexit code 2\n") as refused:
        components["delivery"].run("work_tickets.py pr-body", "--no-such-flag")
    said = json.loads(str(refused.value).split("\n", 1)[1])
    assert said["stdout"] == "" and "work_tickets.py pr-body: error:" in said["stderr"]

    # integration: the command reference check, against this checkout.
    assert components["integration"].run("work_tickets.py docs", "--check") == (
        "README.md: the command reference is up to date")


def test_a_component_refuses_a_command_its_script_does_not_run(tmp_path) -> None:
    folder = tmp_path / "stray"
    folder.mkdir()
    (folder / "component.toml").write_text(se_components.declaration(
        "stray", "A stray.", "Stray", [se_components.Declared("review.py brief", "review.py brief",
                                                             "brief", False)], "a test"),
        encoding="utf-8")
    with pytest.raises(KernError, match="which work_tickets.py does not run"):
        se_components.attach("stray", "work_tickets", folder)


def test_docs_check_refuses_a_stale_declaration_and_docs_rewrites_it(tmp_path, monkeypatch,
                                                                     capsys) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"{work_tickets.REFERENCE_BEGIN}\n{work_tickets.REFERENCE_END}\n",
                      encoding="utf-8")
    monkeypatch.setattr(work_tickets, "README", readme)
    assert work_tickets.main(["docs"]) == 0
    declaration = tmp_path / "components" / "tickets" / "component.toml"
    declaration.write_text(declaration.read_text(encoding="utf-8").replace(
        "initialize the ticket queue", "stale"), encoding="utf-8")
    capsys.readouterr()

    assert work_tickets.main(["docs", "--check"]) == 1
    assert "components/tickets/component.toml" in capsys.readouterr().err
    assert work_tickets.main(["docs"]) == 0
    assert capsys.readouterr().out == "wrote components/tickets/component.toml\n"
    assert work_tickets.main(["docs", "--check"]) == 0
