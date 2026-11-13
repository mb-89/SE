"""`se new app <name> --path <dir>`: a new application on kern, from kern's template at SE's kern pin.

The design is docs/go-core.md "A bare application, and `se new app`"; README "New application" owns
what the command does. While kern is incubated in SE, no Go module `github.com/mb-89/kern` can be
fetched, so the application carries kern's source at the pin in `kern/` and its go.mod replaces the
module by it; the move to `mb-89/kern` drops both.
"""

from __future__ import annotations

import importlib.util
import io
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath

import git_door

SE_ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
# The template names its application `app`: every word `app` in a path or a text file is the name,
# except in the command's own name, `se new app`.
TEMPLATE_NAME = re.compile(r"(?<!se new )\bapp\b")
TEMPLATE_IDENTITY = 'identity = "<name> <name>"'
# go.mod's replace of kern, with the comment lines above it, as the template writes it.
KERN_REPLACE = re.compile(r"(?m)(?:^//.*\n)*^replace github\.com/mb-89/kern => .*\n?")
APP_REPLACE = (
    "// kern is incubated in SE: no module github.com/mb-89/kern can be fetched yet, so kern's\n"
    "// source at its pin is in kern/; the move to mb-89/kern drops this line and that folder.\n"
    "replace github.com/mb-89/kern => ./kern\n"
)


class NewError(Exception):
    """A refusal that names its remedy."""


def _sibling(name: str):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(f"{name}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None, binary: bool = False):
    done = git_door.run(*args, cwd=cwd, env=env, binary=True)
    if done.returncode != 0:
        raise NewError(f"git {' '.join(args)} failed in {cwd}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout if binary else done.stdout.decode().strip()


def _has_ref(root: Path, ref: str) -> bool:
    return git_door.run("rev-parse", "-q", "--verify", f"{ref}^{{commit}}", cwd=root).returncode == 0


def source_ref(se_root: Path, tag: str) -> tuple[str, str]:
    """(ref, note) the template is read at: the pin's tag, fetched from origin where the clone lacks
    it; HEAD, with a note saying so, where the version is not released yet."""
    if not _has_ref(se_root, f"refs/tags/{tag}"):
        git_door.run("fetch", "-q", "origin", f"refs/tags/{tag}:refs/tags/{tag}", cwd=se_root, no_prompt=True)
    if _has_ref(se_root, f"refs/tags/{tag}"):
        return f"refs/tags/{tag}", ""
    head = _git(se_root, "rev-parse", "--short=12", "HEAD")
    return "HEAD", f"{tag} is not released yet: kern and its template come from {se_root}'s HEAD, {head}"


def unpack(se_root: Path, ref: str, path: Path, name: str) -> None:
    """kern's template at `ref` into `path`, the name filled in; kern's source beside it in
    `path/kern`, without the template."""
    archive = _git(se_root, "archive", "--format=tar", ref, "kern", binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            data = tar.extractfile(member).read()
            if parts[:2] == ("kern", "template"):
                relative = [TEMPLATE_NAME.sub(name, part) for part in parts[2:]]
                try:
                    data = TEMPLATE_NAME.sub(name, data.decode("utf-8")).encode("utf-8")
                except UnicodeDecodeError:
                    pass
            else:
                relative = list(parts)
            target = path.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if member.mode & 0o111:
                target.chmod(0o755)


def _fill(path: Path, old: re.Pattern | str, new: str, tag: str) -> None:
    text = path.read_text(encoding="utf-8")
    filled = old.sub(new, text, count=1) if isinstance(old, re.Pattern) else text.replace(old, new, 1)
    if filled == text:
        what = old.pattern if isinstance(old, re.Pattern) else old
        raise NewError(f"kern's template at {tag} has no {what!r} in {path.name}: se_new.py no longer "
                       "matches the template; update the one with the other")
    path.write_text(filled, encoding="utf-8")


def github_owner(se_root: Path) -> str:
    """The owner of SE's origin on github.com, the owner the new repository most likely shares;
    `<owner>` where origin is elsewhere."""
    url = git_door.run("remote", "get-url", "origin", cwd=se_root).stdout.strip()
    found = re.match(r"(?:https://|ssh://git@|git@)github\.com[/:]([A-Za-z0-9-]+)/", url)
    return found[1] if found else "<owner>"


def create(name: str, path: Path, se_root: Path = SE_ROOT) -> list[str]:
    """Create the application `name` in `path` and make its first commit; answers the lines to say,
    the last of them the owner's GitHub step."""
    if not NAME_RE.fullmatch(name):
        raise NewError(f"{name!r} is no application name: lower-case letters, digits and dashes, "
                       "starting with a letter")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise NewError(f"{path} exists and is not empty: name a new or empty folder with --path")
    work_tickets = _sibling("work_tickets")
    identity = work_tickets.commit_identity(se_root)
    if identity is None:
        raise NewError(f"no commit identity for the application: set identity = \"Name <email>\" in "
                       f"[project] of {se_root / 'se.toml'} (README \"Project settings\")")
    version, tag = _sibling("se_modules").kern_pin(se_root)
    ref, note = source_ref(se_root, tag)
    commit = _git(se_root, "rev-parse", "--short=12", ref)
    path.mkdir(parents=True, exist_ok=True)
    unpack(se_root, ref, path, name)
    _fill(path / "go.mod", KERN_REPLACE, APP_REPLACE, tag)
    _fill(path / "se.toml", TEMPLATE_IDENTITY, f'identity = "{identity[0]} <{identity[1]}>"', tag)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", identity[0])
    _git(path, "config", "user.email", identity[1])
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", f"Start {name}, a bare application on kern {version}",
         env=git_door.identity_environment(identity[:2]))
    first = _git(path, "rev-parse", "--short=12", "HEAD")
    owner = github_owner(se_root)
    return [
        *([note] if note else []),
        f"se new app: {name} created in {path} from kern's template at {tag} ({commit}), "
        f"first commit {first}",
        f"Owner's step: create the GitHub repository {owner}/{name}, empty, with a ruleset on main "
        f"that requires the check \"check / battery\", then run: git -C {path} remote add origin "
        f"https://github.com/{owner}/{name}.git && git -C {path} push -u origin main",
    ]
