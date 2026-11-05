"""The role agent definitions exist, point to the work-model skill and are linked from the skills."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"
AGENTS = GITHUB / "agents"
SKILL = GITHUB / "skills" / "catch-up" / "SKILL.md"
WORK_MODEL = GITHUB / "skills" / "work-model" / "SKILL.md"
DECISION = GITHUB / "skills" / "decision" / "SKILL.md"
ROLES = ("dispatcher", "worker", "integrator")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("role", ROLES)
def test_agent_definition_names_its_role_and_points_to_the_work_model(role):
    text = (AGENTS / f"{role}.agent.md").read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert f"name: {role}" in front_matter and "description:" in front_matter
    assert "(../skills/work-model/SKILL.md)" in text


def test_worker_agent_tools_exclude_input_and_workspace_prompts():
    text = (AGENTS / "worker.agent.md").read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert "tools: ['execute', 'read', 'edit', 'search', 'send_message']" in front_matter
    assert "strict-tools-list: true" in front_matter
    assert "ask_user" not in front_matter
    assert "set_workspace" not in front_matter


@pytest.mark.parametrize("role", ("worker", "integrator"))
def test_non_dispatcher_agents_remove_workspace_switching_advice(role):
    text = (AGENTS / f"{role}.agent.md").read_text(encoding="utf-8")
    assert "set_workspace if available" not in text


@pytest.mark.parametrize("path", [*(AGENTS / f"{role}.agent.md" for role in ROLES), SKILL, WORK_MODEL, DECISION],
                         ids=lambda path: path.name)
def test_relative_links_resolve(path):
    text = path.read_text(encoding="utf-8")
    for target in LINK.findall(text):
        if "://" not in target:
            assert (path.parent / target).exists(), f"{path.name}: {target}"


def test_skill_links_every_agent_definition():
    text = SKILL.read_text(encoding="utf-8")
    for role in ROLES:
        assert f"(../../agents/{role}.agent.md)" in text


@pytest.mark.parametrize("role", ("worker", "integrator"))
def test_non_dispatcher_roles_ban_input_prompts_and_escalate(role):
    text = normalized(AGENTS / f"{role}.agent.md")
    assert "never call `ask_user`" in text.casefold()
    assert "`ask_user`" in text.casefold()
    assert "question, confirmation or approval prompt" in text
    assert "dispatcher" in text


def test_only_the_dispatcher_talks_to_the_human():
    dispatcher = normalized(AGENTS / "dispatcher.agent.md")
    assert "only session the human talks to" in dispatcher
    assert "only role that may ask the human with `ask_user`" in dispatcher
    for role in ("worker", "integrator"):
        assert "ask the human" not in normalized(AGENTS / f"{role}.agent.md")
    rules = normalized(WORK_MODEL)
    assert "Only the dispatcher talks to the human" in rules
    assert "to the human at the top level" not in rules


def test_worker_instructions_require_utf8_file_writes_in_windows_powershell():
    worker = normalized(AGENTS / "worker.agent.md")
    assert "powershell 5.1 redirection `>` writes utf-16" in worker.casefold()
    assert "[io.file]::writealltext" in worker.casefold()
    assert "out-file -encoding utf8" in worker.casefold()


def test_worker_requires_evidence_for_every_work_issue_item():
    worker = normalized(AGENTS / "worker.agent.md")
    assert "every numbered requirement and every acceptance line" in worker
    assert "one quoted evidence line" in worker
    assert 'under "not delivered", never as a "decision"' in worker.casefold()


def test_integrator_restarts_only_workers_whose_events_show_a_prompt():
    integrator = normalized(AGENTS / "integrator.agent.md")
    assert "inputneeded" not in integrator.casefold()
    assert 'reads as idle or "review ready" before its first turn' in integrator
    assert "stuck only when its events show it waiting on a prompt" in integrator
    assert "delete it and start it again in its worktree" in integrator


def test_partial_deliveries_define_blockers_and_review_responses():
    rules = normalized(WORK_MODEL)
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    assert "A partial-delivery blocker is only work outside the worker's box" in rules
    assert "tests of the package's own code are never blockers" in rules.casefold()
    assert "throw-away tracker issues for live acceptance runs" in rules
    assert "Deleting or condensing authored content is recorded in the field report" in rules
    assert "## Review responses" in report
    assert "answers every review point" in report
    assert "## Removed behaviour, deleted or weakened tests, and authored prose" in report
    assert "(../skills/work-model/SKILL.md#rules-for-all-roles)" in report


def test_field_report_template_has_requirement_evidence_table():
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    assert "one row per work-issue requirement and acceptance item" in report
    assert "| Work issue item | Result | Commits | Evidence |" in report
    assert "(../agents/worker.agent.md#procedure)" in report


def test_field_report_template_names_the_integration_branch_it_was_tested_against():
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    assert "**Tested against `<integration branch>`:** `<commit>`" in report
    assert "Tested against main" not in report


def test_work_issue_template_asks_for_the_field_reports_reproduction():
    template = normalized(GITHUB / "ISSUE_TEMPLATE" / "work.md")
    assert "## Reproduction" in template
    assert "quote the reproduction command it ran and that command's output" in template


def test_worker_commit_rule_names_its_groupings_and_has_one_owner():
    worker = normalized(GITHUB / "agents" / "worker.agent.md")
    assert "requirements that change one function together share one commit" in worker
    assert "its test may be a test-only commit" in worker
    assert "The field report names each such grouping" in worker
    owners = [path.relative_to(GITHUB).as_posix() for path in sorted(GITHUB.rglob("*.md"))
              if "one commit per" in normalized(path).casefold()]
    assert owners == ["agents/worker.agent.md"]


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
    owners = [path.relative_to(GITHUB).as_posix() for path in sorted(GITHUB.rglob("*.md"))
              if rule.casefold() in normalized(path).casefold()]
    assert len(owners) == 1, owners


def test_dispatcher_can_dispatch_anywhere_without_writing_repositories():
    rule = "The dispatcher never writes any repository"
    owners = [path.relative_to(GITHUB).as_posix() for path in sorted(GITHUB.rglob("*.md"))
              if rule.casefold() in normalized(path).casefold()]
    assert owners == ["skills/work-model/SKILL.md"]
    rules = normalized(WORK_MODEL)
    assert "may file work issues for and dispatch into any repository" in rules
    assert "Each repository has exactly one integrator" in rules
    assert "The integrator starts that repository's workers" in rules


def test_catch_up_starts_integrators_not_workers():
    catch_up = normalized(SKILL)
    assert "If none runs, start one with the prompt" in catch_up
    assert "naming the integrator agent, the repository and this dispatcher session" in catch_up
    assert "Never start workers directly" in catch_up


def test_dispatcher_and_catch_up_link_to_the_shared_dispatch_rule():
    dispatcher = (AGENTS / "dispatcher.agent.md").read_text(encoding="utf-8")
    catch_up = SKILL.read_text(encoding="utf-8")
    assert "(../skills/work-model/SKILL.md#roles-and-flow)" in dispatcher
    assert "(../work-model/SKILL.md#roles-and-flow)" in catch_up


MARKDOWN = sorted(GITHUB.rglob("*.md"))
ANCHOR_LINK = re.compile(r"\]\(([^)\s]*)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def anchors(path: Path) -> set[str]:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces become hyphens."""
    return {re.sub(r"[^\w\- ]", "", heading.strip().casefold()).replace(" ", "-")
            for heading in HEADING.findall(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda path: path.relative_to(GITHUB).as_posix())
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
    # Project and person names are the public check's machine-local deny list; this test
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
    text = normalized(AGENTS / f"{role}.agent.md")
    assert "integration branch" in text
    assert "(../skills/work-model/SKILL.md#integration-branch)" in text
    assert "`main`" not in text.replace("`main` unless the project names another", "")


def test_work_model_owns_the_integration_branch_setting():
    text = normalized(WORK_MODEL)
    assert "## Integration branch" in text
    assert 'integration_branch = "se"' in text and "It is `main` unless" in text


def test_messages_travel_only_up_and_down_the_tree():
    rule = normalized(WORK_MODEL)
    assert "**Messages travel only up and down the tree**" in rule
    assert "news for another repository goes up to the dispatcher" in rule
    integrator = normalized(AGENTS / "integrator.agent.md")
    assert "(../skills/work-model/SKILL.md#roles-and-flow)" in integrator
    assert "never another repository's integrator" in integrator


def test_the_comment_footer_rule_is_said_once():
    assert "**Comments carry the host's footer**" in normalized(WORK_MODEL)
    for path in (*(AGENTS / f"{role}.agent.md" for role in ROLES), SKILL):
        assert "footer" not in normalized(path), path.name


def test_integrator_leaves_a_branch_the_host_refuses_to_delete():
    integrator = normalized(AGENTS / "integrator.agent.md")
    assert "automatic head-branch deletion removes it. Never retry the deletion." in integrator


def test_the_commit_trailer_is_one_setting_the_roles_point_to():
    assert 'commit_trailer = "<trailer line>" # optional; none by default' in WORK_MODEL.read_text(
        encoding="utf-8")
    for path in (*(AGENTS / f"{role}.agent.md" for role in ROLES), SKILL):
        text = normalized(path)
        assert "Co-authored-by" not in text, path.name
    for path in (AGENTS / "worker.agent.md", SKILL):
        assert "`commit_trailer`](" in normalized(path), path.name


def test_one_skill_owns_how_a_decision_is_presented():
    assert "name: decision" in DECISION.read_text(encoding="utf-8").split("---")[1]
    pointers = {AGENTS / "dispatcher.agent.md": "(../skills/decision/SKILL.md)",
                SKILL: "(../decision/SKILL.md)"}
    for path, link in pointers.items():
        text = normalized(path)
        assert link in text, path.name
        for restated in ("What we gain", "Decision 2 of", "Reply A", "one at a time", "one level up"):
            assert restated.casefold() not in text.casefold(), (path.name, restated)


def test_the_decision_skill_holds_the_presentation_rules():
    text = normalized(DECISION)
    for rule in ("exactly one decision", '"Decision 2 of 3"', "one to three sentences",
                 "| Option | What it means | What we gain | What we lose |", "(recommended)",
                 '"Reply A, B or C"', "## Tasks for the person", "never an option in a decision",
                 '"Task 1 of 2"'):
        assert rule in text, rule


def test_the_decision_skill_asks_one_level_up_with_the_worked_example():
    text = normalized(DECISION)
    assert "## One level up" in text
    assert "name the class the instance belongs to and ask about the general mechanism" in text
    assert '"can queries select the manifest note?"' in text
    assert ('"a note can mark itself ignored, like a Python underscore name; the manifest is one '
            'such note"') in text


def test_the_decision_skill_records_the_answer_where_it_takes_effect():
    text = normalized(DECISION)
    assert "## Recording the answer" in text
    assert "recorded where it takes effect, quoting the person word for word" in text


def without_gh_section() -> str:
    text = WORK_MODEL.read_text(encoding="utf-8")
    return text.split("### Without gh", 1)[1].split("\n## ", 1)[0]


def commands_that_need_no_gh() -> set[str]:
    """Subcommands of work_tickets.py whose branch in main never reaches run_gh."""
    import ast
    import importlib.util
    import sys

    script = ROOT / "scripts" / "work_tickets.py"
    spec = importlib.util.spec_from_file_location("work_tickets_commands", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    commands = set(module.make_parser()._subparsers._group_actions[0].choices)
    tree = ast.parse(script.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def called(node: ast.AST) -> set[str]:
        return {call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}

    reaches_gh = {"run_gh"}
    grown = True
    while grown:
        grown = False
        for name, function in functions.items():
            if name not in reaches_gh and called(function) & reaches_gh:
                reaches_gh.add(name)
                grown = True
    needs_gh: set[str] = set()
    for node in ast.walk(functions["main"]):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and getattr(node.test.left, "attr", None) == "command"):
            value = ast.literal_eval(node.test.comparators[0])
            names = {value} if isinstance(value, str) else set(value)
            if any(called(statement) & reaches_gh for statement in node.body):
                needs_gh |= names
    return commands - needs_gh


def test_the_work_model_owns_without_gh_and_lists_the_commands_that_still_run():
    section = without_gh_section()
    line = next(line for line in section.split("\n- ") if line.startswith("**Commands that still run**"))
    listed = set(re.findall(r"`([a-z-]+)`", line.split("Every other command")[0]))
    assert listed == commands_that_need_no_gh()
    assert "the host's GitHub tools" in section
    assert "naming itself, the missing `gh` and this section" in " ".join(section.split())


def test_without_gh_names_what_the_session_prompt_still_carries_and_nothing_else():
    section = without_gh_section()
    assert ("**The session prompt carries only** the agent, the work issue, the branch"
            in " ".join(section.split()))
    prompt = section.split("```text", 1)[1].split("```", 1)[0]
    keys = [line.strip().split(":", 1)[0] for line in prompt.strip().splitlines()]
    assert keys == ["Act as the worker agent defined in <se>/.github/agents/worker.agent.md (read it first, plus the project's AGENTS.md).",
                    "Work issue", "Branch", "Integrator session to notify at delivery"]


@pytest.mark.parametrize("role", ("worker", "integrator"))
def test_roles_point_to_without_gh_and_do_not_restate_it(role):
    text = normalized(AGENTS / f"{role}.agent.md")
    assert "(../skills/work-model/SKILL.md#without-gh)" in text
    for owned in ("Commands that still run", "GitHub tools", "MCP", "outcome branch",
                  "carries only", "`review-note`, `probe`"):
        assert owned not in text, owned


def test_agents_md_names_the_focused_and_complete_test_commands():
    text = normalized(ROOT / "AGENTS.md")
    tests = text.split("## Tests", 1)[1].split(" ## ", 1)[0]
    assert "Focused: `uv run pytest -q tests/<file>.py`" in tests
    assert "Complete: `uv run pytest -q`" in tests


def test_the_work_model_owns_where_the_commit_identity_and_the_public_check_come_from():
    provides = normalized(WORK_MODEL).split("## What the project provides", 1)[1]
    assert "**Commit identity and public check**: every role commits as `public_identity`" in provides
    assert "else as the project's `identity` in its `se.toml`" in provides
    assert "`work_tickets.py sync`, which every role runs at the start, writes whichever applies" in provides
    assert "runs the project's setup command before its first commit" in provides
    assert "se's commits carry `mb <mb>`, the `identity` in `se.toml`" in normalized(ROOT / "AGENTS.md")
    assert "[commit identity](../skills/work-model/SKILL.md#what-the-project-provides)" in normalized(
        AGENTS / "worker.agent.md")


def test_the_worker_commits_each_requirement_while_working():
    worker = normalized(AGENTS / "worker.agent.md")
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
    "**Delivery fallback**: an output whose write keeps failing after those retries goes in full into the next "
    "output that can be written, and a short placeholder points to it: where the field-report issue cannot be "
    "created with the report, the full report goes into the pull request body, a short field-report issue "
    "links it, and the delivery notice names the pull request.",
)


@pytest.mark.parametrize("rule", CLOUD_RULES, ids=lambda rule: rule.split("**")[1])
def test_the_cloud_section_holds_each_cloud_rule_once(rule):
    assert " ".join(without_gh_section().split()).count(rule) == 1
    assert normalized(WORK_MODEL).count(rule.split("**")[1]) == 1
    for path in (*(AGENTS / f"{role}.agent.md" for role in ROLES), SKILL):
        assert rule.split("**")[1] not in normalized(path), path.name


def test_the_worker_installs_the_hooks_before_its_first_commit():
    worker = normalized(AGENTS / "worker.agent.md")
    procedure = worker.split("## Procedure", 1)[1]
    setup = procedure.index("in a fresh clone, first run the project's setup command that installs its hooks")
    assert setup < procedure.index("`work_tickets.py sync`") < procedure.index("commit as the work model's")
    assert "[public check](../skills/work-model/SKILL.md#what-the-project-provides) runs on every commit and push" in worker
    assert "`scripts/setup.sh`" in " ".join(normalized(ROOT / "AGENTS.md").split("## Public safety", 1)[1].split())


def test_the_worker_runs_what_the_acceptance_names_including_the_suite():
    worker = normalized(AGENTS / "worker.agent.md")
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
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    delivered = report.split("## Delivered", 1)[1].split("## Not delivered", 1)[0]
    assert "**Commit groupings:** None <!-- or, per grouping the worker's commit rule allows" in delivered


def test_the_field_report_replaces_evidence_the_host_cannot_carry_with_its_command():
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    assert ("Evidence the host cannot carry is replaced by the command that reproduces it: where images cannot "
            "be attached, each screenshot's row names the command that takes it again.") in report


def test_the_work_model_waits_on_a_background_process_by_its_id():
    shell = normalized(WORK_MODEL).split("## Commands and shell", 1)[1]
    assert "Wait on a background process by its process id (`kill -0 <pid>`" in shell
    assert "never by `pgrep -f <pattern>`" in shell


def test_the_worker_builds_an_acceptance_build_at_the_new_pin_before_code():
    worker = normalized(AGENTS / "worker.agent.md")
    assert "where the acceptance names a real build" in worker
    assert "build it at that pin before writing code" in worker


def test_the_worker_may_work_without_the_ticket_queue_where_the_host_refuses_it():
    worker = normalized(AGENTS / "worker.agent.md")
    assert ("Where the host refuses the local ticket queue (`work_tickets.py init`, `create`, `move`, "
            "`status`), it is optional: work without it and say so in the field report.") in worker


def test_the_worker_runs_the_affected_real_command_once_against_the_real_service():
    worker = normalized(AGENTS / "worker.agent.md")
    procedure = worker.split("## Procedure", 1)[1]
    step = procedure.split("4. **Work the ticket**", 1)[1].split("5. **Deliver", 1)[0]
    assert ("Where the container allows it, run the affected real command once against the real outside "
            "service, not only against its fake: only the real call shows what the service refuses.") in step


def test_the_suite_runs_at_a_moved_pin_before_the_change_for_worker_and_integrator():
    rule = ("When the acceptance names the complete suite and a dependency pin moves, the suite runs at the "
            "new pin before the change, so failures that exist already are told apart from the change's own.")
    assert normalized(WORK_MODEL).count(rule) == 1
    for role in ("worker", "integrator"):
        text = normalized(AGENTS / f"{role}.agent.md")
        assert rule not in text
        assert "[suite at a moved pin](../skills/work-model/SKILL.md#suite-at-a-moved-pin)" in text
