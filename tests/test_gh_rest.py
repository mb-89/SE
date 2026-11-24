"""SE's GitHub door over REST (scripts/gh_rest.py, `work_tickets.gh_backend`): a gh whose sign-in
fails but whose REST API answers counts as usable, and each porcelain call reaches GitHub through
`gh api` alone, never GraphQL. The fake is tests/fake_rest_github.py behind the process door."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from fake_rest_github import RestGitHub

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_tickets", PROJECT / "scripts" / "work_tickets.py")
work_tickets = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("work_tickets", work_tickets)
SPEC.loader.exec_module(work_tickets)

pytestmark = pytest.mark.usefixtures("fake_git_door")
SLUG = "owner/tracker"
REPO = f"github.com/{SLUG}"


def install(monkeypatch, fake_processes, github: RestGitHub) -> RestGitHub:
    """`github` answers every gh call; the door decides afresh, and finds gh on PATH."""
    which = shutil.which
    monkeypatch.setattr(work_tickets, "_gh_backend", {})
    monkeypatch.setattr(work_tickets.shutil, "which",
                        lambda name, *rest: "gh" if name == "gh" else which(name, *rest))
    fake_processes.on("gh", github)
    return github


@pytest.fixture
def rest_gh(monkeypatch, fake_processes) -> RestGitHub:
    """A gh as Claude Code's cloud has it: not signed in, its REST API answering."""
    return install(monkeypatch, fake_processes, RestGitHub())


def gh(root: Path, *arguments: str) -> str:
    return work_tickets.run_gh(root, [*arguments, "--repo", REPO])


def no_graphql(github: RestGitHub) -> bool:
    """Every call was the sign-in check or `gh api` on a REST path."""
    return all(call[:2] == ["auth", "status"] or (call[0] == "api" and "graphql" not in call)
               for call in github.calls)


def test_a_gh_whose_sign_in_fails_but_whose_rest_api_answers_reaches_github_over_rest(rest_gh):
    assert work_tickets.gh_usable() and not work_tickets.hand_off()
    assert work_tickets.gh_backend() == work_tickets.REST
    assert rest_gh.calls == [["auth", "status"], ["api", "rate_limit"]]
    work_tickets.gh_usable()
    assert len(rest_gh.calls) == 2  # decided once for the process


def test_a_gh_neither_signed_in_nor_answered_over_rest_counts_as_no_gh(monkeypatch, fake_processes):
    install(monkeypatch, fake_processes, RestGitHub(rest=False))

    assert not work_tickets.gh_usable() and work_tickets.hand_off()
    with pytest.raises(work_tickets.MissingGhError, match=r"neither signed in \(gh auth status: "
                       r"exit code 1\) nor answered over REST \(gh api rate_limit: exit code 1\)"):
        work_tickets.gh_executable()


def test_a_signed_in_gh_runs_its_porcelain_as_it_is(monkeypatch, fake_processes, tmp_path):
    github = install(monkeypatch, fake_processes, RestGitHub(signed_in=True))

    assert work_tickets.gh_backend() == work_tickets.SIGNED_IN
    with pytest.raises(work_tickets.QueueError, match="GraphQL"):  # the fake's porcelain is refused
        gh(tmp_path, "issue", "list", "--json", "number")
    assert github.calls == [["auth", "status"], ["issue", "list", "--json", "number", "--repo", REPO]]


def test_issue_list_pages_over_rest_without_pull_requests_in_gh_s_fields(rest_gh, tmp_path):
    for number in range(1, 151):
        rest_gh.issue(SLUG, number, f"work-{number}", labels=["work", "ready"],
                      assignees=["alice"] if number == 150 else ())
    rest_gh.issue(SLUG, 200, "other", labels=["work"])
    rest_gh.pull(SLUG, 300, "a pull request", "feature")

    listed = json.loads(gh(tmp_path, "issue", "list", "--state", "open", "--label", "work",
                           "--label", "ready", "--json", "number,title,labels,assignees,url,state",
                           "--limit", "200"))

    assert [item["number"] for item in listed] == list(range(150, 0, -1))
    assert listed[0] == {
        "number": 150, "title": "work-150", "state": "OPEN",
        "url": f"https://github.com/{SLUG}/issues/150",
        "labels": [{"id": "L_work", "name": "work", "description": "", "color": "ededed"},
                   {"id": "L_ready", "name": "ready", "description": "", "color": "ededed"}],
        "assignees": [{"login": "alice", "is_bot": False}]}
    assert [call[3] for call in rest_gh.calls[2:]] == [
        f"repos/{SLUG}/issues?state=open&labels=work%2Cready&per_page=100&page=1",
        f"repos/{SLUG}/issues?state=open&labels=work%2Cready&per_page=100&page=2"]
    assert no_graphql(rest_gh)


def test_issue_list_with_a_search_asks_the_search_api(rest_gh, tmp_path):
    rest_gh.issue(SLUG, 4, "cloud-reads", state="closed")
    rest_gh.issue(SLUG, 5, "other")

    listed = json.loads(gh(tmp_path, "issue", "list", "--state", "all", "--search",
                           '"cloud-reads" in:title', "--json", "number,title,state", "--limit", "100"))

    assert listed == [{"number": 4, "title": "cloud-reads", "state": "CLOSED"}]
    assert rest_gh.calls[-1][3].startswith("search/issues?q=repo%3Aowner%2Ftracker+is%3Aissue+")


def test_issue_view_reads_the_issue_and_its_comments_and_takes_one_jq_field(rest_gh, tmp_path):
    rest_gh.issue(SLUG, 7, "work-7", body="the body", labels=["work"],
                  comments=["first", {"body": "second", "login": "bob",
                                      "author_association": "NONE"}])

    viewed = json.loads(gh(tmp_path, "issue", "view", "7", "--json", work_tickets.ISSUE_FIELDS))
    record = work_tickets.issue_record(viewed, associations=True)

    assert (record["number"], record["body"], record["labels"]) == (7, "the body", [{"name": "work"}])
    assert [(c["author"], c["body"], c["association"], c["byOwner"]) for c in record["comments"]] == [
        ("owner", "first", "OWNER", True), ("bob", "second", "NONE", False)]
    assert gh(tmp_path, "issue", "view", "7", "--json", "state", "--jq", ".state") == "OPEN\n"


def test_issue_edit_writes_its_title_body_and_whole_label_list_in_one_update(rest_gh, tmp_path):
    rest_gh.issue(SLUG, 8, "old", labels=["work", "ready"])
    body = tmp_path / "body.md"
    body.write_text("new body\n", encoding="utf-8")

    printed = gh(tmp_path, "issue", "edit", "8", "--title", "new", "--remove-label", "ready",
                 "--remove-label", "absent", "--add-label", "in-progress", "--add-assignee", "agent",
                 "--body-file", str(body))

    assert printed == f"https://github.com/{SLUG}/issues/8\n"
    assert rest_gh.writes == [
        ("POST", "issues/8/assignees", {"assignees": ["agent"]}),
        ("PATCH", "issues/8", {"title": "new", "body": "new body\n", "labels": ["work", "in-progress"]})]
    assert rest_gh.label_names(SLUG, 8) == ["work", "in-progress"]


def test_issue_create_comment_and_close_print_what_gh_prints(rest_gh, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("text\n", encoding="utf-8")

    created = gh(tmp_path, "issue", "create", "--title", "filed", "--label", "work", "--body-file",
                 str(body))
    number = int(created.strip().rsplit("/", 1)[-1])
    commented = gh(tmp_path, "issue", "comment", str(number), "--body-file", str(body))
    gh(tmp_path, "issue", "close", str(number), "--reason", "not planned")

    assert created == f"https://github.com/{SLUG}/issues/{number}\n"
    assert commented.startswith(f"https://github.com/{SLUG}/issues/{number}#issuecomment-")
    item = rest_gh.issues[SLUG][number]
    assert (item["state"], item["state_reason"], rest_gh.label_names(SLUG, number)) == (
        "closed", "not_planned", ["work"])


def test_labels_list_and_create_over_rest(rest_gh, tmp_path):
    rest_gh.label(SLUG, "work")

    gh(tmp_path, "label", "create", "ready", "--color", "c5def5", "--description", "may be worked")

    assert json.loads(gh(tmp_path, "label", "list", "--json", "name", "--limit", "500")) == [
        {"name": "work"}, {"name": "ready"}]
    assert rest_gh.writes == [("POST", "labels", {"name": "ready", "color": "c5def5",
                                                  "description": "may be worked"})]


def test_pull_requests_list_view_create_edit_and_comment_over_rest(rest_gh, tmp_path):
    rest_gh.pull(SLUG, 3, "feature", "feature", body="report", sha="a" * 40)
    rest_gh.pull(SLUG, 4, "other", "other", base="release")
    body = tmp_path / "body.md"
    body.write_text("described\n", encoding="utf-8")

    listed = json.loads(gh(tmp_path, "pr", "list", "--state", "open", "--base", "main", "--json",
                           "number,title,url,body", "--limit", "200"))
    headed = json.loads(gh(tmp_path, "pr", "list", "--head", "feature", "--base", "main", "--state",
                           "open", "--json", "number,url"))
    viewed = json.loads(gh(tmp_path, "pr", "view", "3", "--json",
                           "number,url,body,headRefName,headRefOid"))
    created = gh(tmp_path, "pr", "create", "--base", "main", "--head", "next", "--title", "next",
                 "--body-file", str(body))
    gh(tmp_path, "pr", "edit", "3", "--title", "feature", "--body-file", str(body))
    gh(tmp_path, "pr", "comment", "3", "--body-file", str(body))

    url = f"https://github.com/{SLUG}/pull/3"
    assert listed == [{"number": 3, "title": "feature", "url": url, "body": "report"}]
    assert headed == [{"number": 3, "url": url}]
    assert viewed == {"number": 3, "url": url, "body": "report", "headRefName": "feature",
                      "headRefOid": "a" * 40}
    assert created == f"https://github.com/{SLUG}/pull/5\n"
    assert rest_gh.pulls[SLUG][3]["body"] == "described\n"
    assert [write[:2] for write in rest_gh.writes] == [
        ("POST", "pulls"), ("PATCH", "pulls/3"), ("POST", "issues/3/comments")]
    assert no_graphql(rest_gh)


@pytest.mark.parametrize("arguments, refusal", [
    (["issue", "list", "--json", "number,milestone"], "field(s) milestone are not answered"),
    (["issue", "list", "--json", "number", "--web"], "option --web is not answered"),
    (["issue", "lock", "3"], "gh issue lock is not answered"),
    (["issue", "view", "3", "--json", "state", "--jq", ".labels[0]"], "it takes one .<field>"),
])
def test_a_form_the_rest_door_does_not_know_is_refused_naming_it(rest_gh, tmp_path, arguments, refusal):
    rest_gh.issue(SLUG, 3, "three")

    with pytest.raises(work_tickets.QueueError, match=re_escape(refusal)):
        gh(tmp_path, *arguments)
    assert no_graphql(rest_gh)


def re_escape(text: str) -> str:
    import re
    return re.escape(text)


def test_a_call_without_repo_means_origin_s_repository(rest_gh, monkeypatch, tmp_path):
    monkeypatch.setattr(work_tickets, "remote_repo", lambda root: REPO)
    rest_gh.issue(SLUG, 9, "nine")

    assert json.loads(work_tickets.run_gh(tmp_path, ["issue", "view", "9", "--json", "title"])) == {
        "title": "nine"}
