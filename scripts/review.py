"""Review commands: what a cold reviewer of a delivered pull request starts from.

`review.py brief <pull request>` prints the brief: the work issue the pull request names (its body
and comments), the diff against its base at the pull request's head commit, the check runs on
that commit and the rule book at that commit. The worker's own account, the pull request's
description (its field report) and its comments, is withheld: a worker's summary misleads a
reviewer most. `--claims` adds it under a heading that calls it claims to check, never evidence,
for once the reviewer's findings are verified.

GitHub is read through work_tickets.py's door (gh). Where gh is not signed in (Claude's cloud) the
command prints its GitHub steps as a plan for the session's GitHub tools and reads their answers
from the files the session saved, as the work model's "Without gh" says for `integrate`. The diff
and the rule book come from git.

Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass, field
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
QueueError = work_tickets.QueueError
Step, Plan, Later = work_tickets.Step, work_tickets.Plan, work_tickets.Later

RULE_BOOK = "src/skills/work-model/references/rules.md"
ISSUE_REFERENCE = re.compile(
    r"\b(?:fixes|refs|closes)\s+(?:#(\d+)|https://([^/\s]+)/([^/\s]+)/([^/\s]+)/issues/(\d+))\b",
    re.IGNORECASE)
CLAIMS_HEADING = "Claims to check, never evidence"
# The answer files the session saves from the plan's steps, by option.
ANSWERS = {
    "pull": "the pull request (pull_request_read get)",
    "issue": "the work issue (issue_read get)",
    "issue_comments": "the work issue's comments (issue_read get_comments)",
    "checks": "the check runs (pull_request_read get_check_runs)",
    "pull_comments": "the pull request's comments (pull_request_read get_comments)",
}


def issue_reference(description: str, repo: str) -> tuple[str, int] | None:
    """The repository (`<host>/<owner>/<repo>`) and number of the first work issue `description`
    names with `Fixes`, `Refs` or `Closes`; a bare `#<n>` is in `repo`."""
    match = ISSUE_REFERENCE.search(description)
    if match is None:
        return None
    if match[1]:
        return repo, int(match[1])
    return f"{match[2]}/{match[3]}/{match[4]}", int(match[5])


class GhDoor:
    """The brief's GitHub reads through work_tickets.py's door: the pull request and its checks
    in `remote`, issues in the repository their reference names."""

    def __init__(self, root: Path, remote: str) -> None:
        self.root, self.remote = root, remote

    def door(self, repo: str):
        return work_tickets.GitHub(self.root, repo)

    def pull(self, number: int) -> dict:
        return self.door(self.remote).pull(number)

    def issue(self, repo: str, number: int) -> dict:
        return self.door(repo).api(f"issues/{number}")

    def issue_comments(self, repo: str, number: int) -> list:
        return self.door(repo).api(f"issues/{number}/comments?per_page=100")

    def checks(self, number: int, sha: str) -> object:
        return self.door(self.remote).api(f"commits/{sha}/check-runs?per_page=100")

    def pull_comments(self, number: int) -> list:
        return self.door(self.remote).api(f"issues/{number}/comments?per_page=100")


class FileDoor:
    """The same reads from the answers the session saved with its GitHub tools, one file each
    (`answers`, by ANSWERS' names)."""

    def __init__(self, answers: dict[str, Path]) -> None:
        self.answers = answers

    def read(self, name: str) -> object:
        path = self.answers[name]
        try:
            return json.loads(work_tickets.read_file(path, ANSWERS[name]))
        except json.JSONDecodeError as error:
            raise QueueError(f"{ANSWERS[name]} in {path} is not JSON: {error}") from error

    def pull(self, number: int) -> dict:
        return self.read("pull")

    def issue(self, repo: str, number: int) -> dict:
        return self.read("issue")

    def issue_comments(self, repo: str, number: int) -> object:
        return self.read("issue_comments")

    def checks(self, number: int, sha: str) -> object:
        return self.read("checks")

    def pull_comments(self, number: int) -> object:
        return self.read("pull_comments")


def items(answer: object, key: str) -> list[dict]:
    """The list in `answer`: the answer itself or its `key` (an API page wraps its list)."""
    if isinstance(answer, dict):
        answer = answer.get(key) or []
    return [item for item in answer if isinstance(item, dict)] if isinstance(answer, list) else []


def comments(answer: object) -> list[dict]:
    return [{"author": str((item.get("user") or {}).get("login") or ""),
             "created": str(item.get("created_at") or ""), "body": str(item.get("body") or "")}
            for item in items(answer, "comments")]


def plan(remote: str, number: int, claims: bool, then: str) -> Plan:
    """The brief's GitHub steps for the session's tools, each with the file its answer goes to."""
    pull = work_tickets.owner_repo(remote)
    issue = {"owner": Later("issue owner", 1), "repo": Later("issue repo", 1),
             "issue_number": Later("issue number", 1)}
    steps = [
        Step("pull", "pull_request_read", {**pull, "method": "get", "pullNumber": number},
             "Save the answer as JSON for --pull <file>. Read nothing more of the description: "
             "its first line names the work issue (Fixes|Refs <issue url>)",
             ("issue owner", "issue repo", "issue number")),
        Step("issue", "issue_read", {**issue, "method": "get"},
             "Save the answer as JSON for --issue <file>"),
        Step("issue_comments", "issue_read", {**issue, "method": "get_comments", "perPage": 100},
             "Save the answer as JSON for --issue-comments <file>"),
        Step("checks", "pull_request_read", {**pull, "method": "get_check_runs",
                                             "pullNumber": number},
             "Save the answer as JSON for --checks <file>"),
    ]
    if claims:
        steps.append(Step("pull_comments", "pull_request_read",
                          {**pull, "method": "get_comments", "pullNumber": number, "perPage": 100},
                          "Save the answer as JSON for --pull-comments <file>"))
    return Plan(f"the review brief of pull request #{number}", tuple(steps), then)


@dataclass
class Brief:
    """Everything a cold reviewer of pull request `number` starts from; `claims` only with
    --claims."""

    number: int
    url: str
    title: str
    base: str
    head: str
    merge_base: str
    issue: dict
    issue_comments: list[dict]
    diff: str
    checks: list[dict]
    rule_book: str
    rule_book_from: str
    claims: dict | None = field(default=None)

    def data(self) -> dict:
        return asdict(self)


def fetched_head(root: Path, number: int, ref: str, sha: str) -> None:
    """Make commit `sha`, the pull request's head, readable here."""
    if work_tickets.run_git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        return
    for refspec in (f"+refs/pull/{number}/head:refs/remotes/origin/pull/{number}",
                    f"+refs/heads/{ref}:refs/remotes/origin/{ref}"):
        work_tickets.run_git(root, "fetch", "-q", "origin", refspec)
        if work_tickets.run_git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
            return
    raise QueueError(f"The head commit {sha} of pull request #{number} is not in {root} and "
                     f"fetching {ref} from origin did not bring it; fetch it and try again")


def rule_book(root: Path, sha: str) -> tuple[str, str]:
    """The rule book at `sha`, and where it came from; the running se's copy where the reviewed
    repository has none at that commit."""
    shown = work_tickets.run_git(root, "show", f"{sha}:{RULE_BOOK}")
    if shown.returncode == 0:
        return shown.stdout, sha
    own = Path(__file__).resolve().parents[1] / RULE_BOOK
    return work_tickets.read_file(own, "the rule book"), f"the running se ({RULE_BOOK})"


def brief(root: Path, number: int, door, remote: str, claims: bool) -> Brief:
    """Read pull request `number`'s brief through `door`; the diff and the rule book from git."""
    pull = door.pull(number)
    head = str((pull.get("head") or {}).get("sha") or "")
    ref = str((pull.get("head") or {}).get("ref") or "")
    base = str((pull.get("base") or {}).get("ref") or "")
    if not head or not base:
        raise QueueError(f"The answer for pull request #{number} names no head commit or base "
                         "branch; save pull_request_read get's whole answer")
    description = str(pull.get("body") or "")
    reference = issue_reference(description, remote)
    if reference is None:
        raise QueueError(f"Pull request #{number}'s description names no work issue; its first "
                         "line names it as Fixes|Refs <issue url> (work_tickets.py pr-body)")
    issue_repo, issue_number = reference
    issue = door.issue(issue_repo, issue_number)
    if int(issue.get("number") or 0) != issue_number:
        raise QueueError(f"The work issue answer is #{issue.get('number')}, but pull request "
                         f"#{number} names #{issue_number}; save issue #{issue_number}")
    if "pull_request" in issue:
        raise QueueError(f"#{issue_number}, which pull request #{number} names, is a pull "
                         "request, not a work issue")
    fetched_head(root, number, ref, head)
    work_tickets.run_git(root, "fetch", "-q", "origin",
                         f"+refs/heads/{base}:refs/remotes/origin/{base}")
    merge_base = work_tickets.checked_git(root, "merge-base", f"origin/{base}", head).strip()
    diff = work_tickets.checked_git(root, "diff", f"{merge_base}..{head}")
    book, book_from = rule_book(root, head)
    checks = [{"name": str(run.get("name") or ""), "status": str(run.get("status") or ""),
               "conclusion": str(run.get("conclusion") or ""),
               "url": str(run.get("html_url") or run.get("details_url") or "")}
              for run in items(door.checks(number, head), "check_runs")]
    found = Brief(
        number=number, url=str(pull.get("html_url") or work_tickets.pull_url(remote, number)),
        title=str(pull.get("title") or ""), base=base, head=head, merge_base=merge_base,
        issue={"number": issue_number, "repo": issue_repo, "title": str(issue.get("title") or ""),
               "state": str(issue.get("state") or ""), "url": str(issue.get("html_url") or ""),
               "body": str(issue.get("body") or "")},
        issue_comments=comments(door.issue_comments(issue_repo, issue_number)),
        diff=diff, checks=checks, rule_book=book, rule_book_from=book_from)
    if claims:
        found.claims = {"description": description,
                        "comments": comments(door.pull_comments(number))}
    return found


def quote(text: str) -> str:
    """`text` another wrote as a Markdown quote, so its headings stay inside it."""
    text = text.strip()
    if not text:
        return "> (empty)"
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def fenced(text: str, language: str = "") -> str:
    """`text` in a code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text.rstrip()}\n{fence}"


def demoted(text: str, levels: int = 2) -> str:
    """`text`'s Markdown headings `levels` deeper (at most six), outside code fences, so a
    document set inside the brief stays under the brief's heading."""
    lines, fence = [], ""
    for line in text.splitlines():
        opening = re.match(r"\s*(`{3,}|~{3,})", line)
        if opening and (not fence or opening[1].startswith(fence)):
            fence = "" if fence else opening[1]
        heading = None if fence or opening else re.match(r"(#{1,6})(\s.*|)$", line)
        lines.append("#" * min(6, len(heading[1]) + levels) + heading[2] if heading else line)
    return "\n".join(lines)


def quoted_comments(found: list[dict]) -> list[str]:
    if not found:
        return ["No comments."]
    return [f"{item['author'] or 'Someone'} wrote{' on ' + item['created'] if item['created'] else ''}:"
            f"\n\n{quote(item['body'])}" for item in found]


def text(found: Brief) -> str:
    """The brief as a reviewer reads it."""
    issue = found.issue
    parts = [
        f"# Brief for the review of pull request #{found.number} {found.title}".rstrip(),
        f"Review the code at {found.head}, the pull request's head ({found.url}): "
        f"`git checkout --detach {found.head}`. The diff is against {found.base} at "
        f"{found.merge_base}, where the branch left it.",
        f"## The ask: #{issue['number']} {issue['title']} ({issue['state']})".rstrip(),
        quote(issue["body"]),
        "### Its comments",
        *quoted_comments(found.issue_comments),
        f"## The diff: {found.merge_base[:12]}..{found.head[:12]}",
        fenced(found.diff, "diff") if found.diff.strip() else "No changes.",
        f"## Checks on {found.head}",
        "\n".join(f"- {run['name']}: {run['status']} {run['conclusion']}".rstrip()
                  + (f" ({run['url']})" if run["url"] else "") for run in found.checks)
        or "No check runs.",
        f"## The rule book at {found.rule_book_from}",
        demoted(found.rule_book.strip()),
    ]
    if found.claims is None:
        parts += ["## Withheld",
                  "The pull request's description (the worker's field report) and its comments "
                  "are withheld until your findings are verified: then `--claims` shows them, as "
                  "claims to check, never as evidence."]
    else:
        parts += [f"## {CLAIMS_HEADING}",
                  "The worker's own account. Check each claim against the code and the checks "
                  "above; none of it is evidence.",
                  "### The pull request's description",
                  quote(found.claims["description"]),
                  "### The pull request's comments",
                  *quoted_comments(found.claims["comments"])]
    return "\n\n".join(parts) + "\n"


def run_brief(args: argparse.Namespace) -> int:
    root = work_tickets.worktree_root(args.worktree)
    remote = args.repo or work_tickets.remote_repo(root)
    if remote is None:
        raise QueueError(f"review.py brief: {root} has no origin remote on GitHub; pass --repo "
                         "[HOST/]OWNER/REPO")
    given = {name: getattr(args, name) for name in ANSWERS if getattr(args, name) is not None}
    needed = [name for name in ANSWERS if name != "pull_comments" or args.claims]
    if given:
        missing = [name for name in needed if name not in given]
        if missing:
            options = ", ".join("--" + name.replace("_", "-") for name in missing)
            raise QueueError(f"review.py brief reads the session's answers from files: also pass "
                             f"{options}, from the plan's steps")
        door = FileDoor(given)
    elif work_tickets.hand_off():
        options = " ".join(f"--{name.replace('_', '-')} <file>" for name in needed)
        then = (f"review.py brief {args.pull_request}{' --claims' if args.claims else ''}"
                f"{' --json' if args.json else ''} {options} --worktree {root}")
        print(f"gh is not signed in, so the session runs these GitHub steps with its GitHub "
              f"tools and passes their answers as files:")
        print(plan(remote, args.pull_request, args.claims, then).text())
        return 0
    else:
        door = GhDoor(root, remote)
    found = brief(root, args.pull_request, door, remote, args.claims)
    if args.json:
        print(json.dumps(found.data(), indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(text(found))
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="review.py", description=__doc__.split("\n\n")[0])
    commands = top.add_subparsers(dest="command", required=True)
    brief_command = commands.add_parser(
        "brief", help="what a cold reviewer of a delivered pull request starts from",
        description="Print the review brief of a pull request: its work issue, its diff at its "
                    "head commit, the checks on that commit and the rule book; its description "
                    "and comments withheld unless --claims.")
    brief_command.add_argument("pull_request", type=int, help="the pull request's number")
    brief_command.add_argument("--claims", action="store_true",
                               help="add the description and comments, as claims to check")
    brief_command.add_argument("--json", action="store_true", help="print the brief as JSON")
    brief_command.add_argument("--worktree", default=".",
                               help="the checkout of the reviewed repository (default: .)")
    brief_command.add_argument("--repo", help="[HOST/]OWNER/REPO of the pull request "
                                              "(default: the origin remote)")
    for name, what in ANSWERS.items():
        brief_command.add_argument(f"--{name.replace('_', '-')}", dest=name, type=Path,
                                   metavar="FILE", help=f"without gh: {what}, as JSON")
    brief_command.set_defaults(run=run_brief)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except QueueError as error:
        print(f"review.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
