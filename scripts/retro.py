"""Retro commands: the mechanical half of a retro, the facts the judging agent starts from.

`retro.py collect <retro issue>` reads the window from GitHub: every work issue closed since the
last closed retro issue (titled `docs/retro-...` or labelled `retro`, other than this one) closed;
where none has, since the oldest open retro issue was created, and the whole history only where no
retro issue exists. `--since <date>` starts it at a date, `--retro <issue>` where that closed retro
issue closed (whose findings it then scores); the rule checks judge that window alone. Each issue
comes with the field report of the pull request that landed
it, found through the landing pull request's `<!-- se:field-report-in <n> -->` marker. It writes a
draft that is a document of the retro template (TEMPLATE_NAME, `templates/retro.md`), its six steps
(field feedback, collect, the table of what happened, the standing questions with their matrix,
classes and homes, the person's decisions; `draft`), each step's heading and instruction the
template's. Step 2, collect, holds

- the sizes: closed, landed, duplicates, escalated;
- per landed issue the deliveries `integrate` refused before it landed (its `Integration
  stopped:` comments), its escalations and the complete suite's time its `Integrated in` comment
  names;
- the field reports' answers to the standing questions (their Retro section, the block
  work_tickets.py `standing_questions` nests; `retro_entries`) by question, and their "Not
  delivered" items, the planning misses;
- the rule checks (RULE_CHECKS), each broken one with what broke it;
- the metrics of the window: the line each landing pull request's description ends in and the
  local metrics file's lines that started in the window, each run once (README "Metrics");
- the previous retro's sizes, where its block is found;
- the breaking-release check over the project's component tree (se_modules.py `breaking`), which
  every collect runs once its answers are all there;

- the previous retro's findings, each scored: the work issues of the window that name it
  (`retro #<n> finding <k>`), whether one closed, and whether the rule check it names broke again
  (recurred); where the overhaul countdown is on (overhaul.py countdown_on), one that an open issue
  takes is too early to score (TOO_EARLY), neither;
- the previous retro's classes measured again (`class_patterns`): rate before, its findings per
  work issue it closed, against rate now, the issues of the window its pattern matches, per issue;

step 3 the timeline in chapters of up to CHAPTER_HOURS, by when each issue came back (`chapters`),
and per step (each issue) what went well, what it cost and whether a machine could do it, from its
record and field report; step 4 the matrix of the standing questions against the chapters, each
cell the issues whose report answers it there, and the questions for the judge to answer; step 5
the home order (HOMES) and the previous retro's classes against the tree (`tree_state`: FIXED, PAST
or OPEN). It ends in a JSON block under BLOCK_MARKER (JSON is YAML too), which `read_block` parses back for
`retro.py file` and later collects. The judge fills the block's `findings`, `classes` and
`went_well`; a class has CLASS_FIELDS, one cause and one fix, its home and the kind of home, the
first of HOMES that holds.

Off by default, three additions leave that draft as it is without them:

- `--signals FILE...` runs the pure functions of the transcript reader (transcript_signals.py, its
  more signals among them) over the session records given and adds a block of counts with a line
  per source; where no file was read it says so, never zero findings (`session_signals`).
- `--refusals` lists each refused delivery (the `Integration stopped:` comments collect already
  reads) and each declined review (the verdict block review.py writes on the pull request that a
  work issue's escalation comment names) with its link, its author's association, inside or
  outside by outside_text.py's `inside` over INSIDE, and its first FIRST_LINES lines in
  outside_text.py's envelope, as data (`refusal_records`).
- `--sessions FILE`, the session tools' answers (each session `list_sessions` lists with its
  `list_events` result events as `"events"`), adds each cloud session's cost, its tokens and its
  cost in dollars from its result events, found by its title (`SE/<repo>/<role>/<topic>`, the work
  model's Visible sessions) and summed per issue, role and repository (`cloud_costs`).
- A class of the judgment may carry the optional keys CLASS_KEYS (`status`, `pattern`, a regular
  expression, and `limits`); the next collect counts each earlier class's pattern over what it
  already reads of each work issue of the window (title, body, comments, field report) and lists
  the classes that carry one (`class_patterns`). A block without them is scored and filed as
  before.

`retro.py file <retro issue> --draft FILE` refuses an incomplete judgment, writing nothing, a
draft whose steps break the retro template (a step or a standing question left open;
`steps_problems`) and a draft the integration branch does not hold as it stands; it files no issue
(wrk-007). It posts the report proper, a document of the retro template (`report`): the draft's
steps, the judgment in step 5, each class with its home and its state against the tree and each
finding with its proposed fix and its kind (`work`, which SE bundles into work issues, or
`decision`, for the owner's decision list), and the person's decisions and what follows in step 6,
as the retro issue's closing comment, and closes the issue. The facts and the block stay in the committed
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
# A class: one cause and one fix, the fix's home (the file it changes) and the kind of home it is,
# one of HOMES.
CLASS_FIELDS = ("name", "cause", "fix", "home", "home_kind")
# The optional keys of a class: its status, the pattern (a regular expression) the next collect
# counts over the window, the limits of its fix, and its mark, a text the fix leaves in its home,
# which the tree check looks for (`tree_state`).
CLASS_KEYS = ("status", "pattern", "limits", "mark")
# The homes of a fix, strongest first: a class's home is the first of them that holds (step 5).
HOMES = ("check", "refusal", "gate", "prefill", "checklist line", "command", "setting", "sentence")
# A class checked against the tree (`tree_state`): its fix is in its home (FIXED), it no longer
# comes back though its fix is not there (PAST), or neither (OPEN), which the person decides.
FIXED, PAST, OPEN = "fixed", "past", "open"
# The timeline's chapters: a chapter takes every event up to this many hours after its first.
CHAPTER_HOURS = 6
# The retro document template: the six steps, the standing questions nested in step 4.
TEMPLATE_NAME = "retro"
# The field report's answers that say whether a machine could do a step (step 3).
MECHANIZE = ("machine_scripts", "shell_command")
# The author associations `--refusals` counts as inside the fleet (outside_text.inside).
INSIDE = ("OWNER", "MEMBER", "COLLABORATOR")
# How many of a refusal's first lines `--refusals` shows.
FIRST_LINES = 3
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
# The escalation comment review.py writes on the work issue of a declined pull request.
DECLINED = re.compile(r"^Declined by the review of pull request #(\d+) \((\S+?)\)")
REFUSED_DELIVERY, DECLINED_REVIEW = "refused delivery", "declined review"
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
# A retro is due once what came back since the last one weighs this much (se.toml [retro]
# due_after): a landing 1, a failure its failure_weight (SETTINGS).
DUE_AFTER = 20
# The state of an earlier run's finding whose issue is still open: it had no time to land, so the
# run lists it and scores it neither way (no failure, no recurrence).
TOO_EARLY = "too early to score"
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
        self.remote = remote
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

    def pages_until(self, door, path: str, stop) -> list[dict]:
        """`pages` of `path` sorted newest update first, up to the first item `stop` refuses."""
        found: list[dict] = []
        page = 1
        while True:
            answer = door.api(f"{path}&sort=updated&direction=desc&per_page={self.PAGE}&page={page}")
            items = [item for item in (answer if isinstance(answer, list) else [])
                     if isinstance(item, dict)]
            for item in items:
                if stop(item):
                    return found
                found.append(item)
            if len(items) < self.PAGE:
                return found
            page += 1

    def closed_issues_until(self, stop) -> list[dict]:
        return [item for item in self.pages_until(self.issues_door, "issues?state=closed", stop)
                if "pull_request" not in item]

    def closed_issues_labelled(self, label: str) -> list[dict]:
        return self.pages(self.issues_door, f"issues?state=closed&labels={label}")

    def pulls_until(self, stop) -> list[dict]:
        return self.pages_until(self.pulls_door, "pulls?state=closed", stop)

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

    def pull_comments(self, number: int) -> list[dict]:
        return listed(self.pulls_door.api(f"issues/{number}/comments?per_page=100"), "comments")


class FileDoor:
    """The same reads from the answers the session saved with its GitHub tools into `directory`:
    `issues.json`, `pulls.json`, `issue-<issue>.json` (where the list names no close time, as
    the host's `list_issues` does not), `comments-<issue>.json`, `checks-<pull>.json` and, for
    `--refusals`, `pull-comments-<pull>.json` of each declined pull request. A missing
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

    def pull_comments(self, number: int) -> list[dict]:
        name = f"pull-comments-{number}.json"
        return listed(self.read(name, Step(name, "pull_request_read", {
            **work_tickets.owner_repo(self.remote), "method": "get_comments",
            "pullNumber": number},
            note=f"Save the answer as JSON to {self.directory / name}")), "comments")


class ToolDoor:
    """The countdowns' reads through kern's relay door (work_tickets.RelayDoor), where a command
    runs as one call: each list page by page, as the host's GitHub tools answer it."""

    def __init__(self, door) -> None:
        self.door = door
        self.missing: list[Step] = []

    def closed_issues(self) -> list[dict]:
        return self.door.issues("CLOSED")

    def open_issues(self) -> list[dict]:
        return self.door.issues("OPEN")

    def pulls(self) -> list[dict]:
        found: list[dict] = []
        page = 1
        while True:
            items = work_tickets.tool_items(self.door.ask("list_pull_requests", {
                "state": "closed", "perPage": 100, "page": page}), "pull_requests")
            found += items
            if len(items) < 100:
                return found
            page += 1

    def issue(self, number: int) -> dict:
        answer = self.door.ask("issue_read", {"method": "get", "issue_number": number})
        return answer if isinstance(answer, dict) else {}


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


def templates():
    return sibling("templates")


def questions():
    """The standing questions, the block the retro, the overhaul and the field report nest."""
    return work_tickets.standing_questions()


def retro_entries(report: str) -> dict[str, str]:
    """The field report's answers to the standing questions (its Retro section), by question
    field; a question left out or answered None is not in it."""
    text = section(report, work_tickets.QUESTIONS_SECTION)
    return {name: one_line(answer)
            for name, answer in templates().answers(questions(), text).items()}


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
    # The field report's answers to the standing questions, by question field (`retro_entries`).
    retro: dict[str, str] = field(default_factory=dict)
    not_delivered: list[str] = field(default_factory=list)
    # When it came back: its landing's merge, else its close; the timeline orders by it.
    at: str = ""


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
    scripts: list[dict] = field(default_factory=list)  # the most-run ad hoc scripts (se_usage)
    # Off by default, outside the block: the session signals (--signals) and the refused
    # deliveries and declined reviews (--refusals); None where not asked for.
    signals: dict | None = None
    refusals: list[dict] | None = None
    costs: dict | None = None  # the cloud sessions' costs (--sessions)
    # The breaking-release check of the project's component tree, which run_collect runs at every
    # retro (`breaking_releases`); None where it did not run.
    breaking: dict | None = None

    def extras(self) -> dict:
        """What the flags asked for, by name: `--json` adds it beside the block's data."""
        return {name: value for name, value in (("signals", self.signals),
                                                ("refusals", self.refusals),
                                                ("costs", self.costs),
                                                ("breaking", self.breaking))
                if value is not None}

    def chapters(self) -> list[dict]:
        """The window's timeline (`chapters`)."""
        return chapters(self.issues)

    def data(self) -> dict:
        return {"version": BLOCK_VERSION, "window": asdict(self.window), "sizes": self.sizes,
                "issues": [asdict(item) for item in self.issues],
                "chapters": self.chapters(),
                "rule_checks": [{**asdict(check), "kept": check.kept} for check in self.checks],
                "metrics": {**self.run_sources, "runs": len(self.runs)},
                "adhoc": self.adhoc, "scripts": self.scripts,
                "previous": self.previous, **{name: [] for name in JUDGMENT}}


def chapters(issues: list[Closed]) -> list[dict]:
    """The timeline of `issues` in chapters, oldest first: each takes the issues that came back
    (`Closed.at`) up to CHAPTER_HOURS after its first, with its first and last time; an issue
    without a time comes last, in a chapter of its own."""
    timed = sorted((item for item in issues if when(item.at)), key=lambda item: when(item.at))
    found: list[dict] = []
    for item in timed:
        moment = when(item.at)
        if not found or (moment - when(found[-1]["start"])).total_seconds() > CHAPTER_HOURS * 3600:
            found.append({"chapter": len(found) + 1, "start": item.at, "end": item.at, "issues": []})
        found[-1]["end"] = item.at
        found[-1]["issues"].append(item.number)
    untimed = [item.number for item in issues if not when(item.at)]
    if untimed:
        found.append({"chapter": len(found) + 1, "start": "", "end": "", "issues": untimed})
    return found


def read_block(text: str, marker: str = BLOCK_MARKER) -> dict | None:
    """The data of the last block under `marker` in `text`; None where it has none."""
    text = text.replace("\r\n", "\n")  # a draft saved on Windows
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


def run_start(issue: Issue) -> datetime | None:
    """When a run (a retro or an overhaul issue) started: its creation, else, where the list
    names none, its close."""
    return when(issue.created_at) or when(issue.closed_at)


def counted_run(issue: Issue) -> bool:
    """A run that counts: not closed as a duplicate or as not planned."""
    return not is_duplicate(issue) and issue.state_reason != "not_planned"


@dataclass
class Countdown:
    """When a retro or an overhaul falls due (README "Retro due"): what came back since the newest
    run of that kind started (`since`, from run `since_run`; None: the whole history), weighted
    into `count`, and whether that, or `days` days since the start with anything come back, makes
    one due; with the runs of that kind still open."""

    kind: str
    since: str | None
    since_run: int | None
    landed: int
    failed: int
    count: int
    due_after: int
    days: int
    elapsed_days: int
    due: bool
    reason: str
    open: list[int] = field(default_factory=list)


def due_reason(kind: str, count: int, what: str, due_after: int, days: int, elapsed: int) -> str:
    """Why a countdown is due, or "" where it is not: `count` at or above `due_after` (0: that
    rule off), or `days` days (0: off) since its start with anything counted."""
    if due_after and count >= due_after:
        return f"{count} {what} since the last {kind} (due at {due_after})"
    if days and count and elapsed >= days:
        return f"{elapsed} days since the last {kind} with {count} {what} (due after {days} days)"
    return ""


def retro_countdown(closed: list[Issue], opened: list[Issue], pulls: list[Pull], tracker: str,
                    branch: str, settings: dict[str, int], now: datetime) -> Countdown:
    """The retro countdown, a pure function of the issues and pull requests it is given: what
    came back since the newest retro started (its creation: a retro's counters reset when it
    starts, so a late retro never makes the next one due at once). A work issue that landed adds
    1; a work issue labelled ESCALATED_LABEL (an escalation or a refused landing) updated since
    then adds `failure_weight`. Opening an issue counts nothing. components/retro-due counts the
    same."""
    runs = [issue for issue in [*closed, *opened] if is_retro(issue) and counted_run(issue)
            and run_start(issue)]
    newest = max(runs, key=run_start, default=None)
    since = run_start(newest) if newest else None

    def after(value: str) -> datetime | None:
        moment = when(value)
        return moment if moment and (since is None or moment > since) else None

    naming: dict[int, list[Pull]] = {}
    for pull in pulls:
        number = reference(pull, tracker)
        if number is not None:
            naming.setdefault(number, []).append(pull)
    moments: list[datetime] = []
    landed = failed = 0
    for issue in closed:
        moment = after(issue.closed_at)
        if (WORK_LABEL in issue.labels and not is_retro(issue) and moment
                and landed_issue(issue, naming.get(issue.number, []), branch)):
            landed += 1
            moments.append(moment)
    for issue in [*closed, *opened]:
        moment = after(issue.updated_at)
        if WORK_LABEL in issue.labels and ESCALATED_LABEL in issue.labels and not is_retro(issue) and moment:
            failed += 1
            moments.append(moment)
    count = landed + failed * settings["failure_weight"]
    start = since or min(moments, default=None)
    elapsed = (now - start).days if start else 0
    reason = due_reason("retro", count, "came back", settings["due_after"], settings["days"],
                        elapsed)
    return Countdown("retro", newest.created_at or newest.closed_at if newest else None,
                     newest.number if newest else None, landed, failed, count,
                     settings["due_after"], settings["days"], elapsed, bool(reason), reason,
                     sorted(issue.number for issue in opened if is_retro(issue)))


def landed_issue(issue: Issue, naming: list[Pull], branch: str) -> bool:
    return landed(issue, landing_of(issue, naming, branch))


def recent_reads(door, opened: list[Issue], overhauls: bool) -> tuple[list[Issue], list[Pull]]:
    """The closed issues and pull requests the countdowns need, read newest update first and only
    back to the start of the newest counted retro (and, with `overhauls`, overhaul): an older
    item cannot count, as an item's update is never before its start or close."""
    overhaul = sibling("overhaul")
    newest: dict[str, datetime | None] = {"retro": None, "overhaul": None}

    def note(issue: Issue) -> None:
        start = run_start(issue)
        if not start or not counted_run(issue):
            return
        for kind, test in (("retro", is_retro), ("overhaul", overhaul.is_overhaul)):
            if test(issue) and (newest[kind] is None or start > newest[kind]):
                newest[kind] = start

    def cutoff(kinds: tuple[str, ...]) -> datetime | None:
        starts = [newest[kind] for kind in kinds]
        return None if None in starts else min(starts)

    for issue in opened:
        note(issue)
    runs: list[Issue] = []
    for label in (RETRO_LABEL, overhaul.OVERHAUL_LABEL):
        for item in door.closed_issues_labelled(label):
            issue = issue_of(item)
            if "pull_request" not in item and (is_retro(issue) or overhaul.is_overhaul(issue)):
                note(issue)
                runs.append(issue)
    kinds = ("retro",)
    closed: list[Issue] = []

    def stop_issue(item: dict) -> bool:
        issue = issue_of(item)
        limit, updated = cutoff(kinds), when(issue.updated_at)
        if limit and updated and updated < limit:
            return True
        if "pull_request" not in item:
            note(issue)
            closed.append(issue)
        return False

    door.closed_issues_until(stop_issue)
    seen = {issue.number for issue in closed}
    closed += [issue for issue in runs if issue.number not in seen and not seen.add(issue.number)]
    limit = cutoff(("retro",))

    def stop_pull(item: dict) -> bool:
        updated = when(str(item.get("updated_at") or item.get("updatedAt") or ""))
        return bool(limit and updated and updated < limit)

    return closed, [pull_of(item) for item in door.pulls_until(stop_pull)]


def countdowns(door, tracker: str, branch: str, root: Path,
               now: datetime) -> dict[str, Countdown] | None:
    """The retro and the overhaul countdowns over what `door` reads: the closed and the open
    issues and the pull requests, each closed issue's close time read one by one where the list
    names none (the host's `list_issues`), only for those updated since the newest run started;
    None where the door is still missing answers."""
    opened = [issue_of(item) for item in door.open_issues()]
    if hasattr(door, "closed_issues_until"):
        closed, pulls = recent_reads(door, opened, sibling("overhaul").countdown_on(root))
    else:
        closed = [issue_of(item) for item in door.closed_issues()]
        pulls = [pull_of(item) for item in door.pulls()]
    if door.missing:
        return None
    overhaul = sibling("overhaul")
    starts = [run_start(issue) for issue in [*closed, *opened]
              if (is_retro(issue) or overhaul.is_overhaul(issue)) and issue.created_at]
    oldest = min((moment for moment in starts if moment), default=None)
    for issue in closed:
        if issue.closed_at:
            continue
        run = is_retro(issue) or overhaul.is_overhaul(issue)
        if run or (WORK_LABEL in issue.labels and (oldest is None or not issue.updated_at
                                                   or when(issue.updated_at) > oldest)):
            read = issue_of(door.issue(issue.number))
            issue.closed_at, issue.state_reason = read.closed_at, read.state_reason
            issue.created_at = issue.created_at or read.created_at
    if door.missing:
        return None
    return {"retro": retro_countdown(closed, opened, pulls, tracker, branch,
                                     settings(root, "retro"), now),
            "overhaul": overhaul.overhaul_countdown(closed, opened, settings(root, "overhaul"),
                                                    now)}


# The countdowns' settings (se.toml [retro] and [overhaul], README "Retro due"), each with its
# built-in: how much makes a run due, what a failure weighs, and after how many days one with
# anything to look at is due. 0 switches a rule off, except a retro's due_after.
SETTINGS = {"retro": {"due_after": DUE_AFTER, "failure_weight": 5, "days": 7},
            "overhaul": {"due_after": 3, "days": 30}}


def settings(root: Path, table: str) -> dict[str, int]:
    """`[<table>]` of se.toml as SETTINGS reads it, each key checked: a whole number, 0 for off
    (a retro's due_after positive)."""
    given = work_tickets.se_table(root, table)
    found = {}
    for key, default in SETTINGS[table].items():
        value = given.get(key, default)
        least = 1 if (table, key) == ("retro", "due_after") else 0
        if isinstance(value, bool) or not isinstance(value, int) or value < least:
            kind = "a positive whole number" if least else "a whole number, 0 for off"
            raise QueueError(f"{table}.{key} in {root / 'se.toml'} must be {kind}; "
                             f"fix it or remove it for the built-in {default}")
        found[key] = value
    return found


def due_after(root: Path, table: str = "retro") -> int:
    """`[<table>] due_after` in se.toml (SETTINGS): how much makes a run of that kind due."""
    return settings(root, table)["due_after"]


def collect(root: Path, number: int, door, tracker: str, branch: str, ref: str,
            now: datetime, since: str | None = None, retro: int | None = None,
            refusals: bool = False, signals: list[Path] | None = None,
            sessions: list[dict] | None = None) -> Collected | None:
    """The window of retro `number` read through `door`, starting at `since` or where retro
    `retro` closed where given (`read_window`); None where the door is still missing answers
    (`door.missing`). With `refusals`, the refused deliveries and declined reviews
    (`refusal_records`); with `signals`, the session signals of those files
    (`session_signals`)."""
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
    # What collect reads of each work issue, for the earlier classes' patterns, and its comments,
    # for the refusals.
    issue_texts: dict[int, list[str]] = {}
    read_comments: dict[int, list[dict]] = {}
    for issue in window:
        read_comments[issue.number] = door.comments(issue.number)
        comments = [str(item.get("body") or "") for item in read_comments[issue.number]]
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
        issue_texts[issue.number] = [issue.title, issue.body, *comments, report or ""]
        duplicate = is_duplicate(issue)
        closed.append(Closed(
            number=issue.number, title=issue.title, state_reason=issue.state_reason or "completed",
            duplicate=duplicate,
            landed=landed(issue, landing),
            refused=refused, escalations=escalations, suite_seconds=suite,
            landing_pull=landing.number if landing else None,
            report_pull=report_pull.number if report_pull else None,
            retro=retro_entries(report) if report else {},
            not_delivered=not_delivered(report) if report else [],
            at=(landing.merged_at if landing is not None and landing.merged_at
                else issue.closed_at)))

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
    # An issue that takes one of the previous findings and is still open makes it too early to
    # score, where the overhaul countdown is on (overhaul.py countdown_on): only then, and only with
    # findings to score, are the open issues read.
    opened = ([issue_of(item) for item in door.open_issues()]
              if (previous or {}).get("findings") and sibling("overhaul").countdown_on(root) else [])
    if door.missing:
        return None
    # The window's metrics: the local file's lines that started in it, and the line each landing
    # pull request's description ends in, which outlives a cloud integrator's container; a run in
    # both counts once, by its local line (README "Metrics").
    local = [line for line in metrics.read(metrics.path())[0] if in_window(str(line["start"]))]
    landed_runs = [line for pull in landings if (line := metrics.of_text(pull.body)) is not None]
    runs = metrics.merged(local, landed_runs)
    records = (refusal_records(read_comments, door, tracker, remote_of(door, tracker))
               if refusals else None)
    if door.missing:
        return None
    scored = scored_findings(previous, last.number if last else 0, window, checks, opened)
    patterns = class_patterns(previous, issue_texts, root)
    sizes = {"closed": len(closed), "landed": sum(item.landed for item in closed),
             "duplicates": sum(item.duplicate for item in closed),
             "escalated": sum(item.escalations > 0 for item in closed)}
    # The ad hoc components to promote: those the use log (se_usage) shows used in enough sessions
    # in this window, by the window's own `in_window` on each use's time.
    uses = se_usage.read(root)
    adhoc = se_usage.candidates(uses, read.in_window)
    scripts = se_usage.script_candidates(uses, read.in_window)
    return Collected(
        Window(number, read.since, read.since_retro,
               now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), read.start),
        sizes, closed, list(checks.values()),
        {"retro": last.number, "sizes": previous.get("sizes"), "findings": scored,
         **({"classes": patterns} if patterns else {})}
        if previous else None, runs, {"landings": len(landed_runs), "local": len(local)}, adhoc,
        scripts, session_signals(signals, root) if signals is not None else None, records,
        cloud_costs(sessions, closed) if sessions is not None else None)


def breaking_releases(root: Path) -> dict:
    """The breaking-release check over the project's component tree, as se_modules.py `breaking`
    prints it (docs/components.md "Breaking releases beyond a pin"): its `lines`, and its `error`
    where the listing failed. A project without se.toml pins nothing."""
    if not (root / "se.toml").is_file():
        return {"lines": ["no breaking release beyond a pin: the project has no se.toml"], "error": None}
    se_modules = sibling("se_modules")
    try:
        found = se_modules.breaking(root, se_modules.load_local(se_modules.default_local_config()))
    except se_modules.ModuleError as error:
        return {"lines": [], "error": str(error)}
    return {"lines": found.lines(), "error": found.error()}


def breaking_lines(breaking: dict | None) -> list[str]:
    """The breaking-release check's section; none where it did not run."""
    if breaking is None:
        return []
    lines = ["", "### Breaking releases beyond a pin", "",
             "`se_modules.py breaking` over the project's component tree, as collect ran it; what "
             "to do about a finding is the person's decision."]
    if breaking["lines"]:
        lines += ["", "```text", *breaking["lines"], "```"]
    if breaking["error"]:
        lines += ["", f"The check failed: {breaking['error']}"]
    return lines


def remote_of(door, tracker: str) -> str:
    """The repository of the pull requests `door` reads, for their links; the tracker's where the
    door names none."""
    return str(getattr(door, "remote", "") or tracker)


def first_lines(text: str, count: int = FIRST_LINES) -> str:
    """The first `count` lines of `text` that hold anything once its HTML comments are gone."""
    shown = [line.rstrip() for line in work_tickets.HTML_COMMENT_PATTERN.sub("", text).splitlines()
             if line.strip()]
    return "\n".join(shown[:count])


def refusal(kind: str, issue: int, pull: int | None, comment: dict, link: str,
            text: str) -> dict:
    """One refused delivery or declined review: where it is, who wrote it, inside or outside the
    fleet (outside_text.inside over INSIDE), and its first lines in outside_text's envelope."""
    outside_text = sibling("outside_text")
    association = str(first(comment, "author_association", "authorAssociation") or "")
    quoted, _ = outside_text.envelope(first_lines(text), link, association or None)
    return {"kind": kind, "issue": issue, "pull": pull, "link": link,
            "association": association or outside_text.UNKNOWN,
            "inside": outside_text.inside(association or None, INSIDE), "text": quoted}


def verdict_of(body: str) -> dict | None:
    """The verdict block review.py writes in its review comment: the last JSON object fenced in
    `body` after review.VERDICT_MARKER that names a verdict; None where it has none."""
    at = body.find(review.VERDICT_MARKER)
    if at < 0:
        return None
    found = None
    for match in re.finditer(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", body[at:],
                             re.MULTILINE | re.DOTALL):
        try:
            data = json.loads(match[2])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "verdict" in data:
            found = data
    return found


def refusal_records(comments: dict[int, list[dict]], door, tracker: str,
                    remote: str) -> list[dict]:
    """Each refused delivery and each declined review of the window's work issues, by issue: a
    refused delivery is an `Integration stopped:` comment among `comments` (read already, so no
    further read); a declined review is the review comment with a `decline` verdict block on the
    pull request a `Declined by the review of pull request #<n>` comment names, read through
    `door` (its escalation comment stands in where that pull request holds none)."""
    records: list[dict] = []
    for number, items in sorted(comments.items()):
        for item in items:
            body = str(item.get("body") or "")
            link = str(first(item, "html_url", "url") or work_tickets.issue_url(tracker, number))
            if body.lstrip().startswith(REFUSED):
                records.append(refusal(REFUSED_DELIVERY, number, None, item, link, body))
                continue
            declined = DECLINED.match(body.lstrip())
            if declined is None:
                continue
            pull = int(declined[1])
            reviews = [comment for comment in door.pull_comments(pull)
                       if (verdict_of(str(comment.get("body") or "")) or {}).get(
                           "verdict") == review.DECLINE]
            if reviews:
                comment = reviews[-1]
                records.append(refusal(
                    DECLINED_REVIEW, number, pull, comment,
                    str(first(comment, "html_url", "url") or work_tickets.pull_url(remote, pull)),
                    str(comment.get("body") or "")))
            else:
                records.append(refusal(DECLINED_REVIEW, number, pull, item, link, body))
    return records


def rate(count: int, closed: object) -> float | None:
    """`count` per closed work issue, to two places; None where nothing closed."""
    return round(count / closed, 2) if isinstance(closed, int) and closed > 0 else None


def tree_state(root: Path, given: dict, matches: int | None = None) -> str:
    """A class checked against the tree at `root`: FIXED where its home holds its mark, PAST
    where it is not but nothing of the window matched its pattern (`matches` 0), else OPEN."""
    home = str(given.get("home") or "").strip().lstrip("./")
    mark = str(given.get("mark") or "").strip()
    path = root / home if home else None
    if mark and path is not None and path.is_file() and mark in path.read_text(
            encoding="utf-8", errors="replace"):
        return FIXED
    return PAST if matches == 0 else OPEN


def class_patterns(previous: dict | None, texts: dict[int, list[str]],
                   root: Path | None = None) -> list[dict]:
    """Each class of the previous retro's block, measured again (step 2): its rate before (its
    findings per work issue the previous retro closed) and, where it carries a `pattern`, its rate
    now (the work issues of `texts`, what collect read of each issue of the window, it matched
    in, per issue), its matches in all and those issues; with its home, its `status` and `limits`
    where given, and its state against the tree at `root` (`tree_state`)."""
    found: list[dict] = []
    findings = [item for item in (previous or {}).get("findings") or [] if isinstance(item, dict)]
    closed = ((previous or {}).get("sizes") or {}).get("closed")
    for given in (previous or {}).get("classes") or []:
        if not isinstance(given, dict):
            continue
        name = str(given.get("name") or "")
        before = rate(sum(str(item.get("class") or "").strip() == name.strip()
                          for item in findings), closed)
        row = {"name": name, "status": given.get("status"), "home": given.get("home"),
               "home_kind": given.get("home_kind"), "limits": given.get("limits"),
               "before": before}
        matches = None
        if isinstance(given.get("pattern"), str):
            pattern = re.compile(given["pattern"])
            counts = {number: sum(len(pattern.findall(text)) for text in read)
                      for number, read in texts.items()}
            issues = sorted(number for number, count in counts.items() if count)
            matches = sum(counts.values())
            row.update({"pattern": given["pattern"], "matches": matches, "issues": issues,
                        "now": rate(len(issues), len(texts))})
        row["tree"] = tree_state(root, given, matches) if root is not None else OPEN
        found.append(row)
    return found


def session_signals(paths: list[Path], root: Path) -> dict:
    """The transcript reader's counts (transcript_signals.py, its more signals among them) over
    the session records at `paths` (files or directories of them): how many were given and read,
    a line per source (its events and hits, `nothing read`, or `not found`) and the total per
    signal; with no file read, no signal is counted."""
    signals = sibling("transcript_signals")
    events: list = []
    files: list[str] = []
    missing: list[str] = []
    for path, label in signals.transcripts(list(paths)):
        if not path.is_file():
            missing.append(label)
            continue
        files.append(label)
        with path.open(encoding="utf-8", errors="replace") as handle:
            events.extend(signals.read_events(handle, label, more=True))
    keep_path = signals.repository_paths(root)
    options = {"repeated-commands": {"keep_path": keep_path},
               "repeated-failures": {"keep_path": keep_path}, "lacked": {"keep_path": keep_path}}
    result = signals.tally(events, files, options, more=True)
    per_file = {file: sum(signal["sessions"].get(file, 0) for signal in result["signals"].values())
                for file in files}
    counted = {file: sum(event.file == file for event in events) for file in files}
    sources = [{"source": file, "events": counted[file], "hits": per_file[file],
                "read": file not in result.get("unread", [])} for file in files]
    sources += [{"source": label, "events": 0, "hits": 0, "read": False, "missing": True}
                for label in missing]
    return {"given": len(files) + len(missing),
            "read": sum(source["read"] for source in sources),
            "sources": sources,
            "signals": {name: signal["total"] for name, signal in result["signals"].items()}}


#: The usage fields of a result event, summed per session as its tokens.
COST_TOKENS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
               "output_tokens")
#: A title SE's roles give their sessions (work_tickets.py session_title): SE/<repo>/<role>[/<topic>].
SESSION_TITLE = re.compile(r"SE/(?P<repo>[A-Za-z0-9._-]+)/(?P<role>[a-z]+)(?:/(?P<topic>.+))?")


def result_records(event: object) -> list[dict]:
    """The result records an event of `list_events` carries: the dicts with `total_cost_usd` or
    `usage` at the event itself, its `data` or its `data`'s `result`."""
    found = []
    for item in (event, *((event.get("data"),) if isinstance(event, dict) else ())):
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        for candidate in (item, result):
            if isinstance(candidate, dict) and (candidate.get("type") in (None, "result")) and (
                    "total_cost_usd" in candidate or isinstance(candidate.get("usage"), dict)) \
                    and candidate not in found:
                found.append(candidate)
    return found


def cloud_cost(session: dict) -> dict:
    """One session's tokens and cost: its result events' usage and `total_cost_usd`, summed, one
    record per turn; `cost` None where no event names one."""
    tokens = dict.fromkeys(COST_TOKENS, 0)
    cost: float | None = None
    turns = 0
    for event in session.get("events") or []:
        for record in result_records(event):
            turns += 1
            usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
            for key in COST_TOKENS:
                value = usage.get(key)
                tokens[key] += value if isinstance(value, int) else 0
            value = record.get("total_cost_usd")
            if isinstance(value, (int, float)):
                cost = (cost or 0.0) + float(value)
    return {"turns": turns, "tokens": tokens, "cost": cost}


def cloud_costs(sessions: list[dict], window: list[Closed]) -> dict:
    """The cloud sessions' costs by their titles: each session SE's roles started (SE/<repo>/
    <role>[/<topic>]) with its tokens and cost (`cloud_cost`), and the sums per issue, role and
    repository. A worker's (and every other role's) topic names its issue by the issue's title; a
    reviewer's names the pull request that delivered or landed one; an integrator's names none. A
    session of another title is counted as `other`, never guessed."""
    by_title = {item.title: item.number for item in window}
    by_pull = {pull: item.number for item in window
               for pull in (item.report_pull, item.landing_pull) if pull is not None}
    rows: list[dict] = []
    other = 0
    for session in sessions:
        title = str(session.get("title") or "")
        match = SESSION_TITLE.fullmatch(title)
        if match is None:
            other += 1
            continue
        topic = match["topic"]
        issue = (by_pull.get(int(topic)) if match["role"] == "reviewer" and topic and topic.isdigit()
                 else by_title.get(topic) if topic else None)
        rows.append({"session": str(session.get("id") or ""), "title": title,
                     "repository": match["repo"], "role": match["role"], "issue": issue,
                     **cloud_cost(session)})

    def summed(key: str) -> dict[str, dict]:
        groups: dict[str, dict] = {}
        for row in rows:
            name = str(row[key]) if row[key] is not None else "none"
            group = groups.setdefault(name, {"sessions": 0, "tokens": dict.fromkeys(COST_TOKENS, 0),
                                             "cost": None})
            group["sessions"] += 1
            for kind in COST_TOKENS:
                group["tokens"][kind] += row["tokens"][kind]
            if row["cost"] is not None:
                group["cost"] = round((group["cost"] or 0.0) + row["cost"], 6)
        return dict(sorted(groups.items()))

    return {"given": len(sessions), "other": other, "sessions": rows,
            "per_issue": summed("issue"), "per_role": summed("role"),
            "per_repository": summed("repository")}


def cost_lines(costs: dict | None) -> list[str]:
    """The cloud sessions' costs block (--sessions); none where not asked for."""
    if costs is None:
        return []
    lines = ["", "## Session costs", "",
             f"{len(costs['sessions'])} sessions of {costs['given']} given carry an SE title"
             + (f"; {costs['other']} other sessions are not counted." if costs["other"] else ".")]
    for heading, key in (("issue", "per_issue"), ("role", "per_role"),
                         ("repository", "per_repository")):
        lines += ["", f"| {heading} | sessions | input | cache write | cache read | output | cost |",
                  "|---|---|---|---|---|---|---|"]
        for name, group in costs[key].items():
            label = f"#{name}" if key == "per_issue" and name != "none" else name
            tokens = group["tokens"]
            cost = "unknown" if group["cost"] is None else f"${group['cost']:.2f}"
            lines.append(f"| {label} | {group['sessions']} | {tokens['input_tokens']} | "
                         f"{tokens['cache_creation_input_tokens']} | "
                         f"{tokens['cache_read_input_tokens']} | {tokens['output_tokens']} | {cost} |")
    return lines


def scored_findings(previous: dict | None, retro: int, window: list[Issue],
                    checks: dict[str, RuleCheck], opened: list[Issue] = ()) -> list[dict]:
    """Each finding of the previous retro's block, scored against this window: the work issues
    closed in it or still open (`opened`) that name the finding (`retro #<retro> finding <k>`),
    its state (closed where one of them closed as completed, else TOO_EARLY where one is still
    open: filed after the previous retro's cut-off, it had no time to land; `opened` is empty
    where the overhaul countdown is off, so nothing is too early there; else the reason they
    closed with, else none) and whether the rule check it names broke again (recurred), which a
    finding too early to score never is."""
    found: list[dict] = []
    for index, finding in enumerate((previous or {}).get("findings") or [], 1):
        if not isinstance(finding, dict):
            continue
        number = int(finding.get("finding") or index)

        def names(issue: Issue) -> bool:
            return any(int(match[1]) == retro and int(match[2]) == number
                       for match in FINDING_REFERENCE.finditer(issue.body))

        naming = [issue for issue in window if names(issue)]
        still = [issue for issue in opened if names(issue)]
        reasons = [issue.state_reason or "completed" for issue in naming]
        state = ("closed" if "completed" in reasons else TOO_EARLY if still
                 else reasons[0] if reasons else "none")
        check = str(finding.get("check") or "")
        found.append({"finding": number, "title": str(finding.get("title") or ""),
                      "class": str(finding.get("class") or ""), "kind": finding.get("kind"),
                      "check": check, "issues": sorted(issue.number for issue in naming + still),
                      "state": state,
                      "recurred": state != TOO_EARLY and bool(check) and check in checks
                      and not checks[check].kept})
    return found


def retro_template():
    """The retro's document template, TEMPLATE_NAME, as SE's checkout holds it."""
    return templates().own(TEMPLATE_NAME)


def step(name: str, body: list[str]) -> list[str]:
    """The retro template's section `name`: its heading, its instruction, then `body`."""
    item = retro_template().field(name)
    return ["", f"## {item.heading}", "", f"<!-- {item.name}: {item.says} -->", *(
        ["", *body] if body else [])]


def cell(text: str) -> str:
    return one_line(text).replace("|", "\\|")


def chapter_label(chapter: dict) -> str:
    if not chapter["start"]:
        return f"{chapter['chapter']} (no time)"
    return f"{chapter['chapter']} ({chapter['start'][:16].replace('T', ' ')})"


def timeline_lines(found: Collected) -> list[str]:
    """Step 3: the chapters, then per step (each work issue that came back) what went well, what
    it cost and whether a machine could do it, from its field report and its record; the judge
    fills what the record leaves open."""
    chapters = found.chapters()
    if not chapters:
        return ["No work issue came back in the window."]
    by_number = {item.number: item for item in found.issues}
    lines = [f"Chapters of up to {CHAPTER_HOURS} hours, by when each work issue came back (its "
             "landing, else its close).", "", "| chapter | from | to | steps |", "|---|---|---|---|"]
    lines += [f"| {chapter['chapter']} | {chapter['start'] or 'unknown'} | "
              f"{chapter['end'] or 'unknown'} | "
              + ", ".join(f"#{number}" for number in chapter["issues"]) + " |"
              for chapter in chapters]
    lines += ["", "| step | chapter | what went well | what it cost | can a machine do it |",
              "|---|---|---|---|---|"]
    for chapter in chapters:
        for number in chapter["issues"]:
            item = by_number[number]
            state = ("landed" if item.landed else "duplicate" if item.duplicate
                     else item.state_reason)
            suite = f", suite {item.suite_seconds:g} s" if item.suite_seconds is not None else ""
            cost = f"{state}; {item.refused} refused, {item.escalations} escalated{suite}"
            machine = "; ".join(item.retro[key] for key in MECHANIZE if key in item.retro)
            lines.append(f"| #{item.number} {cell(item.title)} | {chapter['chapter']} | "
                         f"{cell(item.retro.get('goes_well', ''))} | {cell(cost)} | {cell(machine)} |")
    return lines


def matrix_lines(found: Collected) -> list[str]:
    """Step 4's matrix: each standing question against each chapter, a cell naming the work
    issues whose field report answers it there; the judge fills the rest."""
    chapters = found.chapters()
    if not chapters:
        return ["No chapter: no work issue came back in the window."]
    by_number = {item.number: item for item in found.issues}
    lines = ["| question | " + " | ".join(chapter_label(chapter) for chapter in chapters) + " |",
             "|---|" + "---|" * len(chapters)]
    for question in questions().fields:
        cells = [", ".join(f"#{number}" for number in chapter["issues"]
                           if question.name in by_number[number].retro) for chapter in chapters]
        lines.append(f"| {cell(question.heading)} | " + " | ".join(cells) + " |")
    return lines


def answer_lines(found: Collected) -> list[str]:
    """Step 2's part of the field reports: each standing question with each work issue's answer."""
    lines = ["### The field reports' answers to the standing questions"]
    for question in questions().fields:
        entries = [(item.number, item.retro[question.name]) for item in found.issues
                   if question.name in item.retro]
        lines += ["", f"#### {question.heading}", ""]
        lines += [f"- #{number}: {text}" for number, text in entries] or ["None."]
    return lines


def collect_lines(found: Collected) -> list[str]:
    """Step 2: what collect read, each part a `###` section."""
    window = found.window
    starts = {
        CLOSED_RETRO: f"when retro #{window.since_retro} closed",
        GIVEN: "as --since gives",
        OPEN_RETRO: f"when retro #{window.since_retro}, the oldest open retro issue, was created; "
                    "no retro issue has closed"}
    if window.since:
        lines = [f"Window: work issues closed after {window.since}, {starts[window.start]}, "
                 f"up to {window.until}."]
    else:
        lines = [f"Window: the whole history up to {window.until}; no retro issue exists."]
    previous = (found.previous or {}).get("sizes") or {}
    lines += ["", "### Sizes", ""]
    if previous:
        lines += [f"| size | this window | retro #{found.previous['retro']} |", "|---|---|---|"]
        lines += [f"| {name} | {value} | {previous.get(name, '')} |"
                  for name, value in found.sizes.items()]
    else:
        lines += ["| size | this window |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in found.sizes.items()]
    scored = (found.previous or {}).get("findings") or []
    if found.previous:
        lines += ["", f"### The findings of retro #{found.previous['retro']}", ""]
    if scored:
        lines += ["| finding | class | kind | issues | state | recurred |",
                  "|---|---|---|---|---|---|"]
        for item in scored:
            issues = ", ".join(f"#{number}" for number in item["issues"]) or "none"
            recurred = (("not scored" if item["state"] == TOO_EARLY
                         else "yes" if item["recurred"] else "no") + f" ({item['check']})"
                        if item["check"] else "no check named")
            lines.append(f"| {item['finding']}. {item['title']} | {item['class']} | "
                         f"{item['kind'] or ''} | {issues} | {item['state']} | {recurred} |")
    elif found.previous:
        lines.append("None.")
    lines += class_lines(found)
    lines += ["", "### Landed issues", ""]
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
    lines += ["", "### Rule checks", ""]
    for check in found.checks:
        state = (f"kept ({check.checked} checked)" if check.kept
                 else f"broken {len(check.broken)} of {check.checked}")
        lines.append(f"- **{check.name}**: {check.rule}: {state}")
        lines += [f"  - {item['item']}: {item['what']}" for item in check.broken]
    lines += ["", "### Metrics", "",
              f"{len(found.runs)} runs: {found.run_sources.get('landings', 0)} from the landing "
              f"pull requests, {found.run_sources.get('local', 0)} from {metrics.path()}, each run "
              "once.", "", "```text", metrics.report(found.runs), "```"]
    lines += breaking_lines(found.breaking)
    lines += ["", "### Ad hoc components to promote", ""]
    if found.adhoc:
        lines += [f"Used in {se_usage.PROMOTE_SESSIONS} or more sessions since the last retro; "
                  "promote each to a tracked component (docs/go-core.md).", "",
                  "| component | sessions | uses | path |", "|---|---|---|---|"]
        lines += [f"| {c['component']} | {c['sessions']} | {c['uses']} | `{c['path']}` |"
                  for c in found.adhoc]
    else:
        lines.append("None.")
    lines += ["", "### Ad hoc scripts to promote", ""]
    if found.scripts:
        lines += [f"Run {se_usage.PROMOTE_RUNS} or more times in the window (since "
                  f"{found.window.since or 'the start of the history'}), the most-run "
                  "first; promote each that earns it to a tracked component (docs/go-core.md).", "",
                  "| script | runs | sessions | hash |", "|---|---|---|---|"]
        lines += [f"| `{s['script']}` | {s['runs']} | {s['sessions']} | `{s['hash'][:12]}` |"
                  for s in found.scripts]
    else:
        lines.append("None.")
    lines += ["", *answer_lines(found)]
    lines += ["", "### Planning misses", "", "What the field reports did not deliver:", ""]
    entries = [(item.number, text) for item in found.issues for text in item.not_delivered]
    lines += [f"- #{number}: {text}" for number, text in entries] or ["None."]
    others = [item for item in found.issues if not item.landed]
    if others:
        lines += ["", "Closed without landing: " + ", ".join(
            f"#{item.number} ({'duplicate' if item.duplicate else item.state_reason})"
            for item in others) + "."]
    extra = signal_lines(found.signals) + refusal_lines(found.refusals) + cost_lines(found.costs)
    if extra:
        lines += sibling("review").demoted("\n".join(extra), 1).split("\n")
    return lines


def classes_lines(found: Collected) -> list[str]:
    """Step 5 as collect leaves it: the home order and the last retro's classes against the tree;
    the judge's classes go in the block."""
    lines = ["Home order, strongest first: " + ", ".join(HOMES) + ". A class's `home_kind` is the "
             "first of them that holds; its `home` is the file the fix changes, its `mark` a text "
             "the fix leaves there, which the tree check looks for."]
    earlier = (found.previous or {}).get("classes") or []
    if earlier:
        lines += ["", f"The classes of retro #{found.previous['retro']} against the tree:", "",
                  "| class | home | tree |", "|---|---|---|"]
        lines += [f"| {cell(item['name'])} | {item.get('home_kind') or ''} "
                  f"`{item.get('home') or ''}` | {item['tree']} |" for item in earlier]
    return lines


def draft(found: Collected) -> str:
    """The draft as the judging agent reads it: the retro template's six steps, what collect read
    filled in, then the block `read_block` parses."""
    window = found.window
    answers = templates().sections(questions(), 3).rstrip("\n").split("\n")
    lines = [f"# Retro draft for #{window.retro}"]
    lines += step("field_feedback", [])
    lines += step("collect", collect_lines(found))
    lines += step("timeline", timeline_lines(found))
    lines += step("matrix", matrix_lines(found))
    lines += step("answers", answers)
    lines += step("classes", classes_lines(found))
    lines += step("decisions", [])
    block = json.dumps(found.data(), indent=2, ensure_ascii=False)
    lines += ["", JUDGE_BEGIN, "## Judgment", "",
              "The judge writes the person's field feedback into step 1, fills what steps 3 and 4 "
              "leave open, answers every standing question, fills `findings`, `classes` and "
              f"`went_well` in the block below, then runs `retro.py file {window.retro} --draft "
              "<this file>`, which refuses a step or a question left open: a finding has `title` "
              "(five words or more), `body`, `class` (a class's `name`), `home` (the file it "
              "changes), `controversial` (true where it changes a rule, trades one metric for "
              "another, the judge is unsure, or it recurred after an earlier fix) with its `why`, "
              f"and optionally `check` (a rule check: {', '.join(RULE_CHECKS)}); a class has "
              f"`name`, `cause`, `fix`, `home` and `home_kind` (one of: {', '.join(HOMES)}), and "
              f"optionally {', '.join(f'`{key}`' for key in CLASS_KEYS)}; `went_well` lists what "
              "went well. Step 6 is the person's, in the session. This part is not posted.",
              JUDGE_END, "", BLOCK_MARKER, review.fenced(block, "yaml")]
    return "\n".join(lines) + "\n"


def class_lines(found: Collected) -> list[str]:
    """The last retro's classes measured again: rate before against rate now, the window's
    matches of each pattern; none where it named none."""
    classes = (found.previous or {}).get("classes") or []
    if not classes:
        return []
    lines = ["", f"### The classes of retro #{found.previous['retro']}, measured again", "",
             "Rate before: the class's findings per work issue that retro closed; rate now: the "
             "work issues of this window its pattern matches (title, body, comments, field "
             "report), per issue.", "",
             "| class | status | rate before | rate now | pattern | matches | issues | limits |",
             "|---|---|---|---|---|---|---|---|"]
    for item in classes:
        issues = ", ".join(f"#{number}" for number in item.get("issues") or []) or "none"
        limits = item.get("limits")
        limits = "; ".join(limits) if isinstance(limits, list) else (limits or "")
        pattern = f"`{item['pattern'].replace('|', chr(92) + '|')}`" if "pattern" in item else "none"
        rates = [("unknown" if value is None else f"{value:g}")
                 for value in (item.get("before"), item.get("now"))]
        if "pattern" not in item:
            rates[1], issues = "no pattern", ""
        lines.append(f"| {item['name']} | {item.get('status') or ''} | {rates[0]} | {rates[1]} | "
                     f"{pattern} | {item.get('matches', '')} | {issues} | {one_line(limits)} |")
    return lines


def signal_lines(signals: dict | None) -> list[str]:
    """The session signals block (--signals); none where not asked for."""
    if signals is None:
        return []
    lines = ["", "## Session signals", ""]
    if not signals["read"]:
        lines.append(f"0 files read of {signals['given']} given: no signal was counted, which "
                     "is not zero findings.")
    else:
        lines.append(f"{signals['read']} files read of {signals['given']} given, counted by "
                     "transcript_signals.py.")
    lines.append("")
    for source in signals["sources"]:
        state = ("not found" if source.get("missing") else "nothing read" if not source["read"]
                 else f"{source['events']} events, {source['hits']} hits")
        lines.append(f"- {source['source']}: {state}")
    if signals["read"]:
        lines += ["", "| signal | total |", "|---|---|"]
        lines += [f"| {name} | {total} |" for name, total in signals["signals"].items()]
    return lines


def refusal_lines(refusals: list[dict] | None) -> list[str]:
    """The refused deliveries and declined reviews block (--refusals); none where not asked
    for."""
    if refusals is None:
        return []
    lines = ["", "## Refused deliveries and declined reviews", ""]
    if not refusals:
        return lines + ["None."]
    for item in refusals:
        pull = f" (pull request #{item['pull']})" if item["pull"] else ""
        where = "inside" if item["inside"] else "outside"
        lines.append(f"- #{item['issue']} {item['kind']}{pull}: {item['link']}; author "
                     f"association {item['association']}, {where} the fleet")
        lines += [f"  {line}".rstrip() for line in item["text"].rstrip("\n").splitlines()]
    return lines


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


def class_key_problems(given: dict, name: str) -> list[str]:
    """What is wrong with a class's optional keys (CLASS_KEYS): a status that is no text, a
    pattern that is no regular expression, limits that are neither a text nor a list of texts."""
    problems: list[str] = []
    if "status" in given and not (isinstance(given["status"], str) and given["status"].strip()):
        problems.append(f"{name}: status is a text")
    if "pattern" in given:
        pattern = given["pattern"]
        if not (isinstance(pattern, str) and pattern):
            problems.append(f"{name}: pattern is a regular expression, as a text")
        else:
            try:
                re.compile(pattern)
            except re.error as error:
                problems.append(f"{name}: pattern is no regular expression ({error})")
    if "mark" in given and not (isinstance(given["mark"], str) and given["mark"].strip()):
        problems.append(f"{name}: mark is a text the fix leaves in its home")
    if "limits" in given:
        limits = given["limits"]
        if not (isinstance(limits, str) or (isinstance(limits, list)
                                            and all(isinstance(entry, str) for entry in limits))):
            problems.append(f"{name}: limits is a text or a list of texts")
    return problems


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
        extra = sorted(set(given) - set(CLASS_FIELDS) - set(CLASS_KEYS))
        name = review.words(given.get("name"))
        if extra:
            problems.append(f"class {index} has the unknown field {extra[0]}")
        problems += class_key_problems(given, f'class "{name}"' if name else f"class {index}")
        if not name:
            problems.append(f"class {index} has no name")
        else:
            problems += [f'class "{name}" has no {key}' for key in ("cause", "fix", "home")
                         if not review.words(given.get(key))]
            if review.words(given.get("home_kind")) not in HOMES:
                problems.append(f'class "{name}": home_kind is the first of the home order that '
                                f"holds: {', '.join(HOMES)}")
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


def judged(text: str, number: int, filed: bool = False) -> dict:
    """The block of the draft `text`, its judgment checked, unless `filed` (a retro doc already
    filed, whose judgment was checked when it was, read back by the next collect); every refusal
    is raised before anything is written."""
    block = read_block(text)
    if block is None:
        raise QueueError(f"The draft has no {BLOCK_MARKER} block: write it with retro.py collect "
                         f"{number} --out FILE")
    retro = (block.get("window") or {}).get("retro")
    if retro != number:
        raise QueueError(f"The draft is retro #{retro}'s, not #{number}'s")
    problems = [] if filed else judgment_problems(block)
    if problems:
        raise QueueError(f"The judgment of retro #{number} is not complete, so nothing was "
                         "written: " + "; ".join(problems))
    findings = []
    for index, given in enumerate(block.get("findings") or [], 1):
        if not isinstance(given, dict):
            continue
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


def steps_of(text: str):
    """The draft `text` read as a document of the retro template: its six steps and the answers
    to the standing questions (templates.py `parse`)."""
    return templates().parse(retro_template(), text[:text.rfind(BLOCK_MARKER)]
                             if BLOCK_MARKER in text else text)


def steps_problems(text: str) -> list[str]:
    """What keeps the draft `text` from holding every step the retro template requires, the
    field feedback and each answer to the standing questions among them; none where it does."""
    found = templates().check(retro_template(), steps_of(text))
    return [finding.fix for finding in found if finding.severity == templates().REFUSE]


def class_key_lines(keys: dict) -> list[str]:
    """A class's optional keys as the report shows them; none without."""
    lines = []
    if "status" in keys:
        lines.append(f"Status: {keys['status'].strip()}")
    if "pattern" in keys:
        lines.append(f"Pattern: `{keys['pattern']}`")
    if "limits" in keys:
        limits = keys["limits"]
        lines.append("Limits: " + ("; ".join(entry.strip() for entry in limits)
                                   if isinstance(limits, list) else limits.strip()))
    if "mark" in keys:
        lines.append(f"Mark: `{keys['mark'].strip()}`")
    return ["", *lines] if lines else []


def judged_classes(block: dict, root: Path | None) -> list[dict]:
    """The judged classes, strongest home first (HOMES), each with its findings and its state
    against the tree at `root` (`tree_state`), OPEN where no tree is given."""
    rows = []
    for entry in block["classes"]:
        name = entry["name"].strip()
        rows.append({**entry, "name": name,
                     "findings": [item for item in block["findings"]
                                  if item["class"].strip() == name],
                     "tree": tree_state(root, entry) if root is not None else OPEN})
    return sorted(rows, key=lambda row: HOMES.index(row["home_kind"].strip()))


def report(block: dict, number: int, doc: str, url: str, sha: str, text: str,
           root: Path | None = None) -> str:
    """The retro's report proper, its closing comment, a document of the retro template: the six
    steps, the draft `text`'s for steps 1, 3 and 4, the judgment's for steps 5 and 6 (each class
    with its home and its state against the tree at `root`, and its findings, each with its kind),
    and step 2 linking the committed retro doc `doc` at commit `sha` (`url`), which holds the
    facts and the block the next collect reads."""
    template = retro_template()
    drafted = steps_of(text).fields
    classes = judged_classes(block, root)
    lines = []
    for row in classes:
        lines += ["", f"#### {row['name']} ({len(row['findings'])})", "",
                  f"Cause: {one_line(row['cause'])}", "", f"Fix: {row['fix'].strip()}", "",
                  f"Home: {row['home_kind'].strip()} (home {HOMES.index(row['home_kind'].strip()) + 1} "
                  f"of {len(HOMES)}), `{row['home'].strip()}`; tree: {row['tree']}",
                  *class_key_lines({key: row[key] for key in CLASS_KEYS if key in row}), ""]
        for item in row["findings"]:
            kind = (f"{DECISION}, for the owner's decision list: {item['why'].strip()}"
                    if item["kind"] == DECISION else f"{WORK}, for SE to bundle")
            check = f"; check `{item['check']}`" if item.get("check") else ""
            lines += [f"- **{item['finding']}. {item['title'].strip()}** ({kind}; home "
                      f"`{item['home'].strip()}`{check})",
                      "  " + "\n  ".join(item["body"].strip().splitlines())]
    if not classes:
        lines += ["", "None."]
    lines += ["", "#### What went well", ""]
    lines += [f"- {entry.strip()}" for entry in block["went_well"] if review.words(entry)]
    work = [item["finding"] for item in block["findings"] if item["kind"] == WORK]
    decisions = [item["finding"] for item in block["findings"] if item["kind"] == DECISION]
    still = [row["name"] for row in classes if row["tree"] == OPEN]
    decided = [str(drafted.get("decisions") or "").strip(),
               "Open classes: " + (", ".join(still) or "none") + ".",
               f"This retro filed no issue. SE files what the person accepted: it bundles the "
               f"{WORK} findings ({', '.join(map(str, work)) or 'none'}) into as few work issues "
               f"as the work needs, each naming `retro #{number} finding <k>` for every finding "
               f"it takes, so the next retro scores it; the {DECISION} findings "
               f"({', '.join(map(str, decisions)) or 'none'}) go on the owner's decision list."]
    fields = {
        "field_feedback": drafted.get("field_feedback") or "None.",
        "collect": f"The facts (sizes, landed issues, rule checks, metrics, the field reports' "
                   f"answers and what they did not deliver, the last retro's classes measured "
                   f"again) and the block the next retro reads are in the committed retro doc "
                   f"[{doc}]({url}), at {sha[:12]}.",
        "timeline": drafted.get("timeline") or "None.",
        "matrix": drafted.get("matrix") or "None.",
        "answers": drafted.get("answers") or "None.",
        "classes": "\n".join(lines).strip(),
        "decisions": "\n\n".join(part for part in decided if part),
    }
    body = templates().render(template, fields)
    return (f"{REPORT_MARKER}\n# Retro #{number}: the report\n\n{body.rstrip()}\n\n"
            f"{DOC_MARKER.format(sha=sha, path=doc)}\n")


def parts(text: str, number: int, limit: int = COMMENT_LIMIT) -> list[str]:
    """`text` as the comments that post it: itself where it fits in `limit` characters, else
    numbered parts, cut at line ends (a longer line within it), each labelled `Part k of n`;
    nothing is left out but the report's markers (REPORT_MARKER and the template's), so no part
    is taken for a whole report: `file` checked the whole before it cut it."""
    if len(text) <= limit:
        return [text]
    unmarked = {REPORT_MARKER, templates().FLEET_MARKER}
    text = "".join(line for line in text.splitlines(keepends=True)
                   if line.strip() not in unmarked
                   and not templates().TEMPLATE_MARKER_PATTERN.fullmatch(line.rstrip("\n")))
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
    return judged(text, number, filed=True)


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
    open_steps = steps_problems(text)
    if open_steps:
        raise QueueError(f"The draft of retro #{args.retro} leaves a step of the retro template "
                         f"({retro_template().path or TEMPLATE_NAME}) open, so nothing was written: "
                         + "; ".join(open_steps))
    doc, sha = committed_doc(root, args.draft, text, work_tickets.integration_ref(root))
    url = doc_url(work_tickets.remote_repo(root) or tracker, sha, doc)
    posted = report(block, args.retro, doc, url, sha, text, root)
    refused = [finding.fix for finding in templates().check(retro_template(), templates().parse(
        retro_template(), posted)) if finding.severity == templates().REFUSE]
    if refused:
        raise QueueError(f"The report of retro #{args.retro} breaks the retro template, so nothing "
                         "was written: " + "; ".join(refused))
    comments = parts(posted, args.retro)
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
    sessions = None
    if args.sessions is not None:
        try:
            sessions = work_tickets.tool_items(json.loads(args.sessions.read_text(encoding="utf-8")),
                                               "data")
        except (OSError, json.JSONDecodeError) as error:
            print(f"error: {args.sessions} is not the JSON list of sessions: {error}",
                  file=sys.stderr)
            return 1
    found = collect(root, args.retro, door, tracker, branch, ref, datetime.now(timezone.utc),
                    since_of(args.since), args.since_retro, args.refusals, args.signals, sessions)
    if found is None:
        directory = args.answers or Path("<dir>")
        window = (f" --since {args.since}" if args.since else "") + (
            f" --retro {args.since_retro}" if args.since_retro is not None else "")
        flags = (" --refusals" if args.refusals else "") + (
            " --signals " + " ".join(str(path) for path in args.signals) if args.signals else "") + (
            f" --sessions {args.sessions}" if args.sessions else "")
        then = (f"retro.py collect {args.retro}{window} --answers {directory}"
                f"{f' --out {args.out}' if args.out else ''}{' --json' if args.json else ''}"
                f"{flags}"
                f"{f' --repo {args.repo}' if args.repo else ''} --worktree {root}")
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools "
              f"and saves their answers into {directory}:")
        print(Plan(f"the window of retro #{args.retro}", tuple(door.missing), then).text())
        return 0
    found.breaking = breaking_releases(root)
    output = (json.dumps({**found.data(), **found.extras()}, indent=2, ensure_ascii=False) + "\n"
              if args.json else draft(found))
    if args.out:
        args.out.write_text(output, encoding="utf-8", newline="\n")
        print(f"Wrote the retro draft of #{args.retro} to {args.out}: "
              + ", ".join(f"{value} {name}" for name, value in found.sizes.items()))
    else:
        sys.stdout.write(output)
    return 0


# The retro's issue template, which the filing check files a due retro from, its scope DUE_SCOPE:
# `retro-due-<yyyymmdd>`.
TEMPLATE = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE" / "retro.md"
DUE_SCOPE = "due"


def file_new(root: Path, repo: str | None) -> str:
    """File a retro issue from TEMPLATE, labelled RETRO_LABEL (overhaul.py file_run)."""
    return sibling("overhaul").file_run(root, repo, TEMPLATE, RETRO_LABEL, DUE_SCOPE)


def countdown_lines(found: dict[str, Countdown]) -> list[str]:
    """One line per countdown: what it counted since where it starts, and whether it is due or a
    run of its kind is open."""
    lines = []
    for kind in ("retro", "overhaul"):
        item = found[kind]
        start = f"since #{item.since_run} started {item.since}" if item.since_run else "in the whole history"
        counted = (f"{item.count} ({item.landed} landed, {item.failed} failed)"
                   if kind == "retro" else f"{item.count} retros closed")
        state = (f"open: {', '.join(f'#{n}' for n in item.open)}" if item.open
                 else f"due: {item.reason}" if item.due else "not due")
        lines.append(f"{kind}: {counted} {start}, {item.elapsed_days} days; {state}")
    return lines


def run_due(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    tracker = work_tickets.resolve_repo(root, args.repo)
    remote = work_tickets.remote_repo(root) or tracker
    if args.answers is not None:
        door = FileDoor(args.answers, tracker, remote)
    elif work_tickets.hand_off():
        door = FileDoor(Path("<dir>"), tracker, remote)
    else:
        door = GhDoor(root, tracker, remote)
    found = countdowns(door, tracker, work_tickets.integration_branch(root), root,
                       datetime.now(timezone.utc))
    if found is None:
        directory = args.answers or Path("<dir>")
        then = (f"retro.py due --answers {directory}{' --json' if args.json else ''}"
                f"{f' --repo {args.repo}' if args.repo else ''} --worktree {root}")
        print("gh is not signed in, so the session runs these GitHub steps with its GitHub tools "
              f"and saves their answers into {directory}:")
        print(Plan("the retro and overhaul countdowns", tuple(door.missing), then).text())
        return 0
    if args.json:
        print(json.dumps({kind: asdict(item) for kind, item in found.items()}, indent=2))
    else:
        print("\n".join(countdown_lines(found)))
    return 0


#: retro.py's commands as one kern component (README "Commands as components"), retro; each
#: command's usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "retro", "Retro",
    "A retro: collect writes its draft from the work since the last one, file checks the judged "
    "draft and closes the retro issue with its report, due says whether a retro or an overhaul "
    "is due or open.",
    ("collect", "file", "due")),)
#: The commands that go through kern where it runs (se_components.routed): none, as collect reads
#: GitHub for minutes and writes the draft, and file writes.
INTERACTIVE_COMMANDS: frozenset[str] = frozenset()


def make_parser() -> argparse.ArgumentParser:
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
    collect_command.add_argument("--signals", type=Path, nargs="+", metavar="FILE",
                                 help="add the counts of the transcript reader over these session "
                                      "records (files or directories), a line per source")
    collect_command.add_argument("--refusals", action="store_true",
                                 help="add each refused delivery and declined review of the "
                                      "window with its link, its author's association and its "
                                      "first lines")
    collect_command.add_argument("--sessions", type=Path, metavar="FILE",
                                 help="add each cloud session's tokens and cost, found by its "
                                      "title (SE/<repo>/<role>/<topic>), per issue, role and "
                                      "repository: the session tools' answers, each session "
                                      "list_sessions lists with its list_events result events "
                                      "(kinds [\"result\"]) as \"events\"")
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
    due_command = commands.add_parser(
        "due", help="say whether a retro or an overhaul is due or open",
        description="Count what came back since the newest retro started (a landing 1, an "
                    "escalated work issue its failure_weight) and the retros closed since the "
                    "newest overhaul started, and say whether either is due by se.toml [retro] "
                    "and [overhaul] (README \"Retro due\") or a run of its kind is open; "
                    "work_tickets.py file runs the same check first.")
    due_command.add_argument("--json", action="store_true", help="the countdowns as JSON")
    due_command.add_argument("--answers", type=Path, metavar="DIR",
                             help="without gh: the directory the session saves the plan's "
                                  "answers into")
    due_command.add_argument("--worktree", default=".",
                             help="the checkout of the repository (default: .)")
    due_command.add_argument("--repo", help="[HOST/]OWNER/REPO of the issues (default: the "
                                            "tracker or origin remote)")
    due_command.set_defaults(run=run_due)
    return top


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    words = [args.command]
    routed = sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        args.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    try:
        return args.run(args)
    except QueueError as error:
        print(f"retro.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
