"""Build the Timeline: one obs table of the repositories in se.toml `[timeline]`, newest first.

The page builds itself from GitHub, so nobody maintains it: one read, then pure, then obs.

- Read: for each repository, one batched pass on GitHub's GraphQL API, which needs a token
  (`GITHUB_TOKEN`, in the workflow its own): each request carries a page of its issues (open and
  closed) and a page of its tags, 100 each, until both are read; never a request per issue or tag.
  The result is a snapshot (`--save-snapshot` writes it, `--snapshot` builds from one without the
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
  - open and `in-progress`: Today;
  - open and `ready`: Next;
  - open and `se-person`: Needs you;
  - any other open issue: hidden.
  An open issue is dated the day it was opened. A release is a tag `v<major>.<minor>.<patch>`, a
  Done row dated the day (UTC) it was tagged.
- Status, from state and labels alone: done; waiting for your input (`backlogged`: a backlog idea
  waits for the person before it is work); needs you (`se-person`); in progress; ready.
- Mark, what only the build knows: an open issue of Today, Next or Needs you whose body plans it (a
  line `Planned: yyyy-mm-dd`) is marked `planned <day>`, or `late, planned <day>` once the day has
  passed; it stays in its place.
- Ages, a setting off when absent: `[timeline] ages = true` in the `--config` file (se.toml by
  default) also reads each issue's last label events in the same request and keeps `person_since`,
  when it was last labelled `se-person`; the mark of an issue that needs you (`se-person`, not
  `backlogged`) then says how long it has waited, in whole UTC calendar days to the read (`needs
  you, 3 days`, `needs you, 1 day`, `needs you, today`). An issue with no such event, or a snapshot
  saved without it, has no age. Absent or false, the query, the snapshot and the rows are those
  without the setting; any other value is refused.
- Show: the rows are obs notes, one per row, under a manifest whose one `base` table lists them in
  the scrolling layout (`vault`); obs builds the page (`build`). The table groups them by place
  (Today, Needs you, Next, Backlog, Done), newest first in each, and pages them, `PAGE_SIZE` a page;
  obs's table filter offers each column's values, the repository and the place among them. Opening
  a row shows the first paragraph of its Goal and its link. The text above the table names the day
  of the snapshot; obs refuses a time of day in a page.
- Live: the table declares obs's live source (`live_source`): when the page opens, it asks GitHub's
  public REST list of each repository's issues, with no token, for what changed since an hour
  before the snapshot, and an issue that changed moves to the place and status its state and labels
  give; obs's line under the table then says "Showing current data". Where GitHub does not answer,
  the page shows the snapshot. The mark is never read live.

Exit code 0: written, a gap included; 1: GitHub refused the read of every repository, or obs failed;
2: setup error. The README section "Documentation" says where the page is published.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "se.toml"
API = "https://api.github.com"

FIELD_REPORT = "field-report"
BACKLOGGED = "backlogged"
IN_PROGRESS = "in-progress"
READY = "ready"
PERSON = "se-person"
HIDDEN_REASONS = ("not_planned", "duplicate")

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

# One query per page and repository: a page of its issues and a page of its tags, each with what the
# page needs, so the read never asks per issue or per tag. A connection already read to its end is
# left out of the next page's query.
QUERY = """
query($owner: String!, $name: String!, $issues: String, $tags: String,
      $withIssues: Boolean!, $withTags: Boolean!) {
  repository(owner: $owner, name: $name) {
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


# A release is a tag v<major>.<minor>.<patch> (README "Release tags"); the moving v<major> is none.
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
    cursors: dict[str, str | None] = {"issues": None, "tags": None}
    more = {"issues": True, "tags": True}
    while more["issues"] or more["tags"]:
        data = post(query(ages), {"owner": owner, "name": repo, **cursors,
                                  "withIssues": more["issues"], "withTags": more["tags"]})
        repository = data.get("repository")
        if repository is None:
            raise ReadError(f"GitHub returned no repository {name}; check [timeline] in se.toml")
        for key, field, into in (("issues", "issues", issues), ("tags", "refs", tags)):
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
    }


# --- Compute ----------------------------------------------------------------------------------

# The places an entry goes to, in the table's order, each with the name the page shows: open work
# first, then the ideas waiting for the person, then what is done.
PLACES = {"today": "Today", "needs-you": "Needs you", "next": "Next", "backlog": "Backlog", "done": "Done"}


def place(issue: dict) -> str | None:
    """Where an issue goes: done, backlog, today, needs-you, next, or None (hidden)."""
    labels = set(issue["labels"])
    if FIELD_REPORT in labels:
        return None
    if issue["state"] == "closed":
        return None if issue.get("state_reason") in HIDDEN_REASONS else "done"
    if BACKLOGGED in labels:
        return "backlog"
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
    """What an entry waits for, from its state and labels alone, so the live read derives it again."""
    labels = set(issue["labels"])
    if issue["state"] == "closed":
        return "done"
    if BACKLOGGED in labels:
        return "waiting for your input"
    if PERSON in labels:
        return "needs you"
    if IN_PROGRESS in labels:
        return "in progress"
    if READY in labels:
        return "ready"
    return "open"


def goal(body: str) -> str:
    """The first paragraph of the body's Goal section, or of the body where it has none, as plain text."""
    text = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.S)
    section = re.search(r"^#{1,6}\s*Goal\s*\n(.*?)(?=^#{1,6}\s|\Z)", text, flags=re.S | re.M)
    source = section[1] if section else text
    for block in re.split(r"\n\s*\n", source):
        lines = [line.strip() for line in block.strip().splitlines()]
        lines = [line for line in lines if line and not re.match(r"#{1,6}\s", line)]
        if lines:
            paragraph = " ".join(lines)
            return re.sub(r"\*\*|__|`", "", paragraph)
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
    parts = []
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
    read compares (state, state_reason, labels), its note's `path`, its `url` and its `goal`.
    """
    read_at = snapshot["read_at"]
    today = day(read_at)
    found = []
    for name, data in snapshot["repositories"].items():
        lane = lane_name(name)
        for issue in data["issues"]:
            where = place(issue)
            if where is None:
                continue
            stamp = issue["closed_at"] if where == "done" else issue.get("created_at")
            found.append(({
                "repository": lane, "number": issue["number"], "place": PLACES[where],
                "date": day(stamp) if stamp else "", "subject": issue["title"], "status": status(issue),
                "mark": mark(issue, where, today, ages, read_at), "state": issue["state"],
                "state_reason": issue.get("state_reason"), "labels": sorted(issue["labels"]),
                "path": f"entries/{lane}-{issue['number']}.md", "url": issue["url"], "goal": goal(issue["body"]),
            }, (0, (issue["number"],))))
        for release in data["releases"]:
            if not release.get("published_at"):
                continue
            found.append(({
                "repository": lane, "number": release["tag"], "place": PLACES["done"],
                "date": day(release["published_at"]), "subject": f"Release {release['tag']}", "status": "done",
                "mark": "", "state": "closed", "state_reason": None, "labels": [],
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
    """
    hidden = [{"where": [{"field": "labels", "equals": FIELD_REPORT}], "value": "hidden"},
              *({"where": [{"field": "state_reason", "equals": reason}], "value": "hidden"} for reason in HIDDEN_REASONS)]
    return {
        "name": "GitHub",
        "key": ["repository", "number"],
        "notePath": "entries/{repository}-{number}.md",
        "fields": {"number": "number", "subject": "title", "state": {"path": "state", "lowercase": True},
                   "state_reason": "state_reason", "labels": "labels[].name", "pullRequest": "pull_request.url"},
        "derive": {
            "place": [*hidden,
                      {"where": [{"field": "state", "equals": "closed"}], "value": PLACES["done"]},
                      {"where": [{"field": "labels", "equals": BACKLOGGED}], "value": PLACES["backlog"]},
                      {"where": [{"field": "labels", "equals": IN_PROGRESS}], "value": PLACES["today"]},
                      {"where": [{"field": "labels", "equals": READY}], "value": PLACES["next"]},
                      {"where": [{"field": "labels", "equals": PERSON}], "value": PLACES["needs-you"]},
                      {"value": "hidden"}],
            "status": [{"where": [{"field": "state", "equals": "closed"}], "value": "done"},
                       {"where": [{"field": "labels", "equals": BACKLOGGED}], "value": "waiting for your input"},
                       {"where": [{"field": "labels", "equals": PERSON}], "value": "needs you"},
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
    """``value`` as Markdown text that shows as written: every ASCII punctuation mark escaped, so issue
    text never becomes a link, a tag, markup or HTML."""
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", " ".join(str(value).split()))


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
    files = {"manifest.md": (
        frontmatter({"title": "Timeline"}).replace("\n---\n", "\nobsHtml:\n  layout: scrolling\n  heading: compact\n"
                                                   "  pages: [{page: abstract}]\n---\n")
        + f"\nThe issues and releases of {text(shown)}, newest first in each place, from the snapshot "
          f"read on {short_date(day(snapshot['read_at']))}. {live}A backlog idea waits for your input "
          "before it is work.\n\n" + gaps
        + "```base\n" + json.dumps(base(names), indent=1) + "\n```\n")}
    for rank, row in enumerate(table):
        link = f"[Open {text(row['number'] if isinstance(row['number'], str) else '#' + str(row['number']))} on GitHub](<{row['url']}>)"
        files[row["path"]] = (frontmatter({key: row[key] for key in (*COLUMNS, "state", "state_reason", "labels")}
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
        result = subprocess.run(
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


#: The pages SE renders as one kern component (README "Commands as components"), timeline.py's
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
    parser = argparse.ArgumentParser(prog="timeline.py", description=__doc__.split("\n\n")[0])
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
    sys.exit(main())
