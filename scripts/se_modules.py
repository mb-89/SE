"""Pull dependencies into a repository as modules pinned to commits.

The format and the commands are described once in the README section "Modules".
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

MANIFEST = "se.toml"
MODULES_DIR = Path(".se") / "modules"
TRACKED_BRANCH = "main"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MODULE_KEYS = {"url", "ref", "path"}


class ModuleError(Exception):
    """A user-facing error: bad configuration or a failed git step."""


@dataclass(frozen=True)
class Module:
    name: str
    url: str
    ref: str
    path: str | None = None


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


def load_manifest(root: Path) -> list[Module]:
    """Read and validate the modules declared in `<root>/se.toml`."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ModuleError(f"no {MANIFEST} in {root}")
    tables = _read_toml(manifest).get("modules", {})
    if not isinstance(tables, dict):
        raise ModuleError(f"{MANIFEST}: [modules] must be a table")
    modules = []
    for name, table in tables.items():
        if not NAME_RE.match(name):
            raise ModuleError(f"module name {name!r}: use letters, digits, '.', '_' and '-'")
        if not isinstance(table, dict):
            raise ModuleError(f"module {name}: [modules.{name}] must be a table")
        unknown = sorted(set(table) - MODULE_KEYS)
        if unknown:
            raise ModuleError(f"module {name}: unknown key(s) {', '.join(unknown)}")
        url, ref = table.get("url"), table.get("ref")
        if not isinstance(url, str) or not url:
            raise ModuleError(f"module {name}: url is required")
        if not isinstance(ref, str) or not ref:
            raise ModuleError(f"module {name}: ref is required")
        if not SHA_RE.match(ref):
            raise ModuleError(f"module {name}: ref must be a full commit SHA, got {ref!r}")
        path = _check_subpath(name, table["path"]) if "path" in table else None
        modules.append(Module(name, url, ref.lower(), path))
    return modules


@dataclass(frozen=True)
class LocalConfig:
    """Machine-local settings from `~/.se/local.toml`; only read, never written."""

    paths: dict[str, Path]
    urls: dict[str, str]

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
    unknown = sorted(set(data) - {"paths", "urls"})
    if unknown:
        raise ModuleError(f"{config}: unknown section(s) {', '.join(unknown)}")
    paths = {
        name: (config.parent / Path(value).expanduser()).resolve()
        for name, value in _string_table(config, data, "paths").items()
    }
    return LocalConfig(paths=paths, urls=_string_table(config, data, "urls"))


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


def find_root(start: Path) -> Path:
    for directory in [start, *start.parents]:
        if (directory / MANIFEST).is_file():
            return directory
    raise ModuleError(f"no {MANIFEST} in {start} or its parents")


# Git


def _run_git(cwd: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


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
    git(clone, "fetch", "--quiet", "--prune", "--tags", "origin")


def ensure_commit(source: Source, sha: str) -> None:
    clone = source.checkout
    if has_commit(clone, sha):
        return
    fetch(clone)
    if not has_commit(clone, sha) and not (git_ok(clone, "fetch", "--quiet", "origin", sha) and has_commit(clone, sha)):
        raise ModuleError(f"module {source.module.name}: commit {sha} not found in {source.url}")


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
    state = f"{module.ref[:12]}" if source.kind == "pinned" else "working tree as is"
    return _with_note(f"{module.name}: {source.kind} {source.dir} ({state})", source)


def _with_note(line: str, source: Source) -> str:
    return f"{line} [{source.note}]" if source.note else line


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def status_state(source: Source) -> str:
    pin = source.module.ref
    checkout = source.checkout
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
    line = f"{module.name}: {source.kind} {source.dir} (pin {module.ref[:7]}): {status_state(source)}"
    return _with_note(line, source)


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
    """Move the pin to the newest `main` commit (or to `to`), report the range and sync."""
    pinned = Source(module, "pinned", root / MODULES_DIR / module.name, local.rewrite(module.url))
    ensure_clone(pinned)
    fetch(pinned.checkout)
    new = resolve_target(pinned, to)
    old = module.ref
    label = to or TRACKED_BRANCH
    if new == old:
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
        set_pin(root, module.name, new)
    moved = Module(module.name, module.url, new, module.path)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "update" and (args.all == bool(args.name) or (args.all and args.to)):
        parser.error("update takes a module name (optionally with --to) or --all")
    failed = False
    try:
        root = args.root.resolve() if args.root else find_root(Path.cwd())
        local = load_local(args.local or default_local_config())
        modules = load_manifest(root)
        if args.command == "path":
            print(resolve(root, select(modules, [args.name])[0], local).dir)
            return 0
        names = [args.name] if args.command == "update" and args.name else getattr(args, "names", [])
        for module in select(modules, names):
            try:
                if args.command == "sync":
                    print(sync_module(resolve(root, module, local)))
                elif args.command == "status":
                    print(status_line(resolve(root, module, local)))
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
