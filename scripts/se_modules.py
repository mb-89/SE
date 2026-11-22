"""Pull dependencies into a repository as modules pinned to commits or semantic version ranges.

The format and the commands are described once in the README section "Modules".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import git_door
import se_home
MANIFEST = "se.toml"
LOCK = "se.lock"
MODULES_DIR = Path(".se") / "modules"
#: kern, the Go core, as se.toml [modules.kern] pins it (README "Modules").
KERN = "kern"


def kern_dir(root: Path) -> Path:
    """Where kern is for the checkout at `root`: its pinned clone, `<root>/.se/modules/kern`, which
    `se_modules.py sync kern` places (its Go module, its Python SDK under `python/`)."""
    return root / MODULES_DIR / KERN

TRACKED_BRANCH = "main"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MODULE_KEYS = {"url", "ref", "version", "path", "go"}
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
RANGE_RE = re.compile(r"^([\^~=]?)(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?(?:\.(0|[1-9][0-9]*))?$")
VERSION_REMEDY = 'set version = "MAJOR.MINOR.PATCH" under [project] (README "Project settings")'
Version = tuple[int, int, int]
LOCAL_CONFIG_KEYS = {
    "paths",
    "urls",
    "integrator_session",
    "trackers",
    "worktree_roots",
    "repos",
    "mirrors",
    "public_identity",
    "hooks",
}


#: The environment variable that switches SE's session hooks' core off (hooks_core).
HOOK_CORE_VARIABLE = "SE_HOOK_CORE"


class ModuleError(Exception):
    """A user-facing error: bad configuration or a failed git step."""


@dataclass(frozen=True)
class Module:
    """A declared module; `ref` is its pin, for a `version` range the locked commit ("" unlocked)."""

    name: str
    url: str
    ref: str
    path: str | None = None
    version: str | None = None
    #: For a `go` pin: the `go.mod` (relative to the root) whose `require <name>` is the version.
    go: str | None = None


# Semantic versions


def parse_version(text: object) -> Version | None:
    match = VERSION_RE.match(text) if isinstance(text, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def version_text(version: Version) -> str:
    return ".".join(str(part) for part in version)


def version_bounds(name: str, text: str) -> tuple[Version, Version]:
    """The versions `[low, high)` a range admits: `^1.4`, `~1.4.2`, `1.4` (any 1.4.x) or `1.4.2`."""
    match = RANGE_RE.match(text)
    if not match:
        raise ModuleError(
            f"module {name}: version must be a semver range such as ^1.4, ~1.4.2 or 1.4.2, got {text!r}"
        )
    operator, major, minor, patch = match[1], int(match[2]), match[3], match[4]
    low = (major, int(minor or 0), int(patch or 0))
    if operator == "=" and patch is None:
        raise ModuleError(f"module {name}: ={text[1:]} needs MAJOR.MINOR.PATCH")
    if operator == "^":
        if major or minor is None:
            return low, (major + 1, 0, 0)
        if low[1] or patch is None:
            return low, (0, low[1] + 1, 0)
        return low, (0, 0, low[2] + 1)
    if patch is not None and operator != "~":
        return low, (low[0], low[1], low[2] + 1)
    return low, ((major, low[1] + 1, 0) if minor is not None else (major + 1, 0, 0))


def matches(version: Version, bounds: tuple[Version, Version]) -> bool:
    return bounds[0] <= version < bounds[1]


def checkout_version(checkout: Path, go: bool = False) -> Version | None:
    """`[project] version` of a module checkout's se.toml, or for a `go` pin its `release.toml`
    `version` (kern's se.toml sets none); None where it sets none."""
    if go:
        release = checkout / "release.toml"
        value = _read_toml(release).get("version") if release.is_file() else None
        if value is None:
            return None
        version = parse_version(value)
        if version is None:
            raise ModuleError(f"{release}: version {value!r} is not MAJOR.MINOR.PATCH")
        return version
    manifest = checkout / MANIFEST
    data = _read_toml(manifest) if manifest.is_file() else {}
    project = data.get("project", {})
    value = project.get("version") if isinstance(project, dict) else None
    if value is None:
        return None
    version = parse_version(value)
    if version is None:
        raise ModuleError(f"{manifest}: version {value!r} is not MAJOR.MINOR.PATCH; {VERSION_REMEDY}")
    return version


def read_lock(root: Path) -> dict[str, tuple[str, str]]:
    """`se.lock`: per module pinned by a range, the resolved (version, commit)."""
    lock = root / LOCK
    if not lock.is_file():
        return {}
    entries = {}
    for name, table in _read_toml(lock).get("modules", {}).items():
        version = table.get("version") if isinstance(table, dict) else None
        ref = table.get("ref") if isinstance(table, dict) else None
        if parse_version(version) is None or not isinstance(ref, str) or not SHA_RE.match(ref):
            raise ModuleError(f"{lock}: [modules.{name}] needs version and a full commit ref; delete it and run sync")
        entries[name] = (version, ref.lower())
    return entries


def write_lock(root: Path, name: str, version: str, ref: str) -> None:
    """Record one module's resolved version in `se.lock`, dropping modules no longer pinned by a range."""
    ranged = {m.name for m in load_manifest(root) if m.version}
    entries = {key: value for key, value in read_lock(root).items() if key in ranged}
    entries[name] = (version, ref)
    lines = [f"# {LOCK}: the commits scripts/se_modules.py resolved for the version ranges in {MANIFEST}.",
             "# Written by sync and update; commit it, never edit it."]
    for key in sorted(entries):
        locked_version, locked_ref = entries[key]
        lines += ["", f"[modules.{key}]", f'version = "{locked_version}"', f'ref = "{locked_ref}"']
    (root / LOCK).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ModuleError(f"{path}: {error}") from error


def _check_subpath(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ModuleError(f"module {name}: path must be a non-empty string")
    posix = PurePosixPath(value)
    if posix.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in posix.parts:
        raise ModuleError(f"module {name}: path must be relative inside the module: {value}")
    return value


GO_REQUIRE = re.compile(r"^(?:require\s+)?(?P<module>\S+)\s+v(?P<version>\S+)(?:\s*//.*)?$")


def go_require(root: Path, name: str, value: object) -> tuple[str, str]:
    """(go.mod path relative to root, version) of a `go` pin: the exact version the `go.mod` that
    `value` names (`true`, the root's) requires of the module path `name` (README "Modules")."""
    if value is True:
        relative = "go.mod"
    elif isinstance(value, str) and value:
        relative = _check_subpath(name, value)
    else:
        raise ModuleError(f"module {name}: go must be true or a relative path to a go.mod")
    path = root / relative
    if not path.is_file():
        raise ModuleError(f"module {name}: no {relative} in {root}, which go names")
    block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        bare = line.strip()
        if bare.startswith("require ("):
            block = True
            continue
        if block and bare == ")":
            block = False
            continue
        if not (block or bare.startswith("require ")):
            continue
        match = GO_REQUIRE.match(bare if not block else f"require {bare}")
        if match and match["module"] == name:
            if parse_version(match["version"]) is None:
                raise ModuleError(f"module {name}: {relative} requires {name} v{match['version']}, "
                                  "not vMAJOR.MINOR.PATCH")
            return relative, match["version"]
    raise ModuleError(f"module {name}: {relative} has no require {name} v<version>; add one")


def load_manifest(root: Path) -> list[Module]:
    """Read and validate the modules declared in `<root>/se.toml`."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ModuleError(f"no {MANIFEST} in {root}")
    tables = _read_toml(manifest).get("modules", {})
    if not isinstance(tables, dict):
        raise ModuleError(f"{MANIFEST}: [modules] must be a table")
    locked = read_lock(root)
    modules = []
    for name, table in tables.items():
        if not NAME_RE.match(name):
            raise ModuleError(f"module name {name!r}: use letters, digits, '.', '_' and '-'")
        if not isinstance(table, dict):
            raise ModuleError(f"module {name}: [modules.{name}] must be a table")
        unknown = sorted(set(table) - MODULE_KEYS)
        if unknown:
            raise ModuleError(f"module {name}: unknown key(s) {', '.join(unknown)}")
        url, ref, version = table.get("url"), table.get("ref"), table.get("version")
        if not isinstance(url, str) or not url:
            raise ModuleError(f"module {name}: url is required")
        try:
            # `../<name>.git`: the repository beside this one, on its origin's host (se_home.py).
            url = se_home.resolve_module(root, url)
        except se_home.NoHome as error:
            raise ModuleError(f"module {name}: {error}") from error
        path = _check_subpath(name, table["path"]) if "path" in table else None
        if "go" in table:
            if ref is not None or version is not None:
                raise ModuleError(f"module {name}: go pins the version; drop ref and version")
            gomod, exact = go_require(root, name, table["go"])
            locked_version, locked_ref = locked.get(name, ("", ""))
            modules.append(Module(name, url, locked_ref if locked_version == exact else "", path, exact, gomod))
            continue
        if version is not None:
            if ref is not None:
                raise ModuleError(f"module {name}: pin either ref or version, not both")
            if not isinstance(version, str):
                raise ModuleError(f"module {name}: version must be a semver range string such as \"^1.4\"")
            bounds = version_bounds(name, version)
            locked_version, locked_ref = locked.get(name, ("", ""))
            ok = parse_version(locked_version) is not None and matches(parse_version(locked_version), bounds)
            modules.append(Module(name, url, locked_ref if ok else "", path, version))
            continue
        if not isinstance(ref, str) or not ref:
            raise ModuleError(f"module {name}: ref or version is required")
        if not SHA_RE.match(ref):
            raise ModuleError(f"module {name}: ref must be a full commit SHA, got {ref!r}")
        modules.append(Module(name, url, ref.lower(), path))
    return modules


@dataclass(frozen=True)
class LocalConfig:
    """Machine-local settings from `~/.se/local.toml`; only read, never written."""

    paths: dict[str, Path]
    urls: dict[str, str]
    #: `[hooks]`: `core`, a string or a boolean, whether SE's session hooks start the core (hooks_core).
    hooks: dict[str, str | bool] = field(default_factory=dict)

    def rewrite(self, url: str) -> str:
        """Apply the longest matching `[urls]` prefix rewrite."""
        prefixes = [prefix for prefix in self.urls if url.startswith(prefix)]
        if not prefixes:
            return url
        prefix = max(prefixes, key=len)
        return self.urls[prefix] + url[len(prefix):]


def default_local_config() -> Path:
    return Path.home() / ".se" / "local.toml"


def _string_table(config: Path, data: dict, key: str) -> dict[str, str]:
    table = data.get(key, {})
    if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
        raise ModuleError(f"{config}: [{key}] must map names to strings")
    return table


def load_local(config: Path) -> LocalConfig:
    if not config.is_file():
        return LocalConfig(paths={}, urls={})
    data = _read_toml(config)
    unknown = sorted(set(data) - LOCAL_CONFIG_KEYS)
    if unknown:
        raise ModuleError(f"{config}: unknown section(s) {', '.join(unknown)}")
    paths = {
        name: (config.parent / Path(value).expanduser()).resolve()
        for name, value in _string_table(config, data, "paths").items()
    }
    return LocalConfig(paths=paths, urls=_string_table(config, data, "urls"),
                       hooks=_hooks_table(config, data))


def _hooks_table(config: Path, data: dict) -> dict[str, str | bool]:
    """`[hooks]`: a table that holds `core` alone, as a string or a boolean."""
    table = data.get("hooks", {})
    if (not isinstance(table, dict) or set(table) - {"core"}
            or not all(isinstance(v, (str, bool)) for v in table.values())):
        raise ModuleError(f'{config}: [hooks] holds only core, as a string or a boolean (core = "off")')
    return table


def hooks_core(environment: Mapping[str, str], local: LocalConfig) -> tuple[str, str]:
    """Whether SE's session hooks start and use the core, and the layer that answered.

    `SE_HOOK_CORE` in `environment` answers first wherever it is set, even empty: exactly `off`, in
    any case, is off, every other value on. Only where it is unset does `[hooks] core` of the local
    file answer: `off` in any case, or false, is off; any other string, or true, is on. Neither set,
    the hooks are on. Reads no file, environment or process."""
    if HOOK_CORE_VARIABLE in environment:
        return ("off" if environment[HOOK_CORE_VARIABLE].lower() == "off" else "on"), "environment"
    if "core" in local.hooks:
        value = local.hooks["core"]
        off = value is False or (isinstance(value, str) and value.lower() == "off")
        return ("off" if off else "on"), "local"
    return "on", "default"


@dataclass(frozen=True)
class Source:
    """Where a module comes from on this machine."""

    module: Module
    kind: str  # "local" or "pinned"
    checkout: Path
    url: str
    note: str = ""

    @property
    def dir(self) -> Path:
        return self.checkout / self.module.path if self.module.path else self.checkout


def resolve(root: Path, module: Module, local: LocalConfig) -> Source:
    """Use the local checkout if it exists, else the pinned clone in `.se/modules/<name>`."""
    url = local.rewrite(module.url)
    note = ""
    local_path = local.paths.get(module.name)
    if local_path is not None:
        if local_path.is_dir():
            return Source(module, "local", local_path, url)
        note = f"local path missing: {local_path}"
    return Source(module, "pinned", root / MODULES_DIR / module.name, url, note)


def module_dirs(root: Path, local: LocalConfig) -> list[tuple[str, Path]]:
    """Each module `<root>/se.toml` declares, in its order, with its folder on this machine (as
    `resolve` finds it, its `path` applied), without resolving its URL: a reader of a module's
    files (se_guidance.py) needs no origin. None where there is no se.toml."""
    manifest = root / MANIFEST
    tables = _read_toml(manifest).get("modules", {}) if manifest.is_file() else {}
    if not isinstance(tables, dict):
        raise ModuleError(f"{MANIFEST}: [modules] must be a table")
    found = []
    for name, table in tables.items():
        if not isinstance(table, dict):
            raise ModuleError(f"module {name}: [modules.{name}] must be a table")
        path = _check_subpath(name, table["path"]) if "path" in table else None
        found.append((name, resolve(root, Module(name, "", "", path), local).dir))
    return found


# What `kern-pin` and `app-binary` print for a download base origin names no home for: bootstrap.sh
# then builds the binary from its folder, as where no release matches.
NO_BASE = "-"
#: kern's release.toml in its clone: its release tag (`download`'s last part) and download base.
KERN_RELEASE = "release.toml"


def kern_pin(root: Path) -> tuple[str, str]:
    """(version, tag) of the kern `root` pins: the version `[modules.kern]` reads from the go.mod
    its `go` names (README "Modules"), and the tag the pinned clone's `release.toml` names for it,
    the last part of its `download` (kern's README "Release")."""
    manifest = root / MANIFEST
    table = (_read_toml(manifest).get("modules", {}) if manifest.is_file() else {}).get(KERN)
    if not isinstance(table, dict) or "go" not in table:
        raise ModuleError(f"no [modules.{KERN}] with go in {manifest}: it pins no kern")
    version = go_require(root, KERN, table["go"])[1]
    return version, _kern_download(root)[1].rsplit("/", 1)[-1].replace("{version}", version)


def _kern_download(root: Path) -> tuple[Path, str]:
    """(release.toml, its `download`) of the pinned kern clone, `{version}` unfilled."""
    path = kern_dir(root) / KERN_RELEASE
    if not path.is_file():
        raise ModuleError(f"no {path}: kern is not placed; run uv run python scripts/se_modules.py "
                          f"sync {KERN} in {root}")
    download = _read_toml(path).get("download")
    if not isinstance(download, str) or not download:
        raise ModuleError(f"{path}: download names no URL (kern's README \"Release\")")
    return path, download


def kern_download(root: Path) -> str:
    """Where the release of the kern `root` pins is published: the pinned clone's `release.toml`
    `download`, its version filled in, under the home the clone's origin names (kern's own
    repository), as bootstrap.sh fetches it; "" where that origin names none (`release_base`)."""
    version, _ = kern_pin(root)
    return release_base(kern_dir(root), _kern_download(root)[1], version)


def release_base(root: Path, download: str, version: str) -> str:
    """A release.toml's `download` with `{version}` filled in: a path such as
    `releases/download/se-v{version}` lies under the home `root`'s origin names (se_home.py), so no
    file names where SE lives; "" where origin names none, and the start builds the binary from its
    folder. An absolute URL comes back as it is."""
    filled = download.replace("{version}", version)
    if "://" in filled:
        return filled
    home = se_home.find(root)
    return home.at(filled) if home is not None else ""


@dataclass(frozen=True)
class AppBinary:
    """The binary bootstrap.sh fetches, builds and starts for a checkout: its name (`se` for SE,
    `kern` for a bare application), its version, the download base its release is published under
    (`{version}` filled in), and the folder and package its source builds from."""

    name: str
    version: str
    download: str
    build_dir: str  # relative to the checkout root; holds release.toml, go.mod and the package
    package: str    # the binary's Go package, relative to build_dir


def app_binary(root: Path) -> AppBinary:
    """The application binary the checkout at `root` runs: kern's core plus the application's Go
    components, where it has any, else the bare kern (SE's docs/go-core.md "How the binary
    arrives"). `se.toml` `[binary] release = "<path>"` names where that binary's release.toml
    lives; its `version`, `download`, `binary` and `package` own the binary's facts
    (components/release.toml for SE). An application that sets no `[binary]` runs the bare kern
    of its pinned clone, read from the clone's `release.toml` (kern-pin), built there."""
    manifest = root / MANIFEST
    binary = _read_toml(manifest).get("binary", {}) if manifest.is_file() else {}
    release = binary.get("release") if isinstance(binary, dict) else None
    if not release:
        version, _ = kern_pin(root)
        return AppBinary("kern", version, kern_download(root), (MODULES_DIR / KERN).as_posix(), "./cmd/kern")
    if not isinstance(release, str):
        raise ModuleError(f"{manifest}: [binary] release must be a path to a release.toml")
    _check_subpath("binary", release)
    path = root / release
    if not path.is_file():
        raise ModuleError(f"no {release} in {root}: se.toml [binary] names it but it is missing")
    doc = _read_toml(path)
    version, name = doc.get("version"), doc.get("binary")
    download, package = doc.get("download"), doc.get("package")
    if parse_version(version) is None:
        raise ModuleError(f"{path}: version must be MAJOR.MINOR.PATCH (kern's README \"Release\")")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ModuleError(f"{path}: binary must name the application's binary (e.g. \"se\")")
    if not isinstance(download, str) or not download:
        raise ModuleError(f"{path}: download names no URL (kern's README \"Release\")")
    if not isinstance(package, str) or not package:
        raise ModuleError(f"{path}: package names no Go package (e.g. \"./cmd/se\")")
    return AppBinary(name, version, release_base(root, download, version),
                     PurePosixPath(release).parent.as_posix(), package)


def app_root(se_root: Path, project: Path | None) -> Path:
    """The checkout whose release pins the session runs: the project where it is SE's own
    checkout (its plugin manifest names the same plugin as se_root's and it sets a `[binary]`), so
    a session on SE's main runs main's pins; else se_root, the installed SE."""
    if project is None or project.resolve() == se_root.resolve():
        return se_root

    def plugin(root: Path) -> object:
        try:
            data = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get("name") if isinstance(data, dict) else None

    manifest = project / MANIFEST
    binary = _read_toml(manifest).get("binary") if manifest.is_file() else None
    name = plugin(se_root)
    return project if name and plugin(project) == name and isinstance(binary, dict) else se_root


def find_root(start: Path) -> Path:
    for directory in [start, *start.parents]:
        if (directory / MANIFEST).is_file():
            return directory
    raise ModuleError(f"no {MANIFEST} in {start} or its parents")


# Git


def _run_git(cwd: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess:
    return git_door.run(*args, cwd=cwd, no_prompt=True)


def git(cwd: Path, *args: str) -> str:
    result = _run_git(cwd, args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ModuleError(f"git {' '.join(args)} failed in {cwd}: {detail}")
    return result.stdout.strip()


def git_ok(cwd: Path, *args: str) -> bool:
    return _run_git(cwd, args).returncode == 0


def has_commit(repo: Path, rev: str) -> bool:
    return git_ok(repo, "cat-file", "-e", f"{rev}^{{commit}}")


def is_dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no"))


def is_checkout_root(path: Path) -> bool:
    if not git_ok(path, "rev-parse", "--git-dir"):
        return False
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve() == path.resolve()


def log_lines(repo: Path, revision_range: str) -> list[str]:
    output = git(repo, "log", "--format=%h %s", "--no-decorate", revision_range)
    return output.splitlines() if output else []


def ensure_clone(source: Source) -> None:
    """Create or reuse the module's clone in `.se/modules/<name>`, pointing at the effective url."""
    clone = source.checkout
    if (clone / ".git").exists():
        if git(clone, "remote", "get-url", "origin") != source.url:
            git(clone, "remote", "set-url", "origin", source.url)
        return
    if clone.exists() and any(clone.iterdir()):
        raise ModuleError(f"{clone} exists and is not a git clone; remove it")
    clone.parent.mkdir(parents=True, exist_ok=True)
    git(clone.parent, "clone", "--quiet", "--no-checkout", source.url, str(clone))


def is_populated(clone: Path) -> bool:
    """A clone made with --no-checkout has no index until its first checkout."""
    return (clone / ".git" / "index").exists()


def fetch(clone: Path) -> None:
    """Fetch branches and tags; `--force` follows tags the upstream moved, the lock still pins the commit."""
    git(clone, "fetch", "--quiet", "--force", "--prune", "--tags", "origin")


def ensure_commit(source: Source, sha: str) -> None:
    clone = source.checkout
    if has_commit(clone, sha):
        return
    fetch(clone)
    if not has_commit(clone, sha) and not (git_ok(clone, "fetch", "--quiet", "origin", sha) and has_commit(clone, sha)):
        raise ModuleError(f"module {source.module.name}: commit {sha} not found in {source.url}")


def tagged_versions(clone: Path) -> dict[Version, str]:
    """The clone's `vMAJOR.MINOR.PATCH` tags by version; other tags are ignored."""
    output = git(clone, "tag", "--list", "v*")
    return {version: tag for tag in output.splitlines() if (version := parse_version(tag[1:])) is not None}


def newest_matching(source: Source) -> tuple[str, str] | None:
    """The highest tagged version the module's range admits in its clone, and its commit."""
    module = source.module
    bounds = version_bounds(module.name, module.version or "")
    admitted = [version for version in tagged_versions(source.checkout) if matches(version, bounds)]
    if not admitted:
        return None
    best = max(admitted)
    return version_text(best), git(source.checkout, "rev-parse", "--verify", f"refs/tags/v{version_text(best)}^{{commit}}")


def resolve_range(root: Path, source: Source) -> Module:
    """Fetch the module's tags, lock the highest one its range admits and return the locked module."""
    module = source.module
    ensure_clone(source)
    fetch(source.checkout)
    found = newest_matching(source)
    if found is None and module.go:
        raise ModuleError(
            f"module {module.name}: no tag v{module.version} in {source.url}, which "
            f"{module.go}'s require {module.name} v{module.version} names; release it or change that line"
        )
    if found is None:
        raise ModuleError(
            f"module {module.name}: no tag vMAJOR.MINOR.PATCH in {source.url} matches version "
            f"{module.version!r} of {root / MANIFEST}; widen the range or release the module "
            "(README \"Project settings\")"
        )
    write_lock(root, module.name, *found)
    return Module(module.name, module.url, found[1], module.path, module.version, module.go)


def pinned_source(root: Path, module: Module, local: LocalConfig) -> Source:
    return Source(module, "pinned", root / MODULES_DIR / module.name, local.rewrite(module.url))


def lock_range(root: Path, module: Module, local: LocalConfig) -> Module:
    """A module pinned by a range keeps its locked commit; an unlocked one is resolved and locked."""
    if module.version is None or module.ref:
        return module
    return resolve_range(root, pinned_source(root, module, local))


def version_report(source: Source) -> str:
    """The version of a local checkout, and whether the module's range admits it."""
    module = source.module
    version = checkout_version(source.checkout, go=module.go is not None)
    if version is None:
        if module.go:
            raise ModuleError(f"module {module.name}: {source.checkout / 'release.toml'} sets no version, "
                              f"so the pin {module.version} cannot be checked")
        if module.version:
            raise ModuleError(
                f"module {module.name}: {source.checkout / MANIFEST} sets no version, so range "
                f"{module.version!r} cannot be checked; {VERSION_REMEDY} there"
            )
        return "version none"
    text = f"version {version_text(version)}"
    if module.version and not matches(version, version_bounds(module.name, module.version)):
        text += f", off the pin {module.version}" if module.go else f", outside {module.version}"
    return text


# Commands


def sync_module(source: Source) -> str:
    module = source.module
    if source.kind == "pinned":
        ensure_clone(source)
        ensure_commit(source, module.ref)
        clone = source.checkout
        populated = is_populated(clone)
        if not populated or git(clone, "rev-parse", "HEAD") != module.ref:
            if populated and is_dirty(clone):
                raise ModuleError(
                    f"module {module.name}: {clone} has local changes; commit them in a local path "
                    "(~/.se/local.toml [paths]) or discard them"
                )
            git(clone, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", module.ref)
    if not source.dir.is_dir():
        at = "the local path" if source.kind == "local" else module.ref[:7]
        raise ModuleError(f"module {module.name}: path {module.path} does not exist at {at}")
    if source.kind == "pinned":
        state = module.ref[:12] + (f", {module.go} v{module.version} locked" if module.go
                                   else f", {module.version} locked" if module.version else "")
    else:
        state = f"working tree as is, {version_report(source)}"
    return _with_note(f"{module.name}: {source.kind} {source.dir} ({state})", source)


def _with_note(line: str, source: Source) -> str:
    return f"{line} [{source.note}]" if source.note else line


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def range_state(source: Source) -> str:
    """For a pinned module with a range: a newer admitted tag its clone knows (status never fetches)."""
    newest = newest_matching(source) if is_populated(source.checkout) else None
    if newest and newest[1] != source.module.ref:
        return f"{newest[0]} available: run update"
    return ""


def status_state(source: Source) -> str:
    pin = source.module.ref
    checkout = source.checkout
    if not pin:
        return f"version {source.module.version} not locked (run sync)"
    if source.kind == "pinned":
        if not is_populated(checkout):
            return "not synced (run sync)"
        head = git(checkout, "rev-parse", "HEAD")
        if head != pin:
            return f"at {head[:7]}, pin {pin[:7]}: run sync"
        return "at pin, uncommitted changes" if is_dirty(checkout) else "at pin"
    if not is_checkout_root(checkout):
        return "not a git checkout; drift unknown"
    head = git(checkout, "rev-parse", "HEAD")
    parts = []
    if not has_commit(checkout, pin):
        parts.append(f"HEAD {head[:7]}, pin not in local checkout (fetch it)")
    else:
        behind, ahead = (int(n) for n in git(checkout, "rev-list", "--left-right", "--count", f"{pin}...HEAD").split())
        if ahead:
            parts.append(f"{ahead} ahead of pin")
        if behind:
            parts.append(f"{behind} behind pin")
        if not ahead and not behind:
            parts.append("at pin")
    if is_dirty(checkout):
        parts.append("uncommitted changes")
    return ", ".join(parts)


def status_line(source: Source) -> str:
    module = source.module
    pin = (f"{module.go} v{module.version}, pin {module.ref[:7] or 'none'}" if module.go
           else f"version {module.version}, pin {module.ref[:7] or 'none'}" if module.version
           else f"pin {module.ref[:7]}")
    state = status_state(source)
    if module.version and module.ref and source.kind == "pinned":
        state = ", ".join(filter(None, [state, range_state(source)]))
    if source.kind == "local":
        state = f"{state}, {version_report(source)}"
    return _with_note(f"{module.name}: {source.kind} {source.dir} ({pin}): {state}", source)


def set_pin(root: Path, name: str, sha: str) -> None:
    """Rewrite only the `ref` value of `[modules.<name>]`, keeping the file otherwise byte for byte."""
    manifest = root / MANIFEST
    text = manifest.read_bytes().decode("utf-8")
    quoted = re.escape(name)
    header = re.compile(rf"""^\s*\[\s*modules\s*\.\s*(?:{quoted}|"{quoted}"|'{quoted}')\s*\]\s*(?:#.*)?$""")
    any_header = re.compile(r"^\s*\[")
    ref_line = re.compile(r"""^(\s*ref\s*=\s*)(["'])[0-9a-fA-F]{40}\2""")
    lines = text.splitlines(keepends=True)
    inside = found = False
    for index, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        if any_header.match(bare):
            inside = bool(header.match(bare))
            continue
        match = ref_line.match(bare) if inside else None
        if match:
            lines[index] = f"{match.group(1)}{match.group(2)}{sha}{match.group(2)}{line[match.end():]}"
            found = True
            break
    if not found:
        raise ModuleError(f'{manifest}: write the pin of {name} as ref = "<sha>" inside [modules.{name}]')
    manifest.write_bytes("".join(lines).encode("utf-8"))
    if {m.name: m.ref for m in load_manifest(root)}.get(name) != sha:
        raise ModuleError(f"{manifest}: rewriting the pin of {name} failed")


def regenerate_workflows(root: Path, module: Module, clone: Path, commit: str) -> list[str]:
    """Regenerate the project's copies of SE's workflows and actions at SE's new pin `commit`
    (scripts/se_workflows.py), so they run the version the pin names; one report line per file."""
    import se_workflows
    if module.name != se_workflows.MODULE or not se_workflows.held(root):
        return []
    try:
        plan = se_workflows.plan(root, [], ref=commit, source=clone)
        return [f"  {line}" for line in se_workflows.write(root, plan)]
    except se_workflows.WorkflowError as error:
        raise ModuleError(f"module {module.name}: {error}") from error


def resolve_target(source: Source, to: str | None) -> str:
    clone = source.checkout
    candidates = [f"refs/remotes/origin/{TRACKED_BRANCH}"] if to is None else [f"refs/remotes/origin/{to}", f"refs/tags/{to}", to]
    for candidate in candidates:
        if has_commit(clone, candidate):
            return git(clone, "rev-parse", "--verify", f"{candidate}^{{commit}}")
    if to is not None and SHA_RE.match(to) and git_ok(clone, "fetch", "--quiet", "origin", to):
        return git(clone, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
    raise ModuleError(f"module {source.module.name}: {to or TRACKED_BRANCH} not found in {source.url}")


def update_module(root: Path, module: Module, local: LocalConfig, to: str | None) -> list[str]:
    """Move the pin to the newest `main` commit (or to `to`), or a range's lock to its highest
    admitted tag; report the commits between, regenerate SE's workflows in the project at the new
    pin (regenerate_workflows) and sync."""
    pinned = pinned_source(root, module, local)
    if module.go:
        raise ModuleError(
            f"module {module.name}: pinned by {module.go}'s require {module.name} v{module.version}; "
            "change that line and run sync instead"
        )
    if module.version is not None:
        if to is not None:
            raise ModuleError(
                f"module {module.name}: pinned by version {module.version!r}; change the range in "
                f"{root / MANIFEST} instead of passing --to"
            )
        new = resolve_range(root, pinned).ref
        label = f"highest tag matching {module.version}"
    else:
        ensure_clone(pinned)
        fetch(pinned.checkout)
        new = resolve_target(pinned, to)
        label = to or TRACKED_BRANCH
    old = module.ref
    if not old:
        report = [f"{module.name}: locked at {new[:7]} ({label})"]
    elif new == old:
        report = [f"{module.name}: already at {new[:7]} ({label})"]
    else:
        report = [f"{module.name}: {old[:7]} -> {new[:7]} ({label})"]
        if has_commit(pinned.checkout, old):
            added = log_lines(pinned.checkout, f"{old}..{new}")
            dropped = log_lines(pinned.checkout, f"{new}..{old}")
            if added:
                report.append(f"  {_plural(len(added), 'commit')} added:")
                report.extend(f"    {line}" for line in added)
            if dropped:
                report.append(f"  {_plural(len(dropped), 'commit')} dropped (the pin moves back):")
                report.extend(f"    {line}" for line in dropped)
        else:
            report.append(f"  previous pin {old[:7]} is not in {pinned.url}; range unknown")
        if module.version is None:
            set_pin(root, module.name, new)
    report.extend(regenerate_workflows(root, module, pinned.checkout, new))
    moved = Module(module.name, module.url, new, module.path, module.version, module.go)
    report.append(sync_module(resolve(root, moved, local)))
    return report


def select(modules: list[Module], names: list[str]) -> list[Module]:
    unknown = sorted(set(names) - {m.name for m in modules})
    if unknown:
        raise ModuleError(f"unknown module(s): {', '.join(unknown)}")
    return [m for m in modules if not names or m.name in names]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, help=f"repository with {MANIFEST}; default: nearest ancestor of the current directory")
    parser.add_argument("--local", type=Path, help="machine-local configuration; default: ~/.se/local.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="bring modules to their pins, or use their local paths")
    sync.add_argument("names", nargs="*", help="modules; default: all")
    status = commands.add_parser("status", help="show the source of each module and its drift from the pin")
    status.add_argument("names", nargs="*", help="modules; default: all")
    update = commands.add_parser("update", help=f"move pins to the newest {TRACKED_BRANCH} commit and sync")
    update.add_argument("name", nargs="?", help="module to update")
    update.add_argument("--to", help="branch, tag or commit instead of the newest main commit")
    update.add_argument("--all", action="store_true", help="update every module")
    path = commands.add_parser("path", help="print the directory a module is used from")
    path.add_argument("name")
    commands.add_parser("kern-pin", help="print the version of the kern --root pins and where its release is "
                        "published, on one line (bootstrap.sh reads it)")
    app = commands.add_parser("app-binary", help="print the application binary bootstrap.sh fetches, builds "
                              "and starts: name, version, download base, build folder, package and the "
                              "checkout it was read from, on one line")
    app.add_argument("--project", type=Path, help="the session's project: where it is SE's own checkout, "
                     "its pins are read instead of --root's")
    commands.add_parser("hooks-core", help="print whether SE's session hooks start the core and the layer "
                        "that answered (SE_HOOK_CORE, else [hooks] core of --local), on one line; "
                        "needs no se.toml (bootstrap.sh reads it)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "update" and (args.all == bool(args.name) or (args.all and args.to)):
        parser.error("update takes a module name (optionally with --to) or --all")
    failed = False
    if args.command == "hooks-core":
        try:
            local = load_local(args.local or default_local_config())
        except ModuleError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(*hooks_core(os.environ, local))
        return 0
    try:
        root = args.root.resolve() if args.root else find_root(Path.cwd())
        if args.command == "kern-pin":
            print(kern_pin(root)[0], kern_download(root) or NO_BASE)
            return 0
        if args.command == "app-binary":
            source = app_root(root, args.project)
            b = app_binary(source)
            print(b.name, b.version, b.download or NO_BASE, b.build_dir, b.package, source.as_posix())
            return 0
        local = load_local(args.local or default_local_config())
        modules = load_manifest(root)
        if args.command == "path":
            print(resolve(root, select(modules, [args.name])[0], local).dir)
            return 0
        names = [args.name] if args.command == "update" and args.name else getattr(args, "names", [])
        for module in select(modules, names):
            try:
                if args.command == "sync":
                    source = resolve(root, module, local)
                    if source.kind == "pinned":
                        source = resolve(root, lock_range(root, module, local), local)
                    print(sync_module(source))
                elif args.command == "status":
                    print(status_line(resolve(root, module, local)))
                elif args.all and module.go:
                    print(f"{module.name}: pinned by {module.go}, left as it is")
                else:
                    print("\n".join(update_module(root, module, local, args.to)))
            except ModuleError as error:
                print(f"error: {error}", file=sys.stderr)
                failed = True
    except ModuleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
