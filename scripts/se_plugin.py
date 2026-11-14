"""Generate the Copilot and Claude Code layouts of the se plugin from its one source in `src/`.

Every agent (`src/agents/<name>.md`) and every skill (`src/skills/<name>/...`) is written once.
`build` writes both layouts, the Claude Code plugin manifests, Copilot's hooks
(`.github/hooks/se.json`, a layout setting: `Layout.hooks`), Copilot's one plugin manifest
(`.github/plugin/plugin.json`) and the MCP door's declarations (`.github/mcp.json`, and a root
`.mcp.json` only where `se.toml` `[plugin] root_mcp` is on); `check` refuses when any generated file
differs from what `build` would write, so a hand edit to a generated file fails. Both refuse a Copilot agent or a skill its host would reject or skip, as the standalone
validators of `scripts/agent_lint.py` find them. Where each layout is installed from is the README
section "Install".

Source front matter is one `key: value` per line. A key prefixed `copilot.` or `claude.` goes only
into that layout, without its prefix; every other key goes into both. In a source's body, the lines
between a line `<!-- copilot -->` and a line `<!-- /copilot -->` go only into the Copilot layout,
without the two marker lines; the Claude layout drops them with the markers, so it is byte for byte
what the source without them builds (`hosts`).

The Copilot layout keeps no relative link that leaves its own folder (`.github/agents`,
`.github/skills`): such a link becomes a link to the file on GitHub at the project's version, the
tag `v<version>` (`_rewrite_links`), so the files work copied or installed elsewhere.

The outside skills each role relies on are one list, `se.toml` `[roles.<role>] skills`, never the
agent's own front matter: `build` writes it into the `skills` field of that agent in every layout
whose host preloads skills (`roles` parses it; AGENTS.md "Agents and skills" owns the rule).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
_lint_spec = importlib.util.spec_from_file_location("agent_lint", Path(__file__).with_name("agent_lint.py"))
agent_lint = sys.modules.get("agent_lint") or importlib.util.module_from_spec(_lint_spec)
if "agent_lint" not in sys.modules:
    sys.modules["agent_lint"] = agent_lint
    _lint_spec.loader.exec_module(agent_lint)
SOURCE = PurePosixPath("src")
PLUGIN = "se"
OWNER = "mb-89"
REPOSITORY = "https://github.com/mb-89/SE"
DESCRIPTION = ("SE, the agent a person talks to, with its integrator, worker and reviewer "
               "sub-agents and their skills.")
# `|| true`: a step that needs the person is advice for the session, never a failed start.
# `--hook`: it ends with SE's greeting (scripts/se_start.py status --hook).
BOOTSTRAP = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh" --hook || true'
# Every other session event goes to kern, the core SE pins (README "Kern"), through SE's hook
# command; it fails open, and `|| true` holds a hook that cannot run to the same. The Stop hooks
# (README "Stop hook") are answered by kern's delivery component, else by stop-check directly.
KERN_EVENTS = ("SessionEnd", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
               "SubagentStop")


def kern_hook(event: str) -> str:
    """The plugin's hook command that posts `event` to kern."""
    return f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/se_hook.sh" {event} || true'


# Copilot's hooks (.github/hooks/se.json, version 1): a project's hooks run in the repository's root.
# Events in PascalCase, so Copilot sends Claude-shaped payloads, `session_id` among them, which kern's
# lease needs; each hook's environment names its host (SE_HOOK_HOST, scripts/hosts.sh), so the start
# answers in Copilot's shape, a top-level `additionalContext`. Each fails open: `|| true` (bash) and
# `exit 0` (PowerShell) keep a refused step from failing the hook, and a hook past its `timeoutSec`
# fails open by itself. Event: (script and argument, seconds).
COPILOT_HOOKS = {
    # The greeting and kern's start, once per session; a first start installing uv and Python may
    # take longer, and the core starts detached.
    "SessionStart": ("scripts/bootstrap.sh --hook", 120),
    # The delivery check (README "Stop hook"): kern's answer within 10 s, else stop-check reading gh.
    # It also fires for the se agent; stop-check lets any checkout without a work issue end.
    "Stop": ("scripts/se_hook.sh Stop", 60),
}


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
    # The build setting for the host's own hooks file (Copilot's .github/hooks/se.json, COPILOT_HOOKS);
    # Claude Code's hooks stay in its plugin manifest whatever this says.
    hooks: bool = False


LAYOUTS = (
    Layout("copilot", PurePosixPath(".github/agents"), ".agent.md", PurePosixPath(".github/skills"), False,
           hooks=True),
    Layout("claude", PurePosixPath("agents"), ".md", PurePosixPath("skills"), True),
)
# One outside skill a role relies on: `<plugin>@<marketplace>:<skill>`, a skill of a plugin and the
# marketplace it installs from. A skill Claude Code ships loads by itself and is not listed.
ROLE_SKILL = re.compile(r"^(?P<plugin>[a-z0-9][a-z0-9-]*)@(?P<marketplace>[A-Za-z0-9][\w.-]*)"
                        r":(?P<skill>[a-z0-9][a-z0-9-]*)$")
# The notice that opens every Markdown file the build generates, naming its source: the one mark of
# a whole generated file, which the landing guard reads to leave the file out of authored prose.
NOTICE = ("<!-- Generated from {source} by scripts/se_plugin.py; edit the source and run "
          "`python scripts/se_plugin.py build`. -->\n")
NOTICE_PATTERN = re.compile(
    "^" + re.escape(NOTICE.rstrip("\n")).replace(re.escape("{source}"), r"\S+") + "$", re.MULTILINE)
COPILOT_HOOKS_FILE = PurePosixPath(".github/hooks/se.json")
# Copilot's one plugin manifest: a plugin installed under Copilot reads this one before the Claude
# layout's .claude-plugin/plugin.json.
COPILOT_MANIFEST = PurePosixPath(".github/plugin/plugin.json")
# The MCP door (README "MCP door"), declared per host: Copilot's project file, and the root file
# Claude Code reads too, written only where se.toml [plugin] root_mcp is on (`root_mcp`).
COPILOT_MCP_FILE = PurePosixPath(".github/mcp.json")
ROOT_MCP_FILE = PurePosixPath(".mcp.json")
MANIFESTS = (PurePosixPath(".claude-plugin/plugin.json"), PurePosixPath(".claude-plugin/marketplace.json"),
             COPILOT_HOOKS_FILE, COPILOT_MANIFEST, COPILOT_MCP_FILE, ROOT_MCP_FILE)
# The door's server: its key, and the launcher a host runs, standalone (scripts/se_mcp.sh). A project
# file names it from the project's root, the folder its host starts it in; a plugin's manifest from
# the plugin's root, whose variable a host sets in arguments only, never in the command.
MCP_SERVER = "se"
LAUNCHER = "scripts/se_mcp.sh"
COPILOT_PLUGIN_ROOT = "${PLUGIN_ROOT}"
# The lines that open and close a part of a source's body only the Copilot layout carries (`hosts`).
COPILOT_OPEN, COPILOT_CLOSE = "<!-- copilot -->", "<!-- /copilot -->"


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


def _rewrite_links(text: str, source: PurePosixPath, generated: PurePosixPath, layout: Layout,
                   version: str = "") -> str:
    """Each relative link as the generated file reaches its target; in the Copilot layout, a
    target outside the generated file's own folder (`_folder`) as its GitHub URL at `v<version>`."""
    folder = _folder(generated, layout)

    def replace(match: re.Match) -> str:
        link = match.group(2)
        if SCHEME.match(link) or link.startswith("/"):
            return match.group(0)
        resolved = _normalize((source.parent / link).as_posix())
        if resolved.parts[:2] in (("src", "agents"), ("src", "skills")):
            resolved = _target(resolved, layout)
        if layout.name == "copilot" and not resolved.is_relative_to(folder):
            kind = "tree" if link.endswith("/") else "blob"
            return f"{match.group(1)}{REPOSITORY}/{kind}/v{version}/{resolved.as_posix()}{match.group(3)}"
        relative = _relative(resolved, generated.parent) + ("/" if link.endswith("/") else "")
        return match.group(1) + relative + match.group(3)

    return LINK.sub(replace, text)


def _folder(generated: PurePosixPath, layout: Layout) -> PurePosixPath:
    """The layout folder a generated file lies in: its agents' or its skills'."""
    return layout.agents if generated.is_relative_to(layout.agents) else layout.skills


def hosts(text: str, source: PurePosixPath | str, layout: Layout, first: int = 1) -> str:
    """The body with its Copilot-only parts (between COPILOT_OPEN and COPILOT_CLOSE lines) kept
    without their markers in the Copilot layout and dropped with them in every other; `first` is
    the source's line number of the body's first line, for the refusals."""
    lines, kept, inside = text.splitlines(keepends=True), [], 0
    for number, line in enumerate(lines, first):
        marker = line.strip()
        if marker == COPILOT_OPEN:
            if inside:
                raise SourceError(f"{source}:{number}: {COPILOT_OPEN} inside another; close it first")
            inside = number
        elif marker == COPILOT_CLOSE:
            if not inside:
                raise SourceError(f"{source}:{number}: {COPILOT_CLOSE} without its {COPILOT_OPEN}")
            inside = 0
        elif not inside or layout.name == "copilot":
            kept.append(line)
    if inside:
        raise SourceError(f"{source}:{inside}: {COPILOT_OPEN} is never closed by {COPILOT_CLOSE}")
    return "".join(kept)


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
                    role_skills: dict[str, list[RoleSkill]], version: str = "") -> tuple[PurePosixPath, bytes]:
    generated = _target(source, layout)
    data = (root / source).read_bytes()
    if source.suffix != ".md":
        return generated, data
    # A checkout with CRLF line endings (git on Windows) builds the same LF layout as any other.
    text = data.decode("utf-8").replace("\r\n", "\n")
    for number, line in enumerate(text.splitlines(), 1):
        if UNROOTED_SCRIPT.search(line):
            raise SourceError(f"{source}:{number}: names a script without SE's root; write "
                              "`<se>/scripts/<name>.py` (the work model's \"What the project provides\")")
    role = source.stem if source.parent == SOURCE / "agents" else None
    front, body = _front_matter(text, source, layout, role_skills.get(role, []) if role else [])
    first = text.count("\n", 0, len(text) - len(body)) + 1
    body = _rewrite_links(hosts(body, source, layout, first), source, generated, layout, version)
    return generated, (front + notice(source) + body).encode("utf-8")


def notice(source: PurePosixPath | str) -> str:
    """The notice line that opens a Markdown file generated from `source`."""
    return NOTICE.format(source=source)


def _version(root: Path) -> str:
    """The plugin's version is the project's one version, `version` of `se.toml` `[project]`."""
    with (root / "se.toml").open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str):
        raise SourceError(f"{root / 'se.toml'}: [project] has no version for the plugin manifest")
    return version


def root_mcp(root: Path) -> bool:
    """`se.toml` `[plugin] root_mcp`: whether the build writes a root `.mcp.json`, which Claude Code
    reads too; off by default."""
    with (root / "se.toml").open("rb") as handle:
        table = tomllib.load(handle).get("plugin", {})
    value = table.get("root_mcp", False) if isinstance(table, dict) else None
    if not isinstance(value, bool) or (isinstance(table, dict) and set(table) - {"root_mcp"}):
        raise SourceError(f"{root / 'se.toml'}: [plugin] holds only `root_mcp = true|false`")
    return value


def mcp_server(launcher: str) -> dict:
    """The door's stdio server, its launcher run with bash for the project it starts in."""
    return {"type": "stdio", "command": "bash", "args": [launcher, "--root", "."]}


def _json(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _copilot_hook(command: str, seconds: int) -> dict:
    return {"type": "command", "bash": f"bash {command} || true", "powershell": f"bash {command}; exit 0",
            "cwd": ".", "env": {"SE_HOOK_HOST": "copilot"}, "timeoutSec": seconds}


def _manifests(root: Path, copilot: bool = True) -> dict[PurePosixPath, bytes]:
    plugin = {
        "name": PLUGIN,
        "version": _version(root),
        "description": DESCRIPTION,
        "author": {"name": OWNER},
        "repository": REPOSITORY,
        "license": "MIT",
    }
    plugin["hooks"] = {
        "SessionStart": [{"hooks": [{"type": "command", "command": BOOTSTRAP}]}],
        **{event: [{"hooks": [{"type": "command", "command": kern_hook(event)}]}]
           for event in KERN_EVENTS},
    }
    marketplace = {
        "name": PLUGIN,
        "owner": {"name": OWNER},
        "description": "SE, installed from this repository.",
        "plugins": [{"name": PLUGIN, "source": "./", "description": DESCRIPTION}],
    }
    files = {MANIFESTS[0]: _json(plugin), MANIFESTS[1]: _json(marketplace)}
    if root_mcp(root):
        files[ROOT_MCP_FILE] = _json({"mcpServers": {MCP_SERVER: mcp_server(LAUNCHER)}})
    if not copilot:
        return files
    layout = LAYOUTS[0]
    if layout.hooks:
        files[COPILOT_HOOKS_FILE] = _json({
            "version": 1,
            "hooks": {event: [_copilot_hook(command, seconds)]
                      for event, (command, seconds) in COPILOT_HOOKS.items()},
        })
    files[COPILOT_MCP_FILE] = _json({"mcpServers": {MCP_SERVER: {**mcp_server(LAUNCHER), "tools": ["*"]}}})
    files[COPILOT_MANIFEST] = _json({
        "name": PLUGIN,
        "version": plugin["version"],
        "description": DESCRIPTION,
        "author": {"name": OWNER},
        "repository": REPOSITORY,
        "license": "MIT",
        "agents": f"{layout.agents}/",
        "skills": f"{layout.skills}/",
        **({"hooks": str(COPILOT_HOOKS_FILE)} if layout.hooks else {}),
        "mcpServers": {MCP_SERVER: mcp_server(f"{COPILOT_PLUGIN_ROOT}/{LAUNCHER}")},
    })
    return files


def validate(files: dict[PurePosixPath, bytes]) -> list[str]:
    """One finding per generated agent or skill its host would reject or skip: every Copilot agent
    and every skill of both layouts, through the standalone validators (scripts/agent_lint.py)."""
    findings = []
    for path, data in sorted(files.items()):
        text = data.decode("utf-8", errors="replace")
        if path.parent == LAYOUTS[0].agents and path.name.endswith(LAYOUTS[0].agent_suffix):
            findings += agent_lint.copilot_agent(path, text)
        elif path.name == "SKILL.md" and any(path.parent.parent == layout.skills for layout in LAYOUTS):
            findings += agent_lint.skill(path, text)
    return findings


def expected(root: Path = ROOT, copilot: bool = True) -> dict[PurePosixPath, bytes]:
    """Every generated file and its content, computed from the source alone; without `copilot`,
    the Claude layout alone, which is the same either way."""
    files = _manifests(root, copilot)
    version = _version(root)
    sources = _sources(root)
    role_skills = roles(root)
    agents = {source.stem for source in sources if source.parent == SOURCE / "agents"}
    if unknown := sorted(set(role_skills) - agents):
        raise SourceError(f"{root / 'se.toml'}: [roles.{unknown[0]}] names no agent in {SOURCE}/agents")
    for source in sources:
        for layout in LAYOUTS if copilot else LAYOUTS[1:]:
            path, data = _generated_file(source, layout, root, role_skills, version)
            files[path] = data
    if problems := validate(files):
        raise SourceError("; ".join(problems))
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
