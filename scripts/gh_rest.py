# se:template se/python-module 1.0.0
"""gh's porcelain over GitHub's REST API, for a `gh` that is not signed in but whose REST API answers.

Reader: whoever changes how SE reads or writes GitHub where `gh auth status` fails but `gh api`
answers (Claude Code's cloud: its proxy signs each REST call and refuses GraphQL), or adds a `gh`
porcelain call to SE's scripts.

`work_tickets.run_gh` hands each porcelain call here (`translates`) once its door has found `gh` in
REST mode (`work_tickets.gh_backend`); `run` answers it with REST calls through `api`, the door's
`gh api`, and returns what gh's porcelain prints: the JSON of `--json <fields>` under gh's field
names (`--jq .<field>` taking one), the URL a create, comment or edit prints. GraphQL is never
called: `gh issue`, `gh pr` and `gh label` reach it, `gh api <path>` and `gh run` do not.

- Lists page through the REST API, 100 to a page, until `--limit` items or a short page; a list of
  issues leaves out the pull requests the REST API lists with them.
- Ids are the REST API's numbers, as the GitHub tools give them; the fields gh names alike
  (`url`, a page address; `state` in capitals) keep gh's form.
- A label change reads the issue's labels and writes the whole list in the one update, so a label
  that is not there is not an error.
- A form or `--json` field this module does not know is refused (`GhRestError`), naming it, so a
  new call is added here rather than reaching GraphQL.

Everything here is pure but `api`, which the caller passes.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

#: The REST call the caller makes: method, path below the API root (`repos/<owner>/<repo>/...`,
#: `search/issues?...`), the JSON body or None, the host (None for github.com); the parsed answer.
Api = Callable[[str, str, "dict[str, object] | None", "str | None"], object]

PAGE = 100
DEFAULT_LIMIT = 30  # gh's own default for `issue list` and `pr list`
VALUED = frozenset({
    "--state", "--label", "--search", "--json", "--limit", "--repo", "-R", "--jq", "--title",
    "--body", "--body-file", "--add-label", "--remove-label", "--add-assignee",
    "--remove-assignee", "--assignee", "--base", "--head", "--color", "--description", "--reason",
    "--comment",
})
FLAGS = frozenset({"--draft", "--force"})
CLOSE_REASONS = {"completed": "completed", "not planned": "not_planned", "not_planned": "not_planned"}


class GhRestError(Exception):
    """A gh call this module cannot answer over REST."""


@dataclass
class Call:
    """One porcelain call, parsed: its group and verb (`issue`, `list`), positional words, each
    option's values in order, the flags given."""

    group: str
    verb: str
    positional: list[str] = field(default_factory=list)
    options: dict[str, list[str]] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)

    def one(self, name: str, default: str = "") -> str:
        values = self.options.get(name)
        return values[-1] if values else default

    def many(self, name: str) -> list[str]:
        """Every value of a repeatable option, comma lists split as gh splits them."""
        return [part.strip() for value in self.options.get(name, []) for part in value.split(",")
                if part.strip()]

    def number(self) -> int:
        if not self.positional or not self.positional[0].lstrip("#").isdigit():
            raise GhRestError(f"gh {self.group} {self.verb} over REST needs a number, got "
                              f"{self.positional!r}")
        return int(self.positional[0].lstrip("#"))


def translates(arguments: list[str]) -> bool:
    """Whether `arguments` is gh porcelain that reaches GraphQL, which `run` answers over REST."""
    return bool(arguments) and arguments[0] in ("issue", "pr", "label")


def parse(arguments: list[str]) -> Call:
    if len(arguments) < 2:
        raise GhRestError(f"gh {' '.join(arguments)}: no verb")
    call = Call(arguments[0], arguments[1])
    words = iter(arguments[2:])
    for word in words:
        name, equals, inline = word.partition("=")
        if name in VALUED:
            value = inline if equals else next(words, None)
            if value is None:
                raise GhRestError(f"gh {call.group} {call.verb}: {name} has no value")
            call.options.setdefault("--repo" if name == "-R" else name, []).append(value)
        elif word in FLAGS:
            call.flags.add(word)
        elif word.startswith("-"):
            raise GhRestError(f"gh {call.group} {call.verb}: the option {word} is not answered "
                              "over REST; add it to scripts/gh_rest.py")
        else:
            call.positional.append(word)
    return call


def where(call: Call, default_repo: str) -> tuple[str, str | None]:
    """`owner/repo` and its host (None for github.com) from `--repo [host/]owner/repo`, else the
    default."""
    repo = call.one("--repo") or default_repo
    parts = [part for part in repo.split("/") if part]
    if len(parts) == 2:
        return "/".join(parts), None
    if len(parts) == 3:
        return "/".join(parts[1:]), None if parts[0] == "github.com" else parts[0]
    raise GhRestError(f"No repository for gh {call.group} {call.verb}: {repo!r}")


def body_of(call: Call, read: Callable[[str], str]) -> str | None:
    if "--body-file" in call.options:
        return read(call.one("--body-file"))
    return call.one("--body") if "--body" in call.options else None


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def run(arguments: list[str], api: Api, default_repo: str,
        read: Callable[[str], str] = read_text) -> str:
    """What gh prints for the porcelain call `arguments`, answered through `api` over REST."""
    call = parse(arguments)
    slug, host = where(call, default_repo)
    handler = HANDLERS.get((call.group, call.verb))
    if handler is None:
        raise GhRestError(f"gh {call.group} {call.verb} is not answered over REST; add it to "
                          "scripts/gh_rest.py")

    def rest(method: str, path: str, data: dict[str, object] | None = None) -> object:
        return api(method, path, data, host)

    return handler(call, Repo(slug, rest), lambda: body_of(call, read))


@dataclass(frozen=True)
class Repo:
    """One repository's REST calls."""

    slug: str
    rest: Callable[..., object]

    def get(self, path: str) -> object:
        return self.rest("GET", f"repos/{self.slug}/{path}")

    def write(self, method: str, path: str, data: dict[str, object]) -> object:
        return self.rest(method, f"repos/{self.slug}/{path}", data)

    def pages(self, path: str, limit: int, keep: Callable[[dict[str, object]], bool] = lambda _: True,
              items: str = "", top: bool = False) -> list[dict[str, object]]:
        """Up to `limit` items of the listing `path`, page by page; `items` names the key a search
        answer holds them under, `top` a path below the API root rather than the repository."""
        found: list[dict[str, object]] = []
        joiner = "&" if "?" in path else "?"
        for page in range(1, max(1, math.ceil(limit / PAGE)) + 1):
            paged = f"{path}{joiner}per_page={PAGE}&page={page}"
            answer = self.rest("GET", paged) if top else self.get(paged)
            listed = (answer or {}).get(items, []) if items else answer
            if not isinstance(listed, list):
                raise GhRestError(f"GitHub answered no list for {path}")
            found += [item for item in listed if isinstance(item, dict) and keep(item)]
            if len(listed) < PAGE or len(found) >= limit:
                break
        return found[:limit]


def limit_of(call: Call) -> int:
    value = call.one("--limit", str(DEFAULT_LIMIT))
    if not value.isdigit() or int(value) < 1:
        raise GhRestError(f"gh {call.group} {call.verb}: --limit {value!r} is no positive number")
    return int(value)


def login(user: object) -> dict[str, object]:
    return {"login": user.get("login", ""), "is_bot": user.get("type") == "Bot"} \
        if isinstance(user, dict) else {"login": ""}


def labels_of(item: dict[str, object]) -> list[dict[str, object]]:
    return [{"id": label.get("node_id", ""), "name": label.get("name", ""),
             "description": label.get("description") or "", "color": label.get("color", "")}
            if isinstance(label, dict) else {"name": str(label)} for label in item.get("labels") or []]


def comment_shape(comment: dict[str, object]) -> dict[str, object]:
    return {"id": comment.get("id"), "author": login(comment.get("user")),
            "authorAssociation": comment.get("author_association", ""),
            "body": comment.get("body") or "", "createdAt": comment.get("created_at", ""),
            "url": comment.get("html_url", "")}


ISSUE_FIELDS: dict[str, Callable[[dict[str, object]], object]] = {
    "number": lambda item: item.get("number"),
    "title": lambda item: item.get("title") or "",
    "body": lambda item: item.get("body") or "",
    "url": lambda item: item.get("html_url", ""),
    "state": lambda item: str(item.get("state", "")).upper(),
    "stateReason": lambda item: str(item.get("state_reason") or "").upper(),
    "labels": labels_of,
    "assignees": lambda item: [login(user) for user in item.get("assignees") or []],
    "author": lambda item: login(item.get("user")),
    "authorAssociation": lambda item: item.get("author_association", ""),
    "createdAt": lambda item: item.get("created_at", ""),
    "updatedAt": lambda item: item.get("updated_at", ""),
    "closedAt": lambda item: item.get("closed_at") or "",
    "id": lambda item: item.get("node_id", ""),
}
PULL_FIELDS: dict[str, Callable[[dict[str, object]], object]] = {
    **{name: ISSUE_FIELDS[name] for name in (
        "number", "title", "body", "url", "labels", "assignees", "author", "createdAt",
        "updatedAt", "closedAt", "id")},
    "state": lambda item: "MERGED" if item.get("merged_at") else str(item.get("state", "")).upper(),
    "isDraft": lambda item: bool(item.get("draft")),
    "headRefName": lambda item: (item.get("head") or {}).get("ref", ""),
    "headRefOid": lambda item: (item.get("head") or {}).get("sha", ""),
    "baseRefName": lambda item: (item.get("base") or {}).get("ref", ""),
    "mergedAt": lambda item: item.get("merged_at") or "",
}


def fields_of(call: Call, known: dict[str, Callable[..., object]], extra: set[str] = frozenset()
              ) -> list[str]:
    names = call.many("--json")
    if not names:
        raise GhRestError(f"gh {call.group} {call.verb} over REST prints JSON only: pass --json")
    unknown = sorted(set(names) - set(known) - extra)
    if unknown:
        raise GhRestError(f"gh {call.group} {call.verb}: the field(s) {', '.join(unknown)} are not "
                          "answered over REST; add them to scripts/gh_rest.py")
    return names


def shaped(item: dict[str, object], names: list[str], known: dict[str, Callable[..., object]],
           comments: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {name: [comment_shape(comment) for comment in comments or []] if name == "comments"
            else known[name](item) for name in names}


def printed(call: Call, value: object) -> str:
    """What gh prints for `value`: its JSON, or with `--jq .<field>` that field, a string raw."""
    query = call.one("--jq")
    if query:
        if not query.startswith(".") or not query[1:].isidentifier():
            raise GhRestError(f"gh {call.group} {call.verb}: --jq {query!r} is not answered over "
                              "REST; it takes one .<field>")
        value = value.get(query[1:]) if isinstance(value, dict) else None
        return (value if isinstance(value, str) else json.dumps(value)) + "\n"
    return json.dumps(value) + "\n"


def comments_of(repo: Repo, number: int, count: int) -> list[dict[str, object]]:
    return repo.pages(f"issues/{number}/comments", max(count, 1)) if count else []


def issue_list(call: Call, repo: Repo, _body) -> str:
    state, labels, limit = call.one("--state", "open"), call.many("--label"), limit_of(call)
    names = fields_of(call, ISSUE_FIELDS, {"comments"})
    search = call.one("--search")
    if search:
        terms = [f"repo:{repo.slug}", "is:issue",
                 *([] if state == "all" else [f"state:{state}"]),
                 *(f'label:"{label}"' for label in labels), search]
        found = repo.pages("search/issues?" + urlencode({"q": " ".join(terms)}), limit,
                           items="items", top=True)
    else:
        query = {"state": state, **({"labels": ",".join(labels)} if labels else {})}
        found = repo.pages("issues?" + urlencode(query), limit,
                           keep=lambda item: "pull_request" not in item)
    return printed(call, [shaped(item, names, ISSUE_FIELDS, comments_of(
        repo, int(item["number"]), int(item.get("comments") or 0)) if "comments" in names else None)
        for item in found])


def issue_view(call: Call, repo: Repo, _body) -> str:
    number = call.number()
    names = fields_of(call, ISSUE_FIELDS, {"comments"})
    item = repo.get(f"issues/{number}")
    comments = (comments_of(repo, number, int(item.get("comments") or 0))
                if "comments" in names else None)
    return printed(call, shaped(item, names, ISSUE_FIELDS, comments))


def issue_edit(call: Call, repo: Repo, body) -> str:
    number = call.number()
    change: dict[str, object] = {}
    if "--title" in call.options:
        change["title"] = call.one("--title")
    text = body()
    if text is not None:
        change["body"] = text
    added, removed = call.many("--add-label"), set(call.many("--remove-label"))
    if added or removed:
        have = [label["name"] for label in labels_of(repo.get(f"issues/{number}"))]
        change["labels"] = [*(name for name in have if name not in removed),
                            *(name for name in added if name not in have and name not in removed)]
    assignees = call.many("--add-assignee")
    if assignees:
        repo.write("POST", f"issues/{number}/assignees", {"assignees": assignees})
    if call.many("--remove-assignee"):
        repo.write("DELETE", f"issues/{number}/assignees",
                   {"assignees": call.many("--remove-assignee")})
    answer = repo.write("PATCH", f"issues/{number}", change) if change else repo.get(f"issues/{number}")
    return f"{(answer or {}).get('html_url', '')}\n"


def issue_comment(call: Call, repo: Repo, body) -> str:
    text = body()
    if text is None:
        raise GhRestError("gh issue comment over REST needs --body-file or --body")
    answer = repo.write("POST", f"issues/{call.number()}/comments", {"body": text})
    return f"{(answer or {}).get('html_url', '')}\n"


def issue_close(call: Call, repo: Repo, _body) -> str:
    number = call.number()
    if call.one("--comment"):
        repo.write("POST", f"issues/{number}/comments", {"body": call.one("--comment")})
    reason = call.one("--reason", "completed").lower()
    if reason not in CLOSE_REASONS:
        raise GhRestError(f"gh issue close: --reason {reason!r} is neither completed nor not planned")
    repo.write("PATCH", f"issues/{number}", {"state": "closed", "state_reason": CLOSE_REASONS[reason]})
    return ""


def issue_create(call: Call, repo: Repo, body) -> str:
    data: dict[str, object] = {"title": call.one("--title"), "body": body() or ""}
    if call.many("--label"):
        data["labels"] = call.many("--label")
    if call.many("--assignee"):
        data["assignees"] = call.many("--assignee")
    answer = repo.write("POST", "issues", data)
    return f"{(answer or {}).get('html_url', '')}\n"


LABEL_FIELDS: dict[str, Callable[[dict[str, object]], object]] = {
    "name": lambda item: item.get("name", ""),
    "color": lambda item: item.get("color", ""),
    "description": lambda item: item.get("description") or "",
    "id": lambda item: item.get("node_id", ""),
}


def label_list(call: Call, repo: Repo, _body) -> str:
    names = fields_of(call, LABEL_FIELDS)
    return printed(call, [shaped(item, names, LABEL_FIELDS)
                          for item in repo.pages("labels", limit_of(call))])


def label_create(call: Call, repo: Repo, _body) -> str:
    if not call.positional:
        raise GhRestError("gh label create over REST needs the label's name")
    data = {"name": call.positional[0], "color": call.one("--color", "ededed").lstrip("#"),
            "description": call.one("--description")}
    if "--force" in call.flags:
        repo.write("PATCH", f"labels/{quote(call.positional[0], safe='')}", data)
    else:
        repo.write("POST", "labels", data)
    return ""


def pr_list(call: Call, repo: Repo, _body) -> str:
    names = fields_of(call, PULL_FIELDS)
    query = {"state": call.one("--state", "open")}
    if call.one("--base"):
        query["base"] = call.one("--base")
    if call.one("--head"):
        query["head"] = f"{repo.slug.split('/')[0]}:{call.one('--head')}"
    return printed(call, [shaped(item, names, PULL_FIELDS)
                          for item in repo.pages("pulls?" + urlencode(query), limit_of(call))])


def pr_view(call: Call, repo: Repo, _body) -> str:
    names = fields_of(call, PULL_FIELDS)
    return printed(call, shaped(repo.get(f"pulls/{call.number()}"), names, PULL_FIELDS))


def pr_create(call: Call, repo: Repo, body) -> str:
    data: dict[str, object] = {"title": call.one("--title"), "head": call.one("--head"),
                               "base": call.one("--base"), "body": body() or ""}
    if "--draft" in call.flags:
        data["draft"] = True
    answer = repo.write("POST", "pulls", data)
    return f"{(answer or {}).get('html_url', '')}\n"


def pr_edit(call: Call, repo: Repo, body) -> str:
    change: dict[str, object] = {}
    for option, key in (("--title", "title"), ("--base", "base")):
        if option in call.options:
            change[key] = call.one(option)
    text = body()
    if text is not None:
        change["body"] = text
    answer = repo.write("PATCH", f"pulls/{call.number()}", change)
    return f"{(answer or {}).get('html_url', '')}\n"


def pr_comment(call: Call, repo: Repo, body) -> str:
    return issue_comment(call, repo, body)


HANDLERS: dict[tuple[str, str], Callable[[Call, Repo, Callable[[], str | None]], str]] = {
    ("issue", "list"): issue_list,
    ("issue", "view"): issue_view,
    ("issue", "edit"): issue_edit,
    ("issue", "comment"): issue_comment,
    ("issue", "close"): issue_close,
    ("issue", "create"): issue_create,
    ("label", "list"): label_list,
    ("label", "create"): label_create,
    ("pr", "list"): pr_list,
    ("pr", "view"): pr_view,
    ("pr", "create"): pr_create,
    ("pr", "edit"): pr_edit,
    ("pr", "comment"): pr_comment,
}
