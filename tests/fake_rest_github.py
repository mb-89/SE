"""GitHub's REST API in memory, answering `gh` as Claude Code's cloud does: `gh auth status` fails,
`gh api` answers, and the porcelain that reaches GraphQL (`gh issue`, `gh pr`, `gh label`) is
refused with HTTP 403.

Reader: whoever writes a test of a command where gh reaches GitHub over REST alone
(scripts/gh_rest.py, `work_tickets.gh_backend`), or changes the routes the REST door calls.

A test hands a `RestGitHub` to the process door's fake (`fake_processes.on("gh", github)`) and
fills it with issues, comments, labels and pull requests (`issue`, `pull`); each REST call is
answered from them and each write changes them, so a command's reads after its writes see them.
`calls` records every gh call's words, `writes` every write as `(method, path, body)`. A route it
does not know answers 404, naming it. `signed_in=True` makes `gh auth status` pass, as a signed-in
gh's; `rest=False` refuses `gh api` too, as a host with no account; `host` names the host its page
addresses carry; a repository in `unreachable` answers 404 to every call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import fake_processes as fake_programs

GRAPHQL_REFUSED = ("HTTP 403: GitHub GraphQL is not available from Claude Code sessions; use the "
                   "REST API (gh api repos/{owner}/{repo}/...). (https://api.github.com/graphql)\n")
HOST = "github.com"


@dataclass
class RestGitHub:
    signed_in: bool = False
    rest: bool = True
    host: str = HOST
    unreachable: set[str] = field(default_factory=set)
    issues: dict[str, dict[int, dict]] = field(default_factory=dict)
    comments: dict[tuple[str, int], list[dict]] = field(default_factory=dict)
    labels: dict[str, list[dict]] = field(default_factory=dict)
    pulls: dict[str, dict[int, dict]] = field(default_factory=dict)
    check_runs: dict[str, list[dict]] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    writes: list[tuple[str, str, object]] = field(default_factory=list)
    next_id: int = 1000

    # Filling ------------------------------------------------------------------------------------

    def issue(self, slug: str, number: int, title: str, body: str = "", labels=(), state="open",
              comments=(), assignees=(), **extra) -> dict:
        """Issue `number` of `slug` (`owner/repo`), with comments given as bodies or dicts."""
        item = {
            "id": number * 10, "node_id": f"I_{number}", "number": number, "title": title,
            "body": body, "state": state, "state_reason": None,
            "html_url": f"https://{self.host}/{slug}/issues/{number}",
            "labels": [self.label(slug, name) for name in labels],
            "assignees": [{"login": login, "type": "User"} for login in assignees],
            "user": {"login": slug.split("/")[0], "type": "User"}, "author_association": "OWNER",
            "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-02T00:00:00Z",
            "closed_at": None, "comments": 0, **extra,
        }
        self.issues.setdefault(slug, {})[number] = item
        for comment in comments:
            self.add_comment(slug, number, comment if isinstance(comment, dict) else {"body": comment})
        return item

    def label(self, slug: str, name: str) -> dict:
        listed = self.labels.setdefault(slug, [])
        found = next((label for label in listed if label["name"] == name), None)
        if found is None:
            found = {"name": name, "color": "ededed", "description": "", "node_id": f"L_{name}"}
            listed.append(found)
        return found

    def pull(self, slug: str, number: int, title: str, head: str, base: str = "main", body: str = "",
             sha: str = "0" * 40, **extra) -> dict:
        item = {
            "id": number * 10, "node_id": f"PR_{number}", "number": number, "title": title,
            "body": body, "state": "open", "draft": False, "merged_at": None,
            "html_url": f"https://{self.host}/{slug}/pull/{number}",
            "head": {"ref": head, "sha": sha}, "base": {"ref": base}, "labels": [],
            "user": {"login": "worker", "type": "User"}, "assignees": [],
            "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-02T00:00:00Z", **extra,
        }
        self.pulls.setdefault(slug, {})[number] = item
        return item

    def add_comment(self, slug: str, number: int, data: dict) -> dict:
        self.next_id += 1
        comment = {"id": self.next_id, "node_id": f"IC_{self.next_id}", "body": data.get("body", ""),
                   "user": {"login": data.get("login", slug.split("/")[0]), "type": "User"},
                   "author_association": data.get("author_association", "OWNER"),
                   "created_at": data.get("created_at", "2026-11-03T00:00:00Z"),
                   "html_url": f"https://{self.host}/{slug}/issues/{number}#issuecomment-{self.next_id}"}
        self.comments.setdefault((slug, number), []).append(comment)
        if number in self.issues.get(slug, {}):
            self.issues[slug][number]["comments"] += 1
        return comment

    def label_names(self, slug: str, number: int) -> list[str]:
        return [label["name"] for label in self.issues[slug][number]["labels"]]

    # Answering ----------------------------------------------------------------------------------

    def __call__(self, invocation) -> fake_programs.Answer:
        words = invocation.words[1:]
        self.calls.append(words)
        if words[:2] == ["auth", "status"]:
            return (fake_programs.Answer(0, "", "Logged in to github.com\n") if self.signed_in else
                    fake_programs.Answer(1, "", "X Failed to log in to github.com using token "
                                                "(GH_TOKEN)\n"))
        if words[:1] != ["api"] or words[1:2] == ["graphql"]:
            return fake_programs.Answer(1, "", GRAPHQL_REFUSED)
        if not self.rest:
            return fake_programs.Answer(1, "", "HTTP 401: Bad credentials\n")
        method, path, body, jq = parse_api(words[1:])
        try:
            answer = self.route(method, path, body)
        except LookupError as error:
            return fake_programs.Answer(1, "", f"gh: Not Found (HTTP 404): {error}\n")
        if jq:
            value = answer.get(jq.lstrip(".")) if isinstance(answer, dict) else None
            return fake_programs.Answer(0, f"{value}\n")
        return fake_programs.Answer(0, json.dumps(answer))

    def route(self, method: str, path: str, body: dict | None) -> object:
        parts = urlsplit(path)
        query = {key: values[-1] for key, values in parse_qs(parts.query).items()}
        segments = [unquote(segment) for segment in parts.path.strip("/").split("/")]
        if segments == ["rate_limit"]:
            return {"rate": {"limit": 5000, "remaining": 4999}}
        if segments == ["search", "issues"]:
            return {"items": self.search(query["q"])}
        if segments[0] != "repos" or len(segments) < 4:
            raise LookupError(path)
        slug, rest = "/".join(segments[1:3]), segments[3:]
        if slug in self.unreachable:
            raise LookupError(path)
        if method != "GET":
            self.writes.append((method, "/".join(rest), body))
        page = int(query.get("page", 1)), int(query.get("per_page", 30))
        if rest == ["issues"]:
            if method == "POST":
                number = max([*self.issues.get(slug, {}), *self.pulls.get(slug, {}), 0]) + 1
                return self.issue(slug, number, body["title"], body.get("body", ""),
                                  body.get("labels", ()), assignees=body.get("assignees", ()))
            return paged(self.issue_list(slug, query), *page)
        if rest[0] == "issues" and len(rest) >= 2:
            number = int(rest[1])
            # A pull request is an issue to the REST API: its comments are the issue's.
            item = self.issues.get(slug, {}).get(number) or self.pulls.get(slug, {}).get(number)
            if item is None:
                raise LookupError(path)
            if rest[2:] == ["comments"]:
                if method == "POST":
                    return self.add_comment(slug, number, body)
                return paged(self.comments.get((slug, number), []), *page)
            if rest[2:] == ["assignees"]:
                item["assignees"] += [{"login": login, "type": "User"} for login in body["assignees"]]
                return item
            if rest[2:] == []:
                if method == "PATCH":
                    for key, value in body.items():
                        item[key] = ([self.label(slug, name) for name in value] if key == "labels"
                                     else value)
                    if body.get("state") == "closed":
                        item["closed_at"] = "2026-11-24T00:00:00Z"
                return item
        if rest == ["labels"]:
            if method == "POST":
                return self.label(slug, body["name"]) | {"color": body.get("color", "ededed")}
            return paged(self.labels.get(slug, []), *page)
        if rest == ["pulls"]:
            if method == "POST":
                number = max([*self.issues.get(slug, {}), *self.pulls.get(slug, {}), 0]) + 1
                return self.pull(slug, number, body["title"], body["head"], body["base"],
                                 body.get("body", ""))
            found = [pull for pull in self.pulls.get(slug, {}).values()
                     if pull["state"] == query.get("state", "open")
                     and ("base" not in query or pull["base"]["ref"] == query["base"])
                     and ("head" not in query or pull["head"]["ref"] == query["head"].split(":", 1)[-1])]
            return paged(found, *page)
        if rest[0] == "pulls" and len(rest) == 2:
            pull = self.pulls.get(slug, {}).get(int(rest[1]))
            if pull is None:
                raise LookupError(path)
            if method == "PATCH":
                pull.update(body)
            return pull
        if rest[:3] == ["git", "matching-refs", "heads"]:
            return []
        if rest[0] == "commits" and rest[2:] == ["check-runs"]:
            return {"check_runs": self.check_runs.get(rest[1], [])}
        raise LookupError(path)

    def issue_list(self, slug: str, query: dict[str, str]) -> list[dict]:
        wanted = [name for name in query.get("labels", "").split(",") if name]
        state = query.get("state", "open")
        found = [item for item in self.issues.get(slug, {}).values()
                 if state in ("all", item["state"])
                 and all(name in [label["name"] for label in item["labels"]] for name in wanted)]
        listed = sorted(found, key=lambda item: -item["number"])
        # The REST API lists pull requests among the issues: gh_rest leaves them out.
        return [*listed, *({"number": pull["number"], "title": pull["title"], "pull_request": {}}
                           for pull in self.pulls.get(slug, {}).values() if state != "closed")]

    def search(self, q: str) -> list[dict]:
        slug = re.search(r"repo:(\S+)", q)[1]
        state = (re.search(r"state:(\w+)", q) or [None, "all"])[1]
        title = (re.search(r'"([^"]+)" in:title', q) or [None, ""])[1]
        return [item for item in self.issue_list(slug, {"state": state})
                if "pull_request" not in item and title in item["title"]]


def parse_api(words: list[str]) -> tuple[str, str, dict | None, str]:
    """`gh api`'s method, path, JSON body (its --input file, else its -f/-F fields) and --jq."""
    method, path, body, fields, jq = "GET", "", None, {}, ""
    items = iter(words)
    for word in items:
        if word == "-X":
            method = next(items)
        elif word == "--input":
            body = json.loads(Path(next(items)).read_text(encoding="utf-8"))
        elif word in ("-f", "-F"):
            key, _, value = next(items).partition("=")
            fields[key] = value
        elif word == "--jq":
            jq = next(items)
        elif word == "--hostname":
            next(items)
        elif not path:
            path = word
    if fields and body is None and method != "GET":
        body = fields
    return method, path, body, jq


def paged(items: list[dict], page: int, per_page: int) -> list[dict]:
    return items[(page - 1) * per_page:page * per_page]
