"""Generate the Copilot and Claude Code layouts of the se plugin from its one source in `src/`.

Every agent (`src/agents/<name>.md`) and every skill (`src/skills/<name>/...`) is written once.
`build` writes both layouts and the Claude Code plugin manifests; `check` refuses when any generated
file differs from what `build` would write, so a hand edit to a generated file fails. Where each
layout is installed from is the README section "Install".

Source front matter is one `key: value` per line. A key prefixed `copilot.` or `claude.` goes only
into that layout, without its prefix; every other key goes into both.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE = PurePosixPath("src")
PLUGIN = "se"
OWNER = "mb-89"
REPOSITORY = "https://github.com/mb-89/SE"
DESCRIPTION = ("SE, the agent a person talks to, with its integrator and worker sub-agents and "
               "their skills.")
BOOTSTRAP = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh"'
LINK = re.compile(r"(\]\()([^)\s#]+)((?:#[^)\s]*)?\))")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class Layout:
    """Where one host reads agents and skills, relative to the repository root."""

    name: str
    agents: PurePosixPath
    agent_suffix: str
    skills: PurePosixPath


LAYOUTS = (
    Layout("copilot", PurePosixPath(".github/agents"), ".agent.md", PurePosixPath(".github/skills")),
    Layout("claude", PurePosixPath("agents"), ".md", PurePosixPath("skills")),
)
MANIFESTS = (PurePosixPath(".claude-plugin/plugin.json"), PurePosixPath(".claude-plugin/marketplace.json"))


class SourceError(Exception):
    """A source file the generator cannot translate; the message names the file."""


def _sources(root: Path) -> list[PurePosixPath]:
    base = root / SOURCE
    found = []
    for kind in ("agents", "skills"):
        for path in sorted((base / kind).rglob("*")):
            if path.is_file():
                found.append(PurePosixPath(path.relative_to(root).as_posix()))
    return found


def _target(source: PurePosixPath, layout: Layout) -> PurePosixPath:
    """The path a source file (or a link target inside the source) has in one layout."""
    kind, *rest = source.relative_to(SOURCE).parts
    if kind == "agents":
        if len(rest) != 1 or not rest[0].endswith(".md"):
            raise SourceError(f"{source}: an agent is one Markdown file directly in {SOURCE}/agents")
        return layout.agents / (rest[0].removesuffix(".md") + layout.agent_suffix)
    return layout.skills.joinpath(*rest)


def _normalize(path: str) -> PurePosixPath:
    parts: list[str] = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            if not parts:
                raise SourceError(f"link leaves the repository: {path}")
            parts.pop()
        elif part != ".":
            parts.append(part)
    return PurePosixPath(*parts)


def _relative(target: PurePosixPath, start: PurePosixPath) -> str:
    return PurePosixPath(os.path.relpath(target, start)).as_posix()


def _rewrite_links(text: str, source: PurePosixPath, generated: PurePosixPath, layout: Layout) -> str:
    def replace(match: re.Match) -> str:
        link = match.group(2)
        if SCHEME.match(link) or link.startswith("/"):
            return match.group(0)
        resolved = _normalize((source.parent / link).as_posix())
        if resolved.parts[:2] in (("src", "agents"), ("src", "skills")):
            resolved = _target(resolved, layout)
        relative = _relative(resolved, generated.parent) + ("/" if link.endswith("/") else "")
        return match.group(1) + relative + match.group(3)

    return LINK.sub(replace, text)


def _front_matter(text: str, source: PurePosixPath, layout: Layout) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SourceError(f"{source}: front matter has no closing ---")
    lines = []
    for line in text[4:end].splitlines():
        key, sep, _ = line.partition(":")
        if not sep and line.strip():
            raise SourceError(f"{source}: front matter line is not `key: value`: {line}")
        prefix, dot, bare = key.partition(".")
        if dot and prefix in {item.name for item in LAYOUTS}:
            if prefix == layout.name:
                lines.append(bare + line[len(key):])
        else:
            lines.append(line)
    return "---\n" + "\n".join(lines) + "\n---\n", text[end + 5:]


def _generated_file(source: PurePosixPath, layout: Layout, root: Path) -> tuple[PurePosixPath, bytes]:
    generated = _target(source, layout)
    data = (root / source).read_bytes()
    if source.suffix != ".md":
        return generated, data
    front, body = _front_matter(data.decode("utf-8"), source, layout)
    notice = (f"<!-- Generated from {source} by scripts/se_plugin.py; edit the source and run "
              f"`python scripts/se_plugin.py build`. -->\n")
    body = _rewrite_links(body, source, generated, layout)
    return generated, (front + notice + body).encode("utf-8")


def _version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _json(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _manifests(root: Path) -> dict[PurePosixPath, bytes]:
    plugin = {
        "name": PLUGIN,
        "version": _version(root),
        "description": DESCRIPTION,
        "author": {"name": OWNER},
        "repository": REPOSITORY,
        "license": "MIT",
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": BOOTSTRAP}]}]},
    }
    marketplace = {
        "name": PLUGIN,
        "owner": {"name": OWNER},
        "description": "SE, installed from this repository.",
        "plugins": [{"name": PLUGIN, "source": "./", "description": DESCRIPTION}],
    }
    return {MANIFESTS[0]: _json(plugin), MANIFESTS[1]: _json(marketplace)}


def expected(root: Path = ROOT) -> dict[PurePosixPath, bytes]:
    """Every generated file and its content, computed from the source alone."""
    files = _manifests(root)
    for source in _sources(root):
        for layout in LAYOUTS:
            path, data = _generated_file(source, layout, root)
            files[path] = data
    return files


def _existing(root: Path) -> set[PurePosixPath]:
    """The generated files on disk: everything in the layouts' folders and the manifests."""
    found = {path for path in MANIFESTS if (root / path).is_file()}
    for layout in LAYOUTS:
        for folder in (layout.agents, layout.skills):
            for path in (root / folder).rglob("*") if (root / folder).is_dir() else ():
                if path.is_file():
                    found.add(PurePosixPath(path.relative_to(root).as_posix()))
    return found


def differences(root: Path = ROOT) -> list[str]:
    """One line per generated file that is missing, stale (hand-edited) or not generated at all."""
    want = expected(root)
    lines = []
    for path in sorted(set(want) | _existing(root)):
        if path not in want:
            lines.append(f"{path}: not generated from {SOURCE}/; remove it or add its source")
        elif not (root / path).is_file():
            lines.append(f"{path}: missing")
        elif (root / path).read_bytes() != want[path]:
            lines.append(f"{path}: differs from its source (edited by hand?)")
    return lines


def build(root: Path = ROOT) -> list[PurePosixPath]:
    """Write every generated file, remove generated files without a source; return what changed."""
    want = expected(root)
    changed = []
    for path in sorted(_existing(root) - set(want)):
        (root / path).unlink()
        changed.append(path)
    for path, data in sorted(want.items()):
        target = root / path
        if not target.is_file() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            changed.append(path)
    for layout in LAYOUTS:
        folder = root / layout.skills
        for directory in sorted(folder.rglob("*"), reverse=True) if folder.is_dir() else ():
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="se_plugin.py", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "check"),
                        help="build: write both layouts from src/; check: refuse when they differ")
    parser.add_argument("--root", type=Path, default=ROOT, help="the se checkout (default: this one)")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            for path in build(args.root):
                print(f"wrote {path}")
            return 0
        lines = differences(args.root)
    except SourceError as error:
        print(f"error: se_plugin.py: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(f"se_plugin.py check: {line}", file=sys.stderr)
    if lines:
        print("se_plugin.py check: generated files differ from src/; edit the source, then run "
              "`python scripts/se_plugin.py build`", file=sys.stderr)
        return 1
    print("se_plugin.py check: both layouts match src/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
