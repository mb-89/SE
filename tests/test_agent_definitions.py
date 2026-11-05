"""The role agent definitions exist, point to the work-model skill and are linked from the skills."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"
AGENTS = GITHUB / "agents"
SKILL = GITHUB / "skills" / "catch-up" / "SKILL.md"
WORK_MODEL = GITHUB / "skills" / "work-model" / "SKILL.md"
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


@pytest.mark.parametrize("path", [*(AGENTS / f"{role}.agent.md" for role in ROLES), SKILL, WORK_MODEL],
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


def test_integrator_restarts_workers_waiting_for_input():
    integrator = normalized(AGENTS / "integrator.agent.md")
    assert "checks `list_sessions` for status `inputneeded`" in integrator.casefold()
    assert "deleted and restarted in its worktree" in integrator


def test_partial_deliveries_define_blockers_and_review_responses():
    rules = normalized(WORK_MODEL)
    report = normalized(GITHUB / "ISSUE_TEMPLATE" / "field-report.md")
    assert "A partial-delivery blocker is only work outside the worker's box" in rules
    assert "tests of the package's own code are never blockers" in rules.casefold()
    assert "throw-away tracker issues for live acceptance runs" in rules
    assert "Deleting or condensing authored content is recorded in the field report" in rules
    assert "## Review responses" in report
    assert "answers every review point" in report


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
