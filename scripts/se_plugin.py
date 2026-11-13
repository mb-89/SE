"""Generate the Copilot and Claude Code layouts of the se plugin from its one source in `src/`.

Every agent (`src/agents/<name>.md`) and every skill (`src/skills/<name>/...`) is written once.
`build` writes both layouts and the Claude Code plugin manifests; `check` refuses when any generated
file differs from what `build` would write, so a hand edit to a generated file fails. Where each
layout is installed from is the README section "Install".

Source front matter is one `key: value` per line. A key prefixed `copilot.` or `claude.` goes only
into that layout, without its prefix; every other key goes into both.

The outside skills each role relies on are one list, `se.toml` `[roles.<role>] skills`, never the
agent's own front matter: `build` writes it into the `skills` field of that agent in every layout
whose host preloads skills (`roles` parses it; AGENTS.md "Agents and skills" owns the rule).
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
DESCRIPTION = ("SE, the agent a person talks to, with its integrator, worker and reviewer "
               "sub-agents and their skills.")
# `|| true`: a step that needs the person is advice for the session, never a failed start.
# `--hook`: it ends with SE's greeting (scripts/se_start.py status --hook).
BOOTSTRAP = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh" --hook || true'
# The Stop hook (README "Stop hook"): a worker's turn ends only with its work issue delivered. uv
# where bootstrap.sh installs it; `--no-project` so no project's environment is synced; `|| true`:
# a hook that cannot run lets the turn end (advice fails open).
STOP_CHECK = ('PATH="$HOME/.local/bin:$PATH" uv run --no-project --python ">=3.11" python '
              '"${CLAUDE_PLUGIN_ROOT}/scripts/work_tickets.py" stop-check || true')
LINK = re.compile(r"(\]\()([^)\s#]+)((?:#[^)\s]*)?\))")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# A script path not under `<se>`, the root the start hook names (scripts/se_start.py `root_line`):
# bare `scripts/...`, relative to the working directory, or under another placeholder. Relative links
# (`../../scripts/...`) and other folders' `scripts/` stay allowed.
UNROOTED_SCRIPT = re.compile(r"(?<![\w./>}-])scripts/|<(?!se>)[^<>\n]*>/scripts/|\$\{?\w+\}?/scripts/")


@dataclass(frozen=True)
class Layout:
    """Where one host reads agents and skills, relative to the repository root."""

    name: str
    agents: PurePosixPath
    agent_suffix: str
    skills: PurePosixPath
    preloads_skills: bool  # the host reads an agent's `skills` field (Copilot's agents have none)


LAYOUTS = (
    Layout("copilot", PurePosixPath(".github/agents"), ".agent.md", PurePosixPath(".github/skills"), False),
    Layout("claude", PurePosixPath("agents"), ".md", PurePosixPath("skills"), True),
)
# One outside skill a role relies on: `<plugin>@<marketplace>:<skill>`, a skill of a plugin and the
# marketplace it installs from. A skill Claude Code ships loads by itself and is not listed.
ROLE_SKILL = re.compile(r"^(?P<plugin>[a-z0-9][a-z0-9-]*)@(?P<marketplace>[A-Za-z0-9][\w.-]*)"
                        r":(?P<skill>[a-z0-9][a-z0-9-]*)$")
MANIFESTS = (PurePosixPath(".claude-plugin/plugin.json"), PurePosixPath(".claude-plugin/marketplace.json"))


class SourceError(Exception):
    """A source file the generator cannot translate; the message names the file."""


@dataclass(frozen=True)
class RoleSkill:
    """One entry of a role's `skills` list."""

    plugin: str
    marketplace: str
    skill: str

    @property
    def name(self) -> str:
        """How an agent's `skills` field names it."""
        return f"{self.plugin}:{self.skill}"

    @property
    def install(self) -> str:
        return f"claude plugin install {self.plugin}@{self.marketplace}"


def roles(root: Path = ROOT) -> dict[str, list[RoleSkill]]:
    """`se.toml` `[roles.<role>] skills`: the outside skills each role (agent) relies on."""
    path = root / "se.toml"
    try:
        with path.open("rb") as handle:
            table = tomllib.load(handle).get("roles", {})
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SourceError(f"{path}: cannot read [roles]: {error}") from error
    if not isinstance(table, dict):
        raise SourceError(f"{path}: [roles] is not a table")
    found = {}
    for role, entry in table.items():
        if not isinstance(entry, dict) or set(entry) - {"skills"}:
            raise SourceError(f"{path}: [roles.{role}] holds only `skills = [...]`")
        skills = entry.get("skills", [])
        if not isinstance(skills, list):
            raise SourceError(f"{path}: [roles.{role}] skills is not a list")
        found[role] = []
        for text in skills:
            match = ROLE_SKILL.match(text) if isinstance(text, str) else None
            if not match:
                raise SourceError(f"{path}: [roles.{role}] skills entry {text!r} is not "
                                  "`<plugin>@<marketplace>:<skill>`")
            found[role].append(RoleSkill(**match.groupdict()))
    return found


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


def _front_matter(text: str, source: PurePosixPath, layout: Layout,
                 skills: list[RoleSkill] = ()) -> tuple[str, str]:
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
        if source.parent == SOURCE / "agents" and (bare if dot else key).strip() == "skills":
            raise SourceError(f"{source}: an agent's skills come from se.toml [roles.<role>] skills, "
                              "not its front matter")
        if dot and prefix in {item.name for item in LAYOUTS}:
            if prefix == layout.name:
                lines.append(bare + line[len(key):])
        else:
            lines.append(line)
    if skills and layout.preloads_skills:
        lines.append("skills: " + ", ".join(item.name for item in skills))
    return "---\n" + "\n".join(lines) + "\n---\n", text[end + 5:]


def _generated_file(source: PurePosixPath, layout: Layout, root: Path,
                    role_skills: dict[str, list[RoleSkill]]) -> tuple[PurePosixPath, bytes]:
    generated = _target(source, layout)
    data = (root / source).read_bytes()
    if source.suffix != ".md":
        return generated, data
    text = data.decode("utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if UNROOTED_SCRIPT.search(line):
            raise SourceError(f"{source}:{number}: names a script without SE's root; write "
                              "`<se>/scripts/<name>.py` (the work model's \"What the project provides\")")
    role = source.stem if source.parent == SOURCE / "agents" else None
    front, body = _front_matter(text, source, layout, role_skills.get(role, []) if role else [])
    notice = (f"<!-- Generated from {source} by scripts/se_plugin.py; edit the source and run "
              f"`python scripts/se_plugin.py build`. -->\n")
    body = _rewrite_links(body, source, generated, layout)
    return generated, (front + notice + body).encode("utf-8")


def _version(root: Path) -> str:
    """The plugin's version is the project's one version, `version` of `se.toml` `[project]`."""
    with (root / "se.toml").open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str):
        raise SourceError(f"{root / 'se.toml'}: [project] has no version for the plugin manifest")
    return version


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
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": BOOTSTRAP}]}],
            "Stop": [{"hooks": [{"type": "command", "command": STOP_CHECK}]}],
            "SubagentStop": [{"hooks": [{"type": "command", "command": STOP_CHECK}]}],
        },
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
    sources = _sources(root)
    role_skills = roles(root)
    agents = {source.stem for source in sources if source.parent == SOURCE / "agents"}
    if unknown := sorted(set(role_skills) - agents):
        raise SourceError(f"{root / 'se.toml'}: [roles.{unknown[0]}] names no agent in {SOURCE}/agents")
    for source in sources:
        for layout in LAYOUTS:
            path, data = _generated_file(source, layout, root, role_skills)
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
