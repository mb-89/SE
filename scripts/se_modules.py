"""Pull a repository's components in, found by name and pinned to commits or semantic version ranges.

The format and the commands are described once in the README section "Modules"; how a component is
found on the checkout's remotes is docs/components.md "Finding a component", which this script owns.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import git_door
import se_home
MANIFEST = "se.toml"
LOCK = "se.lock"
MODULES_DIR = Path(".se") / "modules"
#: The se.toml table of a host's components (README "Modules"); se 6 renamed it from [modules].
COMPONENTS = "components"
#: kern, the Go core, as se.toml [components.kern] pins it (README "Modules").
KERN = "kern"
#: The repository topic that marks a component (docs/components.md "A component").
TOPIC = "component"
#: The listing of an owner's marked repositories: unset, the host's own; `off`, none (every
#: component read directly beside its remote); `fake:<file>`, a JSON object mapping
#: `<host>/<owner>` to the names listed or to the reason the owner cannot be listed (the tests').
LISTING_VARIABLE = "SE_COMPONENT_LISTING"
LISTING_TIMEOUT = 20


def kern_dir(root: Path) -> Path:
    """Where kern is for the checkout at `root`: its pinned clone, `<root>/.se/modules/kern`, which
    `se_modules.py sync kern` places (its Go module, its Python SDK under `python/`)."""
    return root / MODULES_DIR / KERN

TRACKED_BRANCH = "main"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: A component's name: its repository's, 1 to 32 letters, digits and dashes (docs/components.md).
COMPONENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,31}$")
COMPONENT_KEYS = {"ref", "version", "path", "go", "optional"}
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
    """A declared component; `ref` is its pin, for a `version` range the locked commit ("" unlocked).
    It names no address: the finder finds it by name (docs/components.md "Finding a component")."""

    name: str
    ref: str
    path: str | None = None
    version: str | None = None
    #: For a `go` pin: the `go.mod` (relative to the root) whose `require <name>` is the version.
    go: str | None = None
    #: `optional = true`: the host works without it; an entry without it is required.
    optional: bool = False

    @property
    def pin(self) -> str:
        """The pin as the host's list states it."""
        if self.go:
            return f"{self.go} v{self.version}"
        return self.version if self.version else f"ref {self.ref[:12]}"

    def admits(self, version: Version | None, commit: str) -> bool:
        """Whether this pin admits the release `version` at `commit`."""
        if self.go:
            return version is not None and version == parse_version(self.version)
        if self.version:
            return version is not None and matches(version, version_bounds(self.name, self.version))
        return commit.lower() == self.ref


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
    """`se.lock`: per component of the tree pinned by a range or a go.mod, the resolved (version, commit)."""
    lock = root / LOCK
    if not lock.is_file():
        return {}
    entries = {}
    for name, table in _read_toml(lock).get(COMPONENTS, {}).items():
        version = table.get("version") if isinstance(table, dict) else None
        ref = table.get("ref") if isinstance(table, dict) else None
        if parse_version(version) is None or not isinstance(ref, str) or not SHA_RE.match(ref):
            raise ModuleError(f"{lock}: [{COMPONENTS}.{name}] needs version and a full commit ref; delete it and run sync")
        entries[name] = (version, ref.lower())
    return entries


def write_lock(root: Path, entries: dict[str, tuple[str, str]]) -> None:
    """Write `se.lock` with exactly `entries`, the (version, commit) of each component of the tree
    pinned by a range or a go.mod; nothing is written where it holds them already."""
    if entries == read_lock(root) and (entries or not (root / LOCK).is_file()):
        return
    lines = [f"# {LOCK}: the commits scripts/se_modules.py resolved for the version ranges and go.mod pins "
             f"of the components {MANIFEST} lists, and of theirs.",
             "# Written by sync and update; commit it, never edit it."]
    for key in sorted(entries):
        locked_version, locked_ref = entries[key]
        lines += ["", f"[{COMPONENTS}.{key}]", f'version = "{locked_version}"', f'ref = "{locked_ref}"']
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
    return go_require_in(lambda relative: _read_file(root / relative), str(root), name, value)


def go_require_in(read: Callable[[str], str | None], where: str, name: str, value: object) -> tuple[str, str]:
    """`go_require` of a host's tree that `read` gives by relative path, named `where`."""
    if value is True:
        relative = "go.mod"
    elif isinstance(value, str) and value:
        relative = _check_subpath(name, value)
    else:
        raise ModuleError(f"module {name}: go must be true or a relative path to a go.mod")
    text = read(relative)
    if text is None:
        raise ModuleError(f"module {name}: no {relative} in {where}, which go names")
    block = False
    for line in text.splitlines():
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


RENAMED = (f"[modules] is [{COMPONENTS}] since se 6: rename each [modules.<name>] to "
           f"[{COMPONENTS}.<name>] and drop its url, as a component is found by its name (README \"Modules\")")


def load_manifest(root: Path) -> list[Module]:
    """Read and validate the components `<root>/se.toml` lists, each range's lock applied."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ModuleError(f"no {MANIFEST} in {root}")
    data = _read_toml(manifest)
    if "modules" in data:
        raise ModuleError(f"{manifest}: {RENAMED}")
    return parse_components(data, MANIFEST, lambda relative: _read_file(root / relative), read_lock(root))


def _read_file(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def parse_components(data: dict, where: str, read: Callable[[str], str | None],
                     locked: dict[str, tuple[str, str]]) -> list[Module]:
    """The `[components]` of a host's se.toml `data` (its file named `where`); `read` gives a file
    of the host's tree by its relative path (a `go` pin's go.mod), `locked` the root's se.lock."""
    tables = data.get(COMPONENTS, {})
    if not isinstance(tables, dict):
        raise ModuleError(f"{where}: [{COMPONENTS}] must be a table")
    modules = []
    for name, table in tables.items():
        if not COMPONENT_NAME_RE.match(name):
            raise ModuleError(f"component name {name!r} in {where}: 1 to 32 letters, digits and '-', "
                              "starting with a letter or digit, as its repository is named")
        if not isinstance(table, dict):
            raise ModuleError(f"component {name}: [{COMPONENTS}.{name}] must be a table")
        if "url" in table:
            raise ModuleError(
                f"component {name}: url is refused in {where}: a component is found by its name under "
                "the owners of the checkout's remotes (docs/components.md \"Finding a component\"); a "
                "machine that needs another place sets [paths] or [urls] in ~/.se/local.toml")
        unknown = sorted(set(table) - COMPONENT_KEYS)
        if unknown:
            raise ModuleError(f"component {name}: unknown key(s) {', '.join(unknown)}")
        optional = table.get("optional", False)
        if not isinstance(optional, bool):
            raise ModuleError(f"component {name}: optional must be true or false")
        ref, version = table.get("ref"), table.get("version")
        path = _check_subpath(name, table["path"]) if "path" in table else None
        locked_version, locked_ref = locked.get(name, ("", ""))
        if "go" in table:
            if ref is not None or version is not None:
                raise ModuleError(f"component {name}: go pins the version; drop ref and version")
            gomod, exact = go_require_in(read, where, name, table["go"])
            modules.append(Module(name, locked_ref if locked_version == exact else "", path, exact, gomod,
                                  optional))
            continue
        if version is not None:
            if ref is not None:
                raise ModuleError(f"component {name}: pin either ref or version, not both")
            if not isinstance(version, str):
                raise ModuleError(f"component {name}: version must be a semver range string such as \"^1.4\"")
            bounds = version_bounds(name, version)
            ok = parse_version(locked_version) is not None and matches(parse_version(locked_version), bounds)
            modules.append(Module(name, locked_ref if ok else "", path, version, None, optional))
            continue
        if not isinstance(ref, str) or not ref:
            raise ModuleError(f"component {name}: ref or version is required")
        if not SHA_RE.match(ref):
            raise ModuleError(f"component {name}: ref must be a full commit SHA, got {ref!r}")
        modules.append(Module(name, ref.lower(), path, None, None, optional))
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
    """Where a component comes from on this machine; `url` is the address the finder found ("" not
    found yet: a placed clone is used without asking any remote)."""

    module: Module
    kind: str  # "local" or "pinned"
    checkout: Path
    url: str = ""
    note: str = ""

    @property
    def dir(self) -> Path:
        return self.checkout / self.module.path if self.module.path else self.checkout


def resolve(root: Path, module: Module, local: LocalConfig) -> Source:
    """Use the local checkout if it exists, else the pinned clone in `.se/modules/<name>`."""
    note = ""
    local_path = local.paths.get(module.name)
    if local_path is not None:
        if local_path.is_dir():
            return Source(module, "local", local_path)
        note = f"local path missing: {local_path}"
    return Source(module, "pinned", root / MODULES_DIR / module.name, "", note)


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
    """(version, tag) of the kern `root` pins: the version `[components.kern]` reads from the go.mod
    its `go` names (README "Modules"), and the tag the pinned clone's `release.toml` names for it,
    the last part of its `download` (kern's README "Release")."""
    manifest = root / MANIFEST
    table = (_read_toml(manifest).get(COMPONENTS, {}) if manifest.is_file() else {}).get(KERN)
    if not isinstance(table, dict) or "go" not in table:
        raise ModuleError(f"no [{COMPONENTS}.{KERN}] with go in {manifest}: it pins no kern")
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
    """Create or reuse the component's clone in `.se/modules/<name>`, its origin the found address."""
    clone = source.checkout
    if (clone / ".git").exists():
        if source.url and git(clone, "remote", "get-url", "origin") != source.url:
            git(clone, "remote", "set-url", "origin", source.url)
        return
    if clone.exists() and any(clone.iterdir()):
        raise ModuleError(f"{clone} exists and is not a git clone; remove it")
    if not source.url:
        raise ModuleError(f"component {source.module.name}: no address found to clone it from")
    clone.parent.mkdir(parents=True, exist_ok=True)
    git(clone.parent, "clone", "--quiet", "--no-checkout", source.url, str(clone))


def is_populated(clone: Path) -> bool:
    """A clone made with --no-checkout has no index until its first checkout."""
    return (clone / ".git" / "index").exists()


def holds(clone: Path, sha: str) -> bool:
    """Whether the clone `.se/modules/<name>` exists and holds the commit `sha`."""
    return bool(sha) and (clone / ".git").exists() and has_commit(clone, sha)


def fetch(clone: Path) -> None:
    """Fetch branches and tags; `--force` follows tags the upstream moved, the lock still pins the commit."""
    git(clone, "fetch", "--quiet", "--force", "--prune", "--tags", "origin")


def ensure_commit(source: Source, sha: str) -> None:
    clone = source.checkout
    if has_commit(clone, sha):
        return
    fetch(clone)
    if not has_commit(clone, sha) and not (git_ok(clone, "fetch", "--quiet", "origin", sha) and has_commit(clone, sha)):
        raise ModuleError(f"module {source.module.name}: commit {sha} not found in {source.url or 'its clone'}")


def tagged_versions(clone: Path) -> dict[Version, str]:
    """The clone's `vMAJOR.MINOR.PATCH` tags by version; other tags are ignored."""
    output = git(clone, "tag", "--list", "v*")
    return {version: tag for tag in output.splitlines() if (version := parse_version(tag[1:])) is not None}


def clone_releases(clone: Path) -> dict[Version, str]:
    """The clone's releases: each `v` tag's version and the commit it points to."""
    return {version: git(clone, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
            for version, tag in tagged_versions(clone).items()}


def newest_matching(source: Source) -> tuple[str, str] | None:
    """The highest tagged version the module's range admits in its clone, and its commit."""
    module = source.module
    bounds = version_bounds(module.name, module.version or "")
    admitted = [version for version in tagged_versions(source.checkout) if matches(version, bounds)]
    if not admitted:
        return None
    best = max(admitted)
    return version_text(best), git(source.checkout, "rev-parse", "--verify", f"refs/tags/v{version_text(best)}^{{commit}}")


# Finding a component (docs/components.md "Finding a component")


class Unlisted(Exception):
    """The host cannot list this owner's repositories (an unknown owner, no login for a private
    one): one line naming the remote, the owner and why, and finding goes on with the next owner."""


class NoListing(Exception):
    """The host offers no listing of the owner's repositories: the repository beside the remote is
    read directly, its mark unchecked."""


def github_listing(owner: str) -> dict[str, str]:
    """The repositories of `owner` on github.com that carry the topic `component`, by lowercase
    name, through GitHub's search with the person's login where the environment holds one
    (`GH_TOKEN`, `GITHUB_TOKEN`); a refused login is retried without it."""
    query = urllib.parse.quote(f"topic:{TOPIC} user:{owner}")
    url = f"https://api.github.com/search/repositories?q={query}&per_page=100"
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    for login in ([token, None] if token else [None]):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "se-modules"}
        if login:
            headers["Authorization"] = f"Bearer {login}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=LISTING_TIMEOUT) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 401 and login:
                continue
            if error.code in (404, 422):
                raise Unlisted(f"github.com knows no owner {owner} it can list (HTTP {error.code})") from None
            raise NoListing(f"github.com answered HTTP {error.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise NoListing(f"github.com could not be read: {getattr(error, 'reason', error)}") from None
        items = data.get("items") if isinstance(data, dict) else None
        return {str(item["name"]).lower(): str(item["name"]) for item in items or []
                if isinstance(item, dict) and isinstance(item.get("name"), str)}
    raise NoListing("github.com refused the login")


def host_listing(host: str, owner: str) -> dict[str, str]:
    """The repositories of `owner` on `host` marked `component`, by lowercase name; `Unlisted`
    where the owner cannot be listed, `NoListing` where the host offers no listing (any host but
    github.com, or `SE_COMPONENT_LISTING=off`)."""
    setting = os.environ.get(LISTING_VARIABLE, "")
    if setting == "off":
        raise NoListing(f"{LISTING_VARIABLE}=off")
    if setting.startswith("fake:"):
        listed = json.loads(Path(setting[len("fake:"):]).read_text(encoding="utf-8"))
        entry = listed.get(f"{host}/{owner}".lower())
        if entry is None:
            raise NoListing(f"the fake listing of {LISTING_VARIABLE} holds no {host}/{owner}")
        if isinstance(entry, str):
            raise Unlisted(entry)
        return {str(name).lower(): str(name) for name in entry}
    if host.lower() == se_home.GITHUB:
        return github_listing(owner)
    raise NoListing(f"SE lists no repositories on {host}")


@dataclass(frozen=True)
class Offer:
    """A component as one owner offers it: where it is reached and the releases its tags name."""

    name: str
    remote: str
    owner: str  # `<host>/<owner>`
    url: str  # the address beside the remote, the machine's [urls] rewrite applied
    releases: dict[Version, str]  # version -> commit, read without fetching objects


@dataclass
class Finding:
    """The first offer the pin admits, or None, with the remotes read and why each offered nothing."""

    offer: Offer | None
    read: list[str]
    reasons: list[str]


def remote_tags(url: str, cwd: Path) -> dict[Version, str]:
    """The `v` tags of the repository at `url`, read without fetching objects (`git ls-remote
    --tags`): version -> commit, an annotated tag by the commit it points to."""
    found: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in git(cwd, "ls-remote", "--tags", url).splitlines():
        sha, _, ref = line.partition("\t")
        tag = ref.removeprefix("refs/tags/")
        if tag.endswith("^{}"):
            peeled[tag[:-3]] = sha.lower()
        else:
            found[tag] = sha.lower()
    found.update(peeled)
    return {version: sha for tag, sha in found.items()
            if tag.startswith("v") and (version := parse_version(tag[1:])) is not None}


class Finder:
    """Finds a component by name under the owners of the checkout's remotes, in the order of
    docs/components.md "Finding a component": `origin` first, then the other remotes; each owner
    once, its marked repositories listed once per run; the first offer the pin admits wins."""

    def __init__(self, root: Path, local: LocalConfig,
                 listing: Callable[[str, str], dict[str, str]] | None = None) -> None:
        self.root, self.local = root, local
        self.listing = listing or host_listing
        self._remotes: list[tuple[str, str]] | None = None
        self._listed: dict[tuple[str, str], dict[str, str] | Exception] = {}
        self._tags: dict[str, dict[Version, str] | ModuleError] = {}
        #: Lines the run prints once each: an owner not listed, a mark not checked.
        self.notes: list[str] = []

    def _note(self, line: str) -> None:
        if line not in self.notes:
            self.notes.append(line)

    def remotes(self) -> list[tuple[str, str]]:
        if self._remotes is None:
            self._remotes = se_home.remotes(self.root)
        return self._remotes

    def _listed_names(self, host: str, owner: str) -> dict[str, str] | Exception:
        key = (host.lower(), owner.lower())
        if key not in self._listed:
            try:
                self._listed[key] = self.listing(host, owner)
            except (Unlisted, NoListing) as error:
                self._listed[key] = error
        return self._listed[key]

    def _releases(self, url: str) -> dict[Version, str] | ModuleError:
        if url not in self._tags:
            try:
                self._tags[url] = remote_tags(url, self.root)
            except ModuleError as error:
                self._tags[url] = error
        return self._tags[url]

    def offers(self, name: str, read: list[str], reasons: list[str]) -> Iterator[Offer]:
        """Each owner's offer of `name`, in the order of the remotes; `read` and `reasons` collect
        the remotes read and why one offered nothing."""
        seen: set[tuple[str, str]] = set()
        for remote, address in self.remotes():
            home = se_home.parse(address)
            if home is None:
                reasons.append(f"{remote}: its address names no host and owner, so it offers nothing")
                continue
            key = (home.host.lower(), home.owner.lower())
            if key in seen:
                continue
            seen.add(key)
            read.append(remote)
            owner = f"{home.host}/{home.owner}"
            listed = self._listed_names(home.host, home.owner)
            if isinstance(listed, Unlisted):
                self._note(f"{remote}: {home.host} cannot list the repositories of {home.owner}: {listed}")
                reasons.append(f"{remote}: {owner} could not be listed")
                continue
            if isinstance(listed, NoListing):
                self._note(f"{remote}: the mark of {owner}/{name} could not be checked ({listed}); "
                           "its repository is read directly")
                repository = name
            elif name.lower() in listed:
                repository = listed[name.lower()]
            else:
                reasons.append(f"{remote}: {owner} marks no repository {name} as a {TOPIC}")
                continue
            url = self.local.rewrite(se_home.beside(address, repository))
            releases = self._releases(url)
            if isinstance(releases, ModuleError):
                reasons.append(f"{remote}: {url} could not be read: {releases}")
                continue
            yield Offer(repository, remote, owner, url, releases)

    def find(self, name: str, admits: Callable[[Offer], bool]) -> Finding:
        """The first offer of `name` that `admits` takes."""
        read: list[str] = []
        reasons: list[str] = []
        for offer in self.offers(name, read, reasons):
            if admits(offer):
                return Finding(offer, read, reasons)
            reasons.append(f"{offer.remote}: {offer.url} offers no release the pin admits")
        return Finding(None, read, reasons)


def missing(module: Module, path: tuple[str, ...], finding: Finding) -> str:
    """Why a component was not found: its path from the root, the remotes read and the remedy."""
    kind = "optional" if module.optional else "required"
    read = ", ".join(finding.read) or "none"
    release = f" with a release its pin {module.pin} admits" if module.version else ""
    lines = [f"the {kind} component {module.name} is missing ({_arrow(path, module.name)}): no remote's "
             f"owner offers a repository {module.name} marked as a {TOPIC}{release} (read: {read})"]
    lines += [f"  {reason}" for reason in finding.reasons]
    lines.append("  Add a remote of an owner that offers it: git remote add <remote> <address>")
    return "\n".join(lines)


# Resolving the tree (docs/components.md "Several hosts, one tree")


@dataclass
class Placed:
    """A component of the tree: the source it is used from and the release placed there."""

    module: Module  # the first entry that named it
    path: tuple[str, ...]  # the host's path from the root
    source: Source
    version: str  # "" where no release names it (a ref pin, a local checkout without one)
    commit: str  # "" for a local checkout
    releases: dict[Version, str]  # what the source offered, for choosing again
    pins: list[tuple[tuple[str, ...], Module]] = field(default_factory=list)


class _Narrow(Exception):
    """A later host's pin does not admit the release chosen, but a common one exists: resolve again
    with that pin known from the start."""

    def __init__(self, key: str, pin: tuple[tuple[str, ...], Module]) -> None:
        super().__init__(key)
        self.key, self.pin = key, pin


def root_name(root: Path) -> str:
    """The root host's component name: its repository's, from origin (se_home), else its folder's."""
    found = se_home.find(root)
    return found.repository if found is not None else root.resolve().name


def _arrow(path: tuple[str, ...], name: str) -> str:
    return " -> ".join((*path, name))


def _components_of(placed: Placed, lock: dict[str, tuple[str, str]]) -> list[Module]:
    """The components a placed component's own se.toml lists, read from its release (a local
    checkout's working tree); a release whose se.toml lists none under [components] lists none."""
    source = placed.source
    if source.kind == "local":
        def read(relative: str) -> str | None:
            return _read_file(source.checkout / relative)
    else:
        def read(relative: str) -> str | None:
            result = _run_git(source.checkout, ("show", f"{placed.commit}:{relative}"))
            return result.stdout if result.returncode == 0 else None
    text = read(MANIFEST)
    if text is None:
        return []
    where = f"{MANIFEST} of {_arrow(placed.path, placed.module.name)}"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ModuleError(f"{where}: {error}") from error
    return parse_components(data, where, read, lock)


class Tree:
    """One resolution of the root's list and its components' lists, one release per name, each
    placed as a clone in `.se/modules/<name>` (or used from its local path)."""

    def __init__(self, root: Path, local: LocalConfig, finder: Finder | None = None,
                 unlock: frozenset[str] = frozenset()) -> None:
        self.root, self.local = root, local
        self.finder = finder or Finder(root, local)
        self.unlock = unlock
        self.lock = read_lock(root)
        self.name = root_name(root)

    def resolve(self, names: list[str] | None = None) -> tuple[list[Placed], list[str]]:
        """The placed components, root's list first, and the lines naming optional ones missing."""
        seeds: dict[str, list[tuple[tuple[str, ...], Module]]] = {}
        for _ in range(64):
            try:
                return self._once(names or [], seeds)
            except _Narrow as narrow:
                seeds.setdefault(narrow.key, []).append(narrow.pin)
        raise ModuleError("the components' pins keep choosing another release; align them")

    def _once(self, names: list[str], seeds: dict) -> tuple[list[Placed], list[str]]:
        placed: dict[str, Placed] = {}
        lines: list[str] = []
        queue = deque(((self.name,), module) for module in select(load_manifest(self.root), names))
        while queue:
            path, module = queue.popleft()
            key = module.name.lower()
            if key in (part.lower() for part in path):
                self._on_path(path, module, placed)
                continue
            if key in placed:
                self._again(placed[key], path, module)
                continue
            chosen = self._choose(path, module, [(path, module), *seeds.get(key, [])])
            if chosen is None:
                lines.append(f"optional component {_arrow(path, module.name)} not found on any remote's owner")
                continue
            placed[key] = chosen
            queue.extend(((*path, module.name), child) for child in _components_of(chosen, self.lock))
        return list(placed.values()), lines

    def _on_path(self, path: tuple[str, ...], module: Module, placed: dict[str, Placed]) -> None:
        """A name already on the path is that component: its pin is checked against it."""
        key = module.name.lower()
        if key == self.name.lower():
            version = checkout_version(self.root, go=module.go is not None)
            head = _run_git(self.root, ("rev-parse", "HEAD")).stdout.strip()
            if module.admits(version, head):
                return
            have = version_text(version) if version else "no version"
            raise ModuleError(f"component {module.name}: {_arrow(path, module.name)} pins {module.pin}, but "
                              f"{module.name} is the root, at {have}; change that pin")
        self._again(placed[key], path, module)

    def _again(self, chosen: Placed, path: tuple[str, ...], module: Module) -> None:
        """A name the tree reaches twice is one component: this pin must admit its release too."""
        chosen.pins.append((path, module))
        if chosen.source.kind == "local" or module.admits(parse_version(chosen.version), chosen.commit):
            return
        common = [version for version, commit in chosen.releases.items()
                  if all(pin.admits(version, commit) for _, pin in chosen.pins)]
        if common:
            raise _Narrow(module.name.lower(), (path, module))
        first_path, first = chosen.pins[0]
        raise ModuleError(
            f"component {module.name}: {_arrow(first_path, module.name)} pins {first.pin} and "
            f"{_arrow(path, module.name)} pins {module.pin}, and no release of {module.name} admits "
            "both; align the two pins")

    def _choose(self, path: tuple[str, ...], module: Module,
                pins: list[tuple[tuple[str, ...], Module]]) -> Placed | None:
        source = resolve(self.root, module, self.local)
        if source.kind == "local":
            version = checkout_version(source.checkout, go=module.go is not None)
            return Placed(module, path, source, version_text(version) if version else "", "", {}, list(pins))

        def ok(version: Version | None, commit: str) -> bool:
            return all(pin.admits(version, commit) for _, pin in pins)

        clone, name = source.checkout, module.name
        locked = self.lock.get(name) if module.version else None
        keep = name not in self.unlock
        if not module.version:  # a ref pin: its commit
            if keep and holds(clone, module.ref):
                return self._placed(module, path, source, "", module.ref, {}, pins)
            finding = self.finder.find(name, lambda offer: True)
            want = None
        elif keep and locked and ok(parse_version(locked[0]), locked[1]):
            if holds(clone, locked[1]):
                return self._placed(module, path, source, locked[0], locked[1], clone_releases(clone), pins)
            want = parse_version(locked[0])
            finding = self.finder.find(name, lambda offer: want in offer.releases)
        else:
            want = None
            finding = self.finder.find(
                name, lambda offer: any(ok(version, commit) for version, commit in offer.releases.items()))
        offer = finding.offer
        if offer is None:
            if module.optional:
                return None
            raise ModuleError(missing(module, path, finding))
        found = Source(module, "pinned", clone, offer.url, source.note)
        if not module.version:
            return self._placed(module, path, found, "", module.ref, offer.releases, pins)
        if want is not None:
            commit = offer.releases[want]
            if commit != locked[1]:
                raise ModuleError(
                    f"component {name}: the release v{locked[0]} that {offer.url} offers ({offer.remote}'s "
                    f"owner {offer.owner}) points to {commit}, but {LOCK} records {locked[1]}; a found "
                    f"release never replaces a locked one silently: run se_modules.py update {name} "
                    "to lock the found one")
            return self._placed(module, path, found, locked[0], commit, offer.releases, pins)
        best = max(version for version, commit in offer.releases.items() if ok(version, commit))
        return self._placed(module, path, found, version_text(best), offer.releases[best], offer.releases, pins)

    def _placed(self, module: Module, path: tuple[str, ...], source: Source, version: str, commit: str,
                releases: dict[Version, str], pins: list) -> Placed:
        """Place the release in the clone (fetched where it lacks the commit) and record it."""
        ensure_clone(source)
        ensure_commit(source, commit)
        if not releases and module.version:
            releases = clone_releases(source.checkout)
        moved = Module(module.name, commit, module.path, module.version, module.go, module.optional)
        return Placed(moved, path, Source(moved, source.kind, source.checkout, source.url, source.note),
                      version, commit, releases, list(pins))


def sync_tree(root: Path, local: LocalConfig, names: list[str] | None = None,
              finder: Finder | None = None, unlock: frozenset[str] = frozenset()) -> list[str]:
    """`sync`: resolve the tree (the root's components named in `names`, default all, and theirs),
    check each placed one out at its release, lock what ranges and go.mod pins chose; one line each,
    then the finder's notes and the optional components missing."""
    tree = Tree(root, local, finder, unlock)
    placed, missing_lines = tree.resolve(names)
    lines = [sync_module(item.source) + (f" (for {' -> '.join(item.path[1:])})" if len(item.path) > 1 else "")
             for item in placed]
    entries = dict(tree.lock) if names else {}  # a partial sync keeps the others' entries
    for item in placed:
        name = item.module.name
        if item.source.kind == "pinned" and item.module.version:
            entries[name] = (item.version, item.commit)
        elif item.source.kind == "local" and name in tree.lock:
            entries[name] = tree.lock[name]  # a local checkout leaves its lock as it is
    write_lock(root, entries)
    return [*lines, *tree.finder.notes, *missing_lines]


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
    """Rewrite only the `ref` value of `[components.<name>]`, keeping the file otherwise byte for byte."""
    manifest = root / MANIFEST
    text = manifest.read_bytes().decode("utf-8")
    quoted = re.escape(name)
    header = re.compile(rf"""^\s*\[\s*{COMPONENTS}\s*\.\s*(?:{quoted}|"{quoted}"|'{quoted}')\s*\]\s*(?:#.*)?$""")
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
        raise ModuleError(f'{manifest}: write the pin of {name} as ref = "<sha>" inside [{COMPONENTS}.{name}]')
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


def update_module(root: Path, module: Module, local: LocalConfig, to: str | None,
                  finder: Finder | None = None) -> list[str]:
    """Find the component again, then move its pin to the newest `main` commit (or to `to`), or a
    range's lock to its highest admitted release the first owner offers; report the commits
    between, regenerate SE's workflows in the project at the new pin (regenerate_workflows) and
    sync."""
    if module.go:
        raise ModuleError(
            f"module {module.name}: pinned by {module.go}'s require {module.name} v{module.version}; "
            "change that line and run sync instead"
        )
    finder = finder or Finder(root, local)
    pinned = Source(module, "pinned", root / MODULES_DIR / module.name)
    if module.version is not None:
        if to is not None:
            raise ModuleError(
                f"module {module.name}: pinned by version {module.version!r}; change the range in "
                f"{root / MANIFEST} instead of passing --to"
            )
        bounds = version_bounds(module.name, module.version)
        finding = finder.find(module.name, lambda offer: any(matches(v, bounds) for v in offer.releases))
        if finding.offer is None:
            raise ModuleError(missing(module, (root_name(root),), finding))
        best = max(v for v in finding.offer.releases if matches(v, bounds))
        new = finding.offer.releases[best]
        pinned = Source(module, "pinned", pinned.checkout, finding.offer.url)
        ensure_clone(pinned)
        ensure_commit(pinned, new)
        write_lock(root, {**read_lock(root), module.name: (version_text(best), new)})
        label = f"highest tag matching {module.version}"
    else:
        finding = finder.find(module.name, lambda offer: True)
        if finding.offer is None:
            raise ModuleError(missing(module, (root_name(root),), finding))
        pinned = Source(module, "pinned", pinned.checkout, finding.offer.url)
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
    moved = Module(module.name, new, module.path, module.version, module.go, module.optional)
    source = resolve(root, moved, local)
    report.append(sync_module(Source(moved, source.kind, source.checkout, pinned.url, source.note)))
    return report + finder.notes


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
    sync = commands.add_parser("sync", help="find the components and theirs by name, place each at its pin, "
                               "or use their local paths")
    sync.add_argument("names", nargs="*", help="components of the root's list; default: all")
    status = commands.add_parser("status", help="show the source of each component and its drift from the pin")
    status.add_argument("names", nargs="*", help="components; default: all")
    update = commands.add_parser("update", help=f"find a component again, move its pin to the newest "
                                 f"{TRACKED_BRANCH} commit (a range's lock to its newest release) and sync")
    update.add_argument("name", nargs="?", help="component to update")
    update.add_argument("--to", help="branch, tag or commit instead of the newest main commit")
    update.add_argument("--all", action="store_true", help="update every component")
    path = commands.add_parser("path", help="print the directory a component is used from")
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
        if args.command == "sync":
            select(modules, names)
            print("\n".join(sync_tree(root, local, names)))
            return 0
        finder = Finder(root, local)
        for module in select(modules, names):
            try:
                if args.command == "status":
                    print(status_line(resolve(root, module, local)))
                elif args.all and module.go:
                    print(f"{module.name}: pinned by {module.go}, left as it is")
                else:
                    print("\n".join(update_module(root, module, local, args.to, finder)))
            except ModuleError as error:
                print(f"error: {error}", file=sys.stderr)
                failed = True
    except ModuleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
