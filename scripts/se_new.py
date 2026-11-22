"""`se new app <name> --path <dir>`: a new application on kern, from kern's template at SE's kern pin.

The design is docs/go-core.md "A bare application, and `se new app`"; README "New application" owns
what the command does. The template comes from the clone of kern se.toml [components.kern] pins
(scripts/se_modules.py `kern_dir`), at its tag `v<version>`. The application pins the kern SE pins:
its go.mod requires kern at that version and replaces the module by `./.se/modules/kern`, its se.lock
locks the commit SE's se.lock locks, and SE's clone at that commit is copied there, ignored, so the
application builds before it has an origin; `se_modules.py sync kern` keeps it there afterwards.
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
# The generic installer every application has (des-016): executable wherever it is unpacked, even
# where the archive lost its mode.
RUNME = "RUNME.sh"
TEMPLATE_IDENTITY = 'identity = "<name> <name>"'
# The application's pin of kern in se.toml: se 6 lists it under [components], found by its name, so
# a template that still writes [modules.kern] with its url gets [components.kern] with its go alone.
KERN_TABLE = "[components.kern]"
TEMPLATE_KERN_TABLE = re.compile(r"(?m)^\[modules\.kern\][ \t]*\n(?:url[ \t]*=.*\n)?")
# go.mod's replace of kern, with the comment lines above it, as the template writes it: the one
# replace of the template, by kern's source one folder up.
KERN_REPLACE = re.compile(r"(?m)(?:^//.*\n)*^replace (?P<module>\S+) => \.\./?[ \t]*\n?")
# go.mod's require of kern, whose version the application gets as the pin.
KERN_REQUIRE = re.compile(r"(?m)^(?P<lead>(?:require[ \t]+|[ \t]+)kern[ \t]+)v\S+")
# The folder of kern's repository that is the application.
TEMPLATE = "template"
# Where the application's kern is: its clone at the pin (se_modules.py `kern_dir`), which git ignores.
KERN_PLACE = ".se/modules/kern"
IGNORED = ".se/modules/"


def app_replace(match: re.Match) -> str:
    """The application's replace of kern's module, by its clone at the pin."""
    module = match["module"]
    return (f"// kern at the version required above, in its clone that `se_modules.py sync kern` places\n"
            f"// there (se.toml [components.kern]).\nreplace {module} => ./{KERN_PLACE}\n")


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


def source_ref(kern: Path, tag: str) -> str:
    """The ref kern's template is read at in the pinned clone `kern`: the pin's tag, fetched from
    its origin where the clone lacks it."""
    if not _has_ref(kern, f"refs/tags/{tag}"):
        git_door.run("fetch", "-q", "origin", f"refs/tags/{tag}:refs/tags/{tag}", cwd=kern, no_prompt=True)
    if not _has_ref(kern, f"refs/tags/{tag}"):
        raise NewError(f"kern's clone {kern} has no tag {tag}: run uv run python scripts/se_modules.py "
                       "sync kern, or release kern at the version components/go.mod requires")
    return f"refs/tags/{tag}"


def unpack(kern: Path, ref: str, path: Path, name: str) -> None:
    """kern's template at `ref` of the clone `kern` into `path`, the name filled in: the template
    alone, none of kern's own source."""
    archive = _git(kern, "archive", "--format=tar", ref, TEMPLATE, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = PurePosixPath(member.name).parts
            if not member.isfile() or parts[0] != TEMPLATE:
                continue
            relative = [TEMPLATE_NAME.sub(name, part) for part in parts[1:]]
            data = tar.extractfile(member).read()
            try:
                data = TEMPLATE_NAME.sub(name, data.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                pass
            target = path.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if member.mode & 0o111 or relative[-1:] == [RUNME]:
                target.chmod(0o755)


def kern_lock(se_root: Path, version: str, kern: Path, ref: str) -> str:
    """The commit SE's se.lock locks for kern `version`, the commit of the tag `ref` in the clone
    `kern`; refused, naming the sync, where the lock is missing, off the pin or off the tag."""
    modules = _sibling("se_modules")
    try:
        locked = modules.read_lock(se_root).get(modules.KERN)
    except modules.ModuleError as error:
        raise NewError(str(error)) from error
    sync = f"run uv run python scripts/se_modules.py sync kern in {se_root}"
    if locked is None or locked[0] != version:
        found = f"locks kern {locked[0]}" if locked else "locks no kern"
        raise NewError(f"{se_root / modules.LOCK} {found}, but the pin is kern {version}: {sync}")
    tagged = _git(kern, "rev-parse", f"{ref}^{{commit}}")
    if tagged != locked[1]:
        raise NewError(f"{se_root / modules.LOCK} locks kern {version} at {locked[1][:12]}, but its tag "
                       f"{ref.removeprefix('refs/tags/')} is {tagged[:12]} in {kern}: {sync}")
    return locked[1]


def place_kern(kern: Path, commit: str, path: Path) -> None:
    """SE's clone of kern, at `commit`, into the application's `.se/modules/kern`, ignored by git:
    the application builds on it before it has an origin, and `se_modules.py sync` there later
    points its origin at kern beside the application."""
    place = path / KERN_PLACE
    place.parent.mkdir(parents=True, exist_ok=True)
    _git(place.parent, "clone", "--quiet", "--no-checkout", str(kern), str(place))
    _git(place, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit)
    ignore = path / ".gitignore"
    text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if not {IGNORED, f"/{IGNORED}", ".se/", "/.se/"} & {line.strip() for line in text.splitlines()}:
        ignore.write_text(text + ("" if not text or text.endswith("\n") else "\n") + IGNORED + "\n",
                          encoding="utf-8")


def _fill(path: Path, old: re.Pattern | str, new, tag: str) -> None:
    text = path.read_text(encoding="utf-8")
    filled = old.sub(new, text, count=1) if isinstance(old, re.Pattern) else text.replace(old, new, 1)
    if not (old.search(text) if isinstance(old, re.Pattern) else old in text):
        what = old.pattern if isinstance(old, re.Pattern) else old
        raise NewError(f"kern's template at {tag} has no {what!r} in {path.name}: se_new.py no longer "
                       "matches the template; update the one with the other")
    path.write_text(filled, encoding="utf-8")


# The workflows the template's CI calls, and the action the battery calls, written beside it as
# generated copies (scripts/se_workflows.py).
APP_WORKFLOWS = (".github/workflows/kern-battery.yml", ".github/actions/kern-at-pin/action.yml")


def se_repository(se_root: Path) -> str:
    """How the application's CI reaches SE: the repository beside it, under the same owner, by the
    name of SE's home (scripts/se_home.py), else of SE's folder."""
    found = _sibling("se_home").find(se_root)
    return f"{_sibling('se_workflows').OWNER}/{found.repository if found else se_root.name}"


def write_workflows(se_root: Path, ref: str, path: Path) -> None:
    """The copies of SE's workflows at `ref` that the template's CI calls, into `path`."""
    workflows = _sibling("se_workflows")
    try:
        plan = workflows.Plan(APP_WORKFLOWS, workflows.commit(se_root, ref), se_repository(se_root), se_root)
        workflows.write(path, plan)
    except workflows.WorkflowError as error:
        raise NewError(str(error)) from error


def github_owner(se_root: Path) -> str:
    """The owner of SE's home on github.com (scripts/se_home.py), the owner the new repository most
    likely shares; `<owner>` where SE's home is elsewhere or unknown."""
    found = _sibling("se_home").find(se_root)
    return found.owner if found and found.host == "github.com" else "<owner>"


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
    modules = _sibling("se_modules")
    try:
        version, tag = modules.kern_pin(se_root)
    except modules.ModuleError as error:
        raise NewError(str(error)) from error
    kern = modules.kern_dir(se_root)
    ref = source_ref(kern, tag)
    commit = kern_lock(se_root, version, kern, ref)
    path.mkdir(parents=True, exist_ok=True)
    unpack(kern, ref, path, name)
    _fill(path / "go.mod", KERN_REQUIRE, lambda match: f"{match['lead']}v{version}", tag)
    _fill(path / "go.mod", KERN_REPLACE, app_replace, tag)
    _fill(path / "se.toml", TEMPLATE_IDENTITY, f'identity = "{identity[0]} <{identity[1]}>"', tag)
    if KERN_TABLE not in (path / "se.toml").read_text(encoding="utf-8"):
        _fill(path / "se.toml", TEMPLATE_KERN_TABLE, KERN_TABLE + "\n", tag)
    (path / modules.LOCK).write_text(modules.lock_text({modules.KERN: (version, commit)}),
                                     encoding="utf-8", newline="\n")
    write_workflows(se_root, "HEAD", path)
    place_kern(kern, commit, path)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", identity[0])
    _git(path, "config", "user.email", identity[1])
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", f"Start {name}, a bare application on kern {version}",
         env=git_door.identity_environment(identity[:2]))
    first = _git(path, "rev-parse", "--short=12", "HEAD")
    owner = github_owner(se_root)
    return [
        f"se new app: {name} created in {path} from kern's template at {tag} ({commit[:12]}), "
        f"first commit {first}",
        f"kern {version} placed in {path / KERN_PLACE}, which git ignores; run uv run python "
        f"<se>/scripts/se_modules.py sync kern there to keep it at the pin",
        f"Owner's step: create the GitHub repository {owner}/{name}, empty, with a ruleset on main "
        f"that requires the check \"check / battery\", then run: git -C {path} remote add origin "
        f"https://github.com/{owner}/{name}.git && git -C {path} push -u origin main",
    ]
