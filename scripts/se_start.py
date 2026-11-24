"""SE's start: the greeting, whether everything SE uses is up to date, and the one refresh.

`status` answers from what is on disk and the cached update check, never from the network, and
starts the check in the background when the cache is stale; `check` runs that check, and where gh
is signed in also counts the work landed since the last retro and runs the fleet check; `refresh`
moves every module that is due within its range, and SE itself, into place; `start-refresh` moves
an installed SE that is a git checkout to its latest release at the session's start;
`start-components` resolves the project's components there, stopping the start where a required one
is missing. What each command does and where SE runs it is the README section "Start and refresh".
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

SE_ROOT = Path(__file__).resolve().parents[1]
ROOT_NAME = "SE root"  # the hook's context names SE_ROOT under this name
CACHE_DEFAULT = Path("~/.se/start-check.json")
CACHE_ENV = "SE_START_CACHE"
MAX_AGE = 3600  # seconds a cached update check stays fresh
RUNNING_FOR = 120  # seconds a started background check counts as running
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
CLOUD_ENV = "CLAUDE_CODE_REMOTE"  # "true" in a Claude Code cloud session
CLOUD_PLUGINS = "README \"Claude Code cloud\""
CHECK_REMEDY = "run it by hand to see the cause: uv run python {se}/scripts/se_start.py check"
START_TIMEOUT = 15  # seconds each network read of the refresh at start may take
COMPONENTS_TIMEOUT = 60  # seconds the project's component listing may take
COMPONENTS_HEADER = ("component", "kind", "installed", "newest", "repository")


def _load(name: str):
    """A sibling script, loaded once under its own name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


git_door = _load("git_door")
process_door = _load("process_door")
se_modules = _load("se_modules")
public_check = _load("public_check")
metrics = _load("metrics")
feedback = _load("feedback")
kern_names = _load("kern_names")
se_plugin = _load("se_plugin")
se_home = _load("se_home")
upgrade_guide = _load("upgrade_guide")
ModuleError = se_modules.ModuleError
Version = tuple[int, int, int]


class RemoteError(Exception):
    """A remote that could not be read; the message names it and the cause."""


# Inputs


def git_tags(url: str, timeout: float = 60) -> list[Version]:
    """The `vMAJOR.MINOR.PATCH` tags of a remote, in one call that fetches nothing."""
    feedback.reading("the remote", ["git", "ls-remote", "--tags", "--refs", url])
    result = git_door.run("ls-remote", "--tags", "--refs", url, no_prompt=True, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RemoteError(f"cannot reach {url}: {detail[-1] if detail else 'git ls-remote failed'}")
    tags = (line.rpartition("refs/tags/v")[2] for line in result.stdout.splitlines() if "refs/tags/v" in line)
    return sorted(v for tag in tags if (v := se_modules.parse_version(tag)) is not None)


def _front_names(folder: Path, pattern: str) -> list[str]:
    return sorted(path.parent.name if path.name == "SKILL.md" else path.stem for path in folder.glob(pattern))


@dataclass(frozen=True)
class Counts:
    skills: int
    rules: int
    subagents: int


def counts(se_root: Path) -> Counts:
    """What the plugin loads, as its layout holds it and the documentation's pages list it
    (se_plugin.py `inventory`): the skills, guidance notes aside; the rules in force, the rule
    book's and every guidance note; every agent but SE itself as a sub-agent."""
    found = se_plugin.layout_inventory(se_root)
    return Counts(len(found.skills), found.rules, len(found.subagents))


def _project(root: Path) -> dict:
    manifest = root / se_modules.MANIFEST
    if not manifest.is_file():
        return {}
    with manifest.open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    return project if isinstance(project, dict) else {}


def _origin(se_root: Path) -> str | None:
    if not (se_root / ".git").exists():
        return None
    result = git_door.run("remote", "get-url", "origin", root=se_root)
    return result.stdout.strip() or None if result.returncode == 0 else None


def _docs_url(se_root: Path) -> str:
    """se.toml's `docs_url` where it sets one, else the docs URL of SE's home, from its origin
    (scripts/se_home.py); "" where neither is known."""
    explicit = _project(se_root).get("docs_url")
    if isinstance(explicit, str) and explicit:
        return explicit
    origin = _origin(se_root)
    home = se_home.parse(origin) if origin else None
    return home.docs_url if home else ""


@dataclass(frozen=True)
class Item:
    """One thing SE uses: SE itself or a module of the project."""

    name: str
    kind: str  # "se", "range", "local", "commit"
    version: Version | None  # in use
    url: str | None  # where newer versions are looked up; None: not looked up
    range: str | None = None
    note: str = ""  # in use, where no version says it (a local path, a commit pin)

    def bounds(self) -> tuple[Version, Version] | None:
        if self.kind == "range":
            return se_modules.version_bounds(self.name, self.range)
        if self.kind == "se" and self.version:
            return self.version, (self.version[0] + 1, 0, 0)
        return None


@dataclass(frozen=True)
class Local:
    """Everything status reads from disk."""

    se_version: Version | None
    docs_url: str
    counts: Counts
    items: list[Item]
    errors: list[str] = field(default_factory=list)
    lacking: list[tuple["se_plugin.RoleSkill", tuple[str, ...]]] = field(default_factory=list)
    skills_error: str = ""  # se.toml [roles] could not be read


def read_local(se_root: Path, root: Path | None, local_config: Path | None) -> Local:
    """SE's version, docs and counts, and each module's version in use; never the network."""
    errors = []
    se_version = se_modules.parse_version(_project(se_root).get("version"))
    try:
        local = se_modules.load_local(local_config or se_modules.default_local_config())
    except ModuleError as error:
        errors.append(f"machine-local configuration: {error}")
        local = se_modules.LocalConfig(paths={}, urls={})
    items = [_se_item(se_root, se_version, local)]
    if root is not None and (root / se_modules.MANIFEST).is_file() and not errors:
        try:
            locked = se_modules.read_lock(root)
            modules = se_modules.load_manifest(root)
            for module in modules:
                items.append(_module_item(root, module, local, locked))
            own = {module.name.lower() for module in modules}
            items += [_nested_item(root, name, version) for name, (version, _) in sorted(locked.items())
                      if name.lower() not in own]
        except ModuleError as error:
            errors.append(f"modules of {root / se_modules.MANIFEST}: {error}")
    try:
        missing, skills_error = lacking(se_root), ""
    except se_plugin.SourceError as error:
        missing, skills_error = [], str(error)
    return Local(se_version, _docs_url(se_root), counts(se_root), items, errors,
                 missing, skills_error)


def _claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def installed_plugins() -> set[str]:
    """The plugins this session has, as `<plugin>@<marketplace>`: those Claude Code's record of the
    installed plugins names, and a plugin cloned into its skills folder (`<plugin>@skills-dir`, as
    the cloud's SE is)."""
    try:
        data = json.loads(plugin_registry().read_text(encoding="utf-8"))
        names = set(data.get("plugins", {})) if isinstance(data, dict) else set()
    except (OSError, ValueError, AttributeError, TypeError):
        names = set()
    skills = _claude_dir() / "skills"
    if skills.is_dir():
        names |= {f"{path.parent.parent.name}@skills-dir"
                  for path in skills.glob("*/.claude-plugin/plugin.json")}
    return names


def lacking(se_root: Path) -> list[tuple["se_plugin.RoleSkill", tuple[str, ...]]]:
    """Each skill of SE's `[roles]` list whose plugin this session lacks, with the roles that rely
    on it."""
    have = installed_plugins()
    present = {name.partition("@")[0] for name in have if name.endswith("@skills-dir")}
    found: dict["se_plugin.RoleSkill", list[str]] = {}
    for role, skills in se_plugin.roles(se_root).items():
        for skill in skills:
            if f"{skill.plugin}@{skill.marketplace}" not in have and skill.plugin not in present:
                found.setdefault(skill, []).append(role)
    return [(skill, tuple(roles)) for skill, roles in found.items()]


def _plugin_repository(se_root: Path) -> str | None:
    """The repository an installed copy names in its plugin manifest, where its versions are tagged."""
    try:
        data = json.loads((se_root / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repository = data.get("repository") if isinstance(data, dict) else None
    return repository if isinstance(repository, str) and repository else None


def marketplace_registry() -> Path:
    """Claude Code's record of the marketplaces it knows, each with the source it reads it from."""
    return _claude_dir() / "plugins" / "known_marketplaces.json"


def _marketplace_repository(se_root: Path) -> str | None:
    """The repository Claude Code installed this copy from: the source of the marketplace whose
    installed plugin lies at `se_root`, as Claude Code's records name it. The generated manifests
    name no home (AGENTS.md "Neutral home"), so an installed copy's home is the host's record."""
    def read(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    plugins = read(plugin_registry()).get("plugins", {})
    marketplace = next((key.partition("@")[2] for key, entries in (plugins.items() if isinstance(plugins, dict) else [])
                        for entry in (entries if isinstance(entries, list) else [entries])
                        if isinstance(entry, dict) and isinstance(entry.get("installPath"), str)
                        and Path(entry["installPath"]).expanduser().resolve() == se_root.resolve()), "")
    source = read(marketplace_registry()).get(marketplace, {}) if marketplace else {}
    source = source.get("source", {}) if isinstance(source, dict) else {}
    if not isinstance(source, dict):
        return None
    if source.get("source") == "github" and isinstance(source.get("repo"), str) and source["repo"]:
        return f"https://github.com/{source['repo']}"
    url = source.get("url")
    return url if source.get("source") == "git" and isinstance(url, str) and url else None


def _se_item(se_root: Path, version: Version | None, local) -> Item:
    """SE itself: a local path of `se` in the machine-local configuration (never touched), a git
    checkout (a development checkout or a cloud setup-script clone), or an installed copy (a Claude
    Code plugin or a Copilot copy), checked against the repository its plugin manifest names or,
    where it names none, the marketplace Claude Code installed it from."""
    path = local.paths.get("se")
    if path is not None and path == se_root.resolve():
        return Item("SE", "local", version, None, note=f"local path {se_root}")
    origin = _origin(se_root)
    if origin:
        return Item("SE", "se", version, origin)
    repository = _plugin_repository(se_root) or _marketplace_repository(se_root)
    return Item("SE", "se", version, repository, note="an installed copy" if repository else
                f"an installed copy without a repository in {PLUGIN_MANIFEST} or a marketplace "
                "record, not checked")


def _found_at(clone: Path) -> str | None:
    """Where a placed component was found, its clone's origin; None where it is not placed, as the
    start reads no remote to find it (docs/components.md "Required and optional at start")."""
    if not (clone / ".git").exists():
        return None
    result = git_door.run("remote", "get-url", "origin", root=clone)
    return result.stdout.strip() or None if result.returncode == 0 else None


def _nested_item(root: Path, name: str, version: str) -> Item:
    """A component the project's tree holds through another one: its locked version, looked up where
    its placed clone was found."""
    return Item(name, "nested", se_modules.parse_version(version),
                _found_at(root / se_modules.MODULES_DIR / name), note="held by a component of the tree")


def _module_item(root: Path, module, local, locked) -> Item:
    source = se_modules.resolve(root, module, local)
    if source.kind == "local":
        try:
            version = se_modules.checkout_version(source.checkout)
        except ModuleError:
            version = None
        return Item(module.name, "local", version, None, module.version, note=f"local path {source.checkout}")
    url = _found_at(source.checkout)
    if module.version is not None:
        text = locked.get(module.name, ("", ""))[0]
        return Item(module.name, "range", se_modules.parse_version(text), url, module.version,
                    note="" if text else "not locked (run se_modules.py sync)")
    clone = root / se_modules.MODULES_DIR / module.name
    try:
        version = se_modules.checkout_version(clone) if se_modules.is_populated(clone) else None
    except ModuleError:
        version = None
    return Item(module.name, "commit", version, url, note=f"pinned to commit {module.ref[:7]}")


# The cache of the update check


@dataclass
class Cache:
    """The last update check: per url its versions or its error, and when it ran."""

    checked_at: float | None = None
    started_at: float | None = None
    remotes: dict[str, dict] = field(default_factory=dict)
    work: dict | None = None  # what is due in the work (work_check); None: not read (no gh)
    components: dict | None = None  # the project's component listing (list_components); None: not run

    @classmethod
    def read(cls, path: Path) -> "Cache":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            work, components = data.get("work"), data.get("components")
            return cls(data.get("checked_at"), data.get("started_at"), dict(data.get("remotes", {})),
                       work if isinstance(work, dict) else None,
                       components if isinstance(components, dict) else None)
        except (OSError, ValueError, AttributeError):
            return cls()

    def write(self, path: Path) -> None:
        """Atomically: a status reading at the same time sees the old or the new check, whole."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"checked_at": self.checked_at, "started_at": self.started_at, "remotes": self.remotes,
                "work": self.work, "components": self.components}
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8",
                                         suffix=".tmp") as handle:
            json.dump(data, handle, indent=1)
        os.replace(handle.name, path)

    def fresh(self, urls: set[str], now: float, listing: dict | None = None) -> bool:
        """Checked within the hour, every url read, and, where the project sets a component
        listing (`listing`: its root and command), that listing run."""
        return (self.checked_at is not None and now - self.checked_at < MAX_AGE
                and urls <= set(self.remotes) and (not listing or components_of(self, listing) is not None))

    def running(self, now: float) -> bool:
        return self.started_at is not None and now - self.started_at < RUNNING_FOR


def default_cache() -> Path:
    return Path(os.environ.get(CACHE_ENV) or CACHE_DEFAULT).expanduser()


def run_check(urls: set[str], remote: Callable[[str], list[Version]]) -> dict[str, dict]:
    """Every remote read once, in parallel."""
    def one(url: str) -> dict:
        try:
            return {"versions": [list(v) for v in remote(url)]}
        except (RemoteError, OSError, subprocess.SubprocessError) as error:
            return {"error": str(error)}

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(urls)))) as pool:
        return dict(zip(sorted(urls), pool.map(one, sorted(urls))))


def countdown_part(found) -> dict:
    """A countdown (retro.py Countdown) as the cache keeps it."""
    part = {"count": found.count, "due_after": found.due_after, "due": found.due,
            "reason": found.reason, "open": list(found.open)}
    if found.kind == "retro":
        part.update(landed=found.landed, failed=found.failed)
    return part


def work_check(root: Path | None) -> dict | None:
    """What is due in the work of the project at `root`, where gh reaches GitHub (signed in, or
    over REST as in Claude Code's cloud, work_tickets.gh_backend): the retro and the
    overhaul countdowns (retro.py countdowns; the overhaul's only where its countdown is on,
    overhaul.py countdown_on), each with what it counted, whether it is due and why, and the runs
    of its kind still open; and the fleet check's findings, each part with its error instead where
    its read failed. None without gh or without a project checkout."""
    if root is None or not (root / ".git").exists():
        return None
    work_tickets = _load("work_tickets")
    if work_tickets.hand_off():
        return None
    retro = _load("retro")
    failures = (work_tickets.QueueError, OSError, ValueError, subprocess.SubprocessError)
    work: dict[str, dict] = {}
    try:
        repo = work_tickets.resolve_repo(root, None)
        branch = work_tickets.integration_branch(root)
    except failures as error:
        return {"retro": {"error": str(error)}, "fleet": {"error": str(error)}}
    overhaul_on = False
    try:
        overhaul_on = _load("overhaul").countdown_on(root)
        door = retro.GhDoor(root, repo, work_tickets.remote_repo(root) or repo)
        found = retro.countdowns(door, repo, branch, root, datetime.now(timezone.utc))
        if found is None:
            raise work_tickets.QueueError("the GitHub reads of the countdowns gave no answer")
        work["retro"] = countdown_part(found["retro"])
        if overhaul_on:  # only where the countdown is on: off, it names nothing
            work["overhaul"] = countdown_part(found["overhaul"])
    except failures as error:
        work["retro"] = {"error": str(error)}
        if overhaul_on:
            work["overhaul"] = {"error": str(error)}
    try:
        found = work_tickets.fleet_findings(
            work_tickets.Fleet(root, repo, branch), datetime.now(timezone.utc),
            work_tickets.fleet_lease(root), work_tickets.repository_name(root))
        work["fleet"] = {"findings": [{"kind": f.kind, "issue": f.issue} for f in found
                                      if f.stuck]}
    except failures as error:
        work["fleet"] = {"error": str(error)}
    return work


def components_command(root: Path | None) -> tuple[list[str] | None, str]:
    """The project's component listing command, `[project] components` of its se.toml, as an
    argument array; (None, "") where unset, (None, cause) where it is no argument array."""
    if root is None:
        return None, ""
    try:
        value = _project(root).get("components")
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, f"{(root / se_modules.MANIFEST).as_posix()}: {error}"
    if value is None:
        return None, ""
    if not isinstance(value, list) or not value or not all(isinstance(a, str) and a for a in value):
        return None, (f"[project] components of {(root / se_modules.MANIFEST).as_posix()} is no "
                      "argument array; set it as components = [\"uv\", \"run\", \"obs-components\"]")
    return value, ""


def listing_key(root: Path | None) -> dict | None:
    """What a cached listing answers for: the project and its command; None where none is set."""
    command, _ = components_command(root)
    return {"root": root.as_posix(), "command": command} if command and root else None


def components_of(cache: Cache, key: dict | None) -> dict | None:
    """The cached listing where it answers for `key`, else None."""
    found = cache.components
    if not key or not found or {k: found.get(k) for k in key} != key:
        return None
    return found


def parse_listing(text: str) -> list[dict]:
    """The rows of the listing's table (obs-components: `component kind installed newest
    repository`, two spaces or more between columns, `(update)` after an update's repository).
    Raises ValueError where the output holds no such table."""
    rows = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines() if line.strip()]
    if not rows or tuple(cell.lower() for cell in rows[0][:5]) != COMPONENTS_HEADER:
        raise ValueError("its output holds no table headed " + "  ".join(COMPONENTS_HEADER))
    offers = []
    for row in rows[1:]:
        if len(row) < 5:
            raise ValueError(f"a row has {len(row)} columns, not 5: {'  '.join(row)}")
        name, kind, installed, newest = row[:4]
        offers.append({"name": name, "kind": kind, "installed": installed, "newest": newest})
    return offers


def list_components(root: Path, command: list[str]) -> dict:
    """Run the project's component listing in its checkout, read-only (the command with no
    subcommand lists, never installs), within COMPONENTS_TIMEOUT: its rows, or its error."""
    try:
        result = process_door.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL, timeout=COMPONENTS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"error": f"{' '.join(command)} took longer than {COMPONENTS_TIMEOUT} s"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"error": f"{' '.join(command)} did not start: {error}"}
    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip()).splitlines()
        return {"error": f"{' '.join(command)} failed with exit code {result.returncode}"
                         + (f": {tail[-1]}" if tail else "")}
    try:
        return {"offers": parse_listing(result.stdout)}
    except ValueError as error:
        return {"error": f"{' '.join(command)}: {error}"}


# The computing: pure, on what was read


@dataclass(frozen=True)
class State:
    item: Item
    latest: Version | None = None  # highest version anywhere
    due: Version | None = None  # highest version the range admits, above the one in use
    outside: Version | None = None  # newest version above the range (a newer major for ^)
    error: str = ""  # the check of this item failed: where and the remedy
    unchecked: bool = False  # no check of this item yet


def assess(item: Item, remotes: dict[str, dict] | None) -> State:
    if item.url is None:
        return State(item)
    entry = (remotes or {}).get(item.url)
    if entry is None:
        return State(item, unchecked=True)
    if "error" in entry:
        return State(item, error=f"{item.name}: {entry['error']}")
    versions = sorted(tuple(v) for v in entry.get("versions", []))
    latest = versions[-1] if versions else None
    bounds = item.bounds()
    if bounds is None or item.kind == "commit":
        return State(item, latest)
    admitted = [v for v in versions if se_modules.matches(v, bounds)]
    due = max(admitted) if admitted and (item.version is None or max(admitted) > item.version) else None
    above = [v for v in versions if v >= bounds[1]]
    return State(item, latest, due, max(above) if above else None)


@dataclass(frozen=True)
class Report:
    local: Local
    states: list[State]
    checked_at: float | None
    running: bool
    now: float
    work: dict | None = None  # the cached work_check
    root: Path | None = None  # the project
    components: dict | None = None  # the cached component listing of the project, where it answers

    @property
    def errors(self) -> list[str]:
        return self.local.errors + [s.error for s in self.states if s.error]


def _v(version: Version | None) -> str:
    return se_modules.version_text(version) if version else "none"


def refresh_command(se_root: Path) -> str:
    return f"uv run python {se_root.as_posix()}/scripts/se_start.py refresh"


#: The template SE's start report is rendered from (templates/boot-report.md).
REPORT = "boot-report"
#: The documentation's page of each count, as se_plugin.py PAGES names them.
PAGE_OF = {"skills_page": "docs/skills.md", "rules_page": "docs/rules.md",
           "subagents_page": "docs/sub-agents.md"}


def page_link(docs_url: str, page: str) -> str:
    """The link to one page of the documentation: the page's chapter in obs's one HTML file, whose
    anchor is the page's path without `.md`, every run of other characters than letters and digits
    one dash (`docs/skills.md`: `#docs-skills`)."""
    anchor = re.sub(r"[^a-z0-9]+", "-", page.removesuffix(".md").lower()).strip("-")
    return f"{docs_url or '.'}#{anchor}"


def report_row(state: State) -> dict[str, str]:
    """One row of the report's table: the component, the version loaded and the newest release."""
    item = state.item
    newest = ("local" if item.kind == "local" else "unknown" if state.error or state.unchecked
              or state.latest is None else _v(state.latest))
    return {"name": item.name, "loaded": _v(item.version) if item.version else "none", "newest": newest}


def update_case(states: list[State]) -> str:
    """`due` where a newer release than one loaded is known, else `unknown` where a newest version
    is not read, else `current`; from versions alone."""
    if any(s.latest and s.item.kind != "local" and (s.item.version is None or s.latest > s.item.version)
           for s in states if not s.error):
        return "due"
    if any(s.error or s.unchecked or (s.latest is None and s.item.url) for s in states if s.item.kind != "local"):
        return "unknown"
    return "current"


def report_values(report: Report) -> dict[str, object]:
    """The fields of the start report: SE's version, the counts and their pages, the table and the
    update line's case."""
    local, c = report.local, report.local.counts
    states = [s for s in report.states if s.item.name != "se"]  # SE itself is its first row, "SE"
    return {"version": _v(local.se_version), "skills": str(c.skills), "rules": str(c.rules),
            "subagents": str(c.subagents), "docs": local.docs_url or ".",
            **{key: page_link(local.docs_url, page) for key, page in PAGE_OF.items()},
            "components": [report_row(state) for state in states], "update": update_case(states)}


def greeting(report: Report, se_root: Path) -> list[str]:
    """SE's start report, rendered from its template (templates/boot-report.md) and nothing else:
    what the session alone acts on is `session_lines`."""
    return _load("interfaces").write(REPORT, report_values(report)).split("\n")


def session_lines(report: Report, se_root: Path) -> list[str]:
    """What the start found for the session, never shown to the person in the report: a stale plugin,
    a check that failed, the project's components listing, missing skills, the work that is due."""
    return (stale_plugin_lines(se_root, report.root) + _check_lines(report, se_root)
            + component_lines(report, se_root) + skill_lines(report.local) + work_lines(report, se_root))


def _plugin_name(root: Path) -> str | None:
    try:
        data = json.loads((root / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def stale_plugin_lines(se_root: Path, root: Path | None) -> list[str]:
    """One line where the project is a checkout of the SE that runs (its plugin manifest names the
    same plugin) at a newer version: the session runs an older SE than the checkout it works on,
    as a cloud container restored from a cached snapshot does (README "Cloud sessions")."""
    if root is None or root.resolve() == se_root.resolve():
        return []
    name = _plugin_name(se_root)
    if name is None or _plugin_name(root) != name:
        return []
    running = se_modules.parse_version(_project(se_root).get("version"))
    checkout = se_modules.parse_version(_project(root).get("version"))
    if running is None or checkout is None or running >= checkout:
        return []
    return [f"SE {_v(running)} runs, older than this checkout's SE {_v(checkout)}: in the cloud, a "
            "container restored from a cached snapshot, which the environment rebuilds only when "
            "its setup script changes (README \"Cloud sessions\")"]


def skill_lines(local: Local) -> list[str]:
    """One line naming each listed skill the session lacks, with the roles that rely on it and the
    command that installs its plugin; in the cloud, that the environment provides plugins."""
    if local.skills_error:
        return [f"Skills check not done: {local.skills_error}"]
    if not local.lacking:
        return []
    named = "; ".join(f"{skill.name} ({', '.join(roles)})" for skill, roles in local.lacking)
    if os.environ.get(CLOUD_ENV, "").lower() == "true":
        return [f"Missing for SE's agents: {named}. This cloud session lacks them; the cloud "
                f"environment provides plugins ({CLOUD_PLUGINS})"]
    installs = list(dict.fromkeys(skill.install for skill, _ in local.lacking))
    return [f"Missing for SE's agents: {named}. Install: {' && '.join(installs)}"]


def component_lines(report: Report, se_root: Path) -> list[str]:
    """From the cached component listing: one line per component offered and not installed and
    per installed one with a newer release, with installed and newest version and the command
    that installs or updates it; SE never runs those. A setting SE cannot read, or a listing
    that failed or took too long, is one warning line. Nothing where the project sets none."""
    command, problem = components_command(report.root)
    if problem:
        return [f"Component check not done: {problem}"]
    if not command:
        return []
    found = report.components
    if found is None:
        if any(s.unchecked for s in report.states):
            return []  # the update check's line already says it runs
        reason = "running in the background" if report.running else "not run yet"
        return [f"Component check not done: {reason}; the next start shows its result"]
    if "error" in found:
        return [f"Component check not done: {found['error']}; "
                f"{CHECK_REMEDY.format(se=se_root.as_posix())}"]
    run = " ".join(command)
    lines = []
    for offer in found.get("offers") or []:
        name, kind = offer.get("name"), offer.get("kind")
        installed, newest = offer.get("installed"), offer.get("newest")
        have, latest = se_modules.parse_version(installed), se_modules.parse_version(newest)
        if latest is None:
            continue  # installed, and no source offers it any more
        if installed == "not installed":
            lines.append(f"Component {name} ({kind}): not installed, newest {newest}; "
                         f"install it: {run} install {name}")
        elif have is not None and latest > have:
            lines.append(f"Component {name} ({kind}): {installed} -> {newest}; "
                         f"update it: {run} update {name}")
    return lines


def work_lines(report: Report, se_root: Path) -> list[str]:
    """From the cached work check: one line for a retro that is due or open, one for an overhaul
    that is due or open and one for the fleet's findings, each with the command to run; a part
    whose read failed is named with the remedy.
    Nothing where no work check ran (no gh)."""
    work = report.work or {}
    se = se_root.as_posix()
    lines = []
    for kind, run in (("retro", f"uv run python {se}/scripts/retro.py collect <retro issue> "
                                "--out <draft>"),
                      ("overhaul", f"uv run python {se}/scripts/overhaul.py read <overhaul issue> "
                                   "--out <draft>")):
        part = work.get(kind) or {}
        name = kind.capitalize()
        live = ", live from kern" if part.get("from") == "kern" else ""
        if "error" in part:
            lines.append(f"{name} check not done: {part['error']}; {CHECK_REMEDY.format(se=se)}")
        elif part.get("open"):
            runs = ", ".join(f"#{number}" for number in part["open"])
            lines.append(f"{name} open: {runs}{live}; SE files no new issue until the person has "
                         f"decided its findings in an SE session; a retro agent runs it in its "
                         f"own session: {run}")
        elif part.get("due") is True:
            lines.append(f"{name} due: {part.get('reason')}{live}; the next issue SE files "
                         f"(work_tickets.py file) files it first, and a retro agent runs it in "
                         f"its own session: {run}")
    fleet = work.get("fleet") or {}
    findings = fleet.get("findings") or []
    if "error" in fleet:
        lines.append(f"Fleet check not done: {fleet['error']}; {CHECK_REMEDY.format(se=se)}")
    elif findings:
        kinds: dict[str, list[str]] = {}
        for finding in findings:
            kinds.setdefault(str(finding.get("kind")), []).append(f"#{finding.get('issue')}")
        where = f" --worktree {report.root.as_posix()}" if report.root else ""
        live = (f", live from kern over {_plural(fleet.get('issues'), 'issue')} read"
                if fleet.get("from") == "kern" else "")
        lines.append(f"Fleet: {_plural(len(findings), 'finding')} ("
                     + "; ".join(f"{kind} {', '.join(issues)}" for kind, issues in kinds.items())
                     + f"){live}; see each with its remedy: uv run python {se}/scripts/work_tickets.py "
                     f"fleet-check{where}")
    return lines


def upgrade_sections(in_use: int, newest: int) -> str:
    """The sections of SE's upgrade guide (scripts/upgrade_guide.py owns its shape) that lead from
    major `in_use` to major `newest`, each headed `SE <major>`."""
    guide, first = upgrade_guide.GUIDE.as_posix(), in_use + 1
    if first >= newest:
        return f"then follow SE's {guide}, section \"SE {newest}\""
    return f"then follow SE's {guide}, sections \"SE {first}\" to \"SE {newest}\", in order"


def take_outside(state: State, root: Path | None, se_root: Path) -> str:
    """The remedy for a version outside the range: the pin to change and where, and the command
    that moves to it; for SE, installed or pinned as the component `se`, also the sections of the
    upgrade guide between its major and the newer one."""
    item, outside = state.item, state.outside
    if item.kind == "se":
        return (f"to take it, install SE {_v(outside)} again as README \"Install\" says, "
                + upgrade_sections(item.version[0], outside[0]))
    where = (root / se_modules.MANIFEST).as_posix() if root else se_modules.MANIFEST
    remedy = (f"to take it, set version = \"^{outside[0]}.{outside[1]}\" in [components.{item.name}] of {where}, "
              f"then run: uv run python {se_root.as_posix()}/scripts/se_modules.py update {item.name}")
    bounds = item.bounds() if item.name == "se" else None
    if bounds is None:
        return remedy
    return f"{remedy}, {upgrade_sections((item.version or bounds[0])[0], outside[0])}"


def _range(item: Item) -> str:
    return item.range if item.kind == "range" else f"SE's major {item.version[0]}"


def _check_lines(report: Report, se_root: Path) -> list[str]:
    lines = [f"Update check not done: {error}; {CHECK_REMEDY.format(se=se_root.as_posix())}"
             for error in report.errors]
    if any(s.unchecked for s in report.states):
        reason = "running in the background" if report.running else "not run yet"
        lines.append(f"Update check not done: {reason}; the next start shows its result")
    return lines


def full(report: Report, se_root: Path) -> list[str]:
    """Status: the greeting's first line, then every item with its version in use, the latest
    version and whether an update is due."""
    lines = greeting(report, se_root)[:1]
    if report.checked_at is not None:
        lines.append(f"Update check: {int(report.now - report.checked_at) // 60} min ago")
    for state in report.states:
        item = state.item
        use = _v(item.version) + (f" ({item.note})" if item.note else "")
        if item.kind == "local":
            lines.append(f"{item.name}: in use {use}; local, refresh never touches it")
            continue
        if item.url is None:
            lines.append(f"{item.name}: in use {use}; not checked")
            continue
        if state.error or state.unchecked:
            lines.append(f"{item.name}: in use {use}; latest unknown")
            continue
        verdict = (f"update due to {_v(state.due)}" if state.due else
                   "pinned by commit, refresh leaves it (se_modules.py update moves it)"
                   if item.kind == "commit" else "up to date")
        if state.outside:
            verdict += (f"; {_v(state.outside)} is outside {_range(item)}, never applied by refresh; "
                        f"{take_outside(state, report.root, se_root)}")
        lines.append(f"{item.name}: in use {use}; latest {_v(state.latest)}; {verdict}")
    if any(s.due for s in report.states):
        lines.append(f"Refresh: {refresh_command(se_root)}")
    return (lines + _check_lines(report, se_root) + component_lines(report, se_root)
            + skill_lines(report.local) + work_lines(report, se_root))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


# Commands


def kern_status(binary: Path, root: Path) -> dict | None:
    """`kern status --json` of the core in the checkout at root: its state and health, or None
    where the binary does not answer."""
    try:
        result = subprocess.run([str(binary), "status", "--root", str(root), "--json"],
                                capture_output=True, text=True, timeout=2)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


@dataclass
class Kern:
    """What bootstrap.sh said of kern at the session's start (README "Kern"): the binary it started,
    why the core is still starting, or why it failed."""

    binary: Path | None = None
    starting: str = ""
    failed: str = ""


def kern_line(se_root: Path, root: Path, kern: Kern, ask: Callable[[Path, Path], dict | None]) -> list[str]:
    """The greeting's line on kern: running, starting, or failed with the cause; none where
    bootstrap.sh said nothing of kern."""
    if not (kern.binary or kern.starting or kern.failed):
        return []
    try:
        binary = se_modules.app_binary(se_modules.app_root(se_root, root))
        name = f"{binary.name} {binary.version}"
    except ModuleError:
        name = "kern ?"
    if kern.failed:
        return [f"{name}: failed: {kern.failed}"]
    if kern.starting or kern.binary is None:
        return [f"{name}: starting: {kern.starting}"]
    answer = ask(kern.binary, root)
    state = (answer or {}).get("state")
    if state == "running":
        return [f"{name}: running"]
    if state == "starting":
        return [f"{name}: starting"]
    log = root / ".se" / ".runtime" / "core.log"
    died = (answer or {}).get("died")
    if died:
        # The core ended at its start: the first lines it said, which kern's status names (kern's
        # host.ReadDied); the next hook tells the session the same once.
        return [f"{name}: failed: the core ended at its start; it said:",
                *(f"  {line}" for line in str(died).splitlines()), f"  (all of it in {log})"]
    cause = "its status does not answer" if answer is None else "not running after its start"
    return [f"{name}: failed: {cause}; see {log}"]


# Under Copilot SE works without its core: every step runs through SE's scripts and gh, and the
# greeting says so under a kern line that failed (the work model's "Host procedure under Copilot").
WITHOUT_KERN = "SE runs without kern: every step goes through SE's scripts and gh."


def without_kern(kern: list[str], host: str, none: bool = False) -> list[str]:
    """The line that says SE runs without kern: under Copilot, after a kern line that failed or
    where bootstrap.sh started no core, the project being inside no git checkout; none elsewhere, so
    Claude Code's greeting stays as it is."""
    failed = bool(kern) and ": failed: " in kern[0]
    return [WITHOUT_KERN] if host == "copilot" and (failed or none) else []


def detached_options(os_name: str) -> dict:
    """The keyword arguments of a detached start on os_name. On Windows a new process group with a
    console that has no window (CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW), so the git and gh it
    runs share that hidden console instead of each opening one, as DETACHED_PROCESS would make
    them; written as numbers, as subprocess names them only on Windows. Elsewhere a new session."""
    if os_name == "nt":
        return {"creationflags": 0x00000200 | 0x08000000}
    return {"start_new_session": True}


def _spawn_detached(argv: list[str]) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **detached_options(os.name))


def _claude(args: list[str]) -> subprocess.CompletedProcess:
    """Claude Code's command line; a machine without it answers as a failed command."""
    try:
        return subprocess.run(["claude", *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(["claude", *args], 127, "", str(error))


@dataclass(frozen=True)
class World:
    """The outside world status, check and refresh reach: the clock, the remotes, the work on
    GitHub, the start of a background check, Claude Code's command line. Tests replace each."""

    clock: Callable[[], float] = time.time
    remote: Callable[[str], list[Version]] = git_tags
    work: Callable[[Path | None], dict | None] = work_check
    components: Callable[[Path, list[str]], dict] = list_components
    spawn: Callable[[list[str]], None] = _spawn_detached
    claude: Callable[[list[str]], subprocess.CompletedProcess] = _claude
    kern: Callable[[Path, Path], dict | None] = kern_status
    live: Callable[[Path | None], dict | None] = kern_names.live_work


def status(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
           world: World, offline: bool = False) -> Report:
    """Answer from disk and the cache; start the update check in the background when stale."""
    local = read_local(se_root, root, local_config)
    now = world.clock()
    cache = Cache.read(cache_path)
    urls = {item.url for item in local.items if item.url}
    running = cache.running(now)
    key = listing_key(root)
    if not offline and not cache.fresh(urls, now, key) and not running:
        cache.started_at = now
        cache.write(cache_path)
        argv = [sys.executable, str(se_root / "scripts" / "se_start.py"), "--cache", str(cache_path)]
        argv += (["--root", str(root)] if root else []) + (["--local", str(local_config)] if local_config else [])
        world.spawn(argv + ["check"])
        running = True
    states = [assess(item, cache.remotes if cache.checked_at is not None else None) for item in local.items]
    return Report(local, states, cache.checked_at, running, now, live_or_cached(world, root, cache.work), root,
                  components_of(cache, key))


def live_or_cached(world: World, root: Path | None, cached: dict | None) -> dict | None:
    """What is due in the work: each part kern's core holds live (kern_names.live_work) over
    the cached work check's."""
    live = world.live(root)
    return {**(cached or {}), **live} if live else cached


def check(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
          world: World, work: bool = True) -> Report:
    """Read every remote once, in parallel, and, with `work`, what is due in the work
    (work_check) and the project's component listing (list_components), where it sets one; keep
    them in the cache. Without `work` the cached work and listing stay."""
    local = read_local(se_root, root, local_config)
    remotes = run_check({item.url for item in local.items if item.url}, world.remote)
    key = listing_key(root)
    if work:
        found = world.work(root)
        listing = {**key, **world.components(root, key["command"])} if key else None
    else:
        cached = Cache.read(cache_path)
        found, listing = cached.work, cached.components
    now = world.clock()
    Cache(now, None, remotes, found, listing).write(cache_path)
    return Report(local, [assess(item, remotes) for item in local.items], now, False, now, found, root,
                  components_of(Cache(components=listing), key))


# Refresh: new location first, check that it starts, then switch


class RefreshError(Exception):
    """One item's refresh failed; what was in use stays in use."""


def _git(cwd: Path, *args: str) -> str:
    return se_modules.git(cwd, *args)


def _trial(repo: Path, sha: str, verify: Callable[[Path], None]) -> None:
    """Check out `sha` into a new worktree of `repo`, verify it there, and remove it again."""
    with tempfile.TemporaryDirectory(prefix="se-refresh-") as parent:
        trial = Path(parent) / "trial"
        _git(repo, "worktree", "add", "--quiet", "--detach", str(trial), sha)
        try:
            verify(trial)
        finally:
            se_modules.git_ok(repo, "worktree", "remove", "--force", str(trial))
            se_modules.git_ok(repo, "worktree", "prune")


def _expect_version(path: Path, version: Version, what: str) -> None:
    try:
        found = se_modules.checkout_version(path)
    except ModuleError as error:
        raise RefreshError(f"{what}: {error}") from error
    if found != version:
        raise RefreshError(f"{what}: v{_v(version)} sets version {_v(found)} in its se.toml")


def _starts(se: Path, root: Path | None, version: Version) -> None:
    """SE at `se` starts: its `status` runs there and greets with `version`."""
    with tempfile.TemporaryDirectory(prefix="se-start-") as scratch:
        argv = [sys.executable, str(se / "scripts" / "se_start.py"), "--cache", str(Path(scratch) / "cache.json")]
        argv += (["--root", str(root)] if root else []) + ["status", "--offline"]
        result = process_door.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or f"SE {_v(version)} started" not in result.stdout:
        raise RefreshError(f"SE v{_v(version)} does not start: {(result.stderr or result.stdout).strip()[-300:]}")


def _fetch_tag(repo: Path, tag: str, timeout: float | None) -> None:
    """One fetch of the tag from origin; in a shallow clone it brings only the commits it lacks."""
    feedback.reading("the remote", ["git", "fetch", "origin", f"refs/tags/{tag}"])
    try:
        result = git_door.run("fetch", "--quiet", "origin", f"refs/tags/{tag}:refs/tags/{tag}", root=repo,
                              no_prompt=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RefreshError(f"fetching {tag} took over {timeout:g} s") from error
    if result.returncode != 0:
        raise RefreshError(f"fetching {tag} failed: {_tail(result)}")


def refresh_se(se_root: Path, root: Path | None, version: Version, timeout: float | None = None) -> str:
    """Bring the se checkout to tag v<version>, after the new version started in a trial worktree."""
    tag = f"v{_v(version)}"
    if se_modules.is_dirty(se_root):
        raise RefreshError(f"the se checkout {se_root} has local changes; commit or discard them")
    _fetch_tag(se_root, tag, timeout)
    sha = _git(se_root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")

    def starts(trial: Path) -> None:
        _expect_version(trial, version, f"SE {tag}")
        _starts(trial, root, version)

    _trial(se_root, sha, starts)
    old = _git(se_root, "rev-parse", "--short", "HEAD")
    branch = _git(se_root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        _git(se_root, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", sha)
    elif not se_modules.git_ok(se_root, "merge", "--quiet", "--ff-only", sha):
        raise RefreshError(f"the se checkout {se_root} has commits on {branch} that {tag} lacks; "
                           "it is a development checkout, so refresh leaves it")
    return f"SE: {old} -> {tag}"


def plugin_registry() -> Path:
    """Claude Code's record of the installed plugins, which `claude plugin update` rewrites."""
    return _claude_dir() / "plugins" / "installed_plugins.json"


def _installed(world: World) -> list[dict]:
    result = world.claude(["plugin", "list", "--json"])
    if result.returncode != 0:
        return []
    try:
        entries = json.loads(result.stdout)
    except ValueError:
        return []
    return [e for e in entries if isinstance(e, dict) and isinstance(e.get("installPath"), str)] \
        if isinstance(entries, list) else []


def installed_plugin(se_root: Path, world: World) -> dict | None:
    """The Claude Code plugin installed at `se_root`, as `claude plugin list --json` names it."""
    here = se_root.resolve()
    return next((e for e in _installed(world) if Path(e["installPath"]).resolve() == here), None)


def _tail(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout).strip()[-300:] or f"exit code {result.returncode}"


def refresh_plugin(se_root: Path, root: Path | None, entry: dict, old: Version, due: Version,
                   world: World, same_major: bool = True) -> str:
    """Update the installed plugin through Claude Code, check that the new install starts, and put
    the old install back in Claude Code's record when it does not; with `same_major`, an install
    outside `old`'s major counts as failed too (the boot passes False: SE moves to its newest)."""
    plugin_id = entry["id"]
    registry = plugin_registry()
    try:
        saved = registry.read_bytes()
    except OSError:
        saved = None
    scope = ["--scope", entry["scope"]] if entry.get("scope") in ("user", "project", "local", "managed") else []
    result = world.claude(["plugin", "update", plugin_id, *scope, "--json"])
    if result.returncode != 0:
        raise RefreshError(f"claude plugin update {plugin_id} failed: {_tail(result)}")
    new = next((e for e in _installed(world) if e.get("id") == plugin_id and e.get("scope") == entry.get("scope")),
               None)
    new_root = Path(new["installPath"]) if new else None
    try:
        if new_root is None:
            raise RefreshError(f"claude plugin list no longer names {plugin_id}")
        found = se_modules.checkout_version(new_root) if (new_root / se_modules.MANIFEST).is_file() else None
        if found is None or found < due or (same_major and found[0] != old[0]):
            raise RefreshError(f"claude plugin update {plugin_id} installed version {_v(found)}, "
                               f"not v{_v(due)} or newer" + (f" within major {old[0]}" if same_major else ""))
        _starts(new_root, root, found)
    except (RefreshError, ModuleError) as error:
        if saved is None:
            raise RefreshError(f"{error}; the old install could not be put back: Claude Code's record "
                               f"{registry} was not readable before the update") from error
        if new_root is not None and new_root.resolve() == se_root.resolve():
            raise
        if not (se_root / se_modules.MANIFEST).is_file():
            raise RefreshError(f"{error}; the old install at {se_root} is gone, so it cannot be put back: "
                               f"reinstall with claude plugin install {plugin_id}") from error
        registry.write_bytes(saved)
        raise RefreshError(f"{error}; the old install at {se_root} is back in {registry}") from error
    return f"SE: {_v(old)} -> {_v(found)} (claude plugin update {plugin_id}; restart Claude Code to load it)"


def refresh_copy(se_root: Path, item: Item, due: Version) -> str:
    """A copy that is neither a git checkout nor a Claude Code plugin: a Copilot copy, which only
    VS Code updates."""
    return (f"SE: {_v(item.version)} -> {_v(due)} is due, but {se_root} is a copy that is neither a git "
            "checkout nor a Claude Code plugin (a GitHub Copilot copy), which only VS Code can update "
            "and it has no command line for it; run in VS Code: Chat: Install Plugin from Source "
            f"with {item.url}")


def refresh_module(root: Path, local_config: Path | None, name: str, version: Version) -> str:
    """Lock a range module at tag v<version> after its checkout passed in a trial worktree."""
    module = next(m for m in se_modules.load_manifest(root) if m.name == name)
    clone = root / se_modules.MODULES_DIR / name
    source = se_modules.Source(module, "pinned", clone, _found_at(clone) or "")
    if se_modules.is_populated(clone) and se_modules.is_dirty(clone):
        raise RefreshError(f"{clone} has local changes; commit them in a local path or discard them")
    se_modules.ensure_clone(source)
    se_modules.fetch(clone)
    tag = f"v{_v(version)}"
    sha = _git(clone, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")

    def verify(trial: Path) -> None:
        _expect_version(trial, version, f"module {name} {tag}")
        if module.path and not (trial / module.path).is_dir():
            raise RefreshError(f"module {name} {tag}: path {module.path} does not exist there")

    _trial(clone, sha, verify)
    old = se_modules.read_lock(root).get(name, ("none", ""))[0]
    previous = _git(clone, "rev-parse", "HEAD") if se_modules.is_populated(clone) else None
    _git(clone, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", sha)
    try:
        se_modules.write_lock(root, {**se_modules.read_lock(root), name: (_v(version), sha)})
    except (OSError, ModuleError):
        if previous:
            se_modules.git_ok(clone, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", previous)
        raise
    return f"{name}: {old} -> {_v(version)} (se.lock; commit it)"


def refresh(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
            world: World) -> tuple[list[str], bool]:
    """Check now, then move every item that is due; one item failing leaves the others moving."""
    report = check(se_root, root, local_config, cache_path, world, work=False)
    lines, failed = [], False
    for state in report.states:
        item = state.item
        if state.outside:
            lines.append(f"{item.name}: {_v(state.outside)} is outside {_range(item)}; not applied; "
                         f"{take_outside(state, root, se_root)}")
        if not state.due:
            continue
        try:
            if item.kind == "se" and (se_root / ".git").exists():
                lines.append(refresh_se(se_root, root, state.due))
            elif item.kind == "se" and (entry := installed_plugin(se_root, world)):
                lines.append(refresh_plugin(se_root, root, entry, item.version, state.due, world))
            elif item.kind == "se":
                lines.append(refresh_copy(se_root, item, state.due))
            else:
                lines.append(refresh_module(root, local_config, item.name, state.due))
        except (RefreshError, ModuleError, OSError, subprocess.SubprocessError) as error:
            failed = True
            lines.append(f"{item.name}: not refreshed, {_v(item.version)} stays in use: {error}")
    for state in report.states:
        if state.item.kind == "local":
            lines.append(f"{state.item.name}: local, not touched")
    if report.errors:
        failed = True
        lines += [f"not checked: {error}" for error in report.errors]
    if not any(s.due for s in report.states) and not report.errors:
        lines.insert(0, "Everything is up to date; nothing moved.")
    if failed:
        lines.append(f"Try again with: {refresh_command(se_root)}")
    else:
        check(se_root, root, local_config, cache_path, world, work=False)
    return lines, failed


def _development(se_root: Path) -> bool:
    """A checkout someone works in: local changes, a branch other than main, or commits that no
    remote branch and no tag holds. A clone a refresh moved to a tag is none of these."""
    if se_modules.is_dirty(se_root):
        return True
    if _git(se_root, "rev-parse", "--abbrev-ref", "HEAD") not in ("HEAD", se_modules.TRACKED_BRANCH):
        return True
    own = git_door.run("rev-list", "--count", "HEAD", "--not", "--remotes", "--tags", root=se_root)
    return own.returncode != 0 or own.stdout.strip() != "0"


HOOKS = ".githooks"  # se's git hooks, beside the se-script they run (AGENTS.md "Public safety")


def stopped_hooks(names: Iterable[str]) -> list[str]:
    """The hooks a checkout's own hooks folder holds that stop running once `core.hooksPath` names
    another folder: each file name there that is no `.sample`, sorted."""
    return sorted(name for name in names if not name.endswith(".sample"))


def stopped_hooks_line(checkout: str, folder: str, names: list[str]) -> str:
    """The one line that says a checkout's own hooks no longer run, and the command that keeps them."""
    return (f"SE: the hooks in {folder} no longer run: {', '.join(names)}, as core.hooksPath now names se's; "
            f"to keep them, run: git -C {checkout} config core.hooksPath {folder} "
            f"(se's public check then does not run on this checkout's commits)")


def own_hooks(root: Path, hooks: Path | None = None) -> tuple[Path, list[str]]:
    """The hooks folder git runs for the checkout now (its `core.hooksPath`, else `git rev-parse
    --git-path hooks`) and the hooks in it that stop running once `core.hooksPath` names `hooks`;
    no folder, one with only `.sample` files, or `hooks` itself, stops none."""
    found = git_door.run("config", "--get", "core.hooksPath", root=root)
    if found.returncode != 0 or not found.stdout.strip():  # unset: git's own folder
        found = git_door.run("rev-parse", "--git-path", "hooks", root=root)
    if found.returncode != 0 or not found.stdout.strip():
        return root, []
    folder = Path(found.stdout.strip())
    folder = folder if folder.is_absolute() else root / folder
    if not folder.is_dir():
        return folder, []
    if hooks is not None and (hooks if hooks.is_absolute() else root / hooks).resolve() == folder.resolve():
        return folder, []
    return folder, stopped_hooks(entry.name for entry in folder.iterdir() if entry.is_file())


def start_hooks(se_root: Path, root: Path | None, local_config: Path | None) -> str:
    """At the session's start: point a project checkout whose `core.hooksPath` is unset at se's
    hooks, as scripts/setup.sh does, so a fresh clone's first commit already runs the public check.
    A checkout that has one keeps it, whatever it names. The hooks are the checkout's own where it
    carries se's (se's own checkout, `.githooks`), else those of the se module it pins, else this
    SE's. The line to show: empty where nothing changed, else the checkout's own hooks that stop
    running (`stopped_hooks`) with the command that keeps them; it fails open."""
    if root is None or not (root / se_modules.MANIFEST).is_file():
        return ""
    current = git_door.run("config", "--get", "core.hooksPath", root=root)
    if current.returncode == 0 and current.stdout.strip():
        return ""
    if git_door.run("rev-parse", "--show-toplevel", root=root).returncode != 0:
        return ""  # no work tree: nothing commits here
    if (root / HOOKS / "se-script").is_file():
        hooks = HOOKS
    else:
        hooks = (se_root / HOOKS).as_posix()
        try:
            local = se_modules.load_local(local_config or se_modules.default_local_config())
            pinned = [m for m in se_modules.load_manifest(root) if m.name == "se"]
            if pinned and (found := se_modules.resolve(root, pinned[0], local).dir / HOOKS / "se-script").is_file():
                hooks = found.parent.as_posix()
        except ModuleError:
            pass  # the start goes on with this SE's hooks
    folder, stopped = own_hooks(root, Path(hooks))
    done = git_door.run("config", "core.hooksPath", hooks, root=root)
    if done.returncode != 0:
        return (f"SE: setting core.hooksPath of {root.as_posix()} failed; run: sh "
                f"{(se_root / 'scripts' / 'setup.sh').as_posix()} {root.as_posix()}")
    return stopped_hooks_line(root.as_posix(), folder.as_posix(), stopped) if stopped else ""


def start_refresh(se_root: Path, root: Path | None, local_config: Path | None,
                  remote: Callable[[str], list[Version]] | None = None) -> tuple[str, bool]:
    """At the session's start: move an installed SE that is a git checkout (the cloud's setup-script
    clone) to the latest release of its major, in one read of its tags and one fetch, so this start
    runs the moved tree. The line to show, and whether it moved; it fails open, every failure a
    line saying the session starts with the SE it has. Leaves alone what the start cannot move in
    place: a development checkout, the session's own working tree, a local path, a plugin Claude
    Code installed (refresh updates it; it loads at the next start)."""
    version = se_modules.parse_version(_project(se_root).get("version"))
    stays = f"this session starts with SE {_v(version)}"
    try:
        local = se_modules.load_local(local_config or se_modules.default_local_config())
        item = _se_item(se_root, version, local)
        if (item.kind != "se" or item.url is None or version is None or not (se_root / ".git").exists()
                or (root is not None and root.resolve() == se_root.resolve()) or _development(se_root)):
            return "", False
        versions = (remote or (lambda url: git_tags(url, timeout=START_TIMEOUT)))(item.url)
    except (RemoteError, ModuleError, OSError, subprocess.SubprocessError) as error:
        return f"SE: no refresh at start, {stays}: {error}", False
    bounds = item.bounds()
    due = max((v for v in versions if se_modules.matches(v, bounds) and v > version), default=None)
    if due is None:
        return "", False
    try:
        refresh_se(se_root, root, due, timeout=START_TIMEOUT)
    except (RefreshError, ModuleError, OSError, subprocess.SubprocessError) as error:
        return f"SE: no refresh at start to {_v(due)}, {stays}: {error}", False
    return f"SE: {_v(version)} -> {_v(due)}, refreshed at this start ({se_root.as_posix()})", True


# The boot (docs/boot.md "The boot"): the checkout current, then every dependency with its pinned, locked and
# newest version, then, with --upgrade, SE and every lock moved to the newest release its pin
# admits; one report. It decides from versions alone.

BOOT_FETCH_TIMEOUT = 60  # seconds the boot's fetch of origin may take


def boot_command(se_root: Path, upgrade: bool = False) -> str:
    return f"uv run python {se_root.as_posix()}/scripts/se_start.py boot" + (" --upgrade" if upgrade else "")


def _ref(root: Path, name: str) -> str | None:
    found = git_door.run("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}", root=root)
    return found.stdout.strip() if found.returncode == 0 and found.stdout.strip() else None


def _contains(root: Path, ancestor: str, descendant: str) -> bool:
    return git_door.run("merge-base", "--is-ancestor", ancestor, descendant, root=root).returncode == 0


def current_checkout(root: Path, integration: str, timeout: float | None = BOOT_FETCH_TIMEOUT
                     ) -> tuple[str, bool]:
    """The boot's first step: fetch origin and bring the checkout to the newest tip of its branch,
    `origin/<branch>` and, on a branch other than the integration branch, `origin/<integration>`
    too, each by a fast-forward where it can, else by a merge on a clean tree. A detached HEAD that
    the integration branch's tip contains moves to that tip. The line to show, and whether the boot
    stops: a fetch that fails, a fast-forward or merge git refuses, a merge needed over local
    changes. It never discards local work: a merge that conflicts is aborted on its clean tree."""
    where = root.as_posix()
    if git_door.run("rev-parse", "--show-toplevel", root=root).returncode != 0:
        return f"Checkout: {where} is no git checkout; nothing to bring current", False
    if git_door.run("remote", "get-url", "origin", root=root).returncode != 0:
        return f"Checkout: {where} has no origin; nothing to fetch", False
    try:
        fetched = git_door.run("fetch", "--quiet", "origin", root=root, no_prompt=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"Checkout: fetching origin took over {timeout:g} s; the boot stops", True
    if fetched.returncode != 0:
        return f"Checkout: fetching origin failed, the boot stops: {_tail(fetched)}", True
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    before = _git(root, "rev-parse", "HEAD")
    tip = f"origin/{integration}"
    if branch == "HEAD":
        target = _ref(root, tip)
        if target is None or target == before or not _contains(root, before, target):
            return (f"Checkout: detached at {before[:7]}, which {tip} does not lead on from; "
                    "left as it is"), False
        moved = git_door.run("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", target,
                             root=root)
        if moved.returncode != 0:
            return f"Checkout: moving the detached HEAD to {tip} failed, the boot stops: {_tail(moved)}", True
        return f"Checkout: detached {before[:7]} -> {target[:7]} ({tip})", False
    targets = [ref for ref in [f"origin/{branch}", *([tip] if branch != integration else [])] if _ref(root, ref)]
    done: list[str] = []
    for ref in targets:
        head = _git(root, "rev-parse", "HEAD")
        if _contains(root, ref, head):
            continue
        if _contains(root, head, ref):
            merged = git_door.run("merge", "--quiet", "--ff-only", ref, root=root)
            if merged.returncode != 0:
                return (f"Checkout: {branch} cannot fast-forward to {ref}, the boot stops; "
                        f"nothing was discarded: {_tail(merged)}"), True
            done.append(f"fast-forward to {ref}")
            continue
        if se_modules.is_dirty(root):
            return (f"Checkout: {branch} needs a merge of {ref} and has local changes, the boot stops; "
                    "commit them, then boot again"), True
        merged = git_door.run("merge", "--quiet", "--no-edit", ref, root=root)
        if merged.returncode != 0:
            git_door.run("merge", "--abort", root=root)
            return (f"Checkout: merging {ref} into {branch} does not merge cleanly, the boot stops; the "
                    f"merge was aborted, nothing was discarded: {_tail(merged)}"), True
        done.append(f"merged {ref}")
    after = _git(root, "rev-parse", "HEAD")
    if not done:
        return f"Checkout: {branch} at {after[:7]}, current with {', '.join(targets) or 'no remote branch'}", False
    return f"Checkout: {branch} {before[:7]} -> {after[:7]} ({'; '.join(done)})", False


@dataclass(frozen=True)
class SEState:
    """SE itself as the boot sees it: the version installed, the newest release, the newest the
    project's pin of se admits (every release where it pins none), and why it does not move."""

    item: Item
    newest: Version | None = None
    due: Version | None = None  # the newest admitted release above the one installed
    pin: str | None = None  # the project's [components.se] version range
    stays: str = ""  # why the boot leaves SE as it is
    error: str = ""


def se_state(se_root: Path, root: Path | None, local, world: World) -> SEState:
    version = se_modules.parse_version(_project(se_root).get("version"))
    item = _se_item(se_root, version, local)
    if item.kind == "local":
        return SEState(item, stays=f"a local path ({se_root.as_posix()}), the boot never touches it")
    if item.url is None:
        return SEState(item, stays=item.note)
    pinned = None
    if root is not None and (root / se_modules.MANIFEST).is_file():
        pinned = next((m.version for m in se_modules.load_manifest(root)
                       if m.name == "se" and m.version and not m.go), None)
    try:
        versions = world.remote(item.url)
    except (RemoteError, OSError, subprocess.SubprocessError) as error:
        return SEState(item, pin=pinned, error=f"its releases could not be read: {error}")
    bounds = se_modules.version_bounds("se", pinned) if pinned else None
    fits = [v for v in versions if bounds is None or se_modules.matches(v, bounds)]
    newest, best = max(versions, default=None), max(fits, default=None)
    due = best if best and (version is None or best > version) else None
    stays = ""
    if due and (se_root / ".git").exists() and (
            (root is not None and root.resolve() == se_root.resolve()) or _development(se_root)):
        stays = "a development checkout, the boot leaves it"
    return SEState(item, newest, due, pinned, stays)


def se_line(state: SEState, moved: str = "") -> str:
    item = state.item
    head = f"SE: installed {_v(item.version)}"
    if state.pin:
        head += f", pinned {state.pin} by the project"
    if state.error:
        return f"{head}: {state.error}"
    if state.newest is None:
        return f"{head}: {state.stays or 'no release found'}"
    head += f", newest {_v(state.newest)}"
    verdict = (moved or (state.stays if state.due and state.stays else "")
               or (f"the upgrade takes {_v(state.due)}" if state.due else "current"))
    if state.pin and not se_modules.matches(state.newest, se_modules.version_bounds("se", state.pin)):
        verdict += (f"; {_v(state.newest)} lies beyond the pin, not taken; to take it, set version = "
                    f"\"^{state.newest[0]}.{state.newest[1]}\" in [components.se] of the project's "
                    f"{se_modules.MANIFEST}")
    return f"{head}: {verdict}"


def upgrade_se(se_root: Path, root: Path | None, state: SEState, world: World) -> tuple[str, bool]:
    """Move SE to `state.due`: a git checkout to its tag, a Claude Code plugin through Claude Code,
    a copy only VS Code updates named. The outcome, and whether it failed."""
    item = state.item
    try:
        if (se_root / ".git").exists():
            return refresh_se(se_root, root, state.due, timeout=BOOT_FETCH_TIMEOUT), False
        if entry := installed_plugin(se_root, world):
            return refresh_plugin(se_root, root, entry, item.version, state.due, world, same_major=False), False
        return refresh_copy(se_root, item, state.due), False
    except (RefreshError, ModuleError, OSError, subprocess.SubprocessError) as error:
        return f"not moved, {_v(item.version)} stays in use: {error}", True


def pin_move(pin, root: Path, se_root: Path) -> str:
    """What moving a pin to its component's newest release needs, from the pin's kind alone."""
    module, newest, se = pin.module, pin.newest, se_root.as_posix()
    holder = pin.path[-1]
    if len(pin.path) > 1:
        return f"{holder} moves its pin in its own {se_modules.MANIFEST} (a ticket for {holder}'s repository)"
    if module.go:
        return (f"set require {module.name} v{_v(newest)} in {(root / module.go).as_posix()}, then run: "
                f"uv run python {se}/scripts/se_modules.py sync {module.name}")
    if module.version:
        return (f"set version = \"^{newest[0]}.{newest[1]}\" in [components.{module.name}] of "
                f"{(root / se_modules.MANIFEST).as_posix()}, then run: {boot_command(se_root, True)}")
    return f"run: uv run python {se}/scripts/se_modules.py update {module.name} --to v{_v(newest)}"


def _takes(pin, locked: dict) -> bool:
    """Whether the upgrade moves this pin's lock: a range locked at another release than the newest
    it admits, below it or outside the pin."""
    module = pin.module
    if not module.version or module.go or pin.admitted is None:
        return False
    return se_modules.parse_version(locked.get(module.name, ("", ""))[0]) != pin.admitted


def pin_row(pin, locked: dict, moved: dict, root: Path, se_root: Path, local_paths: frozenset[str] = frozenset()
            ) -> str:
    """`<holder> pins <name> <pin>, locked <v>, newest <v>: <verdict>`, nested holders' paths after."""
    module = pin.module
    lock = locked.get(module.name, ("", ""))[0] or ("-" if not module.version else "none")
    path = f" ({se_modules._arrow(pin.path, module.name)})" if len(pin.path) > 1 else ""
    head = (f"  {pin.path[-1]} pins {module.name} {pin.pin_text()}, locked {lock}, "
            f"newest {_v(pin.newest) if pin.newest else 'none found'}{path}")
    if module.name in local_paths:
        return f"{head}: a local path, the boot never touches it"
    if pin.newest is None:
        return f"{head}: its releases could not be read: " + ("; ".join(pin.reasons) or "no remote offers it")
    if pin.base is None:
        return f"{head}: not judged, no release at the pin"
    if module.name in moved:
        verdict = f"moved {moved[module.name]}"
    elif _takes(pin, locked):
        verdict = f"the upgrade takes {_v(pin.admitted)}"
    else:
        verdict = "current"
    if pin.beyond:
        kind = "breaking release" if pin.breaking else "newer release"
        verdict += f"; {kind} {_v(pin.newest)} beyond the pin, not taken; to take it: {pin_move(pin, root, se_root)}"
    return f"{head}: {verdict}"


def boot(se_root: Path, root: Path | None, local_config: Path | None, world: World,
         upgrade: bool = False) -> tuple[list[str], bool]:
    """SE's boot, each step mechanical (docs/boot.md "The boot"): the checkout current (current_checkout),
    SE and every pin of the project's component tree, nested ones included, with its pinned,
    locked and newest version (se_modules.breaking); with `upgrade`, SE moved to the newest release
    the project's pin of se admits (every release where it pins none) and every range's lock to the
    newest release it admits (se_modules.place_tree, every name unlocked). A release beyond a pin
    is listed with what moving the pin needs and never taken. The report, once, and whether it
    failed: the checkout could not be brought current (the boot stops there), a listing or a move
    failed."""
    lines = [f"SE boot of {root.as_posix() if root else 'no project'}"
             + (", upgrading" if upgrade else ", checking")]
    if root is not None:
        try:
            integration = _load("work_tickets").integration_branch(root)
        except Exception as error:  # noqa: BLE001 - its own message names the setting
            return lines + [f"Checkout: the integration branch cannot be read, the boot stops: {error}"], True
        line, stopped = current_checkout(root, integration)
        lines.append(line)
        if stopped:
            return lines, True
    failed = False
    try:
        local = se_modules.load_local(local_config or se_modules.default_local_config())
    except ModuleError as error:
        return lines + [f"Machine-local configuration: {error}"], True
    se = se_state(se_root, root, local, world)
    failed |= bool(se.error)
    se_moved = ""
    if upgrade and se.due and not se.stays:
        se_moved, broke = upgrade_se(se_root, root, se, world)
        failed |= broke
    lines.append(se_line(se, se_moved))
    if root is None or not (root / se_modules.MANIFEST).is_file():
        return lines + ["Dependencies: the project has no se.toml"], failed
    try:
        found = se_modules.breaking(root, local)
    except ModuleError as error:
        return lines + [f"Dependencies: not listed: {error}"], True
    before = se_modules.read_lock(root)
    moved: dict[str, str] = {}
    if upgrade and any(_takes(pin, before) for pin in found.pins):
        try:
            se_modules.place_tree(root, local, unlock=frozenset(pin.module.name for pin in found.pins))
        except ModuleError as error:
            failed = True
            lines.append(f"Upgrade of the locks failed, {se_modules.LOCK} stays as it was: {error}")
        after = se_modules.read_lock(root)
        moved = {name: f"{before.get(name, ('none', ''))[0]} -> {version} ({se_modules.LOCK}; commit it)"
                 for name, (version, _) in after.items() if before.get(name, ("", ""))[0] != version}
    locked = se_modules.read_lock(root)
    local_paths = frozenset(pin.module.name for pin in found.pins
                            if se_modules.resolve(root, pin.module, local).kind == "local")
    lines.append(f"Dependencies ({_plural(len(found.pins), 'pin')}: pinned, locked, newest):")
    lines += [pin_row(pin, locked, moved, root, se_root, local_paths) for pin in found.pins]
    lines += [f"  {note}" for note in found.notes]
    failed |= any(pin.module.name not in local_paths for pin in found.unread)
    takes = sum(_takes(pin, locked) for pin in {pin.module.name: pin for pin in found.pins}.values())
    takes += bool(se.due and not se.stays and not upgrade)
    beyond = [pin for pin in found.pins if pin.beyond]
    if upgrade:
        lines.append(f"Moved: {_plural(len(moved) + bool(se_moved and not se_moved.startswith('not ')), 'item')}")
    elif takes:
        lines.append(f"Upgrade: {_plural(takes, 'item')} to take within the pins; run: {boot_command(se_root, True)}")
    else:
        lines.append("Upgrade: nothing to take within the pins")
    if beyond:
        lines.append(f"Left: {_plural(len(beyond), 'release')} beyond a pin, "
                     f"{sum(pin.breaking for pin in beyond)} of them breaking")
    return lines, failed


# The update (docs/boot.md "The update"): the one command the start report names, which takes every
# newer release, also across a breaking one, and hands over the upgrade guide's sections between.

# The person runs it as `/se:update`, SE's skill update (src/skills/update/SKILL.md), which runs
# `update` below and follows the sections it prints; the start report's template names it.


def set_range(root: Path, name: str, version: Version) -> str:
    """Set `[components.<name>] version` of the project's se.toml to `^<version>`; the old range."""
    path = root / se_modules.MANIFEST
    text = path.read_text(encoding="utf-8")
    table = re.search(rf"(?ms)^\[components\.{re.escape(name)}\][^\n]*\n(?P<body>.*?)(?=^\[|\Z)", text)
    line = table and re.search(r'(?m)^(?P<head>version\s*=\s*)"(?P<old>[^"]*)"', table["body"])
    if not line:
        raise ModuleError(f"{path.as_posix()}: [components.{name}] has no version line to move")
    start = table.start("body") + line.start()
    path.write_text(text[:start] + f'{line["head"]}"^{_v(version)}"' + text[table.start("body") + line.end():],
                    encoding="utf-8", newline="")
    return line["old"]


def set_require(root: Path, module, version: Version) -> str:
    """Set the require of `module` in the go.mod its go pin names to `version`; the old version."""
    relative, old = se_modules.go_require(root, module.name, module.go)
    path = root / relative
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?m)^(?P<head>\s*(?:require\s+)?{re.escape(module.name)}\s+)v\S+")
    if not pattern.search(text):
        raise ModuleError(f"{path.as_posix()}: no require {module.name} to move")
    path.write_text(pattern.sub(lambda m: m["head"] + se_modules.go_version(_v(version)), text, count=1),
                    encoding="utf-8", newline="")
    return old


def move_pins(root: Path, pins) -> tuple[list[str], list[str]]:
    """Move each of the project's own pins whose newest release lies beyond it to that release: a
    range to `^<newest>` in se.toml, a go pin's require in its go.mod. The lines of what moved, and
    of what only another repository moves (a component's own pin) or no pin moves (a commit pin)."""
    moved, left = [], []
    for pin in {(pin.path, pin.module.name): pin for pin in pins if pin.beyond}.values():
        module, newest = pin.module, pin.newest
        if len(pin.path) > 1:
            left.append(f"{pin.line()}: {pin.path[-1]} moves it in its own repository (a ticket there)")
        elif module.go:
            old = set_require(root, module, newest)
            moved.append(f"{module.name}: pin v{old} -> v{_v(newest)} ({module.go}; commit it)")
        elif module.version:
            old = set_range(root, module.name, newest)
            moved.append(f"{module.name}: pin {old} -> ^{_v(newest)} ({se_modules.MANIFEST}; commit it)")
        else:
            left.append(f"{pin.line()}: pinned by commit; uv run python <se>/scripts/se_modules.py update "
                        f"{module.name} --to v{_v(newest)} moves it")
    return moved, left


def guide_sections(guide: Path, name: str, old: Version | None, new: Version | None) -> list:
    """The sections of the guide at `guide` that lead `name` from `old` to `new` (scripts/upgrade_guide.py)."""
    if old is None or new is None or new <= old:
        return []
    try:
        text = guide.read_text(encoding="utf-8")
    except OSError:
        return []
    return upgrade_guide.sections(text, name, old, new)


def update(se_root: Path, root: Path | None, local_config: Path | None, world: World) -> tuple[list[str], bool]:
    """The update the start report names (docs/boot.md "The update"), each step decided from
    versions alone: the checkout current; SE to its newest release, across a major too, the
    project's `[components.se]` pin moved with it; each of the project's own pins whose newest
    release lies beyond it moved to that release; every lock to the newest release its pin admits;
    then the sections of the upgrade guides between the old and the new versions, of SE and of each
    component, for the agent to follow in order. The lines, and whether a step failed."""
    lines = [f"SE update of {root.as_posix() if root else 'no project'}"]
    if root is not None:
        try:
            integration = _load("work_tickets").integration_branch(root)
        except Exception as error:  # noqa: BLE001 - its own message names the setting
            return lines + [f"Checkout: the integration branch cannot be read, the update stops: {error}"], True
        line, stopped = current_checkout(root, integration)
        lines.append(line.replace("the boot stops", "the update stops"))
        if stopped:
            return lines, True
    try:
        local = se_modules.load_local(local_config or se_modules.default_local_config())
    except ModuleError as error:
        return lines + [f"Machine-local configuration: {error}"], True
    failed = False
    se = se_state(se_root, root, local, world)
    old_se = se.item.version
    new_se = old_se
    if se.error:
        failed = True
        lines.append(f"SE: {se.error}")
    elif se.newest and (old_se is None or se.newest > old_se) and not se.stays:
        if se.pin and not se_modules.matches(se.newest, se_modules.version_bounds("se", se.pin)):
            lines.append(f"se: pin {set_range(root, 'se', se.newest)} -> ^{_v(se.newest)} "
                         f"({se_modules.MANIFEST}; commit it)")
        moved, broke = upgrade_se(se_root, root, SEState(se.item, se.newest, se.newest, se.pin), world)
        failed |= broke
        lines.append(moved)
        if not broke:
            new_se = se.newest
    else:
        lines.append(f"SE: {_v(old_se)}, " + (se.stays if se.stays and se.newest and se.newest > (old_se or (0, 0, 0))
                                              else "current"))
    sections = [("SE", se_root / upgrade_guide.GUIDE, s) for s in guide_sections(
        se_root / upgrade_guide.GUIDE, "SE", old_se, new_se)]
    if root is not None and (root / se_modules.MANIFEST).is_file():
        try:
            found = se_modules.breaking(root, local)
            before = se_modules.read_lock(root)
            moved_pins, left = move_pins(root, [pin for pin in found.pins if pin.module.name != "se"])
            lines += moved_pins
            se_modules.place_tree(root, local, unlock=frozenset(pin.module.name for pin in found.pins))
            after = se_modules.read_lock(root)
        except ModuleError as error:
            return lines + [f"Components: not updated: {error}"], True
        for name, (version, _) in sorted(after.items()):
            was = before.get(name, ("", ""))[0]
            if was == version:
                continue
            lines.append(f"{name}: {was or 'none'} -> {version} ({se_modules.LOCK}; commit it)")
            clone = root / se_modules.MODULES_DIR / name
            own = clone / upgrade_guide.GUIDE
            guide = own if own.is_file() and upgrade_guide.sections(
                own.read_text(encoding="utf-8"), name, (0, 0, 0), (10 ** 6, 0, 0)) else se_root / upgrade_guide.GUIDE
            sections += [(name, guide, s) for s in guide_sections(guide, name, se_modules.parse_version(was),
                                                                  se_modules.parse_version(version))]
        lines += left
        unread = [pin for pin in found.unread
                  if se_modules.resolve(root, pin.module, local).kind != "local"]
        lines += [f"{pin.line()}: its releases could not be read: " + ("; ".join(pin.reasons) or
                  "no remote offers it") for pin in unread]
        failed |= bool(unread)
    if not sections:
        lines.append("Upgrade guide: no section lies between the versions; the update is done"
                     if not failed else "The update did not finish; run it again once the cause is fixed")
        return lines, failed
    lines.append(f"Upgrade guide: follow {_plural(len(sections), 'section')} in this order, every step "
                 "and then its check, and commit after each:")
    for name, guide, section in sections:
        lines += ["", f"<!-- {section.title}, from {guide.as_posix()} -->", section.text.rstrip("\n")]
    return lines, failed


#: The first words of the start's stop (docs/components.md "Required and optional at start").
STOP = "SE cannot start"


def start_components(root: Path | None, local_config: Path | None,
                     finder: "se_modules.Finder | None" = None) -> tuple[list[str], bool]:
    """At the session's start, before the core starts: resolve the tree of the project's
    `[components]` and theirs, as docs/components.md "Required and optional at start" says. What is
    placed comes first: a clone at its locked commit is used without asking any remote, so a start
    with every component placed stays within its budget and works offline; the rest is found by
    name and placed (`se_modules.place_tree`). The lines to show, and whether the start stops: a
    required component missing anywhere in the tree, or any other failure to resolve it (a lock
    the found release disagrees with, a bad list), is one message opening with `STOP`; an optional
    component missing is one line, and the start goes on. A project without an se.toml says
    nothing. It fails closed: SE works with nothing half-started."""
    if root is None or not (root / se_modules.MANIFEST).is_file():
        return [], False
    try:
        local = se_modules.load_local(local_config or se_modules.default_local_config())
        _, said = se_modules.place_tree(root, local, finder=finder)
    except ModuleError as error:
        return f"{STOP}: {error}".splitlines(), True
    return said, False


def root_line(se_root: Path) -> str:
    """The one named value that tells a session where SE is: `<se>` in SE's skills and agents."""
    return f"{ROOT_NAME}: {se_root}"


#: The environment variable that names the agent a session starts as (README "Claude Code cloud").
DEFAULT_AGENT_ENV = "SE_DEFAULT_AGENT"
#: The one agent it may name: the one a person talks to.
DEFAULT_AGENT = "se"


def default_agent(se_root: Path, environment: Mapping[str, str] | None = None) -> tuple[str, str]:
    """What `SE_DEFAULT_AGENT` hands the session: (the sentence, "") where it is `se` and SE's agent
    file exists; ("", the note line) where it is set to anything else; ("", "") where unset or empty."""
    value = (os.environ if environment is None else environment).get(DEFAULT_AGENT_ENV, "")
    if not value:
        return "", ""
    agent = se_root / "agents" / f"{DEFAULT_AGENT}.md"
    if value != DEFAULT_AGENT or not agent.is_file():
        return "", f"SE: {DEFAULT_AGENT_ENV} names no agent a session starts as: {value}"
    return ("This session acts as the se agent unless it was started as another agent (--agent, an agent "
            "picker) or its first message names another agent file, also where a compaction summarized "
            f"that message: read {se_root}/agents/{DEFAULT_AGENT}.md first and act as it defines."), ""


#: The heading of what the start hands the session alone, below the start report.
FOR_SESSION = "For the session, not part of the report:"


def handed(lines: list[str], session: list[str]) -> str:
    """The start report, then, where the start found any, what it found for the session alone."""
    return "\n".join(lines + (["", FOR_SESSION, *session] if session else []))


def shown_notes(notes: list[str]) -> list[str]:
    """The notes of the start the person sees above the report: a stop (`STOP`) alone."""
    return [note for note in notes if note.startswith(STOP)]


def hook_output(lines: list[str], notes: list[str], se_root: Path, host: str = "claude",
                environment: Mapping[str, str] | None = None, session: list[str] | None = None) -> str:
    """The SessionStart hook output of `host` (scripts/hosts.sh): the start report handed to the
    session, which opens its first message with it, what the start found for the session alone,
    and SE's root for the session. Claude Code also shows the person the report, a stop above it
    (systemMessage); Copilot's sessionStart reads only `additionalContext`. Where
    `SE_DEFAULT_AGENT` counts, the hand-over ends with the agent the session acts as
    (`default_agent`)."""
    sentence, note = default_agent(se_root, environment)
    shown_lines = shown_notes(notes) + lines
    found = ([note] if note else []) + [n for n in notes if n not in shown_lines] + list(session or [])
    text = "\n".join(shown_lines)
    shown = "" if host == "copilot" else ", already shown to the person"
    context = (f"{handed(shown_lines, found)}\n\nSE's start report{shown}. As SE, open your first "
               "message with it as it is and add nothing to it; act on what the start found for the "
               "session, and tell the person only what needs their decision.\n\n"
               f"{root_line(se_root)}\n`<se>` in SE's skills and agents is this path: run SE's scripts as "
               "`uv run python <se>/scripts/<name>.py`, never relative to the working directory.")
    if sentence:
        context += f"\n\n{sentence}"
    if host == "copilot":
        return json.dumps({"additionalContext": context})
    return json.dumps({"systemMessage": text,
                       "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}})


def find_project(given: Path | None) -> Path | None:
    if given is not None:
        return given.resolve()
    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    try:
        return se_modules.find_root(start)
    except ModuleError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="se_start.py", description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, help="the project; default: $CLAUDE_PROJECT_DIR or the nearest "
                        "ancestor with se.toml")
    parser.add_argument("--local", type=Path, help="machine-local configuration; default: ~/.se/local.toml")
    parser.add_argument("--cache", type=Path, help=f"the update check's cache; default: ${CACHE_ENV} or {CACHE_DEFAULT}")
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status", help="SE's version, what it loaded, each module and the "
                                        "documentation, from the cached update check")
    status_parser.add_argument("--greeting", action="store_true", help="only the greeting: out-of-date lines only")
    status_parser.add_argument("--hook", action="store_true", help="the greeting as Claude Code SessionStart JSON")
    status_parser.add_argument("--host", choices=("claude", "copilot"), default="claude",
                               help="with --hook: the host whose payload started the session (scripts/hosts.sh)")
    status_parser.add_argument("--note", action="append", default=[], help="a line to show above the greeting")
    status_parser.add_argument("--offline", action="store_true", help="never start the update check")
    status_parser.add_argument("--kern-bin", type=Path, help="bootstrap.sh: the kern binary it started for the project")
    status_parser.add_argument("--kern-starting", default="", help="bootstrap.sh: why kern is still starting")
    status_parser.add_argument("--kern-failed", default="", help="bootstrap.sh: why kern failed to start")
    status_parser.add_argument("--kern-none", action="store_true",
                               help="bootstrap.sh: no core starts, the project being inside no git checkout")
    commands.add_parser("check", help="read every remote now, in parallel, and, where gh is signed in, "
                        "the work landed since the last retro and the fleet check; cache the result")
    commands.add_parser("refresh", help="move every module due within its range, and SE itself, into place")
    boot_parser = commands.add_parser("boot", help="SE's boot: bring the checkout to the newest tip of its "
                                      "branch, then list SE and every pin of the component tree with its "
                                      "pinned, locked and newest version (README \"Boot\")")
    boot_parser.add_argument("--upgrade", action="store_true", help="also move SE to its newest release "
                             "and every lock to the newest release its pin admits; a release beyond a pin "
                             "is never taken")
    commands.add_parser("update", help="the update the start report names (/se:update): the checkout "
                        "current, SE to its newest release across a major too, every pin and lock to the "
                        "newest release, then the upgrade guide's sections between the versions")
    commands.add_parser("start-refresh", help="bootstrap.sh at the session's start: move an installed SE that "
                        "is a git checkout to its latest release; exit code 0 where it moved")
    commands.add_parser("start-components", help="bootstrap.sh at the session's start, before the core: resolve "
                        "the project's components from what is placed; exit code 1 where a required one is "
                        "missing, which stops the start")
    commands.add_parser("start-hooks", help="bootstrap.sh at the session's start: point an unset core.hooksPath "
                        "of the project at se's hooks, as setup.sh does; a set one stays")
    stopped_parser = commands.add_parser("stopped-hooks", help="setup.sh and setup.ps1, before they set "
                                         "core.hooksPath: name the checkout's own hooks that stop running")
    stopped_parser.add_argument("--repo", type=Path, required=True, help="the checkout")
    stopped_parser.add_argument("--hooks", type=Path, required=True, help="the folder core.hooksPath will name")
    return parser


def main(argv: list[str] | None = None, world: World | None = None) -> int:
    args = build_parser().parse_args(argv)
    code, _ = metrics.recorded(f"se_start.py {args.command}", lambda: run(args, world))
    return code


def run(args: argparse.Namespace, world: World | None) -> int:
    """Run the command `args` selected."""
    world = world or World()
    if args.command == "stopped-hooks":
        folder, stopped = own_hooks(args.repo, args.hooks)
        if stopped:
            print(stopped_hooks_line(args.repo.as_posix(), folder.as_posix(), stopped))
        return 0
    root = find_project(args.root)
    cache_path = (args.cache or default_cache()).expanduser()
    if args.command == "start-refresh":
        try:
            line, moved = start_refresh(SE_ROOT, root, args.local)
        except Exception as error:  # noqa: BLE001 - the start fails open, whatever went wrong
            line, moved = f"SE: no refresh at start, it failed: {type(error).__name__}: {error}", False
        if line:
            print(line)
        return 0 if moved else 1
    if args.command == "start-components":
        try:
            lines, stopped = start_components(root, args.local)
        except Exception as error:  # noqa: BLE001 - the start fails closed, whatever went wrong
            lines, stopped = [f"{STOP}: resolving the components failed: {type(error).__name__}: {error}"], True
        if lines:
            print("\n".join(lines))
        return 1 if stopped else 0
    if args.command == "start-hooks":
        try:
            line = start_hooks(SE_ROOT, root, args.local)
        except Exception as error:  # noqa: BLE001 - the start fails open, whatever went wrong
            line = f"SE: core.hooksPath not set at start, it failed: {type(error).__name__}: {error}"
        if line:
            print(line)
        return 0
    if args.command == "boot":
        lines, failed = boot(SE_ROOT, root, args.local, world, args.upgrade)
        print("\n".join(lines))
        return 1 if failed else 0
    if args.command == "update":
        lines, failed = update(SE_ROOT, root, args.local, world)
        print("\n".join(lines))
        return 1 if failed else 0
    if args.command == "refresh":
        lines, failed = refresh(SE_ROOT, root, args.local, cache_path, world)
        print("\n".join(lines))
        return 1 if failed else 0
    if args.command == "check":
        report = check(SE_ROOT, root, args.local, cache_path, world)
        print("\n".join(full(report, SE_ROOT)))
        return 1 if report.errors else 0
    report = status(SE_ROOT, root, args.local, cache_path, world, args.offline)
    kern = kern_line(SE_ROOT, root or Path.cwd(), Kern(args.kern_bin, args.kern_starting, args.kern_failed),
                     world.kern)
    found = (kern + without_kern(kern, args.host, args.kern_none)
             + (_load("copilot_guards").greeting(root, args.host) if args.host == "copilot" else []))
    if not (args.hook or args.greeting):
        print("\n".join(args.note + full(report, SE_ROOT)[:1] + found + full(report, SE_ROOT)[1:]))
        return 0
    lines, session = greeting(report, SE_ROOT), found + session_lines(report, SE_ROOT)
    if args.hook:
        print(hook_output(lines, args.note, SE_ROOT, args.host, session=session))
    else:
        print(handed(shown_notes(args.note) + lines,
                     [note for note in args.note if note not in shown_notes(args.note)] + session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
