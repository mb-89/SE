#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""Build the Timeline: one obs table of the repositories in se.toml `[timeline]`, newest first.

The page builds itself from GitHub, so nobody maintains it: one read, then pure, then obs.

- Read: for each repository, one batched pass on GitHub's GraphQL API, which needs a token
  (`GITHUB_TOKEN`, in the workflow its own): each request carries a page of its issues (open and
  closed), a page of its tags and a page of its open pull requests, 100 each, until all are read;
  never a request per issue, tag or pull request. The first request also reads the repository's
  `se.toml` at its default branch, for its integration branch (`[project] integration_branch`,
  `main` where it names none). Of a pull request the snapshot keeps its number, link and base, the
  issue its description's first line names (`pr_issues.py`, the one parser of how a pull request
  names its issue) and whether it carries a field report (its `se:field-report` markers). The
  result is a snapshot (`--save-snapshot` writes it, `--snapshot` builds from one without the
  network).
- A repository GitHub refuses to the token (a private one the workflow's token cannot read, a name
  that does not exist) is one gap, not a failed build: the snapshot keeps it under `unreadable`
  with GitHub's answer, the page has no rows of it and names it, with that answer, above the
  table, and the command warns on stderr. Only where no repository can be read does the build fail.
- Compute: the rows come from the snapshot alone. Pull requests and field reports (label
  `field-report`) are left out. An issue goes to exactly one place:
  - closed as not planned or duplicate: hidden;
  - closed otherwise: Done, dated the day (UTC) it closed;
  - open and `backlogged`: Backlog;
  - open and delivered, named by an open pull request to its repository's integration branch that
    carries a field report: Waiting for integrator; its row keeps that pull request's link
    (`delivery`);
  - open and `in-progress`: Today;
  - open and `ready`: Next;
  - open and `se-person`: Needs you;
  - any other open issue: hidden.
  An open issue is dated the day it was opened. A release is a tag `v<major>.<minor>.<patch>`, a
  Done row dated the day (UTC) it was tagged.
- Status, from state, labels and delivery alone: done; waiting for your input (`backlogged`: a
  backlog idea waits for the person before it is work); needs you (`se-person`); delivered, waiting
  for the integrator; in progress; ready.
- Mark, what only the build knows: an open issue of Today, Next or Needs you whose body plans it (a
  line `Planned: yyyy-mm-dd`) is marked `planned <day>`, or `late, planned <day>` once the day has
  passed; it stays in its place. A delivered issue is marked with its pull request, `pull request
  #<n>`.
- Ages, a setting off when absent: `[timeline] ages = true` in the `--config` file (se.toml by
  default) also reads each issue's last label events in the same request and keeps `person_since`,
  when it was last labelled `se-person`; the mark of an issue that needs you (`se-person`, not
  `backlogged`) then says how long it has waited, in whole UTC calendar days to the read (`needs
  you, 3 days`, `needs you, 1 day`, `needs you, today`). An issue with no such event, or a snapshot
  saved without it, has no age. Absent or false, the query, the snapshot and the rows are those
  without the setting; any other value is refused.
- Show: the rows are obs notes, one per row, under a manifest whose one `base` table lists them in
  the scrolling layout (`vault`); obs builds the page (`build`). The table groups them by place
  (Today, Waiting for integrator, Needs you, Next, Backlog, Done), newest first in each, and pages them, `PAGE_SIZE` a page;
  obs's table filter offers each column's values, the repository and the place among them. Opening
  a row shows the first paragraph of its Goal and its link. The text above the table names the day
  of the snapshot; obs refuses a time of day in a page.
- Live: the table declares obs's live source (`live_source`): when the page opens, it asks GitHub's
  public REST list of each repository's issues, with no token, for what changed since an hour
  before the snapshot, and an issue that changed moves to the place and status its state and labels
  give; obs's line under the table then says "Showing current data". Where GitHub does not answer,
  the page shows the snapshot. The mark is never read live. Neither is delivery: obs's live source
  lays an item only over its own row, so a pull request cannot move the issue it names, and GitHub's
  issue list says nothing of pull requests. A delivered row stays Waiting for integrator until a
  read returns its issue changed, which then takes the place its state and labels give, until the
  next build.

Exit code 0: written, a gap included; 1: GitHub refused the read of every repository, or obs failed;
2: setup error. docs/documentation.md "Documentation" says where the page is published.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
import se_script

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "se.toml"
API = "https://api.github.com"

FIELD_REPORT = "field-report"
BACKLOGGED = "backlogged"
IN_PROGRESS = "in-progress"
READY = "ready"
PERSON = "se-person"
HIDDEN_REASONS = ("not_planned", "duplicate")
# A field report sits in a pull request's description between these markers (work_tickets.py
# REPORT_BEGIN and REPORT_END, which write it).
REPORT_BEGIN = "<!-- se:field-report -->"
REPORT_END = "<!-- se:field-report:end -->"
DEFAULT_INTEGRATION_BRANCH = "main"  # work model "Integration branch"

class ReadError(Exception):
    """GitHub refused the read."""


def repositories(config: Path = CONFIG, home=None) -> list[str]:
    """se.toml's `[timeline] repositories`: the one list of the repositories the page shows, each
    `<owner>/<repo>`; a bare `<repo>` lies beside the home of the config's checkout, read from its
    origin (`scripts/se_home.py`) where `home` is not given."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        names = data["timeline"]["repositories"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"timeline: {config} has no [timeline] repositories ({error})") from error
    if not names or not all(isinstance(name, str) and re.fullmatch(r"(?:[\w.-]+/)?[\w.-]+", name) for name in names):
        raise SystemExit(f"timeline: [timeline] repositories in {config} must be <repo> or <owner>/<repo> strings")
    if all("/" in name for name in names):
        return list(names)
    se_home = sibling("se_home")
    if home is None:
        try:
            home = se_home.home(config.parent)
        except se_home.NoHome as error:
            raise SystemExit(f"timeline: [timeline] repositories in {config} names a bare repository: {error}") from error
    return [name if "/" in name else f"{home.owner}/{name}" for name in names]


def ages_setting(config: Path = CONFIG) -> bool:
    """se.toml's `[timeline] ages`: whether the "needs you" marks say how long they have waited; off when absent."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except OSError:
        return False
    except tomllib.TOMLDecodeError as error:
        raise SystemExit(f"timeline: {config} does not parse ({error})") from error
    section = data.get("timeline", {})
    value = section.get("ages", False) if isinstance(section, dict) else False
    if not isinstance(value, bool):
        raise SystemExit(f"timeline: [timeline] ages in {config} must be true or false")
    return value


# --- Read -------------------------------------------------------------------------------------

# One query per page and repository: a page of its issues, of its tags and of its open pull requests,
# each with what the page needs, so the read never asks per issue, tag or pull request; the first
# page also brings the repository's se.toml. A connection already read to its end is
# left out of the next page's query.
QUERY = """
query($owner: String!, $name: String!, $issues: String, $tags: String, $pulls: String,
      $withIssues: Boolean!, $withTags: Boolean!, $withPulls: Boolean!, $withConfig: Boolean!) {
  repository(owner: $owner, name: $name) {
    config: object(expression: "HEAD:se.toml") @include(if: $withConfig) { ... on Blob { text } }
    issues(first: 100, after: $issues) @include(if: $withIssues) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url state stateReason createdAt closedAt body labels(first: 30) { nodes { name } } }
    }
    refs(refPrefix: "refs/tags/", first: 100, after: $tags) @include(if: $withTags) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          ... on Commit { committedDate }
          ... on Tag { tagger { date } target { ... on Commit { committedDate } } }
        }
      }
    }
    pullRequests(states: OPEN, first: 100, after: $pulls) @include(if: $withPulls) {
      pageInfo { hasNextPage endCursor }
      nodes { number url baseRefName body }
    }
  }
}
"""
# With `[timeline] ages` on, each issue also brings its last label events, in the same request.
LABEL_EVENTS = (" timelineItems(itemTypes: [LABELED_EVENT], last: 10)"
                " { nodes { ... on LabeledEvent { createdAt label { name } } } }")
AGES_QUERY = QUERY.replace("labels(first: 30) { nodes { name } } }",
                           "labels(first: 30) { nodes { name } }" + LABEL_EVENTS + " }")


def query(ages: bool = False) -> str:
    """The query one page and repository sends: today's, or with each issue's label events when ``ages``."""
    return AGES_QUERY if ages else QUERY


# A release is a tag v<major>.<minor>.<patch> (docs/settings.md "Release tags"); the moving v<major> is none.
RELEASE_TAG = re.compile(r"v\d+\.\d+\.\d+")

# A poster sends one GraphQL query with its variables and returns the response's `data`.
Poster = Callable[[str, dict], dict]


def http_poster(token: str) -> Poster:
    """A poster on GitHub's GraphQL API with ``token`` (in the workflow, its own token)."""

    def post(query: str, variables: dict) -> dict:
        request = urllib.request.Request(
            f"{API}/graphql", data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "se-timeline"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                answer = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ReadError(f"GitHub answered {error.code} to the GraphQL read") from error
        except urllib.error.URLError as error:
            raise ReadError(f"GitHub could not be reached: {error.reason}") from error
        if answer.get("errors"):
            raise ReadError("GitHub refused the read: " + "; ".join(e.get("message", "?") for e in answer["errors"]))
        return answer["data"]

    return post


def tag_date(target: dict | None) -> str | None:
    """When a tag was made: an annotated tag's tagger date, else its commit's date."""
    target = target or {}
    return ((target.get("tagger") or {}).get("date") or target.get("committedDate")
            or (target.get("target") or {}).get("committedDate"))


def person_since(issue: dict) -> str | None:
    """When an issue node was last labelled `se-person`: its newest such label event's `createdAt`, or None."""
    events = ((issue.get("timelineItems") or {}).get("nodes")) or []
    times = [event["createdAt"] for event in events
             if event and (event.get("label") or {}).get("name") == PERSON and event.get("createdAt")]
    return max(times, key=lambda stamp: datetime.fromisoformat(stamp.replace("Z", "+00:00"))) if times else None


def read(names: list[str], post: Poster, now: datetime, ages: bool = False) -> dict:
    """The snapshot: per repository, its issues and its releases, as read at ``now``.

    GraphQL's issues are issues only; pull requests are never read. With ``ages`` each issue also
    keeps `person_since` ([timeline] ages); without it the snapshot is the same as before the setting.
    A repository whose read GitHub refuses goes under `unreadable` with the refusal; where every
    one is refused, the read fails.
    """
    snapshot: dict = {"read_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "repositories": {}}
    unreadable: dict[str, str] = {}
    for name in names:
        try:
            snapshot["repositories"][name] = read_repository(name, post, ages)
        except ReadError as error:
            unreadable[name] = str(error)
    if unreadable and not snapshot["repositories"]:
        raise ReadError("; ".join(f"{name}: {reason}" for name, reason in unreadable.items()))
    if unreadable:
        snapshot["unreadable"] = unreadable
    return snapshot


def read_repository(name: str, post: Poster, ages: bool) -> dict:
    """One repository's issues and releases, in one batched pass."""
    owner, repo = name.split("/", 1)
    issues: list[dict] = []
    tags: list[dict] = []
    pulls: list[dict] = []
    config: str | None = None
    cursors: dict[str, str | None] = {"issues": None, "tags": None, "pulls": None}
    more = {"issues": True, "tags": True, "pulls": True}
    first = True
    while any(more.values()):
        data = post(query(ages), {"owner": owner, "name": repo, **cursors, "withIssues": more["issues"],
                                  "withTags": more["tags"], "withPulls": more["pulls"], "withConfig": first})
        repository = data.get("repository")
        if repository is None:
            raise ReadError(f"GitHub returned no repository {name}; check [timeline] in se.toml")
        if first:
            config = (repository.get("config") or {}).get("text")
            first = False
        for key, field, into in (("issues", "issues", issues), ("tags", "refs", tags),
                                 ("pulls", "pullRequests", pulls)):
            if more[key]:
                connection = repository[field]
                into.extend(connection["nodes"])
                more[key] = connection["pageInfo"]["hasNextPage"]
                cursors[key] = connection["pageInfo"]["endCursor"]
    return {
        "issues": [{
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "state": issue["state"].lower(),
            "state_reason": (issue.get("stateReason") or "").lower() or None,
            "created_at": issue.get("createdAt"),
            "closed_at": issue.get("closedAt"),
            "labels": sorted(label["name"] for label in issue["labels"]["nodes"]),
            "body": issue.get("body") or "",
            **({"person_since": person_since(issue)} if ages else {}),
        } for issue in issues],
        "releases": [{
            "tag": tag["name"],
            "url": f"https://github.com/{name}/releases/tag/{tag['name']}",
            "published_at": tag_date(tag.get("target")),
        } for tag in tags if RELEASE_TAG.fullmatch(tag["name"])],
        "integration_branch": integration_branch(config),
        "pull_requests": [{
            "number": pull["number"],
            "url": pull["url"],
            "base": pull["baseRefName"],
            "work_issue": sibling("pr_issues").work_issue(pull.get("body") or "", name),
            "field_report": carries_field_report(pull.get("body") or ""),
        } for pull in pulls],
    }


def integration_branch(config: str | None) -> str:
    """The integration branch a repository's se.toml names (`[project] integration_branch`), `main`
    where it has none, names none or does not parse."""
    try:
        project = tomllib.loads(config or "").get("project", {})
    except tomllib.TOMLDecodeError:
        return DEFAULT_INTEGRATION_BRANCH
    branch = project.get("integration_branch") if isinstance(project, dict) else None
    return branch if isinstance(branch, str) and branch.strip() else DEFAULT_INTEGRATION_BRANCH


def carries_field_report(body: str) -> bool:
    """Whether a pull request's description holds a field report: its begin marker, then its end."""
    begin = body.find(REPORT_BEGIN)
    return begin >= 0 and body.find(REPORT_END, begin) >= 0


# --- Compute ----------------------------------------------------------------------------------

# The places an entry goes to, in the table's order, each with the name the page shows: open work
# first, then the ideas waiting for the person, then what is done.
PLACES = {"today": "Today", "waiting": "Waiting for integrator", "needs-you": "Needs you", "next": "Next",
          "backlog": "Backlog", "done": "Done"}
DELIVERED = "delivered, waiting for the integrator"


def deliveries(data: dict) -> dict[int, dict]:
    """A repository's delivered issues, by number: each open pull request to its integration branch
    that carries a field report, under the issue it names. A snapshot without pull requests has none."""
    branch = data.get("integration_branch") or DEFAULT_INTEGRATION_BRANCH
    found: dict[int, dict] = {}
    for pull in sorted(data.get("pull_requests") or [], key=lambda pull: pull["number"]):
        if pull["base"] == branch and pull["field_report"] and pull.get("work_issue") is not None:
            found.setdefault(pull["work_issue"], pull)
    return found


def place(issue: dict) -> str | None:
    """Where an issue goes: done, backlog, waiting, today, needs-you, next, or None (hidden). An issue
    is delivered where its row keeps a pull request (`delivery`)."""
    labels = set(issue["labels"])
    if FIELD_REPORT in labels:
        return None
    if issue["state"] == "closed":
        return None if issue.get("state_reason") in HIDDEN_REASONS else "done"
    if BACKLOGGED in labels:
        return "backlog"
    if issue.get("delivery"):
        return "waiting"
    if IN_PROGRESS in labels:
        return "today"
    if READY in labels:
        return "next"
    if PERSON in labels:
        return "needs-you"
    return None


def needs_you(issue: dict) -> bool:
    return issue["state"] == "open" and PERSON in issue["labels"] and BACKLOGGED not in issue["labels"]


def status(issue: dict) -> str:
    """What an entry waits for, from its state, labels and delivery alone, so the live read derives it again."""
    labels = set(issue["labels"])
    if issue["state"] == "closed":
        return "done"
    if BACKLOGGED in labels:
        return "waiting for your input"
    if PERSON in labels:
        return "needs you"
    if issue.get("delivery"):
        return DELIVERED
    if IN_PROGRESS in labels:
        return "in progress"
    if READY in labels:
        return "ready"
    return "open"


# A code span as CommonMark reads it: a run of backticks, its text, and a run of the same length.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# A wikilink or an embed, which obs reads as a link through every escape but a code span.
WIKILINK = re.compile(r"!?\[\[.*?\]\]")


def spans(value: str) -> list[tuple[str, bool]]:
    """``value`` cut into its pieces, each with whether it is a code span (kept with its backticks)."""
    pieces, at = [], 0
    for match in CODE_SPAN.finditer(value):
        pieces += [(value[at:match.start()], False), (match[0], True)]
        at = match.end()
    return [piece for piece in [*pieces, (value[at:], False)] if piece[0]]


def code(value: str) -> str:
    """``value`` as one code span, its fence longer than any backtick run inside."""
    fence = "`" * (max(map(len, re.findall(r"`+", value)), default=0) + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def quoted_links(value: str, plain=lambda piece: piece) -> str:
    """``value`` with every wikilink outside a code span made a code span, so it stays text, and
    every other piece outside one passed through ``plain``; its code spans are kept as they are."""
    return "".join(piece if is_code else "".join(
        code(part) if WIKILINK.fullmatch(part) else plain(part) for part in re.split(f"({WIKILINK.pattern})", piece))
        for piece, is_code in spans(value))


def goal(body: str) -> str:
    """The first paragraph of the body's Goal section, or of the body where it has none, as one line
    of Markdown: its code spans kept and its bold markers removed outside them."""
    text = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.S)
    section = re.search(r"^#{1,6}\s*Goal\s*\n(.*?)(?=^#{1,6}\s|\Z)", text, flags=re.S | re.M)
    source = section[1] if section else text
    for block in re.split(r"\n\s*\n", source):
        lines = [line.strip() for line in block.strip().splitlines()]
        lines = [line for line in lines if line and not re.match(r"#{1,6}\s", line)]
        if lines:
            paragraph = " ".join(lines)
            return "".join(piece if is_code else re.sub(r"\*\*|__", "", piece) for piece, is_code in spans(paragraph))
    return ""


# The one line that plans an issue (work model "Issues"): `Planned: yyyy-mm-dd` on a line of its own.
PLANNED = re.compile(r"^Planned:[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*$", flags=re.M)


def planned(body: str) -> str | None:
    """The day an issue's body plans it for, from its first `Planned: yyyy-mm-dd` line; None without one."""
    match = PLANNED.search(body.replace("\r\n", "\n"))
    if not match:
        return None
    try:
        return date.fromisoformat(match[1]).isoformat()
    except ValueError:
        return None


def day(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()


def waiting_days(since: str | None, read_at: str) -> int | None:
    """Whole UTC calendar days from ``since`` to ``read_at``, never below 0; None without ``since``."""
    if not since:
        return None
    return max(0, (date.fromisoformat(day(read_at)) - date.fromisoformat(day(since))).days)


def needs_you_mark(waiting: int | None) -> str:
    """The "needs you" mark's text: bare without an age, else how long it has waited."""
    if waiting is None:
        return "needs you"
    if waiting == 0:
        return "needs you, today"
    return f"needs you, {waiting} day" + ("" if waiting == 1 else "s")


def mark(issue: dict, where: str, today: str, ages: bool, read_at: str) -> str:
    """What the build alone knows of an open entry: its planned day ("planned", or "late" once passed)
    and, with ``ages``, how long it has needed you. Never read live, so it never moves a row."""
    parts = [f"pull request #{issue['delivery_number']}"] if where == "waiting" else []
    plan = planned(issue["body"]) if where in ("today", "next", "needs-you") else None
    if plan:
        parts.append(f"late, planned {plan}" if plan < today else f"planned {plan}")
    if ages and needs_you(issue):
        waited = waiting_days(issue.get("person_since"), read_at)
        if waited is not None:
            parts.append(needs_you_mark(waited))
    return "; ".join(parts)


def lane_name(name: str) -> str:
    return name.split("/", 1)[1]


def version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", tag))


def rows(snapshot: dict, ages: bool = False) -> list[dict]:
    """The table's rows from the snapshot alone, in its order: by place (`PLACES`), newest first in
    each, the newest by its date (the day an issue closed or was opened, a release was tagged), then
    the higher number or version. A hidden issue has no row.

    Each row holds its columns (repository, place, date, number, subject, status, mark), what the live
    read compares (state, state_reason, labels, delivery: the link of the pull request that delivered
    it, or None), its note's `path`, its `url` and its `goal`.
    """
    read_at = snapshot["read_at"]
    today = day(read_at)
    found = []
    for name, data in snapshot["repositories"].items():
        lane = lane_name(name)
        delivered = deliveries(data)
        for issue in data["issues"]:
            pull = delivered.get(issue["number"]) if issue["state"] == "open" else None
            issue = issue | ({"delivery": pull["url"], "delivery_number": pull["number"]} if pull else {})
            where = place(issue)
            if where is None:
                continue
            stamp = issue["closed_at"] if where == "done" else issue.get("created_at")
            found.append(({
                "repository": lane, "number": issue["number"], "place": PLACES[where],
                "date": day(stamp) if stamp else "", "subject": quoted_links(issue["title"]), "status": status(issue),
                "mark": mark(issue, where, today, ages, read_at), "state": issue["state"],
                "state_reason": issue.get("state_reason"), "labels": sorted(issue["labels"]),
                "delivery": issue.get("delivery"), "path": f"entries/{lane}-{issue['number']}.md", "url": issue["url"], "goal": goal(issue["body"]),
            }, (0, (issue["number"],))))
        for release in data["releases"]:
            if not release.get("published_at"):
                continue
            found.append(({
                "repository": lane, "number": release["tag"], "place": PLACES["done"],
                "date": day(release["published_at"]), "subject": f"Release {release['tag']}", "status": "done",
                "mark": "", "state": "closed", "state_reason": None, "labels": [], "delivery": None,
                "path": f"entries/{lane}-{release['tag']}.md", "url": release["url"], "goal": "",
            }, (1, version(release["tag"]))))
    order = list(PLACES.values())
    found.sort(key=lambda pair: (pair[0]["date"], pair[1]), reverse=True)
    found.sort(key=lambda pair: order.index(pair[0]["place"]))
    return [row for row, _ in found]


# --- Show -------------------------------------------------------------------------------------

# The columns, in the table's order, with the names the page shows.
COLUMNS = {"repository": "Repo", "place": "Place", "date": "Date", "number": "Item",
           "subject": "Title", "status": "Status", "mark": "Mark"}
PAGE_SIZE = 20
# The live read (obs-html's live data: its spec/generic-tables.md, Current data): GitHub's
# public REST list of a repository's issues, which needs no token and answers any page's origin.
ISSUES_URL = ("https://api.github.com/repos/{name}/issues"
              "?state=all&since={{since}}&sort=updated&direction=asc&per_page=100")


def live_source(names: list[str]) -> dict:
    """The Base's `obsHtml.liveSource` for the repositories ``names`` (each with at least one row).

    Its `derive` repeats `place` and `status` for an issue as GitHub's REST list gives it, so obs's
    check proves every saved row; the mark is the build's alone. An issue a read changes or adds
    moves to its place in the open page; a pull request is left out.

    `delivery` is the build's too: its path names nothing GitHub's issue list gives, so a saved row
    keeps it, which the check proves Waiting for integrator, and an issue a read returns changed has
    none and takes the place its state and labels give (the module's docstring, Live).
    """
    delivered = [{"field": "delivery", "exists": True}]
    hidden = [{"where": [{"field": "labels", "equals": FIELD_REPORT}], "value": "hidden"},
              *({"where": [{"field": "state_reason", "equals": reason}], "value": "hidden"} for reason in HIDDEN_REASONS)]
    return {
        "name": "GitHub",
        "key": ["repository", "number"],
        "notePath": "entries/{repository}-{number}.md",
        "fields": {"number": "number", "subject": "title", "state": {"path": "state", "lowercase": True},
                   "state_reason": "state_reason", "labels": "labels[].name", "pullRequest": "pull_request.url",
                   "delivery": "delivery"},
        "derive": {
            "place": [*hidden,
                      {"where": [{"field": "state", "equals": "closed"}], "value": PLACES["done"]},
                      {"where": [{"field": "labels", "equals": BACKLOGGED}], "value": PLACES["backlog"]},
                      {"where": delivered, "value": PLACES["waiting"]},
                      {"where": [{"field": "labels", "equals": IN_PROGRESS}], "value": PLACES["today"]},
                      {"where": [{"field": "labels", "equals": READY}], "value": PLACES["next"]},
                      {"where": [{"field": "labels", "equals": PERSON}], "value": PLACES["needs-you"]},
                      {"value": "hidden"}],
            "status": [{"where": [{"field": "state", "equals": "closed"}], "value": "done"},
                       {"where": [{"field": "labels", "equals": BACKLOGGED}], "value": "waiting for your input"},
                       {"where": [{"field": "labels", "equals": PERSON}], "value": "needs you"},
                       {"where": delivered, "value": DELIVERED},
                       {"where": [{"field": "labels", "equals": IN_PROGRESS}], "value": "in progress"},
                       {"where": [{"field": "labels", "equals": READY}], "value": "ready"},
                       {"value": "open"}],
            "date": [{"where": [{"field": "state", "equals": "closed"}], "path": "closed_at"}, {"path": "created_at"}],
        },
        "bodyPath": "body",
        "exclude": [{"field": "pullRequest", "exists": True}],
        "changes": [{"provider": "web", "next": "link", "maxPages": 3, "requests": [
            {"set": {"repository": lane_name(name)}, "url": ISSUES_URL.format(name=name)} for name in names]}],
    }


def base(names: list[str]) -> dict:
    """The one table: every entry, grouped by place in `PLACES` order, newest first, paged by obs."""
    definition = {
        "filters": {"and": ["place != null", 'place != "hidden"']},
        "properties": {key: {"displayName": name} for key, name in COLUMNS.items()},
        "views": [{"type": "table", "name": "Timeline", "order": list(COLUMNS),
                   "groupBy": {"property": "place", "direction": "ASC"},
                   "sort": [{"property": "date", "direction": "DESC"}, {"property": "rank", "direction": "ASC"}],
                   "obsHtml": {"pageSize": PAGE_SIZE, "groupOrder": list(PLACES.values())}}],
    }
    if names:
        definition["obsHtml"] = {"liveSource": live_source(names)}
    return definition


def text(value: object) -> str:
    """``value`` as Markdown text that shows as written: its code spans kept, its wikilinks made code
    spans (obs reads one through any backslash) and every other ASCII punctuation mark escaped, so
    issue text never becomes a link, a tag, markup or HTML."""
    return quoted_links(" ".join(str(value).split()), lambda piece: re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", piece))


def frontmatter(fields: dict) -> str:
    """YAML frontmatter, each value as JSON (which YAML reads as it is); an empty value is left out."""
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
             if value not in (None, "", [])]
    return "---\n" + "\n".join(lines) + "\n---\n"


def short_date(iso: str) -> str:
    when = date.fromisoformat(iso)
    return f"{when.day} {when.strftime('%b')} {when.year}"


def vault(snapshot: dict, ages: bool = False) -> dict[str, str]:
    """The Timeline as obs notes, by vault path: the manifest with the table, and one note per row."""
    table = rows(snapshot, ages)
    names = [name for name in snapshot["repositories"] if any(row["repository"] == lane_name(name) for row in table)]
    lanes = [lane_name(name) for name in snapshot["repositories"]]
    shown = ", ".join(lanes[:-1]) + f" and {lanes[-1]}" if len(lanes) > 1 else "".join(lanes)
    gaps = "".join(f"Not shown: {text(name)} could not be read ({text(reason)}).\n\n"
                   for name, reason in (snapshot.get("unreadable") or {}).items())
    live = ("When the page opens, it asks GitHub for what changed since; where GitHub answers, the "
            "line under the table says it shows current data. " if names else "")
    live += ("An issue whose pull request is delivered waits for the integrator under Waiting for "
             "integrator. " if any(row["delivery"] for row in table) else "")
    files = {"manifest.md": (
        frontmatter({"title": "Timeline"}).replace("\n---\n", "\nobsHtml:\n  layout: scrolling\n  heading: compact\n"
                                                   "  pages: [{page: abstract}]\n---\n")
        + f"\nThe issues and releases of {text(shown)}, newest first in each place, from the snapshot "
          f"read on {short_date(day(snapshot['read_at']))}. {live}A backlog idea waits for your input "
          "before it is work.\n\n" + gaps
        + "```base\n" + json.dumps(base(names), indent=1) + "\n```\n")}
    for rank, row in enumerate(table):
        link = f"[Open {text(row['number'] if isinstance(row['number'], str) else '#' + str(row['number']))} on GitHub](<{row['url']}>)"
        files[row["path"]] = (frontmatter({key: row[key] for key in (*COLUMNS, "state", "state_reason", "labels", "delivery")}
                                          | {"rank": rank})
                              + "\n" + (text(row["goal"]) + "\n\n" if row["goal"] else "") + link + "\n")
    return files


# obs's core configuration for the build: issue text is data, so the long-paragraph lint reads it at
# its widest, and what obs still warns of is printed without failing the build.
CORE_CONFIG = {
    "input": {"manifestFilename": "manifest.md", "projectConfigFilename": "cfg.json",
              "longParagraphs": {"warningLines": 30, "lineCharacters": 200}},
    "execution": {"commandTimeoutSeconds": 15},
}


def build(files: dict[str, str], destination: Path, read_at: str) -> int:
    """Build the notes ``files`` into ``destination`` with obs, as made at ``read_at`` (its generation
    time, so a live read asks for what changed since the snapshot). 0 built, 1 obs failed."""
    build_docs = sibling("build_docs")
    obs = build_docs.obs_dir()
    adapter, refusal = build_docs.ready_adapter(obs)
    if adapter is None:
        print(f"timeline: {refusal}", file=sys.stderr)
        return 1
    environment = build_docs.child_environment()
    environment["SOURCE_DATE_EPOCH"] = str(int(datetime.fromisoformat(read_at.replace("Z", "+00:00")).timestamp()))
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch) / "timeline"
        for path, content in files.items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_text(content, encoding="utf-8", newline="\n")
        config = Path(scratch) / "obs-config.json"
        config.write_text(json.dumps(CORE_CONFIG), encoding="utf-8", newline="\n")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = sibling("process_door").run(
            [*build_docs.obs_document_command(obs), "--adapter", build_docs.ADAPTER, "--config", str(config),
             "--source", str(folder / "manifest.md"), "--destination", str(destination.resolve())],
            cwd=ROOT, capture_output=True, text=True, env=environment)
        output = (result.stdout + result.stderr).replace(str(folder), "<timeline notes>")
    for line in build_docs.obs_warnings(output):
        print(f"timeline: obs {line}", file=sys.stderr)
    if result.returncode:
        print(f"timeline: obs-document failed with exit code {result.returncode}:\n{output}", file=sys.stderr)
        return 1
    return 0


# --- Command ----------------------------------------------------------------------------------


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded once under its own name."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


#: The pages SE renders as one kern component (docs/start.md "Commands as components"), timeline.py's
#: command first, then deck.py's, which names this group; each command's usage and help come from
#: its script's make_parser.
COMPONENTS = (sibling("se_components").Group(
    "render", "Render",
    "The pages SE renders: timeline.py builds the Timeline from GitHub, deck.py builds a deck of "
    "decisions, serves it and reads its answers.",
    ("",)),)
#: The commands that go through kern where it runs (se_components.routed): none, as the Timeline
#: writes its page.
INTERACTIVE_COMMANDS: frozenset[str] = frozenset()


def make_parser() -> argparse.ArgumentParser:
    parser = se_script.parser(prog="timeline.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--destination", type=Path, required=True, help="the HTML file to write")
    parser.add_argument("--snapshot", type=Path, help="build from this snapshot file instead of reading GitHub")
    parser.add_argument("--save-snapshot", type=Path, help="also write the snapshot read to this file")
    parser.add_argument("--config", type=Path, default=CONFIG, help="the se.toml naming the repositories and [timeline] ages")
    return parser


def main(argv: list[str] | None = None, post: Poster | None = None, now: datetime | None = None) -> int:
    args = make_parser().parse_args(argv)
    routed = sibling("se_components").routed(
        Path(__file__), [], list(sys.argv[1:] if argv is None else argv), False)
    if routed is not None:
        return routed
    ages = ages_setting(args.config)
    if args.snapshot:
        try:
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"timeline: cannot read the snapshot {args.snapshot}: {error}", file=sys.stderr)
            return 2
    else:
        names = repositories(args.config)
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if post is None and not token:
            print("timeline: GitHub's GraphQL API needs a token; set GITHUB_TOKEN (or build from --snapshot)",
                  file=sys.stderr)
            return 2
        try:
            snapshot = read(names, post or http_poster(token), now or datetime.now(timezone.utc), ages=ages)
        except ReadError as error:
            print(f"timeline: {error}", file=sys.stderr)
            return 1
    if args.save_snapshot:
        args.save_snapshot.write_text(json.dumps(snapshot, indent=1), encoding="utf-8", newline="\n")
    code = build(vault(snapshot, ages=ages), args.destination, snapshot["read_at"])
    if code:
        return code
    for name, reason in (snapshot.get("unreadable") or {}).items():
        print(f"timeline: warning: {name} could not be read, so the page names it as a gap: {reason}",
              file=sys.stderr)
    print(f"timeline: wrote {args.destination} ({len(rows(snapshot, ages))} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
