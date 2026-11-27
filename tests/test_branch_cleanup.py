"""The branch-cleanup workflow (.github/workflows/branch-cleanup.yml, docs/running.md "Workflows"): a closed
pull request's head branch goes, unless a guard holds it; each outcome is one summary line."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import yaml

import se_workflows
from manual import page

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "branch-cleanup.yml"
REPOSITORY = "alice/project"
SHA = "b" * 40


def loaded() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True)
    return data


def script() -> str:
    (step,) = loaded()["jobs"]["delete"]["steps"]
    return step["run"]


class Response(io.BytesIO):
    """One answer of urlopen: its status and body."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(body)
        self.status = status


class GitHub:
    """GitHub's REST API as the script sees it: the repository's branches, its pull requests and
    in-progress issues, how far each sha is ahead of the default branch, and every call, with the
    deletes it was asked for."""

    def __init__(self, branches: dict[str, str], pulls: list[dict], default: str = "main",
                 closed: list[dict] = (), ahead: dict[str, int] | None = None,
                 working: tuple[str, ...] = ()) -> None:
        self.branches, self.pulls, self.default = branches, pulls, default
        self.closed, self.ahead, self.working = list(closed), ahead or {}, working
        self.calls: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def answer(self, status: int, body: object = None) -> "Response":
        return Response(status, json.dumps(body).encode() if body is not None else b"")

    def page(self, query: dict, items: list) -> "Response":
        size, number = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
        return self.answer(200, items[(number - 1) * size:number * size])

    def urlopen(self, request: urllib.request.Request):
        url = urllib.parse.urlsplit(request.full_url)
        path, method = urllib.parse.unquote(url.path), request.get_method()
        query = urllib.parse.parse_qs(url.query)
        self.calls.append((method, path))
        assert request.get_header("Authorization") == "Bearer token"
        prefix = f"/repos/{REPOSITORY}"
        if method == "GET" and path == prefix:
            return self.answer(200, {"default_branch": self.default})
        if method == "GET" and path == f"{prefix}/branches":
            return self.page(query, [{"name": name, "commit": {"sha": sha}}
                                     for name, sha in sorted(self.branches.items())])
        if method == "GET" and path == f"{prefix}/issues":
            assert query["state"] == ["open"] and query["labels"] == ["in-progress"]
            return self.page(query, [{"number": 1, "title": title} for title in self.working])
        if method == "GET" and path == f"{prefix}/pulls":
            pulls = self.pulls if query["state"] == ["open"] else self.closed
            listed = [{"number": pull["number"],
                       "head": {"ref": pull["head"], "sha": pull.get("sha", SHA),
                                "repo": {"full_name": pull.get("repo", REPOSITORY)}}}
                      for pull in pulls]
            if "head" in query:
                head = query["head"][0].split(":", 1)[1]
                return self.answer(200, [pull for pull in listed if pull["head"]["ref"] == head])
            return self.page(query, listed)
        if method == "GET" and path.startswith(f"{prefix}/compare/"):
            base, _, sha = path.removeprefix(f"{prefix}/compare/").partition("...")
            assert base == self.default
            return self.answer(200, {"ahead_by": self.ahead.get(sha, 1)})
        if path.startswith(f"{prefix}/git/ref/heads/") and method == "GET":
            branch = path.removeprefix(f"{prefix}/git/ref/heads/")
            if branch not in self.branches:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            return self.answer(200, {"object": {"sha": self.branches[branch]}})
        if path.startswith(f"{prefix}/git/refs/heads/") and method == "DELETE":
            branch = path.removeprefix(f"{prefix}/git/refs/heads/")
            if branch not in self.branches:
                raise urllib.error.HTTPError(request.full_url, 422, "Reference does not exist", {}, None)
            del self.branches[branch]
            self.deleted.append(branch)
            return self.answer(204)
        raise AssertionError(f"unexpected call {method} {path}")


def run(github: GitHub, tmp_path: Path, branch: str = "feat/topic-20261116", number: int | None = 7,
        head: str = REPOSITORY, sha: str = SHA) -> str:
    """Run the workflow's script on the close of pull request `number`, or as a sweep only where
    it is None; its summary."""
    summary = tmp_path / "summary.md"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(urllib.request, "urlopen", github.urlopen)
        for name, value in {"GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": REPOSITORY,
                            "GITHUB_API_URL": "https://api.example.com",
                            "GITHUB_STEP_SUMMARY": str(summary),
                            "NUMBER": "" if number is None else str(number),
                            "HEAD_REF": branch if number else "", "HEAD_SHA": sha if number else "",
                            "HEAD_REPOSITORY": head if number else ""}.items():
            patch.setenv(name, value)
        try:
            exec(compile(script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
        except SystemExit as exited:
            assert exited.code is None, exited.code
    return summary.read_text(encoding="utf-8") if summary.exists() else ""


def test_a_closed_pull_request_s_branch_is_deleted(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA, "main": "c" * 40}, [])
    assert run(github, tmp_path) == f"Branch cleanup: deleted feat/topic-20261116 of #7 at {SHA[:12]}.\n"
    assert github.deleted == ["feat/topic-20261116"]
    assert github.branches == {"main": "c" * 40}


def test_a_fork_s_branch_is_kept(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [])
    assert run(github, tmp_path, head="mallory/project").splitlines()[0] == (
        "Branch cleanup: kept feat/topic-20261116 of #7: its head repository mallory/project is not "
        f"{REPOSITORY}.")
    assert github.deleted == []


def test_a_deleted_fork_is_kept_too(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [])
    assert "its head repository (deleted) is not" in run(github, tmp_path, head="")
    assert github.deleted == []


@pytest.mark.parametrize("branch", ["main", "trunk", "se", "rehearsal", "ccr-session", "claude/topic"])
def test_a_protected_branch_is_kept(tmp_path, branch):
    github = GitHub({branch: SHA, "trunk": "c" * 40}, [], default="trunk")
    assert run(github, tmp_path, branch=branch) == f"Branch cleanup: kept {branch} of #7: it is a protected branch.\n"
    assert github.deleted == []


def test_a_branch_another_open_pull_request_heads_is_kept(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [{"number": 7, "head": "feat/topic-20261116"},
                                                   {"number": 9, "head": "feat/topic-20261116"},
                                                   {"number": 8, "head": "feat/other"}])
    assert run(github, tmp_path) == ("Branch cleanup: kept feat/topic-20261116 of #7: it is the head of the "
                                     "open pull request #9.\n"
                                     "Branch cleanup: kept feat/topic-20261116: it is the head of an open "
                                     "pull request.\n")
    assert github.deleted == []


def test_a_branch_that_moved_since_the_pull_request_s_head_is_kept(tmp_path):
    github = GitHub({"feat/topic-20261116": "d" * 40}, [])
    assert run(github, tmp_path).splitlines()[0] == (
        f"Branch cleanup: kept feat/topic-20261116 of #7: it moved to {'d' * 12} since the pull "
        f"request's head {SHA[:12]}.")
    assert github.deleted == []


def test_a_branch_already_gone_is_a_success_with_a_note(tmp_path):
    github = GitHub({}, [])
    assert run(github, tmp_path) == "Branch cleanup: feat/topic-20261116 of #7 is already gone.\n"
    assert not any(method == "DELETE" for method, _ in github.calls)


def test_the_sweep_deletes_only_what_nothing_can_lose(tmp_path):
    merged, landed, moved, unmerged = "1" * 40, "2" * 40, "3" * 40, "4" * 40
    github = GitHub(
        {"main": "c" * 40, "claim": "c" * 40, "ccr-session": "5" * 40, "merged": merged,
         "landed": landed, "moved": moved, "unmerged": unmerged, "working": "6" * 40,
         "open": "7" * 40},
        [{"number": 9, "head": "open"}],
        closed=[{"number": 4, "head": "landed", "sha": landed},
                {"number": 5, "head": "moved", "sha": "8" * 40}],
        ahead={merged: 0, landed: 3, moved: 2, unmerged: 1}, working=("working",))
    assert run(github, tmp_path, number=None).splitlines() == [
        "Branch cleanup: kept claim: it is at main's tip, a start's claim in flight.",
        f"Branch cleanup: deleted landed at {landed[:12]}: the closed #4 keeps its commits.",
        f"Branch cleanup: deleted merged at {merged[:12]}: every commit is on main.",
        "Branch cleanup: kept moved: it holds 2 commits not on main that no closed pull request "
        "keeps; the start report lists it for the person.",
        "Branch cleanup: kept open: it is the head of an open pull request.",
        "Branch cleanup: kept unmerged: it holds 1 commit not on main that no closed pull request "
        "keeps; the start report lists it for the person.",
        "Branch cleanup: kept working: an in-progress issue works on it.",
    ]
    assert sorted(github.deleted) == ["landed", "merged"]


def test_the_sweep_reads_every_page(tmp_path):
    branches = {f"b{n:03}": f"{n:040x}" for n in range(1, 151)}
    github = GitHub({"main": "c" * 40, **branches}, [], ahead={sha: 0 for sha in branches.values()})
    run(github, tmp_path, number=None)
    assert sorted(github.deleted) == sorted(branches)


def test_the_close_runs_before_the_sweep(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA, "old": "1" * 40, "main": "c" * 40}, [],
                    ahead={"1" * 40: 0})
    assert run(github, tmp_path).splitlines() == [
        f"Branch cleanup: deleted feat/topic-20261116 of #7 at {SHA[:12]}.",
        f"Branch cleanup: deleted old at {'1' * 12}: every commit is on main.",
    ]


def test_the_workflow_runs_on_a_close_daily_by_hand_or_a_call():
    data = loaded()
    assert set(data["on"]) == {"workflow_call", "pull_request_target", "schedule", "workflow_dispatch"}
    assert data["on"]["pull_request_target"] == {"types": ["closed"]}
    assert len(data["on"]["schedule"]) == 1
    inputs = data["on"]["workflow_call"]["inputs"]
    assert set(inputs) == {"number", "head_ref", "head_sha", "head_repository"}
    assert not any(value["required"] for value in inputs.values())
    assert data["permissions"] == {"contents": "write", "pull-requests": "read", "issues": "read"}


def test_the_workflow_checks_out_no_code_of_the_head():
    (step,) = loaded()["jobs"]["delete"]["steps"]
    assert "uses" not in step and "${{" not in step["run"]


def test_the_workflow_is_shipped_and_its_copy_is_only_called():
    path = ".github/workflows/branch-cleanup.yml"
    assert path in se_workflows.SHIPPED
    copy = se_workflows.generate(WORKFLOW.read_text(encoding="utf-8"), path, "a" * 40, "alice/SE")
    data = yaml.safe_load(copy)
    assert set(data[True]) == {"workflow_call"}
    assert "pull_request_target:" not in copy.split("jobs:", 1)[0]


def test_the_readme_s_trigger_file_calls_the_copy_with_every_input():
    readme = page("running")
    block = readme.split("name: branch-cleanup-on-close\n", 1)[1].split("```", 1)[0]
    trigger = yaml.safe_load("name: branch-cleanup-on-close\n" + block)
    (job,) = trigger["jobs"].values()
    assert job["uses"] == "./.github/workflows/branch-cleanup.yml"
    assert set(job["with"]) == set(loaded()["on"]["workflow_call"]["inputs"])
    assert trigger[True] == {"pull_request_target": {"types": ["closed"]},
                             "schedule": loaded()["on"]["schedule"]}
    assert trigger["permissions"] == loaded()["permissions"]
