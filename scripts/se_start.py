"""SE's start: the greeting, whether everything SE uses is up to date, and the one refresh.

`status` answers from what is on disk and the cached update check, never from the network, and
starts the check in the background when the cache is stale; `check` runs that check; `refresh`
moves every module that is due within its range, and SE itself, into place. What each command
does and where SE runs it is the README section "Start and refresh".
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SE_ROOT = Path(__file__).resolve().parents[1]
CACHE_DEFAULT = Path("~/.se/start-check.json")
CACHE_ENV = "SE_START_CACHE"
MAX_AGE = 3600  # seconds a cached update check stays fresh
RUNNING_FOR = 120  # seconds a started background check counts as running
BUDGET = 1.0  # seconds status may take: it is interactive
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
CHECK_REMEDY = "run it by hand to see the cause: uv run python {se}/scripts/se_start.py check"


def _load(name: str):
    """A sibling script, loaded once under its own name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


se_modules = _load("se_modules")
public_check = _load("public_check")
ModuleError = se_modules.ModuleError
Version = tuple[int, int, int]


class RemoteError(Exception):
    """A remote that could not be read; the message names it and the cause."""


# Inputs


def git_tags(url: str) -> list[Version]:
    """The `vMAJOR.MINOR.PATCH` tags of a remote, in one call that fetches nothing."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=60,
    )
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
    """What the plugin loads: the skills and agents in its Claude Code layout (the Copilot layout
    is generated from the same source), the rules the public check enforces, and every agent but
    SE itself as a sub-agent."""
    agents = [name for name in _front_names(se_root / "agents", "*.md") if name != "se"]
    return Counts(len(_front_names(se_root / "skills", "*/SKILL.md")), len(public_check.RULES), len(agents))


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
    result = subprocess.run(["git", "-C", str(se_root), "remote", "get-url", "origin"],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() or None if result.returncode == 0 else None


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
            for module in se_modules.load_manifest(root):
                items.append(_module_item(root, module, local, locked))
        except ModuleError as error:
            errors.append(f"modules of {root / se_modules.MANIFEST}: {error}")
    return Local(se_version, str(_project(se_root).get("docs_url", "")), counts(se_root), items, errors)


def _plugin_repository(se_root: Path) -> str | None:
    """The repository an installed copy names in its plugin manifest, where its versions are tagged."""
    try:
        data = json.loads((se_root / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repository = data.get("repository") if isinstance(data, dict) else None
    return repository if isinstance(repository, str) and repository else None


def _se_item(se_root: Path, version: Version | None, local) -> Item:
    """SE itself: a local path of `se` in the machine-local configuration (never touched), a git
    checkout (a development checkout or a cloud setup-script clone), or an installed copy (a Claude
    Code plugin or a Copilot copy), checked against the repository its plugin manifest names."""
    path = local.paths.get("se")
    if path is not None and path == se_root.resolve():
        return Item("SE", "local", version, None, note=f"local path {se_root}")
    origin = _origin(se_root)
    if origin:
        return Item("SE", "se", version, origin)
    repository = _plugin_repository(se_root)
    return Item("SE", "se", version, repository, note="an installed copy" if repository else
                f"an installed copy without a repository in {PLUGIN_MANIFEST}, not checked")


def _module_item(root: Path, module, local, locked) -> Item:
    source = se_modules.resolve(root, module, local)
    if source.kind == "local":
        try:
            version = se_modules.checkout_version(source.checkout)
        except ModuleError:
            version = None
        return Item(module.name, "local", version, None, module.version, note=f"local path {source.checkout}")
    url = local.rewrite(module.url)
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

    @classmethod
    def read(cls, path: Path) -> "Cache":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data.get("checked_at"), data.get("started_at"), dict(data.get("remotes", {})))
        except (OSError, ValueError, AttributeError):
            return cls()

    def write(self, path: Path) -> None:
        """Atomically: a status reading at the same time sees the old or the new check, whole."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"checked_at": self.checked_at, "started_at": self.started_at, "remotes": self.remotes}
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8",
                                         suffix=".tmp") as handle:
            json.dump(data, handle, indent=1)
        os.replace(handle.name, path)

    def fresh(self, urls: set[str], now: float) -> bool:
        return self.checked_at is not None and now - self.checked_at < MAX_AGE and urls <= set(self.remotes)

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

    @property
    def errors(self) -> list[str]:
        return self.local.errors + [s.error for s in self.states if s.error]


def _v(version: Version | None) -> str:
    return se_modules.version_text(version) if version else "none"


def refresh_command(se_root: Path) -> str:
    return f"uv run python {se_root.as_posix()}/scripts/se_start.py refresh"


def greeting(report: Report, se_root: Path) -> list[str]:
    """The first line, then only what is out of date, the refresh command and what failed."""
    local = report.local
    c = local.counts
    lines = [f"SE {_v(local.se_version)} started: {_plural(c.skills, 'skill')}, {_plural(c.rules, 'rule')}, "
             f"{_plural(c.subagents, 'sub-agent')}. Documentation: {local.docs_url or 'none set'}"]
    due = [s for s in report.states if s.due]
    for state in due:
        lines.append(f"  {state.item.name}: {_v(state.item.version)} -> {_v(state.due)}")
    for state in (s for s in report.states if s.outside):
        lines.append(f"  {state.item.name}: {_v(state.outside)} is outside "
                     f"{_range(state.item)}; refresh never applies it")
    if due:
        lines.append(f"Refresh: {refresh_command(se_root)}")
    lines += _check_lines(report, se_root)
    return lines


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
            verdict += f"; {_v(state.outside)} is outside {_range(item)}, never applied by refresh"
        lines.append(f"{item.name}: in use {use}; latest {_v(state.latest)}; {verdict}")
    if any(s.due for s in report.states):
        lines.append(f"Refresh: {refresh_command(se_root)}")
    return lines + _check_lines(report, se_root)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


# Commands


def _spawn_detached(argv: list[str]) -> None:
    kwargs = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **kwargs)


def _claude(args: list[str]) -> subprocess.CompletedProcess:
    """Claude Code's command line; a machine without it answers as a failed command."""
    try:
        return subprocess.run(["claude", *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(["claude", *args], 127, "", str(error))


@dataclass(frozen=True)
class World:
    """The outside world status, check and refresh reach: the clock, the remotes, the start of a
    background check, Claude Code's command line. Tests replace each."""

    clock: Callable[[], float] = time.time
    remote: Callable[[str], list[Version]] = git_tags
    spawn: Callable[[list[str]], None] = _spawn_detached
    claude: Callable[[list[str]], subprocess.CompletedProcess] = _claude


def status(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
           world: World, offline: bool = False) -> Report:
    """Answer from disk and the cache; start the update check in the background when stale."""
    local = read_local(se_root, root, local_config)
    now = world.clock()
    cache = Cache.read(cache_path)
    urls = {item.url for item in local.items if item.url}
    running = cache.running(now)
    if not offline and not cache.fresh(urls, now) and not running:
        cache.started_at = now
        cache.write(cache_path)
        argv = [sys.executable, str(se_root / "scripts" / "se_start.py"), "--cache", str(cache_path)]
        argv += (["--root", str(root)] if root else []) + (["--local", str(local_config)] if local_config else [])
        world.spawn(argv + ["check"])
        running = True
    states = [assess(item, cache.remotes if cache.checked_at is not None else None) for item in local.items]
    return Report(local, states, cache.checked_at, running, now)


def check(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
          world: World) -> Report:
    """Read every remote once, in parallel, and keep the result in the cache."""
    local = read_local(se_root, root, local_config)
    remotes = run_check({item.url for item in local.items if item.url}, world.remote)
    now = world.clock()
    Cache(now, None, remotes).write(cache_path)
    return Report(local, [assess(item, remotes) for item in local.items], now, False, now)


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
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or f"SE {_v(version)} started" not in result.stdout:
        raise RefreshError(f"SE v{_v(version)} does not start: {(result.stderr or result.stdout).strip()[-300:]}")


def refresh_se(se_root: Path, root: Path | None, version: Version) -> str:
    """Bring the se checkout to tag v<version>, after the new version started in a trial worktree."""
    tag = f"v{_v(version)}"
    if se_modules.is_dirty(se_root):
        raise RefreshError(f"the se checkout {se_root} has local changes; commit or discard them")
    _git(se_root, "fetch", "--quiet", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
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
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser() / "plugins" / "installed_plugins.json"


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
                   world: World) -> str:
    """Update the installed plugin through Claude Code, check that the new install starts, and put
    the old install back in Claude Code's record when it does not."""
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
        if found is None or found < due or found[0] != old[0]:
            raise RefreshError(f"claude plugin update {plugin_id} installed version {_v(found)}, "
                               f"not v{_v(due)} or newer within major {old[0]}")
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
    local = se_modules.load_local(local_config or se_modules.default_local_config())
    module = next(m for m in se_modules.load_manifest(root) if m.name == name)
    source = se_modules.pinned_source(root, module, local)
    clone = source.checkout
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
        se_modules.write_lock(root, name, _v(version), sha)
    except (OSError, ModuleError):
        if previous:
            se_modules.git_ok(clone, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", previous)
        raise
    return f"{name}: {old} -> {_v(version)} (se.lock; commit it)"


def refresh(se_root: Path, root: Path | None, local_config: Path | None, cache_path: Path,
            world: World) -> tuple[list[str], bool]:
    """Check now, then move every item that is due; one item failing leaves the others moving."""
    report = check(se_root, root, local_config, cache_path, world)
    lines, failed = [], False
    for state in report.states:
        item = state.item
        if state.outside:
            lines.append(f"{item.name}: {_v(state.outside)} is outside {_range(item)}; not applied")
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
        check(se_root, root, local_config, cache_path, world)
    return lines, failed


def hook_output(lines: list[str], notes: list[str]) -> str:
    """Claude Code's SessionStart hook output: the greeting shown to the person (systemMessage) and
    handed to the session, which opens its first message with it."""
    text = "\n".join(notes + lines)
    context = (f"{text}\n\nSE's start greeting, already shown to the person. As SE, open your first "
               "message with it as it is; pass on any line that names a command to run.")
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
    status_parser.add_argument("--note", action="append", default=[], help="a line to show above the greeting")
    status_parser.add_argument("--offline", action="store_true", help="never start the update check")
    commands.add_parser("check", help="read every remote now, in parallel, and cache the result")
    commands.add_parser("refresh", help="move every module due within its range, and SE itself, into place")
    return parser


def main(argv: list[str] | None = None, world: World | None = None) -> int:
    args = build_parser().parse_args(argv)
    world = world or World()
    root = find_project(args.root)
    cache_path = (args.cache or default_cache()).expanduser()
    if args.command == "refresh":
        lines, failed = refresh(SE_ROOT, root, args.local, cache_path, world)
        print("\n".join(lines))
        return 1 if failed else 0
    if args.command == "check":
        report = check(SE_ROOT, root, args.local, cache_path, world)
        print("\n".join(full(report, SE_ROOT)))
        return 1 if report.errors else 0
    report = status(SE_ROOT, root, args.local, cache_path, world, args.offline)
    if args.hook:
        print(hook_output(greeting(report, SE_ROOT), args.note))
    else:
        print("\n".join(args.note + (greeting if args.greeting else full)(report, SE_ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
