#!/usr/bin/env -S uv run python
# se:template se/python-script 1.0.0
"""CI's issue rule: a pull request into the integration branch names an open work issue it does.

The rule is the work model's (src/skills/work-model/SKILL.md "Integration branch"); this script
enforces it in the job `check` of .github/workflows/check.yml. It reads the pull request from the
Actions event (`GITHUB_EVENT_PATH`) and the issues it names through the REST API with the Actions
token (`GITHUB_TOKEN`), so it needs no `gh` sign-in.

A reference is `Refs`, `Closes`, `Fixes` or `Lands`, then `#<n>` or this repository's
`https://github.com/<owner>/<repo>/issues/<n>` (or `/pull/<n>`). The pull request passes when:

- one reference names an issue of this repository that is open and labelled `work`; or
- a retro report names its open retro issue with `Refs #<n>` and
  `<!-- se:retro-report <n> -->`; or
- one `Lands` reference names a pull request (a landing's work pull request) whose description
  names such an issue; or
- it was opened by the repository owner's account and carries the label `housekeeping`; or
- it was opened by the repository owner's account from `land/release-v<version>`, the release
  landing `work_tickets.py release` opens when SE asks for a release: it does no work, it raises
  the version by what the landed work recorded.

The event carries the pull request as it was opened; where that refuses, the pull request is read
again as it is now (the issues API), as `gh pr create --label` sets its labels, and an edit its
description, after the opened event.

A pull request into another branch is not checked. Exit code 0 passed, 1 refused, 2 setup error
(no event, no token, the API failing). A single server error (HTTP 5xx) on a read is read again once,
RETRY_SECONDS later, so one hiccup of GitHub does not fail the required check; a second fails it.

`--release-kind` is CI's release-kind gate (the work model's "Release kind"): a pull request into
the integration branch passes only where its description states its kind, a field report's
`**Release kind:** <kind>` or a `Release-kind: <kind>` line, as a landing and a release state it,
read by work_tickets.py's `stated_release_kind`, the reader `release` reads a merge's message by.
Nothing is exempt, so GitHub's merge button cannot land a pull request that states none. It reads
the event's description first and, where that states none, the description as it is now, as the
issue rule does; a refusal names the line to add. A pull request into another branch is not checked.

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
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
import se_script

WORK_LABEL = "work"
HOUSEKEEPING_LABEL = "housekeeping"
RELEASE_LANDING = re.compile(r"land/release-v\d+\.\d+\.\d+")  # work_tickets.py RELEASE_LANDING
RETRO_REPORT = re.compile(r"<!-- se:retro-report ([1-9]\d*) -->")
KEYWORDS = ("refs", "closes", "fixes", "lands")
RETRY_SECONDS = 5  # the wait before the one read again after a server error
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
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    return None
                if error.code >= 500 and attempt == 1:
                    print(f"::warning::pr-issues: GET issue #{number}: HTTP {error.code}; "
                          "reading it once more")
                    time.sleep(RETRY_SECONDS)
                    continue
                raise SetupError(f"GET issue #{number}: HTTP {error.code}") from error
            except urllib.error.URLError as error:
                raise SetupError(f"GET issue #{number}: {error.reason}") from error
        raise AssertionError("unreachable: the second attempt returns or raises")


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


def is_open_retro(item: dict | None) -> bool:
    """Whether `item` is an open retro issue eligible for its own report pull request."""
    if item is None or item.get("state") != "open":
        return False
    title = str(item.get("title") or "").lower()
    return "retro" in labels(item) or title.startswith("retro-")


def names_work_issue(api: Api, body: str, out: list[str], lands: bool) -> bool:
    """Whether `body` names an open work issue; with `lands`, a `Lands` reference to a pull request
    counts when that pull request's description names one. Writes one line per reference."""
    passed = False
    marker = RETRO_REPORT.search(body)
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
        if (keyword == "refs" and marker is not None and int(marker[1]) == number
                and is_open_retro(item)):
            out.append(f"  Retro report #{number}: open retro issue")
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
    head = str((pull.get("head") or {}).get("ref", ""))
    if author and author.lower() == owner.lower() and RELEASE_LANDING.fullmatch(head):
        return 0, [f"pr-issues: pull request #{number} is the owner's release landing {head}: "
                   "exempt"]
    lines: list[str] = []
    for reading in ("event", "live"):
        if reading == "live":
            # The event is the pull request as it was opened: `gh pr create --label` adds its
            # labels, and an edit its body, a moment later. Read it as it is now before refusing.
            current = api.issue(int(number)) if isinstance(number, int) else None
            if current is None:
                break
            pull = {**pull, "body": current.get("body"), "labels": current.get("labels")}
            lines.append(f"pr-issues: pull request #{number} as it is now:")
        if author and author.lower() == owner.lower() and HOUSEKEEPING_LABEL in labels(pull):
            return 0, [*lines, f"pr-issues: pull request #{number} is the owner's "
                               f"{HOUSEKEEPING_LABEL}: exempt"]
        lines.append(f"pr-issues: pull request #{number} into {branch} names:")
        if names_work_issue(api, str(pull.get("body") or ""), lines, lands=True):
            lines.append("pr-issues: passed, it names an open work issue or its retro report")
            return 0, lines
    lines.append(f"::error::pr-issues: pull request #{number} names no open issue of "
                 f"{api.repository} labelled {WORK_LABEL} (Refs|Closes|Fixes #<n> or the issue's "
                 f"URL; a landing: Lands <work pull request>): {REMEDY}")
    return 1, lines


KIND_REMEDY = ("add the line `{line}` to the description: a worker's field report states it as "
               "`**Release kind:** <kind> — <reason>` (work_tickets.py field-report --draft), a "
               "landing and a release as that line (integrate and release write it); there is no "
               "default (work model, \"Release kind\")")


def kind_check(event: dict, api: Api, branch: str) -> tuple[int, list[str]]:
    """CI's release-kind gate on the pull request of `event`: (exit code, lines to print)."""
    import work_tickets  # late: only this gate reads a release kind

    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise SetupError("the event carries no pull_request")
    number = pull.get("number")
    base = str((pull.get("base") or {}).get("ref", ""))
    if base != branch:
        return 0, [f"release-kind: pull request #{number} targets {base}, not {branch}: not checked"]
    lines: list[str] = []
    body = str(pull.get("body") or "")
    kind = work_tickets.stated_release_kind(body)
    if kind is None and isinstance(number, int):
        # The event is the pull request as it was opened; an edit may have stated the kind since.
        current = api.issue(number)
        if current is not None:
            body = str(current.get("body") or "")
            kind = work_tickets.stated_release_kind(body)
            lines.append(f"release-kind: pull request #{number} as it is now:")
    if kind is not None:
        return 0, [*lines, f"release-kind: pull request #{number} into {branch} states {kind}"]
    kinds = work_tickets.stated_release_kinds(body)
    stated = f"states {', '.join(map(repr, kinds))}" if kinds else "states no release kind"
    lines.append(f"::error::release-kind: pull request #{number} into {branch} {stated}: "
                 + KIND_REMEDY.format(line=work_tickets.RELEASE_KIND_LINE))
    return 1, lines


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    parser = se_script.parser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path("."),
                        help="the checkout whose se.toml names the integration branch")
    parser.add_argument("--work-issue", type=Path, metavar="FILE",
                        help="only print the number of the issue the first line of the pull "
                             "request description in FILE names; exit code 1 where it names none")
    parser.add_argument("--repository", metavar="OWNER/REPO",
                        help="with --work-issue: the repository; default GITHUB_REPOSITORY")
    parser.add_argument("--release-kind", action="store_true",
                        help="CI's release-kind gate instead of the issue rule: refuse a pull "
                             "request into the integration branch whose description states no "
                             "release kind")
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
        judge = kind_check if args.release_kind else check
        code, lines = judge(event, api, integration_branch(args.repo))
    except (SetupError, OSError, ValueError) as error:
        print(f"::error::pr-issues: {error}")
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
