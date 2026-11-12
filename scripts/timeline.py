"""Build the Timeline: one static HTML page of the repositories in se.toml `[timeline]`.

The page builds itself from GitHub, so nobody maintains it: one read, then pure.

- Read: for each repository, one batched pass on GitHub's GraphQL API, which needs a token
  (`GITHUB_TOKEN`, in the workflow its own): each request carries a page of its issues (open and
  closed) and a page of its tags, 100 each, until both are read; never a request per issue or tag.
  The result is a snapshot (`--save-snapshot` writes it, `--snapshot` builds from one without the
  network).
- Compute: the page comes from the snapshot alone. Pull requests and field reports (label
  `field-report`) are left out. An issue goes to exactly one place:
  - closed as not planned or duplicate: hidden;
  - closed otherwise: Done, on the day (UTC) it closed;
  - open and `backlogged`: Backlog, a section below the map;
  - open and `in-progress`: Today;
  - open and `ready`: Next;
  - open and `se-person`: Needs you;
  - any other open issue: hidden.
  An open issue of Today, Next or Needs you whose body plans it (`planned`, a line `Planned:
  yyyy-mm-dd`) goes to that day instead: after today, a planned day; today or before, Today, marked
  "late" when the day has passed.
  An open issue labelled `se-person` and not `backlogged` is marked "needs you" wherever it shows.
  A release is a tag `v<major>.<minor>.<patch>`, a marker on the day (UTC) it was tagged.
- Show: top to bottom, one lane per repository: each past day with an event is one stop per lane
  (a filled dot, a count and a short label, the release if there was one), then the Today line,
  each planned day with an issue as one hollow stop per lane, Needs you and Next; tapping a stop lists its issues, tapping an issue shows the first paragraph of its Goal and
  its link.

Exit code 0: written; 1: GitHub refused the read; 2: setup error. The README section
"Documentation" says where the page is published.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
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


def repositories(config: Path = CONFIG) -> list[str]:
    """se.toml's `[timeline] repositories`: the one list of the repositories the page shows."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        names = data["timeline"]["repositories"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"timeline: {config} has no [timeline] repositories ({error})") from error
    if not names or not all(isinstance(name, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", name) for name in names):
        raise SystemExit(f"timeline: [timeline] repositories in {config} must be <owner>/<repo> strings")
    return list(names)


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
      nodes { number title url state stateReason closedAt body labels(first: 30) { nodes { name } } }
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


def read(names: list[str], post: Poster, now: datetime) -> dict:
    """The snapshot: per repository, its issues and its releases, as read at ``now``.

    GraphQL's issues are issues only; pull requests are never read.
    """
    snapshot: dict = {"read_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "repositories": {}}
    for name in names:
        owner, repo = name.split("/", 1)
        issues: list[dict] = []
        tags: list[dict] = []
        cursors: dict[str, str | None] = {"issues": None, "tags": None}
        more = {"issues": True, "tags": True}
        while more["issues"] or more["tags"]:
            data = post(QUERY, {"owner": owner, "name": repo, **cursors,
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
        snapshot["repositories"][name] = {
            "issues": [{
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["url"],
                "state": issue["state"].lower(),
                "state_reason": (issue.get("stateReason") or "").lower() or None,
                "closed_at": issue.get("closedAt"),
                "labels": sorted(label["name"] for label in issue["labels"]["nodes"]),
                "body": issue.get("body") or "",
            } for issue in issues],
            "releases": [{
                "tag": tag["name"],
                "url": f"https://github.com/{name}/releases/tag/{tag['name']}",
                "published_at": tag_date(tag.get("target")),
            } for tag in tags if RELEASE_TAG.fullmatch(tag["name"])],
        }
    return snapshot


# --- Compute ----------------------------------------------------------------------------------


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


def model(snapshot: dict) -> dict:
    """The page's content from the snapshot alone: lanes, past days, the open places and the backlog."""
    lanes = list(snapshot["repositories"])
    today = day(snapshot["read_at"])
    days: dict[str, dict[str, dict]] = {}
    ahead: dict[str, dict[str, dict]] = {}
    places: dict[str, dict[str, list]] = {key: {lane: [] for lane in lanes}
                                          for key in ("today", "needs-you", "next", "backlog")}

    def stop(date: str, lane: str, into: dict = days) -> dict:
        return into.setdefault(date, {}).setdefault(lane, {"issues": [], "releases": []})

    for lane, data in snapshot["repositories"].items():
        for issue in data["issues"]:
            where = place(issue)
            if where is None:
                continue
            entry = {**issue, "needs_you": needs_you(issue), "goal": goal(issue["body"]), "late": False}
            plan = planned(issue["body"]) if where in ("today", "next", "needs-you") else None
            if where == "done":
                stop(day(issue["closed_at"]), lane)["issues"].append(entry)
            elif plan and plan > today:
                stop(plan, lane, ahead)["issues"].append(entry)
            elif plan:
                entry["late"] = plan < today
                places["today"][lane].append(entry)
            else:
                places[where][lane].append(entry)
        for release in data["releases"]:
            if release.get("published_at"):
                stop(day(release["published_at"]), lane)["releases"].append(release)
    for stops in [*days.values(), *ahead.values()]:
        for entry in stops.values():
            entry["issues"].sort(key=lambda issue: issue["number"])
            entry["releases"].sort(key=lambda release: (release["published_at"],
                                                        [int(part) for part in re.findall(r"\d+", release["tag"])]))
    for lists in places.values():
        for entries in lists.values():
            entries.sort(key=lambda issue: -issue["number"])
    return {"read_at": snapshot["read_at"], "today": today, "lanes": lanes,
            "days": dict(sorted(days.items())), "planned": dict(sorted(ahead.items())), "places": places}


# --- Show -------------------------------------------------------------------------------------

STYLE = """
:root {
  color-scheme: light dark;
  --font-content: Georgia, "Times New Roman", serif;
  --font-interface: Arial, "Helvetica Neue", sans-serif;
  --canvas: #ffffff; --surface: #fafafa; --text: #000000; --muted: #555555;
  --border: #bdbdbd; --soft: #eeeeee; --accent: #00508f; --accent-soft: #e3f1ff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --canvas: #1f1f1f; --surface: #292929; --text: #dddddd; --muted: #bdbdbd;
    --border: #5c5c5c; --soft: #383838; --accent: #8cc8ff; --accent-soft: #15334d;
  }
}
* { box-sizing: border-box; }
html { background: var(--canvas); color: var(--text); }
body { margin: 0 auto; max-width: 48rem; padding: 0 1rem 3rem; font: 1rem/1.45 var(--font-content);
  overflow-wrap: anywhere; }
h1, h2, .row, .lanes, .meta, .issue > summary, .backlog summary { font-family: var(--font-interface); }
h1 { font-size: 1.5rem; margin: 1.25rem 0 0.25rem; }
h2 { font-size: 1.1rem; margin: 2rem 0 0.5rem; }
.meta { color: var(--muted); font-size: 0.85rem; margin: 0 0 1rem; }
a { color: var(--accent); }
.lanes, .row > summary { display: grid; grid-template-columns: 4.5rem repeat(var(--lanes), minmax(0, 1fr));
  column-gap: 0.5rem; align-items: center; }
.lanes { position: sticky; top: 0; z-index: 1; background: var(--canvas); border-bottom: 1px solid var(--border);
  padding: 0.4rem 0; font-size: 0.85rem; font-weight: bold; }
.row > summary { list-style: none; cursor: pointer; min-height: 2.4rem; }
.row > summary::-webkit-details-marker { display: none; }
.when { color: var(--muted); font-size: 0.8rem; }
.year { font: bold 0.8rem var(--font-interface); color: var(--muted); padding: 0.75rem 0 0.25rem; }
.lane { position: relative; display: flex; align-items: center; gap: 0.35rem; min-width: 0; min-height: 2.4rem;
  padding-left: 1.15rem; font-size: 0.85rem; }
.lane::before { content: ""; position: absolute; left: 0.3rem; top: 0; bottom: 0; border-left: 2px solid var(--border); }
.dot { position: absolute; left: 0; width: 0.75rem; height: 0.75rem; border-radius: 50%;
  background: var(--canvas); border: 2px solid var(--text); }
.release .dot { border-radius: 0.1rem; transform: rotate(45deg); background: var(--text); }
.count { font-weight: bold; white-space: nowrap; flex-shrink: 0; }
.label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); }
.release .label { color: var(--text); font-weight: bold; }
.row[open] > summary, .row > summary:hover { background: var(--soft); }
.list { padding: 0.25rem 0 0.75rem 5rem; }
.list h3 { font: bold 0.85rem var(--font-interface); margin: 0.5rem 0 0.25rem; }
.list ul, .backlog ul { list-style: none; margin: 0; padding: 0; }
.issue > summary { cursor: pointer; padding: 0.2rem 0; font-size: 0.9rem; }
.issue p { margin: 0.25rem 0 0.25rem 1rem; }
.issue .link { margin-left: 1rem; font: 0.85rem var(--font-interface); }
.mark { display: inline-block; font: bold 0.7rem var(--font-interface); color: var(--accent);
  border: 1px solid var(--accent); border-radius: 0.25rem; padding: 0 0.25rem; margin-left: 0.25rem; }
.release-line { font: 0.85rem var(--font-interface); margin: 0.25rem 0; }
.today > summary { border-top: 2px solid var(--accent); border-bottom: 2px solid var(--accent);
  background: var(--accent-soft); }
.today .when, .today .dot { color: var(--accent); border-color: var(--accent); font-weight: bold; }
.past .dot { background: var(--text); }
.open .dot { border-style: dashed; }
.planned .when { font-style: italic; }
.lane .mark { flex-shrink: 0; margin-left: 0; }
.needs .dot { border-color: var(--accent); }
.backlog h3 { font: bold 0.95rem var(--font-interface); margin: 1rem 0 0.25rem; }
@media (max-width: 30rem) {
  .lanes, .row > summary { grid-template-columns: 3.9rem repeat(var(--lanes), minmax(0, 1fr)); }
  .list { padding-left: 0.5rem; }
}
"""

SCRIPT = "document.getElementById('today')?.scrollIntoView({block: 'center'});"


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def lane_name(name: str) -> str:
    return name.split("/", 1)[1]


def marks(issue: dict) -> str:
    return (('<span class="mark">needs you</span>' if issue["needs_you"] else "")
            + ('<span class="mark">late</span>' if issue.get("late") else ""))


def issue_item(issue: dict) -> str:
    mark = marks(issue)
    paragraph = f"<p>{esc(issue['goal'])}</p>" if issue["goal"] else ""
    return (f'<li><details class="issue"><summary>#{issue["number"]} {esc(issue["title"])}{mark}</summary>'
            f'{paragraph}<a class="link" href="{esc(issue["url"])}">Open #{issue["number"]} on GitHub</a>'
            f"</details></li>")


def stop_cell(issues: list[dict], releases: list[dict]) -> str:
    """One lane's stop: a dot, the count and a short label (the release if there was one)."""
    if not issues and not releases:
        return '<span class="lane"></span>'
    if releases:
        label = releases[-1]["tag"] + (f" +{len(releases) - 1}" if len(releases) > 1 else "")
    else:
        label = issues[-1]["title"]
    marked = ' needs' if any(issue["needs_you"] for issue in issues) else ""
    late = any(issue.get("late") for issue in issues)
    kind = " release" if releases else ""
    count = f'<span class="count">{len(issues)}</span>' if issues else ""
    mark = '<span class="mark">late</span>' if late else ""
    return (f'<span class="lane{kind}{marked}{" late" if late else ""}"><span class="dot"></span>{count}'
            f'{mark}<span class="label">{esc(label)}</span></span>')


def issue_list(lanes: list[str], stops: dict[str, dict]) -> str:
    parts = []
    for lane in lanes:
        entry = stops.get(lane)
        if not entry or not (entry["issues"] or entry["releases"]):
            continue
        parts.append(f"<h3>{esc(lane_name(lane))}</h3>")
        for release in entry["releases"]:
            parts.append(f'<p class="release-line">Release <a href="{esc(release["url"])}">{esc(release["tag"])}</a></p>')
        if entry["issues"]:
            parts.append("<ul>" + "".join(issue_item(issue) for issue in entry["issues"]) + "</ul>")
    return '<div class="list">' + "".join(parts) + "</div>"


def row(css: str, when: str, lanes: list[str], stops: dict[str, dict], ident: str = "") -> str:
    cells = "".join(stop_cell(stops.get(lane, {}).get("issues", []), stops.get(lane, {}).get("releases", []))
                    for lane in lanes)
    anchor = f' id="{ident}"' if ident else ""
    return (f'<details class="row {css}"{anchor}><summary><span class="when">{when}</span>{cells}</summary>'
            f"{issue_list(lanes, stops)}</details>")


def short_date(iso: str) -> str:
    date = datetime.fromisoformat(iso)
    return f"{date.day} {date.strftime('%b')}"


def render(page: dict) -> str:
    """The Timeline as one HTML file."""
    lanes = page["lanes"]
    parts = [f'<div class="lanes"><span></span>{"".join(f"<span>{esc(lane_name(lane))}</span>" for lane in lanes)}</div>']
    year = None

    def dated(css: str, days: dict[str, dict]) -> None:
        nonlocal year
        for date, stops in days.items():
            if date[:4] != year:
                year = date[:4]
                parts.append(f'<div class="year">{year}</div>')
            parts.append(row(css, short_date(date), lanes, stops))

    dated("past", page["days"])

    def open_row(key: str, title: str, css: str, ident: str = "") -> str:
        stops = {lane: {"issues": issues, "releases": []} for lane, issues in page["places"][key].items()}
        return row(f"open {css}", title, lanes, stops, ident=ident)

    parts.append(open_row("today", "Today", "today", "today"))
    dated("open planned", page["planned"])
    parts.append(open_row("needs-you", "Needs you", "needs"))
    parts.append(open_row("next", "Next", "next"))
    backlog = []
    for lane in lanes:
        issues = page["places"]["backlog"][lane]
        if issues:
            backlog.append(f"<h3>{esc(lane_name(lane))} ({len(issues)})</h3><ul>"
                           + "".join(issue_item(issue) for issue in issues) + "</ul>")
    if not backlog:
        backlog.append('<p class="meta">Nothing is backlogged.</p>')
    read_at = page["read_at"].replace("T", " ").replace("+00:00", " UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timeline</title>
<style>{STYLE}</style>
</head>
<body style="--lanes: {len(lanes)}">
<h1>Timeline</h1>
<p class="meta">Built from the issues and releases of {", ".join(esc(lane) for lane in lanes)} at {esc(read_at)}.
Tap a day to list its issues, an issue for its goal.</p>
<main class="map">
{chr(10).join(parts)}
</main>
<section class="backlog">
<h2>Backlog</h2>
{"".join(backlog)}
</section>
<script>{SCRIPT}</script>
</body>
</html>
"""


# --- Command ----------------------------------------------------------------------------------


def main(argv: list[str] | None = None, post: Poster | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--destination", type=Path, required=True, help="the HTML file to write")
    parser.add_argument("--snapshot", type=Path, help="build from this snapshot file instead of reading GitHub")
    parser.add_argument("--save-snapshot", type=Path, help="also write the snapshot read to this file")
    parser.add_argument("--config", type=Path, default=CONFIG, help="the se.toml naming the repositories")
    args = parser.parse_args(argv)
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
            snapshot = read(names, post or http_poster(token), datetime.now(timezone.utc))
        except ReadError as error:
            print(f"timeline: {error}", file=sys.stderr)
            return 1
    if args.save_snapshot:
        args.save_snapshot.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    page = model(snapshot)
    args.destination.write_text(render(page), encoding="utf-8")
    done = sum(len(stop["issues"]) for stops in page["days"].values() for stop in stops.values())
    print(f"timeline: wrote {args.destination} ({len(page['days'])} days, {done} done issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
