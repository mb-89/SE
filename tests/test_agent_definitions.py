"""The role agent definitions exist, point to the work-model skill and are linked from the skills."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"
SOURCE = ROOT / "src"
AGENTS = SOURCE / "agents"
SKILL = SOURCE / "skills" / "catch-up" / "SKILL.md"
WORK_MODEL = SOURCE / "skills" / "work-model" / "SKILL.md"
DECISION = SOURCE / "skills" / "decision" / "SKILL.md"
RULE_BOOK = SOURCE / "skills" / "work-model" / "references" / "rules.md"
ROLES = ("se", "worker", "integrator", "reviewer")
# The authored prose: the agent and skill sources, the issue templates and the pull request template
# (generated layouts excluded).
# The field report's form, the pull request template.
REPORT_TEMPLATE = GITHUB / "pull_request_template.md"
PROSE = sorted([*SOURCE.rglob("*.md"), *(GITHUB / "ISSUE_TEMPLATE").glob("*.md"), REPORT_TEMPLATE])
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("role", ROLES)
def test_agent_definition_names_its_role_and_points_to_the_work_model(role):
    text = (AGENTS / f"{role}.md").read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert f"name: {role}" in front_matter and "description:" in front_matter
    assert "(../skills/work-model/SKILL.md)" in text


def test_worker_agent_tools_exclude_input_and_workspace_prompts():
    text = (GITHUB / "agents" / "worker.agent.md").read_text(encoding="utf-8")  # what Copilot reads
    front_matter = text.split("---")[1]
    assert "tools: ['execute', 'read', 'edit', 'search', 'send_message', 'se/*']" in front_matter
    assert "strict-tools-list: true" in front_matter
    assert "ask_user" not in front_matter
    assert "set_workspace" not in front_matter


@pytest.mark.parametrize("role", ("worker", "integrator", "reviewer"))
def test_non_se_agents_remove_workspace_switching_advice(role):
    text = (AGENTS / f"{role}.md").read_text(encoding="utf-8")
    assert "set_workspace if available" not in text


@pytest.mark.parametrize("path", [*(AGENTS / f"{role}.md" for role in ROLES), SKILL, WORK_MODEL, DECISION],
                         ids=lambda path: path.name)
def test_relative_links_resolve(path):
    text = path.read_text(encoding="utf-8")
    for target in LINK.findall(text):
        if "://" not in target:
            assert (path.parent / target).exists(), f"{path.name}: {target}"


def test_skill_links_every_agent_definition():
    text = SKILL.read_text(encoding="utf-8")
    for role in ROLES:
        assert f"(../../agents/{role}.md)" in text


@pytest.mark.parametrize("role", ("worker", "integrator", "reviewer"))
def test_non_se_roles_ban_input_prompts_and_escalate(role):
    text = normalized(AGENTS / f"{role}.md")
    assert "never call `ask_user`" in text.casefold()
    assert "`ask_user`" in text.casefold()
    assert "question, confirmation or approval prompt" in text
    assert "SE" in text


def test_only_se_talks_to_the_human():
    dispatcher = normalized(AGENTS / "se.md")
    assert "only session the human talks to" in dispatcher
    assert "only role that may ask the human with `ask_user`" in dispatcher
    for role in ("worker", "integrator", "reviewer"):
        assert "ask the human" not in normalized(AGENTS / f"{role}.md")
    rules = normalized(WORK_MODEL)
    assert "Only SE talks to the human" in rules
    assert "to the human at the top level" not in rules


def test_reviewer_finds_verifies_and_judges_in_order_and_files_one_comment():
    reviewer = normalized(AGENTS / "reviewer.md")
    steps = ["`review.py brief <n>`", "**The riskiest part first.**", "**Find, in two passes**",
             "**Verify each candidate**", "`review.py brief <n> --claims`",
             "**Judge each verified finding**", "`review.py file <n> --report <file>`"]
    positions = [reviewer.find(step) for step in steps]
    assert -1 not in positions and positions == sorted(positions), dict(zip(steps, positions))
    for rule in ("You never write the branch", "never waits for a human", "You file no issue",
                 "Your one output is the review comment `review.py file` posts",
                 "You run a model no weaker than the worker's"):
        assert rule in reviewer, rule
    front_matter = (AGENTS / "reviewer.md").read_text(encoding="utf-8").split("---")[1]
    assert "claude.model: inherit" in front_matter
    copilot = (GITHUB / "agents" / "reviewer.agent.md").read_text(encoding="utf-8").split("---")[1]
    assert "tools: ['execute', 'read', 'search', 'send_message', 'se/*']" in copilot  # no edit tool
    assert "strict-tools-list: true" in copilot


def test_se_starts_a_reviewer_on_request_and_the_integrator_does_not_wait_for_it():
    dispatcher = normalized(AGENTS / "se.md")
    assert 'on the person\'s request "review PR #n", start one [reviewer](reviewer.md) session' in dispatcher
    assert "never a weaker" in dispatcher
    assert "the integrator's procedure does not wait for it" in dispatcher
    assert "reviewer" not in normalized(AGENTS / "integrator.md")


def test_worker_instructions_require_utf8_file_writes_in_windows_powershell():
    worker = normalized(AGENTS / "worker.md")
    assert "powershell 5.1 redirection `>` writes utf-16" in worker.casefold()
    assert "[io.file]::writealltext" in worker.casefold()
    assert "out-file -encoding utf8" in worker.casefold()


def test_worker_requires_evidence_for_every_work_issue_item():
    worker = normalized(AGENTS / "worker.md")
    assert "every numbered requirement and every acceptance line" in worker
    assert "one quoted evidence line" in worker
    assert 'under "not delivered", never as a "decision"' in worker.casefold()


def test_integrator_restarts_only_workers_whose_events_show_a_prompt():
    integrator = normalized(AGENTS / "integrator.md")
    assert "inputneeded" not in integrator.casefold()
    assert 'reads as idle or "review ready" before its first turn' in integrator
    assert "stuck only when its events show it waiting on a prompt" in integrator
    assert "delete it and start it again in its worktree" in integrator


def test_partial_deliveries_define_blockers_and_review_responses():
    rules = normalized(WORK_MODEL)
    report = normalized(REPORT_TEMPLATE)
    assert "A partial-delivery blocker is only work outside the worker's box" in rules
    assert "tests of the package's own code are never blockers" in rules.casefold()
    assert "throw-away tracker issues for live acceptance runs" in rules
    assert "Deleting or condensing authored content is recorded in the field report" in rules
    assert "## Review responses" in report
    assert "answers every review point" in report
    assert "## Removed behaviour, deleted or weakened tests, and authored prose" in report
    assert "(skills/work-model/SKILL.md#rules-for-all-roles)" in report


def test_field_report_template_has_requirement_evidence_table():
    report = normalized(REPORT_TEMPLATE)
    assert "one row per work-issue requirement and acceptance item" in report
    assert 'numbered items under "Changes after filing" are requirements, by their number' in report
    assert "| Work issue item | Result | Commits | Evidence |" in report
    assert "(agents/worker.agent.md#procedure)" in report


def test_field_report_template_names_the_integration_branch_it_was_tested_against():
    report = normalized(REPORT_TEMPLATE)
    assert "**Tested against `<integration branch>`:** `<commit>`" in report
    assert "Tested against main" not in report


def test_work_issue_template_asks_for_the_field_reports_reproduction():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert "## Reproduction" in template
    assert "quote the reproduction command it ran and that command's output" in template


def test_worker_commit_rule_names_its_groupings_and_has_one_owner():
    worker = normalized(AGENTS / "worker.md")
    assert "requirements that change one function together share one commit" in worker
    assert "its test may be a test-only commit" in worker
    assert "The field report names each such grouping" in worker
    owners = [path.relative_to(ROOT).as_posix() for path in PROSE
              if "one commit per" in normalized(path).casefold()]
    assert owners == ["src/agents/worker.md"]


def test_work_issue_template_says_how_to_name_a_design_owner_not_yet_written():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    section = template.split("## Design owner", 1)[1].split("## Requirements", 1)[0]
    assert 'write "none yet: create it at <path>", so the worker knows to create it there' in section


def test_work_model_tests_leave_the_worktree_alone_while_the_complete_suite_runs():
    tests = normalized(WORK_MODEL).split("## Tests", 1)[1].split(" ## ", 1)[0]
    assert "Leave the worktree alone while the complete suite runs" in tests


def test_work_issue_template_assigns_shared_root_file_owners():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert "pyproject.toml" in template
    assert "lock files" in template
    assert "ci config" in template.casefold()


@pytest.mark.parametrize("rule", (
    "judge native commands by exit code only",
    "never take a default on the user's behalf",
    "Packages are worker-sized",
))
def test_shared_rules_have_one_owner(rule):
    owners = [path.relative_to(ROOT).as_posix() for path in PROSE
              if rule.casefold() in normalized(path).casefold()]
    assert len(owners) == 1, owners


def test_se_can_dispatch_anywhere_without_writing_repositories():
    rule = "SE never writes any repository"
    owners = [path.relative_to(ROOT).as_posix() for path in PROSE
              if rule.casefold() in normalized(path).casefold()]
    assert owners == ["src/skills/work-model/SKILL.md"]
    rules = normalized(WORK_MODEL)
    assert "may file work issues for and dispatch into any repository" in rules
    assert "Each repository has exactly one integrator" in rules
    assert "The integrator starts that repository's workers" in rules


def test_catch_up_starts_integrators_not_workers():
    catch_up = normalized(SKILL)
    assert "If none runs, start one with the prompt" in catch_up
    assert "naming the integrator agent, the repository and this SE session" in catch_up
    assert "Never start workers directly" in catch_up


def test_se_and_catch_up_link_to_the_shared_dispatch_rule():
    dispatcher = (AGENTS / "se.md").read_text(encoding="utf-8")
    catch_up = SKILL.read_text(encoding="utf-8")
    assert "(../skills/work-model/SKILL.md#roles-and-flow)" in dispatcher
    assert "(../work-model/SKILL.md#roles-and-flow)" in catch_up


def test_outside_issue_routine_and_consistency_item_link_the_rule_book():
    assert "SE's [rule book](../skills/work-model/references/rules.md)" in normalized(
        AGENTS / "se.md")
    assert ("**Consistency:** [dec-009](../work-model/references/rules.md#dec-009-consistency)"
            in normalized(DECISION))
    assert "A decision names the rule or earlier decision it contradicts and the one it replaces." in (
        normalized(RULE_BOOK))


MARKDOWN = PROSE
ANCHOR_LINK = re.compile(r"\]\(([^)\s]*)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def anchors(path: Path) -> set[str]:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces become hyphens."""
    return {re.sub(r"[^\w\- ]", "", heading.strip().casefold()).replace(" ", "-")
            for heading in HEADING.findall(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_every_process_link_and_anchor_resolves(path):
    for link in ANCHOR_LINK.findall(path.read_text(encoding="utf-8")):
        if "://" in link or not link:
            continue
        target, _, anchor = link.partition("#")
        resolved = (path.parent / target).resolve() if target else path
        assert resolved.exists(), f"{link}: missing target"
        if anchor:
            assert resolved.is_file() and anchor in anchors(resolved), f"{link}: missing anchor"


# Hosts a project-neutral process may name: public services and reserved example names.
PUBLIC_HOSTS = ("github.com", "pypi.org", "pythonhosted.org", "example.com", "example.org",
                "example.net")
RESERVED_SUFFIXES = (".example", ".invalid", ".test", ".localhost")
URL_HOST = re.compile(r"\b[a-z][a-z0-9+.-]*://(?:[^\s/@]*@)?([^\s/:'\"`)>\]]+)", re.IGNORECASE)
BARE_HOST = re.compile(
    r"(?<![\w.-])((?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|de|cloud|corp|internal|intra|lan|local))\b",
    re.IGNORECASE)
LOCAL_PATH = re.compile(r"(?<![\w$%])[a-z]:[\\/]+[\w.~-]|(?<![\w.~-])/(?:home|Users)/[\w.-]",
                        re.IGNORECASE)
CONCRETE_REPO = re.compile(r"--repo\s+(?![<\[{]|REPO\b)\S")


def public_host(host: str) -> bool:
    host = host.casefold().rstrip(".")
    return (host == "example" or host.endswith(RESERVED_SUFFIXES)
            or any(host == public or host.endswith("." + public) for public in PUBLIC_HOSTS))


def neutrality_problems(name: str, text: str) -> list[str]:
    problems = [f"host {host}" for pattern in (URL_HOST, BARE_HOST)
                for host in pattern.findall(text) if not public_host(host)]
    problems += [f"local path at offset {match.start()}" for match in LOCAL_PATH.finditer(text)]
    if name.endswith(".md"):
        problems += [f"concrete --repo at offset {match.start()}"
                     for match in CONCRETE_REPO.finditer(text)]
    return problems


PROCESS_FILES = [*MARKDOWN, ROOT / "scripts" / "work_tickets.py",
                 *sorted((ROOT / "tests").glob("test_work_ticket*.py")), Path(__file__).resolve()]


@pytest.mark.parametrize("path", PROCESS_FILES, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_process_files_name_no_project_host_or_local_path(path):
    # Project and person names are the public check's local list; this test
    # covers what can be recognised without one.
    assert neutrality_problems(path.name, path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(("name", "text"), [
    # Escaped so that this file, which scans itself, holds no literal sample.
    ("a.md", "gh issue view 5 --repo tracker\u002ecorp\u002enet/team/app"),
    ("a.md", "see https\u003a//git\u002eintra/owner/repo/issues/1"),
    ("a.md", "gh issue list --repo team/app"),
    ("a.py", "ROOT = 'D\u003a\\src\\app'"),
    ("a.py", "HOME = '\u002fhome/someone/app'"),
])
def test_neutrality_check_flags_hosts_paths_and_concrete_repositories(name, text):
    assert neutrality_problems(name, text)


def test_neutrality_check_accepts_public_and_placeholder_names():
    text = ("gh issue create --repo <host>/<owner>/<repo>; https://git.example/owner/repo; "
            "git@git.example:owner/repo; 223556219+Copilot@users.noreply.github.com; "
            "https://pypi.org/simple")
    assert neutrality_problems("a.md", text) == []


@pytest.mark.parametrize("role", ("worker", "integrator"))
def test_roles_say_integration_branch_and_link_its_owner(role):
    text = normalized(AGENTS / f"{role}.md")
    assert "integration branch" in text
    assert "(../skills/work-model/SKILL.md#integration-branch)" in text
    assert "`main`" not in text.replace("`main` unless the project names another", "")


def test_work_model_owns_the_integration_branch_setting():
    text = normalized(WORK_MODEL)
    assert "## Integration branch" in text
    assert 'integration_branch = "next"' in text and "It is `main` unless" in text


def test_messages_travel_only_up_and_down_the_tree():
    rule = normalized(WORK_MODEL)
    assert "**Messages travel only up and down the tree**" in rule
    assert "news for another repository goes up to SE" in rule
    integrator = normalized(AGENTS / "integrator.md")
    assert "(../skills/work-model/SKILL.md#roles-and-flow)" in integrator
    assert "never another repository's integrator" in integrator


def test_the_comment_footer_rule_is_said_once():
    assert "**Comments carry the host's footer**" in normalized(WORK_MODEL)
    for path in (*(AGENTS / f"{role}.md" for role in ROLES), SKILL):
        assert "footer" not in normalized(path), path.name


def test_integrator_leaves_a_branch_the_host_refuses_to_delete():
    integrator = normalized(AGENTS / "integrator.md")
    assert "automatic head-branch deletion removes it. Never retry the deletion." in integrator


def test_the_commit_trailer_is_one_setting_the_roles_point_to():
    assert 'commit_trailer = "<trailer line>" # optional; none by default' in WORK_MODEL.read_text(
        encoding="utf-8")
    for path in (*(AGENTS / f"{role}.md" for role in ROLES), SKILL):
        text = normalized(path)
        assert "Co-authored-by" not in text, path.name
    for path in (AGENTS / "worker.md", SKILL):
        assert "`commit_trailer`](" in normalized(path), path.name


def test_one_skill_owns_how_a_decision_is_presented():
    assert "name: decision" in DECISION.read_text(encoding="utf-8").split("---")[1]
    pointers = {AGENTS / "se.md": "(../skills/decision/SKILL.md)",
                SKILL: "(../decision/SKILL.md)"}
    for path, link in pointers.items():
        text = normalized(path)
        assert link in text, path.name
        for restated in ("What we gain", "Decision 2 of", "Reply A", "one at a time", "one level up"):
            assert restated.casefold() not in text.casefold(), (path.name, restated)


def test_the_decision_skill_owns_the_shape_of_the_decision_note():
    text = normalized(DECISION)
    for rule in ("## The decision note", "One Obsidian Markdown note per decision", "`obs: {bless: pending}`",
                 "**`## Current situation`:**", "**`## The problem`:**", "Nothing else goes before the fence",
                 "The `pugh` fence", "The datum is the strongest rival",
                 '"Keep what we have" is an option', "the letters of those it fails",
                 "## Tasks for the person", "never an option in a decision", '"Task 1 of 2"'):
        assert rule in text, rule


def test_the_decision_skill_points_to_obs_for_the_fence_contract_and_restates_none_of_it():
    text = normalized(DECISION)
    assert "(https://github.com/mb-89/obs/blob/main/spec/capabilities/pugh-decisions.md)" in text
    for restated in ("`criteria`", "`candidates`", "`datum`", "`marks`", "`what`", "`wins`", "`item`",
                     "`answer`", "`pass`", "`checklistWeight`", "`-1` worse", "second tab"):
        assert restated not in text, restated


def test_the_agent_decides_its_own_questions_with_the_same_note():
    text = normalized(DECISION)
    assert "## Your own decisions" in text
    for rule in ("same note", "sets `chosen`", "the world that choice needs", "If that world is nonsense"):
        assert rule in text, rule


def test_the_decision_skill_asks_one_level_up_with_the_worked_example():
    text = normalized(DECISION)
    assert "## One level up" in text
    assert "name the class the instance belongs to and decide the general mechanism" in text
    assert '"can queries select the manifest note?"' in text
    assert ('"a note can mark itself ignored, like a Python underscore name; the manifest is one '
            'such note"') in text


def test_the_decision_skill_outputs_the_answered_artifact_and_names_no_storage():
    text = normalized(DECISION)
    assert "## The record" in text
    for rule in ("The skill's output is the answered artifact", "verdict, comments, overrides and vetoes",
                 "That artifact is the decision's record", "an issue may carry it as an attachment",
                 "nothing is required to commit it"):
        assert rule in text, rule
    for storage in ("decisions/", "stored together", "folder", "graft"):
        assert storage not in text, storage


def without_gh_section() -> str:
    text = WORK_MODEL.read_text(encoding="utf-8")
    return text.split("### Without gh", 1)[1].split(" ## ", 1)[0]


def commands_that_need_no_gh() -> set[str]:
    """Commands of work_tickets.py whose registered handlers never reach run_gh."""
    import ast
    import importlib.util
    import sys

    script = ROOT / "scripts" / "work_tickets.py"
    spec = importlib.util.spec_from_file_location("work_tickets_commands", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tree = ast.parse(script.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def called(node: ast.AST) -> set[str]:
        return {call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}

    # A class reaches gh when one of its methods, or a base class, does: calling it opens a door.
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    bases = {name: {base.id for base in node.bases if isinstance(base, ast.Name)}
             for name, node in classes.items()}
    callables = {**functions, **classes}
    reaches_gh = {"run_gh"}
    grown = True
    while grown:
        grown = False
        for name, node in callables.items():
            if name not in reaches_gh and (called(node) | bases.get(name, set())) & reaches_gh:
                reaches_gh.add(name)
                grown = True
    commands: set[str] = set()
    needs_gh: set[str] = set()
    for words, command in module.leaf_commands():
        commands.add(words[0])
        if command.handler.__name__ in reaches_gh:
            needs_gh.add(words[0])
    return commands - needs_gh


def test_the_work_model_owns_without_gh_and_lists_the_commands_that_still_run():
    section = without_gh_section()
    line = next(line for line in section.split("\n- ") if line.startswith("**Commands that still run**"))
    listed = set(re.findall(r"`([a-z-]+)`", line.split("Every other command")[0]))
    assert listed == commands_that_need_no_gh()
    assert "the host's GitHub tools" in section
    assert "naming itself, the missing `gh` and this section" in " ".join(section.split())


def test_without_gh_spells_out_the_field_report_draft_with_its_worktree():
    section = " ".join(without_gh_section().split())
    assert ("`field-report --draft .se/work/field-report.md --worktree <worktree> --issue-body "
            "<file>`" in section)


def test_without_gh_names_what_the_session_prompt_still_carries_and_nothing_else():
    section = without_gh_section()
    assert ("**The session prompt carries only** the agent, the work issue, the branch"
            in " ".join(section.split()))
    prompt = section.split("```text", 1)[1].split("```", 1)[0]
    keys = [line.strip().split(":", 1)[0] for line in prompt.strip().splitlines()]
    assert keys == ["Act as the worker agent defined in <se>/.github/agents/worker.agent.md (read it first, plus the project's AGENTS.md).",
                    "Work issue", "Branch", "Integrator session to notify at delivery"]


def claude_text(path: Path) -> str:
    """A source as the Claude layout carries it: its Copilot-only parts dropped (se_plugin.py
    `hosts`), whitespace normalized."""
    text = re.sub(r"(?ms)^<!-- copilot -->\n.*?^<!-- /copilot -->\n", "", path.read_text(encoding="utf-8"))
    return " ".join(text.split())


@pytest.mark.parametrize("role", ("worker", "integrator"))
def test_roles_point_to_without_gh_and_do_not_restate_it(role):
    """The Claude layout's role text; under Copilot the role names SE's MCP tools, which the work
    model's Host procedure under Copilot owns (the next test)."""
    text = claude_text(AGENTS / f"{role}.md")
    assert "(../skills/work-model/SKILL.md#without-gh)" in text
    for owned in ("Commands that still run", "GitHub tools", "MCP", "outcome branch",
                  "carries only", "`review-note`, `probe`"):
        assert owned not in text, owned


@pytest.mark.parametrize("role", ("worker", "integrator", "reviewer", "se"))
def test_under_copilot_each_role_names_ses_mcp_tools_and_points_to_the_host_procedure(role):
    text = normalized(ROOT / ".github" / "agents" / f"{role}.agent.md")
    assert "MCP tools" in text
    assert "/.github/skills/work-model/SKILL.md#host-procedure-under-copilot)" in text
    assert "Host procedure under Copilot" not in claude_text(AGENTS / f"{role}.md")
    assert "MCP" not in normalized(ROOT / "agents" / f"{role}.md").replace("GitHub MCP", "")


@pytest.mark.parametrize("role", ("worker", "reviewer"))
def test_the_strict_tool_lists_gain_the_se_server_under_copilot_only(role):
    copilot = (ROOT / ".github" / "agents" / f"{role}.agent.md").read_text(encoding="utf-8").split("\n---\n")[0]
    assert "'se/*']" in copilot and "strict-tools-list: true" in copilot
    assert "se/*" not in (ROOT / "agents" / f"{role}.md").read_text(encoding="utf-8")


def host_procedure() -> str:
    text = normalized(ROOT / ".github" / "skills" / "work-model" / "SKILL.md")
    return text.split("## Host procedure under Copilot", 1)[1]


def test_the_host_procedure_is_in_the_copilot_layout_only():
    """The Claude text stays as it is: tests/test_se_plugin.py holds its layout byte for byte."""
    assert "## Host procedure under Copilot" in normalized(ROOT / ".github" / "skills" / "work-model" / "SKILL.md")
    assert "Host procedure under Copilot" not in normalized(ROOT / "skills" / "work-model" / "SKILL.md")


def test_the_host_procedure_branches_on_the_tools_the_session_has():
    section = host_procedure()
    assert "It branches on the tools the session has, never on the host's name or its layout." in section
    assert ("**Starting a session, where the host has a session tool** (`create_session`): use it" in section
            and "`send_message` for the one message a role sends" in section)
    assert ("nohup copilot -C <worktree> --agent worker --trust-folder --no-ask-user --allow-tool=<list> "
            "\\ -n <branch> -p '<prompt>' > <worktree>/.se/worker.log 2>&1 &") in section
    assert "Windows: `Start-Process copilot -ArgumentList '-C','<worktree>','--agent','worker'," in section
    assert "-RedirectStandardOutput <worktree>\\.se\\worker.log -WindowStyle Hidden`" in section
    assert "give the person that one line to run" in section
    assert "**No message tool**: read the queue at each turn (`work_tickets.py queue`)" in section
    assert "**No ask tool** (`ask_user`): SE asks the person in the chat" in section
    assert "Out of scope: the Copilot cloud agent, and VS Code's Claude and Local harnesses." in section


def test_the_host_procedure_uses_the_se_tools_where_present_and_the_scripts_otherwise():
    section = host_procedure()
    for tool in ("se/status", "se/greeting", "se/tickets", "se/integration", "se/overhaul"):
        assert f"`{tool}`" in section, tool
    assert "or the session has no `se` tools, run the same command as its script" in section
    assert "A command no tool offers, every one that writes among them, always runs as its script." in section
    assert "the greeting then says `SE runs without kern`, and so does SE in its first message" in section


def test_agents_md_names_the_focused_and_complete_test_commands():
    text = normalized(ROOT / "AGENTS.md")
    tests = text.split("## Tests", 1)[1].split(" ## ", 1)[0]
    assert "Focused: `uv run pytest -q tests/<file>.py`" in tests
    assert "Complete: `uv run pytest -q`" in tests


def test_the_work_model_owns_where_the_commit_identity_and_the_public_check_come_from():
    provides = normalized(WORK_MODEL).split("## What the project provides", 1)[1]
    assert ("**Commit identity and public check** "
            "([pub-002](references/rules.md#pub-002-a-generic-commit-identity)): every role commits as "
            "`public_identity`") in provides
    assert "else as the project's `identity` in its `se.toml`" in provides
    assert "`work_tickets.py sync`, which every role runs at the start, writes whichever applies" in provides
    assert "runs the project's setup command before its first commit" in provides
    assert "else the project's `identity` (`mb <mb>` for se), and never a real e-mail address" in normalized(
        RULE_BOOK)
    assert "[pub-002](src/skills/work-model/references/rules.md#pub-002-a-generic-commit-identity)" in normalized(
        ROOT / "AGENTS.md")
    assert "[commit identity](../skills/work-model/SKILL.md#what-the-project-provides)" in normalized(
        AGENTS / "worker.md")


def test_the_worker_commits_each_requirement_while_working():
    worker = normalized(AGENTS / "worker.md")
    assert "Commit each requirement as soon as it is done, while working; never reconstruct commits at the end." in worker


def test_the_work_template_asks_a_requirement_over_a_set_to_list_each_member_by_file():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert ('A requirement over a set lists every member by file: each implementation of "both evaluators" '
            'or "all adapters", which ones are in scope (whether an interim implementation counts), and, '
            "in a package that moves code, the source tests it carries, each marked where it needs a "
            "capability outside the package.") in template
    assert '"adapters" or "consumers" must do' not in template


CLOUD_RULES = (
    "**Never `add_repo`**: the host's tool that attaches a repository stops the session at an approval prompt",
    "**Commit trailers**: the project's [`commit_trailer`](#what-the-project-provides) wins over a host's "
    "attribution reminder; with none set, commits carry no trailer.",
    "**Other process files**: where a host loads other instructions (an old plugin, another branch's "
    "`CLAUDE.md`), the role files and the project's `AGENTS.md` on the integration branch are the rules.",
    "**Retries after a server error**: after a 5xx from GitHub, read before retrying any write, not only a "
    "create (the object may exist); where closing with a state reason fails, close without one",
    "**Delivery fallback**: where the pull request cannot be opened with the report as its description after "
    "those retries, open it with the closing line alone, then write the full description (`pr-body`'s output) by "
    "editing the pull request; the delivery notice names the pull request.",
)


@pytest.mark.parametrize("rule", CLOUD_RULES, ids=lambda rule: rule.split("**")[1])
def test_the_cloud_section_holds_each_cloud_rule_once(rule):
    assert " ".join(without_gh_section().split()).count(rule) == 1
    assert normalized(WORK_MODEL).count(rule.split("**")[1]) == 1
    for path in (*(AGENTS / f"{role}.md" for role in ROLES), SKILL):
        assert rule.split("**")[1] not in normalized(path), path.name


def test_the_worker_installs_the_hooks_before_its_first_commit():
    worker = normalized(AGENTS / "worker.md")
    procedure = worker.split("## Procedure", 1)[1]
    setup = procedure.index("in a fresh clone, first run the project's setup command that installs its hooks")
    assert setup < procedure.index("`work_tickets.py sync`") < procedure.index("commit as the work model's")
    assert "[public check](../skills/work-model/SKILL.md#what-the-project-provides) runs on every commit and push" in worker
    assert "`scripts/setup.sh`" in " ".join(normalized(ROOT / "AGENTS.md").split("## Public safety", 1)[1].split())


def test_the_worker_runs_what_the_acceptance_names_including_the_suite():
    worker = normalized(AGENTS / "worker.md")
    assert "Never run the complete suite" not in worker
    assert "run the complete suite only where the acceptance names it, otherwise the integrator does" in worker
    rules = normalized(WORK_MODEL)
    assert "Workers run focused tests only" not in rules
    assert "the complete suite only where it names the suite" in rules


def test_the_work_template_checks_that_acceptance_on_existing_content_is_measurable():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert ("An item that measures something that exists already (the project's own content, a figure, a count) "
            "is checked against that content and the pinned versions before it is written, so it can be "
            "measured at all.") in template


def test_the_field_report_has_a_fixed_line_for_commit_groupings_under_delivered():
    report = normalized(REPORT_TEMPLATE)
    delivered = report.split("## Delivered", 1)[1].split("## Not delivered", 1)[0]
    assert "**Commit groupings:** None <!-- or, per grouping the worker's commit rule allows" in delivered


def test_the_field_report_replaces_evidence_the_host_cannot_carry_with_its_command():
    report = normalized(REPORT_TEMPLATE)
    assert ("Evidence the host cannot carry is replaced by the command that reproduces it: where images cannot "
            "be attached, each screenshot's row names the command that takes it again.") in report


def test_the_work_model_waits_on_a_background_process_by_its_id():
    shell = normalized(WORK_MODEL).split("## Commands and shell", 1)[1]
    assert "Wait on a background process by its process id (`kill -0 <pid>`" in shell
    assert "never by `pgrep -f <pattern>`" in shell


def test_the_worker_builds_an_acceptance_build_at_the_new_pin_before_code():
    worker = normalized(AGENTS / "worker.md")
    assert "where the acceptance names a real build" in worker
    assert "build it at that pin before writing code" in worker


def test_the_worker_may_work_without_the_ticket_queue_where_the_host_refuses_it():
    worker = normalized(AGENTS / "worker.md")
    assert ("Where the host refuses the local ticket queue (`work_tickets.py init`, `create`, `move`, "
            "`status`), it is optional: work without it and say so in the field report.") in worker


def test_the_worker_runs_the_affected_real_command_once_against_the_real_service():
    worker = normalized(AGENTS / "worker.md")
    procedure = worker.split("## Procedure", 1)[1]
    step = procedure.split("4. **Work the ticket**", 1)[1].split("5. **Deliver", 1)[0]
    assert ("Where the container allows it, run the affected real command once against the real outside "
            "service, not only against its fake: only the real call shows what the service refuses.") in step


def test_the_suite_runs_at_a_moved_pin_before_the_change_for_worker_and_integrator():
    rule = ("When the acceptance names the complete suite and a dependency pin moves, the suite runs at the "
            "new pin before the change, so failures that exist already are told apart from the change's own.")
    assert normalized(WORK_MODEL).count(rule) == 1
    for role in ("worker", "integrator"):
        text = normalized(AGENTS / f"{role}.md")
        assert rule not in text
        assert "[suite at a moved pin](../skills/work-model/SKILL.md#suite-at-a-moved-pin)" in text


def test_the_work_model_tells_issue_writers_what_renames_and_docs_issues_name():
    rules = normalized(WORK_MODEL).split("## Rules for all roles", 1)[1]
    assert ("**Writing work issues**: - an issue that renames an identifier says whether the code emits it or "
            "only documents it; - a docs issue that asks to point instead of restating quotes the text to "
            "replace and names each note by its repository path; - a docs requirement names the test file "
            "its regression test belongs in; - content a worker needs from another repository (a list, a "
            "decision, a spec passage) is quoted inline with its source named, because a cloud worker reads "
            "only its own repository: a cross-repository link is never the only copy (`intake` warns on one "
            "with no quoted block next to it).") in rules


def test_the_integrator_reconciles_from_github_and_treats_a_missing_message_as_late():
    integrator = normalized(AGENTS / "integrator.md")
    assert ("A worker's delivery message can arrive minutes late, or never where the worker's prompt named no "
            "integrator: reconcile from GitHub first (`queue`) and treat a missing message as late, not lost."
            ) in integrator


TEST_RULES = (
    "at the outermost interface",
    "on fakes",
    "No sleeping",
    "no wall clock",
    "in parallel",
    "fixtures are built once",
    "Browser checks are batched",
)


def test_the_work_model_states_the_test_rules_once_and_issues_point_to_it():
    section = normalized(WORK_MODEL).split("## Tests", 1)[1].split(" ## ", 1)[0]
    for rule in TEST_RULES:
        assert rule in section, rule
    for path in PROSE:
        if path != WORK_MODEL:
            assert "Browser checks are batched" not in normalized(path), path
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert "(../skills/work-model/SKILL.md#tests)" in template


def test_the_worker_reports_the_suite_time_before_and_after_and_slow_new_tests():
    worker = normalized(AGENTS / "worker.md")
    assert "(../skills/work-model/SKILL.md#tests)" in worker
    assert "work_tickets.py suite" in worker
    template = normalized(REPORT_TEMPLATE)
    assert "**Suite time:**" in template



def test_the_worker_delivery_measures_not_slower_with_one_command():
    delivery = normalized(AGENTS / "worker.md").split("5. **Deliver", 1)[1].split("\n6. ", 1)[0]
    assert ('Where the issue asks for "not slower", run `work_tickets.py suite --compare <integration '
            'branch>` and quote its verdict line in the evidence table.') in delivery
    assert "interleav" not in delivery

CHECKLIST = ("Class or case", "Is the problem real", "Keep what we have", "A named loser", "Fair criteria",
             "Right before cheap", "What if", "Undo cost", "Consistency")
LADDER = ("worker, then integrator", "One rank at a time", "One level per loop",
          "Marked for the person", "as a deck, not as issues")
POINTERS = {AGENTS / "se.md": "(../skills/work-model/SKILL.md#escalation-ladder)",
            AGENTS / "worker.md": "(../skills/work-model/SKILL.md#escalation-ladder)",
            AGENTS / "integrator.md": "(../skills/work-model/SKILL.md#escalation-ladder)",
            SKILL: "(../work-model/SKILL.md#escalation-ladder)"}


def test_the_decision_skill_names_the_nine_checklist_items():
    text = DECISION.read_text(encoding="utf-8")
    checklist = text.split("## The checklist", 1)[1].split(" ## ", 1)[0]
    items = re.findall(r"^\d+\. \*\*(.+?):\*\*", checklist, re.MULTILINE)
    assert items == list(CHECKLIST)


def test_the_worked_example_is_a_chapter_of_the_documentation_obs_builds():
    manifest = (ROOT / "docs.md").read_text(encoding="utf-8")
    assert "[[src/skills/decision/references/decision-deck|" in manifest


def test_the_worked_example_answers_every_checklist_item_in_its_fence():
    note = (DECISION.parent / "references" / "decision-deck.md").read_text(encoding="utf-8")
    assert note.startswith("---\nobs: {bless: pending}\n---\n")
    fence = note.split("```pugh\n", 1)[1].split("```", 1)[0]
    assert re.findall(r"^  - item: (.+)$", fence, re.MULTILINE) == list(CHECKLIST)
    assert "datum: {prefer: [chat]}" in fence and "(keep what we have)" in fence
    for key in ("candidates:", "label:", "what:", "marks:", "wins:", "losses:", "answer:", "pass:"):
        assert key in fence, key
    candidates = fence.split("candidates:\n", 1)[1].split("checklist:", 1)[0]
    shorts = re.findall(r"^    short: (.+)$", candidates, re.MULTILINE)
    assert len(shorts) == len(re.findall(r"^  - key: ", candidates, re.MULTILINE)) == 3
    assert all(len(short.split()) == 1 for short in shorts), shorts


def test_the_decision_skill_asks_every_option_for_a_short_name_and_points_to_obs_for_the_field():
    text = normalized(DECISION)
    assert "Every option carries `short`" in text and "one word where possible, at most five" in text
    assert "(https://github.com/mb-89/obs/blob/main/spec/capabilities/pugh-decisions.md)" in text


@pytest.mark.parametrize("path", POINTERS, ids=lambda path: path.name)
def test_roles_point_to_the_checklist_and_the_ladder_rather_than_restating_them(path):
    text = normalized(path)
    assert POINTERS[path] in text
    for restated in (*(f"**{item}:**" for item in CHECKLIST), "named loser", "tripwire", *LADDER):
        assert restated.casefold() not in text.casefold(), restated


def test_the_work_model_owns_the_escalation_ladder():
    text = normalized(WORK_MODEL)
    assert "## Escalation ladder" in text
    for rule in ("Issues carry work between boxes", "worker, then integrator (integrators may nest",
                 "then SE, then person", *LADDER[1:], "allowed, not preferred",
                 "(../decision/SKILL.md)"):
        assert rule in text, rule
    assert "one table per message" not in text.casefold()


def test_the_outside_issue_routine_is_stated_once_in_the_se_agent():
    se = AGENTS / "se.md"
    owners = [path for path in PROSE if "<!-- se:handled -->" in normalized(path)]
    assert owners == [se, WORK_MODEL]  # the routine, and the work model's definition of the mark
    routine = normalized(se).split("## Outside issues", 1)[1]
    assert "intake --outside" in routine and "decision note in the deck" in routine
    assert "never as an issue" in routine
    model = normalized(WORK_MODEL).split("## Outside issues", 1)[1].split("## ", 1)[0]
    assert "(../../agents/se.md#outside-issues)" in model and "Something contradicted" not in model
    assert sum("Something contradicted" in normalized(path) for path in PROSE) == 1


def test_no_prose_files_finds_or_closes_a_field_report_issue():
    """One issue per piece of work: the field report is the pull request's description."""
    for path in PROSE:
        text = normalized(path)
        for phrase in ("--label field-report", "label `field-report`", "field report #<n>",
                       "integrate <field-report>", "--field-report <file>", "field-report: <branch>"):
            assert phrase not in text, (path, phrase)
        for sentence in re.findall(r"[^.]*field-report issue[^.]*\.", text, re.IGNORECASE):
            assert path == WORK_MODEL and ("No field-report issue is filed" in sentence
                                           or "history" in sentence or "old field-report" in sentence
                                           ), (path, sentence)
    rules = normalized(WORK_MODEL)
    assert "a pull request to the integration branch whose description is the field report" in rules
    assert "between its `<!-- se:field-report -->` and `<!-- se:field-report:end -->` lines" in rules
    assert ("Field-report issues filed before this are history: they keep their `field-report` label "
            "and are not migrated; nothing new gets that label.") in rules
    assert "`integrate` closes the work issue with a comment that links the pull request and the release" in rules
    assert "read the field reports in the pull request descriptions of the window's closed work issues" in rules
    for role in ("worker", "integrator", "se"):
        assert "field-report issue" not in normalized(AGENTS / f"{role}.md").casefold(), role


# Only SE asks the person (rule-book dec-012): no other role's file sends the person to its session.
SE_FILES = {AGENTS / "se.md", *(SOURCE / "skills" / "catch-up").rglob("*.md")}
NON_SE_FILES = sorted({*AGENTS.glob("*.md"), *(SOURCE / "skills").rglob("*.md")} - SE_FILES)
PERSON = re.compile(r"\b(?:person|owner|human|user)(?:'s)?\b", re.IGNORECASE)
OWN_SESSION = re.compile(
    r"\b(?:this|its|your|my|their|own|(?:the|a|an) (?:worker|integrator)'s) session\b"
    r"|\bhere\b", re.IGNORECASE)
ACTS = re.compile(r"\b(?:approv\w*|yes|confirm\w*|ask\w*|answer\w*|act|acts|consent\w*|decid\w*|"
                  r"accept\w*|send\w*|go|goes|come|comes|open\w*|switch\w*|type\w*|give\w*)\b",
                  re.IGNORECASE)
NEGATED = re.compile(r"\b(?:never|not|no|nor)\b|n't\b", re.IGNORECASE)


def sends_the_person_here(text: str) -> list[str]:
    """The sentences that tell or ask the person to act in the writing role's own session."""
    sentences = re.split(r"(?<=[.!?:;])\s+", " ".join(text.split()))
    return [sentence for sentence in sentences
            if PERSON.search(sentence) and OWN_SESSION.search(sentence)
            and ACTS.search(sentence) and not NEGATED.search(sentence)]


@pytest.mark.parametrize("path", NON_SE_FILES, ids=lambda path: path.relative_to(SOURCE).as_posix())
def test_no_role_but_se_sends_the_person_to_its_session(path):
    assert sends_the_person_here(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("text", [
    "The owner's yes counts only when given in this session.",
    "Ask the person to approve the force-push in your session.",
    "Wait until the human confirms here, then push.",
    "Send the user to the integrator's session to switch the setting.",
])
def test_the_own_session_check_flags_a_step_that_needs_the_person_there(text):
    assert sends_the_person_here(text) == [text]


@pytest.mark.parametrize("text", [
    "Never send the person to this session.",
    "SE runs it on the person's yes, or names the one setting the person changes.",
    "A host counts a person's approval only in the session it was given.",
    "Do not judge a worker by its session status right after starting it.",
])
def test_the_own_session_check_passes_pointers_to_se(text):
    assert sends_the_person_here(text) == []


def test_se_runs_the_steps_only_the_person_approves():
    rules = normalized(WORK_MODEL)
    assert "### Steps only the person approves" in WORK_MODEL.read_text(encoding="utf-8")
    for step in ("`work_tickets.py refs request <issue> --triples-file <file>`",
                 "`work_tickets.py refs apply <issue>`", "SE runs it on the person's yes"):
        assert step in rules, step
    for role in ("integrator", "worker", "se"):
        assert "(../skills/work-model/SKILL.md#steps-only-the-person-approves)" in normalized(
            AGENTS / f"{role}.md"), role
    assert "on the person's yes in this session run it yourself" in normalized(AGENTS / "se.md")


def test_se_lists_and_interrupts_the_live_sessions_on_a_pause_and_says_how_to_resume():
    se = normalized(AGENTS / "se.md")
    pause = se[se.index("## Pause"):se.index("## Outside issues")]
    steps = ["Start, dispatch, route and release nothing", "List every live session",
             "when it last wrote", "`list_sessions`", "`list_triggers`", "`last_run.session_id`",
             "Interrupt every working one with `interrupt_session`",
             "Report the list to the owner", "close the pause issue"]
    positions = [pause.find(step) for step in steps]
    assert -1 not in positions and positions == sorted(positions), dict(zip(steps, positions))
    assert "(../skills/work-model/SKILL.md#pause)" in pause
    turn_start = se[se.index("**Turn-start check**"):]
    assert turn_start.index("`work_tickets.py paused") < turn_start.index("`work_tickets.py queue")


def test_the_work_model_states_the_pause_switch_once_and_the_roles_link_it():
    rules = normalized(WORK_MODEL)
    assert rules.count("## Pause") == 1
    assert "an issue labelled `pause` is open in the repository" in rules
    for command in ("`queue`, `start`, `integrate` and `route` refuse while paused",
                    "`work_tickets.py paused` reads it"):
        assert command in rules
    for role in ("se", "integrator"):
        text = normalized(AGENTS / f"{role}.md")
        assert "labelled `pause`" not in text  # the switch is stated once, in the work model
        assert "work-model/SKILL.md#pause)" in text
    integrator = normalized(AGENTS / "integrator.md")
    assert integrator.index("`work_tickets.py paused`") < integrator.index("`work_tickets.py queue`")
