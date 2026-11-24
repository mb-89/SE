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
    """GitHub's REST API as the script sees it: the repository's branches, its open pull requests
    and every call, with the deletes it was asked for."""

    def __init__(self, branches: dict[str, str], pulls: list[dict], default: str = "main") -> None:
        self.branches, self.pulls, self.default = branches, pulls, default
        self.calls: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def answer(self, status: int, body: object = None) -> "Response":
        return Response(status, json.dumps(body).encode() if body is not None else b"")

    def urlopen(self, request: urllib.request.Request):
        url = urllib.parse.urlsplit(request.full_url)
        path, method = urllib.parse.unquote(url.path), request.get_method()
        self.calls.append((method, path))
        assert request.get_header("Authorization") == "Bearer token"
        prefix = f"/repos/{REPOSITORY}"
        if method == "GET" and path == prefix:
            return self.answer(200, {"default_branch": self.default})
        if method == "GET" and path == f"{prefix}/pulls":
            query = urllib.parse.parse_qs(url.query)
            assert query["state"] == ["open"]
            head = query["head"][0].split(":", 1)[1]
            return self.answer(200, [pull for pull in self.pulls if pull["head"] == head])
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


def run(github: GitHub, tmp_path: Path, branch: str = "feat/topic-20261116", number: int = 7,
        head: str = REPOSITORY, sha: str = SHA) -> str:
    """Run the workflow's script on the close of pull request `number`; its summary."""
    summary = tmp_path / "summary.md"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(urllib.request, "urlopen", github.urlopen)
        for name, value in {"GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": REPOSITORY,
                            "GITHUB_API_URL": "https://api.example.com",
                            "GITHUB_STEP_SUMMARY": str(summary), "NUMBER": str(number),
                            "HEAD_REF": branch, "HEAD_SHA": sha, "HEAD_REPOSITORY": head}.items():
            patch.setenv(name, value)
        try:
            exec(compile(script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
        except SystemExit as exited:
            assert exited.code is None, exited.code
    return summary.read_text(encoding="utf-8")


def test_a_closed_pull_request_s_branch_is_deleted(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA, "main": "c" * 40}, [])
    assert run(github, tmp_path) == f"Branch cleanup: deleted feat/topic-20261116 of #7 at {SHA[:12]}.\n"
    assert github.deleted == ["feat/topic-20261116"]
    assert github.branches == {"main": "c" * 40}


def test_a_fork_s_branch_is_kept_without_a_call(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [])
    assert run(github, tmp_path, head="mallory/project") == (
        "Branch cleanup: kept feat/topic-20261116 of #7: its head repository mallory/project is not "
        f"{REPOSITORY}.\n")
    assert github.calls == [] and github.deleted == []


def test_a_deleted_fork_is_kept_too(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [])
    assert "its head repository (deleted) is not" in run(github, tmp_path, head="")
    assert github.deleted == []


@pytest.mark.parametrize("branch", ["main", "trunk", "se", "rehearsal", "ccr-session", "claude/topic"])
def test_a_protected_branch_is_kept(tmp_path, branch):
    github = GitHub({branch: SHA}, [], default="trunk")
    assert run(github, tmp_path, branch=branch) == f"Branch cleanup: kept {branch} of #7: it is a protected branch.\n"
    assert github.deleted == []


def test_a_branch_another_open_pull_request_heads_is_kept(tmp_path):
    github = GitHub({"feat/topic-20261116": SHA}, [{"number": 7, "head": "feat/topic-20261116"},
                                                   {"number": 9, "head": "feat/topic-20261116"},
                                                   {"number": 8, "head": "feat/other"}])
    assert run(github, tmp_path) == ("Branch cleanup: kept feat/topic-20261116 of #7: it is the head of the "
                                     "open pull request #9.\n")
    assert github.deleted == []


def test_a_branch_that_moved_since_the_pull_request_s_head_is_kept(tmp_path):
    github = GitHub({"feat/topic-20261116": "d" * 40}, [])
    assert run(github, tmp_path) == ("Branch cleanup: kept feat/topic-20261116 of #7: it moved to "
                                     f"{'d' * 12} since the pull request's head {SHA[:12]}.\n")
    assert github.deleted == []


def test_a_branch_already_gone_is_a_success_with_a_note(tmp_path):
    github = GitHub({}, [])
    assert run(github, tmp_path) == "Branch cleanup: feat/topic-20261116 of #7 is already gone.\n"
    assert not any(method == "DELETE" for method, _ in github.calls)


def test_the_workflow_runs_only_on_a_closed_pull_request_or_a_call():
    data = loaded()
    assert set(data["on"]) == {"workflow_call", "pull_request"}
    assert data["on"]["pull_request"] == {"types": ["closed"]}
    assert set(data["on"]["workflow_call"]["inputs"]) == {"number", "head_ref", "head_sha", "head_repository"}
    assert data["permissions"] == {"contents": "write", "pull-requests": "read"}


def test_the_workflow_is_shipped_and_its_copy_is_only_called():
    path = ".github/workflows/branch-cleanup.yml"
    assert path in se_workflows.SHIPPED
    copy = se_workflows.generate(WORKFLOW.read_text(encoding="utf-8"), path, "a" * 40, "alice/SE")
    data = yaml.safe_load(copy)
    assert set(data[True]) == {"workflow_call"}
    assert "pull_request:" not in copy.split("jobs:", 1)[0]


def test_the_readme_s_trigger_file_calls_the_copy_with_every_input():
    readme = page("running")
    block = readme.split("name: branch-cleanup-on-close\n", 1)[1].split("```", 1)[0]
    trigger = yaml.safe_load("name: branch-cleanup-on-close\n" + block)
    (job,) = trigger["jobs"].values()
    assert job["uses"] == "./.github/workflows/branch-cleanup.yml"
    assert set(job["with"]) == set(loaded()["on"]["workflow_call"]["inputs"])
    assert trigger[True] == {"pull_request": {"types": ["closed"]}}
    assert trigger["permissions"] == loaded()["permissions"]
