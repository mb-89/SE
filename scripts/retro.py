"""Retro commands: the mechanical half of a retro, the facts the judging agent starts from.

`retro.py collect <retro issue>` reads the window from GitHub: every work issue closed since the
last closed retro issue (titled `docs/retro-...` or labelled `retro`, other than this one) closed,
or the whole history where none has; each with the field report of the pull request that landed
it, found through the landing pull request's `<!-- se:field-report-in <n> -->` marker. It writes a
draft with

- the sizes: closed, landed, duplicates, escalated;
- per landed issue the deliveries `integrate` refused before it landed (its `Integration
  stopped:` comments), its escalations and the complete suite's time its `Integrated in` comment
  names;
- the field reports' Retro sections and their "Not delivered" items, grouped;
- the rule checks (RULE_CHECKS), each broken one with what broke it;
- the previous retro's sizes, where its block is found;


and ends in a JSON block under BLOCK_MARKER (JSON is YAML too), which `read_block` parses back for
`retro.py file` and later collects. The judge fills the block's `findings`, `classes` and
`went_well`.

`retro.py file <retro issue> --draft FILE` refuses an incomplete judgment, writing nothing; it
files no issue (wrk-007). It posts the report, the judgment with each finding's proposed fix and
its kind (`work`, which SE bundles into work issues, or `decision`, for the owner's decision
list), then the facts and the block, as the retro issue's closing comment, and closes the issue.

GitHub is read through work_tickets.py's door (gh). Where gh is not signed in (Claude's cloud) the
command prints its GitHub steps as a plan for the session's GitHub tools and reads their answers
from the files the session saved into `--answers <dir>`, as the work model's "Without gh" says for
`integrate`: each run prints the steps whose answers are still missing (the closed issues and pull
requests; the close time of each retro issue and of each work issue updated in the window, which
the host's `list_issues` does not name; the comments and check runs) and, once every answer is
there, writes the draft. The host's tools name no merge commit, so a commit counts as a pull
request's squash merge by its subject (the pull request's title) and its committer time (the merge
time). The commits on the
integration branch come from git.

Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def sibling(name: str):
    """The script `<name>.py` beside this one, loaded once under its own name."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


work_tickets = sibling("work_tickets")
review = sibling("review")
QueueError = work_tickets.QueueError
Step, Plan = work_tickets.Step, work_tickets.Plan

BLOCK_MARKER = "<!-- se:retro-yaml -->"
REPORT_MARKER = "<!-- se:retro-report -->"
JUDGE_BEGIN, JUDGE_END = "<!-- se:retro-judge -->", "<!-- se:retro-judge:end -->"
FINDING_FIELDS = ("title", "body", "class", "home", "controversial", "why", "check")
CLASS_FIELDS = ("name", "fix")
JUDGMENT = ("findings", "classes", "went_well")
TITLE_WORDS = 5
# A finding whose home is the rule book changes a rule: controversial.
RULE_BOOK = "src/skills/work-model/references/rules.md"
WORK, DECISION = "work", "decision"
BLOCK_VERSION = 1
RETRO_LABEL = "retro"
RETRO_TITLE = "docs/retro-"
WORK_LABEL = work_tickets.WORK_LABELS[0]
ESCALATED_LABEL = "escalated"
REFUSED = "Integration stopped:"
INTEGRATED = "Integrated in "
SUITE_TIME = re.compile(r"Suite: .*?(\d+(?:\.\d+)?) s \(target")
REPORT_IN = re.compile(r"<!-- se:field-report-in (\d+) -->")
REFERENCE = re.compile(
    r"\b(?:fixes|refs|closes)\s+(?:#(\d+)|https://[^/\s]+/([^/\s]+/[^/\s]+)/issues/(\d+))\b",
    re.IGNORECASE)
# The rule checks, by name: what each holds.
RULE_CHECKS = {
    "work-issue": "every landing pull request names a work issue that was open when it merged",
    "check": f"the check `{work_tickets.CHECK_NAME}` passed on every landing pull request's head",
    "outside-pr": "no commit reached the integration branch outside a pull request",
    "field-report": "every closed work issue has a field report",
}
RETRO_KEYS = ("Went well", "Cost time", "Proposed improvement")
EMPTY = {"", "none", "none.", "-", "n/a"}


def when(value: object) -> datetime | None:
    """`value`, an ISO time as GitHub writes it, as an aware datetime; None for none."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def first(item: dict, *keys: str) -> object:
    """The first of `keys` `item` has a value for: REST answers are snake_case, the host's tools
    sometimes camelCase."""
    for key in keys:
        if item.get(key) not in (None, ""):
            return item[key]
    return None


def listed(answer: object, *keys: str) -> list[dict]:
    """The list in `answer`: the answer itself, its pages, or its `keys` (an API page wraps its
    list)."""
    if isinstance(answer, dict):
        answer = next((answer[key] for key in keys if isinstance(answer.get(key), list)), [])
    found: list[dict] = []
    for item in answer if isinstance(answer, list) else []:
        if isinstance(item, list):
            found += listed(item, *keys)
        elif isinstance(item, dict) and any(isinstance(item.get(key), list) for key in keys):
            found += listed(item, *keys)
        elif isinstance(item, dict):
            found.append(item)
    return found


def label_names(item: dict) -> list[str]:
    labels = item.get("labels") or []
    if isinstance(labels, dict):
        labels = labels.get("nodes") or []
    return [str(label.get("name") if isinstance(label, dict) else label) for label in labels]


@dataclass
class Issue:
    number: int
    title: str
    labels: list[str]
    closed_at: str
    state_reason: str
    body: str = ""
    updated_at: str = ""


@dataclass
class Pull:
    number: int
    title: str
    body: str
    head: str
    head_sha: str
    base: str
    merged_at: str
    merge_sha: str


def issue_of(item: dict) -> Issue:
    return Issue(
        number=int(item.get("number") or 0), title=str(item.get("title") or ""),
        labels=label_names(item), closed_at=str(first(item, "closed_at", "closedAt") or ""),
        state_reason=str(first(item, "state_reason", "stateReason") or "").lower(),
        body=str(item.get("body") or ""),
        updated_at=str(first(item, "updated_at", "updatedAt") or ""))


def pull_of(item: dict) -> Pull:
    head = item.get("head") if isinstance(item.get("head"), dict) else {}
    base = item.get("base") if isinstance(item.get("base"), dict) else {}
    return Pull(
        number=int(item.get("number") or 0), title=str(item.get("title") or ""),
        body=str(item.get("body") or ""),
        head=str(head.get("ref") or item.get("headRefName") or ""),
        head_sha=str(head.get("sha") or item.get("headRefOid") or ""),
        base=str(base.get("ref") or item.get("baseRefName") or ""),
        merged_at=str(first(item, "merged_at", "mergedAt") or ""),
        merge_sha=str(first(item, "merge_commit_sha", "mergeCommitSha") or ""))


class GhDoor:
    """The collect's GitHub reads through work_tickets.py's door: issues in `tracker`, pull
    requests and their check runs in `remote`."""

    PAGE = 100

    def __init__(self, root: Path, tracker: str, remote: str) -> None:
        self.issues_door = work_tickets.GitHub(root, tracker)
        self.pulls_door = work_tickets.GitHub(root, remote)
        self.missing: list[Step] = []

    def pages(self, door, path: str) -> list[dict]:
        found: list[dict] = []
        page = 1
        while True:
            answer = door.api(f"{path}&per_page={self.PAGE}&page={page}")
            items = answer if isinstance(answer, list) else []
            found += [item for item in items if isinstance(item, dict)]
            if len(items) < self.PAGE:
                return found
            page += 1

    def closed_issues(self) -> list[dict]:
        return [item for item in self.pages(self.issues_door, "issues?state=closed")
                if "pull_request" not in item]

    def pulls(self) -> list[dict]:
        return self.pages(self.pulls_door, "pulls?state=closed")

    def issue(self, number: int) -> dict:
        answer = self.issues_door.api(f"issues/{number}")
        return answer if isinstance(answer, dict) else {}

    def comments(self, number: int) -> list[dict]:
        return listed(self.issues_door.api(f"issues/{number}/comments?per_page=100"), "comments")

    def checks(self, pull: Pull) -> list[dict]:
        return listed(self.pulls_door.api(f"commits/{pull.head_sha}/check-runs?per_page=100"),
                      "check_runs")


class FileDoor:
    """The same reads from the answers the session saved with its GitHub tools into `directory`:
    `issues.json`, `pulls.json`, `issue-<issue>.json` (where the list names no close time, as
    the host's `list_issues` does not), `comments-<issue>.json` and `checks-<pull>.json`. A missing
    answer reads as empty and is kept as the plan step that saves it (`missing`)."""

    def __init__(self, directory: Path, tracker: str, remote: str) -> None:
        self.directory, self.tracker, self.remote = directory, tracker, remote
        self.missing: list[Step] = []

    def read(self, name: str, step: Step) -> object:
        path = self.directory / name
        if not path.is_file():
            self.missing.append(step)
            return []
        try:
            return json.loads(work_tickets.read_file(path, f"the answer {name}"))
        except json.JSONDecodeError as error:
            raise QueueError(f"The answer {path} is not JSON: {error}") from error

    def closed_issues(self) -> list[dict]:
        return listed(self.read("issues.json", Step("issues.json", "list_issues", {
            **work_tickets.owner_repo(self.tracker), "state": "CLOSED", "perPage": 100},
            note=f"Every page (after the previous page's cursor); save the issues of all pages "
                 f"as one JSON list to {self.directory / 'issues.json'}")), "issues", "nodes")

    def pulls(self) -> list[dict]:
        return listed(self.read("pulls.json", Step("pulls.json", "list_pull_requests", {
            **work_tickets.owner_repo(self.remote), "state": "closed", "perPage": 100},
            note=f"Every page; save the pull requests of all pages as one JSON list to "
                 f"{self.directory / 'pulls.json'}")), "pull_requests", "pulls")

    def issue(self, number: int) -> dict:
        name = f"issue-{number}.json"
        answer = self.read(name, Step(name, "issue_read", {
            **work_tickets.owner_repo(self.tracker), "method": "get", "issue_number": number},
            note=f"Save the answer as JSON to {self.directory / name}"))
        return answer if isinstance(answer, dict) else {}

    def comments(self, number: int) -> list[dict]:
        name = f"comments-{number}.json"
        return listed(self.read(name, Step(name, "issue_read", {
            **work_tickets.owner_repo(self.tracker), "method": "get_comments",
            "issue_number": number, "perPage": 100},
            note=f"Save the answer as JSON to {self.directory / name}")), "comments")

    def checks(self, pull: Pull) -> list[dict]:
        name = f"checks-{pull.number}.json"
        return listed(self.read(name, Step(name, "pull_request_read", {
            **work_tickets.owner_repo(self.remote), "method": "get_check_runs",
            "pullNumber": pull.number},
            note=f"Save the answer as JSON to {self.directory / name}")), "check_runs")


def is_retro(issue: Issue) -> bool:
    return issue.title.startswith(RETRO_TITLE) or RETRO_LABEL in issue.labels


def reference(pull: Pull, tracker: str) -> int | None:
    """The issue in `tracker` that `pull`'s description first names with Fixes, Refs or
    Closes."""
    match = REFERENCE.search(pull.body)
    if match is None:
        return None
    if match[1]:
        return int(match[1])
    return int(match[3]) if match[2].lower() == work_tickets.api_repo(tracker).lower() else None


def section(report: str, heading: str) -> str:
    """The text under `## <heading>` in `report`, up to the next heading of that level."""
    match = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", report,
                      re.MULTILINE | re.DOTALL)
    return work_tickets.HTML_COMMENT_PATTERN.sub("", match[1]).strip() if match else ""


def report_of(body: str) -> str | None:
    if work_tickets.REPORT_BEGIN not in body or work_tickets.REPORT_END not in body:
        return None
    return work_tickets.report_in(body, "the pull request")


def one_line(text: str) -> str:
    return " ".join(text.split())


def retro_entries(report: str) -> dict[str, str]:
    """The field report's Retro section, by RETRO_KEYS; empty entries left out."""
    found: dict[str, str] = {}
    text = section(report, "Retro")
    for key in RETRO_KEYS:
        match = re.search(rf"\*\*{re.escape(key)}:\*\*(.*?)(?=^\s*[-*] \*\*|\Z)", text,
                          re.MULTILINE | re.DOTALL)
        value = one_line(match[1]) if match else ""
        if value.lower() not in EMPTY:
            found[key] = value
    return found


def not_delivered(report: str) -> list[str]:
    """The field report's "Not delivered" items, one per bullet (or the whole text without any);
    none where it says None."""
    text = section(report, "Not delivered")
    if one_line(text).lower() in EMPTY:
        return []
    bullets = re.split(r"^\s*[-*] ", text, flags=re.MULTILINE)
    if len(bullets) == 1:
        return [one_line(text)]
    return [one_line(item) for item in bullets[1:] if one_line(item).lower() not in EMPTY]


@dataclass
class Window:
    retro: int
    since: str | None
    since_retro: int | None
    until: str


@dataclass
class Closed:
    """One work issue of the window and what the record says of it."""

    number: int
    title: str
    state_reason: str
    duplicate: bool
    landed: bool
    refused: int
    escalations: int
    suite_seconds: float | None
    landing_pull: int | None
    report_pull: int | None
    retro: dict[str, str] = field(default_factory=dict)
    not_delivered: list[str] = field(default_factory=list)


@dataclass
class RuleCheck:
    name: str
    rule: str
    checked: int
    broken: list[dict] = field(default_factory=list)

    @property
    def kept(self) -> bool:
        return not self.broken


@dataclass
class Collected:
    window: Window
    sizes: dict[str, int]
    issues: list[Closed]
    checks: list[RuleCheck]
    previous: dict | None

    def data(self) -> dict:
        return {"version": BLOCK_VERSION, "window": asdict(self.window), "sizes": self.sizes,
                "issues": [asdict(item) for item in self.issues],
                "rule_checks": [{**asdict(check), "kept": check.kept} for check in self.checks],
                "previous": self.previous, **{name: [] for name in JUDGMENT}}


def read_block(text: str) -> dict | None:
    """The data of the last block under BLOCK_MARKER in `text`; None where it has none."""
    at = text.rfind(BLOCK_MARKER)
    if at < 0:
        return None
    match = re.search(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", text[at:], re.MULTILINE | re.DOTALL)
    if match is None:
        raise QueueError(f"The {BLOCK_MARKER} block has no fenced block under it")
    try:
        data = json.loads(match[2])
    except json.JSONDecodeError as error:
        raise QueueError(f"The {BLOCK_MARKER} block is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise QueueError(f"The {BLOCK_MARKER} block is not an object")
    return data


def first_parent_commits(root: Path, ref: str) -> list[tuple[str, str, str]]:
    """The first-parent commits of `ref`, newest first: (sha, committer date, subject)."""
    output = work_tickets.checked_git(root, "log", "--first-parent", "--format=%H%x09%cI%x09%s",
                                      ref)
    return [tuple(line.split("\t", 2)) for line in output.splitlines() if line.count("\t") >= 2]


def collect(root: Path, number: int, door, tracker: str, branch: str, ref: str,
            now: datetime) -> Collected | None:
    """The window of retro `number` read through `door`; None where the door is still missing
    answers (`door.missing`)."""
    issues = [issue_of(item) for item in door.closed_issues()]
    pulls = [pull_of(item) for item in door.pulls()]
    if door.missing:
        return None
    by_number = {issue.number: issue for issue in issues}

    def completed(chosen: list[Issue]) -> bool:
        """Each of `chosen` with its close time and reason, read one by one where the list
        named none; False while the door still misses answers."""
        for issue in chosen:
            if not issue.closed_at:
                read = issue_of(door.issue(issue.number))
                issue.closed_at, issue.state_reason = read.closed_at, read.state_reason
        return not door.missing

    if not completed([issue for issue in issues if is_retro(issue) and issue.number != number]):
        return None
    retros = [issue for issue in issues if is_retro(issue) and issue.number != number
              and when(issue.closed_at)]
    last = max(retros, key=lambda issue: when(issue.closed_at), default=None)
    since = when(last.closed_at) if last else None

    def in_window(value: str) -> bool:
        moment = when(value)
        return moment is not None and (since is None or moment > since)

    # An issue closed in the window was updated in it: only those are read one by one.
    if not completed([issue for issue in issues if WORK_LABEL in issue.labels
                      and not is_retro(issue) and (since is None or not issue.updated_at
                                                   or when(issue.updated_at) > since)]):
        return None
    window = sorted((issue for issue in issues if WORK_LABEL in issue.labels
                     and not is_retro(issue) and in_window(issue.closed_at)),
                    key=lambda issue: issue.number)
    pull_numbers = {pull.number: pull for pull in pulls}
    merged = [pull for pull in pulls if pull.merged_at]
    references = {pull.number: reference(pull, tracker) for pull in pulls}
    landings = [pull for pull in merged if pull.base == branch and in_window(pull.merged_at)]

    closed: list[Closed] = []
    for issue in window:
        comments = [str(item.get("body") or "") for item in door.comments(issue.number)]
        refused = sum(body.lstrip().startswith(REFUSED) for body in comments)
        escalations = refused or int(ESCALATED_LABEL in issue.labels)
        suite = None
        for body in comments:
            found = SUITE_TIME.search(body) if body.lstrip().startswith(INTEGRATED) else None
            suite = float(found[1]) if found else suite
        naming = [pull for pull in pulls if references[pull.number] == issue.number]
        landing = next((pull for pull in sorted(naming, key=lambda p: -p.number)
                        if pull.merged_at and pull.base == branch), None)
        report_pull = None
        if landing is not None:
            marker = REPORT_IN.search(landing.body)
            carrier = pull_numbers.get(int(marker[1])) if marker else landing
            report_pull = carrier if carrier and report_of(carrier.body) else None
        if report_pull is None:
            report_pull = next((pull for pull in sorted(naming, key=lambda p: -p.number)
                                if report_of(pull.body)), None)
        report = report_of(report_pull.body) if report_pull else None
        duplicate = issue.state_reason == "duplicate" or "duplicate" in issue.labels
        closed.append(Closed(
            number=issue.number, title=issue.title, state_reason=issue.state_reason or "completed",
            duplicate=duplicate,
            landed=landing is not None and not duplicate and issue.state_reason != "not_planned",
            refused=refused, escalations=escalations, suite_seconds=suite,
            landing_pull=landing.number if landing else None,
            report_pull=report_pull.number if report_pull else None,
            retro=retro_entries(report) if report else {},
            not_delivered=not_delivered(report) if report else []))

    checks = {name: RuleCheck(name, rule, 0) for name, rule in RULE_CHECKS.items()}
    for pull in landings:
        named = references[pull.number]
        target = by_number.get(named) if named is not None else None
        checks["work-issue"].checked += 1
        problem = None
        if named is None:
            problem = "names no work issue (Fixes|Refs <issue url>)"
        elif named in pull_numbers:
            problem = f"names #{named}, a pull request"
        elif target is not None and WORK_LABEL not in target.labels:
            problem = f"names #{named}, which is not labelled {WORK_LABEL}"
        elif target is not None and when(target.closed_at) < when(pull.merged_at):
            problem = f"names #{named}, closed before the pull request merged"
        if problem:
            checks["work-issue"].broken.append({"item": f"#{pull.number}", "what": problem})
        checks["check"].checked += 1
        runs = [run for run in door.checks(pull) if run.get("name") == work_tickets.CHECK_NAME]
        conclusion = str(runs[0].get("conclusion") or runs[0].get("status") or "") if runs else ""
        if conclusion != "success":
            checks["check"].broken.append({
                "item": f"#{pull.number}",
                "what": f"{work_tickets.CHECK_NAME} {conclusion}" if conclusion
                else f"no {work_tickets.CHECK_NAME} run on {pull.head_sha[:12]}"})
    merge_shas = {pull.merge_sha for pull in merged if pull.merge_sha}
    # The host's tools name no merge commit: a squash merge's commit carries the pull request's
    # title as its subject (or GitHub's ` (#<n>)`) and its merge time as its committer time.
    squashes = {(when(pull.merged_at), pull.title) for pull in merged} | {
        (when(pull.merged_at), f"{pull.title} (#{pull.number})") for pull in merged}
    for sha, date, subject in first_parent_commits(root, ref):
        if not in_window(date):
            continue
        checks["outside-pr"].checked += 1
        if sha not in merge_shas and (when(date), subject) not in squashes:
            checks["outside-pr"].broken.append({"item": sha[:12], "what": subject})
    for item in closed:
        if item.duplicate or item.state_reason == "not_planned":
            continue
        checks["field-report"].checked += 1
        if item.report_pull is None:
            checks["field-report"].broken.append({
                "item": f"#{item.number}",
                "what": "no pull request naming it carries a field report"})
    if door.missing:
        return None

    previous = None
    if last is not None:
        texts = [last.body, *(str(item.get("body") or "") for item in door.comments(last.number))]
        blocks = [read_block(text) for text in texts if BLOCK_MARKER in text]
        previous = blocks[-1] if blocks else None
        if door.missing:
            return None
    sizes = {"closed": len(closed), "landed": sum(item.landed for item in closed),
             "duplicates": sum(item.duplicate for item in closed),
             "escalated": sum(item.escalations > 0 for item in closed)}
    return Collected(
        Window(number, last.closed_at if last else None, last.number if last else None,
               now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        sizes, closed, list(checks.values()),
        {"retro": last.number, "sizes": previous.get("sizes")}
        if previous else None)


def draft(found: Collected) -> str:
    """The draft as the judging agent reads it, ending in the block `read_block` parses."""
    window = found.window
    lines = [f"# Retro draft for #{window.retro}", ""]
    if window.since:
        lines.append(f"Window: work issues closed after {window.since}, when retro "
                     f"#{window.since_retro} closed, up to {window.until}.")
    else:
        lines.append(f"Window: the whole history up to {window.until}; no retro issue has closed.")
    previous = (found.previous or {}).get("sizes") or {}
    lines += ["", "## Sizes", ""]
    if previous:
        lines += [f"| size | this window | retro #{found.previous['retro']} |", "|---|---|---|"]
        lines += [f"| {name} | {value} | {previous.get(name, '')} |"
                  for name, value in found.sizes.items()]
    else:
        lines += ["| size | this window |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in found.sizes.items()]
    lines += ["", "## Landed issues", ""]
    landed = [item for item in found.issues if item.landed]
    if landed:
        lines += ["| issue | refused deliveries | escalations | suite time | field report |",
                  "|---|---|---|---|---|"]
        for item in landed:
            suite = f"{item.suite_seconds:g} s" if item.suite_seconds is not None else "unknown"
            report = f"#{item.report_pull}" if item.report_pull else "none"
            lines.append(f"| #{item.number} {item.title} | {item.refused} | {item.escalations} | "
                         f"{suite} | {report} |")
    else:
        lines.append("None.")
    others = [item for item in found.issues if not item.landed]
    if others:
        lines += ["", "Closed without landing: " + ", ".join(
            f"#{item.number} ({'duplicate' if item.duplicate else item.state_reason})"
            for item in others) + "."]
    lines += ["", "## Rule checks", ""]
    for check in found.checks:
        state = (f"kept ({check.checked} checked)" if check.kept
                 else f"broken {len(check.broken)} of {check.checked}")
        lines.append(f"- **{check.name}**: {check.rule}: {state}")
        lines += [f"  - {item['item']}: {item['what']}" for item in check.broken]
    lines += ["", "## Retro sections of the field reports"]
    for key in RETRO_KEYS:
        entries = [(item.number, item.retro[key]) for item in found.issues if key in item.retro]
        lines += ["", f"### {key}", ""]
        lines += [f"- #{number}: {text}" for number, text in entries] or ["None."]
    lines += ["", "## Not delivered", ""]
    entries = [(item.number, text) for item in found.issues for text in item.not_delivered]
    lines += [f"- #{number}: {text}" for number, text in entries] or ["None."]
    block = json.dumps(found.data(), indent=2, ensure_ascii=False)
    lines += ["", JUDGE_BEGIN, "## Judgment", "",
              "The judge fills `findings`, `classes` and `went_well` in the block below, then runs "
              f"`retro.py file {window.retro} --draft <this file>`: a finding has `title` (five "
              "words or more), `body`, `class` (a class's `name`), `home` (the file it changes), "
              "`controversial` (true where it changes a rule, trades one metric for another, the "
              "judge is unsure, or it recurred after an earlier fix) with its `why`, and "
              f"optionally `check` (a rule check: {', '.join(RULE_CHECKS)}); a class has `name` "
              "and `fix`; `went_well` lists what went well. This part is not posted.", JUDGE_END,
              "", BLOCK_MARKER, review.fenced(block, "yaml")]
    return "\n".join(lines) + "\n"


def judgment_problems(block: dict) -> list[str]:
    """What keeps the judgment in `block` from being complete; none where it is."""
    problems: list[str] = []
    lists = {name: block.get(name) for name in JUDGMENT}
    for name, value in lists.items():
        if not isinstance(value, list):
            problems.append(f"`{name}` is not a list")
    if problems:
        return problems
    classes: dict[str, str] = {}
    for index, given in enumerate(lists["classes"], 1):
        if not isinstance(given, dict):
            problems.append(f"class {index} is not an object with {', '.join(CLASS_FIELDS)}")
            continue
        extra = sorted(set(given) - set(CLASS_FIELDS))
        name = review.words(given.get("name"))
        if extra:
            problems.append(f"class {index} has the unknown field {extra[0]}")
        if not name:
            problems.append(f"class {index} has no name")
        elif not review.words(given.get("fix")):
            problems.append(f'class "{name}" has no fix')
        classes[name] = review.words(given.get("fix"))
    for index, given in enumerate(lists["findings"], 1):
        if not isinstance(given, dict):
            problems.append(f"finding {index} is not an object with {', '.join(FINDING_FIELDS)}")
            continue
        title = review.words(given.get("title"))
        name = f'finding {index} ("{title}")' if title else f"finding {index}"
        extra = sorted(set(given) - set(FINDING_FIELDS))
        if extra:
            problems.append(f"{name} has the unknown field {extra[0]}")
        if len(title.split()) < TITLE_WORDS:
            problems.append(f"{name} needs a title of {TITLE_WORDS} words or more that names "
                            "the fix")
        if not review.words(given.get("body")):
            problems.append(f"{name} has no body")
        kind = review.words(given.get("class"))
        if not kind:
            problems.append(f"{name} has no class")
        elif kind not in classes:
            problems.append(f'{name} names the class "{kind}", which `classes` does not')
        home = review.words(given.get("home"))
        if not home:
            problems.append(f"{name} has no home: the file it changes")
        controversial = given.get("controversial", False)
        if not isinstance(controversial, bool):
            problems.append(f"{name}: controversial is true or false")
        check = review.words(given.get("check"))
        if check and check not in RULE_CHECKS:
            problems.append(f'{name} names the check "{check}", which is no rule check '
                            f"({', '.join(RULE_CHECKS)})")
        if home == RULE_BOOK and controversial is not True:
            problems.append(f"{name} changes a rule (its home is the rule book), so it is "
                            "controversial, with its why")
        elif controversial is True and not review.words(given.get("why")):
            problems.append(f"{name} is controversial without a why")
    if not [entry for entry in lists["went_well"] if review.words(entry)]:
        problems.append("`went_well` is empty: record what went well")
    return problems


def judged(text: str, number: int) -> dict:
    """The block of the draft `text`, its judgment checked; every refusal is raised before
    anything is written."""
    block = read_block(text)
    if block is None:
        raise QueueError(f"The draft has no {BLOCK_MARKER} block: write it with retro.py collect "
                         f"{number} --out FILE")
    retro = (block.get("window") or {}).get("retro")
    if retro != number:
        raise QueueError(f"The draft is retro #{retro}'s, not #{number}'s")
    problems = judgment_problems(block)
    if problems:
        raise QueueError(f"The judgment of retro #{number} is not complete, so nothing was "
                         "written: " + "; ".join(problems))
    findings = []
    for index, given in enumerate(block["findings"], 1):
        controversial = given.get("controversial") is True
        findings.append({"finding": index, **{key: given[key] for key in FINDING_FIELDS
                                              if key in given},
                         "controversial": controversial,
                         "kind": DECISION if controversial else WORK})
    return {**block, "findings": findings}


def facts_of(text: str) -> str:
    """The draft's facts: its text between the title and the block, without the judging note,
    its headings two levels down, under the report's "The facts"."""
    head = text[:text.rfind(BLOCK_MARKER)]
    head = re.sub(rf"{re.escape(JUDGE_BEGIN)}.*?{re.escape(JUDGE_END)}", "", head,
                  flags=re.DOTALL)
    lines = head.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return review.demoted("\n".join(lines)).strip()


def report(text: str, block: dict, number: int) -> str:
    """The retro's report, its closing comment: the judgment, each finding with its proposed fix
    and kind, what follows, the facts, then the block the next collect reads."""
    fixes = {entry["name"].strip(): entry["fix"].strip() for entry in block["classes"]}
    lines = [REPORT_MARKER, f"## Retro #{number}: the report", "", "### Findings"]
    if not block["findings"]:
        lines += ["", "None."]
    for name, fix in fixes.items():
        members = [item for item in block["findings"] if item["class"].strip() == name]
        if not members:
            continue
        lines += ["", f"#### {name} ({len(members)})", "", f"Fix: {fix}", ""]
        for item in members:
            kind = (f"{DECISION}, for the owner's decision list: {item['why'].strip()}"
                    if item["kind"] == DECISION else f"{WORK}, for SE to bundle")
            check = f"; check `{item['check']}`" if item.get("check") else ""
            lines += [f"- **{item['finding']}. {item['title'].strip()}** ({kind}; home "
                      f"`{item['home'].strip()}`{check})",
                      "  " + "\n  ".join(item["body"].strip().splitlines())]
    lines += ["", "### What went well", ""]
    lines += [f"- {entry.strip()}" for entry in block["went_well"] if review.words(entry)]
    work = [item["finding"] for item in block["findings"] if item["kind"] == WORK]
    decisions = [item["finding"] for item in block["findings"] if item["kind"] == DECISION]
    lines += ["", "### What follows", "",
              f"This retro filed no issue. SE bundles the {WORK} findings "
              f"({', '.join(map(str, work)) or 'none'}) into as few work issues as the work "
              f"needs, each naming `retro #{number} finding <k>` for every finding it takes, so "
              f"the next retro scores it; the {DECISION} findings "
              f"({', '.join(map(str, decisions)) or 'none'}) go on the owner's decision list.",
              "", "### The facts", "", facts_of(text), "", BLOCK_MARKER,
              review.fenced(json.dumps(block, indent=2, ensure_ascii=False), "yaml")]
    return "\n".join(lines) + "\n"


def file_steps(tracker: str, number: int, comment: str) -> Plan:
    """The writes: the report as the retro issue's closing comment, then the close."""
    issues = work_tickets.owner_repo(tracker)
    return Plan(f"the report of retro #{number}", (
        Step("comment_issue", "add_issue_comment", {**issues, "issue_number": number,
                                                    "body": comment}),
        Step("close_issue", "issue_write", {**issues, "method": "update", "issue_number": number,
                                            "state": "closed", "state_reason": "completed"})))


def run_file(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    text = work_tickets.read_file(args.draft, "the retro draft")
    block = judged(text, args.retro)
    steps = file_steps(tracker, args.retro, report(text, block, args.retro))
    if work_tickets.hand_off():
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools:")
        print(steps.text())
    else:
        work_tickets.run_plan(steps, work_tickets.tracker_actions(root, tracker))
        print(f"Posted the report of retro #{args.retro} as its closing comment and closed it")
    kinds = [item["kind"] for item in block["findings"]]
    print(f"Retro #{args.retro}: {kinds.count(WORK)} {WORK} and {kinds.count(DECISION)} "
          f"{DECISION} finding(s); no issue filed: SE bundles the {WORK} findings into work "
          f"issues and puts the {DECISION} findings on the owner's decision list")
    return 0


def run_collect(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    remote = work_tickets.remote_repo(root) or tracker
    branch = work_tickets.integration_branch(root)
    ref = work_tickets.integration_ref(root)
    if args.answers is not None:
        door = FileDoor(args.answers, tracker, remote)
    elif work_tickets.hand_off():
        door = FileDoor(Path("<dir>"), tracker, remote)
    else:
        door = GhDoor(root, tracker, remote)
    found = collect(root, args.retro, door, tracker, branch, ref, datetime.now(timezone.utc))
    if found is None:
        directory = args.answers or Path("<dir>")
        then = (f"retro.py collect {args.retro} --answers {directory}"
                f"{f' --out {args.out}' if args.out else ''}{' --json' if args.json else ''}"
                f"{f' --repo {args.repo}' if args.repo else ''} --worktree {root}")
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools "
              f"and saves their answers into {directory}:")
        print(Plan(f"the window of retro #{args.retro}", tuple(door.missing), then).text())
        return 0
    output = (json.dumps(found.data(), indent=2, ensure_ascii=False) + "\n" if args.json
              else draft(found))
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"Wrote the retro draft of #{args.retro} to {args.out}: "
              + ", ".join(f"{value} {name}" for name, value in found.sizes.items()))
    else:
        sys.stdout.write(output)
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="retro.py", description=__doc__.split("\n\n")[0])
    commands = top.add_subparsers(dest="command", required=True)
    collect_command = commands.add_parser(
        "collect", help="read a retro's window from GitHub and write its draft",
        description="Read the window of a retro (every work issue closed since the last closed "
                    "retro issue closed) with each issue's field report, and write the draft: "
                    "sizes, per-issue counts, the reports' Retro and Not delivered sections, the "
                    f"rule checks, ending in a {BLOCK_MARKER} block.")
    collect_command.add_argument("retro", type=int, help="the retro issue's number")
    collect_command.add_argument("--out", type=Path, metavar="FILE",
                                 help="write the draft to FILE (default: print it)")
    collect_command.add_argument("--json", action="store_true",
                                 help="the block's data as JSON instead of the draft")
    collect_command.add_argument("--answers", type=Path, metavar="DIR",
                                 help="without gh: the directory the session saves the plan's "
                                      "answers into")
    collect_command.add_argument("--worktree", default=".",
                                 help="the checkout of the repository (default: .)")
    collect_command.add_argument("--repo", help="[HOST/]OWNER/REPO of the issues (default: the "
                                                "tracker or origin remote)")
    collect_command.set_defaults(run=run_collect)
    file_command = commands.add_parser(
        "file", help="check a judged retro draft and close the retro issue with its report",
        description="Check the judgment the judge wrote into the draft's block, refusing an "
                    "incomplete one and writing nothing; post the report (each finding with its "
                    f"proposed fix and kind, {WORK} or {DECISION}, then the facts and the block) "
                    "as the retro issue's closing comment and close it. It files no issue: SE "
                    "reads the report and files the work.")
    file_command.add_argument("retro", type=int, help="the retro issue's number")
    file_command.add_argument("--draft", type=Path, required=True, metavar="FILE",
                              help="the draft retro.py collect wrote, its block judged")
    file_command.add_argument("--worktree", default=".",
                              help="the checkout of the repository (default: .)")
    file_command.add_argument("--repo", help="[HOST/]OWNER/REPO of the issues (default: the "
                                             "tracker or origin remote)")
    file_command.set_defaults(run=run_file)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except QueueError as error:
        print(f"retro.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
