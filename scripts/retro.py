"""Retro commands: the mechanical half of a retro, the facts the judging agent starts from.

`retro.py collect <retro issue>` reads the window from GitHub: every work issue closed since the
last closed retro issue (titled `docs/retro-...` or labelled `retro`, other than this one) closed;
where none has, since the oldest open retro issue was created, and the whole history only where no
retro issue exists. `--since <date>` starts it at a date, `--retro <issue>` where that closed retro
issue closed (whose findings it then scores); the rule checks judge that window alone. Each issue
comes with the field report of the pull request that landed
it, found through the landing pull request's `<!-- se:field-report-in <n> -->` marker. It writes a
draft with

- the sizes: closed, landed, duplicates, escalated;
- per landed issue the deliveries `integrate` refused before it landed (its `Integration
  stopped:` comments), its escalations and the complete suite's time its `Integrated in` comment
  names;
- the field reports' Retro sections and their "Not delivered" items, grouped;
- the rule checks (RULE_CHECKS), each broken one with what broke it;
- the metrics of the window: the line each landing pull request's description ends in and the
  local metrics file's lines that started in the window, each run once (README "Metrics");
- the previous retro's sizes, where its block is found;

- the previous retro's findings, each scored: the work issues of the window that name it
  (`retro #<n> finding <k>`), whether one closed, and whether the rule check it names broke again
  (recurred);

and ends in a JSON block under BLOCK_MARKER (JSON is YAML too), which `read_block` parses back for
`retro.py file` and later collects. The judge fills the block's `findings`, `classes` and
`went_well`.

`retro.py file <retro issue> --draft FILE` refuses an incomplete judgment, writing nothing, and a
draft the integration branch does not hold as it stands; it files no issue (wrk-007). It posts the
report proper, the judgment with each finding's proposed fix and its kind (`work`, which SE
bundles into work issues, or `decision`, for the owner's decision list) and what follows, as the
retro issue's closing comment, and closes the issue. The facts and the block stay in the committed
draft, the retro doc, which the comment links at its commit (DOC_MARKER) and the next collect
reads. A report over GitHub's COMMENT_LIMIT is posted in numbered parts, never cut.

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
se_usage = sibling("se_usage")
QueueError = work_tickets.QueueError
Step, Plan = work_tickets.Step, work_tickets.Plan
metrics = work_tickets.metrics

BLOCK_MARKER = "<!-- se:retro-yaml -->"
REPORT_MARKER = "<!-- se:retro-report -->"
# The report's link to the committed retro doc that holds its facts and block, at a commit.
DOC_MARKER = "<!-- se:retro-doc {sha} {path} -->"
DOC_PATTERN = re.compile(r"<!-- se:retro-doc ([0-9a-f]{40}) (\S+) -->")
# GitHub's limit on an issue comment's body, in characters; a part's label needs at most
# PART_ROOM of them.
COMMENT_LIMIT = 65536
PART_ROOM = 100
JUDGE_BEGIN, JUDGE_END = "<!-- se:retro-judge -->", "<!-- se:retro-judge:end -->"
# A work issue names each retro finding it takes as `retro #<n> finding <k>`.
FINDING_REFERENCE = re.compile(r"\bretro #(\d+) finding (\d+)\b", re.IGNORECASE)
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
# A retro is due once this many work issues landed since the last one (se.toml [retro] due_after).
DUE_AFTER = 10
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
    created_at: str = ""


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
        updated_at=str(first(item, "updated_at", "updatedAt") or ""),
        created_at=str(first(item, "created_at", "createdAt") or ""))


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

    def open_issues(self) -> list[dict]:
        return [item for item in self.pages(self.issues_door, "issues?state=open")
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

    def open_issues(self) -> list[dict]:
        name = "open-issues.json"
        return listed(self.read(name, Step(name, "list_issues", {
            **work_tickets.owner_repo(self.tracker), "state": "OPEN", "perPage": 100},
            note=f"Every page; save the issues of all pages as one JSON list to "
                 f"{self.directory / name}")), "issues", "nodes")

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


# Where a window starts (Window.start): the close of the last closed retro issue (or of the one
# --retro names), the time --since gives, the creation of the oldest open retro issue where none
# has closed, or nowhere: the whole history, where no retro issue exists.
CLOSED_RETRO, GIVEN, OPEN_RETRO, HISTORY = "closed-retro", "given", "open-retro", "history"


@dataclass
class Window:
    retro: int
    since: str | None
    since_retro: int | None
    until: str
    start: str


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
    runs: list[dict] = field(default_factory=list)  # the window's metrics lines, each run once
    run_sources: dict[str, int] = field(default_factory=dict)  # lines read per source
    adhoc: list[dict] = field(default_factory=list)  # the ad hoc components to promote (se_usage)

    def data(self) -> dict:
        return {"version": BLOCK_VERSION, "window": asdict(self.window), "sizes": self.sizes,
                "issues": [asdict(item) for item in self.issues],
                "rule_checks": [{**asdict(check), "kept": check.kept} for check in self.checks],
                "metrics": {**self.run_sources, "runs": len(self.runs)},
                "adhoc": self.adhoc,
                "previous": self.previous, **{name: [] for name in JUDGMENT}}


def read_block(text: str, marker: str = BLOCK_MARKER) -> dict | None:
    """The data of the last block under `marker` in `text`; None where it has none."""
    at = text.rfind(marker)
    if at < 0:
        return None
    match = re.search(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", text[at:], re.MULTILINE | re.DOTALL)
    if match is None:
        raise QueueError(f"The {marker} block has no fenced block under it")
    try:
        data = json.loads(match[2])
    except json.JSONDecodeError as error:
        raise QueueError(f"The {marker} block is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise QueueError(f"The {marker} block is not an object")
    return data


def first_parent_commits(root: Path, ref: str) -> list[tuple[str, str, str]]:
    """The first-parent commits of `ref`, newest first: (sha, committer date, subject)."""
    output = work_tickets.checked_git(root, "log", "--first-parent", "--format=%H%x09%cI%x09%s",
                                      ref)
    return [tuple(line.split("\t", 2)) for line in output.splitlines() if line.count("\t") >= 2]


@dataclass
class Read:
    """What a window's reads give: the closed issues, the pull requests, the previous retro (the
    last closed retro other than the one collecting, or the one --retro names), where the window
    starts (`since`, from `since_retro`, by `start`) and the work issues closed after it."""

    issues: list[Issue]
    pulls: list[Pull]
    last: Issue | None
    window: list[Issue]
    since: str | None
    since_retro: int | None
    start: str

    def in_window(self, value: str) -> bool:
        moment, since = when(value), when(self.since)
        return moment is not None and (since is None or moment > since)


def window_start(door, last: Issue | None, since: str | None) -> tuple[str | None, int | None, str] | None:
    """Where the window starts, as (since, since_retro, start): the time `since` gives, else the
    close of `last`, else the creation of the oldest open retro issue (read through `door`), else
    the whole history; None where the door is still missing answers."""
    if since is not None:
        return since, None, GIVEN
    if last is not None:
        return last.closed_at, last.number, CLOSED_RETRO
    opened = [issue_of(item) for item in door.open_issues()]
    if door.missing:
        return None
    oldest = min((issue for issue in opened if is_retro(issue) and when(issue.created_at)),
                 key=lambda issue: when(issue.created_at), default=None)
    if oldest is None:
        return None, None, HISTORY
    return oldest.created_at, oldest.number, OPEN_RETRO


def read_window(door, number: int, since: str | None = None,
                retro: int | None = None) -> Read | None:
    """The window of retro `number` (0: of the next retro) read through `door`, starting at
    `since` or, with `retro`, where that closed retro issue closed; None where the door is still
    missing answers (`door.missing`)."""
    issues = [issue_of(item) for item in door.closed_issues()]
    pulls = [pull_of(item) for item in door.pulls()]
    if door.missing:
        return None

    def completed(chosen: list[Issue]) -> bool:
        """Each of `chosen` with its close time and reason, read one by one where the list
        named none; False while the door still misses answers."""
        for issue in chosen:
            if not issue.closed_at:
                read = issue_of(door.issue(issue.number))
                issue.closed_at, issue.state_reason = read.closed_at, read.state_reason
                issue.body = issue.body or read.body
        return not door.missing

    if not completed([issue for issue in issues if is_retro(issue) and issue.number != number]):
        return None
    retros = [issue for issue in issues if is_retro(issue) and issue.number != number
              and when(issue.closed_at)]
    if retro is not None:
        last = next((issue for issue in retros if issue.number == retro), None)
        if last is None:
            raise QueueError(f"--retro {retro}: #{retro} is no closed retro issue (titled "
                             f"{RETRO_TITLE}... or labelled {RETRO_LABEL}) other than #{number}")
    else:
        last = max(retros, key=lambda issue: when(issue.closed_at), default=None)
    start = window_start(door, last, since)
    if start is None:
        return None
    moment = when(start[0])
    # An issue closed in the window was updated in it: only those are read one by one.
    if not completed([issue for issue in issues if WORK_LABEL in issue.labels
                      and not is_retro(issue) and (moment is None or not issue.updated_at
                                                   or when(issue.updated_at) > moment)]):
        return None
    found = Read(issues, pulls, last, [], *start)
    found.window = sorted((issue for issue in issues if WORK_LABEL in issue.labels
                           and not is_retro(issue) and found.in_window(issue.closed_at)),
                          key=lambda issue: issue.number)
    return found


def landing_of(issue: Issue, naming: list[Pull], branch: str) -> Pull | None:
    """The newest pull request of `naming` (those naming `issue`) merged into `branch`."""
    return next((pull for pull in sorted(naming, key=lambda p: -p.number)
                 if pull.merged_at and pull.base == branch), None)


def is_duplicate(issue: Issue) -> bool:
    return issue.state_reason == "duplicate" or "duplicate" in issue.labels


def landed(issue: Issue, landing: Pull | None) -> bool:
    """Whether a work issue of the window landed: a pull request naming it merged into the
    integration branch, and it closed neither as a duplicate nor as not planned."""
    return landing is not None and not is_duplicate(issue) and issue.state_reason != "not_planned"


def landed_since_retro(door, tracker: str, branch: str) -> int | None:
    """How many work issues landed in the next retro's window, read through `door`; None where
    the door is still missing answers."""
    found = read_window(door, 0)
    if found is None:
        return None
    references = {pull.number: reference(pull, tracker) for pull in found.pulls}
    return sum(landed(issue, landing_of(issue, [pull for pull in found.pulls
                                                if references[pull.number] == issue.number],
                                        branch))
               for issue in found.window)


def due_after(root: Path) -> int:
    """`[retro] due_after` in se.toml: how many landed work issues make a retro due; built in
    DUE_AFTER."""
    count = work_tickets.se_table(root, "retro").get("due_after", DUE_AFTER)
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise QueueError(f"retro.due_after in {root / 'se.toml'} must be a positive whole number; "
                         f"fix it or remove it for the built-in {DUE_AFTER}")
    return count


def collect(root: Path, number: int, door, tracker: str, branch: str, ref: str,
            now: datetime, since: str | None = None, retro: int | None = None) -> Collected | None:
    """The window of retro `number` read through `door`, starting at `since` or where retro
    `retro` closed where given (`read_window`); None where the door is still missing answers
    (`door.missing`)."""
    read = read_window(door, number, since, retro)
    if read is None:
        return None
    issues, pulls, last, window, in_window = read.issues, read.pulls, read.last, read.window, read.in_window
    by_number = {issue.number: issue for issue in issues}
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
        landing = landing_of(issue, naming, branch)
        report_pull = None
        if landing is not None:
            marker = REPORT_IN.search(landing.body)
            carrier = pull_numbers.get(int(marker[1])) if marker else landing
            report_pull = carrier if carrier and report_of(carrier.body) else None
        if report_pull is None:
            report_pull = next((pull for pull in sorted(naming, key=lambda p: -p.number)
                                if report_of(pull.body)), None)
        report = report_of(report_pull.body) if report_pull else None
        duplicate = is_duplicate(issue)
        closed.append(Closed(
            number=issue.number, title=issue.title, state_reason=issue.state_reason or "completed",
            duplicate=duplicate,
            landed=landed(issue, landing),
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
        if door.missing:
            return None
        previous = posted_block(texts, last.number, git_show(root))
    # The window's metrics: the local file's lines that started in it, and the line each landing
    # pull request's description ends in, which outlives a cloud integrator's container; a run in
    # both counts once, by its local line (README "Metrics").
    local = [line for line in metrics.read(metrics.path())[0] if in_window(str(line["start"]))]
    landed_runs = [line for pull in landings if (line := metrics.of_text(pull.body)) is not None]
    runs = metrics.merged(local, landed_runs)
    scored = scored_findings(previous, last.number if last else 0, window, checks)
    sizes = {"closed": len(closed), "landed": sum(item.landed for item in closed),
             "duplicates": sum(item.duplicate for item in closed),
             "escalated": sum(item.escalations > 0 for item in closed)}
    # The ad hoc components to promote: those the use log (se_usage) shows used in enough sessions
    # in this window, by the window's own `in_window` on each use's time.
    adhoc = se_usage.candidates(se_usage.read(root), read.in_window)
    return Collected(
        Window(number, read.since, read.since_retro,
               now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), read.start),
        sizes, closed, list(checks.values()),
        {"retro": last.number, "sizes": previous.get("sizes"), "findings": scored}
        if previous else None, runs, {"landings": len(landed_runs), "local": len(local)}, adhoc)


def scored_findings(previous: dict | None, retro: int, window: list[Issue],
                    checks: dict[str, RuleCheck]) -> list[dict]:
    """Each finding of the previous retro's block, scored against this window: the work issues
    closed in it that name the finding (`retro #<retro> finding <k>`), its state (closed where one
    of them closed as completed, else the reason they closed with, else none) and whether the rule
    check it names broke again (recurred)."""
    found: list[dict] = []
    for index, finding in enumerate((previous or {}).get("findings") or [], 1):
        if not isinstance(finding, dict):
            continue
        number = int(finding.get("finding") or index)
        naming = [issue for issue in window
                  if any(int(match[1]) == retro and int(match[2]) == number
                         for match in FINDING_REFERENCE.finditer(issue.body))]
        reasons = [issue.state_reason or "completed" for issue in naming]
        state = ("closed" if "completed" in reasons else reasons[0] if reasons else "none")
        check = str(finding.get("check") or "")
        found.append({"finding": number, "title": str(finding.get("title") or ""),
                      "class": str(finding.get("class") or ""), "kind": finding.get("kind"),
                      "check": check, "issues": [issue.number for issue in naming],
                      "state": state,
                      "recurred": bool(check) and check in checks and not checks[check].kept})
    return found


def draft(found: Collected) -> str:
    """The draft as the judging agent reads it, ending in the block `read_block` parses."""
    window = found.window
    lines = [f"# Retro draft for #{window.retro}", ""]
    starts = {
        CLOSED_RETRO: f"when retro #{window.since_retro} closed",
        GIVEN: "as --since gives",
        OPEN_RETRO: f"when retro #{window.since_retro}, the oldest open retro issue, was created; "
                    "no retro issue has closed"}
    if window.since:
        lines.append(f"Window: work issues closed after {window.since}, {starts[window.start]}, "
                     f"up to {window.until}.")
    else:
        lines.append(f"Window: the whole history up to {window.until}; no retro issue exists.")
    previous = (found.previous or {}).get("sizes") or {}
    lines += ["", "## Sizes", ""]
    if previous:
        lines += [f"| size | this window | retro #{found.previous['retro']} |", "|---|---|---|"]
        lines += [f"| {name} | {value} | {previous.get(name, '')} |"
                  for name, value in found.sizes.items()]
    else:
        lines += ["| size | this window |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in found.sizes.items()]
    scored = (found.previous or {}).get("findings") or []
    if found.previous:
        lines += ["", f"## The findings of retro #{found.previous['retro']}", ""]
    if scored:
        lines += ["| finding | class | kind | issues | state | recurred |",
                  "|---|---|---|---|---|---|"]
        for item in scored:
            issues = ", ".join(f"#{number}" for number in item["issues"]) or "none"
            recurred = (("yes" if item["recurred"] else "no") + f" ({item['check']})"
                        if item["check"] else "no check named")
            lines.append(f"| {item['finding']}. {item['title']} | {item['class']} | "
                         f"{item['kind'] or ''} | {issues} | {item['state']} | {recurred} |")
    elif found.previous:
        lines.append("None.")
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
    lines += ["", "## Metrics", "",
              f"{len(found.runs)} runs: {found.run_sources.get('landings', 0)} from the landing "
              f"pull requests, {found.run_sources.get('local', 0)} from {metrics.path()}, each run "
              "once.", "", "```text", metrics.report(found.runs), "```"]
    lines += ["", "## Ad hoc components to promote", ""]
    if found.adhoc:
        lines += [f"Used in {se_usage.PROMOTE_SESSIONS} or more sessions since the last retro; "
                  "promote each to a tracked component (docs/go-core.md).", "",
                  "| component | sessions | uses | path |", "|---|---|---|---|"]
        lines += [f"| {c['component']} | {c['sessions']} | {c['uses']} | `{c['path']}` |"
                  for c in found.adhoc]
    else:
        lines.append("None.")
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


def finding_basics(given: dict, index: int, fields: tuple[str, ...]) -> tuple[str, list[str]]:
    """Finding `index`'s name and what keeps its shared parts from being complete: a field not
    in `fields`, a title of fewer than TITLE_WORDS words, no body."""
    title = review.words(given.get("title"))
    name = f'finding {index} ("{title}")' if title else f"finding {index}"
    problems = [f"{name} has the unknown field {extra}"
                for extra in sorted(set(given) - set(fields))[:1]]
    if len(title.split()) < TITLE_WORDS:
        problems.append(f"{name} needs a title of {TITLE_WORDS} words or more that names the fix")
    if not review.words(given.get("body")):
        problems.append(f"{name} has no body")
    return name, problems


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
    recurred = {item.get("check") for item in ((block.get("previous") or {}).get("findings") or [])
                if isinstance(item, dict) and item.get("recurred")}
    for index, given in enumerate(lists["findings"], 1):
        if not isinstance(given, dict):
            problems.append(f"finding {index} is not an object with {', '.join(FINDING_FIELDS)}")
            continue
        name, found = finding_basics(given, index, FINDING_FIELDS)
        problems += found
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
        elif check and check in recurred and controversial is not True:
            problems.append(f'{name} names the check "{check}", which recurred after the '
                            "previous retro's fix, so it is controversial, with its why")
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


def facts_of(text: str, marker: str = BLOCK_MARKER,
             judge: tuple[str, str] = (JUDGE_BEGIN, JUDGE_END)) -> str:
    """The draft's facts: its text between the title and the block under `marker`, without the
    judging note between `judge`'s markers, its headings two levels down, under the report's
    "The facts"."""
    head = text[:text.rfind(marker)]
    head = re.sub(rf"{re.escape(judge[0])}.*?{re.escape(judge[1])}", "", head,
                  flags=re.DOTALL)
    lines = head.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return review.demoted("\n".join(lines)).strip()


def report(block: dict, number: int, doc: str, url: str, sha: str) -> str:
    """The retro's report proper, its closing comment: the judgment, each finding with its
    proposed fix and kind, what follows, then the link to the committed retro doc `doc` at commit
    `sha` (`url`), which holds the facts and the block the next collect reads."""
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
              "", "### The facts", "",
              f"The facts (sizes, landed issues, rule checks, metrics, the field reports' Retro "
              f"and Not delivered sections) and the block the next retro reads are in the "
              f"committed retro doc [{doc}]({url}), at {sha[:12]}.", "",
              DOC_MARKER.format(sha=sha, path=doc)]
    return "\n".join(lines) + "\n"


def parts(text: str, number: int, limit: int = COMMENT_LIMIT) -> list[str]:
    """`text` as the comments that post it: itself where it fits in `limit` characters, else
    numbered parts, cut at line ends (a longer line within it), each labelled `Part k of n`;
    nothing is left out."""
    if len(text) <= limit:
        return [text]
    size = limit - PART_ROOM
    chunks = [""]
    for line in text.splitlines(keepends=True):
        while line:
            if chunks[-1] and len(chunks[-1]) + len(line) > size:
                chunks.append("")
            room = size - len(chunks[-1])
            chunks[-1], line = chunks[-1] + line[:room], line[room:]
    total = len(chunks)
    return [f"{chunk.rstrip(chr(10))}\n\n_Part {index} of {total} of the report of retro "
            f"#{number}._\n" for index, chunk in enumerate(chunks, 1)]


def committed_doc(root: Path, draft: Path, text: str, ref: str) -> tuple[str, str]:
    """(the draft's path in the checkout, the commit of `ref`) where `ref` holds the draft as
    `text` reads; refused otherwise, since the report links to it for its facts and block."""
    try:
        doc = draft.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise QueueError(f"The draft {draft} is not in the checkout {root}: the report links to "
                         "the committed retro doc for its facts and block, so commit the draft "
                         f"under docs/ and land it on {ref.split('/')[-1]} first") from None
    sha = work_tickets.checked_git(root, "rev-parse", f"{ref}^{{commit}}").strip()
    shown = work_tickets.run_git(root, "show", f"{sha}:{doc}")
    if shown.returncode != 0 or shown.stdout.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
        raise QueueError(f"{ref} at {sha[:12]} does not hold the draft {doc} as it stands: the "
                         "report links to the committed retro doc for its facts and block, so "
                         f"land the draft on {ref.split('/')[-1]} first (sync and file again), "
                         "and nothing was written")
    return doc, sha


def doc_url(repo: str, sha: str, doc: str) -> str:
    host = work_tickets.repo_host(repo) or "github.com"
    return "https://" + f"{host}/{work_tickets.api_repo(repo)}/blob/{sha}/{doc}"


def git_show(root: Path):
    """A reader of `<sha>:<path>` from the checkout at `root`: the text, None where it has none."""
    def show(sha: str, path: str) -> str | None:
        shown = work_tickets.run_git(root, "show", f"{sha}:{path}")
        return shown.stdout if shown.returncode == 0 else None
    return show


def posted_block(texts: list[str], number: int, show) -> dict | None:
    """The judged block of filed retro `number`: from the retro doc the last of `texts` (its
    body and comments) links (DOC_MARKER), read with `show(sha, path)`; None where none links
    one."""
    links = [match for text in texts for match in DOC_PATTERN.finditer(text)]
    if not links:
        return None
    sha, doc = links[-1][1], links[-1][2]
    text = show(sha, doc)
    if text is None:
        raise QueueError(f"Retro #{number}'s report links {doc} at {sha[:12]}, which the checkout "
                         "does not hold: run work_tickets.py sync and read again")
    return judged(text, number)


def file_steps(tracker: str, number: int, comments: list[str], what: str = "retro") -> Plan:
    """The writes: the report as the `what` issue's closing comments, in order, then the
    close."""
    issues = work_tickets.owner_repo(tracker)
    posts = tuple(Step("comment_issue", "add_issue_comment", {
        **issues, "issue_number": number, "body": comment},
        note=f"Part {index} of {len(comments)}: post the parts in order" if len(comments) > 1
        else "") for index, comment in enumerate(comments, 1))
    return Plan(f"the report of {what} #{number}", (
        *posts,
        Step("close_issue", "issue_write", {**issues, "method": "update", "issue_number": number,
                                            "state": "closed", "state_reason": "completed"})))


def run_file(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    text = work_tickets.read_file(args.draft, "the retro draft")
    block = judged(text, args.retro)
    doc, sha = committed_doc(root, args.draft, text, work_tickets.integration_ref(root))
    url = doc_url(work_tickets.remote_repo(root) or tracker, sha, doc)
    comments = parts(report(block, args.retro, doc, url, sha), args.retro)
    steps = file_steps(tracker, args.retro, comments)
    if work_tickets.hand_off():
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools:")
        print(steps.text())
    else:
        work_tickets.run_plan(steps, work_tickets.tracker_actions(root, tracker))
        print(f"Posted the report of retro #{args.retro} as its closing comment and closed it")
    sizes = ", ".join(f"{len(comment)}" for comment in comments)
    print(f"Retro #{args.retro}: the report in {len(comments)} comment(s) of {sizes} characters "
          f"(limit {COMMENT_LIMIT}), linking {doc} at {sha[:12]} for the facts and the block")
    kinds = [item["kind"] for item in block["findings"]]
    print(f"Retro #{args.retro}: {kinds.count(WORK)} {WORK} and {kinds.count(DECISION)} "
          f"{DECISION} finding(s); no issue filed: SE bundles the {WORK} findings into work "
          f"issues and puts the {DECISION} findings on the owner's decision list")
    return 0


def since_of(value: str | None) -> str | None:
    """`--since`, a date (YYYY-MM-DD, its midnight UTC) or an ISO time, as GitHub writes times."""
    if value is None:
        return None
    try:
        moment = when(value)
    except ValueError:
        raise QueueError(f"--since {value}: give a date (YYYY-MM-DD) or an ISO time") from None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    found = collect(root, args.retro, door, tracker, branch, ref, datetime.now(timezone.utc),
                    since_of(args.since), args.since_retro)
    if found is None:
        directory = args.answers or Path("<dir>")
        window = (f" --since {args.since}" if args.since else "") + (
            f" --retro {args.since_retro}" if args.since_retro is not None else "")
        then = (f"retro.py collect {args.retro}{window} --answers {directory}"
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
                    "retro issue closed, or the oldest open one was created where none has, or "
                    "since --since or --retro) with each issue's field report, and write the draft: "
                    "sizes, per-issue counts, the reports' Retro and Not delivered sections, the "
                    f"rule checks, ending in a {BLOCK_MARKER} block.")
    collect_command.add_argument("retro", type=int, help="the retro issue's number")
    start = collect_command.add_mutually_exclusive_group()
    start.add_argument("--since", metavar="DATE",
                       help="start the window at DATE (YYYY-MM-DD, or an ISO time)")
    start.add_argument("--retro", type=int, dest="since_retro", metavar="ISSUE",
                       help="start the window where the closed retro issue ISSUE closed, and "
                            "score its findings")
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
                    f"proposed fix and kind, {WORK} or {DECISION}, and a link to the draft "
                    "committed on the integration branch, which holds the facts and the block) "
                    f"as the retro issue's closing comment, in numbered parts over {COMMENT_LIMIT} "
                    "characters, and close it. It files no issue: SE reads the report and files "
                    "the work.")
    file_command.add_argument("retro", type=int, help="the retro issue's number")
    file_command.add_argument("--draft", type=Path, required=True, metavar="FILE",
                              help="the draft retro.py collect wrote, its block judged, "
                                   "committed on the integration branch as it stands")
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
