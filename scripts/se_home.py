#!/usr/bin/env python3
"""SE's home, from the checkout's origin: the one answer to where a checkout lives.

The same tree may live on more than one Git host, and only a machine that holds both remotes knows
that, so no tracked file should name a host, owner or repository. Where SE needs its own
location, a Python reader asks this module, which reads `origin` through git's
door (`scripts/git_door.py`):

- `home(root)`: `https://<host>/<owner>/<repository>`, with no credentials, no port and no `.git`,
  read from an https origin (with or without credentials) or an ssh one (`ssh://[user@]host/...` or
  `[user@]host:owner/repository`). Any other form, such as a local git proxy's
  `http://proxy@127.0.0.1:<port>/git/<owner>/<repository>` or a path, has no home: `NoHome`, as
  without an origin. Nothing guesses one.
- `Home.tracker`: `<owner>/<repository>`; `Home.docs_url`: the GitHub Pages site of a home on
  `github.com`, `https://<owner>.github.io/<repository>/`, and none on any other host.
- `Home.named(entry)`: a setting's repository: `<repository>` is the one beside the home, under the
  same owner on the same host; `<owner>/<repository>` and `<host>/<owner>/<repository>` stay
  absolute, so another repository's se.toml that names them keeps working.
- `module_url(origin, url)`: a module URL relative to origin (`../obs.git`), resolved against the
  origin URL as git resolves a relative submodule URL; an absolute URL comes back as it is.

As a command, `se_home.py [--repo <path>] {url,tracker,docs,module <url>}` prints one answer; exit
code 0, or 1 with the reason where the checkout has no home.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import git_door

ROOT = Path(__file__).resolve().parents[1]

GITHUB = "github.com"

HTTPS = re.compile(r"^https://(?:[^@/]*@)?(?P<host>[^/:@]+)(?::\d+)?/(?P<path>[^?#]+?)(?:\.git)?/?$",
                   re.IGNORECASE)
SSH = re.compile(r"^ssh://(?:[^@/]+@)?(?P<host>[^/:@]+)(?::\d+)?/(?P<path>[^?#]+?)(?:\.git)?/?$",
                 re.IGNORECASE)
# `[user@]host:owner/repository`; a host of one letter is a Windows drive, not an ssh host.
SCP = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^/:@\\]{2,}):(?!//)(?P<path>[^\\]+?)(?:\.git)?/?$")
NAME = re.compile(r"^[\w.-]+$")
RELATIVE = ("./", "../")


class NoHome(Exception):
    """The checkout's home cannot be known: no origin, or one of no form `parse` reads."""


@dataclass(frozen=True)
class Home:
    host: str
    owner: str
    repository: str

    @property
    def url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.repository}"

    @property
    def tracker(self) -> str:
        return f"{self.owner}/{self.repository}"

    @property
    def docs_url(self) -> str:
        """The GitHub Pages site of a home on github.com; "" on any other host."""
        if self.host.lower() != GITHUB:
            return ""
        return f"https://{self.owner.lower()}.github.io/{self.repository}/"

    def named(self, entry: str) -> str:
        """`<host>/<owner>/<repository>` of a setting's repository: a bare name is beside the home."""
        parts = entry.strip("/").split("/")
        if len(parts) == 1:
            return f"{self.host}/{self.owner}/{parts[0]}"
        if len(parts) == 2:
            return f"{self.host}/{entry.strip('/')}"
        return entry.strip("/")


def parse(url: str) -> Home | None:
    """The home an origin URL names, or None for a form this module does not read."""
    url = url.strip()
    match = HTTPS.match(url) or SSH.match(url) or (None if "://" in url else SCP.match(url))
    if match is None:
        return None
    parts = match.group("path").strip("/").split("/")
    if len(parts) != 2 or not all(NAME.match(part) for part in parts):
        return None
    return Home(match.group("host").lower(), parts[0], parts[1])


def origin(root: Path) -> str | None:
    """The checkout's `origin` URL (git's insteadOf rewrites applied), or None without one."""
    result = git_door.run("remote", "get-url", "origin", root=root)
    url = result.stdout.strip() if result.returncode == 0 else ""
    return url or None


def home(root: Path) -> Home:
    """The checkout's home; NoHome, with its reason, where it cannot be known."""
    url = origin(root)
    if url is None:
        raise NoHome(f"{root} has no origin remote, so SE's home cannot be known")
    found = parse(url)
    if found is None:
        raise NoHome(f"the origin of {root} is no https or ssh repository URL, so SE's home "
                     "cannot be known")
    return found


def find(root: Path) -> Home | None:
    """The checkout's home, or None where it cannot be known."""
    try:
        return home(root)
    except NoHome:
        return None


def is_relative(url: str) -> bool:
    return url.startswith(RELATIVE)


PREFIX = re.compile(r"^(?P<prefix>[a-z][a-z0-9+.-]*://[^/]*/|(?:[^@/:]+@)?[^/:@\\]{2,}:)(?P<path>.*)$",
                    re.IGNORECASE)


def module_url(origin_url: str, url: str) -> str:
    """`url` resolved against `origin_url` as git resolves a relative submodule URL: each `../`
    drops one segment of the origin's path; an absolute `url` comes back unchanged."""
    if not is_relative(url):
        return url
    match = PREFIX.match(origin_url.strip())
    prefix, path = (match.group("prefix"), match.group("path")) if match else ("", origin_url.strip())
    if not match and path.startswith("/"):
        prefix = "/"
    segments = [part for part in path.split("/") if part]
    rest = url
    while rest.startswith(RELATIVE):
        if rest.startswith("../"):
            if not segments:
                raise NoHome(f"{url} climbs above the origin's path")
            segments.pop()
        rest = rest[3:] if rest.startswith("../") else rest[2:]
    return prefix + "/".join([*segments, *([rest] if rest else [])])


def resolve_module(root: Path, url: str) -> str:
    """A module URL as `root`'s checkout reaches it: a relative one against its origin."""
    if not is_relative(url):
        return url
    found = origin(root)
    if found is None:
        raise NoHome(f"{url} is relative to origin, and {root} has no origin remote")
    return module_url(found, url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="se_home.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=ROOT, help="the checkout (default: SE's own)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("url", help="https://<host>/<owner>/<repository>")
    commands.add_parser("tracker", help="<owner>/<repository>")
    commands.add_parser("docs", help="the documentation's URL (GitHub Pages of a github.com home)")
    module = commands.add_parser("module", help="a module URL, a relative one resolved against origin")
    module.add_argument("url")
    args = parser.parse_args(argv)
    try:
        if args.command == "module":
            print(resolve_module(args.repo, args.url))
            return 0
        found = home(args.repo)
    except NoHome as error:
        print(f"se_home: {error}", file=sys.stderr)
        return 1
    answer = {"url": found.url, "tracker": found.tracker, "docs": found.docs_url}[args.command]
    if not answer:
        print(f"se_home: {found.host} has no documentation site SE knows", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
