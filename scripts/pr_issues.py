"""CI's issue rule: a pull request into the integration branch names an open work issue it does.

The rule is the work model's (src/skills/work-model/SKILL.md "Integration branch"); this script
enforces it in the job `check` of .github/workflows/check.yml. It reads the pull request from the
Actions event (`GITHUB_EVENT_PATH`) and the issues it names through the REST API with the Actions
token (`GITHUB_TOKEN`), so it needs no `gh` sign-in.

A reference is `Refs`, `Closes`, `Fixes` or `Lands`, then `#<n>` or this repository's
`https://github.com/<owner>/<repo>/issues/<n>` (or `/pull/<n>`). The pull request passes when:

- one reference names an issue of this repository that is open and labelled `work`; or
- one `Lands` reference names a pull request (a landing's work pull request) whose description
  names such an issue; or
- it was opened by the repository owner's account and carries the label `housekeeping`.

A pull request into another branch is not checked. Exit code 0 passed, 1 refused, 2 setup error
(no event, no token, the API failing).

`references` is the one parser of how a pull request names its issue. The field-report step of the
same job uses it too: `--work-issue <file>` prints the number of the issue the first line of the
description in `<file>` names (`Fixes|Refs <issue url>` as `work_tickets.py pr-body` writes it, or
the short `Refs #<n>`), exit code 1 where it names none.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

WORK_LABEL = "work"
HOUSEKEEPING_LABEL = "housekeeping"
KEYWORDS = ("refs", "closes", "fixes", "lands")
REMEDY = ("name the work issue in the description's first line, `Refs <issue url>` (work_tickets.py "
          "pr-body writes it), or file a work issue first")


class SetupError(Exception):
    pass


def references(body: str, repository: str) -> list[tuple[str, int]]:
    """The (keyword, number) pairs `body` names in this `repository`, in order, without repeats."""
    repo = re.escape(repository)
    pattern = re.compile(
        rf"\b({'|'.join(KEYWORDS)})\s+(?:#(\d+)|https://github\.com/{repo}/(?:issues|pull)/(\d+))\b",
        re.IGNORECASE,
    )
    found: list[tuple[str, int]] = []
    for match in pattern.finditer(body):
        pair = (match[1].lower(), int(match[2] or match[3]))
        if pair not in found:
            found.append(pair)
    return found


def work_issue(body: str, repository: str) -> int | None:
    """The number of the issue the first line of `body` names in `repository`; None without one."""
    found = references(body.split("\n", 1)[0], repository)
    return found[0][1] if found else None


class Api:
    """The one door to GitHub: GET on the REST API with the Actions token."""

    def __init__(self, base: str, token: str, repository: str) -> None:
        self.base, self.token, self.repository = base.rstrip("/"), token, repository

    def issue(self, number: int) -> dict | None:
        """Issue or pull request `number` of the repository as the issues API returns it; None
        where it does not exist."""
        request = urllib.request.Request(
            f"{self.base}/repos/{self.repository}/issues/{number}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                return None
            raise SetupError(f"GET issue #{number}: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise SetupError(f"GET issue #{number}: {error.reason}") from error


def labels(item: dict) -> set[str]:
    return {str(label.get("name", "")).lower() for label in item.get("labels") or []}


def issue_verdict(item: dict | None) -> str | None:
    """None where `item` is an open work issue, else why it does not count."""
    if item is None:
        return "does not exist"
    if "pull_request" in item:
        return "is a pull request"
    if item.get("state") != "open":
        return f"is {item.get('state')}"
    if WORK_LABEL not in labels(item):
        return f"is not labelled {WORK_LABEL}"
    return None


def names_work_issue(api: Api, body: str, out: list[str], lands: bool) -> bool:
    """Whether `body` names an open work issue; with `lands`, a `Lands` reference to a pull request
    counts when that pull request's description names one. Writes one line per reference."""
    passed = False
    for keyword, number in references(body, api.repository):
        item = api.issue(number)
        if keyword == "lands" and item is not None and "pull_request" in item:
            if not lands:
                out.append(f"  Lands #{number}: a landing's landing does not count")
                continue
            out.append(f"  Lands #{number}: pull request, its description:")
            if names_work_issue(api, str(item.get("body") or ""), out, lands=False):
                passed = True
            continue
        why = issue_verdict(item)
        out.append(f"  {keyword.capitalize()} #{number}: " + ("open work issue" if why is None
                                                            else f"{why}, does not count"))
        passed = passed or why is None
    return passed


def integration_branch(root: Path) -> str:
    file = root / "se.toml"
    if not file.exists():
        return "main"
    project = tomllib.loads(file.read_text(encoding="utf-8")).get("project", {})
    return str(project.get("integration_branch", "main"))


def check(event: dict, api: Api, branch: str) -> tuple[int, list[str]]:
    """The verdict on the pull request of `event`: (exit code, lines to print)."""
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise SetupError("the event carries no pull_request")
    number = pull.get("number")
    base = str((pull.get("base") or {}).get("ref", ""))
    if base != branch:
        return 0, [f"pr-issues: pull request #{number} targets {base}, not {branch}: not checked"]
    author = str((pull.get("user") or {}).get("login", ""))
    owner = str(((event.get("repository") or {}).get("owner") or {}).get("login", ""))
    if author and author.lower() == owner.lower() and HOUSEKEEPING_LABEL in labels(pull):
        return 0, [f"pr-issues: pull request #{number} is the owner's {HOUSEKEEPING_LABEL}: exempt"]
    lines = [f"pr-issues: pull request #{number} into {branch} names:"]
    if names_work_issue(api, str(pull.get("body") or ""), lines, lands=True):
        lines.append("pr-issues: passed, it names an open work issue")
        return 0, lines
    lines.append(f"::error::pr-issues: pull request #{number} names no open issue of "
                 f"{api.repository} labelled {WORK_LABEL} (Refs|Closes|Fixes #<n> or the issue's "
                 f"URL; a landing: Lands <work pull request>): {REMEDY}")
    return 1, lines


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path("."),
                        help="the checkout whose se.toml names the integration branch")
    parser.add_argument("--work-issue", type=Path, metavar="FILE",
                        help="only print the number of the issue the first line of the pull "
                             "request description in FILE names; exit code 1 where it names none")
    parser.add_argument("--repository", metavar="OWNER/REPO",
                        help="with --work-issue: the repository; default GITHUB_REPOSITORY")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    if args.work_issue is not None:
        repository = args.repository or env.get("GITHUB_REPOSITORY")
        if not repository:
            print("::error::pr-issues: --work-issue needs --repository or GITHUB_REPOSITORY")
            return 2
        number = work_issue(args.work_issue.read_text(encoding="utf-8"), repository)
        if number is None:
            return 1
        print(number)
        return 0
    try:
        missing = [name for name in ("GITHUB_EVENT_PATH", "GITHUB_TOKEN", "GITHUB_REPOSITORY")
                   if not env.get(name)]
        if missing:
            raise SetupError(f"{', '.join(missing)} not set; the job passes them "
                             "(.github/workflows/check.yml)")
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        api = Api(env.get("GITHUB_API_URL") or "https://api.github.com", env["GITHUB_TOKEN"],
                  env["GITHUB_REPOSITORY"])
        code, lines = check(event, api, integration_branch(args.repo))
    except (SetupError, OSError, ValueError) as error:
        print(f"::error::pr-issues: {error}")
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
